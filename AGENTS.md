# 작업 분담 규칙

이 저장소는 HyperTeX 2.0 기준 구현이다. 명세는 `docs/spec.md`, 계약은 `schema/`와 `tests/manifest.json`이다.

## 공통 규칙

1. **자기 담당 파일만 수정한다.** 아래 표에 없는 파일, 특히 `schema/`, `tests/manifest.json`,
   `tests/docs/`, `tools/check.py`, `AGENTS.md`, `docs/spec.md` 는 **수정 금지**.
2. 명세·스키마·테스트가 틀렸거나 모호하거나 서로 모순되면 **고치지 말고** `notes/<담당>-questions.md` 에
   적는다: 어느 파일 어느 부분, 무엇이 문제인지, 제안하는 해결, 그 사이 임시로 어떻게 가정했는지.
3. 외부 패키지를 추가하지 않는다 (파이썬 표준 라이브러리만. 테스트용 pytest·jsonschema는 예외).
4. 예외로 파싱을 멈추지 않는다. 문제는 `ctx.sink.add(...)` 진단으로 남기고 계속한다 (명세 7절).
5. 완료 기준을 `python tools/run_all.py <사례>` 와 자기 단위 테스트(`tests/unit/test_<담당>_*.py`)로 확인한다.
6. 끝나면 git에 커밋한다. 커밋 메시지 첫 줄은 `[A]`, `[B]` 처럼 담당 표시로 시작.

## 담당 구역

| 담당 | 수정 가능한 파일 | 완료 기준 |
| --- | --- | --- |
| A 정답 트리 | `tests/trees/*.tree.json` (01, 11 제외), `notes/A-questions.md` | 26건 모두 `python tools/check.py --all tests/trees` 통과 |
| B 토큰·매크로 | `htex/lexer.py`, `htex/macros.py`, `tests/unit/test_B_*.py`, `notes/B-questions.md` | `macros.py` docstring 계약 구현. 단위 테스트로 사례 15–18, 20의 매크로 동작 검증 |
| C 구조 | `htex/builder.py`, `htex/commands.py`, `htex/parser.py`, 새 파일 `htex/build_*.py`, `tests/unit/test_C_*.py`, `notes/C-questions.md` | `run_all.py` 로 01–14, 19, 24, 26, 28 통과 (27은 B 결과 합친 뒤) |
| D 계산식·그림 | `htex/expr.py`, `htex/picture.py`, `tests/unit/test_D_*.py`, `notes/D-questions.md` | 두 파일 docstring 계약 구현. 단위 테스트로 21–23, 25의 그림 진단 검증 |
| E HTML | `htex/html/` 아래 전부, `tests/unit/test_E_*.py`, `notes/E-questions.md` | `tests/trees/` 의 모든 트리를 예외 없이 HTML로 변환, 수식은 MathML |

다른 담당의 모듈은 **인터페이스(함수 이름·인자·docstring 계약)만 믿고** 쓴다. 0단계에서는 통과(stub) 구현이므로,
자기 테스트는 자기 모듈만으로 확인할 수 있게 짠다.

## 모듈 사이의 흐름

```
lexer.tokenize ─▶ macros.Expander.expand ─▶ builder.build ─▶ 문서 트리(JSON) ─▶ html.render
   (B)                 (B)                      (C)                                  (E)
                                                 │
                                                 └─▶ picture.check_picture ─▶ expr.parse
                                                         (D)                    (D)
```

## 테스트가 가정하는 번호 규칙

`README.md`의 같은 이름 절을 따른다.


## 2단계 담당 구역

1단계 규칙(공통 규칙 1–6)은 그대로다. 2단계에서는 `docs/interaction-protocol.md`가 F·G·H 사이의 계약이다.
PySide6는 설치되어 있고 `QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox` 로 화면 없이도
QtWebEngine이 동작한다 (페이지 스크린숏으로 결과를 눈으로 확인할 수 있다).

| 담당 | 수정 가능한 파일 | 완료 기준 |
| --- | --- | --- |
| F 전용 뷰어 | `htex/viewer/` 아래 전부, `tests/unit/test_F_*.py`, `notes/F-questions.md` | `htex view` 로 로컬·htex:// 문서 열기, 링크 이동, 히스토리, 미리보기, 슬라이더 연동 |
| G 웹 폴백 | `htex/web/` 아래 전부(interact.js 포함), `tests/unit/test_G_*.py`, `notes/G-questions.md` | `htex serve`, `htex build`, 상호작용 스크립트 |
| H 그림 렌더러 | `htex/tikz/` 아래 전부, `htex/html/render.py`의 `b_picture` 함수 하나, `tests/unit/test_H_*.py`, `notes/H-questions.md` | 사례 21, 23, 25와 예제의 그림을 SVG로 |

`htex/__main__.py`의 명령 추가는 F(`view`)와 G(`serve`, `build`)가 각자 자기 하위 명령만 넣는다(충돌 시 통합 단계에서 합침).


## 3단계 담당 구역 (배포와 뷰어 다듬기)

