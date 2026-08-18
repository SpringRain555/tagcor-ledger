# ADR-0004 資料與程式位置分離

## 狀態

已接受（2026-08-18）。

## 決策

帳務資料放在專案資料夾之外的 `<資料根目錄>`，
由 `system_paths.json` 的 `data_root` 明確指定，`ledger_dir` 與 `backup_dir` 都必須在它底下。

## 理由

專案日後可能推上 remote。程式與資料放在同一棵樹底下時，只要有一次 `.gitignore` 寫漏，
個人財務資料就會被公開，而且 git 歷史一旦推出去就收不回來。分開放讓這件事**在結構上不可能發生**，
而不是靠 `.gitignore` 的正確性。

`data_root` 要明確存而不是從 `ledger_dir.parent` 推導，是因為推導等於讓 `ledger_dir` 的深度
決定 `exports`／`logs`／`tmp` 長在哪裡 —— 少一層就會長到別人的地盤上，而且沒有任何檢查會擋。

## 後果

- 指標檔 `system_paths.json` **必須**留在使用者設定目錄。程式要先找到指標才知道資料在哪，
  這個先有雞先有蛋的問題無法在資料根目錄內解決。
- 改資料路徑變成三步程序（App 設定 → `.claude/settings.json` → 跑 `Verify.ps1` 確認無漂移），
  不是一步。
- agent 的讀寫邊界要另外用文字規則與 `.claude/settings.json` 維持，而那**攔不住 shell**。
- 帳務資料不在專案的備份範圍內，使用者要自行處理資料庫備份。
