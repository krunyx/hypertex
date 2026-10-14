"""SVG 출력: 캔버스(그룹·경로·글·잘라내기), 노드 글 해석과 크기 근사. (담당: H)

내부 좌표는 cm, y 위쪽이 양수(TikZ 관례). 출력할 때 px(=cm×37.8)로, y 를 뒤집는다.
모든 글과 속성값은 html.escape 를 거친다. 스크립트·이벤트 속성·href 를 만들지 않는다.
"""
from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass, field
from typing import Optional

from .styles import CM_PX, EM, FONT_PT, PT

SVG_NS = "http://www.w3.org/2000/svg"
XHTML_NS = "http://www.w3.org/1999/xhtml"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"
FONT_PX = FONT_PT * PT * CM_PX          # 10pt = 13.33px (viewBox 단위)
BODY_FONT = "var(--body-font,serif)"


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def att(s) -> str:
    return html.escape(str(s), quote=True)


def num(v: float) -> str:
    if not math.isfinite(v):
        v = 0.0
    s = f"{v:.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def px(x: float) -> float:
    return x * CM_PX


def py(y: float) -> float:
    return -y * CM_PX


def path_d(segs: list) -> str:
    out = []
    for s in segs:
        k = s[0]
        if k == "M":
            out.append(f"M{num(px(s[1][0]))} {num(py(s[1][1]))}")
        elif k == "L":
            out.append(f"L{num(px(s[1][0]))} {num(py(s[1][1]))}")
        elif k == "C":
            out.append("C" + " ".join(f"{num(px(p[0]))} {num(py(p[1]))}" for p in s[1:4]))
        elif k == "Z":
            out.append("Z")
    return "".join(out)


# ====================================================================== 노드 글
@dataclass
class Run:
    kind: str            # "text" | "math"
    text: str
    bold: bool = False
    italic: bool = False
    mono: bool = False


_SIMPLE_ESC = {"%": "%", "&": "&", "_": "_", "#": "#", "$": "$", "{": "{", "}": "}",
               ",": "\u2009", ";": "\u2005", " ": " ", "!": "", "/": "", "-": ""}
_SYMBOLS = {"ldots": "…", "dots": "…", "textendash": "–", "textemdash": "—", "LaTeX": "LaTeX",
            "TeX": "TeX", "quad": "\u2003", "qquad": "\u2003\u2003", "degree": "°",
            "textdegree": "°", "times": "×", "pm": "±", "S": "§", "copyright": "©",
            "textbackslash": "\\", "par": "\n", "newline": "\n"}
_IGNORE_CMDS = {"tiny", "scriptsize", "footnotesize", "small", "normalsize", "large", "Large",
                "LARGE", "huge", "Huge", "centering", "raggedright", "raggedleft", "bfseries",
                "itshape", "rmfamily", "sffamily", "ttfamily", "upshape", "mdseries", "strut",
                "noindent", "hfill", "relax", "displaystyle"}


def parse_node_text(s: str) -> list[list[Run]]:
    """노드 글 → 줄 목록(각 줄은 Run 목록)."""
    lines: list[list[Run]] = [[]]
    _parse_into(s or "", lines, False, False, False, 0)
    # 빈 줄 정리
    out = []
    for ln in lines:
        merged: list[Run] = []
        for r in ln:
            if merged and merged[-1].kind == r.kind == "text" and (merged[-1].bold, merged[-1].italic,
                                                                     merged[-1].mono) == (r.bold, r.italic, r.mono):
                merged[-1].text += r.text
            else:
                merged.append(r)
        out.append(merged)
    while len(out) > 1 and not out[-1]:
        out.pop()
    return out


def _find_math_end(s: str, i: int, closer: str) -> int:
    j = i
    while j < len(s):
        if s[j] == "\\":
            if s.startswith(closer, j):
                return j
            j += 2
            continue
        if s.startswith(closer, j):
            return j
        j += 1
    return -1


def _brace_arg(s: str, i: int) -> tuple[str, int]:
    while i < len(s) and s[i] == " ":
        i += 1
    if i < len(s) and s[i] == "{":
        depth = 0
        j = i
        while j < len(s):
            c = s[j]
            if c == "\\":
                j += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    if i < len(s):
        return s[i], i + 1
    return "", i


