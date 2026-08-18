# 失敗紀錄

**這是 append-only 的檔案。** 目的是不要重蹈覆轍 —— 新的一筆加在最上面，舊的不刪不改。

每筆的格式：

```
## YYYY-MM-DD 一句話標題

**情境**：當時在做什麼。
**做了什麼**：實際採取的做法。
**為什麼失敗**：根因，不是症狀。
**結論**：現在的做法。
**不要再做**：具體的禁止事項。
```

---

## 2026-08-18 指標檔比資料早一步寫入，搬移失敗就等於資料消失

**情境**：把帳務資料從 `%LOCALAPPDATA%` 搬到 `<資料根目錄>` 之前，檢查既有的路徑搬移程式。

**做了什麼**：`LedgerController.save_path_settings` 的順序是「`path_settings.save()` 寫 JSON → `_move_current_database()` 搬資料庫」。

**為什麼失敗**：搬移會因為目標已存在、磁碟滿、資料庫被鎖等原因失敗，而此時 `system_paths.json` **已經**指向新位置。程式下次啟動會在新位置找不到資料庫，於是初始化一個空的 —— 使用者看到的是「所有帳都不見了」。`except` 只回傳失敗 `Result`，完全沒有回滾。這不是理論風險：資料一放到使用者會改名的 `D:\` 路徑上，觸發機率大幅上升。

**結論**：改成「複製到新位置 → 確認成功 → 寫指標檔 → 才刪舊檔」。任何一步失敗都會刪掉新位置的半成品複本，舊資料與舊指標檔原封不動。指標檔本身也改成寫暫存檔再 `os.replace` 的原子寫入。`tests/integration/test_data_paths.py::test_failed_move_leaves_settings_and_source_database_untouched` 鎖住這個行為。

**不要再做**：不要在資料就位之前寫任何指向新位置的指標。順序不是風格問題，是資料安全問題。

---

## 2026-08-18 從 `ledger_dir.parent` 推導其他資料夾，等於讓路徑深度決定資料長在哪

**情境**：設計 `data_root` 約束時檢查現有的路徑解析。

**做了什麼**：`app/paths.py` 與 `ui/controller.py` 都用 `root = ledger_dir.parent`，再由 `root` 推導 `exports/`、`logs/`、`tmp/`。

**為什麼失敗**：`validate_path_settings` 只檢查 `ledger_dir` 與 `backup_dir` 不相同、不互相包含、可寫，**完全沒有**「這些路徑要在同一個根目錄底下」的概念。所以 `ledger_dir` 少一層（例如設成 `<私人資料樹>\Finance\ledger` 而不是 `<資料根目錄>\ledger`），`root` 就變成 `<私人資料樹>\Finance`，程式會在別人的地盤上長出三個資料夾；`backup_dir` 更是可以設到任何可寫的地方。

**結論**：`system_paths.json` 新增明確的 `data_root`，五個資料夾全部由它推導或驗證必須在它底下，違反丟 `PATH_OUTSIDE_DATA_ROOT`。

**不要再做**：不要用「某個設定值的 parent」當成另一批路徑的基準。要有根目錄就明確存一個根目錄。

---

## 2026-08-18 指標檔就住在準備刪掉的那棵樹裡

**情境**：搬遷完成後要清掉 `%LOCALAPPDATA%\TagCor\TagCorLedger\` 這棵舊資料樹。

**做了什麼**：原本打算整棵 `Remove-Item -Recurse`。

**為什麼失敗**：`platformdirs.user_config_dir` 在 Windows 預設回傳 **LOCALAPPDATA** 而不是 Roaming（`roaming=False` 是預設值），所以 `system_paths.json` 的位置是 `%LOCALAPPDATA%\TagCor\TagCorLedger\system_paths.json` —— 和舊資料同一棵樹。整棵刪會把剛寫好的指標檔一起刪掉，程式下次啟動就退回預設路徑，又指回剛被刪掉的位置。

**結論**：只刪 `data`、`backups`、`config`、`exports`、`logs`、`tmp` 六個子資料夾，保留 `system_paths.json`。

**不要再做**：刪任何目錄樹之前先列出內容確認裡面有什麼。`user_config_dir` 與 `user_data_dir` 在 Windows 上會落在同一個父目錄，不要假設它們分開。

---

## 2026-06-27 conda 與 pip 混裝 PySide6 會讓 Qt DLL 載不起來

**情境**：建置與更新開發環境。

**做了什麼**：把 PySide6 放進 `pyproject.toml` 讓 pip 一起安裝，而環境本身是 conda 建的。

**為什麼失敗**：Windows 下 conda 的 PySide6 與 pip 的 PySide6 各自帶一套 Qt DLL，載入順序衝突，症狀是 `ImportError: DLL load failed while importing QtWidgets`。

**結論**：PySide6 只由 `environment.yaml` 的 conda dependency 管理，不放進 `pyproject.toml`。環境已經混裝的話，重建最乾淨。見 commit `593cc47`。

**不要再做**：不要把 PySide6 加回 `pyproject.toml` 的任何 dependency 區塊。

---

## 2026-06-24 CSV 當主資料庫撐不住帳務語意

**情境**：Phase 0–2 的原始設計用年份切分的 `ledger_YYYY.csv` 加 JSON 做主儲存。

**做了什麼**：新增一筆交易要讀寫整個檔案；沒有索引、外鍵，也沒有跨帳戶的原子交易。

**為什麼失敗**：轉帳要同時寫兩筆 posting，CSV 沒有 transaction 保證，中途失敗就是不平的帳。篩選與分頁只能全量載入後在 Python 裡排序，資料一多就沒救。

**結論**：改用 SQLite 作為唯一帳務真實來源，CSV 降級為匯出格式。見 `docs/decisions/ADR-0002-sqlite-canonical-store.md`。

**不要再做**：不要重新加入 CSV/JSON runtime store 或 importer。0.1.x 的資料用 0.2.0 做一次性轉換。
