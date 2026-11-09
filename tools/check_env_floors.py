"""檢查目前直譯器的套件版本是否達到安全地板。"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import sqlite3
import ssl
import sys
import tomllib
from pathlib import Path
from typing import Any

Version = tuple[int, ...]
CONFIG_PATH = Path(__file__).with_name("env_floors.json")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REBUILD_HINT = "重建環境，見 docs/environment/index.md §4"


def parse_version(value: str | tuple[int, ...] | list[int]) -> Version:
    """把版本字串或整數序列轉成可比較的整數 tuple。"""
    if isinstance(value, str):
        cleaned = value.strip()
        if not re.fullmatch(r"\d+(?:\.\d+)*", cleaned):
            raise ValueError(f"不是有效的版本字串：{value!r}")
        return tuple(int(part) for part in cleaned.split("."))
    if not value or any(not isinstance(part, int) or part < 0 for part in value):
        raise ValueError(f"不是有效的版本序列：{value!r}")
    return tuple(value)


def parse_openssl_version(value: str) -> Version:
    """從 ssl.OPENSSL_VERSION 文字擷取 OpenSSL 的完整版本。"""
    match = re.search(r"\bOpenSSL\s+(\d+(?:\.\d+)+)", value)
    if not match:
        raise ValueError(f"無法從 OpenSSL 版本文字解析版本：{value!r}")
    return parse_version(match.group(1))


def evaluate(
    actual: str | tuple[int, ...] | list[int] | None,
    minimum: str,
    max_exclusive: str | None = None,
) -> bool:
    """判斷實際版本是否達下界且未碰到選用的排他上界。"""
    if actual is None:
        return False
    try:
        current = parse_version(actual)
        lower = parse_version(minimum)
        upper = parse_version(max_exclusive) if max_exclusive is not None else None
    except ValueError:
        return False
    if current < lower:
        return False
    return upper is None or current[: len(upper)] < upper


def evaluate_metadata(actual: str | None, expected: str) -> bool:
    """metadata 版本必須與 pyproject.toml 的專案版本相同。"""
    return actual is not None and actual.strip() == expected.strip()


def _validate_config(config: Any) -> list[dict[str, Any]]:
    if not isinstance(config, dict) or not isinstance(config.get("_readme"), str):
        raise ValueError("頂層必須有字串 _readme 欄位")
    floors = config.get("floors")
    if not isinstance(floors, list) or not floors:
        raise ValueError("floors 必須是非空陣列")
    names: set[str] = set()
    valid_probes = {"python", "openssl", "expat", "sqlite", "qt", "pyside6"}
    for index, floor in enumerate(floors):
        if not isinstance(floor, dict):
            raise ValueError(f"floors[{index}] 必須是物件")
        for key in ("name", "probe", "min", "why"):
            if not isinstance(floor.get(key), str) or not floor[key].strip():
                raise ValueError(f"floors[{index}] 缺少有效的 {key}")
        declared_in = floor.get("declared_in")
        if not isinstance(declared_in, list) or not declared_in or any(
            not isinstance(path, str) or not path.strip() for path in declared_in
        ):
            raise ValueError(f"floors[{index}] 缺少有效的 declared_in")
        if floor["name"] in names:
            raise ValueError(f"重複的地板名稱：{floor['name']}")
        names.add(floor["name"])
        probe = floor["probe"]
        if probe not in valid_probes and not probe.startswith("dist:"):
            raise ValueError(f"不支援的 probe：{probe}")
        if probe.startswith("dist:") and not probe.removeprefix("dist:").strip():
            raise ValueError(f"無效的 distribution probe：{probe}")
        parse_version(floor["min"])
        if "max_exclusive" in floor:
            parse_version(floor["max_exclusive"])
    return floors


def _probe_version(probe: str) -> Version:
    if probe == "python":
        return parse_version(tuple(sys.version_info[:3]))
    if probe == "openssl":
        return parse_openssl_version(ssl.OPENSSL_VERSION)
    if probe == "expat":
        import pyexpat

        return parse_version(tuple(pyexpat.version_info))
    if probe == "sqlite":
        return parse_version(tuple(sqlite3.sqlite_version_info))
    if probe == "qt":
        from PySide6.QtCore import qVersion

        return parse_version(qVersion())
    if probe == "pyside6":
        import PySide6

        return parse_version(PySide6.__version__)
    if probe.startswith("dist:"):
        return parse_version(importlib.metadata.version(probe.removeprefix("dist:")))
    raise ValueError(f"不支援的 probe：{probe}")


def _display_version(value: Version | None) -> str:
    return ".".join(str(part) for part in value) if value is not None else "無法讀取"


def _floor_result(floor: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": floor["name"],
        "probe": floor["probe"],
        "min": floor["min"],
        "max_exclusive": floor.get("max_exclusive"),
        "why": floor["why"],
        "actual": None,
        "ok": False,
        "detail": "",
    }
    try:
        actual = _probe_version(floor["probe"])
    except importlib.metadata.PackageNotFoundError:
        result["detail"] = f"找不到套件 {floor['probe'].removeprefix('dist:')}"
        return result
    except (ImportError, ModuleNotFoundError):
        result["detail"] = "找不到 PySide6" if floor["probe"] in {"qt", "pyside6"} else "無法匯入套件"
        return result
    except (OSError, ValueError) as error:
        result["detail"] = str(error)
        return result
    result["actual"] = _display_version(actual)
    result["ok"] = evaluate(actual, floor["min"], floor.get("max_exclusive"))
    result["detail"] = "符合版本地板" if result["ok"] else "低於安全下界或碰到排他上界"
    return result


def _expected_project_version() -> str:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def _metadata_result(expected: str) -> dict[str, Any]:
    result: dict[str, Any] = {"actual": None, "expected": expected, "ok": False}
    try:
        actual = importlib.metadata.version("tagcor-ledger")
    except importlib.metadata.PackageNotFoundError:
        result["detail"] = "找不到 tagcor-ledger 的安裝 metadata"
        return result
    result["actual"] = actual
    result["ok"] = evaluate_metadata(actual, expected)
    result["detail"] = "metadata 與 pyproject.toml 一致" if result["ok"] else "metadata 版本不符"
    return result


def _load_config() -> list[dict[str, Any]]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return _validate_config(config)


def main() -> int:
    parser = argparse.ArgumentParser(description="檢查目前環境的安全版本地板")
    parser.add_argument("--json", action="store_true", help="輸出 JSON 結果")
    args = parser.parse_args()

    try:
        floors = _load_config()
        expected = _expected_project_version()
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        message = f"地板設定或專案版本格式錯誤：{error}"
        if args.json:
            print(json.dumps({"ok": False, "results": [], "metadata": {}, "error": message}, ensure_ascii=False))
        else:
            print(f"FAIL {message}")
        return 2

    results = [_floor_result(floor) for floor in floors]
    metadata = _metadata_result(expected)
    ok = all(result["ok"] for result in results) and metadata["ok"]
    report = {"ok": ok, "results": results, "metadata": metadata}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    for result in results:
        label = "PySide6" if result["name"] == "pyside6" else result["name"]
        status = "OK" if result["ok"] else "FAIL"
        actual = result["actual"] or result["detail"]
        bounds = f">={result['min']}"
        if result["max_exclusive"]:
            bounds += f"、<{result['max_exclusive']}"
        suffix = "" if result["ok"] else f"修法：{REBUILD_HINT}。"
        print(f"{status} {label}：目前 {actual}，要求 {bounds}。{suffix}")

    metadata_status = "OK" if metadata["ok"] else "FAIL"
    if metadata["ok"]:
        print(f"{metadata_status} metadata：{metadata['actual']} 與 pyproject.toml 一致。")
    else:
        print(
            f"{metadata_status} metadata：{metadata.get('actual') or metadata['detail']}，"
            f"pyproject.toml 要求 {expected}。請用環境的完整路徑執行 "
            'python -m pip install -e ".[dev]"。'
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
