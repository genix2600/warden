; Warden installer, built with Inno Setup 6.
;
; Run scripts\build-installer.ps1 rather than compiling this by hand -- it
; builds the interface and the bundle first, and this script assumes
; dist\Warden already exists.
;
; Two decisions worth stating, because both are unusual and both are deliberate:
;
;   Per-user, not Program Files. PrivilegesRequired=lowest means installing
;   raises no UAC prompt at all. That is only defensible because Warden itself
;   no longer demands elevation to start -- it runs as a standard user, reports
;   which actions it cannot perform, and offers to restart elevated at the point
;   the user meets that limit. An application that could not start without
;   administrator would have no business installing without one either.
;
;   Two editions, from the same script. The standard one is 46 MB and
;   carries the model runtime but no weights; Warden fetches those on request,
;   from the Readiness page, into %LOCALAPPDATA% where they survive an upgrade.
;   The -offline edition bundles the weights too, at about 967 MB, for machines
;   that will never have a usable connection. Passing -Offline to
;   build-installer.ps1 sets the Edition suffix so the two do not collide.

#define AppName "Warden"
#define AppVersion "0.1.0"
#define AppPublisher "Warden"
#define AppURL "https://github.com/genix2600/warden"
#define AppExe "Warden.exe"

; Set by build-installer.ps1 to "-offline" for the edition that carries the
; model weights, so the two outputs do not overwrite one another.
#ifndef Edition
  #define Edition ""
#endif

[Setup]
; Fixed, so a reinstall upgrades in place instead of appearing twice in
; Add/Remove Programs. Never regenerate this.
AppId={{8B1F4A2E-7C3D-4E5A-9B6F-1D2C3E4A5B6C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
VersionInfoVersion={#AppVersion}

DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

SetupIconFile=..\assets\warden.ico
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}{#Edition}
WizardStyle=modern
SolidCompression=yes
; Not lzma2/max. The bulk of the payload is a quantised GGUF model, which is
; already close to incompressible -- max costs many minutes of build time to
; save a rounding error.
Compression=lzma2/normal
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Warden\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
{ WebView2 renders Warden's whole interface, and it is a system component the
  bundle cannot carry. Windows 11 has it; most updated Windows 10 machines do.
  Without it the window opens blank, which reads as "this program is broken"
  rather than "a Windows component is missing". Warn here, at a moment the user
  can act on it.

  Warn only -- never download. Warden's central claim is that it works with the
  network down, and an installer that silently required internet would make a
  liar of it. }
function WebView2Installed(): Boolean;
var
  Version: String;
  Client: String;
begin
  Client := '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + Client, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + Client, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + Client, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WebView2Installed() then
  begin
    Result := MsgBox(
      'Warden draws its interface with the Microsoft Edge WebView2 Runtime, ' +
      'which does not appear to be installed on this machine.' + #13#10#13#10 +
      'Warden will install, but the window will open blank until you add it. ' +
      'You can get it from Microsoft at:' + #13#10 +
      'https://developer.microsoft.com/microsoft-edge/webview2/' + #13#10#13#10 +
      'Continue installing anyway?',
      mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

{ Recorded sessions, logs and any local threshold overrides live in
  %LOCALAPPDATA%\Warden, separately from the program itself. They are the
  user's, not ours. Warden records sessions so that a decision can be reopened
  after the fact; deleting that on uninstall without asking would quietly
  undo the reason it exists. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\Warden');
    if DirExists(DataDir) then
    begin
      if MsgBox(
        'Remove Warden''s recorded sessions and logs as well?' + #13#10#13#10 +
        DataDir + #13#10#13#10 +
        'These are your records of what Warden saw and did. Choose No to keep them.',
        mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
