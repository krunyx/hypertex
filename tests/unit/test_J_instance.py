"""J: 단일 인스턴스 메시지, 대상 문자열 정규화, 자동 새로고침 의존 파일, 원문 보기·테마 (Qt 없이)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from htex.viewer import instance as I
from htex.viewer.core import ViewerCore, source_page, with_theme

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "tests" / "docs"


# ====================================================================== 대상 문자열
def test_normalize_urls_untouched(tmp_path):
    for s in ("htex://ex.org/a.htex#eq:H", "https://ex.org/a.htex", "http://ex.org/", "htexapp://x"):
        assert I.normalize_target("  " + s + "\n", tmp_path) == s


def test_normalize_relative_and_home(tmp_path, monkeypatch):
    (tmp_path / "a.htex").write_text("x")
    assert I.normalize_target("a.htex", tmp_path) == str(tmp_path / "a.htex")
    assert I.normalize_target("./sub/../a.htex", tmp_path) == str(tmp_path / "a.htex")
    assert I.normalize_target("a.htex#eq:H", tmp_path) == str(tmp_path / "a.htex") + "#eq:H"
    monkeypatch.setenv("HOME", str(tmp_path))
    assert I.normalize_target("~/a.htex", Path("/")) == str(tmp_path / "a.htex")
    # 없는 상대 경로도 절대 경로로 (받는 쪽이 '파일 없음' 을 보인다)
    assert I.normalize_target("nope.htex", tmp_path) == str(tmp_path / "nope.htex")


def test_normalize_file_url_and_domain(tmp_path):
    p = tmp_path / "한글 문서.htex"
    p.write_text("x")
    assert I.normalize_target(p.as_uri(), Path("/")) == str(p)
    assert I.normalize_target(p.as_uri() + "#sec:a", Path("/")) == str(p) + "#sec:a"
    assert I.normalize_target("example.org/notes/a.htex", tmp_path) == "example.org/notes/a.htex"


@pytest.mark.skipif(os.name != "nt", reason="윈도 경로")
def test_normalize_windows_drive():   # pragma: no cover
    assert I.normalize_target("C:\\x\\a.htex").lower().startswith("c:\\")


def test_normalize_targets_list_and_str(tmp_path):
    assert I.normalize_targets(None) == []
    assert I.normalize_targets("htex://a/b.htex") == ["htex://a/b.htex"]
    assert I.normalize_targets(["", " ", "htex://a/b.htex"], tmp_path) == ["htex://a/b.htex"]
    assert len(I.normalize_targets(["htex://a/b.htex"] * 100)) == I.MAX_TARGETS


# ====================================================================== 메시지
def test_message_roundtrip():
    data = I.encode_message(["/x/한글.htex", "htex://a/b.htex#eq:1"], "/home/u")
    assert data.endswith(b"\n") and data.count(b"\n") == 1
    msg = I.decode_message(data)
    assert msg == {"cmd": "open", "targets": ["/x/한글.htex", "htex://a/b.htex#eq:1"], "cwd": "/home/u"}
    assert I.decode_message(I.encode_message([])) ["targets"] == []


@pytest.mark.parametrize("bad", [b"", b"not json\n", b'{"v":2,"cmd":"open","targets":[]}\n',
                                 b'{"v":1,"cmd":"rm","targets":[]}\n', b'{"v":1,"cmd":"open","targets":"x"}\n',
                                 b'{"v":1,"cmd":"open","targets":[1]}\n', b"[1,2]\n", b"\xff\xfe\n",
                                 b"x" * (I.MAX_MESSAGE + 1)])
def test_message_rejects(bad):
    assert I.decode_message(bad) is None


def test_instance_name(monkeypatch):
    monkeypatch.delenv("HTEX_VIEWER_INSTANCE", raising=False)
    a = I.instance_name()
    assert a.startswith("hypertex-viewer-") and a == I.instance_name()
    monkeypatch.setenv("HOME", "/other/home")
    assert I.instance_name() != a                 # 사용자(홈)마다 다르다
    monkeypatch.setenv("HTEX_VIEWER_INSTANCE", "test/../x y")
    assert I.instance_name() == "test_.._x_y"


# ====================================================================== 의존 파일
def test_local_dependencies(tmp_path):
    (tmp_path / "sub").mkdir()
    for n in ("notation.htex", "style.hsty", "ch1.tex", "refs.bbl", "other.htex", "sub/x.htex"):
        (tmp_path / n).write_text("x")
    doc = tmp_path / "main.htex"
    doc.write_text(r"""\usemacros{notation} \usestyle{style.hsty} \input{ch1}
% \input{commented}
\bibliography{refs} \ref{other.htex#eq:a} \transclude{sub/x.htex#thm:1} \ref{eq:local}
\usemacros{https://ex.org/m.htex} \input{../outside} \input{missing} \ref{main.htex#self}
""", encoding="utf-8")
    got = [p.relative_to(tmp_path.resolve()).as_posix() for p in I.local_dependencies(doc)]
    assert got == ["notation.htex", "style.hsty", "ch1.tex", "refs.bbl", "other.htex", "sub/x.htex"]


def test_local_dependencies_real_doc():
    deps = I.local_dependencies(DOCS / "18-usemacros.htex")
    assert [p.name for p in deps] == ["notation.htex"]


def test_file_signature(tmp_path):
    p = tmp_path / "a"
    s0 = I.file_signature([p])
    p.write_text("1")
    s1 = I.file_signature([p])
    assert s0 != s1 and s0[0][1] is None


# ====================================================================== 원문 보기·테마 (core)
def test_source_page_escapes():
    page = source_page("<script>alert(1)</script>\n&amp; \\section{x}\n", "/x/a.htex", "제목<b>")
    assert "<script>alert" not in page and "&lt;script&gt;" in page
    assert "&amp;amp;" in page and "제목&lt;b&gt;" in page
    assert "default-src &#x27;none&#x27;" in page


def test_source_endpoint_and_theme(tmp_path):
    doc = tmp_path / "a.htex"
    doc.write_text("\\documentclass{hypertex}\\title{T}\\begin{document}<script>x</script>\\end{document}",
                   encoding="utf-8")
    core = ViewerCore()
    url = core.local_url(doc)
    assert core.respond(url).status == 200
    src = core.source_url(url)
    assert src and src.startswith("htexapp://source/")
    r = core.respond(src)
    assert r.status == 200 and "&lt;script&gt;x" in r.text and "<script>" not in r.text
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert core.display_address(src) == "원문: " + str(doc.resolve())
    # 웹 페이지에서는 못 쓴다
    assert core.respond(src, "https://evil.example").fail
    # 테마
    assert 'data-theme' not in core.respond(url).text.split(">", 2)[1]
    core.theme = "dark"
    assert '<html lang="ko" data-theme="dark">' in core.respond(url).text
    assert 'data-theme="dark"' in core.respond(src).text
    assert 'data-theme="dark"' in core.respond("htexapp://doc-nothere/a.htex").text   # 오류 페이지


def test_with_theme():
    assert with_theme('<html lang="ko"><body>', "light") == '<html lang="ko" data-theme="light"><body>'
    assert with_theme('<html data-theme="dark">', "light") == '<html data-theme="light">'
    assert with_theme("<html>", "") == "<html>" and with_theme("<html>", "evil") == "<html>"
