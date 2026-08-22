"""資產總覽與待確認的合併 —— **這一段是聚合層，站在其他 section 上面。**

## 為什麼它繼承別的 section，其他 section 卻不互相繼承

其餘每一個 section 都只繼承 `ControllerBase`，彼此不呼叫對方（跟 `stores/` 底下
六個 store 一樣的紀律）。這裡是明說的例外：資產總覽這一頁的內容**就是**
「帳戶 ＋ 定存 ＋ 待確認 ＋ 盤點差額」四件事湊起來的，那不是耦合，那是它的定義。

寫成繼承而不是「呼叫服務再自己解包一次」，是因為後者會把
`latest_balance_gap()` 那三行判斷複製一份 —— 而複製出來的那一份遲早會分岔。
"""

from __future__ import annotations

from typing import Any

from tagcor_ledger.ui.controller.automation import AutomationSection
from tagcor_ledger.ui.controller.balance import BalanceSection
from tagcor_ledger.ui.controller.deposits import DepositSection
from tagcor_ledger.ui.controller.ledger import LedgerSection


class OverviewSection(LedgerSection, AutomationSection, DepositSection, BalanceSection):
    def overview_snapshot(self) -> dict[str, Any]:
        """資產總覽要顯示的每一項，一次組好。

        **頁面不自己拼這些規則。** 「總資產只加總使用中帳戶」、「封存帳戶餘額不為 0
        要另外講」這種判斷屬於「這個帳本現在是什麼狀況」，不屬於「怎麼擺 widget」。

        封存的意思是**不出現在選單**，不是錢消失了。所以總資產不算它，但也不能默默
        不提 —— 否則使用者會拿畫面上的數字去對存摺，然後對不起來。
        """
        accounts = self.account_options(include_archived=True)
        active = [item for item in accounts if item["status"] == "active"]
        settings = self.get_settings()
        default_account = next(
            (
                item
                for item in accounts
                if str(item["account_id"]) == settings.default_account_id
            ),
            None,
        )
        return {
            "total_minor": sum(int(item["balance_minor"]) for item in active),
            "accounts": active,
            "archived_with_balance": [
                item
                for item in accounts
                if item["status"] != "active" and int(item["balance_minor"]) != 0
            ],
            "deposit": self._next_deposit_term(),
            "inbox_count": self.inbox_count(),
            # 提醒是**現算**的，不讀 `balance_snapshot_reminder_due` 那個快取值：
            # 那個值只在啟動與存設定時更新，於是「剛盤點完，提醒還在」。
            "snapshot_due_account": (
                str(default_account["name"])
                if default_account is not None
                and self.refresh_balance_snapshot_reminder_due()
                else None
            ),
            "latest_gap": (
                self.latest_balance_gap(settings.default_account_id)
                if default_account is not None
                else None
            ),
        }

    def _next_deposit_term(self) -> dict[str, Any] | None:
        """最近一期會到期的定存。沒有存續中的合約就回傳 None（整段不顯示）。"""
        contracts = {
            str(contract["contract_id"]): contract
            for contract in self.list_deposit_contracts()
        }
        terms = [
            term
            for term in self.list_deposit_terms()
            if term["status"] == "active" and str(term["contract_id"]) in contracts
        ]
        if not terms:
            return None
        nearest = min(terms, key=lambda term: str(term["maturity_date"]))
        return {
            "contract_name": str(contracts[str(nearest["contract_id"])]["name"]),
            "maturity_date": str(nearest["maturity_date"]),
            "principal_minor": int(nearest["principal_minor"]),
            "total_principal_minor": sum(int(term["principal_minor"]) for term in terms),
            "contract_count": len(terms),
        }

    def list_inbox(self) -> list[dict[str, Any]]:
        """待確認的單一清單：定期收支與定存合成一份，依到期日排序。

        **使用者不需要知道待確認來自哪個子系統。** 以前是同一頁上下兩張表，於是
        「我還有幾件事要處理」得自己把兩個數字加起來，六顆按鈕還得先想清楚哪三顆
        是對上面那張表的。

        兩邊的欄位形狀確實不同，所以每一列多帶一個 `source`：
        `inbox_values()` 靠它決定怎麼顯示，「確認入帳」靠它決定分派給誰。
        排序的第二、三順位是 `source` 與 id —— 只用到期日排的話，同一天的項目
        每次重整順序都可能不一樣。
        """
        rows = [dict(item, source="schedule") for item in self.list_pending()]
        rows += [dict(item, source="deposit") for item in self.list_deposit_pending()]
        rows.sort(
            key=lambda item: (
                str(item["due_date"]),
                str(item["source"]),
                str(item.get("occurrence_id") or item.get("event_id") or ""),
            )
        )
        return rows

    def inbox_count(self) -> int:
        """待確認的總筆數 —— **定期收支與定存一起算**。

        側邊欄的數字與資產總覽的數字都走這一個方法。兩邊各自算就會出現「側邊欄說 2、
        總覽說 3」，而使用者沒有辦法知道哪一個才對。
        """
        return len(self.list_inbox())
