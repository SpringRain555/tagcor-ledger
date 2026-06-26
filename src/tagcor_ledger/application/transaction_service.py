"""Transaction commands and keyset-paginated queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3
from typing import Any
from uuid import uuid4

from tagcor_ledger.app.paths import AppPaths
from tagcor_ledger.application.result import Result, new_correlation_id
from tagcor_ledger.domain.models import TransactionFilter, TransactionRecord
from tagcor_ledger.domain.money import Money, MoneyError
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore, NotFoundError


@dataclass(frozen=True, slots=True)
class AddTransactionRequest:
    occurred_at: str
    entry_type: str
    amount: str
    description: str = ""
    currency: str = "TWD"
    account_id: str = "acct_cash"
    category_id: str = "cat_food_711"
    source: str = "manual"


@dataclass(frozen=True, slots=True)
class AddTransferRequest:
    occurred_at: str
    amount: str
    source_account_id: str
    destination_account_id: str
    description: str = ""
    currency: str = "TWD"


@dataclass(frozen=True, slots=True)
class UpdateTransactionRequest:
    transaction_id: str
    expected_revision: int
    occurred_at: str
    amount: str
    account_id: str
    category_id: str
    description: str = ""
    currency: str = "TWD"


@dataclass(frozen=True, slots=True)
class ReplaceTransferRequest:
    original_transaction_id: str
    occurred_at: str
    amount: str
    source_account_id: str
    destination_account_id: str
    description: str = ""
    currency: str = "TWD"


@dataclass(frozen=True, slots=True)
class TransactionQuery:
    limit: int = 50
    cursor_occurred_at: str | None = None
    cursor_transaction_id: str | None = None
    cursor_direction: str = "next"
    transaction_filter: TransactionFilter = TransactionFilter()

    def cursor(self) -> tuple[str, str] | None:
        if self.cursor_occurred_at is None or self.cursor_transaction_id is None:
            return None
        return (self.cursor_occurred_at, self.cursor_transaction_id)


def new_transaction_id() -> str:
    return f"txn_{uuid4().hex}"


def _validate_occurred_at(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("DATETIME_TIMEZONE_REQUIRED")


class AddTransaction:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore(paths)

    def execute(self, request: AddTransactionRequest) -> Result:
        correlation_id = new_correlation_id()
        try:
            _validate_occurred_at(request.occurred_at)
            if request.entry_type not in {"income", "expense"}:
                raise ValueError("ENTRY_TYPE_INVALID")
            money = Money.from_decimal_string(request.amount, currency=request.currency)
            record = self.store.create_transaction(
                transaction_id=new_transaction_id(),
                entry_type=request.entry_type,
                occurred_at=request.occurred_at,
                money=money,
                account_id=request.account_id,
                category_id=request.category_id,
                description=request.description,
                source=request.source,
                correlation_id=correlation_id,
            )
            return Result.ok(
                "交易已儲存。",
                details={"transaction": transaction_to_dict(record)},
                correlation_id=correlation_id,
            )
        except (MoneyError, ValueError) as exc:
            return Result.fail(
                _error_code(exc, "VALIDATION_FAILED"),
                "請檢查交易內容。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )
        except (sqlite3.Error, OSError) as exc:
            return Result.fail(
                "DATABASE_WRITE_FAILED",
                "交易無法儲存，資料庫未變更。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )


class AddTransfer:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore(paths)

    def execute(self, request: AddTransferRequest) -> Result:
        correlation_id = new_correlation_id()
        try:
            _validate_occurred_at(request.occurred_at)
            money = Money.from_decimal_string(request.amount, currency=request.currency)
            record = self.store.create_transfer(
                transaction_id=new_transaction_id(),
                occurred_at=request.occurred_at,
                money=money,
                source_account_id=request.source_account_id,
                destination_account_id=request.destination_account_id,
                description=request.description,
                correlation_id=correlation_id,
            )
            return Result.ok(
                "轉帳已儲存。",
                details={"transaction": transaction_to_dict(record)},
                correlation_id=correlation_id,
            )
        except (MoneyError, ValueError) as exc:
            return Result.fail(
                _error_code(exc, "VALIDATION_FAILED"),
                "請檢查轉帳內容。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )
        except sqlite3.Error as exc:
            return Result.fail(
                "DATABASE_WRITE_FAILED",
                "轉帳無法儲存，兩個帳戶皆未變更。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )


class UpdateTransaction:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore(paths)

    def execute(self, request: UpdateTransactionRequest) -> Result:
        correlation_id = new_correlation_id()
        try:
            _validate_occurred_at(request.occurred_at)
            money = Money.from_decimal_string(request.amount, currency=request.currency)
            record = self.store.update_transaction(
                transaction_id=request.transaction_id,
                expected_revision=request.expected_revision,
                occurred_at=request.occurred_at,
                money=money,
                account_id=request.account_id,
                category_id=request.category_id,
                description=request.description,
                correlation_id=correlation_id,
            )
            return Result.ok(
                "交易已更新。",
                details={"transaction": transaction_to_dict(record)},
                correlation_id=correlation_id,
            )
        except (MoneyError, ValueError, NotFoundError) as exc:
            return Result.fail(
                _error_code(exc, "TRANSACTION_UPDATE_FAILED"),
                "交易無法更新。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )
        except sqlite3.Error as exc:
            return Result.fail(
                "DATABASE_WRITE_FAILED",
                "交易無法更新，資料庫未變更。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )


class ReplaceTransfer:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore(paths)

    def execute(self, request: ReplaceTransferRequest) -> Result:
        correlation_id = new_correlation_id()
        try:
            _validate_occurred_at(request.occurred_at)
            money = Money.from_decimal_string(request.amount, currency=request.currency)
            record = self.store.replace_transfer(
                original_transaction_id=request.original_transaction_id,
                new_transaction_id=new_transaction_id(),
                occurred_at=request.occurred_at,
                money=money,
                source_account_id=request.source_account_id,
                destination_account_id=request.destination_account_id,
                description=request.description,
                correlation_id=correlation_id,
            )
            return Result.ok(
                "轉帳已重新建立，原交易已作廢。",
                details={"transaction": transaction_to_dict(record)},
                correlation_id=correlation_id,
            )
        except (MoneyError, ValueError, NotFoundError) as exc:
            return Result.fail(
                _error_code(exc, "TRANSFER_REPLACE_FAILED"),
                "轉帳無法重新建立，原交易未變更。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )
        except sqlite3.Error as exc:
            return Result.fail(
                "DATABASE_WRITE_FAILED",
                "轉帳無法重新建立，原交易未變更。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )


class VoidTransaction:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore(paths)

    def execute(self, transaction_id: str) -> Result:
        correlation_id = new_correlation_id()
        try:
            self.store.void_transaction(transaction_id, correlation_id)
            return Result.ok("交易已作廢。", correlation_id=correlation_id)
        except NotFoundError as exc:
            return Result.fail(
                "TRANSACTION_NOT_FOUND",
                "找不到可作廢的交易。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )
        except sqlite3.Error as exc:
            return Result.fail(
                "DATABASE_WRITE_FAILED",
                "交易無法作廢，資料庫未變更。",
                details={"reason": str(exc)},
                correlation_id=correlation_id,
            )


class ListTransactions:
    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore(paths)

    def execute(self, query: TransactionQuery | None = None) -> Result:
        request = query or TransactionQuery()
        try:
            records, next_cursor = self.store.list_transactions(
                limit=request.limit,
                cursor=request.cursor(),
                cursor_direction=request.cursor_direction,
                transaction_filter=request.transaction_filter,
            )
            return Result.ok(
                "交易已載入。",
                details={
                    "transactions": [transaction_to_dict(record) for record in records],
                    "next_cursor": (
                        {
                            "occurred_at": next_cursor[0],
                            "transaction_id": next_cursor[1],
                        }
                        if next_cursor is not None
                        else None
                    ),
                    "previous_cursor": (
                        {
                            "occurred_at": records[0].occurred_at,
                            "transaction_id": records[0].transaction_id,
                        }
                        if request.cursor() is not None and records
                        else None
                    ),
                },
            )
        except (ValueError, sqlite3.Error) as exc:
            return Result.fail(
                "LIST_TRANSACTIONS_FAILED",
                "交易列表無法載入。",
                details={"reason": str(exc)},
            )


class ListRecentTransactions:
    """Compatibility query retained for existing integrations."""

    def __init__(self, paths: AppPaths, store: LedgerStore | None = None) -> None:
        self.query = ListTransactions(paths, store)

    def execute(self, limit: int = 20) -> Result:
        return self.query.execute(TransactionQuery(limit=limit))


def transaction_to_dict(transaction: TransactionRecord) -> dict[str, Any]:
    flow_name = {
        "expense": "支出",
        "income": "收入",
        "transfer": "轉帳",
        "adjustment": "調整",
    }.get(transaction.entry_type, transaction.entry_type)
    category_parts = [
        name
        for name in (transaction.category_name, transaction.subcategory_name)
        if name
    ]
    if transaction.entry_type == "transfer":
        path_name = (
            f"轉帳 / {transaction.account_name} / "
            f"{transaction.destination_account_name or ''}"
        )
    else:
        path_name = " / ".join([flow_name, transaction.account_name, *category_parts])
    return {
        "transaction_id": transaction.transaction_id,
        "revision": transaction.revision,
        "status": transaction.status,
        "entry_type": transaction.entry_type,
        "entry_type_name": flow_name,
        "occurred_at": transaction.occurred_at,
        "recorded_at": transaction.recorded_at,
        "updated_at": transaction.updated_at,
        "amount": transaction.money.to_decimal_string(),
        "amount_minor": transaction.money.amount_minor,
        "currency": transaction.money.currency,
        "account_id": transaction.account_id,
        "account_name": transaction.account_name,
        "destination_account_id": transaction.destination_account_id,
        "destination_account_name": transaction.destination_account_name,
        "category_id": transaction.category_id,
        "category_name": transaction.category_name,
        "subcategory_id": transaction.subcategory_id,
        "subcategory_name": transaction.subcategory_name,
        "description": transaction.description,
        "tag_path_name": path_name,
        "correlation_id": transaction.correlation_id,
        "replaces_transaction_id": transaction.replaces_transaction_id,
    }


def _error_code(exc: Exception, fallback: str) -> str:
    text = str(exc).strip()
    return text if text.isupper() and " " not in text else fallback
