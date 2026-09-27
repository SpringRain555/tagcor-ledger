"""定存的三張對話框：合約、一期、中途解約。

**從 `ui/pages/deposits.py` 搬出來**（v0.24.0）。那個檔案原本裝著「一個分頁」加
「兩張對話框」，加上結束合約與中途解約之後會超過 700 行的煙霧偵測器 —— 而它超過
的原因正是那條規則想抓的：一個檔案裝了兩件事。`ui/widgets/template_dialog.py`
是同樣的形狀。

## 這裡最值得讀的一段

`DepositContractDialog._sync_resolved_term()`：使用者手上的存單印的是**最初**那一期
（例如 112/11/15 存入、113/11/15 到期），而勾了「無限次數自動轉期續存」的話，郵局
早就自動續存過好幾輪 —— 2026-08-23 當下存續中的是 114/11/15 那一期，第 3 期。

所以這張對話框問的是**存單上那一天**（一個使用者一定知道的事實），並且當場說出
會建立哪一期。v0.24.0 的第一版問的是「起存日」＝目前那一期的起存日，於是那個欄位的
正確值**不是使用者手上那張紙印的數字**，旁邊還要一段警告加一顆改日期的按鈕才問得
出來。那是設計沒對齊，不是使用者不會填。
"""

from __future__ import annotations

from decimal import InvalidOperation
from typing import Any

from PySide6.QtCore import QDate
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.domain.dates import add_months
from tagcor_ledger.domain.deposits import (
    INTEREST_METHOD_NAMES,
    MATURITY_ACTION_NAMES,
    RATE_TYPE_NAMES,
    InterestMethod,
    MaturityAction,
    RateType,
    current_term,
    rate_to_ppm,
)
from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.infrastructure.clock import today_taipei
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import display_date, minor_text, rate_input_text, result_message
from tagcor_ledger.ui.widgets.forms import date_field, fill_combo, select_data
from tagcor_ledger.ui.widgets.layout import FORM_WIDTH
from tagcor_ledger.ui.widgets.simple_form import TextField, ask_form

MAX_TERM_MONTHS = 600
"""期長上限（月）＝ 50 年。比郵局最長的商品還寬，純粹是防手滑。"""


