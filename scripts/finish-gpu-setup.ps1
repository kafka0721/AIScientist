$ErrorActionPreference = 'Stop'
$gpuRepo = Split-Path $PSScriptRoot -Parent
Set-Location $gpuRepo
$gpuPython = Join-Path $gpuRepo '.venv\Scripts\python.exe'
$pipPython = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:TEMP = Join-Path $gpuRepo '.local-home\gpu-install-temp'
$env:TMP = $env:TEMP
$gpuCache = Join-Path $gpuRepo '.local-home\gpu-downloads'
$gpuPlan = Get-Content (Join-Path $gpuRepo 'artifacts\gpu-pytorch-install-plan.json') -Raw | ConvertFrom-Json
foreach ($gpuPackage in $gpuPlan.install) {
    $gpuWheelName = [Uri]::UnescapeDataString(($gpuPackage.download_info.url -split '/')[-1])
    $gpuCachedWheel = Join-Path $gpuCache $gpuWheelName
    if (Test-Path $gpuCachedWheel) { continue }
    $gpuDownloadedWheel = Get-ChildItem -LiteralPath $env:TEMP -Recurse -Filter $gpuWheelName | Select-Object -First 1
    if ($gpuDownloadedWheel -and (Get-FileHash -LiteralPath $gpuDownloadedWheel.FullName -Algorithm SHA256).Hash.ToLower() -eq $gpuPackage.download_info.archive_info.hashes.sha256) {
        Copy-Item -LiteralPath $gpuDownloadedWheel.FullName -Destination $gpuCachedWheel
        Write-Output "Reusing verified $gpuWheelName"
    }
}
$gpuWheels = @(
    (Join-Path $gpuCache 'torch-2.11.0+cu128-cp312-cp312-win_amd64.whl'),
    (Join-Path $gpuCache 'torchvision-0.26.0+cu128-cp312-cp312-win_amd64.whl'),
    (Join-Path $gpuCache 'torchaudio-2.11.0+cu128-cp312-cp312-win_amd64.whl')
)
& $pipPython -m pip --python $gpuPython install --no-cache-dir @gpuWheels --report artifacts/gpu-pytorch-installed.json
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed' }
& $pipPython -m pip --python $gpuPython install --no-cache-dir 'cupy-cuda12x==14.2.0' --report artifacts/gpu-cupy-installed.json
if ($LASTEXITCODE -ne 0) { throw 'CuPy installation failed' }
. (Join-Path $PSScriptRoot 'activate-gpu.ps1')
& $gpuPython (Join-Path $PSScriptRoot 'check-gpu-environment.py')
if ($LASTEXITCODE -ne 0) { throw 'GPU verification failed' }
& $pipPython -m pip --python $gpuPython check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency validation failed' }
[Environment]::SetEnvironmentVariable('CUDA_PATH', $env:CUDA_PATH, 'User')
[Environment]::SetEnvironmentVariable('CUDA_PATH_V12_8', $env:CUDA_PATH, 'User')
$gpuUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$gpuBin = Join-Path $env:CUDA_PATH 'bin'
if ($gpuBin -notin ($gpuUserPath -split ';')) {
    [Environment]::SetEnvironmentVariable('Path', ($gpuBin + ';' + $gpuUserPath), 'User')
}
Write-Output 'GPU installation and validation completed.'
