"""Tests for chain-based replay with CSV fixtures."""

from pathlib import Path

from alphaflow.options.chain_data.csv_provider import CsvChainProvider
from alphaflow.options.chain_replay import run_chain_replay
from alphaflow.options.options_config import OptionsChainDataParams


def _write_fixture(path: Path) -> None:
    rows = [
        'as_of,underlying,expiry,strike,right,close,delta,option_ticker',
        '2024-02-01,QQQ,20240315,420,C,3.10,0.24,O:QQQ240315C00420000',
        '2024-02-01,QQQ,20240315,400,P,2.80,-0.23,O:QQQ240315P00400000',
        '2024-02-01,QQQ,20240315,395,P,2.10,-0.18,O:QQQ240315P00395000',
        '2024-03-15,QQQ,20240315,420,C,0.50,0.80,O:QQQ240315C00420000',
        '2024-03-15,QQQ,20240315,400,P,0.00,-0.01,O:QQQ240315P00400000',
    ]
    path.write_text('\n'.join(rows) + '\n', encoding='utf-8')


def test_chain_replay_runs_with_csv(tmp_path: Path):
    csv_path = tmp_path / 'chain.csv'
    _write_fixture(csv_path)
    provider = CsvChainProvider(OptionsChainDataParams(provider='csv', csv_path=str(csv_path)))
    trades, summary = run_chain_replay('2024-01-01', '2024-04-01', 50_000.0, provider=provider)
    assert 'total_pnl' in summary
    assert summary['opens'] >= 0
