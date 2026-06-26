from pathlib import Path

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window_phase12 import MainWindow


def test_main_window_has_traditional_chinese_navigation(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    assert window.navigation.count() == 9
    assert window.navigation.item(0).text() == "快速記帳"
    assert window.navigation.item(1).text() == "餘額盤點"
    assert window.navigation.item(2).text() == "待確認（0）"
    assert window.navigation.item(3).text() == "交易紀錄"
    assert window.windowTitle() == "TagCor Ledger"


def test_quick_entry_switches_transfer_fields_and_saves(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.quick

    page.flow.setCurrentIndex(page.flow.findData("transfer"))
    assert page.destination.isHidden() is False
    assert page.category.isHidden() is True

    page.flow.setCurrentIndex(page.flow.findData("expense"))
    page.amount.setText("85")
    page.payee.setText("便利商店")
    page.submit()

    result = window.controller.list_transactions()
    assert result.success
    assert result.details["transactions"][0]["payee_name"] == "便利商店"


def test_balance_snapshot_page_creates_snapshot_and_setting(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.balance

    page.amount.setText("0")
    page.note.setText("啟動後盤點")
    page.create_snapshot()

    assert page.model.rowCount() == 1
    assert "餘額盤點已儲存" in page.result.text()
    assert "未解釋差額" in page.summary.text()

    window.settings.balance_snapshot_reminder.setChecked(False)
    window.settings.save()
    assert not window.controller.get_settings().balance_snapshot_reminder
