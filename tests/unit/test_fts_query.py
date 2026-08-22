"""守門：全文檢索的查詢字串怎麼組。

`build_fts_query()` 是**唯一把使用者打的字送進 FTS5 語法**的地方。它把每個詞包成
`"詞"*`，而包起來之前一定要把詞裡面的 `"` 換成 `""` —— 少了那一步，使用者打一個
雙引號進去，FTS5 就會回 `unterminated string`，整個交易紀錄頁查不出東西。

跟真的 SQLite 對跑，不是只比字串：**這條規則的正確性由 FTS5 的解析器定義，不是由
我對它的理解定義。** 只比字串的話，我會把「我以為對的形狀」測成「對的形狀」。
"""

from __future__ import annotations

import sqlite3

import pytest

from tagcor_ledger.infrastructure.stores.base import build_fts_query


@pytest.fixture()
def fts() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
    connection.execute("INSERT INTO t VALUES ('hello world')")
    return connection


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("早餐", '"早餐"*'),
        ("早餐 咖啡", '"早餐"* AND "咖啡"*'),  # 多個詞是 AND 不是 OR
        ("  早餐   咖啡  ", '"早餐"* AND "咖啡"*'),  # 多餘空白吃掉
        ('a"b', '"a""b"*'),  # 雙引號跳脫成兩個
        ('"', '""""*'),
        ("", ""),
        ("   ", ""),
    ],
)
def test_the_query_shape(typed: str, expected: str) -> None:
    assert build_fts_query(typed) == expected


@pytest.mark.parametrize(
    "typed",
    ['"', 'a"b', '""', "*", "-a", "^x", "NEAR", "OR", 'x" OR t MATCH "y', "早餐", "a.b,c"],
)
def test_anything_the_user_can_type_survives_fts5(fts: sqlite3.Connection, typed: str) -> None:
    """使用者打得出來的字元都不該讓查詢炸掉，**包含 FTS5 自己的語法字元**。

    `NEAR`、`OR`、`*`、`^`、`-` 在 FTS5 裡都有意義，但它們被包在雙引號裡就只是字。
    `x" OR t MATCH "y` 是刻意寫成「想跳出引號」的形狀 —— 跳脫做對了它就只是一串詞。
    """
    query = build_fts_query(typed)
    assert query, "這些輸入都有實際內容，不該組出空查詢"
    rows = fts.execute("SELECT * FROM t WHERE t MATCH ?", (query,)).fetchall()
    assert isinstance(rows, list)


def test_escaping_is_what_keeps_it_alive(fts: sqlite3.Connection) -> None:
    """陽性對照：**證明跳脫那一步是承重的**，不是裝飾。

    照著 `build_fts_query()` 的形狀但拿掉 `.replace('"', '""')`，同一個輸入就會讓
    FTS5 丟 `unterminated string`。沒有這一條的話，上面那批測試在跳脫被拿掉之後
    仍然可能因為別的原因通過，我就看不出來守的是什麼。
    """
    without_escaping = " AND ".join(f'"{term}"*' for term in 'a"b'.split() if term.strip())
    with pytest.raises(sqlite3.OperationalError, match="unterminated string"):
        fts.execute("SELECT * FROM t WHERE t MATCH ?", (without_escaping,)).fetchall()

    fts.execute("SELECT * FROM t WHERE t MATCH ?", (build_fts_query('a"b'),)).fetchall()


def test_an_empty_query_would_be_a_syntax_error_so_callers_must_not_send_it(
    fts: sqlite3.Connection,
) -> None:
    """`build_fts_query("")` 回空字串，而 `MATCH ''` 是 FTS5 的語法錯誤。

    所以「空的就不要走 FTS」這件事**由呼叫端負責**（`TransactionStore.list_transactions()`
    的 `if filters.search.strip():`）。這條測試把那個前提釘住 —— 有人把那道 if 拿掉時，
    這裡會提醒他拿掉的是什麼。
    """
    assert build_fts_query("   ") == ""
    with pytest.raises(sqlite3.OperationalError):
        fts.execute("SELECT * FROM t WHERE t MATCH ?", ("",)).fetchall()


def test_prefix_matching_actually_matches_a_prefix(fts: sqlite3.Connection) -> None:
    """尾巴那個 `*` 是前綴查詢 —— 打「hell」要找得到「hello」。

    少了它，使用者得打完整個詞才搜得到東西，而這個欄位存在的意義就是打一半就找到。
    """
    assert fts.execute(
        "SELECT * FROM t WHERE t MATCH ?", (build_fts_query("hell"),)
    ).fetchall()
    assert not fts.execute(
        "SELECT * FROM t WHERE t MATCH ?", (build_fts_query("xyzzy"),)
    ).fetchall()
