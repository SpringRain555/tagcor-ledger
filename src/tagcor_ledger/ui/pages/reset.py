"""重製目前記帳資料。

重製前的保護備份是**使用者明確勾選**才做，程式不替使用者決定。
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
from tagcor_ledger.ui.widgets.table import set_button_role


class ResetPage(QWidget):
    reset_done = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.backup_first = QCheckBox("重製前先建立備份")
        self.result = QLabel()
        self._build()

    def _build(self) -> None:
        title = QLabel("重製與還原")
        title.setObjectName("pageTitle")
        reset_button = QPushButton("重製目前記帳資料")
        set_button_role(reset_button, "danger")
        self.result.setWordWrap(True)
        self.result.setObjectName("hintLabel")
        hint = QLabel("重製會移除目前記帳資料庫並重新建立預設帳戶與類別；不會刪除備份資料夾。")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.backup_first)
        layout.addWidget(reset_button)
        layout.addWidget(self.result)
        layout.addStretch()
        reset_button.clicked.connect(self.reset)

    def reset(self) -> None:
        answer = QMessageBox.question(
            self,
            "確認重製",
            "這會清空目前記帳資料並重新初始化。是否繼續？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.reset_ledger(
                create_backup_first=self.backup_first.isChecked()
            )
            self.result.setText("記帳資料已重製。")
            self.reset_done.emit()
        except Exception as exc:
            QMessageBox.warning(self, "重製失敗", str(exc))
