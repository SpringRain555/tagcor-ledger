"""`run_gui` 要在視窗顯示之後、進事件迴圈之前寫下「視窗已開」的標記。

`tests/unit/test_startup_signal.py` 守的是模組本身與啟動器那一端；
這一條守的是**中間那一步真的有接上** —— 模組寫得再對，沒有人呼叫它就等於沒有。
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from PySide6.QtWidgets import QApplication, QWidget

from tagcor_ledger.app import startup_signal
from tagcor_ledger.app.bootstrap import bootstrap
from tagcor_ledger.ui import app as ui_app


class _StandInWindow(QWidget):
    """代替 `MainWindow`：這一條測的是 `run_gui` 的順序，不是主視窗的內容。"""

    def __init__(self, _paths: Any) -> None:
        super().__init__()
        self.shown = False

    def show(self) -> None:  # type: ignore[override]
        self.shown = True
        super().show()


def test_run_gui_writes_the_marker_after_show_and_before_exec(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    context = bootstrap(data_dir=tmp_path / "ledger-data", ensure_dirs=True)
    marker = startup_signal.marker_path(context.paths)
    observed: dict[str, Any] = {}

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # run_gui 會接管，測完還原
    monkeypatch.setattr(ui_app, "MainWindow", _StandInWindow)

    def fake_exec(self: QApplication) -> int:
        # 進事件迴圈的那一刻標記就該在了 —— 啟動器等的是這個時間點。
        observed["marker_exists_at_exec"] = marker.exists()
        return 0

    monkeypatch.setattr(QApplication, "exec", fake_exec)

    assert ui_app.run_gui(context) == 0

    assert observed["marker_exists_at_exec"] is True
    assert "pid=" in marker.read_text(encoding="utf-8")


def test_run_gui_still_starts_when_the_marker_cannot_be_written(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """標記寫不進去只該讓主控台多等一會，不該讓程式開不起來。"""
    context = bootstrap(data_dir=tmp_path / "ledger-data", ensure_dirs=True)
    # 把 tmp_dir 變成一個檔案，marker 的上層就建不出來。
    context.paths.tmp_dir.rmdir()
    context.paths.tmp_dir.write_text("blocked", encoding="utf-8")

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(ui_app, "MainWindow", _StandInWindow)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    assert ui_app.run_gui(context) == 0
