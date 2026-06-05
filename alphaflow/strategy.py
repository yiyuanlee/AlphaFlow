"""Backtrader strategy implementation using shared signal rules."""

import backtrader as bt

from alphaflow.constants import is_index
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
            print(f'{dt.isoformat()} {txt}')

    def __init__(self):
        self.inds = {}
        self.trade_stats = {d._name: {'trades': 0, 'won': 0, 'pnl': 0.0} for d in self.datas}

        for d in self.datas:
            atr = bt.indicators.ATR(d, period=self.p.atr_period)
            self.inds[d] = {
                'ema_fast': bt.indicators.EMA(d, period=self.p.fast_period),
                'ema_slow': bt.indicators.EMA(d, period=self.p.slow_period),
                'ema_trend': bt.indicators.EMA(d, period=self.p.trend_period),
                'rsi': bt.indicators.RSI(d, period=self.p.rsi_period),
                'atr': atr,
                'adx': bt.indicators.ADX(d, period=self.p.adx_period),
                'crossover': bt.indicators.CrossOver(
                    bt.indicators.EMA(d, period=self.p.fast_period),
                    bt.indicators.EMA(d, period=self.p.slow_period),
                ),
                'atr_sma': bt.indicators.SMA(atr, period=self.p.vol_filter_period),
                'stop_price': None,
                'highest_price': None,
            }

    def notify_order(self, order):
        if order.status in [order.Completed]:
            d = order.data
            if order.isbuy():
                self.inds[d]['stop_price'] = (
                    order.executed.price - self.inds[d]['atr'][0] * self.p.atr_multiplier
                )
                self.inds[d]['highest_price'] = order.executed.price
            else:
                self.inds[d]['stop_price'] = None
                self.inds[d]['highest_price'] = None

    def notify_trade(self, trade):
        if trade.isclosed:
            name = trade.data._name
            self.trade_stats[name]['trades'] += 1
            self.trade_stats[name]['pnl'] += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.trade_stats[name]['won'] += 1

    def stop(self):
        for d in self.datas:
            pos = self.getposition(d)
            if pos:
                pnl = pos.size * (d.close[0] - pos.price)
                name = d._name
                self.trade_stats[name]['trades'] += 1
                self.trade_stats[name]['pnl'] += pnl
                if pnl > 0:
                    self.trade_stats[name]['won'] += 1

    def _should_enter(self, d, ind) -> bool:
        if ind['crossover'][0] <= 0:
            return False
        if d.close[0] <= ind['ema_trend'][0]:
            return False
        if ind['rsi'][0] >= self.p.rsi_upper:
            return False
        if ind['adx'][0] <= self.p.adx_threshold:
            return False
        if ind['atr'][0] <= ind['atr_sma'][0] * self.p.vol_filter_ratio:
            return False
        return True

    def _should_exit(self, d, ind) -> bool:
        if d.close[0] < ind['ema_trend'][0]:
            return True
        if ind['stop_price'] is not None and d.close[0] < ind['stop_price']:
            return True
        if ind['highest_price'] is not None:
            atr_trail = ind['highest_price'] - ind['atr'][0] * self.p.trailing_atr_mult
            pct_trail = ind['highest_price'] * (1.0 - self.p.trailing_stop)
            if d.close[0] < min(atr_trail, pct_trail):
                return True
        if ind['crossover'][0] < 0:
            return True
        return False

    def next(self):
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
                ind['highest_price'] = max(ind['highest_price'], d.close[0])
                if self._should_exit(d, ind):
                    self.close(d)
                    continue
            elif self._should_enter(d, ind):
                risk_mult = self.p.index_multiplier if is_index(d._name) else 1.0
                risk_amount = total_value * self.p.risk_per_trade * risk_mult
                atr_stop = max(ind['atr'][0] * self.p.atr_multiplier, 0.01)
                size = int(risk_amount / atr_stop)
                order_val = size * d.close[0]
                available_cash = self.broker.get_cash() * 0.95

                if self.p.portfolio_mode:
                    if is_index(d._name):
                        max_allowed_val = total_value * self.p.alloc_index
                        available_val = max_allowed_val - index_exposure
                    else:
                        max_allowed_val = total_value * self.p.alloc_stock
                        available_val = max_allowed_val - stock_exposure
                    actual_available = max(min(available_val, available_cash), 0)
                else:
                    actual_available = available_cash

                if order_val > actual_available:
                    size = int(actual_available / d.close[0])

                if size <= 0:
                    continue

                self.buy(d, size=size)

                if self.p.portfolio_mode:
                    if is_index(d._name):
                        index_exposure += size * d.close[0]
                    else:
                        stock_exposure += size * d.close[0]
