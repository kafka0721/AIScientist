param(
    [int]$WebUiPort = 4716,
    [int]$BackendPort = 6174
)

$ErrorActionPreference = 'SilentlyContinue'

function Test-PortListening {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-HttpHealthy {
    param(
        [string]$Url,
        [int]$TimeoutSec = 5
    )
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    }
    catch {
        return $false
    }
}

function Stop-PortOwners {
    param(
        [int]$Port,
        [string]$Label
    )

    $pids = @(
        Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            Where-Object { $_ -gt 0 }
    )

    foreach ($procId in $pids) {
        Write-Host "  stopping $Label on port $Port (PID $procId)..." -ForegroundColor Yellow
        & taskkill /PID $procId /T /F *> $null
    }
}

function Stop-WitAISciProcesses {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -match 'ImagingSci.*--ui webui' -or
                $_.CommandLine -match '@witaiscientist/webui' -or
                $_.CommandLine -match 'langgraph\.EXE dev.*--port\s+' + $BackendPort
            )
        } |
        ForEach-Object {
            Write-Host "  stopping ImagingSci process (PID $($_.ProcessId))..." -ForegroundColor Yellow
            & taskkill /PID $_.ProcessId /T /F *> $null
        }
}

Write-Host ""
Write-Host "Checking WebUI stack..." -ForegroundColor Cyan

$webUiListening = Test-PortListening -Port $WebUiPort
$backendListening = Test-PortListening -Port $BackendPort
$webUiHealthy = Test-HttpHealthy -Url "http://127.0.0.1:$WebUiPort/"
$backendHealthy = Test-HttpHealthy -Url "http://127.0.0.1:$BackendPort/ok"

Write-Host ("  WebUI    port {0}: listen={1}, http={2}" -f $WebUiPort, $webUiListening, $webUiHealthy)
Write-Host ("  Backend  port {0}: listen={1}, http={2}" -f $BackendPort, $backendListening, $backendHealthy)

if ($webUiHealthy -and $backendHealthy) {
    Write-Host ""
    Write-Host "Both WebUI and backend are healthy." -ForegroundColor Green
    exit 0
}

if ($webUiListening -or $backendListening -or $webUiHealthy -or $backendHealthy) {
    Write-Host ""
    Write-Host "Partial session detected (frontend-only causes Offline / Failed to fetch)." -ForegroundColor Yellow
    Write-Host "Cleaning stale WebUI/backend processes..." -ForegroundColor Yellow
    Stop-PortOwners -Port $WebUiPort -Label "WebUI"
    Stop-PortOwners -Port $BackendPort -Label "backend"
    Stop-WitAISciProcesses
    Start-Sleep -Seconds 3
}

Write-Host ""
Write-Host "Starting fresh WebUI stack..." -ForegroundColor Cyan
exit 1
