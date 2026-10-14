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

구현 메모 (D) — 자세한 가정은 notes/D-questions.md
- TikZ 전체를 파싱하지 않는다. 중괄호·대괄호·괄호 짝을 맞추며 한 번 훑는다. $…$ 와 노드 글(\\node … {글},
  node … {글}, \\addlegendentry{…}, \\legend{…})은 건너뛴다.
- 식 검사 대상: TikZ `plot (…)` 좌표의 각 성분, `\\addplot {…}`·`\\addplot (…)`·`\\addplot expression {…}`,
  옵션의 domain=a:b 양 끝. 일반 좌표 (1,2) 는 식 검사하지 않는다 (단위·calc 문법 때문).
- \\foreach 반복 횟수 = 본문이 실행되는 횟수. 중첩이면 곱한다. 목록 `a,...,b` / `a,b,...,c` 범위를 계산하고,
  값을 알 수 없는 범위(예: 바깥 변수 `0,...,\\i`)는 1회로 센다.
- 경로 요소 = 좌표 ( … ) 수 + 경로 연산(-- |- -| .. rectangle circle ellipse arc grid to node edge coordinate)
  수 + plot 표본 수(상한 1,000으로 자름). \\foreach 본문은 반복 횟수를 곱한다. pgfplots 데이터는 data-limit
  으로 따로 센다.
- tikz-limit 은 원인(foreach, 경로 요소)과 관계없이 그림당 최대 1건.
- plot-sample-limit 은 samples= / samples at= 가 나온 자리마다 1건. data-limit 은 \\addplot 마다 1건.
- 계산식 오류는 식마다 1건. 같은 식에서 여러 성분이 틀려도 성분마다 1건.
- 식 안에서 \\foreach 변수(\\i, count=\\j 등)는 그 본문 안에서 변수로 허용되고 params 에는 넣지 않는다.
- params 에는 식이 참조한 매개변수와 함께 일반 좌표·옵션 값·foreach 목록에 나온 \\<매개변수>도 넣는다
  ($…$ 와 노드 글 안은 제외). 정렬된 목록.
- 보안상 `\\addplot gnuplot/shell`, TikZ `plot function {…}`(gnuplot 호출)도 excluded-command 로 낸다.
- 어떤 입력에도 예외를 던지지 않는다. 내부 오류가 나면 그때까지의 결과를 돌려준다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import expr as _expr
from .diagnostics import Sink, Span

ALLOWED_LIBRARIES = {"arrows.meta", "calc", "positioning"}

LIMITS = {"foreach": 1_000, "samples": 1_000, "path_elements": 10_000, "data_points": 10_000}

DEFAULT_SAMPLES = 25          # TikZ·pgfplots 기본값
_MAX_FOREACH_NEST = 32        # 이보다 깊은 \foreach 중첩은 본문에 반복 수를 곱하지 않고 평평하게 훑는다
_MULT_CAP = 10 ** 12          # 곱셈 폭주 방지


@dataclass
class PictureInfo:
    uses_pgfplots: bool = False
    params: list[str] = field(default_factory=list)


_AXIS = re.compile(r"\\begin\s*\{(axis|semilogxaxis|semilogyaxis|loglogaxis)\}")
_AXIS_ENVS = {"axis", "semilogxaxis", "semilogyaxis", "loglogaxis"}

_PATH_OPS_WORDS = {"rectangle", "circle", "ellipse", "arc", "grid", "to", "node", "edge",
                   "coordinate", "pic"}
_NODE_CS = {"node", "coordinate", "matrix", "pic"}
_TEXT_ARG_CS = {"addlegendentry", "legend", "caption", "label", "text", "textbf", "emph"}
_UNIT = re.compile(r"\s*(pt|cm|mm|in|ex|em|bp|pc|dd|cc|sp)\s*$")
_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def check_picture(source: str, params: set[str], span: Span, sink: Sink) -> PictureInfo:
    source = source or ""
    params = set(params or ())
    c = _Checker(source, params, span, sink)
    try:
        c.run()
    except Exception:  # noqa: BLE001 - 계약: 예외로 멈추지 않는다
        pass
    try:
        c.finish()
    except Exception:  # noqa: BLE001
        pass
    uses = c.uses_pgfplots or bool(_AXIS.search(source))
    return PictureInfo(uses_pgfplots=uses, params=sorted(c.found_params))


