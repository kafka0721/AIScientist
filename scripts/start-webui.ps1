param(
    [string]$RepoRoot = "",
    [string]$Workdir = "",
    [int]$WebUiPort = 4716,
    [int]$BackendPort = 6174,
    [int]$BackendWaitSec = 180,
    [switch]$LocalFrontend
)

$ErrorActionPreference = 'SilentlyContinue'

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}
if (-not $Workdir) {
    $Workdir = Join-Path $RepoRoot 'data'
}
$RepoRoot = (Resolve-Path $RepoRoot).Path.TrimEnd('\')
$null = New-Item -ItemType Directory -Path $Workdir -Force
$Workdir = (Resolve-Path $Workdir).Path.TrimEnd('\')

function Write-Info([string]$Message) { Write-Host $Message -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host $Message -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host $Message -ForegroundColor Yellow }
function Write-Err([string]$Message) { Write-Host $Message -ForegroundColor Red }

function Test-HttpHealthy {
    param([string]$Url, [int]$TimeoutSec = 5)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    }
    catch {
        return $false
    }
}

function Open-WebUi {
    param([string]$Url)
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Url
    $startInfo.UseShellExecute = $true
    [System.Diagnostics.Process]::Start($startInfo) | Out-Null
}

function Stop-PortTree {
    param([int]$Port, [string]$Label)
    $pids = @(
        Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            Where-Object { $_ -gt 0 }
    )
    foreach ($procId in $pids) {
        Write-Warn "  stopping $Label on port $Port (PID $procId)..."
        & taskkill /PID $procId /T /F *> $null
    }
}

function Stop-WitAISciStack {
    Write-Warn "Cleaning stale imaging_scientist processes..."
    Stop-PortTree -Port $WebUiPort -Label "WebUI"
    Stop-PortTree -Port $BackendPort -Label "backend"
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -match 'ImagingSci.*--ui webui' -or
                $_.CommandLine -match 'ImagingSci.*deploy' -or
                $_.CommandLine -match '@witaiscientist/webui' -or
                $_.CommandLine -match 'langgraph\.EXE dev'
            )
        } |
        ForEach-Object {
            Write-Warn "  stopping PID $($_.ProcessId)..."
            & taskkill /PID $_.ProcessId /T /F *> $null
        }
    Start-Sleep -Seconds 3
}

