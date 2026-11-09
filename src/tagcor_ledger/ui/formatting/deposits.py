"""待確認定存利息的扣款標籤、算式與提示。"""

from __future__ import annotations

from typing import Any

from tagcor_ledger.domain.deposits import DepositEventType
from tagcor_ledger.ui.formatting.primitives import group_digits

DEPOSIT_WITHHELD_TAX_LABEL = "所得稅扣繳（TWD）"
DEPOSIT_NHI_PREMIUM_LABEL = "二代健保補充保費（TWD）"
DEPOSIT_TAX_DATA_UNAVAILABLE_NOTE = "稅務資料不可用，扣款請照存摺填。"
DEPOSIT_INTEREST_UNKNOWN_NOTE = "利率尚未填寫，利息與扣款請照存摺填。"


def deposit_event_calculation_text(item: dict[str, Any]) -> str:
    """領息或到期事件的利息毛額、兩筆扣款與預期入帳淨額。"""
    event_type = DepositEventType(str(item["event_type"]))
    if event_type not in {DepositEventType.INTEREST_PAYOUT, DepositEventType.MATURITY}:
        return ""
    gross = item.get("suggested_amount_minor")
    if gross is None:
        return ""
    withheld = int(item.get("suggested_withheld_tax_minor") or 0)
    premium = int(item.get("suggested_nhi_premium_minor") or 0)
    net_value = item.get("expected_amount_minor")
    net = int(net_value) if net_value is not None else int(gross) - withheld - premium
    return (
        f"試算：利息 {group_digits(gross)} − 扣繳 {group_digits(withheld)} "
        f"− 補充保費 {group_digits(premium)} ＝ 預期入帳 {group_digits(net)}。"
        "三格都以存摺為準。"
    )


def deposit_deduction_note(item: dict[str, Any]) -> str:
    """確認表單中，資料缺少時提醒使用者照存摺填。"""
    if item.get("deduction_data_unavailable"):
        return DEPOSIT_TAX_DATA_UNAVAILABLE_NOTE
    if item.get("interest_suggestion_unavailable"):
        return DEPOSIT_INTEREST_UNKNOWN_NOTE
    return ""


def deposit_confirm_note(item: dict[str, Any]) -> str:
    """確認對話框的說明：有試算時先列算式，缺少資料時再接提示。"""
    lines = [
        line
        for line in (deposit_event_calculation_text(item), deposit_deduction_note(item))
        if line
    ]
    return "\n".join(lines)
