"""H: TikZ·pgfplots → SVG 렌더러 단위 테스트 (명세 3.1, 3.2절)."""
from __future__ import annotations

import math
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from htex.parser import parse_file
from htex.tikz import PictureResult, merge_values, render_picture, render_picture_node
from htex.tikz.axis import fmt_tick, log_ticks, nice_ticks
from htex.tikz.engine import Engine
from htex.tikz.styles import Style, css_color, parse_arrow_key, parse_color, parse_dim, PT

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "tests" / "docs"
SVG = "{http://www.w3.org/2000/svg}"


def pictures(tree):
    out, stack = [], [tree]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("kind") == "picture":
                out.append(x)
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return sorted(out, key=lambda n: int(n["id"][1:]))


def svg_of(src, values=None):
    r = render_picture(src, values)
    assert isinstance(r, PictureResult)
    assert r.svg is not None, r.problems
    ET.fromstring(r.svg)
    return r


def engine(src, values=None):
    e = Engine(src, values or {})
    e.run()
    return e


# ---------------------------------------------------------------- 문서의 그림
@pytest.mark.parametrize("doc,ids", [
    ("tests/docs/21-tikz-basic.htex", None),
    ("tests/docs/23-pgfplots.htex", {"n2", "n3"}),
    ("tests/docs/25-parameters.htex", {"n2", "n3"}),
    ("examples/oscillator.htex", None),
])
def test_documents_render(doc, ids):
    tree = parse_file(ROOT / doc)
    pics = pictures(tree)
    assert pics
    for p in pics:
        if ids is not None and p["id"] not in ids:
            continue
        r = render_picture_node(tree, p["id"], {})
        assert r.svg, (p["id"], r.problems)
        root = ET.fromstring(r.svg)
        assert root.tag == SVG + "svg"
        assert root.get("viewBox") and root.get("width") is None


def test_3d_and_bad_expressions_are_problems():
    tree = parse_file(DOCS / "23-pgfplots.htex")
    r = render_picture_node(tree, "n5", {})
    assert r.svg is None and any("3차원" in p for p in r.problems)
    tree = parse_file(DOCS / "25-parameters.htex")
    for nid in ("n5", "n7"):
        r = render_picture_node(tree, nid, {})
        assert r.svg is None and any("계산식" in p for p in r.problems)


def test_render_picture_node_missing_and_defaults():
    tree = parse_file(DOCS / "25-parameters.htex")
    assert render_picture_node(tree, "n999", {}).svg is None
    assert merge_values(tree) == {"omega": 1.0, "gamma": 0.2}
    assert merge_values(tree, {"omega": 99, "gamma": -5, "kappa": 1}) == {"omega": 3.0, "gamma": 0.0}
    assert merge_values(tree, {"omega": "nan"})["omega"] == 1.0
    # 범위로 자른 결과와 같은 그림
    a = render_picture_node(tree, "n2", {"omega": 99}).svg
    b = render_picture_node(tree, "n2", {"omega": 3}).svg
    assert a == b


def test_parameter_changes_svg():
    tree = parse_file(DOCS / "25-parameters.htex")
    a = render_picture_node(tree, "n2", {"omega": 1}).svg
    b = render_picture_node(tree, "n2", {"omega": 2.5}).svg
    c = render_picture_node(tree, "n2", {"omega": 1}).svg
    assert a != b and a == c        # 결정적 (캐시 가능)
    p1 = render_picture_node(tree, "n3", {"omega": 1}).svg
    p2 = render_picture_node(tree, "n3", {"omega": 2}).svg
    assert p1 != p2


def test_html_figure_matches_endpoint():
    from htex.html import render
    tree = parse_file(ROOT / "examples" / "oscillator.htex")
    html = render(tree)
    m = re.search(r'<figure class="htex-picture" id="(n\d+)"[^>]*>(<svg.*?</svg>)', html, re.S)
    assert m
    assert render_picture_node(tree, m.group(1), {}).svg == m.group(2)
    assert "<pre>" not in html.split('class="htex-picture"', 1)[1].split("</figure>", 1)[0]


def test_html_fallback_and_notes():
    from htex.html import render
    tree = parse_file(DOCS / "25-parameters.htex")
    html = render(tree)
    assert "<pre>\\draw plot[domain=0:1] (\\x, {sin(\\x r});</pre>" in html
    tree = {"hypertex": "2.0", "meta": {}, "labels": {}, "parameters": [], "bibliography": [],
            "body": [{"kind": "picture", "id": "n1", "source": "\\draw (0,0) -- (1,1); \\frobnicate;"}]}
    html = render(tree)
    assert '<details class="htex-picture-notes"' in html and "frobnicate" in html


