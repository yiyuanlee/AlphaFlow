"""
AlphaFlow - 热门股短线策略（个股资金池）
==========================================
- 资金：仅使用 alloc_stock 个股池（默认 40%）
- 标的：IBKR 扫描器每日热门股，不固定名单
- 持仓：最长 5 个日历日，到期强制平仓

用法: python scripts/live/ibkr_hot_stocks.py
建议与 scripts/live/ibkr_trading_system_v8.py（指数池 VOO/QQQ）并行运行。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import io
from datetime import date, datetime, time as dt_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup_path

setup_path(__file__)

import ib_insync.util as util
import pytz
from ib_insync import IB, MarketOrder, Stock

from alphaflow.config import load_config, state_path
from alphaflow.hot_config import hot_config_from_yaml
from alphaflow.hot_indicators import compute_intraday_indicators
from alphaflow.hot_journal import log_hot_event
from alphaflow.hot_market import is_market_bullish
from alphaflow.hot_signals import (
    calc_hot_position_size,
    check_hot_entry,
    check_hot_exit,
    hold_days,
)
from alphaflow.scanner import HotStockScanner

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

CONFIG = load_config()
HOT = hot_config_from_yaml(CONFIG)
LIVE = CONFIG.get('live', {})
TWS_HOST = LIVE.get('tws_host', '127.0.0.1')
TWS_PORT = LIVE.get('tws_port', 7497)
CLIENT_ID = CONFIG.get('hot_trading', {}).get('client_id', 2)
STATE_PATH = state_path('hot_trading_state.json')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger()


class HotStockTrader:
    def __init__(self):
        self.ib = IB()
        self.scanner = HotStockScanner(self.ib, HOT.scanner, set(HOT.exclude_symbols))
        self.positions: dict[str, dict] = {}
        self.load_state()

    def load_state(self):
        if STATE_PATH.exists():
            try:
                data = json.loads(STATE_PATH.read_text(encoding='utf-8'))
                self.positions = data.get('positions', {})
                logger.info(f'已加载 {len(self.positions)} 条热门股持仓记录')
            except Exception as exc:
                logger.error(f'读取状态失败: {exc}')
                self.positions = {}

    def save_state(self):
        STATE_PATH.write_text(
            json.dumps({'positions': self.positions, 'updated_at': datetime.now().isoformat()}, indent=2),
            encoding='utf-8',
        )

    def connect(self):
        self.ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
        logger.info('✅ 热门股策略已连接 IBKR')
        self._sync_positions_from_broker()

    def _sync_positions_from_broker(self):
        for p in self.ib.positions():
            sym = p.contract.symbol
            if sym in HOT.exclude_symbols or p.position == 0:
                continue
            if sym not in self.positions and p.position > 0:
                self.positions[sym] = {
                    'entry_date': date.today().isoformat(),
                    'entry_price': p.avgCost,
                }
                logger.info(f'同步券商持仓 [{sym}] entry={p.avgCost:.2f}')

    def is_market_open(self) -> bool:
        tz = pytz.timezone('US/Eastern')
        now = datetime.now(tz)
        if now.weekday() >= 5:
            return False
        return dt_time(9, 45) <= now.time() <= dt_time(15, 55)

    def _account_snapshot(self) -> tuple[float, float, float]:
        summary = self.ib.accountSummary()
        net_liq = float(next(i.value for i in summary if i.tag == 'NetLiquidation'))
        unrealized = sum(float(i.value) for i in summary if i.tag == 'UnrealizedPnL')
        return net_liq, unrealized, net_liq * HOT.risk.stock_pool_pct

    def _stock_exposure(self, net_liq: float) -> float:
        exposure = 0.0
        for p in self.ib.positions():
            if p.position <= 0 or p.contract.symbol in HOT.exclude_symbols:
                continue
            ticker = self.ib.reqMktData(p.contract, '', False, False)
            self.ib.sleep(0.1)
            px = ticker.last if ticker.last and ticker.last > 0 else ticker.close
            exposure += abs(p.position) * px
        return exposure

    def _latest_intraday(self, contract) -> dict | None:
        bars = self.ib.reqHistoricalData(
            contract, endDateTime='', durationStr='1 D', barSizeSetting='1 min',
            whatToShow='ADJUSTED_LAST', useRTH=True,
        )
        if not bars:
            return None
        df = util.df(bars)
        row = compute_intraday_indicators(df, HOT.entry).iloc[-1]
        return row.to_dict()

    def _current_price(self, contract) -> float | None:
        ticker = self.ib.reqMktData(contract, '', False, False)
        self.ib.sleep(0.15)
        px = ticker.last if ticker.last and ticker.last > 0 else ticker.close
        return float(px) if px and px == px else None

    def flatten_all(self, reason: str):
        logger.warning(f'🚨 热门股池清仓: {reason}')
        for p in self.ib.positions():
            if p.position == 0 or p.contract.symbol in HOT.exclude_symbols:
                continue
            action = 'SELL' if p.position > 0 else 'BUY'
            self.ib.placeOrder(p.contract, MarketOrder(action, abs(int(p.position))))
            self.positions.pop(p.contract.symbol, None)
        self.save_state()

    def manage_exits(self, net_liq: float, stock_exposure: float):
        for p in list(self.ib.positions()):
            sym = p.contract.symbol
            if p.position <= 0 or sym in HOT.exclude_symbols:
                continue

            meta = self.positions.get(sym, {'entry_date': date.today().isoformat(), 'entry_price': p.avgCost})
            contract = p.contract
            self.ib.qualifyContracts(contract)
            px = self._current_price(contract)
            if px is None:
                continue

            latest = self._latest_intraday(contract)
            if latest is None:
                continue

            reason = check_hot_exit(
                entry_date=meta['entry_date'],
                entry_price=meta.get('entry_price', p.avgCost),
                current_price=px,
                ema_fast=latest['ema_fast'],
                ema_slow=latest['ema_slow'],
                vwap=latest['vwap'],
                entry=HOT.entry,
                exit_params=HOT.exit,
                position_params=HOT.position,
                as_of=date.today(),
            )
            if reason:
                days = hold_days(meta['entry_date'])
                entry_px = meta.get('entry_price', p.avgCost)
                pnl_pct = (px / entry_px - 1) * 100 if entry_px else 0.0
                logger.info(f'🚩 [{sym}] 离场 ({reason}) 持仓{days}天 价格={px:.2f}')
                log_hot_event(
                    'exit',
                    symbol=sym,
                    price=px,
                    reason=reason,
                    hold_days=days,
                    pnl_pct=pnl_pct,
                    entry_price=entry_px,
                )
                self.ib.placeOrder(contract, MarketOrder('SELL', abs(int(p.position))))
                self.positions.pop(sym, None)
                self.save_state()

    def seek_entries(self, net_liq: float, stock_exposure: float):
        held = {p.contract.symbol for p in self.ib.positions() if p.position > 0}
        hot_list = self.scanner.get_universe()

        if len(held) >= HOT.position.max_positions:
            return

        market_ok, market_info = is_market_bullish(HOT.market)
        if HOT.entry.require_bull_market and not market_ok:
            logger.info(
                f'⏸ 大盘过滤: {market_info.get("benchmark")} '
                f'close={market_info.get("close", 0):.2f} '
                f'EMA{HOT.market.trend_period}={market_info.get("ema_trend", 0):.2f} — 暂停开仓'
            )
            log_hot_event('market_halt', **market_info)
            return

        for sym in hot_list:
            if sym in held:
                continue
            if len(held) >= HOT.position.max_positions:
                break

            contract = Stock(sym, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            latest = self._latest_intraday(contract)
            if latest is None:
                continue

            px = float(latest['close'])
            if px < HOT.scanner.min_price:
                continue

            ok, skip_reason = check_hot_entry(
                close=px,
                ema_fast=latest['ema_fast'],
                ema_slow=latest['ema_slow'],
                rsi=latest['rsi'],
                vwap=latest['vwap'],
                golden_cross=bool(latest.get('golden_cross')),
                adx=latest.get('adx'),
                rel_volume=latest.get('rel_volume'),
                market_bullish=market_ok,
                params=HOT.entry,
            )
            if not ok:
                log_hot_event(
                    'signal_skip',
                    symbol=sym,
                    price=px,
                    reason=skip_reason,
                    golden_cross=bool(latest.get('golden_cross')),
                    adx=latest.get('adx'),
                    rel_volume=latest.get('rel_volume'),
                    rsi=latest.get('rsi'),
                )
                continue

            size = calc_hot_position_size(
                price=px,
                net_liquidation=net_liq,
                stock_exposure=stock_exposure,
                risk=HOT.risk,
                position=HOT.position,
                stop_loss_pct=HOT.exit.stop_loss_pct,
            )
            if size <= 0:
                continue

            logger.info(
                f'🚀 [{sym}] 热门股入场 {size} 股 @ ~{px:.2f} '
                f'(金叉+ADX{latest.get("adx", 0):.1f}+RVOL{latest.get("rel_volume", 0):.2f}) '
                f'个股池 ${stock_exposure:,.0f}/${net_liq * HOT.risk.stock_pool_pct:,.0f}'
            )
            log_hot_event(
                'entry',
                symbol=sym,
                price=px,
                shares=size,
                golden_cross=True,
                adx=latest.get('adx'),
                rel_volume=latest.get('rel_volume'),
                rsi=latest.get('rsi'),
                market=market_info,
            )
            self.ib.placeOrder(contract, MarketOrder('BUY', size))
            self.positions[sym] = {'entry_date': date.today().isoformat(), 'entry_price': px}
            self.save_state()
            held.add(sym)
            stock_exposure += size * px

    def run_once(self):
        if not self.is_market_open():
            return

        net_liq, unrealized, pool_cap = self._account_snapshot()
        if unrealized < -(pool_cap * HOT.risk.pool_drawdown_halt_pct):
            self.flatten_all(f'个股池浮亏超过 {HOT.risk.pool_drawdown_halt_pct:.0%}')
            return

        stock_exposure = self._stock_exposure(net_liq)
        logger.info(
            f'账户净值 ${net_liq:,.0f} | 个股池上限 ${pool_cap:,.0f} | 已用 ${stock_exposure:,.0f}'
        )

        self.manage_exits(net_liq, stock_exposure)
        stock_exposure = self._stock_exposure(net_liq)
        self.seek_entries(net_liq, stock_exposure)

    def run(self):
        self.connect()
        while True:
            try:
                self.run_once()
                self.ib.sleep(HOT.loop_seconds)
            except Exception as exc:
                logger.error(f'循环异常: {exc}')
                self.ib.sleep(30)


def main():
    HotStockTrader().run()


if __name__ == '__main__':
    main()
