"""頁面版面的共同規則：內容置中、寬度有上限。

## 為什麼不是全域一個 `CONTENT_MAX_WIDTH`

因為表單與資料表要的東西相反。表單再寬只會讓標籤與欄位隔半個螢幕，眼睛得橫著跑；
交易紀錄有七欄，寬度是真的有用。所以是**每一類頁面各自的上限**：

| 頁面 | 上限 | 為什麼 |
|---|---|---|
| 記帳 | `ENTRY_WIDTH` 880 | 每天用的那一頁，要填滿預設視窗 |
| 盤點與設定裡的表單區、對話框說明文字 | `FORM_WIDTH` 720 | 純表單 |
| 資產總覽 | `SUMMARY_WIDTH` 980 | 摘要，一眼掃完比多塞欄位重要 |
| 交易紀錄、待確認、操作設定、系統設定、餘額盤點、法規參考 | `TABLE_WIDTH` 1600 | 欄位多 |

行為是 **`min(可用寬度, 上限)` 並置中**：視窗縮小時內容跟著縮，放大時停在上限。
不需要 stretch、不需要 `resizeEvent` —— `setMaximumWidth` 加上單一 `addWidget`
在 `QHBoxLayout` 裡就是這個行為（2026-08-20 實測四種寫法後確認）。

## 窄視窗（2026-09-27 起支援到手機寬度）

視窗窄於 `NARROW_BREAKPOINT` 時，主視窗把側邊欄換成頂端的頁面選單，並對每一頁呼叫
`set_page_compact()` 把外距收小。**每一頁都包在自己的 `QScrollArea` 裡**
（`scrollable()`）：放不下的頁（七欄的交易紀錄）橫向捲動，而不是把整個視窗撐寬 ——
以前視窗最小寬度就是「最寬那一頁的最小寬度」，1024 px。

**捲動區要一頁一個，不能包在 `QStackedWidget` 外面。** 堆疊的最小尺寸是所有頁面
最小尺寸的最大值，包在外面的話記帳頁也會因為交易紀錄太寬而跟著橫向捲動。
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

FORM_WIDTH = 720
"""一般表單（`forms.form_panel()` 的預設、對話框裡會換行的說明文字）。"""

ENTRY_WIDTH = 880
"""記帳頁。

2026-09-27 從 `FORM_WIDTH` 720 分出來放寬：預設大小的視窗（內容區約 830～1050 px）
裡，720 會在表單左右各留五六十 px 的空。記帳頁的標籤靠右貼著欄位，放寬不會讓標籤
與欄位隔半個螢幕。**只放寬記帳頁**：第一次是直接改 `FORM_WIDTH`，結果盤點與兩個
設定分頁的表單區（`form_panel()` 的預設值）也被無聲地放寬了。"""

SUMMARY_WIDTH = 980
"""摘要頁。"""

TABLE_WIDTH = 1600
"""有資料表的頁。"""

PAGE_MARGINS = (24, 20, 24, 20)
"""每一頁的外距，左右比上下大 —— 內容離側邊欄太近會擠。"""

COMPACT_PAGE_MARGINS = (12, 12, 12, 12)
"""窄視窗的外距。手機寬度下 24 px 兩邊就吃掉一成多的寬度，而那時旁邊也沒有側邊欄。"""

NARROW_BREAKPOINT = 720
"""視窗窄於這個寬度時，側邊欄換成頂端的頁面選單、外距收小。

值的來由：側邊欄 152 ＋ 記帳表單「標籤在左」的最小寬度約 560。再窄，側邊欄留著
只會把表單擠成標籤在上，那不如把側邊欄收起來。"""

ENTRY_PAGE_MARGINS = (40, 20, 40, 20)
"""記帳頁的外距，左右比別頁寬。

記帳頁的欄位一路拉到內容區右緣，而左邊有一整欄標籤墊著 —— 同樣 24 px，右邊看起來
緊貼視窗邊（2026-09-27 使用者回報「欄位右邊留白太少」）。表格頁不需要：表格本身
有框線與內距。"""

CONTENT_PANEL_NAME = "pageContent"
"""置中容器的 objectName，測試靠它拿到實際的內容寬度。"""


_MARGINS_PROPERTY = "pageMargins"
"""`page_layout()` 把這一頁「寬視窗時」的外距記在面板上，`set_page_compact()` 還原時用。"""


def page_layout(
    page: QWidget,
    *,
    width: int,
    margins: tuple[int, int, int, int] = PAGE_MARGINS,
) -> QVBoxLayout:
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
    panel.setProperty(_MARGINS_PROPERTY, list(margins))

    outer = QHBoxLayout(page)
    outer.setContentsMargins(*margins)
    outer.setSpacing(0)
    outer.addWidget(panel)
    return inner


def set_page_compact(page: QWidget, compact: bool) -> None:
    """窄視窗時把外距收小。只動 `page_layout()` 建的外層，沒用它的頁不受影響。"""
    outer = page.layout()
    panel = page.findChild(QWidget, CONTENT_PANEL_NAME)
    if outer is None or panel is None:
        return
    left, top, right, bottom = (
        COMPACT_PAGE_MARGINS if compact else panel.property(_MARGINS_PROPERTY) or PAGE_MARGINS
    )
    outer.setContentsMargins(left, top, right, bottom)


def scrollable(page: QWidget) -> QScrollArea:
    """把一頁包進捲動區：放得下時跟以前一模一樣，放不下才出現捲軸。

    `widgetResizable` 讓頁面在夠大時吃滿整個 viewport（表格照樣拉滿），
    只有比頁面自己的最小尺寸還小時才捲。
    """
    area = QScrollArea()
    area.setObjectName("pageScroll")
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(page)
    return area


def content_panel(page: QWidget) -> QWidget | None:
    """拿到某一頁的置中容器。給測試量寬度用。"""
    return page.findChild(QWidget, CONTENT_PANEL_NAME)
