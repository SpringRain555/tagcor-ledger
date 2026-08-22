"""`order_by()`：整個專案唯一把字串拼進 `ORDER BY` 的地方。

**為什麼在這裡量字串，而不是只看查詢結果。** 2026-08-22 先寫的是三條整合測試
（重複欄位、全部認不出來、tiebreaker），陽性對照全部 BAD —— 拿掉那三段程式，
測試照樣綠。原因是那幾筆資料剛好讓「有做」與「沒做」產生同一個順序：

- `name ASC, name DESC` 的結果就等於 `name ASC`
- 全部平手時，「預設順序」與「只剩 tiebreaker」都會落到名稱序
- SQLite 對同一個查詢同一份資料本來就會給同一個順序，看不出少了 tiebreaker

**這些規則是字串層級的規則，就要在字串層級檢查。**
"""

from __future__ import annotations

from tagcor_ledger.domain.models import SortLevel
from tagcor_ledger.infrastructure.stores.base import order_by

FIELDS = {"custom": "sort_order", "name": "name COLLATE NOCASE", "status": "status"}
DEFAULT = ("sort_order",)
TIES = ("name COLLATE NOCASE", "category_id")


def build(*levels: SortLevel) -> str:
    return order_by(levels, fields=FIELDS, default=DEFAULT, tiebreakers=TIES)


def test_one_level_becomes_that_expression_plus_tiebreakers() -> None:
    assert build(SortLevel(field="name")) == "name COLLATE NOCASE, name COLLATE NOCASE, category_id"


def test_descending_only_marks_that_level() -> None:
    result = build(SortLevel(field="name", descending=True))
    assert result.startswith("name COLLATE NOCASE DESC,")
    assert "category_id DESC" not in result, "tiebreaker 不該跟著反向"


def test_levels_keep_the_order_they_were_given() -> None:
    result = build(SortLevel(field="status"), SortLevel(field="custom"))
    assert result.index("status") < result.index("sort_order")


def test_a_repeated_field_appears_only_once() -> None:
    """第一層排過的欄位不可能在第二層再分出勝負。"""
    result = build(SortLevel(field="name"), SortLevel(field="name", descending=True))
    assert "DESC" not in result, result
    assert result.count("name COLLATE NOCASE") == 2, (
        f"應該只有第一層那一次加上 tiebreaker 那一次：{result}"
    )


def test_an_unknown_field_is_dropped_but_the_rest_survives() -> None:
    result = build(SortLevel(field="name; DROP TABLE x"), SortLevel(field="status"))
    assert "DROP TABLE" not in result, f"未知的欄位被拼進 SQL 了：{result}"
    assert result.startswith("status,"), result


def test_an_empty_spec_falls_back_to_the_default() -> None:
    assert build() == "sort_order, name COLLATE NOCASE, category_id"


def test_an_all_unknown_spec_falls_back_to_the_default() -> None:
    """**這一條是三條沒鑑別力的整合測試裡最容易假綠的那一個。**

    在字串層級一眼就分得出來：退回預設有 `sort_order`，沒退回就只剩 tiebreaker。
    """
    result = build(SortLevel(field="亂打的"), SortLevel(field="也不存在"))
    assert result == "sort_order, name COLLATE NOCASE, category_id"
    assert result.startswith("sort_order"), "沒有退回預設順序"


def test_tiebreakers_are_always_last_and_always_present() -> None:
    for spec in (
        (),
        (SortLevel(field="custom"),),
        (SortLevel(field="status", descending=True), SortLevel(field="name")),
    ):
        result = order_by(spec, fields=FIELDS, default=DEFAULT, tiebreakers=TIES)
        assert result.endswith("name COLLATE NOCASE, category_id"), result


def test_the_real_whitelists_only_hold_fixed_expressions() -> None:
    """白名單裡不得出現參數化以外的東西 —— 它的內容會原樣進 SQL。

    這條守的是**未來**：有人為了「依使用者輸入排序」而在 value 裡放格式化字串，
    那一刻注入就成立了。這裡不驗語法，只驗「沒有可疑的字元」。

    **引號也在禁止之列。** 合法的字面值（`COALESCE(x, '')`）本來就可以改寫成不需要
    引號的形式，而放行引號等於讓「哪一個引號是安全的」變成要逐一判斷的事。
    """
    from tagcor_ledger.infrastructure.stores.accounts import ACCOUNT_SORT_FIELDS
    from tagcor_ledger.infrastructure.stores.templates import TEMPLATE_SORT_FIELDS
    from tagcor_ledger.infrastructure.stores.categories import CATEGORY_SORT_FIELDS

    tables = {
        "ACCOUNT_SORT_FIELDS": ACCOUNT_SORT_FIELDS,
        "TEMPLATE_SORT_FIELDS": TEMPLATE_SORT_FIELDS,
        "CATEGORY_SORT_FIELDS": CATEGORY_SORT_FIELDS,
    }
    checked = 0
    for table_name, table in tables.items():
        for key, expression in table.items():
            for bad in (";", "--", "?", "{", "%", "'"):
                assert bad not in expression, f"{table_name}[{key}] 含有 {bad!r}：{expression}"
            checked += 1
    assert checked >= 12, f"只檢查了 {checked} 個欄位，白名單是不是被清空了"
