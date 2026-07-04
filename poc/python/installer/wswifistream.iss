; Inno Setup script for WS WiFi Stream (Windows installer).
; Packages the PyInstaller one-folder build (dist\WS-WiFi-Stream\) into a
; user-level setup.exe with Start Menu + optional desktop shortcut.
; Built in CI: iscc installer\wswifistream.iss

#define MyAppName "WS WiFi Stream"
#define MyAppVersion "1.0.3"
#define MyAppExeName "WS-WiFi-Stream.exe"

[Setup]
AppId={{9F3B2C7A-4D51-4E88-A2C9-7B1E6F0A5D34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=WS WiFi Stream
DefaultDirName={autopf}\WS WiFi Stream
DefaultGroupName=WS WiFi Stream
DisableProgramGroupPage=yes
; Per-user install → no admin prompt (the app is unsigned anyway).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=WS-WiFi-Stream-win-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\WS-WiFi-Stream\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\WS WiFi Stream"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall WS WiFi Stream"; Filename: "{uninstallexe}"
Name: "{userdesktop}\WS WiFi Stream"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch WS WiFi Stream"; Flags: nowait postinstall skipifsilent
