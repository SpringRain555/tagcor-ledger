# Changelog

## 0.21.0 - 例外收斂、保留欄位上鎖、把待辦清單清空

延續 v0.20.0 的收尾清單。**這一版的重點不是「每一條都改了程式」** —— 有幾條複查之後
發現根本不是問題，那它的正確結局是量出數字、變成有守門的事實，而不是硬寫一段程式
去證明自己有做事。

### `NotFoundError` 接不到，而那是 15 個 handler 共同的洞

`NotFoundError` 繼承的是 `RuntimeError`，**不是 `ValueError`**，所以
`except (ValueError, sqlite3.Error)` 接不到它。全面盤點 `application/` 的
**70 個 except handler** 之後發現有 **17 種形狀**，其中 15 個包著會丟 `NotFoundError`
的 store 方法卻沒有列它 —— 真的觸發時使用者看到的是全域錯誤對話框，不是中文。

**17 種形狀不是 17 個疏忽。** 裡面有刻意的兩層寫入路徑（交易與盤點要分開講「內容有
問題」與「內容沒問題但寫不進去」）、有還沒碰到 store 的輸入解析、有刻意收窄以免把
bug 藏成一句客氣中文的。所以做法是**先分類再收**：

- `failures.py` 定 `STORE_FAILURES`（單層）與 `DOMAIN_FAILURES`（兩層的第一層），
  42 個 handler 換過去。
- 兩層結構由守門用 **AST 結構**辨識，不靠名單。
- 真的該不一樣的九處進名單，每一筆都帶理由。

順帶修好一個**已經在說錯話**的地方：`DepositService.skip()` 把 `settle_event()`
的兩種 `NotFoundError` 都回成「這件項目已經處理過了」，於是「這件項目根本不存在」
也講成已處理。同一個檔案的 `update_term()` 兩個月前才因為一模一樣的原因修過。

### 淘汰用詞的守門只掃 `ui/`，於是 `application/` 漏網

「排程」在 2026-08-20 就改叫「定期收支」了，但守門只掃 `ui/`。`application/automation.py`
有 5 處、`failures.py` 有 1 處還寫著舊名，而其中三處**會走到畫面上**
（存檔失敗的 `QMessageBox`）。把掃描範圍擴到 `application/` 之後，它立刻又抓到一個
我沒發現的：`CATEGORY_PARENT_NOT_ACTIVE` 那句話裡有兩個「上層類別」。

### 兩個保留欄位：不刪，改成上鎖

`EntryType.ADJUSTMENT` 與 `Account.account_type` 從 v1 空置至今。照 REQ-0010 自己的
教訓該刪 —— 但複查發現 **REQ-0010 排在 2026-10 月底重新評估，而它的設計正好要用到
這兩樣**（「郵局可逐筆核對／現金只能盤點」就是 `account_type`，「把差額轉成調整交易」
就是 `adjustment`）。八月刪掉、十月加回來是純粹的來回。

改成 `tests/unit/test_reserved_schema.py` 鎖住「保持沒有人用」，期限寫在檔案自己的
docstring 裡：那次評估**兩種結論都會讓那份守門消失**。

### 月底夾取其實不需要「合併」

v0.20.0 把 `add_months()` 與 `next_due_date()` 的兩份月底夾取搬到 `domain/dates.py`
並排，當時的註解說「合併要動到目前正常運作的邏輯，留給下一輪」。**那個判斷是錯的。**
兩者的差別從來不在夾取，在**誰當 anchor** —— 而那是呼叫端的事。抽出
`clamped_date(year, month, anchor_day)`，`add_months()` 傳來源日期自己的日、
`next_due_date()` 傳起存日的日，實作只剩一份，語意差留在呼叫端。

`tests/unit/test_dates.py` 一個字都沒改而且全綠，那就是「沒改行為」的證據。
順帶驗過 1900–2200 全部 3,600 個月份，`days_in_month()` 與 `calendar.monthrange()`
完全一致。

### `application/deposits.py` 658 行 → 六個檔

`DepositService` 裝了合約／期／事件／入帳規劃四件事。照 `LedgerStore` 與
`LedgerController` 的做法拆成套件，**呼叫端一個字都沒改**。

這一個沒有 `OverviewSection` 那種聚合層例外 —— 拆之前用 AST 確認過二十個方法的
`self.*` 呼叫全部落在自己的 section 裡，並加了一條守門保持這樣。

最大的 src 模組從 658 降到 570（`ui/pages/catalog.py`）。

### `tests/ui` 的三行前導重複 50 次

新增 `tests/ui/conftest.py`（**這個專案的第一個 `conftest.py`**）提供 `window` fixture，
50 處換掉。剩下的九處都是真的有理由 —— 要在 `show()` 之前 `resize()`、刻意不 `show()`、
要開第二個視窗、要先拿到 `paths` —— 每一處都留了一行說明。
`test_reorder.py` 自己那個 `_window()` 工廠也一併收掉：兩種解法並存比重複更糟。

**八個頁面的實機截圖與 v0.20.0 逐位元組相同。**

### 走過那 14 行「有寫、但沒有任何測試碰過」的防禦分支

行追蹤掃出來的缺口，分兩種：

- **UI 走不到但 store 走得到** —— `CURRENCY_MISMATCH`（介面沒有建外幣帳戶的入口，
  但 `create_account(currency=...)` 有）、`CATEGORY_NOT_ACTIVE`、`_refresh_fts()`
  的 early return。
- **UI 那層擋過了但 store 那道沒人驗** —— `TRANSFER_SAME_ACCOUNT`。兩道檢查是刻意的，
  但只測上面那道的話，下面那道被刪掉不會有任何東西變紅。

加上 `SettingsService.update()` 的三個驗證分支（含 `DEFAULT_ACCOUNT_NOT_ACTIVE`
的「不存在」與「已封存」兩條路），`application/settings.py`、`stores/base.py`、
`domain/dates.py`、`domain/deposits.py` 現在**四個都是全覆蓋**。
整體行覆蓋率 85.1% → 85.9%。

### `derive_annual_rate_ppm` 沒有效能問題（量出來的）

它拿 `suggest_interest_minor()` 做二分搜尋，240 期零存整付約 4,800 次 `Decimal`
冪運算 —— 帳面上很嚇人。實測：

| 計息方式 | 12 期 | 60 期 | 240 期 |
|---|---|---|---|
| 整存整付 | 0.047 ms | 0.048 ms | 0.046 ms |
| 存本取息 | 0.033 ms | 0.034 ms | 0.031 ms |
| 零存整付 | 0.167 ms | 0.844 ms | **3.832 ms** |

**最壞 3.8 毫秒。** 迭代乘法或封閉解能砍成 1/240，但 `Decimal` 的 `**` 是照 context
精度正確捨入的，換成累乘會累積誤差 —— 為了省 3.8 毫秒去動利息的進位不划算。
改成在 `performance` marker 底下釘一個 50 ms 的上界，這件事就此關閉。

### pre-commit 加上真正的閘門

這個 repo 沒有 remote，GitHub Actions 沒地方跑，本機 hook 是唯一能自動化的。
既有的 `.githooks/pre-commit`（共用慣例，只擋 >5 MB）後面加一段本專案專屬的
ruff ＋ mypy —— 實測加起來不到 2 秒。

**pytest 刻意不進去**：整包 52 秒會讓人習慣性打 `--no-verify`，而一個被習慣性繞過的
閘門比沒有閘門更糟，它讓人以為有守。

### 其他

- 全專案唯一一個半形句號（「待確認項目已載入.」）改成全形，並加了一條守門 ——
  只認「CJK 字元 ＋ 半形句號 ＋ 結尾」，英文縮寫、版本號、副檔名都不會誤判。
- `tests/unit/test_dates.py` 有一個測試叫 `testdays_in_month`（漏了底線）。
  pytest 靠 `test*` 前綴還是收得到，所以它一直有在跑，只是名字錯了。

## 0.20.0 - 補邊界測試、依功能拆檔、收技術債

**這一版沒有新功能。** 除了一個潛在缺陷變成明確失敗以外，**行為零改變** ——
556 條測試在整個過程中一次都沒有變過數字，八個頁面的實機截圖逐一比對過。

### 順序上的一個修正：先補測試，再拆檔

原本的計畫是先拆檔再補測試。那是反的 —— 動 `stores/deposits.py` 的時候它的邊界
測試還沒寫，等於在沒有網子的情況下拆三個聚合。改成先補（對當時的程式、當時的位置
寫），拆完之後同一批測試照樣綠，**那本身就是「搬移沒有改行為」的證據**。

### 兩個修掉的缺陷

**`save_template("")` / `save_schedule("")` 會 UPSERT 出一列主鍵是空字串的資料。**
兩個 `save_*` 都是 `ON CONFLICT(<id>) DO UPDATE`，而空字串是合法主鍵 —— 寫進去不會
失敗，第二次再傳空字串就 UPDATE 到同一列上。2026-08 寫測試 helper 時三個模板就是
這樣塌成一列的，而症狀看起來像「模板沒建成功」，完全指不到原因。
新增 `AUTOMATION_ID_REQUIRED`。

**`group_digits("")` 會 `IndexError`。** `text[:1] in "+-"` 是**子字串**判斷，而空字串
是任何字串的子字串，所以空輸入會進到「有正負號」那個分支再對空字串取 `[0]`。
目前呼叫端都餵整數（`amount` 一律來自 `Money.to_decimal_string()`）所以走不到，
但它是公開函式 ——「走不到」不等於「擋住了」。

### 補了 209 條測試（346 → 555）

`domain/deposits.py` 的 `renewed_principal_minor`、`maturity_returns_principal`、
`interest_goes_to_deposit_account` 在此之前**在 `tests/` 底下一次都沒有被引用過**，
而它們是「到期那天發生什麼」的全部判準。`ui/formatting.py` 438 行純函式零單元測試，
其中 `schedule_values` / `occurrence_values` / `deposit_event_values` 三個
**從頭到尾一行都沒有被執行過**。`get_sort_spec()` 的整段壞資料防禦也是。

新檔：`test_deposit_math.py`、`test_dates.py`、`test_formatting.py`、
`test_fts_query.py`、`test_sort_spec_settings.py`、`test_search_input.py`、
`test_table_columns.py`。整包仍然是 52 秒。

### 依功能拆檔

| 之前 | 之後 |
|---|---|
| `ui/controller.py` 700 行（**貼著上限**） | `ui/controller/` 八段，最大 211 行 |
| `stores/deposits.py` 638 行 | `deposit_contracts` / `deposit_terms` / `deposit_events` |
| `stores/automation.py` 576 行 | `templates` / `schedules` / `occurrences` ＋ `drafts` |
| `ui/formatting.py` 438 行 | `primitives` / `rows` / `messages` |
| `tests/ui/test_main_window.py` 2,153 行 66 條 | 九個檔，最大 407 行 |

**全部用繼承組裝，呼叫端一個字都不用改** —— 這是 `LedgerStore` 的既有做法，
理由（「拆檔只是這個 `def` 放在哪個檔案，換成委派要手寫幾十個轉發方法」）
一字不改地適用。`ui/controller` 與 `ui/formatting` 從模組變成套件，
`import` 路徑因此完全不變。

`domain/dates.py` 收了四個日期函式，**實作一字不改**。兩份「月底夾取」的重複
（`add_months` 夾來源日期自己的日，`next_due_date` 夾 `anchor_day`）語意不同，
合併會動到正常運作的邏輯，所以這一版只搬不合，重複在 docstring 裡標記為已知。

### 六條新守門

controller 組裝檔不放方法、controller 的方法都住在套件裡、`stores/__init__.py` 的
`__all__` 與 `LedgerStore` 的基底一致、頁面不得自己拼列內容、表格欄位數與 formatter
對得起來、**`tests/` 也納入行數上限**（1200）。

`stores/__init__.py` 那一條是補一個**已經發生過**的漏更新 —— 它自己的 docstring
記著 `AutomationStore` 收進來時忘了加進清單，而「沒有人使用的 re-export 清單不會有
任何測試提醒你它過期了」。現在有了。

