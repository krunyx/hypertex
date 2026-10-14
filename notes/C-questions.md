# C (트리 빌더) — 정한 것과 질문

형식: **상황 / 정한 표현 / 이유**. 명세·스키마·manifest·테스트 문서 자체의 문제는 뒤쪽 "문제 보고"에 따로 적었다.

## 1. tree-conventions가 정하지 않은 표현

### 1.1 라벨 표의 `display`
- 상황: 스키마상 선택 필드인데 정답 트리 11은 `"1절"`, `"식 (1)"`을 넣었다.
- 정한 표현: 번호가 있으면 항상 넣는다. 절 `"{n}절"`, 식 `"식 ({n})"`, 그림 `"그림 {n}"`, 표 `"표 {n}"`,
  항목 `"항목 {n}"`, 각주 `"각주 {n}"`, 단계 `"단계 {n}"`, 정리류 `"{표시 이름} {n}"`(예: `"보조정리 3"`, `"추측 4"`).
  번호가 없는 대상(별표 절, itemize 항목, 번호 없는 \newtheorem*)은 `number`와 `display`를 모두 생략.
- 이유: 정답 트리 11과 맞추고, 나머지는 같은 꼴로 확장. **A와 맞춰야 한다** (A에게 확인 요청).

### 1.2 노드 id에 빈틈이 생길 때
- 상황: 단락은 글자가 처음 나올 때 열고 id를 받는데, 결국 비어서 지워지는 경우가 있다 (예: 단락이 `\label`만 있음).
- 정한 표현: 트리를 다 만든 뒤 남은 노드만 문서 순서대로 `n1…`로 다시 매긴다 (라벨 표도 함께 고친다).
- 이유: tree-conventions "문서 순서로 n1, n2, …"는 빈틈 없는 번호로 읽었다.

### 1.3 전문의 `\abstract{…}` 노드 id
- 상황: meta.abstract의 블록도 id가 필요하다. 문서 순서상 전문이 본문보다 앞이다.
- 정한 표현: 원문 순서대로 매긴다. 사례 02에서 초록 단락이 `n1`, 본문 단락이 `n2`.
  호환 모드의 `abstract` 환경도 그 자리(원문 순서)에서 id를 받는다.
- 이유: "노드를 처음 여는 순서" 규칙을 그대로 적용. A와 맞춰야 할 지점.

### 1.4 `\paragraph`의 번호와 중첩
- 정한 표현: level 4, `number` 없음. 다음의 같은 수준 이상 절(`\paragraph`, `\subsubsection`, …)이 나오면 닫힌다.
  `\paragraph` 뒤의 텍스트는 그 section의 첫 paragraph.

### 1.5 별표 절과 부록
- 정한 표현: `\section*`는 번호를 쓰지도 올리지도 않는다. `\appendix` 뒤의 `\section*`에도 `"appendix": true`.
  부록 번호는 A, B, …, Z, AA. `\appendix`를 두 번 써도 두 번째는 무시.

### 1.6 단락 안 공백
- 정한 표현: `\\`(linebreak) 바로 앞뒤의 공백은 지운다 (`"강제 줄바꿈은"`, linebreak, `"여기서 일어난다."`).
  인라인 안(styled 등)의 앞뒤 공백은 그대로 두고, 단락·제목·캡션·항목 용어 등 인라인 목록 전체의 앞뒤만 자른다.
- 이유: LaTeX에서 `\\` 뒤 공백은 줄 첫머리에서 사라진다. 사례 04의 `강제 줄바꿈은\\ 여기서`.

### 1.7 math.tex의 공백
- 상황: lexer는 제어어 뒤 공백을 먹으므로 `tokens.detokenize`로는 `\Psi = \hat{H}`가 `\Psi= \hat{H}`가 된다.
  정답 트리 11의 `m\omega^2 x^2`, `\hbar\omega\left(` 처럼 원문 공백을 살려야 공백 정규화 비교가 맞는다.
- 정한 표현: `build_math.detok`이 토큰 위치(span)로 원문에 공백이 있었는지 보고 하나를 되살린다.
  다음 토큰이 ASCII 글자면 항상 공백 하나 (detokenize와 같다).
- 이유: tree-conventions의 비교 규칙은 "공백 연속을 하나로"이지 "공백을 모두 무시"가 아니다.
- **B에게**: 매크로 확장 결과 토큰은 가능하면 정의 본문 토큰의 span을 그대로 두기를 바란다
  (그래야 확장된 `\left| #1 \right\rangle` 의 공백이 원문대로 나온다). 모든 토큰에 호출 위치 span을 붙이면
  제어어 뒤 공백이 사라질 수 있다. 공백 차이만 생길 뿐 구조는 같다.

