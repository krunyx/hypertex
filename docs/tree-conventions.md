# 문서 트리 표현 규칙

스키마가 정하지 않는 "같은 문서를 어떤 트리로 나타내는가"의 규칙. 정답 트리(A)와 파서(C)가 이 규칙을 똑같이 따라야
나중에 둘을 대조할 수 있다. 규칙이 모자라면 각자 `notes/<담당>-questions.md`에 적고, 정한 가정도 함께 적는다.

## 대조할 때 무시하는 것

- `span` (선택 필드. 정답 트리는 생략해도 된다)
- 진단의 `message` 문구와 `span`, `node`
- `math.tex`와 `picture.source`의 공백 차이 (공백 연속은 하나로, 앞뒤 공백 제거 후 비교. `\alpha x`와 `\alpha  x`는 같다)
- `source.sha256`

그 외는 모두 같아야 한다: 노드 종류, 순서, id, 번호, 라벨, 텍스트, 링크, 진단 코드와 개수.

## 노드 id

문서 순서(깊이 우선, 노드를 처음 여는 순서)로 `n1, n2, …`. 다음 것들도 id를 하나씩 받는다:
displaymath의 각 행, list의 각 항목, steps의 각 단계, footnote. 인라인 text·styled·math·link는 id가 없다.

예: section(n1) → 그 title 안에는 id 노드 없음 → children의 paragraph(n2) → 그 안 footnote(n3) → footnote 안 paragraph(n4) → 다음 블록(n5)…

## 블록 구조

- **절 중첩**: section의 children은 같은 수준 이상의 다음 절이 나오기 전까지의 모든 블록. subsection은 section의 children 안에 들어간다.
  첫 절 앞의 본문 블록은 body 최상위에 놓인다. `\appendix`는 노드를 만들지 않고, 이후 level 1 절에 `"appendix": true`.
- **단락**: 빈 줄(PAR)로 나뉜다. 단락 앞뒤 공백은 지우고, 안의 공백 연속은 공백 하나. 인접한 text 노드는 하나로 합친다.
- **디스플레이 수식은 단락을 끊는다**: "앞 텍스트 → paragraph, displaymath, 뒤 텍스트 → 새 paragraph". 앞이나 뒤가 공백뿐이면 그 paragraph는 만들지 않는다.
  목록, quote, verbatim, 정리 환경, figure 등 다른 블록 환경도 같다.
- `\maketitle`, `\begin{document}`, `\end{document}`, `\HyperTeXversion`, 전문의 메타 명령은 노드를 만들지 않는다.
- `\paragraph{제목}`은 level 4 section (번호 없음). 같은 단락에 이어진 텍스트는 그 section의 첫 paragraph가 된다.

## 인라인

- 글자 치환: `~` → U+00A0, `--` → U+2013, `---` → U+2014, `\,` → U+2009(얇은 공백). `\\`(본문) → linebreak 노드.
- `\emph`→styled emph, `\textbf`→bold, `\textit`→italic, `\texttt`→mono, `\textsc`→smallcaps. 중첩은 그대로 중첩.
- `\verb|…|` → `{"kind":"code"}`. verbatim 환경 → verbatim 블록 (text는 원문 그대로).
- 각주: footnote 노드, 번호는 문서 전체 일련번호, children은 블록(보통 paragraph 하나).

## 수식

- `math.tex`: 구분자(`$…$`, `\[…\]`, 환경 begin/end) 안의 내용을 **매크로 확장한 뒤** 앞뒤 공백을 잘라낸 것.
  `\label{…}`, `\nonumber`, `\notag`는 빼고(라벨은 행의 label로), 나머지는 그대로.
- align·gather·multline: 최상위의 `\\`로 행을 나눈다(중괄호나 cases 같은 내부 환경 안의 `\\`는 나누지 않는다). 각 행의 `&`는 tex에 남긴다.
  multline은 번호가 하나뿐이므로 **행을 나누지 않고** 전체를 행 하나로(내부 `\\` 유지). `\[…\]` → env "displaymath".
