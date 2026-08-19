"""Strictly causal minute-bar backtest for the SPY opening-range strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import inf
from typing import TypedDict

import pandas as pd

from alphaflow.scalping.clock import ET, XnysClock
from alphaflow.scalping.config import ScalpConfig
from alphaflow.scalping.strategy import compute_features, position_size, risk_per_share, signal_at
from alphaflow.scalping.types import (
    ScalpBacktestResult,
    ScalpBacktestTrade,
    ScalpDirection,
    ScalpSignal,
)


@dataclass
class _OpenTrade:
    signal: ScalpSignal
    entry_index: int
    entry_time: datetime
    quantity: int
    raw_entry: float
    entry_price: float
    risk_per_share: float
    stop_price: float
    target_price: float
    entry_commission: float
    entry_slippage: float


@dataclass
class _DayState:
    opening_equity: float
    realized: float = 0.0
    entries: int = 0
    consecutive_losses: int = 0
    locked: bool = False
    cooldown_until: datetime | None = None
    rearmed_long: bool = True
    rearmed_short: bool = True


class ScalpValidationResult(TypedDict):
    passed: bool
    full: ScalpBacktestResult
    out_of_sample: ScalpBacktestResult


def run_backtest(
    bars: pd.DataFrame,
    config: ScalpConfig,
    *,
    initial_equity: float | None = None,
    minimum_trades: int | None = None,
) -> ScalpBacktestResult:
    """Backtest completed RTH bars; signals at bar close can only fill at the next open."""
    if bars.empty:
        return _empty_result(initial_equity or config.backtest.initial_equity, "no minute bars")
    features = compute_features(bars, config.strategy)
    capital = initial_equity or config.backtest.initial_equity
    starting_capital = capital
    trades: list[ScalpBacktestTrade] = []
    clock = XnysClock()
    state: _DayState | None = None
    active_session: date | None = None
    position: _OpenTrade | None = None
    pending_signal: ScalpSignal | None = None
    pending_daily_flatten = False
    equity_peak = capital
    max_drawdown = 0.0
    sessions: set[date] = set()

    for index in range(len(features)):
        row = features.iloc[index]
        timestamp = features.index[index].to_pydatetime().astimezone(timezone.utc)
        session_date = row["session_date"]
        sessions.add(session_date)

        if session_date != active_session:
            if position is not None:
                raise RuntimeError("backtest reached a new session with an overnight position")
            active_session = session_date
            state = _DayState(opening_equity=capital)
            pending_signal = None
            pending_daily_flatten = False

        assert state is not None
        schedule = clock.schedule(session_date)
        if schedule is None:
            continue
        force_flat_at = schedule.force_flat_at(config.execution.force_flat_minutes_before_close)

        # A signal is intentionally delayed until this later bar's open.
        if pending_signal is not None and position is None and not state.locked:
            if pending_signal.session_date == session_date:
                position = _enter_trade(pending_signal, index, timestamp, float(row["open"]), state, config)
                if position is not None:
                    state.entries += 1
            pending_signal = None

        if position is not None:
            exit_reason: str | None = None
            raw_exit = 0.0
            # Time/daily/closing exits execute at a later available bar open before bracket matching.
            if pending_daily_flatten:
                exit_reason, raw_exit = "DAILY_LOSS", float(row["open"])
            elif timestamp >= force_flat_at:
                exit_reason, raw_exit = "SESSION_FLAT", float(row["open"])
            elif timestamp >= position.entry_time + timedelta(minutes=config.strategy.max_holding_minutes):
                exit_reason, raw_exit = "TIME", float(row["open"])
            else:
                exit_reason, raw_exit = _match_bracket(position, float(row["high"]), float(row["low"]))

            if exit_reason is not None:
                trade = _close_trade(position, timestamp, raw_exit, exit_reason, config)
                trades.append(trade)
                capital += trade.net_pnl
                state.realized += trade.net_pnl
                state.consecutive_losses = state.consecutive_losses + 1 if trade.net_pnl < 0 else 0
                state.cooldown_until = timestamp + timedelta(minutes=config.strategy.cooldown_minutes)
                if position.signal.direction is ScalpDirection.LONG:
                    state.rearmed_long = False
                else:
                    state.rearmed_short = False
                position = None
                pending_daily_flatten = False
                if state.consecutive_losses >= config.strategy.max_consecutive_losses:
                    state.locked = True

        # Mark-to-market using only this completed bar's close.
        unrealized = _unrealized(position, float(row["close"])) if position else 0.0
        marked_equity = capital + unrealized
        equity_peak = max(equity_peak, marked_equity)
        max_drawdown = max(max_drawdown, (equity_peak - marked_equity) / equity_peak if equity_peak else 0.0)
        day_pnl = state.realized + unrealized
        if day_pnl <= -(state.opening_equity * config.risk.daily_loss_limit_pct):
            state.locked = True
            pending_signal = None
            if position is not None:
                pending_daily_flatten = True

        inside_range = not pd.isna(row.get("opening_range_low")) and float(row["opening_range_low"]) <= float(
            row["close"]
        ) <= float(row["opening_range_high"])
        if inside_range:
            state.rearmed_long = True
            state.rearmed_short = True

        if position is None and not state.locked and index + 1 < len(features):
            candidate = signal_at(features, index, config.strategy)
            if candidate and _entry_allowed(candidate, timestamp, state, config):
                next_session = features.iloc[index + 1]["session_date"]
                if next_session == session_date and timestamp < force_flat_at:
                    pending_signal = candidate

    if position is not None:
        # A malformed/incomplete data set must not silently value an overnight position.
        last_timestamp = features.index[-1].to_pydatetime().astimezone(timezone.utc)
        trade = _close_trade(position, last_timestamp, float(features.iloc[-1]["close"]), "DATA_END", config)
        trades.append(trade)
        capital += trade.net_pnl

    required = minimum_trades if minimum_trades is not None else config.backtest.minimum_total_trades
    result = _summarize(
        trades,
        sessions=len(sessions),
        initial_equity=starting_capital,
        final_equity=capital,
        max_drawdown_pct=max_drawdown * 100.0,
        minimum_trades=required,
        config=config,
    )
    return result


def split_validation_window(
    bars: pd.DataFrame,
    config: ScalpConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split the last configured complete month as out-of-sample."""
    if bars.empty:
        return bars.copy(), bars.copy()
    dates = pd.Index(bars.index.tz_convert(ET).date)
    last_date = max(dates)
    oos_start = date(last_date.year, last_date.month, 1)
    mask = dates >= oos_start
    return bars.loc[~mask].copy(), bars.loc[mask].copy()


