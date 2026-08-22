"""帳戶的建立、封存、恢復、重新命名、刪除與餘額計算。"""

from __future__ import annotations

from dataclasses import asdict
import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.models import Account
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import (
    NotFoundError,
    StoreBase,
    has_any_reference,
)


class AccountStore(StoreBase):
    def list_accounts(self, *, include_archived: bool = False) -> list[Account]:
        where = "" if include_archived else "WHERE status = 'active'"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT account_id, name, account_type, currency, opening_balance_minor,
                       status, sort_order
                FROM accounts
                {where}
                ORDER BY sort_order, name COLLATE NOCASE
                """
            ).fetchall()
        return [Account(**dict(row)) for row in rows]

    def set_account_order(self, ordered_ids: list[str]) -> None:
        """帳戶的自訂順序。帳戶只有一組，所以不必指名是哪一組。

        這份順序同時決定記帳頁的帳戶下拉與資產總覽的列法 —— `list_accounts()`
        本來就 `ORDER BY sort_order`，只是在這之前沒有人寫過那一欄。
        """
        with database_transaction(self.paths.database_path) as connection:
            current = [
                str(row["account_id"])
                for row in connection.execute("SELECT account_id FROM accounts").fetchall()
            ]
            self._apply_sort_order(
                connection,
                table="accounts",
                id_column="account_id",
                current_ids=current,
                ordered_ids=ordered_ids,
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="account.reorder",
                entity_type="account",
                entity_id="all",
                details={"count": len(ordered_ids)},
            )

    def create_account(
        self,
        *,
        name: str,
        account_type: str = "cash",
        currency: str = "TWD",
        opening_balance_minor: int = 0,
    ) -> Account:
        timestamp = now_iso()
        account = Account(
            account_id=f"acct_{uuid4().hex}",
            name=name.strip(),
            account_type=account_type,
            currency=currency,
            opening_balance_minor=opening_balance_minor,
            status="active",
            sort_order=100,
        )
        if not account.name:
            raise ValueError("ACCOUNT_NAME_REQUIRED")
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO accounts(
                    account_id, name, account_type, currency, opening_balance_minor,
                    status, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account.account_id,
                    account.name,
                    account.account_type,
                    account.currency,
                    account.opening_balance_minor,
                    account.status,
                    account.sort_order,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="account.create",
                entity_type="account",
                entity_id=account.account_id,
                details=asdict(account),
            )
        return account

    def archive_account(self, account_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE accounts SET status = 'archived', updated_at = ?
                WHERE account_id = ? AND status = 'active'
                """,
                (now_iso(), account_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("ACCOUNT_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="account.archive",
                entity_type="account",
                entity_id=account_id,
                details={},
            )

    def restore_account(self, account_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT name FROM accounts WHERE account_id = ? AND status = 'archived'",
                (account_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("ACCOUNT_NOT_FOUND")
            duplicate = connection.execute(
                """
                SELECT 1 FROM accounts
                WHERE name = ? COLLATE NOCASE AND status = 'active' AND account_id != ?
                """,
                (row["name"], account_id),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("ACCOUNT_ACTIVE_NAME_CONFLICT")
            connection.execute(
                "UPDATE accounts SET status = 'active', updated_at = ? WHERE account_id = ?",
                (now_iso(), account_id),
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="account.restore",
                entity_type="account",
                entity_id=account_id,
                details={},
            )

    def rename_account(self, account_id: str, name: str) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("ACCOUNT_NAME_REQUIRED")
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE accounts SET name = ?, updated_at = ?
                WHERE account_id = ? AND status = 'active'
                """,
                (clean_name, now_iso(), account_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("ACCOUNT_NOT_FOUND")
            self._refresh_fts_for_account(connection, account_id)
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="account.rename",
                entity_type="account",
                entity_id=account_id,
                details={"name": clean_name},
            )

    def delete_account(self, account_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("ACCOUNT_NOT_FOUND")
            default_row = connection.execute(
                "SELECT value FROM settings WHERE key = 'default_account_id'"
            ).fetchone()
            if default_row is not None and str(default_row["value"]) == account_id:
                raise ValueError("ACCOUNT_IS_DEFAULT")
            if has_any_reference(
                connection,
                [
                    ("account_postings", "account_id = ?", (account_id,)),
                    ("balance_snapshots", "account_id = ?", (account_id,)),
                    (
                        "transaction_templates",
                        "account_id = ? OR destination_account_id = ?",
                        (account_id, account_id),
                    ),
                    (
                        "recurring_schedules",
                        "account_id = ? OR destination_account_id = ?",
                        (account_id, account_id),
                    ),
                    (
                        "scheduled_occurrences",
                        "account_id = ? OR destination_account_id = ?",
                        (account_id, account_id),
                    ),
                ],
            ):
                raise ValueError("ACCOUNT_IN_USE")
            connection.execute("DELETE FROM accounts WHERE account_id = ?", (account_id,))
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="account.delete",
                entity_type="account",
                entity_id=account_id,
                details={},
            )

    def account_balances(self) -> dict[str, int]:
        """一句話算完**所有**帳戶的餘額。

        `account_balance_minor` 一次只算一個，而 `connect_database` 每次呼叫都開一條
        新連線並跑四個 PRAGMA —— 列一次帳戶就是 1+N 條連線。帳戶數不大，但這條路徑
        在記帳頁、交易紀錄篩選、餘額盤點與資產總覽上各走一次，切頁就付一次成本。

        SQL 與單一帳戶那句一模一樣，只是拿掉 `WHERE`。**兩句必須同時改** ——
        `test_account_balances_match_the_single_account_query` 守住這件事。

        **不用表格別名。** `EXPLAIN QUERY PLAN` 報的是查詢裡寫的名字，所以
        `FROM accounts a` 的計畫會寫成 `SCAN a` —— `tests/integration/test_query_plans.py`
        的守門是照表名判斷哪些表會長大的，別名讓它什麼都認不出來。寫全名囉唆，
        但那份計畫是給人讀的。
        """
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                """
                SELECT accounts.account_id,
                       accounts.opening_balance_minor
                       + COALESCE(
                           SUM(
                               CASE WHEN transactions.status = 'active'
                                    THEN account_postings.amount_minor ELSE 0 END
                           ), 0
                         ) AS balance
                FROM accounts
                LEFT JOIN account_postings
                       ON account_postings.account_id = accounts.account_id
                LEFT JOIN transactions
                       ON transactions.transaction_id = account_postings.transaction_id
                GROUP BY accounts.account_id
                """
            ).fetchall()
        return {str(row["account_id"]): int(row["balance"]) for row in rows}

    def account_balance_minor(self, account_id: str) -> int:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                """
                SELECT a.opening_balance_minor
                       + COALESCE(SUM(CASE WHEN t.status = 'active' THEN p.amount_minor ELSE 0 END), 0)
                         AS balance
                FROM accounts a
                LEFT JOIN account_postings p ON p.account_id = a.account_id
                LEFT JOIN transactions t ON t.transaction_id = p.transaction_id
                WHERE a.account_id = ?
                GROUP BY a.account_id
                """,
                (account_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("ACCOUNT_NOT_FOUND")
        return int(row["balance"])

    @classmethod
    def _refresh_fts_for_account(
        cls,
        connection: sqlite3.Connection,
        account_id: str,
    ) -> None:
        rows = connection.execute(
            "SELECT DISTINCT transaction_id FROM account_postings WHERE account_id = ?",
            (account_id,),
        ).fetchall()
        for row in rows:
            cls._refresh_fts(connection, str(row["transaction_id"]))
