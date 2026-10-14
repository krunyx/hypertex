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

구현 메모 (D)
- 우선순위 (낮음 → 높음, pgfmath 와 같은 순서): 비교(< > ==, 왼쪽 결합) < + - < 접미사 r
  < * / < 단항 - < ^ (우결합) < 기본항.
  -x^2 = -(x^2), 2^-1 = 0.5 (지수 자리에 단항 - 허용), 2^3^2 = 2^9.
- 'r' 접미사는 그때까지의 곱셈 항 전체에 붙는다 (pgfmath 의 r 우선순위 600 이 * / 의 700 보다
  낮고 + - 의 500 보다 높음). pi/2 r = (pi/2) r, 2*\\x r = (2*\\x) r, 1 + x r = 1 + (x r),
  x r * 3 = (x r)*3. 곱셈에서는 결과가 같고 나눗셈에서만 차이가 난다.
- 이름: 글자로 시작하고 글자·숫자가 이어진다 (atan2, log10). 곱셈 기호 생략(2x)은 허용하지 않는다.
- 숫자: 123, 1.5, .5, 1e3, 2.5E-4. 지수 표기는 e 뒤에 숫자(부호 허용)가 올 때만.
- Expr.ast: 중첩 튜플 AST
    ("num", float) | ("var", "x"|"y") | ("param", 이름) | ("neg", a) | ("rad", a)
    | ("bin", op, a, b)  op ∈ + - * / ^ < > ==
    | ("call", 함수 이름, (인수, ...))
  Expr.code: 같은 식의 후위(RPN) 명령 목록. evaluate 는 이것을 스택으로 돌리므로 재귀가 없다.
    ("num", v) | ("load", 키) | ("neg",) | ("rad",) | ("bin", op) | ("call", 이름, 인수 개수)
  Expr.variables: 쓴 표본 변수 {"x", "y"}의 부분집합 (\\x 와 x 는 같은 변수 "x").
- evaluate 의 env 키: 표본 변수는 "x", "y", 매개변수는 역슬래시 뺀 이름. 없는 키는 nan.
  결과가 유한하지 않으면(오버플로·nan) nan. 예외를 던지지 않는다.
- 중첩 깊이(괄호·함수 호출·단항 부호·^ 지수를 각각 1단으로) MAX_DEPTH 초과, 토큰 MAX_TOKENS 초과는 expression-syntax.
- 함수 인수 개수: atan2·mod 2개, ifthenelse 3개, min·max 1개 이상, 나머지 1개.
  atan2(y, x) 순서 (PGF 3.0 이후 관례). mod 는 피제수 부호를 따른다 (fmod).
  round 는 0.5에서 0에서 먼 쪽으로. ifthenelse 는 세 인수를 모두 계산한 뒤 고른다(부작용 없음).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

FUNCTIONS = {
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "sinh", "cosh", "tanh",
    "exp", "ln", "log10", "sqrt",
    "abs", "floor", "ceil", "round", "mod", "min", "max", "sign",
    "ifthenelse",
}
CONSTANTS = {"pi", "e"}

MAX_DEPTH = 100
MAX_TOKENS = 100_000

# 인수 개수: (최소, 최대). 최대 None = 제한 없음.
_ARITY = {name: (1, 1) for name in FUNCTIONS}
_ARITY.update({"atan2": (2, 2), "mod": (2, 2), "ifthenelse": (3, 3),
               "min": (1, None), "max": (1, None)})


class ExprError(Exception):
    def __init__(self, message: str, kind: str = "expression-syntax"):
        super().__init__(message)
        assert kind in ("expression-syntax", "unknown-parameter")
        self.kind = kind


@dataclass
class Expr:
    source: str
    params: set[str] = field(default_factory=set)
    # D 추가 필드
    ast: tuple = field(default=("num", math.nan), repr=False, compare=False)
    code: list = field(default_factory=list, repr=False, compare=False)
    variables: set[str] = field(default_factory=set)


# ---------------------------------------------------------------- 토큰화

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<cs>\\[A-Za-z]+|\\.)
  | (?P<id>[A-Za-z][A-Za-z0-9]*)
  | (?P<op>==|[-+*/^(),<>])
