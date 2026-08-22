"""共用的本地時間工具。目前固定 Asia/Taipei。"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")


def now_iso() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def today_taipei() -> date:
    return datetime.now(TAIPEI).date()
