param(
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[preflight] Python"
python --version

$hdcCommand = Get-Command hdc -ErrorAction Stop
Write-Host "[preflight] HDC: $($hdcCommand.Source)"
$targetText = (& $hdcCommand.Source list targets | Out-String).Trim()
if ([string]::IsNullOrWhiteSpace($targetText)) {
    throw "未检测到 hdc 设备。"
}
Write-Host $targetText

$targetLines = @($targetText -split '\r?\n' | Where-Object {
    -not [string]::IsNullOrWhiteSpace($_) -and $_.Trim() -notmatch "^\["
})
if ($targetLines.Count -lt 1) {
    throw "hdc list targets 没有可用设备。"
}
if ([string]::IsNullOrWhiteSpace($Target) -and $targetLines.Count -ne 1) {
    throw "检测到多个设备，请使用 -Target 指定 serial。"
}

$requiredFiles = @(
    "run_douyu_operation_dataset.py",
    "douyu_v6_session.py",
    "build_douyu_vma_dataset.py",
    "export_douyu_vma_dataset_core.py",
    "douyu_operation_catalog.json",
    "douyu_operation_catalog_all.json",
    "mem_analyze-v6-ohos"
)
foreach ($name in $requiredFiles) {
    $path = Join-Path $scriptRoot $name
    if (-not (Test-Path -LiteralPath $path)) {
        throw "缺少核心文件: $path"
    }
}

Write-Host "[preflight] Python syntax"
python -m py_compile (Join-Path $scriptRoot "run_douyu_operation_dataset.py") (Join-Path $scriptRoot "douyu_v6_session.py") (Join-Path $scriptRoot "build_douyu_vma_dataset.py") (Join-Path $scriptRoot "export_douyu_vma_dataset_core.py")

Write-Host "[preflight] core files: OK"
Write-Host "[preflight] If the target is unlocked and USB debugging is authorized, run the one-trial smoke next."
