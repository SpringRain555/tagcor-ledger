"""交易模板的持久化。

模板是「常用的一筆帳長什麼樣」，套用時才變成真的交易。它有自訂順序
（`sort_order`），排序視窗排的就是它。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from uuid import uuid4

from tagcor_ledger.domain.models import SortLevel, TransactionTemplate
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import StoreBase, new_correlation_id, order_by
from tagcor_ledger.infrastructure.stores.drafts import validate_draft


TEMPLATE_SORT_FIELDS: dict[str, str] = {
    "custom": "sort_order",
    "name": "name COLLATE NOCASE",
    "entry_type": "entry_type",
    # 「套用時輸入」的模板 `amount_minor` 是 NULL。SQLite 的 NULL 排在最前面，
    # 依金額排時它們會擠在開頭 —— 那是對的：它們**沒有**金額，不是金額為 0。
    "amount": "amount_minor",
}
"""模板的 `ORDER BY` 白名單。組裝規則見 `base.order_by()`。"""

TEMPLATE_DEFAULT_ORDER: tuple[str, ...] = ("sort_order",)
TEMPLATE_TIEBREAKERS: tuple[str, ...] = ("name COLLATE NOCASE", "template_id")


class TemplateStore(StoreBase):
    def list_templates(
        self,
        *,
        include_archived: bool = False,
        sort: Sequence[SortLevel] = (),
    ) -> list[TransactionTemplate]:
        where = "" if include_archived else "WHERE status = 'active'"
        order = order_by(
            sort,
            fields=TEMPLATE_SORT_FIELDS,
            default=TEMPLATE_DEFAULT_ORDER,
            tiebreakers=TEMPLATE_TIEBREAKERS,
        )
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT template_id, name, status, entry_type, account_id,
                       destination_account_id, category_id, amount_minor, currency,
                       description, sort_order
                FROM transaction_templates {where}
                ORDER BY {order}
                """
            ).fetchall()
        return [TransactionTemplate(**dict(row)) for row in rows]

    def set_template_order(self, ordered_ids: list[str]) -> None:
        """模板的自訂順序。模板只有一組。

        **不走 `save_template()`。** 那條路會跑整套草稿驗證（帳戶、類別、金額），
        而調順序不該因為某個模板的帳戶被封存了就失敗 —— 那兩件事無關。
        """
        with database_transaction(self.paths.database_path) as connection:
            current = [
                str(row["template_id"])
                for row in connection.execute(
                    "SELECT template_id FROM transaction_templates"
                ).fetchall()
            ]
            self._apply_sort_order(
                connection,
                table="transaction_templates",
                id_column="template_id",
                current_ids=current,
                ordered_ids=ordered_ids,
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="template.reorder",
                entity_type="template",
                entity_id="all",
                details={"count": len(ordered_ids)},
            )

    def save_template(self, template: TransactionTemplate) -> TransactionTemplate:
        validate_draft(template)
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO transaction_templates(
                    template_id, name, status, entry_type, account_id,
                    destination_account_id, category_id, amount_minor, currency,
                    description, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    name = excluded.name, status = excluded.status,
                    entry_type = excluded.entry_type, account_id = excluded.account_id,
                    destination_account_id = excluded.destination_account_id,
                    category_id = excluded.category_id, amount_minor = excluded.amount_minor,
                    currency = excluded.currency, description = excluded.description,
                    sort_order = excluded.sort_order,
                    updated_at = excluded.updated_at
                """,
                (
                    template.template_id,
                    template.name.strip(),
                    template.status,
                    template.entry_type,
                    template.account_id,
                    template.destination_account_id,
                    template.category_id,
                    template.amount_minor,
                    template.currency,
                    template.description.strip(),
                    template.sort_order,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="template.save",
                entity_type="template",
                entity_id=template.template_id,
                details=asdict(template),
            )
        return template

    def archive_template(self, template_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE transaction_templates SET status = 'archived', updated_at = ?
                WHERE template_id = ? AND status = 'active'
                """,
                (now_iso(), template_id),
            ).rowcount
            if changed == 0:
                raise ValueError("TEMPLATE_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="template.archive",
                entity_type="template",
                entity_id=template_id,
                details={},
            )