### 1.8 math.scripts
- 정한 표현: `\begin{…}`/`\end{…}`의 환경 이름, `\label`/`\tag`의 인수, `array`의 열 지정 글자는 세지 않는다.
  scripts가 비면(예: `$\sum$`, `$1+1$`) 필드를 생략. 그리스 문자 목록은 `commands.GREEK`(=_GREEK).
- 이유: `\begin{cases}`의 c-a-s-e-s가 latin으로 잡히면 안 된다.

### 1.9 수식 안의 `\showparam`
- 정한 표현: `$\omega = \showparam{\omega}$` → `math("\omega =")`, `showparam(omega)` 인라인 둘로 나눈다
  (최상위에 있을 때만. 중괄호 안이면 tex에 남기고 `math.params`에 이름을 적는다).
  선언되지 않은 이름이면 그 자리는 inline error(unknown-parameter, raw `\showparam{\kappa}`).
  분리 결과 수식이 비면 math 노드는 만들지 않는다 (`$\showparam{\k}$` → showparam 하나).
- 이유: 스키마상 showparam은 인라인 노드이고 MathSource에는 넣을 자리가 없다. 사례 25의 count showparam 2.
  **A와 맞춰야 할 지점.**

### 1.10 수식 구문 검사 범위
- 정한 표현: 중괄호 짝, `\left`/`\right` 짝, 수식 안 `\begin`/`\end` 짝, 인수가 필요한 명령(`\frac`, `\sqrt`, `\text` …)의
  인수 유무, `^`/`_` 뒤 대상 유무. 이 밖의 것은 렌더러가 판단.
  `$`가 단락 끝까지 닫히지 않으면 math-syntax + inline error (raw는 `$`부터 단락 끝까지).
  디스플레이 수식의 구문 오류는 error **블록**(code math-syntax, raw는 begin/end 포함 원문).
- 이유: 사례 19의 `$\frac{1}{$`. 디스플레이는 블록 자리이므로 error 블록.

### 1.11 수식 안의 정의되지 않은 명령
- 정한 표현: 내장 목록(commands.BUILTIN)에 없는 제어어가 수식에 있으면 undefined-command 진단을 내되
  수식은 그대로 둔다 (math 노드, tex에 그 명령이 남는다). 사례 16의 `$\loopA$`.
- 이유: 수식 전체를 오류로 바꾸면 사례 16의 기대(정확히 undefined-command 2개, math-syntax 0개)에 어긋난다.
- 결과적으로 **B가 매크로를 남기면 C가 undefined-command를 낸다**. B는 사례 16에서 거부된 매크로 참조를 지우지
  말고 남겨 두어야 C가 undefined-command 2개를 낸다 (B의 docstring은 "거부된 이름은 정의되지 않은 상태로 남는다"까지만
  말한다. B가 따로 undefined-command를 내면 4개가 되어 실패하니 **B는 내지 말 것**).

### 1.12 정의되지 않은 명령의 인수
- 정한 표현: 바로 뒤에 붙은 `{…}`와 `[…]`를 모두 인수로 보고 children에 차례로 이어 붙인다.
  인수가 없으면 children 생략.

### 1.13 블록 환경이 인라인 자리에 올 때
- 상황: `\textbf{… \begin{itemize}…}`, `\caption{\[x\]}`처럼 인라인만 허용되는 자리의 블록 환경.
- 정한 표현: 블록을 만든 뒤 인라인으로 펼친다 (displaymath → math, verbatim → code, 목록 → 내용 텍스트…).
  진단은 내지 않는다.

### 1.14 figure 밖의 `\caption`, 환경 밖의 `\item`·`\step`·`\bibitem`
- 정한 표현: `\caption{x}`는 그 자리의 인라인으로. `\item`·`\step`은 명령만 버리고 내용은 계속.

### 1.15 알 수 없는 환경
- 정한 표현: `center`, `flushleft`, `minipage` 같은 배치 환경과 commands.ENVIRONMENTS에 있는 환경은 진단 없이
  투명(내용만 그 자리에). 그 밖의 환경은 undefined-command 진단 + 투명.

### 1.16 짝이 없는 `\end{x}`와 `}`
- 정한 표현: 짝 없는 `\end{x}`는 unclosed-environment(같은 계열로 봄) 진단 후 버림. 짝 없는 `}`는 unbalanced-brace 후 버림.
  단, `\end{document}`는 진단 없이 해석을 끝낸다 (뒤의 내용은 무시).

