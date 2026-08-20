"""所有 store 共用的例外、連線持有者與跨聚合的查詢片段。

放進來的判準是「不只一個聚合會用到」。只有單一聚合用得到的 helper 留在該聚合自己
的模組裡，不要為了整齊往這裡搬 —— 那會讓這個檔案變成第二個大雜燴。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.domain.models import TransactionRecord
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.clock import now_iso


class StoreError(RuntimeError):
    """Raised for persistence failures with stable application semantics."""


class NotFoundError(StoreError):
    """Raised when a requested entity does not exist."""


class StoreBase:
    """持有 `AppPaths` 並提供跨聚合共用的 SQL 片段與稽核寫入。

    **這裡不呼叫 `initialize_database`。** migration 由 `LedgerStore.__init__` 統一跑
    一次；若每個 store 各自跑，一個 `LedgerStore` 就會重複跑四次。
    """

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    @staticmethod
    def _transaction_select(*, joins: str = "") -> str:
        return f"""
        SELECT t.transaction_id, t.revision, t.status, t.entry_type,
               t.occurred_at, t.recorded_at, t.updated_at,
               ABS(p1.amount_minor) AS amount_minor, p1.currency,
               p1.account_id, a1.name AS account_name,
               p2.account_id AS destination_account_id,
               a2.name AS destination_account_name,
               c.category_id, c.name AS category_name,
               pc.category_id AS parent_category_id,
               pc.name AS parent_category_name,
               t.description, t.correlation_id, t.replaces_transaction_id
        FROM transactions t
        JOIN account_postings p1 ON p1.transaction_id = t.transaction_id AND p1.sequence = 1
        JOIN accounts a1 ON a1.account_id = p1.account_id
        LEFT JOIN account_postings p2 ON p2.transaction_id = t.transaction_id AND p2.sequence = 2
        LEFT JOIN accounts a2 ON a2.account_id = p2.account_id
        LEFT JOIN category_allocations ca ON ca.transaction_id = t.transaction_id AND ca.sequence = 1
        LEFT JOIN categories c ON c.category_id = ca.category_id
        LEFT JOIN categories pc ON pc.category_id = c.parent_id
        {joins}
        """

    @staticmethod
    def _row_to_transaction(row: sqlite3.Row) -> TransactionRecord:
        child_id = str(row["category_id"]) if row["category_id"] is not None else None
        child_name = str(row["category_name"]) if row["category_name"] is not None else None
        parent_id = (
            str(row["parent_category_id"]) if row["parent_category_id"] is not None else None
        )
        parent_name = (
            str(row["parent_category_name"]) if row["parent_category_name"] is not None else None
        )
        if parent_id is None:
            parent_id, parent_name = child_id, child_name
            child_id, child_name = None, None
        return TransactionRecord(
            transaction_id=str(row["transaction_id"]),
            revision=int(row["revision"]),
            status=str(row["status"]),
            entry_type=str(row["entry_type"]),
            occurred_at=str(row["occurred_at"]),
            recorded_at=str(row["recorded_at"]),
            updated_at=str(row["updated_at"]),
            money=Money(int(row["amount_minor"]), str(row["currency"])),
            account_id=str(row["account_id"]),
            account_name=str(row["account_name"]),
            destination_account_id=(
                str(row["destination_account_id"])
                if row["destination_account_id"] is not None
                else None
            ),
            destination_account_name=(
                str(row["destination_account_name"])
                if row["destination_account_name"] is not None
                else None
            ),
            category_id=parent_id,
            category_name=parent_name,
            subcategory_id=child_id,
            subcategory_name=child_name,
            description=str(row["description"]),
            correlation_id=str(row["correlation_id"]),
            replaces_transaction_id=(
                str(row["replaces_transaction_id"])
                if row["replaces_transaction_id"] is not None
                else None
            ),
        )

    @staticmethod
    def _require_active_account(
        connection: sqlite3.Connection, account_id: str, currency: str
    ) -> None:
        row = connection.execute(
            "SELECT currency, status FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None or row["status"] != "active":
            raise ValueError("ACCOUNT_NOT_ACTIVE")
        if row["currency"] != currency:
            raise ValueError("CURRENCY_MISMATCH")

    @staticmethod
    def _require_active_category(connection: sqlite3.Connection, category_id: str) -> None:
        row = connection.execute(
            "SELECT status FROM categories WHERE category_id = ?", (category_id,)
        ).fetchone()
        if row is None or row["status"] != "active":
            raise ValueError("CATEGORY_NOT_ACTIVE")

    @classmethod
    def _write_transaction(
        cls,
        connection: sqlite3.Connection,
        *,
        transaction_id: str,
        entry_type: str,
        occurred_at: str,
        money: Money,
        account_id: str,
        category_id: str,
        description: str,
        source: str,
        correlation_id: str,
    ) -> None:
        """在**呼叫者的 transaction 內**寫出一筆收入或支出。

        「一筆交易長什麼樣」只能有一個地方說了算：transactions 一列、posting 一列
        （支出為負）、allocation 一列，然後重建 FTS 索引與稽核。

        **為什麼收 `connection` 而不是自己開一個？** 因為有兩種呼叫情境：
        `create_transaction()` 是「就寫這一筆」，而定期收支的確認是「建交易 ＋ 把那一期
        標成已確認」，兩件事必須在同一個 SQLite transaction 內完成 —— 不然會出現
        「狀態變成 confirmed 但交易沒建出來」。自己開連線就做不到後者，而那正是
        `automation_store` 當初自己另寫一份的原因。收 `connection` 兩種情境都成立。
        """
        timestamp = now_iso()
        posting_amount = money.amount_minor if entry_type == "income" else -money.amount_minor
        cls._require_active_account(connection, account_id, money.currency)
        cls._require_active_category(connection, category_id)
        connection.execute(
            """
            INSERT INTO transactions(
                transaction_id, revision, status, entry_type, occurred_at,
                recorded_at, updated_at, description, source, correlation_id
            ) VALUES (?, 1, 'active', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                entry_type,
                occurred_at,
                timestamp,
                timestamp,
                description.strip(),
                source,
                correlation_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO account_postings(
                posting_id, transaction_id, account_id, amount_minor, currency, sequence
            ) VALUES (?, ?, ?, ?, ?, 1)
            """,
            (f"post_{uuid4().hex}", transaction_id, account_id, posting_amount, money.currency),
        )
        connection.execute(
            """
            INSERT INTO category_allocations(
                allocation_id, transaction_id, category_id, amount_minor, sequence
            ) VALUES (?, ?, ?, ?, 1)
            """,
            (f"alloc_{uuid4().hex}", transaction_id, category_id, money.amount_minor),
        )
        cls._refresh_fts(connection, transaction_id)
        cls._audit(
            connection,
            correlation_id=correlation_id,
            action="transaction.create",
            entity_type="transaction",
            entity_id=transaction_id,
            details={"entry_type": entry_type, "amount_minor": money.amount_minor},
        )

    @classmethod
    def _write_transfer(
        cls,
        connection: sqlite3.Connection,
        *,
        transaction_id: str,
        occurred_at: str,
        money: Money,
        source_account_id: str,
        destination_account_id: str,
        description: str,
        source: str,
        correlation_id: str,
        replaces_transaction_id: str | None = None,
    ) -> None:
        """在**呼叫者的 transaction 內**寫出一筆轉帳：一筆交易、兩筆 posting。

        來源為負（`sequence = 1`）、目的為正（`sequence = 2`）。順序是有意義的 ——
        `_transaction_select()` 靠 `sequence` 分辨哪一邊是來源。

        `replaces_transaction_id` 給替換轉帳用（轉帳不能原地編輯，只能建新的、作廢舊的）。
        作廢舊的那一步留在呼叫端 —— 這裡只負責「新的那一筆長什麼樣」。
        """
        if source_account_id == destination_account_id:
            raise ValueError("TRANSFER_SAME_ACCOUNT")
        timestamp = now_iso()
        cls._require_active_account(connection, source_account_id, money.currency)
        cls._require_active_account(connection, destination_account_id, money.currency)
        connection.execute(
            """
            INSERT INTO transactions(
                transaction_id, revision, status, entry_type, occurred_at,
                recorded_at, updated_at, description, source, correlation_id,
                replaces_transaction_id
            ) VALUES (?, 1, 'active', 'transfer', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                occurred_at,
                timestamp,
                timestamp,
                description.strip(),
                source,
                correlation_id,
                replaces_transaction_id,
            ),
        )
        connection.executemany(
            """
            INSERT INTO account_postings(
                posting_id, transaction_id, account_id, amount_minor, currency, sequence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"post_{uuid4().hex}",
                    transaction_id,
                    source_account_id,
                    -money.amount_minor,
                    money.currency,
                    1,
                ),
                (
                    f"post_{uuid4().hex}",
                    transaction_id,
                    destination_account_id,
                    money.amount_minor,
                    money.currency,
                    2,
                ),
            ],
        )
        cls._refresh_fts(connection, transaction_id)
        details: dict[str, Any] = {
            "source_account_id": source_account_id,
            "destination_account_id": destination_account_id,
            "amount_minor": money.amount_minor,
        }
        if replaces_transaction_id is not None:
            details["replaces_transaction_id"] = replaces_transaction_id
        cls._audit(
            connection,
            correlation_id=correlation_id,
            action=(
                "transaction.transfer"
                if replaces_transaction_id is None
                else "transaction.transfer_replace"
            ),
            entity_type="transaction",
            entity_id=transaction_id,
            details=details,
        )

    @staticmethod
    def _refresh_fts(connection: sqlite3.Connection, transaction_id: str) -> None:
        rows = connection.execute(
            """
            SELECT t.description,
                   COALESCE(GROUP_CONCAT(DISTINCT c.name), '') || ' ' ||
                   COALESCE(GROUP_CONCAT(DISTINCT pc.name), '') AS category_names,
                   COALESCE(GROUP_CONCAT(DISTINCT a.name), '') AS account_names
            FROM transactions t
            LEFT JOIN category_allocations ca ON ca.transaction_id = t.transaction_id
            LEFT JOIN categories c ON c.category_id = ca.category_id
            LEFT JOIN categories pc ON pc.category_id = c.parent_id
            LEFT JOIN account_postings p ON p.transaction_id = t.transaction_id
            LEFT JOIN accounts a ON a.account_id = p.account_id
            WHERE t.transaction_id = ?
            GROUP BY t.transaction_id
            """,
            (transaction_id,),
        ).fetchone()
        if rows is None:
            return
        connection.execute("DELETE FROM transaction_fts WHERE transaction_id = ?", (transaction_id,))
        connection.execute(
            """
            INSERT INTO transaction_fts(transaction_id, description, category, account)
            VALUES (?, ?, ?, ?)
            """,
            (
                transaction_id,
                rows["description"],
                rows["category_names"],
                rows["account_names"],
            ),
        )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        *,
        correlation_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events(
                audit_id, occurred_at, correlation_id, action,
                entity_type, entity_id, result, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, 'success', ?)
            """,
            (
                f"aud_{uuid4().hex}",
                now_iso(),
                correlation_id,
                action,
                entity_type,
                entity_id,
                json.dumps(details, ensure_ascii=False, sort_keys=True),
            ),
        )


def has_any_reference(
    connection: sqlite3.Connection,
    checks: list[tuple[str, str, tuple[object, ...]]],
) -> bool:
    """設定項是否被任何歷史資料引用；有引用就只能封存、不能刪除。"""
    for table, where, parameters in checks:
        row = connection.execute(
            f"SELECT 1 FROM {table} WHERE {where} LIMIT 1",
            parameters,
        ).fetchone()
        if row is not None:
            return True
    return False


def build_fts_query(value: str) -> str:
    terms = [term.replace('"', '""') for term in value.split() if term.strip()]
    return " AND ".join(f'"{term}"*' for term in terms)
