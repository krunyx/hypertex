# HyperTeX 2.0 기준 구현

HTML 대신 LaTeX 문법의 부분집합으로 쓰는 웹 문서 형식 HyperTeX 2.0의 파이썬 기준 구현이다.
명세는 `docs/spec.md`, 상호작용 규약은 `docs/interaction-protocol.md`.

## 설치

**앱** (GitHub 릴리스에서 내려받기. 태그 `v*`를 올리면 `.github/workflows/build.yml`이 만든다)

| OS | 파일 | 비고 |
| --- | --- | --- |
| macOS (Apple Silicon / Intel) | `HyperTeX-<버전>-macos-arm64.dmg` / `-x86_64.dmg` | 열어서 HyperTeX를 응용 프로그램 폴더로 끌기 |
| Windows 10/11 | `HyperTeX-Setup-<버전>.exe` | 관리자 권한 없이 설치. `.htex` 파일과 `htex://` 링크가 연결된다 |
| Linux | `HyperTeX-<버전>-x86_64.AppImage` | `chmod +x` 후 실행 |
| Linux | `HyperTeX-<버전>-linux-x86_64.tar.gz` | 풀고 `./install.sh` → `~/.local`에 설치, `.htex`·`htex://` 연결 (`--uninstall`로 제거) |

**파이썬 패키지** (저장소 폴더에서)

```bash
pip install .              # 파서·HTML 변환·웹 서버 (의존성 없음): htex html / serve / build
pip install ".[viewer]"    # + 전용 뷰어 (PySide6): htex view, htex-viewer
```

pip로 설치한 뷰어를 리눅스 데스크톱에 연결하려면 `packaging/linux/install.sh --pip`.
직접 빌드·서명·릴리스 방법은 `packaging/README.md`.

### 뷰어 단축키 (macOS는 Ctrl 대신 Cmd)

| 동작 | 키 |
| --- | --- |
| 새 탭 / 탭 닫기 / 탭 전환 | Ctrl+T / Ctrl+W / Ctrl+Tab, Ctrl+1…9 |
| 링크를 새 탭으로 | 가운데 클릭 또는 Ctrl+클릭 |
| 찾기 | Ctrl+F, 다음 Enter·F3, 이전 Shift+Enter |
| 확대 / 축소 / 원래 크기 | Ctrl+= / Ctrl+- / Ctrl+0 |
| 원본(.htex) 보기 | Ctrl+U |
| 뒤로 / 앞으로 / 새로고침 / 주소창 | Alt+← / Alt+→ / Ctrl+R / Ctrl+L |

테마(시스템·밝게·어둡게)는 보기 메뉴. 열어 둔 로컬 문서는 저장하면 자동으로 다시 그려진다.

## 빠른 시작

파이썬 3.10 이상. 파서·HTML 변환·웹 서버는 표준 라이브러리만 쓴다.

```bash
cd hypertex

# 문서 → HTML (브라우저로 열기)
python -m htex html examples/oscillator.htex -o oscillator.html

# 전용 뷰어 (PySide6 필요: python -m pip install PySide6)
python -m htex view examples/oscillator.htex

# 일반 브라우저용 서버 → http://127.0.0.1:8000/
python -m htex serve tests/docs

# 정적 웹사이트
python -m htex build tests/docs -o site

# 문서 트리(JSON) 보기
python -m htex parse examples/oscillator.htex
```

기존 `.tex` 파일은 확장자 그대로 열면 호환 모드로 읽는다 (명세 9절).

## 테스트

```bash
python -m pip install pytest jsonschema
python -m pytest -q tests/unit          # 단위 테스트 606건
python tools/run_all.py                 # 테스트 문서 28건 → out/, manifest 기대값 검사
python tools/compare.py                 # 파서 출력과 손으로 쓴 정답 트리 대조
```

## 구성

| 폴더 | 내용 |
| --- | --- |
| `htex/` | lexer, macros(매크로 확장), build_*(문서 트리), expr(계산식), picture(그림 검사) |
| `htex/html/` | 문서 트리 → HTML + MathML |
| `htex/tikz/` | TikZ·pgfplots 부분집합 → SVG |
| `htex/web/` | `serve`, `build`, 상호작용 스크립트 interact.js |
| `htex/viewer/` | PySide6 전용 뷰어 (`htex://` 주소, 히스토리, 미리보기, 슬라이더) |
| `docs/` | 명세 사본, 문서 트리 표현 규칙, 상호작용 규약 |
| `notes/` | 구현 담당별 질문과 임시 가정 |

---

# 문서 트리 스키마와 테스트 묶음

명세 초안(HyperTeX 2.0 명세 초안)의 8절 "기준 파서 → 문서 트리 → 여러 렌더러" 구조에서,
모든 구현이 공유하는 **계약**을 담은 묶음이다. 파서, HTML 변환기, 웹 폴백, 전용 뷰어를
누가(사람이든 에이전트든) 만들든 이 묶음을 통과하면 서로 맞물린다.

