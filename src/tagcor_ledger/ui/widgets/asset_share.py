"""資產占比圓環：資產總覽上「這些錢分別放在哪裡」的那一張圖。

## 為什麼是圓環而不是實心圓餅

中心留白之後，扇形只剩「角度」一個變數要讀。實心圓餅的視覺重量集中在圓心附近，
而那正好是資訊最少的地方 —— 每一片在圓心都收斂成同一個點。

## 為什麼是灰階

專案的硬規則是「彩色只留給金額與警示」，畫面上任何一抹紅或綠都應該是資訊。
所以色階只負責讓人看出「哪一片比較大」，**真正的占比由圖例上的數字講**。
色階的正本在 `colors.CHART_SLICES`，對比由 `test_resources.py` 守著。

## 分成兩個東西：純函式與 widget

`build_shares()` 完全不碰 Qt，所以「負餘額怎麼算」「幾個以上要合併」這些規則
在 `tests/unit/test_asset_share.py` 裡是毫秒級的純函式測試。widget 只負責畫。

**在 Python 裡排這一份是刻意的。** `AGENTS.md` 那條「篩選、排序一律在 SQL 裡做」
講的是會長大的查詢；這裡排的是資產總覽已經載進來的那十來列摘要，與
`controller/overview.py` 的 `min(terms, ...)` 同一類。不要為了整齊把它推回 SQL ——
那會讓帳戶清單多一條只有這張圖要用的排序。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tagcor_ledger.ui import colors
from tagcor_ledger.ui.formatting import group_digits

MAX_SLICES = len(colors.CHART_SLICES)
"""圓環最多幾片。超過就把最小的那些合併成「其他」—— 見 `build_shares()`。

上限等於色階數不是巧合：**再多一片就沒有分得出來的灰可以給它**。"""

LEGEND_WIDTH = 340
"""圖例的寬度上限。

**不設上限的話它會吃掉整個頁寬**：名稱那一欄有 stretch，於是「郵局活儲」與
「182,000」之間隔了一整片空白，兩欄要靠眼睛橫著跑才連得起來（2026-08-23 實機截圖）。
與 `filters.SEARCH_WIDTH`、`layout.FORM_WIDTH` 同一個道理 —— 會拉伸的東西要有上限。
"""

RING_SIZE = 200
"""圓環的邊長（正方形）。"""

RING_THICKNESS = 34
"""圓環的厚度。太細看不出面積差，太粗就退化成實心圓餅。"""

GAP_DEGREES = 1.5
"""每一片前後各縮多少度，做出片與片之間的縫。

