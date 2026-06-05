"""pytest: Backtrader vs alphaflow.indicators parity."""

from alphaflow.config import load_config
from alphaflow.parity import ParityThresholds, run_parity_check


def test_qqq_indicator_parity():
    config = load_config()
    res = run_parity_check('QQQ', config, thresholds=ParityThresholds())
    assert res is not None
    assert res.pass_rate >= 99.0, f'QQQ parity pass rate {res.pass_rate:.2f}%'


def test_voo_indicator_parity():
    config = load_config()
    res = run_parity_check('VOO', config, thresholds=ParityThresholds())
    assert res is not None
    assert res.pass_rate >= 99.0, f'VOO parity pass rate {res.pass_rate:.2f}%'
