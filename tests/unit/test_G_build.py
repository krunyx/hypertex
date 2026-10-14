"""G: htex build (htex/web/build.py), 조각 렌더러(htex/web/fragment.py), interact.js 정적 검사."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from htex.parser import parse_file
from htex.web import INTERACT_JS_PATH, render_fragment
from htex.web.build import build, make_doc_url

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "tests" / "docs"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("g-build")
    src = base / "src"
    shutil.copytree(DOCS, src)
    (src / "sub").mkdir()
    (src / "sub" / "child.htex").write_text(
        "\\documentclass{hypertex}\n\\title{하위}\n\\begin{document}\n"
        "식 \\ref{../11-internal-refs.htex#eq:H}, 그림 \\includegraphics{pic.png}\n\\end{document}\n",
        encoding="utf-8")
    (src / "sub" / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (src / ".hidden").write_text("x", encoding="utf-8")
    (base / "secret.txt").write_text("밖", encoding="utf-8")
    try:
        os.symlink(base / "secret.txt", src / "link-out.txt")
    except OSError:
        pass
    out = base / "out"
    rep = build(src, out)
    return src, out, rep


def test_file_list(built):
    src, out, rep = built
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    docs = sorted(p.relative_to(src).as_posix() for p in src.rglob("*")
                  if p.suffix in (".htex", ".tex") and not p.name.startswith("."))
    for d in docs:
        assert d.rsplit(".", 1)[0] + ".html" in files, d
    assert "physics-notes.hsty" in files
    assert "sub/pic.png" in files
    assert "_htex/interact.js" in files
    assert "index.html" in files and "sub/index.html" in files
    assert ".hidden" not in files and "link-out.txt" not in files
    assert not any(f.endswith((".htex", ".tex")) for f in files)
    assert rep.errors == []
    assert set(rep.files) == set(files)


def test_links_converted(built):
    _, out, _ = built
    html = (out / "12-cross-doc-refs.html").read_text(encoding="utf-8")
    assert 'href="11-internal-refs.html#eq:H"' in html
    assert 'href="11-internal-refs.html#sec:eigen"' in html
    # 절대 주소는 웹 폴백 https:// 그대로 (.htex 확장자 유지: 다른 서버의 문서)
    assert 'href="https://example.org/notes/oscillator.htex#eq:aadag"' in html
    assert 'data-doc="11-internal-refs.htex"' in html       # 원래 주소 정보는 남는다
    html = (out / "14-transclusion.html").read_text(encoding="utf-8")
    assert 'href="08-theorems.html#thm:lagrange"' in html
    html = (out / "sub" / "child.html").read_text(encoding="utf-8")
    assert 'href="../11-internal-refs.html#eq:H"' in html
    assert 'src="pic.png"' in html


def test_script_and_no_endpoints(built):
    _, out, _ = built
    html = (out / "25-parameters.html").read_text(encoding="utf-8")
    assert '<script src="_htex/interact.js" defer></script>' in html
    assert "htex-picture-endpoint" not in html
    assert "htex-fragment-endpoint" not in html
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "object-src &#x27;none&#x27;" in html or "object-src 'none'" in html
    sub = (out / "sub" / "child.html").read_text(encoding="utf-8")
    assert '<script src="../_htex/interact.js" defer></script>' in sub
    assert (out / "_htex" / "interact.js").read_bytes() == INTERACT_JS_PATH.read_bytes()


def test_index_listing(built):
    _, out, _ = built
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="11-internal-refs.html"' in idx and "문서 안 참조" in idx
    assert 'href="sub/index.html"' in idx
    assert 'href="physics-notes.hsty"' in idx
    sub = (out / "sub" / "index.html").read_text(encoding="utf-8")
    assert 'href="child.html"' in sub and 'href="../index.html"' in sub


def test_index_htex_becomes_index_html(tmp_path):
    src = tmp_path / "s"
    src.mkdir()
    (src / "index.htex").write_text("\\title{첫 화면}\n본문.\n", encoding="utf-8")
    rep = build(src, tmp_path / "o")
    assert "첫 화면" in (tmp_path / "o" / "index.html").read_text(encoding="utf-8")
    assert rep.listings == []


def test_name_collision(tmp_path):
    src = tmp_path / "s"
    src.mkdir()
    (src / "a.htex").write_text("\\title{가}\n", encoding="utf-8")
    (src / "a.tex").write_text("\\title{나}\n", encoding="utf-8")
    rep = build(src, tmp_path / "o")
    assert "가" in (tmp_path / "o" / "a.html").read_text(encoding="utf-8")
    assert "나" in (tmp_path / "o" / "a.tex.html").read_text(encoding="utf-8")
    assert rep.warnings


def test_output_inside_source_is_skipped(tmp_path):
    src = tmp_path / "s"
    src.mkdir()
    (src / "a.htex").write_text("\\title{가}\n", encoding="utf-8")
    build(src, src / "site")
    rep = build(src, src / "site")   # 두 번째: 이전 결과를 다시 복사하지 않는다
    assert not any(f.startswith("site/") for f in rep.files)


def test_same_dir_rejected(tmp_path):
    with pytest.raises(ValueError):
        build(tmp_path, tmp_path)


def test_doc_url_mapping():
    f = make_doc_url("a", {"a/x.htex": "a/x.html", "b/y.tex": "b/y.html"})
    assert f("x.htex#l") == "x.html#l"
    assert f("../b/y.tex") == "../b/y.html"
    assert f("https://e.org/z.htex#l") == "https://e.org/z.htex#l"
    assert f("#l") == "#l"
    assert f("pic.png") == "pic.png"
    assert f("missing.htex#q") == "missing.html#q"


def test_cli_build(tmp_path):
    out = tmp_path / "site"
    r = subprocess.run([sys.executable, "-m", "htex", "build", str(DOCS), "-o", str(out)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (out / "index.html").is_file() and (out / "oscillator.html").exists() is False
    assert (out / "25-parameters.html").is_file()


# ---------------------------------------------------------------- 조각
def test_fragment_kinds():
    t = parse_file(DOCS / "11-internal-refs.htex")
    eq = render_fragment(t, "eq:H")
    assert eq and "H = \\frac" in eq and "E_n" not in eq and "htex-eqrow" in eq
    sec = render_fragment(t, "sec:energy")
    assert "에너지" in sec and "htex-fragment-more" in sec and "이다." not in sec   # 세 블록 중 두 개만
    assert render_fragment(t, "nope") is None
    t = parse_file(DOCS / "24-interaction.htex")
    step = render_fragment(t, "step:last")
    assert step.count("<li") == 1 and "2S" in step
    t = parse_file(DOCS / "05-lists.htex")
    item = render_fragment(t, "item:first")
    assert "첫째" in item and "둘째" not in item


def test_fragment_rebase():
    t = parse_file(DOCS / "11-internal-refs.htex")
    sec = render_fragment(t, "sec:eigen", doc_href="/docs/11-internal-refs.htex")
    assert 'href="/docs/11-internal-refs.htex#eq:H"' in sec
    assert 'href="#' not in sec


def test_fragment_section_truncated():
    t = parse_file(ROOT / "examples" / "oscillator.htex")
    sec = render_fragment(t, "sec:E")
    assert sec is not None and "htex-fragment-more" in sec


def test_fragment_every_label_in_test_docs():
    for p in sorted(DOCS.glob("*.htex")):
        t = parse_file(p)
        for lab in (t.get("labels") or {}):
            frag = render_fragment(t, lab, doc_href="/" + p.name)
            assert frag and frag.startswith('<div class="htex-fragment"'), (p.name, lab)
            assert "<script" not in frag


# ---------------------------------------------------------------- interact.js 정적 검사
JS = INTERACT_JS_PATH.read_text(encoding="utf-8")


def test_js_contract_markers():
    for needle in ("htex-picture-endpoint", "htex-fragment-endpoint", "aside.htex-parameters",
                   'type = "range"', "data-params", "aria-label", "prefers-reduced-motion",
                   "Escape", "DEBOUNCE_MS = 150", "--bg", "--fg", "--rule"):
        assert needle in JS, needle


def test_js_no_external_or_eval():
    assert not re.search(r"\beval\s*\(|new Function|innerHTML\s*=|document\.write|https?://(?!www\.w3\.org)", JS)
    assert "import " not in JS and "require(" not in JS


def test_js_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    r = subprocess.run([node, "--check", str(INTERACT_JS_PATH)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
