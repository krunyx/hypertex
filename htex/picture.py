"""TikZ·pgfplots 부분집합 검사 (명세 3.1절). (담당: D)

1.0의 파서는 그림을 그리지 않는다. 확장이 끝난 tikzpicture 소스를 검사해
진단을 내고, 트리의 picture 노드에 들어갈 정보만 돌려준다. 그리기는 2단계(H).

계약: check_picture(source, ...) -> PictureInfo
- source: \\begin{tikzpicture} 와 \\end{tikzpicture} 사이의 원문 (매크로 확장 후).
- 허용 목록 밖의 명령 중 명세가 제외한 것(\\pgfmathdeclarefunction, \\pgfkeys, \\addplot3,
  externalize)은 excluded-command.
- \\foreach 반복 횟수 합이 그림당 1,000을 넘으면 tikz-limit (한 그림에 한 번만).
- samples= 가 1,000을 넘으면 plot-sample-limit. 경로 요소 10,000개 초과면 tikz-limit.
- pgfplots 데이터(coordinates, table)가 10,000점을 넘으면 data-limit.
- 계산식({…} 안의 식, plot 좌표식)은 expr.parse로 검사하고, ExprError.kind 를 그대로 진단 코드로.
- uses_pgfplots: axis 계열 환경이 있으면 True.
- params: 그림이 참조하는 매개변수 이름 (expr가 알려준 것의 합집합).
- 라이브러리 검사(\\usetikzlibrary)는 빌더가 전문에서 하고 이 함수는 하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .diagnostics import Sink, Span

ALLOWED_LIBRARIES = {"arrows.meta", "calc", "positioning"}

LIMITS = {"foreach": 1_000, "samples": 1_000, "path_elements": 10_000, "data_points": 10_000}


@dataclass
class PictureInfo:
    uses_pgfplots: bool = False
    params: list[str] = field(default_factory=list)


_AXIS = re.compile(r"\\begin\{(axis|semilogxaxis|semilogyaxis|loglogaxis)\}")


def check_picture(source: str, params: set[str], span: Span, sink: Sink) -> PictureInfo:
    """0단계: pgfplots 여부만 판별. D가 계약대로 채운다."""
    return PictureInfo(uses_pgfplots=bool(_AXIS.search(source)))
