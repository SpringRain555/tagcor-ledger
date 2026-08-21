"""守門：`.md` 裡的 mermaid 原始碼與產生出來的 SVG 必須同步。

圖是**產生物**，而產生物一定會漂：改了圖的原始碼卻忘了重跑工具，版控裡那張 SVG 就
還是舊的 —— 而看圖的人不會知道自己看的是過期的東西。

**這條測試不需要 node。** 它只比對 SHA-256，所以 `Verify.ps1` 照樣跑得動；
真正要 node 的是 `tools/diagrams/Render-Diagrams.ps1`，那支人手動跑。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = PROJECT_ROOT / "docs" / "architecture"
DIAGRAMS_DIR = DOCS_DIR / "diagrams"
MANIFEST = DIAGRAMS_DIR / "manifest.json"
RERUN = "跑 .\\tools\\diagrams\\Render-Diagrams.ps1 重新產生。"


def _blocks(path: Path) -> list[str]:
    """抓出一份 `.md` 裡所有的 ```mermaid 區塊，回傳每一段的原始碼。

    **切法要與 `Render-Diagrams.ps1` 一模一樣**：逐行掃、以 ``` 收尾、用 `\\n` 接回去。
    兩邊不一致的話 hash 永遠對不上，而那會變成一條每次都紅、於是被學會忽略的守門。
    """
    found: list[str] = []
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if current is None:
            if line.rstrip() == "```mermaid":
                current = []
            continue
        if line.rstrip() == "```":
            found.append("\n".join(current))
            current = None
            continue
        current.append(line)
    assert current is None, f"{path.name} 裡有一個 ```mermaid 區塊沒有收尾"
    return found


def _expected() -> list[tuple[str, int, str]]:
    """(文件名, 第幾張, sha256)，順序與工具一致（檔名排序、文件內由上而下）。"""
    rows: list[tuple[str, int, str]] = []
    for document in sorted(DOCS_DIR.glob("*.md")):
        for index, source in enumerate(_blocks(document), start=1):
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            rows.append((document.name, index, digest))
    return rows


def test_the_extractor_actually_finds_mermaid_blocks() -> None:
    """陽性對照：抽不到圖的話，底下每一條都會空過。"""
    rows = _expected()
    assert len(rows) >= 8, f"只抽到 {len(rows)} 張圖，抽取器或文件路徑不對"
    documents = {name for name, _, _ in rows}
    assert "state-machines.md" in documents, documents
    # 沒有 mermaid 的文件不該憑空長出一張空白圖 —— 工具那邊就是這樣錯過一次。
    assert "error-codes.md" not in documents, "沒有圖的文件被當成有一張圖了"


def test_every_diagram_has_an_up_to_date_svg() -> None:
    """每一段 mermaid 都要有對應的 SVG，而且 SVG 是用**現在這一版**原始碼產的。"""
    assert MANIFEST.exists(), f"找不到 {MANIFEST.relative_to(PROJECT_ROOT)}。{RERUN}"
    recorded = {
        (item["document"], int(item["index"])): item
        for item in json.loads(MANIFEST.read_text(encoding="utf-8"))["diagrams"]
    }
    expected = _expected()

    missing: list[str] = []
    stale: list[str] = []
    for document, index, digest in expected:
        item = recorded.get((document, index))
        if item is None:
            missing.append(f"  {document} 第 {index} 張圖還沒產生過")
            continue
        if item["sha256"] != digest:
            stale.append(f"  {item['svg']}（{document} 第 {index} 張）")
        svg = DIAGRAMS_DIR / str(item["svg"])
        if not svg.exists():
            missing.append(f"  {item['svg']} 在 manifest 裡但檔案不見了")

    orphans = [
        f"  {item['svg']}"
        for key, item in recorded.items()
        if key not in {(doc, idx) for doc, idx, _ in expected}
    ]

    problems = missing + stale + orphans
    if problems:
        pytest.fail(
            "文件裡的 mermaid 與產生出來的 SVG 對不上：\n"
            + "\n".join(problems)
            + f"\n{RERUN}"
        )


def test_the_manifest_is_utf8_without_bom() -> None:
    """`.json` 一律 UTF-8 **無 BOM**（`AGENTS.md` 的「語言與編碼」）。"""
    assert not MANIFEST.read_bytes().startswith(b"\xef\xbb\xbf")


def test_svgs_carry_real_text_not_html_labels() -> None:
    """SVG 的文字要是 `<text>`，**不能是 `<foreignObject>`**。

    mermaid 預設用 HTML label（`htmlLabels: true`），那會把文字塞進 `<foreignObject>`
    —— 瀏覽器看得到，但很多 SVG 檢視器（含 Qt 自己的 renderer）只會畫出空白方框。
    圖進版控的目的就是給沒有 node 的人看，所以這裡必須是純 SVG 文字。

    設定在 `tools/diagrams/mermaid-config.json` 的 `htmlLabels: false`。
    """
    checked = 0
    for svg in sorted(DIAGRAMS_DIR.glob("*.svg")):
        content = svg.read_text(encoding="utf-8")
        assert "foreignObject" not in content, (
            f"{svg.name} 用了 foreignObject —— 檢查 mermaid-config.json 的 htmlLabels"
        )
        assert "<text" in content, f"{svg.name} 裡沒有任何文字"
        checked += 1
    assert checked >= 8, f"只檢查到 {checked} 個 SVG"
