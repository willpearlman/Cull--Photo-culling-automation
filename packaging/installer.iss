; Inno Setup script for the Windows installer. Built by packaging\build.ps1 after PyInstaller.
; Per-user install (no admin prompt) into %LOCALAPPDATA%\Programs\Cull.

#define AppName "Cull"
#define AppVersion "0.1.0-beta"

[Setup]
AppId={{6F3B2D1E-5C4A-4B8E-9A7F-2C1D0E9B8A61}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Will Pearlman
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=CullSetup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Cull.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Cull\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Cull.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Cull.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Cull.exe"; Description: "Start Cull"; Flags: nowait postinstall skipifsilent

[Code]
// Cull draws its window with Microsoft Edge WebView2. Windows 11 includes it; some Windows 10
// machines do not. Warn instead of failing silently at first launch.
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WebView2Installed() then
    MsgBox('Cull needs the Microsoft Edge WebView2 Runtime, which is not installed.' + #13#10 +
           'Install it from https://developer.microsoft.com/microsoft-edge/webview2/ ' +
           '(choose "Evergreen Bootstrapper"), then start Cull.', mbInformation, MB_OK);
end;
