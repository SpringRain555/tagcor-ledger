"""餘額盤點：記錄「現在實際看到多少」、顯示未解釋差額，以及**補上帳本還缺的交易**。

盤點**不建立交易**。差額不為零時的處置是補記交易，不是叫程式生一筆調整。

## 這一頁的形狀（2026-10-05 起）

1. 上方表單只負責**新增**（帳戶同時是底下清單的篩選）。
2. **一排**「新增盤點」「編輯」「刪除」—— 使用者 2026-10-05 要求排在同一排。「編輯」「刪除」
   對所選盤點動作，沒選就停用；「編輯」開對話框（`BalanceSnapshotEditDialog`），
   「刪除」**真的移除**那一筆（ADR-0015）。
3. 最近一次盤點的摘要，然後「盤點紀錄」表。一次列 `PAGE_SIZE` 筆，滿了才出現「載入更多」。
4. **「補記與待確認」**：未解釋差額的兩種處置放在一起 ——「補記交易」去記帳頁補上漏記的
   （帳戶先選好這一頁正在看的那個），底下是定存產生的待確認草稿（`InboxSection`）。
   待確認以前是側邊欄獨立的一頁，理由見 ADR-0016 與 `inbox.py` 的模組說明。

以前點表格某一列會把值倒進上方表單，再按「更新所選盤點」寫回。兩個問題：正在打的新盤點
會被點到的那一列蓋掉；而一顆叫「更新」的按鈕一按就寫入，使用者以為它會先開視窗。
「重新整理」也拿掉了 —— 換帳戶本來就會重查，跨頁的改動由 `main_window` 通知。

**「最近盤點差額期間內的交易」那張表拿掉了。** 它佔掉半頁，而要查交易本來就有交易紀錄頁
（帳戶、日期區間都篩得到）；連同底下那條只有它在用的查詢一起移除，不留死碼。

## 兩個訊號，兩種改動

`changed` 是**盤點**被新增、編輯或刪除 —— 只有這一頁自己要重算。`ledger_changed` 是待確認
按下確認入帳或略過 —— 那會建立交易，交易紀錄、徽章都要跟著動，主視窗把它接到 `_ledger_changed()`。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from tagcor_ledger.ui.pages.inbox import InboxSection
from tagcor_ledger.ui.widgets.confirm import confirm
from tagcor_ledger.ui.widgets.forms import (
    combo_box,
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

PAGE_SIZE = 50
"""盤點紀錄一次列幾筆。滿了才出現「載入更多」，每按一次多 `PAGE_SIZE` 筆。