### 覆蓋率量測用 stdlib，不進依賴

`trace` 掃一次找缺口，掃完就丟。**它的 `ignoredirs` 有一個會產出「看起來完全正常
但是錯的」報告的坑**，細節見失敗紀錄 —— 那一次差點讓我照著假資料去補測試。

## 0.19.0 - 多層排序，而且記得住（自訂排序 Stage 2）

排序視窗左半多了「排序方式」：**最多三層，每層一個欄位與升冪／降冪**。
第一層平手時才輪到第二層。「自訂順序」是其中一個可選欄位。

### 「自訂」在項目那頁是兩個欄位，這是整個設計的關鍵

`sort_order` 的意義**只在同一組之內**。項目跨類別比自己的 `sort_order` 會互相穿插
（每組都是 10、20、30），所以拆成：

| 欄位 | SQL |
|---|---|
| 所屬類別（自訂順序） | `category_parent.sort_order` |
| 項目（自訂順序） | `category_node.sort_order` |

預設的 `[parent_custom, custom]` **就是 v0.18 之前寫死的那個排序** —— 這一版只是
把它變成可以改的。

### 記得住

規格存在 `settings` 這張 key/value 表（**不用 migration**），一頁一個 key，值是 JSON。
讀不懂就靜靜退回預設 ——「畫面怎麼排」的偏好不值得讓程式開不起來，而真正的守衛在
SQL 那一層。

**每一頁要有自己的預設規格，不能用「空規格」代表預設。** 空的填進排序視窗會退成
「下拉裡的第一個」，項目那頁就掉成只剩 `parent_custom` 一層、同類別底下的項目回到
名稱序。**這是實作時真的踩到的**，測試當場紅。

### 點表頭排序拿掉了

兩種入口並存時，點表頭會把使用者設好的多層規格整個換成單層，而畫面上沒有任何東西
說明剛才設的為什麼不見了。

`setSectionsClickable(False)` 寫在 `setup_table()` 裡，**整包表格一起** —— Qt 的預設
是可點，而可點的表頭看起來就像可以排序。（拿掉這件事排在 Stage 2，不是 Stage 1：
提早拿掉會有一段連「依名稱排一下」都做不到。）

### `ORDER BY` 現在由一個函式組，規則寫死在那裡

`stores/base.py::order_by()` 是**整個專案唯一把字串拼進 `ORDER BY` 的地方**：

- 每一層的欄位只是 key，查各 store 的白名單換成固定運算式，**查不到整層跳過**
- 同一個欄位出現第二次跳過（第一層排過的不可能再分勝負）
- 一層都不剩就退回該清單的預設
- **tiebreaker（名稱、id）一律接在最後** —— 少了它，完全同分的兩筆每次重整都可能換位置

白名單的值裡**不得出現引號、分號、`%`、`{`**，有測試掃。為了守住這條，
`parent_name` 從 `COALESCE(category_parent.name, '')` 簡化成 `category_parent.name`
—— 排序時 NULL 在 ASC 本來就排最前，跟空字串一樣，那個 `COALESCE` 從來沒有作用。

### 三條沒有鑑別力的測試（陽性對照抓到的）

先寫的是三條整合測試（重複欄位、全部認不出來、tiebreaker），**陽性對照全部 BAD**
—— 拿掉那三段程式，測試照樣綠。原因是那幾筆資料剛好讓「有做」與「沒做」產生同一
個順序：

- `name ASC, name DESC` 的結果本來就等於 `name ASC`
- 全部平手時，「退回預設」與「只剩 tiebreaker」都落在名稱序
- SQLite 對同一個查詢同一份資料本來就給同一個順序，看不出少了 tiebreaker

**這些是字串層級的規則，就要在字串層級檢查。** 新增 `tests/unit/test_order_by.py`
直接量 `order_by()` 回傳的字串；三條整合測試也改成先排一個「跟名稱序不同的自訂順序」
再驗，這樣才分得出來。修正後 13 項對照全過。

> 這是 0.16.0 那條「測試通過不等於它檢查得到東西」的第二次應驗。差別是這次
> **在寫完就跑了對照**，所以是當場發現，不是三版之後。

### 守門

`tests/unit/test_order_by.py` 9 條、`tests/integration/test_category_order.py` 20 條、
`tests/ui/test_reorder.py` 21 條。全套 337 passed。

## 0.18.0 - 排序搬進獨立視窗，四頁都能拖曳排（自訂排序 Stage 1）

v0.17.0 把「上移／下移」放在主表格上，代價是**依欄位排序時必須停用它們**。
使用者實機遇到了：點一次表頭，按鈕就灰掉，而原因看不出來。

### 根因不是按鈕停用，是排序與調順序擠在同一張表上

只要調順序這件事還發生在主表格裡，「你正在看 A 順序、卻要改 B 順序」就無解 ——
停用按鈕只是把那個矛盾擋住，沒有解決它。

搬進獨立視窗之後矛盾消失：**那個視窗永遠顯示自訂順序**，主表格愛怎麼排就怎麼排。

拖曳也因此變得安全：視窗裡是 `QListWidget` ＋ `InternalMove`（**可寫入的 model**），
不必去動主表格「唯讀 model ＋ 在 SQL 裡排序」那條硬規則。v0.17.0 不建議拖曳的理由
在這裡就消失了。

### 四頁都有：帳戶、類別、項目、模板

`accounts.sort_order` 與 `transaction_templates.sort_order` 跟 `categories` 一樣，
**欄位早就在、`ORDER BY` 早就在用、從來沒有人寫過它**。所以這一版仍然不用 migration。

- **項目的視窗是兩欄**：左邊排類別、右邊排所選類別底下的項目。`sort_order` 的意義
  只在同一組之內 —— 項目跨類別比它會互相穿插，一份平的清單表達不了。
- **按「確定」才寫入**，取消真的什麼都不做。
- **封存的也列出來並標「已封存」** —— 藏起來的話它的順序值會停在舊的，恢復時就跑到
  莫名其妙的位置。
- **同時有拖曳與上移／下移**：只有拖曳的話，鍵盤操作沒有路可走。
- 記帳頁的下拉、資產總覽的帳戶列表都跟著同一份順序。

### store 層換成「收整組」而不是「往上一格」

v0.17.0 的 `reorder_category(id, anchor_id=…, place=…)` 拿掉，改成
`set_category_order(ids, parent_id=…, level=…)` ／ `set_account_order(ids)` ／
`set_template_order(ids)`，共用 `StoreBase._apply_sort_order()`。

排序視窗本來就握有完整順序，送整份進來比在資料庫裡算相對位置簡單，而且**順便擋掉
清單過期**：送進來的 id 必須跟現況是完全一樣的一組，不多、不少、不重複
（`REORDER_LIST_STALE`）。那個檢查連「同一個 id 送兩次、長度剛好對得上」都擋得住。

模板的順序**不走 `save_template()`** —— 那條路會跑草稿驗證，於是「有一個模板的帳戶
被封存了」就會讓整份順序存不進去，而使用者根本不是在編輯那個模板。

### 點表頭排序這一版先留著

終局是拿掉（排序統一走視窗，Stage 2 會做多層排序）。但 Stage 2 之前拿掉的話，
中間會有一段連「依名稱排一下」都做不到 —— 不製造中途的倒退。

### 截圖抓到的一個缺陷

清單沒設高度下限，**五個項目就被切掉第五列**。一個要靠拖曳的清單，看不到全部就
沒辦法決定拖到哪裡。高度改成照字型現算、至少放得下 10 列，並補一條量捲軸範圍的
守門（不是量「有沒有設定 minimumHeight」）。

**純看程式碼看不出來這件事**，`AGENTS.md` 那條「改樣式之後要真的看一眼」又應驗一次。

### 順帶查證的兩件事

- **新增帳戶的期初餘額可以是 0**，而且那就是對話框的預設值。空白、負數、小數會被擋。
- 改類別／項目／帳戶名稱之後，**既有交易會跟著更新**。名稱不存在 `transactions` 表裡，
  是讀取時 JOIN 出來的；唯一抄了一份的全文檢索索引由 `rename_category()` 主動重建，
  連同該類別底下所有項目的交易。

### 守門

`tests/integration/test_category_order.py` 13 條、`tests/ui/test_reorder.py` 12 條。
六項陽性對照都驗過：整組一致性檢查、切換類別時記住已拖的順序、上移後保住選取、
封存標註、取消不寫入、清單高度下限。

## 0.17.0 - 類別與項目可以排成自己想要的順序

「類別」與「項目」兩個分頁多了「上移／下移」。常用的排前面、少用的沉底。

### 不用改 schema —— 欄位早就在，只是沒有人寫過它

`categories.sort_order` 從 **schema v1** 就存在，有索引（`idx_categories_parent`），
而且預設排序一直在用它：

```sql
ORDER BY sort_order, name COLLATE NOCASE
```

但 `create_category()` 把它寫死成 `100`，**沒有任何一段程式改過它**。所以每一列都
平手，實際看到的順序全靠後面那個名稱 tiebreaker 撐著 —— 一個看起來有在運作、
實際上從來沒有生效過的欄位。這一版只是補上「誰去改它」。

（`accounts.sort_order` 也是一樣的狀態，這一版**沒有動它** —— 使用者要的是類別。）

### 三個設計決定

**移動送的是「畫面上那個鄰居的 id」，不是「往上一格」。** 這兩頁可以搜尋與篩選，
畫面上那一列的鄰居不一定是儲存順序裡的鄰居。送 id 進來，結果才會跟眼睛看到的一致。

**只在同一組之內移動。** 類別跟類別、同一個類別底下的項目跟項目。跨類別是
「換類別」不是「調順序」，store 直接擋（`CATEGORY_REORDER_DIFFERENT_PARENT`）。
項目分頁在組的邊界上「上移」會停用 —— 上面那一列屬於別人。

**點表頭排序時上移／下移停用，而且回得去。** 依「項目數」排序時，「上移」要移到哪裡
沒有答案。表頭改成三段循環（升冪 → 降冪 → **收回箭頭**，`setSortIndicatorClearable`）
—— 沒有第三段的話，使用者點過一次表頭就再也調不了順序，而自訂順序才是這兩頁的預設。

### 記帳頁的下拉也跟著

`list_categories()`（下拉的來源）本來就 `ORDER BY sort_order`，所以自訂順序自動生效。
**這是重點不是副作用** —— 名冊排好了但下拉沒跟著，等於沒排。有一條測試守著兩邊一致。

### 順序整組重新編號

移動時把整組兄弟重編成 10、20、30⋯⋯，不是在既有數字之間找空隙。這一層最多幾十列，
而且**目前非重編不可** —— 全部都是 100，沒有空隙可以找。

### 六顆按鈕擠一列，實際量過

`AGENTS.md` 記過「六顆按鈕擠同一行會把視窗最小寬度撐到 855 px」，所以量了：

| | 分頁最小寬 | 按鈕列 | **主視窗最小寬** |
|---|---:|---:|---:|
| 有上移／下移（6 顆） | 644 px | 626 px | **904 px** |
| 對照組（4 顆） | 508 px | 490 px | **904 px** |

分頁自己胖了 136 px，但**主視窗完全沒變** —— 904 px 是別的分頁決定的，這一頁還沒有
碰到天花板。表格沒有橫向捲軸，實機截圖確認六顆排得下。所以維持一列，不拆行。

### 守門

`tests/integration/test_category_order.py` 10 條、`tests/ui/test_main_window.py`
新增 6 條。四項陽性對照都驗過（拿掉判斷 → 紅 → 復原 → 綠）：依欄位排序時停用、
只在同一組裡找鄰居、store 擋跨組、移動之後保住選取。

> 最後那一條是實作時真的踩到的：`_finish()` 會發 `changed`，而
> `main_window._catalog_changed()` 接到之後又把這一頁重整一次 —— 先選再發訊號的話，
> 選取會被那一次重整洗掉，按一次「上移」就得重新點一次才能按第二次。

