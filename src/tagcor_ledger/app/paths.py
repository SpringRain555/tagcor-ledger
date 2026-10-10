"""解析使用者資料與打包資源的位置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from tagcor_ledger.app.data_location import DataLocation, LocationSource, detect_data_location
from tagcor_ledger.app.path_settings import data_root_of, default_settings_path
from tagcor_ledger.domain.models import SystemPathSettings


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

    @property
    def database_path(self) -> Path:
        return self.ledger_dir / "ledger.sqlite3"

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
    return Path(user_data_dir(APP_NAME, APP_AUTHOR)).expanduser().resolve()


def paths_for(settings: SystemPathSettings, *, config_dir: Path) -> AppPaths:
    """一份路徑設定加上設定目錄，組成程式要用的全部位置。

    `exports`／`logs`／`tmp` 由 `data_root` 推導（`docs/architecture/storage-layout.md`）。
    「系統設定 → 資料路徑」換位置時也用這一份，不另外拼。
    """
    root = data_root_of(settings)
    return AppPaths(
        data_dir=root,
        config_dir=config_dir,
        ledger_dir=settings.ledger_dir,
        backup_dir=settings.backup_dir,
        export_dir=root / "exports",
        log_dir=root / "logs",
        tmp_dir=root / "tmp",
    )


def paths_for_location(location: DataLocation) -> AppPaths:
    """`app/data_location.py` 決定好的位置。設定目錄固定是指標檔所在的那一個。"""
    return paths_for(location.settings, config_dir=default_settings_path().parent)


def resolve_location(data_dir: str | Path | None = None) -> tuple[AppPaths, LocationSource]:
    """這一次的路徑，以及它是怎麼決定的。

    給了 `data_dir` 或設了 `TAGCOR_LEDGER_DATA_DIR` 就是開發用的覆寫，**不讀指標檔、不問**；
    否則照 `detect_data_location()` 的四步。
    """
    env_value = os.environ.get(DATA_DIR_ENV)
    if data_dir is None and not env_value:
        location = detect_data_location()
        return paths_for_location(location), location.source
    root = Path(data_dir).expanduser().resolve() if data_dir is not None else default_data_dir()
    return (
        AppPaths(
            data_dir=root,
            config_dir=root / "config",
            ledger_dir=root / "data",
            backup_dir=root / "backups",
            export_dir=root / "exports",
            log_dir=root / "logs",
            tmp_dir=root / "tmp",
        ),
        LocationSource.OVERRIDE,
    )


def resolve_app_paths(data_dir: str | Path | None = None) -> AppPaths:
    return resolve_location(data_dir)[0]


def ensure_directories(paths: AppPaths) -> None:
    for path in paths.as_dict().values():
        Path(path).mkdir(parents=True, exist_ok=True)
