"""第二次啟動時，把已經開著的視窗叫到最前面，而不是跳一個警告。

使用者按下捷徑的意思是「我要用這個程式」，不是「請告訴我它的狀態」。所以正確的回應是
**把視窗給他**，只有在真的做不到時才需要解釋。

## 這不算連網

用的是 `QLocalServer`／`QLocalSocket`，在 Windows 上是**具名管道**（named pipe），
在 Unix 上是 domain socket。沒有 TCP、沒有連接埠、沒有任何封包離開這台機器 ——
「App 永遠不發出網路請求」這條規則沒有被打破。

## 為什麼還是留著 filelock

「誰是第一個」由 `SingleInstanceGuard` 的檔案鎖決定，不由這個管道決定。理由是這個管道
只有在 Qt 起得來時才存在，而**判斷有沒有第二個實例這件事，不能依賴 Qt 起不起得來**。
管道只負責「已經確定有人在跑了，去敲他的門」。

敲不到門（對方卡住、管道殘留、Qt 版本問題）就退回原本的對話框 —— 那條路沒有被移除，
只是降級成備案。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QWidget

from tagcor_ledger.app.logging_setup import get_logger


ACTIVATE_COMMAND = b"activate"
ACKNOWLEDGED = b"ok"
DEFAULT_TIMEOUT_MS = 1500


def channel_name(ledger_dir: Path) -> str:
    """管道名稱綁在帳本位置上，所以不同資料夾的實例互不干擾。

    用雜湊而不是路徑本身：路徑會有冒號、反斜線與中文，都不適合當管道名稱。
    Windows 路徑比對不分大小寫，所以先轉小寫，避免同一個資料夾算出兩個名字。
    """
    resolved = str(Path(ledger_dir).expanduser().resolve()).lower()
    digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:16]
    return f"tagcor-ledger-{digest}"


def bring_to_front(window: QWidget) -> None:
    """把視窗還原、抬起、取得焦點。三個都要做，缺一個就會有情境失效。"""
    state = window.windowState()
    window.setWindowState(
        (state & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
    )
    window.show()
    window.raise_()
    window.activateWindow()


class ActivationServer:
    """第一個實例開的門。收到 `activate` 就呼叫 `on_activate`。"""

    def __init__(self, ledger_dir: Path, on_activate: Callable[[], None]) -> None:
        self._name = channel_name(ledger_dir)
        self._on_activate = on_activate
        self._server: QLocalServer | None = None

    def start(self) -> bool:
        # 上一次沒有正常關閉時管道名稱可能殘留。呼叫端已經先拿到檔案鎖、確定自己是唯一
        # 的實例，所以這裡清掉殘留是安全的。
        QLocalServer.removeServer(self._name)
        server = QLocalServer()
        if not server.listen(self._name):
            get_logger("instance").warning(
                "activation server unavailable reason=%s", server.errorString()
            )
            return False
        server.newConnection.connect(self._handle_connection)
        self._server = server
        get_logger("instance").info("activation server listening")
        return True

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None

    def _handle_connection(self) -> None:
        if self._server is None:
            return
        connection = self._server.nextPendingConnection()
        if connection is None:
            return

        def on_ready() -> None:
            payload = bytes(connection.readAll().data())
            if ACTIVATE_COMMAND not in payload:
                connection.disconnectFromServer()
                return
            connection.write(ACKNOWLEDGED)
            connection.flush()
            get_logger("instance").info("activation requested by another launch")
            try:
                self._on_activate()
            finally:
                connection.disconnectFromServer()

        connection.readyRead.connect(on_ready)


def request_activation(ledger_dir: Path, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> bool:
    """請既有實例把視窗叫到最前面。真的做到才回傳 True。

    等一個 ack 而不是「送出去就算數」：連得上不代表對方還在處理事件，而**回報成功卻
    什麼都沒發生**，比直接顯示警告更糟 —— 使用者會以為自己點錯了。
    """
    _allow_foreground_handoff()
    socket = QLocalSocket()
    socket.connectToServer(channel_name(ledger_dir))
    if not socket.waitForConnected(timeout_ms):
        return False
    try:
        socket.write(ACTIVATE_COMMAND)
        if not socket.waitForBytesWritten(timeout_ms):
            return False
        if not socket.waitForReadyRead(timeout_ms):
            return False
        return ACKNOWLEDGED in bytes(socket.readAll().data())
    finally:
        socket.disconnectFromServer()


def _allow_foreground_handoff() -> None:
    """允許另一個行程搶到前景。

    Windows 預設不讓背景行程把自己拉到最上層（防的是廣告視窗亂跳）。**目前在前景的是
    我們自己**（使用者剛剛按了捷徑），所以由我們主動把這個權利讓出去，既有實例才叫得
    上來；少了這一步，通常只會看到工作列圖示閃爍。

    做不到就算了 —— 最差的情況是視窗沒跳到最前面，不該因此讓啟動失敗。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:  # noqa: BLE001
        pass
