<#
.SYNOPSIS
    Configure and build the PreSearing server.

.DESCRIPTION
    Thin wrapper around CMake so that a fresh checkout needs no manual setup.
    On Windows it uses the Visual Studio generator (found automatically); on
    other platforms it uses the default generator.

.PARAMETER Config
    CMake build configuration. Default: RelWithDebInfo.

.PARAMETER Target
    CMake target to build. Default: presearing_server.

.PARAMETER Clean
    Delete the build directory first.

.PARAMETER Tests
    Also build the presearing_tests target.

.EXAMPLE
    ./scripts/build.ps1

.EXAMPLE
    ./scripts/build.ps1 -Clean -Config Release
#>
[CmdletBinding()]
param(
    [string] $Config = 'RelWithDebInfo',
    [string] $Target = 'presearing_server',
    [string] $BuildDir = 'build',
    [switch] $Clean,
    [switch] $Tests
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if ($Clean -and (Test-Path $BuildDir)) {
        Write-Host "Removing $BuildDir ..." -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $BuildDir
    }

    if (-not (Test-Path $BuildDir)) {
        $cmakeArgs = @('-S', '.', '-B', $BuildDir)
        if ($env:OS -eq 'Windows_NT') {
            $cmakeArgs += @('-G', 'Visual Studio 17 2022', '-A', 'x64')
        }
        Write-Host "Configuring: cmake $($cmakeArgs -join ' ')" -ForegroundColor Cyan
        & cmake @cmakeArgs
        if ($LASTEXITCODE -ne 0) { throw "cmake configure failed ($LASTEXITCODE)" }
    }

    Write-Host "Building target '$Target' ($Config) ..." -ForegroundColor Cyan
    & cmake --build $BuildDir --config $Config --target $Target
    if ($LASTEXITCODE -ne 0) { throw "cmake build failed ($LASTEXITCODE)" }

    if ($Tests) {
        Write-Host "Building target 'presearing_tests' ($Config) ..." -ForegroundColor Cyan
        & cmake --build $BuildDir --config $Config --target presearing_tests
        if ($LASTEXITCODE -ne 0) { throw "cmake build (tests) failed ($LASTEXITCODE)" }
    }

    $exe = Get-ChildItem -Path $BuildDir -Recurse -Filter 'presearing_server.exe' -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($exe) {
        Write-Host "OK -> $($exe.FullName)" -ForegroundColor Green
    } else {
        Write-Host "Build finished, but presearing_server.exe was not found." -ForegroundColor Yellow
    }
}
finally {
    Pop-Location
}
