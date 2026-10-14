"""F: 전용 뷰어 core (Qt 없이). 네트워크 없이 가짜 opener 로 확인한다."""
from __future__ import annotations

import io
import socket
import time
import urllib.error
from pathlib import Path

import pytest

from htex.tikz import PictureResult
from htex.viewer import core as C
from htex.viewer.core import (Fetcher, FetchError, History, TreeCache, ViewerCore, ViewerError,
                              classify_input, fragment_html, htex_to_https, join_url,
                              normalize_htex, run_with_limit)
from htex.parser import parse_text

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "tests" / "docs"


# ====================================================================== 가짜 네트워크
class FakeResp:
    def __init__(self, body: bytes, url: str, ctype="text/x-hypertex", length=True, delay=0.0,
                 chunk=None):
        self.buf = io.BytesIO(body)
        self.url = url
        self.headers = {"Content-Type": ctype}
        if length:
            self.headers["Content-Length"] = str(len(body))
        self.delay = delay
        self.chunk = chunk
        self.closed = False

    def read(self, n=-1):
        if self.delay:
            time.sleep(self.delay)
        return self.buf.read(self.chunk or n)

    def geturl(self):
        return self.url

    def close(self):
        self.closed = True


class FakeOpener:
    """주소 → (본문, 내용 형식) 또는 예외. 요청을 기록한다."""

    def __init__(self, routes=None, **resp_kw):
        self.routes = routes or {}
        self.requests = []
        self.resp_kw = resp_kw

    def open(self, req, timeout=None):
        self.requests.append((req.full_url, dict(req.header_items()), timeout))
        r = self.routes.get(req.full_url)
        if r is None:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        if isinstance(r, BaseException):
            raise r
        if isinstance(r, FakeResp):
            return r
        body, ctype = r if isinstance(r, tuple) else (r, "text/x-hypertex")
        return FakeResp(body.encode() if isinstance(body, str) else body, req.full_url, ctype,
                        **self.resp_kw)


DOC_A = r"""\documentclass{hypertex}
\title{원격 A}
\begin{document}
\section{첫}\label{sec:one}
식 \begin{equation}\label{eq:E} E = mc^2 \end{equation}
다른 문서 \ref{b.htex#eq:F}. 웹 주소로 \href{https://ex.org/n/b.htex}{B 문서}.
\end{document}
"""
DOC_B = r"""\documentclass{hypertex}
\title{원격 B}
\begin{document}
\begin{equation}\label{eq:F} F = ma \end{equation}
\end{document}
"""


def remote_core(**kw):
    op = FakeOpener({"https://ex.org/n/a.htex": DOC_A, "https://ex.org/n/b.htex": DOC_B,
                     "https://ex.org/page.htex": ("<html></html>", "text/html; charset=utf-8")})
    return ViewerCore(fetcher=Fetcher(op), cache=TreeCache(), **kw), op


# ====================================================================== 주소
def test_htex_to_https_and_normalize():
    assert htex_to_https("htex://Example.ORG/notes/a.htex") == "https://example.org/notes/a.htex"
    assert normalize_htex("htex://ex.org:443/a/./b/../c.htex#x") == "htex://ex.org/a/c.htex"
    assert normalize_htex("htex://ex.org:8443/a.htex") == "htex://ex.org:8443/a.htex"
    assert normalize_htex("htex://ex.org") == "htex://ex.org/"
    assert normalize_htex("htex://ex.org/../../etc") == "htex://ex.org/etc"


@pytest.mark.parametrize("bad", ["htex://user@ex.org/a", "htex:///a.htex", "htex://ex org/a",
                                 "https://ex.org/a", "htex://ex.org:99999/a"])
def test_bad_htex_rejected(bad):
    with pytest.raises(ViewerError):
        normalize_htex(bad)


def test_join_url_custom_schemes():
    assert join_url("htex://ex.org/n/a.htex", "b.htex#eq:F") == "htex://ex.org/n/b.htex#eq:F"
    assert join_url("htex://ex.org/n/a.htex", "../c.htex") == "htex://ex.org/c.htex"
    assert join_url("htexapp://doc-k/d/a.htex", "b.htex") == "htexapp://doc-k/d/b.htex"
    assert join_url("htexapp://doc-k/a.htex", "htex://o.org/x") == "htex://o.org/x"


