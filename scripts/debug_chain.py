"""Fast one-day chain diagnostic."""

import io
import sys
import time

from _bootstrap import setup_path

setup_path(__file__)

from alphaflow.config import load_config, params_from_config
from alphaflow.data import fetch_data
from alphaflow.options.chain_data.base import create_chain_provider
from alphaflow.options.options_config import options_config_from_yaml
from alphaflow.options.regime import compute_regime_from_df
from alphaflow.options.signals import route_strategy
from alphaflow.options.underlying import build_underlying_snapshot

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DAY = '2025-02-15'
SYMBOL = 'QQQ'
config = load_config()
opt = options_config_from_yaml(config)
strat, _ = params_from_config(config)
provider = create_chain_provider(opt.chain_data)

t0 = time.time()
spot = provider.get_underlying_close(SYMBOL, DAY)
puts = provider.get_chain(SYMBOL, DAY, 'P')
elapsed = time.time() - t0
bench = fetch_data('QQQ', '2024-01-01', '2025-06-03')
regime = compute_regime_from_df(bench.loc[:DAY], opt.regime)
underlying = build_underlying_snapshot(SYMBOL, bench.loc[:DAY], stock_shares=100, strategy_params=strat)
intent = route_strategy(regime, underlying, opt)

print(f'Day: {DAY} | elapsed: {elapsed:.1f}s | fast={opt.chain_data.fast_mode}')
print(f'Spot: {spot} | Put quotes: {len(puts)}')
if puts:
    q = min(puts, key=lambda x: abs(abs(x.delta) - 0.25))
    print(f'Best put: strike={q.strike} close={q.close:.2f} delta={q.delta:.3f}')
print(f'Regime: {regime.regime.value} | Intent: {intent.value}')
