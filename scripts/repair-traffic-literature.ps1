$ErrorActionPreference = 'Stop'
$taskRepo = 'E:\AIScientist'
$taskWorkspace = 'E:\data'
$taskOutput = Join-Path $taskWorkspace 'artifacts\traffic_survey_distillation'
$taskAudit = Join-Path $taskRepo 'artifacts\traffic_survey_distillation'
$taskRuntime = Join-Path $taskRepo '.imaging-scientist-runtime'
Set-Location $taskRepo
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:WITAISCIENTIST_CONFIG_PATH = Join-Path $taskRepo 'user-config\config.yaml'
New-Item -ItemType Directory -Path $taskAudit -Force | Out-Null

# Preserve the previous report before publishing the verified import result.
foreach ($taskName in @('ingestion_report.md', 'manifest.json')) {
    $taskBackup = Join-Path $taskAudit ('original-' + $taskName)
    if (-not (Test-Path -LiteralPath $taskBackup)) {
        Copy-Item -LiteralPath (Join-Path $taskOutput $taskName) -Destination $taskBackup
    }
}
& '.venv/Scripts/python.exe' scripts/import_literature_memory.py `
    artifacts/traffic_survey_distillation/memory_candidates.jsonl `
    --workspace $taskWorkspace `
    --memory-dir (Join-Path $taskRepo '.local-home\.witaiscientist\memories') `
    --apply --report (Join-Path $taskOutput 'ingestion_result.json')
