"""단위, 색, 선·화살표·노드 스타일 해석. (담당: H)

길이는 내부에서 cm 로 다룬다. 색은 CSS 색 문자열로 바꾼다:
- 지정이 없거나 정확히 black 이면 'currentColor' (다크 모드에서 글자색을 따라감).
- fill 의 white 는 'var(--bg,#fff)' (다크 모드에서 배경색). 그 밖은 #rrggbb.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from .scan import keyvals, split_top, strip_braces

PT = 2.54 / 72.27            # 1pt (TeX) 의 cm
CM_PX = 37.8                 # 1cm = 37.8px (96dpi)
FONT_PT = 10.0               # TikZ 기본 글자 크기
EM = FONT_PT * PT            # 1em (cm)

UNITS = {
    "pt": PT, "cm": 1.0, "mm": 0.1, "in": 2.54, "bp": 2.54 / 72, "pc": 12 * PT,
    "dd": 1238 / 1157 * PT, "cc": 12 * 1238 / 1157 * PT, "sp": PT / 65536,
    "em": EM, "ex": 0.43 * EM, "px": 1 / CM_PX,
}
_DIM = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(pt|cm|mm|in|bp|pc|dd|cc|sp|em|ex|px)\s*$")

# ---------------------------------------------------------------- 색
BASE_COLORS: dict[str, tuple[float, float, float]] = {
    "red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1), "cyan": (0, 1, 1),
    "magenta": (1, 0, 1), "yellow": (1, 1, 0), "black": (0, 0, 0), "white": (1, 1, 1),
    "gray": (.5, .5, .5), "grey": (.5, .5, .5), "darkgray": (.25, .25, .25), "lightgray": (.75, .75, .75),
    "brown": (.75, .5, .25), "lime": (.75, 1, 0), "olive": (.5, .5, 0), "orange": (1, .5, 0),
    "pink": (1, .75, .75), "purple": (.75, 0, .25), "teal": (0, .5, .5), "violet": (.5, 0, .5),
}


def parse_color(spec: str) -> Optional[tuple[float, float, float]]:
    """xcolor 식 → RGB(0~1). 'blue!50' = 50% 파랑 + 흰색, 'red!30!black', 'blue!50!red!20'."""
    spec = (spec or "").strip()
    if not spec:
        return None
    parts = [p.strip() for p in spec.split("!")]
    base = BASE_COLORS.get(parts[0])
    if base is None:
        return None
    rgb = base
    i = 1
    while i < len(parts):
        try:
            pct = float(parts[i])
        except ValueError:
            return None
        pct = min(100.0, max(0.0, pct)) / 100
        other = (1.0, 1.0, 1.0)
        if i + 1 < len(parts):
            o = BASE_COLORS.get(parts[i + 1])
            if o is None:
                return None
            other = o
        rgb = tuple(pct * a + (1 - pct) * b for a, b in zip(rgb, other))
        i += 2
    return rgb  # type: ignore[return-value]


def is_color(spec: str) -> bool:
    return parse_color(spec) is not None


def css_color(spec: Optional[str], *, fill: bool = False) -> str:
    """색 이름 → SVG paint. None/모름/black → currentColor."""
    if spec is None or spec == "currentColor":
        return "currentColor"
    s = spec.strip()
    if s in ("black",):
        return "currentColor"
    if fill and s == "white":
        return "var(--bg,#fff)"
    rgb = parse_color(s)
    if rgb is None:
        return "currentColor"
    return "#%02x%02x%02x" % tuple(int(round(max(0, min(1, c)) * 255)) for c in rgb)


# ---------------------------------------------------------------- 선
LINE_WIDTHS = {"ultra thin": .1, "very thin": .2, "thin": .4, "semithick": .6, "thick": .8,
               "very thick": 1.2, "ultra thick": 1.6}
DASHES = {
    "solid": None,
    "dashed": ("on", 3, 3), "densely dashed": ("on", 3, 2), "loosely dashed": ("on", 3, 6),
    "dotted": ("dot", 2), "densely dotted": ("dot", 1), "loosely dotted": ("dot", 4),
    "dash dot": ("dd", 3, 2), "dashdotted": ("dd", 3, 2), "densely dash dot": ("dd", 3, 1),
    "loosely dash dot": ("dd", 3, 4),
}

# 화살표 끝 이름 → 종류
TIP_KINDS = {
    ">": "to", "<": "to", "to": "to", "To": "to", "": None,
    "stealth": "stealth", "Stealth": "stealth", "latex": "latex", "Latex": "latex",
    "Triangle": "latex", "triangle 45": "latex", "Kite": "stealth",
    "|": "bar", "Bar": "bar", "Circle": "circle", "*": "circle", "o": "ocircle",
    ">>": "to2", "<<": "to2", "Straight Barb": "to", "Classical TikZ Rightarrow": "to",
    "Computer Modern Rightarrow": "to", "Rays": "bar", "Square": "square",
}
_TIP_TOKEN = re.compile(r"^(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|>>|<<|[<>|*o]|stealth|latex|to|Stealth|Latex|Triangle|Circle|Bar|Kite|Square)?$")


def parse_arrow_key(key: str) -> Optional[tuple[Optional[str], Optional[str]]]:
    """'->', '<->', '-{Stealth}', '{Stealth[length=3mm]}-latex', '|-|' → (시작 끝 이름, 끝 이름)."""
    k = key.strip()
    if "-" not in k or "=" in k:
        return None
    # 최상위 '-' 하나로 나눈다 (중괄호 안 제외)
    depth = 0
    pos = -1
    for i, c in enumerate(k):
        if c == "{" or c == "[":
            depth += 1
        elif c == "}" or c == "]":
            depth -= 1
        elif c == "-" and depth == 0:
            if pos >= 0:
                return None
            pos = i
    if pos < 0:
        return None
    a, b = k[:pos].strip(), k[pos + 1:].strip()
    if not (_TIP_TOKEN.match(a) and _TIP_TOKEN.match(b)):
        return None
    return (_tip_name(a), _tip_name(b))


def _tip_name(t: str) -> Optional[str]:
    t = t.strip()
    if t.startswith("{") and t.endswith("}"):
        t = t[1:-1].strip()
    t = re.sub(r"\[.*\]$", "", t).strip()
    return t or None


def tip_kind(name: Optional[str], default: str) -> Optional[str]:
    if name is None:
        return None
    if name in (">", "<"):
        name = default
    kind = TIP_KINDS.get(name)
    if kind is None:
        kind = TIP_KINDS.get(name.capitalize(), "stealth")
    return kind


# ---------------------------------------------------------------- 스타일 상태
@dataclass
class Style:
    color: Optional[str] = None           # 기본 색 (None = currentColor)
    draw: Any = None                      # None=안 그림, True=color 사용, 문자열=색
    fill: Any = None
    text: Optional[str] = None            # 글자 색 (None = color)
    line_width: float = 0.4               # pt
    dash: Any = None
    arrows: tuple = (None, None)
    default_tip: str = ">"
    opacity: float = 1.0
    draw_opacity: float = 1.0
    fill_opacity: float = 1.0
    text_opacity: float = 1.0
    rounded: float = 0.0                  # cm
    line_cap: Optional[str] = None
    line_join: Optional[str] = None
    # 노드
    shape: str = "rectangle"
    inner_xsep: float = 0.3333 * EM
    inner_ysep: float = 0.3333 * EM
    outer_sep: float = 0.0
    min_width: float = 0.0
    min_height: float = 0.0
    font_scale: float = 1.0
    bold: bool = False
    italic: bool = False
    anchor: Optional[str] = None
    place: Optional[tuple] = None         # (방향, 거리 cm 또는 None, of 이름 또는 None)
    pos: Optional[float] = None
    sloped: bool = False
    align: Optional[str] = None
    text_width: Optional[float] = None
    node_shift: tuple = (0.0, 0.0)        # 노드 xshift/yshift (cm, 캔버스)
    node_distance: float = 1.0
    labels: tuple = ()                    # (방향, 글) 목록
    node_rotate: float = 0.0
    # 경로·plot
    domain: tuple = (-5.0, 5.0)
    domain_set: bool = False
    samples: int = 25
    samples_set: bool = False
    smooth: bool = False
    variable: str = "x"
    closed_plot: bool = False
    step: tuple = (1.0, 1.0)
    radius: Optional[float] = None
    x_radius: Optional[float] = None
    y_radius: Optional[float] = None
    start_angle: Optional[float] = None
    end_angle: Optional[float] = None
    delta_angle: Optional[float] = None
    bend: Optional[float] = None          # 양수=left
    out_angle: Optional[float] = None
    in_angle: Optional[float] = None
    looseness: float = 1.0
    use_as_bbox: bool = False
    clip: bool = False
    # 좌표계
    matrix: tuple = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)   # SVG 관례 (a b c d e f), 단위 cm
    xvec: tuple = (1.0, 0.0)
    yvec: tuple = (0.0, 1.0)
    every_node: str = ""                  # every node/.style 내용 (노드에 적용)
    # pgfplots 표식
    mark: Optional[str] = None
    mark_size: float = 2.0                # pt
    only_marks: bool = False
    mark_fill: Optional[str] = None

    def copy(self, **kw) -> "Style":
        return replace(self, **kw)

    def stroke_paint(self) -> Optional[str]:
        if self.draw is None or self.draw is False:
            return None
        if self.draw is True:
            return css_color(self.color)
        return css_color(self.draw)

    def fill_paint(self) -> Optional[str]:
        if self.fill is None or self.fill is False:
            return None
        if self.fill is True:
            return css_color(self.color, fill=True)
        return css_color(self.fill, fill=True)

    def text_paint(self) -> str:
        return css_color(self.text if self.text is not None else self.color)


def mat_mul(m: tuple, n: tuple) -> tuple:
    """m ∘ n (n 을 먼저 적용)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def mat_apply(m: tuple, p: tuple) -> tuple:
    a, b, c, d, e, f = m
    return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)