只有一片的時候**不縮** —— 一個 360 度的圓被縮掉 3 度會在正上方裂一條沒有意義的縫。
"""

SWATCH_SIZE = 12
"""圖例色塊的邊長。"""

OTHERS_LABEL = "其他"


@dataclass(frozen=True)
class Share:
    """圓環上的一片。`ratio` 的分母是**正餘額合計**，不是總資產。"""

    name: str
    balance_minor: int
    ratio: float
    color: str


@dataclass(frozen=True)
class ShareBreakdown:
    """`build_shares()` 的完整回傳值。頁面要的每一項都在這裡，不必自己再算一次。"""

    shares: tuple[Share, ...]
    negative: tuple[dict[str, Any], ...]
    positive_total_minor: int


def build_shares(accounts: list[dict[str, Any]]) -> ShareBreakdown:
    """把帳戶清單換成圓環要畫的那幾片。

    五條規則，每一條都有測試：

    | 情形 | 怎麼處理 |
    |---|---|
    | 餘額 > 0 | 進圓環，**依餘額由大到小** |
    | 餘額 = 0 | 不進圓環也不進圖例。0 度的扇形畫不出來，列出來只是一行空的 |
    | 餘額 < 0 | **不進圓環**，另外回報給頁面用一句話交代 |
    | 超過 `MAX_SLICES` 片 | 前 `MAX_SLICES - 1` 大各一片，其餘合併成「其他（N 個帳戶）」 |
    | 沒有任何正餘額 | 回傳空的 `shares`，頁面整段收起來 |

    **分母是正餘額合計，不是總資產。** 有負餘額帳戶時兩者不同 —— 頁面必須把分母
    寫出來，否則使用者會拿百分比去乘總資產然後對不起來。

    收進來的應該是**使用中**的帳戶（`overview_snapshot()["accounts"]` 已經濾過）。
    封存帳戶不進圓環，與總資產的算法一致：兩個數字用同一組帳戶，才不會出現
    「圓環加起來不等於總資產」。
    """
    positive = sorted(
        (item for item in accounts if int(item["balance_minor"]) > 0),
        key=lambda item: (-int(item["balance_minor"]), str(item["name"])),
    )
    negative = tuple(item for item in accounts if int(item["balance_minor"]) < 0)
    total = sum(int(item["balance_minor"]) for item in positive)
    if not positive:
        return ShareBreakdown(shares=(), negative=negative, positive_total_minor=0)

    if len(positive) > MAX_SLICES:
        head = positive[: MAX_SLICES - 1]
        tail = positive[MAX_SLICES - 1 :]
        entries = [(str(item["name"]), int(item["balance_minor"])) for item in head]
        entries.append(
            (
                f"{OTHERS_LABEL}（{len(tail)} 個帳戶）",
                sum(int(item["balance_minor"]) for item in tail),
            )
        )
    else:
        entries = [(str(item["name"]), int(item["balance_minor"])) for item in positive]

    palette = slice_colors(len(entries))
    return ShareBreakdown(
        shares=tuple(
            Share(
                name=name,
                balance_minor=balance,
                ratio=balance / total,
                color=palette[index],
            )
            for index, (name, balance) in enumerate(entries)
        ),
        negative=negative,
        positive_total_minor=total,
    )


def slice_colors(count: int) -> tuple[str, ...]:
    """`count` 片要用色階裡的哪幾個。

    **不是直接拿前 `count` 個。** 三片的時候拿前三階，最大與第二大只差一個色階
    （對比 1.23）—— 實機上看起來就是兩片一樣的淺灰（2026-08-23 截圖）。
    改成在整條梯度上**平均取樣**：三片拿頭、中、尾，兩片拿最淺與最深。
    片數少的時候對比反而最大，而片數少正是使用者最想一眼比出來的時候。
    """
    if count <= 0:
        return ()
    if count == 1:
        return (colors.CHART_SLICES[0],)
    last = len(colors.CHART_SLICES) - 1
    return tuple(
        colors.CHART_SLICES[round(index * last / (count - 1))] for index in range(count)
    )


def ratio_text(ratio: float) -> str:
    """占比的顯示字串。

    **一律一位小數，包含 `100.0%`。** 位數會跳的數字排成一欄時右邊對不齊，
    而這一欄的用途就是拿來互相比較。
    """
    return f"{ratio * 100:.1f}%"


class ShareRing(QWidget):
    """圓環本體。只畫圖，一個字都不寫 —— 文字全部在圖例那一側。"""

    def __init__(self) -> None:
        super().__init__()
        self._shares: tuple[Share, ...] = ()
        self.setFixedSize(RING_SIZE, RING_SIZE)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(RING_SIZE, RING_SIZE)

    def set_shares(self, shares: tuple[Share, ...]) -> None:
        self._shares = shares
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """一片一次 `drawArc`，用粗筆畫弧線就是圓環。

        **不用「畫實心餅再挖一個洞」。** 那要多一次填色，而且中間那個洞得填成
        底色 —— 底色一改（或某一天這張圖被放到別的底上）就會露出一圈錯的顏色。
        畫弧線的話中間本來就沒有東西。

        Qt 的角度單位是 1/16 度，0 度在三點鐘方向、正值逆時針。要「從 12 點鐘
        順時針」就是 `90 * 16` 起跳、`span` 取負。
        """
        if not self._shares:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = RING_THICKNESS / 2
        box = QRectF(
            inset,
            inset,
            self.width() - RING_THICKNESS,
            self.height() - RING_THICKNESS,
        )
        # 只有一片的時候不縮 —— 一個完整的圓不該在正上方裂一條沒有意義的縫。
        gap = GAP_DEGREES if len(self._shares) > 1 else 0.0
        start = 90.0
        for share in self._shares:
            span = share.ratio * 360.0
            pen = QPen(QColor(share.color))
            pen.setWidth(RING_THICKNESS)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(
                box,
                round((start - gap / 2) * 16),
                round(-(span - gap) * 16),
            )
            start -= span
        painter.end()


def _swatch(color: str) -> QPixmap:
    """圖例的色塊。

    **畫成 QPixmap，不走 QSS。** `test_resources.py` 會掃 `styles.qss` 裡的每一個
    色碼並要求它在 `colors.ALL_TOKENS` 裡，而 `CHART_SLICES` 刻意不在那份清單上
    （那是 QSS 的允許清單）。畫進 pixmap 就完全不經過樣式表。
    """
    pixmap = QPixmap(SWATCH_SIZE, SWATCH_SIZE)
    pixmap.fill(QColor(color))
    return pixmap


class ShareLegend(QWidget):
    """圖例：一列是「色塊｜名稱｜金額｜占比」。

    **用真的 QLabel，不自繪文字。** 中文的字寬、字型 fallback 與截字交給 Qt，
    測試也才能照專案慣例量 geometry（`label.width() >= horizontalAdvance(text)`）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[QLabel, QLabel, QLabel]] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(1, 1)

    def set_shares(self, shares: tuple[Share, ...]) -> None:
        """整份重建。

        列數會變（帳戶增減、跨過「其他」的門檻），而重用舊列就要處理「多的那幾列
        要不要隱藏」—— 隱藏的 QLabel 仍然佔著 grid 的一列高度。列數是個位數，
        重建的成本遠低於維護那個狀態。
        """
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.rows = []

        for index, share in enumerate(shares):
            swatch = QLabel()
            swatch.setPixmap(_swatch(share.color))
            swatch.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
            name = QLabel(share.name)
            name.setObjectName("legendName")
            amount = QLabel(group_digits(share.balance_minor))
            amount.setObjectName("legendAmount")
            amount.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            ratio = QLabel(ratio_text(share.ratio))
            ratio.setObjectName("legendRatio")
            ratio.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._grid.addWidget(swatch, index, 0)
            self._grid.addWidget(name, index, 1)
            self._grid.addWidget(amount, index, 2)
            self._grid.addWidget(ratio, index, 3)
            self.rows.append((name, amount, ratio))


