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

from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.formatting import result_message
from tagcor_ledger.ui.widgets.table import set_button_role


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
        validate = QPushButton("驗證所選備份")
        restore = QPushButton("還原所選備份")
        external = QPushButton("選擇外部備份資料夾")
        export = QPushButton("匯出交易 CSV")
        self.diagnostics_button = QPushButton("匯出診斷資訊")
        self.diagnostics_button.setToolTip(
            "產生一份不含金額與備註的環境報告，出問題時可以直接提供給他人。"
        )
        set_button_role(create, "primary")
        set_button_role(restore, "danger")
        # 六顆按鈕擠同一行，會把整個視窗的最小寬度撐到 855 px。分成兩行同時也把
        # 「對備份動作」與「匯出東西出去」分開 —— 它們本來就不是同一類事。
        backup_row = QHBoxLayout()
        for widget in (create, validate, restore):
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
        validate.clicked.connect(self.validate_selected)
        restore.clicked.connect(self.restore_selected)
        external.clicked.connect(self.restore_external)
        export.clicked.connect(self.export_csv)
        self.diagnostics_button.clicked.connect(self.export_diagnostics)

    def refresh(self) -> None:
        self.list.clear()
        for backup in self.controller.list_backups():
            state = "可用" if backup["valid"] else f"無效：{backup['error_code']}"
            item_text = f"{backup.get('created_at', '')}｜{state}｜{backup['path']}"
            self.list.addItem(item_text)
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
            QMessageBox.warning(self, "備份失敗", str(exc))

    def validate_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        result = self.controller.validate_backup(path)
        self.result.setText(
            "備份驗證通過。"
            if result["valid"]
            else f"備份不可用：{result['error_code']}"
        )

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
            QMessageBox.warning(self, "無法還原", str(validation["error_code"]))
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
            QMessageBox.warning(self, "還原失敗", str(exc))

    def export_csv(self) -> None:
        try:
            self.result.setText(f"CSV 已匯出：{self.controller.export_csv()}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

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
