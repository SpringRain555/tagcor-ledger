"""單一實例的喚醒管道。

第二次啟動時應該把既有視窗叫到最前面，而不是跳警告 —— 使用者按捷徑的意思是
「我要用這個程式」。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QWidget

from tagcor_ledger.ui.instance_channel import (
    ACKNOWLEDGED,
    ACTIVATE_COMMAND,
    ActivationServer,
    bring_to_front,
    channel_name,
    request_activation,
)


def test_channel_name_is_stable_and_per_ledger(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()

    assert channel_name(first) == channel_name(first)
    assert channel_name(first) != channel_name(second)
    # Windows 路徑不分大小寫，同一個資料夾不能算出兩個名字。
    assert channel_name(Path(str(first).upper())) == channel_name(first)
    # 管道名稱不能帶路徑分隔字元或中文。
    assert channel_name(first).replace("-", "").isalnum()


def test_server_activates_and_acknowledges(qtbot, tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    activations: list[int] = []

    server = ActivationServer(ledger_dir, lambda: activations.append(1))
    assert server.start()

    socket = QLocalSocket()
    socket.connectToServer(channel_name(ledger_dir))
    qtbot.waitUntil(lambda: socket.state() == QLocalSocket.LocalSocketState.ConnectedState)
    socket.write(ACTIVATE_COMMAND)
    socket.flush()

    # 回 ack 之前必須真的呼叫過 on_activate，否則「回報成功卻什麼都沒發生」
    # 比直接顯示警告更糟。
    qtbot.waitUntil(lambda: activations == [1])
    qtbot.waitUntil(lambda: socket.bytesAvailable() > 0)
    assert ACKNOWLEDGED in bytes(socket.readAll().data())

    socket.disconnectFromServer()
    server.close()


def test_request_activation_reports_failure_when_nobody_is_listening(tmp_path: Path) -> None:
    """沒人在聽就必須回 False —— 呼叫端要靠這個決定是否退回警告對話框。"""
    ledger_dir = tmp_path / "nobody"
    ledger_dir.mkdir()
    assert request_activation(ledger_dir, timeout_ms=200) is False


def test_server_ignores_unknown_payload(qtbot, tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    activations: list[int] = []
    server = ActivationServer(ledger_dir, lambda: activations.append(1))
    assert server.start()

    socket = QLocalSocket()
    socket.connectToServer(channel_name(ledger_dir))
    qtbot.waitUntil(lambda: socket.state() == QLocalSocket.LocalSocketState.ConnectedState)
    socket.write(b"something-else")
    socket.flush()
    qtbot.wait(150)

    assert activations == []
    socket.disconnectFromServer()
    server.close()


def test_bring_to_front_restores_a_minimised_window(qtbot) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    window.showMinimized()
    assert window.isMinimized()

    bring_to_front(window)

    assert not window.isMinimized()


def test_two_ledgers_get_independent_channels(qtbot, tmp_path: Path) -> None:
    """指向不同資料夾的兩個實例應該可以並存，各自有自己的門。"""
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()

    first = ActivationServer(first_dir, lambda: None)
    second = ActivationServer(second_dir, lambda: None)
    assert first.start()
    assert second.start()

    first.close()
    second.close()