| 담당 | 수정 가능한 파일 | 완료 기준 |
| --- | --- | --- |
| I 배포 | `packaging/` 아래 전부(새로), `pyproject.toml`, `.github/workflows/` 아래 전부(새로), `htex/__main__.py`(GUI 진입점 추가만), `tests/unit/test_I_*.py`, `notes/I-questions.md` | `pip install .[viewer]`, PyInstaller로 리눅스 실행 파일 빌드·실행 확인, 맥·윈도·리눅스 빌드 워크플로, OS에 `.htex`·`htex://` 등록 파일 |
| J 뷰어 다듬기 | `htex/viewer/` 아래 전부, 새 파일 `htex/linkres.py`, `htex/web/server.py`·`htex/web/build.py`(다른 문서 링크 번호 연결 부분만), `tests/unit/test_J_*.py`, `notes/J-questions.md` | 탭, 찾기, 확대·축소, 테마 선택, 로컬 파일 자동 새로고침, 다른 문서 링크 번호 표시, 단일 인스턴스·OS 파일 열기 이벤트 |

I와 J 사이의 약속:
- 실행 진입점은 `htex view [대상…]` 과 GUI 진입점 `htex.__main__:gui_main` (인수 = 파일 경로나 주소 여러 개). 둘 다 `htex.viewer.app.run(targets)` 를 부른다.
- J는 `htex.viewer.app.run` 이 대상 목록(list[str])을 받도록 하고, 이미 떠 있는 뷰어가 있으면 그쪽에 넘기고 끝나게 하며(단일 인스턴스), macOS의 파일 열기 이벤트(QFileOpenEvent: 파일과 htex:// URL)를 처리한다.
- I는 OS 등록(macOS Info.plist의 CFBundleURLTypes·CFBundleDocumentTypes, 윈도 레지스트리, 리눅스 .desktop·MIME)이 위 진입점으로 대상을 넘기게 만든다.
- `htex/web/interact.js`는 실행 파일에 패키지 데이터로 들어가야 한다 (I).


## 4단계 담당 구역 (실제 원고 호환)

| 담당 | 수정 가능한 파일 | 완료 기준 |
| --- | --- | --- |
| K 실제 원고 호환 | `htex/macros.py`·`htex/lexer.py`(compat 부분), 새 파일 `htex/build_compat.py`, `htex/build_blocks.py`·`htex/build_inline.py`·`htex/builder.py`·`htex/build_meta.py`(compat 연결 부분), `htex/commands.py`(수식 목록 일원화), `htex/html/mathml.py`, 새 파일 `htex/html/cd.py`, `htex/html/style.py`(새 표시), `tools/realworld.py`, `tests/unit/test_K_*.py`, `notes/K-questions.md` | `python tools/realworld.py --check` 통과, 기존 단위 테스트·`run_all.py`·`compare.py` 유지 |

- compat(.tex) 전용 처리는 `ctx.mode == "compat"` / `self.mode == "compat"` 안에 둔다. native(.htex) 동작을 바꾸는
  것(수식의 모르는 명령 표시, 중괄호 안의 `$`)은 `notes/K-questions.md` 2절에 적었다.
- 기존 테스트를 바꾼 곳도 같은 절에 적었다. 명세·스키마·manifest는 고치지 않았다 (1절의 확인 필요 항목 참고).


## 5단계 담당 구역 (Chrome 모양 뷰어)

| 담당 | 수정 가능한 파일 | 완료 기준 |
| --- | --- | --- |
| L 뷰어 모양 | `htex/viewer/` 아래 전부(새 파일 `chrome.py`·`bookmarks.py`·`startpage.py`), `README.md`(뷰어 절), `tests/unit/test_L_*.py`, `notes/L-questions.md` | 탭 줄·도구줄·북마크바·페이지 네 줄, 시작 페이지, 북마크, 기존 F·J 테스트 유지 |

- F·J 테스트가 쓰는 이름(`w.tabs` 의 QTabWidget 꼴 메서드, `address`, `diag_label`, `zoom_label`, `act_back` …)은 그대로 둔다.
- 결정과 확인 필요 항목은 `notes/L-questions.md`.


## 6단계 담당 구역 (Markdown 읽기, 로컬 HTML)

| 담당 | 수정 가능한 파일 | 완료 기준 |
| --- | --- | --- |
| M Markdown·로컬 HTML | 새 파일 `htex/markdown.py`, `htex/parser.py`(형식 고르기), `htex/viewer/` (문서 형식·로컬 파일 응답), `htex/web/common.py`·`build.py`·`server.py`(.md 문서), `htex/html/render.py`·`style.py`(strike, 번호 목록 모양), `schema/document-tree.schema.json`(`mode: markdown`, `strike`), `docs/spec.md`(9.1절), `README.md`, `tests/unit/test_M_*.py`, `notes/M-questions.md` | 실제 .md 파일이 스키마·일관성 검사를 통과, 뷰어에서 .md·.html 열기와 링크 따라가기, 기존 테스트 유지 |
