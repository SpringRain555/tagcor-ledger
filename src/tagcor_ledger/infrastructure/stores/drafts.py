"""模板與定期收支共用的草稿驗證。

兩者在 schema 上是不同的表，但**「一份還沒生效的交易草稿」是同一個概念** ——
名稱、流向、帳戶、類別、金額的規則一字不差。2026-08-22 拆檔之前它是
`AutomationStore._validate_draft`，模板與定期收支剛好在同一個 class 裡所以共用得到；
拆開之後如果各留一份，下次改規則就會只改到一邊。

這個模組**沒有 class** —— 它不是 store，不碰連線也不寫 SQL，
所以 `test_every_store_lives_in_the_stores_package` 那條守門與它無關。
"""

from __future__ import annotations

from tagcor_ledger.domain.models import RecurringSchedule, TransactionTemplate


def draft_identifier(draft: TransactionTemplate | RecurringSchedule) -> str:
    """草稿的主鍵。**兩種草稿的欄位名不同，但那是同一個角色。**

    有了它，`validate_draft()` 才能用一行同時守住模板與定期收支 —— 兩邊各寫一次
    檢查的話，下一個加進來的草稿型別又會漏掉。
    """
    if isinstance(draft, TransactionTemplate):
        return draft.template_id
    return draft.schedule_id


def validate_draft(draft: TransactionTemplate | RecurringSchedule) -> None:
    """存進資料庫之前的四道檢查。四種失敗各有自己的錯誤碼。"""
    # **主鍵要先擋。** 兩個 `save_*` 都是 `ON CONFLICT(<id>) DO UPDATE` 的 UPSERT，
    # 而空字串是一個合法的主鍵值 —— 傳 `template_id=""` 進來不會失敗，會安靜地
    # 寫出一列主鍵是空字串的模板，而且第二次再傳空字串就 UPDATE 到同一列上。
    # id 由 `new_template()` / `new_schedule()` 產，所以正常路徑走不到這裡，
    # 但「走不到」不是「擋住了」：2026-08 寫測試 helper 時就撞過一次，
    # 三個模板全部塌成同一列。
    if not draft_identifier(draft).strip():
        raise ValueError("AUTOMATION_ID_REQUIRED")
    if not draft.name.strip():
        raise ValueError("AUTOMATION_NAME_REQUIRED")
    if draft.entry_type == "transfer":
        if draft.destination_account_id is None or draft.category_id is not None:
            raise ValueError("TRANSFER_DRAFT_INVALID")
    elif draft.category_id is None or draft.destination_account_id is not None:
        raise ValueError("TRANSACTION_DRAFT_INVALID")
    if draft.amount_minor is not None and draft.amount_minor <= 0:
        raise ValueError("AUTOMATION_AMOUNT_INVALID")
