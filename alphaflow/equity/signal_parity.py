"""Signal parity: shared equity functions vs Backtrader crossover logic."""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaflow.core.config import StrategyParams
from alphaflow.equity.signals import PositionState, check_entry, check_exit, initial_stop_price
from alphaflow.indicators import compute_indicators


def simulate_signal_decisions(
    df: pd.DataFrame,
    params: StrategyParams,
) -> list[dict]:
    """Replay bar-by-bar entry/exit decisions using shared signal functions."""
    enriched = compute_indicators(df, params)
    decisions: list[dict] = []
    in_position = False
    state = PositionState()

    for i in range(len(enriched)):
        row = enriched.iloc[i]
        if pd.isna(row.get("ema_trend")) or pd.isna(row.get("atr_sma")):
            continue

        golden = bool(row.get("golden_cross", False))
        death = bool(row.get("death_cross", False))
        record = {
            "date": enriched.index[i],
            "close": float(row["close"]),
            "entry": False,
            "exit": False,
            "exit_reason": None,
        }

        if in_position:
            if check_exit(
                close=float(row["close"]),
                ema_trend=float(row["ema_trend"]),
                death_cross=death,
                position=state,
                atr=float(row["atr"]),
                params=params,
            ):
                record["exit"] = True
                record["exit_reason"] = check_exit(
                    close=float(row["close"]),
                    ema_trend=float(row["ema_trend"]),
                    death_cross=death,
                    position=state,
                    atr=float(row["atr"]),
                    params=params,
                )
                in_position = False
                state = PositionState()
        elif check_entry(
            close=float(row["close"]),
            ema_trend=float(row["ema_trend"]),
            rsi=float(row["rsi"]),
            adx=float(row["adx"]),
            atr=float(row["atr"]),
            atr_sma=float(row["atr_sma"]),
            golden_cross=golden,
            params=params,
        ):
            record["entry"] = True
            in_position = True
            stop = initial_stop_price(float(row["close"]), float(row["atr"]), params)
            state = PositionState(stop_price=stop, highest_price=float(row["close"]))

        if in_position and not record["exit"]:
            peak = max(state.highest_price or float(row["close"]), float(row["close"]))
            state = PositionState(stop_price=state.stop_price, highest_price=peak)

        decisions.append(record)

    return decisions


def _synthetic_uptrend(rows: int = 260) -> pd.DataFrame:
    """Generate trending OHLCV suitable for indicator warm-up."""
    idx = pd.date_range("2023-01-01", periods=rows, freq="B")
    close = 100 + np.cumsum(np.random.default_rng(42).normal(0.15, 1.0, rows))
    close = np.maximum(close, 50)
    high = close + 1.5
    low = close - 1.5
    open_ = close - 0.2
    volume = np.full(rows, 1_000_000)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
