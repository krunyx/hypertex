"""D: 그림 검사 단위 테스트 (명세 3.1절, 사례 21–23, 25)."""
import random
import re
from collections import Counter
from pathlib import Path

import pytest

from htex.diagnostics import Sink, Span
from htex.picture import PictureInfo, check_picture

DOCS = Path(__file__).resolve().parents[1] / "docs"
_PIC = re.compile(r"\\begin\{tikzpicture\}(.*?)\\end\{tikzpicture\}", re.S)


def pictures(name):
    return _PIC.findall((DOCS / name).read_text(encoding="utf-8"))


def run(src, params=()):
    sink = Sink()
    info = check_picture(src, set(params), Span(1, 1), sink)
    return info, Counter(d.code for d in sink.items)


def run_doc(name, params=()):
    infos, total = [], Counter()
    for body in pictures(name):
        info, c = run(body, params)
        infos.append(info)
        total += c
    return infos, total


def test_21_tikz_basic():
    infos, diags = run_doc("21-tikz-basic.htex")
    assert len(infos) == 2
    assert diags == Counter()
    assert not any(i.uses_pgfplots for i in infos)


def test_22_tikz_limits():
    infos, diags = run_doc("22-tikz-limits.htex")
    assert len(infos) == 3
    # unknown-tikz-library 는 빌더 몫
    assert diags == Counter({"tikz-limit": 1, "plot-sample-limit": 1, "excluded-command": 1})


def test_23_pgfplots():
    infos, diags = run_doc("23-pgfplots.htex")
    assert len(infos) == 3
    assert all(i.uses_pgfplots for i in infos)
    assert diags == Counter({"excluded-command": 1})


def test_25_parameters():
    infos, diags = run_doc("25-parameters.htex", {"omega", "gamma"})
    assert len(infos) == 4
    assert diags == Counter({"expression-syntax": 2})
    assert infos[0].params == ["gamma", "omega"]
    assert infos[1].params == ["omega"] and infos[1].uses_pgfplots
    assert infos[2].params == [] and infos[3].params == []


def test_unknown_parameter_in_picture():
    _, c = run(r"\draw plot (\x, {\kappa*\x});", {"omega"})
    assert c == Counter({"unknown-parameter": 1})


def test_foreach_limits():
    assert run(r"\foreach \i in {1,...,1000} { \draw (\i,0) circle (1pt); }")[1] == Counter()
    _, c = run(r"\foreach \i in {1,...,600} {\draw (\i,0)--(0,0);}"
               r"\foreach \j in {1,...,600} {\draw (\j,0)--(0,0);}")
    assert c == Counter({"tikz-limit": 1})          # 합 1,200, 한 번만
    _, c = run(r"\foreach \i in {1,...,40} \foreach \j in {1,...,40} {\fill (\i,\j) circle (1pt);}")
    assert c == Counter({"tikz-limit": 1})          # 중첩: 40 + 1,600
    _, c = run(r"\foreach \x in {0,0.001,...,2} {\draw (\x,0) -- (\x,1);}")
    assert c == Counter({"tikz-limit": 1})          # 2,001회
    assert run(r"\foreach \x/\l in {1/a,2/b,3/c} {\node at (\x,0) {\l};}")[1] == Counter()
    assert run(r"\foreach \c in {a,...,z} {\node at (0,0) {\c};}")[1] == Counter()


def test_path_element_limit():
    coords = " -- ".join(f"({i},0)" for i in range(6000))
    _, c = run(r"\draw " + coords + ";")
    assert c == Counter({"tikz-limit": 1})
    _, c = run(r"\foreach \i in {1,...,500} { \draw (0,0) -- (1,1) -- (2,0) -- (3,3) -- (4,4) -- (5,5) -- (6,6) -- (7,7) -- (8,8) -- (9,9) -- (10,10) -- (11,11); }")
    assert c == Counter({"tikz-limit": 1})          # 500 × 23 > 10,000


