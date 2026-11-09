"""把抓下來的法規原文 ＋ 手寫摘要，合成 git 追蹤的 corpus Markdown。

    python tools/law_sync/build_corpus.py

**只用標準庫**，所以專案環境也跑得起來（不必用 research runtime）。

## 為什麼 corpus 是文字檔而不是直接進資料庫

文字檔可以 diff、可以在 PR 裡審閱、可以看出「這次複查改了哪一句」。
`reference.sqlite3` 是從它產生的，隨時可以重建，所以不進版控。
這條分界和專案其他地方一致：手寫的進版控，產生物不進。

`reviewed_at` 表示有人複查過，不是上次重建的時間。REQ-0011 的 `law_review_due`
依它判斷法規參考庫是否完成年度複查，因此重建時沿用既有日期；新增條文則必須明確給複查日期。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = PROJECT_ROOT / "reference"


def load_manifest(path: Path) -> dict[str, dict[str, object]]:
    """每個 pcode 取最後一次抓取紀錄。"""
    latest: dict[str, dict[str, object]] = {}
    if not path.exists():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            latest[str(entry["pcode"])] = entry
    return latest


def frontmatter(values: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in values.items():
        text = "" if value is None else str(value)
        # 值裡有冒號或引號時用雙引號包起來，避免 YAML 解讀出錯。
        if any(ch in text for ch in ':"#') or text.strip() != text:
            text = '"' + text.replace('"', '\\"') + '"'
        lines.append(f"{key}: {text}")
    lines.append("---")
    return "\n".join(lines)


class ReviewedAtRequired(ValueError):
    """有新 corpus 條文但呼叫者未提供複查日期。"""

    def __init__(self, articles: list[str]) -> None:
        super().__init__(", ".join(articles))
        self.articles = articles


def parse_reviewed_at(value: str) -> str:
    """驗證複查日期必須是完整 ISO 日期。"""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("複查日期必須是合法的 YYYY-MM-DD。") from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("複查日期必須是 YYYY-MM-DD 格式。")
    return value


def existing_reviewed_at(path: Path) -> str | None:
    """讀取既有 Markdown frontmatter 中的合法複查日期。"""
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = _REVIEWED_AT.fullmatch(line)
        if match is None:
            continue
        try:
            parsed = date.fromisoformat(match.group(1))
        except ValueError:
            return None
        return match.group(1) if parsed.isoformat() == match.group(1) else None
    return None


_REVIEWED_AT = re.compile(r"^\s*reviewed_at:\s*(\d{4}-\d{2}-\d{2})\s*$")


def build(reference_dir: Path, *, reviewed_at: str | None) -> int:
    if reviewed_at is not None:
        parse_reviewed_at(reviewed_at)
    sources = json.loads((reference_dir / "sources.json").read_text(encoding="utf-8"))
    summaries = json.loads((reference_dir / "summaries.json").read_text(encoding="utf-8"))[
        "summaries"
    ]
    manifest = load_manifest(reference_dir / "manifest.jsonl")
    corpus_dir = reference_dir / "corpus"
    documents: list[tuple[Path, str]] = []
    missing_summary: list[str] = []
    missing_review_date: list[str] = []

    for topic in sources["topics"]:
        for law in topic["laws"]:
            raw_path = reference_dir / "raw" / f"{law['pcode']}.json"
            if not raw_path.exists():
                print(f"  略過 {law['name']}：還沒抓過")
                continue
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            fetched = manifest.get(law["pcode"], {})

            for flno, body in raw["articles"].items():
                key = f"{law['pcode']}:{flno}"
                summary = summaries.get(key)
                if summary is None:
                    missing_summary.append(key)
                    continue

                target = corpus_dir / topic["topic"] / f"{law['pcode']}-{flno}.md"
                document_reviewed_at = reviewed_at or existing_reviewed_at(target)
                if document_reviewed_at is None:
                    missing_review_date.append(key)
                    continue
                document = "\n".join(
                    [
                        frontmatter(
                            {
                                "law_name": law["name"],
                                "article": flno,
                                "title": summary["title"],
                                "topic": topic["topic"],
                                "topic_title": topic["title"],
                                "pcode": law["pcode"],
                                "agency": law["agency"],
                                "amended_date": raw["amended_date"],
                                "legal_status": "現行",
                                "source_url": sources["law_article_url"].format(
                                    pcode=law["pcode"], flno=flno
                                ),
                                "fetched_at": fetched.get("fetched_at", ""),
                                "source_sha256": fetched.get("sha256", ""),
                                "reviewed_at": document_reviewed_at,
                            }
                        ),
                        "",
                        f"# {law['name']} 第 {flno} 條　{summary['title']}",
                        "",
                        "## 白話摘要",
                        "",
                        summary["plain"],
                        "",
                        "## 對這個帳本的意義",
                        "",
                        summary["ledger_note"],
                        "",
                        "## 條文原文",
                        "",
                        "> 以下為原文引用。**摘要與原文有出入時，以原文為準。**",
                        "",
                        "```text",
                        body,
                        "```",
                        "",
                    ]
                )
                documents.append((target, document))

    if missing_review_date:
        raise ReviewedAtRequired(missing_review_date)

    for target, document in documents:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")

    if missing_summary:
        print(f"  以下條文沒有摘要，未產生：{', '.join(missing_summary)}")
    print(f"corpus 產生 {len(documents)} 篇，位置 {corpus_dir}")
    return len(documents)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="產生法規 corpus")
    parser.add_argument("--reference", type=Path, default=REFERENCE_DIR)
    parser.add_argument(
        "--reviewed-at",
        type=parse_reviewed_at,
        default=None,
        help="這次由人複查的日期，格式 YYYY-MM-DD",
    )
    args = parser.parse_args(argv)
    try:
        build(args.reference, reviewed_at=args.reviewed_at)
    except ReviewedAtRequired as error:
        print(f"以下新條文需要提供 --reviewed-at，未寫入任何 corpus：{', '.join(error.articles)}")
        return 2
    return 0


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
