param(
    [string]$RepoRoot = "",
    [int]$WebUiPort = 4716,
    [int]$BackendPort = 6174
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
$RepoRoot = (Resolve-Path $RepoRoot).Path.TrimEnd("\\")
$runtimeDir = Join-Path $RepoRoot ".imaging-scientist-runtime"

$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$stopper = Join-Path $PSScriptRoot "stop-webui.py"
if (-not (Test-Path $pythonExe) -or -not (Test-Path $stopper)) {
    throw "The Imaging Scientist Python runtime or stop helper is missing."
}

& $pythonExe $stopper $RepoRoot
$stopExitCode = $LASTEXITCODE

foreach ($name in @("workspace-supervisor.json", "workspace-switch.json", "langgraph_dev.pid", "langgraph_dev.workspace.json")) {
    Remove-Item -LiteralPath (Join-Path $runtimeDir $name) -Force -ErrorAction SilentlyContinue
}

if ($stopExitCode -ne 0) {
    throw "One or more Imaging Scientist processes could not be stopped."
}
