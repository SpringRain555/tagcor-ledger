"""確保標準庫稅務 CLI 的遞迴 import closure 不含第三方套件。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
SCRIPT = PROJECT_ROOT / "tools" / "tax_data" / "validate.py"
TAX_PREFIX = "tagcor_ledger.domain.tax"


def forbidden_imports(source: str, origin: str) -> tuple[list[str], list[str]]:
    tree = ast.parse(source, filename=origin)
    problems: list[str] = []
    tax_modules: list[str] = []

    def check(module: str, line: int) -> None:
        root = module.split(".", maxsplit=1)[0]
        if root in sys.stdlib_module_names:
            return
        if module == TAX_PREFIX or module.startswith(f"{TAX_PREFIX}."):
            tax_modules.append(module)
            return
        problems.append(f"{origin}:{line}: 不允許的 import {module}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                problems.append(f"{origin}:{node.lineno}: 不允許相對 import")
                continue
            module = node.module or ""
            check(module, node.lineno)
            if module == TAX_PREFIX:
                for alias in node.names:
                    tax_modules.append(f"{module}.{alias.name}")
    return problems, tax_modules


def module_path(module: str) -> Path | None:
    relative = Path(*module.split("."))
    module_file = SRC_DIR / relative.with_suffix(".py")
    package_file = SRC_DIR / relative / "__init__.py"
    if module_file.is_file():
        return module_file
    if package_file.is_file():
        return package_file
    return None


def test_validate_and_recursive_tax_imports_use_only_the_standard_library() -> None:
    pending = [SCRIPT]
    for package in ("tagcor_ledger", "tagcor_ledger.domain", TAX_PREFIX):
        initializer = module_path(package)
        if initializer is not None:
            pending.append(initializer)
    seen: set[Path] = set()
    problems: list[str] = []

    while pending:
        path = pending.pop()
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        found, imported = forbidden_imports(path.read_text(encoding="utf-8"), str(path))
        problems.extend(found)
        for module in imported:
            dependency = module_path(module)
            if dependency is not None:
                pending.append(dependency)

    assert not problems, "\n".join(problems)


def test_import_guard_positive_control_rejects_httpx() -> None:
    problems, _ = forbidden_imports("import httpx\n", "positive-control.py")

    assert problems == ["positive-control.py:1: 不允許的 import httpx"]
