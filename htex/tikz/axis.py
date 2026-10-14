"""pgfplots 부분집합: axis, semilogxaxis, semilogyaxis, loglogaxis. (담당: H)

- 그래프 상자(width/height 기본 240pt×207pt, 상자 크기는 글 자리를 뺀 근사)를 그리고,
  \\addplot 을 모아 범위를 정한 뒤 눈금·격자·선·표식·범례를 그린다.
- 눈금: 선형은 1-2-5 간격(nice_ticks), 로그 축은 10의 거듭제곱(log_ticks).
- 색 순환: blue, red, brown!60!black, black (pgfplots 기본 cycle list 앞부분), 이후 반복.
- 정의역 밖(nan) 점·로그 축의 0 이하 값은 선을 끊는다.
"""
from __future__ import annotations

import math
import re
from typing import Optional

from .. import expr as _expr
from . import geometry as G
from .scan import find_top, group, keyvals, match, skip_ws, split_top, statement_end, strip_braces
from .styles import PT, Style, css_color, is_color
from .svg import att, num, px, py

CYCLE = [("blue", "*"), ("red", "square*"), ("brown!60!black", "o"), ("black", "star"),
         ("blue", "diamond*"), ("red", "*"), ("brown!60!black", "square*"), ("black", "otimes")]
# 표식 없는 함수식에도 기본 표식이 붙는 pgfplots 기본 동작은 그대로 따르지 않는다(가독성):
# mark 가 지정되지 않은 함수식은 표식 없이, coordinates/table 은 순환 표식을 붙인다.

DEFAULT_W = 240 * PT          # cm
DEFAULT_H = 207 * PT


# ====================================================================== 눈금
def nice_step(span: float, target: int = 6) -> float:
    if not (span > 0 and math.isfinite(span)):
        return 1.0
    raw = span / max(1, target)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m == 2.5:
            continue
        if raw <= m * mag * 1.0000001:
            return m * mag
    return 10 * mag


def nice_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    """[lo, hi] 안의 1-2-5 간격 눈금."""
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return []
    step = nice_step(hi - lo, target)
    k0 = math.ceil(lo / step - 1e-9)
    k1 = math.floor(hi / step + 1e-9)
    if k1 - k0 > 200:
        return []
    out = []
    for k in range(k0, k1 + 1):
        v = k * step
        if abs(v) < step * 1e-9:
            v = 0.0
        out.append(round(v, 12))
    return out


def nice_range(lo: float, hi: float) -> tuple[float, float]:
    """데이터 범위 → 축 범위. pgfplots 는 데이터 범위 그대로(enlargelimits 없음 기본은 y 에만…)를 쓰므로
    여기서는 데이터 범위를 그대로 두고, 폭이 0 이면 넓힌다."""
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return 0.0, 1.0
    if hi - lo < 1e-12:
        d = abs(lo) * 0.1 or 1.0
        return lo - d, hi + d
    return lo, hi


def log_ticks(lo: float, hi: float) -> list[float]:
    """로그 축(값은 log10) 의 정수 거듭제곱 눈금. 너무 많으면 성기게."""
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi < lo:
        return []
    k0, k1 = math.ceil(lo - 1e-9), math.floor(hi + 1e-9)
    if k1 - k0 > 400:
        return []
    step = 1
    while (k1 - k0) / step > 10:
        step += 1
    return [float(k) for k in range(k0, k1 + 1) if k % step == 0]


def fmt_tick(v: float, step: float) -> str:
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e5 or a < 1e-4:
        e = math.floor(math.log10(a))
        m = v / 10 ** e
        ms = f"{m:.2f}".rstrip("0").rstrip(".")
        return (f"{ms}\u00b710^{e}") if ms not in ("1", "-1") else (("-" if v < 0 else "") + f"10^{e}")
    dec = max(0, -int(math.floor(math.log10(step))) if step > 0 else 0)
    dec = min(dec, 6)
    s = f"{v:.{dec}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace("-", "\u2212")


# ====================================================================== 데이터 수집
class Plot:
    def __init__(self):
        self.runs: list[list[tuple[float, float]]] = []
        self.style: Optional[Style] = None
        self.mark: Optional[str] = None
        self.only_marks = False
        self.smooth = False
        self.legend: Optional[str] = None
        self.color = "blue"
        self.draw_line = True
        self.fill: Optional[str] = None


