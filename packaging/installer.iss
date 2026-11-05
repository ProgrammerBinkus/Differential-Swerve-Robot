; Inno Setup 6 script for the driver station. packaging\build.ps1 runs it when Inno Setup is installed:
;   ISCC.exe /DAppVersion=1.0.0 packaging\installer.iss
; Installs for the current user by default (no admin needed). Choosing "install for all users" also
; adds a Windows Firewall rule so robot telemetry is let in on private networks.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Differential Swerve Driver Station"
#define AppExe "DriverStation.exe"

[Setup]
AppId={{F44BEA08-6E6F-40A9-BD97-9A63A08CA66E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Eric Zhao
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=DifferentialSwerveDriverStation-{#AppVersion}-setup
SetupIconFile=..\station\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName}"" dir=in action=allow program=""{app}\{#AppExe}"" profile=private,domain"; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName}"""; Flags: runhidden; Check: IsAdminInstallMode; RunOnceId: "RemoveFirewallRule"
