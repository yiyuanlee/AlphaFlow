"""Intraday indicators for hot-stock momentum trading."""

import pandas as pd

from alphaflow.hot_config import HotEntryParams


def compute_intraday_indicators(df: pd.DataFrame, params: HotEntryParams) -> pd.DataFrame:
    out = df.copy()
    out['ema_fast'] = out['close'].ewm(span=params.fast_ema, adjust=False).mean()
    out['ema_slow'] = out['close'].ewm(span=params.slow_ema, adjust=False).mean()

    cum_vol = out['volume'].cumsum().replace(0, pd.NA)
    typical = (out['high'] + out['low'] + out['close']) / 3
    out['vwap'] = (out['volume'] * typical).cumsum() / cum_vol

    delta = out['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=params.rsi_period - 1, min_periods=params.rsi_period).mean()
    avg_loss = loss.ewm(com=params.rsi_period - 1, min_periods=params.rsi_period).mean().replace(0, 0.001)
    out['rsi'] = 100 - (100 / (1 + avg_gain / avg_loss))

    return out