def _data_table(eng, text: str, opts: dict) -> list:
    rows = [ln.strip() for ln in re.split(r"\n|\\\\", text) if ln.strip()]
    if not rows:
        return []
    sep = None
    cs = opts.get("col sep")
    if cs == "comma":
        sep = ","
    elif cs in ("semicolon",):
        sep = ";"
    split = (lambda r: [c.strip() for c in r.split(sep)]) if sep else (lambda r: r.split())
    header = split(rows[0])
    data_rows = rows
    names = None
    if any(not _is_num(c) for c in header):
        names = header
        data_rows = rows[1:]
    xi, yi = 0, 1
    if names:
        xk, yk = opts.get("x"), opts.get("y")
        if xk in names:
            xi = names.index(xk)
        if yk in names:
            yi = names.index(yk)
        if opts.get("x index") is not None:
            xi = int(eng.number(opts["x index"]) or 0)
        if opts.get("y index") is not None:
            yi = int(eng.number(opts["y index"]) or 1)
    out = []
    for r in data_rows[:10_001]:
        cells = split(r)
        try:
            out.append((float(cells[xi]), float(cells[yi])))
        except (ValueError, IndexError):
            out.append(None)
    if len(data_rows) > 10_000:
        eng.problem("표 데이터가 10,000점을 넘어 나머지는 버렸다")
        out = out[:10_000]
    return out


def _is_num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _coords(eng, text: str) -> list:
    out = []
    k = 0
    while k < len(text):
        k = skip_ws(text, k)
        if k >= len(text):
            break
        if text[k] != "(":
            k += 1
            continue
        inner, k = group(text, k)
        parts = split_top(inner, ",")
        if len(parts) >= 2:
            x = eng.number(parts[0])
            y = eng.number(parts[1])
            if len(parts) > 2:
                eng.problem("3차원 좌표는 범위 밖이다 (z 는 무시)")
            out.append((x, y) if x is not None and y is not None else None)
        if len(out) > 10_000:
            eng.problem("coordinates 가 10,000점을 넘어 나머지는 버렸다")
            break
    return out


def _sample(eng, text: str, a: float, b: float, n: int, var: str, logx: bool) -> list:
    t = strip_braces(text)
    parts = split_top(t, ",") if t.startswith("(") is False else None
    xe = ye = None
    if text.strip().startswith("("):
        inner = text.strip()[1:-1]
        ps = split_top(inner, ",")
        if len(ps) != 2:
            eng.problem("\\addplot 매개변수 식을 해석하지 못했다")
            return []
        xe = eng.compile(strip_braces(ps[0]), (var,) if var not in ("x", "y") else ())
        ye = eng.compile(strip_braces(ps[1]), (var,) if var not in ("x", "y") else ())
        if xe is None or ye is None:
            return []
    else:
        ye = eng.compile(t, (var,) if var not in ("x", "y") else ())
        if ye is None:
            return []
    out = []
    for k in range(n):
        if k % 64 == 0:
            eng.tick()
        if logx and a > 0 and b > 0:
            xv = 10 ** (math.log10(a) + (math.log10(b) - math.log10(a)) * k / max(1, n - 1))
        else:
            xv = a + (b - a) * k / max(1, n - 1)
        env = eng.vars_env(x=xv, **({var: xv} if var not in ("x",) else {}))
        y = _expr.evaluate(ye, env)
        x = _expr.evaluate(xe, env) if xe is not None else xv
        out.append((x, y) if math.isfinite(x) and math.isfinite(y) else None)
    return out


