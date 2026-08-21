"""側邊欄：兩組導覽項目，中間留白，設定沉底。

## 為什麼是兩個 QListWidget 而不是一個

因為中間要有一段**會隨視窗長高的留白**，而 `QListWidget` 沒辦法在自己的項目之間
插一個 stretch。兩個清單夾一個 `addStretch()` 是最直接的做法。

代價是選取狀態要自己同步：兩個清單各自維護 current row，使用者點了下面那組，
上面那組仍然亮著。`_syncing` 旗標就是為了這件事 —— 清掉另一組的選取會觸發它自己的
`currentRowChanged`，沒有旗標就是無窮遞迴。

## 為什麼**不**把非作用中那組的 current row 設成 -1

因為 `QAbstractItemView::focusInEvent` 在 current index 無效時，會自己把它設成第一列。
那不是使用者選的，但 `currentRowChanged(0)` 照樣會發出來 —— 舊版因此只要焦點碰到
「日常」那一組，畫面就跳回資產總覽。而讓焦點移動的事情多得數不完：關掉對話框、
按鈕被停用（`bind_selection` 每次刷新都會做）、按 Tab（實測在操作設定裡按四次就中）。
使用者看到的是「在操作設定裡做任何事都有機會跳回資產總覽」。

所以**兩組的 current row 一直都是有效的**，Qt 就沒有東西可以自作主張。
「現在是哪一頁」改由 `Sidebar` 自己記（`_current`），選取狀態才是畫面上的真相：
**任何時候只有一列是選取的**。

代價是「點自己那一組裡已經是 current 的那一列」不會觸發 `currentRowChanged`，
所以另外接了 `itemClicked` —— 側邊欄裡不該有任何點不動的東西。

## 為什麼沒有分組標題

見 `ui/navigation.py` 的模組說明。簡短版：那條路失敗過兩次，這次把標籤整個拿掉，
分組改用位置表達。**側邊欄裡的每一個字都可以點。**
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from tagcor_ledger.ui import colors
from tagcor_ledger.ui.navigation import DAILY_PAGES, LABELS, SETTINGS_PAGES, PageId

PAGE_ROLE = int(Qt.ItemDataRole.UserRole)
BADGE_ROLE = int(Qt.ItemDataRole.UserRole) + 1

WIDTH = 184
COMPACT_WIDTH = 152
COMPACT_BREAKPOINT = 1100
"""視窗窄於這個寬度時，側邊欄縮一階把空間讓給內容。

**不做圖示折疊模式** —— 專案沒有圖示集，八個項目也不值得為此發明一套圖示語言。
"""

BADGE_MARGIN = 12
"""數字距離項目右緣的距離，對齊 QSS 裡 `::item` 的左內距。"""


class _BadgeDelegate(QStyledItemDelegate):
    """在項目右側畫一個數字。

    **不把數字寫進標籤文字。** 舊做法是把「待確認」改寫成「待確認（2）」，
    於是標籤長度隨數字跳動 —— 而側邊欄的項目應該是固定不動的錨點，
    使用者是靠位置與長度記住它們的。
    """

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        count = index.data(BADGE_ROLE)
        if not count:
            return
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QColor(colors.TEXT if selected else colors.TEXT_FAINT))
        font = QFont(option.font)
        font.setPointSizeF(max(font.pointSizeF() - 2.0, 8.0))
        painter.setFont(font)
        painter.drawText(
            option.rect.adjusted(0, 0, -BADGE_MARGIN, 0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            str(count),
        )
        painter.restore()


class _NavList(QListWidget):
    """高度剛好等於內容的清單。

    預設的 `QListWidget` 會盡量長高，兩個清單就會各自吃掉一半的空間，中間的
    stretch 永遠是 0 —— 設定那一組也就浮在中間而不是沉在底部。所以這裡把垂直
    size policy 設成 `Fixed` 並回報真實的內容高度。
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebarNavigation")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setItemDelegate(_BadgeDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        rows = sum(self.sizeHintForRow(row) for row in range(self.count()))
        spacing = self.spacing() * 2 * max(self.count(), 1)
        return QSize(super().sizeHint().width(), rows + spacing + 2 * self.frameWidth())


