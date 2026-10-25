# Capture what the client says to the real ArenaNet servers on 6112.
#
# The goal is to learn which protocol those three outbound sockets speak, because a file
# service we implement has to multiplex with our own auth listener on the same port.
#
# Runs elevated (pktmon needs admin). Waits for the client to open a non-loopback connection
# on 6112 so the capture only covers the interesting traffic, then converts to pcapng for
# offline parsing.

$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\Apo\Documents\GitHub\PreSearing'
$etl  = Join-Path $repo 'build\gw6112.etl'
$pcap = Join-Path $repo 'build\gw6112.pcapng'
$log  = Join-Path $repo 'build\capture-filesrv.log'

function L($m) { "$(Get-Date -Format HH:mm:ss.fff) $m" | Out-File -FilePath $log -Append -Encoding utf8 }

Remove-Item $etl, $pcap, $log -ErrorAction SilentlyContinue
L 'start'

& pktmon stop   2>&1 | Out-Null
& pktmon filter remove 2>&1 | Out-Null
(& pktmon filter add gw6112 -p 6112 2>&1) | ForEach-Object { L "filter: $_" }
(& pktmon start --capture --pkt-size 512 --file-name $etl 2>&1) | ForEach-Object { L "start: $_" }
L 'waiting for a non-loopback 6112 connection (up to 200s)'

$deadline = (Get-Date).AddSeconds(200)
$hit = $null
while ((Get-Date) -lt $deadline) {
    $p = Get-Process Gw.custom -ErrorAction SilentlyContinue
    if ($p) {
        foreach ($r in (netstat -ano | Select-String "\s$($p.Id)$")) {
            if ($r.Line -match ':6112' -and $r.Line -notmatch '127\.0\.0\.1:6112') {
                $hit = $r.Line.Trim()
                break
            }
        }
    }
    if ($hit) { break }
    Start-Sleep -Milliseconds 250
}

if ($hit) {
    L "connection seen: $hit"
    L 'capturing 12s more'
    Start-Sleep -Seconds 12
} else {
    L 'nothing seen in the window'
}

(& pktmon stop 2>&1) | ForEach-Object { L "stop: $_" }
& pktmon filter remove 2>&1 | Out-Null
(& pktmon etl2pcap $etl --out $pcap 2>&1) | ForEach-Object { L "convert: $_" }
if (Test-Path $pcap) { L ('pcap bytes: ' + (Get-Item $pcap).Length) }
L 'done'