# ====================================================================== 축
def render_axis(eng, env_name: str, opts_text: str, body: str, outer: Style) -> None:
    eng.axis_count += 1
    logx = env_name in ("semilogxaxis", "loglogaxis")
    logy = env_name in ("semilogyaxis", "loglogaxis")
    ao: dict[str, Optional[str]] = {}
    for k, v in keyvals(opts_text):
        ao[k] = v
    if ao.get("xmode") == "log":
        logx = True
    if ao.get("ymode") == "log":
        logy = True
    W = eng.length(ao.get("width"), unit="cm") if ao.get("width") else DEFAULT_W
    H = eng.length(ao.get("height"), unit="cm") if ao.get("height") else DEFAULT_H
    W = W if W and W > 0.5 else DEFAULT_W
    H = H if H and H > 0.5 else DEFAULT_H
    W, H = min(W, 60.0), min(H, 60.0)

    # ---- 본문 훑기: \addplot, \addlegendentry, \legend
    plots: list[Plot] = []
    legend_list: Optional[list[str]] = None
    extras: list[str] = []          # 축 좌표로 그릴 TikZ 문장 (\draw, \node …)
    i, n = 0, len(body)
    cyc = 0
    while i < n:
        eng.tick()
        i = skip_ws(body, i)
        if i >= n:
            break
        m = re.match(r"\\([A-Za-z]+3?)(\+?)(\*?)", body[i:])
        if not m:
            j = statement_end(body, i, n)
            i = j + 1
            continue
        cmd = m.group(1)
        plus = m.group(2) == "+"
        j = i + m.end()
        if cmd == "addplot":
            k = statement_end(body, j, n)
            p = _parse_addplot(eng, body[j:k], plus, cyc, ao, logx)
            if p is not None:
                plots.append(p)
                cyc += 1
            i = k + 1
        elif cmd == "addplot3":
            eng.problem("3차원 그래프(\\addplot3)는 범위 밖이라 그리지 않았다")
            i = statement_end(body, j, n) + 1
        elif cmd == "addlegendentry":
            jj = skip_ws(body, j)
            if jj < n and body[jj] == "[":
                _, jj = group(body, jj)
                jj = skip_ws(body, jj)
            if jj < n and body[jj] == "{":
                txt, jj = group(body, jj)
                for p in reversed(plots):
                    if p.legend is None:
                        p.legend = txt
                        break
                else:
                    if plots:
                        plots[-1].legend = txt
            i = jj
        elif cmd == "legend":
            jj = skip_ws(body, j)
            if jj < n and body[jj] == "{":
                txt, jj = group(body, jj)
                legend_list = [strip_braces(x) for x in split_top(txt, ",")]
            i = jj
        else:
            k = statement_end(body, j, n)
            extras.append(body[i:k + 1])
            i = k + 1
    if not plots and not extras:
        eng.problem("축에 그릴 그래프가 없어 축을 그리지 않았다")
        return
    if legend_list is not None:
        for p, t in zip(plots, legend_list):
            p.legend = t
    if ao.get("legend entries"):
        for p, t in zip(plots, [strip_braces(x) for x in split_top(ao["legend entries"] or "", ",")]):
            p.legend = t

    # ---- 범위
    def tx(v):
        if logx:
            return math.log10(v) if v > 0 else math.nan
        return v

    def ty(v):
        if logy:
            return math.log10(v) if v > 0 else math.nan
        return v

    xs, ys = [], []
    for p in plots:
        for run in p.runs:
            for x, y in run:
                a, b = tx(x), ty(y)
                if math.isfinite(a) and math.isfinite(b):
                    xs.append(a)
                    ys.append(b)
    xmin = _opt_num(eng, ao, "xmin")
    xmax = _opt_num(eng, ao, "xmax")
    ymin = _opt_num(eng, ao, "ymin")
    ymax = _opt_num(eng, ao, "ymax")
    if xmin is not None:
        xmin = tx(xmin)
    if xmax is not None:
        xmax = tx(xmax)
    if ymin is not None:
        ymin = ty(ymin)
    if ymax is not None:
        ymax = ty(ymax)
    dx0, dx1 = (min(xs), max(xs)) if xs else (0.0, 1.0)
    dy0, dy1 = (min(ys), max(ys)) if ys else (0.0, 1.0)
    x0 = xmin if xmin is not None and math.isfinite(xmin) else dx0
    x1 = xmax if xmax is not None and math.isfinite(xmax) else dx1
    y0 = ymin if ymin is not None and math.isfinite(ymin) else dy0
    y1 = ymax if ymax is not None and math.isfinite(ymax) else dy1
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    x0, x1 = nice_range(x0, x1)
    y0, y1 = nice_range(y0, y1)
    # pgfplots 기본 enlargelimits: 자동 범위인 쪽만 양쪽 5% 넓힘 (데이터가 축에 붙지 않게)
    enl = ao.get("enlargelimits", "auto")
    if enl not in ("false",):
        if ymin is None and ymax is None and not logy:
            d = (y1 - y0) * 0.05
            y0, y1 = y0 - d, y1 + d
        elif ymin is None and ymax is None and logy:
            d = (y1 - y0) * 0.05 or 0.05
            y0, y1 = y0 - d, y1 + d
        if (xmin is None and xmax is None) and any(not p.runs or p.only_marks for p in plots):
            d = (x1 - x0) * 0.05
            x0, x1 = x0 - d, x1 + d

    # ---- 상자 크기 (글 자리를 뺌)
    has_xlabel = bool(ao.get("xlabel"))
    has_ylabel = bool(ao.get("ylabel"))
    has_title = bool(ao.get("title"))
    left_room = 1.0 + (0.6 if has_ylabel else 0)
    bottom_room = 0.6 + (0.6 if has_xlabel else 0)
    top_room = 0.6 if has_title else 0.0
    bw = max(1.0, W - left_room - 0.3)
    bh = max(1.0, H - bottom_room - top_room - 0.3)
    st0 = outer
    origin = st0.matrix[4], st0.matrix[5]
    ox, oy = origin

    def mapper(x, y):
        a, b = tx(x), ty(y)
        if not (math.isfinite(a) and math.isfinite(b)):
            return None
        return (ox + (a - x0) / (x1 - x0) * bw, oy + (b - y0) / (y1 - y0) * bh)

    def map_t(a, b):
        return (ox + (a - x0) / (x1 - x0) * bw, oy + (b - y0) / (y1 - y0) * bh)

    canvas = eng.canvas
    axis_lines = (ao.get("axis lines") or ao.get("axis lines*") or "box").strip()
    grid = (ao.get("grid") or ("major" if "grid" in ao and ao["grid"] is None else "none")).strip()
    xticks = log_ticks(x0, x1) if logx else nice_ticks(x0, x1, max(3, int(bw / 1.5)))
    yticks = log_ticks(y0, y1) if logy else nice_ticks(y0, y1, max(3, int(bh / 1.1)))
    xticks = _explicit_ticks(eng, ao.get("xtick"), xticks, tx)
    yticks = _explicit_ticks(eng, ao.get("ytick"), yticks, ty)
    xstep = (xticks[1] - xticks[0]) if len(xticks) > 1 else (x1 - x0)
    ystep = (yticks[1] - yticks[0]) if len(yticks) > 1 else (y1 - y0)
    lw = 0.4 * PT * 37.8

    canvas.push(' class="htex-axis"')
    # 격자
    if grid in ("major", "both"):
        d = []
        for v in xticks:
            a, b = map_t(v, y0), map_t(v, y1)
            d.append(f"M{num(px(a[0]))} {num(py(a[1]))}V{num(py(b[1]))}")
        for v in yticks:
            a, b = map_t(x0, v), map_t(x1, v)
            d.append(f"M{num(px(a[0]))} {num(py(a[1]))}H{num(px(b[0]))}")
        if d:
            canvas.add(f'<path d="{"".join(d)}" fill="none" stroke="currentColor" stroke-opacity="0.18" '
                       f'stroke-width="{num(lw * 0.5)}"/>')
    # 축 위치
    if axis_lines in ("left",):
        xaxis_y, yaxis_x = y0, x0
    elif axis_lines in ("middle", "center"):
        xaxis_y = min(max(0.0 if not logy else y0, y0), y1)
        yaxis_x = min(max(0.0 if not logx else x0, x0), x1)
    else:
        xaxis_y, yaxis_x = y0, x0
    # 잘라낼 영역(그래프 상자)
    clip_id = canvas.new_id("axclip")
    a0, a1 = map_t(x0, y0), map_t(x1, y1)
    canvas.defs.append(f'<clipPath id="{clip_id}"><rect x="{num(px(a0[0]))}" y="{num(py(a1[1]))}" '
                       f'width="{num(px(a1[0]) - px(a0[0]))}" height="{num(py(a0[1]) - py(a1[1]))}"/></clipPath>')
    canvas.extend(a0[0], a0[1])
    canvas.extend(a1[0], a1[1])
    # 그래프
    canvas.push(f' clip-path="url(#{clip_id})"')
    for p in plots:
        _draw_plot(eng, p, mapper)
    # 추가 TikZ 문장 (축 좌표)
    if extras:
        saved = eng.axis_map
        eng.axis_map = mapper
        try:
            eng.run_block("\n".join(extras), outer)
        finally:
            eng.axis_map = saved
    canvas.pop()
    # 눈금 표시
    fs = 10 * PT * 37.8 * 0.9
    tick_len = 3 * PT
    tick_d = []
    labels = []
    show_xlabels = ao.get("xticklabels") != "" and ao.get("xticklabels") != "{}"
    show_ylabels = ao.get("yticklabels") != "" and ao.get("yticklabels") != "{}"
    for v in xticks:
        a = map_t(v, xaxis_y)
        tick_d.append(f"M{num(px(a[0]))} {num(py(a[1]))}v{num(-tick_len * 37.8)}")
        if axis_lines == "box":
            b = map_t(v, y1)
            tick_d.append(f"M{num(px(b[0]))} {num(py(b[1]))}v{num(tick_len * 37.8)}")
        if axis_lines in ("middle", "center") and abs(v - yaxis_x) < 1e-12:
            continue
        if show_xlabels:
            label = _tick_label(v, xstep, logx)
            labels.append(_text(px(a[0]), py(a[1]) + fs * 1.25, label, "middle", fs))
    for v in yticks:
        a = map_t(yaxis_x, v)
        tick_d.append(f"M{num(px(a[0]))} {num(py(a[1]))}h{num(tick_len * 37.8)}")
        if axis_lines == "box":
            b = map_t(x1, v)
            tick_d.append(f"M{num(px(b[0]))} {num(py(b[1]))}h{num(-tick_len * 37.8)}")
        if axis_lines in ("middle", "center") and abs(v - xaxis_y) < 1e-12:
            continue
        if show_ylabels:
            label = _tick_label(v, ystep, logy)
            labels.append(_text(px(a[0]) - fs * 0.4, py(a[1]) + fs * 0.35, label, "end", fs))
    if logx or logy:
        # 작은 눈금 (2..9 × 10^k)
        for is_x, lt, (lo, hi) in ((True, logx, (x0, x1)), (False, logy, (y0, y1))):
            if not lt or hi - lo > 12:
                continue
            for k in range(math.floor(lo), math.ceil(hi) + 1):
                for mm in range(2, 10):
                    v = k + math.log10(mm)
                    if lo <= v <= hi:
                        if is_x:
                            a = map_t(v, xaxis_y)
                            tick_d.append(f"M{num(px(a[0]))} {num(py(a[1]))}v{num(-tick_len * 0.6 * 37.8)}")
                        else:
                            a = map_t(yaxis_x, v)
                            tick_d.append(f"M{num(px(a[0]))} {num(py(a[1]))}h{num(tick_len * 0.6 * 37.8)}")
    if tick_d:
        canvas.add(f'<path d="{"".join(tick_d)}" fill="none" stroke="currentColor" stroke-width="{num(lw)}"/>')
    # 축선
    if axis_lines == "box":
        canvas.add(f'<rect x="{num(px(a0[0]))}" y="{num(py(a1[1]))}" width="{num(px(a1[0]) - px(a0[0]))}" '
                   f'height="{num(py(a0[1]) - py(a1[1]))}" fill="none" stroke="currentColor" stroke-width="{num(lw)}"/>')
    elif axis_lines != "none":
        arrow = axis_lines in ("middle", "center", "left")
        xa, xb = map_t(x0, xaxis_y), map_t(x1, xaxis_y)
        ya, yb = map_t(yaxis_x, y0), map_t(yaxis_x, y1)
        ext = 0.25 if arrow else 0.0
        segs_x = [("M", xa), ("L", (xb[0] + ext, xb[1]))]
        segs_y = [("M", ya), ("L", (yb[0], yb[1] + ext))]
        st = Style(draw=True, line_width=0.4, arrows=(None, "Stealth") if arrow else (None, None))
        eng.emit_path(segs_x, st)
        eng.emit_path(segs_y, st)
    canvas.add("".join(labels))
    # 축 이름·제목
    from .engine import place_node  # noqa: F401 (순환 import 방지용 지연)
    mid_x = (a0[0] + a1[0]) / 2
    mid_y = (a0[1] + a1[1]) / 2
    if has_xlabel:
        if axis_lines in ("middle", "center"):
            pnt = map_t(x1, xaxis_y)
            eng.place_node({"word": "node", "style": Style(anchor="west"), "text": ao["xlabel"],
                            "point": (pnt[0] + 0.3, pnt[1]), "pieces": None, "pos": None, "name": None})
        else:
            eng.place_node({"word": "node", "style": Style(anchor="north"), "text": ao["xlabel"],
                            "point": (mid_x, a0[1] - 0.55), "pieces": None, "pos": None, "name": None})
    if has_ylabel:
        if axis_lines in ("middle", "center"):
            pnt = map_t(yaxis_x, y1)
            eng.place_node({"word": "node", "style": Style(anchor="south"), "text": ao["ylabel"],
                            "point": (pnt[0], pnt[1] + 0.3), "pieces": None, "pos": None, "name": None})
        else:
            ytick_w = max([len(_tick_label(v, ystep, logy)) for v in yticks] or [1]) * 0.55 * 10 * PT * 0.9
            eng.place_node({"word": "node", "style": Style(anchor="south", node_rotate=90), "text": ao["ylabel"],
                            "point": (a0[0] - ytick_w - 0.3, mid_y), "pieces": None, "pos": None, "name": None},
                           draw=True)
    if has_title:
        eng.place_node({"word": "node", "style": Style(anchor="south"), "text": ao["title"],
                        "point": (mid_x, a1[1] + 0.15), "pieces": None, "pos": None, "name": None})
    # 범례
    entries = [p for p in plots if p.legend is not None]
    if entries:
        _legend(eng, entries, ao.get("legend pos") or "north east", a0, a1, ao.get("legend style") or "")
    canvas.pop()


