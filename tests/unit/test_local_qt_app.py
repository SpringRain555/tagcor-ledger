"""Vendored local-qt-app wheel must be the one installed in this environment."""

from __future__ import annotations

import hashlib
import re
import sysconfig
import tomllib
from pathlib import Path

import local_qt_app
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = PROJECT_ROOT / "vendor"
WHEEL_PATTERN = re.compile(
    r"local_qt_app-(?P<version>\d+\.\d+\.\d+)-py3-none-any\.whl"
)
WHEEL_SHA256 = "A864727AE91CDBF68719153BC724ED0F615580A44A565CB067E6218699D2358E"


def _single_local_qt_wheel(vendor_dir: Path) -> tuple[Path, str]:
    wheels = sorted(vendor_dir.glob("local_qt_app-*.whl"))
    assert len(wheels) == 1, f"vendor/ 必須恰好有一個 local_qt_app wheel，找到 {len(wheels)} 個"
    match = WHEEL_PATTERN.fullmatch(wheels[0].name)
    assert match is not None, f"不支援的 local_qt_app wheel 檔名：{wheels[0].name}"
    return wheels[0], match.group("version")


def test_the_vendored_wheel_is_the_installed_package() -> None:
    wheel, version = _single_local_qt_wheel(VENDOR_DIR)
    environment = (PROJECT_ROOT / "environment.yaml").read_text(encoding="utf-8")
    references = re.findall(
        r"(?m)^\s*-\s+\./vendor/(local_qt_app-[^\s]+\.whl)\s*$", environment
    )
    assert references == [wheel.name]

    workflow = (PROJECT_ROOT / ".github" / "workflows" / "verify.yml").read_text(
        encoding="utf-8"
    )
    wheel_install = f"python -m pip install vendor/{wheel.name}"
    editable_install = 'python -m pip install -e ".[dev]"'
    assert wheel_install in workflow
    assert workflow.index(wheel_install) < workflow.index(editable_install)

    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    requirements = (
        pyproject["project"]["dependencies"]
        + pyproject["project"]["optional-dependencies"]["dev"]
        + pyproject["build-system"]["requires"]
    )
    assert not any("local-qt-app" in item.lower() for item in requirements)
    assert not any("local_qt_app" in item.lower() for item in requirements)
    assert "D:\\Projects\\_packages" not in environment + workflow
    assert "D:/Projects/_packages" not in environment + workflow

    assert local_qt_app.__version__ == version
    assert hashlib.sha256(wheel.read_bytes()).hexdigest().upper() == WHEEL_SHA256

    installed_file = Path(local_qt_app.__file__).resolve()
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    assert installed_file.is_relative_to(site_packages)
    shared_source = Path("D:/Projects/_packages/local-qt-app").resolve()
    assert not installed_file.is_relative_to(shared_source)


def test_wheel_count_guard_rejects_a_second_version(tmp_path: Path) -> None:
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / "local_qt_app-0.1.0-py3-none-any.whl").touch()
    (vendor_dir / "local_qt_app-0.0.9-py3-none-any.whl").touch()

    with pytest.raises(AssertionError, match="恰好有一個"):
        _single_local_qt_wheel(vendor_dir)
