# 維護者筆記

**這一份沒有任何獨立規則。** 它是查詢表：想知道某件事的規則寫在哪，從這裡找過去。

> 2026-08-20 之前它是**第二份規格** —— conda/PySide6、workspace hygiene、UI 主題、
> 到期產生、餘額盤點全部各抄一段。抄過來的那幾段沒有人在維護，於是慢慢跟正本對不上。
> `docs/index.md` 的原則是「一件事只在一個地方是權威的」，這一份現在照那條原則寫。

## 我要找的規則在哪

| 我想知道 | 去哪 |
|---|---|
| 動手前的硬規則、架構邊界、禁令 | [`AGENTS.md`](../AGENTS.md) ＝ [`CLAUDE.md`](../CLAUDE.md) —— **先讀這份**（兩份平級、內容相同）|
| 資料放哪、`data_root` 約束、備份格式、`window.json` | [storage-layout](architecture/storage-layout.md) |
| 表、欄位、索引、migration 版本 | [data-model](architecture/data-model.md) |
| 有哪些狀態、哪些轉移合法 | [state-machines](architecture/state-machines.md) |
| 每個錯誤碼的成因與處理 | [error-codes](architecture/error-codes.md) |
| 什麼該叫什麼、**不該叫什麼** | [glossary](architecture/glossary.md) |
| 側邊欄順序、每一頁回答什麼問題、版面規則 | [ui-workflows](architecture/ui-workflows.md) |
| 分層、檔案地圖、守著邊界的那幾條測試 | [overview](architecture/overview.md) |
| 建環境、更新環境、混裝 PySide6 怎麼救 | [environment](environment.md) |
| 發版前要檢查什麼 | [release checklist](release_checklist.md) |
| 踩過的坑與「不要再做」 | [lessons](lessons.md) —— **動 migration 或路徑之前必讀** |
| 某個決定為什麼是這樣 | `docs/decisions/ADR-XXXX`。**決定改了要新增 ADR，不要改舊的** |

## 從症狀找到檔案

上面那張表回答「規則寫在哪」。這一張回答**「東西壞了，要去看哪個檔」** ——
兩者不一樣：出問題的時候，人腦子裡有的是症狀，不是規則的名字。

