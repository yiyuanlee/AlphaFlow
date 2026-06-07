"""Options replay using historical chain data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from alphaflow.config import StrategyParams, load_config, params_from_config
from alphaflow.data import fetch_data, slice_ohlcv
from alphaflow.options.chain import (
    days_to_expiry,
    limit_price_from_mid,
    parse_expiry,
    select_expiry,
    select_strike_by_delta,
    spread_limit_credit,
)
from alphaflow.options.chain_data.base import ChainDataProvider, create_chain_provider
from alphaflow.options.chain_data.types import HistoricalOptionQuote
from alphaflow.options.options_config import OptionsTradingConfig, options_config_from_yaml
from alphaflow.options.regime import build_benchmark_regime_lookup
from alphaflow.options.signals import route_strategy, should_close_for_profit
from alphaflow.options.sizing import (
    allow_new_trade,
    csp_max_loss,
    size_cash_secured_put,
    size_covered_call,
    size_vertical_spread,
    vertical_spread_max_loss,
)
from alphaflow.options.types import OptionQuote, StrategyIntent, UnderlyingSnapshot
from alphaflow.options.underlying import build_underlying_snapshot


@dataclass
class ReplayLeg:
    option_ticker: str
    expiry: str
    strike: float
    right: str
    action: str


@dataclass
class OpenReplayPosition:
    symbol: str
    intent: str
    opened_on: str
    expiry: str
    quantity: int
    entry_premium: float
    max_loss: float
    legs: list[ReplayLeg] = field(default_factory=list)


@dataclass
class ChainReplayTrade:
    day: str
    symbol: str
    intent: str
    event: str
    pnl: float
    premium: float = 0.0


def _to_option_quotes(chain: list[HistoricalOptionQuote]) -> list[OptionQuote]:
    return [
        OptionQuote(
            symbol=q.underlying,
            expiry=q.expiry,
            strike=q.strike,
            right=q.right,
            delta=q.delta,
            mid=q.close,
            bid=q.close,
            ask=q.close,
            con_id=0,
        )
        for q in chain
    ]


def _pick_quote(
    provider: ChainDataProvider,
    symbol: str,
    day: str,
    right: str,
    delta_target: float,
    chain_params,
) -> HistoricalOptionQuote | None:
    chain = provider.get_chain(symbol, day, right)
    if not chain:
        return None
    expiries = sorted({q.expiry for q in chain})
    expiry = select_expiry(expiries, chain_params, date.fromisoformat(day))
    if not expiry:
        return None
    day_chain = [q for q in chain if q.expiry == expiry]
    picked = select_strike_by_delta(_to_option_quotes(day_chain), delta_target, right)
    if picked is None:
        return None
    for q in day_chain:
        if q.expiry == picked.expiry and abs(q.strike - picked.strike) < 0.01 and q.right == picked.right:
            return q
    return None


def _settle_short_leg(right: str, strike: float, spot: float, premium: float) -> float:
    if right == 'P':
        intrinsic = max(strike - spot, 0.0)
    else:
        intrinsic = max(spot - strike, 0.0)
    return (premium - intrinsic) * 100


def _settle_spread(intent: str, legs: list[ReplayLeg], spot: float, credit: float) -> float:
    if intent == StrategyIntent.BULL_PUT_SPREAD.value:
        short_k = next(l.strike for l in legs if l.action == 'SELL')
        long_k = next(l.strike for l in legs if l.action == 'BUY')
        short_intr = max(short_k - spot, 0.0)
        long_intr = max(long_k - spot, 0.0)
        spread_loss = max(short_intr - long_intr, 0.0) * 100
        return credit * 100 - spread_loss
    short_k = next(l.strike for l in legs if l.action == 'SELL')
    long_k = next(l.strike for l in legs if l.action == 'BUY')
    short_intr = max(spot - short_k, 0.0)
    long_intr = max(spot - long_k, 0.0)
    spread_loss = max(short_intr - long_intr, 0.0) * 100
    return credit * 100 - spread_loss


def run_chain_replay(
    start: str,
    end: str,
    initial_cash: float = 50_000.0,
    config: dict | None = None,
    provider: ChainDataProvider | None = None,
    symbols: tuple[str, ...] | None = None,
    fast: bool | None = None,
) -> tuple[list[ChainReplayTrade], dict]:
    config = config or load_config()
    opt = options_config_from_yaml(config)
    strat_params, _ = params_from_config(config)
    provider = provider or create_chain_provider(opt.chain_data)
    fast = opt.chain_data.fast_mode if fast is None else fast
    stride = max(opt.chain_data.replay_stride_days, 1) if fast else 1
    symbols = symbols or opt.underlyings

    lookback_start = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime('%Y-%m-%d')
    bench_df = fetch_data(opt.regime.benchmark, lookback_start, end)
    if bench_df is None or bench_df.empty:
        return [], {'error': 'benchmark data unavailable'}
    regime_lookup = build_benchmark_regime_lookup(bench_df, opt.regime)

    underlying_dfs: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = fetch_data(sym, lookback_start, end)
        if df is not None and not df.empty:
            underlying_dfs[sym] = df

    cash = initial_cash
    open_positions: dict[str, OpenReplayPosition] = {}
    trades: list[ChainReplayTrade] = []
    stock_shares = {sym: opt.stock_core.get(sym, 0) for sym in symbols}
    trading_days = [d for d in sorted(regime_lookup) if d >= start]
    entry_days = set(trading_days[::stride])

    for day, regime in sorted(regime_lookup.items()):
        if day < start:
            continue

        # manage open positions
        for sym, pos in list(open_positions.items()):
            if date.fromisoformat(day[:10]) >= parse_expiry(pos.expiry):
                spot = float(underlying_dfs[sym].loc[:day]['close'].iloc[-1]) if sym in underlying_dfs else 0.0
                if len(pos.legs) == 1:
                    leg = pos.legs[0]
                    pnl = _settle_short_leg(leg.right, leg.strike, spot, pos.entry_premium) * pos.quantity
                else:
                    pnl = _settle_spread(pos.intent, pos.legs, spot, pos.entry_premium) * pos.quantity
                cash += pnl
                trades.append(ChainReplayTrade(day, sym, pos.intent, 'expire', pnl, pos.entry_premium))
                del open_positions[sym]
                continue

            if not fast:
                current_value = pos.entry_premium
                if len(pos.legs) == 1 and pos.legs[0].option_ticker:
                    px = provider.get_option_close(pos.legs[0].option_ticker, day)
                    if px is not None:
                        current_value = px
                if should_close_for_profit(pos.entry_premium, current_value, opt.risk.profit_take_pct):
                    pnl = (pos.entry_premium - current_value) * 100 * pos.quantity
                    cash += pnl
                    trades.append(ChainReplayTrade(day, sym, pos.intent, 'take_profit', pnl, pos.entry_premium))
                    del open_positions[sym]

        # open new positions (stride skips most days in fast mode)
        if day not in entry_days:
            continue
        for sym, df in underlying_dfs.items():
            if sym in open_positions:
                continue
            window = df.loc[:day]
            if len(window) < strat_params.trend_period:
                continue
            underlying = build_underlying_snapshot(
                sym, window, stock_shares=stock_shares.get(sym, 0), strategy_params=strat_params,
            )
            intent = route_strategy(regime, underlying, opt)
            if intent in (StrategyIntent.HOLD, StrategyIntent.CLOSE, StrategyIntent.NONE):
                continue

            losses = [p.max_loss for p in open_positions.values() if p.max_loss != float('inf')]
            opened = _try_open_position(provider, opt, sym, day, intent, underlying, cash, losses)
            if opened is None:
                continue
            pos, entry_credit = opened
            open_positions[sym] = pos
            trades.append(ChainReplayTrade(day, sym, intent.value, 'open', 0.0, entry_credit))

    realized = sum(t.pnl for t in trades if t.event != 'open')
    summary = {
        'start': start,
        'end': end,
        'initial_cash': initial_cash,
        'ending_cash': cash,
        'total_pnl': realized,
        'return_pct': (cash - initial_cash) / initial_cash if initial_cash else 0.0,
        'opens': sum(1 for t in trades if t.event == 'open'),
        'closes': sum(1 for t in trades if t.event != 'open'),
        'fast_mode': fast,
        'stride_days': stride,
        'symbols': list(symbols),
        'by_intent': {},
    }
    for t in trades:
        if t.event == 'open':
            summary['by_intent'][t.intent] = summary['by_intent'].get(t.intent, 0) + 1
    return trades, summary


def _try_open_position(
    provider: ChainDataProvider,
    opt: OptionsTradingConfig,
    symbol: str,
    day: str,
    intent: StrategyIntent,
    underlying: UnderlyingSnapshot,
    cash: float,
    losses: list[float],
) -> tuple[OpenReplayPosition, float] | None:
    chain = opt.chain
    exec_params = opt.execution

    if intent == StrategyIntent.CSP:
        quote = _pick_quote(provider, symbol, day, 'P', chain.delta_target_csp, chain)
        if quote is None:
            return None
        qty = size_cash_secured_put(cash, quote.strike, opt.risk.max_contracts_per_symbol)
        if qty <= 0:
            return None
        premium = limit_price_from_mid(quote.close, exec_params.limit_offset_pct, 'SELL')
        pos = OpenReplayPosition(
            symbol=symbol,
            intent=intent.value,
            opened_on=day,
            expiry=quote.expiry,
            quantity=qty,
            entry_premium=premium,
            max_loss=csp_max_loss(quote.strike, qty),
            legs=[ReplayLeg(quote.option_ticker, quote.expiry, quote.strike, 'P', 'SELL')],
        )
        return pos, premium

    if intent == StrategyIntent.COVERED_CALL:
        qty = size_covered_call(underlying.stock_shares, underlying.short_calls, opt.risk.max_contracts_per_symbol)
        if qty <= 0:
            return None
        quote = _pick_quote(provider, symbol, day, 'C', chain.delta_target_cc, chain)
        if quote is None:
            return None
        premium = limit_price_from_mid(quote.close, exec_params.limit_offset_pct, 'SELL')
        pos = OpenReplayPosition(
            symbol=symbol,
            intent=intent.value,
            opened_on=day,
            expiry=quote.expiry,
            quantity=qty,
            entry_premium=premium,
            max_loss=float('inf'),
            legs=[ReplayLeg(quote.option_ticker, quote.expiry, quote.strike, 'C', 'SELL')],
        )
        return pos, premium

    if intent == StrategyIntent.BULL_PUT_SPREAD:
        short_q = _pick_quote(provider, symbol, day, 'P', chain.delta_target_spread, chain)
        if short_q is None:
            return None
        long_strike = short_q.strike - chain.spread_width
        long_q = _nearest_strike(provider.get_chain(symbol, day, 'P'), short_q.expiry, long_strike)
        if long_q is None:
            return None
        qty = size_vertical_spread(chain.spread_width, opt.risk.max_loss_per_trade, opt.risk.max_contracts_per_symbol)
        if qty <= 0:
            return None
        credit = spread_limit_credit(short_q.close, long_q.close, exec_params.limit_offset_pct)
        pos = OpenReplayPosition(
            symbol=symbol,
            intent=intent.value,
            opened_on=day,
            expiry=short_q.expiry,
            quantity=qty,
            entry_premium=credit,
            max_loss=vertical_spread_max_loss(chain.spread_width, qty),
            legs=[
                ReplayLeg(short_q.option_ticker, short_q.expiry, short_q.strike, 'P', 'SELL'),
                ReplayLeg(long_q.option_ticker, long_q.expiry, long_q.strike, 'P', 'BUY'),
            ],
        )
        return pos, credit

    if intent == StrategyIntent.BEAR_CALL_SPREAD:
        short_q = _pick_quote(provider, symbol, day, 'C', chain.delta_target_spread, chain)
        if short_q is None:
            return None
        long_strike = short_q.strike + chain.spread_width
        long_q = _nearest_strike(provider.get_chain(symbol, day, 'C'), short_q.expiry, long_strike)
        if long_q is None:
            return None
        qty = size_vertical_spread(chain.spread_width, opt.risk.max_loss_per_trade, opt.risk.max_contracts_per_symbol)
        if qty <= 0:
            return None
        credit = spread_limit_credit(short_q.close, long_q.close, exec_params.limit_offset_pct)
        pos = OpenReplayPosition(
            symbol=symbol,
            intent=intent.value,
            opened_on=day,
            expiry=short_q.expiry,
            quantity=qty,
            entry_premium=credit,
            max_loss=vertical_spread_max_loss(chain.spread_width, qty),
            legs=[
                ReplayLeg(short_q.option_ticker, short_q.expiry, short_q.strike, 'C', 'SELL'),
                ReplayLeg(long_q.option_ticker, long_q.expiry, long_q.strike, 'C', 'BUY'),
            ],
        )
        return pos, credit

    return None


def _nearest_strike(chain: list[HistoricalOptionQuote], expiry: str, target: float) -> HistoricalOptionQuote | None:
    candidates = [q for q in chain if q.expiry == expiry]
    if not candidates:
        return None
    return min(candidates, key=lambda q: abs(q.strike - target))