class DepositContractDialog(QDialog):
    """新增與修改共用。修改時**計息方式與期長是唯讀的** —— 它們決定了已產生事件的形狀。"""

    def __init__(
        self,
        controller: LedgerController,
        parent: QWidget,
        *,
        current: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.current = current
        self.values: dict[str, Any] = {}
        self.name = QLineEdit("郵局定存")
        self.account = QComboBox()
        self.new_account_button = QPushButton("新增帳戶…")
        self.interest_destination = QComboBox()
        self.interest_method = QComboBox()
        self.maturity_action = QComboBox()
        self.rate_type = QComboBox()
        self.term_months = QSpinBox()
        self.opened_on = date_field()
        self.principal = QLineEdit()
        self.monthly_deposit = QLineEdit()
        self.annual_rate = QLineEdit()
        self.term_hint = QLabel()
        self.resolved_note = QLabel()
        self.error = QLabel()
        self._build()
        self._load()

    def _build(self) -> None:
        editing = self.current is not None
        self.setWindowTitle("修改定存合約" if editing else "新增定存合約")
        for method in InterestMethod:
            self.interest_method.addItem(INTEREST_METHOD_NAMES[method], str(method))
        for action in MaturityAction:
            self.maturity_action.addItem(MATURITY_ACTION_NAMES[action], str(action))
        for kind in RateType:
            self.rate_type.addItem(RATE_TYPE_NAMES[kind], str(kind))
        self.term_months.setRange(1, MAX_TERM_MONTHS)
        self.term_months.setValue(12)
        self.principal.setPlaceholderText("例如：100000")
        self.monthly_deposit.setPlaceholderText("只有零存整付需要")
        self.annual_rate.setPlaceholderText("例如：1.6；不確定就留空，到期照存摺填")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)
        for label in (self.term_hint, self.resolved_note):
            label.setObjectName("hintLabel")
            label.setWordWrap(True)
            label.setVisible(False)
            # **會換行的 QLabel 一定要給寬度上限。** `setWordWrap(True)` 之後
            # `sizeHint()` 走的是「大致方形」的啟發式，於是一段四行的說明會把整個
            # 對話框撐到 1,157 px 寬（2026-08-23 實機截圖）—— 而它是一張表單，
            # 720 px 就是它該有的寬度。同一個坑 v0.22.0 的圓環圖例踩過，見 lessons。
            label.setMaximumWidth(FORM_WIDTH)

        account_row = QWidget()
        account_layout = QHBoxLayout(account_row)
        account_layout.setContentsMargins(0, 0, 0, 0)
        account_layout.addWidget(self.account, 1)
        account_layout.addWidget(self.new_account_button)

        self.form = QFormLayout()
        self.form.addRow("名稱", self.name)
        self.form.addRow("定存帳戶", account_row)
        self.form.addRow("計息方式", self.interest_method)
        self.form.addRow("到期及轉存方式", self.maturity_action)
        self.form.addRow("利息轉入帳戶", self.interest_destination)
        self.form.addRow("利率類型", self.rate_type)
        self.form.addRow("期長（月）", self.term_months)
        # **「首次起存日」不是「起存日」。** 問的是存單上首次存入那一天，也就是
        # 使用者一定知道的那個數字；該建立哪一期由 `current_term()` 算出來，
        # 底下那一行說明結果。見 ADR-0012 的「第二次修正」。
        self.form.addRow("首次起存日", self.opened_on)
        self.form.addRow("", self.resolved_note)
        self.form.addRow("本金（TWD）", self.principal)
        self.form.addRow("每月存入（TWD）", self.monthly_deposit)
        self.form.addRow("年利率（%）", self.annual_rate)
        self.form.addRow("", self.term_hint)
        self.form.addRow("", self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "儲存" if editing else "建立"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(buttons)

        self.new_account_button.clicked.connect(self.add_account)
        self.interest_method.currentIndexChanged.connect(self._sync_fields)
        self.maturity_action.currentIndexChanged.connect(self._sync_fields)
        self.rate_type.currentIndexChanged.connect(self._sync_fields)
        self.opened_on.dateChanged.connect(self._sync_resolved_term)
        self.term_months.valueChanged.connect(self._sync_resolved_term)

        if editing:
            # 修改時只開放名稱、到期及轉存方式、利息轉入帳戶。其餘欄位改了會讓已產生的
            # 期與事件對不上，要換就結束合約、開新的。
            for widget in (
                self.account,
                self.new_account_button,
                self.interest_method,
                self.rate_type,
                self.term_months,
            ):
                widget.setEnabled(False)
            # **本金整列收起來，首次起存日改成唯讀。** 兩者處置不同，因為它們的
            # 歸屬不同：
            #
            # - 本金是**期**的欄位，修改合約時沒有值可以回填 —— 停用之後畫面上顯示的
            #   是建立用的預設值（空白），而一個灰掉但看起來像事實的欄位比沒有那一列
            #   更糟。續存過的合約更沒有單一答案：每一期的本金與利率都不同。
            # - 首次起存日現在是**合約**自己的欄位，回填得出來，而它正是使用者對得回
            #   存單的那個數字 —— 該給他看。但改它會讓期序與實際滾過的輪數對不上，
            #   所以只給看不給改。
            self.opened_on.setEnabled(False)
            # 用不同的迴圈變數名：上面那個 `widget` 綁的是另一組型別（輸入元件），
            # 這裡是 QLineEdit 與 QLabel，重用同一個名字會讓兩邊的型別互相衝突。
            for row_widget in (self.principal, self.resolved_note):
                self.form.setRowVisible(row_widget, False)
            self.term_hint.setText(
                "本金與年利率屬於「期」而不是合約，要改請關掉這個視窗，"
                "在下面的「每一期」選一列按「修改所選期」。\n"
                "首次起存日不能改 —— 它決定了目前是第幾期。"
            )
            self.term_hint.setVisible(True)

    def _load(self) -> None:
        self._reload_accounts()
        if self.current is None:
            self._sync_fields()
            self._sync_resolved_term()
            return
        self.name.setText(str(self.current["name"]))
        select_data(self.account, self.current["account_id"])
        select_data(self.interest_method, self.current["interest_method"])
        select_data(self.maturity_action, self.current["maturity_action"])
        select_data(self.rate_type, self.current.get("rate_type", "fixed"))
        select_data(
            self.interest_destination, self.current.get("interest_destination_account_id")
        )
        self.term_months.setValue(int(self.current["term_months"]))
        opened = str(self.current.get("opened_on") or "")
        if opened:
            self.opened_on.setDate(QDate.fromString(opened, "yyyy-MM-dd"))
        self._sync_fields()

    def _reload_accounts(self) -> None:
        accounts = self.controller.account_options()
        fill_combo(self.account, accounts, "name", "account_id")
        fill_combo(self.interest_destination, accounts, "name", "account_id")

    def add_account(self) -> None:
        """在這個對話框裡直接開一個定存帳戶，省得中途跳去「帳戶」分頁再回來。

        **打到已經存在的名字不是錯誤，是「你要的就是那一個」。** 預設值是「郵局定存」，
        而那正是最可能已經開過的名字 —— 第二次按下去必然撞名。舊版在這裡丟一個
        警告框（還附著 SQLite 原文），使用者只能自己去猜要改什麼。現在直接把那個帳戶
        選起來，因為那就是他按這顆按鈕想達成的事。
        """
        values = ask_form(
            self,
            "新增帳戶",
            [
                TextField("name", "帳戶名稱", default="郵局定存"),
                TextField("balance", "期初餘額（TWD）", default="0"),
            ],
        )
        if values is None:
            return
        cleaned = str(values["name"]).strip()
        if not cleaned:
            return

        if self._select_account_named(cleaned):
            QMessageBox.information(
                self,
                "已經有這個帳戶",
                f"「{cleaned}」已經在清單裡了，已經幫你選起來。",
            )
            return

        result = self.controller.create_account(cleaned, str(values["balance"]).strip() or "0")
        if not result.success:
            QMessageBox.warning(self, "無法新增帳戶", result_message(result))
            return
        self._reload_accounts()
        self._select_account_named(cleaned)

    def _select_account_named(self, name: str) -> bool:
        """名稱對得上就把它選起來，回傳有沒有找到。

        比對用 `casefold()` —— `accounts.name` 是 `COLLATE NOCASE`，
        資料庫眼中「post」與「POST」是同一個名字，畫面上的判斷不能比它寬鬆。
        """
        for index in range(self.account.count()):
            if self.account.itemText(index).casefold() == name.casefold():
                self.account.setCurrentIndex(index)
                return True
        return False

    def _sync_fields(self) -> None:
        """只顯示這個組合真的需要的欄位。

        **修改模式下「每月存入」與「年利率」一律不顯示** —— 理由同 `_build()` 裡
        起存日與本金那一段：它們是「期」的欄位，這裡沒有值可以回填。
        """
        editing = self.current is not None
        installment = self.interest_method.currentData() == str(
            InterestMethod.INSTALLMENT_SAVINGS
        )
        self.form.setRowVisible(self.monthly_deposit, installment and not editing)

        # 本息續存時利息留在定存帳戶，不需要指定轉入帳戶。
        keeps_interest = self.maturity_action.currentData() == str(
            MaturityAction.RENEW_PRINCIPAL_AND_INTEREST
        )
        self.form.setRowVisible(self.interest_destination, not keeps_interest)

        # 機動利率不預先填數字 —— 存的當下填的值到期時多半已經不是那個值了。
        floating = self.rate_type.currentData() == str(RateType.FLOATING)
        self.form.setRowVisible(self.annual_rate, not floating and not editing)

        if not editing:
            self._sync_resolved_term()

    # --- 會建立哪一期 -----------------------------------------------------------

    def entered_opened_on(self) -> str:
        return str(self.opened_on.date().toString("yyyy-MM-dd"))

    def resolved_term(self) -> tuple[str, int]:
        """會建立的那一期：起存日與期序。跟 application 用的是同一個函式。"""
        return current_term(
            opened_on=self.entered_opened_on(),
            term_months=self.term_months.value(),
            maturity_action=str(self.maturity_action.currentData()),
            today=today_taipei().isoformat(),
        )

    def _sync_resolved_term(self) -> None:
        """**永遠說出會建立哪一期**，不只在填錯的時候。

        v0.24.0 的第一版是「填的那一期已經到期才警告，並給一顆改日期的按鈕」——
        那讓欄位的正確值變成一個要靠警告才問得出來的東西。現在欄位問的是存單上
        那一天（一個使用者一定知道的事實），這一行則回答「所以會建立哪一期」。

        兩者不同時就一定要講，因為那是使用者唯一會意外的地方：他填 112/11/15，
        建出來的是 114/11/15 那一期，而且期序是 3 不是 1。
        """
        if self.current is not None:
            return
        months = self.term_months.value()
        opened = self.entered_opened_on()
        start, sequence = self.resolved_term()
        maturity = add_months(start, months)
        span = f"{display_date(start)} – {display_date(maturity)}"

        if sequence > 1:
            text = (
                f"存單上那一期在 {display_date(add_months(opened, months))} 就到期了，"
                f"而它無限次數自動轉期續存。\n"
                f"目前存續中的是第 {sequence} 期：{span} —— 建立的就是這一期。\n"
                "中間幾期不會補紀錄：當時的牌告利率與實際領到的利息都不在帳本裡。"
            )
            if self.maturity_action.currentData() == str(
                MaturityAction.RENEW_PRINCIPAL_AND_INTEREST
            ):
                # 本息續存的本金每一期都含前一期的利息，滾過幾輪之後早就不是存單上
                # 那個數字了 —— 而程式算不出來（各期實際利息不在帳本裡）。
                text += "\n本金請填目前存摺上的金額，不是當初存入的那個數字。"
        elif maturity <= today_taipei().isoformat():
            text = (
                f"這一期在 {display_date(maturity)} 就到期了，而它不自動轉期續存 —— "
                "這份定存已經結束。記進來只會留下一筆歷史紀錄，不會產生任何待確認項目。"
            )
        else:
            text = f"會建立這一期：{span}（第 1 期）。"
        self.resolved_note.setText(text)
        self.resolved_note.setVisible(True)

    def save(self) -> None:
        try:
            annual_rate_ppm = rate_to_ppm(self.annual_rate.text())
        except (InvalidOperation, ValueError):
            self.error.setText("年利率格式不正確，例如 1.6。不確定就留空。")
            return

        keeps_interest = self.maturity_action.currentData() == str(
            MaturityAction.RENEW_PRINCIPAL_AND_INTEREST
        )
        self.values = {
            "account_id": str(self.account.currentData()),
            "name": self.name.text().strip(),
            "interest_method": str(self.interest_method.currentData()),
            "maturity_action": str(self.maturity_action.currentData()),
            "interest_destination_account_id": (
                None if keeps_interest else str(self.interest_destination.currentData())
            ),
            "rate_type": str(self.rate_type.currentData()),
            "term_months": self.term_months.value(),
            "opened_on": self.entered_opened_on(),
            "principal": self.principal.text().strip() or "0",
            "annual_rate_ppm": annual_rate_ppm,
            "monthly_deposit": self.monthly_deposit.text().strip() or None,
        }
        self.accept()


class DepositTermDialog(QDialog):
    """修改一期。**主要用途是查到牌告利率之後回來補。**"""

    def __init__(self, term: dict[str, Any], parent: QWidget) -> None:
        super().__init__(parent)
        self.term = term
        self.values: dict[str, Any] = {}
        self.start_date = date_field()
        self.maturity_date = date_field()
        self.principal = QLineEdit(minor_text(term["principal_minor"]))
        self.monthly_deposit = QLineEdit(
            minor_text(term["monthly_deposit_minor"])
            if term.get("monthly_deposit_minor") is not None
            else ""
        )
        self.annual_rate = QLineEdit(rate_input_text(term.get("annual_rate_ppm")))
        self.error = QLabel()
        self._build()

    def _build(self) -> None:
        self.setWindowTitle(f"修改第 {self.term['sequence']} 期")
        for widget, value in (
            (self.start_date, str(self.term["start_date"])),
            (self.maturity_date, str(self.term["maturity_date"])),
        ):
            widget.setDate(QDate.fromString(value, "yyyy-MM-dd"))
        self.annual_rate.setPlaceholderText("查到牌告利率再填；機動利率請留空")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)

        hint = QLabel(
            "只有「存續中」的期可以修改。已續約或已結清的期已經產生過交易，改了會對不起帳。\n"
            "零存整付的本金留 0 就是「照每月存入 × 期長推算」；"
            "中間漏存過的話請在這裡填實際累積的本金 —— 到期轉回的就是這個數字。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("起存日", self.start_date)
        form.addRow("到期日", self.maturity_date)
        form.addRow("本金（TWD）", self.principal)
        form.addRow("每月存入（TWD）", self.monthly_deposit)
        form.addRow("年利率（%）", self.annual_rate)
        form.addRow("", self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def save(self) -> None:
        try:
            annual_rate_ppm = rate_to_ppm(self.annual_rate.text())
        except (InvalidOperation, ValueError):
            self.error.setText("年利率格式不正確，例如 1.6。不確定就留空。")
            return
        self.values = {
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "maturity_date": self.maturity_date.date().toString("yyyy-MM-dd"),
            "principal": self.principal.text().strip() or "0",
            "annual_rate_ppm": annual_rate_ppm,
            "monthly_deposit": self.monthly_deposit.text().strip() or None,
        }
        self.accept()


class TerminateTermDialog(QDialog):
    """中途解約：問解約日、實際領回的本金、實際領到的利息。

    **三個欄位都由使用者填，程式一個都不預設成試算值。** 提前解約的利息通常會被打折
    （郵局按已存期間的牌告利率再乘一個折數），而 REQ-0007 §邊界 明確不做違約利息計算
    —— 預填一個算出來的數字只會讓人以為那是對的。本金預填這一期的本金，因為那個
    數字通常真的沒變。
    """

    def __init__(self, term: dict[str, Any], contract_name: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.term = term
        self.values: dict[str, Any] = {}
        self.occurred_on = date_field()
        self.principal = QLineEdit(minor_text(term["principal_minor"]))
        self.interest = QLineEdit()
        self.error = QLabel()
        self._build(contract_name)

    def _build(self, contract_name: str) -> None:
        self.setWindowTitle(f"中途解約：{contract_name}")
        self.interest.setPlaceholderText("照存摺填；提前解約的利息通常會打折")
        self.error.setObjectName("errorLabel")
        self.error.setWordWrap(True)

        hint = QLabel(
            # QLabel 不吃 markdown，星號會原樣印出來。要強調只能靠斷句與位置。
            "解約會把本金與利息記成交易轉回指定帳戶，這一期標成「已解約」。\n"
            "這份合約也會一起結束 —— 要重新存請開一份新合約。\n"
            "利息金額程式不試算：提前解約的利率由郵局決定，照存摺填。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("解約日", self.occurred_on)
        form.addRow("領回本金（TWD）", self.principal)
        form.addRow("實際利息（TWD）", self.interest)
        form.addRow("", self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("解約")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def save(self) -> None:
        """金額在**這裡**變成整數元，不是丟給頁面去猜。

        頁面那一層只認得 `Result`，所以它接不住 `MoneyError` —— 讓它自己 try 一次的話，
        「1,000」這種輸入要嘛被靜靜當成 0，要嘛就得在畫面上開第二個錯誤訊息的來源。
        對話框有自己的 `errorLabel`，這種格式問題就該在按下按鈕的地方講。
        """
        try:
            principal = Money.from_decimal_string(
                self.principal.text().strip() or "0", allow_zero=True
            ).amount_minor
            interest = Money.from_decimal_string(
                self.interest.text().strip() or "0", allow_zero=True
            ).amount_minor
        except MoneyError:
            self.error.setText("金額只能填數字，不要加逗號、單位或空白。")
            return
        self.values = {
            "occurred_on": self.occurred_on.date().toString("yyyy-MM-dd"),
            "principal_minor": principal,
            "interest_minor": interest,
        }
        self.accept()
