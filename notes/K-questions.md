# K (4단계: 실제 원고 호환) — 정한 것과 확인이 필요한 것

시험 말뭉치: `tools/realworld.py` (LaTeX 기본 예제 2건, amsmath testmath, pandoc LaTeX 시험 파일,
HoTT 책 2장, Stacks Project 2장). 원고는 저장소에 넣지 않고 `.cache/realworld/`에 받는다.

## 측정 (2026-10-15)

| 문서 | 오류 진단 (전 → 후) | 수식이 원문으로 남은 비율 (전 → 후) |
| --- | --- | --- |
| amsmath testmath | 736 → 12 | 19% → 0.3% |
| HoTT 책 (basics, logic) | 7,993 → 61 | 38% → 0.3% |
| Stacks: sets | 237 → 0 | 7% → 0% |
| Stacks: categories | 1,881 → 4 | 10% → 0% |
| pandoc latex-reader | 43 → 11 | 0% → 0% |

모든 문서가 예외 없이 2초 안에 처리된다 (가장 큰 것 2MB HTML).

## 1. 결정 (2026-10-15 사용자 확정: 네 항목 모두 아래대로)

### 1.1 compat 모드에서 매크로 순환 검사를 하지 않는다
- 명세 4절은 순환하는 정의를 거부한다 (사례 16). 그런데 실제 원고는 `\@ifnextchar`로 보호된 재귀
  (`\prd` → `\prd@parens` → `\prd@parens` …)와 비교 대상으로서의 자기 이름(`\@ifnextchar\prd`)을 흔히 쓴다.
  HoTT 책의 `\prd`, `\sm`(240여 곳)이 이 때문에 모두 정의되지 않았다.
- 정한 것: **compat(.tex)에서만** 순환 검사를 생략한다. 무한 확장은 기존 확장 상한(10만 회, 1만 토큰)이
  막고 expansion-limit 진단이 난다. native(.htex)는 그대로 거부한다.
- 확정: 명세 4절·9절에 반영했다.

### 1.2 화면과 무관한 패키지 경고
- 명세 9절: 기본 5개 외의 `\usepackage`는 "무시하고 경고". 사례 27이 `inputenc`, `geometry`에 경고를 기대한다.
- 처음 안: 지원 기능의 패키지만 조용히 받고 글꼴·여백 패키지는 명세대로 경고.
- 확정: 조판 패키지도 조용히 무시한다. `COMPAT_QUIET_PACKAGES`를 넓히고 명세 9절, 사례 27의 manifest 기대값과
  정답 트리(`unknown-package` 2건 삭제)를 함께 고쳤다. 모르는 패키지는 여전히 경고한다.

### 1.3 `\cref` 의 표시 이름은 영어
- cleveref 기본값을 따라 `\cref` → "theorem 2.1", "eq. (1)", "section 3", `\Cref`·`\autoref` → "Theorem 2.1",
  "Equation (1)", "Section 3". 정리류는 `\newtheorem`의 이름을 쓴다.
- 라벨 표의 `display`("식 (1)", "1절")는 한국어라 다르다. 원고가 영어인 경우가 대부분이라 영어로 했다.
  확정: 영어로 간다 (명세 9절).

### 1.4 `\chapter` 가 있는 책
- 스키마의 절은 4단계(section~paragraph)뿐이다. `\chapter`가 하나라도 있으면 chapter→section,
  section→subsection, subsection→subsubsection, subsubsection→paragraph 로 한 단계씩 내린다.
  `\part`는 번호 없는 최상위 절로. 식·그림 번호는 지금처럼 문서 전체 일련번호. 확정 (명세 9절).

## 2. 바꾼 기존 동작 (테스트도 고침)

- **수식 안의 모르는 명령**: 수식 전체를 원문 코드로 바꾸던 것을, 그 명령 자리만 빨간 `<merror class="htex-unknown">`
  으로 표시하고 나머지를 그리게 했다 (2026-10-14 결정 "모르는 명령은 건너뛰고 멈추지 않는다"와 맞춤).
  `\text{…}` 안의 모르는 명령은 이름만 버린다. 바뀐 테스트: `test_E_mathml.test_errors_fall_back_to_code`의
  두 입력, `test_E_render.test_render_reference_trees`의 16번 기대값.
- **인수 있는 `\def`** (compat): 제외하던 것을 매크로로 바꾼다. 구분자 있는 인수(`\def\a[#1]#2.{…}`)도 TeX처럼
  맞춘다. 매개변수 번호가 차례대로가 아닐 때만 제외. 바뀐 테스트: `test_B_macros.test_compat_def_with_args_is_excluded`.
