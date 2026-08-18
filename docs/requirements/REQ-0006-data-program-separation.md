# REQ-0006 資料與程式位置分離

狀態：**已實作**（v0.6.2，2026-08-18）

## 目標

把「運作的地方」與「儲存的地方」分開，讓專案日後若推上 remote 只公開程式，
不公開任何個人財務資料。同時讓帳務資料的位置成為一個**被驗證的不變量**，
而不是靠慣例維持。

## 功能需求

- 帳務資料放在專案資料夾之外，預設 `<資料根目錄>`。
- `system_paths.json` 新增 `data_root` 與 `settings_version` 欄位。
- `ledger_dir` 與 `backup_dir` **必須都在 `data_root` 底下**，否則丟 `PATH_OUTSIDE_DATA_ROOT`。
- `exports`、`logs`、`tmp` 由 `data_root` 推導，**不得**由 `ledger_dir.parent` 推導。
- 缺 `data_root` 的舊設定檔仍可讀，退回 `ledger_dir.parent`，下次儲存時補上。
- 指標檔用「寫暫存檔再 `os.replace`」的原子寫入。
- **搬移資料的順序**：複製到新位置 → 確認成功 → 寫指標檔 → 才刪舊檔。
  任何一步失敗都要刪掉新位置的半成品複本，舊資料與舊指標檔保持原狀。
- agent 的讀寫邊界寫在 `AGENTS.md`，並由 `.claude/settings.json` 的規則輔助。
- `Verify.ps1` 檢查 `system_paths.json` 與 `.claude/settings.json` 是否漂移。

## 邊界

- 指標檔本身**必須**留在使用者設定目錄（`%LOCALAPPDATA%\TagCor\TagCorLedger\`）。
  程式要先找到指標才知道資料在哪，這個先有雞先有蛋的問題無法在資料根目錄內解決。
- 「從外部檔案還原」仍會讀取使用者從對話框挑選的**任意**路徑。
  這是刻意保留的例外，否則無法從外接硬碟還原。
- deny 規則**攔不住 shell**。它防的是手滑，不是安全邊界。
- 帳務資料庫的完整備份由使用者自行處理，本專案不提供同步腳本。

## 驗收

- `python -m tagcor_ledger --json` 的七個路徑都指向新位置。
- `backup_dir` 設到 `data_root` 外會被拒；`ledger_dir` 少一層會被拒。
- 搬移失敗後，指標檔內容與來源資料庫都必須一字不差地維持原狀。
- 只差大小寫的兩個路徑必須被當成同一個位置（Windows 語意）。
- 漂移檢查對現況零誤報；故意改壞 `settings.json` 的路徑會失敗。
