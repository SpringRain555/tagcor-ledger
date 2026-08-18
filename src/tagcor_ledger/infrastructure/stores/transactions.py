"""交易的建立、轉帳、替換轉帳、編輯、作廢與 keyset 分頁查詢。

轉帳一律是「兩筆 posting、一筆 transaction」；轉帳不支援原地編輯，只能用
`replace_transfer` 建新的、作廢舊的。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from tagcor_ledger.domain.models import TransactionFilter, TransactionRecord
from tagcor_ledger.domain.money import Money
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import (
    NotFoundError,
    StoreBase,
    build_fts_query,
)


class TransactionStore(StoreBase):
    def create_transaction(
        self,
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
    ) -> TransactionRecord:
        timestamp = now_iso()
        posting_amount = money.amount_minor if entry_type == "income" else -money.amount_minor
        with database_transaction(self.paths.database_path) as connection:
            self._require_active_account(connection, account_id, money.currency)
            self._require_active_category(connection, category_id)
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
        description: str,
        correlation_id: str,
    ) -> TransactionRecord:
        if source_account_id == destination_account_id:
            raise ValueError("TRANSFER_SAME_ACCOUNT")
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            self._require_active_account(connection, source_account_id, money.currency)
            self._require_active_account(connection, destination_account_id, money.currency)
            connection.execute(
                """
                INSERT INTO transactions(
                    transaction_id, revision, status, entry_type, occurred_at,
                    recorded_at, updated_at, description, source, correlation_id
                ) VALUES (?, 1, 'active', 'transfer', ?, ?, ?, ?, 'manual', ?)
                """,
                (
                    transaction_id,
                    occurred_at,
                    timestamp,
                    timestamp,
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

    def replace_transfer(
        self,
        *,
        original_transaction_id: str,
        new_transaction_id: str,
        occurred_at: str,
        money: Money,
        source_account_id: str,
        destination_account_id: str,
        description: str,
        correlation_id: str,
    ) -> TransactionRecord:
        if source_account_id == destination_account_id:
            raise ValueError("TRANSFER_SAME_ACCOUNT")
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            original = connection.execute(
                """
                SELECT entry_type, status FROM transactions WHERE transaction_id = ?
                """,
                (original_transaction_id,),
            ).fetchone()
            if original is None or original["entry_type"] != "transfer":
                raise NotFoundError("TRANSFER_NOT_FOUND")
            if original["status"] != "active":
                raise ValueError("TRANSFER_NOT_ACTIVE")
            self._require_active_account(connection, source_account_id, money.currency)
            self._require_active_account(connection, destination_account_id, money.currency)
            connection.execute(
                """
                INSERT INTO transactions(
                    transaction_id, revision, status, entry_type, occurred_at,
                    recorded_at, updated_at, description, source, correlation_id,
                    replaces_transaction_id
                ) VALUES (?, 1, 'active', 'transfer', ?, ?, ?, ?, 'manual', ?, ?)
                """,
                (
                    new_transaction_id,
                    occurred_at,
                    timestamp,
                    timestamp,
                    description.strip(),
                    correlation_id,
                    original_transaction_id,
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
                        new_transaction_id,
                        source_account_id,
                        -money.amount_minor,
                        money.currency,
                        1,
                    ),
                    (
                        f"post_{uuid4().hex}",
                        new_transaction_id,
                        destination_account_id,
                        money.amount_minor,
                        money.currency,
                        2,
                    ),
                ],
            )
            connection.execute(
                """
                UPDATE transactions
                SET status = 'voided', revision = revision + 1, updated_at = ?
                WHERE transaction_id = ?
                """,
                (timestamp, original_transaction_id),
            )
            self._refresh_fts(connection, new_transaction_id)
            self._audit(
                connection,
                correlation_id=correlation_id,
                action="transaction.transfer_replace",
                entity_type="transaction",
                entity_id=new_transaction_id,
                details={"replaces_transaction_id": original_transaction_id},
            )
        return self.get_transaction(new_transaction_id)

    def update_transaction(
        self,
        *,
        transaction_id: str,
        expected_revision: int,
        occurred_at: str,
        money: Money,
        account_id: str,
        category_id: str,
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
            changed = connection.execute(
                """
                UPDATE transactions
                SET revision = revision + 1, occurred_at = ?, updated_at = ?,
                    description = ?
                WHERE transaction_id = ? AND revision = ?
                """,
                (
                    occurred_at,
                    timestamp,
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
        cursor_direction: str = "next",
        transaction_filter: TransactionFilter | None = None,
    ) -> tuple[list[TransactionRecord], tuple[str, str] | None]:
        if not 1 <= limit <= 200:
            raise ValueError("PAGE_LIMIT_INVALID")
        filters = transaction_filter or TransactionFilter()
        conditions: list[str] = []
        parameters: list[Any] = []
        joins = ""
        if filters.status == "active":
            conditions.append("t.status = 'active'")
        elif filters.status == "voided":
            conditions.append("t.status = 'voided'")
        elif filters.status != "all":
            raise ValueError("TRANSACTION_STATUS_FILTER_INVALID")
        if cursor is not None:
            operator = "<" if cursor_direction == "next" else ">"
            conditions.append(
                f"(t.occurred_at {operator} ? OR "
                f"(t.occurred_at = ? AND t.transaction_id {operator} ?))"
            )
            parameters.extend([cursor[0], cursor[0], cursor[1]])
        if filters.date_from:
            conditions.append("t.occurred_at >= ?")
            parameters.append(filters.date_from)
        if filters.date_to:
            conditions.append("t.occurred_at <= ?")
            parameters.append(filters.date_to)
        if filters.account_id:
            conditions.append("EXISTS (SELECT 1 FROM account_postings fp WHERE fp.transaction_id = t.transaction_id AND fp.account_id = ?)")
            parameters.append(filters.account_id)
        if filters.category_id:
            conditions.append(
                "EXISTS (SELECT 1 FROM category_allocations fc "
                "JOIN categories fcat ON fcat.category_id = fc.category_id "
                "WHERE fc.transaction_id = t.transaction_id "
                "AND (fc.category_id = ? OR fcat.parent_id = ?))"
            )
            parameters.extend([filters.category_id, filters.category_id])
        if filters.search.strip():
            joins = "JOIN transaction_fts fts ON fts.transaction_id = t.transaction_id"
            conditions.append("transaction_fts MATCH ?")
            parameters.append(build_fts_query(filters.search))
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order = "ASC" if cursor_direction == "previous" else "DESC"
        sql = (
            self._transaction_select(joins=joins)
            + f" {where} ORDER BY t.occurred_at {order}, t.transaction_id {order} LIMIT ?"
        )
        parameters.append(limit + 1)
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        if cursor_direction == "previous":
            page_rows = list(reversed(page_rows))
        records = [self._row_to_transaction(row) for row in page_rows]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = (str(last["occurred_at"]), str(last["transaction_id"]))
        return records, next_cursor