def test_samples_and_data_limits():
    assert run(r"\draw plot[samples=1000, domain=0:1] (\x, \x);")[1] == Counter()
    assert run(r"\begin{axis}\addplot[samples=1001] {x};\end{axis}")[1] == Counter({"plot-sample-limit": 1})
    assert run(r"\draw[samples=2000] plot (\x, {sin(\x r)});")[1] == Counter({"plot-sample-limit": 1})
    pts = " ".join(f"({i},{i})" for i in range(10_001))
    _, c = run(r"\begin{axis}\addplot coordinates {" + pts + r"};\end{axis}")
    assert c == Counter({"data-limit": 1})
    rows = "\n".join(f"{i} {i*i}" for i in range(10_001))
    _, c = run("\\begin{axis}\\addplot table {\nx y\n" + rows + "\n};\\end{axis}")
    assert c == Counter({"data-limit": 1})
    rows = "\n".join(f"{i} {i*i}" for i in range(10_000))
    assert run("\\begin{axis}\\addplot table {\nx y\n" + rows + "\n};\\end{axis}")[1] == Counter()


def test_excluded_commands():
    for src in [r"\pgfkeys{/tikz/x=2cm}", r"\tikzexternalize", r"\usepgfplotslibrary{external}\tikzexternalize[prefix=f/]",
                r"\begin{axis}\addplot3 {x*y};\end{axis}", r"\pgfmathdeclarefunction{f}{1}{#1}",
                r"\begin{axis}\addplot gnuplot {x**2};\end{axis}"]:
        assert run(src)[1]["excluded-command"] == 1, src


def test_addplot_forms_and_domain():
    src = (r"\begin{axis}[domain=-\omega:\omega]"
           r"\addplot+[mark=none] expression {x^2};"
           r"\addplot ({cos(x r)}, {sin(x r)});"
           r"\addplot {ifthenelse(x > 0, sqrt(x), 0)};\end{axis}")
    info, c = run(src, {"omega"})
    assert c == Counter() and info.params == ["omega"] and info.uses_pgfplots
    _, c = run(r"\begin{axis}\addplot {x +};\end{axis}")
    assert c == Counter({"expression-syntax": 1})


def test_params_outside_expressions_and_foreach_vars():
    info, c = run(r"\foreach \i in {1,2,3} { \draw (\i, \omega) circle ({\i*0.1}); "
                  r"\draw plot[domain=0:\i] (\x, {\i*\x}); } \node at (0,0) {$\gamma$};",
                  {"omega", "gamma"})
    assert c == Counter()
    assert info.params == ["omega"]                 # $\gamma$ 는 노드 글이라 제외


@pytest.mark.parametrize("src", [
    "", "{", "}", "[", "(", ")", "$", "\\", "\\foreach", "\\foreach \\i in", "\\foreach \\i in {",
    "\\addplot", "\\addplot[", "\\addplot {", "\\addplot (", "\\draw plot", "\\draw plot (\\x, {",
    "\\foreach \\i in {1,...,} {}", "\\foreach \\i in {,...,5} {}", "\\foreach \\i in {1,1,...,5} {}",
    "\\draw plot[samples=" + "9" * 500 + "] (\\x,\\x);", "{" * 5000 + "}" * 10,
    "\\foreach \\i in {1,...,10} " * 300 + "{\\draw (0,0);}",
    "(" * 20000, "[" * 20000, "\\begin{", "\\end{axis", "\\pgfkeys", "%",
])
def test_garbage_never_raises(src):
    info, _ = run(src, {"omega"})
    assert isinstance(info, PictureInfo)


def test_random_fuzz_never_raises():
    rnd = random.Random(20261014)
    alphabet = list(r"{}[]()$\;,.:=+-*/^ \n%0123456789") + [
        "\\draw", "\\foreach", " in ", "plot", "\\addplot", "samples=", "domain=", "...",
        "\\x", "\\omega", "sin(", "coordinates", "table", "node", "--", "\\begin{axis}"]
    for _ in range(400):
        src = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 80)))
        info, _ = run(src, {"omega"})
        assert isinstance(info, PictureInfo)