### 1.17 닫히지 않은 환경
- 정한 표현: 다음 `\section`/`\subsection`/`\subsubsection`, `\end{document}`, 바깥 환경의 `\end`, 문서 끝에서 닫고
  unclosed-environment 하나. `\paragraph`는 환경을 닫지 않는다 (목록 안 `\paragraph` 허용).
  수식 환경과 tikzpicture는 원문을 모으므로 같은 지점에서 닫는다.

### 1.18 짝 안 맞는 `{`
- 정한 표현: 명령 인수의 `{`가 단락 끝(PAR)까지 닫히지 않으면 거기서 닫고 unbalanced-brace 하나.
  안쪽에 다시 짝 없는 `{`가 있어도 한 번만 보고. 맨 `{`(그룹)는 단락 끝에서 조용히 닫다가 하나 남아 있으면 하나 보고.
  `\footnote`, `\abstract`, 각주처럼 블록을 담는 인수는 단락을 넘을 수 있고 다음 절·문서 끝에서 닫는다.

### 1.19 표
- `\hline`은 다음 행의 ruleAbove, 마지막 빈 행 앞의 `\hline`은 마지막 행의 ruleBelow (tree-conventions 그대로).
- `\multicolumn{n}{|c|}{…}` → `{colspan: n, align: "c", content}`. 셀 열 지정의 세로선은 기록하지 않는다
  (스키마에 셀 단위 세로선 필드가 없다).
- `p{…}`, `m{…}`, `b{…}`, `X` 열은 align "l". `@{…}`, `>{…}` 는 무시. `*{3}{c}`는 펼친다(최대 100).
- 세로선은 그 앞 열의 ruleRight가 아니라 다음 열의 ruleLeft로 붙이고, 마지막 열 뒤에서만 ruleRight
  (tree-conventions 예시와 같다). `||`는 하나로 본다.

### 1.20 그림·이미지
- `\includegraphics`의 width: `0.6\textwidth`/`\linewidth`/`\columnwidth` → `"60%"`, 그 밖의 값(예 `5cm`)은 문자열 그대로.
  `alt=…` 옵션이 있으면 alt. 주소가 비면 missing-resource 진단, 노드 없음.
- 인라인 자리의 image(단락 안 `\includegraphics`)도 블록 image로 단락을 끊는다 (다른 블록 환경과 같은 규칙).
- picture.source는 tree-conventions대로 원문을 앞뒤 공백만 자르되, 줄바꿈은 살린다 (줄 앞 들여쓰기는 lexer가 없앤다).
  비교 시 공백 정규화를 하므로 상관없다.
- picture의 params는 check_picture가 돌려준 이름 중 선언된 것만 (일관성 검사 통과용).

### 1.21 참고문헌
- `thebibliography`의 `{9}` 인수는 무시. `\bibitem[표시]{키}`의 표시는 무시하고 번호는 순서대로.
- identifier: 본문에서 처음 나오는 `doi:…` 또는 `arXiv:…` (끝의 마침표 제거). isbn은 찾지 않는다.
- 같은 키가 두 번 나오면 첫 것만.
- `\bibliography{refs}`: bibliography 블록 하나 + `refs.bbl`을 loader로 읽어 그 안의 thebibliography를 항목으로.
  파일이 없으면 loader의 missing-resource (사례 27의 missing-resource 1).
- bibitem 본문의 `\label`은 등록하지 않는다.

### 1.22 `\cite`
- `\cite[p.~3]{k}`의 선택 인수는 버린다 (스키마에 자리가 없다).
- 외부 식별자 판정은 대소문자 무시 (`arxiv:`도 외부).
- 외부 식별자와 BibTeX 키가 섞이면 BibTeX 키만 해석: 모두 있으면 `resolved.numbers`는 **BibTeX 키의 번호만**.
  (스키마 numbers가 keys와 같은 길이여야 한다는 말은 없다. A와 맞춰야 할 지점.)

### 1.23 링크 주소 검사
- `\ref{doc#label}`의 doc이 금지 주소면 inline error(insecure-resource) + 진단, 링크를 만들지 않는다.
- `\href`의 금지 주소: inline error(insecure-resource, raw `\href{url}{텍스트}`), children에 표시 텍스트.
- `\url`의 금지 주소: inline error, children 없음.
- `\transclude`의 금지 주소: error **블록**.
- `\ref{#label}`(doc이 빈 것)은 같은 문서 참조로 본다.

