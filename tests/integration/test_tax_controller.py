"""稅務 controller 接線、日期來源與總覽摘要。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest

from tagcor_ledger.app.path_settings import PathSettingsService
from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.tax.dataset import Window
from tagcor_ledger.domain.tax.dataset_validate import validate_tax_dataset
from tagcor_ledger.domain.tax.freshness import FreshnessIssue
from tagcor_ledger.domain.tax.kinds import TaxKind
from tagcor_ledger.domain.tax.reminders import (
    ReminderCycle,
    ReminderState,
    ReminderSwitch,
    ReminderView,
)
from tagcor_ledger.ui.controller import LedgerController


SAMPLE_DATASET = Path(__file__).resolve().parents[1] / "fixtures" / "tax" / "sample.json"


@pytest.fixture
def controller_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LedgerController:
    monkeypatch.setenv("TAGCOR_TAX_DATA", str(SAMPLE_DATASET))
    monkeypatch.setenv("TAGCOR_REFERENCE_DB", str(tmp_path / "missing-reference.sqlite3"))
    return LedgerController(resolve_app_paths(tmp_path / "ledger-data"))


def test_tax_overview_uses_sample_date_and_refuses_missing_filing_inputs(
    controller_for: LedgerController,
) -> None:
    controller = controller_for
    controller.today_provider = lambda: date(2026, 5, 10)

    overview = controller.tax_overview()

    assert len(overview.reminders) == 1
    assert overview.reminders[0].kind is TaxKind.INCOME_TAX
    assert overview.reminders[0].state is ReminderState.OPEN
    assert overview.unset_count == 4
    assert overview.problem is None
    assert overview.income_tax_estimate is not None
    assert overview.income_tax_estimate.refused
    assert any(
        reason.value == "inputs_missing"
        for reason in overview.income_tax_estimate.refused
    )


def test_blocking_missing_dataset_clears_tax_overview(
    controller_for: LedgerController,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = controller_for
    missing = tmp_path / "missing-dataset.json"
    controller.tax.dataset_path = missing
    controller.today_provider = lambda: date(2026, 5, 10)
    kind = TaxKind.HOUSE_TAX
    window = Window(
        kind,
        2026,
        date(2026, 5, 1),
        date(2026, 5, 31),
        False,
        None,
        (),
    )
    cycle = ReminderCycle(
        kind,
        2026,
        window,
        date(2026, 4, 17),
        date(2026, 6, 30),
    )
    view = ReminderView(kind, ReminderState.OPEN, cycle, None, None)
    monkeypatch.setattr(controller, "tax_reminder_views", lambda: (view,))
    monkeypatch.setattr(
        controller,
        "tax_reminder_switches",
        lambda: {tax_kind: ReminderSwitch.ON for tax_kind in TaxKind},
    )

    overview = controller.tax_overview()

    assert overview.problem is not None
    assert overview.problem.issue is FreshnessIssue.DATASET_MISSING
    assert overview.reminders == ()
    assert overview.folded == 0
    assert overview.unset_count == 0
    assert overview.income_tax_estimate is None


def test_five_open_reminders_are_folded_to_two(controller_for: LedgerController, tmp_path: Path) -> None:
    controller = controller_for
    raw = json.loads(SAMPLE_DATASET.read_text(encoding="utf-8"))
    updated = deepcopy(raw)
    updated["calendar"]["years"]["2026"] = {
        kind.value: {
            "start": "2026-05-01",
            "end": "2026-05-31",
            "note": None,
            "source_ids": ["calendar-example"],
        }
        for kind in TaxKind
    }
    assert validate_tax_dataset(updated) == []
    dataset_path = tmp_path / "all-windows.json"
    dataset_path.write_text(json.dumps(updated, ensure_ascii=False), encoding="utf-8")
    controller.tax.dataset_path = dataset_path
    controller.today_provider = lambda: date(2026, 5, 10)
    for kind in TaxKind:
        assert controller.save_tax_reminder_switch(kind, ReminderSwitch.ON).success

    overview = controller.tax_overview()

    assert len(overview.reminders) == 2
    assert overview.folded == 3
    assert all(view.state is ReminderState.OPEN for view in overview.reminders)


def test_overview_snapshot_includes_tax_summary(controller_for: LedgerController) -> None:
    controller = controller_for
    controller.today_provider = lambda: date(2026, 5, 10)

    assert controller.overview_snapshot()["tax"] == controller.tax_overview()


def test_changing_data_paths_rewires_tax_service(controller_for: LedgerController, tmp_path: Path) -> None:
    controller = controller_for
    previous_tax = controller.tax
    controller.path_settings = PathSettingsService(tmp_path / "system_paths.json")
    data_root = tmp_path / "new-data"

    saved = controller.save_path_settings(
        data_root=data_root,
        ledger_dir=data_root / "ledger",
        backup_dir=data_root / "backups",
        move_current=False,
    )

    assert saved.success
    assert controller.tax is not previous_tax

