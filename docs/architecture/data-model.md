# Data Model

## SQLite 主資料庫

主資料庫為 `ledger.sqlite3`。所有帳務變更都透過 SQLite transaction 完成，啟用 foreign keys、WAL 與 busy timeout。

## 主要表

- `accounts`：帳戶主檔，含幣別、期初餘額、狀態。
- `categories`：兩層類別/項目；第一層為類別，第二層為項目。
- `transactions`：交易主檔，含類型、狀態、revision、時間、備註、source、correlation ID。
- `account_postings`：帳戶異動。收入/支出一筆 posting；轉帳一正一負兩筆 posting。
- `category_allocations`：類別/項目配置。目前 UI 只建立一筆 allocation，schema 保留未來拆分交易能力。
- `audit_events`：帳務與設定變更 audit。
- `transaction_fts`：FTS5 搜尋備註、類別/項目與帳戶。
- `settings`：ledger 內的一般偏好，例如預設帳戶、預設流向、每頁筆數、盤點提醒。
- `schema_migrations`：migration registry。
- `transaction_templates`：交易模板。
- `recurring_schedules`：週期排程。
- `scheduled_occurrences`：待確認項目 snapshot。
- `balance_snapshots`：餘額盤點。
- `deposit_contracts`：定存的持續關係 —— 哪個帳戶、怎麼計息、到期怎麼處理、利率是固定還是機動。
- `deposit_terms`：定存的**每一期**。續存產生新的一期，舊的不改寫，所以歷次利率留得下來。
- `deposit_events`：定存的到期與領息，等待使用者確認。**不走 `scheduled_occurrences`**
  —— 排程引擎不需要懂計息 —— 但在同一個「待確認」頁呈現，維持單一收件匣。

Phase 4 起不再有 `payees` 表，也不保留 `payee_id` 或 `payee_name_snapshot`。

### 刻意不存在的表與欄位

| 不存在的東西 | 為什麼 | 誰在守 |
|---|---|---|
| `payees` 表、`payee_id`、`payee_name_snapshot` | Phase 4 移除，用「項目」＋「備註」表達 | `test_schema_v1_migrates_to_latest_and_reruns_safely` |
| 卡內餘額（`card_balance`、`stored_value`、`icash`…） | 電子票證只記儲值當下的支出，見 `AGENTS.md` 與 ADR-0006 | `test_schema_never_grows_a_stored_value_card_concept` |

## 金額規則

- 金額使用 minor unit 整數：`Money(amount_minor: int, currency: str)`。
- 目前固定 TWD。
- 支出 posting 為負，收入 posting 為正。
- 轉帳在同一 transaction 內建立來源帳戶負 posting 與目的帳戶正 posting。

## 餘額盤點

盤點不建立交易、不建立 posting。差額計算：

- 第一筆盤點前，以帳戶期初餘額作為基準。
- 後續盤點以前一筆有效盤點作為基準。
- 預期金額 = 上次盤點實際金額 + 期間有效 posting 加總。
- 未解釋差額 = 本次盤點實際金額 - 預期金額。

## Migration registry

- v1：核心帳務表、舊 payee schema、FTS、settings、audit。
- v2：`transactions.replaces_transaction_id`。
- v3：模板、週期排程、待確認項目。
- v4：`balance_snapshots`。
- v5：移除 payee schema、重建 FTS、移除啟動備份設定。
- v6：`deposit_contracts`、`deposit_terms`、`deposit_events` 三張表與各自的索引。
- v7：`deposit_contracts.rate_type`（`fixed`／`floating`）、
  `deposit_terms.effective_rate_ppm`（從實際利息反推的年利率）。

**v7 是新的一版而不是改 v6**，因為使用者的資料庫已經跑過 v6 了 —— migration 記錄下來
就不會再跑第二次，改 v6 的內容對既有資料庫毫無效果。

系統若偵測到資料庫 schema 比程式支援版本更新，必須拒絕啟動或還原。

## 定存的金額欄位

- `principal_minor`、`actual_interest_minor`、`suggested_amount_minor` 一律是 minor unit 整數。
- **年利率存成 `annual_rate_ppm`：百萬分之一為單位的整數。** 1.6% 是 `16000`。
  不存小數也不存百分比字串 —— 利率會參與金額運算，浮點數進得去就出得來。
- `annual_rate_ppm` 可為 NULL。查不到牌告利率時合約照樣成立，只是算不出建議利息。
  機動利率**刻意不預先填數字**：存的當下填的值，到期時多半已經不是那個值了。
- 建議利息永遠**不是權威值**，以存摺上的實際金額為準。

## 索引與效能

- 交易依 `(occurred_at DESC, transaction_id DESC)` keyset pagination。
- 帳戶、類別、狀態、日期與盤點查詢有索引。
- 文字搜尋走 FTS5，不一次載入所有交易。