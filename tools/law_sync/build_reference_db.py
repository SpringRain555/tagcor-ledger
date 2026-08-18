"""corpus Markdown → `reference.sqlite3`（App 唯讀開啟的查詢用資料庫）。

    python tools/law_sync/build_reference_db.py

**只用標準庫。** 產生物不進版控 —— 隨時可以從 corpus 重建。

## 為什麼要另外做一個資料庫

corpus 是給人讀與審閱的；這個資料庫是給程式查的。分開的好處是全文搜尋用 FTS5 就好，
不必在 App 裡寫 Markdown 解析，而且**App 只需要唯讀開啟一個檔案**，
不必掃描資料夾、不必處理半寫入的檔案。
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = PROJECT_ROOT / "reference"
DATABASE_NAME = "reference.sqlite3"

SCHEMA = """
CREATE TABLE reference_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE reference_entries (
    entry_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    topic_title TEXT NOT NULL,
    law_name TEXT NOT NULL,
    article TEXT NOT NULL,
    title TEXT NOT NULL,
    agency TEXT NOT NULL,
    amended_date TEXT NOT NULL,
    legal_status TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    plain TEXT NOT NULL,
    ledger_note TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX idx_reference_topic ON reference_entries(topic, law_name, article);
CREATE VIRTUAL TABLE reference_fts USING fts5(
    entry_id UNINDEXED,
    law_name,
    title,
    plain,
    ledger_note,
    body,
    tokenize='unicode61'
);
"""

# 中文沒有空白分詞，`unicode61` 會把一整串中文當成**一個 token**。
# 結果是搜「儲蓄投資」找不到「儲蓄投資特別扣除」—— 那不是前綴，是子字串。
#
# 解法是索引時把每個字用空白隔開，查詢時對關鍵字做同樣的轉換再當**片語**查，
# 這樣任何長度的子字串都找得到。索引會變大，但這個庫只有幾十篇，無所謂。
#
# 不用 trigram tokenizer 的原因：它要求關鍵字至少三個字，而中文常見的查詢
# （「定存」「贈與」）只有兩個字。


def characterize(text: str) -> str:
    """把文字拆成以空白分隔的**單一字元**，讓 FTS5 能做子字串比對。

    先把原有的空白與換行去掉再逐字加空白，這樣索引與查詢的轉換方式完全一致 ——
    兩邊只要有一點不同，片語就對不上。
    """
    return " ".join("".join(text.split()))



def phrase_query(keyword: str) -> str:
    """把使用者輸入的關鍵字轉成對應的 FTS5 片語查詢。"""
    cleaned = "".join(ch for ch in keyword if not ch.isspace())
    if not cleaned:
        return ""
    escaped = characterize(cleaned).replace('"', "")
    return f'"{escaped}"'


def parse_document(path: Path) -> dict[str, str]:
    """讀 corpus Markdown 的 frontmatter 與三個區塊。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path} 沒有 frontmatter")
    _, front, rest = text.split("---", 2)

    entry: dict[str, str] = {}
    for line in front.strip().splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        entry[key.strip()] = value

    entry["plain"] = _section(rest, "## 白話摘要")
    entry["ledger_note"] = _section(rest, "## 對這個帳本的意義")
    entry["body"] = _fenced(rest)
    return entry


def _section(text: str, heading: str) -> str:
    if heading not in text:
        return ""
    after = text.split(heading, 1)[1]
    return after.split("##", 1)[0].strip()


def _fenced(text: str) -> str:
    if "```text" not in text:
        return ""
    return text.split("```text", 1)[1].split("```", 1)[0].strip()


def build(reference_dir: Path, *, target: Path | None = None) -> Path:
    corpus_dir = reference_dir / "corpus"
    documents = sorted(corpus_dir.rglob("*.md"))
    if not documents:
        raise SystemExit("corpus 是空的，請先跑 build_corpus.py")

    database = target or (reference_dir / DATABASE_NAME)
    database.unlink(missing_ok=True)

    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA)
        for path in documents:
            entry = parse_document(path)
            entry_id = f"{entry['pcode']}-{entry['article']}"
            connection.execute(
                """
                INSERT INTO reference_entries(
                    entry_id, topic, topic_title, law_name, article, title, agency,
                    amended_date, legal_status, source_url, fetched_at, source_sha256,
                    reviewed_at, plain, ledger_note, body
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    entry["topic"],
                    entry["topic_title"],
                    entry["law_name"],
                    entry["article"],
                    entry["title"],
                    entry["agency"],
                    entry["amended_date"],
                    entry["legal_status"],
                    entry["source_url"],
                    entry["fetched_at"],
                    entry["source_sha256"],
                    entry["reviewed_at"],
                    entry["plain"],
                    entry["ledger_note"],
                    entry["body"],
                ),
            )
            connection.execute(
                """
                INSERT INTO reference_fts(entry_id, law_name, title, plain, ledger_note, body)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    characterize(entry["law_name"]),
                    characterize(entry["title"]),
                    characterize(entry["plain"]),
                    characterize(entry["ledger_note"]),
                    characterize(entry["body"]),
                ),
            )
        for key, value in {
            "schema_version": "1",
            "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "entry_count": str(len(documents)),
            "disclaimer": (
                "本資料庫是個人整理的參考資料，不是稅務或法律意見，以主管機關公告為準。"
            ),
        }.items():
            connection.execute(
                "INSERT INTO reference_meta(key, value) VALUES (?, ?)", (key, value)
            )
        connection.commit()
    finally:
        connection.close()

    print(f"reference.sqlite3 已建立：{database}（{len(documents)} 篇）")
    return database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="從 corpus 建立法規查詢資料庫")
    parser.add_argument("--reference", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--target", type=Path, default=None)
    args = parser.parse_args(argv)
    build(args.reference, target=args.target)
    return 0


def stale_after_months(reviewed_at: str, months: int = 6, *, today: date | None = None) -> bool:
    """`reviewed_at` 超過幾個月就該複查。"""
    current = today or date.today()
    try:
        reviewed = date.fromisoformat(reviewed_at)
    except ValueError:
        return True
    elapsed = (current.year - reviewed.year) * 12 + (current.month - reviewed.month)
    return elapsed >= months


if __name__ == "__main__":
    raise SystemExit(main())
