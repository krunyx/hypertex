"""트리 빌더(C) 단위 테스트.

B(매크로)·D(그림 검사)가 통과(stub) 구현이어도 돌아가도록, 빌더가 직접 책임지는 것만 본다.
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import check  # noqa: E402
from htex.parser import parse_file, parse_text  # noqa: E402

DOCS = ROOT / "tests" / "docs"
TREES = ROOT / "tests" / "trees"


# ---------------------------------------------------------------- 대조 도우미
def _normalize(x):
    """tree-conventions '대조할 때 무시하는 것'을 지운다."""
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k in ("span", "sha256", "message"):
                continue
            if k in ("tex", "source") and isinstance(v, str):
                v = re.sub(r"\s+", " ", v).strip()
            out[k] = _normalize(v)
        return out
    if isinstance(x, list):
        return [_normalize(v) for v in x]
    return x


def _diag_codes(tree):
    return sorted(d["code"] for d in tree["diagnostics"])


def _strip_diag_detail(tree):
    t = dict(tree)
    t["diagnostics"] = [{"severity": d["severity"], "code": d["code"]} for d in tree["diagnostics"]]
    return _normalize(t)


def parse(src: str, **kw):
    return parse_text(src, url="t.htex", base_dir=DOCS, **kw)


def schema_ok(tree):
    rep = check.Report("t")
    if check.check_schema(tree, rep):
        check.check_consistency(tree, rep)
    return rep.errors


def body_kinds(tree):
    return [n.get("kind") for n in check.body_nodes(tree)]


# ---------------------------------------------------------------- 정답 트리와 대조
@pytest.mark.parametrize("case", ["01-minimal", "11-internal-refs"])
def test_matches_gold_tree(case):
    got = parse_file(DOCS / f"{case}.htex")
    want = json.loads((TREES / f"{case}.tree.json").read_text(encoding="utf-8"))
    assert _strip_diag_detail(got) == _strip_diag_detail(want)


# ---------------------------------------------------------------- 모든 문서: 예외 없음 + 스키마
@pytest.mark.parametrize("path", sorted(DOCS.glob("*.htex")) + sorted(DOCS.glob("*.tex")),
                         ids=lambda p: p.name)
def test_every_doc_builds_schema_valid_tree(path):
    tree = parse_file(path)
    assert schema_ok(tree) == []
    assert "render-timeout" not in _diag_codes(tree)


def test_broken_inputs_never_raise():
    rnd = random.Random(20261014)
    docs = [p.read_text(encoding="utf-8") for p in sorted(DOCS.glob("*.htex"))]
    junk = "{}$\\[]&#^_~%"
    for src in docs:
        for _ in range(15):
            r = rnd.random()
            if r < 0.4:
                v = src[:rnd.randrange(len(src) + 1)]
            elif r < 0.7:
                a = rnd.randrange(len(src))
                v = src[:a] + src[a + rnd.randrange(1, 40):]
            else:
                chars = list(src)
                for _ in range(6):
                    chars.insert(rnd.randrange(len(chars) + 1), rnd.choice(junk))
                v = "".join(chars)
            tree = parse(v)
            assert schema_ok(tree) == [], v
            assert "render-timeout" not in _diag_codes(tree), v


@pytest.mark.parametrize("src", [
    "\\textbf{" * 3000 + "x",
    "\\begin{quote}" * 3000 + "x",
    "\\begin{itemize}\\item " * 2000,
    "{" * 20000,
    "$" + "{" * 5000 + "$",
    "\\footnote{" * 2000,
    "",
    "\\",
    "\\begin{",
    "\\end{document}\\section{x}",
])
def test_pathological_inputs(src):
    # 깊은 중첩 트리는 jsonschema의 oneOf 검사가 깊이에 지수적으로 느려지므로
    # 여기서는 예외 없음과 최상위 모양만 본다. 스키마는 아래 얕은 중첩 시험에서.
    tree = parse(src)
    assert set(tree) >= {"hypertex", "meta", "labels", "parameters", "bibliography", "body", "diagnostics"}
    json.dumps(tree)


@pytest.mark.parametrize("src", [
    "\\textbf{" * 5 + "x",
    "\\begin{quote}" * 5 + "x",
    "\\begin{itemize}\\item " * 5,
    "\\footnote{" * 4 + "x",
    "\\begin{figure}\\caption{" * 3,
])
def test_moderately_nested_inputs_schema(src):
    assert schema_ok(parse(src)) == []


# ---------------------------------------------------------------- 블록 구조
def test_section_nesting_and_appendix():
    t = parse("\\section{a}\\subsection{b}x\\section*{c}\\appendix\\section{d}\\subsection{e}")
    s = t["body"]
    assert [n["kind"] for n in s] == ["section", "section", "section"]
    assert s[0]["number"] == "1" and s[0]["children"][0]["number"] == "1.1"
    assert "number" not in s[1]
    assert s[2]["number"] == "A" and s[2]["appendix"] is True
    assert s[2]["children"][0]["number"] == "A.1"


def test_display_math_splits_paragraph():
    t = parse("앞 \\[ x \\] 뒤")
    assert [n["kind"] for n in t["body"]] == ["paragraph", "displaymath", "paragraph"]
    t = parse("\\[ x \\]")
    assert [n["kind"] for n in t["body"]] == ["displaymath"]


def test_paragraph_whitespace_and_text_merge():
    t = parse("  a   b~c --- d \\\\ e  ")
    assert t["body"][0]["content"] == [
        {"kind": "text", "text": "a b\u00a0c \u2014 d"}, {"kind": "linebreak"}, {"kind": "text", "text": "e"}]


def test_definitions_are_skipped_silently():
    t = parse("\\newcommand{\\R}{\\mathbb{R}}\\renewcommand\\S[1][x]{#1}"
              "\\DeclareMathOperator{\\Tr}{Tr}\\def\\v{\\mathbf}본문")
    assert t["diagnostics"] == []
    assert t["body"][0]["content"] == [{"kind": "text", "text": "본문"}]


# ---------------------------------------------------------------- 수식
def test_align_rows_numbers_labels():
    t = parse("\\begin{align} a &= b \\label{x} \\\\ c &= \\begin{cases} 1 \\\\ 2 \\end{cases} \\nonumber \\\\"
              " e &= f \\end{align}")
    rows = t["body"][0]["rows"]
    assert [r.get("number") for r in rows] == ["1", None, "2"]
    assert rows[0]["math"]["tex"] == "a &= b"
    assert "\\\\" in rows[1]["math"]["tex"]
    assert t["labels"]["x"]["node"] == rows[0]["id"]


def test_trailing_row_separator_makes_no_empty_row():
    t = parse("\\begin{align*} a \\\\ b \\\\ \\end{align*}")
    assert len(t["body"][0]["rows"]) == 2


def test_math_scripts():
    t = parse("$a + \\alpha + 가 + \\text{b}$ $\\sum$")
    ms = [n for n in check.body_nodes(t) if n.get("kind") == "math"]
    assert ms[0]["math"]["scripts"] == ["latin", "greek", "hangul"]
    assert "scripts" not in ms[1]["math"]


def test_math_syntax_error_is_inline_error():
    t = parse("가 $\\frac{1}{$ 나 $x^$ 다 $x$")
    errs = [n for n in t["body"][0]["content"] if n["kind"] == "error"]
    assert [e["raw"] for e in errs] == ["$\\frac{1}{$", "$x^$"]
    assert _diag_codes(t) == ["math-syntax", "math-syntax"]


def test_math_keeps_space_after_control_word():
    t = parse("$\\Psi = \\hat{H}\\Psi$")
    assert t["body"][0]["content"][0]["math"]["tex"] == "\\Psi = \\hat{H}\\Psi"


# ---------------------------------------------------------------- 정리·상호작용
def test_theorem_counter_shared_and_newtheorem():
    t = parse("\\newtheorem{conj}{추측}\\newtheorem*{note}{메모}"
              "\\begin{lemma}a\\end{lemma}\\begin{conj}\\label{c}b\\end{conj}"
              "\\begin{note}c\\end{note}\\begin{proof}[collapsed]d\\end{proof}")
    th = [n for n in t["body"] if n["kind"] == "theorem"]
    assert [(n["name"], n.get("number")) for n in th] == [("보조정리", "1"), ("추측", "2"), ("메모", None)]
    assert t["labels"]["c"] == {"node": th[1]["id"], "kind": "theorem", "number": "2", "display": "추측 2"}
    assert t["body"][-1]["collapsed"] is True


def test_steps_labels_number_by_order():
    t = parse("\\begin{steps}\\step a\\step b\\label{s}\\end{steps}")
    assert t["labels"]["s"]["number"] == "2" and t["labels"]["s"]["kind"] == "step"


# ---------------------------------------------------------------- 그림·표
def test_tabular_rules_and_multicolumn():
    t = parse("\\begin{tabular}{|l|c|r|}\\hline a & b & c \\\\ \\hline "
              "\\multicolumn{2}{|c|}{d} & e \\\\ \\hline \\end{tabular}")
    tab = t["body"][0]
    assert tab["columns"] == [{"align": "l", "ruleLeft": True}, {"align": "c", "ruleLeft": True},
                              {"align": "r", "ruleLeft": True, "ruleRight": True}]
    assert len(tab["rows"]) == 2
    assert tab["rows"][0]["ruleAbove"] and tab["rows"][1]["ruleAbove"] and tab["rows"][1]["ruleBelow"]
    assert tab["rows"][1]["cells"][0]["colspan"] == 2


def test_image_width_and_insecure():
    t = parse("\\includegraphics[width=0.35\\linewidth]{a.png} \\includegraphics{file:///etc/x}")
    kinds = body_kinds(t)
    img = [n for n in check.body_nodes(t) if n.get("kind") == "image"][0]
    assert img["width"] == "35%"
    assert kinds.count("error") == 1 and _diag_codes(t) == ["insecure-resource"]


def test_picture_calls_check_picture():
    t = parse("\\begin{tikzpicture}\n\\begin{axis}\\addplot {x};\\end{axis}\n\\end{tikzpicture}")
    pic = t["body"][0]
    assert pic["kind"] == "picture" and pic["usesPgfplots"] is True
    assert pic["source"].startswith("\\begin{axis}")


# ---------------------------------------------------------------- 링크·참조
def test_refs_cites_and_broken():
    t = parse("\\section{a}\\label{s} \\ref{s} \\ref{d.htex#x} \\ref{nope} \\cite{arXiv:1,k} "
              "\\begin{thebibliography}{9}\\bibitem{k} K. arXiv:2401.1\\end{thebibliography}")
    links = [n for n in check.body_nodes(t) if n.get("kind") == "link"]
    assert links[0]["resolved"] == {"number": "1", "node": t["body"][0]["id"]}
    assert links[1] == {"kind": "link", "linkType": "ref", "target": {"doc": "d.htex", "label": "x"}}
    assert links[2]["resolved"] == {"broken": True}
    assert links[3]["resolved"] == {"numbers": ["1"]}
    assert t["bibliography"][0]["identifier"] == {"scheme": "arXiv", "value": "2401.1"}
    assert _diag_codes(t) == ["broken-ref"]


def test_parameters_and_showparam():
    t = parse("\\parameter{\\k}{0}{2}{1}[step=0.5] $k = \\showparam{\\k}$ \\showparam{\\q}")
    assert t["parameters"] == [{"name": "k", "min": 0, "max": 2, "default": 1, "step": 0.5}]
    kinds = [n["kind"] for n in t["body"][0]["content"]]
    assert "showparam" in kinds and "error" in kinds
    assert _diag_codes(t) == ["unknown-parameter"]


# ---------------------------------------------------------------- 메타·스타일·호환
def test_meta_and_libraries():
    t = parse("\\documentclass[note]{hypertex}\\usetikzlibrary{calc, foo}\\usemath{hangulmath}"
              "\\usestyle{https://x.org/s.hsty}\\usemacros{data:x}\\keywords{a, b ,}")
    m = t["meta"]
    assert m["classOptions"] == ["note"] and m["tikzLibraries"] == ["calc"]
    assert m["mathExtensions"] == ["hangulmath"] and m["styles"] == ["https://x.org/s.hsty"]
    assert "macroImports" not in m and m["keywords"] == ["a", "b"]
    assert _diag_codes(t) == ["unknown-tikz-library"]


def test_style_equation_number():
    t = parse("\\usestyle{physics-notes.hsty}\\section{a}\\begin{equation}x\\end{equation}"
              "\\begin{equation}y\\end{equation}\\section{b}\\begin{equation}z\\end{equation}")
    nums = [r["number"] for n in check.body_nodes(t) if n.get("kind") == "displaymath" for r in n["rows"]]
    assert nums == ["1.1", "1.2", "2.1"]


def test_compat_mode_documentclass_and_abstract():
    t = parse_text("\\documentclass[11pt]{article}\\usepackage{amsmath,foo}"
                   "\\begin{document}\\begin{abstract}요약\\end{abstract}본문\\end{document}",
                   url="x.tex", base_dir=DOCS)
    assert t["meta"]["documentclass"] == "hypertex" and "classOptions" not in t["meta"]
    assert len(t["meta"]["abstract"]) == 1
    assert _diag_codes(t) == ["unknown-package"]


# ---------------------------------------------------------------- 오류 관용
def test_error_tolerance_four_errors():
    t = parse_file(DOCS / "19-error-tolerance.htex")
    assert _diag_codes(t) == sorted(["undefined-command", "unbalanced-brace", "math-syntax",
                                     "unclosed-environment"])
    err = [n for n in check.body_nodes(t) if n.get("kind") == "error"
           and n["code"] == "undefined-command"][0]
    assert err["raw"] == "\\foobar" and err["children"][0]["text"] == "인수는 텍스트로 보인다"
    assert sum(1 for n in check.body_nodes(t) if n.get("kind") == "section") == 5
