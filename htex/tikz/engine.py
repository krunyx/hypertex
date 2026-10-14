"""TikZ 부분집합 실행기: 문장 → 경로·노드 → 캔버스. (담당: H)

흐름: Engine.run() 이 원문을 문장 단위로 훑는다(run_block). 경로 문장(\\draw 등)은 PathBuilder 가
세그먼트로 만들고 Engine.emit_path 가 SVG 로 낸다. 노드는 place_node, pgfplots 는 axis.render_axis.

- \\foreach 는 TikZ 처럼 변수를 글자 그대로 바꿔 넣은 본문을 반복 실행한다 (그림 전체 1,000회 상한).
- 계산식은 htex.expr.parse / evaluate (eval 없음). 매개변수 \\이름 은 values 로 평가.
- 시간 상한(기본 1초)을 넘거나 경로 요소가 10,000개를 넘으면 _Stop 으로 멈추고 그때까지 그린 것을 낸다.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from .. import expr as _expr
from . import geometry as G
from .scan import (find_top, group, keyvals, match, skip_ws, split_top, statement_end, strip_braces,
                   substitute)
from .styles import (CM_PX, DIRECTIONS, EM, PT, Style, StyleApplier, css_color, mat_apply, mat_linear,
                     parse_dim, tip_kind, unit_suffix, UNITS)
from .svg import Canvas, att, esc, has_math, measure, num, parse_node_text, path_d, px, py, FONT_PX, \
    MATHML_NS, XHTML_NS

LIMIT_FOREACH = 1_000
LIMIT_SAMPLES = 1_000
LIMIT_ELEMENTS = 10_000
LIMIT_DATA = 10_000
MAX_DEPTH = 40


class _Stop(Exception):
    """시간·요소 상한: 그리기를 멈춘다 (그때까지 그린 것은 남김)."""


_NUM_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
_PATH_CMDS = {"draw", "fill", "filldraw", "path", "clip", "shade", "shadedraw", "pattern"}
_AXIS_ENVS = {"axis", "semilogxaxis", "semilogyaxis", "loglogaxis"}
_IGNORED_CMDS = {"usetikzlibrary", "usepgfplotslibrary", "pgfplotsset", "tikzexternalize",
                 "centering", "small", "footnotesize", "scriptsize", "tiny", "large", "relax",
                 "pgfdeclarelayer", "pgfsetlayers", "begin", "end"}


# ====================================================================== 노드 기하
@dataclass
class NodeGeom:
    center: tuple
    hw: float
    hh: float
    shape: str = "rectangle"

    def offset(self, anchor: str) -> tuple:
        a = (anchor or "center").strip()
        if a in ("center", "mid", "text", "base"):
            if a == "base":
                return (0.0, -self.hh * 0.45)
            return (0.0, 0.0)
        if a in ("mid west", "base west"):
            a = "west"
        if a in ("mid east", "base east"):
            a = "east"
        comp = {"north": 90, "south": 270, "east": 0, "west": 180, "north east": 45, "north west": 135,
                "south east": 315, "south west": 225}
        if self.shape == "coordinate" or (self.hw == 0 and self.hh == 0):
            return (0.0, 0.0)
        if a in comp:
            if self.shape in ("circle", "ellipse"):
                t = math.radians(comp[a])
                return (self.hw * math.cos(t), self.hh * math.sin(t))
            sx = {"east": 1, "west": -1}.get(a.split()[-1], 0)
            sy = {"north": 1, "south": -1}.get(a.split()[0], 0)
            return (sx * self.hw, sy * self.hh)
        try:
            ang = float(a)
        except ValueError:
            return (0.0, 0.0)
        return self.border_dir(math.radians(ang))

    def anchor(self, name: str) -> tuple:
        o = self.offset(name)
        return (self.center[0] + o[0], self.center[1] + o[1])

    def border_dir(self, t: float) -> tuple:
        """중심에서 각 t(라디안) 방향 경계까지의 변위."""
        c, s = math.cos(t), math.sin(t)
        if self.shape == "coordinate":
            return (0.0, 0.0)
        if self.shape in ("circle", "ellipse"):
            a, b = self.hw, self.hh
            if a <= 0 or b <= 0:
                return (0.0, 0.0)
            k = 1 / math.sqrt((c / a) ** 2 + (s / b) ** 2)
            return (k * c, k * s)
        kx = self.hw / abs(c) if abs(c) > 1e-12 else math.inf
        ky = self.hh / abs(s) if abs(s) > 1e-12 else math.inf
        k = min(kx, ky)
        if not math.isfinite(k):
            k = 0.0
        return (k * c, k * s)

    def border_toward(self, p: tuple) -> tuple:
        d = (p[0] - self.center[0], p[1] - self.center[1])
        if math.hypot(*d) < 1e-9:
            return self.center
        o = self.border_dir(math.atan2(d[1], d[0]))
        return (self.center[0] + o[0], self.center[1] + o[1])


@dataclass
class Pt:
    p: tuple
    node: Optional[NodeGeom] = None


# ====================================================================== 엔진
class Engine:
    def __init__(self, source: str, values: Optional[dict[str, float]], *, time_limit: float = 1.0,
                 id_prefix: str = "t"):
        self.source = source or ""
        self.values: dict[str, float] = {}
        for k, v in (values or {}).items():
            try:
                self.values[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        self.param_names = set(self.values)
        self.problems: list[str] = []
        self._seen_problems: set[str] = set()
        self.deadline = time.monotonic() + time_limit
        self.canvas = Canvas(id_prefix)
        self.applier = StyleApplier(self)
        self.nodes: dict[str, NodeGeom] = {}
        self.foreach_count = 0
        self.foreach_over = False
        self.elements = 0
        self.expr_cache: dict[tuple, Any] = {}
        self.axis_map = None              # pgfplots 안: (x, y) → 캔버스
        self.axis_count = 0
        self.depth = 0
        self.stopped = False

    # ------------------------------------------------------------ 공통
    def problem(self, msg: str) -> None:
        if msg not in self._seen_problems and len(self.problems) < 50:
            self._seen_problems.add(msg)
            self.problems.append(msg)

    def tick(self) -> None:
        if time.monotonic() >= self.deadline:   # >= : 윈도 시계는 15ms 단위라 0초 상한에서 같을 수 있다
            self.problem("시간 상한(1초)을 넘어 그때까지 그린 것만 보인다")
            raise _Stop()

    def count(self, n: int = 1) -> None:
        self.elements += n
        if self.elements > LIMIT_ELEMENTS:
            self.problem(f"경로 요소가 {LIMIT_ELEMENTS:,}개를 넘어 나머지는 그리지 않았다")
            raise _Stop()

    # ------------------------------------------------------------ 계산식
    def compile(self, text: str, extra: tuple = ()) -> Optional[_expr.Expr]:
        key = (text, extra)
        if key in self.expr_cache:
            return self.expr_cache[key]
        try:
            e = _expr.parse(text, self.param_names | set(extra))
        except _expr.ExprError as ex:
            self.problem(f"계산식 오류: {text.strip()[:60]} ({ex})")
            e = None
        except Exception:  # noqa: BLE001
            self.problem(f"계산식 오류: {text.strip()[:60]}")
            e = None
        if len(self.expr_cache) < 5000:
            self.expr_cache[key] = e
        return e

    def vars_env(self, **kw) -> dict:
        d = dict(self.values)
        d.update(kw)
        return d

    def number(self, text: Optional[str]) -> Optional[float]:
        if text is None:
            return None
        t = strip_braces(text)
        if not t:
            return None
        if _NUM_RE.match(t):
            v = float(t)
            return v if math.isfinite(v) else None
        e = self.compile(t)
        if e is None:
            return None
        v = _expr.evaluate(e, self.vars_env())
        return v if math.isfinite(v) else None

    def length(self, text: Optional[str], unit: str = "cm") -> Optional[float]:
        """길이 → cm. 단위가 없으면 unit."""
        if text is None:
            return None
        t = strip_braces(text)
        d = parse_dim(t)
        if d is not None:
            return d
        body, u = unit_suffix(t)
        v = self.number(body)
        if v is None:
            return None
        return v * UNITS[u or unit]

    def component(self, text: str) -> Optional[tuple[float, bool]]:
        """좌표 성분 → (값, 단위 있음). 단위가 있으면 cm."""
        t = strip_braces(text)
        d = parse_dim(t)
        if d is not None:
            return d, True
        body, u = unit_suffix(t)
        v = self.number(body)
        if v is None:
            return None
        if u:
            return v * UNITS[u], True
        return v, False

    # ------------------------------------------------------------ 좌표
    def user_to_canvas(self, x: float, y: float, st: Style, xdim=False, ydim=False) -> tuple:
        if self.axis_map is not None and not xdim and not ydim:
            p = self.axis_map(x, y)
            if p is not None:
                return p
        ux = (x, 0.0) if xdim else (x * st.xvec[0], x * st.xvec[1])
        uy = (0.0, y) if ydim else (y * st.yvec[0], y * st.yvec[1])
        return mat_apply(st.matrix, (ux[0] + uy[0], ux[1] + uy[1]))

    def delta_to_canvas(self, x: float, y: float, st: Style, xdim=False, ydim=False) -> tuple:
        ux = (x, 0.0) if xdim else (x * st.xvec[0], x * st.xvec[1])
        uy = (0.0, y) if ydim else (y * st.yvec[0], y * st.yvec[1])
        return mat_linear(st.matrix, (ux[0] + uy[0], ux[1] + uy[1]))

    def coord_value(self, val: str, st: Style) -> Optional[tuple]:
        t = strip_braces(val)
        if t.startswith("(") and match(t, 0) == len(t):
            t = t[1:-1]
        r = self.coord_inner(t, st, depth=0)
        return r.p if r else None

    def coord_inner(self, inner: str, st: Style, depth: int = 0, *, delta: bool = False) -> Optional[Pt]:
        t = inner.strip()
        if depth > 16:
            self.problem("좌표가 너무 깊게 중첩되었다")
            return None
        if not t:
            return None
        if t.startswith("$") and t.endswith("$") and len(t) >= 2:
            return self.calc(t[1:-1], st, depth + 1)
        if t.startswith("axis cs:"):
            t = t[len("axis cs:"):]
        elif re.match(r"^(canvas|xyz|canvas polar|xyz polar) cs:", t):
            t = t.split(":", 1)[1]
            kv = dict(keyvals(t))
            if "angle" in kv:
                t = f"{kv.get('angle')}:{kv.get('radius', '1')}"
            else:
                t = f"{kv.get('x', '0')},{kv.get('y', '0')}"
        for op in ("|-", "-|"):
            k = find_top(t, op)
            if k > 0:
                a = self._side(t[:k], st, depth)
                b = self._side(t[k + 2:], st, depth)
                if a is None or b is None:
                    return None
                return Pt((a[0], b[1]) if op == "|-" else (b[0], a[1]))
        parts = split_top(t, ",")
        if len(parts) == 2:
            cx, cy = self.component(parts[0]), self.component(parts[1])
            if cx is None or cy is None:
                self.problem(f"좌표를 계산하지 못했다: ({t[:40]})")
                return None
            if delta:
                return Pt(self.delta_to_canvas(cx[0], cy[0], st, cx[1], cy[1]))
            return Pt(self.user_to_canvas(cx[0], cy[0], st, cx[1], cy[1]))
        if len(parts) == 3:
            self.problem("3차원 좌표는 지원하지 않는다")
            return None
        k = find_top(t, ":")
        if k > 0:
            ang = self.number(t[:k])
            rtxt = t[k + 1:]
            if ang is None:
                self.problem(f"극좌표 각을 계산하지 못했다: ({t[:40]})")
                return None
            if " and " in rtxt:
                ra, rb = rtxt.split(" and ", 1)
            else:
                ra = rb = rtxt
            a, b = self.component(ra), self.component(rb)
            if a is None or b is None:
                self.problem(f"극좌표 반지름을 계산하지 못했다: ({t[:40]})")
                return None
            c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            if delta:
                return Pt(self.delta_to_canvas(a[0] * c, b[0] * s, st, a[1], b[1]))
            if self.axis_map is not None:
                return Pt(self.user_to_canvas(a[0] * c, b[0] * s, Style(), True, True))
            return Pt(self.user_to_canvas(a[0] * c, b[0] * s, st, a[1], b[1]))
        # 이름 좌표
        return self.named(t)

    def _side(self, t: str, st: Style, depth: int) -> Optional[tuple]:
        t = t.strip()
        if t.startswith("(") and match(t, 0) == len(t):
            t = t[1:-1]
        r = self.coord_inner(t, st, depth + 1)
        return r.p if r else None

    def named(self, t: str) -> Optional[Pt]:
        name = t.strip()
        if name in self.nodes:
            g = self.nodes[name]
            return Pt(g.center, g if g.shape != "coordinate" else None)
        if "." in name:
            base, anchor = name.rsplit(".", 1)
            if base in self.nodes:
                return Pt(self.nodes[base].anchor(anchor))
        self.problem(f"모르는 좌표 이름: ({name[:40]})")
        return None

    def calc(self, text: str, st: Style, depth: int) -> Optional[Pt]:
        """calc: 항 (+|-) 항 … , 항 = [배수*] (좌표) [!t!(B) | !거리!(B) | !(P)!(B) | !t!각:(B)]…"""
        s = text.strip()
        i, n = 0, len(s)
        total = (0.0, 0.0)
        sign = 1.0
        got = False
        while i < n:
            i = skip_ws(s, i)
            if i >= n:
                break
            if s[i] in "+-":
                sign = 1.0 if s[i] == "+" else -1.0
                i += 1
                continue
            factor = 1.0
            if s[i] != "(":
                k = s.find("*", i)
                if k < 0:
                    self.problem(f"calc 식을 해석하지 못했다: {s[:40]}")
                    return None
                f = self.number(s[i:k])
                if f is None:
                    return None
                factor = f
                i = skip_ws(s, k + 1)
                if i >= n or s[i] != "(":
                    self.problem(f"calc 식을 해석하지 못했다: {s[:40]}")
                    return None
            inner, i = group(s, i)
            base = self.coord_inner(inner, st, depth + 1)
            if base is None:
                return None
            p = base.p
            # 수정자
            while True:
                j = skip_ws(s, i)
                if j < n and s[j] == "!":
                    k = j + 1
                    k2 = skip_ws(s, k)
                    if k2 < n and s[k2] == "(":
                        pinner, k3 = group(s, k2)
                        k3 = skip_ws(s, k3)
                        if k3 < n and s[k3] == "!":
                            k3 = skip_ws(s, k3 + 1)
                            if k3 < n and s[k3] == "(":
                                binner, k4 = group(s, k3)
                                P = self.coord_inner(pinner, st, depth + 1)
                                B = self.coord_inner(binner, st, depth + 1)
                                if P is None or B is None:
                                    return None
                                d = G.sub(B.p, p)
                                L2 = d[0] ** 2 + d[1] ** 2
                                tt = 0.0 if L2 < 1e-18 else ((P.p[0] - p[0]) * d[0] + (P.p[1] - p[1]) * d[1]) / L2
                                p = G.lerp(p, B.p, tt)
                                i = k4
                                continue
                        return None
                    k2 = s.find("!", k)
                    if k2 < 0:
                        return None
                    mod = s[k:k2]
                    k3 = skip_ws(s, k2 + 1)
                    angle = 0.0
                    m = re.match(r"([^():]*):", s[k3:])
                    if m and not s[k3:].startswith("("):
                        a = self.number(m.group(1))
                        angle = a or 0.0
                        k3 = skip_ws(s, k3 + m.end())
                    if k3 >= n or s[k3] != "(":
                        return None
                    binner, k4 = group(s, k3)
                    B = self.coord_inner(binner, st, depth + 1)
                    if B is None:
                        return None
                    d = G.sub(B.p, p)
                    if angle:
                        c, sn = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                        d = (d[0] * c - d[1] * sn, d[0] * sn + d[1] * c)
                    dim = parse_dim(mod.strip())
                    if dim is not None:
                        p = G.add(p, G.mul(G.unit(d), dim))
                    else:
                        tv = self.number(mod)
                        if tv is None:
                            return None
                        p = G.add(p, G.mul(d, tv))
                    i = k4
                    continue
                break
            total = (total[0] + sign * factor * p[0], total[1] + sign * factor * p[1])
            sign = 1.0
            got = True
        return Pt(total) if got else None

    # ------------------------------------------------------------ 실행
    def run(self) -> None:
        src = self.source
        st = Style()
        i = skip_ws(src, 0)
        if i < len(src) and src[i] == "[":
            opts, i = group(src, i)
            st = self.applier.apply(st, opts)
        try:
            self.run_block(src[i:], st)
        except _Stop:
            self.stopped = True
        except RecursionError:
            self.problem("그림이 너무 깊게 중첩되었다")

    def run_block(self, s: str, st: Style) -> None:
        self.depth += 1
        try:
            if self.depth > MAX_DEPTH:
                self.problem("그림이 너무 깊게 중첩되었다")
                return
            self._run_block(s, st)
        finally:
            self.depth -= 1

    def _run_block(self, s: str, st: Style) -> None:
        i, n = 0, len(s)
        while i < n:
            self.tick()
            i = skip_ws(s, i)
            if i >= n:
                break
            c = s[i]
            if c == "{":
                inner, j = group(s, i)
                self.scoped(inner, st, None)
                i = j
                continue
            if c == ";" or c == "}":
                i += 1
                continue
            if c != "\\":
                j = statement_end(s, i, n)
                frag = s[i:j].strip()
                if frag:
                    self.problem(f"해석하지 못한 내용을 건너뛰었다: {frag[:40]}")
                i = j + 1
                continue
            m = re.match(r"\\([A-Za-z@]+)\*?", s[i:])
            if not m:
                i += 2
                continue
            name = m.group(1)
            j = i + m.end()
            if name == "begin":
                i = self.begin_env(s, j, st)
                continue
            if name in _PATH_CMDS:
                k = statement_end(s, j, n)
                self.path_statement(name, s[j:k], st)
                i = k + 1
                continue
            if name in ("node", "coordinate", "matrix", "pic"):
                k = statement_end(s, j, n)
                if name in ("matrix", "pic"):
                    self.problem(f"\\{name} 는 지원하지 않는다")
                else:
                    self.path_statement("path", name + " " + s[j:k], st)
                i = k + 1
                continue
            if name == "foreach":
                i = self.foreach_statement(s, j, st)
                continue
            if name == "tikzset":
                jj = skip_ws(s, j)
                if jj < n and s[jj] == "{":
                    inner, i = group(s, jj)
                    self.tikzset(inner)
                else:
                    i = jj
                continue
            if name == "tikzstyle":
                k = statement_end(s, j, n)
                m2 = re.match(r"\s*\{([^{}]*)\}\s*\+?=\s*\[(.*)\]\s*$", s[j:k], re.S)
                if m2:
                    self.applier.styles[m2.group(1).strip()] = (m2.group(2), None)
                i = k + 1
                continue
            if name in ("pgfmathsetmacro", "pgfmathtruncatemacro", "pgfmathsetlengthmacro"):
                jj = skip_ws(s, j)
                if jj < n and s[jj] == "{":
                    mac, jj = group(s, jj)
                else:
                    mm = re.match(r"\\[A-Za-z]+", s[jj:])
                    mac = mm.group() if mm else ""
                    jj += len(mac)
                jj = skip_ws(s, jj)
                if jj < n and s[jj] == "{":
                    body, jj = group(s, jj)
                else:
                    body = ""
                v = self.number(body)
                rest = s[jj:]
                var = mac.strip().lstrip("\\")
                if v is None or not var:
                    self.problem(f"\\{name} 값을 계산하지 못했다")
                    v = 0.0
                if name == "pgfmathtruncatemacro":
                    v = float(int(v))
                s = s[:jj] + substitute(rest, var, _fmt(v))
                n = len(s)
                i = jj
                continue
            if name in ("pgfmathdeclarefunction", "pgfkeys", "pgfmathparse", "addplot3", "def",
                        "newcommand", "pgfplotstableread"):
                self.problem(f"\\{name} 는 지원하지 않는다 (명세 3.1절 제외 목록)")
                k = statement_end(s, j, n) if name not in ("pgfmathdeclarefunction",) else self._skip_args(s, j, 3)
                i = k + 1 if k < n and s[k:k + 1] == ";" else k
                continue
            if name in ("end",):
                k = s.find("}", j)
                i = n if k < 0 else k + 1
                continue
            if name in _IGNORED_CMDS:
                i = self._skip_args(s, j, 1)
                continue
            if name in ("addplot", "addlegendentry", "legend"):
                self.problem(f"\\{name} 는 axis 환경 안에서만 쓸 수 있다")
                k = statement_end(s, j, n)
                i = k + 1
                continue
            self.problem(f"모르는 명령은 건너뛰었다: \\{name}")
            k = statement_end(s, j, n)
            i = k + 1

    def _skip_args(self, s: str, j: int, nargs: int) -> int:
        for _ in range(nargs):
            jj = skip_ws(s, j)
            if jj < len(s) and s[jj] in "{[":
                _, j = group(s, jj)
            else:
                break
        return j

    def tikzset(self, inner: str) -> None:
        for key, val in keyvals(inner):
            if self.applier.define_one(key, val, self.problems):
                continue
            if key.startswith("every ") or key in ("node distance", ">"):
                self.applier.styles.setdefault("@global", ("", None))
                body = self.applier.styles["@global"][0]
                self.applier.styles["@global"] = ((body + ", " if body else "")
                                                  + (f"{key}={{{val}}}" if val is not None else key), None)
                continue
            self.problem(f"\\tikzset 의 키를 무시했다: {key}")

    def scoped(self, inner: str, st: Style, opts: Optional[str]) -> None:
        saved = dict(self.applier.styles)
        depth = self.canvas.depth()
        st2 = self.applier.apply(st, opts) if opts else st
        attrs = ""
        if st2.opacity < 1:
            attrs = f' opacity="{num(st2.opacity)}"'
        self.canvas.push(attrs)
        try:
            self.run_block(inner, st2)
        finally:
            self.canvas.unwind(depth)
            self.applier.styles = saved

    def begin_env(self, s: str, j: int, st: Style) -> int:
        n = len(s)
        jj = skip_ws(s, j)
        if jj >= n or s[jj] != "{":
            return jj
        name, jj = group(s, jj)
        name = name.strip()
        end = _find_env_end(s, jj, name)
        body_end, after = end
        body = s[jj:body_end]
        if name == "scope":
            k = skip_ws(body, 0)
            opts = None
            if k < len(body) and body[k] == "[":
                opts, k = group(body, k)
            self.scoped(body[k:], st, opts)
        elif name in _AXIS_ENVS:
            from .axis import render_axis
            k = skip_ws(body, 0)
            opts = ""
            if k < len(body) and body[k] == "[":
                opts, k = group(body, k)
            render_axis(self, name, opts, body[k:], st)
        elif name in ("tikzpicture",):
            self.run_block(body, st)
        else:
            self.problem(f"그림 안의 {name} 환경은 지원하지 않는다")
        return after

    # ------------------------------------------------------------ foreach
    def parse_foreach(self, s: str, j: int):
        """\\foreach 머리 → (변수 목록, 옵션, 목록 글, 본문 시작 위치)."""
        n = len(s)
        i = skip_ws(s, j)
        vars_: list[str] = []
        opts = ""
        while i < n:
            m = re.match(r"\\([A-Za-z@]+)", s[i:])
            if not m:
                break
            vars_.append(m.group(1))
            i = skip_ws(s, i + m.end())
            if i < n and s[i] == "/":
                i = skip_ws(s, i + 1)
                continue
            break
        i = skip_ws(s, i)
        if i < n and s[i] == "[":
            opts, i = group(s, i)
            i = skip_ws(s, i)
        if not s.startswith("in", i):
            return None
        i = skip_ws(s, i + 2)
        if i < n and s[i] == "{":
            lst, i = group(s, i)
        else:
            m = re.match(r"\\[A-Za-z]+", s[i:])
            lst = m.group() if m else ""
            i += len(lst)
        return vars_, opts, lst, skip_ws(s, i)

    def expand_list(self, lst: str) -> list[str]:
        items = [x.strip() for x in split_top(lst, ",")]
        items = [x for x in items if x != ""]
        out: list[str] = []
        k = 0
        while k < len(items):
            it = items[k]
            if it == "..." and out and k + 1 < len(items):
                last = items[k + 1]
                prev = out[-1]
                prev2 = out[-2] if len(out) >= 2 and k >= 2 and items[k - 2] != "..." else None
                if len(prev) == 1 and prev.isalpha() and len(last) == 1 and last.isalpha():
                    step = 1
                    if prev2 and len(prev2) == 1 and prev2.isalpha():
                        step = ord(prev) - ord(prev2) or 1
                    c = ord(prev) + step
                    while (step > 0 and c <= ord(last)) or (step < 0 and c >= ord(last)):
                        out.append(chr(c))
                        c += step
                        if len(out) > LIMIT_FOREACH + 1:
                            break
                    k += 2
                    continue
                a = self.number(prev)
                b = self.number(last)
                if a is None or b is None:
                    self.problem("\\foreach 범위를 계산하지 못했다")
                    k += 2
                    continue
                step = 1.0 if b >= a else -1.0
                if prev2 is not None:
                    a2 = self.number(prev2)
                    if a2 is not None and a - a2 != 0:
                        step = a - a2
                if step == 0 or (b - a) * step < 0:
                    k += 2
                    out.append(last) if (b - a) * step >= 0 else None
                    continue
                cnt = int(math.floor((b - a) / step + 1e-9))
                if cnt > LIMIT_FOREACH + 1:
                    cnt = LIMIT_FOREACH + 1
                for q in range(1, cnt + 1):
                    out.append(_fmt(a + q * step))
                k += 2
                continue
            out.append(it)
            k += 1
            if len(out) > LIMIT_FOREACH + 1:
                break
        return out

    def foreach_iterations(self, vars_, opts, lst):
        """(변수 → 값) 사전 목록."""
        items = self.expand_list(lst)
        count_var = None
        evals = []
        remember = None
        for key, val in keyvals(opts):
            if key == "count" and val:
                cv = val.split(" from ")
                count_var = (cv[0].strip().lstrip("\\"), self.number(cv[1]) if len(cv) > 1 else 1)
            elif key == "evaluate" and val:
                m = re.match(r"\s*\\([A-Za-z@]+)\s+as\s+\\([A-Za-z@]+)(?:\s+using\s+(.*))?$", val, re.S)
                if m:
                    evals.append((m.group(1), m.group(2), m.group(3)))
            elif key == "remember" and val:
                m = re.match(r"\s*\\([A-Za-z@]+)\s+as\s+\\([A-Za-z@]+)(?:\s*\(initially\s+(.*)\))?\s*$", val, re.S)
                if m:
                    remember = (m.group(1), m.group(2), m.group(3) or "")
        out = []
        prev_rem = remember[2] if remember else None
        for idx, it in enumerate(items):
            parts = split_top(it, "/") if len(vars_) > 1 else [it]
            sub: dict[str, str] = {}
            for vi, v in enumerate(vars_):
                if vi < len(parts):
                    sub[v] = strip_braces(parts[vi]) if parts[vi].strip().startswith("{") else parts[vi].strip()
                else:
                    sub[v] = parts[-1].strip() if parts else ""
            if count_var:
                start = count_var[1] if count_var[1] is not None else 1
                sub[count_var[0]] = _fmt(start + idx)
            for src, dst, using in evals:
                text = using if using else sub.get(src, "")
                for k2, v2 in sub.items():
                    text = substitute(text, k2, v2)
                v = self.number(text)
                sub[dst] = _fmt(v) if v is not None else text
            if remember:
                sub[remember[1]] = prev_rem if prev_rem is not None else ""
                prev_rem = sub.get(remember[0], "")
            out.append(sub)
        return out

    def substitute_all(self, text: str, sub: dict[str, str]) -> str:
        # 긴 이름부터 (\ii 가 \i 보다 먼저)
        for k in sorted(sub, key=len, reverse=True):
            text = substitute(text, k, sub[k])
        return text

    def take_iteration(self) -> bool:
        if self.foreach_over:
            return False
        self.foreach_count += 1
        if self.foreach_count > LIMIT_FOREACH:
            self.foreach_over = True
            self.problem(f"\\foreach 반복이 그림당 상한 {LIMIT_FOREACH:,}회를 넘어 나머지는 건너뛰었다")
            return False
        return True

    def foreach_statement(self, s: str, j: int, st: Style) -> int:
        n = len(s)
        head = self.parse_foreach(s, j)
        if head is None:
            self.problem("\\foreach 문법을 해석하지 못했다")
            return statement_end(s, j, n) + 1
        vars_, opts, lst, i = head
        if i < n and s[i] == "{":
            body, after = group(s, i)
        else:
            # 본문이 문장 하나 (또는 \foreach 하나)
            k = i
            m = re.match(r"\\foreach\b", s[i:])
            if m:
                k = self._foreach_extent(s, i)
            else:
                k = statement_end(s, i, n) + 1
            body, after = s[i:k], k
        for sub in self.foreach_iterations(vars_, opts, lst):
            self.tick()
            if not self.take_iteration():
                break
            self.run_block(self.substitute_all(body, sub), st)
        return after

    def _foreach_extent(self, s: str, i: int) -> int:
        n = len(s)
        head = self.parse_foreach(s, i + len("\\foreach"))
        if head is None:
            return statement_end(s, i, n) + 1
        _, _, _, k = head
        if k < n and s[k] == "{":
            return match(s, k)
        if s.startswith("\\foreach", k):
            return self._foreach_extent(s, k)
        return statement_end(s, k, n) + 1

    # ------------------------------------------------------------ 경로 문장
    def path_statement(self, cmd: str, text: str, st: Style) -> None:
        base = st
        glob = self.applier.styles.get("@global")
        if glob and glob[0]:
            base = self.applier.apply(base, glob[0])
        base = base.copy(draw=None, fill=None, clip=False)
        if cmd in ("draw", "filldraw", "shadedraw"):
            base = base.copy(draw=True)
        if cmd in ("fill", "filldraw", "shade", "shadedraw"):
            base = base.copy(fill=True)
        if cmd == "clip":
            base = base.copy(clip=True)
        if cmd in ("shade", "shadedraw", "pattern"):
            self.problem(f"\\{cmd} 는 단색 채움으로 근사했다")
        pb = PathBuilder(self, base)
        pb.parse(text)
        pb.finish()


def _fmt(v: float) -> str:
    if v is None or not math.isfinite(v):
        return "0"
    if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
        return str(int(round(v)))
    s = f"{v:.10g}"
    return s


def _find_env_end(s: str, i: int, name: str) -> tuple[int, int]:
    """\\begin{name} 다음 위치 i 에서 짝이 되는 \\end{name} → (본문 끝, 그 다음)."""
    pat = re.compile(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}")
    depth = 1
    for m in pat.finditer(s, i):
        if m.group(1) == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.start(), m.end()
    return len(s), len(s)


# ====================================================================== 경로
class PathBuilder:
    def __init__(self, eng: Engine, st: Style):
        self.e = eng
        self.st = st                 # 그리기 스타일 (경로 앞 옵션 반영 후 갱신)
        self.segs: list = []
        self.cur: Optional[tuple] = None
        self.cur_node: Optional[NodeGeom] = None
        self.rel_base: Optional[tuple] = None
        self.sub_start: Optional[tuple] = None
        self.last_pieces: list = []  # 마지막 연산의 [(p0, seg)]
        self.nodes: list = []        # (노드 글, 스타일, 위치 정보) — 경로 뒤에 그림
        self.edges: list = []        # (세그먼트, 스타일)
        self.opts_seen = False
        self.pending_nodes: list = []  # 연산과 목표 사이 노드 (그 연산 조각 위에 놓음)

    # ------------------------------------------------------------ 도우미
    def add(self, seg) -> None:
        self.e.count()
        self.segs.append(seg)

    def move(self, p, node=None) -> None:
        self.add(("M", p))
        self.cur = p
        self.cur_node = node
        self.sub_start = p
        self.last_pieces = []

    def line(self, target: Pt) -> None:
        if self.cur is None:
            self.move(target.p, target.node)
            return
        start = self.cur
        end = target.p
        if self.cur_node is not None:
            start = self.cur_node.border_toward(end)
            self.add(("M", start))
        if target.node is not None:
            end = target.node.border_toward(start if self.cur_node is None else self.cur_node.center)
            if self.cur_node is not None:
                start2 = self.cur_node.border_toward(target.node.center)
                if start2 != start:
                    self.segs[-1] = ("M", start2)
                    start = start2
        self.add(("L", end))
        self.last_pieces = [(start, ("L", end))]
        self.cur = target.p
        self.cur_node = target.node

    def read_coord(self, s: str, i: int) -> tuple[Optional[Pt], int]:
        """i 에서 (좌표) / +(…) / ++(…) 를 읽는다."""
        n = len(s)
        i = skip_ws(s, i)
        rel = 0
        if s.startswith("++", i):
            rel, i = 2, skip_ws(s, i + 2)
        elif s.startswith("+", i):
            rel, i = 1, skip_ws(s, i + 1)
        if i >= n or s[i] != "(":
            return None, i
        inner, j = group(s, i)
        if rel:
            d = self.e.coord_inner(inner, self.st, delta=True)
            if d is None:
                return None, j
            base = self.rel_base if self.rel_base is not None else (self.cur or (0.0, 0.0))
            p = (base[0] + d.p[0], base[1] + d.p[1])
            if rel == 2:
                self.rel_base = p
            return Pt(p), j
        r = self.e.coord_inner(inner, self.st)
        if r is not None:
            self.rel_base = r.p
        return r, j

    # ------------------------------------------------------------ 파싱
    def parse(self, s: str) -> None:
        e = self.e
        i, n = 0, len(s)
        op: Optional[str] = None
        to_style: Optional[Style] = None
        guard = 0
        while i < n:
            guard += 1
            if guard % 64 == 0:
                e.tick()
            i = skip_ws(s, i)
            if i >= n:
                break
            c = s[i]
            if c == "[":
                opts, i = group(s, i)
                if op == "to":
                    to_style = self.e.applier.apply(to_style or self.st, opts)
                else:
                    self.st = self.e.applier.apply(self.st, opts)
                continue
            if c == "{" or c == "}":
                i += 1
                continue
            if s.startswith("--", i):
                op = "--"
                i += 2
                continue
            if s.startswith("-|", i) or s.startswith("|-", i):
                op = s[i:i + 2]
                i += 2
                continue
            if s.startswith("..", i):
                i = self.curve(s, i + 2)
                op = None
                continue
            if c == "(" or c == "+":
                pt, i = self.read_coord(s, i)
                if pt is None:
                    op = None
                    continue
                self.coordinate_op(op, pt, to_style)
                self.flush_pending()
                op = None
                to_style = None
                continue
            m = re.match(r"\\?([A-Za-z]+)", s[i:])
            if not m:
                i += 1
                continue
            word = m.group(1)
            j = i + m.end()
            if word == "cycle":
                if op in ("--", "-|", "|-") and self.sub_start is not None and self.cur is not None:
                    if op != "--":
                        corner = ((self.sub_start[0], self.cur[1]) if op == "-|" else (self.cur[0], self.sub_start[1]))
                        self.add(("L", corner))
                    self.last_pieces = [(self.cur, ("L", self.sub_start))]
                    self.add(("Z",))
                    self.cur = self.sub_start
                    self.cur_node = None
                elif op == "to" and self.sub_start is not None:
                    self.to_op(Pt(self.sub_start), to_style)
                self.flush_pending()
                op = None
                i = j
                continue
            if word in ("node", "coordinate"):
                i = self.node_op(s, j, word, in_op=op is not None)
                continue
            if word == "to":
                op = "to"
                to_style = self.st
                i = j
                continue
            if word == "edge":
                i = self.edge_op(s, j)
                continue
            if word == "rectangle":
                pt, i = self.read_coord(s, j)
                if pt is not None and self.cur is not None:
                    a, b = self.cur, pt.p
                    self.add(("M", a))
                    self.add(("L", (b[0], a[1])))
                    self.add(("L", b))
                    self.add(("L", (a[0], b[1])))
                    self.add(("Z",))
                    self.last_pieces = [(a, ("L", b))]
                    self.cur = b
                    self.cur_node = None
                    self.sub_start = b
                continue
            if word in ("circle", "ellipse"):
                i = self.circle_op(s, j, word)
                continue
            if word == "arc":
                i = self.arc_op(s, j)
                continue
            if word == "grid":
                i = self.grid_op(s, j)
                continue
            if word == "plot":
                i = self.plot_op(s, j, connect=(op == "--"))
                op = None
                continue
            if word == "foreach":
                i = self.inline_foreach(s, j)
                s = self._spliced
                n = len(s)
                continue
            if word in ("let", "sin", "cos", "parabola", "svg", "decorate", "pic"):
                e.problem(f"경로 연산 {word} 는 지원하지 않는다")
                k = statement_end(s, j, n)
                i = k
                continue
            if word == "in" or word == "and" or word == "controls":
                i = j
                continue
            e.problem(f"해석하지 못한 경로 조각: {word}")
            i = j

    def inline_foreach(self, s: str, j: int) -> int:
        """경로 안의 \\foreach: 본문들을 이어 붙여 그 자리에 펼친다."""
        e = self.e
        head = e.parse_foreach(s, j)
        self._spliced = s
        if head is None:
            e.problem("\\foreach 문법을 해석하지 못했다")
            return len(s)
        vars_, opts, lst, i = head
        if i < len(s) and s[i] == "{":
            body, after = group(s, i)
        else:
            body, after = "", i
        parts = []
        total = 0
        for sub in e.foreach_iterations(vars_, opts, lst):
            if not e.take_iteration():
                break
            piece = e.substitute_all(body, sub)
            total += len(piece)
            if total > 2_000_000:
                e.problem("\\foreach 펼침이 너무 길다")
                break
            parts.append(piece)
        start = j - len("\\foreach") if s[j - len("\\foreach"):j] == "\\foreach" else j
        self._spliced = s[:start] + " " + " ".join(parts) + " " + s[after:]
        return start

    def coordinate_op(self, op: Optional[str], pt: Pt, to_style) -> None:
        if op is None or self.cur is None:
            self.move(pt.p, pt.node)
            return
        if op == "--":
            self.line(pt)
        elif op in ("-|", "|-"):
            a = self.cur_node.center if self.cur_node else self.cur
            b = pt.p
            corner = (b[0], a[1]) if op == "-|" else (a[0], b[1])
            self.line(Pt(corner))
            p0 = self.cur
            self.line(pt)
            self.last_pieces = [(self.last_pieces_start(p0), ("L", corner)), (corner, ("L", self.segs[-1][1]))]
        elif op == "to":
            self.to_op(pt, to_style)

    def last_pieces_start(self, p0):
        return p0

    def flush_pending(self) -> None:
        if not self.pending_nodes:
            return
        for spec in self.pending_nodes:
            if spec["pos"] is None:
                spec["pos"] = 0.5
            spec["pieces"] = list(self.last_pieces)
            self.nodes.append(spec)
        self.pending_nodes = []

    def curve(self, s: str, i: int) -> int:
        """.. controls (a) and (b) .. (c)"""
        i = skip_ws(s, i)
        if not s.startswith("controls", i):
            return i
        i += len("controls")
        a, i = self.read_coord(s, i)
        i = skip_ws(s, i)
        b = a
        if s.startswith("and", i):
            b, i = self.read_coord(s, i + 3)
        i = skip_ws(s, i)
        if s.startswith("..", i):
            i += 2
        c, i = self.read_coord(s, i)
        if a is None or b is None or c is None or self.cur is None:
            return i
        p0 = self.cur
        self.add(("C", a.p, b.p, c.p))
        self.last_pieces = [(p0, ("C", a.p, b.p, c.p))]
        self.cur = c.p
        self.cur_node = None
        return i

    def to_op(self, pt: Pt, st: Optional[Style]) -> None:
        st = st or self.st
        if self.cur is None:
            self.move(pt.p, pt.node)
            return
        a = self.cur_node.center if self.cur_node else self.cur
        b = pt.node.center if pt.node else pt.p
        dx, dy = b[0] - a[0], b[1] - a[1]
        dist = math.hypot(dx, dy)
        base = math.degrees(math.atan2(dy, dx)) if dist > 1e-12 else 0.0
        if st.bend is None and st.out_angle is None and st.in_angle is None:
            self.line(pt)
            return
        if st.bend is not None:
            out_a = base + st.bend
            in_a = base + 180 - st.bend
        else:
            out_a = st.out_angle if st.out_angle is not None else base
            in_a = st.in_angle if st.in_angle is not None else base + 180
        start = self.cur_node.anchor_dir(out_a) if self.cur_node else a  # type: ignore[attr-defined]
        end = pt.node.anchor_dir(in_a) if pt.node else b  # type: ignore[attr-defined]
        d = 0.3915 * st.looseness * math.hypot(end[0] - start[0], end[1] - start[1])
        c1 = (start[0] + d * math.cos(math.radians(out_a)), start[1] + d * math.sin(math.radians(out_a)))
        c2 = (end[0] + d * math.cos(math.radians(in_a)), end[1] + d * math.sin(math.radians(in_a)))
        if self.cur_node is not None:
            self.add(("M", start))
        self.add(("C", c1, c2, end))
        self.last_pieces = [(start, ("C", c1, c2, end))]
        self.cur = pt.p
        self.cur_node = pt.node

    def edge_op(self, s: str, j: int) -> int:
        """edge[opts] (target): 따로 그리는 선 (현재 점은 그대로)."""
        n = len(s)
        i = skip_ws(s, j)
        est = self.st
        if i < n and s[i] == "[":
            opts, i = group(s, i)
            est = self.e.applier.apply(self.st, opts)
        # edge 사이 노드
        mid_nodes = []
        while True:
            i = skip_ws(s, i)
            m = re.match(r"node\b", s[i:])
            if not m:
                break
            sub = PathBuilder(self.e, est)
            i = sub.node_op(s, i + 4, "node", in_op=True)
            mid_nodes.extend(sub.pending_nodes)
        pt, i = self.read_coord(s, i)
        if pt is None or self.cur is None:
            return i
        sub = PathBuilder(self.e, est)
        sub.cur, sub.cur_node = self.cur, self.cur_node
        sub.segs = [("M", self.cur)]
        sub.to_op(pt, est)
        if sub.segs and sub.segs[0][0] == "M" and len(sub.segs) > 1 and sub.segs[1][0] == "M":
            sub.segs = sub.segs[1:]
        sub.pending_nodes = mid_nodes
        sub.flush_pending()
        self.edges.append(sub)
        return i

    def circle_op(self, s: str, j: int, word: str) -> int:
        n = len(s)
        i = skip_ws(s, j)
        st = self.st
        if i < n and s[i] == "[":
            opts, i = group(s, i)
            st = self.e.applier.apply(st, opts)
        rx = ry = None
        i = skip_ws(s, i)
        if i < n and s[i] == "(":
            inner, i = group(s, i)
            if " and " in inner:
                a, b = inner.split(" and ", 1)
                rx, ry = self.e.component(a), self.e.component(b)
            else:
                rx = ry = self.e.component(inner)
        else:
            r = st.radius
            rx = (st.x_radius if st.x_radius is not None else r, False) if (st.x_radius or r) is not None else None
            ry = (st.y_radius if st.y_radius is not None else r, False) if (st.y_radius or r) is not None else None
            if rx is not None and ry is not None:
                rx = (rx[0], False)
                ry = (ry[0], False)
        if rx is None or ry is None or self.cur is None or rx[0] is None or ry[0] is None:
            self.e.problem(f"{word} 반지름을 계산하지 못했다")
            return i
        c = self.cur_node.center if self.cur_node else self.cur
        u = self.radius_vec(rx, 0)
        v = self.radius_vec(ry, 1)
        self.ellipse(c, u, v, 0, 360, move=True)
        self.add(("Z",))
        self.cur = c
        self.sub_start = c
        return i

    def radius_vec(self, r: tuple, axis: int) -> tuple:
        val, dim = r
        st = self.st
        if dim:
            vec = (val, 0.0) if axis == 0 else (0.0, val)
        else:
            base = st.xvec if axis == 0 else st.yvec
            vec = (base[0] * val, base[1] * val)
        if self.e.axis_map is not None and not dim:
            o = self.e.axis_map(0, 0)
            q = self.e.axis_map(*( (val, 0) if axis == 0 else (0, val)))
            if o and q:
                return (q[0] - o[0], q[1] - o[1])
        return mat_linear(st.matrix, vec)

    def ellipse(self, c, u, v, a0, a1, *, move: bool) -> None:
        pieces = G.arc_user(0, 0, 1, 1, a0, a1)

        def mp(q):
            return (c[0] + q[0] * u[0] + q[1] * v[0], c[1] + q[0] * u[1] + q[1] * v[1])
        t0 = math.radians(a0)
        start = mp((math.cos(t0), math.sin(t0)))
        if move:
            self.add(("M", start))
        p0 = start
        self.last_pieces = []
        for c1, c2, q in pieces:
            seg = ("C", mp(c1), mp(c2), mp(q))
            self.add(seg)
            self.last_pieces.append((p0, seg))
            p0 = seg[3]
        self.cur = p0

    def arc_op(self, s: str, j: int) -> int:
        n = len(s)
        i = skip_ws(s, j)
        st = self.st
        if i < n and s[i] == "[":
            opts, i = group(s, i)
            st = self.e.applier.apply(st, opts)
        i = skip_ws(s, i)
        a0 = a1 = None
        rx = ry = None
        if i < n and s[i] == "(":
            inner, i = group(s, i)
            parts = split_top(inner, ":")
            if len(parts) == 3:
                a0, a1 = self.e.number(parts[0]), self.e.number(parts[1])
                rt = parts[2]
                if " and " in rt:
                    ra, rb = rt.split(" and ", 1)
                    rx, ry = self.e.component(ra), self.e.component(rb)
                else:
                    rx = ry = self.e.component(rt)
        else:
            a0 = st.start_angle
            a1 = st.end_angle
            if a1 is None and a0 is not None and st.delta_angle is not None:
                a1 = a0 + st.delta_angle
            if a0 is None and a1 is not None and st.delta_angle is not None:
                a0 = a1 - st.delta_angle
            r = st.radius
            xr = st.x_radius if st.x_radius is not None else r
            yr = st.y_radius if st.y_radius is not None else r
            rx = (xr, False) if xr is not None else None
            ry = (yr, False) if yr is not None else None
        if None in (a0, a1, rx, ry) or self.cur is None:
            self.e.problem("arc 를 해석하지 못했다")
            return i
        u = self.radius_vec(rx, 0)
        v = self.radius_vec(ry, 1)
        t0 = math.radians(a0)
        start = self.cur
        c = (start[0] - math.cos(t0) * u[0] - math.sin(t0) * v[0],
             start[1] - math.cos(t0) * u[1] - math.sin(t0) * v[1])
        self.ellipse(c, u, v, a0, a1, move=False)
        self.cur_node = None
        return i

    def grid_op(self, s: str, j: int) -> int:
        n = len(s)
        i = skip_ws(s, j)
        st = self.st
        if i < n and s[i] == "[":
            opts, i = group(s, i)
            st = self.e.applier.apply(st, opts)
        pt, i = self.read_coord(s, i)
        if pt is None or self.cur is None:
            return i
        a, b = self.cur, pt.p
        # 사용자 좌표로 되돌려 눈금 간격 계산 (선형 변환이 축 정렬일 때)
        m = st.matrix
        sx = m[0] * st.xvec[0] or 1.0
        sy = m[3] * st.yvec[1] or 1.0
        ox, oy = m[4], m[5]
        ux0, ux1 = sorted(((a[0] - ox) / sx, (b[0] - ox) / sx))
        uy0, uy1 = sorted(((a[1] - oy) / sy, (b[1] - oy) / sy))
        stx, sty = st.step
        stx = stx / (abs(st.xvec[0]) or 1.0)
        sty = sty / (abs(st.yvec[1]) or 1.0)
        if stx <= 0 or sty <= 0:
            return i
        k0 = math.ceil(ux0 / stx - 1e-9)
        k1 = math.floor(ux1 / stx + 1e-9)
        if k1 - k0 > 2000:
            self.e.problem("grid 선이 너무 많다")
            return i
        for k in range(k0, k1 + 1):
            x = ox + k * stx * sx
            self.add(("M", (x, oy + uy0 * sy)))
            self.add(("L", (x, oy + uy1 * sy)))
        k0 = math.ceil(uy0 / sty - 1e-9)
        k1 = math.floor(uy1 / sty + 1e-9)
        if k1 - k0 > 2000:
            return i
        for k in range(k0, k1 + 1):
            y = oy + k * sty * sy
            self.add(("M", (ox + ux0 * sx, y)))
            self.add(("L", (ox + ux1 * sx, y)))
        self.cur = b
        self.cur_node = None
        self.last_pieces = [(a, ("L", b))]
        return i

    def plot_op(self, s: str, j: int, connect: bool) -> int:
        e = self.e
        n = len(s)
        i = skip_ws(s, j)
        st = self.st
        if i < n and s[i] == "[":
            opts, i = group(s, i)
            st = e.applier.apply(st, opts)
        i = skip_ws(s, i)
        pts: list = []
        if s.startswith("coordinates", i):
            i = skip_ws(s, i + len("coordinates"))
            if i < n and s[i] == "{":
                inner, i = group(s, i)
                k = 0
                while k < len(inner):
                    k = skip_ws(inner, k)
                    if k >= len(inner) or inner[k] != "(":
                        k += 1
                        continue
                    ci, k = group(inner, k)
                    r = e.coord_inner(ci, st)
                    pts.append(r.p if r else None)
                    if len(pts) > LIMIT_DATA:
                        e.problem("plot 좌표가 상한을 넘었다")
                        break
        elif s.startswith("function", i) or s.startswith("file", i):
            e.problem("plot function / file 은 지원하지 않는다 (외부 프로그램·파일)")
            i = skip_ws(s, i + (8 if s.startswith("function", i) else 4))
            if i < n and s[i] == "{":
                _, i = group(s, i)
            return i
        elif i < n and s[i] == "(":
            inner, i = group(s, i)
            pts = self.sample(inner, st)
        else:
            e.problem("plot 뒤에 좌표가 없다")
            return i
        self.emit_points(pts, st, connect)
        return i

    def sample(self, inner: str, st: Style) -> list:
        e = self.e
        var = st.variable
        extra = (var,) if var not in ("x", "y") else ()
        polar = False
        parts = split_top(inner, ",")
        if len(parts) != 2:
            k = find_top(inner, ":")
            if k > 0:
                parts = [inner[:k], inner[k + 1:]]
                polar = True
            else:
                e.problem(f"plot 좌표를 해석하지 못했다: ({inner[:40]})")
                return []
        comps = []
        for ptxt in parts:
            body, unit = unit_suffix(strip_braces(ptxt))
            ex = e.compile(strip_braces(body), extra)
            if ex is None:
                return []
            comps.append((ex, UNITS[unit] if unit else None))
        a, b = st.domain
        nS = st.samples
        out = []
        for k in range(nS):
            if k % 64 == 0:
                e.tick()
            t = a + (b - a) * k / (nS - 1) if nS > 1 else a
            env = e.vars_env(**{var if var != "x" else "x": t})
            vals = [_expr.evaluate(c[0], env) for c in comps]
            if any(not math.isfinite(v) for v in vals):
                out.append(None)
                continue
            (xv, xu), (yv, yu) = zip(vals, (c[1] for c in comps))
            if polar:
                r = yv * (yu or 1.0)
                rd = yu is not None
                xx, yy = r * math.cos(math.radians(xv)), r * math.sin(math.radians(xv))
                out.append(e.user_to_canvas(xx, yy, st, rd, rd))
            else:
                out.append(e.user_to_canvas(xv * (xu or 1.0), yv * (yu or 1.0), st, xu is not None, yu is not None))
        return out

    def emit_points(self, pts: list, st: Style, connect: bool) -> None:
        runs, cur = [], []
        for p in pts:
            if p is None:
                if cur:
                    runs.append(cur)
                cur = []
            else:
                cur.append(p)
        if cur:
            runs.append(cur)
        first = True
        for run in runs:
            p0 = run[0]
            if first and connect and self.cur is not None:
                self.add(("L", p0))
            else:
                self.add(("M", p0))
                self.sub_start = p0
            first = False
            if st.smooth or self.st.smooth:
                segs = G.smooth_segments(run)
            else:
                segs = [("L", q) for q in run[1:]]
            prev = p0
            self.last_pieces = []
            for sg in segs:
                self.add(sg)
                self.last_pieces.append((prev, sg))
                prev = sg[-1]
            self.cur = run[-1]
            self.cur_node = None
        if st.closed_plot and runs:
            self.add(("Z",))

    # ------------------------------------------------------------ 노드
    def node_op(self, s: str, j: int, word: str, in_op: bool) -> int:
        """node[opts] (name) at (coord) {text}  /  coordinate (name) [at (coord)]"""
        e = self.e
        n = len(s)
        i = j
        opts_list: list[str] = []
        name = None
        at: Optional[Pt] = None
        text = None
        while i < n:
            i = skip_ws(s, i)
            if i >= n:
                break
            if s[i] == "[":
                o, i = group(s, i)
                opts_list.append(o)
                continue
            if s[i] == "(":
                inner, i = group(s, i)
                name = inner.strip()
                continue
            if s.startswith("at", i) and not s[i + 2:i + 3].isalpha():
                pt, i = self.read_coord(s, i + 2)
                at = pt
                continue
            if s[i] == "{" and word == "node":
                text, i = group(s, i)
                break
            break
        if word == "coordinate":
            text = ""
        if text is None:
            text = ""
        spec = {"word": word, "opts": opts_list, "name": name, "at": at, "text": text,
                "pos": None, "pieces": None, "point": self.cur}
        st = self.node_style(opts_list)
        spec["style"] = st
        if at is not None:
            spec["point"] = at.p
        elif st.pos is not None:
            spec["pos"] = st.pos
            spec["pieces"] = list(self.last_pieces)
        elif in_op:
            self.pending_nodes.append(spec)
            return i
        if spec["point"] is None and spec["pieces"] is None:
            spec["point"] = (0.0, 0.0)
        if word == "coordinate" or at is not None or spec["pieces"] is None:
            # 이름은 바로 등록해야 같은 경로에서 쓸 수 있다
            g = self.e.place_node(spec, draw=False)
            if g is not None and word == "node" and at is None and spec["point"] is not None:
                pass
            if word == "coordinate":
                return i
        self.nodes.append(spec)
        return i

    def node_style(self, opts_list: list[str]) -> Style:
        e = self.e
        st = self.st.copy(draw=None, fill=None, arrows=(None, None), dash=None, pos=None, place=None,
                          anchor=None, labels=(), node_shift=(0.0, 0.0), rounded=0.0, shape="rectangle",
                          opacity=1.0, node_rotate=0.0, smooth=False)
        if self.st.every_node:
            st = e.applier.apply(st, self.st.every_node, node=True)
        if "every node" in e.applier.styles:
            st = e.applier.apply(st, e.applier.styles["every node"][0], node=True)
        glob = e.applier.styles.get("@global")
        if glob:
            for k, v in keyvals(glob[0]):
                if k == "every node/.style" and v:
                    st = e.applier.apply(st, v, node=True)
        for o in opts_list:
            st = e.applier.apply(st, o, node=True)
        return st

    # ------------------------------------------------------------ 끝
    def finish(self) -> None:
        e = self.e
        self.flush_pending()
        st = self.st
        if self.segs:
            if st.clip:
                e.canvas.clip(self.segs)
                if st.draw or st.fill:
                    e.emit_path(self.segs, st)
            elif st.use_as_bbox:
                bb = Canvas("x")
                bb.extend_segs(self.segs)
                if bb.bbox:
                    e.canvas.fixed_bbox = bb.bbox
            else:
                e.emit_path(self.segs, st)
        for sub in self.edges:
            if sub.segs:
                e.emit_path(sub.segs, sub.st.copy(draw=sub.st.draw or True))
            for spec in sub.nodes:
                e.place_node(spec, draw=True)
        for spec in self.nodes:
            e.place_node(spec, draw=True)


def _anchor_dir(self: NodeGeom, angle_deg: float) -> tuple:
    o = self.border_dir(math.radians(angle_deg))
    return (self.center[0] + o[0], self.center[1] + o[1])


NodeGeom.anchor_dir = _anchor_dir  # type: ignore[attr-defined]


# ====================================================================== 그리기 (Engine 메서드)
def _stroke_attrs(st: Style) -> str:
    stroke = st.stroke_paint()
    if stroke is None:
        return ' stroke="none"'
    lw_px = st.line_width * PT * CM_PX
    a = f' stroke="{att(stroke)}" stroke-width="{num(lw_px)}"'
    if st.dash:
        d = st.dash
        unit = PT * CM_PX
        if d[0] == "on":
            arr = f"{num(d[1] * unit)} {num(d[2] * unit)}"
        elif d[0] == "dot":
            arr = f"{num(max(lw_px, 0.4))} {num(d[1] * unit)}"
        elif d[0] == "dd":
            arr = f"{num(d[1] * unit)} {num(d[2] * unit)} {num(max(lw_px, .4))} {num(d[2] * unit)}"
        else:
            arr = " ".join(num(x * unit) for x in d[1:])
        a += f' stroke-dasharray="{arr}"'
    if st.line_cap:
        a += f' stroke-linecap="{st.line_cap}"'
    if st.line_join:
        a += f' stroke-linejoin="{st.line_join}"'
    if st.draw_opacity < 1:
        a += f' stroke-opacity="{num(st.draw_opacity)}"'
    return a


def emit_path(self: Engine, segs: list, st: Style) -> None:
    stroke = st.stroke_paint()
    fill = st.fill_paint()
    if stroke is None and fill is None:
        # \path: 경계만 넓힌다
        self.canvas.extend_segs(segs)
        return
    subs = G.split_subpaths(segs)
    if st.rounded > 0:
        subs = [G.round_corners(sp, st.rounded) for sp in subs]
    # 화살표
    tips = []
    lw_cm = st.line_width * PT
    if stroke is not None and (st.arrows[0] or st.arrows[1]):
        open_idx = [k for k, sp in enumerate(subs) if sp and sp[-1][0] != "Z" and len(sp) > 1]
        if open_idx:
            for at_end, name in ((False, st.arrows[0]), (True, st.arrows[1])):
                kind = tip_kind(name, st.default_tip)
                if not kind:
                    continue
                k = open_idx[-1] if at_end else open_idx[0]
                ed = G.end_direction(subs[k], at_end)
                if ed is None:
                    continue
                p, d = ed
                tseg, filled, short = G.tip_shape(kind, p, d, lw_cm, PT)
                subs[k] = G.shorten(subs[k], at_end, short)
                tips.append((tseg, filled))
    flat = [sg for sp in subs for sg in sp]
    d = path_d(flat)
    attrs = ""
    if fill is not None:
        attrs += f' fill="{att(fill)}"'
        if st.fill_opacity < 1:
            attrs += f' fill-opacity="{num(st.fill_opacity)}"'
    else:
        attrs += ' fill="none"'
    attrs += _stroke_attrs(st)
    if st.opacity < 1:
        attrs += f' opacity="{num(st.opacity)}"'
    self.canvas.add(f'<path d="{d}"{attrs}/>')
    pad = (lw_cm / 2) if stroke else 0.0
    self.canvas.extend_segs(flat, pad)
    for tseg, filled in tips:
        td = path_d(tseg)
        lw_px = st.line_width * PT * CM_PX
        if filled:
            ta = f' fill="{att(stroke)}" stroke="{att(stroke)}" stroke-width="{num(lw_px * 0.5)}" stroke-linejoin="miter"'
        else:
            ta = f' fill="none" stroke="{att(stroke)}" stroke-width="{num(lw_px)}" stroke-linecap="round" stroke-linejoin="round"'
        if st.opacity < 1:
            ta += f' opacity="{num(st.opacity)}"'
        self.canvas.add(f'<path d="{td}"{ta}/>')
        self.canvas.extend_segs(tseg, lw_cm)


Engine.emit_path = emit_path  # type: ignore[attr-defined]


# ---------------------------------------------------------------- 노드 배치·그리기
def place_node(self: Engine, spec: dict, draw: bool = True) -> Optional[NodeGeom]:
    st: Style = spec["style"]
    word = spec["word"]
    # 위치
    point = spec.get("point")
    if spec.get("pieces"):
        f = G.path_length_fn(spec["pieces"])
        point, tangent = f(spec["pos"] if spec["pos"] is not None else 1.0)
    elif spec.get("pos") is not None and spec.get("pieces") is not None and not spec["pieces"]:
        point = spec.get("point")
    if point is None:
        point = (0.0, 0.0)
    if word == "coordinate":
        g = NodeGeom(point, 0.0, 0.0, "coordinate")
        if spec.get("name"):
            self.nodes[spec["name"]] = g
        return g
    lines = parse_node_text(spec.get("text") or "")
    tw, th, widths = measure(lines, st.font_scale)
    if st.text_width:
        tw = max(tw, st.text_width)
    w = max(tw + 2 * st.inner_xsep, st.min_width)
    h = max(th + 2 * st.inner_ysep, st.min_height)
    shape = st.shape
    if shape == "circle":
        r = max(math.hypot(tw / 2 + st.inner_xsep, th / 2 + st.inner_ysep), st.min_width / 2, st.min_height / 2)
        hw = hh = r
    elif shape == "ellipse":
        hw = (tw / 2 + st.inner_xsep) * 1.4142
        hh = (th / 2 + st.inner_ysep) * 1.4142
    else:
        hw, hh = w / 2, h / 2
    hw += st.outer_sep
    hh += st.outer_sep
    geom = NodeGeom((0.0, 0.0), hw, hh, shape)
    # 기준점과 기준 앵커
    anchor = st.anchor or "center"
    if st.place is not None:
        direction, dist, of = st.place
        anchor = DIRECTIONS[direction]
        vec = {"above": (0, 1), "below": (0, -1), "left": (-1, 0), "right": (1, 0)}
        dx = sum(vec[w_][0] for w_ in direction.split())
        dy = sum(vec[w_][1] for w_ in direction.split())
        if of is not None:
            ref = None
            if of in self.nodes:
                rg = self.nodes[of]
                opp = {"south": "north", "north": "south", "east": "west", "west": "east"}
                ref_anchor = " ".join(opp[x] for x in DIRECTIONS[direction].split())
                ref = rg.anchor(ref_anchor)
            else:
                rp = self.named(of)
                ref = rp.p if rp else None
            if ref is not None:
                dd = dist if dist is not None else st.node_distance
                if dx and dy:
                    dd = dd * 0.7071
                point = (ref[0] + dx * dd, ref[1] + dy * dd)
        elif dist:
            if dx and dy:
                dist = dist * 0.7071
            point = (point[0] + dx * dist, point[1] + dy * dist)
    o = geom.offset(anchor)
    center = (point[0] - o[0] + st.node_shift[0], point[1] - o[1] + st.node_shift[1])
    geom.center = center
    if spec.get("name"):
        self.nodes[spec["name"]] = geom
    if not draw:
        return geom
    if spec.get("_drawn"):
        return geom
    spec["_drawn"] = True
    self.count()
    # 모양
    if st.draw or st.fill:
        if shape in ("circle", "ellipse"):
            segs = [("M", (center[0] + hw - st.outer_sep, center[1]))]
            for c1, c2, q in G.arc_user(center[0], center[1], hw - st.outer_sep, hh - st.outer_sep, 0, 360):
                segs.append(("C", c1, c2, q))
            segs.append(("Z",))
        else:
            x0, x1 = center[0] - hw + st.outer_sep, center[0] + hw - st.outer_sep
            y0, y1 = center[1] - hh + st.outer_sep, center[1] + hh - st.outer_sep
            segs = [("M", (x0, y0)), ("L", (x1, y0)), ("L", (x1, y1)), ("L", (x0, y1)), ("Z",)]
        self.emit_path(segs, st.copy(arrows=(None, None)))
    # 글
    _emit_text(self, lines, widths, tw, th, center, st)
    self.canvas.extend(center[0] - hw, center[1] - hh)
    self.canvas.extend(center[0] + hw, center[1] + hh)
    # label=…
    for lab in st.labels:
        _label(self, geom, lab, st)
    return geom


def _label(self: Engine, geom: NodeGeom, lab: str, st: Style) -> None:
    t = lab.strip()
    opts = ""
    if t.startswith("["):
        opts, k = group(t, 0)
        t = t[k:]
    t = strip_braces(t)
    direction = "above"
    k = find_top(t, ":")
    if k >= 0:
        direction = t[:k].strip()
        t = t[k + 1:]
    text = strip_braces(t)
    dirs = {"above": 90, "below": 270, "left": 180, "right": 0, "above left": 135, "above right": 45,
            "below left": 225, "below right": 315, "north": 90, "south": 270, "east": 0, "west": 180}
    ang = dirs.get(direction)
    if ang is None:
        try:
            ang = float(direction)
        except ValueError:
            ang = 90
    p = geom.anchor_dir(ang)  # type: ignore[attr-defined]
    # 방향에 맞는 앵커
    a = (ang + 180) % 360
    names = {0: "east", 45: "north east", 90: "north", 135: "north west", 180: "west", 225: "south west",
             270: "south", 315: "south east"}
    anchor = names[int(round(a / 45.0)) % 8 * 45]
    lst = self.applier.apply(Style(color=st.color), opts, node=True) if opts else Style(color=st.color)
    lst = lst.copy(anchor=anchor, place=None)
    self.place_node({"word": "node", "style": lst, "text": text, "point": p, "pieces": None, "pos": None,
                     "name": None}, draw=True)


def _emit_text(self: Engine, lines, widths, tw, th, center, st: Style) -> None:
    if not lines or all(not ln for ln in lines):
        return
    color = st.text_paint()
    fs = FONT_PX * st.font_scale
    op = ""
    if st.text_opacity < 1 or st.opacity < 1:
        op = f' opacity="{num(min(st.text_opacity, st.opacity))}"'
    rot = ""
    if st.node_rotate:
        rot = f' transform="rotate({num(-st.node_rotate)} {num(px(center[0]))} {num(py(center[1]))})"'
    align = (st.align or "center").strip()
    if has_math(lines):
        from ..html.mathml import tex_to_mathml
        slack = 1.25
        wpx = max(tw * CM_PX * slack + 4, 8)
        hpx = max(th * CM_PX * 1.2 + 4, fs * 1.4)
        x = px(center[0]) - wpx / 2
        y = py(center[1]) - hpx / 2
        rows = []
        for ln in lines:
            parts = []
            for r in ln:
                if r.kind == "math":
                    parts.append(tex_to_mathml(r.text, attrs={"xmlns": MATHML_NS}))
                else:
                    style = ""
                    if r.bold:
                        style += "font-weight:700;"
                    if r.italic:
                        style += "font-style:italic;"
                    if r.mono:
                        style += "font-family:var(--mono-font,monospace);"
                    parts.append(f'<span style="{style}">{esc(r.text)}</span>' if style else f"<span>{esc(r.text)}</span>")
            rows.append(f'<div>{"".join(parts)}</div>')
        just = {"left": "flex-start", "right": "flex-end"}.get(align, "center")
        css_color_ = "inherit" if color == "currentColor" else color
        div_style = (f"display:flex;flex-direction:column;align-items:{just};justify-content:center;"
                     f"width:100%;height:100%;font-size:{num(fs)}px;line-height:1.25;white-space:nowrap;"
                     f"color:{css_color_};text-align:{'center' if just == 'center' else align}")
        self.canvas.add(f'<foreignObject x="{num(x)}" y="{num(y)}" width="{num(wpx)}" height="{num(hpx)}" '
                        f'style="overflow:visible"{op}{rot}><div xmlns="{XHTML_NS}" style="{att(div_style)}">'
                        f'{"".join(rows)}</div></foreignObject>')
        return
    # 일반 글: <text>
    line_h = th / max(1, len(lines)) if lines else 0
    top = center[1] + th / 2
    anchor_attr = {"left": "start", "right": "end"}.get(align, "middle")
    out = [f'<text text-anchor="{anchor_attr}" fill="{att(color)}"'
           + (f' font-size="{num(fs)}"' if st.font_scale != 1 else "")
           + (' font-weight="700"' if st.bold else "")
           + (' font-style="italic"' if st.italic else "") + f"{op}{rot}>"]
    for k, ln in enumerate(lines):
        base_y = top - line_h * k - line_h * 0.76
        if anchor_attr == "start":
            x = center[0] - tw / 2
        elif anchor_attr == "end":
            x = center[0] + tw / 2
        else:
            x = center[0]
        spans = []
        for r in ln:
            a = ""
            if r.bold:
                a += ' font-weight="700"'
            if r.italic:
                a += ' font-style="italic"'
            if r.mono:
                a += ' font-family="var(--mono-font,monospace)"'
            spans.append(f"<tspan{a}>{esc(r.text)}</tspan>" if a else esc(r.text))
        out.append(f'<tspan x="{num(px(x))}" y="{num(py(base_y))}">{"".join(spans)}</tspan>')
    out.append("</text>")
    self.canvas.add("".join(out))


Engine.place_node = place_node  # type: ignore[attr-defined]
