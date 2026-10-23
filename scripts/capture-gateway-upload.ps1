$ErrorActionPreference = 'Stop'
$captureStarted = $false
$filterAdded = $false
try {
    & pktmon filter add AIScientistUploadProbe -i 172.67.74.19 -t TCP -p 443
    if ($LASTEXITCODE -ne 0) { throw 'Cannot add scoped packet filter' }
    $filterAdded = $true
    & pktmon start --capture --comp nics --pkt-size 96 --file-size 16 --file-name E:/AIScientist/artifacts/gateway-upload.etl
    if ($LASTEXITCODE -ne 0) { throw 'Cannot start packet capture' }
    $captureStarted = $true
    & E:/AIScientist/.venv/Scripts/python.exe E:/AIScientist/scripts/diagnose-response-transport.py --kind model --profiles x25519 --rounds 2 --long --fresh --ip 172.67.74.19
} finally {
    if ($captureStarted) { & pktmon stop }
    if ($filterAdded) { & pktmon filter remove AIScientistUploadProbe }
}
& pktmon etl2pcap E:/AIScientist/artifacts/gateway-upload.etl --out E:/AIScientist/artifacts/gateway-upload.pcapng
