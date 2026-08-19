# AlphaFlow SPY ORB Scalper Runbook

This runtime is a fail-closed SPY stock paper-trading pilot. It is isolated from
the QQQ covered-call service by account, Gateway port, client ID, database,
HALT file, process lock, heartbeat, and audit journal. It must never be pointed
at a live account.

## Safety boundary

- IB Gateway paper port `4004`, API `client_id=4`, and exactly one managed
  account matching `IBKR_SCALP_PAPER_ACCOUNT`.
- Default `shadow_mode: true` and `trading_enabled: false`.
- SPY shares only; one position, no leverage, no overnight holding.
- SQLite WAL at `state/scalper.db`, HALT at `state/SCALP_HALT`, and JSONL audit
  at `output/spy_orb.jsonl`. None of these files are shared with V11 options.
- A live/wrong account is disconnected without cancelling or submitting any
  order. Credentials and 2FA are never stored by AlphaFlow.

The historical/live minute feed uses IBKR `TRADES`, RTH, completed one-minute
bars, a paced resumable cache, and a single `keepUpToDate` subscription. See
[IBKR TWS API documentation](https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/).

## Strategy

The 15 completed bars from 09:30 through 09:44 ET define the opening range.
Between 09:45 and 11:30 ET, a long requires a first close at least `$0.01`
above the range, price above daily VWAP, EMA9 above EMA21, and relative volume
of at least 1.5. Shorts are symmetric and additionally require live IBKR
shortable shares and no account restriction.

Risk per trade is 0.20% of opening NLV. One R is the greater of 0.10% of entry
and 0.5×ATR14; signals over 0.30% are skipped. Position size is capped by the
risk budget, available funds, and 100% of NLV notional. The bracket uses a 1R
stop, 1.5R target and 20-minute time exit. Daily loss locks at 1.00%; all shares
are flattened 15 minutes before the actual XNYS close, including half days.

Bracket transmission follows the IBKR sequence documented in
[Bracket Orders](https://ibkrcampus.com/docs/general/order-types/complex-orders/bracket-orders):
parent `Transmit=false`, target `false`, stop `true`. A partial fill cancels the
parent remainder and resizes the protective children. Any filled quantity
without a valid stop after two seconds is market-flattened and HALTed.

## Install and configure

```powershell
uv venv --python 3.11 .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

[Environment]::SetEnvironmentVariable("IBKR_SCALP_PAPER_ACCOUNT", "DUxxxxxxx", "User")
[Environment]::SetEnvironmentVariable("ALPHAFLOW_TELEGRAM_BOT_TOKEN", "...", "User")
[Environment]::SetEnvironmentVariable("ALPHAFLOW_TELEGRAM_CHAT_ID", "...", "User")
```

Run a second paper IB Gateway instance on port `4004`, enable socket clients,
download open orders on connection, subscribe to live US stock data, and enable
daily restart. Keep the Windows user logged in and plan for periodic manual
Gateway re-authentication.

```powershell
.venv\Scripts\alphaflow.exe scalp doctor --profile paper_spy_orb
.venv\Scripts\alphaflow.exe scalp status --profile paper_spy_orb --json
```

The doctor reports IBKR-provided account restrictions, buying power, shortable
shares and Day Trades Remaining. It intentionally does not hard-code a `$25k`
PDT rule during the 2026–2027 transition; see the
[FINRA transition explanation](https://syndication.finra.org/content/understanding-new-intraday-margin-requirements)
and [IBKR account fields](https://www.ibkrguides.com/traderworkstation/available-for-trading.htm).

## Three-month backtest gate

By default the commands use the latest three complete calendar months. The
cache stores UTC and ET timestamps and can resume incomplete sessions.

```powershell
.venv\Scripts\alphaflow.exe scalp download --profile paper_spy_orb
.venv\Scripts\alphaflow.exe scalp backtest --profile paper_spy_orb
```

Signals fill only at the next minute open with one basis point of adverse
slippage per fill and `$0.005/share`, minimum `$1/order`, commissions. If stop
and target touch in the same minute the stop is filled first. The final month
is out-of-sample. Both all-data and OOS results must be profitable after costs,
Profit Factor at least 1.10 and max drawdown at most 5%; require at least 60 and
15 completed trades respectively.

## Shadow, paper, and operations

Run five complete XNYS sessions with the safe defaults:

```powershell
.venv\Scripts\alphaflow.exe scalp run --profile paper_spy_orb --daemon
```

Only after the backtest passes, doctor is clean, Telegram delivery works, and
`shadow_sessions >= 5`, change exactly:

```yaml
shadow_mode: false
trading_enabled: true
```

Useful controls:

```powershell
.venv\Scripts\alphaflow.exe scalp reconcile --profile paper_spy_orb
.venv\Scripts\alphaflow.exe scalp halt --profile paper_spy_orb --reason "maintenance"
.venv\Scripts\alphaflow.exe scalp resume --profile paper_spy_orb --confirm-account DUxxxxxxx
powershell -ExecutionPolicy Bypass -File scripts\install_scalping_windows_tasks.ps1
```

Paper acceptance requires at least 10 trading days and 30 complete entry/exit
cycles: zero live orders, overnight positions, unprotected positions, duplicate
orders or unexplained differences; at least 99% successful monitoring cycles;
daily-loss flattening within five seconds and critical alerts within one minute.
