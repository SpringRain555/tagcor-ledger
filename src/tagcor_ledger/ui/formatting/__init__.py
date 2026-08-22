"""把 controller 回傳的 dict 轉成畫面上的字串。

**表格與清單的「一列長什麼樣」只在這個套件裡決定。** 頁面負責擺 widget 與接訊號，
不要在頁面裡自己拼列內容 —— 同一個狀態一旦有兩個拼法，兩張表就會對同一筆資料
講不同的話。有一條守門測試（`test_architecture.py`）擋著頁面自己定義 `*_values`。

**頁面自己的一次性訊息不搬進來**（「備份已建立：…」「CSV 已匯出：…」這類）。
分界是**「這句話會不會在別的地方也要用同一個講法」**。

三個模組：`primitives`（金額、日期、名稱表）、`rows`（每一張表的一列）、
`messages`（操作結果與例外翻譯）。**呼叫端一律從這個套件 import**，
不要指名子模組 —— 切法日後可能再調整，那是這個 `__init__` 的存在理由。
"""

from __future__ import annotations

from tagcor_ledger.ui.formatting.messages import (
    BACKUP_STATE_LABELS,
    backup_row_text,
    backup_state_text,
    error_text,
    result_message,
)
from tagcor_ledger.ui.formatting.primitives import (
    DEPOSIT_TERM_STATUS_NAMES,
    ENTRY_NAMES,
    FREQUENCY_NAMES,
    INBOX_SOURCE_NAMES,
    STATUS_NAMES,
    display_date,
    display_datetime,
    group_digits,
    minor_text,
    rate_text,
    signed_amount_text,
)
from tagcor_ledger.ui.formatting.rows import (
    account_values,
    balance_gap_values,
    category_values,
    deposit_contract_values,
    deposit_event_values,
    deposit_term_values,
    inbox_values,
    item_values,
    occurrence_values,
    overview_account_values,
    reference_entry_values,
    schedule_values,
    template_values,
    transaction_values,
)

__all__ = [
    "BACKUP_STATE_LABELS",
    "DEPOSIT_TERM_STATUS_NAMES",
    "ENTRY_NAMES",
    "FREQUENCY_NAMES",
    "INBOX_SOURCE_NAMES",
    "STATUS_NAMES",
    "account_values",
    "backup_row_text",
    "backup_state_text",
    "balance_gap_values",
    "category_values",
    "deposit_contract_values",
    "deposit_event_values",
    "deposit_term_values",
    "display_date",
    "display_datetime",
    "error_text",
    "group_digits",
    "inbox_values",
    "item_values",
    "minor_text",
    "occurrence_values",
    "overview_account_values",
    "rate_text",
    "reference_entry_values",
    "result_message",
    "schedule_values",
    "signed_amount_text",
    "template_values",
    "transaction_values",
]
