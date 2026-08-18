from pathlib import Path

from PySide6.QtWidgets import QApplication

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.main_window import MainWindow


def test_main_window_has_traditional_chinese_navigation(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    assert window.navigation.count() == 6
    assert window.navigation.item(0).text() == "快速記帳"
    assert window.navigation.item(1).text() == "餘額盤點"
    assert window.navigation.item(2).text() == "待確認（0）"
    assert window.navigation.item(3).text() == "交易紀錄"
    assert window.navigation.item(4).text() == "操作設定"
    assert window.navigation.item(5).text() == "系統設定"
    assert window.windowTitle() == "TagCor Ledger"


def test_main_window_applies_scoped_dark_theme(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()

    app = QApplication.instance()
    assert app is not None
    styles = app.styleSheet()
    assert window.navigation.objectName() == "sidebarNavigation"
    assert window.pages.objectName() == "contentStack"
    assert window.system_settings.maintenance.list.objectName() == "backupList"
    assert "QTabBar::tab" in styles
    assert "QListWidget#sidebarNavigation" in styles
    assert "QListWidget#backupList" in styles
    assert "#0F172A" in styles


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
    page.description.setText("早餐")
    page.submit()

    result = window.controller.list_transactions()
    assert result.success
    transaction = result.details["transactions"][0]
    assert transaction["description"] == "早餐"
    assert "payee_name" not in transaction


def test_balance_snapshot_page_creates_snapshot_and_setting(qtbot, tmp_path: Path) -> None:
    window = MainWindow(resolve_app_paths(tmp_path / "ledger-data"))
    qtbot.addWidget(window)
    window.show()
    page = window.balance

    page.amount.setText("0")
    page.note.setText("初次盤點")
    page.create_snapshot()

    assert page.model.rowCount() == 1
    assert "餘額盤點已儲存" in page.result.text()
    assert "未解釋差額" in page.summary.text()

    window.system_settings.general.balance_snapshot_reminder.setChecked(False)
    window.system_settings.general.save()
    assert not window.controller.get_settings().balance_snapshot_reminder