## 0.16.4 - 關掉程式不再跳「發生未預期的錯誤」

使用者實機回報：操作全程正常，**關掉視窗之後**跳出紅色驚嘆號：

```
RuntimeError: libshiboken: Internal C++ object
(PySide6.QtWidgets.QListWidget) already deleted.
  File "ui/widgets/table.py", line 237, in sync
```

### 這是 v0.16.1 進去的，日誌講得很清楚

`app.log` 裡 0.8.0 到 0.14.3 共 **10 次關閉全部乾淨**，只有 0.16.3 這一次噴。
中間動到這段程式的只有一處：**v0.16.1 把 `bind_selection` 從 `QTableView` 放寬到
`QAbstractItemView`**，好讓維護頁的備份清單（`QListWidget`）也能綁選取狀態。

### 為什麼只有 `QListWidget` 會炸

`bind_selection` 把 `sync` 接到 model 的 `modelReset`。兩種 view 的差別在**誰擁有
那個 model**：

| view | model | 銷毀順序 |
|---|---|---|
| `QTableView` | `RowsModel`，**頁面自己持有的 Python 物件** | Python 說了算，view 先走 |
| `QListWidget` | **C++ 那邊的內部子物件** | `~QListWidget` 期間它還會再發一次 `modelReset` |

所以 `QListWidget` 那條路上，`sync` 會在 view 的 Python 包裝已經失效之後被呼叫，
`table.selectionModel()` 當場丟 `RuntimeError`。

修法是在 `sync` 開頭問一句 `shiboken6.isValid(table)`。**這不是把錯誤吞掉** ——
「一個已經不存在的 widget 選了幾列」在那個時間點本來就不是一個成立的問題。

### 守門：`tests/ui/test_shutdown.py`

開**子行程**跑一次完整的「開啟 → 關閉 → 直譯器結束」，斷言 stderr 沒有
`already deleted` 也沒有 `Traceback`。0.76 秒。

必須開子行程，因為這件事發生在**直譯器關閉階段**。同一個 process 裡用
`deleteLater()` ＋ `processEvents()` 抓不到 —— 前三次探針就是這樣落空的。

那條測試裡有兩道防自欺的斷言：先確認驅動程式印出 `DRIVER_OK`（否則「沒有錯誤」
可能只是它根本沒開起來），以及驅動程式裡先斷言備份清單**至少有一列**
（清單是空的就走不到會出事的那條路，bug 還在測試也會綠）。

## 0.16.3 - 清掉 Phase 1 留下來的化石註解與兩段死碼

行為零改變。這一版處理的是**註解與文件說了一件跟程式不一樣的事**。

### 三處註解在說謊

| 位置 | 說的 | 實際 |
|---|---|---|
| `infrastructure/stores/__init__.py` | 「`LedgerStore` 把這裡的**四個** store 組起來」 | 六個。`AutomationStore` 2026-08 收進 `stores/` 時沒補進 re-export，docstring 也停在四 |
| `ui/__init__.py` | 「**PyQt** UI package placeholder for Phase 2」 | PySide6。而 `AGENTS.md` 的「不做的事」**明文禁止**重新加入 PyQt6 |
| `ui/formatting.py` | 「這裡是**唯一**決定畫面上中文長什麼樣子的地方」 | 頁面裡還有 22 處中文 `setText()`。真正的分界是「這句話會不會在別的地方也要用同一個講法」 |

第一條特別值得記：**一份沒有人 import 的 re-export 清單不會有任何測試提醒你它過期。**
`from tagcor_ledger.infrastructure.stores import ...` 在整個專案裡是零次。

### 兩段死碼，而且各自掛著一個編出來的存在理由

- `application/transaction_service.py::ListRecentTransactions` ——
  docstring 寫「Compatibility query retained for existing integrations」。
  這是一個**不連網的本機程式**，沒有任何 integration；`src` 與 `tests` 裡零次呼叫，
  唯一的出處在 `docs/archive/phase-0-2/`。
- `ui/widgets/forms.py::iso_datetime()` —— 它服務的是 `QDateTimeEdit`，
  而 `AGENTS.md` 寫著「日期欄位一律用 `date_field()`，**不要用 `QDateTimeEdit`**」。
  留著一個專門服務被禁用元件的 helper，等於讓那個元件看起來還受支援。

兩段都刪掉。**「留著也不礙事」是錯的** —— 礙事的不是那幾行，是它們附帶的那句
「這個東西還有人在用」。

### 註解與文件全部改回繁體中文

專案自己的規則是「介面文字、錯誤訊息、註解、文件全部繁體中文」，但每個模組的
**第一行 docstring** 都還是 Phase 1／2 留下來的英文 —— 之後補的註解都是中文，
於是每個檔案長成「英文開頭 ＋ 中文內文」。

那一層英文正是漂移最嚴重的地方，上面三條有兩條就出在裡面。原因不難理解：
**沒有人會回頭讀那一行。** 30 處全部改寫，其中幾處順便把散在 `AGENTS.md` 的硬規則
搬到它真正該在的地方：

- `app/path_settings.py::write()` —— 寫指標檔的順序（先搬完再寫指標，反了就等於資料消失）
- `infrastructure/migrations.py` —— 不可以改舊的 migration
- `ui/theme.py::apply_dark_theme()` —— 要在任何 widget 建出來之前呼叫
- `infrastructure/stores/base.py::StoreError` —— 訊息就是錯誤碼，不是中文句子

### 主題一個 process 只套一次（UI 測試從 32 分鐘掉下來）

量 `--durations=25` 的時候發現前 25 名**全部**是 `tests/ui/test_main_window.py`，
36～65 秒一條，佔掉整包 1,931 秒裡的 1,243 秒。

關鍵不在那些數字，在**排名**：最慢的那條在檔案第 2101 行，接著是 2071、2030、1991、
1946⋯⋯**慢的排名就是它在檔案裡的位置排名。**成本是累積的，不是單次的。
單獨跑最慢那一條只要 **0.73 秒**（在完整套件裡 65.6 秒，90 倍）。

隔離量測（探針不進版控）：

| process 裡活著的 MainWindow | 再建一個要多久 | 把 `apply_dark_theme` 換成 no-op |
|---:|---:|---:|
| 0 | 261 ms | 115 ms |
| 5 | 1,614 ms | 97 ms |
| 15 | 12,814 ms | 100 ms |
| 25 | **49,705 ms** | 104 ms |

**百分之百出在 `apply_dark_theme()`。** `setFont` / `setPalette` / `setStyleSheet` 是
**application 層級**的操作，Qt 得把改變傳播給當下活著的每一個 widget 並重跑 style
polish —— 所以第 N 次呼叫要走過前面 N−1 個視窗的所有子元件。

修法是在 `QApplication` 上留一個標記，**同一個 process 只套一次**（`force=True`
留給真的要重套的情況，目前沒有呼叫端）。第二次套用在語意上本來就是 no-op ——
同一份字體、同一份 palette、同一份 QSS。修完同一條曲線是平的（298 ms → 323 ms）。

`AGENTS.md` 那條「要在任何 widget 建出來之前套用」**沒有被削弱，反而更強** ——
第一個視窗照樣先套，後面的視窗一出生就已經在主題底下，不必再被重新 polish 一次。

> **這不是使用者在付的成本。** 正式執行只開一個視窗，`apply_dark_theme` 在零個其他
> widget 的情況下跑，約 150 ms，開程式時付一次。它只在測試裡爆炸 —— 而那的代價是
> **沒有人願意跑完整套件**，於是守門形同虛設。

守門：`test_the_theme_is_only_applied_once_per_process`。它量的是「有沒有再套一次」
不是「花了多久」—— 時間會因機器而異，語意不會。陽性對照驗過（拿掉早退就紅）。

### 文件：roadmap 不再是第二份 changelog

`docs/roadmap.md` 每發一版就長出一節「這一版最值得記住的一件事」，而且長在
**「後續候選 Phase」底下** —— 已完成的東西排在待辦清單中間。四節裡有三節的內容
與 `docs/lessons.md` 重疊。

四節收成「已完成」底下的一張四列表格，`AGENTS.md` 的「文件維護」補上三份文件
各自寫什麼、**不要**寫什麼。第四節（0.16.2 那條守門誤判）本來就該在 `lessons.md`
卻不在，補上了。

## 0.16.2 - 備份清單看得懂了，而且「返」不再被當成簡體字

兩件小事，都是 0.16.1 收尾時記下來的已知問題。

### 備份清單不再需要橫向捲

一列以前長這樣：

```
2026/08/22 01:04｜可用｜C:\Users\…\AppData\Local\…\ledger\backups\backup_20260822_010407_717419
```

上百字元的絕對路徑撐出一條橫向捲軸，而每一列前面那一大段還**完全相同** ——
想分辨哪一份是哪一份，得先橫向捲到最後。現在只到資料夾名：

```
2026/08/22 01:04｜可用｜backup_20260822_010407_717419
```

完整路徑放**兩個地方**：滑過去的 tooltip，以及刪除的確認框。後者是刻意的 ——
清單那一列只到資料夾名，而確認框是最後一次能發現「我選到別顆磁碟上那一份」的機會。

資料夾名看起來跟時間欄重複，但它多了秒與微秒；同一分鐘內建立的兩份備份在時間欄上
長得一模一樣，靠它才分得開。

### `SIMPLIFIED_ONLY` 裡的「返」是誤判

**返是正體標準用字**（返家、返回、往返），不該在那張表裡。它的代價是實際發生過的：
0.16.1 寫失敗紀錄時被擋下來，只好把「函式返回」改寫掉。

移除之後守門仍然抓得到真的簡體字（把「備」換成它的簡體寫法塞進原始碼，測試會紅，
驗過）。表上方加了一段說明「這裡只能放簡體才有的字」，並記下這一次的移除。
**那張表沒有逐字稽核過**，再發現誤判就照樣移除並補記。

> 寫這一段時被自己的守門擋了一次：本來直接把那個簡體字打在 changelog 當範例，
> 而掃描器分不出「範例」與「錯誤」。**這是對的行為** —— 能開例外的掃描器等於沒有
> 掃描器。要舉例就描述它，不要把它寫出來。

> 順帶一提，0.16.1 那句改寫**留著不改回去** —— 那段講的是「函式的 frame 結束、
> 區域變數被回收」這個假設，跟 `return` 這個動作無關，「結束」本來就比「返回」準確。

## 0.16.1 - 備份可以刪掉了（以及讓它一度不可能的那個連線洩漏）

### 順序是刻意的：先修連線，才做得出刪除

`sqlite3.Connection.__exit__` 只做 commit／rollback，**不 close**。
「函式結束時 refcount 會收掉」這個假設在 Windows 上實測不成立：

```python
def leaky(path):
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA integrity_check").fetchone()

leaky(copy); shutil.rmtree(folder)   # PermissionError 32，檔案被佔用
```

`validate_backup()` 要開資料庫讀 schema 版本，`list_backups()` 對每一份都跑它，
而維護頁每次 refresh 都呼叫 `list_backups()`。所以**開著程式看一眼備份清單，
那些備份就全都刪不掉了** —— 不先修這個，刪除功能寫出來也是壞的。
`maintenance.py` 四個 `sqlite3.connect()` 全部包上 `contextlib.closing`。

拿掉 `closing` 之後 `tests/integration/test_backup_deletion.py` 十條裡有八條紅。

### 刪除所選備份

維護頁多一顆 `dangerButton`。三個設計決定：

- **不檢查備份有沒有效。** 檢查了就變成「壞掉的備份刪不掉」，而使用者想刪的
  八成就是壞的那一份 —— 那也是這顆按鈕存在的理由。
- **只肯刪備份資料夾底下的東西。** 這個方法收路徑而且做遞迴刪除，沒有這道檢查，
  一個算錯的路徑就能刪掉別的東西。「選擇外部備份資料夾」餵進來的會被擋下。
