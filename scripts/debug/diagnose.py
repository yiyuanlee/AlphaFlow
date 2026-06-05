import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup_path

setup_path(__file__)

import yfinance as yf
import pandas as pd
import numpy as np

from alphaflow.config import output_path

out = []

def log(msg):
    out.append(str(msg))

tickers = ['VOO', 'QQQ']
for ticker in tickers:
    log(f"\n{'='*60}")
    log(f"  DIAGNOSING: {ticker}")
    log(f"{'='*60}")
    
    df = yf.download(ticker, start='2022-01-01', end='2026-03-20', progress=False, auto_adjust=True)
    log(f"Column type: {type(df.columns).__name__}")
    log(f"Columns: {list(df.columns)}")
    log(f"Is MultiIndex: {isinstance(df.columns, pd.MultiIndex)}")
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        log(f"Flattened: {list(df.columns)}")
    
    log(f"Has dupes: {df.columns.duplicated().any()}")
    log(f"Data rows: {len(df)}")
    log(f"Date range: {df.index[0].date()} to {df.index[-1].date()}")
    
    # Calculate indicators
    fast, slow, trend_p = 10, 25, 200
    rsi_period, rsi_upper = 14, 65
    adx_period, adx_threshold = 14, 20
    
    df['EMA_fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
    df['EMA_slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
    df['EMA_trend'] = df['Close'].ewm(span=trend_p, adjust=False).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=rsi_period-1, min_periods=rsi_period).mean()
    avg_loss = loss.ewm(com=rsi_period-1, min_periods=rsi_period).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Simple ADX approximation
    high, low_p, close = df['High'], df['Low'], df['Close']
    plus_dm = high.diff()
    minus_dm = -low_p.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    
    tr1 = high - low_p
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low_p - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.ewm(span=adx_period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=adx_period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=adx_period, adjust=False).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df['ADX'] = dx.ewm(span=adx_period, adjust=False).mean()
    
    # Find crossovers after warmup
    df['cross'] = (df['EMA_fast'] > df['EMA_slow']) & (df['EMA_fast'].shift(1) <= df['EMA_slow'].shift(1))
    
    df_valid = df.iloc[trend_p:]
    above = (df_valid['Close'] > df_valid['EMA_trend']).sum()
    total = len(df_valid)
    log(f"Days above EMA200: {above}/{total} ({above/total*100:.1f}%)")
    
    cross_dates = df_valid[df_valid['cross'] == True].index
    log(f"Golden crosses: {len(cross_dates)}")
    
    for dt in cross_dates:
        row = df.loc[dt]
        trend_ok = row['Close'] > row['EMA_trend']
        rsi_ok = row['RSI'] < rsi_upper
        adx_ok = row['ADX'] > adx_threshold
        
        status = 'ENTRY' if (trend_ok and rsi_ok and adx_ok) else 'FILTERED'
        reasons = []
        if not trend_ok: reasons.append(f"TREND_FAIL(Close={row['Close']:.2f} <= EMA200={row['EMA_trend']:.2f})")
        if not rsi_ok: reasons.append(f"RSI_HIGH({row['RSI']:.1f}>={rsi_upper})")
        if not adx_ok: reasons.append(f"ADX_LOW({row['ADX']:.1f}<{adx_threshold})")
        
        reason_str = ' | '.join(reasons) if reasons else 'ALL_CONDITIONS_MET'
        log(f"  {dt.date()} | {status} | Close={row['Close']:.2f} EMA_f={row['EMA_fast']:.2f} EMA_s={row['EMA_slow']:.2f} EMA200={row['EMA_trend']:.2f} RSI={row['RSI']:.1f} ADX={row['ADX']:.1f} | {reason_str}")

# Also compare auto_adjust effect
log(f"\n{'='*60}")
log(f"  AUTO_ADJUST COMPARISON")
log(f"{'='*60}")
for ticker in ['VOO', 'QQQ']:
    df_adj = yf.download(ticker, start='2022-01-01', end='2026-03-20', progress=False, auto_adjust=True)
    df_noadj = yf.download(ticker, start='2022-01-01', end='2026-03-20', progress=False, auto_adjust=False)
    if isinstance(df_adj.columns, pd.MultiIndex):
        df_adj.columns = df_adj.columns.get_level_values(0)
    if isinstance(df_noadj.columns, pd.MultiIndex):
        df_noadj.columns = df_noadj.columns.get_level_values(0)
    log(f"\n{ticker}:")
    log(f"  auto_adjust=True  last Close: {df_adj['Close'].iloc[-1]:.4f}")
    log(f"  auto_adjust=False last Close: {df_noadj['Close'].iloc[-1]:.4f}")
    if 'Adj Close' in df_noadj.columns:
        log(f"  auto_adjust=False last AdjClose: {df_noadj['Adj Close'].iloc[-1]:.4f}")

with open(output_path('diagnosis_output.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
    
print("DONE - see output/diagnosis_output.txt")
