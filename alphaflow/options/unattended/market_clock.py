"""NYSE session and entry-window helpers."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from .config import ScheduleConfig


class MarketClock:
    def __init__(self, config: ScheduleConfig):
        self.config = config
        self.tz = ZoneInfo(config.timezone)
        self.calendar = xcals.get_calendar("XNYS")

    @staticmethod
    def _parse(value: str) -> time:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour, minute)

    def eastern(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(tz=ZoneInfo("UTC"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("UTC"))
        return now.astimezone(self.tz)

    def is_session(self, now: datetime | None = None) -> bool:
        local = self.eastern(now)
        try:
            return bool(self.calendar.is_session(pd.Timestamp(local.date())))
        except (ValueError, TypeError):
            return False

    def in_entry_window(self, now: datetime | None = None) -> bool:
        local = self.eastern(now)
        return self.is_session(local) and self._parse(self.config.entry_start) <= local.time() <= self._parse(
            self.config.entry_end
        )

    def in_management_window(self, now: datetime | None = None) -> bool:
        local = self.eastern(now)
        return self.is_session(local) and self._parse(self.config.manage_start) <= local.time() <= self._parse(
            self.config.manage_end
        )

    def session_date(self, now: datetime | None = None) -> str:
        return self.eastern(now).date().isoformat()
