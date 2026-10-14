"""진단(오류·경고) 수집. 명세 7절.

모든 모듈은 예외를 던져 파싱을 멈추지 말고, 여기에 진단을 남긴 뒤 계속한다.
코드 목록은 schema/document-tree.schema.json 의 Diagnostic.code 와 같아야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Severity = Literal["error", "warning"]

# 스키마의 enum과 동일. 새 코드가 필요하면 스키마를 고치지 말고 보고할 것.
CODES = frozenset({
    "undefined-command", "unbalanced-brace", "unclosed-environment", "math-syntax",
    "broken-ref", "duplicate-label", "macro-recursion", "expansion-limit",
    "excluded-command", "unknown-package", "unknown-tikz-library", "tikz-limit",
    "plot-sample-limit", "data-limit", "insecure-resource", "missing-resource",
    "unknown-parameter", "expression-syntax", "render-timeout",
})

# 기본 심각도. 대부분 error이고, 렌더링 결과에 거의 영향이 없는 것만 warning.
DEFAULT_SEVERITY: dict[str, Severity] = {c: "error" for c in CODES}
DEFAULT_SEVERITY.update({
    "broken-ref": "warning",
    "unknown-package": "warning",
    "unknown-tikz-library": "warning",
    "missing-resource": "warning",
})


@dataclass(frozen=True)
class Span:
    line: int
    col: int
    end_line: Optional[int] = None
    end_col: Optional[int] = None

    def to_json(self) -> dict:
        d = {"line": self.line, "col": self.col}
        if self.end_line is not None:
            d["endLine"] = self.end_line
        if self.end_col is not None:
            d["endCol"] = self.end_col
        return d


@dataclass
class Diagnostic:
    code: str
    message: str
    span: Optional[Span] = None
    node: Optional[str] = None
    severity: Optional[Severity] = None

    def __post_init__(self):
        if self.code not in CODES:
            raise ValueError(f"알 수 없는 진단 코드: {self.code}")
        if self.severity is None:
            self.severity = DEFAULT_SEVERITY[self.code]

    def to_json(self) -> dict:
        d = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.span:
            d["span"] = self.span.to_json()
        if self.node:
            d["node"] = self.node
        return d


@dataclass
class Sink:
    """진단을 모으는 곳. 파서 전체가 하나를 공유한다."""
    items: list[Diagnostic] = field(default_factory=list)

    def add(self, code: str, message: str, span: Optional[Span] = None,
            node: Optional[str] = None, severity: Optional[Severity] = None) -> Diagnostic:
        d = Diagnostic(code, message, span, node, severity)
        self.items.append(d)
        return d

    def to_json(self) -> list[dict]:
        return [d.to_json() for d in self.items]
