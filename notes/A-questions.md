# A(정답 트리) 질문·결정 기록

tree-conventions.md가 정하지 않은 상황에서 정답 트리에 쓴 표현, 그리고 명세·스키마·manifest·테스트 문서의 문제를 적는다.
형식: **상황 / 내가 정한 표현 / 이유**.

## 1. tree-conventions에 없어서 A가 정한 표현

### 1.1 라벨 표의 `display` 문자열 (전 사례)
- 상황: LabelTarget.display는 선택 필드이고 형식 규칙이 없다. 대조할 때 무시 목록에도 없다.
- 표현: 예시 트리 11번을 따라 절 `"1절"`, 부록 절 `"부록 A"`·`"부록 A.1"`, 식 `"식 (1)"`, 정리류 `"<theorem.name> <번호>"`(예: `"정의 1"`, `"추측 4"`, 27번 `"Theorem 1"`),
  그림 `"그림 1"`, 표 `"표 1"`, 항목 `"항목 1"`, 단계 `"단계 3"`으로 넣었다.
- 이유: 11번 예시와 맞춤. **제안**: display를 대조 무시 목록에 넣거나 형식을 tree-conventions에 적어 달라. 지금은 C와 어긋나기 쉽다.

### 1.2 메타의 초록(abstract) 안 노드 id 순서 (02, 27)
- 상황: meta.abstract의 블록도 id를 받는데, 본문과의 순서 규칙이 없다.
- 표현: 초록 블록이 먼저 `n1…`을 받고 본문이 이어서 받는다.
- 이유: 두 사례 모두 초록이 문서 순서상 본문 블록보다 앞에 있다(02는 전문의 `\abstract{}`, 27은 `\maketitle` 바로 뒤 abstract 환경).

### 1.3 빈 선택 필드 생략
- 상황: meta.tikzLibraries·styles 등이 비어 있을 때(22: 허용 안 된 라이브러리만 있음) 빈 배열인지 생략인지.
- 표현: 생략. 단, 필수 최상위 필드(labels, parameters, bibliography, diagnostics)는 빈 값으로 둔다.
- 이유: link children 생략 규칙과 같은 방향.

### 1.4 `math.scripts`가 빈 경우 (18)
- 상황: `\left| 0 \right\rangle`(`\ket{0}` 확장)에는 latin·greek·hangul이 하나도 없다.
- 표현: `"scripts": []`.
- 이유: 다른 수식처럼 필드를 항상 두는 편이 대조가 쉽다. 생략으로 정해도 상관없음.

### 1.5 `\\` 뒤 공백 (04)
- 상황: `강제 줄바꿈은\\ 여기서` 에서 linebreak 다음 공백 처리.
- 표현: `"강제 줄바꿈은"`, linebreak, `"여기서 일어난다. …"` (뒤 공백 버림).
- 이유: LaTeX에서도 `\\` 뒤 공백은 출력되지 않는다. 줄 맨 앞 공백은 의미가 없다.

### 1.6 verbatim 블록 앞뒤 줄바꿈 (04)
- 상황: "text는 원문 그대로"인데 `\begin{verbatim}` 바로 뒤와 `\end{verbatim}` 바로 앞의 줄바꿈 포함 여부.
- 표현: 둘 다 뺀다. 내부 줄바꿈·들여쓰기·연속 공백은 그대로 (`"\\section{…}\n  들여쓰기도   그대로"`).
- 이유: LaTeX verbatim 출력과 같다.

### 1.7 description 항목의 number, itemize 항목의 number (05)
- 표현: enumerate 항목만 `number`("1","2","3"). itemize·description 항목은 number 없음. description은 `term`.
- 중첩 목록은 해당 항목 children에서 paragraph 다음 블록.

### 1.8 `\multicolumn`의 세로선 (10)
- 상황: `\multicolumn{3}{|c|}{렙톤}` 의 `|c|` 세로선을 셀에 담을 필드가 스키마에 없다.
- 표현: `{"colspan": 3, "align": "c", "content": […]}` 만. 세로선 정보는 버림.
- 이유: 스키마 Cell에 rule 필드 없음. 이 표에서는 열 지정의 세로선과 같아 손실이 보이지 않는다. (아래 2.6 참조)

### 1.9 허용되지 않는 `\href` (12)
- 상황: tree-conventions는 `\includegraphics`의 허용 안 된 주소만 정했다. `\href{javascript:…}{위험}` 은?
- 표현: link를 만들지 않고 inline error `{code: insecure-resource, raw: "\\href{javascript:alert(1)}{위험}", children: [text "위험"]}` + insecure-resource 진단 1개.
- 이유: includegraphics 규칙과 맞추고, 표시 텍스트는 undefined-command처럼 children으로 남겨 읽을 수 있게 했다.