""", re.VERBOSE)


def _tokenize(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos, n = 0, len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if m is None:
            raise ExprError(f"계산식에 쓸 수 없는 문자 {text[pos]!r} (위치 {pos})")
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group()))
            if len(out) > MAX_TOKENS:
                raise ExprError("계산식이 너무 깁니다")
        pos = m.end()
    out.append(("end", ""))
    return out


# ---------------------------------------------------------------- 파서

class _Parser:
    def __init__(self, text: str, params: set[str]):
        self.toks = _tokenize(text)
        self.i = 0
        self.params = params
        self.used_params: set[str] = set()
        self.used_vars: set[str] = set()
        self.code: list[tuple] = []
        self.depth = 0

    # 도우미
    def peek(self) -> tuple[str, str]:
        return self.toks[self.i]

    def take(self) -> tuple[str, str]:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect_op(self, op: str) -> None:
        k, v = self.take()
        if k != "op" or v != op:
            shown = v if k != "end" else "식의 끝"
            raise ExprError(f"{op!r} 가 있어야 할 자리에 {shown!r}")

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError(f"계산식 중첩이 {MAX_DEPTH}단을 넘습니다")

    def leave(self) -> None:
        self.depth -= 1

    # 문법
    def parse(self) -> tuple:
        if self.peek()[0] == "end":
            raise ExprError("빈 계산식")
        node = self.comparison()
        k, v = self.peek()
        if k != "end":
            raise ExprError(f"식이 끝나야 할 자리에 {v!r}")
        return node

    def comparison(self) -> tuple:
        node = self.additive()
        while self.peek() in (("op", "<"), ("op", ">"), ("op", "==")):
            op = self.take()[1]
            rhs = self.additive()
            node = ("bin", op, node, rhs)
            self.code.append(("bin", op))
        return node

    def additive(self) -> tuple:
        node = self.multiplicative()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            rhs = self.multiplicative()
            node = ("bin", op, node, rhs)
            self.code.append(("bin", op))
        return node

    def multiplicative(self) -> tuple:
        # 'r' 접미사는 pgfmath 우선순위(600: + 500 과 * 700 사이)를 따라
        # 그때까지의 곱셈 항 전체에 붙는다: pi/2 r = (pi/2) r, 1 + x r = 1 + (x r).
        node = self.unary()
        while True:
            t = self.peek()
            if t == ("id", "r"):
                self.take()
                node = ("rad", node)
                self.code.append(("rad",))
            elif t in (("op", "*"), ("op", "/")):
                op = self.take()[1]
                rhs = self.unary()
                node = ("bin", op, node, rhs)
                self.code.append(("bin", op))
            else:
                return node

    def unary(self) -> tuple:
        t = self.peek()
        if t == ("op", "-") or t == ("op", "+"):
            self.take()
            self.enter()
            try:
                a = self.unary()
            finally:
                self.leave()
            if t[1] == "+":
                return a
            self.code.append(("neg",))
            return ("neg", a)
        return self.power()

    def power(self) -> tuple:
        base = self.primary()
        if self.peek() == ("op", "^"):
            self.take()
            self.enter()
            try:
                exp = self.unary()      # 우결합 + 지수 자리의 단항 -
            finally:
                self.leave()
            self.code.append(("bin", "^"))
            return ("bin", "^", base, exp)
        return base

    def primary(self) -> tuple:
        k, v = self.take()
        if k == "num":
            try:
                x = float(v)
            except ValueError:  # pragma: no cover - 정규식이 막는다
                raise ExprError(f"잘못된 수 {v!r}")
            self.code.append(("num", x))
            return ("num", x)
        if k == "op" and v == "(":
            self.enter()
            try:
                node = self.comparison()
            finally:
                self.leave()
            self.expect_op(")")
            return node
        if k == "cs":
            name = v[1:]
            if name in ("x", "y"):
                self.used_vars.add(name)
                self.code.append(("load", name))
                return ("var", name)
            if name in self.params:
                self.used_params.add(name)
                self.code.append(("load", name))
                return ("param", name)
            raise ExprError(f"선언되지 않은 매개변수 {v}", kind="unknown-parameter")
        if k == "id":
            if self.peek() == ("op", "("):
                if v not in FUNCTIONS:
                    raise ExprError(f"허용되지 않은 함수 {v}()")
                return self.call(v)
            if v in ("x", "y"):
                self.used_vars.add(v)
                self.code.append(("load", v))
                return ("var", v)
            if v == "pi":
                self.code.append(("num", math.pi))
                return ("num", math.pi)
            if v == "e":
                self.code.append(("num", math.e))
                return ("num", math.e)
            if v in FUNCTIONS:
                raise ExprError(f"함수 {v} 뒤에 ( 가 없습니다")
            raise ExprError(f"알 수 없는 이름 {v!r}")
        if k == "end":
            raise ExprError("식이 중간에 끝났습니다")
        raise ExprError(f"값이 있어야 할 자리에 {v!r}")

    def call(self, name: str) -> tuple:
        self.expect_op("(")
        self.enter()
        try:
            args = []
            if self.peek() != ("op", ")"):
                args.append(self.comparison())
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.comparison())
        finally:
            self.leave()
        self.expect_op(")")
        lo, hi = _ARITY[name]
        if len(args) < lo or (hi is not None and len(args) > hi):
            want = f"{lo}" if lo == hi else (f"{lo}개 이상" if hi is None else f"{lo}–{hi}")
            raise ExprError(f"{name}() 인수는 {want}개여야 하는데 {len(args)}개")
        self.code.append(("call", name, len(args)))
        return ("call", name, tuple(args))


def parse(text: str, params: set[str]) -> Expr:
    params = set(params or ())
    try:
        p = _Parser(text, params)
        ast = p.parse()
    except RecursionError:
        raise ExprError("계산식 중첩이 너무 깊습니다") from None
    return Expr(source=text, params=p.used_params, ast=ast, code=p.code,
                variables=p.used_vars)


# ---------------------------------------------------------------- 평가기

_DEG = math.pi / 180.0


def _round_half_away(a: float) -> float:
    return math.copysign(math.floor(abs(a) + 0.5), a)


def _sign(a: float) -> float:
    if math.isnan(a):
        return math.nan
    return 1.0 if a > 0 else (-1.0 if a < 0 else 0.0)


def _mod(a: float, b: float) -> float:
    return math.fmod(a, b)  # b == 0 → ValueError → nan


_FUNC1 = {
    "sin": lambda a: math.sin(a * _DEG),
    "cos": lambda a: math.cos(a * _DEG),
    "tan": lambda a: math.tan(a * _DEG),
    "asin": lambda a: math.degrees(math.asin(a)),
    "acos": lambda a: math.degrees(math.acos(a)),
    "atan": lambda a: math.degrees(math.atan(a)),
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "exp": math.exp,
    "ln": math.log, "log10": math.log10, "sqrt": math.sqrt,
    "abs": abs,
    "floor": lambda a: float(math.floor(a)),
    "ceil": lambda a: float(math.ceil(a)),
    "round": _round_half_away,
    "sign": _sign,
}


def _binop(op: str, a: float, b: float) -> float:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return a / b                    # 0 → ZeroDivisionError → nan
    if op == "^":
        return math.pow(a, b)           # 음수^분수 → ValueError → nan
    if math.isnan(a) or math.isnan(b):
        return math.nan
    if op == "<":
        return 1.0 if a < b else 0.0
    if op == ">":
        return 1.0 if a > b else 0.0
    if op == "==":
        return 1.0 if a == b else 0.0
    raise ValueError(op)


def _call(name: str, args: list[float]) -> float:
    if name in _FUNC1:
        return _FUNC1[name](args[0])
    if name == "atan2":
        return math.degrees(math.atan2(args[0], args[1]))
    if name == "mod":
        return _mod(args[0], args[1])
    if name == "min":
        return math.nan if any(math.isnan(a) for a in args) else min(args)
    if name == "max":
        return math.nan if any(math.isnan(a) for a in args) else max(args)
    if name == "ifthenelse":
        c, a, b = args
        if math.isnan(c):
            return math.nan
        return a if c != 0 else b
    raise ValueError(name)


def evaluate(expr: Expr, env: dict[str, float]) -> float:
    stack: list[float] = []
    try:
        for ins in expr.code:
            op = ins[0]
            if op == "num":
                stack.append(ins[1])
            elif op == "load":
                v = env.get(ins[1], math.nan)
                try:
                    stack.append(float(v))
                except (TypeError, ValueError):
                    stack.append(math.nan)
            elif op == "neg":
                stack[-1] = -stack[-1]
            elif op == "rad":
                stack[-1] = stack[-1] * (180.0 / math.pi)
            elif op == "bin":
                b = stack.pop()
                a = stack.pop()
                stack.append(_binop(ins[1], a, b))
            elif op == "call":
                n = ins[2]
                args = stack[-n:]
                del stack[-n:]
                stack.append(_call(ins[1], args))
        if len(stack) != 1:
            return math.nan
        r = float(stack[0])
    except (ValueError, ZeroDivisionError, OverflowError, TypeError, IndexError):
        return math.nan
    return r if math.isfinite(r) else math.nan
