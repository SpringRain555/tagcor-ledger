"""交易模板的持久化。

模板是「常用的一筆帳長什麼樣」，套用時才變成真的交易。它有自訂順序
（`sort_order`），排序視窗排的就是它。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from uuid import uuid4

import sqlite3

from tagcor_ledger.domain.models import SortLevel, TemplateRow, TransactionTemplate
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import (
    NotFoundError,
    StoreBase,
    new_correlation_id,
    order_by,
)


def validate_template(draft: TransactionTemplate) -> None:
    """存進資料庫之前的四道檢查。四種失敗各有自己的錯誤碼。

    **這一段以前在 `stores/drafts.py`**，因為模板與定期收支共用同一套規則。
    v0.23.0 移除定期收支之後只剩一個呼叫端，那個檔案存在的理由就沒了
    （[ADR-0011](../../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)）。
    錯誤碼也從 `AUTOMATION_*` 改成 `TEMPLATE_*` —— 這個專案裡已經沒有「自動化」了。
    """
    # **主鍵要先擋。** `save_template()` 是 `ON CONFLICT(template_id) DO UPDATE` 的
    # UPSERT，而空字串是一個合法的主鍵值 —— 傳 `template_id=""` 進來不會失敗，
    # 會安靜地寫出一列主鍵是空字串的模板，第二次再傳空字串就 UPDATE 到同一列上。
    # id 由 `new_template()` 產，所以正常路徑走不到這裡，但「走不到」不是「擋住了」：
    # 2026-08 寫測試 helper 時就撞過一次，三個模板全部塌成同一列。
    if not draft.template_id.strip():
        raise ValueError("TEMPLATE_ID_REQUIRED")
    if not draft.name.strip():
        raise ValueError("TEMPLATE_NAME_REQUIRED")
    if draft.entry_type == "transfer":
        if draft.destination_account_id is None or draft.category_id is not None:
            raise ValueError("TRANSFER_DRAFT_INVALID")
    elif draft.category_id is None or draft.destination_account_id is not None:
        raise ValueError("TRANSACTION_DRAFT_INVALID")
    if draft.amount_minor is not None and draft.amount_minor <= 0:
        raise ValueError("TEMPLATE_AMOUNT_INVALID")


TEMPLATE_SORT_FIELDS: dict[str, str] = {
    "custom": "t.sort_order",
    "name": "t.name COLLATE NOCASE",
    "entry_type": "t.entry_type",
    # 「套用時輸入」的模板 `amount_minor` 是 NULL。SQLite 的 NULL 排在最前面，
    # 依金額排時它們會擠在開頭 —— 那是對的：它們**沒有**金額，不是金額為 0。
    "amount": "t.amount_minor",
}
"""模板的 `ORDER BY` 白名單。組裝規則見 `base.order_by()`。

