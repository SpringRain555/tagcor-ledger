"""模板、定期收支與待確認項目。

UI 上叫「定期收支」，schema 仍是 `recurring_schedules` —— 那是兩件事，見 glossary。
`generate_due()` 是這裡唯一有判斷的方法，理由寫在它自己的 docstring 裡。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import RecurringSchedule, SortLevel, TransactionTemplate
from tagcor_ledger.ui.controller.wiring import ControllerBase


class AutomationSection(ControllerBase):
    # --- 模板 ---------------------------------------------------------------

    def list_templates(
        self,
        *,
        include_archived: bool = False,
        sort: Sequence[SortLevel] = (),
    ) -> list[dict[str, Any]]:
        return self._rows(
            self.automation.list_templates(include_archived=include_archived, sort=sort),
            "templates",
        )

    def save_template(self, template: TransactionTemplate) -> Result:
        return self.automation.save_template(template)

    def new_template(self, **values: Any) -> TransactionTemplate:
        return self.automation.new_template(**values)

    def archive_template(self, template_id: str) -> Result:
        return self.automation.archive_template(template_id)

    def set_template_order(self, ordered_ids: list[str]) -> Result:
        return self.automation.set_template_order(ordered_ids)

    # --- 定期收支 -----------------------------------------------------------

    def list_schedules(self) -> list[dict[str, Any]]:
        return self._rows(self.automation.list_schedules(), "schedules")

    def save_schedule(self, schedule: RecurringSchedule) -> Result:
        return self.automation.save_schedule(schedule)

    def new_schedule(self, **values: Any) -> RecurringSchedule:
        return self.automation.new_schedule(**values)

    def archive_schedule(self, schedule_id: str) -> Result:
        return self.automation.archive_schedule(schedule_id)

    # --- 待確認 -------------------------------------------------------------

    def generate_due(self) -> Result:
        """定期收支與定存一起產生。**單一收件匣**：使用者不該需要知道待確認來自哪個子系統。"""
        result = self.automation.generate_due()
        deposits = self.deposits.generate_due()
        if not result.success:
            return result
        merged = dict(result.details)
        merged["deposit_generated"] = deposits.details.get("generated", 0)
        # 收件匣靠這個值決定要不要浮出「還有更多漏期」那一行。
        self.generation_has_more = bool(merged.get("has_more"))
        return Result.ok(result.message, details=merged, correlation_id=result.correlation_id)

    def list_pending(self) -> list[dict[str, Any]]:
        return self._rows(self.automation.list_pending(), "occurrences")

    def update_occurrence(self, occurrence_id: str, **values: Any) -> Result:
        return self.automation.update_occurrence(occurrence_id, **values)

    def confirm_occurrence(self, occurrence_id: str) -> Result:
        return self.automation.confirm(occurrence_id)

    def skip_occurrence(self, occurrence_id: str) -> Result:
        return self.automation.skip(occurrence_id)

    def batch_confirm_valid(self) -> Result:
        return self.automation.batch_confirm_valid()
