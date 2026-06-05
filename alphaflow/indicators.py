"""Indicator calculations shared by live trading and diagnostics.

Algorithms match Backtrader defaults: EMA/SMMA seed with the first-period SMA,
then recursive smoothing (see backtrader.indicators.basicops.ExponentialSmoothing).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaflow.config import StrategyParams


def _smooth_backtrader(values: np.ndarray, period: int, alpha: float) -> np.ndarray:
    """Replicate Backtrader ExponentialSmoothing (SMA seed + recursive smooth)."""
    n = len(values)
    out = np.full(n, np.nan, dtype=float)
    if n < period:
        return out

    out[period - 1] = float(np.mean(values[:period]))
    alpha1 = 1.0 - alpha
    for i in range(period, n):
        out[i] = out[i - 1] * alpha1 + values[i] * alpha
    return out


def ema_backtrader(series: pd.Series, period: int) -> pd.Series:
    """EMA with Backtrader-compatible SMA seed (alpha = 2 / (period + 1))."""
    alpha = 2.0 / (period + 1)
    smoothed = _smooth_backtrader(series.to_numpy(dtype=float), period, alpha)
    return pd.Series(smoothed, index=series.index)


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder SMMA with Backtrader-compatible SMA seed (alpha = 1 / period)."""
    alpha = 1.0 / period
    smoothed = _smooth_backtrader(series.to_numpy(dtype=float), period, alpha)
    return pd.Series(smoothed, index=series.index)


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def compute_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """Compute all strategy indicators on an OHLCV DataFrame.

    Expects lowercase columns: open, high, low, close, volume.
    """
    out = df.copy()

    out['ema_fast'] = ema_backtrader(out['close'], params.fast_period)
    out['ema_slow'] = ema_backtrader(out['close'], params.slow_period)
    out['ema_trend'] = ema_backtrader(out['close'], params.trend_period)

    tr = _true_range(out['high'], out['low'], out['close'])
    out['atr'] = wilder_smooth(tr, params.atr_period)

    up_move = out['high'].diff()
    down_move = -out['low'].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    plus_di = 100.0 * wilder_smooth(plus_dm, params.adx_period) / out['atr']
    minus_di = 100.0 * wilder_smooth(minus_dm, params.adx_period) / out['atr']
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 0.001)
    out['adx'] = wilder_smooth(dx, params.adx_period)

    delta = out['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = wilder_smooth(gain, params.rsi_period)
    avg_loss = wilder_smooth(loss, params.rsi_period).replace(0, 0.001)
    out['rsi'] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    out['atr_sma'] = out['atr'].rolling(window=params.vol_filter_period).mean()

    prev_fast = out['ema_fast'].shift(1)
    prev_slow = out['ema_slow'].shift(1)
    out['golden_cross'] = (out['ema_fast'] > out['ema_slow']) & (prev_fast <= prev_slow)
    out['death_cross'] = (out['ema_fast'] < out['ema_slow']) & (prev_fast >= prev_slow)

    return out


def latest_row(df: pd.DataFrame, params: StrategyParams) -> pd.Series:
    """Return the latest indicator row for a price history DataFrame."""
    return compute_indicators(df, params).iloc[-1]
