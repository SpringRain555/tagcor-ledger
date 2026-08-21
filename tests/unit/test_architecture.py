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
# `sqlite_store.py` 是 1,381 行，兩個都是無聲長大的。拆完之後最大的檔案是 589 行，
# 所以 700 留了一點餘裕又遠低於出事的量級。目前最大的是 `application/deposits.py`。
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


# 「一筆交易長什麼樣」只能有一個地方說了算。key 是那段 SQL 的特徵，
# value 是**唯一**允許寫它的模組（相對 SOURCE_ROOT）。三者都在 `stores/base.py`：
# 交易列、FTS 索引與稽核列是同一次寫入的三個部分，拆開放就會像以前那樣各自分岔。
SINGLE_WRITER_TABLES = {
    "INSERT INTO transactions(": "infrastructure/stores/base.py",
    "INSERT INTO transaction_fts(": "infrastructure/stores/base.py",
    "INSERT INTO audit_events(": "infrastructure/stores/base.py",
}

# migration 會在建表與改表時重建 FTS 索引（v5 拿掉 payee 欄位之後就重灌了一次）。
# 那是 schema 演進，不是執行期的寫入路徑，兩者不該混為一談。
SINGLE_WRITER_EXEMPT = {"infrastructure/migrations.py"}


def test_only_one_module_writes_a_transaction() -> None:
    """交易、FTS 索引與稽核列各只有一個寫入點。

    2026-08 之前有兩個：`automation_store.py` 自己重寫了一份「建立交易」
    —— transactions 列 ＋ postings ＋ allocation ＋ FTS，約 70 行。代價不是重複，
    是**分岔**：兩份 `_refresh_fts` 的 SQL 一字不差，但只有一份會先 `DELETE`；
    兩份 `_audit` 只有一份收 `correlation_id`，另一份自己 `uuid4()` 生一個新的，
    於是 `occurrence.confirm` 的稽核列與它建立的交易串不起來。

    **這條守門比「不要複製貼上」有用的地方在於它擋的是後果**：schema 改一次要改
    幾個地方，答案必須是一。
    """
    offenders: list[str] = []
    seen = 0
    for path in _modules("infrastructure"):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        if relative in SINGLE_WRITER_EXEMPT:
            continue
        source = path.read_text(encoding="utf-8")
        for needle, owner in SINGLE_WRITER_TABLES.items():
            if needle not in source:
                continue
            seen += 1
            if relative != owner:
                offenders.append(f"  {relative} 寫了 {needle.rstrip('(')} —— 只有 {owner} 可以")
    assert seen >= len(SINGLE_WRITER_TABLES), (
        f"連正主都沒掃到（只找到 {seen} 處），比對字串或掃描路徑寫錯了"
    )
    if offenders:
        pytest.fail(
            "這些表只能有一個寫入點：\n"
            + "\n".join(offenders)
            + "\n要寫交易就呼叫 StoreBase 的共用寫入器，不要再開一條路。"
        )


def test_every_store_lives_in_the_stores_package() -> None:
    """store 一律放在 `infrastructure/stores/`，不要散在 `infrastructure/` 根目錄。

    `automation_store.py` 曾經是唯一的例外，而它同時也是唯一一個沒有被
    `LedgerStore` 組起來、自己重寫建交易路徑的 store。**位置跑掉與行為跑掉是同一件事**
    —— 沒有跟兄弟放在一起的東西，也不會跟兄弟用同一套做法。
    """
    # `LedgerStore` 是刻意的例外：它不是聚合，只負責把聚合組起來。
    allowed_outside = {"infrastructure/sqlite_store.py": {"LedgerStore"}}

    found: list[str] = []
    strays: list[str] = []
    for path in _modules("infrastructure"):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Store"):
                continue
            found.append(f"{relative}::{node.name}")
            if path.parent.name == "stores":
                continue
            if node.name in allowed_outside.get(relative, set()):
                continue
            strays.append(f"  {relative}::{node.name}")

    assert len(found) >= 6, f"掃描路徑寫錯了，只找到 {found}"
    if strays:
        pytest.fail(
            "store 一律放在 infrastructure/stores/：\n"
            + "\n".join(strays)
            + "\n（唯一例外是 sqlite_store.py 的 LedgerStore，它只負責組裝。）"
        )


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
    # 第一層叫「類別」、第二層叫「項目」，所以項目的那一欄是**它屬於誰**，
    # 不是「它上面還有一層」。列表的表頭一直都寫「所屬類別」，只有新增項目的
    # 對話框寫「上層類別」—— 同一件事在同一個分頁裡有兩個名字。
    "上層類別": "所屬類別",
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


# 日期欄的唯一工廠。`QDateEdit` 直接建出來的話，`date_field()` 裡那些防護
# （關掉上下鍵、日期範圍、日曆彈窗的設定）就完全沒有套到。
DATE_FIELD_FACTORY = "ui/widgets/forms.py"


def _constructor_calls(path: Path, name: str) -> int:
    """這個模組直接呼叫 `name(...)` 幾次。**看 AST 的 Call 節點，不做字串比對** ——
    `from PySide6.QtWidgets import QDateEdit` 這種 import 本身不算，型別註解也不算。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def test_the_constructor_extractor_actually_finds_calls() -> None:
    """陽性對照：抽取器認不出 `QDateEdit(...)` 的話，底下那條會空過。"""
    factory = SOURCE_ROOT / DATE_FIELD_FACTORY
    assert _constructor_calls(factory, "QDateEdit") >= 1, (
        "工廠自己一定會呼叫 QDateEdit()，抽不到就是抽取器壞了"
    )
    assert _constructor_calls(factory, "QDoesNotExist") == 0


def test_every_date_input_comes_from_the_shared_factory() -> None:
    """**`ui/` 底下不得直接建 `QDateEdit`**，一律用 `forms.date_field()`。

    理由不是「統一比較好看」，是 `date_field()` 擋掉了一個 Qt 與 QSS 交互作用的
    誤觸：`QDateTimeEdit` 在 `calendarPopup` 模式下用 CC_ComboBox 做命中測試，但
    `SC_ComboBoxFrame` 與 `SC_SpinBoxUp` 是**同一個數字**，於是點在 QSS 給的那圈
    內距上會被讀成「按了上箭頭」，把年份加一（點文字上則是減一）。
    工廠用 `setButtonSymbols(NoButtons)` 把那條路斷掉。

    2026-08-21 之前有**七個**欄位繞過工廠（交易紀錄的日期區間 2、定存頁 3、
    模板／定期收支的起訖日 2），所以「修好了」只會修到記帳頁那一個。
    """
    offenders: list[str] = []
    for path in _modules("ui"):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        if relative == DATE_FIELD_FACTORY:
            continue
        count = _constructor_calls(path, "QDateEdit")
        if count:
            offenders.append(f"  {relative} 直接建了 {count} 個 QDateEdit")
    if offenders:
        pytest.fail(
            "日期欄一律用 `forms.date_field()`，不要自己 `QDateEdit(...)`：\n"
            + "\n".join(offenders)
        )
