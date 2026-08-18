"""Command entry point for TagCor Ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from tagcor_ledger import __version__
from tagcor_ledger.app.bootstrap import bootstrap
from tagcor_ledger.app.logging_setup import configure_logging, current_log_path, get_logger
from tagcor_ledger.app.single_instance import SingleInstanceGuard
from tagcor_ledger.app.startup import classify_startup_error, resolve_log_dir
from tagcor_ledger.infrastructure.database import initialize_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tagcor-ledger")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override the user data directory for this run.",
    )
    parser.add_argument(
        "--init-data",
        action="store_true",
        help="Create the user data directory structure if it does not exist.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print startup information as JSON.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the PySide6 desktop UI.",
    )
    return parser


def main_gui(argv: Sequence[str] | None = None) -> int:
    """`gui-scripts` 與 Windows 捷徑的進入點：預設就是開視窗。

    不能讓 `gui-scripts` 直接指向 `main` —— `gui-scripts` 產生的 exe 是用 pythonw 建的、
    **沒有主控台**，而 `main()` 少了 `--gui` 只會把資訊印到不存在的 stdout 然後結束。
    使用者雙擊看到的是「什麼都沒發生」。
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--gui" not in arguments:
        arguments.append("--gui")
    return main(arguments)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 這裡是最外層，接不到就等於無聲死掉
        return _report_startup_failure(exc, gui=bool(args.gui))


def _run(args: argparse.Namespace) -> int:
    """實際的啟動流程。**任何一步失敗都由 `main` 翻成使用者看得懂的說明。**"""
    context = bootstrap(data_dir=args.data_dir, ensure_dirs=args.init_data)
    configure_logging(context.paths.log_dir)
    logger = get_logger("startup")
    logger.info("startup version=%s gui=%s", __version__, bool(args.gui))

    initialized_files: dict[str, Path] | None = None
    if args.init_data:
        initialized_files = {"database": initialize_database(context.paths)}
    if args.gui:
        # 單一實例守門要在開資料庫之前 —— 拿不到鎖就不要再去動別人正在用的檔案。
        guard = SingleInstanceGuard(context.paths.ledger_dir)
        guard.acquire()
        try:
            initialize_database(context.paths)
            try:
                from tagcor_ledger.ui.app import run_gui
            except ModuleNotFoundError as exc:
                if exc.name == "PySide6":
                    print(
                        "PySide6 is not installed. Create the conda environment from "
                        "environment.yaml or install the package with GUI dependencies.",
                        file=sys.stderr,
                    )
                    return 1
                raise
            return run_gui(context)
        finally:
            guard.release()

    payload = {
        "app": "TagCor Ledger",
        "version": __version__,
        "data_dir": str(context.paths.data_dir),
        "config_dir": str(context.paths.config_dir),
        "ledger_dir": str(context.paths.ledger_dir),
        "database_path": str(context.paths.database_path),
        "backup_dir": str(context.paths.backup_dir),
        "export_dir": str(context.paths.export_dir),
        "log_dir": str(context.paths.log_dir),
        "tmp_dir": str(context.paths.tmp_dir),
        "styles_available": context.styles_available,
        "initialized_files": (
            {key: str(value) for key, value in initialized_files.items()}
            if initialized_files is not None
            else None
        ),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"{payload['app']} {payload['version']}")
    print(f"Data directory: {payload['data_dir']}")
    print(f"Config directory: {payload['config_dir']}")
    print(f"Ledger directory: {payload['ledger_dir']}")
    print(f"Resources ready: {payload['styles_available']}")
    if initialized_files is not None:
        print("Data store initialized.")
    return 0


def _report_startup_failure(exc: BaseException, *, gui: bool) -> int:
    """寫日誌 → 顯示繁中說明 → 回傳非零。**絕不無聲離開。**

    日誌位置刻意用 `resolve_log_dir(None)`：啟動失敗時 `AppPaths` 常常正是解析不出來的
    那個東西，硬要用它只會在寫日誌時再失敗一次。
    """
    failure = classify_startup_error(exc)

    try:
        configure_logging(resolve_log_dir(None))
        get_logger("startup").error(
            "startup failed code=%s type=%s",
            failure.error_code,
            type(exc).__name__,
            exc_info=exc,
        )
        log_path = current_log_path()
    except Exception:  # noqa: BLE001 —— 記不了日誌不該蓋掉原本的錯誤
        log_path = None

    body = failure.as_text()
    if log_path is not None:
        body += f"\n\n日誌：{log_path}"

    if gui and _show_startup_dialog(failure.title, body):
        return 1
    print(body, file=sys.stderr)
    return 1


def _show_startup_dialog(title: str, body: str) -> bool:
    """用 Qt 對話框顯示；Qt 起不來就回傳 False 讓呼叫端退回 stderr。

    連 import 都包在 try 裡 —— Qt 起不來正是可能的失敗原因之一。
    """
    try:
        from tagcor_ledger.ui.startup_dialog import show_startup_failure

        show_startup_failure(title, body)
        return True
    except Exception:  # noqa: BLE001
        return False
