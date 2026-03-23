import asyncio
import sys

# --- 修复 Python 3.12+ 的事件循环问题 ---
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import *
import pandas as pd
import numpy as np
import time
import logging
import io

# 确保 Windows 上的输出编码正确
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- 配置区 ---
TWS_HOST = '127.0.0.1'
TWS_PORT = 7497  
CLIENT_ID = 1    

TICKERS = ['QQQ', 'VOO', 'AMD', 'NVDA', 'AAPL', 'MSFT', 'TSLA']
INDICES = ['QQQ', 'VOO'] 

# 核心策略参数 (V7.0 增强平衡版)
FAST_PERIOD = 10
SLOW_PERIOD = 25
TREND_PERIOD = 200
ADX_PERIOD = 14
ADX_THRESHOLD = 20
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.5
TRAILING_STOP = 0.12
RISK_PER_TRADE = 0.015
INDEX_MULTIPLIER = 3.0

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()

class LiveSystemV8:
    def __init__(self):
        self.ib = IB()

    def connect(self):
        try:
            self.ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
            logger.info("✅ 成功连接到 IBKR 实时交易接口！")
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            exit()

    def get_indicators(self, bars):
        df = util.asPandas(bars)
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

    def check_signals(self):
        # 1. 获取账户摘要
        summary = self.ib.accountSummary()
        net_liq = float([i.value for i in summary if i.tag == 'NetLiquidation'][0])
        logger.info(f"当前账户总资产: {net_liq:.2f} USD")
        
        # 2. 检查持仓和新信号
        for symbol in TICKERS:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            # 请求历史数据
            bars = self.ib.reqHistoricalData(
                contract, endDateTime='', durationStr='300 D',
                barSizeSetting='1 day', whatToShow='ADJUSTED_LAST', useRTH=True)
            
            if not bars: continue
            latest = self.get_indicators(bars)
            curr_price = bars[-1].close
            
            pos = [p for p in self.ib.positions() if p.contract.symbol == symbol]
            
            if pos:
                # 已有持仓：检查离场逻辑
                position = pos[0]
                if latest['ema_fast'] < latest['ema_slow']:
                    logger.info(f"🚩 [{symbol}] EMA 死叉，执行卖出离场。价格: {curr_price}")
                    self.ib.placeOrder(contract, MarketOrder('SELL', abs(position.position)))
            else:
                # 无持仓：检查入场逻辑
                if (curr_price > latest['ema_trend'] and 
                    latest['ema_fast'] > latest['ema_slow'] and 
                    latest['adx'] > ADX_THRESHOLD):
                    
                    # 风险管理计算
                    mult = INDEX_MULTIPLIER if symbol in INDICES else 1.0
                    risk_amt = net_liq * RISK_PER_TRADE * mult
                    risk_per_share = max(latest['atr'] * ATR_MULTIPLIER, 0.01)
                    size = int(risk_amt / risk_per_share)
                    
                    if size > 0:
                        logger.info(f"🚀 [{symbol}] 信号触发！ADX: {latest['adx']:.1f}，下单 {size} 股")
                        self.ib.placeOrder(contract, MarketOrder('BUY', size))

    def run(self):
        self.connect()
        while True:
            try:
                logger.info("--- 开始新一轮扫描 ---")
                self.check_signals()
                logger.info("扫描结束，1小时后再次检查。")
                self.ib.sleep(3600) 
            except Exception as e:
                logger.error(f"运行中出现错误: {e}")
                self.ib.sleep(60)

if __name__ == "__main__":
    system = LiveSystemV8()
    system.run()