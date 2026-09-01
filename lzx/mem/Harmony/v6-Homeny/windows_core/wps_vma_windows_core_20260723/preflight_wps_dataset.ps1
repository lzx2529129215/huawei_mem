$ErrorActionPreference = 'Stop'

Write-Host '[preflight] Python'
python --version

$hdcPath = ''
if ($env:HDC) {
    $configuredHdc = [Environment]::ExpandEnvironmentVariables($env:HDC)
    if (Test-Path -LiteralPath $configuredHdc -PathType Leaf) {
        $hdcPath = $configuredHdc
    } elseif (Test-Path -LiteralPath $configuredHdc -PathType Container) {
        $windowsHdc = Join-Path -Path $configuredHdc -ChildPath 'hdc.exe'
        if (Test-Path -LiteralPath $windowsHdc -PathType Leaf) {
            $hdcPath = $windowsHdc
        }
    }
}
if (-not $hdcPath) {
    $hdcCommand = Get-Command hdc -ErrorAction SilentlyContinue
    if ($hdcCommand) {
        $hdcPath = $hdcCommand.Source
    }
}
if (-not $hdcPath) {
    throw 'hdc.exe not found. Add its directory to PATH or set HDC to the hdc.exe path or its containing directory.'
}

Write-Host ('[preflight] HDC: ' + $hdcPath)
& $hdcPath list targets
if ($LASTEXITCODE -ne 0) {
    throw 'hdc list targets failed.'
}

$collectorPath = Join-Path -Path $PSScriptRoot -ChildPath 'mem_analyze-v6-ohos'
if (-not (Test-Path -LiteralPath $collectorPath)) {
    throw 'mem_analyze-v6-ohos is missing. Copy the complete package again.'
}

Write-Host '[preflight] core files: OK'
Write-Host '[preflight] If no device serial is shown, check USB, unlock state, and USB debugging authorization.'
