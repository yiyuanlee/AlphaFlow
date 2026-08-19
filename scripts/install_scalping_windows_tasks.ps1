param(
    [string]$TaskPrefix = "AlphaFlow SPY Scalper"
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$daemonScript = (Resolve-Path (Join-Path $PSScriptRoot "run_paper_spy_orb.ps1")).Path
$watchdogScript = (Resolve-Path (Join-Path $PSScriptRoot "watchdog_paper_spy_orb.ps1")).Path
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".venv\Scripts\python.exe"))) {
    throw "Create .venv and install AlphaFlow before registering tasks."
}

$daemonAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$daemonScript`""
$daemonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$daemonSettings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable
Register-ScheduledTask `
    -TaskName "$TaskPrefix Daemon" `
    -Action $daemonAction `
    -Trigger $daemonTrigger `
    -Settings $daemonSettings `
    -Description "Independent AlphaFlow SPY ORB shadow/paper daemon on IB Gateway port 4004" `
    -Force

$watchdogAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdogScript`""
$watchdogTrigger = New-ScheduledTaskTrigger -Daily -At "00:00"
$watchdogTrigger.Repetition.Interval = "PT5M"
$watchdogTrigger.Repetition.Duration = "P1D"
$watchdogSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask `
    -TaskName "$TaskPrefix Watchdog" `
    -Action $watchdogAction `
    -Trigger $watchdogTrigger `
    -Settings $watchdogSettings `
    -Description "Checks the independent SPY scalper heartbeat every five minutes" `
    -Force

Write-Output "Registered '$TaskPrefix Daemon' and '$TaskPrefix Watchdog' for $userId."
