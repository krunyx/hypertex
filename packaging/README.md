# HyperTeX 배포

`htex` 파이썬 패키지와, 설치해서 쓰는 **HyperTeX 뷰어** 앱(맥 `.app`/`.dmg`, 윈도 설치 프로그램, 리눅스 tar.gz·AppImage)을
만드는 방법을 설명한다.

```
packaging/
├── pyinstaller/htex-viewer.spec     PyInstaller 명세 (onedir, Qt 정리, macOS BUNDLE + Info.plist)
├── pyinstaller/htex_viewer_entry.py 실행 파일 진입점 → htex.__main__:gui_main
├── pyinstaller/hooks/hook-htex.py   htex 하위 모듈·패키지 데이터
├── check_bundle.py                  빌드 결과 점검 (QtWebEngineProcess·resources·locales·interact.js·Qt 라이브러리)
├── smoke_test.py                    빌드한 실행 파일을 화면 없이 띄워 예제 문서 + 스크린숏
├── icons/                           htex.svg(원본) → make_icons.py → png/·htex.png·htex.ico·htex.icns
├── macos/                           Info.plist.in, entitlements.plist, make-dmg.sh, sign-and-notarize.sh
├── windows/htex-viewer.iss          Inno Setup (사용자 단위 설치, .htex·.tex·htex: 연결)
├── linux/                           .desktop, MIME XML, install.sh, make-tarball.sh, make-appimage.sh
└── ci/actionlint.yaml               워크플로 검사 설정
.github/workflows/build.yml          테스트 → (태그 v*) 세 OS 빌드 → GitHub Release
```

## 1. 파이썬 패키지

```bash
pip install .            # 파서·HTML 변환·서버 (의존성 없음) → 명령 htex
pip install ".[viewer]"  # + PySide6 → htex view, GUI 명령 htex-viewer
pip install ".[build]"   # 빌드 도구: build, pyinstaller, Pillow
python -m build          # sdist·wheel → dist/
```

- 버전은 `htex/__init__.py` 의 `__version__` 한곳. pyproject 는 이것을 읽는다(`dynamic = ["version"]`),
  PyInstaller spec·Inno Setup·DMG 이름도 여기서 가져온다. 릴리스 태그 `v<버전>` 은 이것과 같아야 한다(CI 가 확인).
- `.py` 아닌 패키지 파일(`htex/web/interact.js` 등)은 `[tool.setuptools.package-data]` 로 들어간다.
  새 종류(예: `.woff2`)를 추가하면 거기에도 추가할 것 — `tests/unit/test_I_package.py` 가 빠진 파일을 잡는다.
- 진입점: 콘솔 `htex = htex.__main__:main`, GUI `htex-viewer = htex.__main__:gui_main`.
  `htex-viewer 파일.htex htex://… …` 는 `htex view 파일.htex htex://… …` 와 같다(옵션 해석 없음, `-` 로 시작하는 인수는 버림).

## 2. 뷰어 앱 빌드 (PyInstaller)

세 OS 모두 같은 명령. 크로스 빌드는 안 된다(각 OS 에서 빌드).

```bash
python -m pip install ".[viewer,build]"
python packaging/icons/make_icons.py                       # 원본 SVG 를 바꿨을 때만 (결과는 커밋되어 있음)
pyinstaller --noconfirm --clean packaging/pyinstaller/htex-viewer.spec
python packaging/check_bundle.py dist/htex-viewer          # macOS: dist/HyperTeX.app
python packaging/smoke_test.py dist/htex-viewer/htex-viewer   # → dist/smoke.png, dist/smoke.json
```

| OS | 결과 | 다음 단계 |
| --- | --- | --- |
| Linux | `dist/htex-viewer/` (`htex-viewer` + `_internal/`) | `packaging/linux/make-tarball.sh`, `make-appimage.sh` |
| macOS | `dist/HyperTeX.app` | (서명) → `packaging/macos/make-dmg.sh` → (공증) |
| Windows | `dist\htex-viewer\htex-viewer.exe` | `iscc /DAppVersion=<버전> packaging\windows\htex-viewer.iss` |

실행 파일은 CLI 명령도 받는다: `htex-viewer html a.htex -o a.html`, `htex-viewer serve 폴더` (첫 인수가 하위 명령일 때).

### 크기 (리눅스 x86_64, PySide6 6.12, Python 3.13 에서 측정)

| | 크기 |
| --- | --- |
| 정리 전 onedir | 531 MB |
| **정리 후 onedir** | **425 MB** (그중 libQt6WebEngineCore 195 MB, resources 25 MB, ICU 31 MB) |
| tar.gz | 178 MB |
| AppImage | 164 MB |

