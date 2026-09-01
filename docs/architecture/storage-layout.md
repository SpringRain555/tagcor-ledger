# Storage Layout

## 程式與資料是分開的

**帳務資料不在專案資料夾裡。** 專案資料夾是程式，推上 remote 公開的只有它；資料放在專案外的另一個位置（由「系統設定 → 資料路徑」指定），永遠不進版控。

下面的路徑都是**範例**，實際位置由使用者自己決定。

指標檔 `system_paths.json` 存在使用者設定目錄（`%LOCALAPPDATA%\TagCor\TagCorLedger\`），不放在 ledger SQLite 內 —— 程式必須先找到指標，才知道資料庫在哪。

## 設定目錄（`config_dir`）

```text
%LOCALAPPDATA%\TagCor\TagCorLedger\
├── system_paths.json    指標檔：data_root / ledger_dir / backup_dir
└── window.json          上次的視窗大小與位置
```

**這個目錄裡沒有帳務資料，所以它不在 `data_root` 底下，也不進備份。**
`platformdirs.user_config_dir` 在 Windows 預設回傳 LOCALAPPDATA（不是 Roaming），
所以它與舊版的資料樹會落在同一個父目錄 —— 清理舊資料樹時**只刪六個子資料夾，
不要整棵刪**，否則會把剛寫好的指標檔一起刪掉（`docs/lessons.md` 2026-08-18）。

`window.json` 是 **UI 狀態不是帳務資料**：

- 內容是 `x` / `y` / `width` / `height` 四個整數。
- **讀不到、格式壞掉、數字不合理，一律當成沒有設定過**，回退到 1280×760。
  這個檔案壞掉不該讓程式開不起來。
- 寫不進去也不報錯 —— 那不值得打斷關閉流程。
- **不進 `ledger.sqlite3`**：帳務資料庫的每一次 schema 變動都要寫 migration，
  為了「上次視窗多大」付那個代價不划算，而且它也不該出現在還原的語意裡
  （從三個月前的備份還原，不該把視窗變回三個月前的大小）。

## 一般使用

```text
data_root/                       ← 例：D:\Ledger\tagcor-ledger
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
  "data_root": "D:\\Ledger\\tagcor-ledger",
  "ledger_dir": "D:\\Ledger\\tagcor-ledger\\ledger",
  "backup_dir": "D:\\Ledger\\tagcor-ledger\\backups"
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