# ---------------------------------------------------------------- 좌표
def test_cartesian_polar_relative():
    e = engine(r"\coordinate (A) at (1,2); \coordinate (B) at (90:2); \coordinate (C) at (2mm, 1cm);")
    assert e.nodes["A"].center == pytest.approx((1, 2))
    assert e.nodes["B"].center == pytest.approx((0, 2), abs=1e-9)
    assert e.nodes["C"].center == pytest.approx((0.2, 1))
    e = engine(r"\draw (1,1) -- ++(1,0) coordinate (P) -- +(0,1) coordinate (Q) -- ++(0,2) coordinate (R);")
    assert e.nodes["P"].center == pytest.approx((2, 1))
    assert e.nodes["Q"].center == pytest.approx((2, 2))
    assert e.nodes["R"].center == pytest.approx((2, 3))   # + 는 기준점을 옮기지 않음


def test_perpendicular_and_calc():
    e = engine(r"\coordinate (A) at (1,2); \coordinate (B) at (3,5);"
               r"\coordinate (C) at (A |- B); \coordinate (D) at (A -| B);"
               r"\coordinate (M) at ($(A)!0.5!(B)$); \coordinate (S) at ($(A)+(1,0)$);"
               r"\coordinate (T) at ($2*(A) - (B)$); \coordinate (U) at ($(A)!1!(A |- 0,0)$);")
    assert e.nodes["C"].center == pytest.approx((1, 5))
    assert e.nodes["D"].center == pytest.approx((3, 2))
    assert e.nodes["M"].center == pytest.approx((2, 3.5))
    assert e.nodes["S"].center == pytest.approx((2, 2))
    assert e.nodes["T"].center == pytest.approx((-1, -1))
    assert e.nodes["U"].center == pytest.approx((1, 0))


def test_scale_and_shift():
    e = engine(r"\begin{scope}[scale=2, xshift=1cm] \coordinate (A) at (1,1); \end{scope}")
    assert e.nodes["A"].center == pytest.approx((4, 2))   # xshift 는 scale 뒤 좌표계에서 (TikZ와 같음)


def test_positioning_and_anchor():
    e = engine(r"\node[draw] (A) at (0,0) {A}; \node[draw, below=of A] (B) {B};"
               r"\node[anchor=west] (C) at (5,0) {긴 글자};")
    a, b, c = e.nodes["A"], e.nodes["B"], e.nodes["C"]
    assert b.center[0] == pytest.approx(0)
    assert (a.center[1] - a.hh) - (b.center[1] + b.hh) == pytest.approx(1.0)   # node distance 1cm
    assert c.center[0] - c.hw == pytest.approx(5)


def test_node_on_path_midway():
    e = engine(r"\draw (0,0) -- (4,0) node[midway, above] (M) {m};")
    m = e.nodes["M"]
    assert m.center[0] == pytest.approx(2)
    assert m.center[1] > 0


# ---------------------------------------------------------------- 스타일
def test_colors():
    assert parse_color("blue!50") == pytest.approx((0.5, 0.5, 1))
    assert parse_color("red!30!black") == pytest.approx((0.3, 0, 0))
    assert parse_color("nope") is None
    assert css_color(None) == "currentColor"
    assert css_color("black") == "currentColor"
    assert css_color("red") == "#ff0000"
    assert css_color("white", fill=True).startswith("var(")


def test_dimensions_and_arrows():
    assert parse_dim("2pt") == pytest.approx(2 * PT)
    assert parse_dim("1in") == pytest.approx(2.54)
    assert parse_dim("2") is None
    assert parse_arrow_key("->") == (None, ">")
    assert parse_arrow_key("<->") == ("<", ">")
    assert parse_arrow_key("-{Stealth}") == (None, "Stealth")
    assert parse_arrow_key("{Stealth[length=3mm]}-latex") == ("Stealth", "latex")
    assert parse_arrow_key("line width") is None


def test_style_application():
    e = Engine("", {})
    st = e.applier.apply(Style(), "thick, dashed, red, fill=blue!20, ->, opacity=0.5, rounded corners")
    assert st.line_width == 0.8 and st.dash and st.color == "red" and st.fill == "blue!20"
    assert st.arrows == (None, ">") and st.opacity == 0.5 and st.rounded > 0
    st = e.applier.apply(Style(), "line width=2pt, help lines")
    assert st.line_width == pytest.approx(0.2)    # help lines 가 뒤에서 덮음
    e.applier.define("mine/.style={very thick, blue}")
    st = e.applier.apply(Style(), "mine")
    assert st.line_width == 1.2 and st.color == "blue"


