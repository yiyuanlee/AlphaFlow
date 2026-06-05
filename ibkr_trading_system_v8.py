"""
AlphaFlow - 实盘交易系统 V8.1
==============================
参数从 config.yaml 读取，信号逻辑与回测共用 alphaflow 模块。

用法: python ibkr_trading_system_v8.py
"""

import asyncio
import sys
import io
import json
import logging
from datetime import datetime
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Stock, MarketOrder
import ib_insync.util as util

from alphaflow.config import load_config, params_from_config
from alphaflow.constants import is_index
from alphaflow.indicators import compute_indicators
from alphaflow.signals import (
    PositionState,
    calc_position_size,
    check_entry,
    check_exit,
    initial_stop_price,
)

config = load_config()
STRATEGY_PARAMS, RISK_PARAMS = params_from_config(config) if config else (None, None)

TWS_HOST = config['live'].get('tws_host', '127.0.0.1') if config else '127.0.0.1'
TWS_PORT = config['live'].get('tws_port', 7497) if config else 7497
CLIENT_ID = config['live'].get('client_id', 1) if config else 1
SCAN_INTERVAL = config['live'].get('scan_interval_seconds', 3600) if config else 3600
if config and config.get('index_tickers'):
    TICKERS = config['index_tickers']
else:
    TICKERS = ['QQQ', 'VOO']
ORDER_TIMEOUT = 10

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger()


