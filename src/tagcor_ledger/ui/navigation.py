"""側邊欄有哪些頁、順序是什麼、每一頁叫什麼。

## 為什麼要有這個檔

在這之前，導覽是拿**顯示文字**當 key 的：`show_page("快速記帳")`、
`self._page_rows["待確認"]`。所以把「快速記帳」改成「記帳」不是改一個字串，
是把導覽與側邊欄徽章一起弄壞 —— 而且是 `KeyError` 那種執行時才炸的壞法。

現在身分是 `PageId`，顯示文字是 `LABELS` 查出來的。**改 `LABELS` 不影響任何查表。**

## 分組為什麼沒有標題

`DAILY_PAGES` 與 `SETTINGS_PAGES` 這兩個名字**只存在於程式裡**。畫面上不寫
「日常」「設定」—— 分組靠位置表達：日常在上、設定沉到側邊欄最底，中間留白。

理由是這條路已經失敗兩次。第一版的分組標題跟其他項目一樣大、只是顏色淡一點；
第二版縮到 9pt、加字距、移出清單。兩次使用者的反應都是「這是什麼？為什麼點不動？」
—— 因為兩次都是**程度差異**：標籤與項目仍然是同一欄、同樣左對齊的灰字，
眼睛就是會把它們讀成一串清單，字級差幾級都一樣。

所以第三次不再讓標籤「看起來不可點」，而是**讓它不存在**。側邊欄裡的每一個字
都可以點，誤判機率因此是零。
"""

from __future__ import annotations

from enum import StrEnum


class PageId(StrEnum):
    """側邊欄一頁的身分。**這是 key，顯示文字不是。**

    `INBOX` 對到的類別目前仍叫 `PendingPage` —— id 描述的是概念（收件匣），
    不是實作的檔名。
    """

    ENTRY = "entry"
    INBOX = "inbox"
    TRANSACTIONS = "transactions"
    BALANCE = "balance"
    REFERENCE = "reference"
    OPERATION_SETTINGS = "operation_settings"
    SYSTEM_SETTINGS = "system_settings"


DAILY_PAGES: tuple[PageId, ...] = (
    PageId.ENTRY,
    PageId.INBOX,
    PageId.TRANSACTIONS,
    PageId.BALANCE,
)
"""每天會用到的頁，排在側邊欄上半。順序的唯一正本。"""

SETTINGS_PAGES: tuple[PageId, ...] = (
    PageId.REFERENCE,
    PageId.OPERATION_SETTINGS,
    PageId.SYSTEM_SETTINGS,
)
"""偶爾才動的頁，沉在側邊欄最底。順序的唯一正本。"""

LABELS: dict[PageId, str] = {
    PageId.ENTRY: "記帳",
    PageId.INBOX: "待確認",
    PageId.TRANSACTIONS: "交易紀錄",
    PageId.BALANCE: "餘額盤點",
    PageId.REFERENCE: "法規參考",
    PageId.OPERATION_SETTINGS: "操作設定",
    PageId.SYSTEM_SETTINGS: "系統設定",
}
"""側邊欄顯示的文字。**改這裡不會影響任何查表。**"""


ALL_PAGES: tuple[PageId, ...] = DAILY_PAGES + SETTINGS_PAGES
"""側邊欄由上到下的完整順序。"""
