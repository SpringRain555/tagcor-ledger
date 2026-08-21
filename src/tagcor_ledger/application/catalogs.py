"""Account and category management use cases."""

from __future__ import annotations

import sqlite3

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.result import Result
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
        try:
            self.store.archive_account(account_id)
            return Result.ok("帳戶已封存。")
        except (NotFoundError, sqlite3.Error) as exc:
            return Result.fail(
                "ACCOUNT_ARCHIVE_FAILED",
                "帳戶無法封存。",
                details={"reason": str(exc)},
            )

    def rename(self, account_id: str, name: str) -> Result:
        try:
            self.store.rename_account(account_id, name)
            return Result.ok("帳戶名稱已更新。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return Result.fail(
                "ACCOUNT_RENAME_FAILED",
                "帳戶名稱無法更新。",
                details={"reason": str(exc)},
            )

    def restore(self, account_id: str) -> Result:
        try:
            self.store.restore_account(account_id)
            return Result.ok("帳戶已恢復使用。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return Result.fail(
                "ACCOUNT_RESTORE_FAILED",
                "帳戶無法恢復，請確認沒有同名使用中帳戶。",
                details={"reason": str(exc)},
            )

    def delete(self, account_id: str) -> Result:
        try:
            self.store.delete_account(account_id)
            return Result.ok("帳戶已刪除。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return Result.fail(
                "ACCOUNT_DELETE_FAILED",
                "帳戶無法刪除；預設帳戶或已有歷史資料的帳戶請改用封存。",
                details={"reason": str(exc)},
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

    def list_tree(self, *, include_archived: bool = False) -> Result:
        """兩層類別 ＋ 上層名稱 ＋ 子項目數，**一句查詢**。

        「類別」與「項目」兩個分頁看的是同一份結果的不同切片，所以不要各查一次。
        """
        nodes = self.store.list_category_tree(include_archived=include_archived)
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
        try:
            category = self.store.create_category(name=name, parent_id=parent_id)
            return Result.ok("類別／項目已建立。", details={"category_id": category.category_id})
        except (ValueError, sqlite3.IntegrityError) as exc:
            return Result.fail(
                "CATEGORY_CREATE_FAILED",
                "類別／項目無法建立，請確認名稱沒有重複且上層類別有效。",
                details={"reason": str(exc)},
            )

    def archive(self, category_id: str) -> Result:
        try:
            self.store.archive_category(category_id)
            return Result.ok("類別／項目已封存。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return Result.fail(
                "CATEGORY_ARCHIVE_FAILED",
                "類別／項目無法封存；請先處理仍在使用的子項目。",
                details={"reason": str(exc)},
            )

    def rename(self, category_id: str, name: str) -> Result:
        try:
            self.store.rename_category(category_id, name)
            return Result.ok("類別／項目名稱已更新。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return Result.fail(
                "CATEGORY_RENAME_FAILED",
                "類別／項目名稱無法更新。",
                details={"reason": str(exc)},
            )

    def restore(self, category_id: str) -> Result:
        try:
            self.store.restore_category(category_id)
            return Result.ok("類別／項目已恢復使用。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return Result.fail(
                "CATEGORY_RESTORE_FAILED",
                "類別／項目無法恢復；請先恢復上層類別並確認沒有同名項目。",
                details={"reason": str(exc)},
            )

    def delete(self, category_id: str) -> Result:
        try:
            self.store.delete_category(category_id)
            return Result.ok("類別／項目已刪除。")
        except (ValueError, NotFoundError, sqlite3.Error) as exc:
            return Result.fail(
                "CATEGORY_DELETE_FAILED",
                "類別／項目無法刪除；若已有歷史資料或子項目，請改用封存。",
                details={"reason": str(exc)},
            )