def mat_linear(m: tuple, v: tuple) -> tuple:
    a, b, c, d, _, _ = m
    return (a * v[0] + c * v[1], b * v[0] + d * v[1])


def mat_scale_factor(m: tuple) -> float:
    a, b, c, d, _, _ = m
    return math.sqrt(abs(a * d - b * c)) or 1.0


DIRECTIONS = {
    "above": "south", "below": "north", "left": "east", "right": "west",
    "above left": "south east", "above right": "south west",
    "below left": "north east", "below right": "north west",
}
POS_WORDS = {"midway": 0.5, "near start": 0.25, "near end": 0.75, "very near start": 0.125,
             "very near end": 0.875, "at start": 0.0, "at end": 1.0}
SHAPES = {"rectangle", "circle", "coordinate", "ellipse"}
FONT_SIZES = {"tiny": .5, "scriptsize": .7, "footnotesize": .8, "small": .9, "normalsize": 1.0,
              "large": 1.2, "Large": 1.44, "LARGE": 1.73, "huge": 2.07, "Huge": 2.49}


class StyleApplier:
    """옵션 목록을 Style 에 적용한다. 숫자는 evaluator(text)->float|None, 길이는 length(text)->cm|None.

    사용자 스타일(\\tikzset{이름/.style=…})은 styles 사전에서 펼친다 (깊이 32 상한).
    """

    def __init__(self, engine):
        self.e = engine
        self.styles: dict[str, tuple[str, Optional[str]]] = {
            "help lines": ("color=gray!60, line width=0.2pt", None),
            "every picture": ("", None),
        }

    # ------------------------------------------------------------ 정의
    def define(self, text: str, problems: list) -> None:
        for key, val in keyvals(text):
            self.define_one(key, val, problems)

    def define_one(self, key: str, val: Optional[str], problems: list) -> bool:
        m = re.match(r"^(.*?)\s*/\.(style|append style|default|code|estyle)$", key)
        if not m:
            return False
        name, what = m.group(1).strip(), m.group(2)
        if what == "code":
            problems.append(f"/.code 키는 지원하지 않는다: {name}")
            return True
        if what == "default":
            body, _ = self.styles.get(name, ("", None))
            self.styles[name] = (body, val or "")
            return True
        if what == "append style":
            body, dflt = self.styles.get(name, ("", None))
            self.styles[name] = ((body + ", " if body else "") + (val or ""), dflt)
        else:
            self.styles[name] = (val or "", self.styles.get(name, ("", None))[1])
        return True

    # ------------------------------------------------------------ 적용
    def apply(self, st: Style, text: Optional[str], *, node: bool = False, depth: int = 0) -> Style:
        if not text:
            return st
        if depth > 32:
            self.e.problem("스타일이 너무 깊게 중첩되었다")
            return st
        for key, val in keyvals(text):
            try:
                st = self.apply_one(st, key, val, node=node, depth=depth)
            except Exception:  # noqa: BLE001 - 옵션 하나가 이상해도 계속
                self.e.problem(f"옵션을 해석하지 못했다: {key}")
        return st

    def apply_one(self, st: Style, key: str, val: Optional[str], *, node: bool, depth: int) -> Style:
        e = self.e
        if self.define_one(key, val, e.problems):
            return st
        if key in self.styles:
            body, dflt = self.styles[key]
            arg = val if val is not None else (dflt or "")
            return self.apply(st, body.replace("#1", arg), node=node, depth=depth + 1)
        if key.startswith("every ") and key.endswith("/.style"):
            return st
        if key in ("every node/.style", "every node/.append style"):
            return st
        if val is None:
            return self.apply_flag(st, key, node=node)
        return self.apply_value(st, key, val, node=node, depth=depth)

    def apply_flag(self, st: Style, key: str, *, node: bool) -> Style:
        if key in LINE_WIDTHS:
            return st.copy(line_width=LINE_WIDTHS[key])
        if key in DASHES:
            return st.copy(dash=DASHES[key])
        if key == "draw":
            return st.copy(draw=True)
        if key == "fill":
            return st.copy(fill=True)
        if key == "smooth":
            return st.copy(smooth=True)
        if key in ("sharp plot", "sharp corners"):
            return st.copy(smooth=False) if key == "sharp plot" else st.copy(rounded=0.0)
        if key == "rounded corners":
            return st.copy(rounded=4 * PT)
        if key in SHAPES:
            return st.copy(shape=key)
        if key == "circle" or key == "rectangle":
            return st.copy(shape=key)
        if key in DIRECTIONS:
            return st.copy(place=(key, None, None), anchor=None)
        if key in POS_WORDS:
            return st.copy(pos=POS_WORDS[key])
        if key == "sloped":
            return st.copy(sloped=True)
        if key in ("bend left", "bend right"):
            return st.copy(bend=30.0 if key == "bend left" else -30.0)
        if key == "use as bounding box":
            return st.copy(use_as_bbox=True)
        if key == "clip":
            return st.copy(clip=True)
        if key == "only marks":
            return st.copy(only_marks=True)
        if key == "no marks" or key == "no markers":
            return st.copy(mark=None)
        if key == "closed":
            return st.copy(closed_plot=True)
        if key == "transform shape":
            return st
        if key in ("solid",):
            return st.copy(dash=None)
        if key.startswith("\\") and key[1:] in FONT_SIZES:
            return st.copy(font_scale=FONT_SIZES[key[1:]])
        arrows = parse_arrow_key(key)
        if arrows is not None:
            return st.copy(arrows=arrows)
        if is_color(key):
            return st.copy(color=key, text=None)
        if key in ("thin", "help lines"):
            return st
        if key.startswith("<") and key.endswith(">"):
            return st
        self.e.problem(f"모르는 옵션은 무시했다: {key}")
        return st

    def apply_value(self, st: Style, key: str, val: str, *, node: bool, depth: int) -> Style:
        e = self.e
        L = e.length
        N = e.number
        if key in ("color",):
            return st.copy(color=val, text=None) if is_color(val) else st
        if key == "draw":
            if val == "none":
                return st.copy(draw=None)
            return st.copy(draw=val if is_color(val) else True)
        if key == "fill":
            if val == "none":
                return st.copy(fill=None)
            return st.copy(fill=val if is_color(val) else True)
        if key in ("text", "text color", "font color"):
            return st.copy(text=val) if is_color(val) else st
        if key == "line width":
            v = L(val, unit="pt")
            return st.copy(line_width=v / PT) if v is not None else st
        if key == "opacity":
            v = N(val)
            return st.copy(opacity=_clamp01(v)) if v is not None else st
        if key == "draw opacity":
            v = N(val)
            return st.copy(draw_opacity=_clamp01(v)) if v is not None else st
        if key == "fill opacity":
            v = N(val)
            return st.copy(fill_opacity=_clamp01(v)) if v is not None else st
        if key == "text opacity":
            v = N(val)
            return st.copy(text_opacity=_clamp01(v)) if v is not None else st
        if key == "rounded corners":
            v = L(val, unit="pt")
            return st.copy(rounded=v) if v is not None else st
        if key == "line cap":
            return st.copy(line_cap={"round": "round", "rect": "square", "butt": "butt"}.get(val))
        if key == "line join":
            return st.copy(line_join={"round": "round", "bevel": "bevel", "miter": "miter"}.get(val))
        if key == ">":
            return st.copy(default_tip=_tip_name(val) or ">")
        if key == "arrows":
            a = parse_arrow_key(val)
            return st.copy(arrows=a) if a else st
        if key in ("inner sep", "inner xsep", "inner ysep"):
            v = L(val, unit="pt")
            if v is None:
                return st
            if key == "inner sep":
                return st.copy(inner_xsep=v, inner_ysep=v)
            return st.copy(inner_xsep=v) if key == "inner xsep" else st.copy(inner_ysep=v)
        if key == "outer sep":
            v = L(val, unit="pt")
            return st.copy(outer_sep=v) if v is not None else st
        if key in ("minimum width", "minimum height", "minimum size"):
            v = L(val, unit="cm")
            if v is None:
                return st
            if key == "minimum size":
                return st.copy(min_width=v, min_height=v)
            return st.copy(min_width=v) if key == "minimum width" else st.copy(min_height=v)
        if key == "shape":
            return st.copy(shape=val) if val in SHAPES else st
        if key == "anchor":
            return st.copy(anchor=val, place=None)
        if key in DIRECTIONS:
            return st.copy(place=self.parse_place(key, val), anchor=None)
        if key == "pos":
            v = N(val)
            return st.copy(pos=v) if v is not None else st
        if key == "font":
            scale, bold, italic = st.font_scale, st.bold, st.italic
            for w in re.findall(r"\\([A-Za-z]+)", val):
                if w in FONT_SIZES:
                    scale = FONT_SIZES[w]
                elif w in ("bfseries", "bf"):
                    bold = True
                elif w in ("itshape", "it"):
                    italic = True
            return st.copy(font_scale=scale, bold=bold, italic=italic)
        if key == "align":
            return st.copy(align=val)
        if key == "text width":
            v = L(val, unit="cm")
            return st.copy(text_width=v)
        if key in ("xshift", "yshift"):
            v = L(val, unit="cm")
            if v is None:
                return st
            if node:
                dx, dy = st.node_shift
                return st.copy(node_shift=(dx + v, dy) if key == "xshift" else (dx, dy + v))
            t = (1, 0, 0, 1, v, 0) if key == "xshift" else (1, 0, 0, 1, 0, v)
            return st.copy(matrix=mat_mul(st.matrix, t))
        if key == "shift":
            p = e.coord_value(val, st)
            if p is None:
                return st
            # shift 는 현재 좌표계 기준 (캔버스로 바꾼 값에서 원점 이동)
            origin = mat_apply(st.matrix, (0, 0))
            dx, dy = p[0] - origin[0], p[1] - origin[1]
            m = st.matrix
            return st.copy(matrix=(m[0], m[1], m[2], m[3], m[4] + dx, m[5] + dy))
        if key in ("scale", "xscale", "yscale"):
            v = N(val)
            if v is None or not math.isfinite(v):
                return st
            sx = v if key in ("scale", "xscale") else 1
            sy = v if key in ("scale", "yscale") else 1
            return st.copy(matrix=mat_mul(st.matrix, (sx, 0, 0, sy, 0, 0)))
        if key == "rotate":
            v = N(val)
            if v is None:
                return st
            if node:
                return st.copy(node_rotate=v)
            c, s = math.cos(math.radians(v)), math.sin(math.radians(v))
            return st.copy(matrix=mat_mul(st.matrix, (c, s, -s, c, 0, 0)))
        if key in ("x", "y"):
            v = L(val, unit="cm")
            if v is not None:
                vec = (v, 0.0) if key == "x" else (0.0, v)
            else:
                p = e.coord_value(val, Style())
                if p is None:
                    return st
                vec = p
            return st.copy(xvec=vec) if key == "x" else st.copy(yvec=vec)
        if key == "domain":
            parts = val.split(":")
            if len(parts) == 2:
                a, b = N(parts[0]), N(parts[1])
                if a is not None and b is not None:
                    return st.copy(domain=(a, b), domain_set=True)
            return st
        if key == "samples":
            v = N(val)
            if v is None or not math.isfinite(v):
                return st
            n = int(round(v))
            if n > 1000:
                e.problem(f"samples={n} 이 상한 1,000을 넘어 1,000으로 줄였다")
                n = 1000
            return st.copy(samples=max(2, n), samples_set=True)
        if key == "variable":
            return st.copy(variable=val.strip().lstrip("\\") or "x")
        if key == "step":
            v = L(val, unit="cm")
            if v is not None:
                return st.copy(step=(v, v))
            p = e.coord_value(val, Style())
            return st.copy(step=(abs(p[0]) or 1, abs(p[1]) or 1)) if p else st
        if key in ("xstep", "ystep"):
            v = L(val, unit="cm")
            if v is None:
                return st
            sx, sy = st.step
            return st.copy(step=(v, sy) if key == "xstep" else (sx, v))
        if key in ("radius", "x radius", "y radius"):
            v = L(val, unit="cm")
            if v is None:
                return st
            if key == "radius":
                return st.copy(radius=v)
            return st.copy(x_radius=v) if key == "x radius" else st.copy(y_radius=v)
        if key in ("start angle", "end angle", "delta angle"):
            v = N(val)
            if v is None:
                return st
            return st.copy(**{key.replace(" ", "_"): v})
        if key in ("bend left", "bend right"):
            v = N(val)
            if v is None:
                return st
            return st.copy(bend=v if key == "bend left" else -v)
        if key in ("out", "in"):
            v = N(val)
            return st.copy(out_angle=v) if key == "out" else st.copy(in_angle=v)
        if key == "looseness":
            v = N(val)
            return st.copy(looseness=v) if v is not None else st
        if key == "node distance":
            v = L(val.split(" and ")[0], unit="cm")
            return st.copy(node_distance=v) if v is not None else st
        if key == "label":
            return st.copy(labels=st.labels + (val,))
        if key == "dash pattern":
            ons = re.findall(r"(on|off)\s+([^\s]+)", val)
            arr = []
            for _, d in ons:
                v = L(d, unit="pt")
                if v is not None:
                    arr.append(v / PT)
            return st.copy(dash=("raw",) + tuple(arr)) if arr else st
        if key == "mark":
            return st.copy(mark=val.strip())
        if key == "mark size":
            v = L(val, unit="pt")
            return st.copy(mark_size=v / PT) if v is not None else st
        if key == "mark options":
            sub = self.apply(Style(color=st.color), val, depth=depth + 1)
            fillc = sub.fill if isinstance(sub.fill, str) else (sub.color if sub.color != st.color else None)
            return st.copy(mark_fill=fillc)
        if key in ("every node", "every node/.style"):
            return st.copy(every_node=val)
        if key in ("minimum", "label distance", "pin", "text height", "text depth", "baseline"):
            return st
        if key in ("execute at begin node", "execute at end node", "decoration", "decorate",
                   "postaction", "preaction", "pattern", "shading", "path picture"):
            e.problem(f"지원하지 않는 옵션을 무시했다: {key}")
            return st
        e.problem(f"모르는 옵션은 무시했다: {key}")
        return st

    def parse_place(self, key: str, val: str) -> tuple:
        v = val.strip()
        m = re.match(r"^(.*?)\bof\s+(.+)$", v)
        if m:
            dist_txt = m.group(1).strip()
            name = m.group(2).strip()
            dist = None
            if dist_txt:
                dist = self.e.length(dist_txt.split(" and ")[0], unit="cm")
            return (key, dist, name)
        d = self.e.length(v, unit="cm")
        return (key, d, None)


def _clamp01(v: float) -> float:
    if v is None or not math.isfinite(v):
        return 1.0
    return max(0.0, min(1.0, v))


def parse_dim(text: str) -> Optional[float]:
    """'2pt' → cm. 단위 없는 숫자는 None (호출 쪽이 기본 단위를 정함)."""
    m = _DIM.match(text or "")
    if not m:
        return None
    return float(m.group(1)) * UNITS[m.group(2)]


def unit_suffix(text: str) -> tuple[str, Optional[str]]:
    """'2*3 cm' → ('2*3', 'cm'). 끝에 단위가 없으면 (text, None)."""
    m = re.match(r"^(.*?)(?<![A-Za-z\\])\s*(pt|cm|mm|in|bp|pc|dd|cc|sp|em|ex|px)\s*$", text or "", re.S)
    if m and m.group(1).strip():
        return m.group(1), m.group(2)
    return text, None


__all__ = ["Style", "StyleApplier", "css_color", "parse_color", "is_color", "parse_dim",
           "unit_suffix", "PT", "CM_PX", "EM", "FONT_PT", "mat_mul", "mat_apply", "mat_linear",
           "mat_scale_factor", "tip_kind", "DIRECTIONS", "split_top", "strip_braces"]
