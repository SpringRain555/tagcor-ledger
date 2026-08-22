"""帳本本體：交易、帳戶、類別／項目、名冊排序與一般設定。

這一段幾乎全是轉發 —— 頁面呼叫 controller，controller 呼叫 service，
service 回 `Result`。**中間不做判斷**：需要判斷的東西（「總資產只算使用中帳戶」
那種）屬於 `overview.py`，不屬於這裡。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tagcor_ledger.application.result import Result
from tagcor_ledger.application.transaction_service import (
    AddTransactionRequest,
    AddTransferRequest,
    ReplaceTransferRequest,
    TransactionQuery,
    UpdateTransactionRequest,
)
from tagcor_ledger.domain.models import (
    ApplicationSettings,
    CategoryTreeFilter,
    SortLevel,
    SortSpec,
    TransactionFilter,
)
from tagcor_ledger.ui.controller.wiring import ControllerBase


class LedgerSection(ControllerBase):
    # --- 帳戶與類別 ---------------------------------------------------------

    def account_options(
        self,
        *,
        include_archived: bool = False,
        sort: Sequence[SortLevel] = (),
    ) -> list[dict[str, Any]]:
        """帳戶清單。**不給 `sort` 就是自訂順序** —— 下拉選單與資產總覽都走這一條。"""
        return self._rows(
            self.accounts.list(include_archived=include_archived, sort=sort), "accounts"
        )

    def category_options(
        self,
        parent_id: str | None = None,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        return self._rows(
            self.categories.list(parent_id=parent_id, include_archived=include_archived),
            "categories",
        )

    def category_tree(
        self,
        *,
        include_archived: bool = False,
        tree_filter: CategoryTreeFilter | None = None,
    ) -> list[dict[str, Any]]:
        """兩層類別攤成一份列表，每一列都帶著上層名稱與子項目數。

        `tree_filter` 一給就以它為準：層級、所屬類別、狀態、名稱搜尋與排序**都在
        SQL 裡處理**。「類別」與「項目」兩個分頁各自送自己的 `level`，不再撈回全部
        再用 Python 濾。
        """
        return self._rows(
            self.categories.list_tree(
                include_archived=include_archived, tree_filter=tree_filter
            ),
            "categories",
        )

    def create_account(self, name: str, opening_balance: str) -> Result:
        return self.accounts.create(name=name, opening_balance=opening_balance)

    def archive_account(self, account_id: str) -> Result:
        return self.accounts.archive(account_id)

    def restore_account(self, account_id: str) -> Result:
        return self.accounts.restore(account_id)

    def rename_account(self, account_id: str, name: str) -> Result:
        return self.accounts.rename(account_id, name)

    def delete_account(self, account_id: str) -> Result:
        return self.accounts.delete(account_id)

    def create_category(self, name: str, parent_id: str | None = None) -> Result:
        return self.categories.create(name=name, parent_id=parent_id)

    def archive_category(self, category_id: str) -> Result:
        return self.categories.archive(category_id)

    def restore_category(self, category_id: str) -> Result:
        return self.categories.restore(category_id)

    def rename_category(self, category_id: str, name: str) -> Result:
        return self.categories.rename(category_id, name)

    def delete_category(self, category_id: str) -> Result:
        return self.categories.delete(category_id)

    # --- 名冊的自訂順序與排序規格 -------------------------------------------

    def set_category_order(
        self,
        ordered_ids: list[str],
        *,
        parent_id: str | None,
        level: int,
    ) -> Result:
        """一整組類別／項目的自訂順序。`parent_id=None, level=1` 就是第一層。"""
        return self.categories.set_order(ordered_ids, parent_id=parent_id, level=level)

    def set_account_order(self, ordered_ids: list[str]) -> Result:
        return self.accounts.set_order(ordered_ids)

    def sort_spec(self, page: str) -> SortSpec:
        """名冊分頁記得住的排序規格。沒存過回傳空的，由頁面換成自己的預設。"""
        return self.settings.get_sort_spec(page)

    def save_sort_spec(self, page: str, spec: Sequence[SortLevel]) -> Result:
        return self.settings.save_sort_spec(page, spec)

    # --- 交易 ---------------------------------------------------------------

    def submit(
        self,
        *,
        occurred_at: str,
        entry_type: str,
        amount: str,
        account_id: str,
        destination_account_id: str | None,
        category_id: str | None,
        description: str,
    ) -> Result:
        if entry_type == "transfer":
            if destination_account_id is None:
                return Result.fail("TRANSFER_DESTINATION_REQUIRED", "請選擇轉入帳戶。")
            return self.add_transfer.execute(
                AddTransferRequest(
                    occurred_at=occurred_at,
                    amount=amount,
                    source_account_id=account_id,
                    destination_account_id=destination_account_id,
                    description=description,
                )
            )
        if category_id is None:
            return Result.fail("CATEGORY_REQUIRED", "請選擇類別／項目。")
        return self.add_transaction.execute(
            AddTransactionRequest(
                occurred_at=occurred_at,
                entry_type=entry_type,
                amount=amount,
                account_id=account_id,
                category_id=category_id,
                description=description,
            )
        )

    def list_transactions(
        self,
        *,
        search: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        account_id: str | None = None,
        category_id: str | None = None,
        status: str = "active",
        cursor: dict[str, str] | None = None,
        direction: str = "next",
        limit: int | None = None,
    ) -> Result:
        page_size = limit or self.settings.get().transactions_page_size
        return self.list_transaction_records.execute(
            TransactionQuery(
                limit=page_size,
                cursor_occurred_at=cursor.get("occurred_at") if cursor else None,
                cursor_transaction_id=cursor.get("transaction_id") if cursor else None,
                cursor_direction=direction,
                transaction_filter=TransactionFilter(
                    search=search,
                    date_from=date_from,
                    date_to=date_to,
                    account_id=account_id,
                    category_id=category_id,
                    status=status,
                ),
            )
        )

    def update_transaction(self, **values: Any) -> Result:
        return self.update_transaction_record.execute(UpdateTransactionRequest(**values))

    def replace_transfer(self, **values: Any) -> Result:
        return self.replace_transfer_record.execute(ReplaceTransferRequest(**values))

    def void_transaction(self, transaction_id: str) -> Result:
        return self.void_transaction_record.execute(transaction_id)

    # --- 一般偏好 -----------------------------------------------------------

    def get_settings(self) -> ApplicationSettings:
        return self.settings.get()

    def save_settings(self, settings: ApplicationSettings) -> Result:
        return self.settings.update(settings)
