[CmdletBinding()]
param(
    [string]$PythonExecutable = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "LogosGo Windows backend must be built natively on Windows."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "LogosGo V1 targets Windows 11 x64."
}

$ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDirectory "..\..")).Path
$WorkDirectory = Join-Path $ScriptDirectory "build"
$DistributionDirectory = Join-Path $ScriptDirectory "dist"
$SpecFile = Join-Path $ScriptDirectory "backend.spec"
$OutputExecutable = Join-Path $DistributionDirectory "logosgo_backend\logosgo_backend.exe"

& $PythonExecutable -c "import PyInstaller" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Install packaging/windows/requirements-build.txt into the Windows build environment first."
}

foreach ($Path in @($WorkDirectory, $DistributionDirectory)) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

Push-Location $ProjectRoot
try {
    & $PythonExecutable -m PyInstaller `
        --noconfirm `
        --clean `
        --workpath $WorkDirectory `
        --distpath $DistributionDirectory `
        $SpecFile
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $OutputExecutable -PathType Leaf)) {
    throw "Backend build did not produce $OutputExecutable"
}

Write-Host "Standalone Windows backend: $OutputExecutable"
