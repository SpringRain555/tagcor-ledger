"""帳戶與類別／項目的管理 use case。"""

from __future__ import annotations

import sqlite3

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.failures import failure
from tagcor_ledger.application.result import Result
from tagcor_ledger.domain.models import CategoryTreeFilter
from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore, NotFoundError


class AccountService:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore(paths)

    def list(self, *, include_archived: bool = False) -> Result:
        """列出帳戶與餘額。

        餘額**一次查完**（`account_balances`），不是每個帳戶各查一次 —— 後者會開
        1+N 條連線，而這個方法在記帳頁、交易紀錄篩選、餘額盤點與資產總覽上都會被呼叫。
        """
        accounts = self.store.list_accounts(include_archived=include_archived)
        balances = self.store.account_balances()
        return Result.ok(
            "帳戶已載入。",
            details={
                "accounts": [
                    {
                        "account_id": account.account_id,
                        "name": account.name,
                        "account_type": account.account_type,
                        "currency": account.currency,
                        "opening_balance_minor": account.opening_balance_minor,
                        "balance_minor": balances[account.account_id],
                        "status": account.status,
                    }
                    for account in accounts
                ]
            },
        )

    def create(
        self,
        *,
        name: str,
        account_type: str = "cash",
        opening_balance: str = "0",
    ) -> Result:
        """建立帳戶。**三種失敗各有各的錯誤碼與說法。**

        以前三種擠在同一個 `ACCOUNT_CREATE_FAILED`，訊息是「請確認名稱沒有重複且金額
        格式正確」，後面還接著 SQLite 的原文
        `（UNIQUE constraint failed: accounts.name）`。使用者看到的是一句同時指控
        兩個欄位、又沒說是哪個名字重複的話 —— 三個問題都出在「一個錯誤碼代表三件事」。
        """
        cleaned = name.strip()
        if not cleaned:
            return Result.fail("ACCOUNT_NAME_REQUIRED", "請輸入帳戶名稱。")

        try:
            opening = Money.from_decimal_string(opening_balance, allow_zero=True)
        except MoneyError:
            return Result.fail(
                "ACCOUNT_OPENING_BALANCE_INVALID",
                "期初餘額只能是整數元，例如 0 或 100000（不要加逗號或單位）。",
            )

        # **先問清楚再寫**，不要靠 UNIQUE 索引把例外丟回來 —— 那條索引是
        # `WHERE status = 'active'` 的部分索引，只有它才知道為什麼失敗，
        # 而它說的話是給資料庫看的，不是給人看的。
        taken = next(
            (
                account
                for account in self.store.list_accounts()
                if account.name.casefold() == cleaned.casefold()
            ),
            None,
        )
        if taken is not None:
            return Result.fail(
                "ACCOUNT_ACTIVE_NAME_CONFLICT",
                f"已經有一個叫「{taken.name}」的帳戶了。"
                "要用它就直接在選單裡選，不需要再新增一個。",
                details={"account_id": taken.account_id, "name": taken.name},
            )

        try:
            account = self.store.create_account(
                name=cleaned,
                account_type=account_type,
                opening_balance_minor=opening.amount_minor,
            )
        except (ValueError, sqlite3.IntegrityError) as exc:
            # 走到這裡表示上面三道檢查都沒攔到 —— 那是預期外的，原文留給診斷用的
            # `detail`，**不放進 `reason`**（`result_message()` 會把 reason 印到畫面上）。
            return Result.fail(
                "ACCOUNT_CREATE_FAILED",
                "帳戶無法建立。請匯出診斷資訊回報。",
                details={"detail": str(exc)},
            )
        return Result.ok("帳戶已建立。", details={"account_id": account.account_id})

    def archive(self, account_id: str) -> Result:
        """封存帳戶。

        底下四個方法都是同一個形狀：**寫入層丟什麼碼，使用者就看到那個碼的說法**
        （`failure()`）。`*_FAILED` 只在原文翻不出來時才用得到 —— 那表示例外是
        `sqlite3.Error` 或一個還沒收錄的碼，兩者都該去看診斷資訊而不是繼續猜。
        """
        try:
            self.store.archive_account(account_id)
            return Result.ok("帳戶已封存。")
        except (NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="ACCOUNT_ARCHIVE_FAILED",
                fallback_message="帳戶無法封存。請匯出診斷資訊回報。",
            )

    def rename(self, account_id: str, name: str) -> Result:
        try:
            self.store.rename_account(account_id, name)
            return Result.ok("帳戶名稱已更新。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="ACCOUNT_RENAME_FAILED",
                fallback_message="帳戶名稱無法更新。請匯出診斷資訊回報。",
            )

    def restore(self, account_id: str) -> Result:
        try:
            self.store.restore_account(account_id)
            return Result.ok("帳戶已恢復使用。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="ACCOUNT_RESTORE_FAILED",
                fallback_message="帳戶無法恢復。請匯出診斷資訊回報。",
                # 恢復撞名時，該改名的是**另外那一個**（現在使用中的那個），
                # 不是使用者手上這個已封存的帳戶。預設說法在這裡會叫錯人。
                overrides={
                    "ACCOUNT_ACTIVE_NAME_CONFLICT": (
                        "已經有一個使用中的帳戶叫這個名字了。"
                        "請先把那一個改名或封存，再恢復這一個。"
                    )
                },
            )

    def delete(self, account_id: str) -> Result:
        try:
            self.store.delete_account(account_id)
            return Result.ok("帳戶已刪除。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="ACCOUNT_DELETE_FAILED",
                fallback_message="帳戶無法刪除。請匯出診斷資訊回報。",
            )