def _rotate_label_fix(eng):
    pass


def _opt_num(eng, ao, key):
    v = ao.get(key)
    if v is None:
        return None
    return eng.number(v)


def _explicit_ticks(eng, spec, default, t):
    if spec is None:
        return default
    s = strip_braces(spec)
    if s == "\\empty" or s == "":
        return []
    if s == "data":
        return default
    items = eng.expand_list(s)
    out = []
    for it in items[:200]:
        v = eng.number(it)
        if v is not None:
            tv = t(v)
            if math.isfinite(tv):
                out.append(tv)
    return out


def _tick_label(v: float, step: float, log: bool) -> str:
    if log:
        k = int(round(v))
        return f"10^{k}"
    return fmt_tick(v, step)


def _text(x: float, y: float, label: str, anchor: str, fs: float) -> str:
    from .svg import esc
    # 10^k 는 윗첨자 tspan 으로
    m = re.match(r"^(.*?)10\^(-?\d+)$", label)
    if m:
        pre = esc(m.group(1))
        expo = m.group(2).replace("-", "\u2212")
        body = f'{pre}10<tspan dy="{num(-fs * 0.4)}" font-size="{num(fs * 0.72)}">{esc(expo)}</tspan>'
    else:
        body = esc(label)
    return (f'<text x="{num(x)}" y="{num(y)}" text-anchor="{anchor}" font-size="{num(fs)}" '
            f'fill="currentColor">{body}</text>')