- 번호: equation·align·gather는 행마다(`\nonumber` 행 제외), 별표 환경과 displaymath는 없음.
- `math.scripts`: 정렬 순서 latin, greek, hangul. 수식 안에 명령 이름이 아닌 ASCII 글자가 있으면 latin, 그리스 문자 명령이 있으면 greek, 한글 음절이 있으면 hangul.
  `\text{…}`, `\operatorname{…}` 안의 글자도 센다.

## 정리·상호작용

- 정리류 번호는 카운터 하나 공유 (definition, theorem, lemma, … remark, \newtheorem 환경 모두). proof는 번호 없음.
- theorem.name: 기본 환경은 `htex/commands.py`의 THEOREM_NAMES, \newtheorem은 그 둘째 인수.
- `\begin{proof}[collapsed]` → collapsed true. 일반 proof는 false. proof의 title은 생략.
- steps의 각 `\step` 뒤 내용(다음 \step 전까지) → 그 단계의 children (보통 paragraph 하나). 단계에 label이 있으면 번호는 단계 순서("1","2","3").

## 그림·표

- figure/table → float. children 순서는 원문 순서에서 `\caption`과 `\label`을 뺀 것. caption은 float.caption으로.
- `\includegraphics[width=0.6\textwidth]{…}` → image, width "60%". 옵션이 없으면 width 생략.
- 허용되지 않는 주소의 `\includegraphics`는 image를 만들지 않고 inline error(code insecure-resource, raw 원문) + 진단.
- tikzpicture → picture. source는 begin/end 사이 원문(확장 후)을 앞뒤 공백 잘라낸 것. figure 안이면 float의 child.
- tabular: 열 지정 `|l|c|r|` → columns [{align l, ruleLeft true}, {align c, ruleLeft true}, {align r, ruleLeft true, ruleRight true}].
  `\hline`은 다음 행의 ruleAbove (마지막 행 뒤의 \hline은 마지막 행의 ruleBelow). 빈 마지막 행(끝의 `\\` 뒤)은 만들지 않는다.

## 링크

- ref/eqref/cite의 children은 빈 배열을 넣지 않고 **생략**한다. href는 children에 표시 텍스트. url은 children 생략.
- 같은 문서 \ref: resolved {number, node}. 없는 라벨: resolved {broken: true} + broken-ref 진단(warning).
- 다른 문서 \ref{doc#label}: target {doc, label}, resolved 생략 (뷰어가 해석).
- \cite{a,b}: target.keys ["a","b"]. 외부 식별자(arXiv:, doi:, isbn:, htex://, https://로 시작)는 resolved 생략.
  BibTeX 키는 resolved.numbers (thebibliography 순서 "1","2",…). 하나라도 없는 키가 있으면 resolved.broken true + broken-ref 진단 하나.
- thebibliography → 그 자리에 bibliography 블록 하나 + 최상위 bibliography 배열에 항목들 {key, number, text, identifier?}.
  bibitem 본문에 `doi:…` 또는 `arXiv:…`가 있으면 identifier로.

## 매개변수

- name은 역슬래시를 뺀 이름. 선언 순서대로.
- \showparam{\k}: 선언된 이름이면 showparam 노드, 아니면 inline error(code unknown-parameter) + 진단.

## 오류 노드

- 정의되지 않은 명령 `\foo{인수}`: inline error {code undefined-command, raw "\\foo", children: [인수의 인라인들]}.
- 수식 구문 오류: math 노드 대신 inline error {code math-syntax, raw: 수식 원문 전체(구분자 포함)}.
- 블록 수준에서 해석 불가: error 블록.
- 제외된 명령: 노드를 만들지 않는다 (진단만).

## 메타

- title, authors(작성 순서), date(문자열 그대로), keywords(쉼표로 나누고 앞뒤 공백 제거), abstract(블록 목록).
- styles, macroImports: 원문 주소 그대로, 허용되지 않는 주소는 넣지 않는다.
- tikzLibraries: 허용 목록에 있는 것만, 작성 순서. mathExtensions: \usemath 인수.
- 호환 모드: documentclass는 "hypertex"로 바꾸고 classOptions는 생략. abstract 환경은 meta.abstract로.
