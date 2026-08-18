param(
    [string]$TaskPrefix = "AlphaFlow V11"
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$daemonScript = (Resolve-Path (Join-Path $PSScriptRoot "run_paper_qqq_cc.ps1")).Path
$watchdogScript = (Resolve-Path (Join-Path $PSScriptRoot "watchdog_paper_qqq_cc.ps1")).Path
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".venv\Scripts\python.exe"))) {
    throw "Create .venv and install AlphaFlow before registering tasks."
}

$daemonAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$daemonScript`""
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
    -Description "AlphaFlow V11 QQQ covered-call paper daemon" `
    -Force

$watchdogAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$watchdogScript`""
$watchdogTrigger = New-ScheduledTaskTrigger -Daily -At "00:00"
$watchdogTrigger.Repetition.Interval = "PT5M"
$watchdogTrigger.Repetition.Duration = "P1D"
$watchdogSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask `
    -TaskName "$TaskPrefix Watchdog" `
    -Action $watchdogAction `
    -Trigger $watchdogTrigger `
    -Settings $watchdogSettings `
    -Description "Checks AlphaFlow V11 heartbeat every five minutes" `
    -Force

Write-Output "Registered '$TaskPrefix Daemon' and '$TaskPrefix Watchdog' for $userId."
