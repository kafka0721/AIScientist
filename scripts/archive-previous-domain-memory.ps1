$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path 'E:\AIScientist').Path.TrimEnd('\')
$memoryRoot = Join-Path $repo '.local-home\.witaiscientist\memories'
$source = Join-Path $memoryRoot 'observations\domain\its'
$archiveBase = Join-Path $repo '.local-home\memory-archives'
$listing = Invoke-RestMethod 'http://127.0.0.1:4716/api/memory' -TimeoutSec 15
if ([IO.Path]::GetFullPath($listing.dir).TrimEnd('\') -ne $memoryRoot) {
    throw 'The live platform uses a different memory directory; aborting.'
}
if (-not (Test-Path -LiteralPath $source)) { throw 'ITS directory no longer exists; inspect previous archive before rerunning.' }
$resolvedSource = (Resolve-Path -LiteralPath $source).Path
if ($resolvedSource -ne $source -or -not $resolvedSource.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Source is outside the verified project directory.'
}
$sourceItems = @(Get-Item -LiteralPath $source) + @(Get-ChildItem -LiteralPath $source -Recurse -Force)
if ($sourceItems | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
    throw 'Unexpected link in the memory subtree; aborting.'
}
$files = @($sourceItems | Where-Object { -not $_.PSIsContainer })
if ($files.Count -ne 77 -or @($files | Where-Object { $_.Extension -ne '.md' }).Count -gt 0) {
    throw 'Memory inventory changed; inspect before archiving.'
}
$inventory = @($files | ForEach-Object {
    [pscustomobject]@{
        relativePath = [IO.Path]::GetRelativePath($source, $_.FullName)
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        bytes = $_.Length
    }
})
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archiveRoot = [IO.Path]::GetFullPath((Join-Path $archiveBase ('its-' + $stamp)))
if (-not $archiveRoot.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase) -or $archiveRoot.StartsWith($memoryRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Archive destination must stay in the project and outside active memory.'
}
New-Item -ItemType Directory -Path $archiveRoot | Out-Null
$archiveSource = Join-Path $archiveRoot 'its'
$inventory | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $archiveRoot 'inventory.json') -Encoding utf8
Move-Item -LiteralPath $resolvedSource -Destination $archiveSource
foreach ($file in $inventory) {
    if ((Get-FileHash -LiteralPath (Join-Path $archiveSource $file.relativePath) -Algorithm SHA256).Hash -ne $file.sha256) {
        throw 'Archived file hash mismatch.'
    }
}
$after = Invoke-RestMethod 'http://127.0.0.1:4716/api/memory' -TimeoutSec 15
$remaining = @($after.entries | Where-Object { $_.path -like 'observations/domain/*' })
if ($remaining.Count -ne 0 -or (Test-Path -LiteralPath $source)) {
    throw 'Domain memory is not empty after the move; inspect active writers.'
}
$report = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    activeMemoryRoot = $memoryRoot
    originalDomainDirectory = $source
    archive = $archiveSource
    archivedCount = $inventory.Count
    roles = @{direction_positive=20; direction_negative=7; strategy=50}
    archivedHashesVerified = $true
    liveDomainMemoryCount = $remaining.Count
    retainedFiles = @($after.entries | ForEach-Object { $_.path })
    domainConfiguration = 'its (unchanged; image classification requires generic before import)'
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $archiveRoot 'cleanup-report.json') -Encoding utf8
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $repo 'artifacts\domain-memory-cleanup.json') -Encoding utf8
$date = Get-Date -Format 'yyyy-MM-dd'
$log = @"
# 旧领域记忆清理

时间：$($report.timestamp)

平台实际记忆根目录：$memoryRoot
清理前交通领域目录：$source

已将旧交通领域蒸馏记忆移出活动库：正向 20 条、负向 7 条、执行策略 50 条，共 77 条。
归档位置：$archiveSource
归档逐文件 SHA256 校验通过；平台实时记忆接口核对剩余领域条目为 0。
保留 4 个档案模板以及 E:\data\development、E:\data\memory 中的 GPU 环境日志。

本次为清空活动记忆库并保留可恢复归档，没有删除历史会话或论文原始产物。
旧会话上下文可能仍含历史内容，新领域任务应从新会话开始。
当前 domain_ema_domain 仍为 its；图像分类论文导入前应切换为 generic，并使用 task_type=image_classification。
归档不在活动 memories 目录下，不会被领域记忆检索扫描。
"@
$log | Set-Content -LiteralPath (Join-Path $archiveRoot 'README.md') -Encoding utf8
$log | Set-Content -LiteralPath "E:\data\development\${date}_domain_memory_cleanup.md" -Encoding utf8
$log | Set-Content -LiteralPath "E:\data\memory\${date}_domain_memory_reset.md" -Encoding utf8
$report | ConvertTo-Json -Depth 5