def validate_three_month_backtest(bars: pd.DataFrame, config: ScalpConfig) -> ScalpValidationResult:
    _verification_bars, out_of_sample_bars = split_validation_window(bars, config)
    full = run_backtest(bars, config, minimum_trades=config.backtest.minimum_total_trades)
    out_of_sample = run_backtest(
        out_of_sample_bars,
        config,
        minimum_trades=config.backtest.minimum_out_of_sample_trades,
    )
    return {"passed": full.passed and out_of_sample.passed, "full": full, "out_of_sample": out_of_sample}


def _entry_allowed(
    signal: ScalpSignal,
    timestamp: datetime,
    state: _DayState,
    config: ScalpConfig,
) -> bool:
    if state.entries >= config.strategy.max_entries_per_day:
        return False
    if state.cooldown_until is not None and timestamp < state.cooldown_until:
        return False
    return state.rearmed_long if signal.direction is ScalpDirection.LONG else state.rearmed_short


def _enter_trade(
    signal: ScalpSignal,
    index: int,
    timestamp: datetime,
    raw_open: float,
    state: _DayState,
    config: ScalpConfig,
) -> _OpenTrade | None:
    slippage_rate = config.backtest.adverse_slippage_bps / 10_000.0
    direction_factor = 1.0 if signal.direction is ScalpDirection.LONG else -1.0
    entry_price = raw_open * (1.0 + direction_factor * slippage_rate)
    per_share = risk_per_share(entry_price, signal.atr14, config.risk)
    if per_share is None:
        return None
    quantity = position_size(
        entry_price=entry_price,
        per_share_risk=per_share,
        opening_net_liquidation=state.opening_equity,
        available_funds=max(0.0, state.opening_equity + state.realized),
        config=config.risk,
    )
    if quantity <= 0:
        return None
    commission = max(config.backtest.minimum_commission, quantity * config.backtest.commission_per_share)
    if signal.direction is ScalpDirection.LONG:
        stop = entry_price - per_share
        target = entry_price + config.risk.target_multiple * per_share
    else:
        stop = entry_price + per_share
        target = entry_price - config.risk.target_multiple * per_share
    return _OpenTrade(
        signal=signal,
        entry_index=index,
        entry_time=timestamp,
        quantity=quantity,
        raw_entry=raw_open,
        entry_price=entry_price,
        risk_per_share=per_share,
        stop_price=stop,
        target_price=target,
        entry_commission=commission,
        entry_slippage=abs(entry_price - raw_open) * quantity,
    )


