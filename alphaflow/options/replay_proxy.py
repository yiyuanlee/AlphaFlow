"""Simplified options replay proxy (routing + risk only, not chain-accurate PnL)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from alphaflow.config import StrategyParams, load_config, params_from_config
from alphaflow.data import fetch_data, slice_ohlcv
from alphaflow.options.options_config import options_config_from_yaml
from alphaflow.options.regime import build_benchmark_regime_lookup, compute_regime_from_df
from alphaflow.options.signals import route_strategy
from alphaflow.options.types import StrategyIntent, UnderlyingSnapshot
from alphaflow.options.underlying import build_underlying_snapshot


@dataclass
class ProxyTrade:
    day: str
    symbol: str
    intent: str
    premium_pct: float
    assumed_pnl: float


DEFAULT_PREMIUM_PCT = {
    StrategyIntent.COVERED_CALL: 0.012,
    StrategyIntent.CSP: 0.015,
    StrategyIntent.BULL_PUT_SPREAD: 0.008,
    StrategyIntent.BEAR_CALL_SPREAD: 0.008,
}


def proxy_premium_pct(intent: StrategyIntent) -> float:
    return DEFAULT_PREMIUM_PCT.get(intent, 0.01)


def run_proxy_replay(
    start: str,
    end: str,
    initial_cash: float = 50_000.0,
    config: dict | None = None,
) -> list[ProxyTrade]:
    config = config or load_config()
    opt = options_config_from_yaml(config)
    strat_params, _ = params_from_config(config)
    benchmark = opt.regime.benchmark
    bench_df = fetch_data(benchmark, start, end)
    if bench_df is None or bench_df.empty:
        return []
    bench_df = slice_ohlcv(bench_df, start, end)
    regime_lookup = build_benchmark_regime_lookup(bench_df, opt.regime)

    underlying_dfs: dict[str, pd.DataFrame] = {}
    for sym in opt.underlyings:
        df = fetch_data(sym, start, end)
        if df is not None and not df.empty:
            underlying_dfs[sym] = slice_ohlcv(df, start, end)

    trades: list[ProxyTrade] = []
    cash = initial_cash
    stock_shares = {sym: opt.stock_core.get(sym, 0) for sym in opt.underlyings}

    for day, regime in sorted(regime_lookup.items()):
        if day < start:
            continue
        for sym, df in underlying_dfs.items():
            window = df.loc[:day]
            if len(window) < strat_params.trend_period:
                continue
            underlying = build_underlying_snapshot(
                sym,
                window,
                stock_shares=stock_shares.get(sym, 0),
                strategy_params=strat_params,
            )
            intent = route_strategy(regime, underlying, opt)
            if intent in (StrategyIntent.HOLD, StrategyIntent.CLOSE, StrategyIntent.NONE):
                continue
            premium_pct = proxy_premium_pct(intent)
            notional = underlying.close * 100
            premium = notional * premium_pct
            assumed_pnl = premium * 0.6
            cash += assumed_pnl
            trades.append(ProxyTrade(day=day, symbol=sym, intent=intent.value, premium_pct=premium_pct, assumed_pnl=assumed_pnl))

    return trades


def summarize_proxy(trades: list[ProxyTrade]) -> dict:
    if not trades:
        return {'trades': 0, 'total_pnl': 0.0, 'by_intent': {}}
    by_intent: dict[str, int] = {}
    for t in trades:
        by_intent[t.intent] = by_intent.get(t.intent, 0) + 1
    return {
        'trades': len(trades),
        'total_pnl': sum(t.assumed_pnl for t in trades),
        'by_intent': by_intent,
    }
