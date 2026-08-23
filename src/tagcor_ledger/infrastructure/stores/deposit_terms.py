"""定存**一期**的持久化。

**續約產生新的一期，不修改舊的那一期** —— 每次續存當時的牌告利率因此都留得下歷史。
`update_term()` 是「查到牌告利率之後回來補」的實作路徑。
"""

from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from tagcor_ledger.domain.deposits import DepositTerm, DepositTermStatus
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import (
    NotFoundError,
    StoreBase,
    new_correlation_id,
)


class DepositTermStore(StoreBase):
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
                correlation_id=new_correlation_id(),
                action="deposit_term.create",
                entity_type="deposit_term",
                entity_id=term.term_id,
                details={"sequence": sequence, "maturity_date": maturity_date},
            )
        return term

    def get_term(self, term_id: str) -> DepositTerm:
        with connect_database(self.paths.database_path) as connection:
            row = connection.execute(
                _TERM_SELECT + " WHERE t.term_id = ?", (term_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("DEPOSIT_TERM_NOT_FOUND")
        return _row_to_term(row)

    def list_terms(self, *, contract_id: str | None = None) -> list[DepositTerm]:
        clause = "WHERE t.contract_id = ?" if contract_id else ""
        parameters: tuple[Any, ...] = (contract_id,) if contract_id else ()
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                f"{_TERM_SELECT} {clause} ORDER BY t.maturity_date DESC, t.sequence DESC",
                parameters,
            ).fetchall()
        return [_row_to_term(row) for row in rows]

    def list_active_terms(self) -> list[DepositTerm]:
        """存續中、而且合約還沒結束的期。

        **合約那一側也要濾。** 產生待確認項目走的是這個清單，少了那個條件，
        一份已結束的合約仍然會生出到期項目 —— 而它在畫面上預設是看不見的。
        """
        with connect_database(self.paths.database_path) as connection:
            rows = connection.execute(
                _TERM_SELECT
                + """
                JOIN deposit_contracts c ON c.contract_id = t.contract_id
                WHERE t.status = 'active' AND c.status = 'active'
                ORDER BY t.maturity_date
                """
            ).fetchall()
        return [_row_to_term(row) for row in rows]

    def update_term(
        self,
        term_id: str,
        *,
        start_date: str,
        maturity_date: str,
        principal_minor: int,
        annual_rate_ppm: int | None,
        monthly_deposit_minor: int | None,
        note: str = "",
    ) -> None:
        """修改一期。**只有存續中的期能改。**

        這是「查到牌告利率再回來補」的實作路徑 —— 沒有這個方法，
        go-live runbook 裡那句話就是做不到的。

        已續約／已結清的期不能改，因為它們已經產生過交易，改了會讓帳與紀錄對不起來。
        """
        if principal_minor < 0:
            raise ValueError("DEPOSIT_PRINCIPAL_INVALID")
        if maturity_date <= start_date:
            raise ValueError("DEPOSIT_MATURITY_BEFORE_START")
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE deposit_terms
                SET start_date = ?, maturity_date = ?, principal_minor = ?,
                    annual_rate_ppm = ?, monthly_deposit_minor = ?, note = ?, updated_at = ?
                WHERE term_id = ? AND status = 'active'
                """,
                (
                    start_date,
                    maturity_date,
                    principal_minor,
                    annual_rate_ppm,
                    monthly_deposit_minor,
                    note.strip(),
                    now_iso(),
                    term_id,
                ),
            ).rowcount
            if changed == 0:
                # **0 列有兩種原因，要分開。** `WHERE term_id = ? AND status = 'active'`
                # 沒改到東西，可能是這一期不存在，也可能是它已續約／已結清。
                # 兩者該給的建議完全不同（「重新整理」對上「這一期已經產生過交易」），
                # 以前一律回 `DEPOSIT_TERM_NOT_EDITABLE` —— 於是找不到的期會被講成
                # 「只有存續中的期可以修改」，而使用者要去找一個畫面上根本沒有的東西。
                exists = connection.execute(
                    "SELECT 1 FROM deposit_terms WHERE term_id = ?", (term_id,)
                ).fetchone()
                # **兩個碼都寫成獨立的 raise，不要用三元運算式。** 掃錯誤碼的
                # AST 守門只看 `raise X("常數")`，包成 `X(a if c else b)` 之後
                # 兩個碼就都掃不到了 —— 第一版這樣寫，是守門自己報出來的。
                if exists is None:
                    raise NotFoundError("DEPOSIT_TERM_NOT_FOUND")
                raise NotFoundError("DEPOSIT_TERM_NOT_EDITABLE")
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="deposit_term.update",
                entity_type="deposit_term",
                entity_id=term_id,
                details={"annual_rate_ppm": annual_rate_ppm},
            )

    def set_term_status(
        self,
        term_id: str,
        status: str,
        *,
        actual_interest_minor: int | None = None,
        effective_rate_ppm: int | None = None,
    ) -> None:
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                """
                UPDATE deposit_terms
                SET status = ?,
                    actual_interest_minor = COALESCE(?, actual_interest_minor),
                    effective_rate_ppm = COALESCE(?, effective_rate_ppm),
                    updated_at = ?
                WHERE term_id = ?
                """,
                (status, actual_interest_minor, effective_rate_ppm, now_iso(), term_id),
            ).rowcount
            if changed == 0:
                raise NotFoundError("DEPOSIT_TERM_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
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


_TERM_SELECT = """
SELECT t.term_id, t.contract_id, t.sequence, t.start_date, t.maturity_date, t.principal_minor,
       t.annual_rate_ppm, t.monthly_deposit_minor, t.actual_interest_minor, t.status, t.note,
       t.effective_rate_ppm
FROM deposit_terms t
"""
"""**欄位一律加 `t.` 前綴。** `list_active_terms()` 要 join `deposit_contracts`，
而兩張表都有 `contract_id` 與 `status` —— 不加前綴的 SELECT 一 join 就是
`ambiguous column name`。"""


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
        effective_rate_ppm=(
            int(row["effective_rate_ppm"]) if row["effective_rate_ppm"] is not None else None
        ),
    )
