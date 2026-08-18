# Storage Layout

## 程式與資料是分開的

**帳務資料不在專案資料夾裡。** 專案（`D:\Projects\tagcor-ledger`）是程式，將來若推上 remote 只會公開它；資料在 `<資料根目錄>`，永遠不進版控。

指標檔 `system_paths.json` 存在使用者設定目錄（`%LOCALAPPDATA%\TagCor\TagCorLedger\`），不放在 ledger SQLite 內 —— 程式必須先找到指標，才知道資料庫在哪。

## 一般使用

```text
data_root/                       ← <資料根目錄>
├── ledger/
│   ├── ledger.sqlite3
│   ├── ledger.sqlite3-wal
│   └── ledger.sqlite3-shm
├── backups/
│   └── backup_YYYYMMDD_HHMMSS_xxxxxx/
│       ├── ledger.sqlite3
│       └── backup_manifest.json
├── exports/
├── logs/
└── tmp/
```

`system_paths.json` 的內容：

```json
{
  "settings_version": 1,
  "data_root": "<資料根目錄>",
  "ledger_dir": "<資料根目錄>\\ledger",
  "backup_dir": "<資料根目錄>\\backups"
}
```

### `data_root` 是被驗證的不變量

- `ledger_dir` 與 `backup_dir` **必須都在 `data_root` 底下**，否則丟 `PATH_OUTSIDE_DATA_ROOT`。
- 兩者必須不同（`LEDGER_BACKUP_PATH_SAME`）、不可互相包含（`LEDGER_BACKUP_PATH_NESTED`）。
- `exports/`、`logs/`、`tmp/` 由 `data_root` 推導，**不是**由 `ledger_dir.parent` 推導。舊版用後者，等於讓 `ledger_dir` 的深度決定另外三個資料夾長在哪裡 —— 少一層就會長到別人的地盤上。
- 缺 `data_root` 的舊設定檔仍可讀，會退回 `ledger_dir.parent` 並在下次儲存時補上。

Windows 的路徑比對不分大小寫（`WindowsPath` 的相等與 `relative_to` 都是），所以只差大小寫的兩個路徑會被正確地當成同一個位置。`tests/integration/test_data_paths.py` 有測試鎖住這個行為。

### 搬移資料的順序不可調換

先複製到新位置 → 確認成功 → 寫指標檔 → 才刪舊檔。反過來會在搬移失敗時留下「指標指向新位置、資料還在舊位置」，下次啟動就在新位置建一個空資料庫，看起來像資料全部消失。

### 程式會碰到的位置只有這些

例外只有一個：「從外部檔案還原」會讀取使用者從對話框挑選的**任意**路徑。這是刻意保留的（否則無法從外接硬碟還原），由使用者主動觸發。

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