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
# `sqlite_store.py` 是 1,381 行，兩個都是無聲長大的。700 留了一點餘裕又遠低於
# 出事的量級。
#
# **這裡不寫「目前最大的是哪一個檔案」。** 那句話寫過一次，然後在
# `ui/controller.py` 長到 700 行的時候就過期了 —— 而註解過期不會有任何東西提醒你。
# 要知道當下的排名，看失敗訊息，它會現算。
MAX_MODULE_LINES = 700

# 測試檔的上限放寬到 1200：測試本來就比實作長（每一條都要自己準備資料與斷言），
# 用同一個 700 只會逼出「為了過門檻而切一半」這種沒有意義的切法。
#
# 2026-08-22 加這條之前，`tests/ui/test_main_window.py` 已經長到 **2,153 行 66 條**，
# 涵蓋八個頁面 —— 因為行數守門只掃 `src/`，沒有任何東西擋它。
MAX_TEST_LINES = 1200


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


# controller 的組裝檔。它只能宣告 `LedgerController` 繼承哪幾段，不能自己長方法。
CONTROLLER_PACKAGE = "tagcor_ledger.ui.controller"


def test_the_controller_assembly_file_holds_no_logic() -> None:
    """`ui/controller/__init__.py` 不得定義任何函式或方法。

    2026-08-22 拆檔之前 `ui/controller.py` 是 700 行，**剛好貼著上限** ——
    上一版是靠壓縮註解才過關的。拆成套件之後，最可能的退化路徑就是「這個方法很短，
    先放組裝檔就好」，然後組裝檔慢慢變回原本那個檔案。
    """
    path = SOURCE_ROOT / "ui" / "controller" / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    assert not defined, (
        f"ui/controller/__init__.py 定義了 {defined} —— 組裝檔只放 class 陳述，"
        "方法請放到對應的 section 模組"
    )


def test_every_controller_method_lives_in_a_section_module() -> None:
    """`LedgerController` 的每一個方法都必須定義在某一個 section 模組裡。

    這條與上面那條是一組：上面擋「組裝檔長方法」，這條擋「方法跑到套件外面去」
    （例如有人為了方便把一個 helper 放回 `ui/formatting.py` 再混進來）。
    """
    from tagcor_ledger.ui.controller import LedgerController

    strays: list[str] = []
    checked = 0
    for name in dir(LedgerController):
        if name.startswith("__"):
            continue
        owner = next(
            (klass for klass in LedgerController.__mro__ if name in vars(klass)), None
        )
        if owner is None or not callable(vars(owner)[name]):
            continue
        checked += 1
        module = owner.__module__
        if not module.startswith(f"{CONTROLLER_PACKAGE}.") or module == CONTROLLER_PACKAGE:
            strays.append(f"  {name}（定義在 {module}）")

    assert checked >= 50, f"只掃到 {checked} 個方法，抽取邏輯可能壞了"
    if strays:
        pytest.fail(
            "controller 的方法必須住在 ui/controller/ 底下的 section 模組：\n"
            + "\n".join(strays)
        )


