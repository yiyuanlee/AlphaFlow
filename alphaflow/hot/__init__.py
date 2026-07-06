"""Hot-stock momentum strategy (archived)."""

from alphaflow.hot.config import (
    HotEntryParams,
    HotExitParams,
    HotMarketFilterParams,
    HotPositionParams,
    HotRiskParams,
    HotScannerParams,
    HotTradingConfig,
    hot_config_from_yaml,
)
from alphaflow.hot.grid_search import format_hot_grid_table, run_hot_grid_search, save_hot_grid_results
from alphaflow.hot.indicators import compute_daily_replay_indicators, compute_intraday_indicators
from alphaflow.hot.journal import load_hot_events, log_hot_event
from alphaflow.hot.market import build_market_regime_lookup, is_market_bullish
from alphaflow.hot.replay import run_daily_replay, summarize_replay
from alphaflow.hot.signals import calc_hot_position_size, check_hot_entry, check_hot_exit
from alphaflow.hot.stats import analyze_paper_journal, format_paper_stats, format_replay_stats

__all__ = [
    "HotEntryParams",
    "HotExitParams",
    "HotMarketFilterParams",
    "HotPositionParams",
    "HotRiskParams",
    "HotScannerParams",
    "HotTradingConfig",
    "analyze_paper_journal",
    "build_market_regime_lookup",
    "calc_hot_position_size",
    "check_hot_entry",
    "check_hot_exit",
    "compute_daily_replay_indicators",
    "compute_intraday_indicators",
    "format_hot_grid_table",
    "format_paper_stats",
    "format_replay_stats",
    "hot_config_from_yaml",
    "is_market_bullish",
    "load_hot_events",
    "log_hot_event",
    "run_daily_replay",
    "run_hot_grid_search",
    "save_hot_grid_results",
    "summarize_replay",
]
