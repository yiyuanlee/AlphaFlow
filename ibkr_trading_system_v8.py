"""
AlphaFlow - 实盘交易系统 V8.1
==============================
在 V8 基础上加入:
1. Trailing Stop 实盘实现（持仓最高点追踪）
2. 订单成交确认（waitOnUpdate 等待成交）
3. 参数从 config.yaml 读取（统一管理）

用法: python ibkr_trading_system_v8.py
"""

import asyncio
import sys
import io
import yaml
from datetime import datetime

# --- 修复 Windows 终端乱码与事件循环问题 ---
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import *
import ib_insync.util as util
import pandas as pd
import numpy as np
import logging

# --- 配置加载 ---
def load_config():
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        # 如果找不到 config.yaml，使用默认值
        return None

config = load_config()

# --- IBKR 连接配置 ---
TWS_HOST = '127.0.0.1'
TWS_PORT = 7497
CLIENT_ID = 1

# 从 config 读取策略参数（找不到则用默认值）
if config and 'live' in config:
    TWS_HOST = config['live'].get('tws_host', TWS_HOST)
    TWS_PORT = config['live'].get('tws_port', TWS_PORT)
    CLIENT_ID = config['live'].get('client_id', CLIENT_ID)

if config and 'strategy' in config:
    s = config['strategy']
    FAST_PERIOD = s.get('fast_period', 10)
    SLOW_PERIOD = s.get('slow_period', 25)
    TREND_PERIOD = s.get('trend_period', 200)
    ADX_PERIOD = s.get('adx_period', 14)
    ADX_THRESHOLD = s.get('adx_threshold', 20)
    ATR_PERIOD = s.get('atr_period', 14)
    ATR_MULTIPLIER = s.get('atr_multiplier', 2.5)
    TRAILING_STOP = s.get('trailing_stop', 0.12)
else:
    # 默认参数
    FAST_PERIOD = 10
    SLOW_PERIOD = 25
    TREND_PERIOD = 200
    ADX_PERIOD = 14
    ADX_THRESHOLD = 20
    ATR_PERIOD = 14
    ATR_MULTIPLIER = 2.5
    TRAILING_STOP = 0.12

if config and 'risk' in config:
    r = config['risk']
    RISK_PER_TRADE = r.get('risk_per_trade', 0.015)
    INDEX_MULTIPLIER = r.get('index_multiplier', 3.0)
else:
    RISK_PER_TRADE = 0.015
    INDEX_MULTIPLIER = 3.0

# 默认标的（可从 config.yaml 的 tickers 读取）
if config and 'tickers' in config:
    TICKERS = config['tickers']
else:
    TICKERS = ['QQQ', 'VOO', 'AMD', 'NVDA', 'AAPL', 'MSFT', 'TSLA']
INDICES = ['QQQ', 'VOO']

# 扫描间隔（秒）
SCAN_INTERVAL = config['live'].get('scan_interval_seconds', 3600) if config and 'live' in config else 3600

# 订单最大等待成交时间（秒）
ORDER_TIMEOUT = 10

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger()


