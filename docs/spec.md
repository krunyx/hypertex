# HyperTeX 2.0 명세 초안 (저장소 사본, 2026-10-14)

원본은 Claude Docs의 "HyperTeX 2.0 명세 초안". 이 사본은 구현 담당자 참고용이며, 충돌하면 원본이 우선한다.

## 1. 개요

HTML 대신 LaTeX 문법으로 쓰는 웹 문서 형식. 수식과 상호참조를 1급 시민으로 다루고, 문서·식·논문 사이를 링크로 이동한다.

설계 원칙
1. 선언적 부분집합: 임의의 TeX 원시 명령은 허용하지 않는다.
2. 반드시 종료: 모든 문서는 유한 시간 안에 렌더링이 끝난다.
3. 오류에 관대: 오류가 있어도 렌더링을 멈추지 않고 해당 부분만 표시한다.
4. 리플로우 기본.
5. 어디서나 읽힘: 일반 브라우저에서도 읽을 수 있어야 한다.
6. 익숙함: 단순한 기존 .tex 문서는 거의 수정 없이 열린다.

범위: 읽기 전용 문서. 선언적 상호작용(3.2절)은 허용, 범용 스크립트와 폼은 범위 밖.

## 2. 문서 구조와 파일 형식

| 항목 | 값 |
| --- | --- |
| 확장자 | .htex |
| MIME | text/x-hypertex |
| 인코딩 | UTF-8 고정 |
| 문서 클래스 | \documentclass{hypertex} 또는 \documentclass[note]{hypertex} |
| 버전 | \HyperTeXversion{2.0} (선택) |

URL 스킴: 표준 주소는 htex://호스트/경로, 전송은 HTTPS. 일반 브라우저용 웹 폴백은 htex:// 링크를 https:// 로 바꿔 출력.

전문(preamble)과 본문. \begin{document}는 생략 가능하며, 생략하면 첫 본문 명령부터 본문.
메타데이터: \title, \author(여러 번 가능), \date, \keywords(쉼표 구분), \abstract.

## 3. 허용 명령어 집합

| 범주 | 명령 |
| --- | --- |
| 구조 | \section, \subsection, \subsubsection, \paragraph, \appendix (별표 형 포함) |
| 텍스트 | \emph, \textbf, \textit, \texttt, \textsc, \footnote, \\, ~ |
| 목록 | itemize, enumerate, description |
| 인용·코드 | quote, verbatim, \verb |
| 수식 | $…$, \[…\], equation, align, gather, multline (별표 형 포함), cases, matrix 계열 |
| 수식 기호 | amsmath·amssymb 수준 |
| 정리 환경 | theorem, lemma, proposition, corollary, definition, example, remark, proof, \newtheorem |
| 그림 | figure, \includegraphics (SVG·PNG·JPEG, URL), \caption |
| 표 | table, tabular (\| l c r, \hline, \multicolumn) |
| 링크 | \label, \ref, \eqref, \href, \url, \cite, \transclude |
| 메타 | \title, \author, \date, \abstract, \keywords, \maketitle |

의도적 제외: \def, \catcode, \input/\include, \write, \openin, 페이지 명령(\newpage, \vspace, \pagestyle).

### 3.1 TikZ 부분집합

허용: tikzpicture, \draw, \fill, \filldraw, \node, \coordinate, \path, \clip; 경로 연산 --, -|, |-, rectangle, circle, ellipse, arc, grid, to[bend left], plot; 직교·극좌표·상대·이름 좌표; 스타일과 \tikzset 키-값; \foreach (그림당 반복 1,000회 상한); plot (샘플 1,000점 상한); 라이브러리 arrows.meta, calc, positioning.
제외: \pgfmathdeclarefunction, \pgfkeys 직접 조작, externalize, 목록 밖 라이브러리(경고 후 무시). 그림 하나 경로 요소 10,000개 상한.

pgfplots 부분집합: axis, semilogxaxis, semilogyaxis, loglogaxis; 축 옵션(xlabel, ylabel, title, xmin…, grid, axis lines, legend pos, width/height); \addplot + 함수식 / coordinates / 인라인 table; domain, samples(1,000 상한), mark, only marks, smooth; \addlegendentry, \legend. 외부 데이터는 같은 출처 HTTPS만, 그래프당 10,000점 상한. 3D(\addplot3)는 범위 밖.

### 3.2 상호작용 (선언적)

| 명령 | 동작 |
| --- | --- |
| \begin{proof}[collapsed] | 접힌 증명 |
| \begin{collapse}{제목} … \end{collapse} | 임의 내용 접기 |
| \begin{steps} \step … \end{steps} | 단계별 펼침 |
| \parameter{k}{min}{max}{기본값}[step=…] | 슬라이더 선언 |
| \showparam{k} | 현재 값 표시 |
| TikZ 안의 \k | 매개변수에 따라 다시 그림 |

정적 출력에서는 기본값, 접힌 내용은 펼친 상태.

계산식 문법: + - * / ^ 괄호, 비교(< > ==), ifthenelse(c,a,b); 상수 pi, e; sin cos tan asin acos atan atan2; sinh cosh tanh; exp ln log10 sqrt; abs floor ceil round mod min max sign. 각도 기본은 도, 라디안은 r 접미사(sin(\x r)). 정의역 밖 값은 그 점만 건너뛴다.

## 4. 매크로 규칙

