"""가환 그림(commutative diagram) → MathML 격자. (4단계, 담당 K)

세 가지 문법을 받는다.
- xy-pic   : \\xymatrix@C=2em{ A \\ar[r]^f \\ar[d]_g & B \\\\ C & D }
- tikz-cd  : \\begin{tikzcd} A \\arrow[r, "f"] \\arrow[d, "g"'] & B \\\\ C & D \\end{tikzcd}
- amscd    : \\begin{CD} A @>f>> B \\\\ @VgVV @VVhV \\\\ C @>>k> D \\end{CD}

표현: 대상 R행 C열을 (2R-1)×(2C-1) 표로 펼쳐 대상은 짝수 칸, 화살표는 사이 칸에 둔다.
여러 칸을 건너는 화살표(rr, dd)도 첫 사이 칸에 그린다 (근사). 휘어짐·이동·꺾기는 무시한다.
라벨 위치는 두 문법 모두 "방향의 왼쪽"이 기본(xy의 ^, tikz-cd의 기본)이고 xy의 _ 와
tikz-cd의 ' (swap)이 반대쪽이다. → 의 왼쪽은 위, ↓ 의 왼쪽은 오른쪽이다.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

# 방향(행 부호, 열 부호) → 화살표 모양별 글자
_DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]
_GLYPHS = {
    "plain":   "→←↓↑↘↙↗↖",
    "double":  "⇒⇐⇓⇑⇘⇙⇗⇖",
    "dashed":  "⇢⇠⇣⇡↘↙↗↖",
    "hook":    "↪↩↓↑↘↙↗↖",
    "twohead": "↠↞↡↟↘↙↗↖",
    "mapsto":  "↦↤↧↥↘↙↗↖",
    "equal":   "==‖‖⟍⟋⟋⟍",
    "nohead":  "——||⟍⟋⟋⟍",
    "squig":   "⇝⇜↓↑↘↙↗↖",
    "twocell": "⇉⇇⇊⇈⇉⇇⇉⇇",
}


class Arrow:
    __slots__ = ("di", "dj", "style", "labels")

    def __init__(self, di: int, dj: int, style: str = "plain"):
        self.di, self.dj, self.style = di, dj, style
        self.labels: list[tuple[str, str]] = []   # (쪽: "left" | "right" | "mid", 원문)


# ====================================================================== 원문 훑기 도우미
def _group_end(s: str, i: int, open_: str = "{", close: str = "}") -> int:
    """s[i] == open_ 일 때 짝이 되는 close 의 다음 위치. 없으면 len(s)."""
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(s)


def _read_token(s: str, i: int) -> tuple[str, int]:
    """공백 건너 다음 인수 원문: {…} 의 안쪽, 제어어 하나, 또는 글자 하나."""
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s):
        return "", i
    if s[i] == "{":
        j = _group_end(s, i)
        return s[i + 1:j - 1], j
    if s[i] == "\\":
        j = i + 1
        if j < len(s) and s[j].isalpha():
            while j < len(s) and s[j].isalpha():
                j += 1
        else:
            j += 1
        return s[i:j], j
    return s[i], i + 1


def split_top(s: str, sep: str) -> list[str]:
    """중괄호 바깥의 구분자로 나눈다. sep 는 "&" 또는 "\\\\"."""
    out, depth, cur, i = [], 0, [], 0
    while i < len(s):
        if depth == 0 and s.startswith(sep, i) and not (sep == "&" and i and s[i - 1] == "\\"):
            out.append("".join(cur))
            cur = []
            i += len(sep)
            if sep == "\\\\" and i < len(s) and s[i] == "[":   # \\[2pt]
                i = _group_end(s, i, "[", "]")
            continue
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            cur.append(s[i:i + 2])
            i += 2
            continue
        depth += c == "{"
        depth -= c == "}"
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def _dir_of(spec: str) -> tuple[int, int]:
    di = spec.count("d") - spec.count("u")
    dj = spec.count("r") - spec.count("l")
    return (di > 0) - (di < 0), (dj > 0) - (dj < 0)


# ====================================================================== xy-pic
def _xy_style(spec: str) -> str:
    sp = spec.replace(" ", "")
    if sp == "":
        return "phantom"
    if "(" in sp or "^{(}" in sp or "_{(}" in sp:
        return "hook"
    if "|->" in sp or "|-->" in sp:
        return "mapsto"
    if "=>" in sp or sp.startswith("=") and ">" in sp:
        return "double"
    if sp in ("=", "=="):
        return "equal"
    if "~>" in sp or "~" in sp:
        return "squig"
    if "->>" in sp:
        return "twohead"
    if "--" in sp or ".>" in sp or sp.startswith("."):
        return "dashed"
    if ">" not in sp and "<" not in sp:
        return "nohead"
    return "plain"


def parse_xy_arrow(s: str, i: int) -> tuple[Optional[Arrow], int]:
    """s[i:] 가 \\ar 바로 뒤. (화살표, 다음 위치)."""
    style = "plain"
    n = len(s)

    def skip_ws(k: int) -> int:
        while k < n and s[k].isspace():
            k += 1
        return k

    i = skip_ws(i)
    while i < n and s[i] == "@":
        i += 1
        if i >= n:
            break
        c = s[i]
        if c == "{":
            j = _group_end(s, i)
            style = _xy_style(s[i + 1:j - 1])
            i = j
        elif c == "/":
            j = s.find("/", i + 1)
            i = n if j < 0 else j + 1
        elif c in "<([":
            close = {"<": ">", "(": ")", "[": "]"}[c]
            i = _group_end(s, i, c, close) if c != "<" else (s.find(">", i) + 1 or n)
        elif c in "^_=-:!.":
            i += 1
            if c == "=":
                style = "double"
            if i < n and s[i] == "{":
                j = _group_end(s, i)
                if c in "^_":
                    style = _xy_style(s[i + 1:j - 1])
                i = j
        else:
            i += 1
        i = skip_ws(i)
    if i < n and s[i] == "[":
        j = _group_end(s, i, "[", "]")
        di, dj = _dir_of(s[i + 1:j - 1])
        i = j
    else:
        return None, i
    arrow = Arrow(di, dj, style)
    while True:
        i = skip_ws(i)
        if i < n and s[i] in "^_|":
            side = {"^": "left", "_": "right", "|": "mid"}[s[i]]
            i += 1
            while i < n and s[i] in "-<>":
                i += 1
            if i < n and s[i] == "(":
                i = _group_end(s, i, "(", ")")
            lab, i = _read_token(s, i)
            if lab.strip():
                arrow.labels.append((side, lab))
            continue
        if i < n and s[i] == "@":   # 라벨 뒤에 붙은 @… 수식어
            i += 1
            if i < n and s[i] in "{<(/[":
                close = {"{": "}", "<": ">", "(": ")", "/": "/", "[": "]"}[s[i]]
                j = s.find(close, i + 1)
                i = n if j < 0 else j + 1
            continue
        break
    return arrow, i


# ====================================================================== tikz-cd
_TIKZ_STYLE_KEYS = [
    ("Rightarrow", "double"), ("Leftarrow", "double"), ("Leftrightarrow", "double"),
    ("Rrightarrow", "double"), ("equal", "equal"), ("hook'", "hook"), ("hook", "hook"),
    ("two heads", "twohead"), ("dashed", "dashed"), ("dotted", "dashed"), ("densely dashed", "dashed"),
    ("mapsto", "mapsto"), ("maps to", "mapsto"), ("dash", "nohead"), ("no head", "nohead"),
    ("squiggly", "squig"), ("rightsquigarrow", "squig"), ("phantom", "phantom"),
    ("tail", "hook"), ("rightarrowtail", "hook"),
]


def _split_options(s: str) -> list[str]:
    out, cur, depth, quote = [], [], 0, False
    for c in s:
        if c == '"' and depth == 0:
            quote = not quote
        if c == "," and depth == 0 and not quote:
            out.append("".join(cur).strip())
            cur = []
            continue
        depth += c == "{"
        depth -= c == "}"
        cur.append(c)
    out.append("".join(cur).strip())
    return [o for o in out if o]


def parse_tikz_arrow(s: str, i: int) -> tuple[Optional[Arrow], int]:
    """s[i:] 가 \\arrow 또는 \\ar 바로 뒤 (tikz-cd 문법)."""
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    if i >= n or s[i] != "[":
        return None, i
    j = _group_end(s, i, "[", "]")
    opts = _split_options(s[i + 1:j - 1])
    i = j
    # \arrow[r]{f} 처럼 뒤에 붙은 라벨 (옛 문법)
    extra: list[str] = []
    while i < n and s[i] == "{":
        k = _group_end(s, i)
        extra.append(s[i + 1:k - 1])
        i = k
    arrow = Arrow(0, 0)
    for o in opts:
        if re.fullmatch(r"[udlr]+", o):
            arrow.di, arrow.dj = _dir_of(o)
            continue
        if o.startswith('"'):
            m = re.match(r'"((?:[^"{}]|\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})*)"(.*)', o)
            if not m:
                continue
            lab, rest = m.group(1), m.group(2)
            swap = rest.lstrip().startswith("'") or "swap" in rest
            side = "mid" if "description" in rest or "marking" in rest else (
                "right" if swap else "left")
            arrow.labels.append((side, lab))
            continue
        key = o.split("=")[0].strip()
        for name, st in _TIKZ_STYLE_KEYS:
            if key == name:
                arrow.style = st
                break
    for lab in extra:
        arrow.labels.append(("left", lab))
    if arrow.di == 0 and arrow.dj == 0:
        return None, i
    return arrow, i


# ====================================================================== 칸 → 대상 + 화살표
_AR_RE = re.compile(r"\\(ar|arrow|[udlr]+(?:upper|lower|compos)?twocell|[udlr]+(?:uppertwocell|lowertwocell)|twocell)(?![A-Za-z])")


def parse_twocell(name: str, s: str, i: int) -> tuple[Optional[Arrow], int]:
    """xy 2-셀 \\rtwocell<5>^{F}_{G}{\\alpha}: 두 평행 화살표(F 위, G 아래)와 2-셀 이름."""
    m = re.match(r"([udlr]+)", name)
    di, dj = _dir_of(m.group(1)) if m else (0, 1)
    if di == 0 and dj == 0:
        return None, i
    a = Arrow(di, dj, "twocell")
    n = len(s)
    while True:
        while i < n and s[i].isspace():
            i += 1
        if i < n and s[i] == "<":
            k = s.find(">", i)
            i = n if k < 0 else k + 1
            continue
        if i < n and s[i] in "^_":
            side = "left" if s[i] == "^" else "right"
            i += 1
            while i < n and s[i] in "-<>":
                i += 1
            lab, i = _read_token(s, i)
            if lab.strip():
                a.labels.append((side, lab))
            continue
        if i < n and s[i] == "{":
            lab, i = _read_token(s, i)
            if lab.strip() and lab.strip() not in ("\\omit",):
                a.labels.append(("cell", lab))
            continue
        break
    return a, i


def split_cell(cell: str, tikz: bool) -> tuple[str, list[Arrow]]:
    """칸 원문에서 화살표 명령을 빼고 (대상 원문, 화살표들)."""
    arrows: list[Arrow] = []
    out: list[str] = []
    i = 0
    while True:
        m = _AR_RE.search(cell, i)
        if not m:
            out.append(cell[i:])
            break
        # 중괄호 안의 \ar 는 대상의 일부가 아니다 — 깊이를 보고 맨 바깥만 처리
        depth = cell[:m.start()].count("{") - cell[:m.start()].count("}")
        if depth != 0:
            out.append(cell[i:m.end()])
            i = m.end()
            continue
        out.append(cell[i:m.start()])
        if "twocell" in m.group(1):
            arrow, k = parse_twocell(m.group(1), cell, m.end())
        else:
            use_tikz = tikz or m.group(1) == "arrow"
            arrow, k = (parse_tikz_arrow if use_tikz else parse_xy_arrow)(cell, m.end())
        if arrow is not None:
            arrows.append(arrow)
        i = max(k, m.end())
    return "".join(out), arrows


# ====================================================================== amscd
def parse_cd(body: str) -> list[list[tuple[str, Any]]]:
    """amscd 본문 → 행들. 대상 행은 [("obj", 원문) | ("h", Arrow)], 세로 행은 [("v", Arrow|None)]."""
    rows = split_top(body, "\\\\")
    out: list[list[tuple[str, Any]]] = []
    for r in rows:
        items: list[tuple[str, Any]] = []
        i, n = 0, len(r)
        buf: list[str] = []
        vertical = re.match(r"\s*@[VA|.]|\s*@\\vert", r) is not None
        while i < n:
            c = r[i]
            if c == "\\" and i + 1 < n:
                buf.append(r[i:i + 2])
                i += 2
                continue
            if c == "{":
                j = _group_end(r, i)
                buf.append(r[i:j])
                i = j
                continue
            if c == "@" and i + 1 < n:
                kind = r[i + 1]
                if r.startswith("@\\vert", i):
                    kind, step = "|", 6
                else:
                    step = 2
                if kind in "><VA":
                    labs = []
                    k = i + step
                    for _ in range(2):
                        lab_end = _find_delim(r, k, kind)
                        labs.append(r[k:lab_end])
                        k = lab_end + 1
                    a = {">": Arrow(0, 1), "<": Arrow(0, -1), "V": Arrow(1, 0),
                         "A": Arrow(-1, 0)}[kind]
                    # 가로: 위(첫째) 아래(둘째) / 세로: 왼쪽(첫째) 오른쪽(둘째)
                    first, second = labs
                    if kind in "><":
                        if first.strip():
                            a.labels.append(("above", first))
                        if second.strip():
                            a.labels.append(("below", second))
                    else:
                        if first.strip():
                            a.labels.append(("west", first))
                        if second.strip():
                            a.labels.append(("east", second))
                    if not vertical:
                        items.append(("obj", "".join(buf)))
                        buf = []
                        items.append(("h", a))
                    else:
                        items.append(("v", a))
                    i = k
                    continue
                if kind in "=|.":
                    if not vertical:
                        items.append(("obj", "".join(buf)))
                        buf = []
                        items.append(("h", Arrow(0, 1, "equal") if kind == "=" else None))
                    else:
                        items.append(("v", Arrow(1, 0, "equal") if kind == "|" else None))
                    i += step
                    continue
            buf.append(c)
            i += 1
        if not vertical:
            items.append(("obj", "".join(buf)))
        out.append(items)
    return out


def _find_delim(s: str, i: int, d: str) -> int:
    depth = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == d and depth == 0:
            return i
        i += 1
    return len(s)


# ====================================================================== 격자 그리기
def glyph(arrow: Arrow) -> str:
    k = _DIRS.index((arrow.di, arrow.dj))
    return _GLYPHS.get(arrow.style, _GLYPHS["plain"])[k]


def absolute_side(arrow: Arrow, side: str) -> str:
    """라벨 쪽("left"=방향의 왼쪽 …) → 화면 위치 above/below/west/east/mid."""
    if side in ("above", "below", "west", "east", "mid", "cell"):
        return side
    x, y = arrow.dj, arrow.di          # 화면 좌표 (y 아래로 +)
    lx, ly = y, -x                     # 방향의 왼쪽
    if side == "right":
        lx, ly = -lx, -ly
    if arrow.di == 0:                  # 가로 화살표
        return "above" if ly < 0 else "below"
    if arrow.dj == 0:                  # 세로 화살표
        return "east" if lx > 0 else "west"
    return "above" if ly < 0 else "below"


def build_grid(objects: list[list[str]], arrows: list[tuple[int, int, Arrow]],
               sub: Callable[[str], Any], El: Any, mo: Callable[..., Any]) -> Any:
    """대상 원문 표와 (행, 열, 화살표) 목록 → <mtable>."""
    R = len(objects)
    C = max((len(r) for r in objects), default=1)
    H, W = 2 * R - 1, 2 * C - 1
    cells: list[list[list[Any]]] = [[[] for _ in range(W)] for _ in range(H)]
    for i, row in enumerate(objects):
        for j, raw in enumerate(row):
            if raw.strip():
                cells[2 * i][2 * j].append(sub(raw))
    for i, j, a in arrows:
        gi, gj = 2 * i + a.di, 2 * j + a.dj
        if not (0 <= gi < H and 0 <= gj < W):
            continue
        cells[gi][gj].append(arrow_el(a, sub, El, mo))
    trs = []
    for r in range(H):
        tds = []
        for c in range(W):
            items = cells[r][c]
            content = items[0] if len(items) == 1 else El("mrow", items)
            tds.append(El("mtd", [content]))
        trs.append(El("mtr", tds))
    return El("mtable", trs, columnspacing="0.25em", rowspacing="0.35em",
              class_="htex-cd", displaystyle="false")


def arrow_el(a: Arrow, sub: Callable[[str], Any], El: Any, mo: Callable[..., Any]) -> Any:
    pos: dict[str, list[Any]] = {}
    for side, raw in a.labels:
        pos.setdefault(absolute_side(a, side), []).append(sub(raw))

    def lab(key: str) -> Optional[Any]:
        items = pos.get(key)
        if not items:
            return None
        body = items[0] if len(items) == 1 else El("mrow", items)
        return El("mstyle", [body], scriptlevel="1")

    cell = pos.pop("cell", None)
    if cell is not None:   # 2-셀 이름: 화살표 옆에 ⇓α 로
        pos.setdefault("mid", []).append(El("mrow", [mo("⇓", stretchy="false"), *cell]))
    if a.style == "phantom":
        mid = lab("mid") or lab("above") or lab("below") or lab("east") or lab("west")
        return mid if mid is not None else El("mrow")
    horizontal = a.di == 0
    vertical = a.dj == 0
    if horizontal:
        op = mo(glyph(a), stretchy="true")
    elif vertical:
        op = mo(glyph(a), stretchy="true", minsize="1.6em")
    else:
        op = mo(glyph(a), stretchy="false")
    mid = lab("mid")
    if mid is not None:
        op = El("mrow", [op, mid]) if not horizontal else El("mover", [op, mid])
    if vertical:
        parts = []
        w, e = lab("west"), lab("east")
        if w is not None:
            parts.append(w)
        parts.append(op)
        if e is not None:
            parts.append(e)
        return parts[0] if len(parts) == 1 else El("mrow", parts)
    over, under = lab("above"), lab("below")
    if horizontal:
        # MathML 연산자는 munder/mover 의 가장 넓은 형제 폭까지만 늘어난다.
        # 보이지 않는 받침(mspace)으로 가로 화살표의 최소 길이를 준다.
        strut = El("mspace", width="2.5em")
        if under is None:
            under = strut
        elif over is None:
            over = strut
    if over is not None and under is not None:
        return El("munderover", [op, under, over])
    if over is not None:
        return El("mover", [op, over])
    if under is not None:
        return El("munder", [op, under])
    return op
