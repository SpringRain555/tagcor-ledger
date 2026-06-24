from pathlib import Path

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window_v2 import MainWindow


def test_main_window_has_traditional_chinese_navigation(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    assert window.navigation.count() == 6
    assert window.navigation.item(0).text() == "快速記帳"
    assert window.navigation.item(1).text() == "交易紀錄"
    assert window.windowTitle() == "TagCor Ledger"


def test_quick_entry_switches_transfer_fields_and_saves(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.quick_page

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
