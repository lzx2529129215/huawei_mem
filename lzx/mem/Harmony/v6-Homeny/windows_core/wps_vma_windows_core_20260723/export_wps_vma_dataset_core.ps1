[CmdletBinding()]
param(
    [string]$Root = 'D:\git-code\huawei_mem\wps_vma_formal_20260723_25trials',
    [string]$OutputDir = '',
    [string]$ZipPath = '',
    [int]$ExpectedLabelCount = 18,
    [string]$Catalog = '',
    [switch]$AllowIncompleteTrials,
    [switch]$NoRawVector,
    [switch]$NoZip
)

$ErrorActionPreference = 'Stop'
$exporter = Join-Path $PSScriptRoot 'export_wps_vma_dataset_core.py'
if (-not (Test-Path -LiteralPath $exporter -PathType Leaf)) {
    throw "找不到 $exporter。请确保 .ps1 与 .py 文件位于同一目录。"
}

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
$pythonArgs = @()
if ($null -ne $pythonCommand) {
    $python = $pythonCommand.Source
    $pythonArgs += '-3'
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw '找不到 Python。请先安装 Python 3 并确认 py 或 python 已加入 PATH。'
    }
    $python = $pythonCommand.Source
}

$argsList = @($exporter, '--root', $Root, '--expected-label-count', $ExpectedLabelCount)
if ($OutputDir) { $argsList += @('--output-dir', $OutputDir) }
if ($ZipPath) { $argsList += @('--zip-path', $ZipPath) }
if ($Catalog) { $argsList += @('--catalog', $Catalog) }
if ($AllowIncompleteTrials) { $argsList += '--allow-incomplete-trials' }
if ($NoRawVector) { $argsList += '--no-raw-vector' }
if ($NoZip) { $argsList += '--no-zip' }

Write-Host "[wps-core-export] root: $Root"
Write-Host "[wps-core-export] filtering compact vector and label files; raw reports will not be copied"
& $python @pythonArgs @argsList
if ($LASTEXITCODE -ne 0) {
    throw "核心数据集导出失败，退出码：$LASTEXITCODE"
}
