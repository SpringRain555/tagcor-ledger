"""External system path settings for ledger and backup locations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from platformdirs import user_config_dir, user_data_dir

from tagcor_ledger.domain.models import SystemPathSettings


APP_NAME = "TagCorLedger"
APP_AUTHOR = "TagCor"
SETTINGS_FILE_NAME = "system_paths.json"
SETTINGS_VERSION = 1


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
        raw_data_root = str(raw.get("data_root", "")).strip()
        return validate_path_settings(
            SystemPathSettings(
                ledger_dir=Path(str(raw.get("ledger_dir", ""))).expanduser(),
                backup_dir=Path(str(raw.get("backup_dir", ""))).expanduser(),
                data_root=Path(raw_data_root).expanduser() if raw_data_root else None,
            )
        )

    def save(self, settings: SystemPathSettings) -> SystemPathSettings:
        validated = validate_path_settings(settings, create=True)
        self.write(validated)
        return validated

    def write(self, validated: SystemPathSettings) -> None:
        """Persist already-validated settings atomically.

        Callers that also move data must finish moving it before calling this, so a
        failed move never leaves the pointer aimed at a location without a database.
        """
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "settings_version": SETTINGS_VERSION,
            "data_root": str(data_root_of(validated)),
            "ledger_dir": str(validated.ledger_dir),
            "backup_dir": str(validated.backup_dir),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=self.settings_path.parent,
            prefix=f".{SETTINGS_FILE_NAME}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, self.settings_path)


def default_settings_path() -> Path:
    return (
        Path(user_config_dir(APP_NAME, APP_AUTHOR)).expanduser().resolve()
        / SETTINGS_FILE_NAME
    )


def default_path_settings() -> SystemPathSettings:
    root = Path(user_data_dir(APP_NAME, APP_AUTHOR)).expanduser().resolve()
    return SystemPathSettings(
        ledger_dir=root / "data",
        backup_dir=root / "backups",
        data_root=root,
    )


def validate_path_settings(
    settings: SystemPathSettings,
    *,
    create: bool = False,
) -> SystemPathSettings:
    ledger_dir = settings.ledger_dir.expanduser().resolve()
    backup_dir = settings.backup_dir.expanduser().resolve()
    data_root = (
        settings.data_root.expanduser().resolve()
        if settings.data_root is not None
        else ledger_dir.parent
    )
    if ledger_dir == backup_dir:
        raise PathSettingsError("LEDGER_BACKUP_PATH_SAME")
    if _contains(ledger_dir, backup_dir) or _contains(backup_dir, ledger_dir):
        raise PathSettingsError("LEDGER_BACKUP_PATH_NESTED")
    if not _contains(data_root, ledger_dir) or not _contains(data_root, backup_dir):
        raise PathSettingsError("PATH_OUTSIDE_DATA_ROOT")
    if create:
        _ensure_writable_directory(ledger_dir)
        _ensure_writable_directory(backup_dir)
    return SystemPathSettings(
        ledger_dir=ledger_dir,
        backup_dir=backup_dir,
        data_root=data_root,
    )


def data_root_of(settings: SystemPathSettings) -> Path:
    """單一的資料根目錄；未明確設定時退回 `ledger_dir.parent`（舊設定檔）。"""
    return settings.data_root if settings.data_root is not None else settings.ledger_dir.parent


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