spec 이 하는 정리:
- 뷰어가 쓰지 않는 Qt 모듈(3D, Charts, Multimedia, Pdf, Quick3D, QuickControls2, Labs, …)과 모든 QML 파일 제외 (`EXCLUDE_QT`, `_UNUSED_LIB`).
  QtQuick·QtQuickWidgets·QtQml·QmlModels·QmlMeta·QmlWorkerScript·WebChannel·Positioning·PrintSupport·OpenGL 은
  libQt6WebEngineCore/Widgets 가 링크하므로 **남겨야 한다** (빼면 import 단계에서 `ImportError`).
  `check_bundle.py` 가 리눅스에서 `readelf` 로 이를 확인한다.
- Chromium 로캘 `.pak` 을 12개 언어로 줄임 (44 MB → 약 8 MB). 전부 넣으려면 `HTEX_WEBENGINE_LOCALES=all`, 목록 지정은
  `HTEX_WEBENGINE_LOCALES=en-US,ko,…`. 없는 로캘은 en-US 로 대신한다(웹 페이지 내용과 무관, Chromium 내부 문구만).
- 다른 Qt 모듈의 번역(.qm) 제외. UPX 는 쓰지 않는다(Qt 라이브러리를 깨뜨린다).
- 더 줄이려면: `--strip`(리눅스, 약 10% 이득, 디버깅 정보 손실), `qtwebengine_devtools_resources.pak` 제외(개발자 도구 안 씀, 12 MB) —
  둘 다 지금은 하지 않았다.

### 실행 파일 진입점과 환경 변수

`pyinstaller/htex_viewer_entry.py` → `htex.__main__:gui_main(argv)` → `htex.viewer.app.run(targets)`.
QApplication 은 만들지 않는다(스킴 등록은 run 이 QApplication 전에 한다).

| 변수 | 뜻 |
| --- | --- |
| `HTEX_NO_SANDBOX=1` | (리눅스) Chromium 샌드박스 끄기. 사용자 네임스페이스가 막힌 시스템·컨테이너용. 기본은 켜 둔다 |
| `HTEX_SMOKE_OUT=접두어` | 첫 문서를 불러온 뒤 `<접두어>.png`(창 스크린숏)·`.json` 을 쓰고 끝냄 (smoke_test.py 가 씀) |
| `QT_QPA_PLATFORM=offscreen` | 화면 없이 실행 (CI) |

## 3. OS 등록 (.htex 파일, htex:// 주소)

모든 OS 에서 OS 가 넘기는 대상은 진입점(`gui_main`)이 받아 `run(targets)` 로 넘긴다. 이미 떠 있는 뷰어로 넘기는 것
(단일 인스턴스)과 macOS 의 파일 열기 이벤트 처리는 뷰어(htex/viewer, 담당 J)가 한다.

### macOS (`macos/Info.plist.in`, spec 의 BUNDLE 단계가 넣음)
- `CFBundleIdentifier = org.hypertex.viewer`
- `CFBundleURLTypes`: `htex` 스킴
- `CFBundleDocumentTypes`: `.htex`(UTI `org.hypertex.htex`, Owner), `.tex`(UTI `org.tug.tex`·`public.tex`, Viewer·**Alternate**)
- `UTExportedTypeDeclarations`: `org.hypertex.htex` (확장자 htex, MIME text/x-hypertex), `.tex` 는 `UTImportedTypeDeclarations`
- macOS 는 파일·URL 을 **명령줄 인수가 아니라 Apple 이벤트**로 넘긴다. `argv_emulation=False` 로 두고 뷰어의
  `QFileOpenEvent` 처리에 맡긴다(앱이 이미 떠 있을 때도 같은 경로).
- 앱을 처음 실행하거나 /Applications 로 옮기면 Launch Services 가 등록한다. 수동 갱신:
  `/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/HyperTeX.app`

### Windows (`windows/htex-viewer.iss`)
- 기본 **사용자 단위 설치**(관리자 권한 불필요): `%LOCALAPPDATA%\Programs\HyperTeX`, 레지스트리는 `HKCU\Software\Classes`.
  설치 화면에서 "모든 사용자" 를 고르면 Program Files·HKLM.
- `.htex` → ProgID `HyperTeX.Document` (기본 앱), `.tex` → `OpenWithProgids` 에만(기본 앱을 빼앗지 않음),
  `htex:` → `HKCU\Software\Classes\htex` + `URL Protocol` 값. 셋 다 설치 화면에서 끌 수 있다.