- **最後一份可用的備份：講，但不擋。** 確認框念出這一份是什麼、刪完還剩幾份可用；
  剩零份時明講「這之後就沒有任何可用的備份了」。硬擋會讓「清掉整個備份資料夾重來」
  變成做不到。

驗證／還原／刪除三顆改用 `bind_selection` 綁選取狀態 —— 以前是 handler 裡
`if path is None: return`，按了什麼都不會發生。`bind_selection` 因此從
`QTableView` 放寬成 `QAbstractItemView`（備份清單是 `QListWidget`）。

### 又三處印英文碼給使用者看

0.16.0 修了維護頁的**例外**路徑，漏了**非例外**路徑：

| 位置 | 以前 | 現在 |
|---|---|---|
| 備份清單那一欄 | `無效：BACKUP_CHECKSUM_MISMATCH` | `不可用（內容被改過）` |
| 壞掉那幾列的時間欄 | 空白（開頭直接是 `｜`） | `2026/08/21 20:44` |
| 按「驗證所選備份」 | `備份不可用：BACKUP_CHECKSUM_MISMATCH` | 完整說法：壞在哪、接下來怎麼辦 |
| 還原前的檢查對話框 | `BACKUP_CHECKSUM_MISMATCH` | 同上 |

清單用**短標籤**、驗證用**完整說法**，兩張表分開 —— 一整句塞進清單那一列會讓
每一列長到看不出哪一份是哪一份。這不是同一件事寫兩遍，是兩個不同的工作；
`test_failure_messages.py` 檢查每個 `BACKUP_*` 兩邊都有，而且標籤不超過 8 個字。

最後那一列是實機截圖才看到的：`validate_backup()` 一發現問題就回傳，`created_at`
來自清單檔所以是空的，於是壞掉那幾列開頭是一個空欄位 —— **而使用者正是在
「這幾份都壞了，該刪哪一份」的時候需要那個時間**。讀不到清單檔就退回資料夾名字
裡的時間戳（`backup_20260821_204447_788741`）。

### 新增的守門

`tests/integration/test_backup_deletion.py`（10 條）與四條 UI 測試，
其中三條走**真正的按鈕路徑**（選一列 → 按刪除 → 確認 → 清單少一列）。

十三個修正各自做過陽性對照，其中兩次對照直接改變了結果：

- 我在 `bind_selection` 裡註明「`QListWidget.clear()` 走 reset 不是
  selectionChanged」，但拿掉 `modelReset` 那一行測試照樣綠 —— **那句註解是錯的**，
  已經刪掉。
- 時間欄的退路第一版**沒有守門**：把它改回 `created_at` 測試還是綠的。
  補上「開頭不是 `｜`、而且長得像 `2026/08/21 20:44`」的斷言。

## 0.16.0 - 錯誤訊息說中文，而且說的是真正發生的那件事

0.15.0 修掉了 `CategoryService.create` 一處「一個錯誤碼代表三件事」，並記下同樣的寫法
還有 50 處。**這一版把它們全部處理完**（實際是 51 處），外加六個 UI 直接印
`str(exc)` 的出處（待確認頁兩處、模板對話框、維護頁三處、重製頁）。

### 使用者看得到的差別

| 操作 | 以前畫面上的字 | 現在 |
|---|---|---|
| 刪掉預設帳戶 | 帳戶無法刪除；預設帳戶或已有歷史資料的帳戶請改用封存。（`ACCOUNT_IS_DEFAULT`） | 這是預設帳戶，不能刪除。請先到「操作設定」把預設帳戶改成別的，再回來刪。 |
| 刪掉有交易的帳戶 | （同上那一句，一字不差） | 這個帳戶已經有交易紀錄，不能刪除。請改用「封存」—— 歷史交易會留著，帳戶則不再出現在選單裡。 |
| 金額填 `0` | 請檢查交易內容。（`Amount must be greater than zero.`） | 金額要大於 0。 |
| 金額填 `1,200` | 請檢查交易內容。（`Amount must be a plain Decimal string without commas or exponent.`） | 金額只能填數字，不要加逗號、單位或空白。 |
| 搬移資料夾但目標已有帳本 | 資料路徑設定無法儲存，請確認兩個路徑分開、都在資料根目錄底下且可寫入。（`TARGET_LEDGER_ALREADY_EXISTS`） | 目標資料夾裡已經有一個帳本檔了。請換一個空資料夾，或先處理掉那一份。 |
| 還原一份被改過的備份 | `BACKUP_CHECKSUM_MISMATCH` | 這個備份的檔案內容與清單裡記的雜湊對不起來 —— 檔案在備份之後被改過或損毀了。請不要還原它，改用別的備份。 |

前兩列是重點：**那是兩件不同的事、兩種不同的處理方式，以前共用一句話**，
差別只寫在括號裡的英文碼。

### 根因不是那串英文難看

是**畫面上唯一講清楚失敗原因的東西只有那串英文**。中文句子太籠統，只好把底層的碼
原封不動印出來讓人自己判斷 —— `details["reason"]` 那個括號是在補償「一個錯誤碼代表
好幾件事」。所以順序不能顛倒：**先拆碼，才能拿掉括號**。只拿掉括號會讓訊息更糟。

### 怎麼做的

新增 [`application/failures.py`](../src/tagcor_ledger/application/failures.py)：

- `ERROR_MESSAGES` —— 錯誤碼 → 中文說法，**一個碼的句子只寫在這一個地方**。
- `failure(exc, fallback_code=…, fallback_message=…)` —— 寫入層丟的碼認得出來就用
  **那個碼**與它的句子；認不出來（`sqlite3.Error` 的原文、還沒收錄的碼）才退回
  `*_FAILED`，原文放 `details["detail"]`（**不顯示**）。
- 情境需要不同說法時用 `overrides=`。例如恢復撞名的帳戶時，該改名的是**另外那一個**。

連帶的：

- `domain/money.py` 的 `MoneyError` 改帶錯誤碼而不是英文散文（`AMOUNT_NOT_POSITIVE`、
  `AMOUNT_FORMAT_INVALID`、`CURRENCY_UNSUPPORTED`、`CURRENCY_FRACTION_UNSUPPORTED`、
  `AMOUNT_NOT_A_STRING`）。
- `result_message()` 不再接 `details["reason"]`，`details["reason"]` 整個廢除。
- UI 自己 `except` 的六處（待確認頁兩處、模板對話框、維護頁三處、重製頁）改走
  `ui/formatting.error_text()`，不再直接印 `str(exc)`。**維護頁那三處最嚴重** ——
  還原一份壞掉的備份時，畫面上就是一句 `BACKUP_CHECKSUM_MISMATCH`。
- `maintenance.py` 的 `raise RuntimeError(f"BACKUP_INTEGRITY_FAILED:{integrity}")`
  拿掉後綴。有後綴就查不到表，於是又會走回「印原文」那條路。
- 刪掉 `transaction_service.py` 與 `balance.py` 各自一份的 `_error_code()`
  —— 同一個函式抄了兩遍，而且它只看 `text.isupper()`，不查表。
- `application/deposits.py` 少掉兩個手寫的特例分支
  （`if str(exc) == "DEPOSIT_CONTRACT_IN_USE"`、`except NotFoundError:` 一律當成
  「不可編輯」）—— 有了對照表，那種「把唯一值得講清楚的失敗特別挑出來」的分支就多餘了。

### 順手發現並修掉的

**`AMOUNT_NEGATIVE` 永遠不會發生。** `DECIMAL_RE` 不收正負號，所以 `-5` 在格式那一關
就退掉了，底下那個 `if allow_zero and amount < 0` 分支跑不到。刪掉分支與錯誤碼，
`allow_zero` 現在名副其實只管 0。

**改一期定存時，「這一期不存在」被講成「這一期不能改」。** store 的 UPDATE 帶
`WHERE term_id = ? AND status = 'active'`，改到 0 列就一律丟
`DEPOSIT_TERM_NOT_EDITABLE` —— 但 0 列有兩種原因，而它們該給的建議完全不同
（「重新整理」對上「這一期已經產生過交易」）。現在 0 列時多問一句這一期在不在。
**這是同一個病的第三個變種**：一個碼代表兩件事，只是這次發生在寫入層而不是應用層。

**七個錯誤碼從來沒被記錄過。** `DESTINATION_ACCOUNT_NOT_ACTIVE` 與六個 `BACKUP_*`
都是 `return` 出來再轉成例外的，`test_error_codes.py` 只掃 `raise` 的常數參數，
所以整組漏掉 —— 而它們照樣會印到畫面上。掃描器現在也讀 `ERROR_MESSAGES` 的 key，
文件補上一整節「備份」。

### 新增的守門

`tests/unit/test_failure_messages.py`：

- 底層 `raise` 的每一個碼都要有中文說法（啟動階段那兩個有豁免，而豁免本身也要
  驗證 `app/startup.py` 真的處理了它們）。
- 對照表裡不能有沒人丟的碼。
- 每一句都要有中文，不能是英文，也不能只是把碼抄一遍。
- **任何地方寫 `details={"reason": …}` 就紅。** 這條最重要 —— 那是加一行就會回來的
  錯誤，51 個出處全都是「照著上面抄」的結果。

十一個修正各自做過陽性對照（把修正還原，確認對應測試會紅；還原前後各跑一次，
確認不是碰巧）。其中一條第一版**沒有鑑別力** —— 關掉抽取器的一半路徑它照樣綠，
是陽性對照本身跑出來才發現的，後來改成兩條路徑各驗一個只有它抽得到的句子。

## 0.15.0 - 三個「畫面停在舊數字」的缺口、日期欄不再誤改年份、名冊可搜尋排序、轉帳分三種對象

這一版分兩批：**先修 bug，再改版**。

### 修掉的（依嚴重度）

**跨頁連動掉了線，三處畫面顯示過期數字。** 三者是同一個病：動作改了帳務，但沒有人被通知。

| 症狀 | 根因 |
|---|---|
| 從交易紀錄作廢一筆帳，餘額盤點的未解釋差額還是舊的 | `TransactionsPage` **從頭到尾沒有對外發過訊號** |
| 在待確認按「確認入帳」，交易紀錄裡找不到那一筆 | `inbox.changed` 只接到側邊欄徽章 |
| 「複製到記帳」把項目換成該類別的第一個 | `apply_draft` 把**父類別 id** 餵給要**項目 id** 的 `_select_category()` |

`MainWindow` 多了一個 `_ledger_changed()`，記帳、交易紀錄、待確認三個來源接同一個方法
（不是三個「差不多」的方法 —— 那份清單就是下一個會漏的地方），並刪掉從 v0.14.0 起
就沒被接上的死碼 `_automation_changed()`。

**日期欄點一下就改年份。** 根因不是 QSS 把箭頭畫歪，是 `QStyle::SubControl` 有兩組
列舉值**數字相同**（`SC_ComboBoxFrame == SC_SpinBoxUp == 0x1`）。`QDateTimeEdit` 在
`calendarPopup` 模式下用 CC_ComboBox 命中測試，非箭頭的結果轉給 `QAbstractSpinBox`，
而它拿同一個數字去比 spinbox 的上下鍵 —— 點內距 +1，**點文字 −1**。
QSS 的 `padding: 7px 10px` 把那一圈從 1 px 撐成 7～10 px，正好在伸手去點箭頭的路徑上。
修法是 `setButtonSymbols(NoButtons)`，日曆箭頭不受影響。

**日曆彈窗的日期全部顯示成「...」。** 這個症狀 2026-08-18 修過一次但沒修對：當時清的是
view 的 padding，真正吃掉日期的是 `QTableView::item { padding: 7px 8px }` —— 日曆的日期格
就是一個 `QTableView`。量出來格子 33x21 但文字矩形只剩 **17x7**，是**高度**不夠。
順便補上六列日期的最小高度（最後一排本來被切掉 7 px）與星期標題的中性配色。

**七個日期欄繞過 `date_field()`**（交易紀錄 2、定存 3、模板／定期收支 2），所以上面兩個
修正本來只會修到記帳頁那一個。全部收回工廠，並加一條 AST 守門擋住下一次。

