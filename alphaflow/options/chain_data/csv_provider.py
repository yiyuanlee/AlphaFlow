"""CSV-backed option chain provider for offline replay."""

from __future__ import annotations

import csv
from pathlib import Path

from alphaflow.options.chain_data.types import HistoricalOptionQuote
from alphaflow.options.options_config import OptionsChainDataParams


class CsvChainProvider:
    """Load rows from CSV with columns:
    as_of, underlying, expiry, strike, right, close, delta, option_ticker
    """

    def __init__(self, params: OptionsChainDataParams):
        self.params = params
        self.path = Path(params.csv_path) if params.csv_path else None
        self._rows: list[HistoricalOptionQuote] | None = None

    def _load(self) -> list[HistoricalOptionQuote]:
        if self._rows is not None:
            return self._rows
        if not self.path or not self.path.exists():
            self._rows = []
            return self._rows
        rows: list[HistoricalOptionQuote] = []
        with open(self.path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for item in reader:
                expiry = str(item['expiry']).replace('-', '')
                rows.append(HistoricalOptionQuote(
                    underlying=item['underlying'],
                    option_ticker=item.get('option_ticker', ''),
                    expiry=expiry,
                    strike=float(item['strike']),
                    right=item['right'].upper(),
                    as_of=item['as_of'],
                    close=float(item['close']),
                    delta=float(item.get('delta', 0) or 0),
                ))
        self._rows = rows
        return rows

    def get_chain(self, underlying: str, as_of: str, right: str) -> list[HistoricalOptionQuote]:
        return [
            q for q in self._load()
            if q.underlying == underlying and q.as_of == as_of and q.right == right.upper()
        ]

    def get_option_close(self, option_ticker: str, as_of: str) -> float | None:
        for q in self._load():
            if q.option_ticker == option_ticker and q.as_of == as_of:
                return q.close
        return None

    def get_underlying_close(self, underlying: str, as_of: str) -> float | None:
        return None
