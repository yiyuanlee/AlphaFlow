"""Tests for options position state persistence."""

from pathlib import Path

from alphaflow.options.state import (
    OptionsPosition,
    StoredLeg,
    load_positions,
    new_position_id,
    save_positions,
)


def test_save_and_load_positions(tmp_path: Path):
    path = tmp_path / 'options_positions.json'
    pid = new_position_id('QQQ', 'cash_secured_put')
    positions = {
        pid: OptionsPosition(
            position_id=pid,
            strategy='cash_secured_put',
            symbol='QQQ',
            quantity=1,
            entry_premium=2.5,
            limit_price=2.45,
            max_loss=40_000,
            expiry='20250221',
            legs=[StoredLeg('QQQ', '20250221', 400.0, 'P', 'SELL', 1, 12345)],
            status='open',
        ),
    }
    save_positions(positions, path)
    loaded = load_positions(path)
    assert pid in loaded
    assert loaded[pid].symbol == 'QQQ'
    assert loaded[pid].legs[0].con_id == 12345
