"""稅務資料標準庫驗證器的子行程契約。"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "tools" / "tax_data" / "validate.py"
SAMPLE = PROJECT_ROOT / "tests" / "fixtures" / "tax" / "sample.json"


def _environment() -> dict[str, str]:
    return {**os.environ, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"}


def _write_manifest(path: Path, dataset: dict[str, Any], *, latest_status: int = 200) -> None:
    records = [
        {"url": source["url"], "status": 200, "sha256": source["sha256"]}
        for source in dataset["sources"]
    ]
    if records and latest_status != 200:
        earlier_records = tuple(records)
        records.extend(
            {"url": record["url"], "status": latest_status, "sha256": record["sha256"]}
            for record in earlier_records
        )
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _run_validate(
    dataset: Path,
    manifest: Path,
    *options: str,
    corpus: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--dataset",
        str(dataset),
        "--manifest",
        str(manifest),
        *options,
    ]
    if corpus is not None:
        command.extend(("--corpus", str(corpus)))
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=_environment(),
        text=True,
    )


def _copy_sample(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    dataset = json.loads(SAMPLE.read_text(encoding="utf-8"))
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.jsonl"
    _write_manifest(manifest_path, dataset)
    return dataset_path, manifest_path, dataset


def _write_skeleton(path: Path) -> None:
    skeleton = {
        "schema_version": 1,
        "reviewed_at": None,
        "next_review_on": None,
        "notes": ["尚未建立：照 docs/operations/tax-data-runbook.md 填入。"],
        "sources": [],
        "calendar": {"typical": {}, "years": {}},
        "income_tax": {},
        "basic_living_expense": {},
        "interest_withholding": [],
        "nhi_supplementary_premium": [],
    }
    path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_sample_dataset_and_matching_manifest_pass(tmp_path: Path) -> None:
    dataset, manifest, _ = _copy_sample(tmp_path)

    result = _run_validate(dataset, manifest)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "通過。"


def test_skeleton_dataset_passes_without_a_manifest(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    _write_skeleton(dataset)

    result = _run_validate(dataset, tmp_path / "missing-manifest.jsonl")

    assert result.returncode == 0, result.stdout + result.stderr


def test_checked_in_dataset_is_valid_as_skeleton_or_populated() -> None:
    from tagcor_ledger.domain.tax.dataset_validate import validate_tax_dataset

    dataset = json.loads((PROJECT_ROOT / "reference" / "tax" / "dataset.json").read_text(encoding="utf-8"))

    assert validate_tax_dataset(dataset) == []
    assert dataset["reviewed_at"] is None or isinstance(dataset["reviewed_at"], str)


def test_skeleton_require_current_reports_not_populated(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    _write_skeleton(dataset)

    result = _run_validate(
        dataset,
        tmp_path / "missing-manifest.jsonl",
        "--today",
        "2026-11-09",
        "--require-current",
    )

    assert result.returncode == 1
    assert "稅務資料還沒建立" in result.stdout


def test_manifest_hash_mismatch_is_a_problem(tmp_path: Path) -> None:
    dataset, manifest, raw = _copy_sample(tmp_path)
    _write_manifest(manifest, raw)
    entries = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    entries[0]["sha256"] = "0" * 64
    manifest.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )

    result = _run_validate(dataset, manifest)

    assert result.returncode == 1
    assert "SHA-256" in result.stdout


def test_latest_manifest_record_controls_status(tmp_path: Path) -> None:
    dataset, manifest, raw = _copy_sample(tmp_path)
    _write_manifest(manifest, raw, latest_status=404)

    result = _run_validate(dataset, manifest)

    assert result.returncode == 1
    assert "最新狀態必須是 200" in result.stdout


def test_missing_manifest_is_reported_for_each_source(tmp_path: Path) -> None:
    dataset, _, _ = _copy_sample(tmp_path)

    result = _run_validate(dataset, tmp_path / "absent.jsonl")

    assert result.returncode == 1
    assert result.stdout.count("manifest.jsonl 不存在") == 3


def test_missing_dataset_is_a_validation_problem(tmp_path: Path) -> None:
    result = _run_validate(tmp_path / "absent.json", tmp_path / "manifest.jsonl")

    assert result.returncode == 1
    assert "dataset.json 不存在" in result.stdout


def test_utf8_bom_is_rejected(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_bytes(b"\xef\xbb\xbf{}\n")

    result = _run_validate(dataset, tmp_path / "manifest.jsonl")

    assert result.returncode == 1
    assert "不得含 UTF-8 BOM" in result.stdout


def test_invalid_today_uses_argparse_exit_code_two(tmp_path: Path) -> None:
    result = _run_validate(
        tmp_path / "absent.json",
        tmp_path / "manifest.jsonl",
        "--today",
        "2026-13-01",
    )

    assert result.returncode == 2
    assert "YYYY-MM-DD" in result.stderr


def test_json_output_has_the_documented_shape(tmp_path: Path) -> None:
    dataset, manifest, _ = _copy_sample(tmp_path)

    result = _run_validate(dataset, manifest, "--json")

    report = json.loads(result.stdout)
    assert result.returncode == 0
    assert set(report) == {"dataset", "ok", "problems", "freshness", "diff"}
    assert report["dataset"] == str(dataset)
    assert report["ok"] is True
    assert report["problems"] == []
    assert report["freshness"] == []
    assert report["diff"] == []


def test_require_current_on_december_fifteenth_reports_year_2027(tmp_path: Path) -> None:
    dataset, manifest, _ = _copy_sample(tmp_path)

    result = _run_validate(
        dataset,
        manifest,
        "--today",
        "2026-12-15",
        "--require-current",
        "--json",
    )

    report = json.loads(result.stdout)
    assert result.returncode == 1
    missing = next(item for item in report["freshness"] if item["issue"] == "parameters_missing")
    assert missing["years"] == [2027]


def test_compare_file_uses_ids_years_and_effective_dates_as_keys(tmp_path: Path) -> None:
    dataset_path, manifest_path, current = _copy_sample(tmp_path)
    baseline = copy.deepcopy(current)
    baseline["income_tax"]["2025"]["exemption"]["value"] += 1
    unused_source = copy.deepcopy(baseline["sources"][0])
    unused_source["id"] = "unused-example"
    baseline["sources"].append(unused_source)

    current["income_tax"]["2027"] = copy.deepcopy(current["income_tax"]["2026"])
    new_rule = copy.deepcopy(current["interest_withholding"][0])
    new_rule["effective_from"] = "2009-01-01"
    current["interest_withholding"].insert(0, new_rule)
    dataset_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_manifest(manifest_path, current)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    result = _run_validate(
        dataset_path,
        manifest_path,
        "--compare-file",
        str(baseline_path),
        "--json",
    )

    report = json.loads(result.stdout)
    assert result.returncode == 0, result.stdout
    assert len(report["diff"]) == 4
    assert any("income_tax.2025.exemption.value：" in item for item in report["diff"])
    assert "＋ income_tax.2027（新增）" in report["diff"]
    assert "－ sources[unused-example]（移除）" in report["diff"]
    assert "＋ interest_withholding[2009-01-01]（新增）" in report["diff"]
