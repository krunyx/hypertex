"""M: Markdown → 문서 트리. 스키마·일관성 검사(tools/check.py 의 검사기)를 함께 통과해야 한다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from htex import parse_text
from htex.html import render
from htex.markdown import parse_markdown, slugify

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
check = pytest.importorskip("check")


def problems(tree: dict) -> list:
    """tools/check.py 의 스키마 검사 + 내부 일관성 검사."""
    rep = check.Report("md")
    check.check_schema(tree, rep)
    check.check_consistency(tree, rep)
    return list(rep.errors)


def md(text: str) -> dict:
    t = parse_markdown(text, url="doc.md")
    assert not problems(t), problems(t)
    return t


def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def kinds(t):
    return [n["kind"] for n in walk(t["body"]) if isinstance(n, dict) and "kind" in n]


def plain(nodes):
    out = []
    for n in nodes:
        if n["kind"] == "text":
            out.append(n["text"])
        elif n["kind"] == "code":
            out.append(n["text"])
        elif n.get("children"):
            out.append(plain(n["children"]))
    return "".join(out)


def para(t, i=0):
    return [n for n in walk(t["body"]) if n.get("kind") == "paragraph"][i]["content"]


# ---------------------------------------------------------------- 연결
def test_parse_text_picks_markdown_by_extension():
    t = parse_text("# 제목\n\n본문", url="notes/a.md")
    assert t["source"]["mode"] == "markdown" and plain(t["meta"]["title"]) == "제목"
    assert parse_text("x", url="a.markdown")["source"]["mode"] == "markdown"
    assert parse_text("x", url="a.htex")["source"]["mode"] == "native"


def test_schema_accepts_markdown_trees():
    t = parse_markdown((ROOT / "README.md").read_text(encoding="utf-8"), url="README.md")
    assert not problems(t)
    assert t["source"]["mode"] == "markdown" and t["labels"]


# ---------------------------------------------------------------- 블록
def test_title_and_sections_are_unnumbered_with_anchors():
    t = md("# 문서\n\n## 첫 절\n\n본문\n\n### 안쪽 절\n\n## 첫 절\n")
    assert plain(t["meta"]["title"]) == "문서"
    secs = [n for n in walk(t["body"]) if n.get("kind") == "section"]
    assert [(s["level"], "number" in s, s["label"]) for s in secs] == [
        (1, False, "첫-절"), (2, False, "안쪽-절"), (1, False, "첫-절-1")]
    assert set(t["labels"]) == {"첫-절", "안쪽-절", "첫-절-1"}


def test_two_h1_keep_levels():
    t = md("# A\n\n# B\n")
    assert "title" not in t["meta"] and [s["level"] for s in walk(t["body"]) if s.get("kind") == "section"] == [1, 1]


def test_front_matter():
    t = md("---\ntitle: 메모\nauthor: A and B\ndate: 2026-10-31\ntags: [x, y]\n---\n\n본문\n")
    m = t["meta"]
    assert plain(m["title"]) == "메모" and [plain(a) for a in m["authors"]] == ["A", "B"]
    assert m["date"] == "2026-10-31" and m["keywords"] == ["x", "y"]


def test_lists_nested_tasks_and_numbers():
    t = md("- a\n  - b\n- [x] done\n- [ ] todo\n\n3. c\n4. d\n")
    lists = [n for n in walk(t["body"]) if n.get("kind") == "list"]
    assert [l["style"] for l in lists] == ["itemize", "itemize", "enumerate"]
    texts = [plain(n["content"]) for n in walk(t["body"]) if n.get("kind") == "paragraph"]
    assert "☑ done" in texts and "☐ todo" in texts
    assert [it["number"] for it in lists[2]["items"]] == ["3", "4"]
    t2 = md("1. a\n2. b\n")
    assert all("number" not in it for it in [n for n in walk(t2["body"]) if n.get("kind") == "list"][0]["items"])


def test_code_quote_table_and_alerts():
    t = md("```py\nx = 1\n```\n\n    indented\n\n> 인용\n> 둘째\n\n> [!WARNING]\n> 조심\n\n"
           "| a | b |\n|:--|--:|\n| 1 | `x|y` |\n| 2 \\| 3 | z |\n")
    vb = [n["text"] for n in walk(t["body"]) if n.get("kind") == "verbatim"]
    assert vb == ["x = 1", "indented"]
    tab = [n for n in walk(t["body"]) if n.get("kind") == "tabular"][0]
    assert [c["align"] for c in tab["columns"]] == ["l", "r"] and len(tab["rows"]) == 3
    assert plain(tab["rows"][1]["cells"][1]["content"]) == "x|y"
    assert plain(tab["rows"][2]["cells"][0]["content"]) == "2 | 3"
    quotes = [n for n in walk(t["body"]) if n.get("kind") == "quote"]
    assert plain(quotes[1]["children"][0]["content"]) == "경고"


def test_details_and_admonition_become_collapse_and_quote():
    t = md("<details><summary>증명</summary>\n\n내용\n\n</details>\n\n!!! note \"메모\"\n    본문\n\n??? tip\n    숨김\n")
    cols = [n for n in walk(t["body"]) if n.get("kind") == "collapse"]
    assert [plain(c["title"]) for c in cols] == ["증명", "Tip"]
    assert "quote" in kinds(t)


# ---------------------------------------------------------------- 수식
def test_math_inline_display_and_dollar_amounts():
    t = md("값은 $x^2$ 와 \\(y\\), 가격은 $5 와 $10.\n\n$$\n\\int_0^1 f\n$$\n\n"
           "\\begin{align}\na &= b \\\\\nc &= d \\nonumber\n\\end{align}\n\n```math\nE=mc^2\n```\n")
    maths = [n["math"]["tex"] for n in walk(t["body"]) if n.get("kind") == "math"]
    assert maths == ["x^2", "y"]
    assert "$5 와 $10." in plain(para(t))
    dm = [n for n in walk(t["body"]) if n.get("kind") == "displaymath"]
    assert [d["env"] for d in dm] == ["displaymath", "align", "displaymath"]
    assert [r.get("number") for r in dm[1]["rows"]] == ["1", None]


def test_bad_math_is_reported_not_fatal():
    t = md("a $\\frac{1}{$ b\n")
    assert t["diagnostics"] and t["diagnostics"][0]["code"] == "math-syntax"
    t = md("$$\n\\frac{1\n$$\n")
    assert "error" in kinds(t)


def test_hangul_in_math_marks_script():
    t = md("$가 + 1$")
    assert [n for n in walk(t["body"]) if n.get("kind") == "math"][0]["math"]["scripts"] == ["hangul"]


# ---------------------------------------------------------------- 글 안
def test_emphasis_code_and_escapes():
    t = md("**굵게** *기울임* ***둘*** ~~취소~~ `a*b` snake_case_word \\*별\\*")
    c = para(t)
    styles = [n["style"] for n in walk(c) if n.get("kind") == "styled"]
    assert styles.count("bold") == 2 and styles.count("emph") == 2 and "strike" in styles
    assert "snake_case_word" in plain(c) and "*별*" in plain(c) and "a*b" in plain(c)


def test_links_anchors_refs_autolinks():
    t = md("# T\n\n## 절 하나\n\n[안](#절-하나) [밖](other.md#x) [웹](http://ex.org) [참조][r] "
           "<https://a.org> www.b.org [깨짐](javascript:alert(1)) [메일](mailto:a@b)\n\n[r]: https://r.org\n")
    links = [n for n in walk(para(t)) if n.get("kind") == "link"]
    got = [(l["linkType"], l["target"].get("url") or l["target"].get("label")) for l in links]
    assert got == [("ref", "절-하나"), ("href", "other.md#x"), ("href", "https://ex.org"),
                   ("href", "https://r.org"), ("url", "https://a.org"), ("href", "https://www.b.org")]
    assert any(n.get("kind") == "error" for n in walk(para(t)))       # javascript: 거부
    assert [d["code"] for d in t["diagnostics"]] == ["insecure-resource"]


def test_images_block_inline_and_badges():
    t = md("![그림](fig.png)\n\n글 ![작은](i.svg) 끝\n\n[![배지](b.svg)](https://x.org)\n")
    imgs = [n for n in walk(t["body"]) if n.get("kind") == "image"]
    assert [(i["src"], i.get("alt")) for i in imgs] == [("fig.png", "그림")]
    links = [n for n in walk(t["body"]) if n.get("kind") == "link"]
    assert plain(links[0]["children"]) == "🖼 작은" and plain(links[1]["children"]) == "배지"


def test_footnotes_and_html_bits():
    t = md("본문[^a] 그리고[^없음]<br>다음 줄 <span>태그</span> &amp; &copy;\n\n[^a]: 각주 **굵게**\n")
    fn = [n for n in walk(t["body"]) if n.get("kind") == "footnote"]
    assert len(fn) == 1 and fn[0]["number"] == "1" and plain(fn[0]["children"][0]["content"]) == "각주 굵게"
    text = plain(para(t))
    assert "[^없음]" in text and "태그" in text and "& ©" in text and "<span>" not in text
    assert "linebreak" in kinds(t)
    assert [d["code"] for d in t["diagnostics"]] == ["broken-ref"]


def test_raw_html_never_reaches_output():
    t = md("<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n<iframe src=https://e.com></iframe>")
    page = render(t)
    body = page.split("</style>", 1)[1]
    assert "<script>alert" not in body and "onerror" not in body and "<iframe" not in body


def test_hostile_inputs_finish():
    # 스키마 검사기는 깊은 oneOf 중첩에서 매우 느리므로 여기서는 변환·HTML 만 확인한다
    t = parse_markdown(">" * 5000 + " x\n\n" + "[" * 3000 + "\n\n" + "*" * 5000 + "\n\n" + "- " * 2000 + "y\n")
    assert t["source"]["mode"] == "markdown" and not t["diagnostics"]
    assert "x" in render(t)


def test_slugify_matches_github_style():
    assert slugify("Hello, World! 2.0") == "hello-world-20"
    assert slugify("한글 제목 (설명)") == "한글-제목-설명"


def test_render_markdown_tree_to_html():
    page = render(md("# T\n\n본문 $a$\n\n- x\n"))
    assert "<math" in page and "<li" in page and "<title>T</title>" in page
