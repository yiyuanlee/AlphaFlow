"""Compressed, resumable and de-duplicated local SPY minute-bar cache."""

from __future__ import annotations

import csv
import gzip
import os
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from alphaflow.scalping.types import MinuteBar

ET = ZoneInfo("America/New_York")
COLUMNS = ("timestamp_utc", "timestamp_et", "session_date", "open", "high", "low", "close", "volume")


class MinuteBarCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> list[MinuteBar]:
        if not self.path.exists():
            return []
        rows: list[MinuteBar] = []
        with gzip.open(self.path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                timestamp_utc = datetime.fromisoformat(row["timestamp_utc"]).astimezone(timezone.utc)
                timestamp_et = datetime.fromisoformat(row["timestamp_et"]).astimezone(ET)
                rows.append(
                    MinuteBar(
                        timestamp_utc=timestamp_utc,
                        timestamp_et=timestamp_et,
                        session_date=date.fromisoformat(row["session_date"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(float(row["volume"])),
                    )
                )
        return sorted(rows, key=lambda bar: bar.timestamp_utc)

    def merge(self, bars: Iterable[MinuteBar]) -> int:
        merged = {bar.timestamp_utc: bar for bar in self.read()}
        before = len(merged)
        changed = False
        for bar in bars:
            _validate_bar(bar)
            if merged.get(bar.timestamp_utc) != bar:
                changed = True
            merged[bar.timestamp_utc] = bar
        if not changed:
            return 0
        ordered = sorted(merged.values(), key=lambda bar: bar.timestamp_utc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp.gz")
        with gzip.open(temporary, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            for bar in ordered:
                writer.writerow(
                    {
                        "timestamp_utc": bar.timestamp_utc.astimezone(timezone.utc).isoformat(),
                        "timestamp_et": bar.timestamp_et.astimezone(ET).isoformat(),
                        "session_date": bar.session_date.isoformat(),
                        "open": f"{bar.open:.8f}",
                        "high": f"{bar.high:.8f}",
                        "low": f"{bar.low:.8f}",
                        "close": f"{bar.close:.8f}",
                        "volume": bar.volume,
                    }
                )
        os.replace(temporary, self.path)
        return len(merged) - before

    def to_frame(self, start: date | None = None, end: date | None = None) -> pd.DataFrame:
        bars = [
            bar
            for bar in self.read()
            if (start is None or bar.session_date >= start) and (end is None or bar.session_date <= end)
        ]
        if not bars:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]).set_axis(
                pd.DatetimeIndex([], tz="UTC"), axis="index"
            )
        return pd.DataFrame(
            {
                "open": [bar.open for bar in bars],
                "high": [bar.high for bar in bars],
                "low": [bar.low for bar in bars],
                "close": [bar.close for bar in bars],
                "volume": [bar.volume for bar in bars],
            },
            index=pd.DatetimeIndex([bar.timestamp_utc for bar in bars], name="timestamp_utc"),
        )

    def session_dates(self) -> set[date]:
        return {bar.session_date for bar in self.read()}

    def session_counts(self) -> dict[date, int]:
        counts: dict[date, int] = {}
        for bar in self.read():
            counts[bar.session_date] = counts.get(bar.session_date, 0) + 1
        return counts


def minute_bar_from_utc(
    timestamp_utc: datetime,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: int,
) -> MinuteBar:
    if timestamp_utc.tzinfo is None:
        raise ValueError("IBKR minute bar timestamp must be timezone-aware")
    utc_value = timestamp_utc.astimezone(timezone.utc)
    et_value = utc_value.astimezone(ET)
    return MinuteBar(utc_value, et_value, et_value.date(), open_price, high, low, close, int(volume))


def _validate_bar(bar: MinuteBar) -> None:
    if bar.timestamp_utc.tzinfo is None or bar.timestamp_et.tzinfo is None:
        raise ValueError("minute bar timestamps must be timezone-aware")
    if bar.timestamp_utc.astimezone(ET) != bar.timestamp_et.astimezone(ET):
        raise ValueError("ET and UTC timestamps do not identify the same instant")
    if bar.session_date != bar.timestamp_et.astimezone(ET).date():
        raise ValueError("session_date does not match the ET timestamp")
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        raise ValueError("OHLC prices must be positive")
    if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
        raise ValueError("invalid OHLC range")
    if bar.volume < 0:
        raise ValueError("volume cannot be negative")
