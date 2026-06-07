"""yfinance option chain provider (current date only — not for historical replay)."""

from __future__ import annotations

from datetime import date

import yfinance as yf

from alphaflow.options.chain_data.black_scholes import delta, estimate_vol_from_price
from alphaflow.options.chain_data.types import HistoricalOptionQuote
from alphaflow.options.options_config import OptionsChainDataParams


class YFinanceChainProvider:
    """Supports today's chain snapshot. Historical as_of dates return empty."""

    def __init__(self, params: OptionsChainDataParams):
        self.params = params

    def get_underlying_close(self, underlying: str, as_of: str) -> float | None:
        if as_of != date.today().isoformat():
            return None
        ticker = yf.Ticker(underlying)
        hist = ticker.history(period='1d')
        if hist.empty:
            return None
        return float(hist['Close'].iloc[-1])

    def get_option_close(self, option_ticker: str, as_of: str) -> float | None:
        return None

    def get_chain(self, underlying: str, as_of: str, right: str) -> list[HistoricalOptionQuote]:
        if as_of != date.today().isoformat():
            return []
        ticker = yf.Ticker(underlying)
        expiries = ticker.options
        if not expiries:
            return []
        spot = self.get_underlying_close(underlying, as_of)
        if spot is None:
            return []
        quotes: list[HistoricalOptionQuote] = []
        as_of_date = date.fromisoformat(as_of)
        for expiry_iso in expiries:
            expiry = expiry_iso.replace('-', '')
            exp_date = date.fromisoformat(expiry_iso)
            dte = (exp_date - as_of_date).days
            if dte < self.params.dte_min or dte > self.params.dte_max:
                continue
            chain = ticker.option_chain(expiry_iso)
            df = chain.calls if right.upper() == 'C' else chain.puts
            for _, row in df.iterrows():
                strike = float(row['strike'])
                bid = float(row.get('bid', 0) or 0)
                ask = float(row.get('ask', 0) or 0)
                last = float(row.get('lastPrice', 0) or 0)
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                if mid <= 0:
                    continue
                vol = estimate_vol_from_price(spot, strike, dte, right, mid)
                greek = float(row.get('delta', 0) or 0) or delta(spot, strike, dte, right, vol)
                quotes.append(HistoricalOptionQuote(
                    underlying=underlying,
                    option_ticker='',
                    expiry=expiry,
                    strike=strike,
                    right=right.upper(),
                    as_of=as_of,
                    close=mid,
                    delta=greek,
                ))
        return quotes
