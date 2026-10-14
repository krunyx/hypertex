"""B: 매크로 확장기 단위 테스트. 사례 15–18, 20, 27의 매크로 단계를 직접 확인한다."""
from collections import Counter
from pathlib import Path

import pytest

from htex.diagnostics import Sink
from htex.lexer import tokenize
from htex.loader import Loader
from htex.macros import Expander, Limits, MacroTable
from htex.tokens import T, detokenize

DOCS = Path(__file__).resolve().parent.parent / "docs"


def run(src, mode="native", base=DOCS, limits=None):
    sink = Sink()
    toks = tokenize(src, sink)
    out = Expander(MacroTable(), sink, Loader(base), mode=mode, limits=limits).expand(toks)
    return out, sink


def run_doc(name):
    return run((DOCS / name).read_text(encoding="utf-8"),
               mode="compat" if name.endswith(".tex") else "native")


def codes(sink):
    return Counter(d.code for d in sink.items)


def cs_names(tokens):
    return [t.text for t in tokens if t.type is T.CS]


def norm(s):
    return " ".join(s.split())


# ------------------------------------------------------------ 사례 15
def test_case15_macros():
    out, sink = run_doc("15-macros.htex")
    assert codes(sink) == Counter()
    names = cs_names(out)
    for gone in ("newcommand", "renewcommand", "DeclareMathOperator",
                 "ket", "bra", "braket", "norm", "R", "Tr"):
        assert gone not in names
    assert out[-1].type is T.EOF
    text = norm(detokenize(out))
    assert r"$\left| \psi \right\rangle$" in text
    assert r"$\left\langle\phi \right|$" in text
    assert r"\left\langle\phi \middle| \psi \right\rangle" in text
    assert r"\left\| x \right\|_{2}" in text            # 기본 선택 인수
    assert r"\left\| x \right\|_{\infty}" in text       # 준 선택 인수
    assert r"\in\mathbb{R}$" in text
    assert r"\operatorname{Tr}\rho" in text
    assert r"$\mathbf{R}^3$" in text                     # \renewcommand 이후


def test_case15_spans_point_to_call_site():
    out, _ = run_doc("15-macros.htex")
    left = next(t for t in out if t.is_cs("left"))
    assert left.span.line == 11


# ------------------------------------------------------------ 사례 16
def test_case16_recursion():
    out, sink = run_doc("16-macro-recursion.htex")
    assert codes(sink) == Counter({"macro-recursion": 3})
    assert [d.span.line for d in sink.items] == [3, 4, 5]
    names = cs_names(out)
    assert "newcommand" not in names
    assert names.count("loopA") == 1 and names.count("self") == 1   # 빌더가 undefined-command 2건
    assert "loopB" not in names
    assert "이 단락 이후의 내용은 정상 렌더링되어야 한다." in detokenize(out)


# ------------------------------------------------------------ 사례 17
def test_case17_expansion_limit():
    out, sink = run_doc("17-expansion-limit.htex")
    assert codes(sink) == Counter({"expansion-limit": 2})
    assert [d.span.line for d in sink.items] == [16, 18]
    body = out[next(k for k, t in enumerate(out) if t.is_cs("begin")):]
    xs = sum(1 for t in body if t.type is T.CHAR and t.text == "x")
    assert xs == 20 + 200 + 2000
    names = cs_names(out)
    assert not any(n.startswith("x") for n in names)
    assert "이 단락은 정상 렌더링되어야 한다." in detokenize(out)


def test_total_expansion_limit():
    src = r"\newcommand{\a}{a}" + r"\a" * 50
    out, sink = run(src, limits=Limits(total_expansions=10))
    assert codes(sink) == Counter({"expansion-limit": 40})
    assert sum(1 for t in out if t.text == "a") == 10


def test_total_limit_inside_one_expansion():
    src = r"\newcommand{\a}{a}\newcommand{\b}{\a\a\a\a\a}\b z"
    out, sink = run(src, limits=Limits(total_expansions=3))
    assert codes(sink) == Counter({"expansion-limit": 1})
    assert norm(detokenize(out)) == "z"


# ------------------------------------------------------------ 사례 18
def test_case18_usemacros():
    out, sink = run_doc("18-usemacros.htex")
    assert codes(sink) == Counter()
    names = cs_names(out)
    assert "usemacros" in names               # 빌더가 meta.macroImports를 채운다
    i = next(k for k, t in enumerate(out) if t.is_cs("usemacros"))
    j = next(k for k in range(i, len(out)) if out[k].type is T.EGROUP)
    assert detokenize(out[i:j + 1]) == r"\usemacros{notation.htex}"
    text = norm(detokenize(out))
    assert r"\left| 0 \right\rangle" in text
    assert r"\mathrm{d}x" in text
    assert r"\operatorname{Tr}A" in text
    assert "본문은" not in text               # notation.htex 본문은 가져오지 않는다


def test_usemacros_missing():
    _, sink = run(r"\usemacros{nope.htex}")
    assert codes(sink) == Counter({"missing-resource": 1})


def test_usemacros_forbidden():
    out, sink = run(r"\usemacros{javascript:alert(1)}")
    assert codes(sink) == Counter({"insecure-resource": 1})
    assert "usemacros" in cs_names(out)


