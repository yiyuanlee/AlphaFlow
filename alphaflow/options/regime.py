"""Market regime for options routing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from alphaflow.config import StrategyParams
from alphaflow.hot_config import HotMarketFilterParams
from alphaflow.hot_market import build_market_regime_lookup
from alphaflow.indicators import compute_indicators
from alphaflow.options.options_config import OptionsRegimeParams


class MarketRegime(str, Enum):
    STRONG_UPTREND = 'strong_uptrend'
    MILD_BULL = 'mild_bull'
    WEAK = 'weak'
    SHARP_DROP = 'sharp_drop'


@dataclass(frozen=True)
class RegimeSnapshot:
    benchmark: str
    close: float
    ema_trend: float
    adx: float
    rsi: float
    bullish: bool
    regime: MarketRegime


def classify_regime(
    close: float,
    ema_trend: float,
    adx_val: float,
    rsi_val: float,
    params: OptionsRegimeParams,
) -> MarketRegime:
    bullish = close > ema_trend
    if not bullish:
        if rsi_val > 70:
            return MarketRegime.WEAK
        if adx_val >= params.adx_trend_threshold:
            return MarketRegime.SHARP_DROP
        return MarketRegime.WEAK
    if adx_val >= params.adx_trend_threshold:
        return MarketRegime.STRONG_UPTREND
    if params.adx_range_low <= adx_val < params.adx_range_high:
        return MarketRegime.MILD_BULL
    return MarketRegime.MILD_BULL


def compute_regime_from_df(df: pd.DataFrame, params: OptionsRegimeParams) -> RegimeSnapshot:
    strat = StrategyParams(trend_period=params.trend_period)
    ind = compute_indicators(df, strat)
    row = ind.iloc[-1]
    close = float(row['close'])
    adx_val = float(row['adx']) if not pd.isna(row['adx']) else 0.0
    rsi_val = float(row['rsi']) if not pd.isna(row['rsi']) else 50.0
    ema_trend = float(row['ema_trend']) if not pd.isna(row['ema_trend']) else close
    bullish = close > ema_trend
    regime = classify_regime(close, ema_trend, adx_val, rsi_val, params)
    return RegimeSnapshot(
        benchmark=params.benchmark,
        close=close,
        ema_trend=ema_trend,
        adx=adx_val,
        rsi=rsi_val,
        bullish=bullish,
        regime=regime,
    )


def build_benchmark_regime_lookup(
    benchmark_df: pd.DataFrame,
    params: OptionsRegimeParams,
) -> dict[str, RegimeSnapshot]:
    lookup: dict[str, RegimeSnapshot] = {}
    dates = benchmark_df.index
    for i in range(params.trend_period, len(benchmark_df)):
        window = benchmark_df.iloc[: i + 1]
        day = str(dates[i].date()) if hasattr(dates[i], 'date') else str(dates[i])[:10]
        lookup[day] = compute_regime_from_df(window, params)
    return lookup


def is_bullish_on_date(
    lookup: dict[str, bool] | dict[str, RegimeSnapshot],
    day: str,
) -> bool:
    entry = lookup.get(day)
    if entry is None:
        return False
    if isinstance(entry, RegimeSnapshot):
        return entry.bullish
    return bool(entry)


def preload_benchmark_regime(
    start: str,
    end: str,
    params: OptionsRegimeParams,
) -> dict[str, bool]:
    hot_params = HotMarketFilterParams(
        benchmark=params.benchmark,
        trend_period=params.trend_period,
        require_bull_market=params.require_bull_market,
    )
    return build_market_regime_lookup(hot_params, start, end)
