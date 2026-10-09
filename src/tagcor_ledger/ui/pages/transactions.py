"""交易紀錄：組合篩選、雙向 keyset 分頁、編輯與刪除。

轉帳沒有「編輯」—— 編輯轉帳實際上是建一筆新的、刪除原本那筆（替換轉帳），所以同一顆
按鈕在轉帳與非轉帳時做的是兩件不同的事，對話框標題也不一樣。

**「刪除」是 `void`，不是真的刪掉。** 那一列的狀態變成 `voided`、不再計入，但紀錄留著，
篩選「已刪除」看得到、不可復原（`state-machines.md` §1）。2026-09-20 之前叫「作廢」；
改字的理由與兩個「刪除」怎麼區分見 `glossary.md`。

**「建立模板」不在這一頁做事。** 它只把所選交易的內容送出去（`template_requested`），
由 `main_window` 帶到「操作設定 → 模板」開一張已經填好的新增視窗，使用者自己取名、自己按儲存。
2026-09-20 之前這顆按鈕叫「複製到記帳」—— 把同一筆內容帶回記帳頁再存一次；
那件事模板的「填入記帳頁」本來就會做，而且做得更好（模板記得住、下次不用再找那一筆）。
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QDate, QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import result_message, transaction_values
from tagcor_ledger.ui.widgets.confirm import confirm
from tagcor_ledger.ui.widgets.forms import (
    combo_box,
    date_field,
    fill_combo,
    iso_from_date,
    select_data,
)
from tagcor_ledger.ui.widgets.layout import TABLE_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import (
    RowsModel,
    bind_selection,
    set_button_role,
    setup_table,
)


class TransactionsPage(QWidget):
    template_requested = Signal(dict)
    """所選交易的 dict。接收端拿它去開一張預填好的「新增模板」視窗（見模組說明）。"""

    changed = Signal()
    """這一頁改動了帳務。**餘額盤點的未解釋差額因此要重算。**

    刪除與編輯都會改變 posting，而未解釋差額就是「盤點金額 － 期間 posting 加總」。
    以前這兩個動作只重刷自己那張表，於是使用者刪掉一筆錯帳之後切到餘額盤點，
    差額還是舊的數字 —— 而那個數字正是那一頁存在的唯一理由。
    """

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.table = QTableView()
        self.model = RowsModel(
            # 「流向」不是「類型」—— 用詞表明文（記帳頁、篩選都叫流向，這個表頭以前是唯一的例外）。
            ["日期", "流向", "帳戶", "類別／項目", "金額（TWD）", "備註", "狀態"],
            transaction_values,
            amount_column=4,
        )
        self.search = QLineEdit()
        self.date_enabled = QCheckBox("日期")
        self.date_from = date_field(QDate.currentDate().addMonths(-1))
        self.date_to = date_field(QDate.currentDate())
        self.account = combo_box()
        self.category = combo_box()
        self.status = combo_box()
        self.previous_button = QPushButton("上一頁")
        self.next_button = QPushButton("下一頁")
        self.cursors: list[dict[str, str] | None] = [None]
        self.page_index = 0
        self.next_cursor: dict[str, str] | None = None
        self._build()
        self.reload_filters()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("交易紀錄")
        title.setObjectName("pageTitle")
        self.search.setPlaceholderText("搜尋備註、類別、項目或帳戶")
        # 格式、日曆彈窗與誤觸防護都由 `date_field()` 統一處理，這裡只管「一開始停用」。
        for date_widget in (self.date_from, self.date_to):
            date_widget.setEnabled(False)
        self.date_enabled.toggled.connect(self.date_from.setEnabled)
        self.date_enabled.toggled.connect(self.date_to.setEnabled)
        self.status.addItem("有效", "active")
        self.status.addItem("已刪除", "voided")
        self.status.addItem("全部", "all")
        apply_button = QPushButton("套用篩選")
        clear_button = QPushButton("清除篩選")
        set_button_role(apply_button, "primary")

        # 篩選列拆成兩行並加上標籤。原本九個元件擠同一行，其中帳戶／類別／狀態
        # 三個下拉**完全沒有標籤**，要靠猜哪個是哪個。
        top_row = QHBoxLayout()
        top_row.addWidget(self.search, 1)
        top_row.addWidget(self.date_enabled)
        top_row.addWidget(self.date_from)
        top_row.addWidget(QLabel("到"))
        top_row.addWidget(self.date_to)

        bottom_row = QHBoxLayout()
        for label, widget in (
            ("帳戶", self.account),
            ("類別", self.category),
            ("狀態", self.status),
        ):
            bottom_row.addWidget(QLabel(label))
            bottom_row.addWidget(widget)
            bottom_row.addSpacing(12)
        bottom_row.addStretch()
        bottom_row.addWidget(apply_button)
        bottom_row.addWidget(clear_button)

        setup_table(self.table, self.model, stretch_column=5)
        # 「編輯」對轉帳其實是「替換」，那個差別在按下去之後的對話框標題與儲存鈕上講
        # （「替換轉帳」／「建立新轉帳並刪除原交易」），按鈕本身不再寫「編輯／替換」。
        edit_button = QPushButton("編輯")
        delete_button = QPushButton("刪除")
        template_button = QPushButton("建立模板")
        set_button_role(edit_button, "primary")
        set_button_role(delete_button, "danger")
        bind_selection(self.table, edit_button, template_button)
        # 「刪除」只對有效的交易有意義；「編輯」不綁 —— 對已刪除的交易按下去，
        # store 會回 TRANSACTION_VOIDED 的中文，那是有用的回饋。從已刪除的交易建模板也合理。
        bind_selection(
            self.table,
            delete_button,
            enabled_when=lambda item: item["status"] == "active",
        )
        actions = QHBoxLayout()
        for action_button in (edit_button, delete_button, template_button):
            actions.addWidget(action_button)
        actions.addStretch()
        actions.addWidget(self.previous_button)
        actions.addWidget(self.next_button)
        layout = page_layout(self, width=TABLE_WIDTH)
        layout.addWidget(title)
        layout.addLayout(top_row)
        layout.addLayout(bottom_row)
        layout.addWidget(self.table)
        layout.addLayout(actions)
        apply_button.clicked.connect(self.first_page)
        clear_button.clicked.connect(self.clear_filters)
        self.search.returnPressed.connect(self.first_page)
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        edit_button.clicked.connect(self.edit_selected)
        delete_button.clicked.connect(self.delete_selected)
        template_button.clicked.connect(self.create_template_from_selected)

    def reload_filters(self) -> None:
        fill_combo(
            self.account,
            self.controller.account_options(),
            "name",
            "account_id",
            first=("全部帳戶", None),
        )
        fill_combo(
            self.category,
            self.controller.category_options(),
            "name",
            "category_id",
            first=("全部類別", None),
        )

    def first_page(self) -> None:
        self.cursors = [None]
        self.page_index = 0
        self.refresh()

    def clear_filters(self) -> None:
        self.search.clear()
        self.date_enabled.setChecked(False)
        self.account.setCurrentIndex(0)
        self.category.setCurrentIndex(0)
        self.status.setCurrentIndex(0)
        self.first_page()

    def next_page(self) -> None:
        if self.next_cursor is None:
            return
        self.cursors = self.cursors[: self.page_index + 1]
        self.cursors.append(self.next_cursor)
        self.page_index += 1
        self.refresh()

    def previous_page(self) -> None:
        if self.page_index == 0:
            return
        self.page_index -= 1
        self.refresh()

    def refresh(self) -> None:
        result = self.controller.list_transactions(
            search=self.search.text().strip(),
            date_from=(
                self.date_from.date().toString("yyyy-MM-dd") + "T00:00:00+08:00"
                if self.date_enabled.isChecked()
                else None
            ),
            date_to=(
                self.date_to.date().toString("yyyy-MM-dd") + "T23:59:59+08:00"
                if self.date_enabled.isChecked()
                else None
            ),
            account_id=cast(str | None, self.account.currentData()),
            category_id=cast(str | None, self.category.currentData()),
            status=str(self.status.currentData()),
            cursor=self.cursors[self.page_index],
        )
        if not result.success:
            QMessageBox.warning(self, "交易無法載入", result_message(result))
            return
        self.model.replace_rows(list(result.details.get("transactions", [])))
        next_cursor = result.details.get("next_cursor")
        self.next_cursor = dict(next_cursor) if isinstance(next_cursor, dict) else None
        self.previous_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(self.next_cursor is not None)

    def create_template_from_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is not None:
            self.template_requested.emit(item)

    def edit_selected(self) -> None:
        item = self.model.selected_item(self.table)
        if item is None:
            return
        dialog = TransactionEditDialog(self.controller, item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.first_page()
            self.changed.emit()

    def delete_selected(self) -> None:
        # 按鈕對已刪除的列本來就停用（`enabled_when`），這一行只是防程式直接呼叫。
        item = self.model.selected_item(self.table)
        if item is None or item["status"] != "active":
            return
        if not confirm(
            self,
            "確認刪除",
            "確定要刪除所選交易嗎？\n\n紀錄會保留在狀態「已刪除」裡，但不能再改回有效。",
        ):
            return
        result = self.controller.void_transaction(str(item["transaction_id"]))
        if result.success:
            self.first_page()
            self.changed.emit()
        else:
            QMessageBox.warning(self, "無法刪除", result_message(result))


class TransactionEditDialog(QDialog):
    def __init__(
        self,
        controller: LedgerController,
        transaction: dict[str, Any],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.transaction = transaction
        self.account = combo_box()
        self.destination = combo_box()
        self.category = combo_box()
        self.detail = combo_box()
        self.occurred_at = date_field()
        self.amount = QLineEdit(str(transaction["amount"]))
        self.description = QLineEdit(str(transaction["description"]))
        self.error = QLabel()
        self._build()
        self._load()

    def _build(self) -> None:
        transfer = self.transaction["entry_type"] == "transfer"
        self.setWindowTitle("替換轉帳" if transfer else "編輯交易")
        self.occurred_at.setDate(
            QDateTime.fromString(
                str(self.transaction["occurred_at"]), Qt.DateFormat.ISODate
            ).date()
        )
        self.error.setObjectName("errorLabel")
        form = QFormLayout()
        form.addRow("帳戶", self.account)
        if transfer:
            form.addRow("轉入帳戶", self.destination)
        else:
            form.addRow("類別", self.category)
            form.addRow("項目", self.detail)
        form.addRow("日期", self.occurred_at)
        form.addRow("金額（TWD）", self.amount)
        form.addRow("備註", self.description)
        form.addRow("", self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "建立新轉帳並刪除原交易" if transfer else "儲存"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.category.currentIndexChanged.connect(self._load_details)

    def _load(self) -> None:
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.destination, accounts, "name", "account_id")
        select_data(self.account, self.transaction["account_id"])
        select_data(self.destination, self.transaction["destination_account_id"])
        if self.transaction["entry_type"] != "transfer":
            fill_combo(
                self.category,
                self.controller.category_options(),
                "name",
                "category_id",
            )
            select_data(self.category, self.transaction["category_id"])
            self._load_details()
            select_data(self.detail, self.transaction["subcategory_id"])

    def _load_details(self) -> None:
        parent_id = self.category.currentData()
        children = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        fill_combo(self.detail, children, "name", "category_id")

    def save(self) -> None:
        common = {
            # 編輯時沿用原本的時分秒：只改個備註不該讓它跳到當天最後一筆。
            "occurred_at": iso_from_date(
                self.occurred_at, keep_time_from=str(self.transaction["occurred_at"])
            ),
            "amount": self.amount.text().strip(),
            "description": self.description.text().strip(),
        }
        if self.transaction["entry_type"] == "transfer":
            result = self.controller.replace_transfer(
                original_transaction_id=str(self.transaction["transaction_id"]),
                source_account_id=str(self.account.currentData()),
                destination_account_id=str(self.destination.currentData()),
                **common,
            )
        else:
            result = self.controller.update_transaction(
                transaction_id=str(self.transaction["transaction_id"]),
                expected_revision=int(self.transaction["revision"]),
                account_id=str(self.account.currentData()),
                category_id=str(self.detail.currentData()),
                **common,
            )
        if result.success:
            self.accept()
        else:
            self.error.setText(result_message(result))
