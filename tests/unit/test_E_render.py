"""E: 문서 트리 → HTML 변환 테스트 (htex/html/render.py).

- tests/trees/*.tree.json 전부 + 스키마의 모든 블록·인라인 kind를 담은 합성 트리를 렌더해서
  예외 없음, 태그 짝, 모든 노드 id 존재를 확인한다.
- 합성 트리는 스키마 검증(tools/check.py check_schema)을 통과해야 한다.
- 렌더 결과는 확인용으로 /tmp/htex-E/ 에 저장한다 (저장소에는 넣지 않음).
"""
from __future__ import annotations

import copy
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from htex.html import render
from htex.html.render import safe_url, split_top_level_amp

ROOT = Path(__file__).resolve().parents[2]
TREES = sorted((ROOT / "tests" / "trees").glob("*.tree.json"))
OUT_DIR = Path("/tmp/htex-E")

sys.path.insert(0, str(ROOT / "tools"))
import check  # noqa: E402

SCHEMA = json.loads((ROOT / "schema" / "document-tree.schema.json").read_text(encoding="utf-8"))


# ====================================================================== 도우미
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
        "track", "wbr", "mspace"}


class TagChecker(HTMLParser):
    """태그 짝 검사 + id 수집."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []
        self.ids: list[str] = []
        self.tags: list[tuple[str, dict]] = []
        self.data: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if "id" in a:
            self.ids.append(a["id"])
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if "id" in a:
            self.ids.append(a["id"])

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"짝 없는 </{tag}> (줄 {self.getpos()[0]})")
            return
        top, line = self.stack.pop()
        if top != tag:
            self.errors.append(f"<{top}> (줄 {line}) 를 </{tag}> 로 닫음 (줄 {self.getpos()[0]})")

    def handle_data(self, data):
        self.data.append(data)


def parse_html(s: str) -> TagChecker:
    p = TagChecker()
    p.feed(s)
    p.close()
    for tag, line in p.stack:
        p.errors.append(f"닫히지 않은 <{tag}> (줄 {line})")
    return p


def all_node_ids(tree) -> list[str]:
    return [n["id"] for n in check.body_nodes(tree) if "id" in n]


def footnote_ids(tree) -> list[str]:
    return [n["id"] for n in check.body_nodes(tree) if n.get("kind") == "footnote"]


def assert_good_html(tree, name: str) -> tuple[str, TagChecker]:
    out = render(tree)
    assert out.startswith("<!doctype html>")
    assert out.rstrip().endswith("</html>")
    p = parse_html(out)
    assert not p.errors, p.errors[:10]
    ids = set(p.ids)
    missing = [i for i in all_node_ids(tree) if i not in ids]
    assert not missing, f"HTML에 없는 노드 id: {missing}"
    dup = {i for i in p.ids if p.ids.count(i) > 1}
    assert not dup, f"중복 id: {dup}"
    # 같은 문서 링크(#…)는 모두 존재하는 id 를 가리킨다
    for tag, a in p.tags:
        href = a.get("href")
        if tag == "a" and href and href.startswith("#"):
            assert href[1:] in ids, f"없는 앵커로 가는 링크 {href}"
    # 라벨 앵커가 모두 있다 (라벨이 노드 id 와 같은 경우는 노드 id 자체가 앵커)
    for label in tree["labels"]:
        assert label in ids, f"라벨 앵커 {label} 없음"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.html").write_text(out, encoding="utf-8")
    return out, p


# ====================================================================== 합성 트리
def T(s):
    return {"kind": "text", "text": s}


def M(tex, scripts=None, **kw):
    m = {"tex": tex}
    if scripts:
        m["scripts"] = scripts
    m.update(kw)
    return {"kind": "math", "math": m}


def P(i, *content):
    return {"kind": "paragraph", "id": i, "content": list(content)}


def synthetic_tree() -> dict:
    """스키마의 블록 17종·인라인 9종을 모두 담은 트리 (id 는 문서 순서대로)."""
    return {
        "hypertex": "2.0",
        "source": {"url": "htex://example.org/synthetic.htex", "mode": "native"},
        "meta": {
            "documentclass": "hypertex",
            "classOptions": ["note"],
            "title": [T("합성 문서 "), M("E=mc^2", ["latin"]), T(" <script>alert(1)</script>")],
            "authors": [[T("홍길동")], [T("Ada "), {"kind": "styled", "style": "smallcaps",
                                                   "children": [T("Lovelace")]}]],
            "date": "2026-10-14",
            "keywords": ["하이퍼텍", "수식", "a<b"],
            "abstract": [P("n100", T("요약 단락. "), M(r"\alpha", ["greek"]))],
            "styles": ["physics-notes.hsty"],
            "macroImports": ["htex://example.org/macros.htex"],
            "mathExtensions": ["hangulmath"],
            "tikzLibraries": ["arrows.meta"],
        },
        "labels": {
            "sec:intro": {"node": "n1", "kind": "section", "number": "1", "display": "1절"},
            "eq:H": {"node": "n4", "kind": "equation", "number": "1", "display": "식 (1)"},
            "eq:sq": {"node": "n6", "kind": "equation", "number": "2", "display": "식 (2)"},
            "thm:main": {"node": "n12", "kind": "theorem", "number": "1", "display": "정리 1"},
            "item:b": {"node": "n17", "kind": "item", "number": "2"},
            "fig:pic": {"node": "n32", "kind": "figure", "number": "1", "display": "그림 1"},
            "tab:t": {"node": "n34", "kind": "table", "number": "1", "display": "표 1"},
            "step:last": {"node": "n29", "kind": "step", "number": "2"},
            "fn:one": {"node": "n9", "kind": "footnote", "number": "1"},
            "n2": {"node": "n2", "kind": "section", "number": "1.1"},
        },
        "parameters": [
            {"name": "omega", "min": 0.5, "max": 3, "default": 1, "step": 0.1},
            {"name": "gamma", "min": 0, "max": 1, "default": 0.2},
        ],
        "bibliography": [
            {"key": "epr1935", "number": "1",
             "text": [T("A. Einstein et al., Phys. Rev. 47, 777 (1935).")],
             "identifier": {"scheme": "doi", "value": "10.1103/PhysRev.47.777"}},
            {"key": "bell1964", "number": "2", "text": [T("J. S. Bell, Physics 1, 195 (1964).")],
             "identifier": {"scheme": "arXiv", "value": "quant-ph/0000000"}},
            {"key": "isbnbook", "number": "3", "text": [T("어떤 책")],
             "identifier": {"scheme": "isbn", "value": "9780198520115"}},
        ],
        "body": [
            {"kind": "section", "id": "n1", "level": 1, "number": "1", "label": "sec:intro",
             "title": [T("서론 "), {"kind": "styled", "style": "emph", "children": [T("강조")]}],
             "children": [
                 {"kind": "section", "id": "n2", "level": 2, "number": "1.1",
                  "title": [T("절 id와 같은 라벨")],
                  "children": [
                      {"kind": "displaymath", "id": "n3", "env": "equation", "rows": [
                          {"id": "n4", "number": "1", "label": "eq:H",
                           "math": {"tex": r"H = \frac{p^2}{2m} + \frac{1}{2} m\omega^2 x^2",
                                    "scripts": ["latin", "greek"]}}]},
                      {"kind": "displaymath", "id": "n5", "env": "align", "rows": [
                          {"id": "n6", "number": "2", "label": "eq:sq",
                           "math": {"tex": r"(a+b)^2 &= a^2 + 2ab + b^2", "scripts": ["latin"]}},
                          {"id": "n7", "math": {"tex": r"x &= 1 & y &= 2", "scripts": ["latin"]}},
                      ]},
                  ]},
                 P("n8",
                   T("본문 <b>escape</b> & 각주"),
                   {"kind": "footnote", "id": "n9", "number": "1",
                    "children": [P("n10", T("각주 내용 "), M("x^2", ["latin"]))]},
                   T(", 굵게 "), {"kind": "styled", "style": "bold", "children": [T("굵게")]},
                   T(", "), {"kind": "styled", "style": "italic", "children": [T("기울임")]},
                   T(", "), {"kind": "styled", "style": "mono", "children": [T("고정폭")]},
                   {"kind": "linebreak"},
                   T("코드 "), {"kind": "code", "text": r"\begin{document}<x>"},
                   T(", 매개변수 "), {"kind": "showparam", "name": "omega"},
                   T(", 오류 "), {"kind": "error", "code": "undefined-command", "raw": r"\foo",
                                 "children": [T("인수")]},
                   T(", 수식 오류 "), {"kind": "error", "code": "math-syntax",
                                     "raw": r"$\frac{1}{$"},
                   ),
                 P("n11",
                   T("참조 "),
                   {"kind": "link", "linkType": "ref", "target": {"label": "sec:intro"},
                    "resolved": {"number": "1", "node": "n1"}},
                   T(", 식 "),
                   {"kind": "link", "linkType": "eqref", "target": {"label": "eq:H"},
                    "resolved": {"number": "1", "node": "n4"}},
                   T(", 노드 id 라벨 "),
                   {"kind": "link", "linkType": "ref", "target": {"label": "n2"},
                    "resolved": {"number": "1.1", "node": "n2"}},
                   T(", 깨진 "),
                   {"kind": "link", "linkType": "ref", "target": {"label": "eq:missing"},
                    "resolved": {"broken": True}},
                   T(", 깨진 eqref "),
                   {"kind": "link", "linkType": "eqref", "target": {"label": "eq:none"},
                    "resolved": {"broken": True}},
                   T(", 다른 문서 "),
                   {"kind": "link", "linkType": "ref",
                    "target": {"doc": "htex://example.org/notes/oscillator.htex", "label": "eq:H"}},
                   T(", 상대 문서 "),
                   {"kind": "link", "linkType": "eqref",
                    "target": {"doc": "notation.htex", "label": "eq:x"}},
                   T(", href "),
                   {"kind": "link", "linkType": "href", "target": {"url": "https://example.org/?a=1&b=2"},
                    "children": [T("예시")]},
                   T(", url "),
                   {"kind": "link", "linkType": "url", "target": {"url": "https://example.org/x"}},
                   T(", 인용 "),
                   {"kind": "link", "linkType": "cite", "target": {"keys": ["epr1935", "bell1964"]},
                    "resolved": {"numbers": ["1", "2"]}},
                   T(" "),
                   {"kind": "link", "linkType": "cite", "target": {"keys": ["arXiv:2401.01234"]}},
                   T(" "),
                   {"kind": "link", "linkType": "cite", "target": {"keys": ["doi:10.1103/PhysRev.47.777"]}},
                   T(" "),
                   {"kind": "link", "linkType": "cite", "target": {"keys": ["isbn:9780198520115"]}},
                   T(" "),
                   {"kind": "link", "linkType": "cite",
                    "target": {"keys": ["htex://example.org/notes/oscillator.htex"]}},
                   T(" 없는 키 "),
                   {"kind": "link", "linkType": "cite", "target": {"keys": ["nobody2000"]},
                    "resolved": {"broken": True}},
                   ),
             ]},
            {"kind": "theorem", "id": "n12", "env": "theorem", "name": "정리", "number": "1",
             "label": "thm:main", "note": [T("라그랑주")],
             "children": [P("n13", M(r"\sum_{k=1}^n k = \frac{n(n+1)}{2}", ["latin"]), T("."))]},
            {"kind": "proof", "id": "n14", "collapsed": False, "children": [P("n15", T("자명하다."))]},
            {"kind": "list", "id": "n16", "style": "enumerate", "items": [
                {"id": "n17", "number": "1", "children": [P("n18", T("첫째"))]},
                {"id": "n19", "number": "2", "label": "item:b", "children": [P("n20", T("둘째"))]},
            ]},
            {"kind": "list", "id": "n21", "style": "itemize", "items": [
                {"id": "n22", "children": [P("n23", T("점"))]}]},
            {"kind": "list", "id": "n24", "style": "description", "items": [
                {"id": "n25", "term": [T("용어")], "children": [P("n26", T("설명"))]}]},
            {"kind": "steps", "id": "n27", "steps": [
                {"id": "n28", "children": [P("n30", M(r"\displaystyle S = 1 + \cdots + n", ["latin"]))]},
                {"id": "n29", "label": "step:last", "children": []},
            ]},
            {"kind": "float", "id": "n31", "floatType": "figure", "number": "1", "label": "fig:pic",
             "caption": [T("그림 설명")],
             "children": [
                 {"kind": "picture", "id": "n32", "source": r"\draw (0,0) -- (1,1) node {$<x>$};",
                  "params": ["omega"]},
                 {"kind": "image", "id": "n33", "src": "https://example.org/a.svg", "width": "60%",
                  "alt": "\"인용\" <img>"},
             ]},
            {"kind": "float", "id": "n34", "floatType": "table", "number": "1", "label": "tab:t",
             "caption": [T("표 설명")],
             "children": [
                 {"kind": "tabular", "id": "n35",
                  "columns": [{"align": "l", "ruleLeft": True}, {"align": "c", "ruleLeft": True},
                              {"align": "r", "ruleLeft": True, "ruleRight": True}],
                  "rows": [
                      {"ruleAbove": True, "cells": [{"content": [T("a")]}, {"content": [T("b")]},
                                                    {"content": [M("c^2")]}]},
                      {"ruleAbove": True, "ruleBelow": True,
                       "cells": [{"colspan": 2, "align": "c", "content": [T("병합")]},
                                 {"content": []}]},
                  ]},
             ]},
            {"kind": "quote", "id": "n36", "children": [P("n37", T("인용문"))]},
            {"kind": "verbatim", "id": "n38", "text": "<script>alert('x')</script>\n  들여쓰기"},
            {"kind": "proof", "id": "n39", "collapsed": True, "title": [T("증명 스케치")],
             "children": [P("n40", T("접힌 증명"))]},
            {"kind": "collapse", "id": "n41", "title": [T("참고: 가우스")],
             "children": [P("n42", T("접힌 내용"))]},
            {"kind": "transclusion", "id": "n43", "href": "htex://example.org/notes/oscillator.htex#eq:H"},
            {"kind": "error", "id": "n44", "code": "unclosed-environment",
             "raw": "\\begin{itemize}\n<b>"},
            {"kind": "displaymath", "id": "n45", "env": "gather*", "rows": [
                {"id": "n46", "math": {"tex": r"가(x) = \sum_{나=1}^{다} 나 \, x^나",
                                       "scripts": ["latin", "hangul"]}},
                {"id": "n47", "math": {"tex": r"\frac{1}{", "scripts": ["latin"]}},
            ]},
            {"kind": "displaymath", "id": "n48", "env": "multline", "rows": [
                {"id": "n49", "number": "3",
                 "math": {"tex": r"f(x) = a_0 + a_1 x \\ + a_4 x^4", "scripts": ["latin"]}}]},
            {"kind": "displaymath", "id": "n50", "env": "displaymath", "rows": [
                {"id": "n51", "math": {"tex": r"\omega = \showparam{\omega}", "scripts": ["greek"],
                                       "params": ["omega"]}}]},
            {"kind": "section", "id": "n52", "level": 1, "number": "A", "appendix": True,
             "title": [T("부록")], "children": [
                 {"kind": "section", "id": "n53", "level": 4, "title": [T("문단 제목")],
                  "children": [P("n54", T("이어지는 글"))]},
                 {"kind": "bibliography", "id": "n55", "title": [T("참고문헌")]},
             ]},
        ],
        "diagnostics": [
            {"severity": "warning", "code": "broken-ref", "message": "라벨 eq:missing <없음>",
             "span": {"line": 3, "col": 7}},
            {"severity": "error", "code": "unclosed-environment", "message": "itemize", "node": "n44"},
        ],
    }


# ====================================================================== 테스트
def test_synthetic_tree_passes_schema_and_consistency():
    tree = synthetic_tree()
    rep = check.Report("synthetic")
    check.check_schema(tree, rep)
    check.check_consistency(tree, rep)
    assert rep.ok, rep.errors


def test_synthetic_tree_covers_every_kind():
    defs = SCHEMA["$defs"]
    block_kinds = {defs[r["$ref"].split("/")[-1]]["properties"]["kind"]["const"]
                   for r in defs["Block"]["oneOf"]}
    inline_kinds = {defs[r["$ref"].split("/")[-1]]["properties"]["kind"]["const"]
                    for r in defs["Inline"]["oneOf"]}
    tree = synthetic_tree()
    seen = {n.get("kind") for n in check.body_nodes(tree)}
    for e in tree["meta"].get("title", []):
        seen.add(e["kind"])
    assert block_kinds <= seen, block_kinds - seen
    assert inline_kinds <= seen, inline_kinds - seen
    assert len(block_kinds) == 17 and len(inline_kinds) == 9
    link_types = {n["linkType"] for n in check.body_nodes(tree) if n.get("kind") == "link"}
    assert link_types == {"ref", "eqref", "href", "url", "cite"}


def test_render_synthetic_tree():
    out, p = assert_good_html(synthetic_tree(), "synthetic")
    assert "<math" in out


@pytest.mark.parametrize("path", TREES, ids=[p.name for p in TREES])
def test_render_reference_trees(path):
    tree = json.loads(path.read_text(encoding="utf-8"))
    out, p = assert_good_html(tree, path.name.replace(".tree.json", ""))
    for tag, a in p.tags:
        for key in ("href", "src"):
            if a.get(key) is not None:
                assert safe_url(a[key]) == a[key], (tag, key, a[key])
    # 실제 트리의 수식은 모두 MathML 로 변환되어야 한다 (수식 구문 오류는 이미 error 노드).
    # 예외: 16번은 수식 안의 정의되지 않은 명령을 math 노드로 남기고 렌더러가 원문으로 보여 준다 (통합 단계 결정).
    body = out.split("<style>")[0] + out.split("</style>")[1]
    if path.name.startswith("16-"):
        assert body.count("htex-math-error") == 2
    else:
        assert "htex-math-error" not in body


# ---------------------------------------------------------------- 세부 동작
@pytest.fixture(scope="module")
def html_out() -> str:
    return render(synthetic_tree())


def test_escape_everywhere(html_out):
    assert "<script>" not in html_out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out
    assert "<b>escape</b>" not in html_out and "&lt;b&gt;escape&lt;/b&gt;" in html_out
    assert 'alt="&quot;인용&quot; &lt;img&gt;"' in html_out
    # 진단 메시지도 escape
    assert "&lt;없음&gt;" in html_out


def test_doc_structure(html_out):
    assert '<html lang="ko">' in html_out
    assert html_out.count("<style>") == 1
    assert "<link" not in html_out and "<script" not in html_out  # 외부 자원·스크립트 없음
    assert '<section class="htex-section htex-level-1" id="n1">' in html_out
    assert '<h3 class="htex-heading">' in html_out


def test_equation_number_on_right(html_out):
    assert '<td class="htex-eqno">(1)</td>' in html_out
    assert re.search(r'<tr class="htex-eqrow" id="n4"[^>]*>.*?<span class="htex-anchor" id="eq:H">',
                     html_out)


def test_align_rows_split_into_cells(html_out):
    row = re.search(r'<tr class="htex-eqrow" id="n7".*?</tr>', html_out).group(0)
    assert row.count("<math") == 4  # x | = 1 | y | = 2
    # 각 셀의 annotation 은 & 로 나눈 원본 조각
    assert '<annotation encoding="application/x-tex">= 1</annotation>' in row
    row6 = re.search(r'<tr class="htex-eqrow" id="n6".*?</tr>', html_out).group(0)
    assert 'data-tex="(a+b)^2 &amp;= a^2 + 2ab + b^2"' in row6


def test_theorem_heading(html_out):
    assert ('<strong class="htex-thm-name">정리 <span class="htex-thm-num">1</span></strong> '
            '<span class="htex-thm-note">(라그랑주)</span>.') in html_out


def test_refs(html_out):
    assert '<a class="htex-ref" href="#sec:intro" title="1절">1</a>' in html_out
    assert '<a class="htex-ref" href="#eq:H" title="식 (1)">(1)</a>' in html_out
    # 라벨이 다른 노드 id 와 같으면 노드 id 로
    assert '<a class="htex-ref" href="#n2">1.1</a>' in html_out
    assert re.search(r'<span class="htex-ref htex-broken" title="[^"]*eq:missing[^"]*">\?\?</span>',
                     html_out)
    assert ">(??)</span>" in html_out
    assert 'href="htex://example.org/notes/oscillator.htex#eq:H"' in html_out
    assert 'href="notation.htex#eq:x"' in html_out


def test_web_fallback_rewrites_htex():
    out = render(synthetic_tree(), web_fallback=True)
    assert not re.search(r'\shref="htex://', out)
    assert 'href="https://example.org/notes/oscillator.htex#eq:H"' in out


def test_links_and_cites(html_out):
    assert 'href="https://example.org/?a=1&amp;b=2">예시</a>' in html_out
    assert '<span class="htex-tt">https://example.org/x</span></a>' in html_out
    assert re.search(r'\[<a href="#bib~epr1935" title="epr1935">1</a>, '
                     r'<a href="#bib~bell1964" title="bell1964">2</a>\]', html_out)
    assert 'href="https://arxiv.org/abs/2401.01234">arXiv:2401.01234</a>' in html_out
    assert 'href="https://doi.org/10.1103/PhysRev.47.777">doi:10.1103/PhysRev.47.777</a>' in html_out
    assert '<span class="htex-cite-ext">isbn:9780198520115</span>' in html_out
    assert re.search(r'\[<span class="htex-broken"[^>]*>\?\?</span>\]', html_out)


def test_bibliography(html_out):
    assert html_out.count('class="htex-bibliography"') == 1
    assert '<section class="htex-bibliography" id="n55">' in html_out
    assert '<li id="bib~epr1935" data-key="epr1935"><span class="htex-bibnum">[1]</span>' in html_out
    assert 'href="https://doi.org/10.1103/PhysRev.47.777">doi:10.1103/PhysRev.47.777</a>' in html_out


def test_footnotes_cross_linked(html_out):
    assert '<a id="n9" href="#fn~n9" role="doc-noteref">1</a>' in html_out
    assert '<li id="fn~n9">' in html_out
    assert 'href="#n9" role="doc-backlink"' in html_out


def test_interaction(html_out):
    assert re.search(r'<details class="htex-proof htex-collapsed" id="n39"><summary>', html_out)
    assert '<details class="htex-collapse" id="n41"><summary>참고: 가우스</summary>' in html_out
    assert '<ol class="htex-steps" id="n27" data-steps="2">' in html_out
    assert 'class="htex-step htex-step-2" id="n29"' in html_out
    assert '<output class="htex-param" data-param="omega">1</output>' in html_out
    assert '<mn class="htex-param" data-param="omega">1</mn>' in html_out
    assert "<script" not in html_out


def test_picture_placeholder(html_out):
    assert re.search(r'<figure class="htex-picture" id="n32"[^>]*><pre>\\draw \(0,0\) -- \(1,1\) '
                     r'node \{\$&lt;x&gt;\$\};</pre></figure>', html_out)


def test_errors_and_diagnostics(html_out):
    assert '<pre class="htex-error" id="n44" data-code="unclosed-environment"' in html_out
    assert '<code class="htex-error" data-code="undefined-command" title="undefined-command">\\foo</code>' in html_out
    assert '<code class="htex-math-error"' in html_out  # n47 \frac{1}{
    assert '<details class="htex-diagnostics"><summary>진단 2건 (오류 1, 경고 1)</summary>' in html_out
    assert '<a href="#n44">위치로</a>' in html_out


def test_hangul_math(html_out):
    assert '<mi mathvariant="normal" class="htex-hangul">가</mi>' in html_out
    assert "htex-has-hangul" in html_out
    assert "word-break:keep-all" in html_out


def test_float_caption_and_image(html_out):
    assert '<span class="htex-float-name">그림 1</span>: 그림 설명</figcaption>' in html_out
    assert '<span class="htex-float-name">표 1</span>: 표 설명' in html_out
    assert 'src="https://example.org/a.svg"' in html_out and 'style="width:60%"' in html_out


def test_tabular(html_out):
    assert '<td class="htex-c htex-rule-left" colspan="2">병합</td>' in html_out
    assert '<tr class="htex-rule-above htex-rule-below">' in html_out


def test_unsafe_urls_never_in_href():
    tree = synthetic_tree()
    # 스키마를 우회한 입력이 와도 href/src 에 위험한 주소를 넣지 않는다
    bad = ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,x", "http://x.org",
           "file:///etc/passwd", "//evil.org/x", " javascript:alert(1)", "java\tscript:x",
           "vbscript:x", "a:b"]
    para = tree["body"][0]["children"][1]["content"]
    for u in bad:
        para.append({"kind": "link", "linkType": "href", "target": {"url": u}, "children": [T("x")]})
    tree["body"].append({"kind": "image", "id": "n99", "src": "javascript:alert(1)"})
    tree["body"].append({"kind": "transclusion", "id": "n98", "href": "data:x"})
    out = render(tree)
    p = parse_html(out)
    for tag, a in p.tags:
        for key in ("href", "src"):
            v = a.get(key)
            if v is None:
                continue
            assert safe_url(v) == v, (tag, key, v)
            assert not re.match(r"\s*(javascript|data|file|http|vbscript):", v, re.I)
            assert not v.startswith("//")


@pytest.mark.parametrize("url,ok", [
    ("https://a.org", True), ("htex://a.org/x#y", True), ("notes/x.htex#eq:1", True),
    ("#eq:H", True), ("?q=1", True), ("javascript:x", False), ("data:x", False),
    ("http://a.org", False), ("//a.org", False), ("a:b/c", False), ("", False),
    ("https://a.org/\nx", False), ("\\\\server\\x", False),
])
def test_safe_url(url, ok):
    assert (safe_url(url) is not None) == ok


def test_split_top_level_amp():
    assert split_top_level_amp(r"a &= b") == ["a ", "= b"]
    assert split_top_level_amp(r"\begin{pmatrix} a & b \end{pmatrix} &= c") == [
        r"\begin{pmatrix} a & b \end{pmatrix} ", "= c"]
    assert split_top_level_amp(r"{a & b}") == [r"{a & b}"]
    assert split_top_level_amp(r"a \& b") == [r"a \& b"]
    assert split_top_level_amp(r"a { b") is None


def test_minimal_tree_without_optional_fields():
    tree = {"hypertex": "2.0", "meta": {"documentclass": "hypertex"}, "labels": {},
            "parameters": [], "bibliography": [], "body": [], "diagnostics": []}
    out = render(tree)
    assert "<title>HyperTeX 문서</title>" in out
    assert not parse_html(out).errors


def test_render_does_not_mutate_tree():
    tree = synthetic_tree()
    before = copy.deepcopy(tree)
    render(tree)
    assert tree == before
