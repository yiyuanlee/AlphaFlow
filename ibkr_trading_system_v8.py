import asyncio
import sys
import io

# --- 修复 Windows 终端乱码与事件循环问题 ---
if sys.platform == 'win32':
    # 强制标准输出和错误输出使用 UTF-8 编码
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

# 设置日志：显式指定 stream 为 sys.stdout 以应用上面的编码设置
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(message)s',
    stream=sys.stdout  # 关键修复：确保日志使用我们修复过的输出流
)
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

    def check_signals(self):
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
            
            logger.info(f"检查 {symbol:4}: 价格={curr_price:.2f}, EMA10={latest['ema_fast']:.2f}, EMA25={latest['ema_slow']:.2f}, ADX={latest['adx']:.1f}")
            
            pos = [p for p in self.ib.positions() if p.contract.symbol == symbol]
            
            if pos:
                position = pos[0]
                if latest['ema_fast'] < latest['ema_slow']:
                    logger.info(f"🚩 [{symbol}] EMA 死叉，执行卖出离场。价格: {curr_price}")
                    self.ib.placeOrder(contract, MarketOrder('SELL', abs(position.position)))
            else:
                cond_trend = curr_price > latest['ema_trend']
                cond_cross = latest['ema_fast'] > latest['ema_slow']
                cond_adx = latest['adx'] > ADX_THRESHOLD
                
                if cond_trend and cond_cross and cond_adx:
                    mult = INDEX_MULTIPLIER if symbol in INDICES else 1.0
                    risk_amt = net_liq * RISK_PER_TRADE * mult
                    risk_per_share = max(latest['atr'] * ATR_MULTIPLIER, 0.01)
                    size = int(risk_amt / risk_per_share)
                    
                    if size > 0:
                        logger.info(f"🚀 [{symbol}] 信号触发！下单 {size} 股")
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