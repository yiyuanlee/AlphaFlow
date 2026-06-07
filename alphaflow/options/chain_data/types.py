"""Types for option chain data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoricalOptionQuote:
    underlying: str
    option_ticker: str
    expiry: str
    strike: float
    right: str
    as_of: str
    close: float
    delta: float = 0.0
    volume: int = 0

    @property
    def mid(self) -> float:
        return self.close