```
hypertex/
├── schema/document-tree.schema.json   문서 트리 JSON 스키마 (Draft 2020-12)
├── tests/
│   ├── manifest.json                  28개 사례의 목적, 명세 절, 기대 결과
│   ├── docs/                          테스트 입력 (.htex 26개 + 호환 모드 .tex 1개 + 보조 파일)
│   └── trees/                         손으로 쓴 정답 트리 예시 (01, 11)
└── tools/check.py                     검사기
```

## 문서 트리의 요점

- 파서는 **매크로 확장, 번호 매김, 라벨 해석을 끝낸 상태**로 트리를 낸다. 렌더러는 TeX를 다시 해석하지 않는다.
- 노드는 `kind`로 구분한다. 블록 17종(section, paragraph, displaymath, theorem, picture, …), 인라인 9종(text, math, link, footnote, …).
- 모든 노드는 문서 안에서 유일한 `id`(`n1`, `n2`, …)를 갖고, 최상위 `labels` 표가 라벨 → 노드 id·종류·번호를 잇는다. `htex://…#라벨` 주소는 이 표로 해석한다.
- 수식은 확장이 끝난 TeX 문자열(`math.tex`)과 쓰인 문자 체계(`scripts`, 한글이면 `hangul`)로 저장한다. MathML 변환은 렌더러 몫이다.
- TikZ·pgfplots 그림은 1.0에서 확장된 소스 문자열(`picture.source`)로 넘긴다. 그림 내부 구조 스키마는 다음 단계 과제다.
- 오류는 `diagnostics` 배열과, 해석하지 못한 자리의 `error` 노드로 동시에 남긴다(명세 7절).
- 주소에는 `javascript:`, `data:`, `file:`, `http:`가 들어갈 수 없다(스키마가 거부).

## 테스트가 가정하는 번호 규칙

명세에 아직 적히지 않은 기본값을 테스트가 아래처럼 고정했다. 다르게 하고 싶으면 manifest와 명세를 함께 고친다.

- 절: `1`, `1.1`, `1.1.1`. `\paragraph`와 별표 절은 번호 없음. 부록은 `A`, `A.1`.
- 식, 그림, 표, 각주: 각각 문서 전체 일련번호. `align`의 `\nonumber` 행은 번호를 쓰지 않는다.
- 정리류(definition, theorem, lemma, remark, `\newtheorem` 정의 환경)는 카운터 하나를 공유. proof는 번호 없음.
- 스타일 파일의 `equation.number = "(section.equation)"`이 있으면 식 번호가 `1.1`, `2.1` 꼴이 된다(사례 28).
- 호환 모드의 `\input{파일}`은 그 자리에 펼쳐 넣어 번호와 라벨이 한 문서로 이어진다(사례 27).
- 매개변수 이름이 그리스 문자 명령과 같아도 된다. 계산식과 `\showparam` 안에서만 매개변수로 해석한다(사례 25).

## 검사기 사용법

```bash
pip install jsonschema

# 트리 하나: 스키마 + 내부 일관성
python tools/check.py out/06-math-basic.tree.json

# 기대값까지
python tools/check.py out/06-math-basic.tree.json --case 06-math-basic

# 파서가 out/ 에 <id>.tree.json 들을 써 두었을 때 전체
python tools/check.py --all out/
```

검사 항목은 세 층이다.

1. **스키마**: 구조와 값의 형식. oneOf 실패는 가장 깊은 원인 위치를 보여준다.
2. **일관성**: 노드 id 중복, 없는 노드를 가리키는 라벨·진단, 선언되지 않은 매개변수 참조, 범위 밖 기본값.
3. **기대값**: manifest의 `count`, `labels`, `links`, `meta`, `parameters`, `diagnostics`(`exact` 또는 `atLeast`) 등.

현재 상태: 손으로 쓴 정답 트리 2개가 통과하고(`--all tests/trees`), 나머지 26개는 파서가 만들 차례다.

## 사례 목록

| 사례 | 명세 | 확인하는 것 |
| --- | --- | --- |
| 01–05 | 2, 3 | 최소 구조, 메타데이터, 절 번호, 텍스트 서식, 목록 |
| 06–07 | 3 | 수식 기본, 여러 줄 수식과 번호 |
| 08–10 | 3 | 정리 환경, 그림, 표 |
| 11–14 | 5 | 문서 안·문서 간 참조, 인용, 전사 |
| 15–18 | 4 | 매크로, 순환 거부, 확장 상한, 매크로 가져오기 |
| 19–20 | 7 | 오류 관용, 제외된 명령 차단 |
| 21–23 | 3.1 | TikZ, TikZ 제한, pgfplots |
| 24–25 | 3.2 | 접기·단계, 매개변수 슬라이더와 계산식 |
| 26 | 8 | 한글 줄바꿈과 한글 수식 |
| 27 | 9 | 기존 LaTeX 호환 모드 |
| 28 | 6 | 스타일 파일 |
