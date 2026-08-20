"""守門：分層邊界與檔案大小。

`AGENTS.md` 的「架構邊界」一節寫的是規則，這裡是讓規則會失敗的地方。純文字的規則會
隨著時間被違反 —— 通常不是有人決定不遵守，而是某天為了趕一個小功能就直接在 UI 裡寫
一行 SQL，然後沒人發現。

用 AST 而不是純文字比對：`import` 要看真的 import 了什麼，不是原始碼裡出現什麼字。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "tagcor_ledger"

# 只挑「不會出現在正常英文散文裡」的形狀，避免對註解與說明文字誤報。
SQL_PATTERNS = [
    re.compile(r"\bSELECT\b.+\bFROM\b", re.DOTALL),
    re.compile(r"\bINSERT\s+INTO\b"),
    re.compile(r"\bUPDATE\b.+\bSET\b", re.DOTALL),
    re.compile(r"\bDELETE\s+FROM\b"),
    re.compile(r"\bCREATE\s+(TABLE|INDEX|VIRTUAL\s+TABLE)\b"),
    re.compile(r"\bPRAGMA\s+\w"),
]

# 檔案行數上限。這是煙霧偵測器，不是規矩 —— 一個內聚的 700 行檔案沒有問題，
# 但一個檔案長到這個地步時，值得停下來問「它是不是裝了兩件事」。
#
# 門檻怎麼來的：2026-08 拆檔前 `main_window_phase12.py` 是 2,114 行、
# `sqlite_store.py` 是 1,381 行，兩個都是無聲長大的。拆完之後最大的檔案是 589 行
# （`automation_store.py`，這次沒動它），所以 700 留了一點餘裕又遠低於出事的量級。
MAX_MODULE_LINES = 700


def _modules(*relative: str) -> list[Path]:
    files: list[Path] = []
    for part in relative:
        files.extend(sorted((SOURCE_ROOT / part).rglob("*.py")))
    return [path for path in files if "__pycache__" not in path.parts]


def _imported_roots(path: Path) -> set[str]:
    """這個模組 import 了哪些頂層模組（`a.b.c` 也一併收 `a` 與 `a.b`）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            parts = name.split(".")
            for index in range(1, len(parts) + 1):
                roots.add(".".join(parts[:index]))
    return roots


def _sql_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if any(pattern.search(node.value) for pattern in SQL_PATTERNS):
            found.append(" ".join(node.value.split())[:70])
    return found


def test_extractors_work_on_a_known_module() -> None:
    """陽性對照：抽取邏輯壞掉時這裡先失敗，而不是讓底下的檢查靜默通過。"""
    store = SOURCE_ROOT / "infrastructure" / "stores" / "accounts.py"
    assert "sqlite3" in _imported_roots(store)
    assert "tagcor_ledger.infrastructure.database" in _imported_roots(store)
    assert _sql_strings(store), "infrastructure 的 store 一定有 SQL，抓不到代表偵測器壞了"


def test_domain_depends_on_nothing_but_itself() -> None:
    """domain 是最內層：不得認得 Qt、SQLite，也不得認得其他任何一層。"""
    forbidden = {
        "PySide6",
        "sqlite3",
        "tagcor_ledger.app",
        "tagcor_ledger.application",
        "tagcor_ledger.infrastructure",
        "tagcor_ledger.ui",
    }
    offenders: list[str] = []
    for path in _modules("domain"):
        for name in sorted(_imported_roots(path) & forbidden):
            offenders.append(f"  {path.relative_to(PROJECT_ROOT)} -> {name}")
    if offenders:
        pytest.fail("domain 不得依賴外層或具體技術：\n" + "\n".join(offenders))


