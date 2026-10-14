"""문서 트리 → HTML + MathML (명세 8절). (담당: E)

계약
- render(tree) -> str: 완결된 HTML5 문서 하나 (<!doctype html> … </html>).
- 입력은 스키마를 만족하는 문서 트리뿐. TeX 원문이나 파서 내부에 의존하지 않는다.
- 수식(math.tex) → MathML. 외부 라이브러리 없이 동작하는 기본 변환기를 htex/html/mathml.py 에 둔다
  (분수, 첨자, 근호, 그리스 문자, 연산자, 괄호, matrix·cases, \\text, \\operatorname, \\mathbb 등 명세 3절 범위).
  변환하지 못한 수식은 원본 TeX를 <code class="htex-math-error"> 로 보여준다.
  한글 음절은 <mi mathvariant="normal" class="htex-hangul"> 로 한 음절씩 (명세 8절).
- 노드마다 id 속성 = 노드 id, 라벨이 있으면 라벨로도 이동 가능하게 (<a id="eq:H"> 등).
- link: ref/eqref → 같은 문서는 #라벨, 다른 문서는 원래 주소 유지(htex:// 그대로). 깨진 링크는 "??".
- proof[collapsed], collapse → <details>. steps → 모두 펼친 순서 목록(자바스크립트 없이 읽을 수 있게,
  단계별 표시는 class로만 표시). showparam → 기본값 표시.
- picture → 1단계에서는 <figure class="htex-picture"><pre>원문</pre></figure> 자리 표시.
- error 노드 → 빨간 고정폭 원문.
- 외부 자원 없이 열리는 단일 파일 (CSS 인라인). 사용자 입력은 모두 escape.
"""
from __future__ import annotations

from typing import Any

from .mathml import tex_to_mathml
from .render import render as _render

__all__ = ["render", "tex_to_mathml"]


def render(tree: dict[str, Any], *, web_fallback: bool = False) -> str:
    """문서 트리 → 완결된 HTML5 문서 문자열.

    web_fallback=True 이면 htex:// 링크를 https:// 로 바꿔 출력한다 (명세 2절 웹 폴백).
    기본값(False)은 htex:// 를 그대로 두어 전용 뷰어가 처리하게 한다.
    """
    return _render(tree, web_fallback=web_fallback)