其餘：轉帳兩個下拉預設同一個帳戶（新開程式選轉帳按儲存**必定**撞 `TRANSFER_SAME_ACCOUNT`）、
修改定存合約每次都把備註寫成空字串、修改合約時起存日顯示成「今天」（那是「期」的欄位，
合約沒有值可回填，改成整列收起來並指路到「修改所選期」）、
「資料路徑」看不到資料根目錄（而 `PATH_OUTSIDE_DATA_ROOT` 講的正是那個值）。

### 改版

- **類別／項目的檢視面板**：名稱搜尋、狀態（使用中／已封存／全部）、所屬類別篩選，
  點欄位標題排序。**全部下推到 SQL**（`CategoryTreeFilter`），連 `level` 都不再用
  Python 濾。排序**不用** `setSortingEnabled(True)` —— 那會讓 `QTableView` 自己在
  Python 裡排；表頭只負責可點與箭頭，真正的排序是把 `sort_key` 送回 SQL。
  `sort_key` 只能是白名單裡的值，那是唯一一處把字串拼進 `ORDER BY` 的地方。
  項目的搜尋**也吃類別名**：打「交通」列出交通底下的每一項。
- **新增與重新命名改成一張表單**：以前是兩個連續的 `QInputDialog`，取消第二個會把
  第一個輸入的東西靜靜丟掉。新的 `SimpleFormDialog` 在必填欄空白時停用「確定」。
  「上層類別」改成**「所屬類別」**（列表表頭一直都是這個字），「名稱」改成
  「帳戶名稱」／「類別名稱」／「項目名稱」。
- **轉帳分三種對象**：我的帳戶之間／別人轉入／轉出給別人。**不新增 `entry_type`** ——
  對外的兩種存成收入與支出，因為錢真的離開或進入了總資產。理由與被否決的兩個替代方案
  （新增列舉值、建「外部」虛擬帳戶）寫在 [ADR-0010](decisions/ADR-0010-external-transfers.md)。
- **文件加上 10 張 mermaid 圖**：分層與交易寫入路徑、四張狀態機、頁面地圖、記帳決策、
  跨頁連動、資料表關聯。**圖是加在轉移表旁邊，不是取代它** —— 「從 A 能不能到 B」
  只有表格答得出來。同一份原始碼另外算成 SVG 進版控（`docs/architecture/diagrams/`），
  由 `tools/diagrams/Render-Diagrams.ps1` 產生，`tests/unit/test_diagrams_drift.py`
  比對 SHA-256 擋漂移（**不需要 node**）。

### 錯誤碼

`CategoryService.create` 本來把三種失敗塌成一個 `CATEGORY_CREATE_FAILED`，還把
`str(exc)` 放進 `details["reason"]` —— 而 `result_message()` 會把它印在畫面上，
直接違反 `AGENTS.md` 那條「一個錯誤碼只能代表一件事」。拆成
`CATEGORY_NAME_REQUIRED` / `CATEGORY_PARENT_INVALID` / `CATEGORY_ACTIVE_NAME_CONFLICT`。

> **同樣的寫法在別處還有 50 處**（`details={"reason": str(exc)}`）。這一版只修了
> 這一個，其餘沒動 —— 那是一次獨立的整理，不該夾在改版裡順手做掉。
> 那次整理是 **0.16.0**。

### 新增的守門

`ui/` 不得直接建 `QDateEdit`、系統設定四個分頁名納入文件漂移比對、
類別樹查詢不得掃到會長大的表、mermaid 與 SVG 的 SHA-256 比對，
以及三條走**真正按鈕路徑**的跨頁連動測試（不是自己 `emit`）。

## 0.14.4 - 記帳那一頁終於叫記帳（行為零改變）

v0.14.0 把 UI 上的「快速記帳」改成「記帳」時，**檔名與類別名留在原地** ——
那是刻意延後的（改檔名要動 import 與測試，而當時的收益只是名字好看）。現在收掉。

| | 舊 | 新 |
|---|---|---|
| 檔案 | `ui/pages/quick_entry.py` | `ui/pages/entry.py` |
| 類別 | `QuickEntryPage` | `EntryPage` |
| 屬性 | `MainWindow.quick` | `MainWindow.entry` |

屬性一起改，是因為 `MainWindow` 其他七個頁面屬性**全部**跟著 `PageId` 命名
（`overview`、`inbox`、`transactions`…），只有這一個不是 —— 留著它等於只改一半。

**文件一個字都沒動。** `quick_entry` / `QuickEntryPage` 在 `.md` 裡零出現；
「快速記帳」四個字只出現在 changelog、lessons、REQ 這些記錄歷史的地方，那些該保留舊名。

### 沒有加守門測試，以及為什麼

想過寫一條「`PageId.X` 必須對到 `pages/x.py` 的 `XPage`」，但 `PageId.BALANCE`
對到的是 `balance_snapshot.py` / `BalanceSnapshotPage`。**第一天就要例外清單的規則不是規則** ——
它擋不住真正的漂移（漂的那一個大可以進例外清單），只會讓下一個人以為有人在看著。

## 0.14.3 - 表格不再在字體套上去之前量自己

**剛開程式時「操作設定 → 帳戶」的表頭是切掉的**（「目前餘額（TWD」），底下還有一條
橫向捲軸。修前兩個缺陷時截實機圖發現的。

`setup_table()` 在建構表格的當下就量欄寬，而 `MainWindow.__init__` 是**先建好八個頁面、
再**套 `apply_dark_theme(app)` —— 那會換掉整個 application 的字體。量的時候字體還是
預設的：header 回報 `sectionSizeHint = [32, 109, 32]`，套上 12pt 中文字型之後是
`[52, 155, 52]`。`maximumWidth` 因此凍結在 187 px，而欄位實際需要 279 px。

而且沒有東西會再算一次 —— `fit_to_contents` 只掛在 `modelReset` 上。所以這個缺陷
**只在「剛開程式、還沒動過任何東西」時看得到**，也就是每天的第一眼。

修法是把 `apply_dark_theme()` 移到 `MainWindow.__init__` 的最前面，任何 widget 建出來
之前就套好。`_build()` 裡原本那句「側邊欄要在 apply_dark_theme 之後才建」說明作者
早就知道這一類問題，只是當時只處理了側邊欄。

### 既有的守門為什麼漏掉

`test_shrink_wrapped_tables_are_never_clipped` 在量之前先建了帳戶與類別、又呼叫了
一次 `refresh()` —— 那會多發一次 `modelReset`，而**那一次的重算是對的**。
所以它只證明了「刷新過的表格沒問題」。

新增 `test_tables_are_not_clipped_on_a_brand_new_ledger`：**開完程式什麼都不做**，
直接量每一張表的寬度與橫向捲軸。它在修好之前是紅的（帳戶表 186 px、欄位需要 288 px）。

## 0.14.2 - 側邊欄不再自己跳頁，新增帳戶說得出哪裡不對

兩個使用者回報的缺陷。

### 焦點碰到側邊欄，畫面就跳回資產總覽

回報的症狀是「在操作設定裡做任何事都有機會跳回資產總覽」。

`QAbstractItemView::focusInEvent` 在 current index **無效**時會自己把它設成第一列 ——
而舊版把非作用中那一組的 current row 設成 `-1`，第 0 列又正好是資產總覽。
於是焦點一碰到「日常」那組，`currentRowChanged(0)` 就發出來，畫面跟著跳。

讓焦點移動的事情多得數不完：關掉對話框、按鈕被 `bind_selection` 停用、按 Tab。
**實測在操作設定裡按四次 Tab 就中**，焦點鏈是
`QTabBar → QPushButton → QTableView → 側邊欄清單`。

同一個成因還有一個沒被回報的版本：**剛啟動、還沒點過任何一頁時**，「設定」那一組
從來沒有被選過，焦點碰到它會跳到法規參考。

修法是讓兩組清單的 current row **一直保持有效**，Qt 就沒有東西可以自作主張。
「現在是哪一頁」改由 `Sidebar._current` 自己記。代價是「點自己那組裡已經是 current
的那一列」不會觸發 `currentRowChanged`，所以另外接了 `itemClicked` ——
側邊欄裡不該有任何點不動的東西。

### 「新增帳戶」的錯誤訊息把 SQL 丟到畫面上

在定存對話框按「新增帳戶…」會看到：

> 帳戶無法建立，請確認名稱沒有重複且金額格式正確。
> （UNIQUE constraint failed: accounts.name）

三個問題，同一個成因：`AccountService.create` 把三種例外接在同一個 `except`，
回同一個 `ACCOUNT_CREATE_FAILED`。**一個錯誤碼代表三件事，訊息就只能同時指控兩個
欄位而且兩個都說不清楚**；`details["reason"]` 塞 `str(exc)`，`result_message()`
又會把它印出來，所以 SQLite 原文直接漏到畫面上。

現在三種失敗各自有錯誤碼與說法，而且**先問清楚再寫**：

| 情況 | 錯誤碼 | 使用者看到 |
|---|---|---|
| 名稱空白 | `ACCOUNT_NAME_REQUIRED` | 請輸入帳戶名稱。 |
| 金額格式不對 | `ACCOUNT_OPENING_BALANCE_INVALID`（新增） | 期初餘額只能是整數元，例如 0 或 100000 |
| 名稱已被使用中帳戶佔用 | `ACCOUNT_ACTIVE_NAME_CONFLICT` | 已經有一個叫「郵局定存」的帳戶了。要用它就直接在選單裡選 |

預期外的例外原文放 `details["detail"]`（不顯示），不再放 `reason`。

**互動上更重要的一點**：那個對話框的預設名稱就是「郵局定存」，也就是最可能已經開過的
名字 —— 第二次按必然撞名。撞名時使用者要的其實是「用那一個」，所以現在直接把它
選起來並說一聲，而不是丟一個他無法行動的錯誤框。

### 新的守門（各注入驗證過會紅）

- `test_focus_landing_on_the_sidebar_does_not_navigate` —— 四種 focus reason ×
  兩組清單 × 啟動當下，都不能換頁。
- `test_tabbing_through_a_settings_tab_never_changes_the_page` —— 連按 40 次 Tab。
- `test_clicking_the_current_page_again_still_works` —— `itemClicked` 那條路。
- `test_creating_an_account_with_a_taken_name_says_which_name_and_leaks_no_sql`
  —— 訊息要有名字，且不得出現 `UNIQUE` / `constraint` / `sqlite3` / `accounts.name`。
- `test_a_bad_opening_balance_is_a_different_error_from_a_taken_name`
- `test_adding_an_account_that_already_exists_just_selects_it`

## 0.14.1 - 交易只剩一個寫入點

架構檢視找到的一塊沒收乾淨的東西，以及它已經造成的一個實際缺陷。

**`infrastructure/automation_store.py` 是唯一不在 `stores/` 底下、也不是 `LedgerStore`
一部分的 store。** 它的 `confirm_occurrence` 自己重寫了一份「建立交易」——
transactions 列 ＋ postings ＋ allocation ＋ FTS，約 70 行。

當初那樣寫是有理由的：確認入帳要在**同一個 SQLite transaction** 內建交易並把那一期標成
`confirmed`（否則會出現「狀態是 confirmed 但交易沒建出來」），而
`create_transaction()` 會自己開一個 transaction，塞不進外層。**錯的不是那個取捨，
是停在那裡** —— 兩份實作放著不動就會各自漂，而它們真的漂了：

- 兩份 `_refresh_fts` 的 SQL 一字不差，但**只有一份會先 `DELETE`**。
- 兩份 `_audit` **只有一份收 `correlation_id`**，另一份自己 `uuid4()` 生一個新的。

### 修好的缺陷

**`occurrence.confirm` 的稽核列與它建立的交易帶著兩個不相干的 `correlation_id`。**
那一欄存在的唯一目的就是把同一次操作在不同表留下的列串起來 —— 拿著交易查稽核查不到，
拿著稽核查交易也查不到。現在確認入帳的三張表（`transactions`、`scheduled_occurrences`、
`audit_events`）共用同一個。

