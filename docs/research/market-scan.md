# 市面產品對照

調查日期：2026-08-18　｜　原始檔與雜湊：`sources/manifest.jsonl`　｜　查詢紀錄：`query-log.md`

**這份文件的用途是改變決定，不是介紹產品。** 每一節只回答三件事：借什麼、不借什麼、為什麼。
不影響 tagcor-ledger 設計的功能一律不寫。

**產品會改版。** 每個判讀都附抓取日期，超過半年請重查而不是沿用。

---

## 結論摘要

| 本專案的決定 | 市面對照 | 判定 |
|---|---|---|
| 兩層分類（類別／項目） | AndroMoney 同為兩層；Firefly III 用四個正交軸；純文字記帳可任意深 | **主流中段，維持** |
| 一律手動輸入，不接載具 | CWMoney／AndroMoney 都主打發票掃描與自動歸戶 | **異數，但刻意，維持** |
| 盤點只記差額，不自動產生調整交易 | Actual Budget 提供「建立對帳交易」按鈕；GnuCash 對現金帳戶建議定期調整 | **偏保守，Phase 6 應補一個明確的使用者動作** |
| 交易沒有「已核對」狀態 | Actual 有 pending／cleared／locked 三態 | **缺口，郵局存摺對帳會需要** |
| 電子票證只記儲值金額 | CWMoney 把悠遊卡／一卡通／iCash 當**帳戶**並自動歸戶 | **刻意相反，維持** |
| 排程只產生待確認，不自動入帳 | Firefly III 會自動建立交易 | **刻意相反，維持** |
| 定存要算出建議利息 | Firefly III 存利率與期間但**明確不計算** | **要小心，見下** |

---

## P1　分類要幾層

### Firefly III：四個正交軸，而不是一棵深樹

