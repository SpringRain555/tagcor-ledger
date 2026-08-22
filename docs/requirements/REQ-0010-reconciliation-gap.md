# REQ-0010 對帳缺口

狀態：**已記錄需求，刻意尚未實作。** 見下方「為什麼現在不做」。

## 問題

**盤點只能對總額。有存摺的帳戶其實能逐筆核對，但目前沒有地方記錄「這一筆我對過存摺了」。**

這個缺口是 Stage 1 的市場調查發現的。GnuCash 的文件把兩種帳戶分得很清楚
（[GnuCash Guide 5.4](https://www.gnucash.org/docs/v5/C/gnucash-guide/cbook-reconacct1.html)，
抓取 2026-08-18）：

> "Income and expense accounts are usually not reconciled, because there is no statement to check
> them against. **You also don't need to reconcile cash accounts, for the same reason.** With a cash
> account, though, you might want to **adjust the balance every once in a while**, so that your
> actual cash on hand matches the balance in your cash account."

對照到本專案的兩個帳戶：

| | 郵局 | 現金 |
|---|---|---|
| 有對帳依據 | 有（存摺明細） | 沒有 |
| 合適的動作 | **逐筆核對** | **定期盤點** |
| 差額的意義 | 記錯或漏記，該查到底 | 忘了記的零星消費，預期之內 |

**目前對兩者一視同仁。對現金是正確的，對郵局不夠。**

## 如果要做，該長什麼樣

Actual Budget 的做法可以直接參考
（[Reconciliation](https://actualbudget.org/docs/accounts/reconciliation/)，抓取 2026-08-18）：

1. 交易加一個**已核對**狀態（Actual 用 pending／cleared 兩態就夠，不需要第三態）。
2. 帳戶檢視分別顯示**已核對餘額**與**未核對餘額**，比單一個未解釋差額更能指出問題在哪。
3. 對帳完成後**上鎖**，防止事後手滑改動已對過的歷史。Actual 的鎖可解，但要明確操作。
4. **「把差額轉成調整交易」做成一顆明確的按鈕**，不是自動行為。
   Actual 的 `Create reconciliation transaction` 就是這樣做的。
   這與「盤點不建立交易、不建立 posting」不衝突 —— 盤點本身仍然不入帳，
   是使用者另外按一顆按鈕決定要不要補一筆調整。

## 為什麼現在不做

**不是因為不重要，是因為現在做會做錯。**

**一、「反正 v6 要 migration，順手加個欄位」是這個 codebase 已經吃過的虧。**
`EntryType.ADJUSTMENT` 從 v1 就躺在列舉、`CHECK` 約束與兩張顯示名稱表裡，
為了「將來的對帳調整」預留 —— 兩個月過去，**沒有任何程式碼會建立它**。
一個沒有 UI、沒有測試、沒有人記得為什麼存在的欄位，還是要被每一次 migration 測試帶著跑。
不要再製造第二個。

**二、急迫性沒有想像中高。** 兩個帳戶、每月約五十筆，差額不為零時用眼睛掃五十列對存摺是可行的。
逐筆打勾是「出事時」的工具，不是日常必需。

**三、真正該決定的資訊要到九月之後才有。** 使用者實際對過一兩次存摺，
才知道眼睛掃夠不夠用、以及需不需要上鎖。現在決定等於猜。

**四、migration 的成本沒有那麼可怕。** 這個專案的 migration 是手寫但測試扎實
（v1 → v5 全程可跑且有測試）。日後補一個 v7 的成本完全可以接受，比留一個空欄位便宜。

## 重新評估的時機

**2026 年 10 月底**，也就是實際使用兩個月、對過至少一次郵局存摺之後。屆時要回答：

- 差額不為零時，眼睛掃過去找得出來嗎？花多久？
- 有沒有發生過「以為對過了結果沒有」的情況？
- 現金帳戶的差額大概是什麼量級？大到需要調整交易嗎？

答案是「找不出來 / 花太久 / 發生過」的話，就照上面的設計做 schema v7。

## 那兩個為它留著的欄位

上面說 `EntryType.ADJUSTMENT` 是「先加著以後再說」的前車之鑑 —— 那句話仍然成立，
但 2026-08-22 複查時發現一件事：**這份需求的設計正好要用到它，以及 `account_type`。**

| 這份需求要的 | 對應的欄位 |
|---|---|
| 「郵局有存摺可逐筆核對／現金只能定期盤點」的區分 | `accounts.account_type` |
| 「把未解釋差額轉成一筆調整交易」那顆按鈕 | `EntryType.ADJUSTMENT` |

所以八月沒有把它們刪掉 —— 刪掉再在十月加回來是純粹的來回。改成
**`tests/unit/test_reserved_schema.py` 鎖住「保持沒有人用」**，
並把期限寫在那份檔案的 docstring 裡。上面那次評估**兩種結論都會讓它消失**：
要做，欄位就開始有值；不做，就在那時發 schema v8 清掉。