### 1.10 thebibliography 처리 (13)
- 표현: bibliography 블록에 title 없음. bibitem text는 본문 전체(식별자 문자열 `doi:…` 포함)를 text 하나로. identifier는 `{scheme: "doi", value: "10.1103/PhysRev.47.777"}` (url 생략).
  `\cite{epr1935}` → resolved `{numbers: ["1"]}` (node 없음).
- 이유: 식별자를 본문에서 지우면 원문 정보가 빠진다. bibitem에는 노드 id가 없어 node를 넣을 수 없다.

### 1.11 수식 안의 미정의 명령 (16)
- 상황: `$\loopA$`, `$\self$` — 정의가 거부되어 미정의가 된 명령이 수식 안에서 쓰였다. 규칙은 본문용(`\foo{인수}`)만 있다.
- 표현: math 노드를 만들지 않고 그 자리에 inline error `{code: undefined-command, raw: "\\loopA"}` (children 없음, 인수가 없으므로). `\self`도 같다.
- 이유: 수식 전체가 미정의 명령 하나뿐이라 math 노드로 남길 내용이 없다. **대안**: math 노드(tex `"\\loopA"`)를 유지하고 진단만 남기는 방식도 가능 — C와 맞춰야 한다.

### 1.12 확장 상한 초과 지점 (17)
- 상황: `\xe{}`, `\xf{}` 확장 상한 초과 시 트리에 무엇을 남기는가.
- 표현: htex/macros.py 계약("아무것도 남기지 않는다")을 따라 **노드 없음**, 진단만 2개. 남은 `{}`는 빈 그룹, 그 뒤 공백은 단락 앞 공백이라 지워진다 → 단락은 `"는 토큰 20,000개로 …"`.
- 진단 개수: 정확히 expansion-limit 2개 (`\xe`, `\xf` 각 1). `\xb`·`\xc`·`\xd` 는 정상 확장(각각 x 20·200·2,000개, 인접 text와 합쳐짐). 문서 전체 확장 횟수는 100,000회를 넘지 않는다.
- 문제: 명세 7절 "그 호출 지점만 오류"는 화면에 오류 표시가 있어야 한다고 읽힌다 (2.3 참조).

