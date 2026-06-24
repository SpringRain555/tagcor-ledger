# 架構總覽

## 架構方向

TagCor Ledger 是單機、同進程 PySide6 應用程式。SQLite 提供交易一致性與索引查詢，不拆分 HTTP backend。

```text
PySide6 UI
  → UI Controller
    → Application Use Cases
      → Repository / Maintenance Services
        → SQLite / legacy files / backup files
```

## 分層

- `domain`：Money、帳戶、分類與交易模型。
- `application`：新增交易、轉帳、編輯、作廢、查詢、帳戶與分類管理。
- `infrastructure`：SQLite schema、migration、repository、備份與匯出。
- `ui`：側邊導覽、快速輸入、交易表格及管理頁面。
- `app`：資料路徑、啟動與依賴組裝。

## 設計原則

- UI 不直接執行 SQL。
- Application 不依賴 Qt。
- 寫入與 audit 同一 transaction。
- 金額以整數 minor units 儲存。
- 交易列表使用 keyset pagination。
- CSV 是交換格式，不是執行期資料庫。

## 技術債控制

Phase 2 CSV 與 PyQt6 模組暫時只保留 legacy compatibility，不可新增功能；完成相容期後應移出執行套件。
