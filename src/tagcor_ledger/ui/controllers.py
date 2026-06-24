"""Thin UI controllers that translate widgets into application requests."""

from __future__ import annotations

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.tags import TagCatalog
from tagcor_ledger.application.transactions import (
    AddTransaction,
    AddTransactionRequest,
    ListRecentTransactions,
)
from tagcor_ledger.domain.models import TagPath
from tagcor_ledger.infrastructure.json_config import JsonConfigRepository
from tagcor_ledger.infrastructure.repositories import initialize_data_store


class LedgerUiController:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        initialize_data_store(paths)
        self.add_transaction = AddTransaction(paths)
        self.list_recent = ListRecentTransactions(paths)

    def load_tag_catalog(self) -> TagCatalog:
        document = JsonConfigRepository(self.paths.config_dir / "tags.json").read()
        return TagCatalog(document)

    def submit_transaction(
        self,
        *,
        occurred_at: str,
        entry_type: str,
        amount: str,
        tag_path: TagPath,
        description: str,
    ):
        request = AddTransactionRequest(
            occurred_at=occurred_at,
            entry_type=entry_type,
            amount=amount,
            tag_path=tag_path,
            description=description,
        )
        return self.add_transaction.execute(request)

    def recent_transactions(self):
        return self.list_recent.execute(limit=20)