### 1.13 제외 명령의 인수 범위와 진단 개수 (20)
- 표현: 아래 9개에 각 1개씩, 총 excluded-command 9개. 인수는 모두 소비되어 텍스트로 새지 않는다.
  `\catcode` (`` `\@=11`` 까지), `\def` (`\withargs#1{#1}` 까지), `\input{chapter1}`, `\include{chapter2}`,
  `\immediate`, `\write` (`18{rm -rf /}` 까지), `\openin` (`1=/etc/passwd` 까지), `\newpage`, `\vspace{2cm}`.
  본문은 단락 하나 `"이 문장은 정상 렌더링되어야 한다."`.
- 이유: macros.py의 EXCLUDED에 `immediate`와 `write`가 따로 있으므로 각각 진단. manifest는 atLeast 8이라 통과.
  `\catcode`·`\openin`·`\write18` 처럼 중괄호 아닌 인수의 범위는 명세에 없다 (2.4 참조).

### 1.14 수식 안의 `\showparam` (25)
- 상황: `$\omega = \showparam{\omega}$`. showparam은 인라인 노드인데 수식 안에 있다.
- 표현: 수식을 나눈다 → math `"\\omega ="`(greek) + showparam `omega`. `$\showparam{\kappa}$` 는 math 없이 inline error `{code: unknown-parameter, raw: "\\showparam{\\kappa}"}`.
- 이유: manifest가 showparam 노드 2개를 요구하므로 math.tex 안에 남길 수 없다. (2.1 참조)

### 1.15 picture.params 순서 (25)
- 표현: 매개변수 선언 순서 (`["omega", "gamma"]`). 첫 그림 식에는 `\gamma`가 먼저 나오지만 선언 순서를 따랐다.
- 이유: tree-conventions "매개변수: 선언 순서대로"를 확장 적용. 오류 그림 두 개(문법 오류, `gamma()` 함수)는 params 없음.

### 1.16 수식 구문 오류의 범위 (19)
- 상황: `$\frac{1}{$ 은 … $x+1$` 에서 첫 수식이 어디서 끝나는가.
- 표현: 다음 `$`에서 끝난다 → raw `"$\\frac{1}{$"`, 진단은 math-syntax 1개(이 수식에 대한 unbalanced-brace는 따로 내지 않음). 뒤의 `$x+1$`은 정상 math.
- 이유: manifest가 unbalanced-brace 1개(=`\textbf{` 것)만 요구한다. 수식 안 괄호 불균형은 math-syntax로 흡수.

### 1.17 미정의 명령 뒤 공백 (19)
- 표현: `\foobar{…} 그리고` → error 노드 뒤 text `" 그리고 계속된다."` (공백 유지). 인수가 있어 공백이 명령 이름 바로 뒤가 아니므로 남는다.

### 1.18 호환 모드 세부 (27)
- `\documentclass[11pt,a4paper]{article}` → documentclass "hypertex", classOptions 생략.
- unknown-package: inputenc, geometry 각 1 (amsmath·amssymb·amsthm·graphicx·hyperref는 내장으로 무시).
- `\newtheorem{theorem}{Theorem}` 이 기본 theorem의 표시 이름을 덮어 name "Theorem".
- `\bibliographystyle{plain}` 진단 없이 무시. `\bibliography{refs}`: refs.bbl이 없어 missing-resource 1개, bibliography 블록은 만들지 않음, 최상위 bibliography 배열 비어 있음.
- `\newpage` 진단 없이 무시. appendix.tex의 절은 번호 2로 이어짐.

### 1.19 그림 진단 (22, 23)
- 22: `\usetikzlibrary{decorations.pathmorphing}` → unknown-tikz-library(warning) 1, meta.tikzLibraries 생략.
  tikz-limit 1(foreach 2,000회), plot-sample-limit 1(samples=5000), excluded-command 1(`\pgfmathdeclarefunction`, picture는 그대로 만든다). `\pgfmathparse`는 제외 명령의 인수 안이라 따로 세지 않음.
- 23: `\addplot3` → excluded-command 1. 그 그림도 picture(usesPgfplots true)로 남긴다(manifest가 3개 요구).

## 2. 명세·스키마·manifest·테스트 문서의 문제

### 2.1 25번: 수식 안 `\showparam` vs 스키마 MathSource.params
- 스키마 MathSource.params 설명("\\showparam 등으로 참조한 매개변수. 값이 바뀌면 이 수식만 다시 그린다")은 `\showparam`이 math.tex 안에 남는 설계를 암시한다.
  그런데 manifest 25번은 showparam 노드 2개를 요구하고, 테스트 문서는 `\showparam`을 `$…$` 안에 썼다.
- 제안: (a) 테스트 문서를 `$\omega = $\showparam{\omega}` 꼴로 고치거나, (b) tree-conventions에 "수식 안 \showparam은 수식을 나눠 showparam 노드로" 규칙을 적거나, (c) manifest count에서 showparam을 빼고 math.params를 검사.
- 임시 가정: (b) — 1.14처럼 수식을 나눴다.

### 2.2 16번: 수식 안 미정의 명령의 표현
- manifest가 undefined-command 2개를 요구하지만 tree-conventions의 오류 노드 규칙은 본문용만 있다. 1.11 참조.
- 제안: 수식 안 미정의 명령의 표현(오류 노드로 수식 대체 / math 유지)을 tree-conventions에 추가.

### 2.3 17번: 명세 7절 "그 호출 지점만 오류" vs macros.py "아무것도 남기지 않는다"
- 명세는 호출 지점에 오류를 보여 줘야 한다고 읽히지만, macros.py 계약은 토큰을 하나도 남기지 않으므로 빌더가 오류 노드를 만들 수 없다.
  tree-conventions에도 expansion-limit 오류 노드 규칙이 없다.
- 제안: Expander가 그 자리에 표식 토큰을 남기고 빌더가 inline error `{code: expansion-limit, raw: "\\xe"}` 를 만들게 하자.
- 임시 가정: macros.py 계약대로 노드 없음 (1.12).

### 2.4 20번: 제외 명령의 인수 범위 미정
- `` \catcode`\@=11``, `\openin1=/etc/passwd`, `\immediate\write18{…}`는 중괄호 인수가 아니다. 명세·macros.py 모두 "인수까지 소비"라고만 한다.
  잘못 구현하면 `` `\@=11``, `1=/etc/passwd`, `18` 같은 찌꺼기가 본문 텍스트로 샌다.
- 제안: 제외 명령별 인수 꼴(`\catcode`: `` `\X=숫자``, `\openin`/`\openout`: `숫자=경로` 줄 끝까지, `\write`: `숫자{…}`)을 명시. `\immediate\write`를 진단 1개로 셀지 2개로 셀지도 정하자.
- 임시 가정: 1.13 (9개).

### 2.5 27번: `\bibliography{refs}`에 .bbl이 없을 때
- 명세 9절은 ".bbl → 인용 목록"만 말하고, 없을 때 bibliography 블록을 만들지 정하지 않았다. manifest는 missing-resource 1개만 요구.
- 임시 가정: 블록을 만들지 않는다.

### 2.6 10번: 스키마 Cell에 세로선 필드 없음
- `\multicolumn{n}{|c|}{…}`의 세로선을 표현할 수 없다. 제안: Cell에 ruleLeft/ruleRight 추가(선택).

### 2.7 LabelTarget.display 형식 미정
- 1.1 참조. 대조 규칙의 "무시하는 것"에 없으면서 형식이 정해져 있지 않다.
