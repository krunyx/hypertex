"""4단계(K): 실제 LaTeX 원고 호환. 매크로 층·렉서·빌더의 compat 동작."""
from __future__ import annotations

from collections import Counter

from htex.diagnostics import Sink
from htex.lexer import tokenize
from htex.loader import Loader
from htex.macros import Expander, MacroTable
from htex.parser import parse_text
from htex.tokens import T


def run(src, mode="compat"):
    sink = Sink()
    out = Expander(MacroTable(), sink, Loader("."), mode=mode).expand(tokenize(src, sink))
    return out, sink


def flat(tokens):
    return "".join(("\\" + t.text + " ") if t.type is T.CS else t.text
                   for t in tokens if t.type is not T.EOF).strip()


def codes(sink):
    return Counter(d.code for d in sink.items)


def parse(src):
    return parse_text(src, url="doc.tex")


def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def kinds(tree):
    return Counter(n["kind"] for n in walk(tree["body"]) if "kind" in n)


def diag_codes(tree):
    return Counter(d["code"] for d in tree["diagnostics"])


# ---------------------------------------------------------------- 매크로 층
def test_skip_table_consumes_arguments():
    out, sink = run(r"a\index{foo}\setcounter{x}{3}\medskip\numberwithin{equation}{section}b")
    assert flat(out) == "ab" and not sink.items


def test_skip_table_only_in_compat():
    out, sink = run(r"\index{foo}", mode="native")
    assert "index" in flat(out)


def test_def_with_params():
    out, sink = run(r"\def\pair#1#2{(#1,#2)}\pair{a}{b}")
    assert flat(out) == "(a,b)" and not sink.items


def test_gdef_and_let():
    out, sink = run(r"\gdef\a{x}\let\b=\a \let\c\alpha \b\c")
    assert flat(out) == r"x\alpha" and not sink.items


def test_let_copies_macro_with_args():
    out, _ = run(r"\newcommand{\f}[1]{<#1>}\let\g\f \g{z}")
    assert flat(out) == "<z>"


def test_providecommand_does_not_override():
    out, _ = run(r"\newcommand{\a}{1}\providecommand{\a}{2}\providecommand{\b}{3}\a\b")
    assert flat(out) == "13"


def test_newenvironment_expands():
    src = r"\newenvironment{note}[1]{\textbf{#1:} }{ (end)}\begin{note}{N}body\end{note}"
    out, sink = run(src)
    assert flat(out) == r"\textbf {N:} body (end)" and not sink.items


def test_comment_environment_and_comment_like_newenvironment():
    src = (r"\newenvironment{history}{\comment}{\endcomment}"
           r"a\begin{comment}x \begin{comment} y\end{comment} z\end{comment}b"
           r"\begin{history}secret\end{history}c")
    out, sink = run(src)
    assert flat(out) == "abc" and not sink.items


def test_makeatletter_ifnextchar():
    src = (r"\makeatletter\def\f{\@ifnextchar[{\f@opt}{\f@plain}}"
           r"\def\f@opt[#1]{O#1}\def\f@plain{P}\makeatother\f[x] \f y")
    out, sink = run(src)
    assert flat(out) == "Ox Py" and not sink.items


def test_ifstar():
    src = r"\makeatletter\def\s{\@ifstar{S}{N}}\makeatother\s*\s"
    out, _ = run(src)
    assert flat(out) == "SN"


def test_at_is_not_letter_outside_makeatletter():
    toks = tokenize(r"\a@b")
    assert [t.text for t in toks if t.type is T.CS] == ["a"]


# ---------------------------------------------------------------- 수식
def test_mathop_definition_no_longer_breaks_math():
    tree = parse(r"\def\Hom{\mathop{\mathrm{Hom}}\nolimits}"
                 r"\begin{document}$\Hom(X,Y)$ and $\mathbin{\centerdot}$\end{document}")
    assert "undefined-command" not in diag_codes(tree)


def test_delimited_def():
    out, sink = run(r"\def\pt(#1,#2){P_{#1#2}}\pt(a,{b,c}) \def\upto#1\stop{[#1]}\upto x y\stop!")
    assert flat(out) == "P_{ab,c} [x y]!" and not sink.items


def test_guarded_recursion_allowed_in_compat():
    src = (r"\makeatletter\def\tp#1{[#1]\@ifnextchar\bgroup{\tp}{}}\makeatother"
           r"\tp{a}{b}{c}.")
    out, sink = run(src)
    assert flat(out) == "[a][b][c]." and not sink.items


def test_runaway_recursion_hits_limit_not_hang():
    out, sink = run(r"\def\loop{x\loop}\loop")
    assert "expansion-limit" in codes(sink)


