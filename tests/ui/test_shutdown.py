"""關掉程式的時候不可以留下未處理例外。

這裡開**子行程**跑一次完整的「開啟 → 關閉 → 直譯器結束」，因為要抓的東西發生在
**直譯器關閉階段** —— 在同一個 process 裡用 `deleteLater()` ＋ `processEvents()`
是抓不到的（2026-08-22 前三次探針就是這樣落空的，看起來像沒有 bug）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DRIVER = '''
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.ui.controller import LedgerController
from tagcor_ledger.ui.main_window import MainWindow

paths = resolve_app_paths(Path(sys.argv[1]) / "ledger-data")


def run():
    app = QApplication.instance() or QApplication([])
    # 清單要有列。空的清單走不到會出事的那條路 —— 少了這一步，這條測試會
    # 在 bug 還在的情況下變綠。
    seed = LedgerController(paths)
    seed.create_backup()
    del seed
    # 不用 `window` fixture：要先用同一個 `paths` 造一份備份再開視窗。
    window = MainWindow(paths)
    window.show()
    assert window.system_settings.maintenance.list.count() >= 1, "備份清單是空的"
    QTimer.singleShot(0, window.close)
    QTimer.singleShot(30, app.quit)
    return int(app.exec())


run()
print("DRIVER_OK", flush=True)
'''


def test_closing_the_program_leaves_no_unhandled_exception(tmp_path: Path) -> None:
    """關閉時不得出現 `already deleted`。

    2026-08-22 使用者實機遇到的：關掉視窗之後跳出「發生未預期的錯誤」，
    內容是 `RuntimeError: libshiboken: Internal C++ object
    (PySide6.QtWidgets.QListWidget) already deleted`。操作本身沒有任何問題，
    純粹是關閉流程留下來的 —— 但使用者看到的是一個紅色驚嘆號。

    成因：`bind_selection` 把 `sync` 接到 model 的 `modelReset`。`QTableView`
    用的 `RowsModel` 由頁面自己持有，銷毀順序是 Python 說了算；而 `QListWidget`
    的 model 是 **C++ 那邊的內部子物件**，`~QListWidget` 期間它會發一次
    `modelReset`，那時候 view 的 Python 包裝已經失效了。

    v0.16.1 把 `bind_selection` 從 `QTableView` 放寬到 `QAbstractItemView`
    （為了讓維護頁的備份清單也能用），這條路才第一次被走到。日誌可以佐證：
    0.8.0～0.14.3 共 10 次關閉全部乾淨，只有 0.16.3 這次噴。
    """
    driver = tmp_path / "close_cycle.py"
    driver.write_text(DRIVER, encoding="utf-8")

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", str(driver), str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )

    # 先確認驅動程式真的跑完了 —— 否則「stderr 沒有 already deleted」
    # 可能只是因為它根本沒開起來。
    assert "DRIVER_OK" in completed.stdout, (
        "驅動程式沒跑完，這條測試沒有檢查到任何東西：\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )
    assert completed.returncode == 0, f"子行程退出碼 {completed.returncode}"
    assert "already deleted" not in completed.stderr, (
        "關閉程式時留下未處理例外：\n" + completed.stderr
    )
    assert "Traceback" not in completed.stderr, (
        "關閉程式時留下未處理例外：\n" + completed.stderr
    )