# ---------------------------------------------------------------- 짝 맞추기 도우미

def _skip_escape(s: str, i: int) -> int:
    """s[i] == '\\' 일 때 제어 시퀀스 다음 위치."""
    j = i + 1
    if j < len(s) and s[j].isalpha():
        while j < len(s) and s[j].isalpha():
            j += 1
        return j
    return min(j + 1, len(s))


def _match_group(s: str, i: int, end: int, open_ch: str, close_ch: str) -> int:
    """s[i] == open_ch. 짝이 되는 close_ch 다음 위치. 짝이 없으면 end.

    중괄호 안의 open/close 문자는 세지 않는다 (open_ch 가 '{' 일 때는 중괄호만 센다).
    """
    depth = 0       # open/close 깊이
    brace = 0       # 중괄호 깊이 (open_ch 가 '{' 가 아닐 때)
    j = i
    while j < end:
        ch = s[j]
        if ch == "\\":
            j = _skip_escape(s, j)
            continue
        if ch == "%":
            nl = s.find("\n", j, end)
            j = end if nl < 0 else nl + 1
            continue
        if open_ch != "{":
            if ch == "{":
                brace += 1
            elif ch == "}":
                if brace > 0:
                    brace -= 1
                else:
                    return end   # 바깥 그룹이 먼저 닫혔다 → 짝 없음
            elif brace == 0:
                if ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        return j + 1
        else:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return j + 1
        j += 1
    return end


def _split_top(text: str, sep: str = ",") -> list[str]:
    """괄호·중괄호·대괄호 바깥의 sep 로 나눈다."""
    parts, depth, cur = [], 0, []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            j = _skip_escape(text, i)
            cur.append(text[i:j])
            i = j
            continue
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _strip_braces(t: str) -> str:
    t = t.strip()
    while len(t) >= 2 and t[0] == "{" and _match_group(t, 0, len(t), "{", "}") == len(t):
        t = t[1:-1].strip()
    return t


def _parse_keyvals(text: str) -> list[tuple[str, str | None]]:
    out = []
    for part in _split_top(text, ","):
        part = part.strip()
        if not part:
            continue
        depth, eq = 0, -1
        for k, ch in enumerate(part):
            if ch in "{([":
                depth += 1
            elif ch in "})]":
                depth -= 1
            elif ch == "=" and depth == 0:
                eq = k
                break
        if eq < 0:
            out.append((" ".join(part.split()), None))
        else:
            out.append((" ".join(part[:eq].split()), part[eq + 1:].strip()))
    return out


def _strip_math(t: str) -> str:
    return re.sub(r"\$[^$]*\$?", " ", t)


# ---------------------------------------------------------------- 검사기