class Sidebar(QFrame):
    """側邊欄。對外只有三件事：選了哪一頁、跳到哪一頁、某一頁的數字是多少。

    **是 `QFrame` 不是 `QWidget`** —— 純 `QWidget` 不會畫 QSS 給的背景與邊框，
    而右邊那條分隔線是畫在這一層上的（不是畫在清單上，否則兩個清單之間會斷線）。
    """

    page_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebarRail")
        self._rows: dict[PageId, tuple[_NavList, int]] = {}
        self._syncing = False
        self._current: PageId | None = None
        """哪一頁是作用中的。**這是正本**，不從 current row 推 —— 兩組都有 current row。"""
        self.daily = self._build_list(DAILY_PAGES)
        self.settings = self._build_list(SETTINGS_PAGES)
        self._build()

    def _build(self) -> None:
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        # QSS 的 `max-height: 1px` 只管畫出來的樣子，版面配置仍然用 sizeHint（HLine 是 3px）。
        separator.setFixedHeight(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(0)
        layout.addWidget(self.daily)
        layout.addStretch(1)
        layout.addWidget(self._inset(separator))
        layout.addSpacing(8)
        layout.addWidget(self.settings)

    @staticmethod
    def _inset(widget: QWidget) -> QWidget:
        """把分隔線左右縮進來，讓它對齊項目文字而不是頂到邊。

        **垂直 size policy 必須是 `Fixed`。** 預設的 `Preferred` 會讓這個容器
        自己吸掉多餘的高度 —— 於是「設定沉底」看起來是對的，但真正在撐開版面的是
        這個間隔容器而不是中間的 stretch，把 stretch 拿掉也不會有人發現。
        """
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(12, 0, 12, 0)
        holder_layout.setSpacing(0)
        holder_layout.addWidget(widget)
        return holder

    def _build_list(self, pages: tuple[PageId, ...]) -> _NavList:
        widget = _NavList()
        for page in pages:
            item = QListWidgetItem(LABELS[page])
            item.setData(PAGE_ROLE, str(page))
            self._rows[page] = (widget, widget.count())
            widget.addItem(item)
        widget.updateGeometry()
        # **先給一個有效的 current index，而且在接訊號之前。** 只要它是無效的，
        # 焦點一碰到這個清單 Qt 就會自己把它設成第 0 列並發出 currentRowChanged。
        widget.setCurrentRow(0)
        widget.clearSelection()
        widget.currentRowChanged.connect(
            lambda row, source=widget: self._row_changed(source, row)
        )
        # current row 沒變就不會有 currentRowChanged，所以「點目前這一列」要另外接。
        widget.itemClicked.connect(lambda item, source=widget: self._item_clicked(source, item))
        return widget

    # --- 對外 -----------------------------------------------------------------

    def adapt_to(self, window_width: int) -> None:
        """視窗變窄時把側邊欄縮一階。導覽本身不該跟著視窗抖動，所以只有兩個寬度。"""
        self.setFixedWidth(
            COMPACT_WIDTH if window_width < COMPACT_BREAKPOINT else WIDTH
        )

    def select(self, page: PageId) -> None:
        """把某一頁標成作用中。**只改畫面狀態，不發訊號** —— 呼叫者自己知道要去哪。"""
        widget, row = self._rows[page]
        self._syncing = True
        try:
            widget.setCurrentRow(row)
            for other in (self.daily, self.settings):
                if other is not widget:
                    other.clearSelection()
            item = widget.item(row)
            if item is not None:
                item.setSelected(True)
        finally:
            self._syncing = False
        self._current = page

    def set_badge(self, page: PageId, count: int) -> None:
        """設定某一頁右側的數字。`0` 表示不顯示。"""
        widget, row = self._rows[page]
        item = widget.item(row)
        if item is not None:
            item.setData(BADGE_ROLE, count or None)

    def current_page(self) -> PageId | None:
        """作用中的那一頁。**不從 current row 推** —— 兩組清單都有 current row。"""
        return self._current

    def item_for(self, page: PageId) -> QListWidgetItem | None:
        """給測試用：拿到某一頁對應的那一列。"""
        widget, row = self._rows[page]
        return widget.item(row)

    def all_items(self) -> list[QListWidgetItem]:
        """側邊欄上的每一列。守門測試會斷言它們**全部都可以選取**。"""
        items: list[QListWidgetItem] = []
        for widget in (self.daily, self.settings):
            for row in range(widget.count()):
                item = widget.item(row)
                if item is not None:
                    items.append(item)
        return items

    # --- 內部 -----------------------------------------------------------------

    def _row_changed(self, source: _NavList, row: int) -> None:
        """鍵盤移動游標＝換頁。`_syncing` 擋掉 `select()` 自己造成的變動。"""
        if self._syncing or row < 0:
            return
        self._choose(source.item(row))

    def _item_clicked(self, source: _NavList, item: QListWidgetItem) -> None:
        """滑鼠點一列＝換頁，**不管它是不是已經是 current row**。

        少了這條，「切到設定那組之後，再點回日常那組原本停著的那一列」會完全沒反應
        —— current row 沒變，`currentRowChanged` 就不會發。
        """
        if self._syncing:
            return
        self._choose(item)

    def _choose(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        page = PageId(str(item.data(PAGE_ROLE)))
        if page is self._current:
            return
        self.select(page)
        self.page_selected.emit(str(page))