順帶：定期收支確認出來的交易現在也會留下 `transaction.create` 稽核列，與手動記帳一致。

### 做法：改簽章，不是選一邊

共用的部分抽成 `StoreBase._write_transaction()` / `_write_transfer()`，它們**收
`connection` 而不是自己開**。「就寫這一筆」的呼叫者自己包一層 transaction，
「建交易＋改狀態」的呼叫者直接傳自己的進去 —— 兩種情境同一份實作，原子性也保住了。

`replace_transfer` 那第三份寫入路徑一併收編（多一個 `replaces_transaction_id` 參數）。
`automation_store.py` 搬到 `stores/automation.py` 並成為 `LedgerStore` 的第六個聚合；
`AutomationService` 的簽章改成跟其他 service 一樣收一個可選的 store（以前自己 new 一個，
所以 controller 沒辦法分享，`initialize_database` 也多跑一次）。

**淨減 74 行**（`automation.py` 562→487、`transactions.py` 406→280、`base.py` 211→338）。

### 順手補上一條從來沒被測過的行為

注入驗證時把 `_refresh_fts` 的 `DELETE` 拿掉，預期會紅 —— 結果 **128 個測試照樣全綠**。
`transaction_fts` 是另一張表，少了 `DELETE` 就會留下過期索引，症狀是**改過備註的交易
用舊關鍵字還搜得到**，而且每改一次多長一列。這個行為從專案有 FTS 那天起就沒有測過。

補了 `test_editing_a_transaction_leaves_no_stale_row_in_the_search_index`，再跑一次注入
就紅了，訊息正好是使用者會看到的症狀。

**注入之後沒有變紅，不是「這段程式不重要」，是「這裡沒有測試」。**

### 新的守門（各注入驗證過會紅）

- `test_only_one_module_writes_a_transaction` —— `transactions`、`transaction_fts`、
  `audit_events` 各只能有一個寫入點（`migrations.py` 除外，重建索引是 schema 演進）。
- `test_every_store_lives_in_the_stores_package` —— store 一律放 `infrastructure/stores/`。
- `test_confirming_an_occurrence_shares_one_correlation_id_with_its_transaction`
- `test_confirming_an_occurrence_goes_through_the_same_transaction_writer`

## 0.14.0 - UI 結構重整

**這一版沒有新的帳務功能。** 八個症狀有同一個成因：這個專案從來沒有寫下
**「一頁是什麼、什麼東西該放在哪一頁」**。每一頁各自發明版面；分組標題沒地方放就塞進
清單裡假裝成不能點的項目；沒有「這一頁回答什麼問題」的成文說明，所以連作者自己都會
忘記「待確認」是做什麼的 —— 那不是記性問題，是那一頁沒有講出自己是誰。

分六個 Stage，逐 Stage 停下確認。

### 兩個真的壞掉的東西

- **有子項目的類別完全無法被選取。** 舊的類別列表只在類別**沒有**子項目時，才把類別
  自己加成一列；有子項目時只列出項目，那一列的第一欄放的是類別名。所以「伙食」看得到
  卻選不到，改名、封存、刪除對這種類別全部失效。畫面上一切正常，壞的是**那一列代表誰**。
- **導覽拿顯示文字當 key**（`show_page("快速記帳")`、`_page_rows["待確認"]`）。
  改一個字就是執行時的 `KeyError`，而 mypy --strict 對 `dict[str, QWidget]` 沒有意見。
  改成 `PageId(StrEnum)`，顯示文字由 `LABELS` 查出來 —— **改 `LABELS` 不影響任何查表**。

### 側邊欄：分組標題整個拿掉

第三次處理這件事，前兩次（v0.12.0 淡色、v0.13.0 縮小加字距）都失敗，因為兩次都是
**程度差異**：標籤與項目仍然在同一欄、同樣左對齊的灰字，眼睛照樣讀成一串清單。

這次改成**讓它不存在**。分組靠**位置**表達：日常五項在上、設定三項沉到最底、
中間是會隨視窗長高的留白，加一條分隔線。**側邊欄裡每一個字都可以點**，有測試守著。

順序：資產總覽／記帳／待確認／交易紀錄／餘額盤點 ‖ 法規參考／操作設定／系統設定。
「快速記帳」改叫「記帳」。待確認的數字改畫在項目右側，不再把標籤改寫成「待確認（2）」。

### 資產總覽（新的第一頁，也是啟動預設頁）

總資產大數字 → 各帳戶餘額 → 定存 → 待辦。

- **總資產只加總「使用中」帳戶。** 封存的意思是不出現在選單，**不是錢消失了** ——
  封存帳戶若還有餘額，另外列一行講清楚，否則拿這個數字去對存摺會對不起來。
- 待辦有三種：待確認筆數、今天還沒盤點、最近一次盤點的未解釋差額。
  **差額為 0 時不顯示** —— 「差額 0」不是待辦事項。
- **今日尚未盤點的提醒從狀態列搬到這裡。** 一則 10 秒就消失的訊息，去泡杯茶回來就
  看不到了，等於沒有提醒。
- **切到這一頁就重算**，不靠其他頁發訊號。

### 效能：帳戶餘額改單一查詢（N+1）

`AccountService.list()` 原本對每個帳戶各跑一次 `account_balance_minor`，而
`connect_database` **每次都開一條新連線＋4 個 PRAGMA** —— 列一次帳戶等於 1+N 條連線。
改成一句 `LEFT JOIN` ＋ `GROUP BY` 算完所有帳戶。記帳頁、交易紀錄篩選、餘額盤點頁
一起受益。20 萬筆下實測 113 ms。

新的守門測試量的是**斜率**（多加幾筆資料，連線數不能跟著長），不是絕對數字。
`EXPLAIN QUERY PLAN` 那條另外斷言 `SCAN accounts` 要逐字出現 —— SQLite 的計畫報的是
查詢裡的別名，所以那句 SQL **刻意不用表格別名**，別名一加守門就什麼都認不出來。

### 待確認：兩張表併成一個收件匣

一張表六欄（到期日／來源／名稱／類型／金額／狀態說明），六顆按鈕減到三顆。

- **「來源」欄不能省。** 兩種來源的「類型」講的是不同的事：定期收支是收入／支出／轉帳，
  定存是到期／領息／存入。
- 確認與略過都**依來源分派**：定期收支開對話框可先改，定存只問**實際金額**（以存摺為準）。
- **「全部確認」不處理定存。** 建議利息是程式試算的，權威值在存摺上；批次套用試算值
  等於替使用者決定一個他沒看過的數字。訊息會講清楚還剩幾件，不是默默跳過。
- **「產生到期項目」不再常駐。** 啟動時本來就會產生一次，平常按它什麼都不會發生 ——
  一顆按了沒反應的按鈕比沒有按鈕更糟。只有真的還有漏期時才浮出一行提示與行內按鈕。
- **空的時候整組操作收起來，換成一段說明**：這裡的東西是草稿，確認之後才會變成交易，
  程式不會自己記帳。空表格加三顆停用的按鈕說不出任何事情。

### 操作設定拆成六個分頁

**帳戶／類別／項目／模板／定期收支／定存** —— 前四個是記帳會用到的名冊，
後兩個是會自己到期的東西，**順序本身就是分組**。

- 「類別」與「項目」分開是因為要做的事不一樣：類別十來個、很少動；項目幾十個、
  每個月都在加。合在一頁時兩邊都做不好，舊版就是這樣漏掉「有子項目的類別沒有自己的列」。
- **UI 上「週期排程」全部改叫「定期收支」**。程式識別字 `recurring_schedules`、
  `schedule_id` 不動 —— 那是 schema，改它要 migration，而使用者看不到它。
- **定存不與定期收支合併**：一個是「每 N 個月重複同一筆」，一個是「一期一期滾、
  有利率與到期轉存方式」，合併會做出一個裝兩種表單的分頁。
- `automation.py`（385 行、裝了兩件事）拆成 `templates.py` 與 `recurring.py`，
  `DraftDialog` 移到 `widgets/draft_dialog.py` 共用。

### 版面：內容置中、各自有寬度上限

**一個全域上限套全部是錯的** —— 表單再寬只會讓標籤與欄位隔半個螢幕，但交易紀錄有七欄，
寬度是真的有用。所以記帳 720、資產總覽 980、其餘 1600，行為是
`min(可用寬度, 上限)` 並置中。1920 px 下記帳頁不再靠左貼著側邊欄、右邊空一半。

- **欄位少的表格收到欄寬總和**，不然表頭只畫到最後一欄就結束，右邊留下一大塊有框線
  卻沒有表頭的空白。操作設定裡的表格**連高度也收到列數**（上限 14 列）。
- **不寫死視窗最小尺寸**，讓內容決定；實測從 1131 px 降到 904 px（拆開兩處
  「六顆按鈕擠同一行」，並把那行不會換行的資料庫完整路徑搬進「系統設定 → 資料路徑」，
  改成可選取複製的唯讀輸入框）。
- 視窗大小與位置記在 `config_dir/window.json`。那是 UI 狀態不是帳務資料，**不進資料庫**。
- 狀態列只留暫時訊息。

### 文件與守門

- **`docs/architecture/ui-workflows.md` 整份重寫**，開頭新增**頁面地圖** ——
  每一頁四欄：它回答什麼問題／什麼時候用／**不在這裡做的事**。
- 新增 `tests/unit/test_docs_drift.py`：把八個頁面名與六個分頁名**逐字**比對它們有沒有
  出現在那份文件裡，並斷言退休的舊名真的消失（不是新舊並存）。
- 用詞漂移的守門改成**掃原始碼的 AST**（`RETIRED_UI_WORDS`），不是掃執行中的 widget ——
  只有按下「重製」才看得到的那份字串，靠實機點過去發現不了。
- `state-machines.md` §3 改成**兩個來源、同一張轉移表**（分開寫的那一版正是「一頁兩張表」
  的來源）；glossary 新增資產總覽／總資產／記帳／定期收支／收件匣。
- `docs/lessons.md` 新增三筆：程度差異失敗兩次、顯示文字當 key、
  有子項目的類別選不到（含「第一版回歸測試差點是假的」）。

### 這一版學到最貴的一件事

**測試全綠不等於畫面是對的。** 這六個 Stage 裡有四個毛病是**只有截實機的圖才看得到**的：
表格底下 200 px 的空框、還有 700 px 空間卻先斷行的說明、收到寬度卻沒收高度而變成
又窄又高的長條、表格停在 `QTableView` 那個沒有意義的預設 sizeHint。

而且發現了一條**從加進來那天起就沒有檢查過任何東西**的守門 ——
它用 `if not table.isVisible(): continue` 過濾，而 `QStackedWidget` 底下的頁在
offscreen 平台上**永遠**回報 `False`。現在的規則是：UI 測試量 geometry 不量可見性，
**每一個帶 `continue` 的檢查迴圈都要有一條陽性對照**（`assert checked >= N`）。

## 0.13.0 - 字體、日期精度與側邊欄標題

實機試用後的三項修正。

- **字體改成 `Microsoft JhengHei UI` 12pt Medium。** 原本是 `Segoe UI Variable` 11pt，
  而那個字型**沒有中文字形** —— 中文全靠 fallback，字重也套不到 fallback 上，
  所以中文看起來偏細。把七種組合排在同一張圖上比對才看出來：對 Segoe 設 Medium
  只有數字變粗，中文一點都沒變。主字體改用中文字型，字重才管得到該管的字。
- **時間欄位改成只有日期（UI-1 以「不做時鐘」收掉）。** 原本規劃彈出式時鐘選擇器，
  改成把時分欄位整個拿掉 —— 記帳需要的精度就是「哪一天」。
  資料庫仍存完整時間戳：新建補現在的時分秒（**保住同一天的先後順序**，
  全塞 00:00 的話當天排序只能靠 id），編輯沿用原值（改個備註不該讓那筆跳到當天最後）。
  三個輸入點一起改：快速記帳、餘額盤點、交易編輯對話框。顯示一律只到日。
