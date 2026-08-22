"""守門：每張表的欄位標題數量與它的列格式化函式對得起來。

## 為什麼需要這一條

`RowsModel.data()` 做的是 `self.mapper(item)[index.column()]`，而 `columnCount()` 回的是
`len(self.headers)`。**兩邊是各自定義的**，沒有任何東西逼它們一致：

- 標題多、值少 → Qt 問到最後一欄時 `IndexError`。
- 標題少、值多 → 多出來的靜靜消失，畫面看起來完全正常。

加一欄標題卻忘了改 formatter 是很容易發生的事（兩者在不同檔案），而且**現有的
UI 測試一條都抓不到** —— 它們斷言的是「表格上有沒有這個字」。

## 這裡怎麼驗

用 AST 把 `ui/pages/` 底下每一個 `RowsModel(...)` 的標題清單與 formatter 名字挖出來，
再用一份人寫的樣本列實際呼叫那個 formatter 比長度。不建頁面 —— 建頁面要 controller
與整個資料庫，而這條測試要驗的東西跟資料無關。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable

import pytest

from tagcor_ledger.ui import formatting
from tagcor_ledger.ui.pages.catalog import AccountsPage, CategoriesPage, ItemsPage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAGES_ROOT = PROJECT_ROOT / "src" / "tagcor_ledger" / "ui" / "pages"

# 一份能餵給每個 formatter 的樣本列。**鍵要齊** —— formatter 用 `item["x"]` 取值，
# 少一個鍵就是 KeyError，而那也算這條測試該報的事。
SAMPLES: dict[str, dict[str, Any]] = {
    "account_values": {"name": "現金", "balance_minor": 1000, "status": "active"},
    "overview_account_values": {"name": "現金", "balance_minor": 1000},
    "category_values": {"name": "伙食", "item_count": 3, "status": "active"},
    "item_values": {"parent_name": "伙食", "name": "早餐", "status": "active"},
    "template_values": {
        "name": "早餐",
        "entry_type": "expense",
        "amount_minor": 85,
        "description": "",
    },
    "schedule_values": {
        "name": "房租",
        "entry_type": "expense",
        "interval_count": 1,
        "frequency": "monthly",
        "next_due_date": "2026-09-01",
        "end_date": None,
    },
    "occurrence_values": {
        "due_date": "2026-09-01",
        "schedule_name": "房租",
        "entry_type": "expense",
        "amount_minor": 12_000,
        "invalid_reason": None,
    },
    "inbox_values": {
        "source": "schedule",
        "due_date": "2026-09-01",
        "schedule_name": "房租",
        "entry_type": "expense",
        "amount_minor": 12_000,
        "invalid_reason": None,
    },
    "transaction_values": {
        "occurred_at": "2026-08-22T12:00:00+08:00",
        "entry_type": "expense",
        "entry_type_name": "支出",
        "account_name": "現金",
        "destination_account_name": None,
        "category_name": "伙食",
        "subcategory_name": "早餐",
        "amount": "85",
        "description": "",
        "status": "active",
    },
    "balance_gap_values": {
        "observed_at": "2026-08-22T12:00:00+08:00",
        "account_name": "現金",
        "actual_balance": "1000",
        "expected_balance": "1050",
        "difference": "-50",
        "note": "",
        "status": "active",
    },
    "deposit_contract_values": {
        "name": "郵局一年期",
        "account_name": "郵局",
        "interest_method": "lump_sum",
        "maturity_action": "none",
        "rate_type": "fixed",
        "term_months": 12,
        "status": "active",
    },
    "deposit_term_values": {
        "sequence": 1,
        "start_date": "2026-01-01",
        "maturity_date": "2027-01-01",
        "principal_minor": 1_000_000,
        "annual_rate_ppm": 16_000,
        "actual_interest_minor": None,
        "status": "active",
        "effective_rate_ppm": None,
    },
    "deposit_event_values": {
        "due_date": "2026-09-01",
        "contract_name": "郵局一年期",
        "event_type": "maturity",
        "suggested_amount_minor": None,
    },
    "reference_entry_values": {
        "law_name": "所得稅法",
        "article": "14",
        "title": "綜合所得總額",
        "amended_date": "2026-01-01",
        "stale": False,
    },
}

# 值比標題多、而且**那是刻意的**：餘額盤點頁的明細表只顯示交易的前五欄，
# 備註與狀態那兩欄在那個情境沒有意義（同一頁上方已經有整筆的說明）。
# `RowsModel.data()` 是照 column 索引取值，多的在尾巴，所以截掉是安全的。
DELIBERATE_TRUNCATION = {("balance_snapshot.py", "transaction_values"): 5}


def _rows_model_sites() -> list[tuple[str, list[str], str]]:
    """`(檔名, 標題清單, formatter 名)`。只挑標題是字面清單的那些。"""
    sites: list[tuple[str, list[str], str]] = []
    for path in sorted(PAGES_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "RowsModel" or len(node.args) < 2:
                continue
            headers, mapper = node.args[0], node.args[1]
            if not isinstance(headers, ast.List) or not isinstance(mapper, ast.Name):
                continue  # `catalog.py` 走 class 屬性，底下另外驗
            if not all(
                isinstance(item, ast.Constant) and isinstance(item.value, str)
                for item in headers.elts
            ):
                continue
            sites.append(
                (path.name, [item.value for item in headers.elts], mapper.id)  # type: ignore[attr-defined]
            )
    return sites


def _all_rows_model_calls() -> int:
    total = 0
    for path in sorted(PAGES_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        total += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "RowsModel"
        )
    return total


def test_the_extractor_finds_every_table_in_the_app() -> None:
    """陽性對照：抽取器漏掉一張表時這裡先失敗，而不是讓那張表靜靜不受檢查。

    `catalog.py` 那一個走 `list(self.HEADERS)`，抽取器認不出來 —— 所以是
    「字面清單的數量 ＋ 1」。這個 1 由 `test_the_catalog_pages_...` 那一條接手。
    """
    literal = _rows_model_sites()
    assert _all_rows_model_calls() == len(literal) + 1, (
        "新增或改寫了一個 RowsModel，抽取器沒認出來 —— 先修抽取器，不要改這個數字"
    )
    assert len(literal) >= 9, f"只抽到 {len(literal)} 張表，掃描路徑可能寫錯了"


def test_every_formatter_used_by_a_table_has_a_sample_row() -> None:
    """陽性對照：新增一個 formatter 而沒有給樣本時，底下那條會整個跳過它。"""
    used = {mapper for _, _, mapper in _rows_model_sites()}
    used |= {"account_values", "category_values", "item_values"}
    missing = sorted(used - set(SAMPLES))
    assert not missing, f"這些 formatter 沒有樣本列，等於沒被檢查：{missing}"


@pytest.mark.parametrize(
    ("filename", "headers", "mapper_name"),
    _rows_model_sites(),
    ids=[f"{name}:{mapper}" for name, _, mapper in _rows_model_sites()],
)
def test_a_table_never_has_more_columns_than_its_formatter_produces(
    filename: str, headers: list[str], mapper_name: str
) -> None:
    """標題比值多 → Qt 問到最後一欄時 `RowsModel.data()` 直接 `IndexError`。

    值比標題多是另一回事（尾巴被截掉，畫面正常），只在 `DELIBERATE_TRUNCATION`
    列出來的地方允許 —— 新出現的靜默截斷要有人看過才算數。
    """
    mapper: Callable[[dict[str, Any]], list[str]] = getattr(formatting, mapper_name)
    values = mapper(SAMPLES[mapper_name])
    assert len(values) >= len(headers), (
        f"{filename} 的「{mapper_name}」只給得出 {len(values)} 個值，"
        f"但表格宣告了 {len(headers)} 欄（{headers}）—— 最後一欄會 IndexError"
    )
    expected = DELIBERATE_TRUNCATION.get((filename, mapper_name))
    if len(values) > len(headers):
        assert expected == len(headers), (
            f"{filename} 的「{mapper_name}」產出 {len(values)} 個值但只顯示 {len(headers)} 欄，"
            "多的會靜靜消失。刻意的話請加進 DELIBERATE_TRUNCATION 並寫明理由"
        )


@pytest.mark.parametrize("page", [AccountsPage, CategoriesPage, ItemsPage])
def test_the_catalog_pages_line_up_too(page: type) -> None:
    """名冊三頁的標題與 formatter 都是 class 屬性，不用建頁面就取得到。"""
    values = page._values(SAMPLES[page._values.__name__])
    assert len(values) == len(page.HEADERS), (
        f"{page.__name__} 宣告了 {len(page.HEADERS)} 欄但 formatter 給 {len(values)} 個值"
    )
