"""
AlphaFlow 信号诊断脚本
=====================
检查 VOO/QQQ 为什么从上次回测的正收益变成了 0 交易或负收益。
"""

import yfinance as yf
import pandas as pd
import numpy as np
import sys
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup_path

setup_path(__file__)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from alphaflow.config import load_config


def diagnose_ticker(ticker, config):
    p = config['strategy']
    start = config['backtest']['start_date']
    end = config['backtest']['end_date']

    print(f'\n{"="*60}')
    print(f'  诊断标的: {ticker}')
    print(f'  回测区间: {start} ~ {end}')
    print(f'{"="*60}')

    # 1. 检查数据下载
    print(f'\n--- 步骤 1: 数据下载检查 ---')
    df_raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    print(f'  原始列名: {list(df_raw.columns)}')
    print(f'  列类型: {type(df_raw.columns)}')
    print(f'  是否 MultiIndex: {isinstance(df_raw.columns, pd.MultiIndex)}')

    # 扁平化
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)
        print(f'  扁平化后列名: {list(df_raw.columns)}')

    print(f'  数据行数: {len(df_raw)}')
    print(f'  日期范围: {df_raw.index[0].date()} ~ {df_raw.index[-1].date()}')
    print(f'  前 5 行收盘价:')
    print(df_raw['Close'].head())
    print(f'  后 5 行收盘价:')
    print(df_raw['Close'].tail())

    # 2. 计算技术指标
    print(f'\n--- 步骤 2: 技术指标计算 ---')
    df = df_raw.copy()
    fast = p.get('fast_period', 10)
    slow = p.get('slow_period', 25)
    trend = p.get('trend_period', 200)
    rsi_period = p.get('rsi_period', 14)
    rsi_upper = p.get('rsi_upper', 65)
    adx_period = p.get('adx_period', 14)
    adx_threshold = p.get('adx_threshold', 20)

    print(f'  参数: EMA({fast},{slow}), Trend EMA({trend}), RSI<{rsi_upper}, ADX>{adx_threshold}')

    df['EMA_fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
    df['EMA_slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
    df['EMA_trend'] = df['Close'].ewm(span=trend, adjust=False).mean()

    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=rsi_period - 1, min_periods=rsi_period).mean()
    avg_loss = loss.ewm(com=rsi_period - 1, min_periods=rsi_period).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 简单 ADX (近似)
    high = df['High']
    low = df['Low']
    close = df['Close']

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=adx_period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=adx_period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=adx_period, adjust=False).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df['ADX'] = dx.ewm(span=adx_period, adjust=False).mean()

    # 金叉信号
    df['cross'] = (df['EMA_fast'] > df['EMA_slow']) & (df['EMA_fast'].shift(1) <= df['EMA_slow'].shift(1))

    # 3. 扫描入场条件
    print(f'\n--- 步骤 3: 入场信号扫描 ---')
    df_valid = df.iloc[trend:]  # 跳过预热期

    # 找到所有金叉点
    cross_dates = df_valid[df_valid['cross'] == True].index
    print(f'  金叉次数: {len(cross_dates)}')

    if len(cross_dates) == 0:
        print(f'  ⚠️ 在整个回测期内没有发生任何 EMA 金叉！')
    else:
        for dt in cross_dates:
            row = df.loc[dt]
            trend_ok = row['Close'] > row['EMA_trend']
            rsi_ok = row['RSI'] < rsi_upper
            adx_ok = row['ADX'] > adx_threshold

            status = '✅ 入场' if (trend_ok and rsi_ok and adx_ok) else '❌ 过滤'
            reasons = []
            if not trend_ok:
                reasons.append(f'趋势失败(Close {row["Close"]:.2f} <= EMA200 {row["EMA_trend"]:.2f})')
            if not rsi_ok:
                reasons.append(f'RSI过高({row["RSI"]:.1f} >= {rsi_upper})')
            if not adx_ok:
                reasons.append(f'ADX过低({row["ADX"]:.1f} < {adx_threshold})')

            reason_str = ' | '.join(reasons) if reasons else '所有条件满足'
            print(f'  {dt.date()} | {status} | Close={row["Close"]:.2f} | EMA_f={row["EMA_fast"]:.2f} | '
                  f'EMA_s={row["EMA_slow"]:.2f} | EMA200={row["EMA_trend"]:.2f} | '
                  f'RSI={row["RSI"]:.1f} | ADX={row["ADX"]:.1f} | {reason_str}')

    # 4. 检查趋势过滤器覆盖率
    print(f'\n--- 步骤 4: 趋势过滤器统计 ---')
    above_trend = (df_valid['Close'] > df_valid['EMA_trend']).sum()
    total_days = len(df_valid)
    print(f'  价格在 EMA200 之上的天数: {above_trend}/{total_days} ({above_trend/total_days*100:.1f}%)')

    # 5. 检查 auto_adjust 的影响
    print(f'\n--- 步骤 5: 对比 auto_adjust ---')
    df_no_adj = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(df_no_adj.columns, pd.MultiIndex):
        df_no_adj.columns = df_no_adj.columns.get_level_values(0)

    print(f'  auto_adjust=True  最后收盘价: {df_raw["Close"].iloc[-1]:.2f}')
    print(f'  auto_adjust=False 最后收盘价: {df_no_adj["Close"].iloc[-1]:.2f}')
    print(f'  auto_adjust=False Adj Close : {df_no_adj["Adj Close"].iloc[-1]:.2f}')

    # 检查是否有重复列名的问题
    print(f'\n--- 步骤 6: 列名去重检查 ---')
    if isinstance(df_raw.columns, pd.Index):
        dupes = df_raw.columns[df_raw.columns.duplicated()].tolist()
        if dupes:
            print(f'  ⚠️ 发现重复列名: {dupes}')
        else:
            print(f'  ✅ 无重复列名')

    return df


if __name__ == '__main__':
    config = load_config()
    # 重点诊断 VOO（从 +28.33% 变成 0%）和 QQQ（从 +9.34% 变成 -3.46%）
    for ticker in ['VOO', 'QQQ']:
        diagnose_ticker(ticker, config)
