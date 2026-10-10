"""第一次啟動：資料要放在哪裡（ADR-0018）。

什麼時候算第一次啟動、為什麼不另外記「問過了沒」，寫在 `app/data_location.py`。這裡只管問：
三個選項，按「確定」才建資料夾（帳本由 `main._run` 接著建），按「結束」什麼都不建。

單獨放一個模組的理由同 `startup_dialog.py`：`main.py` 不必自己 import PySide6。
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import cast

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.app import startup_signal
from tagcor_ledger.app.data_location import (
    PROGRAM_DATA_FOLDER,
    DataLocation,
    LocationChoice,
    OtherFolder,
    inspect_other_folder,
    prepare_location,
    program_data_root,
)
from tagcor_ledger.app.logging_setup import get_logger
from tagcor_ledger.app.path_settings import PathSettingsError, default_data_root
from tagcor_ledger.application.failures import failure, message_for
from tagcor_ledger.ui.theme import apply_dark_theme
from tagcor_ledger.ui.widgets.forms import show_status, status_label
from tagcor_ledger.ui.widgets.table import set_button_role

DIALOG_WIDTH = 600
"""路徑很長（`C:\\Users\\…\\AppData\\Local\\TagCor\\TagCorLedger`），太窄的話每一行說明都斷成三行。"""

PROGRAM_HINT = (
    "整個資料夾搬走或複製到別台電腦，帳本跟著走。更新程式時，要把 "
    f"{PROGRAM_DATA_FOLDER} 一起搬到新的資料夾；不要放在 OneDrive 同步的資料夾（例如桌面、文件）。"
)
USER_HINT = "更新或重新下載程式都不影響帳本。"
OTHER_HINT = "放在自己管理的資料夾，例如另一顆硬碟；也可以選以前用過的資料夾，把原本的帳本接回來。"
UPDATE_HINT = (
    f"從舊版的程式資料夾更新過來的話：先按「結束」，把舊資料夾裡的 {PROGRAM_DATA_FOLDER} "
    "整個搬到這個程式資料夾，再重新開啟。"
)
PROGRAM_UNAVAILABLE = "（不是從程式資料夾執行，這個選項不能用）"
OTHER_EXISTING = "這裡已經有帳本，會直接使用它。"
OTHER_NEW = "會在這裡建立新的帳本。"


class DataLocationDialog(QDialog):
    """三選一。`chosen` 在按下「確定」而且資料夾都建好之後才有值。"""

    shown = Signal()
    """真的顯示出來了。啟動器的標記檔接在這裡（`choose_data_location()`）。"""

    def __init__(
        self,
        *,
        program_folder: Path | None,
        user_folder: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("TagCor Ledger")
        self.chosen: DataLocation | None = None
        self.other: OtherFolder | None = None
        self.choices = QButtonGroup(self)
        self.program_option = QRadioButton("放在程式資料夾裡")
        self.user_option = QRadioButton("放在這台電腦的使用者資料夾")
        self.other_option = QRadioButton("其他位置…")
        self.pick_button = QPushButton("選擇資料夾…")
        self.program_path = _path_field(program_folder)
        self.user_path = _path_field(user_folder)
        self.other_path = _path_field(None)
        self.other_path.setPlaceholderText("還沒選資料夾")
        self.other_status = status_label()
        self.status = status_label()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._build(program_available=program_folder is not None)

    def _build(self, *, program_available: bool) -> None:
        title = QLabel("資料要放在哪裡？")
        title.setObjectName("pageTitle")
        intro = _hint("第一次開啟，先決定帳本存在哪裡。之後可以在「系統設定 → 資料路徑」改。")

        for option, choice in (
            (self.program_option, LocationChoice.PROGRAM_FOLDER),
            (self.user_option, LocationChoice.USER_FOLDER),
            (self.other_option, LocationChoice.OTHER),
        ):
            option.setProperty("choice", str(choice))
            self.choices.addButton(option)
        self.choices.setExclusive(True)

        if program_available:
            self.program_option.setChecked(True)
        else:
            # 不是原始碼資料夾就沒有「程式資料夾」可言；說出原因，預選改成下一個。
            self.program_option.setEnabled(False)
            self.program_path.setText(PROGRAM_UNAVAILABLE)
            self.user_option.setChecked(True)

        other_row = QHBoxLayout()
        other_row.addWidget(self.other_option)
        other_row.addStretch()
        other_row.addWidget(self.pick_button)

        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("確定")
        set_button_role(ok, "primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("結束")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addWidget(self.program_option)
        layout.addWidget(self.program_path)
        layout.addWidget(_hint(PROGRAM_HINT))
        layout.addSpacing(8)
        layout.addWidget(self.user_option)
        layout.addWidget(self.user_path)
        layout.addWidget(_hint(USER_HINT))
        layout.addSpacing(8)
        layout.addLayout(other_row)
        layout.addWidget(self.other_path)
        layout.addWidget(_hint(OTHER_HINT))
        layout.addWidget(self.other_status)
        if program_available:
            layout.addSpacing(8)
            layout.addWidget(_hint(UPDATE_HINT))
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self.setMinimumWidth(DIALOG_WIDTH)

        # 兩行訊息有話要說才出現；空的時候不要佔著一塊空白。
        self.other_status.setVisible(False)
        self.status.setVisible(False)
        self.pick_button.clicked.connect(self.pick_other_folder)
        self.choices.buttonToggled.connect(lambda *_: self._sync_ok())
        self._sync_ok()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self.shown.emit()

    def selected_choice(self) -> LocationChoice | None:
        button = self.choices.checkedButton()
        return LocationChoice(str(button.property("choice"))) if button is not None else None

    def pick_other_folder(self) -> None:
        start = str(self.other.root) if self.other is not None else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "選擇資料夾", start)
        if folder:
            self.set_other_folder(Path(folder))

    def set_other_folder(self, folder: Path) -> None:
        """挑好資料夾：顯示它、說明會發生什麼，並選到「其他位置」。"""
        self.other = inspect_other_folder(folder)
        self.other_path.setText(str(self.other.root))
        if self.other.error_code is not None:
            show_status(self.other_status, _message(self.other.error_code), ok=False)
        else:
            show_status(
                self.other_status,
                OTHER_EXISTING if self.other.has_ledger else OTHER_NEW,
                ok=None,
            )
        self.other_status.setVisible(True)
        self.other_option.setChecked(True)
        self._sync_ok()

    def _sync_ok(self) -> None:
        """「其他位置」還沒挑資料夾、或挑到不能用的，不讓按「確定」—— 按下去才知道不行太晚了。"""
        ready = self.selected_choice() is not None
        if self.selected_choice() is LocationChoice.OTHER:
            ready = self.other is not None and self.other.settings is not None
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ready)

    def accept(self) -> None:
        """建好資料夾才關窗。建不出來就在這裡說原因，讓使用者換一個選項。"""
        choice = self.selected_choice()
        if choice is None:
            return
        folder = self.other.root if choice is LocationChoice.OTHER and self.other else None
        try:
            self.chosen = prepare_location(choice, other_folder=folder)
        except (PathSettingsError, OSError, ValueError) as exc:
            result = failure(
                exc,
                fallback_code="SYSTEM_PATH_NOT_WRITABLE",
                fallback_message=_message("SYSTEM_PATH_NOT_WRITABLE"),
            )
            show_status(self.status, result.message, ok=False)
            self.status.setVisible(True)
            return
        super().accept()


def choose_data_location(*, ready_marker: Path) -> DataLocation | None:
    """問使用者資料放哪裡。按「結束」、Esc 或關掉視窗回 `None`，那時什麼都沒建。

    `ready_marker` 是啟動器在等的標記檔：對話框一出現，使用者就看得到東西了，主控台可以退場。
    """
    app = cast(QApplication, QApplication.instance() or QApplication(sys.argv[:1]))
    apply_dark_theme(app)
    # 對話框一關，Qt 會當成「最後一個視窗關了」而排一個結束事件 —— 而主視窗還沒建，
    # 那個事件會讓等一下的 `app.exec()` 一開始就結束。問的這段期間先關掉，問完還原。
    quit_on_close = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    try:
        dialog = DataLocationDialog(
            program_folder=program_data_root(), user_folder=default_data_root()
        )
        # **不要先 `show()` 再 `exec()`**：已經顯示的視窗改不了 modality，`exec()` 給的
        # 只會是一個非 modal 的對話框（2026-10-10 實機跑出來的）。標記改在真的顯示的那一刻寫。
        dialog.shown.connect(lambda: _mark_ready(ready_marker))
        dialog.exec()
        return dialog.chosen
    finally:
        app.setQuitOnLastWindowClosed(quit_on_close)


def _mark_ready(marker: Path) -> None:
    if not startup_signal.mark_ready(marker):
        get_logger("ui").warning("ready marker not written path=%s", marker)


def _path_field(path: Path | None) -> QLineEdit:
    """唯讀、可選取的路徑。用 QLineEdit 不用 QLabel 的理由同 `settings_paths.py`：
    沒有空白的長路徑 QLabel 斷不掉，會把對話框撐寬。"""
    field = QLineEdit(str(path) if path is not None else "")
    field.setReadOnly(True)
    return field


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hintLabel")
    label.setWordWrap(True)
    return label


def _message(code: str) -> str:
    return message_for(code) or code