def _parse_addplot(eng, text: str, plus: bool, cyc: int, ao: dict, logx: bool) -> Optional[Plot]:
    p = Plot()
    i = skip_ws(text, 0)
    n = len(text)
    opts = ""
    if i < n and text[i] == "[":
        opts, i = group(text, i)
        i = skip_ws(text, i)
    color, cmark = CYCLE[cyc % len(CYCLE)]
    st = Style(color=color, draw=True, line_width=0.4)
    # 축 전체 옵션 중 plot 에 적용되는 것
    base_opts = []
    for k in ("domain", "samples", "smooth", "mark", "only marks", "no marks", "thick", "variable"):
        if k in ao:
            base_opts.append(k if ao[k] is None else f"{k}={{{ao[k]}}}")
    if base_opts:
        st = eng.applier.apply(st, ", ".join(base_opts))
    explicit_color = False
    if opts:
        if not plus:
            st = st.copy(color="black")
        for k, v in keyvals(opts):
            if v is None and is_color(k) or k in ("color", "draw") and v and is_color(v):
                explicit_color = True
        if not plus and not explicit_color:
            st = st.copy(color=color)
        st = eng.applier.apply(st, opts)
    has_mark_opt = any(k == "mark" for k, _ in keyvals(opts))
    rest = text[i:].strip()
    a, b = st.domain if st.domain_set else (-5.0, 5.0)
    samples = st.samples if st.samples_set else 25
    if samples > 1000:
        samples = 1000
    kind = "expr"
    if rest.startswith("coordinates"):
        kind = "coords"
        j = skip_ws(rest, len("coordinates"))
        inner = group(rest, j)[0] if j < len(rest) and rest[j] == "{" else ""
        pts = _coords(eng, inner)
    elif rest.startswith("table"):
        kind = "table"
        j = skip_ws(rest, len("table"))
        topts: dict = {}
        if j < len(rest) and rest[j] == "[":
            to, j = group(rest, j)
            topts = dict(keyvals(to))
            j = skip_ws(rest, j)
        if j < len(rest) and rest[j] == "{":
            inner, _ = group(rest, j)
            if "\n" not in inner and "\\\\" not in inner and len(inner.split()) <= 1:
                eng.problem(f"외부 데이터 파일은 읽지 않는다: {inner.strip()[:40]}")
                return None
            pts = _data_table(eng, inner, topts)
        else:
            eng.problem("table 데이터를 해석하지 못했다")
            return None
    elif rest.startswith("expression"):
        j = skip_ws(rest, len("expression"))
        inner = group(rest, j)[0] if j < len(rest) and rest[j] == "{" else ""
        pts = _sample(eng, inner, a, b, samples, st.variable, logx)
    elif rest.startswith("{"):
        inner, _ = group(rest, 0)
        pts = _sample(eng, inner, a, b, samples, st.variable, logx)
    elif rest.startswith("("):
        k = match(rest, 0)
        pts = _sample(eng, rest[:k], a, b, samples, st.variable, logx)
    elif rest.startswith("gnuplot") or rest.startswith("shell") or rest.startswith("file"):
        eng.problem("\\addplot gnuplot/shell/file 은 지원하지 않는다")
        return None
    else:
        eng.problem(f"\\addplot 을 해석하지 못했다: {rest[:40]}")
        return None
    runs, cur = [], []
    for q in pts:
        if q is None:
            if cur:
                runs.append(cur)
            cur = []
        else:
            cur.append(q)
    if cur:
        runs.append(cur)
    p.runs = runs
    p.style = st
    p.color = st.color or color
    if has_mark_opt:
        p.mark = st.mark if st.mark not in ("none", "") else None
    elif kind in ("coords", "table") and not opts:
        p.mark = cmark
    elif kind in ("coords", "table") and plus:
        p.mark = cmark
    else:
        p.mark = None
    if st.only_marks:
        p.only_marks = True
        if p.mark is None:
            p.mark = cmark
    p.smooth = st.smooth
    p.draw_line = not st.only_marks
    p.fill = st.fill if isinstance(st.fill, str) else None
    return p


