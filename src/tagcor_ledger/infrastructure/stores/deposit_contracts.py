"""定存**合約**的持久化：建立、列出、修改、結束、刪除。

合約是持續性的關係（哪個帳戶、怎麼計息、到期怎麼處理）；每一次續存產生的是新的
一「期」，那在 `deposit_terms.py`。刪除合約會連同它的期與事件一起刪，所以那個方法
在這裡而不是在期那一邊 —— **它的判準是「這個合約有沒有入帳過」**。
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from tagcor_ledger.domain.deposits import DepositContract
from tagcor_ledger.infrastructure.clock import now_iso
from tagcor_ledger.infrastructure.database import connect_database, database_transaction
from tagcor_ledger.infrastructure.stores.base import (
    NotFoundError,
    StoreBase,
    new_correlation_id,
)


class DepositContractStore(StoreBase):
    def create_contract(
        self,
        *,
        account_id: str,
        name: str,
        interest_method: str,
        maturity_action: str,
        interest_destination_account_id: str | None,
        term_months: int,
        rate_type: str = "fixed",
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
            rate_type=rate_type,
        )
        timestamp = now_iso()
        with database_transaction(self.paths.database_path) as connection:
            self._require_deposit_account(connection, account_id)
            connection.execute(
                """
                INSERT INTO deposit_contracts(
                    contract_id, account_id, name, interest_method, maturity_action,
                    interest_destination_account_id, term_months, status, note,
                    rate_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    contract.rate_type,
                    timestamp,
                    timestamp,
                ),
            )
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
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
                       interest_destination_account_id, term_months, status, note, rate_type
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
                       interest_destination_account_id, term_months, status, note, rate_type
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
                correlation_id=new_correlation_id(),
                action="deposit_contract.close",
                entity_type="deposit_contract",
                entity_id=contract_id,
                details={},
            )

    def update_contract(
        self,
        contract_id: str,
        *,
        name: str,
        maturity_action: str,
        interest_destination_account_id: str | None,
        note: str | None = None,
    ) -> None:
        """只改名稱、到期轉存方式、利息轉入帳戶。

        **計息方式與期長刻意不能改。** 它們決定了已經產生出來的事件長什麼樣子，
        事後改會讓歷史難以解讀 —— 要換就結束這個合約、開一個新的。

        **`note=None` 表示「不要動備註」，不是「把備註清空」。** 以前它的預設值是
        `""` 而且無條件寫進 SQL，於是修改合約永遠會把備註洗掉 —— 而畫面上根本沒有
        備註欄位，使用者沒有任何機會發現。要清空就明確傳 `""`。
        """
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("DEPOSIT_NAME_REQUIRED")
        columns = ["name = ?", "maturity_action = ?", "interest_destination_account_id = ?"]
        values: list[object] = [
            clean_name,
            maturity_action,
            interest_destination_account_id,
        ]
        if note is not None:
            columns.append("note = ?")
            values.append(note.strip())
        columns.append("updated_at = ?")
        values.extend([now_iso(), contract_id])
        with database_transaction(self.paths.database_path) as connection:
            changed = connection.execute(
                f"""
                UPDATE deposit_contracts
                SET {", ".join(columns)}
                WHERE contract_id = ? AND status = 'active'
                """,
                tuple(values),
            ).rowcount
            if changed == 0:
                raise NotFoundError("DEPOSIT_CONTRACT_NOT_FOUND")
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="deposit_contract.update",
                entity_type="deposit_contract",
                entity_id=contract_id,
                details={"maturity_action": maturity_action},
            )

    def delete_contract(self, contract_id: str) -> None:
        """刪除從未入帳過的合約，連同它的期與待確認事件。

        **只要有任何一件事件已經確認入帳就不得刪除** —— 那代表帳本裡有交易指向它，
        刪掉會讓那些交易失去來歷。這種情形請改用「結束合約」。
        """
        with database_transaction(self.paths.database_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM deposit_contracts WHERE contract_id = ?", (contract_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("DEPOSIT_CONTRACT_NOT_FOUND")
            confirmed = connection.execute(
                """
                SELECT 1 FROM deposit_events e
                JOIN deposit_terms t ON t.term_id = e.term_id
                WHERE t.contract_id = ? AND e.status = 'confirmed'
                LIMIT 1
                """,
                (contract_id,),
            ).fetchone()
            if confirmed is not None:
                raise ValueError("DEPOSIT_CONTRACT_IN_USE")
            connection.execute(
                """
                DELETE FROM deposit_events
                WHERE term_id IN (SELECT term_id FROM deposit_terms WHERE contract_id = ?)
                """,
                (contract_id,),
            )
            connection.execute("DELETE FROM deposit_terms WHERE contract_id = ?", (contract_id,))
            connection.execute(
                "DELETE FROM deposit_contracts WHERE contract_id = ?", (contract_id,)
            )
            self._audit(
                connection,
                correlation_id=new_correlation_id(),
                action="deposit_contract.delete",
                entity_type="deposit_contract",
                entity_id=contract_id,
                details={},
            )

    @staticmethod
    def _require_deposit_account(connection: sqlite3.Connection, account_id: str) -> None:
        row = connection.execute(
            "SELECT status FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None or row["status"] != "active":
            raise ValueError("ACCOUNT_NOT_ACTIVE")


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
        rate_type=str(row["rate_type"]),
    )
