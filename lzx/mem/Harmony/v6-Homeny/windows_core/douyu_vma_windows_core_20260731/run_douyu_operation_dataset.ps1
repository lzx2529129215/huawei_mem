param(
    [string]$Target = "",
    [int]$Trials = 1,
    [string]$Out = "",
    [switch]$NoBuild,
    [switch]$KeepRaw
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCommand = Get-Command python -ErrorAction Stop
$runArgs = @(
    (Join-Path $scriptRoot "run_douyu_operation_dataset.py"),
    "-Trials", "$Trials"
)
if (-not [string]::IsNullOrWhiteSpace($Target)) {
    $runArgs += @("-Target", $Target)
}
if (-not [string]::IsNullOrWhiteSpace($Out)) {
    $runArgs += @("-Out", $Out)
}
if ($NoBuild) {
    $runArgs += "-NoBuild"
}
if ($KeepRaw) {
    $runArgs += "--keep-raw"
}

& $pythonCommand.Source @runArgs
if ($LASTEXITCODE -ne 0) {
    throw "斗鱼数据集脚本失败，退出码: $LASTEXITCODE"
}
