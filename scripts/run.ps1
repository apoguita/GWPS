<#
.SYNOPSIS
    Run the PreSearing server stack locally.

.DESCRIPTION
    The server resolves "db/database.db" and "Gw.dat" as paths RELATIVE TO THE
    WORKING DIRECTORY (see code/OpenTyria/GameSrv.c:98 and :103), so it must be
    launched from the repository root. This script does that for you.

    It can also start the fake web gate (tools/webgate.py) that the client talks
    to during login.

.PARAMETER Config
    Build configuration to run. Default: RelWithDebInfo.

.PARAMETER WithWebGate
    Also start tools/webgate.py in a separate process.

.PARAMETER NoPreflight
    Skip the checks for Gw.dat / database.db.

.EXAMPLE
    ./scripts/run.ps1 -WithWebGate
#>
[CmdletBinding()]
param(
    [string] $Config = 'RelWithDebInfo',
    [string] $BuildDir = 'build',
    [switch] $WithWebGate,
    [switch] $NoPreflight
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (-not $NoPreflight) {
        if (-not (Test-Path 'Gw.dat')) {
            Write-Host 'WARNING: Gw.dat is missing from the repo root.' -ForegroundColor Yellow
            Write-Host '         Map and asset loading will fail. See README.md "Prerequisites".' -ForegroundColor DarkGray
        }
        if (-not (Test-Path 'db/database.db')) {
            Write-Host 'WARNING: db/database.db is missing.' -ForegroundColor Yellow
            Write-Host '         Run ./scripts/seed-db.ps1 first.' -ForegroundColor DarkGray
        }
    }

    $exe = Get-ChildItem -Path $BuildDir -Recurse -Filter 'presearing_server.exe' -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if (-not $exe) {
        throw "presearing_server.exe not found under '$BuildDir'. Run ./scripts/build.ps1 first."
    }

    $gate = $null
    if ($WithWebGate) {
        $py = (Get-Command python -ErrorAction SilentlyContinue)
        if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue) }
        if (-not $py) { throw 'Python is required for -WithWebGate.' }
        Write-Host 'Starting tools/webgate.py ...' -ForegroundColor Cyan
        $gate = Start-Process -FilePath $py.Source -ArgumentList 'tools/webgate.py' -WorkingDirectory $root -PassThru
        Write-Host "  webgate pid $($gate.Id)" -ForegroundColor DarkGray
    }

    Write-Host "Starting server: $($exe.FullName)" -ForegroundColor Green
    Write-Host '  listening: 6112 (portal), 6113 (game), 1337 (internal ctrl)' -ForegroundColor DarkGray
    Write-Host '  press Ctrl+C to stop' -ForegroundColor DarkGray
    & $exe.FullName
    $code = $LASTEXITCODE

    if ($gate -and -not $gate.HasExited) {
        Write-Host 'Stopping webgate ...' -ForegroundColor DarkGray
        Stop-Process -Id $gate.Id -Force -ErrorAction SilentlyContinue
    }

    exit $code
}
finally {
    Pop-Location
}
