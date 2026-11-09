"""驗證公開稅務資料、來源紀錄與資料新鮮度。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from tagcor_ledger.domain.tax.dataset_parse import parse_tax_dataset  # noqa: E402
from tagcor_ledger.domain.tax.dataset_validate import validate_tax_dataset  # noqa: E402
from tagcor_ledger.domain.tax.freshness import (  # noqa: E402
    DatasetLoad,
    DatasetLoadState,
    FRESHNESS_SENTENCES,
    FreshnessProblem,
    assess_freshness,
)


_REVIEWED_AT = re.compile(r"^\s*reviewed_at:\s*(\d{4}-\d{2}-\d{2})\s*$")
_RULE_LISTS = {"interest_withholding", "nhi_supplementary_premium"}


def _set_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("日期必須是合法的 YYYY-MM-DD。") from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("日期必須是 YYYY-MM-DD 格式。")
    return parsed


def _read_dataset(path: Path) -> tuple[object | None, DatasetLoadState | None, list[str]]:
    """讀 dataset.json。讀不到時回傳那個狀態（不在／壞掉）；讀得到時狀態是 None，由之後的驗證決定。

    狀態直接回傳，不從錯誤訊息裡找字 —— 訊息的措辭一改，靠字串判斷的狀態就會靜靜地錯。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, DatasetLoadState.MISSING, [f"dataset.json 不存在：{path}"]
    except (OSError, UnicodeError) as error:
        return None, DatasetLoadState.INVALID, [f"無法讀取 dataset.json：{error}"]

    if text.startswith("\ufeff"):
        return None, DatasetLoadState.INVALID, ["dataset.json 不得含 UTF-8 BOM。"]
    try:
        return json.loads(text), None, []
    except json.JSONDecodeError as error:
        return (
            None,
            DatasetLoadState.INVALID,
            [f"dataset.json 不是有效 JSON：第 {error.lineno} 行第 {error.colno} 欄。"],
        )


def _latest_manifest_records(path: Path, problems: list[str]) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    if not path.is_file():
        return latest
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        problems.append(f"無法讀取 manifest.jsonl：{error}")
        return latest

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"manifest.jsonl 第 {line_number} 行不是有效 JSON。")
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            problems.append(f"manifest.jsonl 第 {line_number} 行缺少網址欄位。")
            continue
        latest[entry["url"]] = entry
    return latest


def _check_manifest(
    raw: object,
    manifest_path: Path,
    problems: list[str],
) -> None:
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        return
    sources = [source for source in raw["sources"] if isinstance(source, dict)]
    if not sources:
        return

    if not manifest_path.is_file():
        for source in sources:
            problems.append(f"sources[{source.get('id', '?')}]：manifest.jsonl 不存在。")
        return

    latest = _latest_manifest_records(manifest_path, problems)
    for source in sources:
        source_id = source.get("id", "?")
        url = source.get("url")
        record = latest.get(url) if isinstance(url, str) else None
        if record is None:
            problems.append(f"sources[{source_id}]：manifest.jsonl 沒有這個網址的紀錄。")
            continue
        if type(record.get("status")) is not int or record.get("status") != 200:
            problems.append(f"sources[{source_id}]：manifest 最新狀態必須是 200。")
        if record.get("sha256") != source.get("sha256"):
            problems.append(f"sources[{source_id}]：manifest 最新 SHA-256 與 dataset 不同。")


