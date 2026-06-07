"""
AlphaFlow - Options trading (Covered Call / CSP / Vertical Spreads)
=================================================================
Primary live sleeve: regime-routed options on QQQ/VOO + blue chips.

用法: python scripts/live/ibkr_options.py
"""

from __future__ import annotations

import asyncio
import io
import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup_path

setup_path(__file__)

import ib_insync.util as util
import pytz
from ib_insync import IB

from alphaflow.config import load_config, params_from_config
from alphaflow.data import fetch_data
from alphaflow.options.journal import log_options_event
from alphaflow.options.manager import OptionsManager
from alphaflow.options.options_config import options_config_from_yaml
from alphaflow.options.regime import compute_regime_from_df
from alphaflow.options.signals import route_strategy
from alphaflow.options.underlying import (
    UnderlyingManager,
    build_underlying_snapshot,
    sync_option_exposure,
    sync_stock_positions,
)

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

CONFIG = load_config()
OPT = options_config_from_yaml(CONFIG)
STRAT_PARAMS, _ = params_from_config(CONFIG)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)


class OptionsTrader:
    def __init__(self):
        self.ib = IB()
        self.manager = OptionsManager(self.ib, OPT)
        self.underlying_mgr = UnderlyingManager(self.ib, OPT)

    def connect(self) -> None:
        self.ib.connect(OPT.tws_host, OPT.tws_port, clientId=OPT.client_id)
        logger.info(f'已连接 IBKR ({OPT.tws_host}:{OPT.tws_port}, clientId={OPT.client_id})')

    def account_metrics(self) -> tuple[float, float]:
        summary = {item.tag: float(item.value) for item in self.ib.accountSummary() if item.currency == 'USD'}
        cash = summary.get('TotalCashValue', summary.get('AvailableFunds', 0.0))
        nlv = summary.get('NetLiquidation', cash)
        return cash, nlv

    def benchmark_regime(self):
        benchmark = OPT.regime.benchmark
        df = fetch_data(benchmark, '2018-01-01', date.today().strftime('%Y-%m-%d'))
        if df is None or df.empty:
            raise RuntimeError(f'无法获取 {benchmark} 日线数据')
        return compute_regime_from_df(df, OPT.regime)

    def run_cycle(self) -> None:
        regime = self.benchmark_regime()
        cash, nlv = self.account_metrics()
        logger.info(
            f'Regime={regime.regime.value} benchmark={regime.benchmark} '
            f'close={regime.close:.2f} adx={regime.adx:.1f} rsi={regime.rsi:.1f}'
        )
        self.manager.manage_open_positions()
        self.underlying_mgr.rebalance(cash)
        shares = sync_stock_positions(self.ib, list(OPT.underlyings))
        exposure = sync_option_exposure(self.ib, list(OPT.underlyings))

        for symbol in OPT.underlyings:
            df = fetch_data(symbol, '2018-01-01', date.today().strftime('%Y-%m-%d'))
            if df is None or df.empty:
                continue
            exp = exposure.get(symbol, {'short_calls': 0, 'short_puts': 0})
            underlying = build_underlying_snapshot(
                symbol,
                df,
                stock_shares=shares.get(symbol, 0),
                short_calls=exp['short_calls'],
                short_puts=exp['short_puts'],
                strategy_params=STRAT_PARAMS,
            )
            has_open = any(
                p.status == 'open' and p.symbol == symbol
                for p in self.manager.positions.values()
            )
            intent = route_strategy(regime, underlying, OPT, has_open_option=has_open)
            logger.info(f'{symbol} intent={intent.value} shares={underlying.stock_shares}')
            if intent.value in ('hold', 'close', 'none'):
                continue
            ok = self.manager.execute_intent(intent, underlying, cash, nlv)
            log_options_event('route', symbol=symbol, intent=intent.value, executed=ok)

    def run_forever(self) -> None:
        self.connect()
        et = pytz.timezone('US/Eastern')
        while True:
            now = util.now().astimezone(et)
            if now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 35)) and now.hour < 16:
                try:
                    self.run_cycle()
                except Exception as exc:
                    logger.exception(f'循环异常: {exc}')
            time.sleep(OPT.execution.loop_seconds)


def main():
    trader = OptionsTrader()
    if '--once' in sys.argv:
        trader.connect()
        trader.run_cycle()
        trader.ib.disconnect()
        return
    trader.run_forever()


if __name__ == '__main__':
    main()
