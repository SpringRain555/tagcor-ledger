"""Path resolution for user data and packaged resources."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from platformdirs import user_data_dir
except ImportError:  # pragma: no cover - dependency is declared, fallback helps early dev shells.
    user_data_dir = None


APP_NAME = "TagCorLedger"
APP_AUTHOR = "TagCor"
DATA_DIR_ENV = "TAGCOR_LEDGER_DATA_DIR"


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    config_dir: Path
    ledger_dir: Path
    backup_dir: Path
    export_dir: Path
    log_dir: Path
    tmp_dir: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "data_dir": str(self.data_dir),
            "config_dir": str(self.config_dir),
            "ledger_dir": str(self.ledger_dir),
            "backup_dir": str(self.backup_dir),
            "export_dir": str(self.export_dir),
            "log_dir": str(self.log_dir),
            "tmp_dir": str(self.tmp_dir),
        }


def default_data_dir() -> Path:
    env_value = os.environ.get(DATA_DIR_ENV)
    if env_value:
        return Path(env_value).expanduser().resolve()
    if user_data_dir is not None:
        return Path(user_data_dir(APP_NAME, APP_AUTHOR)).expanduser().resolve()
    return (Path.home() / APP_NAME).resolve()


def resolve_app_paths(data_dir: str | Path | None = None) -> AppPaths:
    root = Path(data_dir).expanduser().resolve() if data_dir is not None else default_data_dir()
    return AppPaths(
        data_dir=root,
        config_dir=root / "config",
        ledger_dir=root / "data",
        backup_dir=root / "backups",
        export_dir=root / "exports",
        log_dir=root / "logs",
        tmp_dir=root / "tmp",
    )


def ensure_directories(paths: AppPaths) -> None:
    for path in paths.as_dict().values():
        Path(path).mkdir(parents=True, exist_ok=True)
