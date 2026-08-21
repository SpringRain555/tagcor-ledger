"""備份、驗證、還原與 CSV 匯出。

備份**只能由使用者手動建立**，啟動流程不做自動備份。「選擇外部備份資料夾」是程式
唯一會讀取指定資料夾以外路徑的地方 —— 這是刻意保留的例外，否則無法從外接硬碟還原。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.application.failures import message_for
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import backup_row_text, error_text, result_message
from tagcor_ledger.ui.widgets.table import bind_selection, set_button_role

BACKUP_FALLBACK = (
    "備份操作失敗。請確認備份資料夾存在且可寫入、磁碟還有空間，然後匯出診斷資訊回報。"
)
"""認不出來的例外才用這一句。備份自己那幾種失敗（檔案缺少、雜湊對不上、
完整性檢查沒過⋯⋯）由 `error_text()` 從 `application/failures.py` 那張表取，
每一種都有自己的說法。"""


class MaintenancePage(QWidget):
    restored = Signal()

    def __init__(self, controller: LedgerController) -> None:
        super().__init__()
        self.controller = controller
        self.list = QListWidget()
        self.result = QLabel()
        self.protect_restore = QCheckBox("還原前先建立備份")
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.list.setObjectName("backupList")
        create = QPushButton("建立完整備份")
        self.validate_button = QPushButton("驗證所選備份")
        self.restore_button = QPushButton("還原所選備份")
        self.delete_button = QPushButton("刪除所選備份")
        self.delete_button.setToolTip(
            "永久刪除這一份備份。壞掉的備份也刪得掉 —— 那正是這顆按鈕的主要用途。"
        )
        external = QPushButton("選擇外部備份資料夾")
        export = QPushButton("匯出交易 CSV")
        self.diagnostics_button = QPushButton("匯出診斷資訊")
        self.diagnostics_button.setToolTip(
            "產生一份不含金額與備註的環境報告，出問題時可以直接提供給他人。"
        )
        set_button_role(create, "primary")
        set_button_role(self.restore_button, "danger")
        set_button_role(self.delete_button, "danger")
        # 六顆按鈕擠同一行，會把整個視窗的最小寬度撐到 855 px。分成兩行同時也把
        # 「對備份動作」與「匯出東西出去」分開 —— 它們本來就不是同一類事。
        backup_row = QHBoxLayout()
        for widget in (
            create,
            self.validate_button,
            self.restore_button,
            self.delete_button,
        ):
            backup_row.addWidget(widget)
        backup_row.addStretch()
        export_row = QHBoxLayout()
        for widget in (external, export, self.diagnostics_button):
            export_row.addWidget(widget)
        export_row.addStretch()
        self.result.setWordWrap(True)
        self.result.setObjectName("hintLabel")
        layout = QVBoxLayout(self)
        layout.addLayout(backup_row)
        layout.addLayout(export_row)
        layout.addWidget(self.protect_restore)
        layout.addWidget(self.list)
        layout.addWidget(self.result)
        create.clicked.connect(self.create_backup)
        self.validate_button.clicked.connect(self.validate_selected)
        self.restore_button.clicked.connect(self.restore_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        external.clicked.connect(self.restore_external)
        export.clicked.connect(self.export_csv)
        self.diagnostics_button.clicked.connect(self.export_diagnostics)
        # 三顆都是對「所選那一份」動作 —— 沒選就停用，不要按了沒反應。
        bind_selection(
            self.list, self.validate_button, self.restore_button, self.delete_button
        )

    def refresh(self) -> None:
        self.list.clear()
        for backup in self.controller.list_backups():
            self.list.addItem(backup_row_text(backup))
            self.list.item(self.list.count() - 1).setData(
                Qt.ItemDataRole.UserRole,
                backup["path"],
            )

    def create_backup(self) -> None:
        try:
            path = self.controller.create_backup()
            self.result.setText(f"備份已建立：{path}")
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(
                self, "備份失敗", error_text(exc, fallback=BACKUP_FALLBACK)
            )

    def validate_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        result = self.controller.validate_backup(path)
        if result["valid"]:
            self.result.setText("備份驗證通過。")
            return
        # 這裡是**完整說法**（清單那一欄只有短標籤）—— 使用者按了「驗證」，
        # 要的就是「壞在哪、接下來怎麼辦」。以前這裡印的是英文碼。
        code = str(result.get("error_code") or "")
        self.result.setText(message_for(code) or f"備份不可用（{code or '原因不明'}）。")

    def delete_selected(self) -> None:
        """刪掉所選的備份。

        確認框要念出**這一份是什麼**（時間、狀態）而不是只問「確定嗎」——
        清單上每一列長得很像，只靠反白很容易刪錯一份。
        壞掉的備份照樣刪得掉，那正是這顆按鈕存在的理由。
        """
        item = self.list.currentItem()
        path = self._selected_path()
        if item is None or path is None:
            return
        answer = QMessageBox.question(
            self,
            "確認刪除備份",
            f"要永久刪除這一份備份嗎？\n\n{item.text()}\n\n"
            f"{self._remaining_usable_text(path)}\n"
            "刪掉之後救不回來。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self.controller.delete_backup(path)
        if not result.success:
            QMessageBox.warning(self, "刪除失敗", result_message(result))
            self.refresh()
            return
        self.result.setText("備份已刪除。")
        self.refresh()

    def _remaining_usable_text(self, path: Path) -> str:
        """刪掉之後還剩幾份可用的備份。

        **不擋、只講。** 「這是你最後一份可用的備份」是使用者需要知道的事，
        但要不要刪是他的決定 —— 硬擋會讓「清掉整個備份資料夾重來」變成做不到。
        """
        others = [
            backup
            for backup in self.controller.list_backups()
            if backup["valid"] and Path(str(backup["path"])) != path
        ]
        if others:
            return f"刪掉之後還有 {len(others)} 份可用的備份。"
        return "這之後就沒有任何可用的備份了。"

    def restore_selected(self) -> None:
        path = self._selected_path()
        if path is not None:
            self._restore(path)

    def restore_external(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "選擇含 manifest 的備份資料夾")
        if selected:
            self._restore(Path(selected))

    def _restore(self, path: Path) -> None:
        validation = self.controller.validate_backup(path)
        if not validation["valid"]:
            code = str(validation.get("error_code") or "")
            QMessageBox.warning(
                self,
                "無法還原",
                message_for(code) or f"這份備份不可用（{code or '原因不明'}）。",
            )
            return
        answer = QMessageBox.question(
            self,
            "確認還原",
            "還原前會先備份目前資料。確定繼續嗎？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.restore_backup(
                path,
                create_backup_first=self.protect_restore.isChecked(),
            )
            self.result.setText("備份已還原。")
            self.restored.emit()
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(
                self, "還原失敗", error_text(exc, fallback=BACKUP_FALLBACK)
            )

    def export_csv(self) -> None:
        try:
            self.result.setText(f"CSV 已匯出：{self.controller.export_csv()}")
        except Exception as exc:
            QMessageBox.warning(
                self,
                "匯出失敗",
                error_text(exc, fallback="CSV 無法匯出。請確認匯出資料夾可寫入、磁碟還有空間。"),
            )

    def export_diagnostics(self) -> None:
        result = self.controller.export_diagnostics()
        if result.success:
            self.result.setText(
                f"診斷資訊已匯出：{result.details.get('path')}（不含金額與備註，可直接提供給他人）"
            )
            return
        QMessageBox.warning(self, "診斷資訊匯出失敗", result_message(result))

    def _selected_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(str(item.data(Qt.ItemDataRole.UserRole))) if item else None
