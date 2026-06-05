"""Hot-stock momentum trading configuration."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HotScannerParams:
    scan_code: str = 'TOP_PERC_GAIN'
    location_code: str = 'STK.US.MAJOR'
    min_price: float = 10.0
    min_volume: int = 1_000_000
    max_results: int = 15
    rescan_minutes: int = 15


@dataclass(frozen=True)
class HotMarketFilterParams:
    benchmark: str = 'QQQ'
    trend_period: int = 200
    require_bull_market: bool = True


@dataclass(frozen=True)
class HotPositionParams:
    max_hold_days: int = 5
    max_positions: int = 5
    max_single_position_pct: float = 0.10


@dataclass(frozen=True)
class HotEntryParams:
    fast_ema: int = 9
    slow_ema: int = 21
    rsi_period: int = 14
    rsi_max: float = 70.0
    require_above_vwap: bool = True
    require_golden_cross: bool = True
    adx_period: int = 14
    min_adx: float = 20.0
    rel_volume_period: int = 20
    min_rel_volume: float = 1.2
    require_bull_market: bool = True


@dataclass(frozen=True)
class HotExitParams:
    take_profit_pct: float = 0.05
    stop_loss_pct: float = 0.04
    use_ema_cross: bool = True
    use_vwap_break: bool = True
    force_exit_on_max_hold: bool = True


@dataclass(frozen=True)
class HotRiskParams:
    risk_per_trade: float = 0.02
    stock_pool_pct: float = 0.40
    pool_drawdown_halt_pct: float = 0.05


@dataclass(frozen=True)
class HotReplayParams:
    start_date: str = '2023-01-01'
    end_date: str = '2026-06-03'
    initial_cash: float = 20_000.0
    commission: float = 0.001


@dataclass(frozen=True)
class HotTradingConfig:
    scanner: HotScannerParams
    market: HotMarketFilterParams
    position: HotPositionParams
    entry: HotEntryParams
    exit: HotExitParams
    risk: HotRiskParams
    replay: HotReplayParams
    loop_seconds: int = 60
    exclude_symbols: tuple[str, ...] = ()


def hot_config_from_yaml(config: dict[str, Any]) -> HotTradingConfig:
    h = config.get('hot_trading', {})
    s = h.get('scanner', {})
    m = h.get('market_filter', {})
    p = h.get('position', {})
    e = h.get('entry', {})
    x = h.get('exit', {})
    r = h.get('risk', {})
    rp = h.get('replay', {})

    stock_pool = r.get('stock_pool_pct', config.get('risk', {}).get('alloc_stock', 0.40))
    require_bull = e.get('require_bull_market', m.get('require_bull_market', True))

    return HotTradingConfig(
        scanner=HotScannerParams(
            scan_code=s.get('scan_code', 'TOP_PERC_GAIN'),
            location_code=s.get('location_code', 'STK.US.MAJOR'),
            min_price=s.get('min_price', 10.0),
            min_volume=s.get('min_volume', 1_000_000),
            max_results=s.get('max_results', 15),
            rescan_minutes=s.get('rescan_minutes', 15),
        ),
        market=HotMarketFilterParams(
            benchmark=m.get('benchmark', 'QQQ'),
            trend_period=m.get('trend_period', 200),
            require_bull_market=require_bull,
        ),
        position=HotPositionParams(
            max_hold_days=p.get('max_hold_days', 5),
            max_positions=p.get('max_positions', 5),
            max_single_position_pct=p.get('max_single_position_pct', 0.10),
        ),
        entry=HotEntryParams(
            fast_ema=e.get('fast_ema', 9),
            slow_ema=e.get('slow_ema', 21),
            rsi_period=e.get('rsi_period', 14),
            rsi_max=e.get('rsi_max', 70.0),
            require_above_vwap=e.get('require_above_vwap', True),
            require_golden_cross=e.get('require_golden_cross', True),
            adx_period=e.get('adx_period', 14),
            min_adx=e.get('min_adx', 20.0),
            rel_volume_period=e.get('rel_volume_period', 20),
            min_rel_volume=e.get('min_rel_volume', 1.2),
            require_bull_market=require_bull,
        ),
        exit=HotExitParams(
            take_profit_pct=x.get('take_profit_pct', 0.05),
            stop_loss_pct=x.get('stop_loss_pct', 0.04),
            use_ema_cross=x.get('use_ema_cross', True),
            use_vwap_break=x.get('use_vwap_break', True),
            force_exit_on_max_hold=x.get('force_exit_on_max_hold', True),
        ),
        risk=HotRiskParams(
            risk_per_trade=r.get('risk_per_trade', 0.02),
            stock_pool_pct=stock_pool,
            pool_drawdown_halt_pct=r.get('pool_drawdown_halt_pct', 0.05),
        ),
        replay=HotReplayParams(
            start_date=rp.get('start_date', config.get('backtest', {}).get('start_date', '2023-01-01')),
            end_date=rp.get('end_date', config.get('backtest', {}).get('end_date', '2026-06-03')),
            initial_cash=rp.get('initial_cash', config.get('backtest', {}).get('initial_cash', 20_000.0) * 0.4),
            commission=rp.get('commission', config.get('backtest', {}).get('commission', 0.001)),
        ),
        loop_seconds=h.get('loop_seconds', 60),
        exclude_symbols=tuple(h.get('exclude_symbols', ['VOO', 'QQQ', 'SPY', 'IWM'])),
    )
