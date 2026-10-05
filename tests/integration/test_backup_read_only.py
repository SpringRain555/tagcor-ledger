"""驗證、列出、還原都只**讀**備份：不取鎖、不留旁檔、內容與時間戳一個都不變。

以前是讀寫模式開，維護頁每次 refresh 都對每一份備份這樣開一次。備份正是
「最不該被碰到」的那份檔案 —— 讀它的連線不該有能力寫它。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tagcor_ledger.app.paths import resolve_app_paths
from tagcor_ledger.infrastructure.maintenance import MaintenanceService, _open_backup
from tagcor_ledger.infrastructure.sqlite_store import LedgerStore


@pytest.fixture
def maintenance(tmp_path: Path) -> MaintenanceService:
    paths = resolve_app_paths(tmp_path / "ledger")
    LedgerStore(paths)
    return MaintenanceService(paths)


def _snapshot(folder: Path) -> dict[str, tuple[bytes, int]]:
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.iterdir()}


def test_validating_and_listing_leave_the_backup_untouched(
    maintenance: MaintenanceService,
) -> None:
    """**這條在讀寫模式下其實也會過** —— 乾淨的 WAL 在最後一條連線關掉時會自己收乾淨。

    留著它是守「驗證不留下任何東西」這件事本身；真正區分唯讀與讀寫的是下面兩條
    （反向驗證過：改回讀寫模式，那兩條紅、這條綠）。
    """
    backup_dir = maintenance.create_backup(reason="test")
    before = _snapshot(backup_dir)
    assert set(before) == {"backup_manifest.json", "ledger.sqlite3"}

    for _ in range(3):
        assert maintenance.validate_backup(backup_dir)["valid"]
        assert len(maintenance.list_backups()) == 1

    # 沒有多出 -wal／-shm／-journal，內容與修改時間都沒動。
    assert _snapshot(backup_dir) == before


def test_the_backup_connection_cannot_write(maintenance: MaintenanceService) -> None:
    database_copy = maintenance.create_backup(reason="test") / "ledger.sqlite3"
    with _open_backup(database_copy) as connection:
        # 陽性對照：讀得到東西，這條連線不是開到一個空檔。
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] > 0
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM schema_migrations")


def test_a_stray_wal_next_to_the_backup_is_not_applied(maintenance: MaintenanceService) -> None:
    """**備份的定義就是那一個檔** —— manifest 的 SHA-256 只算它。

    旁邊躺著一個別處來的 `-wal`（例如手動連同 `-wal` 一起複製過來）時，讀寫模式會把它
    套用進來、讓內容跟雜湊對不上；immutable 不看它。
    """
    backup_dir = maintenance.create_backup(reason="test")
    stray = backup_dir / "ledger.sqlite3-wal"
    stray.write_bytes(b"garbage that is not a WAL file")

    assert maintenance.validate_backup(backup_dir)["valid"]
    assert stray.read_bytes() == b"garbage that is not a WAL file"
