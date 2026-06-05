"""Daily scanner replay proxy for hot-stock strategy validation.

TOP_PERC_GAIN is approximated by ranking a fixed liquid universe by daily % change.
VWAP filter uses close > (high+low)/2 on daily bars (session-strength proxy).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from alphaflow.data import fetch_data
from alphaflow.hot_config import HotTradingConfig, hot_config_from_yaml
from alphaflow.hot_indicators import compute_daily_replay_indicators
from alphaflow.hot_market import is_market_bullish
from alphaflow.hot_signals import calc_hot_position_size, check_hot_entry, check_hot_exit, hold_days


@dataclass
class ReplayPosition:
    symbol: str
    entry_date: str
    entry_price: float
    shares: int


@dataclass
class ReplayTrade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    exit_reason: str


@dataclass
class ReplayResult:
    trades: list[ReplayTrade] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    signal_stats: dict[str, int] = field(default_factory=dict)
    final_equity: float = 0.0
    total_return_pct: float = 0.0


def _replay_universe(config: dict[str, Any], hot: HotTradingConfig) -> list[str]:
    tickers = config.get('tickers', [])
    exclude = set(hot.exclude_symbols) | {hot.market.benchmark}
    return [t for t in tickers if t not in exclude]


def scanner_proxy_daily(
    ohlcv: dict[str, pd.DataFrame],
    day: pd.Timestamp,
    hot: HotTradingConfig,
) -> list[str]:
    rows: list[tuple[str, float]] = []
    for sym, df in ohlcv.items():
        if day not in df.index:
            continue
        loc = df.index.get_loc(day)
        if loc == 0:
            continue
        prev = df.iloc[loc - 1]
        today = df.iloc[loc]
        if float(today['close']) < hot.scanner.min_price:
            continue
        if float(today['volume']) < hot.scanner.min_volume:
            continue
        pct = float(today['close'] / prev['close'] - 1.0)
        rows.append((sym, pct))
    rows.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in rows[: hot.scanner.max_results]]


def run_daily_replay(config: dict[str, Any], hot: HotTradingConfig | None = None) -> ReplayResult:
    hot = hot or hot_config_from_yaml(config)
    universe = _replay_universe(config, hot)
    warmup_start = (
        pd.Timestamp(hot.replay.start_date) - pd.Timedelta(days=max(hot.entry.slow_ema, hot.market.trend_period) + 30)
    ).strftime('%Y-%m-%d')

    ohlcv: dict[str, pd.DataFrame] = {}
    indicators: dict[str, pd.DataFrame] = {}
    for sym in universe:
        df = fetch_data(sym, warmup_start, hot.replay.end_date)
        if df is None or len(df) < hot.entry.slow_ema + 5:
            continue
        ohlcv[sym] = df
        indicators[sym] = compute_daily_replay_indicators(df, hot.entry)

    if not ohlcv:
        return ReplayResult()

    start = pd.Timestamp(hot.replay.start_date)
    end = pd.Timestamp(hot.replay.end_date)
    trading_days = sorted({d for df in ohlcv.values() for d in df.index if start <= d <= end})

    cash = float(hot.replay.initial_cash)
    positions: dict[str, ReplayPosition] = {}
    trades: list[ReplayTrade] = []
    signal_stats: dict[str, int] = {}
    equity_curve: list[dict[str, Any]] = []

    for day in trading_days:
        day_date = day.date() if hasattr(day, 'date') else day
        market_ok, market_info = is_market_bullish(hot.market, as_of=day_date, lookback_start=warmup_start)

        # exits
        for sym in list(positions.keys()):
            pos = positions[sym]
            ind_df = indicators.get(sym)
            if ind_df is None or day not in ind_df.index:
                continue
            row = ind_df.loc[day]
            px = float(row['close'])
            reason = check_hot_exit(
                entry_date=pos.entry_date,
                entry_price=pos.entry_price,
                current_price=px,
                ema_fast=float(row['ema_fast']),
                ema_slow=float(row['ema_slow']),
                vwap=float(row['vwap']),
                entry=hot.entry,
                exit_params=hot.exit,
                position_params=hot.position,
                as_of=day_date,
            )
            if reason:
                proceeds = px * pos.shares * (1 - hot.replay.commission)
                cost = pos.entry_price * pos.shares * (1 + hot.replay.commission)
                pnl = proceeds - cost
                trades.append(ReplayTrade(
                    symbol=sym,
                    entry_date=pos.entry_date,
                    exit_date=str(day_date),
                    entry_price=pos.entry_price,
                    exit_price=px,
                    shares=pos.shares,
                    pnl=pnl,
                    pnl_pct=(px / pos.entry_price - 1) * 100,
                    exit_reason=reason,
                ))
                cash += proceeds
                del positions[sym]

        exposure = sum(p.entry_price * p.shares for p in positions.values())
        equity = cash + sum(
            float(indicators[s].loc[day, 'close']) * p.shares
            for s, p in positions.items()
            if s in indicators and day in indicators[s].index
        )
        equity_curve.append({'date': str(day_date), 'equity': equity})

        if not market_ok:
            signal_stats['market_not_bullish'] = signal_stats.get('market_not_bullish', 0) + 1
            continue

        if len(positions) >= hot.position.max_positions:
            continue

        candidates = scanner_proxy_daily(ohlcv, day, hot)
        for sym in candidates:
            if sym in positions:
                continue
            if len(positions) >= hot.position.max_positions:
                break
            ind_df = indicators.get(sym)
            if ind_df is None or day not in ind_df.index:
                continue
            row = ind_df.loc[day]
            px = float(row['close'])
            ok, reason = check_hot_entry(
                close=px,
                ema_fast=float(row['ema_fast']),
                ema_slow=float(row['ema_slow']),
                rsi=float(row['rsi']),
                vwap=float(row['vwap']),
                golden_cross=bool(row['golden_cross']),
                adx=float(row['adx']) if pd.notna(row['adx']) else float('nan'),
                rel_volume=float(row['rel_volume']) if pd.notna(row['rel_volume']) else float('nan'),
                market_bullish=market_ok,
                params=hot.entry,
            )
            if not ok:
                signal_stats[reason] = signal_stats.get(reason, 0) + 1
                continue

            size = calc_hot_position_size(
                price=px,
                net_liquidation=equity,
                stock_exposure=exposure,
                risk=hot.risk,
                position=hot.position,
                stop_loss_pct=hot.exit.stop_loss_pct,
            )
            if size <= 0:
                signal_stats['size_zero'] = signal_stats.get('size_zero', 0) + 1
                continue

            cost = px * size * (1 + hot.replay.commission)
            if cost > cash:
                signal_stats['insufficient_cash'] = signal_stats.get('insufficient_cash', 0) + 1
                continue

            cash -= cost
            exposure += px * size
            positions[sym] = ReplayPosition(
                symbol=sym,
                entry_date=str(day_date),
                entry_price=px,
                shares=size,
            )
            signal_stats['entries'] = signal_stats.get('entries', 0) + 1

    final_equity = equity_curve[-1]['equity'] if equity_curve else hot.replay.initial_cash
    total_return = (final_equity / hot.replay.initial_cash - 1) * 100 if hot.replay.initial_cash else 0.0
    return ReplayResult(
        trades=trades,
        equity_curve=equity_curve,
        signal_stats=signal_stats,
        final_equity=final_equity,
        total_return_pct=total_return,
    )


def summarize_replay(result: ReplayResult) -> dict[str, Any]:
    if not result.trades:
        return {
            'trades': 0,
            'total_return_pct': result.total_return_pct,
            'final_equity': result.final_equity,
            'signal_stats': result.signal_stats,
        }

    wins = [t for t in result.trades if t.pnl > 0]
    losses = [t for t in result.trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses)) or 1e-9

    eq = pd.Series([p['equity'] for p in result.equity_curve])
    peak = eq.cummax()
    dd = (eq - peak) / peak
    max_dd = float(dd.min() * 100) if len(dd) else 0.0

    return {
        'trades': len(result.trades),
        'win_rate_pct': len(wins) / len(result.trades) * 100,
        'profit_factor': gross_win / gross_loss,
        'avg_pnl_pct': sum(t.pnl_pct for t in result.trades) / len(result.trades),
        'total_return_pct': result.total_return_pct,
        'final_equity': result.final_equity,
        'max_drawdown_pct': max_dd,
        'signal_stats': result.signal_stats,
        'exit_reasons': pd.Series([t.exit_reason for t in result.trades]).value_counts().to_dict(),
    }
