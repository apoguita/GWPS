<#
.SYNOPSIS
    Prepare this machine to run Phase 0 of the GWPS test plan.

.DESCRIPTION
    Does every mechanical prerequisite in docs/04-scope.md and changes nothing
    outside this repo except staging two files in the Guild Wars client folder.
    Safe to re-run: each step is skipped when it is already done.

    What it does:
      1. builds gwps_server and portal.dll
      2. seeds db/database.db if missing
      3. copies Gw.dat into the repo root (the server opens "Gw.dat" relative to
         its working directory -- GameSrv.c:103)
      4. patches the client to Gw.custom.exe with the DH keys from keys.txt
      5. stages portal.dll next to Gw.custom.exe

    It does NOT start the server, the web gate, or the client. See the printed
    "Next" block, or docs/04-scope.md.

.PARAMETER ClientDir
    Folder holding Gw.exe and Gw.dat.

.PARAMETER DatSource
    Gw.dat to copy into the repo root.

.PARAMETER SkipDatCopy
    Do not copy Gw.dat (use when it is already in the repo root).

.PARAMETER SkipPatch
    Do not patch the client or stage portal.dll.

.EXAMPLE
    ./scripts/phase0-prepare.ps1
#>
[CmdletBinding()]
param(
    [string] $ClientDir = 'F:\GW\GW1',
    [string] $DatSource = 'F:\GW\GW1\Gw.dat',
    [string] $Config = 'RelWithDebInfo',
    [switch] $SkipDatCopy,
    [switch] $SkipPatch
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

function Step($msg) { Write-Host "`n=== $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  ok   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  warn $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  FAIL $msg" -ForegroundColor Red }

try {
    # ---- 1. build -------------------------------------------------------
    Step '1/5 Building'
    $cmake = Get-Command cmake -ErrorAction SilentlyContinue
    if (-not $cmake) { throw 'cmake not found on PATH' }
    if (-not (Test-Path 'build')) {
        & cmake -S . -B build -G 'Visual Studio 17 2022' -A x64 | Out-Null
    }
    & cmake --build build --config $Config --target gwps_server portal 2>&1 |
        Select-Object -Last 3 | ForEach-Object { "       $_" }
    if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }
    $exe = Get-ChildItem build -Recurse -Filter 'gwps_server.exe' | Select-Object -First 1
    $dll = Get-ChildItem build -Recurse -Filter 'portal.dll' | Select-Object -First 1
    if (-not $exe) { throw 'gwps_server.exe not produced' }
    if (-not $dll) { throw 'portal.dll not produced' }
    Ok "server  $($exe.FullName)"
    Ok "portal  $($dll.FullName)"

    # ---- 2. database ----------------------------------------------------
    Step '2/5 Database'
    if (Test-Path 'db/database.db') {
        Ok 'db/database.db already exists (left untouched)'
    } else {
        & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed-db.ps1 -Force
        if ($LASTEXITCODE -ne 0) { throw 'seeding failed' }
    }

    # ---- 3. Gw.dat ------------------------------------------------------
    Step '3/5 Gw.dat'
    if ($SkipDatCopy) {
        Warn 'skipped (--SkipDatCopy)'
    } elseif (Test-Path 'Gw.dat') {
        $size = (Get-Item 'Gw.dat').Length
        Ok ("Gw.dat already in repo root ({0:N0} MB)" -f ($size / 1MB))
    } elseif (-not (Test-Path $DatSource)) {
        Fail "not found: $DatSource"
        Warn 'the server cannot load any map without it'
    } else {
        $src = Get-Item $DatSource
        Write-Host ("  copying {0:N0} MB from {1}" -f ($src.Length / 1MB), $src.FullName)
        Write-Host '  (this is the one slow step; ~1-3 minutes)'
        Copy-Item -Path $src.FullName -Destination 'Gw.dat'
        $copied = (Get-Item 'Gw.dat').Length
        if ($copied -ne $src.Length) { throw 'copy size mismatch' }
        Ok ("copied ({0:N0} MB)" -f ($copied / 1MB))
    }

    # ---- 4. patch client ------------------------------------------------
    Step '4/5 Patch client'
    if ($SkipPatch) {
        Warn 'skipped (--SkipPatch)'
    } else {
        $gwExe = Join-Path $ClientDir 'Gw.exe'
        $custom = Join-Path $ClientDir 'Gw.custom.exe'
        if (-not (Test-Path $gwExe)) { throw "not found: $gwExe" }
        if (-not (Test-Path 'keys.txt')) { throw 'keys.txt missing from repo root' }
        if (Test-Path $custom) {
            Ok 'Gw.custom.exe already exists (re-patching to be safe)'
        }
        $py = (Get-Command python -ErrorAction SilentlyContinue)
        if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue) }
        if (-not $py) { throw 'python not found; patch-gw.py needs it' }
        Write-Host "  patching $gwExe"
        & $py.Source tools\patch-gw.py $gwExe keys.txt --output $custom 2>&1 |
            ForEach-Object { "       $_" }
        if ($LASTEXITCODE -ne 0) { throw "patching failed ($LASTEXITCODE)" }
        if (-not (Test-Path $custom)) { throw 'Gw.custom.exe was not produced' }
        Ok "patched -> $custom"
    }

    # ---- 5. portal.dll --------------------------------------------------
    Step '5/5 Stage portal.dll'
    if ($SkipPatch) {
        Warn 'skipped (--SkipPatch)'
    } else {
        $target = Join-Path $ClientDir 'portal.dll'
        if (Test-Path $target) {
            Remove-Item -Force $target
        }
        Copy-Item -Path $dll.FullName -Destination $target
        Ok "portal.dll -> $target"
    }

    # ---- next steps -----------------------------------------------------
    Write-Host "`n=== Next" -ForegroundColor Cyan
    Write-Host '  Terminal 1:  ./scripts/run.ps1 -WithWebGate'
    Write-Host '  Terminal 2:  (from the client folder)'
    Write-Host "                 .\Gw.custom.exe -authsrv 127.0.0.1 -portal 127.0.0.1"
    Write-Host '  Log in with: user1@example.com'
    Write-Host ''
    Write-Host '  Start the server FIRST: it opens Gw.dat when the first map'
    Write-Host '  server spawns, and the client grabs the file it ships with.'
    Write-Host ''
    Write-Host '  Expected end state: you log in, pick/create a character, and'
    Write-Host '  land in Kamadan. See docs/04-scope.md for the pass criteria.'
}
finally {
    Pop-Location
}