if ($LASTEXITCODE -ne 0) { throw 'Import or verification failed; inspect ingestion_result.json.' }
$taskResult = Get-Content -LiteralPath (Join-Path $taskOutput 'ingestion_result.json') -Raw | ConvertFrom-Json
$taskWritten = @($taskResult.rows | Where-Object { $_.status -in @('created', 'existing') })
$taskDeferred = @($taskResult.rows | Where-Object { $_.status -eq 'deferred' })
if (@($taskWritten | Where-Object { -not $_.readback_verified -or -not $_.retrieval_verified }).Count) {
    throw 'Some imported records were not verified.'
}
$taskReport = @(
    '# 文献候选入库修复报告'
    ''
    ('更新时间：' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'))
    ''
    ('候选总数：' + $taskResult.candidate_count)
    ('已入库并通过回读、检索验证：' + $taskWritten.Count)
    ('保留待审：' + $taskDeferred.Count)
    '任务类型：predict=2，survey=4，evaluation=9（原报告误写为8）。'
    ''
    '全部入库项是 literature/source_unverified 文献先验，尚未逐条核实论文原文或完成本地复现。utility_score=0 是未评分的排序下限，不是实测分数。未生成实验 run_id、metrics 或伪造评审信号。'
    ''
    '原始 memory_candidates.jsonl 保留不变；ITS-SV-013 的实际入库分类纠正为 strategy。ITS-SV-001、011、012、015 留待审核。'
    ''
    '| 候选 ID | 实际分类 | 状态 | 记忆 ID | 回读 | 检索 |'
    '|---|---|---|---|---|---|'
)
foreach ($taskRow in $taskResult.rows) {
    $taskReport += '| ' + $taskRow.id + ' | ' + $taskRow.role + ' | ' + $taskRow.status + ' | ' + $taskRow.observation_id + ' | ' + $taskRow.readback_verified + ' | ' + $taskRow.retrieval_verified + ' |'
}
$taskReport += @('', '详细路径、分类理由和验证结果见同目录 ingestion_result.json。',
    '旧报告和旧 manifest 已备份至 E:\AIScientist\artifacts\traffic_survey_distillation。',
    '新增 import_domain_memory 工具支持先预检再导入，无需执行 shell 或额外实验。论文全文阅读状态沿用原任务记录，本次未重新核验全部111页。')
[IO.File]::WriteAllText((Join-Path $taskOutput 'ingestion_report.md'), ($taskReport -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
$taskManifest = Get-Content -LiteralPath (Join-Path $taskOutput 'manifest.json') -Raw | ConvertFrom-Json
$taskManifest.domain_memory_ingestion = [pscustomobject]@{
    status = 'partial_import_verified'
    reason = 'Eligible literature priors imported; secondary direction claims and research gap deferred.'
    candidates_generated = $taskResult.candidate_count
    candidates_ingested = $taskWritten.Count
    candidates_deferred = $taskDeferred.Count
    evidence_status = 'source_unverified'
    readback_verified = $true
    retrieval_verified = $true
    details = 'ingestion_result.json'
}
[IO.File]::WriteAllText((Join-Path $taskOutput 'manifest.json'), ($taskManifest | ConvertTo-Json -Depth 15) + "`n", [Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $taskOutput 'ingestion_result.json') -Destination (Join-Path $taskAudit 'ingestion_result.json') -Force
Copy-Item -LiteralPath (Join-Path $taskOutput 'ingestion_report.md') -Destination (Join-Path $taskAudit 'ingestion_report.md') -Force
Write-Output "Imported and verified $($taskWritten.Count) literature priors; $($taskDeferred.Count) deferred."

# Verify ownership before restarting this deployment's backend. The frontend
# remains connected to the same port; the active workspace is preserved.
$taskState = Get-Content -LiteralPath (Join-Path $taskRuntime 'langgraph_dev.workspace.json') -Raw | ConvertFrom-Json
if ($taskState.workspace -ne $taskWorkspace) { throw 'Active workspace changed; refusing to restart another workspace.' }
$taskSupervisor = Get-Content -LiteralPath (Join-Path $taskRuntime 'workspace-supervisor.json') -Raw | ConvertFrom-Json
$taskSupervisorProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($taskSupervisor.pid)"
$taskBackendProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($taskState.pid)"
if ($taskSupervisorProcess.Name -ne 'python.exe' -or $taskSupervisorProcess.CommandLine -notmatch 'imaging_scientist.*deploy') { throw 'Unexpected backend supervisor.' }
if ($taskBackendProcess.ParentProcessId -ne $taskSupervisor.pid -or $taskBackendProcess.CommandLine -notlike '*E:\AIScientist\imaging_scientist\langgraph_dev\langgraph.json*') { throw 'Unexpected backend ownership.' }
$taskLastQueue = Get-Content -LiteralPath (Join-Path $taskRuntime 'langgraph_dev.log') -Tail 100 | Select-String 'Queue stats' | Select-Object -Last 1
if (-not $taskLastQueue -or $taskLastQueue.Line -notmatch 'n_pending=0 n_running=0') { throw 'Backend may have active tasks; restart deferred.' }
& taskkill /PID $taskSupervisor.pid /T /F
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the verified backend process tree.' }

$env:WITAISCIENTIST_HOST_USERPROFILE = [Environment]::GetFolderPath('UserProfile')
$env:WITAISCIENTIST_EXTRA_SKILLS_DIR = Join-Path $env:WITAISCIENTIST_HOST_USERPROFILE '.witaiscientist\skills'
$env:USERPROFILE = Join-Path $taskRepo '.local-home'
$env:XDG_CONFIG_HOME = Join-Path $env:USERPROFILE '.config'
$env:WITAISCIENTIST_DATA_DIR = Join-Path $env:USERPROFILE '.witaiscientist'
$env:WITAISCIENTIST_RUNTIME_DIR = $taskRuntime
$env:WITAISCIENTIST_WORKSPACE_DIR = $taskWorkspace
$env:WITAISCIENTIST_BUILTIN_SKILLS_DIR = Join-Path $taskRepo 'imaging_scientist\skills'
$env:WITAISCIENTIST_LANGGRAPH_DEV_PORT = '6174'
$env:NO_PROXY = 'localhost,127.0.0.1'
$taskPathValue = $env:Path
Remove-Item Env:PATH -ErrorAction SilentlyContinue
$env:Path = $taskPathValue
if ([string]::IsNullOrWhiteSpace($env:PROCESSOR_ARCHITECTURE)) { $env:PROCESSOR_ARCHITECTURE = 'AMD64' }
$taskNew = Start-Process -FilePath (Join-Path $taskRepo '.venv\Scripts\python.exe') `
    -ArgumentList @('-u', '-m', 'imaging_scientist', 'deploy', '--workdir', $taskWorkspace, '--port', '6174') `
    -WorkingDirectory $taskRepo -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $taskRepo '.local-home\logs\backend.stdout.log') `
    -RedirectStandardError (Join-Path $taskRepo '.local-home\logs\backend.stderr.log')
Write-Output "Backend reload started: launcher PID $($taskNew.Id)."
