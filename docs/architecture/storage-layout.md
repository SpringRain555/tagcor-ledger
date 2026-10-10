# Storage Layout

## 資料放在哪裡：第一次啟動時選（ADR-0018）

[ADR-0018](../decisions/ADR-0018-choose-data-location-on-first-run.md) 之前，沒設定過路徑的人資料一律在使用者資料夾。
現在第一次啟動時跳出對話框問，三個選項：

| 選項 | 資料根 | 怎麼記住 |
|---|---|---|
| 放在程式資料夾裡（**預選**） | `<程式資料夾>\userdata` | **不寫指標檔**：每次從程式自己的位置往下找，整個資料夾搬走或帶到別台電腦都找得到 |
| 放在這台電腦的使用者資料夾 | `%LOCALAPPDATA%\TagCor\TagCorLedger` | 不寫指標檔：ADR-0018 之前唯一的預設位置，舊使用者的帳本就在這裡 |
| 其他位置… | 使用者挑的資料夾 | 寫指標檔 `system_paths.json`（跟「系統設定 → 資料路徑」同一條路）。重灌之後指標檔不見、資料還在，用它接回去 |

**每次啟動都照同樣四步找**（`app/data_location.py`）：指標檔 → `userdata` 裡的帳本 → 使用者資料夾裡的帳本 →
都沒有才問。「有帳本」＝資料根底下的 `data\ledger.sqlite3` 或 `ledger\ledger.sqlite3`。
**看的是帳本檔，不是資料夾**：啟動器的預檢在使用者選之前就會建 `logs\`。
按「確定」當場就建出帳本，所以「問過了沒」不另外記 —— 帳本本身就是證據。按「結束」什麼都不建，下次再問。

**`userdata` 整個在 `.gitignore` 裡** —— 匯出的交易 CSV、備份的 manifest 都不是 `*.sqlite3`，只靠副檔名的規則
擋不到。`tests/unit/test_data_location.py` 用 `git check-ignore` 守著。「其他位置…」不能挑在程式資料夾裡面
（`DATA_ROOT_INSIDE_PROGRAM_FOLDER`），理由相同。

**這個 repo 的開發者本機不用 `userdata`**：資料在專案外的資料根，由指標檔指定（CONVENTIONS §11），
推上 remote 公開的只有程式。

下面的路徑都是**範例**，實際位置由使用者自己決定。

指標檔 `system_paths.json` 存在使用者設定目錄（`%LOCALAPPDATA%\TagCor\TagCorLedger\`），不放在 ledger SQLite 內 —— 程式必須先找到指標，才知道資料庫在哪。

## 設定目錄（`config_dir`）

```text
%LOCALAPPDATA%\TagCor\TagCorLedger\
└── system_paths.json    指標檔：data_root / ledger_dir / backup_dir
```

**指標檔本身不是帳務資料，所以它不在 `data_root` 底下，也不進備份。**
`platformdirs.user_config_dir` 在 Windows 預設回傳 LOCALAPPDATA（不是 Roaming），
所以它跟「使用者資料夾」那個選項的資料根**是同一個資料夾** —— 清理那裡的資料時**只刪子資料夾，
不要整棵刪**，否則會把指標檔一起刪掉（`docs/lessons.md` 2026-08-18）。
選了程式資料夾的人，這裡也會有啟動器預檢留下的 `logs\` 與 `tmp\`（選之前的那一次），沒有帳本。

**舊版會在這裡留下 `window.json`**（上次的視窗大小與位置）。2026-09-27 起每次啟動
都是預設大小，那個檔案不讀也不寫 —— 放著無害，刪掉也無妨。

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

帳本資料夾叫 `ledger\` 或 `data\` 都認得。第一次啟動新建的資料根（三個選項都是）用 `data\`
（`path_settings.layout_for()`，跟 ADR-0018 之前的使用者資料夾一樣）。

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

**寫指標檔是分水嶺。** 在那之前失敗：刪掉新位置的複本，舊的原封不動（`PATH_SETTINGS_SAVE_FAILED` 等）。在那之後失敗：新位置那份就是正本，**不回頭刪它** —— 刪舊檔失敗（被別的程式開著）照樣回成功並提醒舊檔沒刪乾淨；重新接上 service 失敗回 `PATH_SETTINGS_RELOAD_FAILED`。2026-09-13 之前兩段共用一個 `except`，刪舊檔刪到一半時會連複本一起刪掉。

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

**備份只讀不寫。** 驗證、列出、還原都用 `mode=ro&immutable=1` 開那一份 `ledger.sqlite3`
（`maintenance._open_backup()`）：不取鎖、不留 `-wal`／`-shm`／`-journal`，連線沒有能力寫它。
**備份的定義就是那一個檔** —— manifest 的 SHA-256 只算它，所以旁邊就算躺著一個別處來的
`-wal` 也不會被套用（讀寫模式會）。備份本身是 WAL 格式，要改它的人（例如測試）寫完一定要
關連線，變更才會落進主檔。