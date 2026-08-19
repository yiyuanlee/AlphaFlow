# AlphaFlow V11 Unattended Paper Runbook

V11 is a fail-closed pilot for one QQQ covered call in an IBKR paper account.
It never buys stock, never connects to a live account, and does not enable CSP,
vertical spreads, rolling, V8, or V9.

## 1. Prepare IB Gateway

1. Install the stable IB Gateway and sign in with the paper username.
2. Enable socket API clients, set the paper socket port to `4002`, enable
   downloading open orders on connection, and enable daily auto-restart.
3. Subscribe the paper username to real-time US stock and options data.
4. Manually hold at least 100 QQQ shares in the paper account.
5. Keep the Windows user session logged in. IB Gateway still requires periodic
   manual authentication; credentials and 2FA are never stored by AlphaFlow.

IBKR references: [TWS API and Gateway operation](https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/)
and [open-order recovery constraints](https://interactivebrokers.github.io/tws-api/open_orders.html).

## 2. Install and configure

```powershell
uv venv --python 3.11 .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

[Environment]::SetEnvironmentVariable("IBKR_PAPER_ACCOUNT", "DUxxxxxxx", "User")
[Environment]::SetEnvironmentVariable("ALPHAFLOW_TELEGRAM_BOT_TOKEN", "...", "User")
[Environment]::SetEnvironmentVariable("ALPHAFLOW_TELEGRAM_CHAT_ID", "...", "User")
```

Open a new terminal so it receives the user environment variables, then run:

```powershell
.venv\Scripts\alphaflow.exe options doctor --profile paper_qqq_cc
.venv\Scripts\alphaflow.exe options status --profile paper_qqq_cc --json
```

Do not place IBKR credentials, 2FA secrets, Telegram tokens, or account IDs in
Git-tracked files.

## 3. Five-session shadow gate

Keep `shadow_mode: true` and `trading_enabled: false` in
`config/paper_qqq_cc.yaml`. Start the daemon and collect five distinct valid
NYSE sessions:

```powershell
.venv\Scripts\alphaflow.exe options run --profile paper_qqq_cc --daemon
```

After `status` reports five shadow sessions and all doctor checks pass, change
only these two values:

```yaml
shadow_mode: false
trading_enabled: true
```

The runtime still refuses any account other than the exact `DU...` account in
`IBKR_PAPER_ACCOUNT`.

## 4. Operations

```powershell
# Broker/local reconciliation
.venv\Scripts\alphaflow.exe options reconcile --profile paper_qqq_cc

# Block new entries; risk-reducing exits continue
.venv\Scripts\alphaflow.exe options halt --profile paper_qqq_cc --reason "manual maintenance"

# Resume only after a clean broker reconciliation
.venv\Scripts\alphaflow.exe options resume --profile paper_qqq_cc --confirm-account DUxxxxxxx

# Install daemon and independent five-minute watchdog tasks
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
```

The daemon writes transactional state to `state/alphaflow.db`, its manual
circuit breaker to `state/HALT`, and the audit journal to
`output/unattended_paper.jsonl`. These runtime files must remain untracked.

## 5. Acceptance gate

Remain in the IBKR paper account for at least 60 NYSE trading sessions and
complete at least three entry/exit cycles. Required results are zero live-account
orders, naked calls, duplicate orders, or unexplained position mismatches; at
least 99% of expected monitoring cycles; reconnection without duplicate orders;
critical Telegram alerts within five minutes; and HALT enforcement within one
monitoring cycle.
