"""重製目前記帳資料。

重製前的保護備份是**使用者明確勾選**才做，程式不替使用者決定。

## 確認框為什麼要講得這麼具體

重製不可逆。原本的確認只寫「這會清空目前記帳資料並重新初始化」——
那句話對「剛開始用、只有三筆」與「用了半年、四百筆」的人是同一句，
但後果差很多。所以現在**把筆數念出來**，而且沒勾備份時明講「沒有備份，救不回來」。

預設按鈕明確設成「否」：這種對話框最常見的誤觸是順手按 Enter。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.widgets.forms import show_status, status_label
from tagcor_ledger.ui.widgets.table import set_button_role

COUNT_LABELS = {
    "transactions": "交易",
    "balance_snapshots": "餘額盤點",
    "accounts": "帳戶",
    "categories": "類別與項目",
    "transaction_templates": "模板",
    "recurring_schedules": "週期排程",
}


class ResetPage(QWidget):
    reset_done = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.backup_first = QCheckBox("重製前先建立備份")
        self.result = status_label()
        self._build()

    def _build(self) -> None:
        # 純文字，不要用 Markdown 星號 —— QLabel 只認 HTML，星號會原樣顯示出來。
        hint = QLabel(
            "重製會刪掉目前的記帳資料庫，重新建立預設的帳戶與類別。"
            "備份資料夾不會被動到，之前建立的備份都還在。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        self.backup_first.setChecked(True)
        reset_button = QPushButton("重製目前記帳資料")
        set_button_role(reset_button, "danger")
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.backup_first)
        layout.addWidget(reset_button)
        layout.addWidget(self.result)
        layout.addStretch()
        reset_button.clicked.connect(self.reset)

    def loss_summary(self) -> str:
        """把「會失去什麼」寫成人看得懂的一行。"""
        counts = self.controller.ledger_counts()
        parts = [
            f"{label} {counts[key]} 筆"
            for key, label in COUNT_LABELS.items()
            if counts.get(key, 0) > 0
        ]
        return "、".join(parts) if parts else "目前沒有任何資料"

    def reset(self) -> None:
        backup = self.backup_first.isChecked()
        answer = QMessageBox.question(
            self,
            "確認重製",
            f"目前的資料：{self.loss_summary()}。\n\n"
            "重製後這些全部會消失，"
            + ("重製前會先自動建立一份備份。" if backup else "而且沒有備份可以救。")
            + "\n\n確定要重製嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.reset_ledger(create_backup_first=backup)
        except Exception as exc:  # noqa: BLE001 —— 這裡要攔住一切，不能讓視窗無聲消失
            QMessageBox.warning(self, "重製失敗", str(exc))
            show_status(self.result, f"重製失敗：{exc}", ok=False)
            return
        show_status(
            self.result,
            "記帳資料已重製。" + ("重製前的備份已建立。" if backup else ""),
            ok=True,
        )
        self.reset_done.emit()
