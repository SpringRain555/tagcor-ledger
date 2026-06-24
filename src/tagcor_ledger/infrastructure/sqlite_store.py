"""SQLite-backed repositories for ledger application services."""

from __future__ import annotations

from dataclasses import asdict
import json
import sqlite3
from typing import Any
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.domain.models import Account, Category, TransactionRecord
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.database import (
    connect_database,
    database_transaction,
    initialize_database,
    now_iso,
)


class StoreError(RuntimeError):
    """Raised for persistence failures with stable application semantics."""


class NotFoundError(StoreError):
    """Raised when a requested entity does not exist."""


class LedgerStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        initialize_database(paths)

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

    def list_categories(
        self,
        *,
        parent_id: str | None = None,
        include_archived: bool = False,
    ) -> list[Category]:
        status_clause = "" if include_archived else "AND status = 'active'"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT category_id, name, parent_id, level, status, sort_order
                FROM categories
                WHERE parent_id IS ? {status_clause}
                ORDER BY sort_order, name COLLATE NOCASE
                """,
                (parent_id,),
            ).fetchall()
        return [Category(**dict(row)) for row in rows]

    def create_category(self, *, name: str, parent_id: str | None = None) -> Category:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("CATEGORY_NAME_REQUIRED")
        level = 1
        if parent_id is not None:
            with connect_database(self.paths.database_path) as connection:
                parent = connection.execute(
                    "SELECT level, status FROM categories WHERE category_id = ?", (parent_id,)
                ).fetchone()
            if parent is None or parent["status"] != "active" or int(parent["level"]) != 1:
                raise ValueError("CATEGORY_PARENT_INVALID")
            level = 2
        timestamp = now_iso()
        category = Category(
            category_id=f"cat_{uuid4().hex}",
            name=clean_name,
            parent_id=parent_id,
            level=level,
            status="active",
            sort_order=100,
        )
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO categories(
                    category_id, parent_id, level, name, status, sort_order,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category.category_id,
                    category.parent_id,
                    category.level,
                    category.name,
                    category.status,
                    category.sort_order,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.create",
                entity_type="category",
                entity_id=category.category_id,
                details=asdict(category),
            )
        return category

    def archive_category(self, category_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            children = connection.execute(
                """
                SELECT COUNT(*) AS count FROM categories
                WHERE parent_id = ? AND status = 'active'
                """,
                (category_id,),
            ).fetchone()
            if children is not None and int(children["count"]) > 0:
                raise ValueError("CATEGORY_HAS_ACTIVE_CHILDREN")
            changed = connection.execute(
                """
                UPDATE categories SET status = 'archived', updated_at = ?
                WHERE category_id = ? AND status = 'active'
                """,
                (now_iso(), category_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("CATEGORY_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.archive",
                entity_type="category",
                entity_id=category_id,
                details={},
            )

    def rename_category(self, category_id: str, name: str) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("CATEGORY_NAME_REQUIRED")
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE categories SET name = ?, updated_at = ?
                WHERE category_id = ? AND status = 'active'
                """,
                (clean_name, now_iso(), category_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("CATEGORY_NOT_FOUND")
            self._refresh_fts_for_category(connection, category_id)
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="category.rename",
                entity_type="category",
                entity_id=category_id,
                details={"name": clean_name},
            )

    def create_transaction(
        self,
        *,
        transaction_id: str,
        entry_type: str,
        occurred_at: str,
        money: Money,
        account_id: str,
        category_id: str,
        payee_name: str,
        description: str,
        source: str,
        correlation_id: str,
    ) -> TransactionRecord:
        timestamp = now_iso()
        posting_amount = money.amount_minor if entry_type == "income" else -money.amount_minor
        with database_transaction(self.paths.database_path) as connection:
            self._require_active_account(connection, account_id, money.currency)
            self._require_active_category(connection, category_id)
            payee_id = self._upsert_payee(connection, payee_name, timestamp)
            connection.execute(
                """
                INSERT INTO transactions(
                    transaction_id, revision, status, entry_type, occurred_at,
                    recorded_at, updated_at, payee_id, payee_name_snapshot,
                    description, source, correlation_id
                ) VALUES (?, 1, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    entry_type,
                    occurred_at,
                    timestamp,
                    timestamp,
                    payee_id,
                    payee_name.strip(),
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
            self._refresh_fts(connection, transaction_id)
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="transaction.create",
                entity_type="transaction",
                entity_id=transaction_id,
                details={"entry_type": entry_type, "amount_minor": money.amount_minor},
            )
        return self.get_transaction(transaction_id)

    def create_transfer(
        self,
        *,
        transaction_id: str,
        occurred_at: str,
        money: Money,
        source_account_id: str,
        destination_account_id: str,
        payee_name: str,
        description: str,
        correlation_id: str,
    ) -> TransactionRecord:
        if source_account_id == destination_account_id:
            raise ValueError("TRANSFER_SAME_ACCOUNT")
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            self._require_active_account(connection, source_account_id, money.currency)
            self._require_active_account(connection, destination_account_id, money.currency)
            payee_id = self._upsert_payee(connection, payee_name, timestamp)
            connection.execute(
                """
                INSERT INTO transactions(
                    transaction_id, revision, status, entry_type, occurred_at,
                    recorded_at, updated_at, payee_id, payee_name_snapshot,
                    description, source, correlation_id
                ) VALUES (?, 1, 'active', 'transfer', ?, ?, ?, ?, ?, ?, 'manual', ?)
                """,
                (
                    transaction_id,
                    occurred_at,
                    timestamp,
                    timestamp,
                    payee_id,
                    payee_name.strip(),
                    description.strip(),
                    correlation_id,
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
            self._refresh_fts(connection, transaction_id)
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="transaction.transfer",
                entity_type="transaction",
                entity_id=transaction_id,
                details={
                    "source_account_id": source_account_id,
                    "destination_account_id": destination_account_id,
                    "amount_minor": money.amount_minor,
                },
            )
        return self.get_transaction(transaction_id)

    def update_transaction(
        self,
        *,
        transaction_id: str,
        expected_revision: int,
        occurred_at: str,
        money: Money,
        account_id: str,
        category_id: str,
        payee_name: str,
        description: str,
        correlation_id: str,
    ) -> TransactionRecord:
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            current = connection.execute(
                "SELECT entry_type, revision, status FROM transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
            if current is None:
                raise NotFoundError("TRANSACTION_NOT_FOUND")
            if current["status"] != "active":
                raise ValueError("TRANSACTION_VOIDED")
            if current["entry_type"] == "transfer":
                raise ValueError("TRANSFER_EDIT_NOT_SUPPORTED")
            if int(current["revision"]) != expected_revision:
                raise ValueError("TRANSACTION_REVISION_CONFLICT")
            self._require_active_account(connection, account_id, money.currency)
            self._require_active_category(connection, category_id)
            payee_id = self._upsert_payee(connection, payee_name, timestamp)
            changed = connection.execute(
                """
                UPDATE transactions
                SET revision = revision + 1, occurred_at = ?, updated_at = ?,
                    payee_id = ?, payee_name_snapshot = ?, description = ?
                WHERE transaction_id = ? AND revision = ?
                """,
                (
                    occurred_at,
                    timestamp,
                    payee_id,
                    payee_name.strip(),
                    description.strip(),
                    transaction_id,
                    expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("TRANSACTION_REVISION_CONFLICT")
            signed = money.amount_minor if current["entry_type"] == "income" else -money.amount_minor
            connection.execute(
                """
                UPDATE account_postings
                SET account_id = ?, amount_minor = ?, currency = ?
                WHERE transaction_id = ? AND sequence = 1
                """,
                (account_id, signed, money.currency, transaction_id),
            )
            connection.execute(
                """
                UPDATE category_allocations
                SET category_id = ?, amount_minor = ?
                WHERE transaction_id = ? AND sequence = 1
                """,
                (category_id, money.amount_minor, transaction_id),
            )
            self._refresh_fts(connection, transaction_id)
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="transaction.update",
                entity_type="transaction",
                entity_id=transaction_id,
                details={"revision": expected_revision + 1},
            )
        return self.get_transaction(transaction_id)

    def void_transaction(self, transaction_id: str, correlation_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE transactions
                SET status = 'voided', revision = revision + 1, updated_at = ?
                WHERE transaction_id = ? AND status = 'active'
                """,
                (now_iso(), transaction_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("TRANSACTION_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="transaction.void",
                entity_type="transaction",
                entity_id=transaction_id,
                details={},
            )

    def get_transaction(self, transaction_id: str) -> TransactionRecord:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                self._transaction_select() + " WHERE t.transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("TRANSACTION_NOT_FOUND")
        return self._row_to_transaction(row)

    def list_transactions(
        self,
        *,
        limit: int = 50,
        cursor: tuple[str, str] | None = None,
        search: str = "",
        account_id: str | None = None,
        category_id: str | None = None,
        include_voided: bool = False,
    ) -> tuple[list[TransactionRecord], tuple[str, str] | None]:
        if not 1 <= limit <= 200:
            raise ValueError("PAGE_LIMIT_INVALID")
        conditions: list[str] = []
        parameters: list[Any] = []
        joins = ""
        if not include_voided:
            conditions.append("t.status = 'active'")
        if cursor is not None:
            conditions.append("(t.occurred_at < ? OR (t.occurred_at = ? AND t.transaction_id < ?))")
            parameters.extend([cursor[0], cursor[0], cursor[1]])
        if account_id:
            conditions.append("EXISTS (SELECT 1 FROM account_postings fp WHERE fp.transaction_id = t.transaction_id AND fp.account_id = ?)")
            parameters.append(account_id)
        if category_id:
            conditions.append(
                "EXISTS (SELECT 1 FROM category_allocations fc "
                "JOIN categories fcat ON fcat.category_id = fc.category_id "
                "WHERE fc.transaction_id = t.transaction_id "
                "AND (fc.category_id = ? OR fcat.parent_id = ?))"
            )
            parameters.extend([category_id, category_id])
        if search.strip():
            joins = "JOIN transaction_fts fts ON fts.transaction_id = t.transaction_id"
            conditions.append("transaction_fts MATCH ?")
            parameters.append(_fts_query(search))
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = (
            self._transaction_select(joins=joins)
            + f" {where} ORDER BY t.occurred_at DESC, t.transaction_id DESC LIMIT ?"
        )
        parameters.append(limit + 1)
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        records = [self._row_to_transaction(row) for row in page_rows]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = (str(last["occurred_at"]), str(last["transaction_id"]))
        return records, next_cursor

    def integrity_check(self) -> str:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row is not None else "unknown"

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
               t.payee_name_snapshot, t.description, t.correlation_id
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
            payee_name=str(row["payee_name_snapshot"]),
            description=str(row["description"]),
            correlation_id=str(row["correlation_id"]),
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

    @staticmethod
    def _upsert_payee(
        connection: sqlite3.Connection, payee_name: str, timestamp: str
    ) -> str | None:
        clean_name = payee_name.strip()
        if not clean_name:
            return None
        row = connection.execute(
            "SELECT payee_id FROM payees WHERE name = ? COLLATE NOCASE", (clean_name,)
        ).fetchone()
        if row is not None:
            return str(row["payee_id"])
        payee_id = f"payee_{uuid4().hex}"
        connection.execute(
            """
            INSERT INTO payees(payee_id, name, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            (payee_id, clean_name, timestamp, timestamp),
        )
        return payee_id

    @staticmethod
    def _refresh_fts(connection: sqlite3.Connection, transaction_id: str) -> None:
        rows = connection.execute(
            """
            SELECT t.payee_name_snapshot, t.description,
                   COALESCE(GROUP_CONCAT(DISTINCT c.name), '') AS category_names,
                   COALESCE(GROUP_CONCAT(DISTINCT a.name), '') AS account_names
            FROM transactions t
            LEFT JOIN category_allocations ca ON ca.transaction_id = t.transaction_id
            LEFT JOIN categories c ON c.category_id = ca.category_id
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
            INSERT INTO transaction_fts(transaction_id, payee, description, category, account)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                rows["payee_name_snapshot"],
                rows["description"],
                rows["category_names"],
                rows["account_names"],
            ),
        )

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

    @classmethod
    def _refresh_fts_for_category(
        cls,
        connection: sqlite3.Connection,
        category_id: str,
    ) -> None:
        rows = connection.execute(
            """
            SELECT DISTINCT ca.transaction_id
            FROM category_allocations ca
            JOIN categories c ON c.category_id = ca.category_id
            WHERE ca.category_id = ? OR c.parent_id = ?
            """,
            (category_id, category_id),
        ).fetchall()
        for row in rows:
            cls._refresh_fts(connection, str(row["transaction_id"]))

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


def _fts_query(value: str) -> str:
    terms = [term.replace('"', '""') for term in value.split() if term.strip()]
    return " AND ".join(f'"{term}"*' for term in terms)
