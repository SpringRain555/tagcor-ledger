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

## 金額與 posting

- TWD 使用整數元，`Money.amount_minor` 不含浮點數。
- 支出：來源帳戶 posting 為負值。
- 收入：來源帳戶 posting 為正值。
- 轉帳：來源為負、目的為正，幣別與金額相同。
- 帳戶餘額為期初餘額加上所有有效交易 posting。

## 交易修改與作廢

- 一般交易以 optimistic revision 更新。
- 轉帳首輪不提供直接編輯，應作廢後重建。
- 作廢只更新狀態與 revision，不刪除 posting 或 audit。

## 索引

交易日期、狀態、帳戶、分類、payee 與 audit entity 均有索引。交易頁依 `(occurred_at DESC, transaction_id DESC)` 使用 keyset cursor。