| 症狀 | 主要檔案 | 守著它的測試 |
|---|---|---|
| 某一頁的數字沒跟著別頁更新 | `ui/main_window.py::_ledger_changed()` | `tests/ui/test_inbox_page.py::test_confirming_an_inbox_item_refreshes_the_transaction_list` |
| 側邊欄自己跳頁、焦點一碰就換頁 | `ui/widgets/sidebar.py` | `test_focus_landing_on_the_sidebar_does_not_navigate` |
| 日期欄怪怪的、日曆跑版 | `ui/widgets/forms.py::date_field()` ＋ `styles.qss` 的日曆一節 | `test_clicking_inside_the_date_field_never_changes_the_year` 等五條 |
| 表格被切掉、欄寬不對 | `ui/widgets/table.py` 的 `fit_to_contents` / `fit_to_rows` | `tests/ui/test_layout.py` |
| 金額顏色不對、紅綠被壓成白 | `ui/widgets/table.py::amount_color` ＋ QSS**不得**設 `color` | `test_amount_colours_survive_the_stylesheet` |
| 錯誤訊息看不懂、太籠統、印出英文碼或 SQLite 原文 | [`application/failures.py`](../src/tagcor_ledger/application/failures.py) 的 `ERROR_MESSAGES`（碼 → 中文，一個碼一個地方） | `tests/unit/test_failure_messages.py`、`tests/unit/test_error_codes.py` |
| 例外沒被接住、跳出全域錯誤對話框而不是中文 | [`application/failures.py`](../src/tagcor_ledger/application/failures.py) 的 `STORE_FAILURES` / `DOMAIN_FAILURES`。`NotFoundError` 繼承 `RuntimeError`，自己拼的 tuple 接不到它 | `tests/integration/test_store_failures.py`、`test_the_application_layer_catches_store_failures_by_name` |
| 到期日跳月、月底算錯、每月領息少一期 | [`domain/dates.py`](../src/tagcor_ledger/domain/dates.py) —— `add_months()` 一律用來源日期自己的日當 anchor，`clamped_date()` 是**唯一**實作「那個月裝不下就退到月底」的地方 | `tests/unit/test_dates.py` |
| 模板存成空 id、存下去卻不見了 | [`stores/templates.py`](../src/tagcor_ledger/infrastructure/stores/templates.py)`::validate_template` —— 空主鍵會 UPSERT 成一列空 id | `tests/integration/test_templates.py` 的空主鍵那一條 |
| 按了按鈕，視窗直接消失 | [`ui/error_handler.py`](../src/tagcor_ledger/ui/error_handler.py) —— 它接管 `sys.excepthook`，讓 Qt slot 的例外變成一句中文而不是關掉程式 | `tests/ui/test_error_handler.py` |
| 編輯模板之後多出一筆，舊的還在 | [`ui/widgets/template_dialog.py`](../src/tagcor_ledger/ui/widgets/template_dialog.py)`::save()` 沒保住 `template_id`（同一個 `replace()` 也要帶 `sort_order` 與 `status`）| `tests/ui/test_template_dialog.py` |
| 利率顯示對不上、輸入框讀不回去 | `domain/deposits.py::rate_to_ppm()` 解析、`ui/formatting/primitives.py::ppm_digits()` 顯示 —— **只有這一份** | `tests/unit/test_rate_conversion.py` |
| 交易翻頁翻到重複或空白 | [`ui/pages/transactions.py`](../src/tagcor_ledger/ui/pages/transactions.py) 的游標堆疊（keyset，不是 OFFSET） | `tests/ui/test_transactions_paging.py` |
| 想加一個新的 `raise ValueError("SOME_CODE")` | 加完要在 `ERROR_MESSAGES` 補一列，並在 [error-codes](architecture/error-codes.md) 補一列 | 兩條都會紅，訊息會告訴你缺哪一個 |
| 備份刪不掉、清單看不懂哪一份是哪一份 | `infrastructure/maintenance.py`（每個 `sqlite3.connect()` 都要包 `closing`）＋ `ui/formatting/messages.py::backup_row_text` | `tests/integration/test_backup_deletion.py`、`tests/unit/test_formatting.py` |
| 表格少一欄、最後一欄空白或炸 IndexError | 欄位標題在頁面的 `RowsModel(...)`，值在 `ui/formatting/rows.py` —— **兩邊各自定義** | `tests/ui/test_table_columns.py` |
| 搜尋框打特殊字元就查不出東西或跳錯 | `infrastructure/stores/base.py::build_fts_query`（雙引號要跳脫成 `""`）＋ 呼叫端的「空白就不要走 FTS」 | `tests/unit/test_fts_query.py`、`tests/integration/test_search_input.py` |
| 查詢變慢 | `infrastructure/stores/` 的 SQL | `tests/integration/test_query_plans.py` |
| **測試**變慢（尤其是越後面越慢） | `ui/theme.py::apply_dark_theme` —— application 層級的操作要傳播給每一個活著的 widget，一個 process 只能套一次 | `test_the_theme_is_only_applied_once_per_process` |
| 名冊的順序不對、排序設定沒記住 | `ui/widgets/reorder_dialog.py` ＋ `sort_editor.py`；`ORDER BY` 由 `stores/base.py::order_by()` 從各 store 的白名單組 | `tests/unit/test_order_by.py`、`tests/ui/test_reorder.py`、`tests/integration/test_category_order.py` |
| 文件與程式對不上 | `docs/architecture/ui-workflows.md` | `tests/unit/test_docs_drift.py` |
| 圖跟文字對不上 | `docs/architecture/*.md` 的 mermaid 區塊 | `tests/unit/test_diagrams_drift.py` |
| 畫面上出現不該有的用詞 | `ui/` 的字串常數 | `test_architecture.py` 的 `RETIRED_UI_WORDS` |

## 三件最容易踩的

1. **PySide6 由 conda 管理，不能放回 `pyproject.toml`。** Windows 下混裝 conda/pip 的
   PySide6 會讓 Qt DLL 載入失敗。已經混裝的話重建環境最乾淨。
2. **不要用 PATH 上的 `python`。** 一律完整路徑呼叫
   `<conda-root>\envs\tagcor-ledger\python.exe` ——
   工具 shell 不載入 profile，`conda activate` 會回報成功卻什麼都沒換。
3. **schema 變更一定要新增 migration**，不可假設是新資料庫。改舊的 migration 對已經
   跑過那一版的資料庫毫無效果。
