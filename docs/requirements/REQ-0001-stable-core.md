# REQ-0001：穩固核心

## 目標

建立可長期使用的本機個人記帳核心，主資料庫使用 SQLite，介面使用繁體中文 PySide6。

## 需求

1. Windows-first、本機優先。
2. 金額使用 `Money(amount_minor: int, currency: str)`，禁止 float。
3. 固定 TWD 與 Asia/Taipei。
4. 支援帳戶、兩層類別/項目、收入、支出、同幣別轉帳、編輯與作廢。
5. 轉帳必須在同一 SQLite transaction 建立來源與目的 posting。
6. 交易、posting、allocation 與 audit 必須保持一致。
7. 交易列表不得一次載入全部資料，需使用分頁。
8. CSV 只作匯出/交換格式，不作主資料庫。

## Phase 4 修正

- UI 與文件使用「類別／項目」，不再使用「分類／細項」。
- 已移除「對象／商家」欄位；具體收支內容由「項目」與「備註」表達。
- 備份改為手動建立。