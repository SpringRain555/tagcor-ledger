"""守門：程式裡的錯誤碼與 docs/architecture/error-codes.md 必須一致。

漂移是遲早的 —— 加一個錯誤碼很快，回頭補文件很容易忘。這個測試讓忘記變成紅燈。

用 AST 掃描而不是正則，因為正則會把註解、docstring 與測試資料裡的大寫字串一起抓進來。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "tagcor_ledger"
CATALOGUE = PROJECT_ROOT / "docs" / "architecture" / "error-codes.md"

# 錯誤碼長這樣：大寫開頭、只有大寫英數與底線、至少 4 個字元。
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")

# 產生錯誤碼的三種呼叫形式。
RAISING_CALLS = {"fail", "_error_code"}


def _string_code(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if CODE_PATTERN.match(node.value):
            return node.value
    return None


def codes_in_source() -> dict[str, set[str]]:
    """回傳 {錯誤碼: {出現的檔案}}。"""
    found: dict[str, set[str]] = {}
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = str(path.relative_to(SOURCE_ROOT)).replace("\\", "/")
        for node in ast.walk(tree):
            code: str | None = None
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                code = _string_code(node.exc.args[0])
            elif isinstance(node, ast.Call):
                function = node.func
                name = ""
                if isinstance(function, ast.Attribute):
                    name = function.attr
                elif isinstance(function, ast.Name):
                    name = function.id
                if name in RAISING_CALLS:
                    for argument in node.args:
                        code = _string_code(argument)
                        if code:
                            break
            if code:
                found.setdefault(code, set()).add(relative)
    return found


def codes_in_catalogue() -> set[str]:
    """目錄裡以反引號包起來的錯誤碼。"""
    text = CATALOGUE.read_text(encoding="utf-8")
    return {match for match in re.findall(r"`([A-Z][A-Z0-9_]{3,})`", text)}


def test_extractor_finds_a_plausible_number_of_codes() -> None:
    """陽性對照：抽取邏輯壞掉時先失敗，而不是讓比對靜默通過。"""
    source = codes_in_source()
    assert len(source) > 50, "抽取到的錯誤碼太少，AST 走訪可能壞了"
    assert "TRANSFER_SAME_ACCOUNT" in source
    assert "DATABASE_SCHEMA_TOO_NEW" in source
    assert "PATH_OUTSIDE_DATA_ROOT" in source


def test_every_source_code_is_documented() -> None:
    missing = sorted(set(codes_in_source()) - codes_in_catalogue())
    if missing:
        source = codes_in_source()
        lines = [f"  {code}  （出現在 {', '.join(sorted(source[code]))}）" for code in missing]
        pytest.fail(
            "以下錯誤碼在程式裡但不在 docs/architecture/error-codes.md：\n" + "\n".join(lines)
        )


def test_catalogue_has_no_phantom_codes() -> None:
    """目錄裡有、程式裡沒有 —— 代表功能移除了但文件忘了刪。"""
    documented = codes_in_catalogue()
    source = set(codes_in_source())
    phantom = sorted(documented - source)
    if phantom:
        pytest.fail(
            "以下錯誤碼在 docs/architecture/error-codes.md 但程式裡找不到，"
            "可能是功能已移除而文件未更新：\n" + "\n".join(f"  {code}" for code in phantom)
        )
