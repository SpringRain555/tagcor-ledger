"""視窗的預設大小與下限。

**每次啟動都是預設大小，不記上次的大小與位置**（2026-09-27 使用者指定）。
以前會把大小與位置寫進 `config_dir/window.json`、下次開的時候還原；那個檔案現在
不讀也不寫。舊版留下的 `window.json` 放著無害，刪掉也無妨。
"""

from __future__ import annotations

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 760
"""每次啟動的大小。螢幕比這個小時，由 `MainWindow` 縮到螢幕可用範圍內。"""

MINIMUM_WIDTH = 360
MINIMUM_HEIGHT = 480
"""再小就不給拖。有下限，版面才有一個可以被驗證的最壞情況。

2026-09-27 從 1024×680 降到手機寬度：窄視窗改用頂端選單、每一頁自己捲動
（`ui/widgets/layout.py`），不再需要整個視窗撐到最寬那一頁的寬度。
360 是常見手機的 CSS 寬度下限。"""
