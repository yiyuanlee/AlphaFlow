"""Debug why chain replay has zero opens."""

import io
import sys

from _bootstrap import setup_path

setup_path(__file__)

import pandas as pd
from alphaflow.config import load_config, params_from_config
from alphaflow.data import fetch_data
from alphaflow.options.chain_data.base import create_chain_provider
from alphaflow.options.chain_replay import _pick_quote, _try_open_position
from alphaflow.options.options_config import options_config_from_yaml
from alphaflow.options.regime import build_benchmark_regime_lookup
from alphaflow.options.signals import route_strategy
from alphaflow.options.underlying import build_underlying_snapshot

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

start, end, symbol = '2025-01-01', '2025-03-31', 'QQQ'
config = load_config()
opt = options_config_from_yaml(config)
strat, _ = params_from_config(config)
provider = create_chain_provider(opt.chain_data)
lookback = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime('%Y-%m-%d')
bench = fetch_data(opt.regime.benchmark, lookback, end)
regime_lookup = build_benchmark_regime_lookup(bench, opt.regime)
df = fetch_data(symbol, lookback, end)
stride = opt.chain_data.replay_stride_days
days = [d for d in sorted(regime_lookup) if d >= start][::stride]

for day in days[:8]:
    regime = regime_lookup[day]
    underlying = build_underlying_snapshot(symbol, df.loc[:day], stock_shares=100, strategy_params=strat)
    intent = route_strategy(regime, underlying, opt)
    quote = None
    if intent.value == 'covered_call':
        quote = _pick_quote(provider, symbol, day, 'C', opt.chain.delta_target_cc, opt.chain)
    elif intent.value == 'cash_secured_put':
        quote = _pick_quote(provider, symbol, day, 'P', opt.chain.delta_target_csp, opt.chain)
    opened = _try_open_position(provider, opt, symbol, day, intent, underlying, 50_000.0, [])
    print(f'{day} regime={regime.regime.value} intent={intent.value} quote={quote is not None} open={opened is not None}')