- "기본 앱" 설정 화면에 나오도록 `RegisteredApplications`·`Capabilities` 도 쓴다.
  Windows 10/11 은 사용자가 고르기 전까지 기존 기본 앱을 바꾸지 않을 수 있다(UserChoice 해시 보호) — 정상 동작.
- 제거하면 위 키·값을 지운다. 사용자 캐시(`%LOCALAPPDATA%\HyperTeX\Cache`)는 남긴다.

### Linux (`linux/`)
- `org.hypertex.viewer.desktop`: `Exec=htex-viewer %U`, `MimeType=text/x-hypertex;x-scheme-handler/htex;`
- `hypertex-mime.xml`: `text/x-hypertex`, glob `*.htex`, `text/plain` 의 하위 형식
- `install.sh` (사용자 단위, `~/.local`):
  ```bash
  packaging/linux/install.sh dist/htex-viewer     # 번들을 ~/.local/lib/hypertex 로 복사, ~/.local/bin/htex-viewer 링크, 등록
  packaging/linux/install.sh --pip                # pip 로 설치한 htex-viewer 를 등록만
  HTEX_EXEC=~/Apps/HyperTeX.AppImage packaging/linux/install.sh --exec   # AppImage 등 임의 실행 파일 등록
  packaging/linux/install.sh --uninstall
  ```
  `update-mime-database`·`update-desktop-database`·`gtk-update-icon-cache` 를 부르고 `xdg-mime default` 로 기본 앱을 정한다
  (`HTEX_SET_DEFAULT=0` 이면 기본 앱 지정 안 함). 릴리스 tar.gz 안에도 같은 install.sh 가 들어 있다(인수 없이 실행).
- AppImage 는 스스로 등록하지 않는다. 위 `--exec` 나 AppImageLauncher 를 쓴다.

확인 (이 저장소 작업 공간에서 임시 HOME 으로 해 봄):
```bash
gio info -a standard::content-type a.htex       # text/x-hypertex
xdg-mime query default text/x-hypertex          # org.hypertex.viewer.desktop
xdg-mime query default x-scheme-handler/htex    # org.hypertex.viewer.desktop
gio open a.htex ; gio open htex://example.org/doc.htex   # 뷰어가 뜬다
```
데스크톱 환경이 없는 곳에서 `xdg-mime query filetype` 은 `file --mime-type` 을 써서 `text/plain` 을 낼 수 있다
(GNOME·KDE 에서는 shared-mime-info 를 쓴다).

## 4. CI 로 릴리스 만들기 (`.github/workflows/build.yml`)

1. `htex/__init__.py` 의 `__version__` 을 올리고 커밋.
2. `git tag v<버전> && git push --tags`
3. 워크플로: **test** (ubuntu·macos·windows × Python 3.11·3.13, + ubuntu 3.12; `pytest tests/unit`, `tools/run_all.py`)
   → **build** (태그 `v*` 일 때만; ubuntu-22.04, macos-15(arm64), macos-15-intel(x86_64), windows-latest)
   → **release** (모든 산출물 + `SHA256SUMS.txt` 를 **초안(draft)** GitHub Release 로). 확인 후 손으로 공개.
   태그에 `-` 가 있으면(`v0.1.0-rc1`) prerelease.
4. 빌드 단계마다 `check_bundle.py` 와 `smoke_test.py`(화면 없이 예제 문서 열기)가 돌고 스크린숏을 `smoke-<os>` 아티팩트로 올린다.
5. 산출물: `HyperTeX-<v>-linux-x86_64.tar.gz`, `HyperTeX-<v>-x86_64.AppImage`, `HyperTeX-<v>-macos-arm64.dmg`,
   `HyperTeX-<v>-macos-x86_64.dmg`, `HyperTeX-Setup-<v>.exe`, `HyperTeX-<v>-windows-x64.zip`.

태그 없이 빌드만 시험하려면 Actions 화면에서 workflow_dispatch 로 `build: true`.

워크플로 검사(로컬): `actionlint -config-file packaging/ci/actionlint.yaml .github/workflows/build.yml`

## 5. 서명과 공증

비밀값이 없으면 해당 단계는 건너뛰고 서명 안 된 산출물이 나온다(맥은 ad-hoc 서명. 사용자는 처음 열 때
"확인되지 않은 개발자" 경고 → 우클릭 › 열기, 윈도는 SmartScreen 경고).

