"""Intraday indicators for hot-stock momentum trading."""

import pandas as pd

from alphaflow.hot_config import HotEntryParams
from alphaflow.indicators import ema_backtrader, wilder_smooth, _true_range


def compute_intraday_indicators(df: pd.DataFrame, params: HotEntryParams) -> pd.DataFrame:
    out = df.copy()
    if 'close' not in out.columns:
        out = out.rename(columns={c: c.lower() for c in out.columns})

    out['ema_fast'] = ema_backtrader(out['close'], params.fast_ema)
    out['ema_slow'] = ema_backtrader(out['close'], params.slow_ema)

    prev_fast = out['ema_fast'].shift(1)
    prev_slow = out['ema_slow'].shift(1)
    out['golden_cross'] = (out['ema_fast'] > out['ema_slow']) & (prev_fast <= prev_slow)
    out['death_cross'] = (out['ema_fast'] < out['ema_slow']) & (prev_fast >= prev_slow)

    cum_vol = out['volume'].cumsum().replace(0, pd.NA)
    typical = (out['high'] + out['low'] + out['close']) / 3
    out['vwap'] = (out['volume'] * typical).cumsum() / cum_vol

    tr = _true_range(out['high'], out['low'], out['close'])
    up_move = out['high'].diff()
    down_move = -out['low'].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    plus_di = 100.0 * wilder_smooth(plus_dm, params.adx_period) / wilder_smooth(tr, params.adx_period)
    minus_di = 100.0 * wilder_smooth(minus_dm, params.adx_period) / wilder_smooth(tr, params.adx_period)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 0.001)
    out['adx'] = wilder_smooth(dx, params.adx_period)

    delta = out['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = wilder_smooth(gain, params.rsi_period)
    avg_loss = wilder_smooth(loss, params.rsi_period).replace(0, 0.001)
    out['rsi'] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    vol_avg = out['volume'].rolling(window=params.rel_volume_period, min_periods=1).mean()
    out['rel_volume'] = out['volume'] / vol_avg.replace(0, pd.NA)

    return out


def compute_daily_replay_indicators(df: pd.DataFrame, params: HotEntryParams) -> pd.DataFrame:
    """Daily-bar indicators for scanner replay (VWAP proxy = close above bar midpoint)."""
    out = compute_intraday_indicators(df, params)
    out['vwap'] = (out['high'] + out['low']) / 2
    return out
