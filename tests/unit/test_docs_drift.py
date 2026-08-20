"""守門：文件裡的頁面名稱必須跟程式一致。

`docs/architecture/ui-workflows.md` 是「側邊欄順序與各頁流程」的權威文件，而它在
2026-08-20 之前已經漂到**整份都是錯的**：側邊欄順序是舊的、寫「時間」（v0.13.0 已改成
日期）、字體寫 `Segoe UI Variable`（已改成 Microsoft JhengHei UI）、還留著「重製與還原」
這個已經拆開的分頁名。沒有人做錯什麼 —— 只是改程式的時候沒有任何東西提醒要改文件。

**這裡做的是逐字比對，不做推論。** 名稱的正本是 `navigation.LABELS` 與
`OperationSettingsPage._tabs()`；這份測試只問「這個字串有沒有出現在那份文件裡」。
比對範圍刻意窄 —— 一個會誤報的守門比沒有守門更糟，因為你會學會忽略它。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tagcor_ledger.ui.navigation import ALL_PAGES, LABELS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UI_WORKFLOWS = PROJECT_ROOT / "docs" / "architecture" / "ui-workflows.md"
OPERATION_SETTINGS = (
    PROJECT_ROOT / "src" / "tagcor_ledger" / "ui" / "pages" / "operation_settings.py"
)


def _settings_tab_labels() -> list[str]:
    """從 `_tabs()` 的原始碼取出六個分頁名。

    **用 AST 讀原始碼，不 import 之後去建 widget** —— 這個測試在 `tests/unit`，
    不該需要 QApplication。
    """
    tree = ast.parse(OPERATION_SETTINGS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_tabs":
            return [
                element.elts[1].value
                for element in ast.walk(node)
                if isinstance(element, ast.Tuple)
                and len(element.elts) == 2
                and isinstance(element.elts[1], ast.Constant)
                and isinstance(element.elts[1].value, str)
            ]
    raise AssertionError("找不到 OperationSettingsPage._tabs()，抽取器要跟著改")


def test_the_extractor_finds_the_six_tabs() -> None:
    """陽性對照：抽不到名字的話，底下那條會空過。"""
    labels = _settings_tab_labels()
    assert len(labels) == 6, labels
    assert "定期收支" in labels


def test_every_page_name_appears_in_the_ui_workflows_doc() -> None:
    """側邊欄八頁與操作設定六個分頁的名字，都要逐字出現在頁面地圖那份文件裡。"""
    document = UI_WORKFLOWS.read_text(encoding="utf-8")
    expected = [LABELS[page] for page in ALL_PAGES] + _settings_tab_labels()

    missing = [name for name in expected if name not in document]
    if missing:
        pytest.fail(
            "這些頁面名稱在 docs/architecture/ui-workflows.md 裡找不到：\n"
            + "\n".join(f"  {name}" for name in missing)
            + "\n改了 navigation.LABELS 或操作設定的分頁名，要一起改那份文件。"
        )


def test_the_doc_does_not_still_name_pages_that_are_gone() -> None:
    """舊名字要真的消失，不是新舊並存。

    只加新的、不刪舊的，文件會變成「兩份都對不上現況」—— 比只有舊的更難判斷。
    """
    document = UI_WORKFLOWS.read_text(encoding="utf-8")
    retired = ["快速記帳", "模板與週期排程", "重製與還原"]
    offenders = [name for name in retired if name in document]
    assert not offenders, f"ui-workflows.md 裡還有已經不存在的頁面名：{offenders}"
