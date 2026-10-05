"""餘額盤點：記錄「現在實際看到多少」，並顯示未解釋差額。

盤點**不建立交易**。差額不為零時的處置是補記交易，不是叫程式生一筆調整。

## 這一頁的形狀（2026-09-20 起）

上方表單只負責**新增**。表格底下兩排按鈕：第一排是「產生新東西」（新增盤點、補記交易），
第二排對**所選盤點**動作（編輯、刪除）。「編輯」開對話框（`BalanceSnapshotEditDialog`），
「刪除」**真的移除**那一筆（2026-10-05 起，ADR-0015；之前是標成已刪除、紀錄留著）。

以前點表格某一列會把值倒進上方表單，再按「更新所選盤點」寫回。兩個問題：正在打的新盤點
會被點到的那一列蓋掉；而一顆叫「更新」的按鈕一按就寫入，使用者以為它會先開視窗。
「重新整理」也拿掉了 —— 換帳戶、換狀態本來就會重查，跨頁的改動由 `main_window` 通知。

**「最近盤點差額期間內的交易」那張表拿掉了。** 它佔掉半頁，而要查交易本來就有交易紀錄頁
（帳戶、日期區間都篩得到）；連同底下那條只有它在用的查詢一起移除，不留死碼。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.application.result import Result
from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    balance_gap_values,
    display_date,
    minor_text,
    result_message,
)
from tagcor_ledger.ui.widgets.forms import (
    date_field,
    fill_combo,
    form_panel,
    iso_from_date,
    select_data,
    show_status,
)
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import (
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


class BalanceSnapshotPage(QWidget):
    changed = Signal()
    record_transaction_requested = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.account = QComboBox()
        self.observed_at = date_field()
        self.amount = QLineEdit()
        self.note = QLineEdit()
        self.result = QLabel()
        self.summary = QLabel()
        self.table = QTableView()
        self.model = RowsModel(
            ["盤點日期", "帳戶", "實際金額", "預期金額", "未解釋差額", "備註", "狀態"],
            balance_gap_values,
            amount_column=4,
        )
        self._build()
        self.reload_accounts()

    def _build(self) -> None:
        title = QLabel("餘額盤點")
        title.setObjectName("pageTitle")
        help_text = QLabel(
            "盤點只記錄實際看到的帳戶金額，不會直接入帳。"
            "補記兩次盤點之間的交易後，未解釋差額會自動重新計算。"
        )
        help_text.setObjectName("hintLabel")
        help_text.setWordWrap(True)
        self.amount.setPlaceholderText("例如：1200，可填 0")
        self.note.setPlaceholderText("可留空，例如：開啟程式時盤點")
        self.result.setObjectName("statusLabel")
        self.result.setWordWrap(True)
        self.summary.setObjectName("hintLabel")
        self.summary.setWordWrap(True)

        create_button = QPushButton("新增盤點")
        quick_button = QPushButton("補記交易")
        edit_button = QPushButton("編輯")
        delete_button = QPushButton("刪除")
        set_button_role(create_button, "primary")
        set_button_role(delete_button, "danger")

        form = QFormLayout()
        form.addRow("帳戶", self.account)
        form.addRow("盤點日期", self.observed_at)
        form.addRow("目前金額（TWD）", self.amount)
        form.addRow("備註", self.note)
        form.addRow("", self.result)

        # 兩排，分的是**動作的對象**：第一排產生新東西，第二排對所選盤點動作。
        # 「匯出盤點 CSV」2026-10-05 搬到「系統設定 → 備份與還原」。
        create_row = QHBoxLayout()
        for button in (create_button, quick_button):
            create_row.addWidget(button)
        create_row.addStretch()
        selected_row = QHBoxLayout()
        for button in (edit_button, delete_button):
            selected_row.addWidget(button)
        selected_row.addStretch()

        setup_table(self.table, self.model, stretch_column=5)
        # 編輯／刪除是對所選盤點動作，沒選就停用。
        bind_selection(self.table, edit_button, delete_button)
        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addWidget(help_text)
        # 表單另外收到 720 —— 這一頁有表單也有表格，整頁用表單寬度會塞不下七欄的表。
        layout.addWidget(form_panel(form))
        layout.addLayout(create_row)
        layout.addLayout(selected_row)
        layout.addWidget(self.summary)
        records_title = QLabel("盤點紀錄")
        records_title.setObjectName("sectionTitle")
        layout.addWidget(records_title)
        layout.addWidget(self.table)

        self.account.currentIndexChanged.connect(self.refresh)
        create_button.clicked.connect(self.create_snapshot)
        quick_button.clicked.connect(lambda: self.record_transaction_requested.emit())
        edit_button.clicked.connect(self.edit_selected)
        delete_button.clicked.connect(self.delete_selected)

    def reload_accounts(self) -> None:
        fill_combo(self.account, self.controller.account_options(), "name", "account_id")
        self.refresh()

    def refresh(self) -> None:
        account_id = self._account_id()
        if account_id is None:
            self.model.replace_rows([])
            self.summary.setText("尚未建立帳戶。")
            return
        gaps = self.controller.list_balance_snapshots(account_id=account_id, limit=50)
        self.model.replace_rows(gaps)
        latest = self.controller.latest_balance_gap(account_id)
        if latest is None:
            self.summary.setText("此帳戶尚未盤點。可先輸入目前金額，之後再慢慢補記交易。")
            return
        difference = int(latest["difference_minor"])
        sign_text = "完全吻合" if difference == 0 else latest["difference"]
        self.summary.setText(
            "最近盤點："
            f"{display_date(str(latest['observed_at']))}；"
            f"實際 {latest['actual_balance']} TWD，"
            f"預期 {latest['expected_balance']} TWD，"
            f"未解釋差額 {sign_text} TWD。"
        )

    def create_snapshot(self) -> None:
        account_id = self._account_id()
        if account_id is None:
            show_status(self.result, "請先建立帳戶。", ok=False)
            return
        result = self.controller.create_balance_snapshot(
            account_id=account_id,
            observed_at=iso_from_date(self.observed_at),
            actual_balance=self.amount.text().strip(),
            note=self.note.text().strip(),
        )
        show_status(self.result, result_message(result), ok=result.success)
        if result.success:
            self.amount.clear()
            self.note.clear()
            self.observed_at.setDate(QDate.currentDate())
            self.changed.emit()
            self.refresh()

    def edit_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        dialog = BalanceSnapshotEditDialog(self.controller, item, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.saved_result is None:
            return
        show_status(self.result, result_message(dialog.saved_result), ok=True)
        self.changed.emit()
        self.refresh()

    def delete_selected(self) -> None:
        """**真的刪掉**（ADR-0015）。確認框講兩件事：找不回來，以及後面那次盤點會怎樣。"""
        item = self.model.selected_item(self.table)
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "確認刪除",
            f"確定要刪除 {display_date(str(item['observed_at']))} 那一次盤點嗎？\n\n"
            "刪掉之後就找不回來了。後面那一次盤點的未解釋差額，會改拿再前一次的盤點重算。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self.controller.delete_balance_snapshot(str(item["snapshot_id"]))
        show_status(self.result, result_message(result), ok=result.success)
        if result.success:
            self.changed.emit()
            self.refresh()

    def _account_id(self) -> str | None:
        value = self.account.currentData()
        return str(value) if isinstance(value, str) else None


class BalanceSnapshotEditDialog(QDialog):
    """編輯一筆盤點。形狀照 `transactions.TransactionEditDialog`：
    失敗把訊息印在視窗裡、**不關視窗**，成功才 `accept()`。

    `saved_result` 給頁面拿成功訊息用 —— **不叫 `result`**，那是 `QDialog` 自己的方法。
    """

    def __init__(
        self,
        controller: LedgerController,
        snapshot: dict[str, Any],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.snapshot = snapshot
        self.account = QComboBox()
        self.observed_at = date_field()
        self.amount = QLineEdit(minor_text(snapshot["actual_balance_minor"]))
        self.note = QLineEdit(str(snapshot.get("note", "")))
        self.error = QLabel()
        self.saved_result: Result | None = None
        self._build()

    def _build(self) -> None:
        self.setWindowTitle("編輯盤點")
        try:
            observed = datetime.fromisoformat(str(self.snapshot["observed_at"])).astimezone(TAIPEI)
            self.observed_at.setDate(QDate(observed.year, observed.month, observed.day))
        except ValueError:
            pass
        self.error.setObjectName("errorLabel")
        fill_combo(self.account, self.controller.account_options(), "name", "account_id")
        select_data(self.account, self.snapshot.get("account_id"))
        form = QFormLayout()
        form.addRow("帳戶", self.account)
        form.addRow("盤點日期", self.observed_at)
        form.addRow("目前金額（TWD）", self.amount)
        form.addRow("備註", self.note)
        form.addRow("", self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def save(self) -> None:
        result = self.controller.update_balance_snapshot(
            str(self.snapshot["snapshot_id"]),
            account_id=str(self.account.currentData()),
            # 編輯沿用原本的時分秒 —— 只改個備註不該讓它跳到當天最後一筆（同交易的編輯）。
            observed_at=iso_from_date(
                self.observed_at, keep_time_from=str(self.snapshot["observed_at"])
            ),
            actual_balance=self.amount.text().strip(),
            note=self.note.text().strip(),
        )
        if result.success:
            self.saved_result = result
            self.accept()
        else:
            self.error.setText(result_message(result))