def _parse_into(s: str, lines: list, bold: bool, italic: bool, mono: bool, depth: int) -> None:
    if depth > 20:
        lines[-1].append(Run("text", s))
        return
    i, n = 0, len(s)
    buf: list[str] = []

    def flush():
        if buf:
            lines[-1].append(Run("text", "".join(buf), bold, italic, mono))
            buf.clear()

    while i < n:
        c = s[i]
        if c == "$":
            if s.startswith("$$", i):
                j = _find_math_end(s, i + 2, "$$")
                if j >= 0:
                    flush()
                    lines[-1].append(Run("math", s[i + 2:j]))
                    i = j + 2
                    continue
            j = _find_math_end(s, i + 1, "$")
            if j >= 0:
                flush()
                lines[-1].append(Run("math", s[i + 1:j]))
                i = j + 1
                continue
            buf.append("$")
            i += 1
            continue
        if c == "\\":
            if s.startswith("\\(", i):
                j = _find_math_end(s, i + 2, "\\)")
                if j >= 0:
                    flush()
                    lines[-1].append(Run("math", s[i + 2:j]))
                    i = j + 2
                    continue
            if s.startswith("\\\\", i):
                flush()
                lines.append([])
                i += 2
                # \\[2pt] 같은 간격 인수 건너뛰기
                if i < n and s[i] == "[":
                    k = s.find("]", i)
                    i = n if k < 0 else k + 1
                continue
            m = re.match(r"\\([A-Za-z]+)\s*", s[i:])
            if not m:
                ch = s[i + 1] if i + 1 < n else ""
                buf.append(_SIMPLE_ESC.get(ch, ch))
                i += 2
                continue
            name = m.group(1)
            i += m.end()
            if name in ("textbf", "textit", "emph", "texttt", "textrm", "textsf", "text", "mbox",
                        "textup", "textnormal", "underline", "textsc"):
                arg, i = _brace_arg(s, i)
                flush()
                _parse_into(arg, lines, bold or name == "textbf", italic or name in ("textit", "emph"),
                            mono or name == "texttt", depth + 1)
                continue
            if name in ("textcolor", "color"):
                _, i = _brace_arg(s, i)
                if name == "textcolor":
                    arg, i = _brace_arg(s, i)
                    flush()
                    _parse_into(arg, lines, bold, italic, mono, depth + 1)
                continue
            if name in _SYMBOLS:
                sym = _SYMBOLS[name]
                if sym == "\n":
                    flush()
                    lines.append([])
                else:
                    buf.append(sym)
                continue
            if name in _IGNORE_CMDS:
                continue
            # 모르는 명령: 이름은 버리고 인수는 글로
            continue
        if c in "{}":
            i += 1
            continue
        if c == "~":
            buf.append("\u00a0")
            i += 1
            continue
        if c == "-" and s.startswith("---", i):
            buf.append("—")
            i += 3
            continue
        if c == "-" and s.startswith("--", i):
            buf.append("–")
            i += 2
            continue
        if c in "\n\t":
            buf.append(" ")
            i += 1
            continue
        buf.append(c)
        i += 1
    flush()


def _is_wide(ch: str) -> bool:
    o = ord(ch)
    return (0x1100 <= o <= 0x11FF or 0x2E80 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF
            or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFF60 or 0x3130 <= o <= 0x318F)


def text_width_em(t: str, bold: bool = False, mono: bool = False) -> float:
    w = 0.0
    for ch in t:
        if mono:
            w += 0.6 if not _is_wide(ch) else 1.0
        elif _is_wide(ch):
            w += 1.0
        elif ch in " \u00a0":
            w += 0.28
        elif ch in "\u2009\u2005":
            w += 0.2
        elif ch in "\u2003":
            w += 1.0
        elif ch in "il.,;:'|!`":
            w += 0.28
        elif ch in "mwMW":
            w += 0.85
        elif ch.isupper():
            w += 0.7
        elif ch.isdigit():
            w += 0.5
        elif ch.isalpha():
            w += 0.5
        else:
            w += 0.5
    return w * (1.06 if bold else 1.0)


_MATH_FUNCS = {"sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp", "lim", "max", "min",
               "det", "sinh", "cosh", "tanh", "arg", "deg", "dim", "ker", "sup", "inf", "Pr", "gcd",
               "arcsin", "arccos", "arctan", "Tr", "tr"}
