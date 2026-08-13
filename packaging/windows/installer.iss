; groupwatch Windows installer (Inno Setup). Built by CI — see .github/workflows/release.yml.
; Autostart is managed by the app itself (Settings toggle, ON by default) — AGENTS.md §3.7.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{B7E1A3C4-5D6F-4A2B-8C9D-0E1F2A3B4C5D}
AppName=groupwatch
AppVersion={#MyAppVersion}
AppVerName=groupwatch {#MyAppVersion}
DefaultDirName={localappdata}\Programs\groupwatch
DefaultGroupName=groupwatch
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=groupwatch-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\groupwatch.exe

[Files]
Source: "..\..\dist\groupwatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\groupwatch"; Filename: "{app}\groupwatch.exe"
Name: "{autodesktop}\groupwatch"; Filename: "{app}\groupwatch.exe"

[Run]
Filename: "{app}\groupwatch.exe"; Description: "Launch groupwatch"; Flags: nowait postinstall skipifsilent
