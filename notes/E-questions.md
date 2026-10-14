# E (HTML 변환기) 질문과 임시 가정

## 1. 수식 안 `\showparam`과 MathSource.params (스키마 / tests/trees/25)
- 어디: schema MathSource.params 설명("\showparam 등으로 참조한 매개변수"), A-questions 2.1, 정답 트리 25.
- 문제: 정답 트리는 `$\omega = \showparam{\omega}$`를 math `"\omega ="` + showparam 노드로 나눈다.
  그러면 math.params는 쓰일 곳이 없고, 수식 조각 `\omega =`가 관계 기호로 끝나는 불완전한 수식이 된다.
  반대로 math.tex 안에 `\showparam`이 남는 트리도 스키마상 가능하다.
- 제안: 하나로 정한다. 렌더러 입장에서는 "tex 안에 \showparam 유지 + math.params"가 수식 간격·재렌더에 더 낫다.
- 임시 가정: 두 표현 모두 지원. 나뉜 경우 `<math>` 뒤 `<output class="htex-param">`(CSS로 간격 보정),
  tex 안에 남은 경우 `<mn class="htex-param" data-param>` 로 기본값 표시. 선언되지 않은 이름은 `<merror>`.

## 2. 다른 문서 \ref의 표시 텍스트 (docs/tree-conventions.md 링크 절)
- 문제: 다른 문서 ref는 resolved가 없어 번호를 모른다. 정적 HTML에서 무엇을 보여줄지 정해져 있지 않다.
- 제안: 명세 8절에 "정적 출력은 라벨 이름(eqref는 괄호)을 보이고 뷰어가 번호로 바꾼다"고 적기.
- 임시 가정: 라벨 이름을 보이고(eqref는 `(eq:aadag)`), `<a class="htex-ref htex-xref" data-doc data-label>`로 뷰어가 바꿀 수 있게 둔다.

## 3. htex:// 링크의 웹 폴백 변환 위치 (명세 2절)
- 문제: "웹 폴백은 htex:// 를 https:// 로 바꿔 출력"인데 HTML 변환기 결과를 뷰어와 웹 폴백이 같이 쓴다.
- 임시 가정: `render(tree, web_fallback=False)` 기본은 htex:// 유지, `web_fallback=True`면 href만 https:// 로 바꾼다
  (data-doc·data-href 속성은 원래 주소 유지).

## 4. 라벨이 다른 노드의 id와 겹치는 경우 (스키마 LabelName)
- 문제: LabelName 패턴이 `n12` 같은 노드 id를 허용하므로, 라벨 앵커 id와 노드 id가 충돌할 수 있다.
- 제안: 스키마에서 `^n[0-9]+$` 라벨을 금지하거나, HTML 앵커에 접두어 규칙을 둔다.
- 임시 가정: 겹치는 라벨은 앵커를 만들지 않고 그 라벨로 가는 링크를 노드 id(resolved.node)로 보낸다.
  변환기가 새로 만드는 id는 라벨 문법에 없는 `~`를 써서(`fn~n9`, `bib~키`) 충돌을 피한다.

## 5. 식 번호 형식 스타일 (명세 6절, 사례 28)
- 문제: `equation.number = "(section.equation)"`의 괄호가 번호 문자열에 들어가는지, 렌더러가 붙이는지 불명확.
- 임시 가정: 트리의 number는 괄호 없는 `1.1`이고 렌더러가 `(1.1)`로 감싼다 (정답 트리 28과 일치). 스타일 파일
  나머지 키(글꼴·색)는 1단계에서 적용하지 않고 `<meta name="htex-style">`로만 남긴다.

## 6. 정리 머리말에 쓰이는 이름과 번호 (정리 2 (라그랑주).)
- 임시 가정: theorem.name을 그대로 쓰고 "이름 번호 (note)." 형식. proof는 title이 없으면 "증명".
  접힌 증명의 요약 줄에는 "증명"만 보인다.

## 7. bibliography 블록이 없는데 최상위 bibliography 배열이 있는 경우
- 임시 가정: 문서 끝에 "참고문헌" 절을 자동으로 붙인다. bibliography 블록이 여러 개면 첫 블록에만 목록을 넣는다.

## 8. MathML 변환 범위에서 아직 못 하는 것
- `\newcommand`로 확장되지 않은 매크로(트리에서는 이미 확장된다고 가정), `\color`, `\tag`, `\substack`, `\xrightarrow`,
  `\overset` 이외의 복잡한 스택, `array`의 `|` 세로줄, `\hline`(무시).
- 임시 가정: 모르는 명령이 있으면 그 수식 전체를 `<code class="htex-math-error">`로 원문 표시 (명세 7절 "그 수식만 원본 TeX로").
