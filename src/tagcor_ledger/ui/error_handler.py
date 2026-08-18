"""程式跑起來之後的未攔截例外處理。

沒有這一層時，Qt slot 裡丟出的例外會讓程式直接消失 —— 使用者按下一顆按鈕，視窗就沒了，
沒有訊息也沒有紀錄。記到一半的那筆帳當然也不見了。

這裡的原則是：**能繼續就繼續。** 一顆按鈕的 handler 壞掉不代表整個程式不能用；
顯示訊息、寫日誌，然後讓使用者自己決定要不要關掉。

給的 `correlation_id` 是為了讓畫面上看到的那串字，能在日誌裡搜得到同一次事故。
"""

from __future__ import annotations

import sys
import traceback
from types import TracebackType

from PySide6.QtWidgets import QMessageBox

from tagcor_ledger.app.logging_setup import current_log_path, get_logger
from tagcor_ledger.application.result import new_correlation_id


def install_exception_handler() -> None:
    """接管 `sys.excepthook`。PySide6 的 slot 例外也會走到這裡。"""
    sys.excepthook = _handle


def _handle(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    # Ctrl+C 交回預設行為 —— 使用者主動中止不是「錯誤」。
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return

    correlation_id = new_correlation_id()
    try:
        get_logger("crash").error(
            "unhandled corr=%s type=%s",
            correlation_id,
            exc_type.__name__,
            exc_info=(exc_type, exc, tb),
        )
    except Exception:  # noqa: BLE001 —— 記不了日誌不該再引發第二次崩潰
        traceback.print_exception(exc_type, exc, tb)

    try:
        _show(exc_type, exc, correlation_id)
    except Exception:  # noqa: BLE001 —— 連對話框都開不起來就只能退回 stderr
        traceback.print_exception(exc_type, exc, tb)


def _show(exc_type: type[BaseException], exc: BaseException, correlation_id: str) -> None:
    log_path = current_log_path()
    body = (
        "剛才的操作沒有完成，但程式還可以繼續使用。\n"
        "如果同樣的操作一直失敗，請關閉程式後再開一次；"
        "資料不會因為這個訊息而遺失。"
    )
    detail = f"{exc_type.__name__}: {exc}\n\n識別碼：{correlation_id}"
    if log_path is not None:
        detail += f"\n日誌：{log_path}"

    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("發生未預期的錯誤")
    box.setText(body)
    box.setInformativeText(detail)
    box.setStandardButtons(QMessageBox.StandardButton.Close)
    close_button = box.button(QMessageBox.StandardButton.Close)
    if close_button is not None:
        close_button.setText("繼續使用")
    box.exec()
