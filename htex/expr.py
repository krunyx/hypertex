"""계산식 파서와 평가기 (명세 3.2절 "계산식 문법"). (담당: D)

슬라이더 값을 쓰는 식, TikZ plot, pgfplots \\addplot 식이 모두 이것을 쓴다.
반복·대입·사용자 함수 없음 → 항상 종료.

계약
- parse(text, params) -> Expr. 문법 오류나 허용되지 않은 함수면 ExprError.
  * 변수: \\x, \\y (TikZ), x, y (pgfplots), 그리고 \\<매개변수 이름> (예: \\omega).
  * \\<이름>이 params에 없고 \\x·\\y도 아니면 ExprError(kind="unknown-parameter").
  * 그 외 오류는 ExprError(kind="expression-syntax").
- 함수: FUNCTIONS. 상수: pi, e. 연산: + - * / ^ (우결합), 단항 -, 괄호, < > == (참=1, 거짓=0),
  ifthenelse(c, a, b).
- 각도: 삼각함수 인수는 기본 도(degree). 바로 뒤 'r' 접미사(예: \\x r, (2*x) r)는 라디안으로
  표시한다 = 값에 180/pi 를 곱해 도로 바꾼다. 역삼각함수는 도를 돌려준다 (TikZ 관례).
- evaluate(expr, env) -> float. 정의역 밖(ln(-1), 0으로 나누기 등)은 math.nan.
- Expr.params: 식이 참조한 매개변수 이름 집합 (역슬래시 제외).
"""
from __future__ import annotations

from dataclasses import dataclass, field

FUNCTIONS = {
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "sinh", "cosh", "tanh",
    "exp", "ln", "log10", "sqrt",
    "abs", "floor", "ceil", "round", "mod", "min", "max", "sign",
    "ifthenelse",
}
CONSTANTS = {"pi", "e"}


class ExprError(Exception):
    def __init__(self, message: str, kind: str = "expression-syntax"):
        super().__init__(message)
        assert kind in ("expression-syntax", "unknown-parameter")
        self.kind = kind


@dataclass
class Expr:
    source: str
    params: set[str] = field(default_factory=set)
    # D가 내부 표현(AST)을 자유롭게 추가한다


def parse(text: str, params: set[str]) -> Expr:
    raise NotImplementedError("D가 구현")


def evaluate(expr: Expr, env: dict[str, float]) -> float:
    raise NotImplementedError("D가 구현")
