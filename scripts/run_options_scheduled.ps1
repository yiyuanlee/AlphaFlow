# Deprecated V10 scheduled runner. It is intentionally dry-run only.
Set-Location $PSScriptRoot\..
& python scripts/options_daily_scan.py
& python scripts/live/ibkr_options.py --live --dry-run
