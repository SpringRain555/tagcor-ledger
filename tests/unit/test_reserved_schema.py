"""守門：兩個「留著但沒有人用」的 schema 欄位，要一直保持沒有人用 —— 而且有期限。

## 為什麼是守門而不是刪掉

`EntryType.ADJUSTMENT` 與 `Account.account_type` 從 v1 就在，兩個都沒有任何程式碼
會產生它們自己以外的值。`REQ-0010` 甚至拿 `adjustment` 當「先加著以後再說」的前車之鑑。

按那個教訓，該刪。**但 `REQ-0010` 本身排在 2026-10 月底重新評估，而它的設計正好要用
到這兩樣**：

- 「郵局有存摺可逐筆核對／現金只能定期盤點」的區分，就是 `account_type`。
- 「把未解釋差額轉成一筆調整交易」那顆按鈕，就是 `adjustment`。

八月刪掉、十月加回來是純粹的來回，而且中間那兩個月要跑兩次 migration 測試。
所以 2026-08-22 的決定是**不刪，改成鎖住**：讓「沒有人用」從註解裡的一句話，
變成兩條會失敗的測試。

## 期限

**2026-10 月底 `REQ-0010` 重新評估時**：

- 判定要做逐筆對帳 → 這兩個欄位開始有值，這份檔案跟著刪掉。
- 判定不做 → 那時候發 schema v8 清掉它們，這份檔案也跟著刪掉。

**兩條路都會讓這份檔案消失。** 它還在，就表示那次評估還沒發生。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.domain.models import EntryType
from tagcor_ledger.infrastructure.database import connect_database
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "tagcor_ledger"

DEADLINE = (
    "REQ-0010 排在 2026-10 月底重新評估。判定要做逐筆對帳，這個欄位就開始有值；"
    "判定不做，就在那時發 schema v8 清掉它。在那之前它是有意的保留，不是遺忘。"
)

# `"adjustment"` 這個字串**允許**出現的地方。除了這幾處，任何地方出現都表示
# 有人開始用它了 —— 那不一定是錯的，但一定要有人回頭看 REQ-0010。
ADJUSTMENT_HOMES = {
    # 列舉定義自己。
    "domain/models.py",
    # schema 的 CHECK 約束（拿掉要 migration）。
    "infrastructure/migrations.py",
    # 兩張顯示名稱表 —— 資料庫裡真的出現 adjustment 時畫面才不會印英文。
    "application/transaction_service.py",
    "infrastructure/maintenance.py",
}


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _modules() -> list[Path]:
    return [p for p in sorted(SOURCE_ROOT.rglob("*.py")) if "__pycache__" not in p.parts]


def test_the_adjustment_entry_type_is_still_unused() -> None:
    """沒有任何程式碼建立 `adjustment` 交易。"""
    assert EntryType.ADJUSTMENT.value == "adjustment", "列舉值改名了，這份守門要跟著改"

    offenders: list[str] = []
    for path in _modules():
        relative = str(path.relative_to(SOURCE_ROOT)).replace("\\", "/")
        if relative in ADJUSTMENT_HOMES:
            continue
        if any("adjustment" in value for value in _string_constants(path)):
            offenders.append(f"  {relative}")
    if offenders:
        pytest.fail(
            "這些地方開始用 `adjustment` 了，先回頭看 REQ-0010：\n"
            + "\n".join(offenders)
            + f"\n\n{DEADLINE}"
        )


def test_the_adjustment_homes_all_still_exist() -> None:
    """陽性對照：豁免名單裡的檔案要真的都還在、而且真的都還提到 `adjustment`。

    少了這一條，上面那條會在檔案改名之後靜靜地什麼都不檢查。
    """
    for relative in sorted(ADJUSTMENT_HOMES):
        path = SOURCE_ROOT / relative
        assert path.exists(), f"{relative} 不見了，ADJUSTMENT_HOMES 要跟著改"
        assert "adjustment" in path.read_text(encoding="utf-8"), (
            f"{relative} 已經沒有 adjustment 了 —— 該把它從豁免名單裡拿掉"
        )


def test_account_type_is_always_cash(tmp_path: Path) -> None:
    """`account_type` 沒有第二個值 —— 介面沒有入口，程式也沒有人傳別的進去。

    分兩邊查：`create_account()` 的預設值（靜態），以及真的建出來的資料（動態）。
    只查靜態的話，有人繞過預設值直接寫 SQL 就看不到。
    """
    accounts = SOURCE_ROOT / "infrastructure" / "stores" / "accounts.py"
    tree = ast.parse(accounts.read_text(encoding="utf-8"), filename=str(accounts))
    defaults = [
        default.value
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "create_account"
        for name, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
        if name.arg == "account_type" and isinstance(default, ast.Constant)
    ]
    assert defaults == ["cash"], f"create_account 的 account_type 預設值變成 {defaults}"

    paths = resolve_app_paths(tmp_path / "ledger-data")
    store = LedgerStore(paths)
    store.create_account(name="測試帳戶")
    with connect_database(paths.database_path) as connection:
        kinds = {
            str(row["account_type"])
            for row in connection.execute("SELECT DISTINCT account_type FROM accounts")
        }
    assert kinds == {"cash"}, f"資料庫裡出現了第二種 account_type：{sorted(kinds)}。\n{DEADLINE}"
