# 儲存配置

```text
TagCorLedger/
├── data/
│   └── ledger.sqlite3
├── backups/
│   ├── backup_YYYYMMDD_HHMMSS_xxxxxx/
│   │   ├── ledger.sqlite3
│   │   └── backup_manifest.json
├── exports/
│   ├── transactions_YYYYMMDD_HHMMSS.csv
│   └── balance_snapshots_YYYYMMDD_HHMMSS.csv
├── logs/
├── config/
└── tmp/
```

## 規則

- `ledger.sqlite3` 是唯一帳務真實來源。
- `-wal`、`-shm` 是 SQLite 執行期檔案，不可手動搬移。
- 備份使用 SQLite backup API，不直接複製使用中的資料庫。
- 匯出檔不是備份。
- 交易與餘額盤點 CSV 都是 UTF-8 BOM 人類可讀匯出，不是可還原資料庫。
- 外部備份資料夾必須同時包含資料庫與 manifest。
- 0.1.x CSV/JSON 不由目前 runtime 讀取；須先以 0.2.0 轉為 SQLite。
