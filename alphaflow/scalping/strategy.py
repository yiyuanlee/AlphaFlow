"""Pure SPY opening-range signal, risk, and bracket calculations."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

import pandas as pd

from alphaflow.indicators import _true_range, ema_backtrader, wilder_smooth
from alphaflow.scalping.clock import ET, in_time_window, parse_hhmm
from alphaflow.scalping.config import OrbStrategyConfig, ScalpExecutionConfig, ScalpRiskConfig
from alphaflow.scalping.types import BracketIntent, ScalpDirection, ScalpSignal, StockQuote

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def compute_features(bars: pd.DataFrame, config: OrbStrategyConfig) -> pd.DataFrame:
    """Compute continuous RTH EMA/ATR and session-reset VWAP/relative volume/ORB."""
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars must use a timezone-aware DatetimeIndex")
    if bars.index.tz is None:
        raise ValueError("bars index must be timezone-aware")
    missing = [column for column in REQUIRED_COLUMNS if column not in bars.columns]
    if missing:
        raise ValueError(f"bars missing columns: {', '.join(missing)}")

    out = bars.sort_index().copy()
    out.index = out.index.tz_convert("UTC")
    local = out.index.tz_convert(ET)
    out["session_date"] = pd.Series(local.date, index=out.index)
    out["local_time"] = pd.Series(local.time, index=out.index)

    out["ema_fast"] = ema_backtrader(out["close"], config.ema_fast)
    out["ema_slow"] = ema_backtrader(out["close"], config.ema_slow)
    out["atr14"] = wilder_smooth(_true_range(out["high"], out["low"], out["close"]), config.atr_period)

    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    groups = out.groupby("session_date", sort=False)
    cumulative_volume = groups["volume"].cumsum().replace(0, pd.NA)
    out["vwap"] = (typical * out["volume"]).groupby(out["session_date"]).cumsum() / cumulative_volume

    prior_mean = groups["volume"].transform(
        lambda volume: (
            volume.shift(1)
            .rolling(
                config.relative_volume_period,
                min_periods=config.relative_volume_min_periods,
            )
            .mean()
        )
    )
    out["relative_volume"] = out["volume"] / prior_mean.replace(0, pd.NA)

    range_start = parse_hhmm(config.opening_range_start)
    range_end = parse_hhmm(config.opening_range_end)
    opening = out[(out["local_time"] >= range_start) & (out["local_time"] < range_end)]
    opening_stats = opening.groupby("session_date").agg(
        opening_range_high=("high", "max"),
        opening_range_low=("low", "min"),
        opening_range_bars=("close", "count"),
    )
    out = out.join(opening_stats, on="session_date")
    out.loc[out["opening_range_bars"] != 15, ["opening_range_high", "opening_range_low"]] = pd.NA
    return out


def signal_at(features: pd.DataFrame, position: int, config: OrbStrategyConfig) -> ScalpSignal | None:
    """Return a signal from one completed bar; the caller may only fill on a later bar."""
    if position <= 0 or position >= len(features):
        return None
    row = features.iloc[position]
    previous = features.iloc[position - 1]
    timestamp = features.index[position]
    timestamp_utc = timestamp.to_pydatetime().astimezone(timezone.utc)
    timestamp_et = timestamp_utc.astimezone(ET)
    if not in_time_window(timestamp_et, config.entry_start, config.entry_end):
        return None
    if previous["session_date"] != row["session_date"]:
        return None

    required = (
        "opening_range_high",
        "opening_range_low",
        "vwap",
        "ema_fast",
        "ema_slow",
        "relative_volume",
        "atr14",
    )
    if any(pd.isna(row[name]) for name in required):
        return None

    high_threshold = float(row["opening_range_high"]) + config.breakout_buffer
    low_threshold = float(row["opening_range_low"]) - config.breakout_buffer
    long_break = float(previous["close"]) < high_threshold <= float(row["close"])
    short_break = float(previous["close"]) > low_threshold >= float(row["close"])
    volume_ok = float(row["relative_volume"]) >= config.relative_volume_threshold

    direction: ScalpDirection | None = None
    if (
        long_break
        and volume_ok
        and float(row["close"]) > float(row["vwap"])
        and float(row["ema_fast"]) > float(row["ema_slow"])
    ):
        direction = ScalpDirection.LONG
    elif (
        short_break
        and volume_ok
        and float(row["close"]) < float(row["vwap"])
        and float(row["ema_fast"]) < float(row["ema_slow"])
    ):
        direction = ScalpDirection.SHORT
    if direction is None:
        return None

    return ScalpSignal(
        direction=direction,
        session_date=row["session_date"],
        bar_time_utc=timestamp_utc,
        bar_time_et=timestamp_et,
        close=float(row["close"]),
        opening_range_high=float(row["opening_range_high"]),
        opening_range_low=float(row["opening_range_low"]),
        vwap=float(row["vwap"]),
        ema_fast=float(row["ema_fast"]),
        ema_slow=float(row["ema_slow"]),
        relative_volume=float(row["relative_volume"]),
        atr14=float(row["atr14"]),
    )


def risk_per_share(entry_price: float, atr14: float, config: ScalpRiskConfig) -> float | None:
    if entry_price <= 0 or atr14 <= 0:
        return None
    risk = max(entry_price * config.minimum_stop_pct, atr14 * config.atr_stop_multiple)
    if risk > entry_price * config.maximum_stop_pct:
        return None
    return risk


def position_size(
    *,
    entry_price: float,
    per_share_risk: float,
    opening_net_liquidation: float,
    available_funds: float,
    config: ScalpRiskConfig,
) -> int:
    if min(entry_price, per_share_risk, opening_net_liquidation, available_funds) <= 0:
        return 0
    risk_quantity = math.floor(opening_net_liquidation * config.risk_per_trade_pct / per_share_risk)
    funds_quantity = math.floor(available_funds / entry_price)
    notional_quantity = math.floor(opening_net_liquidation * config.max_notional_pct / entry_price)
    return max(0, min(risk_quantity, funds_quantity, notional_quantity))


def quote_is_executable(
    quote: StockQuote,
    now_utc: datetime,
    config: ScalpExecutionConfig,
) -> tuple[bool, str]:
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if quote.delayed and not config.allow_delayed_data:
        return False, "delayed quote"
    if quote.bid <= 0 or quote.ask <= 0 or quote.ask < quote.bid:
        return False, "invalid bid/ask"
    age = (now_utc.astimezone(timezone.utc) - quote.timestamp_utc.astimezone(timezone.utc)).total_seconds()
    if age < -1 or age > config.quote_max_age_seconds:
        return False, f"stale quote ({age:.1f}s)"
    if quote.spread > config.max_spread + 1e-9:
        return False, f"spread too wide ({quote.spread:.2f})"
    return True, "ok"


def _tick(value: float, tick_size: float, rounding: str = "nearest") -> float:
    units = Decimal(str(value)) / Decimal(str(tick_size))
    mode = {
        "up": ROUND_CEILING,
        "down": ROUND_FLOOR,
        "nearest": ROUND_HALF_UP,
    }[rounding]
    return float(units.quantize(Decimal(1), rounding=mode) * Decimal(str(tick_size)))


def build_bracket_intent(
    signal: ScalpSignal,
    quote: StockQuote,
    quantity: int,
    per_share_risk: float,
    risk: ScalpRiskConfig,
    execution: ScalpExecutionConfig,
) -> BracketIntent:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if signal.direction is ScalpDirection.LONG:
        entry = _tick(quote.ask, execution.tick_size, "up")
        stop = _tick(entry - per_share_risk, execution.tick_size, "up")
        target = _tick(entry + risk.target_multiple * per_share_risk, execution.tick_size, "down")
    else:
        entry = _tick(quote.bid, execution.tick_size, "down")
        stop = _tick(entry + per_share_risk, execution.tick_size, "down")
        target = _tick(entry - risk.target_multiple * per_share_risk, execution.tick_size, "up")
    identity = "|".join(
        (
            "SPY-ORB-v1",
            signal.session_date.isoformat(),
            signal.bar_time_utc.isoformat(),
            signal.direction.value,
            str(quantity),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16].upper()
    root = f"AFSCALP-{digest}"
    return BracketIntent(
        intent_id=root,
        parent_order_ref=f"{root}-P",
        take_profit_order_ref=f"{root}-TP",
        stop_order_ref=f"{root}-SL",
        direction=signal.direction,
        symbol=quote.symbol,
        quantity=quantity,
        entry_limit=entry,
        take_profit_price=target,
        stop_price=stop,
        risk_per_share=per_share_risk,
        session_date=signal.session_date,
        signal_time_utc=signal.bar_time_utc,
    )


def is_inside_opening_range(price: float, signal: ScalpSignal) -> bool:
    return signal.opening_range_low <= price <= signal.opening_range_high
