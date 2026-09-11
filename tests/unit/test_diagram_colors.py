"""守門：**架構圖用的顏色，必須是這個 app 真的在用的顏色。**

`tools/diagrams/mermaid-config.json` 的 `themeVariables` 是**手抄**的 ——
建那支腳本的時候有人從 `colors.py` 複製了幾個色碼過去。
而 `colors.py` 改過，那份複本不會跟著改，**也沒有任何東西會說**：
色碼是合法的顏色，圖看起來也很正常。

2026-09-11 回頭對的時候抓到一個：`tertiaryColor` 是 `#26262E`，
而 `SELECTED` 早就改成 `#2E2E38` 了（改的理由寫在 `colors.py` 那一段
docstring 裡 —— `#26262E` 對一般列底的對比只有 1.20，看不出哪一列被選中）。

## 為什麼不能對整個 `colors.py` 做字串搜尋

**那個舊值就躺在 docstring 裡。** 一個「檔案裡找得到這個色碼」的檢查
會在那句歷史說明上得到假的通過 —— 而那正是這一條要抓的東西。
所以這裡讀的是**模組真的宣告出來的常數**，不是檔案內容。

## 為什麼是「弱形式」

只驗**包含關係**：宣告的每個色碼都要在色票裡存在。不驗「哪個 token 對應到
哪個 `themeVariable`」—— 那是設計判斷，而且 mermaid 的 primary／secondary／
tertiary 跟這個 app 的語意（表面／線／文字／金額）本來就對不起來。
強形式會逼人寫一份對照表，而那份對照表本身就是第二份會漂的手抄本。

> 同一條規則在 `cyclosa` 與 `webscouts` 各有一份（各自對它們的色票正本）。
> **三份是抄的，不是共用套件** —— 三個 repo 的色票格式不同，
> 抽出去會造出一條跨專案相依。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tagcor_ledger.ui import colors

HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "tools" / "diagrams" / "mermaid-config.json"


def declared_palette() -> set[str]:
    """`colors.py` 真的宣告出來的每一個色碼，正規化成大寫。

    **走模組的屬性，不走檔案內容** —— 見模組 docstring。
    `ALL_TOKENS` 一個人不夠：它是 **QSS 的允許清單**，`CHART_SLICES`
    刻意不在裡面（圓環是 `QPainter` 畫的，一個字都不經過 QSS）。
    圖表配色可以用到色票裡的任何一個顏色，所以這裡收全部。
    """
    palette: set[str] = set()
    for name in dir(colors):
        if name.startswith("_"):
            continue
        value = getattr(colors, name)
        if isinstance(value, str):
            candidates: tuple[str, ...] = (value,)
        elif isinstance(value, (tuple, frozenset, set, list)):
            candidates = tuple(v for v in value if isinstance(v, str))
        else:
            continue
        for candidate in candidates:
            if HEX_COLOR.fullmatch(candidate):
                palette.add(candidate.upper())
    return palette


def theme_colours() -> set[str]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    blob = json.dumps(config.get("themeVariables", {}))
    return {match.group(0).upper() for match in HEX_COLOR.finditer(blob)}


def test_the_palette_and_the_theme_are_both_non_empty() -> None:
    """掃不到東西的檢查永遠會過 —— 零命中跟規則壞掉長得一模一樣。"""
    assert len(declared_palette()) >= 10, "色票掃不出來，`colors.py` 的形狀變了？"
    assert len(theme_colours()) >= 5, "配色檔掃不出色碼，正規表示式或路徑壞了"


def test_every_diagram_colour_is_a_declared_token() -> None:
    """`mermaid-config.json` 裡不得出現 `colors.py` 沒宣告的色碼。"""
    unknown = sorted(theme_colours() - declared_palette())
    assert not unknown, f"這些色碼不在 colors.py 裡：{unknown}"


def test_the_check_would_catch_the_one_that_was_stale() -> None:
    """**注入一次真違規。**

    上面那一條修完之後是零命中，而零命中跟規則壞掉在測試報告上長得一樣。
    這一條把 2026-09-11 修掉的那個色碼餵回去，確認判準真的認得出來 ——
    **而且確認它沒有被 docstring 裡那句歷史說明騙過去。**
    """
    stale = "#26262E"
    assert stale not in declared_palette(), f"{stale} 又變成一個真的 token 了"
    assert stale in CONFIG_PATH.parent.parent.parent.joinpath(
        "src", "tagcor_ledger", "ui", "colors.py"
    ).read_text(encoding="utf-8"), "那句解釋為什麼換掉 #26262E 的說明不見了"
