# PyInstaller build of the driver station. Run packaging\build.ps1 rather than this directly.
# -*- mode: python -*-
import sys
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from station import APP_NAME, __version__  # noqa: E402

numbers = tuple(int(part) for part in __version__.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("ProductName", APP_NAME),
            StringStruct("FileDescription", APP_NAME),
            StringStruct("FileVersion", __version__),
            StringStruct("ProductVersion", __version__),
            StringStruct("InternalName", "DriverStation"),
            StringStruct("OriginalFilename", "DriverStation.exe"),
            StringStruct("LegalCopyright", "Eric Zhao"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / "packaging" / "station_entry.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "station" / "assets"), "assets")],
    # The robot side and the dev tools never run on the laptop.
    excludes=["robot", "tools", "tests", "wpimath", "wpiutil", "wpinet", "periphery", "numpy",
              "PIL", "pytest", "pyflakes", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DriverStation",
    icon=str(ROOT / "station" / "assets" / "icon.ico"),
    version=version_info,
    console=False,          # a windowed app; logs go to %LOCALAPPDATA%\<app>\logs
    upx=False,              # UPX-packed executables trip antivirus scanners
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name=APP_NAME)
