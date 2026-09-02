param(
    [ValidateSet("formal", "fast")]
    [string]$Mode = "formal",
    [switch]$FastKeepRaw,
    [string]$Out,
    [string]$Target = "",
    [int]$Trials = 6,
    [double]$ActionWindowS = 15,
    [double]$PostWindowS = 5,
    [int]$BaselineWindowCount = 2,
    [double]$BaselineWindowS = 5,
    [double]$LaunchWaitS = 10,
    [string]$DeviceDir = "/data/local/tmp/mem_analyze_v6",
    [string]$DeviceOut = "/data/local/tmp/mem_analyze_v6/wps_reports",
    [int]$EditorX = 1100,
    [int]$EditorY = 1020,
    [string]$TestSerial = "WPS-DATASET-0001",
    [switch]$NoBuild
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$arguments = @(
    (Join-Path $scriptDir "run_wps_operation_dataset.py"),
    "--mode", $Mode,
    "--trials", $Trials,
    "--action-window-s", $ActionWindowS,
    "--post-window-s", $PostWindowS,
    "--baseline-window-count", $BaselineWindowCount,
    "--baseline-window-s", $BaselineWindowS,
    "--launch-wait-s", $LaunchWaitS,
    "--device-dir", $DeviceDir,
    "--device-out", $DeviceOut,
    "--editor-x", $EditorX,
    "--editor-y", $EditorY,
    "--test-serial", $TestSerial
)
if ($Out) { $arguments += @("--out", $Out) }
if ($Target) { $arguments += @("--target", $Target) }
if ($NoBuild) { $arguments += "--no-build" }
if ($FastKeepRaw) { $arguments += "--fast-keep-raw" }

& python @arguments
exit $LASTEXITCODE
