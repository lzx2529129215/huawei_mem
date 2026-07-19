param(
    [Parameter(Position = 0)]
    [string]$Target,

    [string]$Out = "",
    [string]$DeviceDir = "/data/local/tmp/mem_analyze_v6",
    [string]$DeviceOut = "/storage/media/100/local/files/Docs/Desktop/output-lzx",
    [string]$OperationCommand = "",

    [switch]$WithVma,
    [switch]$NoBuild,
    [switch]$NoPush,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ScriptDir = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
    $PSScriptRoot
} else {
    Split-Path -Parent $PSCommandPath
}

function Show-Usage {
    $scriptName = Split-Path -Leaf $PSCommandPath
    @"
Usage:
  .\$scriptName -Target <pid|app_keyword> [-WithVma]
  .\$scriptName <pid|app_keyword> [-Out .\hdc_out] [-DeviceOut /storage/media/100/local/files/Docs/Desktop/output-lzx]

Options:
  -Target <value>            PID or app/package keyword. Digits are treated as PID.
  -Out <path>                Local output directory. Default: lzx-Test1\v6-Homeny\hdc_out
  -DeviceDir <path>          Device binary/work directory. Default: /data/local/tmp/mem_analyze_v6
  -DeviceOut <path>          Device report output directory. Default: /storage/media/100/local/files/Docs/Desktop/output-lzx
  -OperationCommand <cmd>    Local command to run after clear_refs and before smaps sampling.
                             If omitted, the script waits for Enter.
  -WithVma                   Include VMA-level Referenced table.
  -NoBuild                   Skip cross compilation and reuse local mem_analyze-v6-ohos.
  -NoPush                    Skip sending the binary to device.
  -Help                      Show this help.

Examples:
  .\$scriptName -Target 12345 -WithVma
  .\$scriptName -Target com.example.app -OperationCommand 'hdc shell "aa start -a EntryAbility -b com.example.app"'
  .\$scriptName com.example.app -NoBuild -NoPush
"@
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Get-DefaultSdkPath {
    $candidate = "D:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\native"
    if (Test-Path -LiteralPath $candidate) {
        return $candidate
    }
    return ""
}

if ($Help) {
    Show-Usage
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Target)) {
    Show-Usage
    throw "Missing -Target <pid|app_keyword>."
}

if ([string]::IsNullOrWhiteSpace($Out)) {
    $Out = Join-Path $ScriptDir "hdc_out"
}

$Source = Join-Path $ScriptDir "mem_analyze-v6.c"
$LocalBin = Join-Path $ScriptDir "mem_analyze-v6-ohos"
$DeviceBin = "$DeviceDir/mem_analyze-v6"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$DeviceReport = "$DeviceOut/referenced_$Timestamp.md"
$DeviceJsonl = "$DeviceOut/referenced_$Timestamp.jsonl"

if (-not $NoBuild) {
    $sdk = $env:OHOS_SDK
    if ([string]::IsNullOrWhiteSpace($sdk)) {
        $sdk = Get-DefaultSdkPath
    }
    if ([string]::IsNullOrWhiteSpace($sdk) -or -not (Test-Path -LiteralPath $sdk)) {
        throw "OHOS_SDK is not set and the default SDK path was not found."
    }

    $clang = Join-Path $sdk "llvm\bin\clang.exe"
    $sysroot = Join-Path $sdk "sysroot"
    if (-not (Test-Path -LiteralPath $clang)) {
        throw "OpenHarmony clang not found: $clang"
    }
    if (-not (Test-Path -LiteralPath $sysroot)) {
        throw "OpenHarmony sysroot not found: $sysroot"
    }

    Write-Host "==> Building HarmonyOS collector"
    Invoke-External $clang "-O2" "-std=c11" "-Wall" "-Wextra" "-target" "aarch64-linux-ohos" "--sysroot=$sysroot" "-o" $LocalBin $Source
}

if (-not (Test-Path -LiteralPath $LocalBin)) {
    throw "Local collector binary not found: $LocalBin. Build first or remove -NoBuild."
}

if (-not $NoPush) {
    Write-Host "==> Pushing collector to device"
    Invoke-External hdc "shell" "mkdir -p '$DeviceDir' '$DeviceOut'"
    Invoke-External hdc "file" "send" $LocalBin $DeviceBin
    Invoke-External hdc "shell" "chmod 755 '$DeviceBin'"
}

$TargetArgs = @()
if ($Target -match '^[0-9]+$') {
    $TargetArgs += $Target
} else {
    $TargetArgs += "--app"
    $TargetArgs += $Target
}

Write-Host "==> Device and /proc permission check"
Invoke-External hdc "list" "targets"
Invoke-External hdc "shell" "id; ls -l /proc/self/smaps /proc/self/clear_refs"

Write-Host "==> Clearing referenced bits"
$clearCmd = @("'$DeviceBin'", "--clear-refs") + $TargetArgs
Invoke-External hdc "shell" ($clearCmd -join " ")

if ([string]::IsNullOrWhiteSpace($OperationCommand)) {
    Write-Host ""
    Write-Host "Referenced bits are cleared. Perform the target operation on the HarmonyOS device now."
    Read-Host "Press Enter to sample smaps"
} else {
    Write-Host "==> Running operation command"
    Invoke-Expression $OperationCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Operation command failed with exit code ${LASTEXITCODE}: $OperationCommand"
    }
}

Write-Host "==> Sampling smaps"
$sampleCmd = @("'$DeviceBin'") + $TargetArgs + @("-o", "'$DeviceReport'", "--jsonl-output", "'$DeviceJsonl'")
if ($WithVma) {
    $sampleCmd += "--with-vma"
}
Invoke-External hdc "shell" ($sampleCmd -join " ")

Write-Host "==> Pulling reports"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Invoke-External hdc "file" "recv" $DeviceOut $Out

Write-Host "==> Done"
Write-Host "Local output: $Out"
Write-Host "Device output: $DeviceOut"
