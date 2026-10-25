# Turn the GWPS hostname redirection on or off.
#
# WHY THIS EXISTS
# The client does not use the hostname strings we can patch in the exe: with all six literals
# redirected it still opened sockets to real ArenaNet servers, so it resolves or caches the
# names itself. Pointing the names at loopback is what makes our server the one answering the
# client's file/version check.
#
# WHY IT IS A SWITCH
# The hosts file is machine-wide. While the block below is present, ANY client on this machine
# that resolves these names is redirected to 127.0.0.1 -- including a retail Gw.exe, which will
# then fail to connect exactly the way ours did before the file check was answered. It is a
# test-machine setting, so it has to be easy to turn off.
#
#   .\tools\hosts-gwps.ps1 -Enable     add the block (needs an elevated shell)
#   .\tools\hosts-gwps.ps1 -Disable    remove it
#   .\tools\hosts-gwps.ps1 -Status     show whether it is on
#
# Reversible by design: the original file is copied to hosts.gwps-backup once, and removing
# the block leaves every other hosts entry untouched.

[CmdletBinding()]
param(
    [switch] $Enable,
    [switch] $Disable,
    [switch] $Status,
    [string] $HostsPath = (Join-Path $env:WINDIR 'System32\drivers\etc\hosts')
)

$ErrorActionPreference = 'Stop'
$beginMarker = '# --- GWPS private server ---'
$endMarker = '# --- end GWPS ---'

# An elevated window's output is not returned to the caller, so every run records what it did.
# That matters: a refresh that removed the old block and then failed to write the new one left
# the machine with no redirection at all, and nothing said so.
$log = Join-Path (Split-Path -Parent $PSScriptRoot) 'build\hosts-gwps.log'
function Note($m) {
    "$(Get-Date -Format HH:mm:ss.fff) $m" | Out-File -FilePath $log -Append -Encoding utf8
}

$lines = @(
    '127.0.0.1 Auth1.ArenaNetworks.com',
    # The client uses more than one file server: a DNS capture (tools/capture-dns.ps1) caught
    # it looking up File2.ArenaNetworks.com while File1 was already redirected, and File2 was
    # the socket still reaching a real server. Covering a small range beats chasing them one
    # per login -- a name that does not exist simply never gets queried.
    '127.0.0.1 File1.ArenaNetworks.com',
    '127.0.0.1 File2.ArenaNetworks.com',
    '127.0.0.1 File3.ArenaNetworks.com',
    '127.0.0.1 File4.ArenaNetworks.com',
    '127.0.0.1 File5.ArenaNetworks.com',
    '127.0.0.1 File6.ArenaNetworks.com',
    '127.0.0.1 Diag.ArenaNetworks.com',
    '127.0.0.1 icmp.arenanetworks.com',
    '127.0.0.1 account.arena.net'
)

$content = Get-Content $HostsPath -Raw
$enabled = $content -match [regex]::Escape($beginMarker)

if ($Status -or (-not $Enable -and -not $Disable)) {
    if ($enabled) { 'enabled: those hostnames resolve to 127.0.0.1 (retail clients are redirected too)' }
    else { 'disabled: hostnames resolve normally' }
    return
}

if ($Disable) {
    if (-not $enabled) { 'already disabled'; return }
    # Drop the block, keeping everything else byte for byte.
    $kept = New-Object System.Collections.Generic.List[string]
    $skipping = $false
    foreach ($line in ($content -split "`r?`n")) {
        if ($line.Trim() -eq $beginMarker) { $skipping = $true; continue }
        if ($line.Trim() -eq $endMarker) { $skipping = $false; continue }
        if (-not $skipping) { $kept.Add($line) }
    }
    Set-Content -Path $HostsPath -Value ($kept -join "`r`n") -Encoding ascii
    'disabled'
    return
}

if ($Enable) {
    try {
        $backup = "$HostsPath.gwps-backup"
        if (-not (Test-Path $backup)) { Copy-Item $HostsPath $backup -Force }

        # One write, not remove-then-append. The earlier two-step version removed the old block
        # and then failed to write the new one, leaving the machine with no redirection at all
        # and nothing in the output to say so.
        $kept = New-Object System.Collections.Generic.List[string]
        $skipping = $false
        foreach ($line in ($content -split "`r?`n")) {
            if ($line.Trim() -eq $beginMarker) { $skipping = $true; continue }
            if ($line.Trim() -eq $endMarker) { $skipping = $false; continue }
            if (-not $skipping) { $kept.Add($line) }
        }
        while ($kept.Count -gt 0 -and $kept[$kept.Count - 1].Trim() -eq '') {
            $kept.RemoveAt($kept.Count - 1)
        }

        $new = (@($kept) + @('', $beginMarker) + $lines + @($endMarker)) -join "`r`n"
        Set-Content -Path $HostsPath -Value $new -Encoding ascii

        # Read it back: the only trustworthy confirmation is the file itself.
        $check = Get-Content $HostsPath -Raw
        $ok = $check -match [regex]::Escape($beginMarker) -and $check -match [regex]::Escape('File2.ArenaNetworks.com')
        Note "enable: $($lines.Count) entries, read-back ok=$ok"
        if ($ok) { 'enabled' } else { 'FAILED: block not present after write' }
    } catch {
        Note "enable failed: $($_.Exception.Message)"
        throw
    }
    return
}
