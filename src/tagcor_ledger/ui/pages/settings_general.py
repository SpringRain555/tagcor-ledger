"""一般設定：預設帳戶、預設流向、每頁筆數、盤點提醒。

幣別與時區固定顯示為唯讀（TWD、Asia/Taipei），不是還沒做的下拉選單。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.domain.models import ApplicationSettings
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import ENTRY_NAMES, result_message
from tagcor_ledger.ui.widgets.forms import fill_combo, form_panel, select_data
from tagcor_ledger.ui.widgets.table import set_button_role


class GeneralSettingsPage(QWidget):
    saved = Signal()

    def __init__(self, controller: LedgerController, paths: AppPaths) -> None:
        super().__init__()
        self.controller = controller
        self.paths = paths
        self.account = QComboBox()
        self.flow = QComboBox()
        self.page_size = QComboBox()
        self.balance_snapshot_reminder = QCheckBox("每日提醒記錄預設帳戶目前金額")
        self.result = QLabel()
        self._build()
        self.reload()

    def _build(self) -> None:
        for key in ("expense", "income", "transfer"):
            self.flow.addItem(ENTRY_NAMES[key], key)
        for size in (20, 50, 100):
            self.page_size.addItem(f"{size} 筆", size)
        save = QPushButton("儲存設定")
        set_button_role(save, "primary")
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("預設帳戶", self.account)
        form.addRow("預設流向", self.flow)
        form.addRow("交易列表每頁", self.page_size)
        form.addRow("餘額盤點提醒", self.balance_snapshot_reminder)
        form.addRow("固定幣別", QLabel("TWD"))
        form.addRow("固定時區", QLabel("Asia/Taipei"))
        # 資料庫檔案的完整路徑在「資料路徑」分頁 —— 這一頁講的是偏好，不是位置。
        # 而且那一行 QLabel 是整個視窗最小寬度的來源（907 px），放在這裡沒有理由。
        form.addRow("", save)
        form.addRow("", self.result)
        row = QHBoxLayout()
        row.addWidget(form_panel(form))
        row.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addStretch()
        save.clicked.connect(self.save)

    def reload(self) -> None:
        fill_combo(
            self.account,
            self.controller.account_options(),
            "name",
            "account_id",
        )
        settings = self.controller.get_settings()
        select_data(self.account, settings.default_account_id)
        select_data(self.flow, settings.default_entry_type)
        select_data(self.page_size, settings.transactions_page_size)
        self.balance_snapshot_reminder.setChecked(settings.balance_snapshot_reminder)

    def save(self) -> None:
        result = self.controller.save_settings(
            ApplicationSettings(
                default_account_id=str(self.account.currentData()),
                default_entry_type=str(self.flow.currentData()),
                transactions_page_size=int(self.page_size.currentData()),
                balance_snapshot_reminder=self.balance_snapshot_reminder.isChecked(),
            )
        )
        self.result.setText(result_message(result))
        if result.success:
            self.saved.emit()
