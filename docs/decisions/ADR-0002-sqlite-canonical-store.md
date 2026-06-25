# ADR-0002 SQLite 作為 canonical store

## 狀態

已接受。

## 決策

使用 Python 內建 `sqlite3`，SQLite 為唯一帳務真實來源；CSV 僅保留匯出。

## 理由

CSV 新增交易需反覆讀寫全檔且無索引、外鍵或跨帳戶原子交易。SQLite 能提供穩定的新增成本、索引、transaction、backup API 與可驗證 migration。

## 後果

- 使用者不應直接編輯資料庫。
- 必須維護 schema migration、備份與匯出。
- 0.1.x CSV/JSON 必須先使用 0.2.0 轉成 SQLite，目前 runtime 不再包含 importer。
