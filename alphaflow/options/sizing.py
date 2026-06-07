"""Contract sizing and portfolio risk checks."""

from __future__ import annotations

import math

from alphaflow.options.options_config import OptionsRiskParams


def size_covered_call(stock_shares: int, existing_short_calls: int, max_contracts: int) -> int:
    capacity = stock_shares // 100 - existing_short_calls
    return max(min(capacity, max_contracts), 0)


def size_cash_secured_put(available_cash: float, strike: float, max_contracts: int) -> int:
    if strike <= 0 or available_cash <= 0:
        return 0
    per_contract = strike * 100
    by_cash = int(available_cash // per_contract)
    return max(min(by_cash, max_contracts), 0)


def size_vertical_spread(width: float, max_loss_per_trade: float, max_contracts: int) -> int:
    if width <= 0:
        return 0
    per_contract_loss = width * 100
    by_risk = int(max_loss_per_trade // per_contract_loss)
    return max(min(by_risk, max_contracts), 0)


def vertical_spread_max_loss(width: float, contracts: int) -> float:
    return width * 100 * contracts


def csp_max_loss(strike: float, contracts: int) -> float:
    return strike * 100 * contracts


def portfolio_margin_used(positions_max_loss: list[float], net_liquidation: float) -> float:
    if net_liquidation <= 0:
        return 0.0
    return sum(positions_max_loss) / net_liquidation


def allow_new_trade(
    risk: OptionsRiskParams,
    positions_max_loss: list[float],
    trade_max_loss: float,
    net_liquidation: float,
) -> bool:
    projected = portfolio_margin_used(positions_max_loss + [trade_max_loss], net_liquidation)
    return projected <= risk.max_portfolio_margin_pct and trade_max_loss <= risk.max_loss_per_trade


def round_limit_price(price: float) -> float:
    return round(max(price, 0.01), 2)


def contracts_from_premium_budget(premium: float, budget: float) -> int:
    if premium <= 0:
        return 0
    return max(int(math.floor(budget / (premium * 100))), 0)