- **側邊欄的分組標題不再長得像可以點的項目。** 「每天用」「設定與查閱」原本只是
  顏色淡一點、大小照舊，使用者的第一個反應是「這是什麼？為什麼不能用？」——
  那就是做壞了。改成字級小一階、字距拉開、顏色更淡，看起來就不像可以點的東西。

## 0.12.0 - 配色重做與介面優化（UI-2）

深藍換成**中性純灰**。方向由使用者定案：固定深色 ／ 零色偏灰 ／ 幾乎不用彩色 ／
支出紅收入綠。**介面本身幾乎沒有顏色**，所以畫面上任何一抹紅或綠都一定是資訊。

- 色票集中在新的 `ui/colors.py`，**QSS 不得出現清單以外的色碼**（測試會掃）。
  主要按鈕改成近白底深字 —— 在沒有強調色的前提下，靠明度（對比 14.75）比任何
  彩色按鈕都更跳。選取列是淺一階的灰。
- 每個「文字／底色」組合的 WCAG 對比都算過並有測試守著，而且是拿**選取列**
  （最亮的底）去算 —— 選取時金額正好是最該看清楚的東西。
- **金額欄重做**：右對齊、千分位、正負號、支出紅收入綠、轉帳不上色。
  顏色不是唯一線索，`-120` / `+36,000` 的符號在色盲與列印時仍然成立。
- **修正成功訊息用紅色顯示。** 「交易已儲存。」原本寫進紅色的 `errorLabel`，
  每天最常做的動作回饋長得像失敗。改用帶 `state` 屬性的 `statusLabel`。
- **修正 12 處「沒選取就按按鈕，完全沒反應」。** 新增 `bind_selection`，
  對所選項目動作的按鈕在沒有選取時停用。
- 快速記帳：流向改成**三顆分段按鈕**（不必展開下拉），金額欄放大成主角，
  表單有寬度上限（全螢幕時不再拉成 1,400 px 寬）。
- 交易紀錄：篩選拆成兩行並補上標籤 —— 帳戶／類別／狀態三個下拉原本**完全沒有標籤**。
- 側邊欄分成「每天用」與「設定與查閱」兩組；待確認的數字改用查表定位，
  不再寫死 `item(2)`。
- 分頁名稱照 glossary 修正：「重製與還原」→「重製」（那一頁只做重製，
  「還原」在隔壁分頁是另一件事）；子頁不再各自畫一個 20pt 大標，標題只留在容器層。
- 表格：欄寬依內容決定、標題與資料同一邊對齊、指定哪一欄吃掉多餘寬度
  （原本 `stretchLastSection` 把空間給了「狀態」，而「備註」被擠窄）。
- 帳戶列表移除「類型」與「幣別」兩欄 —— 前者永遠是英文的 `cash`，後者永遠是 TWD。
- **重製的確認框現在講得出會失去什麼**（「交易 12 筆、帳戶 3 筆…」），
  沒勾備份時明講「沒有備份可以救」，預設按鈕明確設成「否」。
  重製功能本身實測正常：開著視窗按下去不會被 Windows 檔案鎖擋住，
  資料清空、預設資料重建、備份保留、畫面全部重載。

## 0.11.0 - 收尾：電子票證慣例與文件對齊

**這一版沒有新功能**，是七個 Stage 的收尾：把一條慣例變成守得住的規則，並把落後的文件補上。

- **電子票證慣例（悠遊卡／一卡通／iCash）寫成硬規則。** 儲值 = 支出（類別「交通」、
  項目「電子票證儲值」），複數張卡共用同一個項目，退卡退餘額記成收入、同一個項目；
  **不建卡片帳戶、不追蹤卡內餘額**。慣例本身不需要任何程式，用現有的欄位就能表達。
- 新增 `test_schema_never_grows_a_stored_value_card_concept`：掃 schema 的所有表與欄位名，
  出現 `stored_value`／`card_balance`／`icash` 這類名字就失敗。**實際注入
  `accounts.card_balance_minor` 驗證過它會紅**，並有陽性對照擋住「掃到空清單卻靜默通過」。
  它守的是 schema 不是使用者的命名 —— 帳戶要取名叫「悠遊卡」程式攔不住，也不該攔。
- go-live runbook 補上「電子票證儲值」模板的逐欄填法。**金額欄留空是刻意的**：
  每次儲值金額不同，預填一個數字只會讓人不小心按下去。
- **`data-model.md` 補上 v6 與 v7** —— 三張定存表、`rate_type`、`effective_rate_ppm`，
  以及年利率為什麼存成 `annual_rate_ppm` 整數。這在 v0.9.1 就該補，是這次收尾才發現的落差；
  glossary 當時有同步，data-model 沒有。同時新增「刻意不存在的表與欄位」一節，
  把 payee 與卡內餘額兩條禁令連到守著它們的測試。
- `docs/index.md` 的 REQ-0007／0008／0009 狀態從「規劃中」更正為「已實作」。
- changelog 的三個「未發布」改成實際出貨的版本號（0.6.2、0.7.0、0.9.1）。
- README 更新到 0.11.0，補上定存與法規參考兩頁，驗證改為指向 `Verify.ps1`。
- **版本號寫在兩個地方，這次只改了一個。** `pyproject.toml` 升到 0.11.0 之後，
  `--json` 還印 0.10.0 —— 因為程式印的是 `__init__.py` 的 `__version__`。
  程式照跑、測試照樣全綠，只有每一份交出去的診斷檔上寫著舊版號。
  新增 `test_version_is_the_same_number_everywhere` 把兩處綁在一起，
  並要求 changelog 有對應的一節。同樣注入舊版號驗證過它會紅。

## 0.10.0 - 稅務與金融法規參考庫

側邊欄新增「法規參考」頁。**收 6 部法規、17 條精選條文**，涵蓋綜合所得稅、郵政儲金、
電子票證與電子支付、勞健保與贈與稅四個主題。

- 每一條都有**白話摘要 ＋ 對這個帳本的意義 ＋ 條文原文**，並附來源網址、修正日期、
  抓取時間與原始檔 SHA-256。摘要與原文不符時以原文為準，這句話寫在每一篇裡。
- **App 完全不連網。** 抓取是 `tools/law_sync/` 的外掛工具，用 research runtime 手動執行，
  依賴不進 `environment.yaml`。有一個測試用 AST 掃 `src/`，確認 App 不依賴任何網路函式庫。
- 法規庫以 `mode=ro` **唯讀開啟** —— 它是產生物，任何寫入都是 bug，應該當場失敗。
  測試會實際嘗試 DELETE 並斷言失敗。
- **法規庫不存在是正常狀態**，記帳完全不受影響，法規頁顯示怎麼建立而不是報錯。
- 中文全文搜尋改用**逐字索引**：`unicode61` 會把整串中文當成一個 token，
  導致搜「儲蓄投資」找不到「儲蓄投資特別扣除」。索引與查詢兩邊都逐字加空白，
  任何長度的子字串都找得到。不用 trigram tokenizer 是因為它要求關鍵字至少三個字，
  而「定存」「贈與」只有兩個字。
- `reviewed_at` 超過**六個月**標「需複查」。只是提示，程式不會自動抓取也不會自動改內容。
- 抓取紀律：同網域間隔 4 秒、**一部法規一個請求**（抓全文再自行切條）、429／503 立即全停。
  `--reparse` 可以只重新解析已存的原始檔，一個網路請求都不發。
- 繁中守門移除三個**兩用字**：`准`、`佣`、`划`。`佣` 是掃到所得稅法第 88 條原文才發現的 ——
  官方法律條文用了這個字，沒有比這更硬的證據。抓下來的原文與由它產生的 corpus
  一律不納入繁中掃描：引用的法條必須逐字照抄，不該去「修正」別人的法律。

**硬性非目標**：App 不計算稅額、不做申報、不依法規自動調整任何帳務數字。

## 0.9.1 - 定存的修改與機動利率（schema v7）

實機試用後的五項修正。

- **修正一鍵啟動器把「喚回既有視窗」誤報成失敗。** `Start-Process -PassThru` 的
  `ExitCode` 有時是 `$null`，而 PowerShell 裡 `$null -ne 0` 為真 —— 畫面上印出的是
  「程式啟動後隨即結束（exit code ）」，括號裡空的就是線索。既有視窗完全沒受影響，
  只有訊息是錯的。
- **修正日曆彈出視窗跑版。** 之前沒有任何 `QCalendarWidget` 樣式，導致全域的
  `QSpinBox` padding 撐爆年份輸入框、`QAbstractItemView` 的 padding 讓日期格容不下
  兩位數而全部顯示成「...」。新增一整節專屬樣式把日曆從全域規則隔開。
- **定存新增「利率類型」（固定／機動）。** 機動利率**不預先填數字** —— 存的當下填的值，
  到期時多半已經不是那個值了，「看起來精確但其實是舊的」比留空更糟。
- **新增從實際利息反推年利率。** 到期照存摺輸入實際利息，程式算出這一期實際等於年利率
  多少並存起來。反推用二分搜尋套用正推函式，所以**反推與正推必定一致**，
  進位規則變了兩邊會一起變。
- **補上定存的修改與刪除。** 合約可改名稱、到期轉存方式、利息轉入帳戶
  （計息方式與期長鎖住 —— 它們決定了已產生事件的形狀）；期可改本金、利率、日期。
  **這是 go-live runbook 裡「查到牌告利率再回來補」的實作路徑** —— 在此之前
  runbook 寫了一個不存在的操作。
- 新增定存合約的對話框可以直接開新帳戶，不必中途跳去「帳戶」分頁。
- schema v7：`deposit_contracts.rate_type`、`deposit_terms.effective_rate_ppm`。
  **必須是新的一版而不是改 v6** —— 使用者的資料庫已經跑過 v6，改 v6 對它毫無效果。

## 0.9.0 - 郵局定存（schema v6）

三種計息方式 × 四種到期轉存方式**全部實作**，共十二種組合各有測試。

- Schema v6：`deposit_contracts`、`deposit_terms`、`deposit_events` 三張表。
  `deposit_events` 的 `UNIQUE (term_id, event_type, due_date)` 讓「產生到期項目」
  可以重複按而不會產生重複列。
- **年利率用 `annual_rate_ppm` 整數存**（1.6% = 16000），延續「禁止 float」的規則。
  **可以留空** —— 還沒查到牌告利率不該擋住把定存記下來，只是算不出建議金額。
- **續約產生新的一期，不改寫舊的那一期**，所以每次續存當時的利率都留得下歷史。
  新一期的利率刻意留空，不沿用上一期 —— 續存是照當時牌告，沿用等於捏造事實。
- **程式不自動入帳。** 到期與每月領息只產生待確認項目，
  `test_generating_events_never_writes_a_posting` 斷言產生事件後 posting 一列都沒增加。
- 到期**提前七天**出現在待確認，讓「不自動轉存」來得及去郵局處理。
- 利息記成**收入**而非轉帳 —— 利息是新產生的錢，記成轉帳會讓總資產憑空不變。
- 試算永遠只是**建議值**，實際金額以存摺為準且可覆寫；覆寫的值才寫進
  `actual_interest_minor`。計息基準（複利／單利、進位規則）已列為 Stage 6 的查證項目。
- 起存日**允許早於帳本第一筆交易** —— 既有定存本來就比開始記帳早。
- UI：操作設定新增「定存」分頁（合約與每一期）；到期處理一律在「待確認」頁，
  不另開第二個入帳入口。
- 錯誤碼新增 13 個定存相關條目。

## 0.8.0 - 例外處理與可觀測性

- **第二次啟動改成把既有視窗叫到最前面**，不再跳「程式已經開著了」警告。使用者按捷徑的
  意思是「我要用這個程式」，正確的回應是把視窗給他。用 `QLocalServer` 具名管道
  （不是網路連線，沒有連接埠），並在 Windows 上先 `AllowSetForegroundWindow` 讓出前景權，
  否則通常只會看到工作列閃爍。等對方回 ack 才算成功 —— 「回報成功卻什麼都沒發生」比
  直接顯示警告更糟。叫不動時仍退回原本的對話框。
