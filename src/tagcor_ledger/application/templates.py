"""模板的 use case。

模板是「常用的一筆帳長什麼樣」。它**不會自己變成交易** —— 「填入記帳頁」只把欄位帶到
記帳頁，使用者仍然要自己按儲存。

## 這個檔案以前叫 `automation.py`

它曾經同時管模板、定期收支與待確認項目，所以叫「自動化」。v0.23.0 移除定期收支之後，
這裡剩下的東西**沒有一項是自動的** —— 留著那個名字只會讓下一個人以為還有背景工作在跑。
理由見 [ADR-0011](../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.failures import STORE_FAILURES, failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import SortLevel, TransactionTemplate
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


class TemplateService:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        # 簽章跟其他 service 一樣收一個可選的 store。以前是自己建一個，
        # 於是 controller 沒辦法把同一個 store 分給它，`initialize_database` 也多跑一次。
        self.store = store or LedgerStore(paths)

    def list_templates(
        self,
        *,
        include_archived: bool = False,
        sort: Sequence[SortLevel] = (),
    ) -> Result:
        """模板清單。**每一列攤平成一個 dict，名字與 id 平輩。**

        `TemplateRow` 是「模板 ＋ 四個 join 回來的名字」的組合，但頁面拿到的一律是
        平的 dict（`RowsModel` 存的就是那個）—— 做法與 `CategoryService.list_tree()`
        把 `CategoryNode` 攤平成一列一樣。

        **不要 `asdict(row)`。** 那會產生 `{"template": {...}, "account_name": ...}`
        這種巢狀結構，於是每一個讀 `item["template_id"]` 的地方都要改成
        `item["template"]["template_id"]` —— 而那些地方包括排序視窗、編輯對話框與
        「填入記帳頁」。
        """
        return Result.ok(
            "模板已載入。",
            details={
                "templates": [
                    {
                        **asdict(row.template),
                        "account_name": row.account_name,
                        "destination_account_name": row.destination_account_name,
                        "category_name": row.category_name,
                        "subcategory_name": row.subcategory_name,
                    }
                    for row in self.store.list_templates(
                        include_archived=include_archived, sort=tuple(sort)
                    )
                ]
            },
        )

    def save_template(self, template: TransactionTemplate) -> Result:
        try:
            saved = self.store.save_template(template)
            return Result.ok("模板已儲存。", details={"template": asdict(saved)})
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TEMPLATE_SAVE_FAILED",
                fallback_message="模板無法儲存。請匯出診斷資訊回報。",
            )

    def new_template(
        self,
        *,
        name: str,
        entry_type: str,
        account_id: str,
        destination_account_id: str | None,
        category_id: str | None,
        amount_minor: int | None,
        description: str,
    ) -> TransactionTemplate:
        return TransactionTemplate(
            template_id=f"tpl_{uuid4().hex}",
            name=name,
            status="active",
            entry_type=entry_type,
            account_id=account_id,
            destination_account_id=destination_account_id,
            category_id=category_id,
            amount_minor=amount_minor,
            currency="TWD",
            description=description,
            sort_order=100,
        )

    def archive_template(self, template_id: str) -> Result:
        try:
            self.store.archive_template(template_id)
            return Result.ok("模板已封存。")
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TEMPLATE_ARCHIVE_FAILED",
                fallback_message="模板無法封存。請匯出診斷資訊回報。",
            )

    def restore_template(self, template_id: str) -> Result:
        try:
            self.store.restore_template(template_id)
            return Result.ok("模板已恢復。")
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TEMPLATE_RESTORE_FAILED",
                fallback_message="模板無法恢復。請匯出診斷資訊回報。",
            )

    def delete_template(self, template_id: str) -> Result:
        try:
            self.store.delete_template(template_id)
            return Result.ok("模板已刪除。")
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TEMPLATE_DELETE_FAILED",
                fallback_message="模板無法刪除。請匯出診斷資訊回報。",
            )

    def set_template_order(self, ordered_ids: list[str]) -> Result:
        """模板的自訂順序。"""
        try:
            self.store.set_template_order(ordered_ids)
            return Result.ok("順序已更新。")
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="TEMPLATE_REORDER_FAILED",
                fallback_message="順序無法更新。請匯出診斷資訊回報。",
            )