def _oldest_law_reviewed_at(corpus: Path) -> date | None:
    dates: list[date] = []
    if not corpus.is_dir():
        return None
    for path in corpus.rglob("*.md"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        if not lines or lines[0].strip() != "---":
            continue
        for line in lines[1:]:
            if line.strip() == "---":
                break
            match = _REVIEWED_AT.fullmatch(line)
            if match is None:
                continue
            try:
                reviewed = date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if reviewed.isoformat() == match.group(1):
                dates.append(reviewed)
    return min(dates) if dates else None


def _freshness_message(problem: FreshnessProblem) -> str:
    return FRESHNESS_SENTENCES[problem.issue].format(
        years="、".join(str(year) for year in problem.years),
        due=problem.due_on.isoformat() if problem.due_on is not None else "",
    )


def _freshness_json(problem: FreshnessProblem) -> dict[str, object]:
    return {
        "issue": problem.issue.value,
        "years": list(problem.years),
        "due_on": problem.due_on.isoformat() if problem.due_on is not None else None,
        "details": list(problem.details),
    }


def _normalise_for_diff(value: object, path: tuple[str, ...] = ()) -> object:
    if isinstance(value, dict):
        return {str(key): _normalise_for_diff(child, (*path, str(key))) for key, child in value.items()}
    if isinstance(value, list):
        if path == ("sources",):
            key_name = "id"
        elif path and path[-1] in _RULE_LISTS:
            key_name = "effective_from"
        else:
            key_name = ""
        result: dict[str, object] = {}
        for index, child in enumerate(value):
            if key_name and isinstance(child, dict) and isinstance(child.get(key_name), str):
                key = f"[{child[key_name]}]"
            else:
                key = f"[{index}]"
            result[key] = _normalise_for_diff(child, (*path, key))
        return result
    return value


def _display_path(parent: str, child: str) -> str:
    if child.startswith("["):
        return f"{parent}{child}"
    return f"{parent}.{child}" if parent else child


def _display_value(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _diff(old: object, new: object) -> list[str]:
    differences: list[str] = []

    def visit(before: object, after: object, path: str = "") -> None:
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(before.keys() - after.keys()):
                differences.append(f"－ {_display_path(path, key)}（移除）")
            for key in sorted(after.keys() - before.keys()):
                differences.append(f"＋ {_display_path(path, key)}（新增）")
            for key in sorted(before.keys() & after.keys()):
                visit(before[key], after[key], _display_path(path, key))
            return
        if before != after:
            differences.append(f"{path}：{_display_value(before)} → {_display_value(after)}")

    visit(_normalise_for_diff(old), _normalise_for_diff(new))
    return differences


def _read_compare_file(path: Path) -> tuple[object | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
        if text.startswith("\ufeff"):
            return None, "比較檔含 UTF-8 BOM，無法產生差異摘要。"
        return json.loads(text), None
    except FileNotFoundError:
        return None, f"比較檔不存在：{path}。"
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, f"無法讀取比較檔 {path}：{error}。"


def _read_git_ref(reference: str) -> tuple[object | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "show", f"{reference}:reference/tax/dataset.json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        return None, f"無法執行 git 讀取比較版本 {reference}：{error}。"
    if result.returncode != 0:
        return None, f"無法從比較版本 {reference} 取得 reference/tax/dataset.json。"
    try:
        text = result.stdout.decode("utf-8")
        if text.startswith("\ufeff"):
            return None, f"比較版本 {reference} 的 dataset.json 含 UTF-8 BOM。"
        return json.loads(text), None
    except (UnicodeError, json.JSONDecodeError):
        return None, f"比較版本 {reference} 的 dataset.json 不是有效 UTF-8 JSON。"


def main(argv: list[str] | None = None) -> int:
    _set_utf8_output()
    parser = argparse.ArgumentParser(description="驗證公開稅務資料集與來源紀錄")
    parser.add_argument("--dataset", type=Path, default=PROJECT_ROOT / "reference/tax/dataset.json")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "reference/tax/manifest.jsonl")
    parser.add_argument("--corpus", type=Path, default=PROJECT_ROOT / "reference/corpus")
    parser.add_argument("--today", type=_parse_date, help="今天，格式 YYYY-MM-DD")
    parser.add_argument("--require-current", action="store_true", help="同時檢查資料新鮮度")
    compare = parser.add_mutually_exclusive_group()
    compare.add_argument("--compare-ref", help="與 git 版本的 dataset.json 比較")
    compare.add_argument("--compare-file", type=Path, help="與指定 JSON 檔比較")
    parser.add_argument("--json", action="store_true", help="輸出機器可讀 JSON")
    args = parser.parse_args(argv)

    raw, load_state, problems = _read_dataset(args.dataset)
    loaded = load_state is None
    parsed_dataset = None
    load_problem_details = [] if load_state is DatasetLoadState.MISSING else list(problems)
    if loaded:
        try:
            dataset_problems = validate_tax_dataset(raw)
        except (KeyError, TypeError, ValueError) as error:
            dataset_problems = [f"dataset.json 驗證失敗：{error}"]
        load_problem_details = list(dataset_problems)
        problems.extend(dataset_problems)
        if dataset_problems:
            load_state = DatasetLoadState.INVALID
        else:
            try:
                parsed_dataset = parse_tax_dataset(raw)
                load_state = DatasetLoadState.OK
            except (KeyError, TypeError, ValueError) as error:
                parse_problem = f"dataset.json 無法轉成稅務資料：{error}"
                problems.append(parse_problem)
                load_problem_details = [parse_problem]
                load_state = DatasetLoadState.INVALID

    if loaded:
        _check_manifest(raw, args.manifest, problems)

    freshness: list[dict[str, object]] = []
    if args.require_current:
        today = args.today or datetime.now(timezone(timedelta(hours=8))).date()
        if load_state is DatasetLoadState.OK and parsed_dataset is not None:
            load = DatasetLoad(DatasetLoadState.OK, dataset=parsed_dataset)
        elif load_state is DatasetLoadState.MISSING:
            load = DatasetLoad(DatasetLoadState.MISSING)
        else:
            load = DatasetLoad(DatasetLoadState.INVALID, problems=tuple(load_problem_details))
        freshness_problems = assess_freshness(
            today=today,
            load=load,
            law_oldest_reviewed_at=_oldest_law_reviewed_at(args.corpus),
        )
        freshness = [_freshness_json(item) for item in freshness_problems]
        problems.extend(_freshness_message(item) for item in freshness_problems)

    diff: list[str] = []
    compare_requested = args.compare_ref is not None or args.compare_file is not None
    if compare_requested:
        if args.compare_ref is not None:
            previous, compare_error = _read_git_ref(args.compare_ref)
        else:
            previous, compare_error = _read_compare_file(args.compare_file)
        if compare_error is not None:
            diff.append(compare_error)
        elif loaded:
            diff = _diff(previous, raw)
        else:
            diff.append("目前 dataset.json 無法讀取，沒有產生差異摘要。")

    ok = not problems
    if args.json:
        print(
            json.dumps(
                {
                    "dataset": str(args.dataset),
                    "ok": ok,
                    "problems": problems,
                    "freshness": freshness,
                    "diff": diff,
                },
                ensure_ascii=False,
            )
        )
    else:
        for problem in problems:
            print(problem)
        if compare_requested:
            if diff:
                for line in diff:
                    print(line)
            else:
                print("沒有差異。")
        print("通過。" if ok else f"有 {len(problems)} 個問題。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
