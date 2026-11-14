"""環境安全地板檢查器：設定與宣告需同步，純函式不依賴本機環境。"""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLOOR_PATH = PROJECT_ROOT / "tools" / "env_floors.json"
CHECKER_PATH = PROJECT_ROOT / "tools" / "check_env_floors.py"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_env_floors", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _floor_map() -> dict[str, dict[str, object]]:
    config = json.loads(FLOOR_PATH.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in config["floors"]}


def _environment_specs() -> dict[str, str]:
    pattern = re.compile(r'^\s*-\s*"?([A-Za-z0-9_.-]+)(.*?)"?\s*$')
    specs: dict[str, str] = {}
    for line in (PROJECT_ROOT / "environment.yaml").read_text(encoding="utf-8").splitlines():
        indentation = len(line) - len(line.lstrip())
        if indentation != 2 or line.strip() == "- pip:":
            continue
        match = pattern.match(line)
        if match:
            specs[match.group(1)] = match.group(2)
    return specs


def _declared_requirement(name: str, floor: dict[str, object]) -> str:
    requirement = f">={floor['min']}"
    maximum = floor.get("max_exclusive")
    if maximum:
        requirement += f",<{maximum}"
    return requirement


def test_floor_file_has_required_fields_and_reasons() -> None:
    config = json.loads(FLOOR_PATH.read_text(encoding="utf-8"))
    assert isinstance(config.get("_readme"), str)
    assert all(text in config["_readme"] for text in ("environment.yaml", "pyproject.toml", "verify.yml"))
    for floor in config["floors"]:
        assert all(key in floor for key in ("name", "probe", "min", "why"))
        assert isinstance(floor.get("declared_in"), list) and floor["declared_in"]
        assert floor["why"].strip()
        assert re.search(r"[\u4e00-\u9fff]", floor["why"])
        assert "CVE" in floor["why"]


def test_declared_floors_match_conda_pyproject_and_ci() -> None:
    floors = _floor_map()
    environment = _environment_specs()
    conda_names = (
        "python",
        "openssl",
        "libexpat",
        "libsqlite",
        "pyside6",
        "pip",
        "setuptools",
        "filelock",
    )
    for name in conda_names:
        assert environment.get(name) == _declared_requirement(name, floors[name])

    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    filelock = next(item for item in dependencies if item.startswith("filelock"))
    setuptools = pyproject["build-system"]["requires"]
    assert filelock == f"filelock{_declared_requirement('filelock', floors['filelock'])}"
    assert setuptools == [f"setuptools{_declared_requirement('setuptools', floors['setuptools'])}"]
    all_python_dependencies = dependencies + pyproject["project"]["optional-dependencies"]["dev"]
    assert not any(item.lower().startswith("pyside6") for item in all_python_dependencies)

    workflow = (PROJECT_ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    pyside_floor = floors["pyside6"]["min"]
    assert f'python -m pip install "PySide6=={pyside_floor}"' in workflow


def test_workflow_actions_are_pinned_to_full_commit_shas() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "verify.yml").read_text(
        encoding="utf-8"
    )
    uses_lines = re.findall(r"^\s*-\s+uses:\s*(.+)$", workflow, flags=re.MULTILINE)
    assert uses_lines
    for line in uses_lines:
        assert re.search(r"@[0-9a-fA-F]{40}\s+# v\d+\.\d+\.\d+\s*$", line), line


def test_verify_has_version_floor_step_and_utf8_bom() -> None:
    verify_path = PROJECT_ROOT / "tools" / "Verify.ps1"
    raw = verify_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "版本地板" in raw.decode("utf-8-sig")
    assert "check_env_floors.py" in raw.decode("utf-8-sig")


def test_version_floor_evaluation_at_and_around_minimum() -> None:
    checker = _load_checker()
    assert not checker.evaluate("3.12.15", "3.12.16")
    assert checker.evaluate("3.12.16", "3.12.16")
    assert checker.evaluate("3.12.17", "3.12.16")


def test_exclusive_maximum_compares_only_its_version_parts() -> None:
    checker = _load_checker()
    assert checker.evaluate("3.5.99", "3.5.0", "3.6")
    assert not checker.evaluate("3.6.0", "3.5.0", "3.6")
    assert not checker.evaluate("3.6.9", "3.5.0", "3.6")


def test_openssl_version_text_parses_patch_component() -> None:
    checker = _load_checker()
    assert checker.parse_openssl_version("OpenSSL 3.6.5 29 Sep 2026") == (3, 6, 5)


def test_version_parser_strips_trailing_whitespace() -> None:
    checker = _load_checker()
    assert checker.parse_version("6.11.3 ") == (6, 11, 3)


def test_metadata_version_mismatch_fails() -> None:
    checker = _load_checker()
    assert checker.evaluate_metadata("0.27.0", "0.27.0")
    assert not checker.evaluate_metadata("0.24.1", "0.27.0")
