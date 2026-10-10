"""守門：schema 裡**留著、但執行期不再寫**的欄位與值。

拿掉一個欄位或一個 CHECK 值要重建整張表，所以 v12、v13 都選擇留著
（[ADR-0015](../../docs/decisions/ADR-0015-delete-balance-snapshots-for-real.md)、
[ADR-0017](../../docs/decisions/ADR-0017-delete-transactions-for-real.md)）。
留著的代價是「看起來還能用」—— 這份檔案把「不再寫」從註解裡的一句話變成會失敗的測試。

| 留著的 | 從哪一版起不寫 | 為什麼 |
|---|---|---|
| `transactions.replaces_transaction_id` | v13 | 它指向被替換掉的舊轉帳，而舊轉帳現在是真的刪掉 —— 外鍵會擋住刪除。替換關係改記在稽核列 |
| `status = 'voided'`（交易、盤點） | v13、v12 | 刪除是真的移除，資料庫裡沒有「已刪除」這個狀態了 |

只有 `infrastructure/migrations.py` 可以提到它們（建表、CHECK、清掉舊資料的那幾版）。
docstring 與註解不算 —— 那是寫給人看的歷史，本來就該講得出它們以前是什麼。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "tagcor_ledger"
MIGRATIONS = "infrastructure/migrations.py"

RETIRED = {
    "replaces_transaction_id": "v13 起不寫（ADR-0017）：替換關係記在稽核列的 `replaces`",
    "voided": "v12／v13 起刪除是真的移除（ADR-0015、ADR-0017），沒有已刪除這個狀態",
}


def _value_strings(path: Path) -> list[str]:
    """這個模組裡**當成值用**的字串（SQL、字典的鍵…）。docstring 那種裸字串陳述式不算。"""
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


def _modules() -> list[Path]:
    return [p for p in sorted(SOURCE_ROOT.rglob("*.py")) if "__pycache__" not in p.parts]


def test_the_extractor_sees_the_migrations_and_skips_docstrings() -> None:
    """陽性對照：migration 那一份一定提到這兩個字（建表與清舊資料），抽不到就是抽取器壞了；
    而 `stores/base.py` 的 docstring 有提到 `replaces_transaction_id`，那不該被抽出來。"""
    migrations = " ".join(_value_strings(SOURCE_ROOT / MIGRATIONS))
    for word in RETIRED:
        assert word in migrations, f"migrations.py 裡抽不到 {word}"
    base = SOURCE_ROOT / "infrastructure" / "stores" / "base.py"
    assert "replaces_transaction_id" in base.read_text(encoding="utf-8"), "前提：docstring 提到它"
    assert not any("replaces_transaction_id" in value for value in _value_strings(base))


@pytest.mark.parametrize("word", sorted(RETIRED))
def test_runtime_code_no_longer_writes_the_retired_value(word: str) -> None:
    offenders = [
        str(path.relative_to(SOURCE_ROOT)).replace("\\", "/")
        for path in _modules()
        if str(path.relative_to(SOURCE_ROOT)).replace("\\", "/") != MIGRATIONS
        and any(word in value for value in _value_strings(path))
    ]
    if offenders:
        pytest.fail(
            f"這些地方又開始用 `{word}` 了 —— {RETIRED[word]}：\n  " + "\n  ".join(offenders)
        )
