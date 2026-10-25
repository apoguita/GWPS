<#
.SYNOPSIS
    Publish this repo to a new, empty GitHub repository as `origin`.

.DESCRIPTION
    PreSearing's history is an independent import of the OpenTyria tree, so it
    shares no ancestor with OpenTyria. That is fine for a new repo, but it means
    two things must be true or the push is refused:

      1. The GitHub repo must be EMPTY. If it already has a commit (an initial
         README, a licence, a .gitignore ticked at creation time), then its
         branch already exists with unrelated history and git rejects the push as
         non-fast-forward -- exactly the error this repo already hit once.

      2. We push our own branch, never an existing one.

    This script checks (1) before it tries, so the failure is explained rather
    than mysterious.

    `upstream` is left alone and stays fetch-only; it is the OpenTyria reference,
    not a publish target.

.PARAMETER Url
    The new repo's clone URL. Defaults to https://github.com/apoguita/PreSearing.git

.EXAMPLE
    ./scripts/publish.ps1

.EXAMPLE
    ./scripts/publish.ps1 -Url https://github.com/apoguita/PreSearing.git -Branch master
#>
[CmdletBinding()]
param(
    [string] $Url = 'https://github.com/apoguita/PreSearing.git',
    [string] $Remote = 'origin',
    [string] $Branch = 'master'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

function Ok($m)   { Write-Host "  ok   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  warn $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  FAIL $m" -ForegroundColor Red }
function Step($m) { Write-Host "`n=== $m" -ForegroundColor Cyan }

try {
    Write-Host "target: $Url"

    # ---- 1. confirm the remote repo exists and is empty ------------------
    Step '1/3 Checking the remote'
    $refs = git ls-remote --heads $Url 2>&1
    if ($LASTEXITCODE -ne 0) {
        Fail "could not read $Url"
        Write-Host '  Does the repository exist yet? Create it first:'
        Write-Host '    https://github.com/new  ->  Private, and do NOT tick any "initialize" box'
        return 1
    }

    $lines = @($refs | Where-Object { $_ -match '\S' })
    if ($lines.Count -gt 0) {
        Fail 'the remote is NOT empty:'
        $lines | ForEach-Object { Write-Host "         $_" }
        Write-Host ''
        Write-Host '  Pushing master here would be rejected as non-fast-forward, because this'
        Write-Host '  repo has no shared ancestor with whatever is already there.'
        Write-Host '  Fix it by making the remote empty again:'
        Write-Host '    - delete the repo and recreate it WITHOUT initialising it, or'
        Write-Host '    - delete every branch in it (GitHub: Settings -> Branches).'
        return 1
    }
    Ok 'remote exists and has no branches'

    # ---- 2. point origin at it -----------------------------------------
    Step "2/3 Configuring remote '$Remote'"
    $existing = git remote
    if ($existing -contains $Remote) {
        git remote set-url $Remote $Url
        Ok "$Remote updated"
    } else {
        git remote add $Remote $Url
        Ok "$Remote added"
    }

    # ---- 3. push -------------------------------------------------------
    Step "3/3 Pushing $Branch"
    Write-Host '  (first push of ~64 MB; credential manager may prompt to sign in)'
    git push -u $Remote $Branch
    if ($LASTEXITCODE -ne 0) {
        Fail 'push failed -- read the message above'
        return 1
    }
    Ok 'pushed'

    Write-Host "`n=== Result"
    git remote -v
    Write-Host ''
    git branch -vv
    Write-Host ''
    Write-Host 'upstream should still be fetch-only. If it is missing its URL:'
    Write-Host '  git remote set-url --push upstream "DISABLED-fetch-only-remote"'
    return 0
}
finally {
    Pop-Location
}
