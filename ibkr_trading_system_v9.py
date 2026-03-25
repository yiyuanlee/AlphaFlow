import asyncio
import sys
import io
from datetime import datetime, time as dt_time
import pytz

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

# --- 核心配置区 (V9.5 止血专用版) ---
TWS_HOST = '127.0.0.1'
TWS_PORT = 7497  
CLIENT_ID = 1    

# 默认观察名单 (仅保留流动性极佳的蓝筹)
FALLBACK_TICKERS = ['QQQ', 'NVDA', 'AMD', 'AAPL', 'MSFT', 'TSLA']

# 策略参数
FAST_EMA = 9
SLOW_EMA = 21
RSI_PERIOD = 14
RSI_ENTRY = 45   
RISK_PER_TRADE = 0.01   # 降低每笔风险到 1%，先稳住阵脚
MAX_POSITIONS = 5       # 减少同时持仓，集中火力
TAKE_PROFIT = 0.02      # 略微调高止盈空间

# --- V9.5 极严格风控设置 ---
MIN_PRICE = 10.0        # 股价低于 $10 的绝对不碰（规避高额佣金与低流动性）
MAX_SHARES = 2000       # 严限股数，防止产生巨额佣金
MAX_DOLLAR_VALUE = 30000 # 限制单笔总额
LIMIT_OFFSET = 0.02     # 限价单偏移量 (买入时高于现价2美分，防止踏空且锁定成本)

# 设置日志
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger()

class HighFreqIntradayV9:
    def __init__(self):
        self.ib = IB()
        self.active_tickers = []
        self.pending_tickers = set()

    def connect(self):
        try:
            self.ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
            logger.info("✅ 成功连接！V9.5 止血版已上线，已禁用市价单。")
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            exit()

    def is_market_open(self):
        tz = pytz.timezone('US/Eastern')
        now = datetime.now(tz)
        if now.weekday() >= 5: return False
        # 避开开盘前 15 分钟的剧烈波动，从 9:45 开始
        return dt_time(9, 45) <= now.time() <= dt_time(15, 45)

    def get_dynamic_universe(self):
        """扫描全美股活跃标的，强制高股价与高成交量"""
        try:
            sub = ScannerSubscription(
                instrument='STK', 
                locationCode='STK.US.MAJOR', 
                scanCode='TOP_PERC_GAIN' 
            )
            tag_values = [
                TagValue('priceAbove', str(MIN_PRICE)),
                TagValue('volumeAbove', '1000000') # 只要日成交量 > 100万的股票
            ]
            scan_data = self.ib.reqScannerData(sub, scannerSubscriptionFilterOptions=tag_values)
            return [cd.contractDetails.contract.symbol for cd in scan_data[:15]] if scan_data else FALLBACK_TICKERS
        except Exception as e:
            logger.error(f"❌ 扫描出错: {e}")
            return FALLBACK_TICKERS

    def get_intraday_indicators(self, bars):
        df = util.df(bars)
        if df is None or df.empty: return None
        df['ema_fast'] = df['close'].ewm(span=FAST_EMA).mean()
        df['ema_slow'] = df['close'].ewm(span=SLOW_EMA).mean()
        df['vwap'] = (df['volume'] * (df['high'] + df['low'] + df['close'])/3).cumsum() / df['volume'].cumsum()
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean().replace(0, 0.001)
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        return df.iloc[-1]

    def trade_logic(self):
        if not self.is_market_open(): return

        self.active_tickers = self.get_dynamic_universe()
        summary = self.ib.accountSummary()
        net_liq = float([i.value for i in summary if i.tag == 'NetLiquidation'][0])
        
        positions = {p.contract.symbol: p for p in self.ib.positions()}
        current_orders = self.ib.openOrders()
        self.pending_tickers = {o.symbol for o in current_orders}

        for symbol in self.active_tickers:
            if len(positions) >= MAX_POSITIONS and symbol not in positions: continue
            if symbol in self.pending_tickers: continue 

            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            # 获取实时报价以检查买卖价差
            ticker = self.ib.reqMktData(contract, '', False, False)
            self.ib.sleep(1) # 等待数据返回
            
            if ticker.bid > 0 and ticker.ask > 0:
                spread = (ticker.ask - ticker.bid) / ticker.ask
                if spread > 0.005: # 如果买卖价差 > 0.5%，放弃该笔交易
                    logger.warning(f"⚠️ [{symbol}] 价差过大 ({spread:.2%})，已跳过。")
                    continue

            bars = self.ib.reqHistoricalData(contract, '', '1 D', '1 min', 'ADJUSTED_LAST', True)
            if not bars or len(bars) < SLOW_EMA: continue
            latest = self.get_indicators_fix(bars)
            curr_price = bars[-1].close
            
            if symbol in positions:
                p = positions[symbol]
                if curr_price > p.avgCost * (1 + TAKE_PROFIT) or curr_price < latest['vwap'] or latest['ema_fast'] < latest['ema_slow']:
                    logger.info(f"🚨 [{symbol}] 满足离场条件，发出限价单卖出。")
                    # 卖出时用 LimitOrder 保证价格
                    self.ib.placeOrder(contract, LimitOrder('SELL', abs(p.position), round(curr_price - 0.01, 2)))
            else:
                if curr_price > latest['vwap'] and latest['ema_fast'] > latest['ema_slow'] and latest['rsi'] > RSI_ENTRY:
                    size = min(int((net_liq * RISK_PER_TRADE) / (curr_price * 0.05)), MAX_SHARES)
                    if size * curr_price > MAX_DOLLAR_VALUE: size = int(MAX_DOLLAR_VALUE / curr_price)

                    if size > 0:
                        lmt_price = round(curr_price + LIMIT_OFFSET, 2)
                        logger.info(f"🔥 [{symbol}] 触发入场！限价单价格: {lmt_price}")
                        self.ib.placeOrder(contract, LimitOrder('BUY', size, lmt_price))

    def get_indicators_fix(self, bars):
        # 内部封装，确保逻辑一致
        return self.get_intraday_indicators(bars)

    def run(self):
        self.connect()
        while True:
            try:
                self.trade_logic()
                self.ib.sleep(30) 
            except Exception as e:
                logger.error(f"⚠️ 异常: {e}")
                self.ib.sleep(10)

if __name__ == "__main__":
    system = HighFreqIntradayV9()
    system.run()