def _draw_plot(eng, p: Plot, mapper) -> None:
    st = p.style or Style()
    canvas = eng.canvas
    stroke = css_color(p.color)
    if p.draw_line:
        segs = []
        for run in p.runs:
            pts = [mapper(x, y) for x, y in run]
            sub_runs, cur = [], []
            for q in pts:
                if q is None:
                    if cur:
                        sub_runs.append(cur)
                    cur = []
                else:
                    cur.append(q)
            if cur:
                sub_runs.append(cur)
            for r in sub_runs:
                eng.count(len(r))
                segs.append(("M", r[0]))
                if p.smooth:
                    segs += G.smooth_segments(r)
                else:
                    segs += [("L", q) for q in r[1:]]
        if segs:
            eng.emit_path(segs, st.copy(draw=True, color=p.color, fill=st.fill if p.fill else None))
    if p.mark:
        _marks(eng, p, mapper, stroke)


def _marks(eng, p: Plot, mapper, stroke: str) -> None:
    st = p.style or Style()
    r = st.mark_size * PT * 37.8
    lw = 0.4 * PT * 37.8
    fillc = css_color(st.mark_fill, fill=True) if st.mark_fill else stroke
    m = p.mark.strip()
    out = []
    for run in p.runs:
        for x, y in run:
            q = mapper(x, y)
            if q is None:
                continue
            eng.count()
            X, Y = px(q[0]), py(q[1])
            if m in ("*", "ball"):
                out.append(f'<circle cx="{num(X)}" cy="{num(Y)}" r="{num(r)}" fill="{att(fillc)}"/>')
            elif m == "o":
                out.append(f'<circle cx="{num(X)}" cy="{num(Y)}" r="{num(r)}" fill="none"/>')
            elif m in ("x",):
                out.append(f'<path d="M{num(X - r)} {num(Y - r)}L{num(X + r)} {num(Y + r)}M{num(X - r)} {num(Y + r)}L{num(X + r)} {num(Y - r)}" fill="none"/>')
            elif m in ("+",):
                out.append(f'<path d="M{num(X - r)} {num(Y)}H{num(X + r)}M{num(X)} {num(Y - r)}V{num(Y + r)}" fill="none"/>')
            elif m in ("square", "square*"):
                f = att(fillc) if m.endswith("*") else "none"
                out.append(f'<rect x="{num(X - r)}" y="{num(Y - r)}" width="{num(2 * r)}" height="{num(2 * r)}" fill="{f}"/>')
            elif m in ("triangle", "triangle*"):
                f = att(fillc) if m.endswith("*") else "none"
                out.append(f'<path d="M{num(X)} {num(Y - r)}L{num(X + r * .87)} {num(Y + r * .5)}L{num(X - r * .87)} {num(Y + r * .5)}Z" fill="{f}"/>')
            elif m in ("diamond", "diamond*"):
                f = att(fillc) if m.endswith("*") else "none"
                out.append(f'<path d="M{num(X)} {num(Y - r)}L{num(X + r)} {num(Y)}L{num(X)} {num(Y + r)}L{num(X - r)} {num(Y)}Z" fill="{f}"/>')
            elif m in ("star", "asterisk", "otimes", "oplus", "|", "-"):
                out.append(f'<path d="M{num(X - r)} {num(Y)}H{num(X + r)}M{num(X)} {num(Y - r)}V{num(Y + r)}'
                           f'M{num(X - r * .7)} {num(Y - r * .7)}L{num(X + r * .7)} {num(Y + r * .7)}" fill="none"/>')
            else:
                out.append(f'<circle cx="{num(X)}" cy="{num(Y)}" r="{num(r)}" fill="{att(fillc)}"/>')
    if out:
        eng.canvas.add(f'<g stroke="{att(stroke)}" stroke-width="{num(lw)}">{"".join(out)}</g>')


