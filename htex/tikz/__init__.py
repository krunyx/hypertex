"""TikZ·pgfplots 부분집합 → SVG (명세 3.1절). (담당: H, 2단계)

구현 (H): scan.py(원문 훑기) · styles.py(단위·색·옵션) · geometry.py(곡선·화살표) · engine.py(TikZ 실행)
· axis.py(pgfplots) · svg.py(캔버스·노드 글). 지원 범위와 가정은 notes/H-questions.md.

계약
- render_picture(source, values=None) -> PictureResult
  * source: 문서 트리 picture.source (매크로 확장이 끝난 tikzpicture 본문).
  * values: 매개변수 이름(역슬래시 제외) → 값. None이면 그림이 참조하지 않는다고 본다.
    식 안의 \\<이름> 은 이 값으로 평가한다 (htex.expr.parse / evaluate 사용).
  * 반환: svg = 완결된 <svg …>…</svg> 문자열 하나 (외부 자원·스크립트·이벤트 속성 없음), 못 그리면 None.
    problems = 그리면서 건너뛴 것들의 설명 (진단이 아니라 화면 하단 주석·로그용).
  * 예외를 던지지 않는다. 시간 상한 1초 (넘으면 그때까지 그린 것 또는 None).
  * 같은 입력이면 같은 출력 (캐시 가능).
- render_picture_node(tree, node_id, values) -> PictureResult
  문서 트리에서 그 id의 picture 노드를 찾아 render_picture. values에 없는 매개변수는 트리의 기본값.
  범위(min~max) 밖 값은 범위로 자른다. 없는 노드면 svg=None.

SVG 규칙
- 1cm = 37.8px (96dpi). viewBox는 그림 경계 + 여백. width/height 속성은 넣지 않고 CSS가 정한다
  (렌더러가 max-width:100% 로 감싼다).
- 색은 TikZ 색 이름·xcolor 혼합(blue!50, red!30!black)을 지원하고, 지정이 없으면 currentColor
  (다크 모드에서 글자색을 따라가게).
- 노드 글의 수식은 <foreignObject> 안에 htex.html.mathml.tex_to_mathml 결과를 넣는다.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PictureResult:
    svg: Optional[str] = None
    problems: list[str] = field(default_factory=list)


TIME_LIMIT = 1.0     # 초


def render_picture(source: str, values: Optional[dict[str, float]] = None) -> PictureResult:
    try:
        return _render(source, values)
    except Exception as e:  # noqa: BLE001 - 계약: 예외를 던지지 않는다
        return PictureResult(None, [f"그림을 그리지 못했다 (내부 오류: {type(e).__name__})"])


def _render(source: str, values: Optional[dict[str, float]]) -> PictureResult:
    from .engine import Engine
    if not isinstance(source, str):
        return PictureResult(None, ["그림 원문이 없다"])
    if len(source) > 1_000_000:
        return PictureResult(None, ["그림 원문이 너무 길다 (1,000,000자 상한)"])
    vals: dict[str, float] = {}
    for k, v in (values or {}).items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            vals[str(k)] = f
    key = source + "\0" + repr(sorted(vals.items()))
    prefix = "htx" + hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:8]
    eng = Engine(source, vals, time_limit=TIME_LIMIT, id_prefix=prefix)
    eng.run()
    c = eng.canvas
    if c.count == 0 or c.bbox is None:
        problems = eng.problems or ["그릴 것이 없다"]
        return PictureResult(None, problems)
    return PictureResult(c.to_svg(), eng.problems)


def render_picture_node(tree: dict[str, Any], node_id: str,
                        values: Optional[dict[str, float]] = None) -> PictureResult:
    try:
        node = _find(tree, node_id)
        if node is None:
            return PictureResult(None, [f"그림 노드가 없다: {node_id}"])
        return render_picture(node.get("source") or "", merge_values(tree, values))
    except Exception as e:  # noqa: BLE001
        return PictureResult(None, [f"그림을 그리지 못했다 (내부 오류: {type(e).__name__})"])


def merge_values(tree: dict[str, Any], values: Optional[dict[str, Any]] = None) -> dict[str, float]:
    """트리의 매개변수 기본값에 values 를 덮어쓰고 [min, max] 로 자른다. 선언되지 않은 이름은 버린다."""
    out: dict[str, float] = {}
    values = values or {}
    for p in (tree or {}).get("parameters") or []:
        name = p.get("name")
        if not isinstance(name, str):
            continue
        v = p.get("default")
        if name in values:
            try:
                f = float(values[name])
                if math.isfinite(f):
                    v = f
            except (TypeError, ValueError):
                pass
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        lo, hi = p.get("min"), p.get("max")
        try:
            if lo is not None:
                v = max(float(lo), v)
            if hi is not None:
                v = min(float(hi), v)
        except (TypeError, ValueError):
            pass
        out[name] = v
    return out


def _find(tree: Any, node_id: str) -> Optional[dict]:
    stack = [tree]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("kind") == "picture" and x.get("id") == node_id:
                return x
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return None