_MATH_SPACE = {",": .17, ":": .22, ";": .28, "!": -.17, "quad": 1.0, "qquad": 2.0, " ": .28,
               "enspace": .5, "thinspace": .17}
_MATH_ZERO = {"left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "textstyle",
              "scriptstyle", "limits", "nolimits", "mathrm", "mathbf", "mathit", "mathsf",
              "mathcal", "mathbb", "boldsymbol", "operatorname", "text", "mathfrak", "hat", "bar",
              "vec", "dot", "ddot", "tilde", "widehat", "widetilde", "overline", "underline"}


def math_size_em(tex: str, depth: int = 0) -> tuple[float, float]:
    """수식 근사 (너비, 높이) em."""
    w, h = 0.0, 1.15
    i, n = 0, len(tex)
    while i < n:
        if depth > 12:
            return w + 0.55 * (n - i), h
        c = tex[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+)", tex[i:])
            if not m:
                ch = tex[i + 1] if i + 1 < n else ""
                w += _MATH_SPACE.get(ch, 0.5)
                i += 2
                continue
            name = m.group(1)
            i += m.end()
            if name in ("frac", "dfrac", "tfrac", "binom"):
                a, i = _brace_arg(tex, i)
                b, i = _brace_arg(tex, i)
                sc = 0.75 if name != "dfrac" else 1.0
                wa, ha = math_size_em(a, depth + 1)
                wb, hb = math_size_em(b, depth + 1)
                w += max(wa, wb) * sc + 0.25
                h = max(h, (ha + hb) * sc + 0.3)
            elif name == "sqrt":
                a, i = _brace_arg(tex, i)
                wa, ha = math_size_em(a, depth + 1)
                w += wa + 0.8
                h = max(h, ha + 0.2)
            elif name in ("text", "mathrm", "operatorname", "textrm", "textbf", "mbox"):
                a, i = _brace_arg(tex, i)
                w += text_width_em(a) + (0.15 if name == "operatorname" else 0)
            elif name in _MATH_FUNCS:
                w += 0.5 * len(name) + 0.17
            elif name in _MATH_SPACE:
                w += _MATH_SPACE[name]
            elif name in _MATH_ZERO:
                pass
            elif name in ("sum", "prod", "int", "oint", "bigcup", "bigcap"):
                w += 1.0 if name != "int" else 0.6
                h = max(h, 1.6)
            elif name in ("cdot", "times", "pm", "mp", "leq", "geq", "le", "ge", "neq", "approx",
                          "equiv", "to", "rightarrow", "leftarrow", "Rightarrow", "mapsto", "in",
                          "subset", "sim", "propto", "cdots", "ldots"):
                w += 1.0
            else:
                w += 0.62
            continue
        if c in "^_":
            a, i = _brace_arg(tex, i + 1)
            wa, ha = math_size_em(a, depth + 1)
            w += wa * 0.7
            h = max(h, 1.45)
            continue
        if c in "{}":
            i += 1
            continue
        if c in "=<>+-":
            w += 0.78 if c != "-" or (i > 0 and tex[i - 1] not in "({[^_") else 0.6
        elif c in ",;":
            w += 0.3
        elif c in "()[]|":
            w += 0.39
        elif c == " ":
            pass
        elif c == "&":
            pass
        elif c.isdigit() or c == ".":
            w += 0.5
        elif _is_wide(c):
            w += 1.0
        else:
            w += 0.56
        i += 1
    return w, h


def measure(lines: list[list[Run]], scale: float = 1.0) -> tuple[float, float, list[float]]:
    """(너비 cm, 높이 cm, 줄별 너비 cm). 높이는 글자 높이+깊이."""
    em = EM * scale
    widths, heights = [], []
    for ln in lines:
        w, h = 0.0, 0.95
        for r in ln:
            if r.kind == "math":
                mw, mh = math_size_em(r.text)
                w += mw * 1.07
                h = max(h, mh)
            else:
                w += text_width_em(r.text, r.bold, r.mono)
        widths.append(w * em)
        heights.append(h)
    if not lines or (len(lines) == 1 and not lines[0]):
        return 0.0, 0.0, [0.0]
    total_h = sum(heights) + 0.25 * (len(lines) - 1)
    return max(widths), total_h * em, widths