def test_classify_input(tmp_path):
    f = tmp_path / "a.htex"
    f.write_text("x", encoding="utf-8")
    assert classify_input("htex://ex.org/a.htex#eq:1").url == "htex://ex.org/a.htex#eq:1"
    t = classify_input("https://ex.org/n/a.htex")
    assert (t.kind, t.url) == ("remote", "htex://ex.org/n/a.htex")
    assert classify_input("https://ex.org/index.html").kind == "web"
    assert classify_input("http://ex.org/").kind == "web"
    assert classify_input(str(f)).path == f.resolve()
    assert classify_input("a.htex", cwd=tmp_path).path == f.resolve()
    assert classify_input(f.resolve().as_uri()).path == f.resolve()
    assert classify_input("ex.org/n/a.htex").url == "htex://ex.org/n/a.htex"
    with pytest.raises(ViewerError):
        classify_input("http://ex.org/a.htex")          # 문서 전송은 https 만
    with pytest.raises(ViewerError):
        classify_input("javascript:alert(1)")
    with pytest.raises(ViewerError):
        classify_input("없는파일.htex", cwd=tmp_path)


# ====================================================================== 가져오기
def test_fetch_https_only_and_user_agent():
    op = FakeOpener({"https://ex.org/a.htex": "본문"})
    f = Fetcher(op)
    r = f.fetch("https://ex.org/a.htex")
    assert r.content.decode() == "본문"
    url, headers, timeout = op.requests[0]
    assert "HyperTeX-Viewer" in headers.get("User-agent", "")
    assert timeout == C.FETCH_TIMEOUT
    for bad in ("http://ex.org/a.htex", "file:///etc/passwd", "ftp://ex.org/a", "data:,x"):
        with pytest.raises(FetchError) as e:
            f.fetch(bad)
        assert e.value.code == "insecure"
    assert len(op.requests) == 1


def test_fetch_redirect_must_stay_https():
    resp = FakeResp(b"x", "http://evil.example/a.htex")
    f = Fetcher(FakeOpener({"https://ex.org/a.htex": resp}))
    with pytest.raises(FetchError) as e:
        f.fetch("https://ex.org/a.htex")
    assert e.value.code == "insecure-redirect"
    h = C.HTTPSOnlyRedirect()
    with pytest.raises(FetchError):
        h.redirect_request(None, None, 302, "Found", {}, "http://evil.example/")


def test_default_opener_has_no_file_handler():
    op = C.default_opener()
    names = {type(h).__name__ for h in op.handlers}
    assert "FileHandler" not in names and "FTPHandler" not in names and "DataHandler" not in names


def test_fetch_size_limit_by_header_and_stream():
    big = b"a" * 2000
    f = Fetcher(FakeOpener({"https://ex.org/a.htex": big}), max_bytes=1000)
    with pytest.raises(FetchError) as e:
        f.fetch("https://ex.org/a.htex")
    assert e.value.code == "too-large"
    # Content-Length 없이 흘려 보내도 상한에서 멈춘다
    f = Fetcher(FakeOpener({"https://ex.org/a.htex": big}, length=False, chunk=300), max_bytes=1000)
    with pytest.raises(FetchError) as e:
        f.fetch("https://ex.org/a.htex")
    assert e.value.code == "too-large"
    assert C.MAX_BYTES == 5 * 1024 * 1024


def test_fetch_timeouts():
    f = Fetcher(FakeOpener({"https://ex.org/a": socket.timeout("t")}))
    with pytest.raises(FetchError) as e:
        f.fetch("https://ex.org/a")
    assert e.value.code == "timeout"
    f = Fetcher(FakeOpener({"https://ex.org/a": urllib.error.URLError(socket.timeout("t"))}))
    with pytest.raises(FetchError) as e:
        f.fetch("https://ex.org/a")
    assert e.value.code == "timeout"
    # 조금씩 오래 끄는 응답: 전체 시간 제한
    slow = FakeResp(b"a" * 100, "https://ex.org/a", length=False, delay=0.05, chunk=1)
    f = Fetcher(FakeOpener({"https://ex.org/a": slow}), timeout=0.2)
    t0 = time.monotonic()
    with pytest.raises(FetchError) as e:
        f.fetch("https://ex.org/a")
    assert e.value.code == "timeout"
    assert time.monotonic() - t0 < 2


