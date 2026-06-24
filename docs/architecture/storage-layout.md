# 儲存配置

```text
TagCorLedger/
├── data/
│   └── ledger.sqlite3
├── backups/
│   ├── backup_YYYYMMDD_HHMMSS_xxxxxx/
│   │   ├── ledger.sqlite3
│   │   └── backup_manifest.json
│   └── legacy-import-.../
├── exports/
│   └── transactions_YYYYMMDD_HHMMSS.csv
├── logs/
│   └── legacy_migration_report.json
├── config/        # 僅 legacy import 相容
└── tmp/
```

## 規則

- `ledger.sqlite3` 是唯一帳務真實來源。
- `-wal`、`-shm` 是 SQLite 執行期檔案，不可手動搬移。
- 備份使用 SQLite backup API，不直接複製使用中的資料庫。
- 匯出檔不是備份。
- legacy 原檔在匯入前完整複製並記錄 SHA-256。
