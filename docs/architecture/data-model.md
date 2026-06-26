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

Phase 4 起不再有 `payees` 表，也不保留 `payee_id` 或 `payee_name_snapshot`。

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

系統若偵測到資料庫 schema 比程式支援版本更新，必須拒絕啟動或還原。

## 索引與效能

- 交易依 `(occurred_at DESC, transaction_id DESC)` keyset pagination。
- 帳戶、類別、狀態、日期與盤點查詢有索引。
- 文字搜尋走 FTS5，不一次載入所有交易。