class LiveSystemV8:
    def __init__(self):
        self.ib = IB()
        # 持仓最高点追踪（用于 Trailing Stop）
        # 结构: {symbol: peak_price}
        self.peak_prices = {}
        # ATR 止损价位（结构: {symbol: stop_price}）
        self.stop_prices = {}
        # 订单追踪（防止重复下单）
        self.pending_orders = set()  # 记录正在等待成交的订单 ID

    def connect(self):
        try:
            self.ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
            logger.info("✅ 成功连接到 IBKR 实时交易接口！")
            logger.info(f"📋 当前持仓标的管理: {TICKERS}")
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            exit()

    def get_indicators(self, bars):
        """计算 EMA / ATR / ADX 指标"""
        df = util.df(bars)

        # EMA
        df['ema_fast'] = df['close'].ewm(span=FAST_PERIOD).mean()
        df['ema_slow'] = df['close'].ewm(span=SLOW_PERIOD).mean()
        df['ema_trend'] = df['close'].ewm(span=TREND_PERIOD).mean()

        # ATR
        high_low = df['high'] - df['low']
        high_cp = (df['high'] - df['close'].shift()).abs()
        low_cp = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=ATR_PERIOD).mean()

        # ADX
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        minus_dm = minus_dm.abs()
        tr_smooth = tr.rolling(window=ADX_PERIOD).mean()
        plus_di = 100 * (plus_dm.rolling(window=ADX_PERIOD).mean() / tr_smooth)
        minus_di = 100 * (minus_dm.rolling(window=ADX_PERIOD).mean() / tr_smooth)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        df['adx'] = dx.rolling(window=ADX_PERIOD).mean()

        return df.iloc[-1]

    def get_current_price(self, contract):
        """获取标的当前价格"""
        ticker = self.ib.reqMktData(contract, '', False, False)
        self.ib.sleep(0.2)  # 等待实时数据推送
        price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
        return price

    def wait_for_fill(self, order, timeout=ORDER_TIMEOUT):
        """等待订单成交确认，超时则返回 False"""
        deadline = datetime.now().timestamp() + timeout
        while datetime.now().timestamp() < deadline:
            if order.isFilled():
                return True
            self.ib.sleep(0.5)
        return False

    def check_signals(self):
        """核心信号扫描：检查入场 / 离场信号"""
        summary = self.ib.accountSummary()
        net_liq_items = [i.value for i in summary if i.tag == 'NetLiquidation']
        if not net_liq_items:
            logger.warning("未能获取到账户净值，跳过本轮扫描。")
            return

        net_liq = float(net_liq_items[0])
        logger.info(f"当前账户总资产: {net_liq:.2f} USD")

        for symbol in TICKERS:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)

            bars = self.ib.reqHistoricalData(
                contract, endDateTime='', durationStr='300 D',
                barSizeSetting='1 day', whatToShow='ADJUSTED_LAST', useRTH=True)

            if not bars:
                logger.warning(f"无法获取 {symbol} 的历史数据")
                continue

            latest = self.get_indicators(bars)
            curr_price = bars[-1].close

            logger.info(f"检查 {symbol:4}: 价格={curr_price:.2f}, "
                       f"EMA10={latest['ema_fast']:.2f}, EMA25={latest['ema_slow']:.2f}, "
                       f"ADX={latest['adx']:.1f}, ATR={latest['atr']:.2f}")

            pos = [p for p in self.ib.positions() if p.contract.symbol == symbol]

            # ===========================
            # 持仓管理：检查离场信号
            # ===========================
            if pos:
                position = pos[0]
                is_long = position.position > 0

                # --- 离场信号 1: EMA 死叉 ---
                if latest['ema_fast'] < latest['ema_slow']:
                    logger.info(f"🚩 [{symbol}] EMA 死叉，执行卖出离场。价格: {curr_price}")
                    order = MarketOrder('SELL', abs(position.position))
                    self.ib.placeOrder(contract, order)
                    self.pending_orders.add(order.orderId)
                    # 清理追踪数据
                    self.peak_prices.pop(symbol, None)
                    self.stop_prices.pop(symbol, None)
                    continue

                # --- 离场信号 2: ATR 动态止损 ---
                stop_price = self.stop_prices.get(symbol)
                if stop_price and curr_price < stop_price:
                    logger.info(f"🛑 [{symbol}] 触发 ATR 止损！价格: {curr_price:.2f}, 止损位: {stop_price:.2f}")
                    order = MarketOrder('SELL', abs(position.position))
                    self.ib.placeOrder(contract, order)
                    self.pending_orders.add(order.orderId)
                    self.peak_prices.pop(symbol, None)
                    self.stop_prices.pop(symbol, None)
                    continue

                # --- 离场信号 3: Trailing Stop（移动止损）---
                peak_price = self.peak_prices.get(symbol)
                if peak_price:
                    trailing_threshold = peak_price * (1.0 - TRAILING_STOP)
                    if curr_price < trailing_threshold:
                        drawdown_pct = (peak_price - curr_price) / peak_price * 100
                        logger.info(f"📊 [{symbol}] 触发移动止损！"
                                    f"最高价: {peak_price:.2f}, 当前价: {curr_price:.2f}, "
                                    f"回撤: {drawdown_pct:.1f}% (阈值: {TRAILING_STOP:.0%})")
                        order = MarketOrder('SELL', abs(position.position))
                        self.ib.placeOrder(contract, order)
                        self.pending_orders.add(order.orderId)
                        self.peak_prices.pop(symbol, None)
                        self.stop_prices.pop(symbol, None)
                        continue

                # --- 更新持仓最高点（每轮扫描都检查）---
                if is_long:
                    current_peak = self.peak_prices.get(symbol, curr_price)
                    if curr_price > current_peak:
                        self.peak_prices[symbol] = curr_price
                        logger.info(f"📈 [{symbol}] 更新持仓最高点: {current_peak:.2f} → {curr_price:.2f}")

            # ===========================
            # 无持仓：检查入场信号
            # ===========================
            else:
                # 入场条件
                cond_trend = curr_price > latest['ema_trend']
                cond_cross = latest['ema_fast'] > latest['ema_slow']
                cond_adx = latest['adx'] > ADX_THRESHOLD

                if symbol not in self.peak_prices:  # 避免重复入场
                    if cond_trend and cond_cross and cond_adx:
                        mult = INDEX_MULTIPLIER if symbol in INDICES else 1.0
                        risk_amt = net_liq * RISK_PER_TRADE * mult
                        risk_per_share = max(latest['atr'] * ATR_MULTIPLIER, 0.01)
                        size = int(risk_amt / risk_per_share)

                        if size > 0:
                            logger.info(f"🚀 [{symbol}] 信号触发！计划买入 {size} 股，"
                                        f"风险敞口: ${risk_amt:.2f} ({risk_amt/net_liq:.2%})")

                            order = MarketOrder('BUY', size)
                            placed_order = self.ib.placeOrder(contract, order)
                            self.pending_orders.add(placed_order.orderId)

                            # --- 等待成交确认（P1-2）---
                            filled = self.wait_for_fill(placed_order, timeout=ORDER_TIMEOUT)
                            if filled:
                                exec_price = placed_order.filledPrice if placed_order.filledPrice else curr_price
                                logger.info(f"✅ [{symbol}] 买入成交！价格: {exec_price:.2f}, 数量: {size}")

                                # 初始化 ATR 止损位
                                self.stop_prices[symbol] = exec_price - (latest['atr'] * ATR_MULTIPLIER)
                                # 初始化持仓最高点
                                self.peak_prices[symbol] = exec_price
                                logger.info(f"🛡️ [{symbol}] 初始止损位: {self.stop_prices[symbol]:.2f}, "
                                            f"移动止损回撤阈值: {exec_price * (1 - TRAILING_STOP):.2f}")
                            else:
                                logger.warning(f"⚠️ [{symbol}] 订单未能在 {ORDER_TIMEOUT} 秒内成交，可能被拒绝")

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