**每一個都要帶 `t.` 前綴。** `list_templates()` 會 join 帳戶與類別，而那兩張表也有
`name` 欄位 —— 不指名就是 `ambiguous column name: name`，而那是執行期才炸的。"""

TEMPLATE_DEFAULT_ORDER: tuple[str, ...] = ("t.sort_order",)
TEMPLATE_TIEBREAKERS: tuple[str, ...] = ("t.name COLLATE NOCASE", "t.template_id")


TEMPLATE_COLUMNS: tuple[str, ...] = (
    "template_id",
    "name",
    "status",
    "entry_type",
    "account_id",
    "destination_account_id",
    "category_id",
    "amount_minor",
    "currency",
    "description",
    "sort_order",
)
"""`TransactionTemplate` 的欄位。查詢多 join 了四個名字，不能再 `**dict(row)`。"""


def _row_to_template(row: sqlite3.Row) -> TemplateRow:
    return TemplateRow(
        template=TransactionTemplate(
            **{column: row[column] for column in TEMPLATE_COLUMNS}
        ),
        account_name=str(row["account_name"] or ""),
        destination_account_name=row["destination_account_name"],
        category_name=row["category_name"],
        subcategory_name=row["subcategory_name"],
    )


class TemplateStore(StoreBase):
    def list_templates(
        self,
        *,
        include_archived: bool = False,
        sort: Sequence[SortLevel] = (),
    ) -> list[TemplateRow]:
        """模板清單，**帳戶與類別的名字一起 join 回來**。

        模板頁要讓使用者在填進記帳頁之前就看得出「這一個是從哪個帳戶付、記到哪個
        項目」—— 只列名稱與金額的話，兩個都叫「午餐」的模板分不出誰是誰。
        分開查就是 1+N（每一列各查一次帳戶、各查一次類別），所以**一句查詢**。

        `category_name` / `subcategory_name` 的拆法與 `TransactionRecord` 一致：
        模板的 `category_id` 存的是**項目**（第二層），所以第一層要從它的
        `parent_id` 再 join 一次。指到第一層類別的模板（沒有 `parent_id`）
        則是 `category_name` 有值、`subcategory_name` 空的。
        """
        where = "" if include_archived else "WHERE t.status = 'active'"
        order = order_by(
            sort,
            fields=TEMPLATE_SORT_FIELDS,
            default=TEMPLATE_DEFAULT_ORDER,
            tiebreakers=TEMPLATE_TIEBREAKERS,
        )
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT t.template_id, t.name, t.status, t.entry_type, t.account_id,
                       t.destination_account_id, t.category_id, t.amount_minor,
                       t.currency, t.description, t.sort_order,
                       a.name AS account_name,
                       da.name AS destination_account_name,
                       COALESCE(pc.name, c.name) AS category_name,
                       CASE WHEN pc.category_id IS NOT NULL THEN c.name END
                           AS subcategory_name
                FROM transaction_templates t
                LEFT JOIN accounts a ON a.account_id = t.account_id
                LEFT JOIN accounts da ON da.account_id = t.destination_account_id
                LEFT JOIN categories c ON c.category_id = t.category_id
                LEFT JOIN categories pc ON pc.category_id = c.parent_id
                {where}
                ORDER BY {order}
                """
            ).fetchall()
        return [_row_to_template(row) for row in rows]

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
        validate_template(template)
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

    def restore_template(self, template_id: str) -> None:
        """把封存的模板放回清單。

        **同名檢查不能省。** schema 有
        `CREATE UNIQUE INDEX idx_templates_active_name ... WHERE status = 'active'`，
        少了這一步就會讓 `sqlite3.IntegrityError` 的英文原文一路浮到畫面上 ——
        而使用者做的事只是「把封存的東西拿回來」。做法與 `restore_account()` 相同。
        """
        with database_transaction(self.paths.database_path) as connection:
            row = connection.execute(
                """
                SELECT name FROM transaction_templates
                WHERE template_id = ? AND status = 'archived'
                """,
                (template_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("TEMPLATE_NOT_FOUND")
            duplicate = connection.execute(
                """
                SELECT 1 FROM transaction_templates
                WHERE name = ? COLLATE NOCASE AND status = 'active' AND template_id != ?
                """,
                (row["name"], template_id),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("TEMPLATE_ACTIVE_NAME_CONFLICT")
            connection.execute(
                """
                UPDATE transaction_templates SET status = 'active', updated_at = ?
                WHERE template_id = ?
                """,
                (now_iso(), template_id),
            )
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="template.restore",
                entity_type="template",
                entity_id=template_id,
                details={},
            )

    def delete_template(self, template_id: str) -> None:
        """真的刪掉一個模板。

        **這裡沒有引用檢查，而且那是查過 schema 的結論不是疏漏**：整份 schema 裡
        沒有任何一張表指向 `transaction_templates`。模板是「常用的一筆帳長什麼樣」，
        套用之後產生的是一筆獨立的交易，那筆交易不記得自己從哪個模板來 ——
        所以刪掉模板動不到任何歷史資料。

        對照組是帳戶與類別：它們被 posting、盤點與模板引用，所以刪除前一定要檢查。
        """
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                "DELETE FROM transaction_templates WHERE template_id = ?",
                (template_id,),
            ).rowcount
            if changed == 0:
                raise NotFoundError("TEMPLATE_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="template.delete",
                entity_type="template",
                entity_id=template_id,
                details={},
            )
