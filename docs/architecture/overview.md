# 架構總覽

## 架構方向

TagCor Ledger 是單機、同進程 PySide6 應用程式。SQLite 提供交易一致性與索引查詢，不拆分 HTTP backend。

```text
PySide6 UI
  → UI Controller
    → Application Use Cases
      → Repository / Automation / Maintenance Services
        → SQLite / backup files / CSV exports
```

## 分層

- `domain`：Money、帳戶、分類與交易模型。
- `application`：交易、設定、模板、排程、待確認、帳戶與分類 use cases。
- `infrastructure`：ordered migration、SQLite repository、排程持久化、備份與匯出。
- `ui`：側邊導覽、快速輸入、交易表格、管理及待確認頁面。
- `app`：資料路徑、啟動與依賴組裝。

## 設計原則

- UI 不直接執行 SQL。
- Application 不依賴 Qt。
- 寫入與 audit 同一 transaction。
- 金額以整數 minor units 儲存。
- 交易列表使用 keyset pagination。
- CSV 是交換格式，不是執行期資料庫。
- 排程只在程式啟動或使用者要求時產生待確認項目，不啟動背景程序。

## 技術債控制

舊 PyQt6、TagPath、CSV/JSON runtime 與 importer 已從執行套件移除。歷史內容只保存在 `docs/archive/phase-0-2/`。
