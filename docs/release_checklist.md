# Release Checklist

## 自動基準

- Ruff、mypy、pytest 全部通過。
- migration、backup、CSV export 與 headless UI smoke 通過。
- 200,000 筆效能測試符合文件門檻。

## 乾淨 Windows

- 從空資料目錄啟動並建立 SQLite。
- 可新增支出、收入與兩個帳戶間轉帳。
- 關閉重開後餘額與交易仍正確。
- 搜尋、下一頁、作廢可用。
- 建立備份與 CSV 匯出成功。

## Legacy Migration

- 放入 Phase 2 CSV/JSON 後啟動。
- 確認先建立 legacy backup。
- 確認交易 ID、時間、snapshot 與 correlation ID 保留。
- 再次啟動不重複匯入。