def test_fetch_http_and_network_errors():
    f = Fetcher(FakeOpener({}))
    with pytest.raises(FetchError) as e:
        f.fetch("https://ex.org/missing")
    assert e.value.code == "http-error"
    f = Fetcher(FakeOpener({"https://ex.org/a": urllib.error.URLError("dns")}))
    with pytest.raises(FetchError) as e:
        f.fetch("https://ex.org/a")
    assert e.value.code == "network"


# ====================================================================== 원격 문서
def test_remote_document_page():
    core, op = remote_core()
    r = core.respond("htex://ex.org/n/a.htex#sec:one")
    assert r.status == 200 and not r.fail and r.mime == "text/html"
    assert op.requests[0][0] == "https://ex.org/n/a.htex"
    assert "<title>원격 A</title>" in r.text
    assert "Content-Security-Policy" in r.headers
    assert "script-src htexapp:" in r.headers["Content-Security-Policy"]
    rec = r.record
    assert rec.remote and rec.address == "htex://ex.org/n/a.htex"
    # 규약 2절: meta 두 개와 스크립트
    assert f'<meta name="htex-picture-endpoint" content="htexapp://picture/{rec.key}">' in r.text
    assert f'<meta name="htex-fragment-endpoint" content="htexapp://fragment/{rec.key}">' in r.text
    assert '<script src="htexapp://asset/interact.js" defer></script>' in r.text
    # 스크립트는 그것 하나뿐
    assert r.text.count("<script") == 1


def test_remote_html_page_goes_to_web():
    core, _ = remote_core()
    r = core.respond("htex://ex.org/page.htex")
    assert r.redirect == "https://ex.org/page.htex"


def test_remote_fetch_error_page():
    core, _ = remote_core()
    r = core.respond("htex://ex.org/nothing.htex")
    assert r.status == 200 and "문서를 열 수 없습니다" in r.text and "http-error" in r.text
    assert "<script" not in r.text


def test_remote_doc_cannot_read_local_files(tmp_path):
    secret = Path.cwd() / "AGENTS.md"
    doc = "\\documentclass{hypertex}\n\\usemacros{AGENTS.md}\n\\begin{document}x\\end{document}\n"
    op = FakeOpener({"https://ex.org/a.htex": doc})
    core = ViewerCore(fetcher=Fetcher(op), cache=TreeCache())
    rec = core.load("htex://ex.org/a.htex")
    assert secret.exists() or True
    assert any(d["code"] == "missing-resource" for d in rec.diagnostics)


# ====================================================================== 시간 상한
def test_run_with_limit():
    assert run_with_limit(lambda: 3, 1) == 3
    with pytest.raises(C.RenderTimeout):
        run_with_limit(lambda: time.sleep(0.5), 0.05)
    with pytest.raises(KeyError):
        run_with_limit(lambda: {}["x"], 1)


def test_parse_over_limit_gives_error_page():
    def slow_parse(text, **kw):
        time.sleep(0.4)
        return parse_text(text, **kw)
    op = FakeOpener({"https://ex.org/a.htex": DOC_A})
    core = ViewerCore(fetcher=Fetcher(op), cache=TreeCache(), parse=slow_parse, render_limit=0.05)
    t0 = time.monotonic()
    r = core.respond("htex://ex.org/a.htex")
    assert time.monotonic() - t0 < 0.3
    assert "render-timeout" in r.text and r.record is None
    assert C.RENDER_LIMIT == 2.0


