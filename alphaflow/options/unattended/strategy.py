"""Pure QQQ covered-call signal, quote, and idempotency helpers."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timezone

import pandas as pd

from alphaflow.indicators import ema_backtrader, wilder_smooth
from alphaflow.options.chain import days_to_expiry

from .config import CoveredCallConfig, SafeExecutionConfig
from .types import DailyBar, OptionMarketQuote, TradeIntent


def completed_bar_bullish(bars: list[DailyBar], trend_period: int) -> tuple[bool, float, float]:
    if len(bars) < trend_period:
        return False, 0.0, 0.0
    closes = pd.Series([bar.close for bar in bars], dtype=float)
    ema = ema_backtrader(closes, trend_period)
    last_close = float(closes.iloc[-1])
    last_ema = float(ema.iloc[-1])
    return bool(math.isfinite(last_close) and math.isfinite(last_ema) and last_close > last_ema), last_close, last_ema


def completed_bar_diagnostics(bars: list[DailyBar], trend_period: int) -> dict[str, float | bool | None]:
    """Return the decision inputs plus audit-only RSI/ADX values."""
    bullish, close, ema = completed_bar_bullish(bars, trend_period)
    diagnostics: dict[str, float | bool | None] = {
        "bullish": bullish,
        "close": close,
        "ema200": ema,
        "rsi14": None,
        "adx14": None,
    }
    if len(bars) < 28:
        return diagnostics

    closes = pd.Series([bar.close for bar in bars], dtype=float)
    delta = closes.diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)
    avg_gain = wilder_smooth(gains, 14)
    avg_loss = wilder_smooth(losses, 14).replace(0, 0.001)
    rsi = float((100.0 - 100.0 / (1.0 + avg_gain / avg_loss)).iloc[-1])
    diagnostics["rsi14"] = rsi if math.isfinite(rsi) else None

    if not all(bar.high > 0 and bar.low > 0 for bar in bars):
        return diagnostics
    highs = pd.Series([bar.high for bar in bars], dtype=float)
    lows = pd.Series([bar.low for bar in bars], dtype=float)
    previous_close = closes.shift(1)
    true_range = pd.concat(
        [highs - lows, (highs - previous_close).abs(), (lows - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = wilder_smooth(true_range, 14)
    up_move = highs.diff()
    down_move = -lows.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    plus_di = 100.0 * wilder_smooth(plus_dm, 14) / atr
    minus_di = 100.0 * wilder_smooth(minus_dm, 14) / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 0.001)
    valid_dx = dx.dropna().reset_index(drop=True)
    adx = float(wilder_smooth(valid_dx, 14).iloc[-1]) if len(valid_dx) >= 14 else math.nan
    diagnostics["adx14"] = adx if math.isfinite(adx) else None
    return diagnostics


def quote_age_seconds(quote: OptionMarketQuote, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(quote.timestamp)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return max((now.astimezone(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds(), 0.0)


def quote_is_safe(
    quote: OptionMarketQuote,
    spot: float,
    strategy: CoveredCallConfig,
    execution: SafeExecutionConfig,
    *,
    as_of: date | None = None,
    now: datetime | None = None,
) -> bool:
    if quote.symbol != strategy.symbol or quote.right.upper() != "C":
        return False
    if not all(math.isfinite(value) for value in (spot, quote.strike, quote.delta, quote.bid, quote.ask)):
        return False
    if quote.strike <= spot or quote.multiplier != 100:
        return False
    dte = days_to_expiry(quote.expiry, as_of)
    if not strategy.dte_min <= dte <= strategy.dte_max:
        return False
    if quote.bid <= 0 or quote.ask <= 0 or quote.ask < quote.bid or quote.mid <= 0:
        return False
    if quote.delayed and not execution.allow_delayed_data:
        return False
    if quote_age_seconds(quote, now) > execution.quote_max_age_seconds:
        return False
    if (quote.ask - quote.bid) / quote.mid > execution.max_bid_ask_spread_pct:
        return False
    return 0 < quote.delta < 1


def select_covered_call_quote(
    quotes: list[OptionMarketQuote],
    spot: float,
    strategy: CoveredCallConfig,
    execution: SafeExecutionConfig,
    *,
    as_of: date | None = None,
    now: datetime | None = None,
) -> OptionMarketQuote | None:
    as_of = as_of or datetime.now(timezone.utc).date()
    safe = [q for q in quotes if quote_is_safe(q, spot, strategy, execution, as_of=as_of, now=now)]
    if not safe:
        return None
    return min(
        safe,
        key=lambda q: (abs(q.delta - strategy.delta_target), days_to_expiry(q.expiry, as_of), q.strike),
    )


def make_intent(
    *,
    purpose: str,
    action: str,
    quote: OptionMarketQuote,
    quantity: int,
    limit_price: float,
    session_date: str,
    reason: str,
) -> TradeIntent:
    raw = ":".join(
        [purpose, action, quote.symbol, quote.expiry, f"{quote.strike:.4f}", quote.right, session_date, reason]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return TradeIntent(
        intent_id=raw,
        order_ref=f"AFV11-{digest}",
        purpose=purpose,
        action=action,
        symbol=quote.symbol,
        quantity=quantity,
        limit_price=round(limit_price, 2),
        session_date=session_date,
        reason=reason,
        expiry=quote.expiry,
        strike=quote.strike,
        right=quote.right,
        con_id=quote.con_id,
    )


def exit_reason(entry_credit: float, ask: float, expiry: str, force_exit_dte: int, as_of: date) -> str | None:
    if entry_credit > 0 and ask > 0 and ask <= entry_credit * 0.5:
        return "profit_take_50pct"
    if days_to_expiry(expiry, as_of) <= force_exit_dte:
        return "force_exit_dte"
    return None


def next_limit_price(current: float, action: str, tick_size: float, boundary: float | None = None) -> float:
    direction = -1 if action.upper() == "SELL" else 1
    candidate = max(current + direction * tick_size, tick_size)
    if boundary is not None:
        candidate = max(candidate, boundary) if direction < 0 else min(candidate, boundary)
    return round(candidate, 2)
