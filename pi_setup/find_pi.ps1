# Find the Pi on the local network: by name first, then any device on this PC's Wi-Fi subnet with SSH open.
# Run: powershell -ExecutionPolicy Bypass -File pi_setup\find_pi.ps1
param([string]$PiHost = "orangepi4pro.local")
$found = @()
try { $found += (Resolve-DnsName $PiHost -Type A -ErrorAction Stop).IPAddress } catch {}
if (-not $found) {
    $me = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi*" -ErrorAction SilentlyContinue |
        Where-Object { $_.PrefixLength -eq 24 } | Select-Object -First 1
    if (-not $me) { "no /24 Wi-Fi network found on this PC"; exit 1 }
    $net = $me.IPAddress -replace '\.\d+$', ''
    $jobs = 1..254 | ForEach-Object {
        $c = New-Object System.Net.Sockets.TcpClient
        [pscustomobject]@{ ip = "$net.$_"; c = $c; t = $c.ConnectAsync("$net.$_", 22) }
    }
    Start-Sleep -Seconds 4
    foreach ($j in $jobs) { if ($j.t.Status -eq 'RanToCompletion') { $found += $j.ip }; $j.c.Dispose() }
}
if ($found) { "SSH open on: $($found -join ', ')" } else { "no device with SSH found: is the Pi on and on this Wi-Fi?" }