### macOS — 필요한 저장소 비밀값
| 비밀값 | 내용 |
| --- | --- |
| `MACOS_CERTIFICATE_P12` | "Developer ID Application" 인증서+개인 키를 내보낸 .p12 의 base64 (`base64 -i cert.p12 \| pbcopy`) |
| `MACOS_CERTIFICATE_PASSWORD` | .p12 암호 |
| `MACOS_SIGN_IDENTITY` | 예: `Developer ID Application: 이름 (TEAMID)` |
| `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` | 공증용. 앱 암호는 appleid.apple.com › 로그인 및 보안 › 앱 암호 |

절차(`macos/sign-and-notarize.sh`): 안쪽 Mach-O 파일 → 안쪽 번들(QtWebEngineProcess.app, *.framework) → 바깥 .app 순으로
`codesign --options runtime --timestamp --entitlements macos/entitlements.plist` (hardened runtime; `--deep` 은 쓰지 않음)
→ DMG 만들기 → DMG 서명 → `xcrun notarytool submit --wait` → `xcrun stapler staple`.
entitlements: `allow-jit`, `allow-unsigned-executable-memory`(V8), `disable-library-validation`(PyInstaller 가 푼 확장 모듈).
로컬: `MACOS_SIGN_IDENTITY=… packaging/macos/sign-and-notarize.sh sign dist/HyperTeX.app`,
`NOTARY_PROFILE=… packaging/macos/sign-and-notarize.sh notarize dist/HyperTeX-….dmg`.

### Windows — 필요한 저장소 비밀값
| 비밀값 | 내용 |
| --- | --- |
| `WINDOWS_CERTIFICATE_PFX` | 코드 서명 인증서 .pfx 의 base64 |
| `WINDOWS_CERTIFICATE_PASSWORD` | .pfx 암호 |

`signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256` 로 `htex-viewer.exe` 를 서명하고,
Inno Setup 에 `/Ssigntool=…` 과 `/DSignTool=signtool` 을 넘겨 설치 프로그램과 제거 프로그램도 서명한다.
2023년 이후 새 OV/EV 인증서는 하드웨어 토큰·클라우드 HSM(Azure Trusted Signing, DigiCert KeyLocker 등)에만 발급되므로
.pfx 방식이 안 될 수 있다 — 그때는 이 단계를 해당 서비스의 서명 액션으로 바꾼다.

### Linux
서명 없음. 릴리스의 `SHA256SUMS.txt` 로 확인. AppImage 서명(`appimagetool --sign`)은 GPG 키가 생기면 추가.

## 6. 알려진 문제

- **크기**: QtWebEngine(Chromium) 때문에 400 MB 대(압축 160–180 MB). 시스템 Qt 를 쓰는 배포판 패키지(deb/rpm/Flatpak)가
  장기적으로 더 작다.
- **리눅스 샌드박스**: Ubuntu 24.04 이후 AppArmor 가 비특권 사용자 네임스페이스를 막아 Chromium 샌드박스가 실패할 수 있다
  (빈 창 또는 즉시 종료). 임시로 `HTEX_NO_SANDBOX=1`. 근본 해결은 AppArmor 프로필(`/etc/apparmor.d/`) 또는 배포판 패키지.
- **리눅스 xcb**: Qt 6.5+ 의 xcb 플랫폼은 시스템의 `libxcb-cursor0` 이 필요하다(번들에 넣지 않음). 없으면
  "Could not load the Qt platform plugin xcb" — `sudo apt install libxcb-cursor0`. Wayland 세션은 상관없다.
- **glibc**: 빌드한 시스템보다 오래된 glibc 에서는 돌지 않는다. CI 는 ubuntu-22.04(glibc 2.35)에서 빌드한다.
  PySide6 휠 자체가 요구하는 glibc 보다 낮출 수는 없다.
- **macOS 첫 실행**: 서명·공증 안 된 빌드는 Gatekeeper 가 막는다(우클릭 › 열기, 또는 `xattr -dr com.apple.quarantine HyperTeX.app`).
- **macOS 파일 열기**: Finder 더블클릭·htex:// 링크는 Apple 이벤트로 오므로 뷰어의 QFileOpenEvent 처리(J)가 합쳐져야 동작한다.
  그 전에는 앱만 뜨고 문서는 열리지 않는다.
- **단일 인스턴스**: 뷰어(J)가 합쳐지기 전에는 파일을 열 때마다 새 프로세스·창이 뜬다.
- **Windows 기본 앱**: Windows 10/11 은 설치 프로그램이 기본 앱을 강제로 바꾸지 못하게 한다. `.htex` 는 다른 앱이 없으면 바로,
  있으면 "연결 프로그램" 에서 한 번 고르게 된다.
- **로캘 경고**: `LANG=C` 환경에서 Qt 가 "Detected locale C …" 를 찍는다. 동작에는 영향 없다.
