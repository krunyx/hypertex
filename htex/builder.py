"""토큰 → 문서 트리 (명세 2, 3, 5, 6, 7, 9절). (담당: C)

0단계 상태: 빈 본문을 가진, 스키마에 맞는 최소 트리만 낸다. C가 채운다.

계약
- 입력: Expander가 확장을 끝낸 토큰 목록 (\\newcommand 정의는 이미 사라짐).
- 출력: schema/document-tree.schema.json 을 만족하는 dict. diagnostics 는 비워 두고
  (parser.py가 sink에서 채운다) 진단은 ctx.sink.add 로만 남긴다.
- 노드 id는 문서 순서대로 n1, n2, … (ctx.new_id()).
- 번호 규칙은 README "테스트가 가정하는 번호 규칙"과 스타일 파일(equation.number)을 따른다.
- 수식은 detokenize 로 math.tex 를 만들고, scripts 에 쓰인 문자 체계를 적는다
  (ASCII 글자 → latin, 그리스 문자 명령 → greek, 한글 음절 → hangul).
- tikzpicture 는 detokenize 한 원문을 picture.check_picture 에 넘기고 결과로 picture 노드를 만든다.
- \\usetikzlibrary 의 허용 목록 밖 라이브러리는 unknown-tikz-library (경고).
- 오류 관용: 어떤 입력에도 예외 없이 끝까지 트리를 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .diagnostics import Sink
from .loader import Loader
from .tokens import Token


@dataclass
class BuildContext:
    sink: Sink
    loader: Loader
    mode: str = "native"          # "native" | "compat"
    source_url: str = ""
    _next_id: int = field(default=0, repr=False)

    def new_id(self) -> str:
        self._next_id += 1
        return f"n{self._next_id}"


def build(tokens: list[Token], ctx: BuildContext) -> dict[str, Any]:
    """0단계: 최소 트리."""
    return {
        "hypertex": "2.0",
        "meta": {"documentclass": "hypertex"},
        "labels": {},
        "parameters": [],
        "bibliography": [],
        "body": [],
        "diagnostics": [],
    }
