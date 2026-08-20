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
        try:
            opening = Money.from_decimal_string(opening_balance, allow_zero=True)
            account = self.store.create_account(
                name=name,
                account_type=account_type,
                opening_balance_minor=opening.amount_minor,
            )
            return Result.ok("帳戶已建立。", details={"account_id": account.account_id})
        except (MoneyError, ValueError, sqlite3.IntegrityError) as exc:
            return Result.fail(
                "ACCOUNT_CREATE_FAILED",
                "帳戶無法建立，請確認名稱沒有重複且金額格式正確。",
                details={"reason": str(exc)},
            )

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
