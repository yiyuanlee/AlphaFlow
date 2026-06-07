"""
AlphaFlow - Options trading (Covered Call / CSP / Vertical Spreads)
=================================================================
推荐工作流（避免 IBKR 半天重登 + 长时间挂进程）:
  python scripts/options_daily_scan.py          # 每日快扫（无需 IBKR，~10秒）
  python scripts/live/ibkr_options.py --live      # 开盘/午盘各跑一次（连上即下单即断开）
  python scripts/live/ibkr_options.py --live --dry-run   # 连 IBKR 但不下单，只写日志

旧模式（需 TWS 常驻）: python scripts/live/ibkr_options.py --loop
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
from alphaflow.options.daily_scan import format_daily_scan, run_daily_scan
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


def _opt_config(dry_run: bool = False):
    cfg = {
        **CONFIG,
        'options_trading': {
            **CONFIG.get('options_trading', {}),
            'execution': {
                **CONFIG.get('options_trading', {}).get('execution', {}),
                'dry_run': dry_run or CONFIG.get('options_trading', {}).get('execution', {}).get('dry_run', False),
            },
        },
    }
    return options_config_from_yaml(cfg)


class OptionsTrader:
    def __init__(self, dry_run: bool = False):
        self.ib = IB()
        self.opt = _opt_config(dry_run)
        self.dry_run = self.opt.execution.dry_run
        self.manager = OptionsManager(self.ib, self.opt)
        self.underlying_mgr = UnderlyingManager(self.ib, self.opt)

    def connect(self) -> None:
        timeout = self.opt.execution.connect_timeout
        self.ib.connect(self.opt.tws_host, self.opt.tws_port, clientId=self.opt.client_id, timeout=timeout)
        mode = 'DRY-RUN' if self.dry_run else 'LIVE'
        logger.info(
            f'已连接 IBKR [{mode}] ({self.opt.tws_host}:{self.opt.tws_port}, clientId={self.opt.client_id})',
        )

    def account_metrics(self) -> tuple[float, float]:
        summary = {item.tag: float(item.value) for item in self.ib.accountSummary() if item.currency == 'USD'}
        cash = summary.get('TotalCashValue', summary.get('AvailableFunds', 0.0))
        nlv = summary.get('NetLiquidation', cash)
        return cash, nlv

    def benchmark_regime(self):
        benchmark = self.opt.regime.benchmark
        df = fetch_data(benchmark, '2018-01-01', date.today().strftime('%Y-%m-%d'))
        if df is None or df.empty:
            raise RuntimeError(f'无法获取 {benchmark} 日线数据')
        return compute_regime_from_df(df, self.opt.regime)

    def run_cycle(self) -> None:
        regime = self.benchmark_regime()
        cash, nlv = self.account_metrics()
        logger.info(
            f'Regime={regime.regime.value} benchmark={regime.benchmark} '
            f'close={regime.close:.2f} adx={regime.adx:.1f} rsi={regime.rsi:.1f}'
        )
        if not self.dry_run:
            self.manager.manage_open_positions()
            self.underlying_mgr.rebalance(cash)
        shares = sync_stock_positions(self.ib, list(self.opt.underlyings))
        exposure = sync_option_exposure(self.ib, list(self.opt.underlyings))

        for symbol in self.opt.underlyings:
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
            intent = route_strategy(regime, underlying, self.opt, has_open_option=has_open)
            logger.info(f'{symbol} intent={intent.value} shares={underlying.stock_shares}')
            if intent.value in ('hold', 'close', 'none'):
                continue
            ok = self.manager.execute_intent(intent, underlying, cash, nlv)
            log_options_event('route', symbol=symbol, intent=intent.value, executed=ok, dry_run=self.dry_run)

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
            time.sleep(self.opt.execution.loop_seconds)


def main():
    argv = sys.argv[1:]
    if '--loop' in argv:
        OptionsTrader(dry_run='--dry-run' in argv).run_forever()
        return
    if '--live' in argv or '--once' in argv:
        trader = OptionsTrader(dry_run='--dry-run' in argv)
        try:
            trader.connect()
            trader.run_cycle()
        finally:
            trader.ib.disconnect()
        return
    # 默认：离线快扫，无需 IBKR
    report = run_daily_scan()
    print(format_daily_scan(report))


if __name__ == '__main__':
    main()
