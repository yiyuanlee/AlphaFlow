# AlphaFlow 期权定时任务（建议一天 2 次，无需 TWS 常驻）
# 任务计划程序示例：09:40 ET、14:00 ET 各运行一次 --live
Set-Location $PSScriptRoot\..
& python scripts/options_daily_scan.py
& python scripts/live/ibkr_options.py --live
