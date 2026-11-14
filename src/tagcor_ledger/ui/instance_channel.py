"""TagCor Ledger 的叫醒管道設定與共用 Qt 啟動機制轉接層。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from local_qt_app.activation import (
    ACKNOWLEDGED,
    ACTIVATE_COMMAND,
    DEFAULT_TIMEOUT_MS,
    ActivationServer as _SharedActivationServer,
    bring_to_front,
    channel_name as _channel_name,
    request_activation as _request_activation,
)

from tagcor_ledger.app.logging_setup import get_logger


CHANNEL_PREFIX = "tagcor-ledger-"
__all__ = [
    "ACKNOWLEDGED",
    "ACTIVATE_COMMAND",
    "ActivationServer",
    "bring_to_front",
    "channel_name",
    "DEFAULT_TIMEOUT_MS",
    "request_activation",
]


def channel_name(ledger_dir: Path) -> str:
    """管道名稱依帳本資料夾區分，並保留舊版對 `~` 路徑的展開方式。"""
    return _channel_name(CHANNEL_PREFIX, ledger_dir.expanduser())


class ActivationServer:
    """在 TagCor Ledger 的管道上接收叫醒要求。"""

    def __init__(self, ledger_dir: Path, on_activate: Callable[[], None]) -> None:
        self._server = _SharedActivationServer(
            CHANNEL_PREFIX,
            ledger_dir.expanduser(),
            on_activate,
            logger=get_logger("instance"),
        )

    def start(self) -> bool:
        return self._server.start()

    def close(self) -> None:
        self._server.close()


def request_activation(
    ledger_dir: Path, *, timeout_ms: int = DEFAULT_TIMEOUT_MS
) -> bool:
    """叫醒同一份帳本的既有視窗；失敗交由啟動流程顯示原有訊息。"""
    return _request_activation(
        CHANNEL_PREFIX,
        ledger_dir.expanduser(),
        timeout_ms=timeout_ms,
        logger=get_logger("instance"),
    )
