"""法規 corpus 建置時保留人工作成的 reviewed_at。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "tools" / "law_sync" / "build_corpus.py"


def _reference_dir(tmp_path: Path, *, include_new_article: bool = False) -> Path:
    reference = tmp_path / "reference"
    (reference / "raw").mkdir(parents=True)
    (reference / "corpus" / "tax").mkdir(parents=True)
    sources = {
        "law_article_url": "https://law.example/{pcode}/{flno}",
        "topics": [
            {
                "topic": "tax",
                "title": "稅務",
                "laws": [{"pcode": "L0001", "name": "所得稅法", "agency": "主管機關"}],
            }
        ],
    }
    summaries = {
        "summaries": {
            "L0001:1": {"title": "第一條", "plain": "摘要", "ledger_note": "說明"}
        }
    }
    articles = {"1": "第一條原文"}
    if include_new_article:
        articles["2"] = "第二條原文"
        summaries["summaries"]["L0001:2"] = {
            "title": "第二條",
            "plain": "另一段摘要",
            "ledger_note": "另一段說明",
        }
    raw = {"amended_date": "2026-01-01", "articles": articles}
    manifest = [{"pcode": "L0001", "fetched_at": "2026-01-02T00:00:00Z", "sha256": "a" * 64}]
    (reference / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    (reference / "summaries.json").write_text(json.dumps(summaries, ensure_ascii=False), encoding="utf-8")
    (reference / "raw" / "L0001.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (reference / "manifest.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in manifest), encoding="utf-8"
    )
    return reference


def _existing_document(reference: Path, reviewed_at: str) -> Path:
    target = reference / "corpus" / "tax" / "L0001-1.md"
    target.write_text(f"---\nreviewed_at: {reviewed_at}\n---\n既有內容\n", encoding="utf-8")
    return target


def _run_build(reference: Path, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--reference", str(reference), *options],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        text=True,
    )


def test_existing_reviewed_at_is_preserved_without_argument(tmp_path: Path) -> None:
    reference = _reference_dir(tmp_path)
    target = _existing_document(reference, "2025-04-03")

    result = _run_build(reference)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "reviewed_at: 2025-04-03" in target.read_text(encoding="utf-8")


def test_explicit_reviewed_at_replaces_existing_date(tmp_path: Path) -> None:
    reference = _reference_dir(tmp_path)
    target = _existing_document(reference, "2025-04-03")

    result = _run_build(reference, "--reviewed-at", "2026-11-09")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "reviewed_at: 2026-11-09" in target.read_text(encoding="utf-8")


def test_new_article_without_review_date_writes_nothing(tmp_path: Path) -> None:
    reference = _reference_dir(tmp_path, include_new_article=True)
    existing = _existing_document(reference, "2025-04-03")
    original = existing.read_bytes()
    new_article = reference / "corpus" / "tax" / "L0001-2.md"

    result = _run_build(reference)

    assert result.returncode == 2
    assert "L0001:2" in result.stdout
    assert existing.read_bytes() == original
    assert not new_article.exists()


def test_invalid_reviewed_at_exits_two(tmp_path: Path) -> None:
    reference = _reference_dir(tmp_path)
    _existing_document(reference, "2025-04-03")

    result = _run_build(reference, "--reviewed-at", "2026-13-09")

    assert result.returncode == 2
    assert "YYYY-MM-DD" in result.stderr
