"""Backtrader strategy using shared equity signal functions."""

from __future__ import annotations

import backtrader as bt

from alphaflow.constants import is_index
from alphaflow.core.config import RiskParams, StrategyParams
from alphaflow.equity.signals import (
    PositionState,
    calc_position_size,
    check_entry,
    check_exit,
)


class AlphaFlowStrategy(bt.Strategy):
    """Trend-following strategy with portfolio capital allocation."""

    params = dict(
        fast_period=10,
        slow_period=25,
        trend_period=200,
        rsi_period=14,
        rsi_upper=65,
        adx_period=14,
        adx_threshold=20,
        atr_period=14,
        atr_multiplier=2.5,
        vol_filter_period=100,
        vol_filter_ratio=0.8,
        trailing_atr_mult=3.0,
        trailing_stop=0.12,
        risk_per_trade=0.030,
        alloc_index=0.60,
        alloc_stock=0.40,
        index_multiplier=3.0,
        portfolio_mode=True,
        printlog=False,
    )

    def log(self, txt, dt=None):
        if self.params.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f"{dt.isoformat()} {txt}")

    def __init__(self):
        self.inds = {}
        self.trade_stats = {d._name: {"trades": 0, "won": 0, "pnl": 0.0} for d in self.datas}

        for d in self.datas:
            atr = bt.indicators.ATR(d, period=self.p.atr_period)
            self.inds[d] = {
                "ema_fast": bt.indicators.EMA(d, period=self.p.fast_period),
                "ema_slow": bt.indicators.EMA(d, period=self.p.slow_period),
                "ema_trend": bt.indicators.EMA(d, period=self.p.trend_period),
                "rsi": bt.indicators.RSI(d, period=self.p.rsi_period),
                "atr": atr,
                "adx": bt.indicators.ADX(d, period=self.p.adx_period),
                "crossover": bt.indicators.CrossOver(
                    bt.indicators.EMA(d, period=self.p.fast_period),
                    bt.indicators.EMA(d, period=self.p.slow_period),
                ),
                "atr_sma": bt.indicators.SMA(atr, period=self.p.vol_filter_period),
                "stop_price": None,
                "highest_price": None,
            }

    def _strategy_params(self) -> StrategyParams:
        p = self.p
        return StrategyParams(
            fast_period=p.fast_period,
            slow_period=p.slow_period,
            trend_period=p.trend_period,
            rsi_period=p.rsi_period,
            rsi_upper=p.rsi_upper,
            adx_period=p.adx_period,
            adx_threshold=p.adx_threshold,
            atr_period=p.atr_period,
            atr_multiplier=p.atr_multiplier,
            vol_filter_period=p.vol_filter_period,
            vol_filter_ratio=p.vol_filter_ratio,
            trailing_atr_mult=p.trailing_atr_mult,
            trailing_stop=p.trailing_stop,
        )

    def _risk_params(self) -> RiskParams:
        p = self.p
        return RiskParams(
            risk_per_trade=p.risk_per_trade,
            alloc_index=p.alloc_index,
            alloc_stock=p.alloc_stock,
            index_multiplier=p.index_multiplier,
        )

    def notify_order(self, order):
        if order.status in [order.Completed]:
            d = order.data
            if order.isbuy():
                self.inds[d]["stop_price"] = (
                    order.executed.price - self.inds[d]["atr"][0] * self.p.atr_multiplier
                )
                self.inds[d]["highest_price"] = order.executed.price
            else:
                self.inds[d]["stop_price"] = None
                self.inds[d]["highest_price"] = None

    def notify_trade(self, trade):
        if trade.isclosed:
            name = trade.data._name
            self.trade_stats[name]["trades"] += 1
            self.trade_stats[name]["pnl"] += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.trade_stats[name]["won"] += 1

    def stop(self):
        for d in self.datas:
            pos = self.getposition(d)
            if pos:
                pnl = pos.size * (d.close[0] - pos.price)
                name = d._name
                self.trade_stats[name]["trades"] += 1
                self.trade_stats[name]["pnl"] += pnl
                if pnl > 0:
                    self.trade_stats[name]["won"] += 1

    def next(self):
        strategy_params = self._strategy_params()
        risk_params = self._risk_params()
        total_value = self.broker.getvalue()
        index_exposure = 0.0
        stock_exposure = 0.0

        for d in self.datas:
            pos = self.getposition(d)
            if pos:
                val = pos.size * d.close[0]
                if is_index(d._name):
                    index_exposure += val
                else:
                    stock_exposure += val

        for d in self.datas:
            pos = self.getposition(d)
            ind = self.inds[d]

            if pos:
                ind["highest_price"] = max(ind["highest_price"], d.close[0])
                state = PositionState(
                    stop_price=ind["stop_price"],
                    highest_price=ind["highest_price"],
                )
                if check_exit(
                    close=d.close[0],
                    ema_trend=ind["ema_trend"][0],
                    death_cross=ind["crossover"][0] < 0,
                    position=state,
                    atr=ind["atr"][0],
                    params=strategy_params,
                ):
                    self.close(d)
                    continue
            elif check_entry(
                close=d.close[0],
                ema_trend=ind["ema_trend"][0],
                rsi=ind["rsi"][0],
                adx=ind["adx"][0],
                atr=ind["atr"][0],
                atr_sma=ind["atr_sma"][0],
                golden_cross=ind["crossover"][0] > 0,
                params=strategy_params,
            ):
                size = calc_position_size(
                    symbol=d._name,
                    close=d.close[0],
                    atr=ind["atr"][0],
                    total_value=total_value,
                    available_cash=self.broker.get_cash(),
                    index_exposure=index_exposure,
                    stock_exposure=stock_exposure,
                    strategy=strategy_params,
                    risk=risk_params,
                    portfolio_mode=self.p.portfolio_mode,
                )
                if size <= 0:
                    continue

                self.buy(d, size=size)

                if self.p.portfolio_mode:
                    order_val = size * d.close[0]
                    if is_index(d._name):
                        index_exposure += order_val
                    else:
                        stock_exposure += order_val