以前寫死 50、沒有下一頁：一個帳戶每月盤點一次，四年多之後最舊的就看不到了。"""

MAX_ROWS = 10_000
"""「載入更多」的上限，跟 store 的 `list_balance_gaps(limit=...)` 允許的最大值一致。"""

RECORD_TABLE_ROWS = 12
"""盤點紀錄表最多長到幾列，再多就讓它自己捲 —— 底下還有「補記與待確認」，
表格長滿整頁的話那一塊會被推到看不見的地方。"""

GAP_HELP = (
    "未解釋差額不為零，通常是兩種情形：有交易漏記了 —— 按「補記交易」去記帳頁補上；"
    "或定存的利息、到期本息還沒確認入帳 —— 就在下面確認。兩種做完，差額都會自動重算。"
)


class BalanceSnapshotPage(QWidget):
    changed = Signal()
    """盤點被新增、編輯或刪除。"""

    ledger_changed = Signal()
    """待確認按下確認入帳或略過 —— 帳本本身變了（見模組說明「兩個訊號」）。"""

    record_transaction_requested = Signal(str)
    """「補記交易」。帶著這一頁正在看的帳戶 id（沒有帳戶時是空字串）。"""

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.account = combo_box()
        self.observed_at = date_field()
        self.amount = QLineEdit()
        self.note = QLineEdit()
        self.result = QLabel()
        self.summary = QLabel()
        self.table = QTableView()
        # **沒有「帳戶」與「狀態」兩欄。** 清單本來就照上方選的帳戶篩，每一列的帳戶都一樣；
        # 盤點的刪除是真的移除（ADR-0015），剩下的每一筆都有效 —— 兩欄都是每列同值的雜訊。
        self.model = RowsModel(
            ["盤點日期", "實際金額", "預期金額", "未解釋差額", "備註"],
            balance_gap_values,
            amount_column=3,
        )
        self.limit = PAGE_SIZE
        self.more_button = QPushButton("載入更多")
        self.inbox = InboxSection(controller)
        self.pending_title = QLabel("補記與待確認")
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
        edit_button = QPushButton("編輯")
        delete_button = QPushButton("刪除")
        record_button = QPushButton("補記交易")
        record_button.setToolTip("切到記帳頁，帳戶先選好這一頁正在看的那一個。")
        set_button_role(create_button, "primary")
        set_button_role(delete_button, "danger")

        form = QFormLayout()
        form.addRow("帳戶", self.account)
        form.addRow("盤點日期", self.observed_at)
        form.addRow("實際金額（TWD）", self.amount)
        form.addRow("備註", self.note)
        form.addRow("", self.result)

        actions = QHBoxLayout()
        for button in (create_button, edit_button, delete_button):
            actions.addWidget(button)
        actions.addStretch()

        setup_table(
            self.table, self.model, stretch_column=4, fit_rows=RECORD_TABLE_ROWS
        )
        # 編輯／刪除是對所選盤點動作，沒選就停用。
        bind_selection(self.table, edit_button, delete_button)

        more_row = QHBoxLayout()
        more_row.addWidget(self.more_button)
        more_row.addStretch()

        records_title = QLabel("盤點紀錄")
        records_title.setObjectName("sectionTitle")
        self.pending_title.setObjectName("sectionTitle")
        gap_help = QLabel(GAP_HELP)
        gap_help.setObjectName("hintLabel")
        gap_help.setWordWrap(True)
        record_row = QHBoxLayout()
        record_row.addWidget(record_button)
        record_row.addStretch()

        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addWidget(help_text)
        # 表單另外收到 720 —— 這一頁有表單也有表格，整頁用表單寬度會塞不下那張表。
        layout.addWidget(form_panel(form))
        layout.addLayout(actions)
        layout.addWidget(self.summary)
        layout.addWidget(records_title)
        layout.addWidget(self.table)
        layout.addLayout(more_row)
        layout.addWidget(self.pending_title)
        layout.addWidget(gap_help)
        layout.addLayout(record_row)
        layout.addWidget(self.inbox)
        # 表格都是固定高度（`fit_rows`），多出來的高度留在最底下，不要平均塞進每一塊之間。
        layout.addStretch()

        self.account.currentIndexChanged.connect(self._account_changed)
        create_button.clicked.connect(self.create_snapshot)
        edit_button.clicked.connect(self.edit_selected)
        delete_button.clicked.connect(self.delete_selected)
        self.more_button.clicked.connect(self.load_more)
        record_button.clicked.connect(
            lambda: self.record_transaction_requested.emit(self._account_id() or "")
        )
        self.inbox.changed.connect(self._inbox_changed)

    def reload_accounts(self) -> None:
        fill_combo(self.account, self.controller.account_options(), "name", "account_id")
        self.refresh()

    def refresh(self) -> None:
        """重查盤點紀錄、最近一次的摘要，以及底下的待確認。

        待確認也在這裡重查：它會因為「操作設定 → 定存」產生新的草稿、或還原了一份備份
        而改變，那兩條路主視窗都會叫到這裡（`reload_accounts()`）。
        """
        self.inbox.refresh()
        account_id = self._account_id()
        if account_id is None:
            self.model.replace_rows([])
            self.more_button.setVisible(False)
            self.summary.setText("尚未建立帳戶。")
            return
        gaps = self.controller.list_balance_snapshots(account_id=account_id, limit=self.limit)
        self.model.replace_rows(gaps)
        # 回傳滿 `limit` 筆才可能還有更多。剛好整除時多按一次會什麼都沒多出來 ——
        # 那一次之後按鈕就消失，比為了一顆按鈕多查一次總筆數划算。
        self.more_button.setVisible(len(gaps) >= self.limit and self.limit < MAX_ROWS)
        latest = self.controller.latest_balance_gap(account_id)
        if latest is None:
            self.summary.setText("此帳戶尚未盤點。可先輸入實際金額，之後再慢慢補記交易。")
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

    def load_more(self) -> None:
        self.limit = min(self.limit + PAGE_SIZE, MAX_ROWS)
        self.refresh()

    def _account_changed(self) -> None:
        """換帳戶就從第一頁重新開始 —— 上一個帳戶載入到第幾頁，跟這一個沒有關係。"""
        self.limit = PAGE_SIZE
        self.refresh()

    def _inbox_changed(self) -> None:
        """確認入帳或略過之後：這一頁的差額要重算，帳本的其他地方交給主視窗。"""
        self.refresh()
        self.ledger_changed.emit()

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
        if not confirm(
            self,
            "確認刪除",
            f"確定要刪除 {display_date(str(item['observed_at']))} 那一次盤點嗎？\n\n"
            "刪掉之後就找不回來了。後面那一次盤點的未解釋差額，會改拿再前一次的盤點重算。",
        ):
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
        self.account = combo_box()
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
        form.addRow("實際金額（TWD）", self.amount)
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
