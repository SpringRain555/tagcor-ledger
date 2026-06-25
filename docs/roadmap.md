# TagCor Ledger Roadmap

## 穩固核心版

- [x] 建立 Git baseline 與文件制度。
- [x] SQLite schema、WAL、外鍵、FTS5 與索引。
- [x] 帳戶、兩層分類、payee、posting 與 audit。
- [x] 收入、支出、轉帳、修改、作廢與 keyset pagination。
- [x] ordered SQLite migration registry。
- [x] PySide6 側邊導覽與繁中快速記帳。
- [x] SQLite backup 與 CSV 匯出。
- [x] 完成核心自動驗收與 200,000 筆效能基準。

## Phase 1–2

- [x] 組合篩選、雙向分頁及可設定頁面筆數。
- [x] 原子轉帳替換。
- [x] 帳戶與分類恢復。
- [x] 備份列舉、驗證、外部還原及還原前備份。
- [x] 預設帳戶、流向、頁面筆數及啟動備份設定。
- [x] 移除 PyQt6、TagPath、CSV/JSON runtime 與 legacy importer。
- [x] 模板、複製交易及 payee 自動完成。
- [x] 日／週／月／年週期排程與 366 期漏期生成。
- [x] 待確認修改、確認、略過及批次確認。

## 後續候選

1. 月預算與基本報表。
2. 拆分交易 UI。
3. 正式對帳與匯入規則。
4. 多幣別與匯率模型。
5. Windows Installer。
