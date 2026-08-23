"""定存的 use case：建合約、產生到期待確認、確認入帳、續約。

## 最重要的一條：程式不自動入帳

到期與每月領息**只產生待確認項目**，成為交易一定要經過使用者按下確認。這與既有的
「排程只產生待確認項目」一致，也與「手動輸入才感受得到花費」的初衷一致。

`tests/integration/test_deposits.py` 有一個測試專門斷言：產生事件之後
**`account_postings` 一列都沒有增加**。

## 第二重要的一條：建檔之前的歷史不產生項目

既有定存比開始記帳早，而那段期間的利息已經含在帳戶的期初餘額裡。所以
`contract.recorded_on`（建檔那天）是產生的下界 —— 見
[ADR-0012](../../../../docs/decisions/ADR-0012-deposit-events-start-at-record-date.md)。

## 三 × 四效果矩陣

| 計息方式 | 期間內每月 | 到期 |
|---|---|---|
| 整存整付 | 無 | 依到期及轉存方式 |
| 存本取息 | 收入：利息 → 指定帳戶 | 依到期及轉存方式（本金部分） |
| 零存整付 | 轉帳：指定帳戶 → 定存 | 依到期及轉存方式 |

到期那天做什麼：

| 到期及轉存方式 | 本金 | 利息 | 這一期 |
|---|---|---|---|
| 不自動轉存 | 轉帳：定存 → 指定帳戶 | 收入 → 指定帳戶 | 已結清 |
| 本金（息）自動轉存本人帳戶 | 轉帳：定存 → 指定帳戶 | 收入 → 指定帳戶 | 已結清 |
| 本金無限次數自動轉期續存，利息轉存帳戶 | 留在定存（不產生交易） | 收入 → 指定帳戶 | 已續約 |
| 本息無限次數自動轉期續存 | 留在定存 | 收入 → **定存帳戶** | 已續約，下期本金含息 |

前兩種在帳本上的效果**完全相同**，差別只在銀行端是否自動處理。這裡誠實記下來，
免得日後有人以為漏實作了什麼。

## 利息是收入，不是轉帳

利息是新產生的錢，所以記成**收入**；只有本金在兩個帳戶之間移動時才是**轉帳**。
把利息記成轉帳會讓總資產憑空不變，看不出來自己賺了多少。

## 這個套件怎麼組起來

`DepositService` 由三個 section 用**繼承**組成，比照 `LedgerStore` 與
`LedgerController`。用繼承而不是委派的理由跟那兩個一樣：拆檔只決定「這個 `def`
放在哪個檔案」，換成委派要手寫二十幾個轉發方法，而每一個都是新的出錯機會。

| section | 負責 |
|---|---|
| `ContractSection` | 合約與期：建立、修改、刪除、列出 |
| `EventSection` | 到期與每月領息怎麼長出待確認項目 |
| `PostingSection` | 確認之後產生哪幾筆交易、這一期怎麼走 |

**section 之間彼此不呼叫對方**（與 `stores/` 同一條紀律）—— 拆之前用 AST 確認過
二十個方法的呼叫關係全部落在自己的 section 裡，所以這裡不需要
`ui/controller/overview.py` 那種聚合層例外。
"""

from __future__ import annotations

from tagcor_ledger.application.deposits.base import (
    MATURITY_LEAD_DAYS,
    DepositPosting,
)
from tagcor_ledger.application.deposits.contracts import ContractSection
from tagcor_ledger.application.deposits.events import EventSection
from tagcor_ledger.application.deposits.postings import PostingSection

__all__ = ["MATURITY_LEAD_DAYS", "DepositPosting", "DepositService"]


class DepositService(ContractSection, EventSection, PostingSection):
    """定存的 use case 入口。**這裡只組裝，方法在各 section 模組裡。**"""
