"""XNYS session helpers used by live trading and backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


@dataclass(frozen=True)
class SessionSchedule:
    session_date: date
    open_utc: datetime
    close_utc: datetime

    @property
    def open_et(self) -> datetime:
        return self.open_utc.astimezone(ET)

    @property
    def close_et(self) -> datetime:
        return self.close_utc.astimezone(ET)

    def force_flat_at(self, minutes_before_close: int = 15) -> datetime:
        return self.close_utc - timedelta(minutes=minutes_before_close)


class XnysClock:
    def __init__(self) -> None:
        self.calendar = xcals.get_calendar("XNYS")

    def is_session(self, session_date: date) -> bool:
        return bool(self.calendar.is_session(pd.Timestamp(session_date)))

    def schedule(self, session_date: date) -> SessionSchedule | None:
        label = pd.Timestamp(session_date)
        if not self.calendar.is_session(label):
            return None
        open_utc = self.calendar.session_open(label).to_pydatetime().astimezone(UTC)
        close_utc = self.calendar.session_close(label).to_pydatetime().astimezone(UTC)
        return SessionSchedule(session_date, open_utc, close_utc)

    def session_for(self, timestamp: datetime) -> date | None:
        aware = ensure_utc(timestamp)
        local_date = aware.astimezone(ET).date()
        schedule = self.schedule(local_date)
        if schedule and schedule.open_utc <= aware < schedule.close_utc:
            return local_date
        return None

    def complete_month_window(self, today: date, months: int = 3) -> tuple[date, date]:
        first_this_month = today.replace(day=1)
        end = first_this_month - timedelta(days=1)
        cursor = first_this_month
        for _ in range(months):
            cursor = (cursor - timedelta(days=1)).replace(day=1)
        return cursor, end


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def parse_hhmm(value: str) -> time:
    return time.fromisoformat(value)


def in_time_window(local: datetime, start: str, end: str) -> bool:
    if local.tzinfo is None:
        raise ValueError("local timestamp must be timezone-aware")
    current = local.timetz().replace(tzinfo=None)
    return parse_hhmm(start) <= current <= parse_hhmm(end)
