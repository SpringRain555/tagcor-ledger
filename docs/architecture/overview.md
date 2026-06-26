# Architecture Overview

```text
PySide6 UI
  → LedgerController
  → application services / Result
  → infrastructure stores / SQLite / backup / CSV
  → domain models
```

## 分層

- `domain`：純模型與 Money，不依賴 Qt 或 SQLite。
- `application`：交易、設定、帳戶/類別、模板/排程、盤點、備份/還原/重製 use cases。
- `infrastructure`：SQLite schema migration、store、backup API、CSV export。
- `ui`：PySide6 widgets 與 controller。
- `app`：啟動、路徑、外部系統設定。

## 資料流

UI 不直接操作 SQL。所有 UI 操作透過 controller 呼叫 application service。service 回傳 `Result`，UI 將錯誤顯示為繁體中文訊息。

## Phase 4 邊界

- 系統路徑設定在 SQLite 外部，因為資料庫路徑本身不能可靠存放在資料庫內。
- payee 已移除；「項目」負責描述具體收支項目，備註負責補充說明。
- 備份只由明確手動操作觸發。