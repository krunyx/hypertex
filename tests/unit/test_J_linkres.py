"""J: 다른 문서 참조 번호 채우기 (htex.linkres) 와 웹 서버·정적 빌드·뷰어 core 연결."""
from __future__ import annotations

import copy
import re
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from htex.linkres import (cross_doc_targets, load_label_tables, local_doc_for_link,
                          resolve_cross_refs)
from htex.parser import parse_file, parse_text

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "tests" / "docs"


def link(doc, label, lt="ref", **extra):
    return {"kind": "link", "linkType": lt, "target": {"doc": doc, "label": label}, **extra}


def tree_with(*links):
    return {"labels": {}, "body": [{"kind": "paragraph", "id": "n1", "content": list(links)}]}


OTHER = {"labels": {"eq:H": {"node": "n4", "kind": "equation", "number": "1"},
                    "sec:x": {"node": "n1", "kind": "section", "number": "2.3"},
                    "fig:nonum": {"node": "n9", "kind": "figure"}}}


def numbers(tree):
    return [x.get("resolved", {}).get("number") for x in tree["body"][0]["content"]]


# ====================================================================== 순수 함수
def test_fills_numbers_and_keeps_input_untouched():
    t = tree_with(link("b.htex", "eq:H"), link("b.htex", "sec:x", "eqref"),
                  {"kind": "text", "text": "x"})
    before = copy.deepcopy(t)
    calls = []
    out = resolve_cross_refs(t, lambda d: (calls.append(d), OTHER)[1])
    assert numbers(out) == ["1", "2.3", None]
    assert t == before                      # 입력 트리(캐시)는 그대로
    assert calls == ["b.htex"]              # 같은 문서는 한 번만


def test_missing_label_number_or_doc_left_alone():
    t = tree_with(link("b.htex", "eq:none"), link("b.htex", "fig:nonum"), link("c.htex", "eq:H"))
    out = resolve_cross_refs(t, lambda d: OTHER if d == "b.htex" else None)
    assert numbers(out) == [None, None, None]
    assert out is t                          # 바꿀 것이 없으면 그대로


def test_loader_exception_is_silent():
    def bad(d):
        if d == "bad.htex":
            raise RuntimeError("network")
        return OTHER
    t = tree_with(link("bad.htex", "eq:H"), link("ok.htex", "eq:H"))
    assert numbers(resolve_cross_refs(t, bad)) == [None, "1"]


def test_time_budget():
    def slow(d):
        if d == "slow.htex":
            time.sleep(2.0)
        return OTHER
    t = tree_with(link("slow.htex", "eq:H"), link("fast.htex", "eq:H"))
    t0 = time.monotonic()
    out = resolve_cross_refs(t, slow, budget=0.3)
    assert time.monotonic() - t0 < 1.0
    assert numbers(out) == [None, "1"]


def test_max_docs():
    t = tree_with(*[link(f"d{i}.htex", "eq:H") for i in range(25)])
    seen = []
    lock = threading.Lock()

    def ld(d):
        with lock:
            seen.append(d)
        return OTHER
    out = resolve_cross_refs(t, ld)
    assert len(seen) == 20
    assert numbers(out)[:20] == ["1"] * 20 and numbers(out)[20:] == [None] * 5


def test_cycles_are_one_level():
    """A↔B, 자기 자신을 가리켜도 loader 는 문서마다 한 번, 끝난다."""
    a = parse_text(r"\documentclass{hypertex}\begin{document}\section{A}\label{sec:a}"
                   r"\ref{b.htex#sec:b} \ref{a.htex#sec:a}\end{document}", url="a.htex")
    b = parse_text(r"\documentclass{hypertex}\begin{document}\section{B}\section{B2}\label{sec:b}"
                   r"\ref{a.htex#sec:a}\end{document}", url="b.htex")
    calls = []

    def ld(d):
        calls.append(d)
        return {"a.htex": a, "b.htex": b}[d]
    out = resolve_cross_refs(a, ld)
    assert sorted(calls) == ["a.htex", "b.htex"]
    got = {(x["target"]["doc"], x.get("resolved", {}).get("number")) for x in _links(out)}
    assert got == {("b.htex", "2"), ("a.htex", "1")}
    # B 쪽에서 A 를 풀어도 같다 (순환이어도 한 단계)
    assert {x.get("resolved", {}).get("number") for x in _links(resolve_cross_refs(b, ld))} == {"1"}


def _links(tree):
    out, stack = [], [tree["body"]]
    while stack:
        y = stack.pop()
        if isinstance(y, dict):
            if y.get("kind") == "link":
                out.append(y)
            stack.extend(v for v in y.values() if isinstance(v, (dict, list)))
        elif isinstance(y, list):
            stack.extend(y)
    return out


def test_nested_links_and_targets():
    t = {"labels": {}, "body": [{"kind": "theorem", "body": [
        {"kind": "paragraph", "content": [{"kind": "emph", "children": [link("b.htex", "eq:H", "eqref")]}]}]}]}
    assert cross_doc_targets(t) == ["b.htex"]
    out = resolve_cross_refs(t, lambda d: OTHER)
    assert out["body"][0]["body"][0]["content"][0]["children"][0]["resolved"]["number"] == "1"
    assert "resolved" not in t["body"][0]["body"][0]["content"][0]["children"][0]