- **수식 명령 목록 일원화**: `commands.MATH`가 MathML 변환기의 표(`mathml.HANDLED_COMMANDS`)를 끌어온다.
  변환기가 그리는 기호(`\centerdot`, `\amalg` …)를 빌더가 "정의되지 않음"으로 진단하던 불일치를 없앴다.
  `htex.commands`가 `htex.html.mathml`을 가져오지만 mathml은 표준 라이브러리만 쓰므로 순환은 없다.
  본문에서도 뜻이 있는 명령(`\rm`, `\mbox`, `\index` …)은 `TEXTLIKE_COMMANDS`로 따로 두어, 본문에서
  인라인 수식으로 바뀌지 않게 했다.
- **중괄호 안의 `$`**: `$x \raisebox{1ex}{$\cdot$} y$`, `$\text{a $b$ c}$`의 안쪽 `$`를 바깥 수식의 끝으로
  보지 않는다 (TeX와 같다). 깊이 0의 `$`가 단락 안에 없으면(중괄호가 안 닫힌 수식) 예전처럼 첫 `$`에서 닫는다
  (사례 19 유지). native에도 적용된다.

## 3. 새로 지원 (모두 compat 전용, 수식 쪽은 native에서도)

- 매크로 층 (`macros.py`): 버리는 명령 표 `COMPAT_SKIP`(인수 서명으로 소비), `\let`, `\gdef`·`\edef`·`\xdef`(=`\def`로 근사),
  `\providecommand`, `\DeclareRobustCommand`, `\newenvironment`, `comment` 환경, `\@ifnextchar`, `\@ifstar`,
  `\@gobble` 류, `\bgroup`·`\egroup`, `\iffalse`·`\iftrue`·`\if`·`\ifx`·`\ifdefined`·`\else`·`\fi`, `\detokenize`, `\chardef`.
- 렉서: `\makeatletter` … `\makeatother` 사이에서 `@`를 제어어 글자로.
- 빌더 (`build_compat.py`): 옛 글꼴 전환(`{\bf …}`의 범위), `\cref` 류, 글자 악센트(`\c{c}`, `\v{s}`, `\H{o}`),
  본문 기호(`\ss`, `\o`, `\textgreater` …), `\textsuperscript`, `\ensuremath`, 내용만 남기는 상자·색 명령,
  `\chapter`, `\begin{math}`, 레이아웃 환경(multicols, spacing …), TeX 따옴표 합자(``` `` ''```).
- 수식 (`mathml.py`): `\mathop`·`\mathbin`·`\mathrel`·`\mathord`·`\mathopen`·`\mathclose`·`\mathpunct`·`\mathinner`,
  `\ensuremath`, `\mathchoice`, 옛 글꼴 전환(`\rm` 등, 그룹 범위), 중위 분수(`\over`, `\choose`, `\atop`, `\above`),
  `\genfrac`, `\kern`·`\mkern`·`\hskip`, `\raisebox`·`\fbox` 류, 대문자 악센트, 기호 약 150개, `\hdotsfor`,
  `\xmapsto` 류, `\cancel`, `\sideset`, `\leftroot`·`\uproot`, `\pod`.
- 가환 그림 (`html/cd.py`): `\xymatrix`(xy-pic, 2-셀 포함), `tikzcd`, amscd `CD`. 대상은 짝수 칸, 화살표는 사이 칸.
  화살표 모양(갈고리, 두 촉, 점선, 겹선, 등호, mapsto), 라벨 위치(방향의 왼쪽이 기본, `_`·`'`로 반대쪽).
  여러 칸을 건너는 화살표는 첫 사이 칸에 그리고, 휘어짐·이동은 무시한다 (근사).

## 4. 남은 것 (다음 후보)

- `\if` 계열 가운데 `\ifnum`, `\ifdim`, `\ifcase`, `\ifcsname` (지금은 거짓으로 보거나 정의되지 않음).
- `\begin{xy}` 일반 xy-pic 문법 (`\xymatrix`만 지원).
- 여러 칸을 건너는 가환 그림 화살표를 실제 길이로 (MathML 표의 칸 합치기 또는 SVG).
- `lstlisting`, `minted`, `Verbatim` 같은 코드 목록 환경 (렉서가 verbatim만 안다).
- 장(chapter)마다 식 번호를 다시 매기는 책 형식 번호 (`1.1`, `2.1`).
- arXiv 원고로 시험 넓히기: 이 작업 환경에서는 arXiv에 접근할 수 없었다.
