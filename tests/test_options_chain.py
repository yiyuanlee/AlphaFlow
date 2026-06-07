"""Tests for option chain selection helpers."""

from datetime import date

from alphaflow.options.chain import (
    days_to_expiry,
    filter_expiries_by_dte,
    limit_price_from_mid,
    select_expiry,
    select_strike_by_delta,
    spread_limit_credit,
)
from alphaflow.options.options_config import OptionsChainParams
from alphaflow.options.types import OptionQuote


def test_days_to_expiry():
    as_of = date(2025, 1, 1)
    assert days_to_expiry('20250131', as_of) == 30


def test_select_expiry_in_window():
    params = OptionsChainParams(dte_min=20, dte_max=40)
    as_of = date(2025, 1, 1)
    expiries = ['20250110', '20250201', '20250301']
    picked = select_expiry(expiries, params, as_of)
    assert picked == '20250201'


def test_filter_expiries_by_dte():
    params = OptionsChainParams(dte_min=21, dte_max=45)
    as_of = date(2025, 6, 1)
    expiries = ['20250630', '20250715', '20250915']
    valid = filter_expiries_by_dte(expiries, params, as_of)
    assert '20250630' in valid
    assert '20250915' not in valid


def test_select_strike_by_delta_puts():
    quotes = [
        OptionQuote('QQQ', '20250221', 400, 'P', -0.10, 1.0, 0.9, 1.1),
        OptionQuote('QQQ', '20250221', 390, 'P', -0.25, 2.0, 1.9, 2.1),
        OptionQuote('QQQ', '20250221', 380, 'P', -0.40, 3.5, 3.4, 3.6),
    ]
    picked = select_strike_by_delta(quotes, 0.25, 'P')
    assert picked is not None
    assert picked.strike == 390


def test_limit_price_from_mid():
    assert limit_price_from_mid(2.0, 0.02, 'SELL') == 1.96
    assert limit_price_from_mid(2.0, 0.02, 'BUY') == 2.04


def test_spread_limit_credit():
    assert spread_limit_credit(3.0, 1.0, 0.02) == 1.96
