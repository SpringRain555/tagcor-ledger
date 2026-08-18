"""守門：文件裡的相對連結必須指向真的存在的檔案。

檔案改名或搬家時，指向它的連結不會自己跟著改。這種斷連結不會讓任何程式壞掉，
所以沒有守門就會一直累積，直到文件變得不能信任。

只檢查相對連結。外部 URL 不檢查 —— 那需要連網，而驗證流程必須能離線跑。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_DIRS = {".git", "__pycache__", "archive", ".venv"}
EXTERNAL_SCHEMES = {"http", "https", "mailto"}


def _markdown_files() -> list[Path]:
    return [
        path
        for path in sorted(PROJECT_ROOT.rglob("*.md"))
        if not any(part in SKIP_DIRS for part in path.relative_to(PROJECT_ROOT).parts)
    ]


def _relative_links(path: Path) -> list[str]:
    links: list[str] = []
    for target in LINK_PATTERN.findall(path.read_text(encoding="utf-8")):
        if urlparse(target).scheme in EXTERNAL_SCHEMES:
            continue
        file_part = target.split("#")[0]
        if file_part:
            links.append(target)
    return links


def test_scan_actually_covers_docs() -> None:
    """避免 SKIP_DIRS 寫錯導致什麼都沒檢查。"""
    files = _markdown_files()
    names = {path.name for path in files}
    assert "index.md" in names
    assert "AGENTS.md" in names
    assert sum(len(_relative_links(path)) for path in files) > 30


def test_every_relative_link_resolves() -> None:
    broken: list[str] = []
    for path in _markdown_files():
        for target in _relative_links(path):
            resolved = (path.parent / target.split("#")[0]).resolve()
            if not resolved.exists():
                broken.append(f"  {path.relative_to(PROJECT_ROOT)}  ->  {target}")
    if broken:
        pytest.fail("以下文件連結指向不存在的檔案：\n" + "\n".join(broken))