def test_only_the_ui_layer_knows_about_qt() -> None:
    """涵蓋 `ui/` 以外的**全部**模組，包含根目錄的 `main.py`。

    最初這個測試只掃四個子套件，`main.py` 因此漏掉 —— Stage 4 加啟動失敗對話框時就真的
    在那裡 import 了 PySide6。範圍寫成「除了 ui 以外都要檢查」才不會再有這種縫。
    """
    offenders: list[str] = []
    for path in _modules(""):
        relative = path.relative_to(SOURCE_ROOT)
        if relative.parts and relative.parts[0] == "ui":
            continue
        if "PySide6" in _imported_roots(path):
            offenders.append(f"  {path.relative_to(PROJECT_ROOT)}")
    if offenders:
        pytest.fail("只有 ui/ 可以 import PySide6：\n" + "\n".join(offenders))


def test_nothing_below_the_ui_imports_the_ui() -> None:
    offenders: list[str] = []
    for path in _modules("app", "application", "domain", "infrastructure"):
        if "tagcor_ledger.ui" in _imported_roots(path):
            offenders.append(f"  {path.relative_to(PROJECT_ROOT)}")
    if offenders:
        pytest.fail("依賴方向只能由外往內，ui 不得被下層 import：\n" + "\n".join(offenders))


def test_ui_layer_contains_no_sql() -> None:
    """UI 要查資料就經過 controller 與 application，不自己寫 SQL。"""
    paths = _modules("ui")
    assert len(paths) > 10, "掃描路徑寫錯了，根本沒掃到 ui 模組"
    offenders: list[str] = []
    for path in paths:
        for statement in _sql_strings(path):
            offenders.append(f"  {path.relative_to(PROJECT_ROOT)}: {statement}")
    if offenders:
        pytest.fail("ui/ 不得直接撰寫 SQL：\n" + "\n".join(offenders))


def test_no_module_grows_back_into_a_monolith() -> None:
    oversized: list[str] = []
    for path in _modules(""):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > MAX_MODULE_LINES:
            oversized.append(f"  {path.relative_to(PROJECT_ROOT)}：{lines} 行")
    if oversized:
        pytest.fail(
            f"以下模組超過 {MAX_MODULE_LINES} 行，先確認它是不是裝了不只一件事：\n"
            + "\n".join(oversized)
        )


# UI 上不該再出現的字，以及該用的字。
# **鍵是實作的名字，值是使用者腦子裡的名字。** 程式識別字（`recurring_schedules`、
# `schedule_id`）不在此限 —— 那是 schema，改它要 migration，而使用者看不到它。
RETIRED_UI_WORDS = {
    "排程": "定期收支",
    "快速記帳": "記帳",
}


def _value_strings(path: Path) -> list[str]:
    """這個模組裡**當成值用**的字串常數。

    裸的字串陳述式（module／class／def 的 docstring，以及常數底下那種說明字串）
    一律不算 —— 那是寫給開發者看的，本來就該用實作的名字討論實作。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    documentation = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in documentation
    ]


def test_extractor_separates_documentation_from_values() -> None:
    """陽性對照：抽取邏輯壞掉時這裡先失敗，而不是讓底下的檢查靜默通過。"""
    page = SOURCE_ROOT / "ui" / "pages" / "recurring.py"
    values = _value_strings(page)
    assert "新增定期收支" in values, "抓不到按鈕文字，抽取器壞了"
    assert not any("為什麼改叫" in value for value in values), "docstring 被當成值抓進來了"


def test_ui_does_not_use_retired_wording() -> None:
    """UI 的字串常數不得出現已經淘汰的用詞。

    這條攔的是**漏改**。2026-08-20 把「週期排程」改成「定期收支」時，分頁標籤與按鈕都
    改了，但重製確認框裡那份 `COUNT_LABELS` 差點漏掉 —— 那一行只有在按下「重製」時
    才看得到，實機點過去的機率很低。
    """
    offenders: list[str] = []
    for path in _modules("ui"):
        for value in _value_strings(path):
            for retired, replacement in RETIRED_UI_WORDS.items():
                if retired in value:
                    offenders.append(
                        f"  {path.relative_to(PROJECT_ROOT)}：{value!r}"
                        f"（「{retired}」應為「{replacement}」）"
                    )
    if offenders:
        pytest.fail("UI 字串裡還有淘汰的用詞：\n" + "\n".join(offenders))
