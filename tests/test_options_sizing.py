"""Tests for options sizing and risk."""

from alphaflow.options.options_config import OptionsRiskParams
from alphaflow.options.sizing import (
    allow_new_trade,
    csp_max_loss,
    portfolio_margin_used,
    size_cash_secured_put,
    size_covered_call,
    size_vertical_spread,
)


def test_size_covered_call():
    assert size_covered_call(250, 1, 2) == 1
    assert size_covered_call(50, 0, 2) == 0


def test_size_cash_secured_put():
    assert size_cash_secured_put(50_000, 400, 2) == 1
    assert size_cash_secured_put(10_000, 400, 2) == 0


def test_size_vertical_spread():
    assert size_vertical_spread(5, 500, 2) == 1
    assert size_vertical_spread(10, 500, 2) == 0


def test_csp_max_loss():
    assert csp_max_loss(400, 2) == 80_000


def test_allow_new_trade():
    risk = OptionsRiskParams(max_portfolio_margin_pct=0.30, max_loss_per_trade=500)
    assert allow_new_trade(risk, [1000], 400, 20_000) is True
    assert allow_new_trade(risk, [6000], 400, 20_000) is False
    assert allow_new_trade(risk, [], 600, 20_000) is False


def test_portfolio_margin_used():
    assert portfolio_margin_used([3000], 10_000) == 0.3
