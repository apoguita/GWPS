# Turn the GWPS "closed" network mode on or off.
#
# WHAT THIS IS FOR
# The Guild Wars client holds up to three connections to ArenaNet's file servers while playing on
# GWPS, and it builds and resolves those names itself -- some of the lookups ignore the hosts
# file (after flushing the DNS cache, entries for file2/file6 reappeared although both were in
# hosts). Answering the lookup is therefore the only reliable way to keep it on this machine.
# Full explanation: docs/09-client-connections.md.
#
# THE DEFAULT IS OPEN. Nothing here runs unless you ask for it: an open connection is what a
# normal install uses, and it is what lets a retail client work on the same machine.
#
#   .\tools\dns-gwps.ps1 -Enable     start the responder, point the adapter at it (elevated)
#   .\tools\dns-gwps.ps1 -Disable    restore the adapter's DNS and stop the responder
#   .\tools\dns-gwps.ps1 -Status     report whether it is running and what DNS the adapter uses
#
# WHAT IT CHANGES ON THE MACHINE
#   - the active adapter's DNS servers become 127.0.0.1 while enabled (restored on -Disable)
#   - a gwps_dns.exe process runs on 127.0.0.1:53, answering 127.0.0.1 for anything under
#     arenanetworks.com / ncplatform.net and forwarding every other query to the resolver the
#     adapter had before
# Because it is machine-wide, a retail client is also redirected while this is enabled. Disable
# before playing retail.

[CmdletBinding()]
param(
    [switch] $Enable,
    [switch] $Disable,
    [switch] $Status
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root 'build\RelWithDebInfo\gwps_dns.exe'
$stateFile = Join-Path $root 'build\dns-gwps-state.json'
$logFile = Join-Path $root 'build\dns-gwps.log'
$processName = 'gwps_dns'

function Note($m) {
    "$(Get-Date -Format HH:mm:ss.fff) $m" | Out-File -FilePath $logFile -Append -Encoding utf8
}

function Get-ActiveAdapter {
    try {
        Get-NetAdapter -Physical -ErrorAction Stop |
            Where-Object { $_.Status -eq 'Up' } |
            Sort-Object InterfaceMetric |
            Select-Object -First 1
    } catch {
        # Reading adapter state requires an elevated shell; -Status still reports the responder
        # and says so rather than failing outright.
        return $null
    }
}

function Get-RunningResponder {
    Get-Process -Name $processName -ErrorAction SilentlyContinue | Select-Object -First 1
}

if ($Status -or (-not $Enable -and -not $Disable)) {
    $proc = Get-RunningResponder
    $adapter = Get-ActiveAdapter

    $dns = 'n/a'
    if ($adapter) {
        $dns = (Get-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses -join ', '
    }

    $mode = 'open (default)'
    if ($proc -and $dns -match '127\.0\.0\.1') {
        $mode = 'closed (responder running, adapter -> 127.0.0.1)'
    } elseif ($proc) {
        $mode = 'responder running but adapter not pointed at it'
    }

    $adapterText = 'unavailable (adapter state needs an elevated shell)'
    if ($adapter) { $adapterText = "$($adapter.Name) (ifIndex $($adapter.ifIndex))" }

    $procText = 'not running'
    if ($proc) { $procText = "PID $($proc.Id)" }

    $savedText = 'none'
    if (Test-Path $stateFile) { $savedText = (Get-Content $stateFile -Raw).Trim() }

    "mode       : $mode"
    "adapter    : $adapterText"
    "adapter DNS: $dns"
    "responder  : $procText"
    "saved      : $savedText"
    return
}

if ($Enable) {
    $adapter = Get-ActiveAdapter
    if (-not $adapter) {
        throw 'adapter settings need an elevated shell: run this from an Administrator PowerShell'
    }
    if (-not (Test-Path $exe)) { throw "gwps_dns.exe not built: run cmake --build build --config RelWithDebInfo --target gwps_dns" }

    $current = (Get-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses
    if ($current -contains '127.0.0.1' -and $current.Count -eq 1) {
        'already enabled'
        return
    }

    # Remember what to restore. Written before anything changes, so a failure leaves a record.
    $upstream = $current | Where-Object { $_ -and $_ -ne '127.0.0.1' } | Select-Object -First 1
    @{
        ifIndex      = $adapter.ifIndex
        adapterName  = $adapter.Name
        serverAddresses = @($current)
        upstream     = $upstream
    } | ConvertTo-Json | Set-Content -Path $stateFile -Encoding utf8

    if (-not (Get-RunningResponder)) {
        $args = @()
        if ($upstream) { $args += @('--upstream', $upstream) }
        Start-Process -FilePath $exe -ArgumentList $args -WindowStyle Hidden
        Start-Sleep -Milliseconds 400
        Note "started responder (upstream=$upstream)"
    }

    Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses '127.0.0.1'
    Clear-DnsClientCache
    Note "adapter $($adapter.Name) DNS -> 127.0.0.1 (was: $($current -join ', '))"
    'closed mode enabled'
    return
}

if ($Disable) {
    $proc = Get-RunningResponder
    if ($proc) {
        Stop-Process -Id $proc.Id -Force
        Note "stopped responder PID $($proc.Id)"
    }

    if (Test-Path $stateFile) {
        $state = Get-Content $stateFile -Raw | ConvertFrom-Json
        $restore = @($state.serverAddresses | Where-Object { $_ })
        if ($restore.Count -gt 0) {
            Set-DnsClientServerAddress -InterfaceIndex $state.ifIndex -ServerAddresses $restore
        } else {
            Set-DnsClientServerAddress -InterfaceIndex $state.ifIndex -ResetServerAddresses
        }
        Clear-DnsClientCache
        Note "adapter $($state.adapterName) DNS restored to: $($restore -join ', ')"
        Remove-Item $stateFile -Force
    }

    'open mode restored'
    return
}
