"""程式跑起來之後的未攔截例外：**最後一道防線本身不能倒。**

## 為什麼這一份特別重要

2026-08-22 的覆蓋率掃描顯示 `ui/error_handler.py` **47 行一行都沒被執行過**。
它是「Qt slot 裡丟出例外時，使用者看到一句中文而不是視窗直接消失」的那一層 ——
換句話說，**它只在別的東西壞掉的時候才會跑**，而那正是最不能再壞一次的時刻。

零覆蓋的處理器有一個特別討厭的失敗模式：它自己出錯的話，原本的例外連同新的例外
一起消失，使用者看到的是「按了按鈕，視窗沒了」，日誌裡什麼都沒有。

所以這裡除了「正常路徑會顯示對話框」之外，特別測**兩條退路**：
記不了日誌、以及連對話框都開不起來。那兩條 `except Exception` 存在的唯一理由就是
「不要讓錯誤處理自己變成第二次崩潰」，而在這份檔案之前沒有東西驗過它們。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import pytest
from PySide6.QtWidgets import QMessageBox

from tagcor_ledger.ui import error_handler


@pytest.fixture
def shown(monkeypatch: Any) -> list[QMessageBox]:
    """攔下 `QMessageBox.exec()`，把對話框物件收集起來而不是真的顯示。

    `exec()` 會卡住等使用者按按鈕 —— 測試裡不能真的開。
    """
    boxes: list[QMessageBox] = []

    def fake_exec(self: QMessageBox) -> int:
        boxes.append(self)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return boxes


def _raise(kind: type[BaseException] = RuntimeError, text: str = "壞掉了") -> tuple[Any, ...]:
    """造一組真的 `(type, exc, tb)`，不要自己捏 traceback。"""
    try:
        raise kind(text)
    except BaseException:  # noqa: BLE001 —— 這裡就是要把它抓下來當素材
        return sys.exc_info()


def test_installing_the_handler_takes_over_excepthook(monkeypatch: Any) -> None:
    """`install_exception_handler()` 真的接管 `sys.excepthook`。

    **用 monkeypatch 還原** —— 直接改 `sys.excepthook` 而不還原的話，
    後面每一條測試的例外都會走進這個 handler。
    """
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    error_handler.install_exception_handler()
    assert sys.excepthook is error_handler._handle


def test_an_unhandled_exception_shows_a_chinese_dialog(
    qtbot: Any, shown: list[QMessageBox]
) -> None:
    """畫面上要有：能繼續用的那句話、例外類型、以及可以拿去搜日誌的識別碼。"""
    error_handler._handle(*_raise())

    assert len(shown) == 1, "沒有顯示對話框"
    box = shown[0]
    assert box.windowTitle() == "發生未預期的錯誤"
    assert "還可以繼續使用" in box.text()
    assert "資料不會因為這個訊息而遺失" in box.text()

    detail = box.informativeText()
    assert "RuntimeError: 壞掉了" in detail, "認不出是什麼錯的話，回報等於沒有資訊"
    assert "識別碼：corr_" in detail, "沒有識別碼就沒辦法在日誌裡找到同一次事故"


def test_the_close_button_says_it_is_safe_to_continue(
    qtbot: Any, shown: list[QMessageBox]
) -> None:
    """按鈕寫「繼續使用」不是「關閉」。

    這一層的原則是「能繼續就繼續」，而按鈕上寫「關閉」會讓人以為要關掉程式 ——
    那正是這一層想避免的事（記到一半的那筆帳會不見）。
    """
    error_handler._handle(*_raise())
    button = shown[0].button(QMessageBox.StandardButton.Close)
    assert button is not None
    assert button.text() == "繼續使用"


def test_two_crashes_get_two_different_ids(qtbot: Any, shown: list[QMessageBox]) -> None:
    """識別碼每次都要不一樣 —— 一樣的話日誌裡兩次事故會混成一次。"""
    error_handler._handle(*_raise())
    error_handler._handle(*_raise())

    ids = [box.informativeText().split("識別碼：")[1].split("\n")[0] for box in shown]
    assert len(set(ids)) == 2, f"兩次崩潰拿到同一個識別碼：{ids}"


def test_ctrl_c_is_not_treated_as_a_crash(
    qtbot: Any, monkeypatch: Any, shown: list[QMessageBox]
) -> None:
    """`KeyboardInterrupt` 交回預設行為，不跳對話框。

    使用者主動中止不是「錯誤」。跳一個「發生未預期的錯誤」給他看是在說謊。
    """
    delegated: list[type[BaseException]] = []
    monkeypatch.setattr(
        sys, "__excepthook__", lambda exc_type, exc, tb: delegated.append(exc_type)
    )

    error_handler._handle(*_raise(KeyboardInterrupt, ""))

    assert delegated == [KeyboardInterrupt], "沒有交回預設 excepthook"
    assert not shown, "Ctrl+C 不該跳對話框"


def test_the_crash_is_written_to_the_log(
    qtbot: Any, shown: list[QMessageBox], caplog: Any
) -> None:
    """日誌要記下識別碼與例外類型，而且畫面上那個識別碼要對得起來。"""
    with caplog.at_level(logging.ERROR, logger="tagcor_ledger.crash"):
        error_handler._handle(*_raise(ValueError, "TEST_CODE"))

    assert caplog.records, "什麼都沒記到日誌"
    logged = caplog.records[0].getMessage()
    shown_id = shown[0].informativeText().split("識別碼：")[1].split("\n")[0]
    assert shown_id in logged, "畫面上的識別碼在日誌裡搜不到，那它就沒有用"
    assert "ValueError" in logged


def test_a_broken_logger_does_not_swallow_the_crash(
    qtbot: Any, monkeypatch: Any, shown: list[QMessageBox], capsys: Any
) -> None:
    """記不了日誌時退回 stderr，**而且對話框照樣要出現**。

    這條守的是那個 `except Exception` 的意義：記日誌失敗不該讓使用者連訊息都看不到。
    """
    monkeypatch.setattr(
        error_handler, "get_logger", lambda name: (_ for _ in ()).throw(OSError("磁碟滿了"))
    )

    error_handler._handle(*_raise(ValueError, "還是要看得到"))

    assert "ValueError: 還是要看得到" in capsys.readouterr().err, "沒有退回 stderr"
    assert len(shown) == 1, "日誌壞掉不該連對話框都不見"


def test_a_broken_dialog_falls_back_to_stderr_instead_of_crashing(
    qtbot: Any, monkeypatch: Any, capsys: Any
) -> None:
    """連對話框都開不起來時，**不准再丟一次例外**。

    這是最後的退路。它自己丟例外的話，`sys.excepthook` 裡的例外會被 Python
    直接印掉，原本那個錯就徹底消失了。
    """
    monkeypatch.setattr(
        error_handler,
        "_show",
        lambda *args: (_ for _ in ()).throw(RuntimeError("沒有 QApplication")),
    )

    error_handler._handle(*_raise(ValueError, "原本那個錯"))  # 不得丟出例外

    assert "ValueError: 原本那個錯" in capsys.readouterr().err


def test_the_dialog_points_at_the_log_file_when_there_is_one(
    qtbot: Any, monkeypatch: Any, shown: list[QMessageBox], tmp_path: Any
) -> None:
    """有日誌檔時要把路徑寫出來 —— 使用者回報問題時才知道要附哪個檔。

    沒有日誌檔（`current_log_path()` 回 `None`）時就不寫，不要印一行「日誌：None」。
    """
    log_file = tmp_path / "tagcor.log"
    monkeypatch.setattr(error_handler, "current_log_path", lambda: log_file)
    error_handler._handle(*_raise())
    assert f"日誌：{log_file}" in shown[0].informativeText()

    shown.clear()
    monkeypatch.setattr(error_handler, "current_log_path", lambda: None)
    error_handler._handle(*_raise())
    assert "日誌：" not in shown[0].informativeText(), "沒有日誌檔就不要提日誌"
