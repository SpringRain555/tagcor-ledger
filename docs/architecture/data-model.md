# 資料模型

## SQLite

資料庫位於 `data/ledger.sqlite3`。啟動時套用明確 migration，並啟用 `foreign_keys`、WAL、`busy_timeout` 與短交易。

## 核心資料表

- `accounts`：帳戶名稱、類型、幣別、期初餘額與封存狀態。
- `categories`：兩層父子分類。
- `payees`：對象／商家主檔。
- `transactions`：交易時間、類型、狀態、revision、對象 snapshot、備註與 correlation ID。
- `account_postings`：每筆交易對帳戶餘額的影響。
- `category_allocations`：交易金額分配；首輪一筆，未來可支援拆分。
- `audit_events`：與帳務寫入同 transaction 的操作紀錄。
- `transaction_fts`：對象、備註、分類與帳戶全文搜尋。
- `schema_migrations`、`settings`：資料版本與執行設定。
- `transaction_templates`：收入、支出與轉帳表單模板，金額可為空。
- `recurring_schedules`：日、週、月、年排程、間隔、結束日與下一個到期日。
- `scheduled_occurrences`：排程產生的 snapshot，狀態為 pending、confirmed 或 skipped。
- `balance_snapshots`：單一帳戶在指定時間的實際盤點金額、備註與狀態。

## 金額與 posting

- TWD 使用整數元，`Money.amount_minor` 不含浮點數。
- 支出：來源帳戶 posting 為負值。
- 收入：來源帳戶 posting 為正值。
- 轉帳：來源為負、目的為正，幣別與金額相同。
- 帳戶餘額為期初餘額加上所有有效交易 posting。

## 餘額盤點與差額

- 盤點只保存實際看到的帳戶金額，不建立交易或 posting。
- 第一筆有效盤點以前，以帳戶期初餘額作為基準。
- 後續盤點以上一筆同帳戶有效盤點作為基準。
- 預期金額 = 上次盤點實際金額 + 期間內該帳戶有效 posting 加總。
- 未解釋差額 = 本次盤點實際金額 - 預期金額。
- 補記、修改或作廢期間交易後，差額依查詢時資料重新計算，不儲存衍生結果。
- 作廢盤點保留紀錄與 audit，但不參與後續差額計算。

## 交易修改、替換與作廢

- 一般交易以 optimistic revision 更新。
- 轉帳修改使用原子替換：建立新轉帳、設定 `replaces_transaction_id`、作廢舊轉帳及寫入 audit 必須同時成功。
- 作廢只更新狀態與 revision，不刪除 posting 或 audit。

## Migration registry

- Schema v1：核心帳務、FTS5、settings 與 audit。
- Schema v2：`transactions.replaces_transaction_id`。
- Schema v3：模板、週期排程與待確認項目。
- Schema v4：餘額盤點 `balance_snapshots`。
- 每個版本只記錄一次於 `schema_migrations`，初始化可安全重跑。

## 排程規則

- 排程只建立待確認 snapshot，不直接建立交易。
- 修改排程不更新既有 occurrence。
- 月排程以開始日為 anchor；目標月份不存在該日時使用月末。
- 每次最多產生 366 期，`next_due_date` 保留下一個尚未生成日期。

## 索引

交易日期、狀態、帳戶、分類、payee、audit entity 與餘額盤點帳戶時間均有索引。交易頁依 `(occurred_at DESC, transaction_id DESC)` 使用 keyset cursor；盤點頁依 `(account_id, observed_at DESC, snapshot_id DESC)` 顯示最近盤點。
