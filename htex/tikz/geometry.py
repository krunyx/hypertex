"""기하 도우미: 원호·타원 베지어, 둥근 모서리, 매끈한 곡선, 화살표 끝 모양. (담당: H)

세그먼트 표현: ("M", p) | ("L", p) | ("C", c1, c2, p) | ("Z",), p = (x, y) cm 캔버스 좌표.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

_K = 4 / 3 * (math.sqrt(2) - 1)


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, k):
    return (a[0] * k, a[1] * k)


def norm(a):
    return math.hypot(a[0], a[1])


def unit(a):
    n = norm(a)
    return (a[0] / n, a[1] / n) if n > 1e-12 else (1.0, 0.0)


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def bez(p0, c1, c2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * p3[1])


def bez_tangent(p0, c1, c2, p3, t):
    u = 1 - t
    return (3 * u * u * (c1[0] - p0[0]) + 6 * u * t * (c2[0] - c1[0]) + 3 * t * t * (p3[0] - c2[0]),
            3 * u * u * (c1[1] - p0[1]) + 6 * u * t * (c2[1] - c1[1]) + 3 * t * t * (p3[1] - c2[1]))


def arc_user(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float) -> list:
    """사용자 좌표 원호 (도) → [(c1, c2, p), ...] 베지어 조각 (90° 이하씩)."""
    out = []
    total = a1 - a0
    if not (math.isfinite(total)) or total == 0:
        return out
    n = max(1, int(math.ceil(abs(total) / 90.0 - 1e-9)))
    n = min(n, 400)
    step = total / n
    for i in range(n):
        s = math.radians(a0 + i * step)
        e = math.radians(a0 + (i + 1) * step)
        k = 4 / 3 * math.tan((e - s) / 4)
        p0 = (cx + rx * math.cos(s), cy + ry * math.sin(s))
        p3 = (cx + rx * math.cos(e), cy + ry * math.sin(e))
        c1 = (p0[0] - k * rx * math.sin(s), p0[1] + k * ry * math.cos(s))
        c2 = (p3[0] + k * rx * math.sin(e), p3[1] - k * ry * math.cos(e))
        out.append((c1, c2, p3))
    return out


def smooth_segments(pts: list, tension: float = 0.55) -> list:
    """점 목록 → 지나가는 매끈한 곡선의 C 세그먼트 (TikZ smooth, 장력 0.55)."""
    segs = []
    n = len(pts)
    if n < 2:
        return segs
    if n == 2:
        return [("L", pts[1])]
    f = tension / 0.55 / 6.0 * 1.0
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
        c1 = add(p1, mul(sub(p2, p0), f))
        c2 = sub(p2, mul(sub(p3, p1), f))
        segs.append(("C", c1, c2, p2))
    return segs


def round_corners(sub_segs: list, r: float) -> list:
    """한 하위 경로(M 으로 시작, L·Z 만 있을 때)의 모서리를 반지름 r 로 둥글게."""
    if r <= 0 or not sub_segs or sub_segs[0][0] != "M":
        return sub_segs
    if any(s[0] not in ("M", "L", "Z") for s in sub_segs):
        return sub_segs
    pts = [sub_segs[0][1]] + [s[1] for s in sub_segs[1:] if s[0] == "L"]
    closed = sub_segs[-1][0] == "Z"
    if closed and len(pts) > 1 and norm(sub(pts[0], pts[-1])) < 1e-9:
        pts = pts[:-1]
    n = len(pts)
    if n < 3 and not closed:
        return sub_segs
    if n < 3:
        return sub_segs

    def corner(prev, cur, nxt):
        d1, d2 = sub(prev, cur), sub(nxt, cur)
        l1, l2 = norm(d1), norm(d2)
        rr = min(r, l1 / 2, l2 / 2)
        a = add(cur, mul(unit(d1), rr))
        b = add(cur, mul(unit(d2), rr))
        c1 = lerp(a, cur, 0.5523)
        c2 = lerp(b, cur, 0.5523)
        return a, c1, c2, b

    out = []
    if closed:
        a, c1, c2, b = corner(pts[-1], pts[0], pts[1])
        out.append(("M", b))
        for i in range(1, n):
            a2, d1, d2, b2 = corner(pts[i - 1], pts[i], pts[(i + 1) % n])
            out.append(("L", a2))
            out.append(("C", d1, d2, b2))
        out.append(("L", a))
        out.append(("C", c1, c2, b))
        out.append(("Z",))
    else:
        out.append(("M", pts[0]))
        for i in range(1, n - 1):
            a2, d1, d2, b2 = corner(pts[i - 1], pts[i], pts[i + 1])
            out.append(("L", a2))
            out.append(("C", d1, d2, b2))
        out.append(("L", pts[-1]))
    return out


def split_subpaths(segs: list) -> list:
    subs, cur = [], []
    for s in segs:
        if s[0] == "M" and cur:
            subs.append(cur)
            cur = []
        cur.append(s)
    if cur:
        subs.append(cur)
    return subs


def end_direction(sub_segs: list, at_end: bool) -> Optional[tuple]:
    """하위 경로 끝(또는 시작)의 (끝점, 들어오는 방향 단위벡터). 닫힌 경로면 None."""
    if not sub_segs or sub_segs[-1][0] == "Z" or len(sub_segs) < 2:
        return None
    if at_end:
        last = sub_segs[-1]
        prev_pt = _seg_end(sub_segs[-2])
        p = _seg_end(last)
        if last[0] == "C":
            q = last[2] if norm(sub(p, last[2])) > 1e-9 else (last[1] if norm(sub(p, last[1])) > 1e-9 else prev_pt)
        else:
            q = prev_pt
        if norm(sub(p, q)) < 1e-12:
            return None
        return p, unit(sub(p, q))
    first = sub_segs[1]
    p = sub_segs[0][1]
    if first[0] == "C":
        q = first[1] if norm(sub(first[1], p)) > 1e-9 else (first[2] if norm(sub(first[2], p)) > 1e-9 else first[3])
    else:
        q = _seg_end(first)
    if norm(sub(p, q)) < 1e-12:
        return None
    return p, unit(sub(p, q))


def _seg_end(s):
    if s[0] == "C":
        return s[3]
    if s[0] in ("M", "L"):
        return s[1]
    return (0.0, 0.0)


def shorten(sub_segs: list, at_end: bool, amount: float) -> list:
    """하위 경로의 끝(또는 시작)을 amount(cm)만큼 줄인다 (화살표 자리)."""
    if amount <= 0 or len(sub_segs) < 2:
        return sub_segs
    segs = list(sub_segs)
    if at_end:
        last = segs[-1]
        prev = _seg_end(segs[-2])
        p = _seg_end(last)
        if last[0] == "L":
            L = norm(sub(p, prev))
            if L <= amount:
                return segs
            segs[-1] = ("L", lerp(p, prev, amount / L))
        elif last[0] == "C":
            d = unit(sub(p, last[2] if norm(sub(p, last[2])) > 1e-9 else prev))
            np_ = sub(p, mul(d, amount))
            segs[-1] = ("C", last[1], sub(last[2], mul(d, amount)), np_)
    else:
        first = segs[1]
        p = segs[0][1]
        if first[0] == "L":
            q = first[1]
            L = norm(sub(q, p))
            if L <= amount:
                return segs
            segs[0] = ("M", lerp(p, q, amount / L))
        elif first[0] == "C":
            d = unit(sub(first[1] if norm(sub(first[1], p)) > 1e-9 else first[3], p))
            np_ = add(p, mul(d, amount))
            segs[0] = ("M", np_)
            segs[1] = ("C", add(first[1], mul(d, amount)), first[2], first[3])
    return segs


def tip_shape(kind: str, p, d, lw_cm: float, pt: float):
    """화살표 끝 모양. 반환 (세그먼트, 채움 여부, 줄일 길이 cm)."""
    n = (-d[1], d[0])
    if kind in ("stealth", "latex"):
        L = 3 * pt + 4.5 * lw_cm
        W = 0.75 * L if kind == "stealth" else 0.75 * L
        inset = 0.325 * L if kind == "stealth" else 0.0
        back = sub(p, mul(d, L))
        a = add(back, mul(n, W / 2))
        b = sub(back, mul(n, W / 2))
        if kind == "stealth":
            m = sub(p, mul(d, L - inset))
            segs = [("M", p), ("L", a), ("L", m), ("L", b), ("Z",)]
        else:
            segs = [("M", p), ("C", lerp(p, a, 0.4), lerp(a, p, 0.1), a), ("L", b),
                    ("C", lerp(b, p, 0.1), lerp(p, b, 0.4), p), ("Z",)]
        return segs, True, L * 0.7
    if kind in ("to", "to2"):
        L = 1.6 * pt + 2.4 * lw_cm
        W = 1.9 * pt + 2.8 * lw_cm
        out = []
        tips = [p] if kind == "to" else [p, sub(p, mul(d, L * 0.8))]
        for q in tips:
            back = sub(q, mul(d, L))
            a = add(back, mul(n, W / 2))
            b = sub(back, mul(n, W / 2))
            out += [("M", a), ("C", lerp(a, back, 0.0), lerp(q, back, 0.45), q),
                    ("C", lerp(q, back, 0.45), lerp(b, back, 0.0), b)]
        return out, False, lw_cm * 0.6
    if kind == "bar":
        W = 2 * pt + 1.5 * lw_cm
        return [("M", add(p, mul(n, W))), ("L", sub(p, mul(n, W)))], False, 0.0
    if kind in ("circle", "ocircle"):
        r = 1.2 * pt + 1.2 * lw_cm
        c = sub(p, mul(d, r))
        segs = [("M", (c[0] + r, c[1]))]
        for c1, c2, q in arc_user(c[0], c[1], r, r, 0, 360):
            segs.append(("C", c1, c2, q))
        segs.append(("Z",))
        return segs, kind == "circle", 2 * r if kind == "circle" else 2 * r
    if kind == "square":
        r = 1.2 * pt + 1.2 * lw_cm
        c = sub(p, mul(d, r))
        corners = [add(c, add(mul(d, sx * r), mul(n, sy * r))) for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
        return [("M", corners[0]), ("L", corners[1]), ("L", corners[2]), ("L", corners[3]), ("Z",)], True, 2 * r
    return [], False, 0.0


def path_length_fn(pieces: list) -> Callable[[float], tuple]:
    """조각 [(p0, 세그먼트)] → pos(t) 가 (점, 접선) 을 돌려주는 함수. 조각마다 같은 몫."""
    def f(t: float):
        if not pieces:
            return (0.0, 0.0), (1.0, 0.0)
        t = max(0.0, min(1.0, t))
        k = len(pieces)
        idx = min(int(t * k), k - 1)
        lt = t * k - idx
        p0, s = pieces[idx]
        if s[0] == "C":
            return bez(p0, s[1], s[2], s[3], lt), unit(bez_tangent(p0, s[1], s[2], s[3], lt))
        q = s[1]
        return lerp(p0, q, lt), unit(sub(q, p0))
    return f