class AssetShareChart(QWidget):
    """圓環 ＋ 圖例。資產總覽只需要認識這一個東西。

    `set_accounts()` 回傳這一次算出來的 `ShareBreakdown`，頁面拿它去寫負餘額那一
    行字 —— 兩邊因此一定用同一份計算結果，不會出現「圖上畫了五片、字裡說四個」。
    """

    def __init__(self) -> None:
        super().__init__()
        self.ring = ShareRing()
        self.legend = ShareLegend()
        self.caption = QLabel()
        self.caption.setObjectName("hintLabel")
        # **不開 `setWordWrap`。** 這是一句話，而會換行的 QLabel 的 sizeHint 是一個
        # 「大致方形」的啟發值 —— 開了之後它會在還有一大片空白的情況下自己斷成兩行
        # （`pages/overview.py::_action_row` 踩過同一顆）。
        self.caption.setWordWrap(False)
        self.legend.setMaximumWidth(LEGEND_WIDTH)
        self._build()

    def _build(self) -> None:
        legend_column = QVBoxLayout()
        legend_column.setContentsMargins(0, 0, 0, 0)
        legend_column.addWidget(self.legend)
        legend_column.addWidget(self.caption)
        legend_column.addStretch()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignTop)
        layout.addSpacing(20)
        # **圖例不吃剩餘寬度**，剩下的由呼叫端的 `addStretch()` 收掉。給它 stretch
        # 的話「名稱」那一欄會把金額與占比推到頁面最右邊。
        layout.addLayout(legend_column, 0)
        layout.addStretch()

    def set_accounts(self, accounts: list[dict[str, Any]]) -> ShareBreakdown:
        breakdown = build_shares(accounts)
        self.ring.set_shares(breakdown.shares)
        self.legend.set_shares(breakdown.shares)
        self.caption.setText(
            f"占比以正餘額合計 {group_digits(breakdown.positive_total_minor)} TWD 為分母。"
            if breakdown.negative
            else ""
        )
        # 沒有負餘額帳戶時，分母就等於總資產 —— 再寫一次只是重複頁面上那個大數字。
        self.caption.setVisible(bool(breakdown.negative))
        return breakdown
