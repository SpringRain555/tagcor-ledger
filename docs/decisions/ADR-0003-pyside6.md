# ADR-0003 使用 PySide6

## 狀態

已接受。

## 決策

桌面 UI 由 PyQt6 改為 PySide6。

## 理由

PySide6 是 Qt 官方 binding、授權較適合長期桌面發布，並與同工作區的 `webscouts` 技術棧一致。

## 後果

需要更新環境、Signal/import 與 UI 測試；舊 PyQt6 模組已從執行套件移除。
