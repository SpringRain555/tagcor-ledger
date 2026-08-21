"""資料路徑設定。

改完這一頁之後還有兩步，不要以為改完就結束：同步改 `.claude\\settings.json` 的
deny／allow 清單，然後跑 `.\\Verify.ps1` 確認漂移檢查通過。細節見 `AGENTS.md`。

「搬移目前資料」的順序是先複製、再寫指標檔、最後才刪舊檔，順序不可調換 —— 詳見
`docs/lessons.md`。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.app.path_settings import data_root_of
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import result_message
from tagcor_ledger.ui.widgets.forms import form_panel
from tagcor_ledger.ui.widgets.table import set_button_role


class PathSettingsPage(QWidget):
    changed = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.ledger_dir = QLineEdit()
        self.backup_dir = QLineEdit()
        # 唯讀的 QLineEdit 而不是 QLabel：路徑很長又沒有空白，QLabel 就算開了
        # wordWrap 也斷不掉，會把整個視窗的最小寬度撐大。QLineEdit 會自己捲，
        # 而且可以選取複製 —— 出問題要貼給人看的時候正好需要。
        self.database = QLineEdit()
        self.database.setReadOnly(True)
        # 資料根目錄是**推導值**（`ledger_dir` 的上一層），所以是唯讀的顯示不是輸入框。
        # 沒有它的時候，`PATH_OUTSIDE_DATA_ROOT` 這個錯誤講的是一個使用者在畫面上
        # 看不到的東西 —— 訊息叫他「把兩個路徑放進資料根目錄底下」，而他不知道那是哪裡。
        self.data_root = QLineEdit()
        self.data_root.setReadOnly(True)
        self.result = QLabel()
        self._build()
        self.reload()

    def _build(self) -> None:
        self.result.setWordWrap(True)
        self.result.setObjectName("hintLabel")
        browse_ledger = QPushButton("選擇記帳資料路徑")
        browse_backup = QPushButton("選擇備份路徑")
        switch_button = QPushButton("切換到既有資料")
        move_button = QPushButton("搬移目前資料")
        set_button_role(switch_button, "primary")
        set_button_role(move_button, "primary")

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("記帳資料路徑", self.ledger_dir)
        form.addRow("", browse_ledger)
        form.addRow("備份路徑", self.backup_dir)
        form.addRow("", browse_backup)
        form.addRow("目前的資料根目錄", self.data_root)
        form.addRow("目前的資料庫檔案", self.database)
        actions = QHBoxLayout()
        actions.addWidget(switch_button)
        actions.addWidget(move_button)
        actions.addStretch()

        form_row = QHBoxLayout()
        form_row.addWidget(form_panel(form))
        form_row.addStretch()
        layout = QVBoxLayout(self)
        layout.addLayout(form_row)
        layout.addLayout(actions)
        hint = QLabel(
            "記帳資料會存放 ledger.sqlite3；備份會建立在獨立備份路徑下。"
            "備份路徑不可與資料路徑相同或互相包含。"
            "兩個路徑都必須在同一個資料根目錄底下，而資料根目錄取的是"
            "「記帳資料路徑」的上一層 —— 所以把備份放到另一顆磁碟會被擋下來。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self.result)
        layout.addStretch()

        browse_ledger.clicked.connect(lambda: self._choose(self.ledger_dir))
        browse_backup.clicked.connect(lambda: self._choose(self.backup_dir))
        switch_button.clicked.connect(lambda: self._save(move_current=False))
        move_button.clicked.connect(lambda: self._save(move_current=True))

    def reload(self) -> None:
        settings = self.controller.get_path_settings()
        self.ledger_dir.setText(str(settings.ledger_dir))
        self.backup_dir.setText(str(settings.backup_dir))
        self.data_root.setText(str(data_root_of(settings)))
        self.database.setText(str(self.controller.paths.database_path))

    def _choose(self, target: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "選擇資料夾")
        if selected:
            target.setText(selected)

    def _save(self, *, move_current: bool) -> None:
        result = self.controller.save_path_settings(
            ledger_dir=Path(self.ledger_dir.text().strip()),
            backup_dir=Path(self.backup_dir.text().strip()),
            move_current=move_current,
        )
        self.result.setText(result_message(result))
        if result.success:
            self.reload()
            self.changed.emit()
