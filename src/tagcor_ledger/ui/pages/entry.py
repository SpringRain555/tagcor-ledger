"""記帳：每天最常用的那一頁。

## 這一頁的三個設計取捨

1. **金額是主角，但它排在最後面，而且只靠字重說話。** 它是唯一每次都必須手打的欄位，
   所以是粗體、`Ctrl+N` 直接聚焦到它 —— **字級與高度與其他欄位一致**。
   欄位由上到下照使用者實際填寫的順序：先決定這筆錢的身分（帳戶、哪一天、類別、項目），
   最後才打金額。日期緊跟在帳戶後面（2026-09-27 使用者指定）—— 補記過去幾天的帳時，
   「哪個帳戶、哪一天」是一起決定的，之後才一筆一筆換類別。那些欄位多半沿用上次或用預設值，一路確認下來，游標最後落在唯一要
   動手的那一格。（建立順序本來就是這個順序，所以 Qt 的預設 Tab 順序與眼睛看到的
   順序也終於一致。）

   **強調的手段與位置是綁在一起的。** 這個欄位曾經同時放大三個維度（15pt、600、
   40px 高），那是它還排在第三列、緊貼著「流向」的年代訂的 —— 在最上面當標題看剛好。
   搬到項目與備註之間之後，上下都是一般高度的欄位，同樣的對比就從「標題」變成
   「中間凸一塊」。樣式一個字都沒動，是順序讓它換了個意思。
2. **流向用三顆分段按鈕，不是下拉選單。** 下拉要「點開、找、再點」三個動作；
   三顆按鈕一下就好。選項永遠只有三個，不會長出第四個。
3. **成功與失敗共用一個訊息位置，但顏色不同。** 以前成功訊息寫進紅色的 `errorLabel`，
   每天最常做的動作回饋長得像失敗。

## 轉帳有三種對象，但資料庫只有一種轉帳

實際生活裡的「轉帳」多半不是自己兩個帳戶之間搬錢，而是**跟別人之間**。三種情形在
畫面上是三顆按鈕，存進資料庫卻是兩種不同的東西：

| 轉帳對象 | 存成 | 為什麼 |
|---|---|---|
| 我的帳戶之間 | `entry_type="transfer"`，兩筆 posting | 錢沒有離開你，只是換了地方 |
| 別人轉入 | `entry_type="income"` ＋ 類別／項目 | 錢**進入**你的總資產，那就是收入 |
| 轉出給別人 | `entry_type="expense"` ＋ 類別／項目 | 錢**離開**你的總資產，那就是支出 |

**不新增 `entry_type`。** 理由與 `state-machines.md` 寫的「利息記成收入，不是轉帳」
完全一樣：總資產有沒有變，才是收支與轉帳的分界。把對外轉帳記成 transfer 會讓總資產
憑空不變，看不出錢真的少了。完整的決定與被否決的兩個替代方案見
`docs/decisions/ADR-0010-external-transfers.md`。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import ENTRY_NAMES, minor_text, result_message
from tagcor_ledger.ui.widgets.forms import (
    add_suffix_hint,
    date_field,
    fill_combo,
    iso_from_date,
    select_data,
    show_status,
    status_label,
)
from tagcor_ledger.ui.widgets.layout import ENTRY_PAGE_MARGINS, ENTRY_WIDTH, page_layout
from tagcor_ledger.ui.widgets.table import set_button_role

ENTRY_TYPES = ("expense", "income", "transfer")

TRANSFER_SCOPES: tuple[tuple[str, str], ...] = (
    ("internal", "我的帳戶之間"),
    ("inbound", "別人轉入"),
    ("outbound", "轉出給別人"),
)
"""轉帳的三種對象。第一個是預設 —— 它是唯一真的會寫成 `transfer` 的那一種。"""

SCOPE_ENTRY_TYPES = {"internal": "transfer", "inbound": "income", "outbound": "expense"}

SCOPE_ACCOUNT_LABELS = {
    "internal": "轉出帳戶",
    "inbound": "收款帳戶",
    "outbound": "付款帳戶",
}
"""「帳戶」那一列在三種對象下各自叫什麼。同一個下拉在三種情境下問的是不同的問題，
標籤不跟著改的話，使用者得自己推論那一格現在是誰。"""

SAVED_MESSAGE_MS = 3000
"""「交易已儲存。」停留多久（毫秒）。

