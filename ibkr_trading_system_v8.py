import pandas as pd
import numpy as np
from ib_insync import *
import time
import logging

# --- 配置区 ---
TWS_HOST = '127.0.0.1'
TWS_PORT = 7497  # TWS 模拟盘默认端口是 7497，Gateway 默认是 4002
CLIENT_ID = 1    # 确保每个脚本的 ID 唯一

TICKERS = ['QQQ', 'VOO', 'AMD', 'NVDA', 'AAPL', 'MSFT', 'TSLA']
INDICES = ['QQQ', 'VOO'] # 享受更高权重倍数的标的

# 策略参数 (继承自 V7.0)
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
        self.contracts = {}
        self.last_prices = {}

    def connect(self):
        try:
            self.ib.connect(TWS_HOST, TWS_PORT, clientId=CLIENT_ID)
            logger.info("成功连接到 IBKR 模拟盘！")
        except Exception as e:
            logger.error(f"连接失败: {e}")
            exit()

    def get_indicators(self, bars):
        """使用 Pandas 计算策略指标"""
        df = util.asPandas(bars)
        # EMA
        df['ema_fast'] = df['close'].ewm(span=FAST_PERIOD).mean()
        df['ema_slow'] = df['close'].ewm(span=SLOW_PERIOD).mean()
        df['ema_trend'] = df['close'].ewm(span=TREND_PERIOD).mean()
        
        # ATR (简化计算)
        high_low = df['high'] - df['low']
        high_cp = (df['high'] - df['close'].shift()).abs()
        low_cp = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=ATR_PERIOD).mean()

        # ADX 计算核心逻辑
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
        
        return df.iloc[-1] # 返回最新一行数据

    def check_signals(self):
        """执行核心策略检查逻辑"""
        # 1. 获取账户净值
        account = self.ib.accountSummary()
        net_liquidation = float([i.value for i in account if i.tag == 'NetLiquidation'][0])
        
        # 2. 遍历标的
        for symbol in TICKERS:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            # 获取历史数据 (200+ 天确保均线准确)
            bars = self.ib.reqHistoricalData(
                contract, endDateTime='', durationStr='300 D',
                barSizeSetting='1 day', whatToShow='ADJUSTED_LAST', useRTH=True)
            
            if not bars: continue
            latest = self.get_indicators(bars)
            curr_price = bars[-1].close
            
            # 获取当前持仓
            pos = [p for p in self.ib.positions() if p.contract.symbol == symbol]
            
            if pos:
                # --- 持仓逻辑：止损检查 ---
                position = pos[0]
                # 这里可以根据成交价计算移动止损，简单起见检查死叉
                if latest['ema_fast'] < latest['ema_slow']:
                    logger.info(f"[{symbol}] EMA 死叉，准备离场。价格: {curr_price}")
                    self.ib.placeOrder(contract, MarketOrder('SELL', abs(position.position)))
            else:
                # --- 入场逻辑 ---
                cond_trend = curr_price > latest['ema_trend']
                cond_cross = latest['ema_fast'] > latest['ema_slow']
                cond_rsi = True # 简化版暂略 RSI
                cond_adx = latest['adx'] > ADX_THRESHOLD
                
                if cond_trend and cond_cross and cond_adx:
                    # 风险对等仓位计算
                    mult = INDEX_MULTIPLIER if symbol in INDICES else 1.0
                    risk_amt = net_liquidation * RISK_PER_TRADE * mult
                    risk_per_share = max(latest['atr'] * ATR_MULTIPLIER, 0.01)
                    size = int(risk_amt / risk_per_share)
                    
                    if size > 0:
                        logger.info(f"[{symbol}] 信号确认！ADX: {latest['adx']:.1f}，下单 {size} 股")
                        self.ib.placeOrder(contract, MarketOrder('BUY', size))

    def run(self):
        self.connect()
        while True:
            try:
                # 由于是日线策略，我们不需要秒级扫描
                # 实际运行可以在美股开盘期间每小时运行一次，或收盘前运行
                logger.info("开始例行扫描信号...")
                self.check_signals()
                logger.info("扫描完成，等待下一次运行 (1小时后)...")
                self.ib.sleep(3600) 
            except Exception as e:
                logger.error(f"运行异常: {e}")
                self.ib.sleep(60)

if __name__ == "__main__":
    system = LiveSystemV8()
    system.run()