- 修正啟動失敗對話框把標題重複顯示兩次。
- 診斷資訊匯出改用 **UTF-8 with BOM**：這是「寫檔一律無 BOM」的例外，因為它是給人雙擊
  打開的 `.txt`，Windows 上沒有 BOM 的中文純文字會被編輯器猜成 cp950 而整份亂碼。

- **修正一鍵啟動器被新日誌打斷**：`Launch.ps1` 原本用 `2>&1` 把兩條串流合起來再解析 JSON，
  Stage 4 的啟動日誌一寫到 stderr 就讓它解析失敗。程式本身沒問題（`--json` 的 stdout
  仍是純 JSON），是啟動器不該混串流。改用 `Start-Process` 分開收，並新增
  `tests/integration/test_cli_output.py` 把這個契約釘住。

出錯時看得到訊息，也留得下紀錄。在這之前是**全專案零日誌、零 crash 處理**。

- **啟動失敗的六種分支全部實作**（`app/startup.py`）：設定檔損毀、路徑越界、資料夾不可用、
  磁碟滿、資料庫被鎖／損毀、schema 太新、已有實例在跑。每一種都給**可執行的**繁中指示 ——
  例如設定檔損毀會明講「刪掉它會退回預設路徑，不會損失帳務資料」。
  `--gui` 用 Qt 對話框，Qt 起不來就退回 stderr。
- **日誌**（`app/logging_setup.py`）：`logs/app.log`，1 MB × 5 輪替，UTF-8 無 BOM。
  **不記金額也不記備註**，只記操作名稱、錯誤碼、`correlation_id`、時間，所以可以直接交出去。
  日誌路徑分兩段決定：解析得出 `AppPaths` 就寫進去，解析不出來（設定檔壞了正是最常見的
  啟動失敗原因）就退回作業系統標準位置，避免最需要紀錄的那次失敗剛好沒有紀錄。
- **全域例外攔截**（`ui/error_handler.py`）：Qt slot 丟出的例外不再讓視窗無聲消失，
  改成寫日誌 ＋ 顯示含 `correlation_id` 的對話框，**可以繼續使用**。
- **單一實例守門**（`app/single_instance.py`）：用 `filelock` 在 `ledger_dir` 放 advisory
  lock。這把原本宣告了卻沒人用的依賴變成有用的依賴。鎖綁在 `ledger_dir` 上，
  所以指向不同資料夾的實例互不干擾；殘留的鎖檔不會擋住下次啟動。
- **診斷資訊匯出**（系統設定 → 備份與還原）：版本、schema 版本、七個路徑、
  `integrity_check`、各表筆數、最近 200 行日誌。**不含任何金額、備註或帳戶名稱。**
- 新增 24 個測試：REQ-0009 的五種驗收故障、日誌與診斷檔的隱私守門、
  以及熱查詢的 `EXPLAIN QUERY PLAN` 守門。
- 錯誤碼目錄新增「啟動失敗」與「診斷資訊」兩節，共 10 個新錯誤碼（總計 93）。
- 錯誤碼抽取器現在也看 `StartupFailure(...)` 與 `error_code=` 關鍵字。
- 架構守門的 Qt 檢查範圍改成「`ui/` 以外全部」—— 原本只掃四個子套件，
  根目錄的 `main.py` 漏掉了，而 Stage 4 正好差點在那裡 import PySide6。

## 0.7.0（後續補丁） - 一鍵啟動與快速記帳欄位修正

- **修正快速記帳與模板／排程對話框的孤兒標籤**：流向不是轉帳時仍會顯示「轉入帳戶」標籤。
  成因是 `QFormLayout` 的標籤是獨立 widget，舊寫法只對欄位 `setVisible`，改用 `setRowVisible`
  一起收掉整列。這是 Phase 1–2 就存在的缺陷，2026-08-18 實機試用時發現。
  `tests/ui/test_main_window.py` 已加測試鎖住，並實際退回舊寫法確認測試會失敗。

- 新增 `啟動 TagCor Ledger.cmd` 與 `Launch.ps1`：雙擊即可開程式，不需要先開終端機或
  `conda activate`。用絕對路徑呼叫環境直譯器，並清掉繼承來的 `VIRTUAL_ENV`／`PYTHONPATH`。
  已在乾淨環境與刻意重現的 venv 污染環境下各實測通過。
- `Launch.ps1 -CreateShortcut` 可在桌面建立捷徑；`TAGCOR_PYTHON` 可覆寫直譯器位置。
- **修正 `[project.gui-scripts]` 指向錯誤的函式。** 它原本指向 `main:main`，而 `main()`
  少了 `--gui` 只會印文字然後結束 —— `gui-scripts` 產生的 exe 沒有主控台，所以雙擊
  `tagcor-ledger.exe` 的實際效果是「什麼都沒發生」。改指向新的 `main_gui()`。
- 新增 `tests/unit/test_entrypoints.py` 守住上述兩者，以及 `.ps1` 的 BOM 與 `.cmd` 的純 ASCII。

## 0.7.0 - 徹底重構（行為零改變）

**這一版沒有任何功能變更。** 50 個既有測試斷言一個字都沒改，全部通過 —— 那是「純搬移」的證明。

- `ui/main_window_phase12.py`（2,114 行、13 個畫面類）拆成 `ui/pages/` 底下 12 個檔案，
  一個檔案一個畫面；共用的表格與表單 helper 移到 `ui/widgets/`，顯示字串集中到 `ui/formatting.py`。
  `MainWindow` 移到 `ui/main_window.py`，檔名不再帶 `phase12` 這種歷史痕跡。
- `infrastructure/sqlite_store.py`（1,381 行）依聚合拆成 `infrastructure/stores/` 底下的
  `base`／`accounts`／`categories`／`transactions`／`balance`。`LedgerStore` 對外的方法一個沒少。
- 新增 `tests/unit/test_architecture.py`：用 AST 守住分層邊界（domain 不得認得 Qt／SQLite／其他層、
  只有 `ui/` 可以 import PySide6、依賴方向只能由外往內、`ui/` 不得出現 SQL），
  以及單一模組 700 行上限。四個守門都實際注入違規驗證過會失敗。
- mypy 的 PySide6 放寬範圍縮小：從整個 `main_window_phase12` 改成只放寬真的碰 Qt 的模組，
  且改用 `disallow_subclassing_any = false` 取代整組 `misc`。`ui/controller.py` 與
  `ui/formatting.py` 現在維持完整 `--strict`。
- 移除 `package-data` 指向不存在的 `resources/icons/`。
- 繁體中文守門字表改用專案外的 204 個繁體 Markdown 驗證，移除三個誤報：`承`、`殖`、`璃`。

## 0.6.2（後續補丁） - 文件骨架

- 新增 `docs/architecture/state-machines.md`：八個狀態機的完整轉移表，含刻意不做的推論。
  記錄了 `EntryType.ADJUSTMENT` 自 v1 起空置至今，作為「先加著以後再說」的實例。
- 新增 `docs/architecture/error-codes.md`：**83 個錯誤碼**全部有成因與「使用者該怎麼做」。
  由 `tests/unit/test_error_codes.py` 用 AST 掃描比對，程式與文件不同步會讓測試失敗。
- 新增 `docs/architecture/glossary.md`：用詞對照表，含「不要叫成什麼」與「刻意不存在的詞」。
- 新增 `docs/operations/go-live-2026-09.md`：九月上線操作清單，不需寫任何程式。
- 新增 REQ-0006～REQ-0010 與 ADR-0004～ADR-0009。
- `docs/index.md` 改寫：加入人類與 LLM 兩條閱讀路線，以及每份文件的權威範圍。
- 新增 `docs/research/`：市面產品調查（Stage 1），17 個來源含 SHA-256 與抓取時間。
- 新增 `tools/fetch.py`：有節奏紀律與出處紀錄的擷取器，Stage 6 法規庫沿用。

## 0.6.2 - 資料與程式位置分離

- 帳務資料移出程式所在位置，改到 `<資料根目錄>`；專案資料夾之後若推上 remote 只會公開程式。
- `system_paths.json` 新增 `data_root` 與 `settings_version`。`ledger_dir` 與 `backup_dir` 現在必須都在 `data_root` 底下，違反時丟 `PATH_OUTSIDE_DATA_ROOT`。
- `exports/`、`logs/`、`tmp/` 改由 `data_root` 推導，不再由 `ledger_dir.parent` 推導 —— 舊做法讓 `ledger_dir` 的深度決定另外三個資料夾長在哪。
- **修正路徑搬移的順序缺陷**：舊版先寫指標檔才搬資料庫，搬移失敗時指標已指向新位置而資料還在舊位置，下次啟動會建一個空資料庫、看起來像資料消失。現在改為「先複製 → 寫指標檔 → 才刪舊檔」，任何一步失敗都會清掉半成品並保持原狀。
- 指標檔改用「寫暫存檔再 `os.replace`」的原子寫入，避免寫到一半損毀。
- 新增 `tests/integration/test_data_paths.py`（7 個測試），涵蓋 `data_root` 約束、舊設定檔相容、搬移失敗回滾，以及 Windows 路徑大小寫語意。
- 移除 `CODEX.md`；`AGENTS.md` 成為 agent 規則的唯一正本，`CLAUDE.md` 指向它。
- 新增 `.claude/settings.json` 的讀寫邊界規則，與 `Verify.ps1` 的路徑漂移檢查。
- 新增 `Verify.ps1`：一鍵跑漂移檢查 ＋ ruff ＋ mypy --strict ＋ pytest。

## 0.6.1 - Phase 4.1

- 將 PySide6 UI 統一為專業深藍深色主題。
- 新增 `apply_dark_theme(app)`，統一設定 `Fusion` style、字體、palette 與 QSS。
- 修正 `QTabWidget/QTabBar` 未選取分頁文字與背景對比不足。
- 側邊欄與備份清單改用不同 objectName，避免全域 `QListWidget` 樣式污染。
- 新增主要/危險按鈕角色樣式與 UI smoke 測試。
- README、CODEX、Roadmap、Requirements、Architecture 與 Release Checklist 依 Phase 4.1 重新整理。
- 清理文件編碼與閱讀順序，當前規格文件維持 UTF-8 可讀內容。

## 0.6.0 - Phase 4

- 側邊欄重整為 6 個主頁：快速記帳、餘額盤點、待確認、交易紀錄、操作設定、系統設定。
- 新增外部系統路徑設定，分離記帳資料路徑與備份路徑。
- 備份改為手動建立；移除啟動自動備份。
- 還原/重製前保護備份改為使用者勾選。
- 新增重製目前記帳資料功能。
- 帳戶、類別、項目新增「刪除未使用」。
- UI 用詞改為「類別／項目」。
- 移除「對象／商家」與 payee schema/runtime/UI/tests。
- Schema v5 重建交易 FTS，只搜尋備註、類別/項目與帳戶。
- README、CODEX 與 docs 依 Phase 4 重新整理。

## 0.4.0 - Phase 3

- 新增餘額盤點與未解釋差額追蹤。
- Schema v4 新增 `balance_snapshots`。
- 新增盤點列表、差額交易列表、盤點 CSV 匯出。
- 啟動後可提醒今日尚未盤點預設帳戶。

## 0.3.0 - Phase 1–2

- 交易列表新增組合篩選與雙向分頁。
- 新增原子轉帳替換。
- 新增帳戶與類別恢復。
- 新增模板、週期排程、待確認項目。
- 新增備份驗證、還原與 CSV 匯出。

## 0.2.0 - Stable core

- SQLite 成為主資料庫。
- 建立帳戶、類別、交易、posting、allocation、audit 與 FTS。
- 移除 CSV/JSON runtime store。

## 0.1.0 - 原型

- 初版快速記帳原型與歷史文件，已封存於 `docs/archive/phase-0-2/`。
