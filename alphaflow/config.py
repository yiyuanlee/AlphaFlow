"""Configuration loading and typed parameter objects."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class StrategyParams:
    fast_period: int = 10
    slow_period: int = 25
    trend_period: int = 200
    rsi_period: int = 14
    rsi_upper: float = 65
    adx_period: int = 14
    adx_threshold: float = 20
    atr_period: int = 14
    atr_multiplier: float = 2.5
    vol_filter_period: int = 100
    vol_filter_ratio: float = 0.8
    trailing_atr_mult: float = 3.0
    trailing_stop: float = 0.12


@dataclass(frozen=True)
class RiskParams:
    risk_per_trade: float = 0.030
    alloc_index: float = 0.60
    alloc_stock: float = 0.40
    index_multiplier: float = 3.0


def load_config(path: str | Path = 'config.yaml') -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def params_from_config(config: dict[str, Any]) -> tuple[StrategyParams, RiskParams]:
    s = config.get('strategy', {})
    r = config.get('risk', {})
    strategy = StrategyParams(
        fast_period=s.get('fast_period', 10),
        slow_period=s.get('slow_period', 25),
        trend_period=s.get('trend_period', 200),
        rsi_period=s.get('rsi_period', 14),
        rsi_upper=s.get('rsi_upper', 65),
        adx_period=s.get('adx_period', 14),
        adx_threshold=s.get('adx_threshold', 20),
        atr_period=s.get('atr_period', 14),
        atr_multiplier=s.get('atr_multiplier', 2.5),
        vol_filter_period=s.get('vol_filter_period', 100),
        vol_filter_ratio=s.get('vol_filter_ratio', 0.8),
        trailing_atr_mult=s.get('trailing_atr_mult', 3.0),
        trailing_stop=s.get('trailing_stop', 0.12),
    )
    risk = RiskParams(
        risk_per_trade=r.get('risk_per_trade', 0.030),
        alloc_index=r.get('alloc_index', 0.60),
        alloc_stock=r.get('alloc_stock', 0.40),
        index_multiplier=r.get('index_multiplier', 3.0),
    )
    return strategy, risk


def strategy_params_to_bt(strategy: StrategyParams, risk: RiskParams) -> dict[str, Any]:
    """Convert typed params to Backtrader strategy kwargs."""
    return {
        'fast_period': strategy.fast_period,
        'slow_period': strategy.slow_period,
        'trend_period': strategy.trend_period,
        'rsi_period': strategy.rsi_period,
        'rsi_upper': strategy.rsi_upper,
        'adx_period': strategy.adx_period,
        'adx_threshold': strategy.adx_threshold,
        'atr_period': strategy.atr_period,
        'atr_multiplier': strategy.atr_multiplier,
        'vol_filter_period': strategy.vol_filter_period,
        'vol_filter_ratio': strategy.vol_filter_ratio,
        'trailing_atr_mult': strategy.trailing_atr_mult,
        'trailing_stop': strategy.trailing_stop,
        'risk_per_trade': risk.risk_per_trade,
        'alloc_index': risk.alloc_index,
        'alloc_stock': risk.alloc_stock,
        'index_multiplier': risk.index_multiplier,
    }