\newcommand, \renewcommand만 허용.
1. 인수 최대 9개, 첫 인수 기본값 허용.
2. 재귀 금지: 정의 본문이 자기 자신을 부르거나 다른 매크로를 거쳐 순환을 만들면 정의를 거부한다. 모르는 명령을 부르는 정의는 받아들이고, 그 명령은 쓰는 자리에서 오류로 표시한다 (2026-10-14 결정). 호환 모드(9절)에서는 순환 검사를 하지 않고 확장 상한만으로 막는다 (2026-10-15 결정).
3. 확장 상한: 문서 전체 100,000회, 한 번의 확장 결과 10,000토큰. 넘으면 그 지점만 오류.
4. 정의 이후에만 유효.
5. \DeclareMathOperator 허용.
매크로 공유: \usemacros{주소}로 다른 문서의 전문 매크로만 가져온다.

## 5. 링크 모델

모든 \label은 주소가 된다: htex://example.org/notes/oscillator.htex#eq:H

| 명령 | 의미 |
| --- | --- |
| \ref{라벨} | 같은 문서 참조, 번호 표시 |
| \ref{문서#라벨} | 다른 문서 참조 (상대·절대 URL) |
| \eqref | 괄호 포함 |
| \href{URL}{텍스트}, \url | 일반 링크 |
| \cite{식별자} | arXiv:, doi:, isbn:, htex://, 또는 BibTeX 키 (thebibliography / \bibliography) |
| \transclude{문서#라벨} | 다른 문서의 식·정리를 이 자리에 표시 |

라벨 영구성은 보장하지 않는다. 대상을 찾지 못하면 깨진 링크로 표시.

## 6. 스타일 시스템

.hsty 키-값 파일 (매크로·실행 코드 불가). \usestyle. 예: equation.number = "(section.equation)", math.hangul.font, cjk.latin.space, cjk.math.space. 독자 설정이 우선.

## 7. 오류 처리와 보안

| 오류 | 처리 |
| --- | --- |
| 정의되지 않은 명령 | 이름을 빨간 고정폭으로, 인수는 일반 텍스트로 |
| 짝 안 맞는 { } | 단락 끝에서 자동으로 닫고 경고 |
| 닫히지 않은 환경 | 다음 \section 또는 문서 끝에서 닫음 |
| 수식 구문 오류 | 그 수식만 원본 TeX로 |
| 깨진 \ref | ?? 와 툴팁 |
| 확장 상한 초과 | 그 호출 자리에 원문을 빨간 오류로 표시 |

보안: 파일 시스템·셸·네트워크 직접 접근 불가. 외부 자원은 \includegraphics, \usestyle, \usemacros, \transclude로만, HTTPS만. 렌더링 시간 상한(문서당 2초). 스크립트 없음.

## 8. 렌더링 요구사항

파서(파이썬 기준 구현) → 문서 트리(JSON) → HTML 변환기(HTML + MathML) → 웹 폴백 / 전용 뷰어(PySide6) / 자체 조판 엔진(2단계).
성능: 20만 자 문서 1초 안에 첫 화면. 접근성: MathML, 원본 TeX 복사 가능.

한글 조판: 어절 단위 줄바꿈. 한 어절이 줄보다 길 때만 음절 분리.
한글 수식(hangulmath): 수식 안 한글은 그리스 문자처럼 한 음절 = 한 기호(ord), 첨자 가능, 별도 간격 규칙 없음, 직립 고딕(기본 Noto Sans KR). 여러 음절 단어는 \text{}나 \operatorname{}. 수식 노드에 script=hangul 속성. \usemath{hangulmath} 예약.

## 9. 기존 LaTeX 호환성 (.tex → 호환 모드)

| 기존 요소 | 처리 |
| --- | --- |
| \documentclass{article} 등 | hypertex로 대체 |
| \usepackage{amsmath, amssymb, amsthm, hyperref, graphicx} | 내장으로 보고 무시 |
| 지원하는 기능의 패키지(amscd, tikz-cd, xy, cleveref …)와 글꼴·여백·조판 패키지(inputenc, geometry, microtype …) | 경고 없이 무시 |
| 그 외 \usepackage | 무시하고 경고 |
| \def (구분자 있는 인수 포함), \let, \newenvironment, \providecommand | 매크로로 변환 |
| 매크로 순환 | 검사하지 않음 (확장 상한으로 막음) |
| \chapter | 절 단계를 하나씩 내림 (chapter→section … subsubsection→paragraph), \part는 번호 없는 최상위 절 |
| \cref, \Cref, \autoref | 참조 + 영어 종류 이름 (cleveref 기본값: "theorem 2.1", "Section 3", "eq. (1)") |
| \input{chapter1} | 같은 위치 파일을 그 자리에 펼쳐 넣음 (번호·라벨이 한 문서로 이어짐) |
| \bibliography{refs} + .bbl | 인용 목록으로 변환 |
| 페이지 명령 | 무시 |

## 10. 결정 기록

htex:// 채택 / TikZ 부분집합 / pgfplots 2D / 선언적 상호작용 / 계산식 함수 한정 / 라벨 영구성 미보장 / 매크로 상한 100,000·10,000 / 어절 줄바꿈 / 한글 수식은 그리스 문자처럼 / 명칭 HyperTeX 2.0 / 호환 모드: 순환 검사 생략, 조판 패키지 경고 없음, \cref 영어 이름, \chapter 단계 내림 (2026-10-15).
