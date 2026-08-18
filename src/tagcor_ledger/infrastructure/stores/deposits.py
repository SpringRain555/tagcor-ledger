"""定存合約、期與待確認事件的持久化。

這一層只負責存取，**不決定「到期該產生什麼」** —— 那是 `application/deposits.py`
的職責。理由是那些規則會隨著查證法規而修正，把它們關在 application 層比較好改。
"""

from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from tagcor_ledger.domain.deposits import (
    DepositContract,
    DepositEvent,
    DepositEventStatus,
    DepositTerm,
    DepositTermStatus,
)
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import NotFoundError, StoreBase


class DepositStore(StoreBase):
    # --- 合約 ---------------------------------------------------------------

    def create_contract(
        self,
        *,
        account_id: str,
        name: str,
        interest_method: str,
        maturity_action: str,
        interest_destination_account_id: str | None,
        term_months: int,
        note: str = "",
    ) -> DepositContract:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("DEPOSIT_NAME_REQUIRED")
        if term_months <= 0:
            raise ValueError("DEPOSIT_TERM_MONTHS_INVALID")
        contract = DepositContract(
            contract_id=f"dep_{uuid4().hex}",
            account_id=account_id,
            name=clean_name,
            interest_method=interest_method,
            maturity_action=maturity_action,
            interest_destination_account_id=interest_destination_account_id,
            term_months=term_months,
            status="active",
            note=note.strip(),
        )
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            self._require_deposit_account(connection, account_id)
            connection.execute(
                """
                INSERT INTO deposit_contracts(
                    contract_id, account_id, name, interest_method, maturity_action,
                    interest_destination_account_id, term_months, status, note,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract.contract_id,
                    contract.account_id,
                    contract.name,
                    contract.interest_method,
                    contract.maturity_action,
                    contract.interest_destination_account_id,
                    contract.term_months,
                    contract.status,
                    contract.note,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="deposit_contract.create",
                entity_type="deposit_contract",
                entity_id=contract.contract_id,
                details={"interest_method": interest_method, "maturity_action": maturity_action},
            )
        return contract

    def list_contracts(self, *, include_closed: bool = False) -> list[DepositContract]:
        where = "" if include_closed else "WHERE status = 'active'"
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT contract_id, account_id, name, interest_method, maturity_action,
                       interest_destination_account_id, term_months, status, note
                FROM deposit_contracts
                {where}
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
        return [_row_to_contract(row) for row in rows]

    def get_contract(self, contract_id: str) -> DepositContract:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                """
                SELECT contract_id, account_id, name, interest_method, maturity_action,
                       interest_destination_account_id, term_months, status, note
                FROM deposit_contracts WHERE contract_id = ?
                """,
                (contract_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("DEPOSIT_CONTRACT_NOT_FOUND")
        return _row_to_contract(row)

    def close_contract(self, contract_id: str) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE deposit_contracts SET status = 'closed', updated_at = ?
                WHERE contract_id = ? AND status = 'active'
                """,
                (now_iso(), contract_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("DEPOSIT_CONTRACT_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="deposit_contract.close",
                entity_type="deposit_contract",
                entity_id=contract_id,
                details={},
            )

    # --- 期 -----------------------------------------------------------------

    def create_term(
        self,
        *,
        contract_id: str,
        sequence: int,
        start_date: str,
        maturity_date: str,
        principal_minor: int,
        annual_rate_ppm: int | None,
        monthly_deposit_minor: int | None = None,
        note: str = "",
    ) -> DepositTerm:
        if principal_minor < 0:
            raise ValueError("DEPOSIT_PRINCIPAL_INVALID")
        if maturity_date <= start_date:
            raise ValueError("DEPOSIT_MATURITY_BEFORE_START")
        term = DepositTerm(
            term_id=f"dterm_{uuid4().hex}",
            contract_id=contract_id,
            sequence=sequence,
            start_date=start_date,
            maturity_date=maturity_date,
            principal_minor=principal_minor,
            annual_rate_ppm=annual_rate_ppm,
            monthly_deposit_minor=monthly_deposit_minor,
            actual_interest_minor=None,
            status=str(DepositTermStatus.ACTIVE),
            note=note.strip(),
        )
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            connection.execute(
                """
                INSERT INTO deposit_terms(
                    term_id, contract_id, sequence, start_date, maturity_date,
                    principal_minor, annual_rate_ppm, monthly_deposit_minor,
                    actual_interest_minor, status, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    term.term_id,
                    term.contract_id,
                    term.sequence,
                    term.start_date,
                    term.maturity_date,
                    term.principal_minor,
                    term.annual_rate_ppm,
                    term.monthly_deposit_minor,
                    term.status,
                    term.note,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="deposit_term.create",
                entity_type="deposit_term",
                entity_id=term.term_id,
                details={"sequence": sequence, "maturity_date": maturity_date},
            )
        return term

    def get_term(self, term_id: str) -> DepositTerm:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(_TERM_SELECT + " WHERE term_id = ?", (term_id,)).fetchone()
        if row is None:
            raise NotFoundError("DEPOSIT_TERM_NOT_FOUND")
        return _row_to_term(row)

    def list_terms(self, *, contract_id: str | None = None) -> list[DepositTerm]:
        clause = "WHERE contract_id = ?" if contract_id else ""
        parameters: tuple[Any, ...] = (contract_id,) if contract_id else ()
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"{_TERM_SELECT} {clause} ORDER BY maturity_date DESC, sequence DESC",
                parameters,
            ).fetchall()
        return [_row_to_term(row) for row in rows]

    def list_active_terms(self) -> list[DepositTerm]:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                _TERM_SELECT + " WHERE status = 'active' ORDER BY maturity_date"
            ).fetchall()
        return [_row_to_term(row) for row in rows]

    def set_term_status(
        self, term_id: str, status: str, *, actual_interest_minor: int | None = None
    ) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE deposit_terms
                SET status = ?,
                    actual_interest_minor = COALESCE(?, actual_interest_minor),
                    updated_at = ?
                WHERE term_id = ?
                """,
                (status, actual_interest_minor, now_iso(), term_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("DEPOSIT_TERM_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="deposit_term.status",
                entity_type="deposit_term",
                entity_id=term_id,
                details={"status": status},
            )

    def next_sequence(self, contract_id: str) -> int:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS latest FROM deposit_terms WHERE contract_id = ?",
                (contract_id,),
            ).fetchone()
        return int(row["latest"]) + 1 if row is not None else 1

    # --- 事件 ---------------------------------------------------------------

    def add_event(
        self,
        *,
        term_id: str,
        event_type: str,
        due_date: str,
        suggested_amount_minor: int | None,
        note: str = "",
    ) -> bool:
        """新增一件待確認事件。已經有同一期、同種類、同日期的就不重複建立。

        回傳是否真的新增了 —— 呼叫端靠這個數「這次產生了幾筆」。
        """
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO deposit_events(
                    event_id, term_id, event_type, due_date, status,
                    suggested_amount_minor, actual_amount_minor, transaction_id,
                    note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    f"devt_{uuid4().hex}",
                    term_id,
                    event_type,
                    due_date,
                    suggested_amount_minor,
                    note,
                    timestamp,
                    timestamp,
                ),
            )
            return cursor.rowcount > 0

    def list_pending_events(self) -> list[DepositEvent]:
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                _EVENT_SELECT + " WHERE e.status = 'pending' ORDER BY e.due_date, e.event_type"
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def get_event(self, event_id: str) -> DepositEvent:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                _EVENT_SELECT + " WHERE e.event_id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("DEPOSIT_EVENT_NOT_FOUND")
        return _row_to_event(row)

    def settle_event(
        self,
        event_id: str,
        *,
        status: str,
        actual_amount_minor: int | None = None,
        transaction_id: str | None = None,
    ) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE deposit_events
                SET status = ?, actual_amount_minor = ?, transaction_id = ?, updated_at = ?
                WHERE event_id = ? AND status = ?
                """,
                (
                    status,
                    actual_amount_minor,
                    transaction_id,
                    now_iso(),
                    event_id,
                    str(DepositEventStatus.PENDING),
                ),
            ).rowcount
            if changed == 0:
                raise NotFoundError("DEPOSIT_EVENT_NOT_PENDING")
            self._audit(
                connection,
                correlation_id=f"corr_{uuid4().hex}",
                action="deposit_event.settle",
                entity_type="deposit_event",
                entity_id=event_id,
                details={"status": status},
            )

    @staticmethod
    def _require_deposit_account(connection: sqlite3.Connection, account_id: str) -> None:
        row = connection.execute(
            "SELECT status FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None or row["status"] != "active":
            raise ValueError("ACCOUNT_NOT_ACTIVE")


_TERM_SELECT = """
SELECT term_id, contract_id, sequence, start_date, maturity_date, principal_minor,
       annual_rate_ppm, monthly_deposit_minor, actual_interest_minor, status, note
FROM deposit_terms
"""

_EVENT_SELECT = """
SELECT e.event_id, e.term_id, t.contract_id, c.name AS contract_name,
       e.event_type, e.due_date, e.status, e.suggested_amount_minor,
       e.actual_amount_minor, e.transaction_id, e.note
FROM deposit_events e
JOIN deposit_terms t ON t.term_id = e.term_id
JOIN deposit_contracts c ON c.contract_id = t.contract_id
"""


def _row_to_contract(row: sqlite3.Row) -> DepositContract:
    return DepositContract(
        contract_id=str(row["contract_id"]),
        account_id=str(row["account_id"]),
        name=str(row["name"]),
        interest_method=str(row["interest_method"]),
        maturity_action=str(row["maturity_action"]),
        interest_destination_account_id=(
            str(row["interest_destination_account_id"])
            if row["interest_destination_account_id"] is not None
            else None
        ),
        term_months=int(row["term_months"]),
        status=str(row["status"]),
        note=str(row["note"]),
    )


def _row_to_term(row: sqlite3.Row) -> DepositTerm:
    return DepositTerm(
        term_id=str(row["term_id"]),
        contract_id=str(row["contract_id"]),
        sequence=int(row["sequence"]),
        start_date=str(row["start_date"]),
        maturity_date=str(row["maturity_date"]),
        principal_minor=int(row["principal_minor"]),
        annual_rate_ppm=(
            int(row["annual_rate_ppm"]) if row["annual_rate_ppm"] is not None else None
        ),
        monthly_deposit_minor=(
            int(row["monthly_deposit_minor"])
            if row["monthly_deposit_minor"] is not None
            else None
        ),
        actual_interest_minor=(
            int(row["actual_interest_minor"])
            if row["actual_interest_minor"] is not None
            else None
        ),
        status=str(row["status"]),
        note=str(row["note"]),
    )


def _row_to_event(row: sqlite3.Row) -> DepositEvent:
    return DepositEvent(
        event_id=str(row["event_id"]),
        term_id=str(row["term_id"]),
        contract_id=str(row["contract_id"]),
        contract_name=str(row["contract_name"]),
        event_type=str(row["event_type"]),
        due_date=str(row["due_date"]),
        status=str(row["status"]),
        suggested_amount_minor=(
            int(row["suggested_amount_minor"])
            if row["suggested_amount_minor"] is not None
            else None
        ),
        actual_amount_minor=(
            int(row["actual_amount_minor"]) if row["actual_amount_minor"] is not None else None
        ),
        transaction_id=(
            str(row["transaction_id"]) if row["transaction_id"] is not None else None
        ),
        note=str(row["note"]),
    )
