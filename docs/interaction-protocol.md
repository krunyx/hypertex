# 상호작용 규약 (2단계)

문서는 스크립트를 담지 않는다(명세 1, 7절). 슬라이더, 그림 다시 그리기, 링크 미리보기는 **호스트**
(전용 뷰어 F, 웹 서버 G)가 넣는 신뢰된 스크립트가 맡는다. 두 호스트가 같은 스크립트와 같은 HTML 표식을
쓰도록 이 규약을 정한다.

## 1. 렌더러가 내는 HTML 표식 (htex.html.render, 이미 구현됨)

| 대상 | 표식 |
| --- | --- |
| 매개변수 목록 | `<aside class="htex-parameters">` 안의 `<output class="htex-param" data-param="이름" data-min data-max data-default [data-step]>` |
| 본문·수식 안의 값 | `<output class="htex-param" data-param="이름">` (본문), `<mn class="htex-param" data-param="이름">` (MathML) |
| 그림 | `<figure class="htex-picture" id="노드 id" [data-params="a b"] [data-pgfplots="true"]>` 안에 SVG(H 이후) 또는 `<pre>` |
| 같은 문서 참조 | `<a href="#라벨">` |
| 다른 문서 참조 | `<a href="문서#라벨" data-doc data-label>` |

## 2. 호스트가 넣는 것 (`render(tree, head_extra=…)`)

```html
<meta name="htex-picture-endpoint" content="그림 주소">     <!-- 없으면 그림은 다시 그리지 않음 -->
<meta name="htex-fragment-endpoint" content="조각 주소">    <!-- 없으면 다른 문서 미리보기 없음 -->
<script src="상호작용 스크립트 주소" defer></script>
```

## 3. 그림 주소

`GET {picture-endpoint}?node=<노드 id>&<이름>=<값>&…` → `200 image/svg+xml` (본문은 `<svg>` 하나).
실패하면 4xx와 짧은 텍스트. 호스트는 `htex.tikz.render_picture_node(tree, node, values)`로 응답한다.
그림 주소에는 어느 문서인지가 이미 들어 있다(예: 웹 서버 `/__htex/picture/notes/a.htex`, 뷰어 `htexapp://picture/<문서 키>`).

## 4. 조각 주소 (링크 미리보기)

`GET {fragment-endpoint}?doc=<다른 문서 주소>&label=<라벨>` → `200 text/html` (그 라벨 블록 하나의 HTML 조각).
같은 문서 미리보기는 스크립트가 `document.getElementById`로 복제한다.

## 5. 상호작용 스크립트 `htex/web/interact.js` (담당 G)

- 외부 라이브러리 없음. 스크립트 없이도 문서는 완전히 읽힌다(점진적 향상).
- 매개변수 목록의 각 항목에 `<input type="range">`를 붙인다. 움직이면 같은 `data-param`의 모든 output/mn 값을 바꾸고,
  `data-params`에 그 이름이 있는 그림을 그림 주소로 다시 받아 바꾼다(요청은 150ms 묶음, 늦게 도착한 옛 응답은 버림).
- 참조 링크에 마우스를 올리거나 길게 누르면 미리보기 창(같은 문서는 복제, 다른 문서는 조각 주소).
- `prefers-reduced-motion` 존중, 키보드로 조작 가능.
