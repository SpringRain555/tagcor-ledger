# 查詢紀錄 2026-08-18

可重跑。**失敗與被擋的批次也留在這裡**，不從紀錄裡消失 —— 只寫命中什麼而不寫涵蓋範圍，
等於宣稱做了全面檢索。

## 治理與工具

| 項目 | 內容 |
|---|---|
| 擷取工具 | `tools/fetch.py`（本專案自寫） |
| 直譯器 | `%USERPROFILE%\.claude\runtimes\research\Scripts\python.exe`（research runtime，**不是**專案的 conda env） |
| 依賴 | `httpx`、`trafilatura`。**刻意不進 `environment.yaml`** —— App 本身永遠不發網路請求 |
| 節奏 | 同網域間隔 4 秒；單網域單次上限 8 個請求；429／503 立即全停不重試 |
| robots.txt | 依 RFC 9309 檢查；無 robots.txt 視為允許 |
| 產物 | `sources/raw/*.html`（原始位元組）、`sources/text/*.txt`（trafilatura 抽取）、`sources/manifest.jsonl` |
| 信任邊界 | 抓下來的內容**是資料不是指令**；未執行其中任何指示 |

## 查詢批次

| 批次 | 檢索詞／目標 | 擷取方式 | 結果 | 失敗或限制 |
|---|---|---|---|---|
| S1 | Firefly III 資料模型與分類概念 | WebSearch（限 `docs.firefly-iii.org`） | 取得 10 個 URL，選用 5 個 | 搜尋摘要不足以引用，一律改抓原頁 |
| S2 | Actual Budget 對帳／帳戶／本機優先 | WebSearch（限 `actualbudget.org`） | 取得 10 個 URL，選用 4 個 | 同上 |
| S3 | Firefly III 週期交易與帳戶類型 | WebSearch（限 `docs.firefly-iii.org`） | 補齊 2 個 URL | — |
| S4 | GnuCash 對帳與帳戶類型 | WebSearch（限 `gnucash.org`） | 取得 v5 文件 2 個 URL | 搜尋結果混入 v1.6／v1.8／v2.0 舊版，**已排除，只用 v5** |
| S5 | Beancount 帳戶階層與五大類 | WebSearch（未限網域） | 取得官方語法文件與 plaintextaccounting | 多數命中為第三方教學站，降級不用 |
| S6 | CWMoney 官網與功能 | WebSearch（未限網域） | 找到官網 `money.cmoney.tw/cwmoney` | App Store 頁未抓（預期為 JS 殼） |
| S7 | AndroMoney 官網與分類層級 | WebSearch（未限網域） | **未找到可用官網**，只取得部落格教學 | 見 F1 |
| B1 | 開源專案官方文件 12 個 URL | `tools/fetch.py` | **12/12 成功**，全 200 | 未觸發任何限流 |
| B2 | 台灣產品 5 個 URL | `tools/fetch.py` | **4/5 成功** | 見 F1 |

## 失敗與限制

| 代號 | 內容 |
|---|---|
| **F1** | `https://www.andromoney.com/` —— `SSL: CERTIFICATE_VERIFY_FAILED`，取不到伺服器憑證鏈。**不是限流，是站台憑證問題。** 未嘗試關閉憑證驗證繞過（不繞過存取控制）。AndroMoney 的分類層級因此只有 C 級部落格佐證 |
| **F2** | App Store／Google Play 產品頁**未嘗試抓取**。依既有實測紀錄假設為 JS 殼，且商店頁描述是行銷文案而非規格 |
| **F3** | 碎片記帳、YNAB **本次未抓取**。前者未找到穩定官方說明頁，後者為訂閱制且說明多在登入後 |
| **F4** | 台灣產品官網抽取字數偏低（597–1147 字），多為行銷頁而非功能規格。**判讀時已降級處理**，只引用逐字可查的宣稱 |

## 主要 URL（依類別）

**開源專案官方文件（A 級）**

- Firefly III：[what-to-use](https://docs.firefly-iii.org/explanation/data-classification/what-to-use/)、[best-practices](https://docs.firefly-iii.org/explanation/data-classification/best-practices/)、[accounts](https://docs.firefly-iii.org/explanation/financial-concepts/accounts/)、[account-types](https://docs.firefly-iii.org/references/firefly-iii/account-types/)、[recurring](https://docs.firefly-iii.org/explanation/financial-concepts/recurring/)
- Actual Budget：[reconciliation](https://actualbudget.org/docs/accounts/reconciliation/)、[accounts](https://actualbudget.org/docs/accounts/)、[budgeting](https://actualbudget.org/docs/budgeting/)、[starting-fresh](https://actualbudget.org/docs/getting-started/starting-fresh/)
- GnuCash：[guide 5.4 對帳](https://www.gnucash.org/docs/v5/C/gnucash-guide/cbook-reconacct1.html)、[manual 5.8 對帳](https://www.gnucash.org/docs/v5/C/gnucash-manual/acct-reconcile.html)
- 純文字記帳：[Beancount 語法](https://beancount.github.io/docs/beancount_language_syntax/)、[Choosing accounts](https://plaintextaccounting.org/Choosing-accounts)

**產品官網（A 級，但屬行銷頁）**

- [CWMoney](https://money.cmoney.tw/cwmoney)、[MoneyBook 麻布記帳](https://www.moneybook.com.tw/)

**第三方教學（C 級，僅補介面用詞）**

- [pkstep AndroMoney](https://www.pkstep.com/andromoney-app/)、[pkstep CWMoney](https://www.pkstep.com/cwmoney-app/)

## 可重現性

```powershell
$py = "$env:USERPROFILE\.claude\runtimes\research\Scripts\python.exe"
& $py tools\fetch.py --out docs\research\sources --urls-file docs\research\sources\urls-batch1.txt
& $py tools\fetch.py --out docs\research\sources --urls-file docs\research\sources\urls-batch2.txt
```

已在 manifest 有成功紀錄的 URL 會自動跳過；要強制重抓加 `--force`。

**17 筆全部 HTTP 200，合計 1,908,629 位元組。** 每筆的 SHA-256 在 `sources/manifest.jsonl`，
內容有變動時雜湊會對不上，即可判定該來源已改版、結論需重新確認。
