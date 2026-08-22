"""存在 SQLite 裡的操作偏好（預設帳戶、盤點提醒、各名冊分頁的排序⋯⋯）。

**資料路徑不在這裡** —— 那是 `app/path_settings.py` 的外部 JSON。

## 排序規格為什麼不放進 `ApplicationSettings`

`settings` 是一張 key/value 表，所以多存四個 key **不用 migration**。但把它們塞進
`ApplicationSettings` 那個 dataclass 就得改「一般設定」那一頁的存檔流程 ——
而使用者在那一頁按「儲存」時，心裡想的不包括「順便把我排序視窗裡的設定寫回去」。
兩件事分開存，各自的儲存時機才說得清楚。
"""

from __future__ import annotations

from collections.abc import Sequence
import json

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.failures import STORE_FAILURES, failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import ApplicationSettings, SortLevel, SortSpec
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction

SORT_SPEC_PAGES = ("accounts", "categories", "items", "templates")
"""哪幾頁記得住自己的排序。**這份清單就是 key 的來源**（`sort_spec.<page>`），
所以不要拿使用者輸入當 page 名 —— 雖然它是綁定參數，但一個打錯的名字會安靜地
存成一筆永遠讀不回來的設定。"""


def _sort_spec_key(page: str) -> str:
    if page not in SORT_SPEC_PAGES:
        raise ValueError("SORT_SPEC_PAGE_UNKNOWN")
    return f"sort_spec.{page}"


class SettingsService:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    # --- 各名冊分頁的排序規格 -------------------------------------------------

    def get_sort_spec(self, page: str) -> SortSpec:
        """讀回這一頁的排序規格。**讀不懂就當成空的**（＝用該清單的預設順序）。

        壞掉的 JSON、少了欄位、型別不對 —— 全部靜靜退回預設，不丟例外。這是一個
        「畫面怎麼排」的偏好，不值得讓程式開不起來；而且真正的守衛在 SQL 那一層：
        認不出來的欄位 `order_by()` 本來就會跳過。
        """
        key = _sort_spec_key(page)
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return ()
        try:
            raw = json.loads(str(row["value"]))
        except (TypeError, ValueError):
            return ()
        if not isinstance(raw, list):
            return ()
        levels: list[SortLevel] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            field = item.get("field")
            if not isinstance(field, str) or not field:
                continue
            levels.append(SortLevel(field=field, descending=bool(item.get("desc"))))
        return tuple(levels)

    def save_sort_spec(self, page: str, spec: Sequence[SortLevel]) -> Result:
        try:
            key = _sort_spec_key(page)
            payload = json.dumps(
                [{"field": level.field, "desc": level.descending} for level in spec],
                ensure_ascii=False,
            )
            with database_transaction(self.paths.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, payload, now_iso()),
                )
            return Result.ok("排序方式已儲存。")
        except STORE_FAILURES as exc:
            return failure(
                exc,
                fallback_code="SORT_SPEC_SAVE_FAILED",
                fallback_message="排序方式無法儲存。請匯出診斷資訊回報。",
            )

    def get(self) -> ApplicationSettings:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        values = {str(row["key"]): str(row["value"]) for row in rows}
        return ApplicationSettings(
            default_account_id=values.get("default_account_id", "acct_cash"),
            default_entry_type=values.get("default_entry_type", "expense"),
            transactions_page_size=int(values.get("transactions_page_size", "50")),
            balance_snapshot_reminder=values.get(
                "balance_snapshot_reminder", "true"
            ).lower()
            == "true",
        )

    def update(self, settings: ApplicationSettings) -> Result:
        if settings.default_entry_type not in {"income", "expense", "transfer"}:
            return Result.fail("SETTINGS_ENTRY_TYPE_INVALID", "預設流向不正確。")
        if settings.transactions_page_size not in {20, 50, 100}:
            return Result.fail(
                "SETTINGS_PAGE_SIZE_INVALID",
                "每頁筆數只能是 20、50 或 100。",
            )
        try:
            with database_transaction(self.paths.database_path) as connection:
                account = connection.execute(
                    "SELECT status FROM accounts WHERE account_id = ?",
                    (settings.default_account_id,),
                ).fetchone()
                if account is None or account["status"] != "active":
                    raise ValueError("DEFAULT_ACCOUNT_NOT_ACTIVE")
                timestamp = now_iso()
                values = {
                    "default_account_id": settings.default_account_id,
                    "default_entry_type": settings.default_entry_type,
                    "transactions_page_size": str(settings.transactions_page_size),
                    "balance_snapshot_reminder": (
                        "true" if settings.balance_snapshot_reminder else "false"
                    ),
                }
                for key, value in values.items():
                    connection.execute(
                        """
                        INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                            updated_at = excluded.updated_at
                        """,
                        (key, value, timestamp),
                    )
            return Result.ok("設定已儲存。")
        except STORE_FAILURES as exc:
            # `DEFAULT_ACCOUNT_NOT_ACTIVE` 是這裡自己 raise 的（上面幾行），
            # 所以它會被 `failure()` 認出來，不會塌成 `SETTINGS_SAVE_FAILED`。
            return failure(
                exc,
                fallback_code="SETTINGS_SAVE_FAILED",
                fallback_message="設定無法儲存。請匯出診斷資訊回報。",
            )
