# Storage Layout

## 一般使用

系統路徑設定儲存在使用者設定目錄中的外部 JSON，不放在 ledger SQLite 內。

```text
ledger_dir/
├── ledger.sqlite3
├── ledger.sqlite3-wal
└── ledger.sqlite3-shm

backup_dir/
└── backup_YYYYMMDD_HHMMSS_xxxxxx/
    ├── ledger.sqlite3
    └── backup_manifest.json
```

`ledger_dir` 與 `backup_dir` 必須不同，且不可互相包含。

## 開發/測試 `--data-dir`

指定 `--data-dir <root>` 時使用舊式開發布局：

```text
root/
├── config/
├── data/
│   └── ledger.sqlite3
├── backups/
├── exports/
├── logs/
└── tmp/
```

此模式方便測試，不代表一般使用者必須把資料放在專案資料夾。

## 備份

備份使用 SQLite backup API，並寫入 manifest：

- `manifest_version`
- `database_schema_version`
- `backup_id`
- `created_at`
- `reason`
- `database_file`
- `sha256`
- `integrity_check`

還原前必須驗證 checksum、`PRAGMA integrity_check` 與 schema version。