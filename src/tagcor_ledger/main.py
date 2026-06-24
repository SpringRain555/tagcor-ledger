"""Command entry point for TagCor Ledger.

The command can either print startup information for smoke checks or launch the
Phase 2 PyQt MVP with ``--gui``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from tagcor_ledger import __version__
from tagcor_ledger.app.bootstrap import bootstrap
from tagcor_ledger.infrastructure.repositories import initialize_data_store


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
        help="Launch the PyQt desktop UI.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context = bootstrap(data_dir=args.data_dir, ensure_dirs=args.init_data)
    initialized_files = None
    if args.init_data:
        initialized_files = initialize_data_store(context.paths)
    if args.gui:
        initialize_data_store(context.paths)
        try:
            from tagcor_ledger.ui.app import run_gui
        except ModuleNotFoundError as exc:
            if exc.name == "PyQt6":
                print(
                    "PyQt6 is not installed. Create the conda environment from environment.yaml "
                    "or install the package with GUI dependencies.",
                    file=sys.stderr,
                )
                return 1
            raise

        return run_gui(context)

    payload = {
        "app": "TagCor Ledger",
        "version": __version__,
        "data_dir": str(context.paths.data_dir),
        "config_dir": str(context.paths.config_dir),
        "ledger_dir": str(context.paths.ledger_dir),
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
