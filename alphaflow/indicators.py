"""Indicator calculations shared by live trading and diagnostics."""

import pandas as pd

from alphaflow.config import StrategyParams


def compute_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """Compute all strategy indicators on an OHLCV DataFrame.

    Expects lowercase columns: open, high, low, close, volume.
    """
    out = df.copy()

    out['ema_fast'] = out['close'].ewm(span=params.fast_period, adjust=False).mean()
    out['ema_slow'] = out['close'].ewm(span=params.slow_period, adjust=False).mean()
    out['ema_trend'] = out['close'].ewm(span=params.trend_period, adjust=False).mean()

    high_low = out['high'] - out['low']
    high_cp = (out['high'] - out['close'].shift()).abs()
    low_cp = (out['low'] - out['close'].shift()).abs()
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)

    out['atr'] = tr.ewm(span=2 * params.atr_period - 1, adjust=False).mean()

    up_move = out['high'].diff()
    down_move = -out['low'].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr_smooth = tr.ewm(span=2 * params.adx_period - 1, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=2 * params.adx_period - 1, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (minus_dm.ewm(span=2 * params.adx_period - 1, adjust=False).mean() / tr_smooth)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 0.001)
    out['adx'] = dx.ewm(span=2 * params.adx_period - 1, adjust=False).mean()

    delta = out['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=params.rsi_period - 1, min_periods=params.rsi_period).mean()
    avg_loss = loss.ewm(com=params.rsi_period - 1, min_periods=params.rsi_period).mean().replace(0, 0.001)
    out['rsi'] = 100 - (100 / (1 + avg_gain / avg_loss))

    out['atr_sma'] = out['atr'].rolling(window=params.vol_filter_period).mean()

    prev_fast = out['ema_fast'].shift(1)
    prev_slow = out['ema_slow'].shift(1)
    out['golden_cross'] = (out['ema_fast'] > out['ema_slow']) & (prev_fast <= prev_slow)
    out['death_cross'] = (out['ema_fast'] < out['ema_slow']) & (prev_fast >= prev_slow)

    return out


def latest_row(df: pd.DataFrame, params: StrategyParams) -> pd.Series:
    """Return the latest indicator row for a price history DataFrame."""
    return compute_indicators(df, params).iloc[-1]
