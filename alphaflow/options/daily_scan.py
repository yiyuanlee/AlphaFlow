"""Offline daily signal scan — no IBKR connection required."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from alphaflow.config import StrategyParams, load_config, params_from_config
from alphaflow.data import fetch_data
from alphaflow.options.chain_replay import _pick_quote
from alphaflow.options.chain_data.base import create_chain_provider
from alphaflow.options.journal import log_options_event
from alphaflow.options.options_config import OptionsTradingConfig, options_config_from_yaml
from alphaflow.options.regime import RegimeSnapshot, compute_regime_from_df
from alphaflow.options.signals import route_strategy
from alphaflow.options.state import load_positions
from alphaflow.options.types import StrategyIntent
from alphaflow.options.underlying import build_underlying_snapshot


@dataclass
class SymbolScan:
    symbol: str
    intent: str
    close: float
    shares: int
    short_calls: int
    short_puts: int
    strike: float | None = None
    expiry: str | None = None
    est_premium: float | None = None
    delta: float | None = None
    reason: str = ''


@dataclass
class DailyScanReport:
    as_of: str
    regime: RegimeSnapshot
    symbols: list[SymbolScan]
    open_positions: int


def _right_for_intent(intent: StrategyIntent) -> str | None:
    if intent in (StrategyIntent.CSP, StrategyIntent.BULL_PUT_SPREAD):
        return 'P'
    if intent in (StrategyIntent.COVERED_CALL, StrategyIntent.BEAR_CALL_SPREAD):
        return 'C'
    return None


def _delta_target(intent: StrategyIntent, opt: OptionsTradingConfig) -> float:
    if intent == StrategyIntent.COVERED_CALL:
        return opt.chain.delta_target_cc
    if intent == StrategyIntent.CSP:
        return opt.chain.delta_target_csp
    return opt.chain.delta_target_spread


def run_daily_scan(
    config: dict | None = None,
    as_of: str | None = None,
    use_chain: bool = True,
) -> DailyScanReport:
    config = config or load_config()
    opt = options_config_from_yaml(config)
    strat_params, _ = params_from_config(config)
    as_of = as_of or date.today().isoformat()
    lookback = '2018-01-01'

    bench = fetch_data(opt.regime.benchmark, lookback, as_of)
    if bench is None or bench.empty:
        raise RuntimeError(f'无法获取 {opt.regime.benchmark} 行情')
    regime = compute_regime_from_df(bench.loc[:as_of], opt.regime)

    positions = load_positions()
    open_by_symbol = {s: 0 for s in opt.underlyings}
    for pos in positions.values():
        if pos.status == 'open' and pos.symbol in open_by_symbol:
            open_by_symbol[pos.symbol] += 1

    provider = create_chain_provider(opt.chain_data) if use_chain else None
    rows: list[SymbolScan] = []

    for symbol in opt.underlyings:
        df = fetch_data(symbol, lookback, as_of)
        if df is None or df.empty:
            continue
        shares = opt.stock_core.get(symbol, 0)
        has_open = open_by_symbol.get(symbol, 0) > 0
        underlying = build_underlying_snapshot(
            symbol,
            df.loc[:as_of],
            stock_shares=shares,
            strategy_params=strat_params,
        )
        intent = route_strategy(regime, underlying, opt, has_open_option=has_open)
        row = SymbolScan(
            symbol=symbol,
            intent=intent.value,
            close=underlying.close,
            shares=shares,
            short_calls=underlying.short_calls,
            short_puts=underlying.short_puts,
        )
        if use_chain and provider and intent not in (
            StrategyIntent.HOLD, StrategyIntent.CLOSE, StrategyIntent.NONE,
        ):
            right = _right_for_intent(intent)
            if right:
                quote = _pick_quote(provider, symbol, as_of, right, _delta_target(intent, opt), opt.chain)
                if quote:
                    row.strike = quote.strike
                    row.expiry = quote.expiry
                    row.est_premium = quote.close
                    row.delta = quote.delta
                else:
                    row.reason = 'no_chain_quote'
        rows.append(row)

    report = DailyScanReport(
        as_of=as_of,
        regime=regime,
        symbols=rows,
        open_positions=sum(1 for p in positions.values() if p.status == 'open'),
    )
    log_options_event(
        'daily_scan',
        as_of=as_of,
        regime=regime.regime.value,
        bullish=regime.bullish,
        symbols=[s.__dict__ for s in rows],
    )
    return report


def format_daily_scan(report: DailyScanReport) -> str:
    lines = [
        f'=== Options Daily Scan ({report.as_of}) ===',
        f'QQQ Regime: {report.regime.regime.value} | close={report.regime.close:.2f} '
        f'adx={report.regime.adx:.1f} rsi={report.regime.rsi:.1f} bullish={report.regime.bullish}',
        f'Open positions (state file): {report.open_positions}',
        '',
        f'{"Symbol":<6} {"Intent":<18} {"Close":>8} {"Strike":>8} {"Prem":>6} {"Delta":>6}',
        '-' * 58,
    ]
    for s in report.symbols:
        strike = f'{s.strike:.0f}' if s.strike else '-'
        prem = f'{s.est_premium:.2f}' if s.est_premium else '-'
        delta = f'{s.delta:.2f}' if s.delta else '-'
        lines.append(
            f'{s.symbol:<6} {s.intent:<18} {s.close:>8.2f} {strike:>8} {prem:>6} {delta:>6}',
        )
    lines.append('')
    lines.append('无需 IBKR。实盘下单: python scripts/live/ibkr_options.py --live [--dry-run]')
    return '\n'.join(lines)