class CategoryService:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore(paths)

    def list(
        self,
        *,
        parent_id: str | None = None,
        include_archived: bool = False,
    ) -> Result:
        categories = self.store.list_categories(
            parent_id=parent_id,
            include_archived=include_archived,
        )
        return Result.ok(
            "類別已載入。",
            details={
                "categories": [
                    {
                        "category_id": category.category_id,
                        "name": category.name,
                        "parent_id": category.parent_id,
                        "level": category.level,
                        "status": category.status,
                    }
                    for category in categories
                ]
            },
        )

    def list_tree(
        self,
        *,
        include_archived: bool = False,
        tree_filter: CategoryTreeFilter | None = None,
    ) -> Result:
        """兩層類別 ＋ 上層名稱 ＋ 子項目數，**一句查詢**。

        篩選（層級、所屬類別、狀態、名稱搜尋）與排序全部下推到 SQL —— 撈回來再用
        Python 過濾的話，`AGENTS.md` 那條「篩選、排序、分頁一律在 SQL 裡做」就只剩
        交易那一半還算數。
        """
        nodes = self.store.list_category_tree(
            include_archived=include_archived, tree_filter=tree_filter
        )
        return Result.ok(
            "類別已載入。",
            details={
                "categories": [
                    {
                        "category_id": node.category.category_id,
                        "name": node.category.name,
                        "parent_id": node.category.parent_id,
                        "level": node.category.level,
                        "status": node.category.status,
                        "parent_name": node.parent_name,
                        "item_count": node.item_count,
                    }
                    for node in nodes
                ]
            },
        )

    def create(self, *, name: str, parent_id: str | None = None) -> Result:
        """建立類別或項目。**三種失敗各有各的錯誤碼與說法。**

        以前三種擠在同一個 `CATEGORY_CREATE_FAILED`，訊息是「請確認名稱沒有重複且
        上層類別有效」，後面還接著 SQLite 的原文 —— 一句同時指控兩件事、又沒說是哪個
        名字重複的話。這裡照 `AccountService.create` 的形狀改（同一個檔案上面那一個）。
        """
        cleaned = name.strip()
        if not cleaned:
            return Result.fail(
                "CATEGORY_NAME_REQUIRED",
                "請輸入項目名稱。" if parent_id else "請輸入類別名稱。",
            )

        if parent_id is not None:
            parent = next(
                (
                    item
                    for item in self.store.list_categories(include_archived=True)
                    if item.category_id == parent_id
                ),
                None,
            )
            if parent is None or parent.status != "active" or parent.level != 1:
                return Result.fail(
                    "CATEGORY_PARENT_INVALID",
                    "所屬類別不存在或已封存，請先在「類別」分頁選一個使用中的類別。",
                )

        # **先問清楚再寫。** 唯一索引是 `WHERE status = 'active'` 的部分索引，
        # 它丟出來的話是給資料庫看的，不是給人看的。
        taken = next(
            (
                item
                for item in self.store.list_categories(parent_id=parent_id)
                if item.name.casefold() == cleaned.casefold()
            ),
            None,
        )
        if taken is not None:
            layer = "項目" if parent_id else "類別"
            return Result.fail(
                "CATEGORY_ACTIVE_NAME_CONFLICT",
                f"同一層裡已經有一個叫「{taken.name}」的{layer}了。"
                "要用它就直接在選單裡選，不需要再新增一個。",
                details={"category_id": taken.category_id, "name": taken.name},
            )

        try:
            category = self.store.create_category(name=cleaned, parent_id=parent_id)
        except (ValueError, sqlite3.IntegrityError) as exc:
            # 三道檢查都沒攔到才會走到這裡 —— 那是預期外的。原文放給診斷用的
            # `detail`，**不放進 `reason`**（`result_message()` 會把 reason 印在畫面上）。
            return Result.fail(
                "CATEGORY_CREATE_FAILED",
                "類別／項目無法建立。請匯出診斷資訊回報。",
                details={"detail": str(exc)},
            )
        return Result.ok("類別／項目已建立。", details={"category_id": category.category_id})

    def archive(self, category_id: str) -> Result:
        try:
            self.store.archive_category(category_id)
            return Result.ok("類別／項目已封存。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="CATEGORY_ARCHIVE_FAILED",
                fallback_message="類別／項目無法封存。請匯出診斷資訊回報。",
            )

    def rename(self, category_id: str, name: str) -> Result:
        try:
            self.store.rename_category(category_id, name)
            return Result.ok("類別／項目名稱已更新。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="CATEGORY_RENAME_FAILED",
                fallback_message="類別／項目名稱無法更新。請匯出診斷資訊回報。",
            )

    def reorder(self, category_id: str, *, anchor_id: str, place: str) -> Result:
        """調整自訂順序：把一個類別／項目移到同一層裡另一個的前面或後面。"""
        try:
            self.store.reorder_category(category_id, anchor_id=anchor_id, place=place)
            return Result.ok("順序已更新。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="CATEGORY_REORDER_FAILED",
                fallback_message="順序無法更新。請匯出診斷資訊回報。",
            )

    def restore(self, category_id: str) -> Result:
        try:
            self.store.restore_category(category_id)
            return Result.ok("類別／項目已恢復使用。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="CATEGORY_RESTORE_FAILED",
                fallback_message="類別／項目無法恢復。請匯出診斷資訊回報。",
                # 同 `AccountService.restore`：撞名時該處理的是另外那一個。
                overrides={
                    "CATEGORY_ACTIVE_NAME_CONFLICT": (
                        "同一層裡已經有一個使用中的項目叫這個名字了。"
                        "請先把那一個改名或封存，再恢復這一個。"
                    )
                },
            )

    def delete(self, category_id: str) -> Result:
        try:
            self.store.delete_category(category_id)
            return Result.ok("類別／項目已刪除。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return failure(
                exc,
                fallback_code="CATEGORY_DELETE_FAILED",
                fallback_message="類別／項目無法刪除。請匯出診斷資訊回報。",
            )
