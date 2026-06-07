# AlphaFlow Options Strategy (V10)

## Overview

AlphaFlow V10 shifts the primary live sleeve from equity momentum to **options income and defined-risk spreads** on:

- **ETFs:** QQQ, VOO
- **Blue chips:** AAPL, MSFT (extensible via `config.yaml`)

A small **stock core** (`stock_core`) supports covered calls (e.g. QQQ 100 shares).

## Architecture

| Module | Role |
|--------|------|
| `alphaflow/options/regime.py` | QQQ benchmark regime (EMA200, ADX, RSI) |
| `alphaflow/options/signals.py` | Route intent by regime + underlying state |
| `alphaflow/options/chain.py` | IBKR chain fetch, DTE/delta strike selection |
| `alphaflow/options/sizing.py` | Contract sizing and portfolio margin caps |
| `alphaflow/options/execution.py` | Limit orders (single-leg + credit spreads) |
| `alphaflow/options/manager.py` | Open/close, 50% profit take, roll signals |
| `alphaflow/options/underlying.py` | Stock core rebalance for CC collateral |

**Live entry:** `python scripts/live/ibkr_options.py` (TWS client_id=3)

## Regime routing (balanced mode)

| Regime | Condition | Primary strategy |
|--------|-----------|------------------|
| Strong uptrend | QQQ > EMA200, ADX ≥ 25, golden cross | Bull Put Spread |
| Mild bull / range | QQQ > EMA200, ADX 15–25 | Covered Call (if ≥100 shares) or CSP |
| Weak | QQQ < EMA200 or high RSI | Hold / manage only |
| Sharp drop | Below EMA200 + high ADX | Bear Call Spread (optional, default off) |

Per-strategy toggles in `options_trading.strategies`.

## Risk controls

- `max_contracts_per_symbol`
- `max_loss_per_trade` (vertical spreads)
- `max_portfolio_margin_pct` (portfolio cash at risk)
- `profit_take_pct` (default 50% of entry premium)
- `roll_dte` (alert when DTE ≤ 7)

## Paper validation

- Journal: `output/options_trades.jsonl`
- Stats: `python scripts/options_paper_stats.py`
- State: `state/options_positions.json`
- Proxy replay (routing only, **not** chain-accurate PnL): `python scripts/options_replay_proxy.py`

## Requirements

- IBKR **margin** account with options permissions
- CSP requires cash secured at strike × 100
- Covered call requires **100-share** lots

## Deprecated

- `scripts/live/ibkr_hot_stocks.py` — archived under `archive/scripts/live/`
- V8 momentum entries — do not run alongside `ibkr_options.py`

## Out of scope (V10)

- Full historical option chain backtest
- 0DTE, iron condor, calendar spreads
- Auto delta hedge
