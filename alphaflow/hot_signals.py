"""Entry/exit and sizing for hot-stock momentum sleeve."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd

from alphaflow.hot_config import HotEntryParams, HotExitParams, HotPositionParams, HotRiskParams


def check_hot_entry(
    close: float,
    ema_fast: float,
    ema_slow: float,
    rsi: float,
    vwap: float,
    golden_cross: bool,
    adx: float,
    rel_volume: float,
    market_bullish: bool,
    params: HotEntryParams,
) -> tuple[bool, str]:
    """Return (allowed, reason_code)."""
    if params.require_bull_market and not market_bullish:
        return False, 'market_not_bullish'

    if params.require_golden_cross and not golden_cross:
        return False, 'no_golden_cross'

    if ema_fast <= ema_slow:
        return False, 'ema_not_aligned'

    if rsi >= params.rsi_max:
        return False, 'rsi_too_high'

    if params.require_above_vwap and (pd.isna(vwap) or close <= vwap):
        return False, 'below_vwap'

    if pd.isna(adx) or adx < params.min_adx:
        return False, 'adx_too_low'

    if pd.isna(rel_volume) or rel_volume < params.min_rel_volume:
        return False, 'rel_volume_too_low'

    return True, 'ok'


def hold_days(entry_date: str, today: date | None = None) -> int:
    today = today or date.today()
    entered = datetime.strptime(entry_date[:10], '%Y-%m-%d').date()
    return (today - entered).days


def check_hot_exit(
    entry_date: str,
    entry_price: float,
    current_price: float,
    ema_fast: float,
    ema_slow: float,
    vwap: float,
    entry: HotEntryParams,
    exit_params: HotExitParams,
    position_params: HotPositionParams,
    as_of: date | None = None,
) -> Optional[str]:
    if exit_params.force_exit_on_max_hold:
        if hold_days(entry_date, as_of) >= position_params.max_hold_days:
            return 'max_hold_days'

    if current_price >= entry_price * (1 + exit_params.take_profit_pct):
        return 'take_profit'

    if current_price <= entry_price * (1 - exit_params.stop_loss_pct):
        return 'stop_loss'

    if exit_params.use_ema_cross and ema_fast < ema_slow:
        return 'ema_cross'

    if exit_params.use_vwap_break and not pd.isna(vwap) and current_price < vwap:
        return 'vwap_break'

    return None


def calc_hot_position_size(
    price: float,
    net_liquidation: float,
    stock_exposure: float,
    risk: HotRiskParams,
    position: HotPositionParams,
    stop_loss_pct: float,
) -> int:
    """Size order using only the stock capital pool."""
    pool_cap = net_liquidation * risk.stock_pool_pct
    available_pool = max(pool_cap - stock_exposure, 0)
    if available_pool <= 0 or price <= 0:
        return 0

    stop_per_share = price * stop_loss_pct
    if stop_per_share <= 0:
        return 0

    risk_budget = pool_cap * risk.risk_per_trade
    size_by_risk = int(risk_budget / stop_per_share)
    size_by_cap = int(pool_cap * position.max_single_position_pct / price)
    size_by_pool = int(available_pool / price)
    return max(min(size_by_risk, size_by_cap, size_by_pool), 0)