def test_load_label_tables_ignores_bad_results():
    got = load_label_tables(["a", "b", "c"], lambda d: {"a": OTHER, "b": {"labels": 3}, "c": "x"}[d])
    assert list(got) == ["a"]


def test_local_doc_for_link(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.htex").write_text("x")
    (tmp_path / "sub" / "b.htex").write_text("x")
    (tmp_path / ".hid.htex").write_text("x")
    (tmp_path / "pic.png").write_bytes(b"x")
    doc = tmp_path / "sub" / "b.htex"
    assert local_doc_for_link(tmp_path, doc, "../a.htex") == (tmp_path / "a.htex").resolve()
    assert local_doc_for_link(tmp_path, tmp_path / "a.htex", "sub/b.htex") == doc.resolve()
    for bad in ("../../etc/passwd.htex", "htex://x/a.htex", "https://x/a.htex", "/a.htex",
                "../.hid.htex", "../pic.png", "nothere.htex", "", "..\\a.htex"):
        assert local_doc_for_link(tmp_path, doc, bad) is None, bad


# ====================================================================== 렌더러와 호스트 연결
XREF = re.compile(r'<a class="htex-ref htex-xref"[^>]*data-label="([^"]*)">([^<]*)</a>')


def test_renderer_shows_resolved_number():
    from htex.html import render
    t = parse_file(DOCS / "12-cross-doc-refs.htex")
    out = resolve_cross_refs(t, lambda d: parse_file(DOCS / d) if d == "11-internal-refs.htex" else None)
    got = dict(XREF.findall(render(out)))
    assert got == {"eq:H": "1", "eq:aadag": "(eq:aadag)", "sec:eigen": "2"}


def test_viewer_core_fills_numbers():
    from htex.viewer.core import ViewerCore, Fetcher

    class NoNet:
        requests = []

        def open(self, req, timeout=None):
            self.requests.append(req.full_url)
            raise OSError("no network")
    op = NoNet()
    core = ViewerCore(fetcher=Fetcher(op))
    r = core.respond(core.local_url(DOCS / "12-cross-doc-refs.htex"))
    assert dict(XREF.findall(r.text)) == {"eq:H": "1", "eq:aadag": "(eq:aadag)", "sec:eigen": "2"}
    assert op.requests == []         # 로컬 문서를 열었다고 네트워크에 나가지 않는다


def test_viewer_core_remote_cross_doc():
    from htex.viewer.core import ViewerCore, Fetcher, TreeCache
    from tests.unit.test_F_core import FakeOpener, DOC_A, DOC_B
    op = FakeOpener({"https://ex.org/n/a.htex": DOC_A, "https://ex.org/n/b.htex": DOC_B})
    core = ViewerCore(fetcher=Fetcher(op), cache=TreeCache())
    r = core.respond("htex://ex.org/n/a.htex")
    assert dict(XREF.findall(r.text)) == {"eq:F": "1"}
    # 네트워크 실패는 조용히: 라벨 이름
    op2 = FakeOpener({"https://ex.org/n/a.htex": DOC_A})
    core2 = ViewerCore(fetcher=Fetcher(op2), cache=TreeCache())
    r2 = core2.respond("htex://ex.org/n/a.htex")
    assert r2.status == 200 and dict(XREF.findall(r2.text)) == {"eq:F": "eq:F"}


def test_web_server_numbers():
    from htex.web.server import serve_in_thread
    srv = serve_in_thread(DOCS)
    try:
        with urllib.request.urlopen(srv.url + "12-cross-doc-refs.htex", timeout=10) as resp:
            body = resp.read().decode("utf-8")
    finally:
        srv.shutdown()
        srv.server_close()
    assert dict(XREF.findall(body)) == {"eq:H": "1", "eq:aadag": "(eq:aadag)", "sec:eigen": "2"}


def test_static_build_numbers(tmp_path):
    from htex.web.build import build
    site = tmp_path / "site"
    (site / "sub").mkdir(parents=True)
    (site / "a.htex").write_text(
        "\\documentclass{hypertex}\n\\title{A}\n\\begin{document}\n\\section{가}\\section{나}\\label{sec:n}\n"
        "\\begin{equation}\\label{eq:e} x=1 \\end{equation}\n\\end{document}\n", encoding="utf-8")
    (site / "sub" / "b.htex").write_text(
        "\\documentclass{hypertex}\n\\title{B}\n\\begin{document}\n"
        "\\ref{../a.htex#sec:n}, \\eqref{../a.htex#eq:e}, \\ref{../a.htex#nope}, \\ref{../../x.htex#y}\n"
        "\\end{document}\n", encoding="utf-8")
    out = tmp_path / "out"
    rep = build(site, out)
    assert not rep.errors
    html = (out / "sub" / "b.html").read_text(encoding="utf-8")
    assert XREF.findall(html) == [("sec:n", "2"), ("eq:e", "(1)"), ("nope", "nope"), ("y", "y")]
    assert 'href="../a.html#sec:n"' in html
