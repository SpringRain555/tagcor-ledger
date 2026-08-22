"""守門：名冊分頁的排序規格怎麼存、怎麼讀、讀不懂怎麼辦。

`get_sort_spec()` 的整段防禦（壞 JSON、型別不對、少欄位）2026-08-22 掃出來
**一行都沒有執行過** —— 那段程式碼的存在理由正是「資料壞掉時畫面還要開得起來」，
而沒有人驗證過它做不做得到。

放 `tests/integration/` 不是 `unit/`：它要一個真的 `settings` 表。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.application.settings import SORT_SPEC_PAGES, SettingsService
from tagcor_ledger.domain.models import SortLevel
from tagcor_ledger.infrastructure.database import database_transaction
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


@pytest.fixture()
def settings(tmp_path: Path) -> SettingsService:
    paths = resolve_app_paths(tmp_path / "ledger-data")
    LedgerStore(paths)  # 建表；SettingsService 自己不跑 migration
    return SettingsService(paths)


def _write_raw(service: SettingsService, page: str, value: str) -> None:
    """繞過 `save_sort_spec()` 直接塞一個壞值，模擬手改資料庫或舊版留下的內容。"""
    with database_transaction(service.paths.database_path) as connection:
        connection.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, '2026-01-01T00:00:00+08:00')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (f"sort_spec.{page}", value),
        )


@pytest.mark.parametrize("page", SORT_SPEC_PAGES)
def test_a_spec_survives_a_round_trip(settings: SettingsService, page: str) -> None:
    """四頁各自一份，互不影響 —— key 是 `sort_spec.<page>`。"""
    spec = (SortLevel(field="parent_custom"), SortLevel(field="name", descending=True))
    assert settings.save_sort_spec(page, spec).success
    assert settings.get_sort_spec(page) == spec
    for other in SORT_SPEC_PAGES:
        if other != page:
            assert settings.get_sort_spec(other) == (), f"{page} 的設定漏到 {other} 去了"


def test_a_page_that_has_never_been_configured_reads_as_empty(
    settings: SettingsService,
) -> None:
    """空的代表「用那份清單自己的預設」，由頁面換成它的 `DEFAULT_SORT`。"""
    assert settings.get_sort_spec("accounts") == ()


def test_an_unknown_page_is_refused_instead_of_silently_stored(
    settings: SettingsService,
) -> None:
    """打錯的頁名會存成一筆**永遠讀不回來**的設定，所以寧可丟碼。

    它是綁定參數，沒有 SQL injection 的問題；擋的是「存了但沒有人讀得到」。
    """
    with pytest.raises(ValueError, match="SORT_SPEC_PAGE_UNKNOWN"):
        settings.get_sort_spec("nope")
    result = settings.save_sort_spec("nope", (SortLevel(field="name"),))
    assert not result.success
    assert result.error_code == "SORT_SPEC_PAGE_UNKNOWN"


@pytest.mark.parametrize(
    ("label", "raw"),
    [
        ("不是 JSON", "{{{"),
        ("是 JSON 但不是陣列", '{"field": "name"}'),
        ("是 JSON 但是數字", "42"),
        ("null", "null"),
        ("空字串", ""),
        ("陣列裡不是物件", '["name", "custom"]'),
        ("少了 field", '[{"desc": true}]'),
        ("field 不是字串", '[{"field": 7}]'),
        ("field 是空字串", '[{"field": ""}]'),
        ("field 是 null", '[{"field": null}]'),
    ],
)
def test_unreadable_settings_fall_back_to_empty_without_raising(
    settings: SettingsService, label: str, raw: str
) -> None:
    """**壞掉的偏好不該讓程式開不起來。**

    這是「畫面怎麼排」的偏好，不是帳務資料。真正的守衛在 SQL 那一層：認不出來的
    欄位 `order_by()` 本來就會跳過，所以這裡靜靜退回預設是安全的。
    """
    _write_raw(settings, "categories", raw)
    assert settings.get_sort_spec("categories") == (), label


def test_a_partly_broken_list_keeps_the_levels_it_can_read(
    settings: SettingsService,
) -> None:
    """壞掉的那一層跳過，好的留下 —— 不是整份丟掉。

    使用者設了三層而中間一層壞掉時，全丟等於把另外兩層也一起沒收。
    """
    _write_raw(
        settings,
        "items",
        '[{"field": "parent_custom"}, {"field": 7}, {"field": "name", "desc": true}]',
    )
    assert settings.get_sort_spec("items") == (
        SortLevel(field="parent_custom"),
        SortLevel(field="name", descending=True),
    )


def test_a_missing_desc_flag_means_ascending(settings: SettingsService) -> None:
    _write_raw(settings, "templates", '[{"field": "name"}]')
    assert settings.get_sort_spec("templates") == (SortLevel(field="name"),)


def test_an_empty_spec_can_be_saved_to_mean_back_to_default(
    settings: SettingsService,
) -> None:
    assert settings.save_sort_spec("accounts", (SortLevel(field="name"),)).success
    assert settings.get_sort_spec("accounts")
    assert settings.save_sort_spec("accounts", ()).success
    assert settings.get_sort_spec("accounts") == ()