Firefly III 把分類拆成**四個互不隸屬**的維度：帳戶、預算、類別、標籤。官方的使用指引寫得很直白
（[best-practices](https://docs.firefly-iii.org/explanation/data-classification/best-practices/)、
[what-to-use](https://docs.firefly-iii.org/explanation/data-classification/what-to-use/)，抓取 2026-08-18）：

- **預算**是唯一能設上限的東西，所以用來抓大方向：伙食、居住、交通。
- **類別**用來把同一筆支出講得更精確，可以跨預算。
- **標籤**用來「評價」自己的消費 —— 作者自己有一個 `bad buy 2026` 標籤。
- **支出帳戶**用來記「錢付給誰」：每家店、每個電商各一個帳戶。

一句話值得注意：

> "You can't force a subset of categories for specific budgets though."

四個軸彼此不能約束，代表**使用者要自己維持一致性**。這是把複雜度從資料模型推給使用者。

### 純文字記帳：層數是取捨，不是有標準答案

[plaintextaccounting.org/Choosing-accounts](https://plaintextaccounting.org/Choosing-accounts)（抓取 2026-08-18）
直接把這題當成開放問題處理：

> "Should you have deep hierarchical account names or shallow ones? ... **Detailed categories allow more precise reports, simple ones require less mental effort.**"
>
> "Some hierarchy is natural for accounts and categories ... but if you prefer a flat list of account names, you can do that too."

另一句對本專案有實際意義：

> "You don't need to try to pick the perfect set of accounts at the start ... account names can always be changed later."

### AndroMoney：台灣主流是兩層

AndroMoney 的介面是「類別」加「子類別」，兩層，可自訂
（[pkstep 教學](https://www.pkstep.com/andromoney-app/)，C 級，抓取 2026-08-18）。

### 借什麼、不借什麼

**借：** 「開始時不必挑到完美，之後可以改名」這個設計前提。tagcor-ledger 已經有重新命名與封存，
方向正確 —— 但這代表**九月上線時不該花時間設計完美的類別樹**，先建最小可用的幾個，用一個月再調整。
應寫進 go-live runbook。

**不借：** Firefly III 的四軸模型。四個正交維度對一個單人、每月幾十筆的帳本是明顯過度設計，
而且它把一致性責任推給使用者。兩層（類別／項目）配合備註欄，複雜度與表達力的比例更好。

**維持兩層的理由**，現在有證據支撐而不只是直覺：層數在業界是公認的取捨而非有正確答案；
台灣同類產品也落在兩層；而「簡單的分類需要較少心智負擔」正好對齊本專案「手動輸入才感受得到花費」
的核心目的 —— 輸入時要做的決定越少，越不會放棄記帳。

---

## P3　對帳與盤點（支柱）

這是本專案與市面差距最大、也最值得補課的一塊。

### Actual Budget：三態 ＋ 上鎖 ＋ 一顆「建立對帳交易」按鈕

[Reconciliation](https://actualbudget.org/docs/accounts/reconciliation/)（抓取 2026-08-18）描述的流程：

1. 每筆交易有 **pending（灰）→ cleared（綠）** 的核對狀態，使用者逐筆點掉。
2. 開啟對帳工具，輸入銀行對帳單上的**實際餘額**。
3. 工具即時顯示**差額**，使用者逐筆核對直到差額歸零。
4. 按 **Lock transactions** 把已核對的交易上鎖。之後要編輯會跳警告。

還有一個直接對應本專案 Phase 6 構想的功能：

> "**Create reconciliation transaction** button ... to easily create a new transaction that automatically
> brings the value of the asset in line with the new valuation."

用途是追蹤房產、投資這類「只有市值、沒有逐筆交易」的資產。

### GnuCash：有對帳單的帳戶才對帳，現金帳戶只做定期調整

[GnuCash Guide 5.4](https://www.gnucash.org/docs/v5/C/gnucash-guide/cbook-reconacct1.html)（抓取 2026-08-18）
把兩種帳戶明確分開：

> "**Income and expense accounts are usually not reconciled, because there is no statement to check them
> against. You also don't need to reconcile cash accounts, for the same reason.** With a cash account,
> though, you might want to adjust the balance every once in a while, so that your actual cash on hand
> matches the balance in your cash account."

### 借什麼、不借什麼

**這一段直接命中你的兩個帳戶。** 郵局有存摺（＝有對帳單），現金沒有。GnuCash 說的正是這個區別：

| | 郵局 | 現金 |
|---|---|---|
| 有對帳依據嗎 | 有（存摺明細） | 沒有 |
| 合適的動作 | **逐筆核對** —— 每一筆都能對到存摺 | **定期盤點** —— 只能對總額 |
| 差額的意義 | 記錯或漏記，應該查到底 | 忘了記的零星消費，是預期中的 |

tagcor-ledger 目前對兩者一視同仁，都只做「盤點總額 ＋ 算未解釋差額」。這對現金是對的，
**對郵局是不夠的** —— 存摺能逐筆對，卻沒有地方記錄「這筆我對過了」。

**借（建議納入後續 Phase）：**

1. **交易的已核對狀態**。Actual 的 pending／cleared 兩態就夠，不需要第三態。有了它，郵局帳戶才能
   真正對帳；而且「未核對餘額」與「已核對餘額」分開顯示，比單一個未解釋差額更能指出問題在哪。
2. **對帳完成後上鎖**。防止事後手滑改動已對過的歷史。Actual 的做法是可解鎖但要明確操作，不是硬鎖。
3. **「把差額轉成調整交易」做成一顆明確的按鈕**，而不是自動行為。Actual 就是這樣做的。
   這與現有規則「盤點不建立交易、不建立 posting」不衝突 —— 盤點本身仍然不入帳，
   是使用者另外按一顆按鈕決定要不要補一筆調整。

**不借：** Actual 的三態（多出的 locked 其實是「已對帳」的衍生狀態）。兩態加一個「盤點已完成」
的標記就能表達同樣的事，狀態機更小。

---

## P7　定存這類帳戶怎麼建模

### Firefly III：存了利率，但明確不算

[Account types](https://docs.firefly-iii.org/references/firefly-iii/account-types/)（抓取 2026-08-18）：

- 資產帳戶有幾種「風味」：預設／共用／**儲蓄帳戶**／現金錢包／信用卡。
- 負債（貸款、債務、房貸）**可以設利率與計息期間**，但緊接著一句：

> "**Firefly III will not automatically calculate the result however, these fields are for your own
> administration.**"

### Actual Budget：預算內 / 預算外

[Accounts](https://actualbudget.org/docs/accounts/)（抓取 2026-08-18）：

> "**Off budget accounts** don't affect the budget and are meant to track stuff like investments and
> mortgages. **Transactions in off budget accounts can't be categorized; they simply track balances over
> time.**"

新增帳戶的流程是：本機帳戶或連結銀行 → 命名 → 選預算內／外 → **填目前餘額**。

### 借什麼、不借什麼

**借：**

1. **「只追蹤餘額、不分類」這個帳戶概念**正好描述定存。定存帳戶裡的動作只有本金進出與利息，
   沒有「這筆屬於哪個類別」的問題。本專案的定存帳戶應該比照辦理，
   在 UI 上不要求也不提供類別欄位。
2. **建立帳戶時就問目前餘額。** Actual 把它放進新增帳戶的四步之一。定存帳戶尤其需要 ——
   開帳前就存在的那一期，本金要靠期初餘額帶進來，不該留給使用者自己想到。

**要小心：** Firefly III 存了利率卻**選擇不計算**，這是一個值得認真對待的訊號。計息規則
（單利／複利、實際天數／365、進位到元、有無扣繳）在不同商品之間差異很大，算錯比不算更糟 ——
使用者會相信一個錯的數字。

因此定存的做法要維持計畫裡的分寸：**算出來的是建議值，不是權威值**，
UI 必須讓使用者覆寫成存摺上的實際金額，而且要標示清楚哪一個是程式算的、哪一個是實際入帳的。
計息規則本身當時列入法規庫的查證項目，不憑記憶寫（後續發展見 `open-questions.md` Q5）。

---

## P8　電子票證：本專案刻意與市場相反

CWMoney 官網首頁（[money.cmoney.tw/cwmoney](https://money.cmoney.tw/cwmoney)，A 級，抓取 2026-08-18）
的主打功能之一，逐字是：

> 「歸戶悠遊卡、一卡通、iCash，同步雲端發票自動記帳，**連帳戶都幫你分好了！**」

也就是說市場主流的做法是：**電子票證＝一個帳戶**，而且**發票自動匯入**。這兩件事正好是
tagcor-ledger 明確拒絕的兩件事。

### 為什麼仍然維持相反的做法

不是因為做不到，是因為目的不同。本專案的前提是「手動輸入才讓使用者感受到花費的程度」。
自動歸戶把感受拿掉了 —— 卡片餘額自己會變，使用者不會經歷「我又花了 500」這個瞬間。

而且「只記儲值金額」在帳務上是自洽的：儲值當下錢確實離開了郵局或現金，那一刻就是支出。
之後卡裡怎麼用，對「我這個月花了多少」這個問題不產生新資訊。代價是看不出電子票證的消費結構 ——
這個代價是使用者知情且接受的。

**維持現況。** 並且要把它寫成硬規則（已寫進 `AGENTS.md`）：不得為一卡通／悠遊卡建立帳戶或餘額欄位。
否則日後很容易有人「順手」加上去，因為市面產品都這樣做。

---

## P4　週期交易：自動入帳 vs 待確認

[Firefly III recurring](https://docs.firefly-iii.org/explanation/financial-concepts/recurring/)
（抓取 2026-08-18）：

> "Firefly III features the ability to **automatically create transactions**, so you don't have to."
>
> "Most users use recurring transactions **when they do not import data** into Firefly III."

值得注意的是它的定位：自動建立交易是**匯入功能的替代品**，給沒有在匯入資料的人用的。

**維持現況。** tagcor-ledger 的排程只產生待確認項目、由使用者確認才入帳，與「手動輸入」的核心
一致。Firefly 的自動建立解的是「我懶得輸入」，本專案解的是「我要感受到花費」，目的不同，
不該照抄。定存到期產生的待確認項目也依此辦理。

---

## 尚未有足夠證據的部分

以下在本次檢索範圍內沒有取得可靠一手來源，**不代表不存在**，詳見 `open-questions.md`：

- **P2 降低手動輸入摩擦的具體手法** —— 只從 CWMoney 官網取得功能名稱（月曆記帳、桌面快速記帳、
  GPS 與照片記帳），沒有取得操作流程細節。
- **P5 初次設定流程** —— 只有 Actual 的四步驟，缺其他產品對照。
- **P6 繁體中文用詞對照** —— AndroMoney 官網憑證驗證失敗抓不到，目前只有 C 級部落格佐證。
- **碎片記帳、YNAB** —— 本次未抓取。
