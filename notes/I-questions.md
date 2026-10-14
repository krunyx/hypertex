# I (배포) 질문과 임시 가정

형식: 어디 / 무엇이 문제 / 제안 / 임시 가정.

## 1. `htex.viewer.app.run` 의 서명 (J 와의 약속)
- 어디: `htex/viewer/app.py` `run(target: Optional[str] = None, argv=None)`, AGENTS.md "I와 J 사이의 약속".
- 문제: 약속은 `run(targets: list[str])` 인데 지금 저장소는 아직 str 하나를 받는다.
- 제안: J 결과가 합쳐지면 `htex/__main__.py` 의 `_call_run` 을 `return run(targets)` 한 줄로 줄이고,
  `tests/unit/test_I_entry.py::test_call_run_old_signature` 와 `test_real_run_signature_is_supported` 의 `"target"` 허용을 지운다.
- 임시 가정: `_call_run` 이 `inspect.signature` 로 첫 인수를 본다. 이름이 `targets` 이거나 주석에 list/Sequence/Iterable 이
  있으면 목록 전체, 아니면 첫 번째만(여러 개면 stderr 에 알림). **J 는 첫 인수 이름을 `targets` 로 해 주기를** 바란다.

## 2. macOS 파일·URL 열기는 Apple 이벤트로만 온다 (J)
- 어디: `packaging/pyinstaller/htex-viewer.spec` `argv_emulation=False`, `packaging/macos/Info.plist.in`.
- 문제: Finder 더블클릭, `open a.htex`, 브라우저의 htex:// 링크는 argv 가 아니라 `QFileOpenEvent` 로 온다.
  PyInstaller 의 argv_emulation 은 시작 시 한 번만 이벤트를 argv 로 바꾸고, 앱이 떠 있을 때의 이벤트는 놓친다(또 Qt 의 이벤트 처리와 충돌).
- 제안: J 의 QFileOpenEvent 처리(`QApplication` 하위 클래스의 `event()`)가 `file()`·`url()` 둘 다 보도록.
  htex:// URL 은 `QFileOpenEvent.url()` 로 오고 `file()` 은 비어 있다.
- 임시 가정: argv_emulation 끔. J 결과 전에는 맥에서 앱만 뜨고 문서는 열리지 않는다(packaging/README.md 알려진 문제).

## 3. 단일 인스턴스 + 윈도·리눅스 등록 (J)
- 어디: `packaging/windows/htex-viewer.iss`(`"…\htex-viewer.exe" "%1"`), `packaging/linux/org.hypertex.viewer.desktop`(`%U`).
- 문제: 윈도는 파일 여러 개를 고르면 파일마다 프로세스를 하나씩 띄운다(`%1`). 리눅스 `%U` 는 한 번에 여러 개를 준다.
- 제안: J 의 단일 인스턴스(QLocalServer)가 짧은 간격으로 몰려오는 여러 프로세스를 한 창(탭)으로 모으면 된다.
  서버 이름은 사용자별로(예: `hypertex-<사용자>`) — 다른 사용자 세션과 섞이지 않게.
- 임시 가정: 등록은 모두 "인수 = 대상 목록" 으로 gui_main 에 넘긴다.

## 4. 리눅스 Chromium 샌드박스
- 어디: `packaging/pyinstaller/htex_viewer_entry.py` (`HTEX_NO_SANDBOX=1`).
- 문제: 컨테이너와 Ubuntu 24.04+(AppArmor 의 비특권 userns 제한)에서는 샌드박스가 실패한다. 실패하면 빈 창이나 즉시 종료.
- 제안: 뷰어(J)가 렌더 프로세스 비정상 종료(`renderProcessTerminated`)를 잡아 "HTEX_NO_SANDBOX=1 로 실행" 을 안내하면 좋겠다.
  배포판 패키지(deb)라면 AppArmor 프로필을 함께 설치.
- 임시 가정: 기본은 샌드박스 켬. 환경 변수로만 끈다. CI·스모크 테스트는 끈다.

## 5. 뷰어의 창 아이콘
- 어디: `htex/viewer/app.py` (QApplication·창에 `setWindowIcon` 없음).
- 문제: 리눅스는 .desktop `Icon=org.hypertex.viewer` 와 `StartupWMClass=HyperTeX` 로 작업 표시줄 아이콘을 찾는데,
  pip 설치본(번들이 아닌)으로 실행하면 창 아이콘이 기본 Qt 아이콘. 윈도·맥은 실행 파일·번들 아이콘이 쓰인다.
- 제안: J 가 `app.setDesktopFileName("org.hypertex.viewer")` (Wayland 에서 .desktop 과 창을 잇는 데 필요)와
  `app.setWindowIcon(...)` 을 넣기. 아이콘 파일을 패키지 데이터로 넣을 필요가 있으면 `htex/viewer/` 아래에 두면 된다
  (pyproject `package-data` 의 `*.png`·`*.svg` 가 이미 포함). `packaging/icons/png/htex-256.png` 를 복사해 쓰면 된다.
- 임시 가정: 없음 (번들 아이콘만).

## 6. 시스템 setuptools 와 `--no-build-isolation`
- 어디: 작업 공간의 Debian setuptools 68.1.2.
- 문제: 격리 없이 wheel 을 만들면 `AttributeError: install_layout` 로 실패한다(Debian 패치). 격리 빌드(`python -m build`)는 된다.
- 임시 가정: `tests/unit/test_I_package.py` 는 격리 없이 먼저 해 보고 실패하면 격리 빌드(PyPI 에서 setuptools 받음)로 넘어간다.
  그래서 PyPI 에 닿지 않고 시스템 setuptools 도 깨진 환경에서는 이 테스트가 실패한다.

## 7. 명세·다른 담당 코드에 대한 것
- 없음. 런타임 의존성은 늘리지 않았다(`dependencies = []`, PySide6 는 `viewer` 선택 의존성).

---

## 루트 README 에 넣을 설치 절 (통합 담당에게 제안)

"빠른 시작" 바로 앞에 넣는 것을 제안:

```markdown
## 설치

**앱(권장)** — [릴리스](../../releases) 에서 내려받는다.

| OS | 파일 | 비고 |
| --- | --- | --- |
| macOS (Apple Silicon / Intel) | `HyperTeX-<버전>-macos-arm64.dmg` / `-x86_64.dmg` | 열어서 HyperTeX 를 응용 프로그램 폴더로 끌기 |
| Windows 10/11 | `HyperTeX-Setup-<버전>.exe` | 관리자 권한 없이 설치. `.htex` 파일과 `htex://` 링크가 연결된다 |
| Linux | `HyperTeX-<버전>-x86_64.AppImage` | `chmod +x` 후 실행 |
| Linux | `HyperTeX-<버전>-linux-x86_64.tar.gz` | 풀고 `./install.sh` → `~/.local` 에 설치, `.htex`·`htex://` 연결 (`--uninstall` 로 제거) |

**파이썬 패키지**

```bash
pip install htex              # 파서·HTML 변환·웹 서버 (의존성 없음): htex html / serve / build
pip install "htex[viewer]"    # + 전용 뷰어 (PySide6): htex view, htex-viewer
```

pip 로 설치한 뷰어를 리눅스 데스크톱에 연결하려면 저장소의 `packaging/linux/install.sh --pip`.
직접 빌드·서명·릴리스 방법은 `packaging/README.md`.
```