def test_svg_attributes_from_style():
    r = svg_of(r"\draw[thick, red, dashed] (0,0) -- (1,0); \fill[blue!50, fill opacity=0.3] (0,0) circle (1);"
               r"\draw (0,0) -- (1,1);")
    assert 'stroke="#ff0000"' in r.svg and "stroke-dasharray" in r.svg
    assert 'fill="#8080ff"' in r.svg and 'fill-opacity="0.3"' in r.svg
    assert 'stroke="currentColor"' in r.svg


def test_tikzset_style():
    r = svg_of(r"\tikzset{box/.style={draw, fill=yellow}} \node[box] {x};")
    assert 'fill="#ffff00"' in r.svg


def test_arrow_tips_drawn():
    r = svg_of(r"\draw[-{Stealth}] (0,0) -- (2,0);")
    assert r.svg.count("<path") == 2
    r = svg_of(r"\draw[<->] (0,0) -- (2,0);")
    assert r.svg.count("<path") == 3


def test_path_operations():
    for src in [r"\draw (0,0) rectangle (1,1);", r"\draw (0,0) ellipse (1 and 0.5);",
                r"\draw (0,0) arc (0:90:1);", r"\draw (0,0) arc[start angle=0, delta angle=90, radius=1];",
                r"\draw (0,0) to[bend left] (2,0);", r"\draw (0,0) to[bend right=45] (2,0);",
                r"\draw (0,0) -| (1,1) |- (2,2);", r"\draw[step=0.5] (0,0) grid (2,2);",
                r"\draw (0,0) .. controls (1,1) and (2,1) .. (3,0);",
                r"\clip (0,0) rectangle (1,1); \draw (0,0) circle (2);",
                r"\filldraw[fill=red] (0,0) -- (1,0) -- (0,1) -- cycle;",
                r"\path[draw] (0,0) -- (1,1);", r"\draw[rounded corners=3pt] (0,0) -- (1,0) -- (1,1);",
                r"\draw plot[smooth] coordinates {(0,0) (1,1) (2,0)};",
                r"\draw[domain=0:360, samples=50] plot (\x:1);"]:
        svg_of(src)


def test_arc_geometry():
    e = engine(r"\draw (1,0) arc (0:90:1) coordinate (E);")
    assert e.nodes["E"].center == pytest.approx((0, 1), abs=1e-9)


def test_node_text_svg_and_math():
    r = svg_of(r"\node at (0,0) {한글 <b>&};")
    root = ET.fromstring(r.svg)
    texts = [t for t in root.iter(SVG + "text")]
    assert texts and "".join(texts[0].itertext()) == "한글 <b>&"
    assert "var(--body-font" in r.svg
    r = svg_of(r"\node at (0,0) {상태 $\psi$};")
    assert "<foreignObject" in r.svg and "<math" in r.svg and "http://www.w3.org/1998/Math/MathML" in r.svg


# ---------------------------------------------------------------- foreach
def test_foreach_list_and_range():
    e = engine(r"\foreach \i in {0,...,4} { \coordinate (P\i) at (\i,0); }")
    assert {f"P{i}" for i in range(5)} <= set(e.nodes)
    e = engine(r"\foreach \x in {1,3,...,9} \coordinate (Q\x) at (\x,0);")
    assert {"Q1", "Q3", "Q5", "Q7", "Q9"} <= set(e.nodes) and "Q2" not in e.nodes
    e = engine(r"\foreach \x/\y in {1/a, 2/b} \coordinate (\y) at (\x,0);")
    assert e.nodes["b"].center == pytest.approx((2, 0))


def test_foreach_nested_and_count():
    e = engine(r"\foreach \i in {1,2} \foreach \j in {1,2,3} \coordinate (N\i\j) at (\i,\j);")
    assert len([k for k in e.nodes if k.startswith("N")]) == 6
    e = engine(r"\foreach \c [count=\n] in {a,b,c} \coordinate (C\n) at (\n,0);")
    assert {"C1", "C2", "C3"} <= set(e.nodes)


def test_foreach_limit():
    r = render_picture(r"\foreach \i in {1,...,2000} { \draw (0,0) -- (\i,1); }")
    assert r.svg is not None
    assert any("1,000" in p for p in r.problems)
    assert r.svg.count("<path") <= 1000
    r = render_picture(r"\foreach \i in {1,...,100} \foreach \j in {1,...,100} \fill (\i,\j) circle (1pt);")
    assert any("1,000" in p for p in r.problems)