### 1.24 라벨 이름
- 스키마 LabelName 패턴 `^[A-Za-z0-9가-힣:._-]+$` 밖의 글자(공백, `/` 등)는 `_`로 바꾼다. 빈 라벨은 등록하지 않는다.
- 같은 라벨 두 번: duplicate-label, 첫 것 유지.
- `\label`이 붙을 대상은 LaTeX의 \@currentlabel처럼 "가장 최근에 연 번호 대상" (절, 정리, float, 항목, 단계, 각주).
  한 노드에 라벨이 여럿이면 노드의 `label` 필드는 첫 것, 라벨 표에는 모두.

### 1.25 매개변수
- `\parameter`는 전문·본문 어디서나. 숫자가 아닌 값, min > max, step ≤ 0 → expression-syntax 진단, 선언하지 않는다
  (기본값만 범위 밖이면 범위 안으로 잘라 선언하고 expression-syntax).
- `\showparam`은 문서 어디서든 선언 위치와 상관없이 해석 (전문을 먼저 훑는다).
- 같은 이름 두 번 선언: 첫 것만.

### 1.26 메타
- `\author{A \and B}` → 저자 둘.
- `\keywords`를 여러 번 쓰면 이어 붙인다. 빈 키워드는 버린다.
- `\usemath{x}`에서 hangulmath가 아닌 것: unknown-package 경고 (스키마 enum 밖이라 넣을 수 없다).
- `\usestyle`: 허용 주소면 meta.styles에 넣고, 상대 주소면 읽어 `*.number` 키를 반영. 읽기 실패(missing-resource)여도
  주소는 meta.styles에 남긴다. 절대 주소(https, htex)는 읽지 않는다 (loader 정책).
- equation.number 등 번호 형식: `"(section.equation)"` → 바깥 괄호는 표시용으로 보고 떼어 `section.equation`.
  `section`은 현재 절 번호(부록이면 A), 대상 카운터는 그 상위 카운터가 바뀔 때 0으로 돌아간다.
  figure.number, table.number, footnote.number, theorem.number도 같은 방식으로 받는다.
- 호환 모드 `\usepackage`: amsmath, amssymb, amsthm, amsfonts, hyperref, graphicx, graphics, tikz, pgfplots, mathtools,
  kotex, url, xcolor, color, bm은 조용히 무시, 그 밖의 것은 패키지마다 unknown-package 하나.
  **native 모드의 \usepackage도 같은 규칙**으로 처리했다 (명세에 native 규칙이 없다).

### 1.27 정의 명령
- `\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareMathOperator(*)`, `\def`는 인수만 소비하고 진단 없음
  (B가 처리한 뒤엔 오지 않는다). `\newtheorem`은 C가 처리 (`\newtheorem*`는 번호 없음).

### 1.28 내부 한도
- 중첩 상한 16단계(인수 안 인수, 환경 안 환경). 넘으면 안쪽은 원문 텍스트로 두고 render-timeout 진단 하나.
  - 이유: 파이썬 재귀 한도 안에서 끝나야 하고, 또 tools/check.py(jsonschema)의 oneOf 검증이 깊이에 지수적으로
    느려진다 (중첩 36단계 트리 하나 검증에 수십 초). 보통 문서는 5단계를 넘지 않는다.
  - 진단 코드는 마땅한 것이 없어 render-timeout을 썼다 (아래 문제 보고 3).
- 최후 방어선: 빌더 내부 예외가 나도 빈 본문 트리 + render-timeout 진단을 낸다 (시험에서는 한 번도 나지 않았다).

## 2. 다른 담당에게 기대하는 인터페이스 동작 (docstring에 없던 것)

### B (lexer·macros)
1. 확장된 토큰은 정의 본문 토큰의 span을 유지 (1.7).
2. 거부된 매크로·정의되지 않은 매크로의 사용(`\loopA`)은 CS 토큰 그대로 남기고 **undefined-command는 내지 않는다**.
   C가 수식·본문에서 낸다 (1.11). 사례 17의 expansion-limit 호출 자리는 docstring대로 아무것도 남기지 않음.
3. `\usemacros{…}` 명령은 출력에 남기고, 금지·없는 주소의 진단(insecure-resource, missing-resource)은 B가 낸다.
   C는 meta.macroImports 기록만 하고 진단은 내지 않는다.
