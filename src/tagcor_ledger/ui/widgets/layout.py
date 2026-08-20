"""頁面版面的共同規則：內容置中、寬度有上限。

## 為什麼不是全域一個 `CONTENT_MAX_WIDTH`

因為表單與資料表要的東西相反。表單再寬只會讓標籤與欄位隔半個螢幕，眼睛得橫著跑；
交易紀錄有七欄，寬度是真的有用。所以是**每一類頁面各自的上限**：

| 頁面 | 上限 | 為什麼 |
|---|---|---|
| 記帳 | `FORM_WIDTH` 720 | 純表單 |
| 資產總覽 | `SUMMARY_WIDTH` 980 | 摘要，一眼掃完比多塞欄位重要 |
| 交易紀錄、待確認、操作設定、系統設定、餘額盤點、法規參考 | `TABLE_WIDTH` 1600 | 欄位多 |

行為是 **`min(可用寬度, 上限)` 並置中**：視窗縮小時內容跟著縮，放大時停在上限。
不需要 stretch、不需要 `resizeEvent` —— `setMaximumWidth` 加上單一 `addWidget`
在 `QHBoxLayout` 裡就是這個行為（2026-08-20 實測四種寫法後確認）。
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

FORM_WIDTH = 720
"""純表單頁。"""

SUMMARY_WIDTH = 980
"""摘要頁。"""

TABLE_WIDTH = 1600
"""有資料表的頁。"""

PAGE_MARGINS = (24, 20, 24, 20)
"""每一頁的外距，左右比上下大 —— 內容離側邊欄太近會擠。"""

CONTENT_PANEL_NAME = "pageContent"
"""置中容器的 objectName，測試靠它拿到實際的內容寬度。"""


def page_layout(page: QWidget, *, width: int) -> QVBoxLayout:
    """建立頁面的內容 layout，回傳的是**內層**（東西加到這裡）。

    ```python
    layout = page_layout(self, width=TABLE_WIDTH)
    layout.addWidget(title)
    layout.addWidget(self.table)
    ```

    外層負責外距與置中，頁面不需要知道它的存在。
    """
    inner = QVBoxLayout()
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(10)

    panel = QWidget()
    panel.setObjectName(CONTENT_PANEL_NAME)
    panel.setLayout(inner)
    panel.setMaximumWidth(width)

    outer = QHBoxLayout(page)
    outer.setContentsMargins(*PAGE_MARGINS)
    outer.setSpacing(0)
    outer.addWidget(panel)
    return inner


def content_panel(page: QWidget) -> QWidget | None:
    """拿到某一頁的置中容器。給測試量寬度用。"""
    return page.findChild(QWidget, CONTENT_PANEL_NAME)
