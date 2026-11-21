# Copy a whole SD card into an image file, opening the card read-only (the card is never changed).
# Run in an elevated PowerShell (Windows asks for admin approval) with the card in a USB reader:
#   powershell -ExecutionPolicy Bypass -File pi_setup\card\backup_card.ps1 -Out C:\pi\card.img
# Find the card's disk number with Get-Disk (default 1). If the copy stops part-way (the reader dropped
# off the USB bus), run it again with -StartGB set to a little before where it stopped.
# A failed read is retried 3 times, reopening the card; 8 failed 4 MB blocks in a row stop the copy.
param([Parameter(Mandatory)][string]$Out, [int]$Disk = 1, [double]$StartGB = 0, [string]$Log = "$Out.log")
$ErrorActionPreference = "Stop"
function Open-Card { New-Object System.IO.FileStream("\\.\PHYSICALDRIVE$Disk", [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite) }
function Write-Log($text) { $text | Tee-Object -FilePath $Log -Append }

$d = Get-Disk -Number $Disk
if ($d.BusType -ne "USB" -or $d.Size -gt 256GB) { throw "disk $Disk is $($d.FriendlyName) on $($d.BusType): not an SD card in a USB reader" }
$size = [long]$d.Size
$chunk = 4MB
$done = [long]([Math]::Floor($StartGB * 1GB / $chunk) * $chunk)
$src = Open-Card
$dst = New-Object System.IO.FileStream($Out, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::Write, [IO.FileShare]::Read)
$buf = New-Object byte[] $chunk
$bad = 0; $streak = 0; $start = Get-Date
Write-Log ("disk {0} ({1}, {2:N1} GB) -> {3}, from {4:N2} GB" -f $Disk, $d.FriendlyName, ($size/1GB), $Out, ($done/1GB))
while ($done -lt $size) {
    $want = [int][Math]::Min([long]$chunk, $size - $done)
    $ok = $false
    for ($try = 1; $try -le 3 -and -not $ok; $try++) {
        try {
            $src.Position = $done
            if ($src.Read($buf, 0, $want) -ne $want) { throw "short read" }
            $ok = $true
        } catch {
            Write-Log ("read error at {0:N3} GB (try {1}): {2}" -f ($done/1GB), $try, $_.Exception.Message)
            try { $src.Close() } catch {}
            Start-Sleep -Seconds 2
            try { $src = Open-Card } catch { Write-Log "reopen failed: $($_.Exception.Message)" }
        }
    }
    if ($ok) { $streak = 0 } else {
        $bad++; $streak++; [Array]::Clear($buf, 0, $want)   # zeros keep the offsets right
        if ($streak -ge 8) { Write-Log ("STOPPED at {0:N2} GB: the card stopped answering" -f ($done/1GB)); break }
    }
    $dst.Position = $done
    $dst.Write($buf, 0, $want)
    $done += $want
    if (($done % 512MB) -eq 0) { Write-Log ("{0:N1} of {1:N1} GB, {2} unreadable blocks, {3:N0} s" -f ($done/1GB), ($size/1GB), $bad, ((Get-Date)-$start).TotalSeconds) }
}
$src.Close(); $dst.Close()
Write-Log ("DONE at {0:N2} GB, {1} unreadable 4 MB blocks, {2:N0} s" -f ($done/1GB), $bad, ((Get-Date)-$start).TotalSeconds)
