"""模板。

這一段全是轉發 —— 頁面呼叫 controller，controller 呼叫 service，service 回 `Result`。
**中間不做判斷**：需要判斷的東西屬於 `overview.py`，不屬於這裡。

這個檔案以前叫 `automation.py`，還管著定期收支與待確認項目。v0.23.0 移除定期收支之後
剩下的東西沒有一項是自動的（[ADR-0011](../../../../docs/decisions/ADR-0011-drop-recurring-schedules.md)）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import SortLevel, TransactionTemplate
from tagcor_ledger.ui.controller.wiring import ControllerBase


class TemplateSection(ControllerBase):
    def list_templates(
        self,
        *,
        include_archived: bool = False,
        sort: Sequence[SortLevel] = (),
    ) -> list[dict[str, Any]]:
        return self._rows(
            self.templates.list_templates(include_archived=include_archived, sort=sort),
            "templates",
        )

    def save_template(self, template: TransactionTemplate) -> Result:
        return self.templates.save_template(template)

    def new_template(self, **values: Any) -> TransactionTemplate:
        return self.templates.new_template(**values)

    def archive_template(self, template_id: str) -> Result:
        return self.templates.archive_template(template_id)

    def restore_template(self, template_id: str) -> Result:
        return self.templates.restore_template(template_id)

    def delete_template(self, template_id: str) -> Result:
        return self.templates.delete_template(template_id)

    def set_template_order(self, ordered_ids: list[str]) -> Result:
        return self.templates.set_template_order(ordered_ids)
