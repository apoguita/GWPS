# Capture the DNS lookups the client makes while it starts.
#
# The client still reaches a real File1 address after we redirected the hostname, and the
# address is not cached in Gw.dat (the byte matches there are chance coincidences in 3.6 GB).
# So it resolves a name we have not redirected. This records every DNS query so the name is
# known rather than guessed.
#
# Runs elevated (pktmon needs admin).

$ErrorActionPreference = 'Continue'
$repo = 'C:\Users\Apo\Documents\GitHub\PreSearing'
$etl  = Join-Path $repo 'build\dns.etl'
$pcap = Join-Path $repo 'build\dns.pcapng'
$log  = Join-Path $repo 'build\capture-dns.log'

function L($m) { "$(Get-Date -Format HH:mm:ss.fff) $m" | Out-File -FilePath $log -Append -Encoding utf8 }

Remove-Item $etl, $pcap, $log -ErrorAction SilentlyContinue
L 'start'

& pktmon stop 2>&1 | Out-Null
& pktmon filter remove 2>&1 | Out-Null
(& pktmon filter add dns -p 53 2>&1) | ForEach-Object { L "filter: $_" }
(& pktmon start --capture --pkt-size 512 --file-name $etl 2>&1) | Select-Object -First 3 | ForEach-Object { L "start: $_" }
L 'waiting for the client process (up to 200s)'

$deadline = (Get-Date).AddSeconds(200)
while ((Get-Date) -lt $deadline) {
    if (Get-Process Gw.custom -ErrorAction SilentlyContinue) { break }
    Start-Sleep -Milliseconds 250
}

L 'client seen, capturing 15s'
Start-Sleep -Seconds 15

(& pktmon stop 2>&1) | ForEach-Object { L "stop: $_" }
& pktmon filter remove 2>&1 | Out-Null
(& pktmon etl2pcap $etl --out $pcap 2>&1) | ForEach-Object { L "convert: $_" }
if (Test-Path $pcap) { L ('pcap bytes: ' + (Get-Item $pcap).Length) }
L 'done'
