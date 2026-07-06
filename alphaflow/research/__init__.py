"""Research utilities (walk-forward, grid search, parity)."""

from alphaflow.research.grid import (
    DEFAULT_PARAM_GRID,
    QUICK_PARAM_GRID,
    grid_search_portfolio,
    grid_search_single,
    iter_param_combos,
    objective_score,
)
from alphaflow.research.parity import ParityResult, ParityThresholds, run_parity_check
from alphaflow.research.walkforward import (
    print_walk_forward_summary,
    run_walk_forward,
    save_walk_forward_results,
    walkforward_config_from_yaml,
)

__all__ = [
    "DEFAULT_PARAM_GRID",
    "QUICK_PARAM_GRID",
    "ParityResult",
    "ParityThresholds",
    "grid_search_portfolio",
    "grid_search_single",
    "iter_param_combos",
    "objective_score",
    "print_walk_forward_summary",
    "run_parity_check",
    "run_walk_forward",
    "save_walk_forward_results",
    "walkforward_config_from_yaml",
]
