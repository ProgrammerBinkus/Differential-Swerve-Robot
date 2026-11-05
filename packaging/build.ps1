# Builds the Windows driver station app.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Produces, in dist\:
#   Differential Swerve Driver Station\DriverStation.exe   the app (portable folder)
#   DifferentialSwerveDriverStation-<version>-portable.zip
#   DifferentialSwerveDriverStation-<version>-setup.exe     only if Inno Setup 6 is installed
param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No venv found. Run: python -m venv venv; venv\Scripts\pip install -r requirements-build.txt" }

Push-Location $root
try {
    if (-not $SkipTests) {
        & $python -m pytest -q
        if ($LASTEXITCODE) { throw "Tests failed; not building." }
    }

    & $python -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build packaging\station.spec
    if ($LASTEXITCODE) { throw "PyInstaller failed." }

    $version = (& $python -c "import station; print(station.__version__)").Trim()
    $app = "dist\Differential Swerve Driver Station"
    $zip = "dist\DifferentialSwerveDriverStation-$version-portable.zip"
    Compress-Archive -Path $app -DestinationPath $zip -Force
    Write-Host "Built $app\DriverStation.exe and $zip"

    $iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
              "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($iscc) {
        & $iscc /Q "/DAppVersion=$version" packaging\installer.iss
        if ($LASTEXITCODE) { throw "Inno Setup failed." }
        Write-Host "Built dist\DifferentialSwerveDriverStation-$version-setup.exe"
    } else {
        Write-Host "Inno Setup 6 not found, so no installer was built (the portable zip works on its own)."
        Write-Host "Install it from https://jrsoftware.org/isinfo.php and run this script again to get one."
    }
} finally {
    Pop-Location
}
