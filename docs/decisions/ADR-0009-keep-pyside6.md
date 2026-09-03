# ADR-0009 UI 技術維持 PySide6

## 狀態

已接受（2026-08-18）。曾評估改為 Vue 本機端網頁，**決定不換**。

## 決策

UI 維持 PySide6。核心的 domain／application／infrastructure 分層不動。

## 背景

2026-08 提出的問題是：實作語言選得適當嗎？操作介面改成 Vue 的本機端網頁是否更適當？

分層讓 UI **確實可換** —— `domain/` 不依賴 Qt、`application/` 不碰 UI，
這兩條規則被確實遵守。實際比例：

| | 行數 | 換 UI 的命運 |
|---|---|---|
| domain ＋ application ＋ infrastructure ＋ app ＋ main | 4,452 | 完全可重用 |
| `ui/`（含 419 行 QSS） | 2,597 ＋ 419 | 丟掉 |

UI 只佔 Python 的 37%，而且 30 個測試裡只有 `tests/ui/` 的 4 個會受影響。
**技術上可行，成本也不算高。**

## 理由（為什麼還是不換）

**一、localhost HTTP server 會打破「純本機不連網」。** 綁 port 就是開網路監聽，
機器上任何行程都能打它，而帳務 API 沒有任何驗證。這是與 ADR-0005 同一個不變量。
若真要走 Vue，只能用 pywebview 或 Tauri，**不能用 localhost server**。

**二、JSON 會污染金額。** REQ-0001 明訂禁止 float，而 JSON number 就是 IEEE 754 double。
跨 HTTP／IPC 傳金額必須全程走 minor unit 整數或字串，這是一整類新 bug，
直接威脅專案最核心的正確性保證。

**三、第二套生態系。** 現在是一個 conda env、兩個執行期依賴。加 Vue 就是 Node ＋ vite ＋ TS ＋
ESLint ＋ 元件庫。本機的全域規則第一節標題就是「Python 解譯器不一致（最常踩）」——
再引入一套工具鏈是把這個問題乘二。Tauri 還要再加 Rust；Electron 更會逼你把 SQLite 搬到 Node，
那就連 4,452 行核心一起丟掉。

**四、「檔案 2,114 行」是 organization 問題，不是框架問題。** 用換框架來解檔案太大，
是用對的手段解錯的問題。當時排定的那次拆檔（v0.7.0）不管用什麼框架都得做。

## 什麼情況下會重新考慮

Vue 真正會明顯贏的地方只有一個：**法規參考頁的長篇條文排版**。
`QTextBrowser` 做得出來但很鈍，CSS 做這個是壓倒性的。

若日後要試，路徑是 **pywebview**（純 Python 後端、無 port、無 Node 執行期依賴、
Windows 內建 WebView2）先做**那一頁**當真實試驗。感覺好就逐頁遷移，
不好就只損失一頁的工，不是整個 App。

**前提是那次拆檔已經完成** —— 乾淨的 `LedgerController` 門面正是任何前端要綁的接縫。
（**這個前提在 v0.7.0 就成立了**，v0.20.0 又把 `LedgerController` 拆成
`ui/controller/` 套件，門面沒有變。所以這條路現在隨時可以試。）

## 順帶記錄的語言評估

若今天從零開始、且以 Windows 單機發布為第一目標，**C#/.NET + WinUI 客觀上比 Python 更適合**
（自帶單一 exe、真靜態型別、沒有解譯器錯配問題）。Python 目前唯一的真實弱點是**打包** ——
還沒有 installer，只能從 conda env 啟動（roadmap Phase 8 才排）。全面改寫的代價遠超收益。

TypeScript 全棧有個實質反對理由：**JS 沒有 Decimal**，記帳的金額運算天生比 Python 脆弱。
