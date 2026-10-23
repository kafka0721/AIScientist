param(
    [string]$RepoRoot = "",
    [string]$Workdir = "",
    [int]$WebUiPort = 4716,
    [int]$BackendPort = 6174
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
$RepoRoot = (Resolve-Path $RepoRoot).Path.TrimEnd("\\")
if (-not $Workdir) {
    # First-run state belongs with the installation, not an assumed drive.
    # Users can still explicitly choose another workspace with -Workdir or
    # switch projects from the WebUI after the service is running.
    $Workdir = Join-Path $RepoRoot "data"
}
if (-not (Test-Path $Workdir)) {
    New-Item -ItemType Directory -Path $Workdir -Force | Out-Null
}
$Workdir = (Resolve-Path $Workdir).Path.TrimEnd("\\")

$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$frontendEntry = Join-Path $RepoRoot "webui\dist\server.js"
$logDir = Join-Path $RepoRoot ".local-home\logs"
$runtimeDir = Join-Path $RepoRoot ".imaging-scientist-runtime"

# Windows PowerShell 5.1 does not auto-load this assembly when resolving the
# HttpClient types used by the health check below.
Add-Type -AssemblyName System.Net.Http

function Test-HttpHealthy([string]$Url, [int]$TimeoutSec = 3) {
    try {
        # PowerShell's Invoke-WebRequest can route even 127.0.0.1 through a
        # machine proxy. The backend itself may then be healthy while this
        # launcher incorrectly keeps waiting. Force direct local connections.
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $handler.UseProxy = $false
        $client = [System.Net.Http.HttpClient]::new($handler)
        $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        $client.Dispose()
        $handler.Dispose()
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Test-WorkspaceSupervisor {
    $marker = Join-Path $runtimeDir "workspace-supervisor.json"
    if (-not (Test-Path $marker)) {
        return $false
    }
    try {
        $state = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        $supervisorPid = [int]$state.pid
        return $supervisorPid -gt 0 -and $null -ne (Get-Process -Id $supervisorPid -ErrorAction SilentlyContinue)
    } catch {
        return $false
    }
}

function Wait-WorkspaceSupervisor {
    param([System.Diagnostics.Process]$Process, [int]$TimeoutSec = 15)

    $marker = Join-Path $runtimeDir "workspace-supervisor.json"
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        # The launcher removes stale markers before it starts this backend.
        # A newly-created marker is therefore sufficient here, even when a
        # restricted Windows session cannot inspect the Python process ID.
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

if (-not (Test-Path $pythonExe)) {
    throw "Backend Python was not found: $pythonExe"
}
if (-not (Test-Path $frontendEntry)) {
    throw "WebUI production bundle is missing. Run npm run build in $RepoRoot\webui."
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    throw "Node.js 20 or newer was not found on PATH. Install Node.js, then run this script again."
}
$nodeExe = $nodeCommand.Source
$nodeMajor = [int]((& $nodeExe -p "process.versions.node.split('.')[0]").Trim())
if ($nodeMajor -lt 20) {
    throw "Node.js 20 or newer is required; found $(& $nodeExe --version) at $nodeExe"
}
$backendHealthy = Test-HttpHealthy "http://127.0.0.1:$BackendPort/ok"
$webUiHealthy = Test-HttpHealthy "http://127.0.0.1:$WebUiPort/"
if ($backendHealthy -and $webUiHealthy) {
    if (Test-WorkspaceSupervisor) {
        Write-Host "Imaging Scientist is already running." -ForegroundColor Green
        Write-Host "WebUI:   http://127.0.0.1:$WebUiPort"
        Write-Host "Backend: http://127.0.0.1:$BackendPort"
        exit 0
    }
    throw "A backend and WebUI are already using ports $BackendPort/$WebUiPort, but they were not started by this workspace-aware launcher. Run stop_webui.bat, then start-webui.bat."
}
foreach ($port in @($WebUiPort, $BackendPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the existing stack before starting a new one."
    }
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Write-Host "Preparing Imaging Scientist runtime..." -ForegroundColor Cyan

# Keep application state under the repository and use the existing project config.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if ([string]::IsNullOrWhiteSpace($env:PROCESSOR_ARCHITECTURE)) {
    # Some VM / remote-shell launches omit this Windows variable. wasmtime
    # then sees an empty architecture and the backend cannot import its graph.
    $env:PROCESSOR_ARCHITECTURE = "AMD64"
}
$hostUserProfile = $env:USERPROFILE
if (-not $hostUserProfile) {
    $hostUserProfile = [Environment]::GetFolderPath("UserProfile")
}
if ($hostUserProfile) {
    $env:WITAISCIENTIST_HOST_USERPROFILE = $hostUserProfile
    $env:WITAISCIENTIST_EXTRA_SKILLS_DIR = Join-Path $hostUserProfile ".witaiscientist\skills"
}
$env:USERPROFILE = Join-Path $RepoRoot ".local-home"
$env:XDG_CONFIG_HOME = Join-Path $env:USERPROFILE ".config"
$env:WITAISCIENTIST_DATA_DIR = Join-Path $env:USERPROFILE ".witaiscientist"
$env:WITAISCIENTIST_CONFIG_PATH = Join-Path $RepoRoot "user-config\config.yaml"
$env:WITAISCIENTIST_RUNTIME_DIR = $runtimeDir
$env:WITAISCIENTIST_WORKSPACE_DIR = $Workdir
$env:WITAISCIENTIST_BUILTIN_SKILLS_DIR = Join-Path $RepoRoot "imaging_scientist\skills"
$env:WITAISCIENTIST_LANGGRAPH_DEV_PORT = "$BackendPort"
$env:PORT = "$WebUiPort"
$env:HOSTNAME = "127.0.0.1"
$env:NO_PROXY = "localhost,127.0.0.1"
$env:no_proxy = "localhost,127.0.0.1"

# Windows PowerShell can inherit both Path and PATH from terminal hosts that
# preserve case. Start-Process copies them into a case-insensitive dictionary
# and throws before it can launch Python or Node. Recreate one canonical entry.
$pathValue = $env:Path
if ([string]::IsNullOrWhiteSpace($pathValue)) {
    $pathValue = $env:PATH
}
Remove-Item Env:PATH -ErrorAction SilentlyContinue
$env:Path = $pathValue

# Let experiment subprocesses use the project's GPU-enabled Python and CUDA.
$gpuActivation = Join-Path $RepoRoot "scripts\activate-gpu.ps1"
if ((Test-Path $gpuActivation) -and (Test-Path (Join-Path $RepoRoot ".local-home\cuda\v12.8\bin\nvcc.exe"))) {
    . $gpuActivation
}

# Remove a marker from a prior dead launch before starting this backend.
Remove-Item -LiteralPath (Join-Path $runtimeDir "workspace-supervisor.json") -Force -ErrorAction SilentlyContinue

$legacySkillsDir = Join-Path $hostUserProfile ".witaiscientist\skills"
$localSkillsDir = Join-Path $env:WITAISCIENTIST_DATA_DIR "skills"
if ($hostUserProfile -and (Test-Path $legacySkillsDir)) {
    New-Item -ItemType Directory -Path $localSkillsDir -Force | Out-Null
    Get-ChildItem -LiteralPath $legacySkillsDir -Force | Copy-Item -Destination $localSkillsDir -Recurse -Force
}

$backendLog = Join-Path $logDir "backend.stdout.log"
$backendErrorLog = Join-Path $logDir "backend.stderr.log"
$frontendLog = Join-Path $logDir "webui.stdout.log"
$frontendErrorLog = Join-Path $logDir "webui.stderr.log"

function Start-HiddenProcess {
    param(
        [string]$FileName,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    # Start the actual executable, rather than a cmd.exe wrapper. Tracking the
    # wrapper made a healthy backend look exited after its parent console closed.
    $quote = {
        param([string]$value)
        '"' + $value.Replace('"', '""') + '"'
    }
    $argumentLine = ($Arguments | ForEach-Object { & $quote $_ }) -join " "
    $process = Start-Process `
        -FilePath $FileName `
        -ArgumentList $argumentLine `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath `
        -WindowStyle Hidden `
        -PassThru
    if (-not $process) {
        throw "Could not start $FileName"
    }
    return $process
}

function Stop-ProcessTree {
    param([System.Diagnostics.Process]$Process)
    if (-not $Process -or $Process.HasExited) {
        return
    }
    & taskkill /PID $Process.Id /T /F *> $null
}

function Show-BackendStartupDiagnostics {
    param([System.Diagnostics.Process]$Process)

    $runtimeLog = Join-Path $env:WITAISCIENTIST_RUNTIME_DIR "langgraph_dev.log"
    Write-Host "" 
    Write-Host "Backend startup diagnostics:" -ForegroundColor Yellow
    if ($Process -and $Process.HasExited) {
        Write-Host "  Launcher exit code: $($Process.ExitCode)"
    }

    foreach ($entry in @(
        @{ Label = "backend stderr"; Path = $backendErrorLog },
        @{ Label = "backend stdout"; Path = $backendLog },
        @{ Label = "langgraph dev"; Path = $runtimeLog }
    )) {
        $path = $entry.Path
        if ((Test-Path $path) -and (Get-Item $path).Length -gt 0) {
            Write-Host "--- $($entry.Label): $path ---" -ForegroundColor Yellow
            Get-Content -LiteralPath $path -Tail 80
        } else {
            Write-Host "--- $($entry.Label): no output ($path) ---" -ForegroundColor DarkYellow
        }
    }
}

# Run from the deployment root so a copied source checkout wins over any
# older package cached inside .venv. The workspace remains explicit via
# --workdir and is never inferred from the current directory.
Write-Host "Starting backend on http://127.0.0.1:$BackendPort..." -ForegroundColor Cyan
$backend = Start-HiddenProcess `
    -FileName $pythonExe `
    -Arguments @("-u", "-m", "imaging_scientist", "deploy", "--workdir", $Workdir, "--port", $BackendPort) `
    -WorkingDirectory $RepoRoot `
    -StdoutPath $backendLog `
    -StderrPath $backendErrorLog

$backendReady = $false
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    if (Test-HttpHealthy -Url "http://127.0.0.1:$BackendPort/ok" -TimeoutSec 2) {
        $backendReady = $true
        break
    }
    if ($backend.HasExited) {
        Show-BackendStartupDiagnostics -Process $backend
        throw "Backend exited during startup. Check the diagnostics above."
    }
    if ($attempt -gt 0 -and $attempt % 2 -eq 0) {
        Write-Host "  Backend is initializing ($($attempt * 2)s elapsed)..." -ForegroundColor DarkCyan
    }
    Start-Sleep -Seconds 2
}
if (-not $backendReady) {
    Stop-ProcessTree $backend
    throw "Backend did not become healthy within 180 seconds. Check $backendErrorLog"
}
if (-not (Wait-WorkspaceSupervisor -Process $backend)) {
    Show-BackendStartupDiagnostics -Process $backend
    Stop-ProcessTree $backend
    throw "Backend became healthy but did not enable workspace switching. Check $backendLog and $runtimeDir\langgraph_dev.log"
}

Write-Host "Starting WebUI on http://127.0.0.1:$WebUiPort..." -ForegroundColor Cyan
$frontend = Start-HiddenProcess `
    -FileName $nodeExe `
    -Arguments @($frontendEntry) `
    -WorkingDirectory (Join-Path $RepoRoot "webui") `
    -StdoutPath $frontendLog `
    -StderrPath $frontendErrorLog

$webUiReady = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Test-HttpHealthy -Url "http://127.0.0.1:$WebUiPort/" -TimeoutSec 2) {
        $webUiReady = $true
        break
    }
    if ($frontend.HasExited) {
        Stop-ProcessTree $backend
        throw "WebUI exited during startup. Check $frontendErrorLog"
    }
    if ($attempt -gt 0 -and $attempt % 3 -eq 0) {
        Write-Host "  WebUI is initializing ($attempt s elapsed)..." -ForegroundColor DarkCyan
    }
    Start-Sleep -Seconds 1
}
if (-not $webUiReady) {
    Stop-ProcessTree $frontend
    Stop-ProcessTree $backend
    throw "WebUI did not become healthy within 30 seconds. Check $frontendErrorLog"
}

Write-Host "Backend ready: http://127.0.0.1:$BackendPort" -ForegroundColor Green
Write-Host "WebUI ready:   http://127.0.0.1:$WebUiPort" -ForegroundColor Green
Write-Host "Logs:          $logDir"