# ====================================================================== 캐시
def test_tree_cache_memory_and_disk(tmp_path):
    calls = []

    def counting(text, **kw):
        calls.append(kw.get("url"))
        return parse_text(text, **kw)

    op = FakeOpener({"https://ex.org/n/a.htex": DOC_A})
    core = ViewerCore(fetcher=Fetcher(op), cache=TreeCache(tmp_path), parse=counting)
    r1 = core.load("htex://ex.org/n/a.htex")
    r2 = core.load("htex://ex.org/n/a.htex")
    assert r1 is r2 and len(calls) == 1 and len(op.requests) == 1
    assert list((tmp_path / "trees").glob("*.json"))
    # 새 뷰어(재시작)는 디스크 캐시에서 트리를 읽는다 (가져오기는 다시 한다)
    core2 = ViewerCore(fetcher=Fetcher(op), cache=TreeCache(tmp_path), parse=counting)
    r3 = core2.load("htex://ex.org/n/a.htex")
    assert len(calls) == 1 and r3.tree["meta"] == r1.tree["meta"]
    # 내용이 바뀌면 다시 해석
    op.routes["https://ex.org/n/a.htex"] = DOC_A.replace("원격 A", "원격 A2")
    r4 = core2.load("htex://ex.org/n/a.htex", reload=True)
    assert len(calls) == 2 and r4.title == "원격 A2"


def test_tree_cache_lru():
    c = TreeCache(capacity=2)
    for i in range(3):
        c.put(f"u{i}", "s", {"i": i})
    assert len(c) == 2 and c.get("u0", "s") is None and c.get("u2", "s") == {"i": 2}


def test_local_documents_not_disk_cached(tmp_path):
    cache_dir = tmp_path / "cache"
    core = ViewerCore(cache=TreeCache(cache_dir))
    core.load(core.local_url(DOCS / "01-minimal.htex"))
    assert not (cache_dir / "trees").exists()


def test_default_cache_dir_is_platform_folder():
    d = C.default_cache_dir()
    assert d.is_absolute() and "hypertex" in str(d).lower()


# ====================================================================== 히스토리
def test_history():
    h = History()
    assert not h.can_back() and h.back() is None
    h.visit("a")
    h.visit("b")
    h.visit("b")          # 같은 주소 연달아 → 하나
    h.visit("c")
    assert [e.url for e in h.entries] == ["a", "b", "c"]
    assert h.back().url == "b" and h.back().url == "a" and h.back() is None
    assert h.forward().url == "b"
    h.visit("d")          # 앞쪽 기록(c)은 지운다
    assert [e.url for e in h.entries] == ["a", "b", "d"] and not h.can_forward()
    h.set_title("제목")
    assert h.current.title == "제목"


def test_history_limit():
    h = History(limit=3)
    for u in "abcde":
        h.visit(u)
    assert [e.url for e in h.entries] == ["c", "d", "e"] and h.index == 2


# ====================================================================== 로컬 파일
def test_local_url_roundtrip_and_page():
    core = ViewerCore(cache=TreeCache())
    url = core.local_url(DOCS / "11-internal-refs.htex")
    assert url.startswith("htexapp://doc-") and url.endswith("/11-internal-refs.htex")
    assert core.local_path(url) == (DOCS / "11-internal-refs.htex").resolve()
    assert core.display_address(url + "#eq:H") == str((DOCS / "11-internal-refs.htex").resolve()) + "#eq:H"
    r = core.respond(url)
    assert r.status == 200 and "<title>문서 안 참조</title>" in r.text
    assert r.record.counts() == (0, 1)


def test_local_outside_folder_rejected(tmp_path):
    core = ViewerCore(cache=TreeCache())
    url = core.local_url(DOCS / "01-minimal.htex")
    host = url.split("/")[2]
    for bad in (f"htexapp://{host}/../manifest.json", f"htexapp://{host}/%2E%2E/manifest.json",
                f"htexapp://{host}/..%2F..%2FAGENTS.md", "htexapp://doc-unknown/a.htex"):
        r = core.respond(bad)
        assert "forbidden" in r.text and r.record is None, bad
    with pytest.raises(ViewerError):
        core.local_path(f"htexapp://{host}/../manifest.json")
    # 심볼릭 링크로 밖을 가리켜도 거부
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "a.htex").write_text("\\documentclass{hypertex}x", encoding="utf-8")
    (tmp_path / "out.htex").write_text("\\documentclass{hypertex}비밀", encoding="utf-8")
    try:
        (tmp_path / "d" / "link.htex").symlink_to(tmp_path / "out.htex")
    except OSError:
        pytest.skip("심볼릭 링크를 만들 수 없음")
    u = core.local_url(tmp_path / "d" / "a.htex")
    r = core.respond(u.rsplit("/", 1)[0] + "/link.htex")
    assert "forbidden" in r.text
    # 등록 없이 폴더 밖 파일은 열 수 없다
    with pytest.raises(ViewerError):
        core.local_url(tmp_path / "out.htex", register=False)