class _Checker:
    def __init__(self, s: str, params: set[str], span: Span, sink: Sink):
        self.s = s
        self.params = params
        self.span = span
        self.sink = sink
        self.uses_pgfplots = False
        self.found_params: set[str] = set()
        self.foreach_total = 0
        self.tikz_limit_reported = False
        self.elements = 0
        self.nest = 0

    # 진단
    def diag(self, code: str, msg: str) -> None:
        if code == "tikz-limit":
            if self.tikz_limit_reported:
                return
            self.tikz_limit_reported = True
        self.sink.add(code, msg, self.span)

    def add_elements(self, n: int, mult: int) -> None:
        self.elements = min(self.elements + n * mult, _MULT_CAP)

    # 매개변수 참조 (식이 아닌 자리)
    def note_refs(self, text: str, scope: frozenset) -> None:
        for m in re.finditer(r"\\([A-Za-z]+)", _strip_math(text)):
            name = m.group(1)
            if name in self.params and name not in scope:
                self.found_params.add(name)

    # 식 검사
    def check_expr(self, text: str, scope: frozenset, what: str) -> None:
        text = text.strip()
        try:
            e = _expr.parse(text, self.params | scope)
        except _expr.ExprError as err:
            self.sink.add(err.kind, f"{what} {text!r}: {err}", self.span)
            return
        except Exception as err:  # noqa: BLE001
            self.sink.add("expression-syntax", f"{what} {text!r}: {err}", self.span)
            return
        self.found_params |= (e.params - scope)

    def check_coord_exprs(self, inner: str, scope: frozenset, what: str) -> None:
        """plot ( … ) 안: 'a, b' 또는 극좌표 'a:b'. 성분마다 식 검사."""
        parts = _split_top(inner, ",")
        if len(parts) == 1:
            parts = _split_top(inner, ":")
        for p in parts:
            raw = p.strip()
            braced = raw.startswith("{")
            t = _strip_braces(raw)
            if not braced:
                t = _UNIT.sub("", t)
            self.check_expr(t, scope, what)

    def eval_number(self, text: str, scope: frozenset) -> float | None:
        t = _strip_braces(text)
        if _NUM.match(t):
            return float(t)
        try:
            e = _expr.parse(t, self.params | scope)
        except Exception:  # noqa: BLE001
            return None
        if e.params or e.variables:
            return None
        v = _expr.evaluate(e, {})
        return None if math.isnan(v) else v

    # 옵션 [ … ]
    def handle_options(self, inner: str, scope: frozenset) -> int | None:
        """옵션을 읽고 그 안의 samples 값을 돌려준다 (없으면 None)."""
        samples = None
        for key, val in _parse_keyvals(inner):
            if val is None:
                continue
            k = key.lstrip("/").split("/")[-1]
            if k == "samples":
                n = self.eval_number(val, scope)
                if n is not None:
                    samples = n
                    if n > LIMITS["samples"]:
                        self.diag("plot-sample-limit",
                                  f"samples={val} 가 상한 {LIMITS['samples']:,}을 넘습니다")
                else:
                    self.note_refs(val, scope)
            elif k == "samples at":
                n = self.count_list(_strip_braces(val), scope)
                samples = n
                if n > LIMITS["samples"]:
                    self.diag("plot-sample-limit",
                              f"samples at 의 점 {n:,}개가 상한 {LIMITS['samples']:,}을 넘습니다")
            elif k == "domain" or k == "y domain":
                ends = _split_top(_strip_braces(val), ":")
                if len(ends) == 2:
                    for t in ends:
                        self.check_expr(_strip_braces(t), scope, "domain")
                else:
                    self.sink.add("expression-syntax", f"domain={val!r} 는 a:b 꼴이어야 합니다",
                                  self.span)
            else:
                self.note_refs(val, scope)
        return samples

    # \foreach 목록 세기
    def count_list(self, inner: str, scope: frozenset) -> int:
        items = [x.strip() for x in _split_top(inner, ",")]
        items = [x for x in items if x != ""]
        if not items:
            return 0
        self.note_refs(inner, scope)
        count = 0
        i = 0
        while i < len(items):
            if items[i] == "..." and i > 0 and i + 1 < len(items):
                # 범위: 앞 원소(들)와 끝
                endv = self.item_value(items[i + 1], scope)
                startv = self.item_value(items[i - 1], scope)
                step = None
                if i >= 2:
                    a = self.item_value(items[i - 2], scope)
                    if a is not None and startv is not None:
                        step = startv - a
                if startv is None or endv is None:
                    n_more = 1        # 값을 알 수 없으면 1회
                else:
                    if step is None:
                        step = 1.0 if endv >= startv else -1.0
                    if step == 0 or (endv - startv) * step < 0:
                        n_more = 1 if step == 0 else 0
                        if step == 0:
                            n_more = _MULT_CAP   # TeX 에서는 끝나지 않는 반복
                    else:
                        q = (endv - startv) / step
                        n_more = int(min(math.floor(q + 1e-9), _MULT_CAP)) + 1
                # 앞 원소(start)는 이미 셌다. 끝 원소까지 포함한 나머지.
                count += max(n_more - 1, 0)
                i += 2
                continue
            if items[i] != "...":
                count += 1
            i += 1
        return min(count, _MULT_CAP)

    def item_value(self, item: str, scope: frozenset) -> float | None:
        t = _strip_braces(item)
        if "/" in t:
            t = t.split("/")[0].strip()
        if len(t) == 1 and t.isalpha():
            return float(ord(t))
        return self.eval_number(t, scope)

    # 훑기 -----------------------------------------------------------
    def run(self) -> None:
        self.scan(0, len(self.s), 1, frozenset())

    def finish(self) -> None:
        if self.foreach_total > LIMITS["foreach"]:
            self.diag("tikz-limit",
                      f"\\foreach 반복 {self.foreach_total:,}회가 그림당 상한 "
                      f"{LIMITS['foreach']:,}회를 넘습니다")
        if self.elements > LIMITS["path_elements"]:
            self.diag("tikz-limit",
                      f"경로 요소 약 {self.elements:,}개가 그림당 상한 "
                      f"{LIMITS['path_elements']:,}개를 넘습니다")

    def skip_ws(self, i: int, end: int) -> int:
        s = self.s
        while i < end:
            if s[i].isspace():
                i += 1
            elif s[i] == "%":
                nl = s.find("\n", i, end)
                i = end if nl < 0 else nl + 1
            else:
                break
        return i

    def word_at(self, i: int, end: int) -> tuple[str, int]:
        j = i
        while j < end and self.s[j].isalpha():
            j += 1
        return self.s[i:j], j

    def scan(self, i: int, end: int, mult: int, scope: frozenset) -> None:
        s = self.s
        stmt_samples: float | None = None
        while i < end:
            ch = s[i]
            if ch == "%":
                nl = s.find("\n", i, end)
                i = end if nl < 0 else nl + 1
            elif ch == "$":
                j = s.find("$", i + 1, end)
                i = end if j < 0 else j + 1
            elif ch == "\\":
                i = self.handle_cs(i, end, mult, scope)
            elif ch == "[":
                j = _match_group(s, i, end, "[", "]")
                smp = self.handle_options(s[i + 1:j - 1] if j <= end and s[j - 1:j] == "]"
                                          else s[i + 1:j], scope)
                if smp is not None:
                    stmt_samples = smp
                i = j
            elif ch == "(":
                j = _match_group(s, i, end, "(", ")")
                self.note_refs(s[i + 1:j], scope)
                self.add_elements(1, mult)
                i = j
            elif ch == ";":
                stmt_samples = None
                i += 1
            elif ch.isalpha():
                w, j = self.word_at(i, end)
                if w == "plot":
                    i = self.handle_plot(j, end, mult, scope, stmt_samples)
                elif w == "foreach":
                    i = self.handle_foreach(j, end, mult, scope)
                elif w in ("node", "pic", "coordinate"):
                    self.add_elements(1, mult)
                    i = self.handle_node(j, end, mult, scope)
                elif w in _PATH_OPS_WORDS:
                    self.add_elements(1, mult)
                    i = j
                else:
                    i = j
            elif s.startswith("--", i) or s.startswith("|-", i) or s.startswith("-|", i) \
                    or s.startswith("..", i):
                self.add_elements(1, mult)
                i += 2
            else:
                i += 1

    def handle_cs(self, i: int, end: int, mult: int, scope: frozenset) -> int:
        s = self.s
        j = _skip_escape(s, i)
        name = s[i + 1:j]
        if not name.isalpha():
            return j
        if name == "addplot":
            if j < end and s[j] == "3":
                self.diag("excluded-command", "\\addplot3 (3D 그래프)은 1.0 범위 밖입니다")
                return self.skip_statement(j + 1, end)
            return self.handle_addplot(j, end, scope)
        if name == "pgfmathdeclarefunction":
            self.diag("excluded-command", "\\pgfmathdeclarefunction 은 허용되지 않습니다")
            return self.skip_args(j, end, 3)
        if name.startswith("pgfkeys"):
            self.diag("excluded-command", f"\\{name} (pgfkeys 직접 조작)은 허용되지 않습니다")
            return self.skip_args(j, end, 3 if name != "pgfkeys" else 1)
        if "externalize" in name:
            self.diag("excluded-command", f"\\{name} (externalize)은 허용되지 않습니다")
            return self.skip_args(j, end, 2)
        if name == "foreach":
            return self.handle_foreach(j, end, mult, scope)
        if name in _NODE_CS:
            self.add_elements(1, mult)
            return self.handle_node(j, end, mult, scope)
        if name in _TEXT_ARG_CS:
            return self.skip_args(j, end, 1)
        if name in ("tikzset", "pgfplotsset"):
            k = self.skip_ws(j, end)
            if k < end and s[k] == "{":
                g = _match_group(s, k, end, "{", "}")
                inner = s[k + 1:g - 1] if s[g - 1:g] == "}" else s[k + 1:g]
                self.handle_options(inner, scope)
                return g
            return j
        if name == "begin" or name == "end":
            k = self.skip_ws(j, end)
            if k < end and s[k] == "{":
                g = _match_group(s, k, end, "{", "}")
                env = s[k + 1:g - 1].strip()
                if name == "begin" and env in _AXIS_ENVS:
                    self.uses_pgfplots = True
                return g
            return j
        if name in self.params and name not in scope:
            self.found_params.add(name)
        return j

    def skip_args(self, i: int, end: int, n: int) -> int:
        """[옵션]과 {인수}를 최대 n개 건너뛴다."""
        s = self.s
        k = i
        got = 0
        while got < n:
            k2 = self.skip_ws(k, end)
            if k2 < end and s[k2] == "[":
                k = _match_group(s, k2, end, "[", "]")
                continue
            if k2 < end and s[k2] == "{":
                k = _match_group(s, k2, end, "{", "}")
                got += 1
                continue
            break
        return k

    def skip_statement(self, i: int, end: int) -> int:
        """다음 깊이 0의 ';' 다음 위치."""
        s = self.s
        k = i
        while k < end:
            ch = s[k]
            if ch == "\\":
                k = _skip_escape(s, k)
            elif ch == "{":
                k = _match_group(s, k, end, "{", "}")
            elif ch == ";":
                return k + 1
            elif ch == "}":
                return k     # 바깥 그룹이 닫힘
            else:
                k += 1
        return end

    def handle_node(self, i: int, end: int, mult: int, scope: frozenset) -> int:
        """node [opts] (name) at (coord) {text} — 글은 건너뛴다."""
        s = self.s
        k = i
        for _ in range(8):
            k = self.skip_ws(k, end)
            if k >= end:
                return end
            ch = s[k]
            if ch == "[":
                g = _match_group(s, k, end, "[", "]")
                self.handle_options(s[k + 1:g - 1], scope)
                k = g
            elif ch == "(":
                g = _match_group(s, k, end, "(", ")")
                self.note_refs(s[k + 1:g], scope)
                k = g
            elif ch == "{":
                return _match_group(s, k, end, "{", "}")
            elif s.startswith("at", k) and not s[k + 2:k + 3].isalpha():
                k += 2
            else:
                return k
        return k

    # plot ------------------------------------------------------------
    def handle_plot(self, i: int, end: int, mult: int, scope: frozenset,
                    stmt_samples: float | None) -> int:
        s = self.s
        samples = stmt_samples
        k = self.skip_ws(i, end)
        while k < end and s[k] == "[":
            g = _match_group(s, k, end, "[", "]")
            smp = self.handle_options(s[k + 1:g - 1], scope)
            if smp is not None:
                samples = smp
            k = self.skip_ws(g, end)
        if k >= end:
            return end
        if s[k] == "(":
            g = _match_group(s, k, end, "(", ")")
            closed = s[g - 1:g] == ")" and g > k + 1
            inner = s[k + 1:g - 1] if closed else s[k + 1:g]
            if not closed:
                self.sink.add("expression-syntax", f"plot 좌표 ( … 가 닫히지 않았습니다", self.span)
            else:
                self.check_coord_exprs(inner, scope, "plot 좌표식")
            n = samples if samples is not None else DEFAULT_SAMPLES
            self.add_elements(int(min(max(n, 0), LIMITS["samples"])), mult)
            return g
        w, j = self.word_at(k, end)
        if w == "coordinates":
            k = self.skip_ws(j, end)
            if k < end and s[k] == "{":
                g = _match_group(s, k, end, "{", "}")
                self.add_elements(self.count_points(s[k + 1:g - 1], scope), mult)
                return g
            return j
        if w == "function":
            self.diag("excluded-command", "plot function (gnuplot 호출)은 허용되지 않습니다")
            return self.skip_args(j, end, 1)
        if w == "file":
            return self.skip_args(j, end, 1)
        return k

    def count_points(self, inner: str, scope: frozenset) -> int:
        n = 0
        k, end = 0, len(inner)
        while k < end:
            ch = inner[k]
            if ch == "(":
                g = _match_group(inner, k, end, "(", ")")
                self.note_refs(inner[k + 1:g], scope)
                n += 1
                k = g
            elif ch == "\\":
                k = _skip_escape(inner, k)
            else:
                k += 1
        return n

    # \addplot ----------------------------------------------------------
    def handle_addplot(self, i: int, end: int, scope: frozenset) -> int:
        s = self.s
        k = self.skip_ws(i, end)
        if k < end and s[k] == "+":
            k = self.skip_ws(k + 1, end)
        while k < end and s[k] == "[":
            g = _match_group(s, k, end, "[", "]")
            self.handle_options(s[k + 1:g - 1], scope)
            k = self.skip_ws(g, end)
        if k >= end:
            return end
        ch = s[k]
        if ch == "{":
            g = _match_group(s, k, end, "{", "}")
            if s[g - 1:g] != "}":
                self.sink.add("expression-syntax", "\\addplot { … 가 닫히지 않았습니다", self.span)
                return g
            self.check_expr(s[k + 1:g - 1], scope, "\\addplot 식")
            return g
        if ch == "(":
            g = _match_group(s, k, end, "(", ")")
            if s[g - 1:g] != ")":
                self.sink.add("expression-syntax", "\\addplot ( … 가 닫히지 않았습니다", self.span)
                return g
            self.check_coord_exprs(s[k + 1:g - 1], scope, "\\addplot 매개변수식")
            return g
        w, j = self.word_at(k, end)
        if w == "coordinates":
            k2 = self.skip_ws(j, end)
            if k2 < end and s[k2] == "{":
                g = _match_group(s, k2, end, "{", "}")
                n = self.count_points(s[k2 + 1:g - 1], scope)
                self.check_data(n, "coordinates")
                return g
            return j
        if w == "table":
            k2 = self.skip_ws(j, end)
            while k2 < end and s[k2] == "[":
                g = _match_group(s, k2, end, "[", "]")
                k2 = self.skip_ws(g, end)
            if k2 < end and s[k2] == "{":
                g = _match_group(s, k2, end, "{", "}")
                n = self.count_table_rows(s[k2 + 1:g - 1])
                if n is not None:
                    self.check_data(n, "table")
                return g
            return k2
        if w == "expression":
            k2 = self.skip_ws(j, end)
            if k2 < end and s[k2] == "{":
                g = _match_group(s, k2, end, "{", "}")
                self.check_expr(s[k2 + 1:g - 1], scope, "\\addplot 식")
                return g
            return j
        if w in ("gnuplot", "shell"):
            self.diag("excluded-command", f"\\addplot {w} 는 허용되지 않습니다")
            return self.skip_statement(j, end)
        return k

    def check_data(self, n: int, what: str) -> None:
        if n > LIMITS["data_points"]:
            self.diag("data-limit",
                      f"{what} 데이터 {n:,}점이 그래프 상한 {LIMITS['data_points']:,}점을 넘습니다")

    @staticmethod
    def count_table_rows(inner: str) -> int | None:
        """인라인 표의 데이터 행 수. 파일 이름 하나뿐이면 None."""
        text = inner.replace("\\\\", "\n")
        lines = [ln.split() for ln in text.split("\n")]
        lines = [ln for ln in lines if ln]
        if not lines:
            return 0
        if len(lines) == 1:
            toks = lines[0]
            if len(toks) == 1 and not _NUM.match(toks[0]):
                return None   # 외부 파일 이름
            # 줄바꿈이 사라진 경우: 머리글 열 수로 나눈다 (머리글이 없으면 2열 가정)
            ncols = 0
            while ncols < len(toks) and not _NUM.match(toks[ncols]):
                ncols += 1
            data = len(toks) - ncols
            cols = ncols if ncols > 0 else 2
            return math.ceil(data / cols)
        header = 1 if any(not _NUM.match(t) for t in lines[0]) else 0
        return len(lines) - header

    # \foreach ----------------------------------------------------------
    def handle_foreach(self, i: int, end: int, mult: int, scope: frozenset) -> int:
        s = self.s
        k = self.skip_ws(i, end)
        names: set[str] = set()
        # 변수: \a/\b/...
        while k < end:
            if s[k] == "\\":
                j = _skip_escape(s, k)
                names.add(s[k + 1:j])
                k = self.skip_ws(j, end)
                if k < end and s[k] == "/":
                    k = self.skip_ws(k + 1, end)
                    continue
            break
        # 옵션: count=\j, evaluate=\i as \k using ..., remember=\i as \k
        while k < end and s[k] == "[":
            g = _match_group(s, k, end, "[", "]")
            opt = s[k + 1:g - 1]
            for m in re.finditer(r"(?:count\s*=\s*|\bas\s*)\\([A-Za-z]+)", opt):
                names.add(m.group(1))
            k = self.skip_ws(g, end)
        inner_scope = scope | frozenset(names)
        w, j = self.word_at(k, end)
        if w != "in":
            return k     # 형식이 이상하면 그대로 계속 훑는다
        k = self.skip_ws(j, end)
        if k < end and s[k] == "{":
            g = _match_group(s, k, end, "{", "}")
            n = self.count_list(s[k + 1:g - 1], scope)
            k = g
        elif k < end and s[k] == "\\":
            g = _skip_escape(s, k)   # 목록이 매크로 하나: 알 수 없음 → 1회
            self.note_refs(s[k:g], scope)
            n = 1
            k = g
        else:
            n = 1
        times = min(mult * n, _MULT_CAP)
        self.foreach_total = min(self.foreach_total + times, _MULT_CAP)
        k = self.skip_ws(k, end)
        if k >= end:
            return end
        if self.nest >= _MAX_FOREACH_NEST:
            # 너무 깊은 중첩: 본문을 따로 훑지 않고 바깥 훑기가 그대로 지나가게 한다 (선형 시간 유지)
            return k
        body_mult = times
        self.nest += 1
        try:
            if s[k] == "{":
                g = _match_group(s, k, end, "{", "}")
                self.scan(k + 1, g - 1 if s[g - 1:g] == "}" else g, body_mult, inner_scope)
                return g
            if s.startswith("\\foreach", k):
                return self.handle_foreach(k + len("\\foreach"), end, body_mult, inner_scope)
            w2, j2 = self.word_at(k, end)
            if w2 == "foreach":
                return self.handle_foreach(j2, end, body_mult, inner_scope)
            g = self.skip_statement(k, end)
            self.scan(k, g, body_mult, inner_scope)
            return g
        finally:
            self.nest -= 1
