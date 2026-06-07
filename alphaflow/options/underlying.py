"""Stock core management for covered calls."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd

from alphaflow.config import StrategyParams, params_from_config
from alphaflow.data import fetch_data
from alphaflow.indicators import compute_indicators
from alphaflow.options.options_config import OptionsTradingConfig
from alphaflow.options.types import UnderlyingSnapshot

if TYPE_CHECKING:
    from ib_insync import IB


def fetch_underlying_daily(symbol: str, lookback_days: int = 400) -> pd.DataFrame | None:
    end = date.today()
    start = end - timedelta(days=lookback_days)
    return fetch_data(symbol, start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))


def build_underlying_snapshot(
    symbol: str,
    df: pd.DataFrame,
    stock_shares: int = 0,
    short_calls: int = 0,
    short_puts: int = 0,
    strategy_params: StrategyParams | None = None,
) -> UnderlyingSnapshot:
    strategy_params = strategy_params or StrategyParams()
    ind = compute_indicators(df, strategy_params)
    row = ind.iloc[-1]
    prev = ind.iloc[-2] if len(ind) > 1 else row
    golden = bool(row['golden_cross']) if not pd.isna(row.get('golden_cross')) else (
        row['ema_fast'] > row['ema_slow'] and prev['ema_fast'] <= prev['ema_slow']
    )
    return UnderlyingSnapshot(
        symbol=symbol,
        close=float(row['close']),
        ema_fast=float(row['ema_fast']),
        ema_slow=float(row['ema_slow']),
        ema_trend=float(row['ema_trend']),
        rsi=float(row['rsi']),
        adx=float(row['adx']),
        golden_cross=golden,
        stock_shares=stock_shares,
        short_calls=short_calls,
        short_puts=short_puts,
    )


def sync_stock_positions(ib: IB, symbols: list[str]) -> dict[str, int]:
    shares: dict[str, int] = {s: 0 for s in symbols}
    for pos in ib.positions():
        if pos.contract.secType != 'STK':
            continue
        sym = pos.contract.symbol
        if sym in shares:
            shares[sym] = int(pos.position)
    return shares


def sync_option_exposure(ib: IB, symbols: list[str]) -> dict[str, dict[str, int]]:
    exposure = {s: {'short_calls': 0, 'short_puts': 0} for s in symbols}
    for pos in ib.positions():
        if pos.contract.secType != 'OPT':
            continue
        sym = pos.contract.symbol
        if sym not in exposure:
            continue
        qty = int(pos.position)
        right = pos.contract.right
        if qty < 0 and right == 'C':
            exposure[sym]['short_calls'] += abs(qty)
        if qty < 0 and right == 'P':
            exposure[sym]['short_puts'] += abs(qty)
    return exposure


def stock_core_gap(target: int, current: int) -> int:
    """Shares needed to reach target (rounded to 100-lot steps for CC)."""
    if current >= target:
        return 0
    need = target - current
    if need < 100:
        return 0
    return (need // 100) * 100


class UnderlyingManager:
    """Maintain stock_core targets for covered call collateral."""

    def __init__(self, ib: IB, config: OptionsTradingConfig):
        self.ib = ib
        self.config = config

    def rebalance(self, available_cash: float) -> list[dict[str, Any]]:
        from ib_insync import MarketOrder, Stock

        actions: list[dict[str, Any]] = []
        shares = sync_stock_positions(self.ib, list(self.config.underlyings))
        for symbol, target in self.config.stock_core.items():
            if target <= 0:
                continue
            current = shares.get(symbol, 0)
            buy_qty = stock_core_gap(target, current)
            if buy_qty <= 0:
                continue
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            ticker = self.ib.reqMktData(contract, snapshot=True)
            self.ib.sleep(1)
            price = float(ticker.last or ticker.close or 0)
            self.ib.cancelMktData(contract)
            if price <= 0 or buy_qty * price > available_cash:
                continue
            order = MarketOrder('BUY', buy_qty)
            trade = self.ib.placeOrder(contract, order)
            actions.append({'symbol': symbol, 'qty': buy_qty, 'price': price, 'trade': trade})
        return actions
