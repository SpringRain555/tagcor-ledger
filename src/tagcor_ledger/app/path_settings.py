"""External system path settings for ledger and backup locations."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from platformdirs import user_config_dir, user_data_dir

from tagcor_ledger.domain.models import SystemPathSettings


APP_NAME = "TagCorLedger"
APP_AUTHOR = "TagCor"
SETTINGS_FILE_NAME = "system_paths.json"


class PathSettingsError(ValueError):
    """Raised when ledger and backup paths are unsafe or not writable."""


class PathSettingsService:
    """Read and write path settings that cannot live inside the ledger database."""

    def __init__(self, settings_path: Path | None = None) -> None:
        self.settings_path = settings_path or default_settings_path()

    def load(self) -> SystemPathSettings:
        if not self.settings_path.is_file():
            return default_path_settings()
        try:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PathSettingsError("SYSTEM_PATH_SETTINGS_INVALID") from exc
        return validate_path_settings(
            SystemPathSettings(
                ledger_dir=Path(str(raw.get("ledger_dir", ""))).expanduser(),
                backup_dir=Path(str(raw.get("backup_dir", ""))).expanduser(),
            )
        )

    def save(self, settings: SystemPathSettings) -> SystemPathSettings:
        validated = validate_path_settings(settings, create=True)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ledger_dir": str(validated.ledger_dir),
            "backup_dir": str(validated.backup_dir),
        }
        self.settings_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return validated


def default_settings_path() -> Path:
    return (
        Path(user_config_dir(APP_NAME, APP_AUTHOR)).expanduser().resolve()
        / SETTINGS_FILE_NAME
    )


def default_path_settings() -> SystemPathSettings:
    root = Path(user_data_dir(APP_NAME, APP_AUTHOR)).expanduser().resolve()
    return SystemPathSettings(ledger_dir=root / "data", backup_dir=root / "backups")


def validate_path_settings(
    settings: SystemPathSettings,
    *,
    create: bool = False,
) -> SystemPathSettings:
    ledger_dir = settings.ledger_dir.expanduser().resolve()
    backup_dir = settings.backup_dir.expanduser().resolve()
    if ledger_dir == backup_dir:
        raise PathSettingsError("LEDGER_BACKUP_PATH_SAME")
    if _contains(ledger_dir, backup_dir) or _contains(backup_dir, ledger_dir):
        raise PathSettingsError("LEDGER_BACKUP_PATH_NESTED")
    if create:
        _ensure_writable_directory(ledger_dir)
        _ensure_writable_directory(backup_dir)
    return SystemPathSettings(ledger_dir=ledger_dir, backup_dir=backup_dir)


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _ensure_writable_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(prefix=".tagcor_write_check_", dir=path, delete=True):
            pass
    except OSError as exc:
        raise PathSettingsError("SYSTEM_PATH_NOT_WRITABLE") from exc