class LiveSystemV8:
    def __init__(self):
        self.ib = IB()
        self.peak_prices = {}
        self.stop_prices = {}
        self.pending_orders = set()
        self.state_file_path = 'trading_state.json'
        self.load_state()

    def save_state(self):
        state = {'peak_prices': self.peak_prices, 'stop_prices': self.stop_prices}
        try:
            with open(self.state_file_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=4)
            logger.info("💾 交易状态已成功保存至 trading_state.json")
        except Exception as e:
            logger.error(f"❌ 保存交易状态失败: {e}")

    def load_state(self):
        if Path(self.state_file_path).exists():
            try:
                with open(self.state_file_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                self.peak_prices = state.get('peak_prices', {})
                self.stop_prices = state.get('stop_prices', {})
                logger.info("💾 成功从 trading_state.json 加载历史状态！")
            except Exception as e:
                logger.error(f"❌ 读取 trading_state.json 失败，将重新初始化: {e}")
                self.peak_prices = {}
                self.stop_prices = {}
        else:
            self.peak_prices = {}
            self.stop_prices = {}

    def get_avg_fill_price(self, trade, fallback_price):
        if trade.orderStatus and trade.orderStatus.avgFillPrice > 0:
            return trade.orderStatus.avgFillPrice
        if trade.fills:
            total_val = sum(f.execution.price * f.execution.shares for f in trade.fills)
            total_shares = sum(f.execution.shares for f in trade.fills)
            if total_shares > 0:
                return total_val / total_shares
        return fallback_price

    def get_indicators(self, bars):
        df = util.df(bars)
        return compute_indicators(df, STRATEGY_PARAMS).iloc[-1]

    def recover_state_from_broker(self):
        logger.info("🔄 正在从 IBKR 校验并恢复仓位风控状态...")
        positions = self.ib.positions()
        state_updated = False

        for p in positions:
            symbol = p.contract.symbol
            if symbol in TICKERS and p.position > 0:
                if symbol not in self.stop_prices or symbol not in self.peak_prices:
                    avg_cost = p.avgCost
                    bars = self.ib.reqHistoricalData(
                        p.contract, endDateTime='', durationStr='30 D',
                        barSizeSetting='1 day', whatToShow='ADJUSTED_LAST', useRTH=True,
                    )
                    atr = self.get_indicators(bars)['atr'] if bars else avg_cost * 0.02

                    if symbol not in self.stop_prices:
                        self.stop_prices[symbol] = initial_stop_price(avg_cost, atr, STRATEGY_PARAMS)
                    if symbol not in self.peak_prices:
                        self.peak_prices[symbol] = max(avg_cost, bars[-1].close if bars else avg_cost)

                    logger.info(
                        f"🛡️ 已恢复 [{symbol}] 风控保护：平均成本={avg_cost:.2f}, "
                        f"止损位={self.stop_prices[symbol]:.2f}, 最高点={self.peak_prices[symbol]:.2f}"
                    )
                    state_updated = True

        if state_updated:
            self.save_state()

    def connect(self):
        try:
            self.ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
            logger.info("✅ 成功连接到 IBKR 实时交易接口！")
            logger.info(f"📋 当前持仓标的管理: {TICKERS}")
            self.recover_state_from_broker()
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            exit()

    def wait_for_fill(self, order, timeout=ORDER_TIMEOUT):
        deadline = datetime.now().timestamp() + timeout
        while datetime.now().timestamp() < deadline:
            if order.isFilled():
                return True
            self.ib.sleep(0.5)
        return False

    def _calc_exposure(self):
        index_exposure = 0.0
        stock_exposure = 0.0
        for p in self.ib.positions():
            if p.position <= 0:
                continue
            ticker = self.ib.reqMktData(p.contract, '', False, False)
            self.ib.sleep(0.1)
            price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
            val = abs(p.position) * price
            if is_index(p.contract.symbol):
                index_exposure += val
            else:
                stock_exposure += val
        return index_exposure, stock_exposure

    def check_signals(self):
        summary = self.ib.accountSummary()
        net_liq_items = [i.value for i in summary if i.tag == 'NetLiquidation']
        if not net_liq_items:
            logger.warning("未能获取到账户净值，跳过本轮扫描。")
            return

        net_liq = float(net_liq_items[0])
        cash_items = [i.value for i in summary if i.tag == 'CashBalance']
        available_cash = float(cash_items[0]) if cash_items else net_liq * 0.9
        index_exposure, stock_exposure = self._calc_exposure()

        logger.info(f"当前账户总资产: {net_liq:.2f} USD | 可用现金: {available_cash:.2f} USD")

        for symbol in TICKERS:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)

            bars = self.ib.reqHistoricalData(
                contract, endDateTime='', durationStr='500 D',
                barSizeSetting='1 day', whatToShow='ADJUSTED_LAST', useRTH=True,
            )
            if not bars:
                logger.warning(f"无法获取 {symbol} 的历史数据")
                continue

            latest = self.get_indicators(bars)
            curr_price = bars[-1].close

            logger.info(
                f"检查 {symbol:4}: 价格={curr_price:.2f}, "
                f"EMA10={latest['ema_fast']:.2f}, EMA25={latest['ema_slow']:.2f}, "
                f"RSI={latest['rsi']:.1f}, ADX={latest['adx']:.1f}, "
                f"ATR={latest['atr']:.2f}, EMA200={latest['ema_trend']:.2f}"
            )

            pos = [p for p in self.ib.positions() if p.contract.symbol == symbol]

            if pos:
                position = pos[0]
                peak = self.peak_prices.get(symbol, curr_price)
                if curr_price > peak:
                    self.peak_prices[symbol] = curr_price
                    logger.info(f"📈 [{symbol}] 更新持仓最高点: {peak:.2f} → {curr_price:.2f}")
                    self.save_state()

                state = PositionState(
                    stop_price=self.stop_prices.get(symbol),
                    highest_price=self.peak_prices.get(symbol),
                )
                exit_reason = check_exit(
                    close=curr_price,
                    ema_trend=latest['ema_trend'],
                    death_cross=bool(latest['death_cross']),
                    position=state,
                    atr=latest['atr'],
                    params=STRATEGY_PARAMS,
                )
                if exit_reason:
                    logger.info(f"🚩 [{symbol}] 触发离场 ({exit_reason})，价格: {curr_price:.2f}")
                    order = MarketOrder('SELL', abs(position.position))
                    self.ib.placeOrder(contract, order)
                    self.pending_orders.add(order.orderId)
                    self.peak_prices.pop(symbol, None)
                    self.stop_prices.pop(symbol, None)
                    self.save_state()
            else:
                if symbol in self.peak_prices:
                    continue

                if check_entry(
                    close=curr_price,
                    ema_trend=latest['ema_trend'],
                    rsi=latest['rsi'],
                    adx=latest['adx'],
                    atr=latest['atr'],
                    atr_sma=latest['atr_sma'],
                    golden_cross=bool(latest['golden_cross']),
                    params=STRATEGY_PARAMS,
                ):
                    size = calc_position_size(
                        symbol=symbol,
                        close=curr_price,
                        atr=latest['atr'],
                        total_value=net_liq,
                        available_cash=available_cash,
                        index_exposure=index_exposure,
                        stock_exposure=stock_exposure,
                        strategy=STRATEGY_PARAMS,
                        risk=RISK_PARAMS,
                        portfolio_mode=True,
                    )
                    if size > 0:
                        logger.info(
                            f"🚀 [{symbol}] 信号触发！计划买入 {size} 股，"
                            f"预计订单总额: ${size * curr_price:.2f}"
                        )
                        placed_order = self.ib.placeOrder(contract, MarketOrder('BUY', size))
                        self.pending_orders.add(placed_order.orderId)

                        if self.wait_for_fill(placed_order, timeout=ORDER_TIMEOUT):
                            exec_price = self.get_avg_fill_price(placed_order, curr_price)
                            logger.info(f"✅ [{symbol}] 买入成交！价格: {exec_price:.2f}, 数量: {size}")
                            self.stop_prices[symbol] = initial_stop_price(
                                exec_price, latest['atr'], STRATEGY_PARAMS,
                            )
                            self.peak_prices[symbol] = exec_price
                            self.save_state()
                            order_val = size * curr_price
                            if is_index(symbol):
                                index_exposure += order_val
                            else:
                                stock_exposure += order_val
                        else:
                            logger.warning(
                                f"⚠️ [{symbol}] 订单未能在 {ORDER_TIMEOUT} 秒内成交，可能被拒绝"
                            )

    def run(self):
        self.connect()
        while True:
            try:
                logger.info("--- 开始新一轮扫描 ---")
                self.check_signals()
                logger.info(f"扫描结束，{SCAN_INTERVAL} 秒后再次检查。")
                self.ib.sleep(SCAN_INTERVAL)
            except Exception as e:
                logger.error(f"运行中出现错误: {e}")
                self.ib.sleep(60)


if __name__ == "__main__":
    system = LiveSystemV8()
    system.run()
