"""餘額盤點：記錄「現在實際看到多少」，並顯示未解釋差額。

盤點**不建立交易**。差額不為零時的處置是補記交易，不是叫程式生一筆調整。
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QWidget,
)

from tagcor_ledger.infrastructure.clock import TAIPEI
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import (
    balance_gap_values,
    display_date,
    minor_text,
    result_message,
    transaction_values,
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
        self.status = QComboBox()
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
        self.transactions = QTableView()
        self.transactions_model = RowsModel(
            ["日期", "類型", "帳戶", "類別／項目", "金額（TWD）"],
            transaction_values,
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
        for label, value in (("有效", "active"), ("已作廢", "voided"), ("全部", "all")):
            self.status.addItem(label, value)

        create_button = QPushButton("新增盤點")
        update_button = QPushButton("更新所選盤點")
        void_button = QPushButton("作廢所選盤點")
        export_button = QPushButton("匯出盤點 CSV")
        refresh_button = QPushButton("重新整理")
        quick_button = QPushButton("補記交易")
        set_button_role(create_button, "primary")
        set_button_role(void_button, "danger")

        form = QFormLayout()
        form.addRow("帳戶", self.account)
        form.addRow("盤點日期", self.observed_at)
        form.addRow("目前金額（TWD）", self.amount)
        form.addRow("備註", self.note)
        form.addRow("列表狀態", self.status)
        form.addRow("", self.result)

        # 分兩行：對盤點動作的一行，其他的一行。六顆擠一行會把視窗最小寬度撐大。
        actions = QHBoxLayout()
        for button in (create_button, update_button, void_button):
            actions.addWidget(button)
        actions.addStretch()
        extra_actions = QHBoxLayout()
        for button in (export_button, refresh_button, quick_button):
            extra_actions.addWidget(button)
        extra_actions.addStretch()

        setup_table(self.table, self.model, stretch_column=5)
        setup_table(self.transactions, self.transactions_model, stretch_column=3)
        # 更新／作廢是對所選盤點動作，沒選就停用。
        bind_selection(self.table, update_button, void_button)
        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addWidget(help_text)
        # 表單另外收到 720 —— 這一頁有表單也有表格，整頁用表單寬度會塞不下七欄的表。
        layout.addWidget(form_panel(form))
        layout.addLayout(actions)
        layout.addLayout(extra_actions)
        layout.addWidget(self.summary)
        records_title = QLabel("盤點紀錄")
        records_title.setObjectName("sectionTitle")
        layout.addWidget(records_title)
        layout.addWidget(self.table)
        period_title = QLabel("最近盤點差額期間內的交易")
        period_title.setObjectName("sectionTitle")
        layout.addWidget(period_title)
        layout.addWidget(self.transactions)

        self.account.currentIndexChanged.connect(self.refresh)
        self.status.currentIndexChanged.connect(self.refresh)
        create_button.clicked.connect(self.create_snapshot)
        update_button.clicked.connect(self.update_selected)
        void_button.clicked.connect(self.void_selected)
        export_button.clicked.connect(self.export_csv)
        refresh_button.clicked.connect(self.refresh)
        quick_button.clicked.connect(lambda: self.record_transaction_requested.emit())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.load_selected())

    def reload_accounts(self) -> None:
        fill_combo(self.account, self.controller.account_options(), "name", "account_id")
        self.refresh()

    def refresh(self) -> None:
        account_id = self._account_id()
        if account_id is None:
            self.model.replace_rows([])
            self.transactions_model.replace_rows([])
            self.summary.setText("尚未建立帳戶。")
            return
        gaps = self.controller.list_balance_snapshots(
            account_id=account_id,
            status=str(self.status.currentData()),
            limit=50,
        )
        self.model.replace_rows(gaps)
        latest = self.controller.latest_balance_gap(account_id)
        if latest is None:
            self.summary.setText("此帳戶尚未盤點。可先輸入目前金額，之後再慢慢補記交易。")
            self.transactions_model.replace_rows([])
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
        self.transactions_model.replace_rows(
            self.controller.list_balance_gap_transactions(
                account_id=account_id,
                period_start=cast(str | None, latest.get("period_start")),
                period_end=str(latest["period_end"]),
            )
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

    def update_selected(self) -> None:
        item = self.model.selected_item(self.table)
        account_id = self._account_id()
        if item is None or account_id is None:
            show_status(self.result, "請先選擇要更新的盤點。", ok=False)
            return
        result = self.controller.update_balance_snapshot(
            str(item["snapshot_id"]),
            account_id=account_id,
            observed_at=iso_from_date(
                self.observed_at, keep_time_from=str(item["observed_at"])
            ),
            actual_balance=self.amount.text().strip(),
            note=self.note.text().strip(),
        )
        show_status(self.result, result_message(result), ok=result.success)
        if result.success:
            self.changed.emit()
            self.refresh()

    def void_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None or item["status"] != "active":
            return
        answer = QMessageBox.question(self, "確認作廢", "確定要作廢所選餘額盤點嗎？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self.controller.void_balance_snapshot(str(item["snapshot_id"]))
        show_status(self.result, result_message(result), ok=result.success)
        if result.success:
            self.changed.emit()
            self.refresh()

    def load_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        select_data(self.account, item.get("account_id"))
        try:
            observed = datetime.fromisoformat(str(item["observed_at"])).astimezone(TAIPEI)
            self.observed_at.setDate(QDate(observed.year, observed.month, observed.day))
        except ValueError:
            pass
        self.amount.setText(minor_text(item["actual_balance_minor"]))
        self.note.setText(str(item.get("note", "")))

    def export_csv(self) -> None:
        result = self.controller.export_balance_snapshots_csv()
        if result.success:
            show_status(
                self.result,
                f"餘額盤點 CSV 已匯出：{result.details.get('path')}",
                ok=True,
            )
        else:
            show_status(self.result, result_message(result), ok=False)

    def _account_id(self) -> str | None:
        value = self.account.currentData()
        return str(value) if isinstance(value, str) else None
