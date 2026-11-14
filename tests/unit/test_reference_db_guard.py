"""預設路徑必須走 session 現建的法規庫，不能讀工作樹裡那個不進版控的產生物。

那個產生物本機有、CI 的乾淨 checkout 上沒有；讀到它的測試本機綠、CI 紅
（`docs/lessons.md` 2026-11-14）。這條**刻意不要求** `fake_reference_db` fixture：
要求它的話，autouse 被拿掉時它仍會被這條測試自己啟動，守門就量不到東西。
"""

from pathlib import Path

from tagcor_ledger.application.reference import ReferenceLibrary, default_reference_path


def test_default_reference_path_is_built_from_the_corpus() -> None:
    working_tree_artifact = (
        Path(__file__).resolve().parents[2] / "reference" / "reference.sqlite3"
    ).resolve()
    path = default_reference_path().resolve()
    assert path != working_tree_artifact, "測試讀到了工作樹裡的產生物；CI 上沒有它"

    library = ReferenceLibrary(path)
    assert library.status().success, "session 現建的法規庫不在"
    assert library.list_entries(keyword="存簿儲金"), "現建的法規庫查不到東西"