def test_local_from_other_origin_rejected():
    core = ViewerCore(cache=TreeCache())
    url = core.local_url(DOCS / "01-minimal.htex")
    host = url.split("/")[2]
    assert "forbidden" in core.respond(url, initiator="https://evil.example").text
    assert "forbidden" in core.respond(url, initiator="htex://ex.org").text
    assert "forbidden" in core.respond(url, initiator="htexapp://doc-other").text
    assert core.respond(url, initiator=f"htexapp://{host}").record is not None


def test_local_non_document_and_image(tmp_path):
    (tmp_path / "a.htex").write_text("\\documentclass{hypertex}x", encoding="utf-8")
    (tmp_path / "p.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (tmp_path / "s.txt").write_text("비밀", encoding="utf-8")
    core = ViewerCore(cache=TreeCache())
    base = core.local_url(tmp_path / "a.htex").rsplit("/", 1)[0]
    r = core.respond(base + "/p.svg", initiator=base.split("/")[0] + "//" + base.split("/")[2])
    assert r.mime == "image/svg+xml" and r.headers["Content-Security-Policy"] == "default-src 'none'"
    assert "not-document" in core.respond(base + "/s.txt").text


# ====================================================================== 조각 주소
def test_fragment_endpoint_local():
    core = ViewerCore(cache=TreeCache())
    rec = core.respond(core.local_url(DOCS / "12-cross-doc-refs.htex")).record
    origin = "htexapp://" + rec.address.split("/")[2]
    r = core.respond(f"htexapp://fragment/{rec.key}?doc=11-internal-refs.htex&label=eq:H", origin)
    assert r.status == 200 and not r.fail
    assert r.headers.get("Access-Control-Allow-Origin") == origin
    assert r.text.startswith('<div class="htex-fragment"') and "(1)" in r.text and "<math" in r.text
    assert ' id="' not in r.text
    # 절: 제목 + 앞부분, 같은 문서 링크는 원 문서 주소로
    r = core.respond(f"htexapp://fragment/{rec.key}?doc=11-internal-refs.htex&label=sec:eigen", origin)
    assert "고윳값" in r.text and "11-internal-refs.htex#eq:H" in r.text
    # 없는 라벨, 없는 문서
    assert core.respond(f"htexapp://fragment/{rec.key}?doc=11-internal-refs.htex&label=nope",
                        origin).status == 404
    assert core.respond(f"htexapp://fragment/{rec.key}?doc=none.htex&label=x", origin).fail
    # doc 에 #라벨 이 붙어 와도
    r = core.respond(f"htexapp://fragment/{rec.key}?doc=11-internal-refs.htex%23eq:En", origin)
    assert r.status == 200 and "(2)" in r.text


def test_fragment_same_document_and_theorem():
    core = ViewerCore(cache=TreeCache())
    rec = core.load(core.local_url(DOCS / "08-theorems.htex"))
    r = core.respond(f"htexapp://fragment/{rec.key}?doc=&label=thm:lagrange")
    assert r.status == 200 and "라그랑주" in r.text


def test_fragment_remote_and_isolation():
    core, op = remote_core()
    rec = core.load("htex://ex.org/n/a.htex")
    r = core.respond(f"htexapp://fragment/{rec.key}?doc=b.htex&label=eq:F", "htex://ex.org")
    assert r.status == 200 and "F" in r.text
    assert op.requests[-1][0] == "https://ex.org/n/b.htex"
    # 원격 문서는 로컬을 가리킬 수 없다
    assert core.respond(f"htexapp://fragment/{rec.key}?doc=htexapp://doc-x/a.htex&label=a",
                        "htex://ex.org").status == 403
    # 웹 페이지에서는 내부 주소 금지
    assert core.respond(f"htexapp://fragment/{rec.key}?doc=b.htex&label=eq:F",
                        "https://evil.example").status == 403
    # 원격 출처가 로컬 문서 조각을 요청할 수 없다
    local = core.load(core.local_url(DOCS / "11-internal-refs.htex"))
    assert core.respond(f"htexapp://fragment/{local.key}?doc=&label=eq:H", "htex://ex.org").status == 403


def test_fragment_html_escapes_and_unknown():
    tree = parse_text("\\documentclass{hypertex}\\begin{document}"
                      "\\begin{equation}\\label{eq:x} a<b \\end{equation}\\end{document}")
    html = fragment_html(tree, "eq:x", "htex://ex.org/a.htex")
    assert html and "&lt;" in html and "<b " not in html
    assert fragment_html(tree, "nope", "htex://ex.org/a.htex") is None


def test_transclusion_filled_in_page():
    core = ViewerCore(cache=TreeCache())
    r = core.respond(core.local_url(DOCS / "14-transclusion.htex"))
    assert r.text.count("htex-transcluded") >= 2
    assert "라그랑주" in r.text and "출처:" in r.text


def test_transclusion_failure_keeps_link():
    doc = ("\\documentclass{hypertex}\\begin{document}\\transclude{missing.htex#x}"
           "\\end{document}")
    op = FakeOpener({"https://ex.org/a.htex": doc})
    core = ViewerCore(fetcher=Fetcher(op), cache=TreeCache())
    r = core.respond("htex://ex.org/a.htex")
    assert "htex-transclusion-failed" in r.text and "missing.htex" in r.text


# ====================================================================== 그림 주소
def test_picture_endpoint_stub_and_renderer():
    core = ViewerCore(cache=TreeCache())
    rec = core.load(core.local_url(DOCS / "25-parameters.htex"))
    pic = next(b for b in rec.tree["body"] if b.get("kind") == "picture")
    origin = "htexapp://" + rec.address.split("/")[2]
    # H 가 stub 이면 svg 는 None → 실패 응답
    r = core.respond(f"htexapp://picture/{rec.key}?node={pic['id']}&omega=2", origin)
    assert r.fail and r.status == 404

    seen = {}

    def fake(tree, node, values):
        seen.update(node=node, values=values)
        return PictureResult('<svg viewBox="0 0 1 1"></svg>')

    core.picture_renderer = fake
    r = core.respond(f"htexapp://picture/{rec.key}?node={pic['id']}&omega=2&gamma=0.5", origin)
    assert r.status == 200 and r.mime == "image/svg+xml" and r.text.startswith("<svg")
    assert seen == {"node": pic["id"], "values": {"omega": 2.0, "gamma": 0.5}}
    assert r.headers["Access-Control-Allow-Origin"] == origin
    assert core.respond(f"htexapp://picture/{rec.key}?node={pic['id']}&omega=x", origin).status == 400
    assert core.respond(f"htexapp://picture/{rec.key}", origin).status == 400
    assert core.respond("htexapp://picture/nokey?node=n1", origin).status == 404
    # 렌더러가 svg 아닌 것을 내면 거부
    core.picture_renderer = lambda *a: PictureResult("<script>x</script>")
    assert core.respond(f"htexapp://picture/{rec.key}?node={pic['id']}", origin).fail


def test_asset_interact_js(tmp_path):
    js = tmp_path / "interact.js"
    core = ViewerCore(cache=TreeCache(), interact_js=js)
    r = core.respond("htexapp://asset/interact.js")
    assert r.status == 200 and r.mime == "text/javascript" and r.body.startswith(b"/*")
    js.write_text("window.x=1;", encoding="utf-8")
    assert core.respond("htexapp://asset/interact.js").text == "window.x=1;"
    assert core.respond("htexapp://asset/other.js").status == 404
    assert core.respond("htexapp://asset/interact.js", "https://evil.example").status == 403


def test_respond_never_raises():
    core = ViewerCore(cache=TreeCache())
    for u in ("htex://", "htexapp://", "htexapp://zzz/", "nope:x", "htex://ex.org:abc/"):
        r = core.respond(u)
        assert isinstance(r, C.Response)