function Wait-BackendHealthy {
    param([int]$TimeoutSec, [System.Diagnostics.Process]$Process)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpHealthy -Url "http://127.0.0.1:$BackendPort/ok" -TimeoutSec 3) {
            return $true
        }
        if ($Process -and $Process.HasExited) {
            Write-Err "Backend exited before it became healthy (exit code $($Process.ExitCode))."
            return $false
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Test-WorkspaceSupervisor {
    $runtimeDir = $env:WITAISCIENTIST_RUNTIME_DIR
    if (-not $runtimeDir) {
        return $false
    }
    $marker = Join-Path $runtimeDir 'workspace-supervisor.json'
    if (-not (Test-Path $marker)) {
        return $false
    }
    try {
        $state = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        $supervisorPid = [int]$state.pid
        return $supervisorPid -gt 0 -and $null -ne (Get-Process -Id $supervisorPid -ErrorAction SilentlyContinue)
    }
    catch {
        return $false
    }
}

function Wait-WorkspaceSupervisor {
    param([System.Diagnostics.Process]$Process, [int]$TimeoutSec = 15)
    $marker = Join-Path $env:WITAISCIENTIST_RUNTIME_DIR 'workspace-supervisor.json'
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        # Stale markers are removed before this backend starts, so existence
        # confirms the newly started supervisor without requiring process
        # inspection permissions across Windows integrity boundaries.
        if (Test-Path $marker) {
            return $true
        }
        if ($Process -and $Process.HasExited) {
            return $false
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Test-PythonRuntime {
    param([string]$PythonExe)
    if (-not $PythonExe -or -not (Test-Path $PythonExe)) {
        return $false
    }
    & $PythonExe -c "import imaging_scientist, langgraph, pypdf" *> $null
    return ($LASTEXITCODE -eq 0)
}

$CmdExe = Join-Path $env:WINDIR 'System32\cmd.exe'
if (-not (Test-Path $CmdExe)) { $CmdExe = 'cmd.exe' }
$HostUserProfile = $env:USERPROFILE
if (-not $HostUserProfile -or -not (Test-Path $HostUserProfile)) {
    $HostUserProfile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
}

Set-Location $RepoRoot
# PYTHONUTF8 must be exactly 0 or 1. Do NOT set it via `cmd /c "set PYTHONUTF8=1 && ..."`
# from PowerShell — quote mangling can make the value invalid and Python aborts at startup.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PROCESSOR_ARCHITECTURE = 'AMD64'
$localHome = Join-Path $RepoRoot '.local-home'
$env:USERPROFILE = $localHome
$env:XDG_CONFIG_HOME = Join-Path $localHome '.config'
$env:WITAISCIENTIST_DATA_DIR = Join-Path $localHome '.witaiscientist'
$env:WITAISCIENTIST_CONFIG_PATH = Join-Path $RepoRoot 'user-config\config.yaml'
$env:WITAISCIENTIST_WORKSPACE_DIR = $Workdir
$env:WITAISCIENTIST_BUILTIN_SKILLS_DIR = Join-Path $RepoRoot 'imaging_scientist\skills'
$env:WITAISCIENTIST_RUNTIME_DIR = Join-Path $RepoRoot '.imaging-scientist-runtime'
$legacySkillsDir = Join-Path $HostUserProfile '.witaiscientist\skills'
$localSkillsDir = Join-Path $env:WITAISCIENTIST_DATA_DIR 'skills'
if (Test-Path $legacySkillsDir) {
    New-Item -ItemType Directory -Path $localSkillsDir -Force | Out-Null
    Get-ChildItem -LiteralPath $legacySkillsDir -Force | Copy-Item -Destination $localSkillsDir -Recurse -Force
}
$env:PATH = "E:\anaconda\Library\bin;$env:PATH"
$env:NO_PROXY = 'localhost,127.0.0.1'
$env:no_proxy = 'localhost,127.0.0.1'
Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:http_proxy -ErrorAction SilentlyContinue
Remove-Item Env:https_proxy -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "========================================" -ForegroundColor White
$launcherTitle = if ($LocalFrontend) { "imaging_scientist WebUI Dev Launcher" } else { "imaging_scientist WebUI Launcher" }
Write-Host "  $launcherTitle" -ForegroundColor White
Write-Host "========================================" -ForegroundColor White
Write-Host "Workspace: $Workdir"
Write-Host "WebUI:     http://localhost:$WebUiPort"
Write-Host "Backend:   http://127.0.0.1:$BackendPort"
Write-Host ""

$webUiHealthy = Test-HttpHealthy -Url "http://127.0.0.1:$WebUiPort/"
$backendHealthy = Test-HttpHealthy -Url "http://127.0.0.1:$BackendPort/ok"
Write-Info ("Status: WebUI={0}, Backend={1}" -f $webUiHealthy, $backendHealthy)

# Only reuse a healthy stack if it was already started with the requested workdir.
$runningWorkdirMatch = $false
if ($webUiHealthy -and $backendHealthy) {
    $runningWorkdirMatch = [bool](
        Get-CimInstance Win32_Process |
            Where-Object {
                $_.CommandLine -and (
                    $_.CommandLine -match ('ImagingSci.*deploy.*--workdir[^\S\r\n]+["'']?' + [regex]::Escape($Workdir))
                )
            }
    )
}

if (-not $LocalFrontend -and $webUiHealthy -and $backendHealthy -and $runningWorkdirMatch -and (Test-WorkspaceSupervisor)) {
    Write-Ok "Both services are healthy with workspace $Workdir."
    Open-WebUi "http://localhost:$WebUiPort"
    Write-Host ""
    Write-Host "Keep both the Backend and WebUI windows open."
    exit 0
}

if ($webUiHealthy -or $backendHealthy) {
    Write-Warn "Restarting stack so workspace becomes: $Workdir"
}

Stop-WitAISciStack
Remove-Item -LiteralPath (Join-Path $env:WITAISCIENTIST_RUNTIME_DIR 'workspace-supervisor.json') -Force -ErrorAction SilentlyContinue

Write-Info "Step 1/2: starting backend in a new window..."
# Inherit PYTHONUTF8=1 from this process; avoid inline `set PYTHONUTF8=...` in cmd.
# Always use set "VAR=value" — bare `set VAR=value &&` makes cmd keep the space before &&.
$backendPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-PythonRuntime -PythonExe $backendPython)) {
    Write-Err "No working imaging_scientist Python environment was found."
    Write-Err "Run: uv sync --frozen"
    exit 1
}
Write-Ok "Using backend Python: $backendPython"
$backendScripts = Split-Path $backendPython -Parent
$env:PATH = "$backendScripts;$env:PATH"
$pythonPathParts = @($RepoRoot)
if ($env:PYTHONPATH) {
    $pythonPathParts += $env:PYTHONPATH
}
$env:PYTHONPATH = $pythonPathParts -join [IO.Path]::PathSeparator

# Avoid Start-Process: it fails when Windows exposes both Path and PATH.
$backendInfo = New-Object System.Diagnostics.ProcessStartInfo
$backendInfo.FileName = $backendPython
$backendInfo.Arguments = "-m imaging_scientist deploy --workdir `"$Workdir`" --port $BackendPort"
$backendInfo.WorkingDirectory = $RepoRoot
$backendInfo.UseShellExecute = $false
$backendInfo.CreateNoWindow = $true
# ProcessStartInfo environment inheritance is unreliable on some Windows
# shells when the launcher itself was started in the background. Set the
# paths explicitly: the backend must use this deployment's runtime state,
# not a stale per-user state directory from a prior WebUI session.
$backendInfo.EnvironmentVariables['USERPROFILE'] = $env:USERPROFILE
$backendInfo.EnvironmentVariables['XDG_CONFIG_HOME'] = $env:XDG_CONFIG_HOME
$backendInfo.EnvironmentVariables['WITAISCIENTIST_DATA_DIR'] = $env:WITAISCIENTIST_DATA_DIR
$backendInfo.EnvironmentVariables['WITAISCIENTIST_CONFIG_PATH'] = $env:WITAISCIENTIST_CONFIG_PATH
$backendInfo.EnvironmentVariables['WITAISCIENTIST_WORKSPACE_DIR'] = $env:WITAISCIENTIST_WORKSPACE_DIR
$backendInfo.EnvironmentVariables['WITAISCIENTIST_RUNTIME_DIR'] = $env:WITAISCIENTIST_RUNTIME_DIR
$backendInfo.EnvironmentVariables['PYTHONPATH'] = $env:PYTHONPATH
$backendInfo.EnvironmentVariables['PYTHONUTF8'] = $env:PYTHONUTF8
$backendInfo.EnvironmentVariables['PYTHONIOENCODING'] = $env:PYTHONIOENCODING
$backendProcess = [System.Diagnostics.Process]::Start($backendInfo)

Write-Info "Waiting for backend /ok (up to $BackendWaitSec s)..."
if (-not (Wait-BackendHealthy -TimeoutSec $BackendWaitSec -Process $backendProcess)) {
    Write-Err "Backend did not become healthy."
    Write-Err "Check the 'ImagingSci Backend' window for errors."
    Write-Err "Log: $env:USERPROFILE\.config\witaiscientist\langgraph_dev.log"
    exit 1
}
Write-Ok "Backend is online."
if (-not (Wait-WorkspaceSupervisor -Process $backendProcess)) {
    Write-Err "Backend became healthy but did not enable workspace switching."
    Write-Err "Check: $env:WITAISCIENTIST_RUNTIME_DIR\langgraph_dev.log"
    Stop-WitAISciStack
    exit 1
}

Write-Info "Step 2/2: starting WebUI frontend in this window..."
$env:PORT = "$WebUiPort"
$env:WITAISCIENTIST_LANGGRAPH_DEV_PORT = "$BackendPort"
$env:npm_config_cache = Join-Path $env:TEMP 'ImagingSci-npm-cache'
# Trim: a trailing space in HOSTNAME causes getaddrinfo ENOTFOUND '127.0.0.1 '
$env:HOSTNAME = '127.0.0.1'.Trim()

if ($LocalFrontend) {
    $webUiDir = Join-Path $RepoRoot 'webui'
    $nextCli = Join-Path $webUiDir 'node_modules\next\dist\bin\next'
    if (-not (Test-Path (Join-Path $webUiDir 'package.json'))) {
        Write-Err "Local WebUI source is missing: $webUiDir"
        exit 1
    }
    if (-not (Test-Path $nextCli)) {
        Write-Err "Local WebUI dependencies are missing. Run:"
        Write-Err "  cd `"$webUiDir`""
        Write-Err "  npm ci"
        exit 1
    }

    $bundledNode = Join-Path $HostUserProfile '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
    $nodeExe = if (Test-Path $bundledNode) {
        $bundledNode
    } else {
        (Get-Command node -ErrorAction SilentlyContinue).Source
    }
    if (-not $nodeExe) {
        Write-Err "Node.js 20 or newer is required for local WebUI development."
        exit 1
    }
    $nodeMajor = [int]((& $nodeExe -p "process.versions.node.split('.')[0]").Trim())
    if ($nodeMajor -lt 20) {
        Write-Err "Node.js 20 or newer is required; found $(& $nodeExe --version) at $nodeExe"
        exit 1
    }

    Set-Location $webUiDir
    Write-Ok "Using local WebUI source: $webUiDir"
    $frontendInfo = New-Object System.Diagnostics.ProcessStartInfo
    $frontendInfo.FileName = $nodeExe
    $frontendInfo.Arguments = "`"$nextCli`" dev --turbopack --port $WebUiPort"
    $frontendInfo.WorkingDirectory = $webUiDir
    $frontendInfo.UseShellExecute = $false
    $frontendInfo.CreateNoWindow = $true
    $frontendProcess = [System.Diagnostics.Process]::Start($frontendInfo)

    Write-Info "Waiting for the local WebUI to become ready..."
    $frontendDeadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $frontendDeadline -and -not $frontendProcess.HasExited) {
        if (Test-HttpHealthy -Url "http://127.0.0.1:$WebUiPort/" -TimeoutSec 3) {
            Write-Ok "WebUI is online. Opening http://localhost:$WebUiPort"
            Open-WebUi "http://localhost:$WebUiPort"
            $frontendProcess.WaitForExit()
            exit $frontendProcess.ExitCode
        }
        Start-Sleep -Seconds 1
    }
    if ($frontendProcess.HasExited) {
        Write-Err "WebUI exited before it became ready (exit code $($frontendProcess.ExitCode))."
        exit $frontendProcess.ExitCode
    }
    Write-Err "WebUI did not become ready within 120 seconds."
    exit 1
}

Write-Host ""
Write-Ok "Keep BOTH windows open while using imaging_scientist."
Write-Host "If the page still shows Offline, open Settings (gear icon) and set:"
Write-Host "  Deployment URL = http://127.0.0.1:$BackendPort"
Write-Host ""

# Prefer a locally cached @witaiscientist/webui (npx can hang offline / behind proxy).
$webUiCaches = @(
    "$env:LOCALAPPDATA\Temp\cursor-sandbox-cache",
    (Join-Path $env:TEMP 'ImagingSci-npm-cache\_npx')
) | Where-Object { Test-Path $_ }
$localWebui = Get-ChildItem $webUiCaches -Recurse -Filter "witaiscientist-webui.mjs" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
$bundledNode = Join-Path $HostUserProfile '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$nodeExe = if (Test-Path $bundledNode) {
    $bundledNode
} else {
    (Get-Command node -ErrorAction SilentlyContinue).Source
}
if (-not $nodeExe) {
    Write-Err "Node.js 20 or newer is required to launch the WebUI."
    exit 1
}
if ($localWebui) {
    Write-Info "Using local WebUI: $localWebui"
    & $nodeExe $localWebui --port $WebUiPort
} else {
    $npxCommand = (Get-Command npx -ErrorAction SilentlyContinue).Source
    $npxCli = if ($npxCommand) {
        Join-Path (Split-Path $npxCommand -Parent) 'node_modules\npm\bin\npx-cli.js'
    }
    if ($npxCli -and (Test-Path $npxCli)) {
        & $nodeExe $npxCli --yes @witaiscientist/webui@latest --port $WebUiPort
    } else {
        & npx --yes @witaiscientist/webui@latest --port $WebUiPort
    }
}
exit $LASTEXITCODE