def _match_bracket(position: _OpenTrade, high: float, low: float) -> tuple[str | None, float]:
    if position.signal.direction is ScalpDirection.LONG:
        stop_hit = low <= position.stop_price
        target_hit = high >= position.target_price
    else:
        stop_hit = high >= position.stop_price
        target_hit = low <= position.target_price
    # Conservative ambiguity rule: a stop wins whenever both touch in one bar.
    if stop_hit:
        return "STOP", position.stop_price
    if target_hit:
        return "TARGET", position.target_price
    return None, 0.0


def _close_trade(
    position: _OpenTrade,
    timestamp: datetime,
    raw_exit: float,
    reason: str,
    config: ScalpConfig,
) -> ScalpBacktestTrade:
    slippage_rate = config.backtest.adverse_slippage_bps / 10_000.0
    direction_factor = 1.0 if position.signal.direction is ScalpDirection.LONG else -1.0
    exit_price = raw_exit * (1.0 - direction_factor * slippage_rate)
    gross = direction_factor * (raw_exit - position.raw_entry) * position.quantity
    exit_commission = max(
        config.backtest.minimum_commission,
        position.quantity * config.backtest.commission_per_share,
    )
    commission = position.entry_commission + exit_commission
    exit_slippage = abs(exit_price - raw_exit) * position.quantity
    slippage = position.entry_slippage + exit_slippage
    net = direction_factor * (exit_price - position.entry_price) * position.quantity - commission
    return ScalpBacktestTrade(
        session_date=position.signal.session_date,
        direction=position.signal.direction,
        signal_time_utc=position.signal.bar_time_utc,
        entry_time_utc=position.entry_time,
        exit_time_utc=timestamp,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        risk_per_share=position.risk_per_share,
        gross_pnl=gross,
        commission=commission,
        slippage=slippage,
        net_pnl=net,
        exit_reason=reason,
    )


def _unrealized(position: _OpenTrade | None, price: float) -> float:
    if position is None:
        return 0.0
    factor = 1.0 if position.signal.direction is ScalpDirection.LONG else -1.0
    return factor * (price - position.entry_price) * position.quantity - position.entry_commission


def _summarize(
    trades: list[ScalpBacktestTrade],
    *,
    sessions: int,
    initial_equity: float,
    final_equity: float,
    max_drawdown_pct: float,
    minimum_trades: int,
    config: ScalpConfig,
) -> ScalpBacktestResult:
    profits = sum(trade.net_pnl for trade in trades if trade.net_pnl > 0)
    losses = abs(sum(trade.net_pnl for trade in trades if trade.net_pnl < 0))
    profit_factor = profits / losses if losses else (inf if profits else 0.0)
    win_rate = sum(1 for trade in trades if trade.net_pnl > 0) / len(trades) if trades else 0.0
    failures: list[str] = []
    if len(trades) < minimum_trades:
        failures.append(f"requires at least {minimum_trades} trades, got {len(trades)}")
    if final_equity <= initial_equity:
        failures.append("net result is not profitable after costs")
    if profit_factor < config.backtest.minimum_profit_factor:
        failures.append(f"profit factor {profit_factor:.3f} is below {config.backtest.minimum_profit_factor:.2f}")
    if max_drawdown_pct > config.backtest.maximum_drawdown_pct:
        failures.append(f"max drawdown {max_drawdown_pct:.3f}% exceeds {config.backtest.maximum_drawdown_pct:.2f}%")
    return ScalpBacktestResult(
        start_date=min((trade.session_date for trade in trades), default=None),
        end_date=max((trade.session_date for trade in trades), default=None),
        initial_equity=initial_equity,
        final_equity=final_equity,
        trades=tuple(trades),
        net_profit=final_equity - initial_equity,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        sessions=sessions,
        passed=not failures,
        failures=tuple(failures),
    )


def _empty_result(initial_equity: float, reason: str) -> ScalpBacktestResult:
    return ScalpBacktestResult(
        start_date=None,
        end_date=None,
        initial_equity=initial_equity,
        final_equity=initial_equity,
        trades=(),
        net_profit=0.0,
        profit_factor=0.0,
        max_drawdown_pct=0.0,
        win_rate=0.0,
        sessions=0,
        passed=False,
        failures=(reason,),
    )
