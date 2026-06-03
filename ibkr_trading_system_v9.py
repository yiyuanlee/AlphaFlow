import asyncio
import sys
import io
from datetime import datetime, time as dt_time
import pytz

# --- 修复 Windows 终端乱码 ---
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# asyncio.get_event_loop() is deprecated in Python 3.10+
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from ib_insync import IB, Stock, MarketOrder, ScannerSubscription, TagValue
import ib_insync.util as util
import pandas as pd
import numpy as np
import logging

# --- 核心配置 ---
TWS_HOST = '127.0.0.1'
TWS_PORT = 7497  
CLIENT_ID = 1    

# 策略参数
FAST_EMA = 9
SLOW_EMA = 21
RSI_PERIOD = 14
RSI_ENTRY = 45   
RISK_PER_TRADE = 0.01   
MAX_POSITIONS = 5       
TAKE_PROFIT = 0.015     

# --- 极严格风控 ---
MIN_PRICE = 10.0        
MAX_SHARES = 2000       
MAX_DOLLAR_VALUE = 30000 
TOTAL_STOP_LOSS_PCT = 0.04 # 降低到 4% 强制保护

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger()

class HighFreqIntradayV9:
    def __init__(self):
        self.ib = IB()
        self.active_tickers = []
        self.last_scan_time = datetime.min
        self.indicators = {} # 存储每个标的的最新指标

    def connect(self):
        try:
            self.ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
            # 开启实时持仓与账户更新推送
            self.ib.reqPositions()
            self.ib.accountSummary()
            logger.info("✅ V9.7 架构优化版上线：扫描器解耦 + 实时价格监控。")
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            exit()

    def is_market_open(self):
        tz = pytz.timezone('US/Eastern')
        now = datetime.now(tz)
        if now.weekday() >= 5: return False
        return dt_time(9, 45) <= now.time() <= dt_time(15, 55)

    def flatten_all(self, reason=""):
        logger.warning(f"🚨🚨🚨 触发全账户紧急清仓！原因: {reason}")
        for p in self.ib.positions():
            contract = p.contract
            self.ib.qualifyContracts(contract)
            action = 'SELL' if p.position > 0 else 'BUY'
            order = MarketOrder(action, abs(p.position))
            self.ib.placeOrder(contract, order)
            logger.warning(f"正在清算 {contract.symbol}")

    def update_indicators(self, symbol):
        """仅在需要时更新指标，减少请求频率"""
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            bars = self.ib.reqHistoricalData(contract, '', '1 D', '1 min', 'ADJUSTED_LAST', True)
            if not bars:
                return None

            df = util.df(bars)
            df['ema_fast'] = df['close'].ewm(span=FAST_EMA, adjust=False).mean()
            df['ema_slow'] = df['close'].ewm(span=SLOW_EMA, adjust=False).mean()
            cum_vol = df['volume'].cumsum()
            df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close']) / 3).cumsum() / cum_vol

            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
            avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean().replace(0, 0.001)
            df['rsi'] = 100 - (100 / (1 + avg_gain / avg_loss))

            self.indicators[symbol] = df.iloc[-1]
            return self.indicators[symbol]
        except Exception as e:
            logger.warning(f"[{symbol}] 指标计算失败: {e}")
            return None

    def get_dynamic_universe(self):
        """将扫描频率降低至 15 分钟一次，彻底解决 Error 162"""
        now = datetime.now()
        if (now - self.last_scan_time).total_seconds() < 900: 
            return self.active_tickers
        
        try:
            logger.info("🔍 正在执行每15分钟一次的市场扫描...")
            sub = ScannerSubscription(instrument='STK', locationCode='STK.US.MAJOR', scanCode='TOP_PERC_GAIN')
            tag_values = [TagValue('priceAbove', str(MIN_PRICE)), TagValue('volumeAbove', '1000000')]
            scan_data = self.ib.reqScannerData(sub, scannerSubscriptionFilterOptions=tag_values)
            self.active_tickers = [cd.contractDetails.contract.symbol for cd in scan_data[:10]] if scan_data else ['QQQ', 'NVDA']
            self.last_scan_time = now
            return self.active_tickers
        except Exception as e:
            logger.warning(f"扫描器暂时不可用: {e}")
            return self.active_tickers

    def monitor_positions(self):
        """核心止损逻辑：使用实时价格监控"""
        positions = self.ib.positions()
        if not positions: return

        # 检查账户总回撤
        summary = self.ib.accountSummary()
        net_liq = float([i.value for i in summary if i.tag == 'NetLiquidation'][0])
        unrealized_pnl = sum([float(i.value) for i in summary if i.tag == 'UnrealizedPnL'])
        
        if unrealized_pnl < -(net_liq * TOTAL_STOP_LOSS_PCT):
            self.flatten_all(f"账户回撤达到 {TOTAL_STOP_LOSS_PCT:.1%}")
            return

        for p in positions:
            symbol = p.contract.symbol
            # 订阅实时行情获取当前价格
            ticker = self.ib.reqMktData(p.contract, '', False, False)
            self.ib.sleep(0.1)
            curr_price = ticker.last if ticker.last == ticker.last else ticker.close # 处理 NaN

            # 确保有指标数据
            latest = self.indicators.get(symbol)
            if latest is None:
                latest = self.update_indicators(symbol)
                if not latest: continue

            # 离场逻辑检测
            exit_signal = False
            is_long = p.position > 0
            
            if is_long:
                if curr_price > p.avgCost * (1 + TAKE_PROFIT) or curr_price < latest['vwap'] or latest['ema_fast'] < latest['ema_slow']:
                    exit_signal = True
                    action = 'SELL'
            else:
                if curr_price < p.avgCost * (1 - TAKE_PROFIT) or curr_price > latest['vwap'] or latest['ema_fast'] > latest['ema_slow']:
                    exit_signal = True
                    action = 'BUY'

            if exit_signal:
                logger.info(f"🚩 [{symbol}] 实时离场触发！价格: {curr_price:.2f}")
                self.ib.placeOrder(p.contract, MarketOrder(action, abs(p.position)))

    def run(self):
        self.connect()
        while True:
            try:
                if self.is_market_open():
                    # 1. 监控并止损（最高优先级）
                    self.monitor_positions()
                    # 2. 获取股票池（低频）
                    self.active_tickers = self.get_dynamic_universe()
                    # 3. 寻找新机会（仅在有空位时）
                    held_symbols = {p.contract.symbol for p in self.ib.positions()}
                    if len(held_symbols) < MAX_POSITIONS:
                        for symbol in self.active_tickers:
                            if symbol in held_symbols:
                                continue
                            latest = self.update_indicators(symbol)
                            if latest is None:
                                continue
                            ema_cross = latest['ema_fast'] > latest['ema_slow']
                            rsi_ok = latest['rsi'] < RSI_ENTRY
                            above_vwap = latest['close'] > latest['vwap']
                            if ema_cross and rsi_ok and above_vwap:
                                curr_price = float(latest['close'])
                                if curr_price < MIN_PRICE:
                                    continue
                                order_val = RISK_PER_TRADE * MAX_DOLLAR_VALUE
                                size = max(1, int(order_val / curr_price))
                                size = min(size, MAX_SHARES)
                                if size * curr_price > MAX_DOLLAR_VALUE:
                                    size = int(MAX_DOLLAR_VALUE / curr_price)
                                if size > 0:
                                    contract = Stock(symbol, 'SMART', 'USD')
                                    self.ib.qualifyContracts(contract)
                                    order = MarketOrder('BUY', size)
                                    self.ib.placeOrder(contract, order)
                                    logger.info(f"🚀 [{symbol}] V9 入场信号触发，买入 {size} 股 @ ~{curr_price:.2f}")
                
                self.ib.sleep(10) # 缩短循环到 10 秒，但内部逻辑更轻量
            except Exception as e:
                logger.error(f"⚠️ 循环异常: {e}")
                self.ib.sleep(5)

if __name__ == "__main__":
    system = HighFreqIntradayV9()
    system.run()