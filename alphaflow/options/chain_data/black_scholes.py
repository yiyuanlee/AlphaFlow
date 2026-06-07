"""Black-Scholes helpers for delta when greeks are unavailable."""

from __future__ import annotations

import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1(spot: float, strike: float, t_years: float, rate: float, vol: float) -> float:
    if t_years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    return (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))


def delta(spot: float, strike: float, dte_days: int, right: str, vol: float = 0.25, rate: float = 0.05) -> float:
    t = max(dte_days, 1) / 365.0
    d1 = _d1(spot, strike, t, rate, vol)
    if right.upper() == 'C':
        return _norm_cdf(d1)
    return _norm_cdf(d1) - 1.0


def option_price(
    spot: float,
    strike: float,
    dte_days: int,
    right: str,
    vol: float = 0.22,
    rate: float = 0.05,
) -> float:
    t = max(dte_days, 1) / 365.0
    d1 = _d1(spot, strike, t, rate, vol)
    d2 = d1 - vol * math.sqrt(t)
    if right.upper() == 'C':
        px = spot * _norm_cdf(d1) - strike * math.exp(-rate * t) * _norm_cdf(d2)
    else:
        px = strike * math.exp(-rate * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return max(px, 0.01)


def target_strike(spot: float, right: str, delta_target: float = 0.25) -> float:
    """Heuristic OTM strike for ~target delta."""
    if right.upper() == 'P':
        return spot * (1.0 - 0.04 - delta_target * 0.04)
    return spot * (1.0 + 0.04 + delta_target * 0.04)


def estimate_vol_from_price(
    spot: float,
    strike: float,
    dte_days: int,
    right: str,
    price: float,
    rate: float = 0.05,
) -> float:
    if price <= 0:
        return 0.25
    vol = 0.25
    for _ in range(20):
        t = max(dte_days, 1) / 365.0
        d1 = _d1(spot, strike, t, rate, vol)
        d2 = d1 - vol * math.sqrt(t)
        if right.upper() == 'C':
            model = spot * _norm_cdf(d1) - strike * math.exp(-rate * t) * _norm_cdf(d2)
        else:
            model = strike * math.exp(-rate * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        diff = model - price
        if abs(diff) < 0.01:
            break
        vol = max(min(vol - diff * 0.1, 2.0), 0.05)
    return vol