def test_recursion_still_rejected_in_native():
    out, sink = run(r"\newcommand{\a}{\a}", mode="native")
    assert "macro-recursion" in codes(sink)


def test_iffalse_and_chardef():
    out, sink = run(r"a\iffalse hidden \iffalse x\fi more\fi b\chardef\bs=`\\ \bs")
    assert flat(out) == "ab \\" and not sink.items


# ---------------------------------------------------------------- 빌더
def texts(nodes):
    out = []
    for n in walk(nodes):
        if n.get("kind") == "text":
            out.append(n["text"])
    return "".join(out)


def test_cref_fills_type_names():
    tree = parse(r"""\newtheorem{theorem}{Theorem}
\begin{document}
\section{Intro}\label{sec:a}
\begin{equation}x=1\label{eq:a}\end{equation}
\begin{theorem}\label{thm:a}T\end{theorem}
See \cref{thm:a}, \Cref{sec:a}, \cref{eq:a} and \cref{sec:a,thm:a}.
\end{document}""")
    para = tree["body"][0]["children"][-1]
    links = [n for n in walk(para) if n.get("kind") == "link"]
    shown = [texts(l.get("children", [])) for l in links]
    assert shown == ["theorem 1", "Section 1", "eq. (1)", "section 1", "theorem 1"]
    assert "and" in texts(para)
    assert "undefined-command" not in diag_codes(tree)


def test_old_font_switch_scopes_to_group():
    tree = parse(r"\begin{document}a {\bf b c} d {\it e \em f} g\end{document}")
    para = tree["body"][0]
    styled = [(n["style"], texts(n["children"])) for n in walk(para) if n.get("kind") == "styled"]
    assert ("bold", "b c") in styled and ("italic", "e ") in styled and ("emph", "f") in styled
    assert texts(para).endswith("g")


def test_chapters_shift_section_levels():
    tree = parse(r"\begin{document}\chapter{One}\section{A}\subsection{B}\part{P}\chapter{Two}\end{document}")
    secs = [(n["level"], n.get("number"), texts(n["title"])) for n in walk(tree["body"])
            if n.get("kind") == "section"]
    assert secs == [(1, "1", "One"), (2, "1.1", "A"), (3, "1.1.1", "B"), (1, None, "P"),
                    (1, "2", "Two")]


def test_letter_accents_and_symbols():
    tree = parse(r"\begin{document}Fran\c{c}ois \v{S}koda, Erd\H{o}s, \ss{} \o\ \textgreater\end{document}")
    assert texts(tree["body"]) == "François Škoda, Erdős, ß ø >"
    assert not tree["diagnostics"]


def test_bare_tikzcd_and_math_env():
    tree = parse(r"""\begin{document}
\begin{tikzcd} A \arrow[r] & B \end{tikzcd}
and \begin{math}x^2\end{math} here
\end{document}""")
    k = kinds(tree)
    assert k["displaymath"] == 1 and k["math"] >= 1
    assert "undefined-command" not in diag_codes(tree)


def test_compat_layout_envs_are_quiet():
    tree = parse(r"\begin{document}\begin{multicols}{2}text\end{multicols}\end{document}")
    assert not tree["diagnostics"] and texts(tree["body"]) == "text"


def test_dollar_inside_braces_is_nested_math():
    tree = parse(r"\begin{document}A $x \mathbin{\raisebox{1ex}{$\cdot$}} y$ and $\text{a $b$ c}$ B\end{document}")
    maths = [n for n in walk(tree["body"]) if n.get("kind") == "math"]
    assert len(maths) == 2 and "raisebox" in maths[0]["math"]["tex"]
    assert not tree["diagnostics"]


def test_unbalanced_brace_in_math_falls_back_to_first_dollar():
    tree = parse(r"\begin{document}a $\frac{1}{$ b $x$ c\end{document}")
    errs = [n for n in walk(tree["body"]) if n.get("kind") == "error"]
    assert [e["raw"] for e in errs] == [r"$\frac{1}{$"]


def test_quote_ligatures_in_compat():
    tree = parse(r"\begin{document}``big'' and `x' don't\end{document}")
    assert texts(tree["body"]) == "“big” and ‘x' don't"


def test_tex_conditionals_empty_arg_idiom():
    src = (r"\def\opt#1{\if\relax\detokenize{#1}\relax E\else N(#1)\fi}"
           r"\opt{}\opt{ab}\iftrue T\else F\fi\iffalse T\else F\fi"
           r"\def\a{x}\def\b{x}\ifx\a\b S\else D\fi\ifdefined\a Y\fi\ifdefined\zz Y\else Z\fi")
    out, sink = run(src)
    assert flat(out).replace(" ", "") == "EN(ab)TFSYZ" and not sink.items
