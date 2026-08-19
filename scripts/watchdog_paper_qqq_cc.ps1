param(
    [string]$Profile = "paper_qqq_cc"
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Virtual environment not found: $venvPython"
}

Set-Location -LiteralPath $projectRoot
& $venvPython -m alphaflow.cli options watchdog --profile $Profile
exit $LASTEXITCODE
