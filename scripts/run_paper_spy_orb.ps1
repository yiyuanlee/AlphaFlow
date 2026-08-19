param(
    [string]$Profile = "paper_spy_orb"
)

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Virtual environment not found: $venvPython"
}

Set-Location -LiteralPath $projectRoot
& $venvPython -m alphaflow.cli scalp run --profile $Profile --daemon
exit $LASTEXITCODE
