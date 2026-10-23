# Dot-source this file before running experiments from PowerShell.
$gpuRepoRoot = Split-Path $PSScriptRoot -Parent
$gpuCudaRoot = Join-Path $gpuRepoRoot '.local-home\cuda\v12.8'
if (-not (Test-Path (Join-Path $gpuCudaRoot 'bin\nvcc.exe'))) {
    throw "CUDA compiler is missing: $gpuCudaRoot"
}
$env:CUDA_PATH = $gpuCudaRoot
$env:CUDA_PATH_V12_8 = $gpuCudaRoot
$env:VIRTUAL_ENV = Join-Path $gpuRepoRoot '.venv'
$gpuPathEntries = @((Join-Path $env:VIRTUAL_ENV 'Scripts'), (Join-Path $gpuCudaRoot 'bin'))
$gpuExistingPath = @($env:Path -split ';' | Where-Object { $_ -and $_ -notin $gpuPathEntries })
$env:Path = ($gpuPathEntries + $gpuExistingPath) -join ';'