# ---------------------------------------------------------------- 계산식 연동
def test_plot_uses_expr_and_params():
    src = r"\draw plot[domain=0:1, samples=3] (\x, {\k*\x});"
    a = svg_of(src, {"k": 1}).svg
    b = svg_of(src, {"k": 2}).svg
    assert a != b
    e = engine(r"\coordinate (A) at ({cos(60)}, {sin(pi/2 r)});")
    assert e.nodes["A"].center == pytest.approx((0.5, 1))
    e = engine(r"\coordinate (A) at (\k, 0);", {"k": 3})
    assert e.nodes["A"].center == pytest.approx((3, 0))


def test_nan_breaks_line():
    r = svg_of(r"\draw plot[domain=-1:1, samples=5] (\x, {sqrt(\x)});")
    d = re.findall(r'<path d="([^"]+)"', r.svg)[0]
    assert d.startswith("M") and "NaN" not in r.svg and "nan" not in r.svg


def test_samples_limit():
    r = render_picture(r"\draw plot[domain=0:1, samples=5000] (\x, {\x^2});")
    assert r.svg and any("1,000" in p for p in r.problems)
    d = re.findall(r'<path d="([^"]+)"', r.svg)[0]
    assert d.count("L") == 999


# ---------------------------------------------------------------- pgfplots
def test_nice_ticks():
    assert nice_ticks(0, 10) == [0, 2, 4, 6, 8, 10]
    assert nice_ticks(-0.75, 1.0) == [-0.5, 0, 0.5, 1.0]
    assert nice_ticks(0, 1, 5) == pytest.approx([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    for lo, hi in [(0, 7), (-3.3, 12.1), (1e-3, 5e-3), (100, 1000)]:
        t = nice_ticks(lo, hi)
        step = t[1] - t[0]
        mant = step / 10 ** math.floor(math.log10(step))
        assert round(mant, 6) in (1, 2, 5)
        assert all(lo - 1e-12 <= v <= hi + 1e-12 for v in t)
    assert log_ticks(0, 2) == [0, 1, 2]
    assert len(log_ticks(-30, 30)) <= 11
    assert fmt_tick(0.5, 0.5) == "0.5" and fmt_tick(-1, 1) == "\u22121"


def _axis(body, opts=""):
    return render_picture(f"\\begin{{axis}}[{opts}]\n{body}\n\\end{{axis}}")


def test_axis_basics():
    r = _axis(r"\addplot[domain=0:10, samples=50] {x^2}; \addlegendentry{$x^2$}",
              "xlabel={$t$}, ylabel=높이, title=제목, grid=major, legend pos=north west")
    assert r.svg and not r.problems, r.problems
    ET.fromstring(r.svg)
    assert "높이" in r.svg and "제목" in r.svg and 'stroke-opacity="0.18"' in r.svg
    assert "clip-path" in r.svg


def test_axis_color_cycle_and_marks():
    r = _axis(r"\addplot coordinates {(0,0) (1,1)}; \addplot coordinates {(0,1) (1,0)};"
              r"\addplot coordinates {(0,.5) (1,.5)}; \addplot coordinates {(0,.2) (1,.2)};")
    s = r.svg
    i_blue, i_red, i_brown = s.find("#0000ff"), s.find("#ff0000"), s.find("#734c26")
    assert -1 < i_blue < i_red < i_brown
    r = _axis(r"\addplot[only marks, mark=o] coordinates {(0,0) (1,1) (2,0.5)};")
    assert r.svg.count("<circle") == 3


def test_axis_marks_kinds():
    for m in ("*", "o", "x", "+", "square"):
        r = _axis(f"\\addplot[mark={m}] coordinates {{(0,0) (1,1)}};")
        assert r.svg, (m, r.problems)


def test_axis_table_and_log():
    r = render_picture("\\begin{semilogyaxis}\n\\addplot table {\nn E\n1 1\n2 10\n3 100\n};\n\\end{semilogyaxis}")
    assert r.svg and not r.problems
    assert ">10<tspan" in r.svg      # 10^k 눈금
    r = render_picture("\\begin{loglogaxis}\\addplot coordinates {(1,1) (10,0) (100,100)};\\end{loglogaxis}")
    assert r.svg      # 0 은 로그 축에서 건너뜀


def test_axis_nan_breaks_line():
    r = _axis(r"\addplot[domain=-1:1, samples=21] {ln(x)};")
    assert r.svg
    r = _axis(r"\addplot[domain=-2:2, samples=5] {1/x};")
    paths = re.findall(r'<path d="(M[^"]+)" fill="none" stroke="#0000ff"', r.svg)
    assert paths and paths[0].count("M") == 2


def test_axis_explicit_limits():
    e = Engine("\\begin{axis}[xmin=0, xmax=4, ymin=-1, ymax=1]\\addplot coordinates {(1,0) (2,0.5)};\\end{axis}", {})
    e.run()
    assert not e.problems


def test_legend_command():
    r = _axis(r"\addplot coordinates {(0,0) (1,1)}; \addplot coordinates {(0,1) (1,0)}; \legend{가, 나}")
    assert "가" in r.svg and "나" in r.svg


# ---------------------------------------------------------------- 안전
@pytest.mark.parametrize("src", [
    r"\node {<script>alert(1)</script>};",
    r"\node[draw] {\"><svg onload=alert(1)>};",
    r'\node[fill={red" onload="x}] {a};',
    r"\node {$<script>$};",
    r"\draw[color=javascript:alert(1)] (0,0) -- (1,1);",
    r"\tikzset{x/.code={\write18{rm}}} \draw[x] (0,0) -- (1,1);",
    r"\begin{axis}[xlabel={<img src=x onerror=alert(1)>}]\addplot coordinates {(0,0) (1,1)};\end{axis}",
    r"\draw (0,0) -- (1,1) node {\href{javascript:x}{y}};",
])
def test_injection_is_escaped(src):
    r = render_picture(src)
    if r.svg is None:
        return
    root = ET.fromstring(r.svg)
    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        assert tag not in ("script", "iframe", "object", "embed", "image", "use", "a")
        for k in el.attrib:
            kl = k.split("}")[-1].lower()
            assert not kl.startswith("on")
            assert kl not in ("href", "src")
    assert "javascript:" not in r.svg.lower().replace("&amp;", "&") or "javascript:" not in "".join(
        v for el in root.iter() for v in el.attrib.values())


@pytest.mark.parametrize("src", [
    "", "\\", "{{{{{{", "}}}}", "\\draw (", "\\draw[", "\\draw (0,0) -- (", "\\node",
    "\\foreach \\i in {1,...,} {}", "\\foreach", "\\draw (0,0) circle;", "\\draw (A) -- (B);",
    "\\begin{axis}", "\\begin{axis}\\addplot {", "\\draw plot (\\x, {1/0});",
    "\\draw (" + "(" * 500 + "0,0" + ")" * 500 + ";", "{" * 5000 + "}" * 5000,
    "\\draw (0,0) -- (1e308,1e308);", "\\draw (nan,0) -- (1,1);",
    "\\begin{scope}" * 100, "\\draw " + "-- (1,1) " * 20000 + ";",
    "\\coordinate (A) at ($(A)+(1,0)$); \\draw (A) -- (0,0);",
    "\\tikzset{a/.style={b}, b/.style={a}} \\draw[a] (0,0) -- (1,1);",
])
def test_garbage_never_raises(src):
    r = render_picture(src)
    assert isinstance(r, PictureResult)
    if r.svg:
        ET.fromstring(r.svg)


def test_non_string_inputs():
    assert render_picture(None).svg is None
    assert render_picture(r"\draw (0,0) -- (1,1);", {"k": "abc", "j": None}).svg
    assert render_picture_node({}, "n1").svg is None
    assert render_picture_node(None, "n1").svg is None


def test_huge_loops_are_bounded_in_time():
    t0 = time.monotonic()
    r = render_picture(r"\foreach \i in {1,...,1000} { \foreach \j in {1,...,1000} { \draw plot[samples=1000] (\x,\x); } }")
    assert time.monotonic() - t0 < 2.5
    assert r.problems
    t0 = time.monotonic()
    r = render_picture("\\begin{axis}" + "\\addplot[samples=1000] {sin(x)};" * 200 + "\\end{axis}")
    assert time.monotonic() - t0 < 2.5


def test_element_limit():
    r = render_picture(r"\draw " + "-- (1,1) -- (0,0) " * 6000 + ";")
    assert any("10,000" in p for p in r.problems)


def test_timeout_reports(monkeypatch):
    import htex.tikz as tk
    monkeypatch.setattr(tk, "TIME_LIMIT", 0.0)
    r = render_picture(r"\foreach \i in {1,...,50} { \draw (0,0) -- (\i,1); }")
    assert any("시간" in p for p in r.problems)
