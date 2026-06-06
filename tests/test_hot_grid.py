"""Unit tests for hot-stock grid scoring."""

from alphaflow.hot_grid import hot_objective_score


def test_balanced_penalizes_zero_trades():
    score = hot_objective_score({'trades': 0, 'total_return_pct': 50}, 'balanced')
    assert score == -999.0


def test_balanced_rewards_trades_and_return():
    score = hot_objective_score({
        'trades': 5,
        'total_return_pct': 10.0,
        'max_drawdown_pct': -4.0,
        'profit_factor': 1.5,
    }, 'balanced')
    assert score > 0
