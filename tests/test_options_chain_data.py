"""Tests for option chain data layer."""

from pathlib import Path

from alphaflow.options.chain_data.black_scholes import delta, estimate_vol_from_price
from alphaflow.options.chain_data.csv_provider import CsvChainProvider
from alphaflow.options.chain_data.types import HistoricalOptionQuote
from alphaflow.options.options_config import OptionsChainDataParams


def test_black_scholes_delta_put():
    d = delta(400, 380, 30, 'P', 0.25)
    assert d < 0
    assert -0.5 < d < 0


def test_csv_provider_loads_chain(tmp_path: Path):
    csv_path = tmp_path / 'chain.csv'
    csv_path.write_text(
        'as_of,underlying,expiry,strike,right,close,delta,option_ticker\n'
        '2024-01-15,QQQ,20240216,380,P,2.35,-0.25,O:QQQ240216P00380000\n'
        '2024-01-15,QQQ,20240216,375,P,1.80,-0.18,O:QQQ240216P00375000\n',
        encoding='utf-8',
    )
    provider = CsvChainProvider(OptionsChainDataParams(provider='csv', csv_path=str(csv_path)))
    chain = provider.get_chain('QQQ', '2024-01-15', 'P')
    assert len(chain) == 2
    assert chain[0].strike == 380


def test_estimate_vol_positive():
    vol = estimate_vol_from_price(400, 380, 30, 'P', 2.5)
    assert 0.05 < vol < 2.0
