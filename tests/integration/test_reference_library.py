"""法規參考庫：唯讀、可缺席、能查中文。

三個最重要的性質：

1. **法規庫不存在時 App 照常運作。** 記帳不依賴它。
2. **唯讀開啟。** 它是產生物，任何寫入都是 bug，應該當場失敗。
3. **中文搜尋要找得到子字串。** 搜「儲蓄投資」必須命中「儲蓄投資特別扣除」。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tagcor_ledger.application.reference import (
    DISCLAIMER,
    ReferenceLibrary,
    characterize,
    is_stale,
    phrase_query,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_REFERENCE = PROJECT_ROOT / "reference" / "reference.sqlite3"


@pytest.fixture
def library() -> ReferenceLibrary:
    if not REAL_REFERENCE.exists():
        pytest.skip("尚未建立法規庫；跑 tools/law_sync/ 之後才有")
    return ReferenceLibrary(REAL_REFERENCE)


# --- 缺席時的行為 -----------------------------------------------------------


def test_missing_library_is_reported_not_raised(tmp_path: Path) -> None:
    """**沒有法規庫是正常狀態**，不是錯誤 —— 使用者可能永遠不跑抓取工具。"""
    missing = ReferenceLibrary(tmp_path / "nope.sqlite3")
    assert missing.available is False

    status = missing.status()
    assert not status.success
    assert status.error_code == "REFERENCE_LIBRARY_MISSING"
    # 訊息要講怎麼建立，不能只說「找不到」。
    assert "tools/law_sync" in str(status.details["how"])

    # 查詢一律回空，不丟例外。
    assert missing.topics() == []
    assert missing.list_entries() == []
    assert missing.list_entries(keyword="贈與") == []


def test_corrupt_library_is_reported(tmp_path: Path) -> None:
    broken = tmp_path / "broken.sqlite3"
    broken.write_text("這不是資料庫", encoding="utf-8")
    status = ReferenceLibrary(broken).status()
    assert not status.success
    assert status.error_code == "REFERENCE_LIBRARY_UNREADABLE"


# --- 唯讀 -------------------------------------------------------------------


def test_library_is_opened_read_only(library: ReferenceLibrary) -> None:
    """寫入必須失敗。這是**檔案層級**的保證，不是「我們小心不要寫」。"""
    connection = library._connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM reference_entries")
    finally:
        connection.close()


def test_read_only_open_creates_no_side_files(library: ReferenceLibrary) -> None:
    """唯讀開啟不該產生 -wal／-shm，資料夾要維持乾淨。"""
    connection = library._connect()
    try:
        connection.execute("SELECT COUNT(*) FROM reference_entries").fetchone()
    finally:
        connection.close()
    assert not REAL_REFERENCE.with_suffix(".sqlite3-wal").exists()
    assert not REAL_REFERENCE.with_suffix(".sqlite3-shm").exists()


# --- 內容與出處 -------------------------------------------------------------


def test_every_entry_carries_its_provenance(library: ReferenceLibrary) -> None:
    """**沒有出處的法規條目沒有用** —— 查到之後要能回頭驗證。"""
    entries = library.list_entries()
    assert entries, "法規庫是空的"
    for entry in entries:
        assert entry.source_url.startswith("https://law.moj.gov.tw/"), entry.entry_id
        assert entry.amended_date, entry.entry_id
        assert entry.fetched_at, entry.entry_id
        assert entry.reviewed_at, entry.entry_id
        assert entry.body, entry.entry_id
        assert entry.plain, entry.entry_id


def test_status_carries_the_disclaimer(library: ReferenceLibrary) -> None:
    status = library.status()
    assert status.success
    assert status.details["disclaimer"] == DISCLAIMER
    assert "不是稅務或法律意見" in DISCLAIMER


def test_topics_cover_the_four_planned_areas(library: ReferenceLibrary) -> None:
    titles = {str(item["title"]) for item in library.topics()}
    assert titles == {"綜合所得稅", "郵政儲金與存款", "電子票證與電子支付", "勞健保與贈與稅"}


# --- 中文搜尋 ---------------------------------------------------------------


def test_characterize_matches_the_builder() -> None:
    """App 與建置腳本的轉換必須一致，差一點片語就對不上。"""
    assert characterize("儲蓄投資") == "儲 蓄 投 資"
    assert characterize("存簿\n儲金") == "存 簿 儲 金"
    assert phrase_query("贈與") == '"贈 與"'
    assert phrase_query("   ") == ""


@pytest.mark.parametrize(
    ("keyword", "expected_law"),
    [
        ("存簿儲金", "郵政儲金匯兌法"),
        ("儲蓄投資", "所得稅法"),
        ("贈與稅免稅額", "遺產及贈與稅法"),
        ("補充保險費", "全民健康保險法"),
        ("儲值卡", "電子支付機構管理條例"),
    ],
)
def test_substring_search_finds_chinese_terms(
    library: ReferenceLibrary, keyword: str, expected_law: str
) -> None:
    """中文沒有空白分詞，**子字串搜尋是這裡唯一有用的語意**。"""
    laws = {entry.law_name for entry in library.list_entries(keyword=keyword)}
    assert any(expected_law in name for name in laws), f"搜「{keyword}」找不到 {expected_law}"


def test_search_can_be_combined_with_topic(library: ReferenceLibrary) -> None:
    entries = library.list_entries(topic="postal-savings", keyword="利息")
    assert entries
    assert all(entry.topic == "postal-savings" for entry in entries)


def test_bad_search_input_returns_empty_not_an_exception(library: ReferenceLibrary) -> None:
    assert library.list_entries(keyword='"""') == []


# --- 複查提示 ---------------------------------------------------------------


def test_staleness_is_six_months() -> None:
    from datetime import date

    today = date(2026, 8, 18)
    assert is_stale("2026-08-01", today=today) is False
    assert is_stale("2026-03-01", today=today) is False  # 差 5 個月
    assert is_stale("2026-02-01", today=today) is True  # 差 6 個月
    assert is_stale("不是日期", today=today) is True, "看不懂的日期一律當成該複查"


# --- App 不連網 -------------------------------------------------------------


def test_app_package_never_imports_a_network_library() -> None:
    """抓取工具在 `tools/`，**不在 `src/`**。App 永遠不發網路請求。"""
    import ast

    forbidden = {"httpx", "requests", "urllib3", "aiohttp", "socket", "http"}
    offenders: list[str] = []
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in forbidden:
                    offenders.append(f"  {path.relative_to(PROJECT_ROOT)} -> {name}")
    assert not offenders, "App 不得依賴任何網路函式庫：\n" + "\n".join(offenders)


def test_law_sync_tools_run_without_the_app_environment() -> None:
    """`tools/law_sync/` 的兩支建置腳本只用標準庫，專案環境跑得起來。

    子行程的編碼要兩邊都釘死成 UTF-8。原本只寫 `text=True`，於是子行程用 cp950 寫、
    父行程用 cp950 讀，說明文字裡的中文一撞上就在 reader thread 丟 `UnicodeDecodeError` ——
    **測試照樣通過**（returncode 另外拿），只是 `result.stderr` 變成空的，
    真的失敗時錯誤訊息會什麼都看不到。
    """
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for script in ("build_corpus.py", "build_reference_db.py"):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "law_sync" / script), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        assert result.returncode == 0, f"{script}: {result.stderr}"
        # 陽性對照：真的讀到了說明文字，而不是拿到一段被吞掉的空字串。
        assert "--help" in result.stdout, f"{script} 的說明沒有讀回來：{result.stdout!r}"