def test_no_page_builds_its_own_table_row() -> None:
    """「一列長什麼樣」只由 `ui/formatting/` 決定，`ui/pages/` 不得自己定義 `*_values`。

    同一個狀態一旦有兩個拼法，兩張表就會對同一筆資料講不同的話 —— 而那種不一致
    很難在畫面上看出來，因為兩張表通常不會同時出現在眼前。

    抓的是**函式定義**不是呼叫：頁面當然要呼叫這些函式，它只是不能自己寫一個。

    判準是「名字以 `_values` 結尾**而且真的 `return [...]`**」，不是只看名字 ——
    `CatalogPage._values` 是子類要填的抽象掛鉤（`raise NotImplementedError`），
    子類填的是 `staticmethod(account_values)`，那正是我們要的做法。
    """
    offenders: list[str] = []
    checked = 0
    for path in _modules("ui/pages"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            checked += 1
            if not node.name.endswith("_values"):
                continue
            builds_a_row = any(
                isinstance(inner, ast.Return) and isinstance(inner.value, ast.List)
                for inner in ast.walk(node)
            )
            if builds_a_row:
                offenders.append(f"  {path.relative_to(PROJECT_ROOT)}::{node.name}")
    assert checked >= 50, f"只掃到 {checked} 個函式，掃描路徑可能寫錯了"
    if offenders:
        pytest.fail(
            "頁面不得自己拼列內容，請放到 ui/formatting/rows.py：\n" + "\n".join(offenders)
        )


def test_the_store_package_reexports_exactly_what_ledger_store_composes() -> None:
    """`stores/__init__.py` 的 `__all__` 要與 `LedgerStore` 的基底一致。

    這條是補一個**已經發生過的**漏更新：`AutomationStore` 在 2026-08 被收進
    `stores/` 時忘了加進 re-export 清單，那份 docstring 也跟著停在「四個」。
    沒有人使用的 re-export 清單不會有任何東西提醒你它過期了 —— 所以現在有了。
    """
    from tagcor_ledger.infrastructure import stores
    from tagcor_ledger.infrastructure.sqlite_store import LedgerStore

    composed = {base.__name__ for base in LedgerStore.__bases__}
    exported = set(stores.__all__)
    # 這三個不是聚合，是共用的基底與例外，所以清單裡有、`LedgerStore` 的基底裡沒有。
    exported -= {"StoreBase", "StoreError", "NotFoundError"}

    assert len(composed) >= 8, f"只掃到 {composed}，LedgerStore 的組法可能改了"
    if composed != exported:
        pytest.fail(
            "stores/__init__.py 的 __all__ 與 LedgerStore 的基底對不上：\n"
            f"  組進去但沒 re-export：{sorted(composed - exported) or '（無）'}\n"
            f"  re-export 但沒組進去：{sorted(exported - composed) or '（無）'}"
        )


# `application/` 底下**整個模組**都不經過寫入層，所以它們的例外不是「寫入層失敗」。
# 這兩個是名單而不是猜測 —— 它們自己開連線，`self.store` 根本不存在。
NON_STORE_MODULES = {
    "diagnostics.py": "健檢自己開連線跑 PRAGMA 與 COUNT，不經過 store",
    "reference.py": "法規參考庫是另一個唯讀資料庫，不經過 store",
}

# 這些 handler 包的**不是** store 呼叫，或是刻意收窄的。key 是（檔名, 函式名, 形狀）。
# 加一筆進來要寫得出理由 —— 寫不出來的就該用 STORE_FAILURES。
EXPECTED_SPECIAL_HANDLERS = {
    ("balance.py", "export_csv", "(OSError, sqlite3.Error, ValueError)"): (
        "寫 CSV 檔，OSError 是本質的（磁碟滿、沒有權限），不是寫入層失敗"
    ),
    ("catalogs.py", "create", "MoneyError"): "解析期初餘額，還沒碰到 store",
    ("catalogs.py", "create", "(ValueError, sqlite3.IntegrityError)"): (
        "刻意收窄：走到這裡表示上面三道重名檢查都沒攔到，那是預期外的。"
        "放寬成 STORE_FAILURES 會把真正的 bug 藏成一句客氣的中文"
    ),
    ("deposits.py", "create_contract", "ValueError"): "建列舉與解析金額，還沒碰到 store",
    ("deposits.py", "update_contract", "ValueError"): "建列舉，還沒碰到 store",
    ("deposits.py", "update_term", "ValueError"): "解析金額，還沒碰到 store",
    ("settings.py", "get_sort_spec", "(TypeError, ValueError)"): (
        "壞掉的 JSON 靜靜退回預設，這是偏好設定不是寫入失敗"
    ),
}


def _except_handlers(path: Path) -> list[tuple[str, str, bool]]:
    """這個模組的每一個 except handler：（函式名, 形狀, 是不是兩層寫入路徑的第二層）。

    「第二層」用**結構**判斷，不靠名單：同一個 `try` 裡，第一個 handler 是
    `DOMAIN_FAILURES` 時，後面那些就是「內容沒問題但寫不進去」的那一層。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    owner: dict[int, str] = {}
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(function):
                owner[id(node)] = function.name

    found: list[tuple[str, str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        first = node.handlers[0] if node.handlers else None
        tiered = (
            first is not None
            and isinstance(first.type, ast.Name)
            and first.type.id == "DOMAIN_FAILURES"
        )
        for index, handler in enumerate(node.handlers):
            shape = ast.unparse(handler.type) if handler.type else "bare"
            found.append((owner.get(id(handler), "?"), shape, tiered and index > 0))
    return found


def test_the_application_layer_catches_store_failures_by_name() -> None:
    """`application/` 的 except 只能是那兩個具名常數，其餘要在名單上帶理由。

    2026-08-22 盤點時，這一層有 **70 個 handler、17 種形狀**，而其中 15 個包著會丟
    `NotFoundError` 的 store 方法卻沒有列它 —— `NotFoundError` 繼承的是
    `RuntimeError`，`except (ValueError, sqlite3.Error)` 接不到。

    **17 種形狀不是 17 個疏忽。** 裡面有刻意的兩層寫入路徑、有還沒碰到 store 的
    輸入解析、有刻意收窄以免把 bug 藏起來的。所以這條守的不是「全部長一樣」，
    是「**每一個不一樣的地方都說得出為什麼**」。
    """
    offenders: list[str] = []
    total = 0
    for path in _modules("application"):
        if path.name in NON_STORE_MODULES:
            continue
        for function, shape, is_tier_two in _except_handlers(path):
            total += 1
            if shape in ("STORE_FAILURES", "DOMAIN_FAILURES"):
                continue
            if is_tier_two:
                continue
            if (path.name, function, shape) in EXPECTED_SPECIAL_HANDLERS:
                continue
            offenders.append(f"  {path.name}::{function} —— except {shape}")

    assert total >= 40, f"只掃到 {total} 個 handler，掃描路徑可能寫錯了"
    if offenders:
        pytest.fail(
            "application/ 的 except 要用 STORE_FAILURES 或 DOMAIN_FAILURES：\n"
            + "\n".join(offenders)
            + "\n\n真的不該用的話，加進 EXPECTED_SPECIAL_HANDLERS 並寫下理由。"
        )


def test_the_handler_extractor_sees_both_tiers() -> None:
    """陽性對照：抽取器認不出兩層結構的話，上面那條會把第二層全部誤報成違規。"""
    shapes = _except_handlers(SOURCE_ROOT / "application" / "transaction_service.py")
    assert ("execute", "DOMAIN_FAILURES", False) in shapes, "抓不到第一層"
    assert ("execute", "sqlite3.Error", True) in shapes, "第二層沒有被認出來"
    assert any(shape == "STORE_FAILURES" for _, shape, _ in shapes), "抓不到單層 handler"


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


def _line_counts(root: Path) -> list[tuple[int, str]]:
    counts: list[tuple[int, str]] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        counts.append((lines, str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")))
    return sorted(counts, reverse=True)


@pytest.mark.parametrize(
    ("label", "root", "limit"),
    [
        ("src", SOURCE_ROOT, MAX_MODULE_LINES),
        ("tests", PROJECT_ROOT / "tests", MAX_TEST_LINES),
    ],
)
def test_no_module_grows_back_into_a_monolith(label: str, root: Path, limit: int) -> None:
    """**`tests/` 也要掃。** 以前只掃 `src/`，於是 `test_main_query.py` 那一類的
    測試檔可以無聲長到兩千行 —— 2026-08-22 拆掉的那一個就是 2,153 行 66 條、
    橫跨八個頁面。實作有守門而測試沒有，是「規則只寫在文件上」的另一種形狀。
    """
    counts = _line_counts(root)
    assert len(counts) >= 10, f"只掃到 {len(counts)} 個 {label} 檔案，路徑可能寫錯了"
    oversized = [f"  {name}：{lines} 行" for lines, name in counts if lines > limit]
    if oversized:
        top = "、".join(f"{name}（{lines}）" for lines, name in counts[:3])
        pytest.fail(
            f"以下 {label} 模組超過 {limit} 行，先確認它是不是裝了不只一件事：\n"
            + "\n".join(oversized)
            + f"\n（目前最大的三個：{top}）"
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

    **2026-08-22 把掃描範圍從 `ui/` 擴到 `application/`。** 那一層的
    `Result.ok("排程已儲存。")` 與 `fallback_message` 一樣會走到畫面上
    （`recurring.py::_finish()` 失敗時直接進 `QMessageBox`），而舊的守門只掃 `ui/`，
    於是「定期收支」這一頁存檔失敗時跳出來的訊息裡寫的是「排程」。
    """
    offenders: list[str] = []
    for path in _modules("ui", "application"):
        for value in _value_strings(path):
            for retired, replacement in RETIRED_UI_WORDS.items():
                if retired in value:
                    offenders.append(
                        f"  {path.relative_to(PROJECT_ROOT)}：{value!r}"
                        f"（「{retired}」應為「{replacement}」）"
                    )
    if offenders:
        pytest.fail("使用者看得到的字串裡還有淘汰的用詞：\n" + "\n".join(offenders))


def test_no_chinese_sentence_ends_with_a_half_width_period() -> None:
    """中文句子的句號要用全形「。」。

    這條守的是一個**只有一處、但會回來**的錯誤：`automation.py` 的
    「待確認項目已載入.」在整個專案裡是唯一的半形句號，而它就長在一句中文後面。
    半形句號在中文字旁邊會貼著上一個字，看起來像雜訊而不是標點。

    只認「CJK 字元 ＋ 半形句號 ＋ 結尾」這一種形狀 —— 英文縮寫、副檔名、版本號、
    路徑都不會誤判。
    """
    offenders: list[str] = []
    for path in _modules("ui", "application", "domain", "infrastructure", "app"):
        for value in _value_strings(path):
            text = value.rstrip()
            if len(text) >= 2 and text.endswith(".") and _is_cjk(text[-2]):
                offenders.append(f"  {path.relative_to(PROJECT_ROOT)}：{value!r}")
    if offenders:
        pytest.fail("中文句尾要用全形句號「。」：\n" + "\n".join(offenders))


def _is_cjk(char: str) -> bool:
    return "一" <= char <= "鿿"


def test_the_half_width_period_detector_can_tell_the_difference() -> None:
    """陽性對照：偵測器要抓得到中文句尾的半形句號，又不能誤傷英文與版本號。"""
    assert _is_cjk("載") and not _is_cjk("d") and not _is_cjk("。")
    caught = "待確認項目已載入."
    assert caught.endswith(".") and _is_cjk(caught[-2]), "抓不到目標形狀"
    for innocent in ("0.20.0", "ledger.sqlite3", "e.g.", "已載入。"):
        assert not (innocent.endswith(".") and _is_cjk(innocent[-2])), innocent


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