# ------------------------------------------------------------ 사례 20
def test_case20_excluded():
    out, sink = run_doc("20-excluded-commands.htex")
    c = codes(sink)
    assert c["excluded-command"] >= 8 and set(c) == {"excluded-command"}
    text = norm(detokenize(out))
    for leaked in ("rm -rf", "passwd", "chapter1", "chapter2", "2cm", "withargs", "@=11"):
        assert leaked not in text
    assert "이 문장은 정상 렌더링되어야 한다." in text
    assert set(cs_names(out)) == {"documentclass", "title", "begin", "end"}


# ------------------------------------------------------------ 사례 27
def test_case27_compat():
    out, sink = run_doc("27-compat-article.tex")
    assert codes(sink) == Counter()
    names = cs_names(out)
    for gone in ("def", "vect", "input", "newpage", "bibliographystyle"):
        assert gone not in names
    text = norm(detokenize(out))
    assert r"$\mathbf{v}$" in text and r"\mathbf{F} = m \mathbf{a}" in text
    # appendix.tex가 \input 자리(정리 뒤, \bibliography 앞)에 펼쳐진다
    assert text.index(r"\end{theorem}") < text.index(r"\section{Appendix}") < text.index(r"\bibliography")
    assert r"\label{sec:appendix}" in text
    assert "plain" not in text


def test_compat_input_missing_and_depth(tmp_path):
    (tmp_path / "self.tex").write_text(r"x\input{self}", encoding="utf-8")
    out, sink = run(r"\input{self}\input{nope}", mode="compat", base=tmp_path)
    c = codes(sink)
    assert c["missing-resource"] == 1 and c["expansion-limit"] == 1
    assert sum(1 for t in out if t.text == "x") == 8


def test_compat_def_with_args_is_excluded():
    out, sink = run(r"\def\f#1{#1}\f{a}", mode="compat")
    assert codes(sink) == Counter({"excluded-command": 1})
    assert cs_names(out) == ["f"]


def test_native_input_is_excluded():
    _, sink = run(r"\input{appendix}")
    assert codes(sink) == Counter({"excluded-command": 1})


# ------------------------------------------------------------ 일반 규칙
@pytest.mark.parametrize("src,expected", [
    (r"\newcommand{\f}[2]{(#1,#2)}\f{a}{b}", "(a,b)"),
    (r"\newcommand{\f}[2]{(#1,#2)}\f ab", "(a,b)"),                 # 단일 토큰 인수
    (r"\newcommand\f[1]{<#1>}\f{\alpha}", r"<\alpha>"),             # 중괄호 없는 이름
    (r"\newcommand*{\f}{F}\f", "F"),
    (r"\newcommand{\f}[2][d]{(#1,#2)}\f[{a]b}]{y}", "(a]b,y)"),     # 중괄호 속 ]
    (r"\newcommand{\f}[2][d]{(#1,#2)}\f[[z]]{w}", "([z],w)"),       # 중첩 대괄호
    (r"\newcommand{\f}[1]{<#1>}\newcommand{\g}{\f}\g{x}", "<x>"),   # 본문 뒤 인수 읽기
    (r"\newcommand{\f}[1]{#1#1}\f{{a}}", "{a}{a}"),
    (r"\newcommand{\f}{A}\newcommand{\f}{B}\f", "A"),                # 중복 \newcommand 무시
    (r"\renewcommand{\g}{G}\g", "G"),
    (r"\newcommand{\alpha}{X}\alpha", r"\alpha"),                    # 내장 명령은 재정의 안 함
    (r"\foo{x}", r"\foo{x}"),                                        # 미정의는 통과
])
def test_expansion(src, expected):
    out, sink = run(src)
    assert codes(sink) == Counter()
    assert detokenize(out) == expected


def test_indirect_cycle_via_renew():
    _, sink = run(r"\newcommand{\b}{B}\newcommand{\a}{\b}\renewcommand{\b}{\a}\a")
    assert codes(sink) == Counter({"macro-recursion": 1})


def test_parameter_name_not_macro():
    out, sink = run(r"\parameter{\k}{0}{1}{0}\newcommand{\k}{K}\newcommand{\u}{\k}\u")
    assert codes(sink) == Counter()
    assert cs_names(out) == ["parameter", "k", "k"]


def test_unterminated_definition_does_not_raise():
    out, sink = run("\\newcommand{\\f}{abc\n\nrest")
    assert out[-1].type is T.EOF
    assert "rest" in detokenize(out)


@pytest.mark.parametrize("src", [r"\newcommand", r"\newcommand{", r"\newcommand{\f}[x]{y}",
                                 r"\DeclareMathOperator", r"\usemacros", r"\usemacros{",
                                 r"\def", r"\catcode", r"\csname a", "\\newcommand{\\f}[1]{#1}\\f"])
def test_never_raises(src):
    for mode in ("native", "compat"):
        out, _ = run(src, mode=mode)
        assert out[-1].type is T.EOF


def test_compat_macro_body_may_use_page_commands():
    out, sink = run(r"\newcommand{\np}{\newpage x}\np", mode="compat")
    assert codes(sink) == Counter()
    assert detokenize(out) == "x"


def test_native_macro_body_with_excluded_is_rejected():
    out, sink = run(r"\newcommand{\np}{\newpage x}\np")
    assert codes(sink) == Counter({"excluded-command": 1})
    assert cs_names(out) == ["np"]


def test_large_document_is_fast():
    import time
    src = (r"\newcommand{\v}[1]{\mathbf{#1}}" + "\n"
           + ("가나다 $\\v{x} + \\v{y}$ 라마바.\n\n" * 8000))
    t0 = time.perf_counter()
    out, sink = run(src)
    assert time.perf_counter() - t0 < 2.0
    assert codes(sink) == Counter()