以前它會一直留著，直到下一次儲存或按清空。於是填第二筆的時候畫面上還寫著「交易已儲存」，
而那句話講的是**上一筆** —— 使用者分不出眼前這一筆到底存了沒。成功訊息只需要被看到一眼，
三秒夠了；**失敗訊息不會被清掉**（`submit()` 失敗時會先停掉計時器），那是要讀完的。
"""


ROW_SPACING = 16
"""欄位之間的間距。**固定值，不隨視窗高度變。**

2026-09-27 試過「高的視窗把一半多餘高度分給列距」，結果切到轉帳時多一列、間距跟著
重算變小，**每一個欄位都換了位置**——支出與收入明明欄位一樣，切來切去卻在跳。
欄位的位置要穩定，使用者才能不看就點到；下方留白是換來的代價。"""

WRAP_WIDTH = 560
"""頁面窄於這個寬度時，標籤移到欄位上方、轉帳對象的三顆按鈕改成直排。

手機寬度下「標籤在左」會讓欄位只剩兩百出頭 px，而三顆轉帳對象按鈕並排要四百多 px。"""


class EntryPage(QWidget):
    saved = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.flow_buttons = QButtonGroup(self)
        self.scope_buttons = QButtonGroup(self)
        self.scope_row = QWidget()
        self._labels: list[QLabel] = []
        self.account = QComboBox()
        self.destination = QComboBox()
        self.occurred_at = date_field()
        self.category = QComboBox()
        self.detail = QComboBox()
        self.amount = QLineEdit()
        self.description = QLineEdit()
        self.status = status_label()
        self.save_button = QPushButton("儲存交易")
        self.clear_button = QPushButton("清空")
        # 成功訊息的計時器。單發、只在 `submit()` 成功時啟動；任何會改寫訊息的動作
        # （清空、帶入模板、失敗）都先把它停掉，免得三秒後把那句新的也清掉。
        self.saved_message_timer = QTimer(self)
        self.saved_message_timer.setSingleShot(True)
        self.saved_message_timer.setInterval(SAVED_MESSAGE_MS)
        self.saved_message_timer.timeout.connect(lambda: show_status(self.status, ""))
        self._build()
        self.reload_options()
        self.apply_defaults()

    def _build(self) -> None:
        title = QLabel("記帳")
        title.setObjectName("pageTitle")
        set_button_role(self.save_button, "primary")

        flow_row = QHBoxLayout()
        flow_row.setSpacing(8)
        for index, key in enumerate(ENTRY_TYPES):
            button = QPushButton(ENTRY_NAMES[key])
            button.setObjectName("segmentButton")
            button.setCheckable(True)
            button.setProperty("entry_type", key)
            self.flow_buttons.addButton(button, index)
            flow_row.addWidget(button)
        flow_row.addStretch()
        self.flow_buttons.setExclusive(True)
        self.flow_buttons.button(0).setChecked(True)

        # 轉帳對象也用分段按鈕，跟流向同一套視覺 —— 它們是同一個問題的兩層，
        # 一個用按鈕一個用下拉會讓第二層看起來像次要設定。
        scope_layout = QHBoxLayout(self.scope_row)
        self._scope_layout = scope_layout
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(8)
        for index, (key, label) in enumerate(TRANSFER_SCOPES):
            button = QPushButton(label)
            button.setObjectName("segmentButton")
            button.setCheckable(True)
            button.setProperty("transfer_scope", key)
            self.scope_buttons.addButton(button, index)
            scope_layout.addWidget(button)
        scope_layout.addStretch()
        self.scope_buttons.setExclusive(True)
        self.scope_buttons.button(0).setChecked(True)

        self.amount.setObjectName("amountInput")
        self.amount.setPlaceholderText("0")
        # 幣別放在框內右緣當背景提示，標籤就只要兩個字 —— 見 `add_suffix_hint()`。
        add_suffix_hint(self.amount, "TWD")
        self.description.setPlaceholderText("可留空")

        self.form = QFormLayout()
        form = self.form
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(ROW_SPACING)
        # **標籤靠右，貼著自己的欄位**（`_align_labels()`）。靠左時標籤欄的寬度由最長的
        # 那個標籤決定，「流向」「帳戶」這些兩個字的標籤離欄位一百多 px（2026-09-27 使用者回報）。
        # **順序照使用者實際填寫的順序**，見模組說明的取捨 1。只在轉帳時出現的兩列
        # 各自貼著自己的第一層：轉帳對象是流向的第二層，轉入帳戶是「帳戶」的另一半。
        form.addRow("流向", flow_row)
        form.addRow("轉帳對象", self.scope_row)
        form.addRow("帳戶", self.account)
        form.addRow("轉入帳戶", self.destination)
        form.addRow("日期", self.occurred_at)
        form.addRow("類別", self.category)
        form.addRow("項目", self.detail)
        form.addRow("金額", self.amount)
        form.addRow("備註", self.description)
        # 「清空」跟 Esc 是同一件事（`clear_form()`），只是做成看得到的按鈕。
        # 它刻意**不**清流向／帳戶／類別 —— 連記幾筆同類的帳時那幾格本來就該留著。
        # 儲存成功之後的自動清除範圍再小一格：連日期也留著（`_clear_after_save()`）。
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.save_button)
        actions.addWidget(self.clear_button)
        # **訊息放在「清空」右邊，不是獨立一列。** 獨立一列時沒有訊息也佔著一列加兩段
        # 間距，備註與按鈕之間空一大塊；出現訊息時它長高，按鈕還會被往下推。
        # 放在按鈕旁邊、吃掉剩下的寬度，長訊息就在那裡換行，上面的欄位一格都不會動。
        actions.addSpacing(8)
        actions.addWidget(self.status, 1)
        form.addRow("", actions)
        self._pin_label_column()

        layout = page_layout(self, width=ENTRY_WIDTH, margins=ENTRY_PAGE_MARGINS)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addStretch()

        self.flow_buttons.idToggled.connect(lambda *_: self._sync_flow())
        self.scope_buttons.idToggled.connect(lambda *_: self._sync_flow())
        self.category.currentIndexChanged.connect(self._reload_details)
        # 改了來源帳戶就重新閃開一次，否則使用者只要把「帳戶」切到跟「轉入帳戶」
        # 同一個，就又回到那個必定失敗的狀態。
        self.account.currentIndexChanged.connect(self._avoid_same_account)
        self.save_button.clicked.connect(self.submit)
        self.clear_button.clicked.connect(self.clear_form)
        self.amount.returnPressed.connect(self.submit)
        self.description.returnPressed.connect(self.submit)
        self._sync_flow()

    # --- 版面 -----------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_to_size()

    def is_wrapped(self) -> bool:
        """標籤是不是在欄位上方（窄版面）。給測試用。"""
        return self.form.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapAllRows

    def _pin_label_column(self) -> None:
        """標籤欄固定成「任何流向下最寬的那個標籤」的寬度。

        標籤欄的寬度是**看得到的**標籤裡最寬的那個：支出時全是兩個字，切到轉帳就多了
        「轉帳對象」「轉出帳戶」四個字 —— 標籤欄一變寬，每個欄位的左緣都往右跳。
        先把每一個標籤撐到同一個寬度，切流向時欄位就一格都不橫移。
        """
        labels: list[QLabel] = []
        for row in range(self.form.rowCount()):
            item = self.form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            label = item.widget() if item is not None else None
            if isinstance(label, QLabel):
                labels.append(label)
        if not labels:
            return
        texts = [label.text() for label in labels] + list(SCOPE_ACCOUNT_LABELS.values())
        metrics = labels[0].fontMetrics()
        width = max(metrics.horizontalAdvance(text) for text in texts)
        self._labels = labels
        for label in labels:
            label.setMinimumWidth(width)
        # 標籤撐到同寬之後，`setLabelAlignment` 只管得到「整個標籤放在欄裡哪裡」，
        # 管不到字在標籤裡靠哪邊 —— 字的對齊要設在每一個標籤自己身上。
        self._align_labels(wrapped=False)

    def _align_labels(self, *, wrapped: bool) -> None:
        """標籤在左時靠右貼著欄位；標籤在上方時靠左，跟欄位的左緣對齊。"""
        horizontal = Qt.AlignmentFlag.AlignLeft if wrapped else Qt.AlignmentFlag.AlignRight
        self.form.setLabelAlignment(horizontal | Qt.AlignmentFlag.AlignVCenter)
        # 標籤在左時跟欄位一樣高，`AlignVCenter` 才真的對到欄位中線 —— QFormLayout 把
        # 標籤放在列的頂端，標籤只有字高時字會比欄位裡的字高出好幾 px。
        row_height = 0 if wrapped else self.account.sizeHint().height()
        for label in self._labels:
            label.setAlignment(horizontal | Qt.AlignmentFlag.AlignVCenter)
            label.setMinimumHeight(row_height)

    def _fit_to_size(self) -> None:
        """窄的時候標籤移到上方、轉帳對象的按鈕直排。"""
        wrap = self.width() < WRAP_WIDTH
        if wrap != self.is_wrapped():
            self.form.setRowWrapPolicy(
                QFormLayout.RowWrapPolicy.WrapAllRows
                if wrap
                else QFormLayout.RowWrapPolicy.DontWrapRows
            )
            # 標籤在上方時靠左 —— 靠右會讓它飄在欄位右上角，跟欄位對不起來。
            self._align_labels(wrapped=wrap)
            self._scope_layout.setDirection(
                QBoxLayout.Direction.TopToBottom if wrap else QBoxLayout.Direction.LeftToRight
            )

    # --- 流向 -----------------------------------------------------------------

    def current_entry_type(self) -> str:
        button = self.flow_buttons.checkedButton()
        return str(button.property("entry_type")) if button is not None else "expense"

    def select_entry_type(self, entry_type: object) -> None:
        for button in self.flow_buttons.buttons():
            if button.property("entry_type") == entry_type:
                button.setChecked(True)
                return

    def current_transfer_scope(self) -> str:
        button = self.scope_buttons.checkedButton()
        return str(button.property("transfer_scope")) if button is not None else "internal"

    def select_transfer_scope(self, scope: object) -> None:
        for button in self.scope_buttons.buttons():
            if button.property("transfer_scope") == scope:
                button.setChecked(True)
                return

    def effective_entry_type(self) -> str:
        """真正會寫進資料庫的 `entry_type`。

        非轉帳時就是流向本身；轉帳時看對象 —— 只有「我的帳戶之間」才是 `transfer`，
        另外兩種是收入與支出（見模組說明）。
        """
        if self.current_entry_type() != "transfer":
            return self.current_entry_type()
        return SCOPE_ENTRY_TYPES[self.current_transfer_scope()]

    # --- 選項 -----------------------------------------------------------------

    def reload_options(self) -> None:
        # 帳戶只查一次填兩個下拉。以前是連呼叫兩次 `account_options()`，
        # 而那個方法會去算每個帳戶的餘額 —— 等於整段成本白付兩遍。
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.destination, accounts, "name", "account_id")
        fill_combo(self.category, self.controller.category_options(), "name", "category_id")
        self._reload_details()
        self._avoid_same_account()

    def apply_defaults(self) -> None:
        settings = self.controller.get_settings()
        select_data(self.account, settings.default_account_id)
        self.select_entry_type(settings.default_entry_type)
        self._avoid_same_account()
        self._sync_flow()

    def _avoid_same_account(self) -> None:
        """轉入帳戶不要停在跟來源帳戶同一個。

        兩個下拉填的是**同一份清單**，預設也都停在第 0 項 —— 於是剛開程式選「轉帳」
        直接按儲存必定撞 `TRANSFER_SAME_ACCOUNT`。那是一個「照著做就一定失敗」的
        預設值，而使用者要先讀完錯誤訊息才知道要去改哪一個欄位。

        只有一個帳戶時什麼都不做 —— 那時候本來就沒有合法的轉帳可選，讓 store 的
        錯誤訊息把話講完整比在這裡猜好。
        """
        if self.destination.count() < 2:
            return
        source = self.account.currentData()
        if self.destination.currentData() != source:
            return
        for index in range(self.destination.count()):
            if self.destination.itemData(index) != source:
                self.destination.setCurrentIndex(index)
                return

    def apply_draft(self, draft: dict[str, Any], *, use_current_time: bool = True) -> None:
        self.saved_message_timer.stop()
        self.select_entry_type(draft.get("entry_type"))
        select_data(self.account, draft.get("account_id"))
        select_data(self.destination, draft.get("destination_account_id"))
        # **交易與模板的 `category_id` 不是指同一層。** 交易的 dict 裡 `category_id` 是
        # 類別（第一層）、`subcategory_id` 才是項目；模板只有一個 `category_id`，存的就是
        # 項目。而 `_select_category()` 要的是**項目**的 id。餵父層進去比對必然落空，
        # 結果是類別對了、項目卻被靜靜換成該類別的第一個 —— 以前交易紀錄的
        # 「複製到記帳」就是這樣帶錯項目的。那條路 2026-09-20 改成「建立模板」、走
        # `TemplateDialog`，同一個坑在那邊有同一道防護；這裡留著 `or`，是因為兩種形狀
        # 的 dict 都可能再送進來。
        self._select_category(draft.get("subcategory_id") or draft.get("category_id"))
        amount_minor = draft.get("amount_minor")
        self.amount.setText(minor_text(amount_minor) if amount_minor is not None else "")
        self.description.setText(str(draft.get("description", "")))
        if use_current_time:
            self.occurred_at.setDate(QDate.currentDate())
        show_status(self.status, "內容已帶入，確認後再儲存。")
        self.amount.setFocus()

    def clear_form(self) -> None:
        """「清空」與 Esc：清金額、備註，**日期回今天**。

        儲存成功後**不**走這裡 —— 那條路保留日期，見 `_clear_after_save()`。
        """
        self.occurred_at.setDate(QDate.currentDate())
        self._clear_after_save()
        show_status(self.status, "")

    def _clear_after_save(self) -> None:
        """儲存成功後清掉的範圍：金額與備註。**日期留著。**

        補記前幾天的帳時，同一天常常連記好幾筆；以前每存一筆日期就跳回今天，
        下一筆忘了改就記錯天，而且畫面上完全看不出來（2026-09-27 使用者回報）。
        要回今天就按「清空」。
        """
        self.saved_message_timer.stop()
        self.amount.clear()
        self.description.clear()
        self.amount.setFocus()

    def submit(self) -> None:
        # **送出去的是 `effective_entry_type()`，不是畫面上那顆按鈕。**
        # 「轉帳 ＋ 別人轉入」在資料庫裡就是一筆收入 —— 見模組說明與 ADR-0010。
        entry_type = self.effective_entry_type()
        result = self.controller.submit(
            occurred_at=iso_from_date(self.occurred_at),
            entry_type=entry_type,
            amount=self.amount.text().strip(),
            account_id=str(self.account.currentData()),
            destination_account_id=(
                str(self.destination.currentData()) if entry_type == "transfer" else None
            ),
            category_id=(
                str(self.detail.currentData()) if entry_type != "transfer" else None
            ),
            description=self.description.text().strip(),
        )
        if result.success:
            self._clear_after_save()
            show_status(self.status, "交易已儲存。", ok=True)
            self.saved_message_timer.start()
            self.saved.emit()
            return
        # 失敗訊息要留到被讀完 —— 上一筆成功的計時器若還在跑，三秒後會把它清掉。
        self.saved_message_timer.stop()
        show_status(self.status, result_message(result), ok=False)

    def _sync_flow(self) -> None:
        """用不到的整列收起來，並讓「帳戶」那一列說出它現在問的是什麼。

        必須用 `setRowVisible` 而不是對欄位 `setVisible`：QFormLayout 的標籤是獨立的
        widget，只藏欄位會留下一個沒有內容的標籤浮在畫面上。

        | 流向／對象 | 轉帳對象列 | 轉入帳戶 | 類別／項目 | 帳戶的標籤 |
        |---|---|---|---|---|
        | 支出／收入 | 收起 | 收起 | 顯示 | 帳戶 |
        | 轉帳・我的帳戶之間 | 顯示 | 顯示 | 收起 | 轉出帳戶 |
        | 轉帳・別人轉入 | 顯示 | 收起 | **顯示** | 收款帳戶 |
        | 轉帳・轉出給別人 | 顯示 | 收起 | **顯示** | 付款帳戶 |

        對外轉帳要類別／項目，因為它存成收入或支出 —— 而收支一定要有類別。
        """
        transfer = self.current_entry_type() == "transfer"
        scope = self.current_transfer_scope()
        internal = transfer and scope == "internal"

        self.form.setRowVisible(self.scope_row, transfer)
        self.form.setRowVisible(self.destination, internal)
        self.form.setRowVisible(self.category, not internal)
        self.form.setRowVisible(self.detail, not internal)

        label = self.form.labelForField(self.account)
        if isinstance(label, QLabel):
            label.setText(SCOPE_ACCOUNT_LABELS[scope] if transfer else "帳戶")

    def _reload_details(self) -> None:
        parent_id = self.category.currentData()
        items = (
            self.controller.category_options(str(parent_id))
            if isinstance(parent_id, str)
            else []
        )
        fill_combo(self.detail, items, "name", "category_id")

    def _select_category(self, category_id: object) -> None:
        """把「項目」選起來，順便把它的類別也選對。**收的是項目（第二層）的 id。**

        找不到對應項目時退回「把它當成類別來選」—— 那是給只有類別、沒有項目的
        資料用的，不是正常路徑。
        """
        if not isinstance(category_id, str):
            return
        for parent_index in range(self.category.count()):
            parent_id = str(self.category.itemData(parent_index))
            children = self.controller.category_options(parent_id)
            if any(str(item["category_id"]) == category_id for item in children):
                self.category.setCurrentIndex(parent_index)
                self._reload_details()
                select_data(self.detail, category_id)
                return
        select_data(self.category, category_id)
