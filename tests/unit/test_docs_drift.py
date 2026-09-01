"""守門：同一件事寫在兩個地方時，兩個地方要一致。

三組：

1. **頁面名稱 ↔ `docs/architecture/ui-workflows.md`** —— 那份文件在 2026-08-20 之前
   已經漂到**整份都是錯的**：側邊欄順序是舊的、寫「時間」（v0.13.0 已改成日期）、
   字體寫 `Segoe UI Variable`、還留著「重製與還原」這個已經拆開的分頁名。
   沒有人做錯什麼 —— 只是改程式的時候沒有任何東西提醒要改文件。
2. **版本號**（`pyproject.toml` ／ `__init__.py` ／ README）—— 每發一版都要動三處。
3. **檢查工具的版本範圍**（`environment.yaml` ／ `pyproject.toml`）—— 2026-09-01
   踩過：`pyproject` 加了上界而 `environment.yaml` 沒有，而後者才是真正建環境的那一份，
   於是新 clone 的 ruff 可能落在宣告範圍外，本機與 CI 的結果不同。

**這裡做的是逐字比對，不做推論。** 只問「這個字串有沒有出現在那份文件裡」、
「這兩個值一不一樣」。比對範圍刻意窄 —— 一個會誤報的守門比沒有守門更糟，
因為你會學會忽略它。
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

from tagcor_ledger import __version__
from tagcor_ledger.ui.navigation import ALL_PAGES, LABELS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UI_WORKFLOWS = PROJECT_ROOT / "docs" / "architecture" / "ui-workflows.md"
OPERATION_SETTINGS = (
    PROJECT_ROOT / "src" / "tagcor_ledger" / "ui" / "pages" / "operation_settings.py"
)
SYSTEM_SETTINGS = (
    PROJECT_ROOT / "src" / "tagcor_ledger" / "ui" / "pages" / "system_settings.py"
)


def _settings_tab_labels() -> list[str]:
    """從 `_tabs()` 的原始碼取出五個分頁名。

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


def _system_tab_labels() -> list[str]:
    """從 `SystemSettingsPage._build()` 的 `addTab(..., "名稱")` 取出四個分頁名。

    系統設定沒有 `_tabs()` 那種正本方法，分頁是一行一行 `addTab` 加的，所以這裡
    直接抓那些呼叫的第二個引數。**它一樣需要守門** —— 2026-08-21 之前只有操作設定
    的分頁被逐字比對，系統設定的四個（一般設定／資料路徑／備份與還原／重製）
    改了名不會有任何東西變紅，而「重製與還原」那個舊名正是這樣漂過一次的。
    """
    tree = ast.parse(SYSTEM_SETTINGS.read_text(encoding="utf-8"))
    labels = [
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "addTab"
        and len(node.args) == 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    ]
    if not labels:
        raise AssertionError("找不到 SystemSettingsPage 的 addTab 呼叫，抽取器要跟著改")
    return labels


def test_the_extractor_finds_the_five_tabs() -> None:
    """陽性對照：抽不到名字的話，底下那條會空過。"""
    labels = _settings_tab_labels()
    assert len(labels) == 5, labels
    assert "定存" in labels


def test_the_extractor_finds_the_four_system_tabs() -> None:
    """陽性對照：同上，抽取器壞掉的話下面那條會空過。"""
    labels = _system_tab_labels()
    assert len(labels) == 4, labels
    assert "備份與還原" in labels


def test_every_page_name_appears_in_the_ui_workflows_doc() -> None:
    """側邊欄八頁、操作設定五個分頁、系統設定四個分頁，都要逐字出現在頁面地圖那份文件裡。"""
    document = UI_WORKFLOWS.read_text(encoding="utf-8")
    expected = (
        [LABELS[page] for page in ALL_PAGES]
        + _settings_tab_labels()
        + _system_tab_labels()
    )

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


def _declared_versions() -> dict[str, str]:
    """版本號寫在三個地方，把三個都讀出來。

    **不 import `tomllib` 之外的東西，也不靠 `importlib.metadata`** —— 後者讀的是
    「安裝時」的中繼資料，改了 `pyproject.toml` 但沒重裝的話它還是舊值，那會讓這條
    守門在最該紅的時候是綠的。
    """
    import tomllib

    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"目前版本：\*\*([0-9]+\.[0-9]+\.[0-9]+)\*\*", readme)

    return {
        "pyproject.toml": pyproject["project"]["version"],
        "src/tagcor_ledger/__init__.py": __version__,
        "README.md": match.group(1) if match else "（找不到「目前版本：**X.Y.Z**」）",
    }


