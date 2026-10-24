<#
.SYNOPSIS
    Seed db/database.db from db/seed.sql using the Python sqlite3 module.

.DESCRIPTION
    Upstream's README asks you to compile the SQLite shell with clang just to run
    `sqlite.exe database.db < seed.sql`. We do not need a C compiler for that:
    Python ships sqlite3, and this machine has Python. This script therefore
    needs no toolchain at all.

    The seed script DROPs and recreates every table, so this is destructive for
    the target database. Pass -Force to skip the confirmation prompt.

.PARAMETER Database
    Path to the database file. Default: db/database.db

.PARAMETER Seed
    Path to the seed SQL file. Default: db/seed.sql

.EXAMPLE
    python scripts/seed-db.py -Force
#>
[CmdletBinding()]
param(
    [string] $Database = 'db/database.db',
    [string] $Seed = 'db/seed.sql',
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dbPath = if ([System.IO.Path]::IsPathRooted($Database)) { $Database } else { Join-Path $root $Database }
$seedPath = if ([System.IO.Path]::IsPathRooted($Seed)) { $Seed } else { Join-Path $root $Seed }

if (-not (Test-Path $seedPath)) { throw "Seed file not found: $seedPath" }

if ((Test-Path $dbPath) -and -not $Force) {
    $answer = Read-Host "This will DESTROY data in '$dbPath'. Continue? [y/N]"
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host 'Aborted.' -ForegroundColor Yellow
        return
    }
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { throw 'Python is required to seed the database. https://python.org' }

$pyScript = @'
import sqlite3, sys, os
db_path, seed_path = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
with open(seed_path, 'r', encoding='utf-8') as fp:
    script = fp.read()
con = sqlite3.connect(db_path)
try:
    con.executescript(script)
    con.commit()
finally:
    con.close()
print(f'OK: seeded {db_path} from {seed_path}')
'@

$tmp = [System.IO.Path]::GetTempFileName() + '.py'
Set-Content -Path $tmp -Value $pyScript -Encoding UTF8
try {
    & $py.Source $tmp $dbPath $seedPath
    if ($LASTEXITCODE -ne 0) { throw "Seeding failed ($LASTEXITCODE)" }
}
finally {
    Remove-Item -Force $tmp -ErrorAction SilentlyContinue
}