def has_math(lines: list[list[Run]]) -> bool:
    return any(r.kind == "math" for ln in lines for r in ln)


# ====================================================================== 캔버스
@dataclass
class _Group:
    attrs: str
    items: list = field(default_factory=list)


class Canvas:
    def __init__(self, id_prefix: str):
        self.root = _Group("")
        self.stack = [self.root]
        self.defs: list[str] = []
        self.bbox: Optional[list[float]] = None
        self.fixed_bbox: Optional[list[float]] = None
        self.id_prefix = id_prefix
        self.ids = 0
        self.count = 0

    def new_id(self, kind: str) -> str:
        self.ids += 1
        return f"{self.id_prefix}-{kind}{self.ids}"

    # ------------------------------------------------------------ 경계
    def extend(self, x: float, y: float, pad: float = 0.0) -> None:
        if not (math.isfinite(x) and math.isfinite(y)):
            return
        if self.bbox is None:
            self.bbox = [x - pad, y - pad, x + pad, y + pad]
        else:
            b = self.bbox
            b[0] = min(b[0], x - pad)
            b[1] = min(b[1], y - pad)
            b[2] = max(b[2], x + pad)
            b[3] = max(b[3], y + pad)

    def extend_segs(self, segs: list, pad: float = 0.0) -> None:
        for s in segs:
            for p in s[1:]:
                self.extend(p[0], p[1], pad)

    # ------------------------------------------------------------ 그룹
    def push(self, attrs: str) -> None:
        g = _Group(attrs)
        self.stack[-1].items.append(g)
        self.stack.append(g)

    def pop(self) -> None:
        if len(self.stack) > 1:
            self.stack.pop()

    def add(self, frag: str) -> None:
        self.stack[-1].items.append(frag)
        self.count += 1

    def clip(self, segs: list) -> None:
        """현재 그룹의 나머지에 잘라내기를 건다: 새 그룹을 열고 스택에 남긴다(그룹 끝까지)."""
        cid = self.new_id("clip")
        self.defs.append(f'<clipPath id="{cid}"><path d="{path_d(segs)}"/></clipPath>')
        g = _Group(f' clip-path="url(#{cid})"')
        self.stack[-1].items.append(g)
        # 같은 깊이에 남겨 두고 이후 그리기는 이 그룹 안으로
        self.stack[-1] = self.stack[-1]  # noqa: PLW0127 (자리 유지)
        self.stack.append(g)
        self._clip_marks = getattr(self, "_clip_marks", [])
        self._clip_marks.append(len(self.stack))

    def depth(self) -> int:
        return len(self.stack)

    def unwind(self, depth: int) -> None:
        while len(self.stack) > max(1, depth):
            self.stack.pop()

    # ------------------------------------------------------------ 출력
    def to_svg(self, pad_px: float = 4.0, extra_style: str = "") -> str:
        b = self.fixed_bbox or self.bbox or [0.0, 0.0, 0.0, 0.0]
        x0, y0 = px(b[0]) - pad_px, py(b[3]) - pad_px
        w = max(px(b[2]) - px(b[0]) + 2 * pad_px, 1.0)
        h = max(py(b[1]) - py(b[3]) + 2 * pad_px, 1.0)
        width_em = w / FONT_PX
        style = (f"display:block;margin:0 auto;width:{num(width_em)}em;max-width:100%;height:auto;"
                 f"overflow:visible;font-family:{BODY_FONT}")
        parts = [f'<svg xmlns="{SVG_NS}" class="htex-tikz" viewBox="{num(x0)} {num(y0)} {num(w)} {num(h)}" '
                 f'role="img" font-size="{num(FONT_PX)}" style="{att(style + extra_style)}">']
        if self.defs:
            parts.append("<defs>" + "".join(self.defs) + "</defs>")
        self._emit(self.root, parts)
        parts.append("</svg>")
        return "".join(parts)

    def _emit(self, g: _Group, out: list) -> None:
        for it in g.items:
            if isinstance(it, _Group):
                if not it.items:
                    continue
                out.append(f"<g{it.attrs}>")
                self._emit(it, out)
                out.append("</g>")
            else:
                out.append(it)
