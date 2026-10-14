; HyperTeX 뷰어 Windows 설치 프로그램 (Inno Setup 6.1 이상). 이 파일은 UTF-8(BOM) 이어야 한다 (한글 메시지).
;
; 빌드 (저장소 뿌리에서, PyInstaller 결과 dist\htex-viewer 가 있어야 한다):
;   iscc /DAppVersion=0.0.1 packaging\windows\htex-viewer.iss
;   → dist\HyperTeX-Setup-0.0.1.exe
;
; - 기본은 관리자 권한 없이 사용자 단위 설치(%LOCALAPPDATA%\Programs\HyperTeX, HKCU\Software\Classes).
;   설치 화면에서 "모든 사용자" 를 고르면 관리자 권한으로 Program Files·HKLM 에 설치한다.
;   레지스트리 루트 HKA 는 이 선택에 따라 HKCU 또는 HKLM 이 된다.
; - .htex 연결(기본 앱), .tex 는 "연결 프로그램" 목록에만(OpenWithProgids), htex: URL 프로토콜.
; - 제거 시 위 레지스트리 항목을 지운다(uninsdeletekey / uninsdeletevalue).
; - 실행 인수: "경로" 또는 "htex://…" 를 그대로 htex-viewer.exe 에 넘긴다 (htex.__main__:gui_main).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\htex-viewer"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

#define AppName "HyperTeX"
#define AppExe "htex-viewer.exe"
#define ProgId "HyperTeX.Document"
#define TexProgId "HyperTeX.TeXDocument"

[Setup]
; AppId 는 바꾸지 말 것 (업그레이드·제거가 이 값으로 같은 앱을 찾는다)
AppId={{6F2E8C1A-4B7D-4E59-9C3A-2D1F0B7E5A41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=HyperTeX contributors
AppPublisherURL=https://github.com/hypertex
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\icons\htex.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=yes
; 서명: CI 가 /DSignTool=... 을 넘길 때만 (packaging/README.md 참고)
#ifdef SignTool
SignTool={#SignTool}
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; Korean.isl 은 Inno Setup 6.3 이후 공식 번역에 들어 있다. 없는 버전이면 영어만.
#if FileExists(AddBackslash(CompilerPath) + "Languages\Korean.isl")
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "assoc_htex"; Description: "{cm:AssocHtex}"; GroupDescription: "{cm:AssocGroup}"
Name: "assoc_tex"; Description: "{cm:AssocTex}"; GroupDescription: "{cm:AssocGroup}"
Name: "url_htex"; Description: "{cm:UrlHtex}"; GroupDescription: "{cm:AssocGroup}"

[CustomMessages]
english.AssocGroup=File and link associations:
english.AssocHtex=Open .htex files with {#AppName}
english.AssocTex=Add {#AppName} to "Open with" for .tex files
english.UrlHtex=Open htex:// links with {#AppName}
#if FileExists(AddBackslash(CompilerPath) + "Languages\Korean.isl")
korean.AssocGroup=파일·링크 연결:
korean.AssocHtex=.htex 파일을 {#AppName}(으)로 열기
korean.AssocTex=.tex 파일의 "연결 프로그램" 목록에 {#AppName} 추가
korean.UrlHtex=htex:// 링크를 {#AppName}(으)로 열기
#endif

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\icons\htex.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\htex.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\htex.ico"; Tasks: desktopicon

[Registry]
; ---- .htex → HyperTeX.Document -------------------------------------------------------------
Root: HKA; Subkey: "Software\Classes\.htex"; ValueType: string; ValueName: ""; ValueData: "{#ProgId}"; Flags: uninsdeletevalue; Tasks: assoc_htex
Root: HKA; Subkey: "Software\Classes\.htex"; ValueType: string; ValueName: "Content Type"; ValueData: "text/x-hypertex"; Flags: uninsdeletevalue; Tasks: assoc_htex
Root: HKA; Subkey: "Software\Classes\.htex"; ValueType: string; ValueName: "PerceivedType"; ValueData: "text"; Flags: uninsdeletevalue; Tasks: assoc_htex
Root: HKA; Subkey: "Software\Classes\.htex\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc_htex
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "HyperTeX Document"; Flags: uninsdeletekey; Tasks: assoc_htex
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\htex.ico,0"; Tasks: assoc_htex
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc_htex

; ---- .tex: 기본 앱은 바꾸지 않고 '연결 프로그램' 목록에만 -----------------------------------
Root: HKA; Subkey: "Software\Classes\.tex\OpenWithProgids"; ValueType: string; ValueName: "{#TexProgId}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc_tex
Root: HKA; Subkey: "Software\Classes\{#TexProgId}"; ValueType: string; ValueName: ""; ValueData: "TeX Document (HyperTeX viewer)"; Flags: uninsdeletekey; Tasks: assoc_tex
Root: HKA; Subkey: "Software\Classes\{#TexProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\htex.ico,0"; Tasks: assoc_tex
Root: HKA; Subkey: "Software\Classes\{#TexProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc_tex

; ---- htex: URL 프로토콜 (HKCU\Software\Classes\htex, "URL Protocol") -----------------------
Root: HKA; Subkey: "Software\Classes\htex"; ValueType: string; ValueName: ""; ValueData: "URL:HyperTeX Protocol"; Flags: uninsdeletekey; Tasks: url_htex
Root: HKA; Subkey: "Software\Classes\htex"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Tasks: url_htex
Root: HKA; Subkey: "Software\Classes\htex\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\htex.ico,0"; Tasks: url_htex
Root: HKA; Subkey: "Software\Classes\htex\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: url_htex

; ---- "기본 앱" 설정 화면에 나오도록 (Windows 10/11 RegisteredApplications) --------------------
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".htex"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".tex"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\HyperTeX\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\HyperTeX\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "HyperTeX 2.0 document viewer"
Root: HKA; Subkey: "Software\HyperTeX\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\htex.ico,0"
Root: HKA; Subkey: "Software\HyperTeX\Capabilities\FileAssociations"; ValueType: string; ValueName: ".htex"; ValueData: "{#ProgId}"
Root: HKA; Subkey: "Software\HyperTeX\Capabilities\FileAssociations"; ValueType: string; ValueName: ".tex"; ValueData: "{#TexProgId}"
Root: HKA; Subkey: "Software\HyperTeX\Capabilities\URLAssociations"; ValueType: string; ValueName: "htex"; ValueData: "htex"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\HyperTeX\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 사용자 캐시(%LOCALAPPDATA%\HyperTeX\Cache)는 지우지 않는다. 프로그램 폴더의 남은 파일만.
Type: filesandordirs; Name: "{app}"
