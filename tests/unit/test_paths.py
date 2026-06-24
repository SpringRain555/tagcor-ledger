from pathlib import Path

from tagcor_ledger.app.paths import ensure_directories, resolve_app_paths


def test_resolve_app_paths_uses_explicit_data_dir(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")

    assert paths.data_dir == (tmp_path / "ledger-data").resolve()
    assert paths.config_dir == paths.data_dir / "config"
    assert paths.ledger_dir == paths.data_dir / "data"
    assert paths.backup_dir == paths.data_dir / "backups"
    assert paths.export_dir == paths.data_dir / "exports"
    assert paths.log_dir == paths.data_dir / "logs"
    assert paths.tmp_dir == paths.data_dir / "tmp"


def test_ensure_directories_creates_phase_zero_directories(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path / "ledger-data")

    ensure_directories(paths)

    assert paths.config_dir.is_dir()
    assert paths.ledger_dir.is_dir()
    assert paths.backup_dir.is_dir()
    assert paths.export_dir.is_dir()
    assert paths.log_dir.is_dir()
    assert paths.tmp_dir.is_dir()
