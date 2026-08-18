"""稅務與金融法規參考庫的查詢（**唯讀**）。

## App 永遠不連網

這個服務只會開一個本機檔案。抓取是專案外掛工具（`tools/law_sync/`）的事，
用 research runtime 手動執行，它的依賴不進 `environment.yaml`。

## 為什麼要用 `mode=ro` 而不是「小心不要寫」

`file:...?mode=ro` 讓 SQLite 在**檔案層級**拒絕寫入。這比「我們不會寫」強得多 ——
參考庫是產生物，任何寫入都是 bug，而 bug 應該當場失敗而不是靜靜地改壞資料。
唯讀開啟也不會建立 `-wal`／`-shm`，資料夾維持乾淨。

## 法規庫不存在是正常狀態

使用者可能永遠沒跑過抓取工具。那時法規頁要顯示「尚未建立」，**不是崩潰**，
也不是擋住整個程式啟動 —— 記帳不依賴法規庫。
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tagcor_ledger.application.result import Result

REFERENCE_DB_ENV = "TAGCOR_REFERENCE_DB"
STALE_AFTER_MONTHS = 6
DISCLAIMER = "本頁是個人整理的參考資料，不是稅務或法律意見，以主管機關公告為準。"


def default_reference_path() -> Path:
    """法規庫在專案底下 —— 它是公開資訊，不是個人資料，與帳務資料完全分離。"""
    override = os.environ.get(REFERENCE_DB_ENV)
    if override:
        return Path(override).expanduser()
    # src/tagcor_ledger/application/reference.py → 專案根目錄
    return Path(__file__).resolve().parents[3] / "reference" / "reference.sqlite3"


@dataclass(frozen=True, slots=True)
class ReferenceEntry:
    entry_id: str
    topic: str
    topic_title: str
    law_name: str
    article: str
    title: str
    agency: str
    amended_date: str
    legal_status: str
    source_url: str
    fetched_at: str
    reviewed_at: str
    plain: str
    ledger_note: str
    body: str

    @property
    def heading(self) -> str:
        return f"{self.law_name} 第 {self.article} 條"


def characterize(text: str) -> str:
    """與 `tools/law_sync/build_reference_db.py` 必須完全一致的逐字轉換。

    中文沒有空白分詞，`unicode61` 會把整串中文當成一個 token，所以搜「儲蓄投資」
    找不到「儲蓄投資特別扣除」。索引與查詢兩邊都逐字加空白，才做得到子字串比對。
    """
    return " ".join("".join(text.split()))


def phrase_query(keyword: str) -> str:
    cleaned = "".join(ch for ch in keyword if not ch.isspace())
    if not cleaned:
        return ""
    return '"' + characterize(cleaned).replace('"', "") + '"'


def is_stale(reviewed_at: str, *, today: date | None = None) -> bool:
    """超過半年沒複查就標「需複查」。**只是提示，不會自動去抓新版。**"""
    current = today or date.today()
    try:
        reviewed = date.fromisoformat(reviewed_at)
    except ValueError:
        return True
    elapsed = (current.year - reviewed.year) * 12 + (current.month - reviewed.month)
    return elapsed >= STALE_AFTER_MONTHS


class ReferenceLibrary:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or default_reference_path()

    @property
    def available(self) -> bool:
        return self.database_path.exists()

    def _connect(self) -> sqlite3.Connection:
        """唯讀開啟。寫入會直接失敗，這是刻意的。"""
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def status(self) -> Result:
        if not self.available:
            return Result.fail(
                "REFERENCE_LIBRARY_MISSING",
                "尚未建立法規庫。",
                details={
                    "path": str(self.database_path),
                    "how": (
                        "先跑 tools/law_sync/fetch_laws.py 抓取，"
                        "再跑 build_corpus.py 與 build_reference_db.py 產生。"
                    ),
                },
            )
        try:
            with self._connect() as connection:
                meta = {
                    str(row["key"]): str(row["value"])
                    for row in connection.execute("SELECT key, value FROM reference_meta")
                }
        except sqlite3.Error as exc:
            return Result.fail(
                "REFERENCE_LIBRARY_UNREADABLE",
                "法規庫無法讀取。",
                details={"reason": str(exc)},
            )
        return Result.ok("法規庫可用。", details={"meta": meta, "disclaimer": DISCLAIMER})

    def topics(self) -> list[dict[str, object]]:
        if not self.available:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT topic, topic_title, COUNT(*) AS entries
                FROM reference_entries
                GROUP BY topic, topic_title
                ORDER BY topic_title
                """
            ).fetchall()
        return [
            {"topic": str(row["topic"]), "title": str(row["topic_title"]),
             "entries": int(row["entries"])}
            for row in rows
        ]

    def list_entries(self, *, topic: str | None = None, keyword: str = "") -> list[ReferenceEntry]:
        if not self.available:
            return []
        conditions: list[str] = []
        parameters: list[object] = []
        joins = ""
        if keyword.strip():
            joins = "JOIN reference_fts f ON f.entry_id = e.entry_id"
            conditions.append("reference_fts MATCH ?")
            parameters.append(phrase_query(keyword))
        if topic:
            conditions.append("e.topic = ?")
            parameters.append(topic)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = (
            f"SELECT e.* FROM reference_entries e {joins} {where} "
            "ORDER BY e.law_name, CAST(e.article AS INTEGER)"
        )
        try:
            with self._connect() as connection:
                rows = connection.execute(sql, parameters).fetchall()
        except sqlite3.Error:
            # 搜尋字串讓 FTS5 語法錯誤時回空清單，不要把例外丟到畫面上。
            return []
        return [_row_to_entry(row) for row in rows]


def _row_to_entry(row: sqlite3.Row) -> ReferenceEntry:
    return ReferenceEntry(
        entry_id=str(row["entry_id"]),
        topic=str(row["topic"]),
        topic_title=str(row["topic_title"]),
        law_name=str(row["law_name"]),
        article=str(row["article"]),
        title=str(row["title"]),
        agency=str(row["agency"]),
        amended_date=str(row["amended_date"]),
        legal_status=str(row["legal_status"]),
        source_url=str(row["source_url"]),
        fetched_at=str(row["fetched_at"]),
        reviewed_at=str(row["reviewed_at"]),
        plain=str(row["plain"]),
        ledger_note=str(row["ledger_note"]),
        body=str(row["body"]),
    )