def test_the_version_is_the_same_in_all_three_places() -> None:
    """版本號有三個出處，而在這條守門之前沒有任何東西比對它們。

    專案對文件漂移已經有四條守門（頁面名、圖、連結、錯誤碼），版本號卻是漏的 ——
    而它正是每發一版都要動、最容易漏掉一處的東西。漏掉的那一份會繼續用權威的
    語氣講一個已經不成立的版本。
    """
    versions = _declared_versions()
    if len(set(versions.values())) != 1:
        pytest.fail(
            "版本號不一致：\n"
            + "\n".join(f"  {where:<32} {value}" for where, value in versions.items())
            + "\n發版時三個地方要一起改。"
        )


def test_the_version_reader_actually_finds_all_three() -> None:
    """避免 README 的正規表示式改壞之後靜默跳過 —— 那會讓上面那條永遠是綠的。"""
    versions = _declared_versions()
    assert len(versions) == 3
    for where, value in versions.items():
        assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value), f"{where} 讀出來的是 {value!r}"


# 兩份都該宣告的套件：執行期相依 ＋ 檢查工具。
#
# **PySide6 刻意不在裡面** —— 它只能由 conda 裝，本來就不該出現在 pyproject 的
# dependencies 裡（Windows 下混用 conda/pip 的 PySide6 會讓 Qt DLL 載入失敗）。
#
# `tzdata` 是 2026-09-01 補進來的：conda 的 Python 一向會帶它，所以它在 pyproject
# 裡缺席了很久都沒事 —— 直到在純 pip venv 上跑，29 個測試 collection error。
# **隱形的相依就是還沒爆炸的相依**，這條守門要涵蓋執行期而不只是工具。
SHARED_TOOLS = ("filelock", "platformdirs", "tzdata", "pytest", "pytest-qt", "ruff", "mypy")


def _conda_tool_specs() -> dict[str, str]:
    """從 environment.yaml 讀 `- "ruff>=0.15,<0.16"` 這種列。

    **不 import pyyaml** —— 專案沒有這個相依，而為了讀四行設定多裝一個套件不划算
    （同 `reference/sources.json` 選 JSON 而不選 YAML 的理由）。
    格式固定且由這條測試自己守著，逐行比對就夠。
    """
    text = (PROJECT_ROOT / "environment.yaml").read_text(encoding="utf-8")
    specs: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r'\s*-\s*"?([A-Za-z0-9_.-]+)((?:[<>=!].*?)?)"?\s*$', line)
        if match and match.group(1) in SHARED_TOOLS:
            specs[match.group(1)] = match.group(2).strip()
    return specs


def _pyproject_tool_specs() -> dict[str, str]:
    """執行期相依與 dev 相依都要讀 —— 兩塊都有該與 conda 對齊的套件。"""
    import tomllib

    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries = list(pyproject["project"]["dependencies"])
    entries += list(pyproject["project"]["optional-dependencies"]["dev"])

    specs: dict[str, str] = {}
    for entry in entries:
        match = re.match(r"([A-Za-z0-9_.-]+)(.*)", entry)
        if match and match.group(1) in SHARED_TOOLS:
            specs[match.group(1)] = match.group(2).strip()
    return specs


def test_the_checker_versions_agree_between_conda_and_pyproject() -> None:
    """`environment.yaml` 才是真正建環境的那一份，只改 `pyproject` 沒有用。

    2026-09-01 實際發生過：pyproject 加了上界、environment.yaml 沒有，於是
    `conda env create` 拿到的 ruff 可能落在宣告範圍外，本機與 CI 的規則集不同。
    """
    conda = _conda_tool_specs()
    pyproject = _pyproject_tool_specs()

    mismatched = [
        f"  {tool:<10} environment.yaml={conda.get(tool, '（沒宣告）'):<16} "
        f"pyproject={pyproject.get(tool, '（沒宣告）')}"
        for tool in SHARED_TOOLS
        if conda.get(tool) != pyproject.get(tool)
    ]
    if mismatched:
        pytest.fail(
            "檢查工具的版本範圍兩邊不一致：\n"
            + "\n".join(mismatched)
            + "\n改一份就要改另一份 —— environment.yaml 才是真正建環境的那一份。"
        )


def test_both_spec_readers_actually_find_every_tool() -> None:
    """陽性對照：任何一邊解析失敗都會讓上面那條變成「兩個空 dict 相等」。"""
    for label, specs in (("environment.yaml", _conda_tool_specs()),
                         ("pyproject.toml", _pyproject_tool_specs())):
        missing = [tool for tool in SHARED_TOOLS if tool not in specs]
        assert not missing, f"{label} 裡沒讀到：{missing}"
        for tool, spec in specs.items():
            assert spec.startswith(">="), f"{label} 的 {tool} 讀出來是 {spec!r}"
