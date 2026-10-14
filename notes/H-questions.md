# H(그림 렌더러) 질문과 임시 가정

형식: 어디 / 무엇이 문제 / 제안 / 임시 가정

## 1. SVG를 figure의 직계 자식으로 넣음 (`div.htex-svg` 감싸기를 하지 않음)
- 어디: 작업 지시("`<figure …><div class="htex-svg">SVG</div></figure>`"), htex/web/interact.js `replacePicture`
- 문제: interact.js는 figure의 **직계 자식** `svg`(또는 `pre`)를 찾아 바꿔 끼우고, CSS도 `figure.htex-picture>svg`를 쓴다.
  div로 감싸면 슬라이더를 움직일 때 새 SVG가 div 옆에 따로 들어가 그림이 두 개가 된다.
- 제안: 규약(docs/interaction-protocol.md 1절)에 "SVG는 figure의 직계 자식"이라고 적는다.
- 임시 가정: `<figure class="htex-picture" id data-params data-pgfplots><svg …/>[<details class="htex-picture-notes">]</figure>`.
  처음 렌더(b_picture)와 그림 주소 응답(render_picture_node)은 바이트 단위로 같은 SVG다(테스트로 확인).

## 2. E의 테스트 두 건과 F의 테스트 한 건이 1단계 자리 표시(stub)를 전제함 — 담당자 수정 요청
- 어디: tests/unit/test_E_render.py `test_picture_placeholder` (picture → `<pre>` 기대),
  tests/unit/test_F_core.py `test_picture_endpoint_stub_and_renderer` 첫 부분 ("H가 stub이면 422" 기대)
- 문제: 렌더러가 생겼으므로 `\draw (0,0) -- (1,1) node {$<x>$};`는 이제 SVG가 되고, 25번 n2 그림 주소는 200이다.
  두 파일은 H가 고칠 수 없다.
- 제안: E는 "그릴 수 있는 그림은 `<figure …><svg`, 못 그리는 그림(예: `\draw plot (\x, {sin(\x r});`)은 `<pre>`"로,
  F는 "실제 렌더러면 200 image/svg+xml, 못 그리는 n5는 422"로 바꾼다.
- 임시 가정: 이 두 건은 실패한 채로 둔다 (나머지 604건 통과).

## 3. "원문으로 표시" 안내(::before)가 SVG 위에도 뜸 — E에게 CSS 요청
- 어디: htex/html/style.py `.htex-picture::before{content:"그림 (TikZ, 이 보기에서는 원문으로 표시)"…}`
- 문제: SVG로 그린 그림 위에도 이 안내가 보인다. interact.js는 다시 그린 뒤에만 `.htex-picture-live`로 숨긴다.
  SVG 안에 `<style>`을 넣어 숨기는 방법은 E의 테스트(`<style>`은 문서에 하나)와 부딪쳐 쓰지 않았다.
- 제안: style.py를 `.htex-picture:has(>pre)::before{…}`로 바꾸거나, `.htex-picture>pre` 앞에만 붙게 한다.
  `.htex-picture-notes`의 모양(작은 글, 왼쪽 정렬)도 style.py에 넣어 주면 b_picture의 인라인 style을 뺄 수 있다.
- 임시 가정: 안내는 그대로 보인다. notes 상자는 인라인 style 속성으로 꾸몄다.

## 4. SVG 안 스타일은 표현 속성과 style 속성만 씀 (CSP)
- 어디: 뷰어 CSP `style-src 'unsafe-inline'`, 서버 CSP_HTML/CSP_SVG
- 확인: 뷰어(htexapp:)와 웹 서버(http) 둘 다에서 슬라이더 응답 SVG가 막히지 않았다(콘솔에 CSP 위반 없음).
  foreignObject 안의 MathML도 보인다. SVG에는 `<style>` 요소가 없고 색·선은 fill/stroke 같은 표현 속성이다.
  `style` 속성은 svg 루트(크기·글꼴)와 foreignObject 안의 div(배치)에만 쓴다.
- 제안: 'unsafe-inline'을 빼려면 이 두 style 속성을 클래스와 style.py 규칙으로 옮겨야 한다 (E와 협의).

## 5. 크기·단위
- 어디: htex/tikz/__init__.py docstring "width/height 속성은 넣지 않고 CSS가 정한다"
- 문제: width가 없으면 브라우저가 SVG를 글 상자 폭(100%)까지 늘려 작은 그림이 거대해진다.
- 임시 가정: width/height 속성은 넣지 않고, 루트 style에 `width:<자연 크기>em;max-width:100%;height:auto`를 둔다
  (1cm=37.8px, font-size 10pt=13.29px 기준 em). 그래서 본문 글자 크기를 따라 같이 커지고 줄어든다.

## 6. 색 기본값
- 임시 가정: 색이 없거나 정확히 `black`이면 `currentColor`(다크 모드에서 글자색). `fill=white`는 `var(--bg,#fff)`.
  `black!50` 같은 혼합은 계산한 #rrggbb 그대로다(다크 모드에서도 같은 회색).
- 범례 상자 바탕도 `var(--bg,#fff)`.

## 7. pgfplots 세부 동작 (pgfplots와 다른 점)
- 표식: pgfplots는 `\addplot {식}`에도 기본 표식(`*`)을 붙이지만, 함수식은 표식 없이 그렸다(mark=를 쓰면 그림).
  coordinates/table은 순환 표식(*, square*, o, star)을 붙인다.
- 색 순환: blue, red, brown!60!black, black 순. 옵션이 있는 `\addplot[…]`도 색 지정이 없으면 순환 색을 쓴다
  (pgfplots는 `\addplot[...]`이면 검정, `\addplot+[...]`이면 순환 — 화면에서 검정 선만 남는 것을 피하려고 순환 쪽으로 가정).
- 자동 범위: 데이터 범위, y는 양쪽 5% 넓힘(enlargelimits 근사). 축 상자 크기는 width/height에서 글 자리를 대략 뺀 값.
- 3D(`\addplot3`)는 problems에 기록하고, 그릴 그래프가 하나도 없으면 svg=None(→ 원문 `<pre>`).
- 외부 파일(`table {파일}`)은 읽지 않는다(problems). 명세의 "같은 출처 HTTPS"는 렌더러가 네트워크를 쓰지 않기로 하고 미룸.
- `axis cs:`와 축 안의 `\draw`·`\node`는 축 좌표로 그린다.

## 8. 아직 못 하는 것 (problems에 "지원하지 않는다"로 기록)
- `let`, `pic`, `\matrix`, decorations, shading(단색 근사), patterns, `/.code`, `\pgfmathparse`, `plot function`.
- 노드의 `sloped`, `transform shape`, 노드 모양 중 rectangle/circle/ellipse/coordinate 밖의 것.
- `to[out=, in=]`은 지원, `controls`의 `+()` 상대 좌표는 근사.
- 노드 크기는 글자 수 근사(한글 1em, 라틴 0.5em 안팎, 수식은 기호별 근사). 정확한 글자 폭은 브라우저마다 달라
  수식 노드는 foreignObject를 25% 넉넉히 잡고 가운데 맞춤했다.

## 9. 한도
- \foreach: 그림 전체 실행 횟수 1,000 (D의 정적 집계와 같은 합산). 넘으면 거기서 멈추고 problems.
- plot·\addplot samples 1,000, 데이터 10,000점, 경로 요소 10,000(좌표·연산·표본 하나씩), 시간 1초(time.monotonic).
  넘으면 그때까지 그린 것을 SVG로 내고 problems에 적는다.
