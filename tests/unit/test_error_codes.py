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

# 產生錯誤碼的呼叫形式。`StartupFailure` 的第一個位置參數就是錯誤碼 ——
# 加新的攜帶型別到這裡時，記得它的錯誤碼必須用**位置參數**傳，否則掃不到。
RAISING_CALLS = {"fail", "_error_code", "StartupFailure"}

# 有些呼叫用關鍵字傳，例如 `SomeThing(error_code="X")`、
# `failure(exc, fallback_code="X", ...)`。這兩個名字都帶著意圖，不會誤抓到別的
# 字串，所以任何呼叫上出現它們都算數。
CODE_KEYWORDS = {"error_code", "fallback_code"}

# 模組層的錯誤碼對照表。它的 **key 就是錯誤碼**，而且是使用者真的會看到的那一組 ——
# 有些碼（例如 `DESTINATION_ACCOUNT_NOT_ACTIVE`）是被 `return` 出來再轉成例外的，
# 只掃 `raise` 抓不到，只有從這裡才看得見。
CODE_TABLES = {"ERROR_MESSAGES"}


def _code_table_keys(node: ast.AST) -> list[ast.expr]:
    """`ERROR_MESSAGES: dict[str, str] = {...}` 的 key 清單，不是這種賦值就回空。

    **`Assign` 與 `AnnAssign` 都要接。** 有型別註記的賦值是 `AnnAssign`，只寫
    `isinstance(node, ast.Assign)` 會靜靜地一個 key 都抓不到 —— 而抓不到的表現
    是測試通過，不是失敗，所以底下有一條陽性對照守著。
    """
    if isinstance(node, ast.AnnAssign):
        targets: list[ast.expr] = [node.target]
    elif isinstance(node, ast.Assign):
        targets = list(node.targets)
    else:
        return []
    if not isinstance(node.value, ast.Dict):
        return []
    if not any(isinstance(target, ast.Name) and target.id in CODE_TABLES for target in targets):
        return []
    return [key for key in node.value.keys if key is not None]


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
            table_keys = _code_table_keys(node)
            if table_keys:
                for key in table_keys:
                    table_code = _string_code(key)
                    if table_code:
                        found.setdefault(table_code, set()).add(relative)
                continue
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
                if code is None:
                    for keyword in node.keywords:
                        if keyword.arg in CODE_KEYWORDS:
                            code = _string_code(keyword.value)
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
    # 三個抽取路徑各抓一個：`raise`、`fallback_code=`、以及 `ERROR_MESSAGES` 的 key。
    # 最後這個只出現在對照表裡（`_occurrence_invalid_reason` 是 `return` 不是 `raise`），
    # 少了表格掃描就會漏掉它。
    assert "ACCOUNT_DELETE_FAILED" in source, "fallback_code= 這條路徑沒抓到"
    assert "DESTINATION_ACCOUNT_NOT_ACTIVE" in source, "ERROR_MESSAGES 的 key 沒抓到"
    assert "application/failures.py" in source["DESTINATION_ACCOUNT_NOT_ACTIVE"]


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