def _legend(eng, entries, pos: str, a0, a1, style: str) -> None:
    from .svg import measure, parse_node_text
    fs_scale = 0.9
    rows = []
    maxw = 0.0
    for p in entries:
        lines = parse_node_text(p.legend or "")
        w, h, _ = measure(lines, fs_scale)
        rows.append((p, lines, w, max(h, 0.35)))
        maxw = max(maxw, w)
    sample_w = 0.6
    pad = 0.12
    row_h = max(r[3] for r in rows) + 0.08
    box_w = pad * 3 + sample_w + maxw + 0.1
    box_h = pad * 2 + row_h * len(rows)
    pos = pos.strip()
    gap = 0.15
    if pos == "north west":
        bx, by = a0[0] + gap, a1[1] - gap
    elif pos == "south west":
        bx, by = a0[0] + gap, a0[1] + gap + box_h
    elif pos == "south east":
        bx, by = a1[0] - gap - box_w, a0[1] + gap + box_h
    elif pos == "outer north east":
        bx, by = a1[0] + 0.2, a1[1]
    else:
        bx, by = a1[0] - gap - box_w, a1[1] - gap
    c = eng.canvas
    c.add(f'<rect x="{num(px(bx))}" y="{num(py(by))}" width="{num(box_w * 37.8)}" height="{num(box_h * 37.8)}" '
          f'fill="var(--bg,#fff)" stroke="currentColor" stroke-width="{num(0.4 * PT * 37.8)}"/>')
    c.extend(bx, by)
    c.extend(bx + box_w, by - box_h)
    for k, (p, lines, w, h) in enumerate(rows):
        cy = by - pad - row_h * (k + 0.5)
        sx0, sx1 = bx + pad, bx + pad + sample_w
        stroke = css_color(p.color)
        if p.draw_line:
            lw = (p.style.line_width if p.style else 0.4) * PT * 37.8
            dash = ""
            if p.style and p.style.dash:
                from .engine import _stroke_attrs
                c.add(f'<path d="M{num(px(sx0))} {num(py(cy))}H{num(px(sx1))}" fill="none"{_stroke_attrs(p.style.copy(draw=True, color=p.color))}/>')
            else:
                c.add(f'<path d="M{num(px(sx0))} {num(py(cy))}H{num(px(sx1))}" fill="none" stroke="{att(stroke)}" '
                      f'stroke-width="{num(lw)}"{dash}/>')
        if p.mark:
            _marks(eng, _single(p), lambda x, y, cx=(sx0 + sx1) / 2, cyy=cy: (cx, cyy), stroke)
        eng.place_node({"word": "node", "style": Style(anchor="west", font_scale=fs_scale,
                                                       inner_xsep=0.0, inner_ysep=0.0),
                        "text": p.legend, "point": (sx1 + pad, cy), "pieces": None, "pos": None, "name": None})


def _single(p: Plot) -> Plot:
    q = Plot()
    q.runs = [[(0.0, 0.0)]]
    q.style = p.style
    q.mark = p.mark
    q.color = p.color
    return q
