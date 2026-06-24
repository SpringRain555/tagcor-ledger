"""Thin UI controller for the PySide6 presentation layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.catalogs import AccountService, CategoryService
from tagcor_ledger.application.result import Result
from tagcor_ledger.application.transaction_service import (
    AddTransaction,
    AddTransactionRequest,
    AddTransfer,
    AddTransferRequest,
    ListTransactions,
    TransactionQuery,
    UpdateTransaction,
    UpdateTransactionRequest,
    VoidTransaction,
)
from tagcor_ledger.infrastructure.maintenance import MaintenanceService
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


class LedgerController:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.store = LedgerStore(paths)
        self.accounts = AccountService(paths, self.store)
        self.categories = CategoryService(paths, self.store)
        self.add_transaction_use_case = AddTransaction(paths, self.store)
        self.add_transfer_use_case = AddTransfer(paths, self.store)
        self.list_transactions_use_case = ListTransactions(paths, self.store)
        self.update_transaction_use_case = UpdateTransaction(paths, self.store)
        self.void_transaction_use_case = VoidTransaction(paths, self.store)
        self.maintenance = MaintenanceService(paths)

    def account_options(self) -> list[dict[str, Any]]:
        result = self.accounts.list()
        return list(result.details.get("accounts", []))

    def category_options(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        result = self.categories.list(parent_id=parent_id)
        return list(result.details.get("categories", []))

    def submit(
        self,
        *,
        occurred_at: str,
        entry_type: str,
        amount: str,
        account_id: str,
        destination_account_id: str | None,
        category_id: str | None,
        payee_name: str,
        description: str,
    ) -> Result:
        if entry_type == "transfer":
            if destination_account_id is None:
                return Result.fail("TRANSFER_DESTINATION_REQUIRED", "請選擇轉入帳戶。")
            return self.add_transfer_use_case.execute(
                AddTransferRequest(
                    occurred_at=occurred_at,
                    amount=amount,
                    source_account_id=account_id,
                    destination_account_id=destination_account_id,
                    payee_name=payee_name,
                    description=description,
                )
            )
        if category_id is None:
            return Result.fail("CATEGORY_REQUIRED", "請選擇分類細項。")
        return self.add_transaction_use_case.execute(
            AddTransactionRequest(
                occurred_at=occurred_at,
                entry_type=entry_type,
                amount=amount,
                account_id=account_id,
                category_id=category_id,
                payee_name=payee_name,
                description=description,
            )
        )

    def list_transactions(
        self,
        *,
        search: str = "",
        cursor: dict[str, str] | None = None,
        limit: int = 50,
    ) -> Result:
        return self.list_transactions_use_case.execute(
            TransactionQuery(
                limit=limit,
                cursor_occurred_at=cursor.get("occurred_at") if cursor else None,
                cursor_transaction_id=cursor.get("transaction_id") if cursor else None,
                search=search,
            )
        )

    def void_transaction(self, transaction_id: str) -> Result:
        return self.void_transaction_use_case.execute(transaction_id)

    def update_transaction(
        self,
        *,
        transaction_id: str,
        expected_revision: int,
        occurred_at: str,
        amount: str,
        account_id: str,
        category_id: str,
        payee_name: str,
        description: str,
    ) -> Result:
        return self.update_transaction_use_case.execute(
            UpdateTransactionRequest(
                transaction_id=transaction_id,
                expected_revision=expected_revision,
                occurred_at=occurred_at,
                amount=amount,
                account_id=account_id,
                category_id=category_id,
                payee_name=payee_name,
                description=description,
            )
        )

    def create_account(self, name: str, opening_balance: str) -> Result:
        return self.accounts.create(name=name, opening_balance=opening_balance)

    def archive_account(self, account_id: str) -> Result:
        return self.accounts.archive(account_id)

    def rename_account(self, account_id: str, name: str) -> Result:
        return self.accounts.rename(account_id, name)

    def create_category(self, name: str, parent_id: str | None = None) -> Result:
        return self.categories.create(name=name, parent_id=parent_id)

    def archive_category(self, category_id: str) -> Result:
        return self.categories.archive(category_id)

    def rename_category(self, category_id: str, name: str) -> Result:
        return self.categories.rename(category_id, name)

    def create_backup(self) -> Path:
        return self.maintenance.create_backup()

    def export_csv(self) -> Path:
        return self.maintenance.export_transactions_csv()
