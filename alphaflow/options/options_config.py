"""Options trading configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OptionsRegimeParams:
    benchmark: str = 'QQQ'
    trend_period: int = 200
    require_bull_market: bool = True
    adx_trend_threshold: float = 25.0
    adx_range_low: float = 15.0
    adx_range_high: float = 25.0


@dataclass(frozen=True)
class OptionsChainParams:
    dte_min: int = 21
    dte_max: int = 45
    delta_target_cc: float = 0.25
    delta_target_csp: float = 0.25
    delta_target_spread: float = 0.30
    spread_width: float = 5.0


@dataclass(frozen=True)
class OptionsRiskParams:
    max_contracts_per_symbol: int = 2
    max_portfolio_margin_pct: float = 0.30
    max_loss_per_trade: float = 500.0
    profit_take_pct: float = 0.50
    roll_dte: int = 7


@dataclass(frozen=True)
class OptionsExecutionParams:
    order_type: str = 'limit'
    limit_offset_pct: float = 0.02
    loop_seconds: int = 300


@dataclass(frozen=True)
class OptionsStrategyToggles:
    covered_call: bool = True
    cash_secured_put: bool = True
    bull_put_spread: bool = True
    bear_call_spread: bool = False


@dataclass(frozen=True)
class OptionsTradingConfig:
    regime: OptionsRegimeParams
    chain: OptionsChainParams
    risk: OptionsRiskParams
    execution: OptionsExecutionParams
    strategies: OptionsStrategyToggles
    client_id: int = 3
    underlyings: tuple[str, ...] = ('QQQ', 'VOO', 'AAPL', 'MSFT')
    stock_core: dict[str, int] = field(default_factory=lambda: {'QQQ': 100, 'VOO': 0, 'AAPL': 0, 'MSFT': 0})
    tws_host: str = '127.0.0.1'
    tws_port: int = 7497


def options_config_from_yaml(config: dict[str, Any]) -> OptionsTradingConfig:
    o = config.get('options_trading', {})
    live = config.get('live', {})
    regime = o.get('regime', {})
    chain = o.get('chain', {})
    risk = o.get('risk', {})
    execution = o.get('execution', {})
    strategies = o.get('strategies', {})
    stock_core_raw = o.get('stock_core', {'QQQ': 100, 'VOO': 0, 'AAPL': 0, 'MSFT': 0})

    return OptionsTradingConfig(
        client_id=o.get('client_id', 3),
        underlyings=tuple(o.get('underlyings', ['QQQ', 'VOO', 'AAPL', 'MSFT'])),
        stock_core={str(k): int(v) for k, v in stock_core_raw.items()},
        regime=OptionsRegimeParams(
            benchmark=regime.get('benchmark', 'QQQ'),
            trend_period=regime.get('trend_period', 200),
            require_bull_market=regime.get('require_bull_market', True),
            adx_trend_threshold=regime.get('adx_trend_threshold', 25.0),
            adx_range_low=regime.get('adx_range_low', 15.0),
            adx_range_high=regime.get('adx_range_high', 25.0),
        ),
        chain=OptionsChainParams(
            dte_min=chain.get('dte_min', 21),
            dte_max=chain.get('dte_max', 45),
            delta_target_cc=chain.get('delta_target_cc', 0.25),
            delta_target_csp=chain.get('delta_target_csp', 0.25),
            delta_target_spread=chain.get('delta_target_spread', 0.30),
            spread_width=chain.get('spread_width', 5.0),
        ),
        risk=OptionsRiskParams(
            max_contracts_per_symbol=risk.get('max_contracts_per_symbol', 2),
            max_portfolio_margin_pct=risk.get('max_portfolio_margin_pct', 0.30),
            max_loss_per_trade=risk.get('max_loss_per_trade', 500.0),
            profit_take_pct=risk.get('profit_take_pct', 0.50),
            roll_dte=risk.get('roll_dte', 7),
        ),
        execution=OptionsExecutionParams(
            order_type=execution.get('order_type', 'limit'),
            limit_offset_pct=execution.get('limit_offset_pct', 0.02),
            loop_seconds=execution.get('loop_seconds', 300),
        ),
        strategies=OptionsStrategyToggles(
            covered_call=strategies.get('covered_call', True),
            cash_secured_put=strategies.get('cash_secured_put', True),
            bull_put_spread=strategies.get('bull_put_spread', True),
            bear_call_spread=strategies.get('bear_call_spread', False),
        ),
        tws_host=live.get('tws_host', '127.0.0.1'),
        tws_port=live.get('tws_port', 7497),
    )