4. `\usepackage`, `\usetikzlibrary`, `\usestyle`, `\newtheorem`, `\parameter`는 건드리지 않고 남긴다 (C가 처리·진단).
5. `\bibliography{…}`, `\bibliographystyle`도 남겨도 된다 (C가 각각 처리, 무시). compat 모드에서 B가 `\bibliographystyle`을
   지워도 상관없다.
6. 매개변수 이름과 같은 그리스 문자(`\omega`)는 확장하지 않는다 (docstring에 있음. C는 `\showparam{\omega}` 안의 CS 하나를 이름으로 읽는다).
7. 제외 명령(EXCLUDED)이 B를 통과해 오면 C는 이름과 뒤의 `{…}` 인수들만 조용히 버린다 (진단은 B 몫).
   `\catcode`\@=11` 같은 비중괄호 인수는 B가 함께 소비해야 본문에 찌꺼기 글자가 남지 않는다 (지금 stub에서는 `` `=11 ``이 남는다).
8. verbatim 환경은 lexer가 VERBATIM 토큰 하나로 낸다 (지금처럼). 확장 결과에 `\begin{verbatim}`이 CS로 오면 C가 원문으로 모은다.

### D (picture·expr)
1. `check_picture`의 `params` 인자에는 **그 시점까지 선언된** 매개변수 이름 집합을 넘긴다
   (C는 전문을 먼저 훑지 않고 \parameter 처리 순서를 따른다. 그림보다 뒤에서 선언된 이름은 미선언).
2. `PictureInfo.params`에 선언되지 않은 이름이 있으면 C가 걸러 낸다 (일관성 검사). 미선언 이름의 진단은 D가 낸다.
3. 그림 안 `\showparam`은 C가 따로 보지 않는다. D가 그림 원문에서 처리.
4. `\usetikzlibrary` 진단(unknown-tikz-library)은 C가 낸다 (docstring 그대로). D는 내지 않기.
5. check_picture가 예외를 던져도 C는 picture 노드(usesPgfplots 없이)를 내고 계속한다. 다만 진단은 남지 않으니 예외는 피해 주기를.
6. source는 앞뒤 공백을 자르고 원래 줄바꿈을 살린 문자열이다 (줄 앞 들여쓰기는 lexer 단계에서 사라진다).
   `%` 주석은 lexer가 이미 지웠다.

## 3. 문제 보고 (명세·스키마·manifest·테스트)

1. **스키마 Footnote에 `label` 필드가 없다**: `\footnote{…\label{fn:a}}`는 라벨 표에는 등록되지만(kind footnote)
   노드 자체에는 label을 적을 수 없다. 제안: Footnote에 `label` 추가. 임시: 라벨 표에만 둔다.
2. **스키마 Image·Picture는 블록뿐**: 단락 중간의 `\includegraphics`(사례 09 마지막 줄의 허용 주소 판)는
   단락을 끊을 수밖에 없다. 제안: 인라인 image 추가 또는 규칙으로 명시. 임시: 단락을 끊는다.
3. **중첩 상한·내부 한도의 진단 코드가 없다**: 임시로 render-timeout. 제안: `nesting-limit` 같은 코드 추가 또는 render-timeout으로 명시.
4. **tools/check.py의 스키마 검사가 깊은 트리에서 지수적으로 느리다** (Block·Inline의 oneOf). 30단계 중첩 트리 하나에
   수십 초. 제안: kind별 if/then 또는 discriminator 방식으로 스키마를 바꾸면 선형. 임시: 빌더 중첩 상한 16.
5. **사례 25의 `$\showparam{\kappa}$`**: tree-conventions는 "\showparam{\k}: 선언된 이름이면 showparam 노드, 아니면 inline error"라
   하지만 수식 안에 있을 때 math 노드를 어떻게 나누는지는 말하지 않는다. 임시: 1.9.
6. **README 번호 규칙 "각주: 문서 전체 일련번호"**와 스타일의 footnote.number: 정의된 키 목록이 명세 6절에 없다.
   임시: `<카운터>.number`를 equation·figure·table·footnote·theorem에 대해 받는다.
7. **명세 9절 `\usepackage` 목록**: native 모드에서의 처리가 없다. 임시: 호환 모드와 같은 규칙 (1.26).
8. **manifest 27**: `\bibliography{refs}`의 refs.bbl이 tests/docs에 없어 missing-resource 1을 기대하는 것으로 읽었다.
   의도라면 문제없다. bibliography 블록은 항목 없이 남는다.
9. **스키마 Section.level 4(`\paragraph`)에 number 금지 규칙이 스키마에 없다**: README에는 "번호 없음". 문제는 아니고 확인용.
