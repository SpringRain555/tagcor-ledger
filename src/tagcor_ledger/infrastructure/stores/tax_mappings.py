"""稅務所得與支出稅目的類別對應，以及帳本事實查詢。"""

from __future__ import annotations

from datetime import date, timedelta
import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.tax.estimate import LedgerIncome
from tagcor_ledger.domain.tax.kinds import Flow, IncomeKind, TaxKind
from tagcor_ledger.domain.tax.records import (
    KindTotal,
    PaymentFact,
    TaxMapping,
    TaxMappingRow,
)
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import NotFoundError, StoreBase


class TaxMappingStore(StoreBase):
    def list_tax_mappings(self) -> list[TaxMapping]:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                """
                SELECT category_id, flow, tax_kind
                FROM tax_category_mappings
                ORDER BY category_id, flow
                """
            ).fetchall()
        return [
            TaxMapping(
                category_id=str(row["category_id"]),
                flow=Flow(str(row["flow"])),
                tax_kind=str(row["tax_kind"]),
            )
            for row in rows
        ]

    def set_tax_mapping(
        self,
        *,
        category_id: str,
        flow: Flow,
        tax_kind: str | None,
    ) -> None:
        try:
            selected_flow = Flow(flow)
        except (TypeError, ValueError) as exc:
            raise ValueError("TAX_MAPPING_KIND_INVALID") from exc
        allowed = IncomeKind if selected_flow is Flow.INCOME else TaxKind
        if tax_kind is not None and tax_kind not in {kind.value for kind in allowed}:
            raise ValueError("TAX_MAPPING_KIND_INVALID")

        with database_transaction(self.paths.database_path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM categories WHERE category_id = ?", (category_id,)
            ).fetchone()
            if exists is None:
                raise NotFoundError("CATEGORY_NOT_FOUND")
            if tax_kind is None:
                connection.execute(
                    "DELETE FROM tax_category_mappings WHERE category_id = ? AND flow = ?",
                    (category_id, selected_flow.value),
                )
                action = "tax_mapping.clear"
            else:
                connection.execute(
                    """
                    INSERT INTO tax_category_mappings(category_id, flow, tax_kind, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(category_id, flow) DO UPDATE SET
                        tax_kind = excluded.tax_kind,
                        updated_at = excluded.updated_at
                    """,
                    (category_id, selected_flow.value, tax_kind, now_iso()),
                )
                action = "tax_mapping.set"
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action=action,
                entity_type="category",
                entity_id=category_id,
                details={"flow": selected_flow.value, "tax_kind": tax_kind},
            )

    def list_tax_mapping_rows(self, income_year: int) -> list[TaxMappingRow]:
        start = f"{income_year:04d}-01-01"
        end = f"{income_year + 1:04d}-01-01"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                """
                SELECT category_node.category_id, category_node.parent_id,
                       COALESCE(category_parent.name, category_node.name) AS category_name,
                       CASE WHEN category_node.level = 2
                            THEN category_node.name END AS item_name,
                       category_node.status,
                       income_mapping.tax_kind AS income_kind,
                       expense_mapping.tax_kind AS expense_kind,
                       parent_income_mapping.tax_kind AS parent_income_kind,
                       parent_expense_mapping.tax_kind AS parent_expense_kind,
                       COALESCE(income_mapping.tax_kind, parent_income_mapping.tax_kind)
                           AS effective_income_kind,
                       COALESCE(expense_mapping.tax_kind, parent_expense_mapping.tax_kind)
                           AS effective_expense_kind,
                       COUNT(DISTINCT category_year_transaction.transaction_id)
                           AS own_year_count,
                       COALESCE(SUM(CASE WHEN category_year_transaction.transaction_id IS NOT NULL
                                         THEN category_year_allocation.amount_minor ELSE 0 END), 0)
                           AS own_year_minor,
                       CASE WHEN category_node.level = 1 THEN
                           COUNT(DISTINCT category_year_transaction.transaction_id) + (
                               SELECT COUNT(DISTINCT child_transaction.transaction_id)
                               FROM categories category_item
                               JOIN category_allocations child_allocation
                                 ON child_allocation.category_id = category_item.category_id
                               JOIN transactions child_transaction
                                 ON child_transaction.transaction_id = child_allocation.transaction_id
                               WHERE category_item.parent_id = category_node.category_id
                                 AND child_transaction.status = 'active'
                                 AND child_transaction.entry_type = 'income'
                                 AND child_transaction.occurred_at >= ?
                                 AND child_transaction.occurred_at < ?
                           )
                           ELSE COUNT(DISTINCT category_year_transaction.transaction_id)
                       END AS year_count,
                       COALESCE(SUM(CASE WHEN category_year_transaction.transaction_id IS NOT NULL
                                         THEN category_year_allocation.amount_minor ELSE 0 END), 0) +
                       CASE WHEN category_node.level = 1 THEN COALESCE((
                           SELECT SUM(child_allocation.amount_minor)
                           FROM categories category_item
                           JOIN category_allocations child_allocation
                             ON child_allocation.category_id = category_item.category_id
                           JOIN transactions child_transaction
                             ON child_transaction.transaction_id = child_allocation.transaction_id
                           WHERE category_item.parent_id = category_node.category_id
                             AND child_transaction.status = 'active'
                             AND child_transaction.entry_type = 'income'
                             AND child_transaction.occurred_at >= ?
                             AND child_transaction.occurred_at < ?
                       ), 0) ELSE 0 END AS year_minor
                FROM categories category_node
                LEFT JOIN categories category_parent
                  ON category_parent.category_id = category_node.parent_id
                LEFT JOIN category_allocations category_year_allocation
                  ON category_year_allocation.category_id = category_node.category_id
                LEFT JOIN transactions category_year_transaction
                  ON category_year_transaction.transaction_id =
                     category_year_allocation.transaction_id
                 AND category_year_transaction.status = 'active'
                 AND category_year_transaction.entry_type = 'income'
                 AND category_year_transaction.occurred_at >= ?
                 AND category_year_transaction.occurred_at < ?
                LEFT JOIN tax_category_mappings income_mapping
                  ON income_mapping.category_id = category_node.category_id
                 AND income_mapping.flow = 'income'
                LEFT JOIN tax_category_mappings expense_mapping
                  ON expense_mapping.category_id = category_node.category_id
                 AND expense_mapping.flow = 'expense'
                LEFT JOIN tax_category_mappings parent_income_mapping
                  ON parent_income_mapping.category_id = category_parent.category_id
                 AND parent_income_mapping.flow = 'income'
                LEFT JOIN tax_category_mappings parent_expense_mapping
                  ON parent_expense_mapping.category_id = category_parent.category_id
                 AND parent_expense_mapping.flow = 'expense'
                GROUP BY category_node.category_id
                HAVING category_node.status = 'active' OR year_count > 0
                ORDER BY CASE WHEN own_year_count > 0 AND effective_income_kind IS NULL
                              THEN 0 ELSE 1 END,
                         COALESCE(category_parent.sort_order, category_node.sort_order),
                         COALESCE(category_parent.name, category_node.name) COLLATE NOCASE,
                         category_node.level, category_node.sort_order,
                         category_node.name COLLATE NOCASE, category_node.category_id
                """,
                (start, end, start, end, start, end),
            ).fetchall()
        return [_row_to_tax_mapping_row(row) for row in rows]

    def income_totals(self, income_year: int) -> LedgerIncome:
        start = f"{income_year:04d}-01-01"
        end = f"{income_year + 1:04d}-01-01"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                """
                SELECT COALESCE(income_mapping.tax_kind, parent_income_mapping.tax_kind)
                           AS income_kind,
                       COUNT(DISTINCT transactions.transaction_id) AS transaction_count,
                       SUM(category_allocations.amount_minor) AS net_minor,
                       SUM((
                           SELECT COALESCE(SUM(COALESCE(deposit_events.withheld_tax_minor, 0)), 0)
                           FROM deposit_events
                           WHERE deposit_events.transaction_id = transactions.transaction_id
                             AND deposit_events.status = 'confirmed'
                       )) AS withheld_tax_minor,
                       SUM((
                           SELECT COALESCE(SUM(COALESCE(deposit_events.nhi_premium_minor, 0)), 0)
                           FROM deposit_events
                           WHERE deposit_events.transaction_id = transactions.transaction_id
                             AND deposit_events.status = 'confirmed'
                       )) AS nhi_premium_minor
                FROM transactions
                JOIN category_allocations
                  ON category_allocations.transaction_id = transactions.transaction_id
                JOIN categories category_node
                  ON category_node.category_id = category_allocations.category_id
                LEFT JOIN categories category_parent
                  ON category_parent.category_id = category_node.parent_id
                LEFT JOIN tax_category_mappings income_mapping
                  ON income_mapping.category_id = category_node.category_id
                 AND income_mapping.flow = 'income'
                LEFT JOIN tax_category_mappings parent_income_mapping
                  ON parent_income_mapping.category_id = category_parent.category_id
                 AND parent_income_mapping.flow = 'income'
                WHERE transactions.status = 'active'
                  AND transactions.entry_type = 'income'
                  AND transactions.occurred_at >= ?
                  AND transactions.occurred_at < ?
                GROUP BY income_kind
                """,
                (start, end),
            ).fetchall()

        by_kind: dict[IncomeKind, KindTotal] = {}
        unmapped = KindTotal(0, 0, 0, 0)
        for row in rows:
            total = KindTotal(
                count=int(row["transaction_count"]),
                net_minor=int(row["net_minor"] or 0),
                withheld_tax_minor=int(row["withheld_tax_minor"] or 0),
                nhi_premium_minor=int(row["nhi_premium_minor"] or 0),
            )
            if row["income_kind"] is None:
                unmapped = total
            else:
                by_kind[IncomeKind(str(row["income_kind"]))] = total
        return LedgerIncome(by_kind=by_kind, unmapped=unmapped)

    def payment_fact(self, kind: TaxKind, *, start: date, end: date) -> PaymentFact:
        after_end = end + timedelta(days=1)
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(DISTINCT transactions.transaction_id) AS transaction_count,
                       COALESCE(SUM(category_allocations.amount_minor), 0) AS total_minor,
                       MAX(substr(transactions.occurred_at, 1, 10)) AS last_on
                FROM transactions
                JOIN category_allocations
                  ON category_allocations.transaction_id = transactions.transaction_id
                JOIN categories category_node
                  ON category_node.category_id = category_allocations.category_id
                LEFT JOIN categories category_parent
                  ON category_parent.category_id = category_node.parent_id
                LEFT JOIN tax_category_mappings expense_mapping
                  ON expense_mapping.category_id = category_node.category_id
                 AND expense_mapping.flow = 'expense'
                LEFT JOIN tax_category_mappings parent_expense_mapping
                  ON parent_expense_mapping.category_id = category_parent.category_id
                 AND parent_expense_mapping.flow = 'expense'
                WHERE transactions.status = 'active'
                  AND transactions.entry_type = 'expense'
                  AND transactions.occurred_at >= ?
                  AND transactions.occurred_at < ?
                  AND COALESCE(expense_mapping.tax_kind, parent_expense_mapping.tax_kind) = ?
                """,
                (
                    f"{start.isoformat()}T00:00:00",
                    f"{after_end.isoformat()}T00:00:00",
                    kind.value,
                ),
            ).fetchone()
        return PaymentFact(
            count=int(row["transaction_count"]),
            total_minor=int(row["total_minor"]),
            last_on=str(row["last_on"]) if row["last_on"] is not None else None,
        )


def _row_to_tax_mapping_row(row: sqlite3.Row) -> TaxMappingRow:
    income_kind = row["income_kind"]
    expense_kind = row["expense_kind"]
    parent_income_kind = row["parent_income_kind"]
    parent_expense_kind = row["parent_expense_kind"]
    effective_income_kind = row["effective_income_kind"]
    effective_expense_kind = row["effective_expense_kind"]
    item_name = row["item_name"]
    return TaxMappingRow(
        category_id=str(row["category_id"]),
        parent_id=str(row["parent_id"]) if row["parent_id"] is not None else None,
        category_name=str(row["category_name"]),
        item_name=str(item_name) if item_name is not None else None,
        archived=str(row["status"]) == "archived",
        income_kind=IncomeKind(str(income_kind)) if income_kind is not None else None,
        expense_kind=TaxKind(str(expense_kind)) if expense_kind is not None else None,
        parent_income_kind=(
            IncomeKind(str(parent_income_kind)) if parent_income_kind is not None else None
        ),
        parent_expense_kind=(
            TaxKind(str(parent_expense_kind)) if parent_expense_kind is not None else None
        ),
        effective_income_kind=(
            IncomeKind(str(effective_income_kind))
            if effective_income_kind is not None
            else None
        ),
        effective_expense_kind=(
            TaxKind(str(effective_expense_kind))
            if effective_expense_kind is not None
            else None
        ),
        own_year_count=int(row["own_year_count"]),
        own_year_minor=int(row["own_year_minor"]),
        year_count=int(row["year_count"]),
        year_minor=int(row["year_minor"]),
    )
