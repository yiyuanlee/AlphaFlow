"""Indicator parity checks: Backtrader vs alphaflow.indicators (live module)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import backtrader as bt
import pandas as pd

from alphaflow.config import StrategyParams, params_from_config
from alphaflow.data import fetch_data
from alphaflow.indicators import compute_indicators


@dataclass(frozen=True)
class ParityThresholds:
    ema_rel_pct: float = 0.01
    rsi_abs: float = 1.0
    atr_rel_pct: float = 1.0
    adx_abs: float = 5.0
    atr_sma_rel_pct: float = 1.0


@dataclass
class ParityResult:
    ticker: str
    rows_compared: int
    pass_rate: float
    failures: list[dict[str, Any]]
    summary: dict[str, dict[str, float]]
    passed: bool


class _IndicatorRecorder(bt.Strategy):
    """Record Backtrader indicator values bar-by-bar."""

    params = dict(
        fast_period=10,
        slow_period=25,
        trend_period=200,
        rsi_period=14,
        adx_period=14,
        atr_period=14,
        vol_filter_period=100,
    )

    def __init__(self):
        self.rows: list[dict[str, Any]] = []
        atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        ema_fast = bt.indicators.EMA(self.data, period=self.p.fast_period)
        ema_slow = bt.indicators.EMA(self.data, period=self.p.slow_period)
        self.inds = {
            'ema_fast': ema_fast,
            'ema_slow': ema_slow,
            'ema_trend': bt.indicators.EMA(self.data, period=self.p.trend_period),
            'rsi': bt.indicators.RSI(self.data, period=self.p.rsi_period),
            'atr': atr,
            'adx': bt.indicators.ADX(self.data, period=self.p.adx_period),
            'atr_sma': bt.indicators.SMA(atr, period=self.p.vol_filter_period),
            'crossover': bt.indicators.CrossOver(ema_fast, ema_slow),
        }

    def next(self):
        dt = self.data.datetime.date(0)
        self.rows.append({
            'date': dt.isoformat(),
            'close': float(self.data.close[0]),
            'ema_fast': float(self.inds['ema_fast'][0]),
            'ema_slow': float(self.inds['ema_slow'][0]),
            'ema_trend': float(self.inds['ema_trend'][0]),
            'rsi': float(self.inds['rsi'][0]),
            'atr': float(self.inds['atr'][0]),
            'adx': float(self.inds['adx'][0]),
            'atr_sma': float(self.inds['atr_sma'][0]),
            'golden_cross': bool(self.inds['crossover'][0] > 0),
        })


def _run_backtrader_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(
        _IndicatorRecorder,
        fast_period=params.fast_period,
        slow_period=params.slow_period,
        trend_period=params.trend_period,
        rsi_period=params.rsi_period,
        adx_period=params.adx_period,
        atr_period=params.atr_period,
        vol_filter_period=params.vol_filter_period,
    )
    strats = cerebro.run()
    return pd.DataFrame(strats[0].rows)


def _rel_pct_diff(a: float, b: float) -> float:
    if a == 0 and b == 0:
        return 0.0
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom * 100


def _check_row(
    row: pd.Series,
    thresholds: ParityThresholds,
) -> list[dict[str, Any]]:
    issues = []

    for col, rel_limit in (
        ('ema_fast', thresholds.ema_rel_pct),
        ('ema_slow', thresholds.ema_rel_pct),
        ('ema_trend', thresholds.ema_rel_pct),
    ):
        diff = _rel_pct_diff(row[f'bt_{col}'], row[f'py_{col}'])
        if diff > rel_limit:
            issues.append({
                'field': col,
                'type': 'rel_pct',
                'diff': diff,
                'limit': rel_limit,
                'backtrader': row[f'bt_{col}'],
                'alphaflow': row[f'py_{col}'],
            })

    rsi_diff = abs(row['bt_rsi'] - row['py_rsi'])
    if rsi_diff > thresholds.rsi_abs:
        issues.append({
            'field': 'rsi',
            'type': 'abs',
            'diff': rsi_diff,
            'limit': thresholds.rsi_abs,
            'backtrader': row['bt_rsi'],
            'alphaflow': row['py_rsi'],
        })

    atr_diff = _rel_pct_diff(row['bt_atr'], row['py_atr'])
    if atr_diff > thresholds.atr_rel_pct:
        issues.append({
            'field': 'atr',
            'type': 'rel_pct',
            'diff': atr_diff,
            'limit': thresholds.atr_rel_pct,
            'backtrader': row['bt_atr'],
            'alphaflow': row['py_atr'],
        })

    adx_diff = abs(row['bt_adx'] - row['py_adx'])
    if adx_diff > thresholds.adx_abs:
        issues.append({
            'field': 'adx',
            'type': 'abs',
            'diff': adx_diff,
            'limit': thresholds.adx_abs,
            'backtrader': row['bt_adx'],
            'alphaflow': row['py_adx'],
        })

    atr_sma_diff = _rel_pct_diff(row['bt_atr_sma'], row['py_atr_sma'])
    if atr_sma_diff > thresholds.atr_sma_rel_pct:
        issues.append({
            'field': 'atr_sma',
            'type': 'rel_pct',
            'diff': atr_sma_diff,
            'limit': thresholds.atr_sma_rel_pct,
            'backtrader': row['bt_atr_sma'],
            'alphaflow': row['py_atr_sma'],
        })

    if bool(row['bt_golden_cross']) != bool(row['py_golden_cross']):
        issues.append({
            'field': 'golden_cross',
            'type': 'bool',
            'diff': 1.0,
            'limit': 0.0,
            'backtrader': bool(row['bt_golden_cross']),
            'alphaflow': bool(row['py_golden_cross']),
        })

    return issues


def run_parity_check(
    ticker: str,
    config: dict,
    thresholds: ParityThresholds | None = None,
    start: str | None = None,
    end: str | None = None,
    max_failures: int = 20,
) -> ParityResult | None:
    thresholds = thresholds or ParityThresholds()
    strategy, _ = params_from_config(config)

    start = start or config['backtest']['start_date']
    end = end or config['backtest']['end_date']

    df = fetch_data(ticker, start, end)
    if df is None or len(df) < strategy.trend_period + 10:
        return None

    bt_df = _run_backtrader_indicators(df, strategy)
    py_df = compute_indicators(df, strategy).copy()
    py_df['date'] = py_df.index.strftime('%Y-%m-%d')

    bt_df = bt_df.add_prefix('bt_').rename(columns={'bt_date': 'date'})
    py_cols = {
        'ema_fast': 'py_ema_fast',
        'ema_slow': 'py_ema_slow',
        'ema_trend': 'py_ema_trend',
        'rsi': 'py_rsi',
        'atr': 'py_atr',
        'adx': 'py_adx',
        'atr_sma': 'py_atr_sma',
        'golden_cross': 'py_golden_cross',
    }
    py_df = py_df.rename(columns=py_cols)
    py_df['date'] = py_df['date'].astype(str)

    merged = bt_df.merge(
        py_df[['date', *py_cols.values()]],
        on='date',
        how='inner',
    )
    merged = merged.iloc[strategy.trend_period:]

    failures: list[dict[str, Any]] = []
    field_max: dict[str, float] = {}

    for _, row in merged.iterrows():
        issues = _check_row(row, thresholds)
        if not issues:
            continue
        for issue in issues:
            field = issue['field']
            field_max[field] = max(field_max.get(field, 0.0), float(issue['diff']))
        failures.append({'date': row['date'], 'issues': issues})
        if len(failures) >= max_failures:
            break

    rows_compared = len(merged)
    fail_rows = sum(1 for _, row in merged.iterrows() if _check_row(row, thresholds))
    pass_rate = (rows_compared - fail_rows) / rows_compared * 100 if rows_compared else 0.0

    return ParityResult(
        ticker=ticker,
        rows_compared=rows_compared,
        pass_rate=pass_rate,
        failures=failures,
        summary={k: {'max_diff': v} for k, v in field_max.items()},
        passed=fail_rows == 0,
    )
