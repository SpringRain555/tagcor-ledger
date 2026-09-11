"""「視窗已經開起來了」這件事，要怎麼告訴啟動它的那個主控台。

## 問題

`Launch.ps1` 把 `pythonw.exe` 叫起來之後要決定自己什麼時候可以退場。
2026-08-18 到 2026-09-11 之間它的判準是**等 5 秒，行程還在就當視窗開了**。
那個數字擋得住「一啟動就死」，擋不住另外兩種：

- 視窗第 8 秒才出來（冷啟動、防毒掃描）—— 主控台在第 5 秒已經印了
  「視窗已開啟」然後關掉，使用者對著一片空白等
- 第 6 秒才炸掉 —— 錯誤進了 `launch-stderr.log`，而唯一會說話的那個視窗
  已經不在了

**固定秒數不是訊號，是猜測。** CONVENTIONS §16 第 3 題要的是一個明確的
就緒訊號；這一份就是那個訊號。

## 為什麼是檔案

行程之間要傳一個 bit，可選的有具名管道、mutex、socket、以及一個檔案。
前三個在 PowerShell 5.1 那一側都要寫十幾行 .NET 互通程式碼；檔案是
`Test-Path`。而這個訊號本來就只有一個位元組的資訊量。

檔案裡放的是 PID 與時間，**不是為了讓誰去讀**，是為了在出問題的時候
（例如標記沒被清掉）看得出來它是哪一次留下的。

## 位置從 `AppPaths` 來，不在 PowerShell 那一側拼

標記放在 `tmp_dir` 底下 —— 它的生命週期是「這一次啟動」，不是「這份安裝」。
`Launch.ps1` 從 `--json` 的 `ready_marker` 欄位拿路徑；那個 payload 它本來就
要讀（`log_dir` 也是從那裡來的）。在 PowerShell 裡自己拼 `tmp\\ui-ready.txt`
就是第二份路徑實作，`--data-dir` 或指標檔改了資料根之後它會安靜地指錯地方。

## 這是 `webscouts` 那一份的複本

`webscouts/app/startup_signal.py` 先寫的（2026-09-11），這一份照抄再改成
吃 `AppPaths`。**不抽共用套件** —— 兩個獨立 repo、獨立相依，抽出去會造出
一條跨專案相依；理由與單一實例守門那一份相同。
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from tagcor_ledger.app.paths import AppPaths

MARKER_FILE_NAME = "ui-ready.txt"


def marker_path(paths: AppPaths) -> Path:
    """這一份資料根的標記檔位置。`--json` 把它印給啟動器。"""
    return paths.tmp_dir / MARKER_FILE_NAME


def clear(path: Path) -> None:
    """把上一次的標記刪掉。啟動器在叫起 Python 之前也會刪一次；這裡是沒有啟動器
    （直接 `python -m tagcor_ledger --gui`）那條路的保險。

    刪不掉就算了 —— 最壞的情況是主控台早一點關掉，
    那比「因為刪不掉一個暫存檔而不給開程式」好。
    """
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def mark_ready(path: Path) -> bool:
    """記下「視窗已經顯示」。回傳有沒有寫成功。

    **要在 `window.show()` 之後呼叫**，不是之前 —— 這個訊號的意思是
    「使用者看得到東西了」，提早寫就只是「程式碼跑到這一行了」。

    寫不進去要回 `False` 讓呼叫端記進日誌。回 `True` 而讓啟動器永遠等下去，
    比主控台早關掉糟糕得多。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"pid={os.getpid()}\nat={datetime.now().isoformat(timespec='seconds')}\n",
            encoding="utf-8",
        )
    except OSError:
        return False
    return True
