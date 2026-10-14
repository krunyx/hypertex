"""G: htex serve (htex/web/server.py) 테스트.

서버를 임의 포트에 스레드로 띄워 urllib(필요하면 http.client: 정규화되지 않은 경로)로 요청한다.
문서 폴더는 tests/docs 를 tmp_path 로 복사해 쓴다 (캐시 갱신 시험에서 파일을 고치므로).
"""
from __future__ import annotations

import http.client
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import htex.tikz
from htex.web.server import serve_in_thread

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "tests" / "docs"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    base = tmp_path_factory.mktemp("g-site")
    root = base / "docs"
    shutil.copytree(DOCS, root)
    (root / "sub").mkdir()
    (root / "sub" / "child.htex").write_text(
        "\\documentclass{hypertex}\n\\title{하위 문서}\n\\begin{document}\n"
        "\\section{가}\\label{sec:a}\n본문 \\ref{../11-internal-refs.htex#eq:H}.\n\\end{document}\n",
        encoding="utf-8")
    (root / ".secret").write_text("숨김", encoding="utf-8")
    (root / ".hidden-dir").mkdir()
    (root / ".hidden-dir" / "x.txt").write_text("숨김", encoding="utf-8")
    (base / "outside.txt").write_text("밖의 비밀", encoding="utf-8")
    (root / "evil.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                                   encoding="utf-8")
    try:
        os.symlink(base / "outside.txt", root / "link-out.txt")
        os.symlink(base, root / "link-dir")
        os.symlink(root / "physics-notes.hsty", root / "link-in.hsty")
    except OSError:
        pass
    srv = serve_in_thread(root)
    srv.test_root = root
    yield srv
    srv.shutdown()
    srv.server_close()


def get(srv, path, headers=None):
    req = urllib.request.Request(srv.url.rstrip("/") + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def raw_get(srv, path, method="GET"):
    """경로를 손대지 않고 그대로 보낸다 (urllib 은 일부를 정규화한다)."""
    host, port = srv.server_address[:2]
    c = http.client.HTTPConnection(host, port, timeout=10)
    c.putrequest(method, path, skip_accept_encoding=True)
    c.endheaders()
    r = c.getresponse()
    body = r.read().decode("utf-8", "replace")
    c.close()
    return r.status, r.headers, body


# ---------------------------------------------------------------- 문서
def test_document_html(site):
    st, h, body = get(site, "/11-internal-refs.htex")
    assert st == 200
    assert h["Content-Type"].startswith("text/html")
    assert body.startswith("<!doctype html>")
    assert "<math" in body and 'id="eq:H"' in body
    assert '<script src="/__htex/interact.js" defer></script>' in body
    assert '<meta name="htex-picture-endpoint" content="/__htex/picture/11-internal-refs.htex">' in body
    assert '<meta name="htex-fragment-endpoint" content="/__htex/fragment">' in body


def test_document_web_fallback_links(site):
    _, _, body = get(site, "/12-cross-doc-refs.htex")
    assert 'href="https://example.org/notes/oscillator.htex#eq:aadag"' in body
    assert 'href="11-internal-refs.htex#eq:H"' in body
    assert "javascript:" not in body.split("<body", 1)[1].split("htex-error")[0]


def test_tex_document_and_subfolder(site):
    st, h, body = get(site, "/27-compat-article.tex")
    assert st == 200 and h["Content-Type"].startswith("text/html")
    st, _, body = get(site, "/sub/child.htex")
    assert st == 200 and "하위 문서" in body
    assert 'content="/__htex/picture/sub/child.htex"' in body


def test_korean_filename(site):
    (site.test_root / "한글 문서.htex").write_text("\\title{한글 이름}\n본문.\n", encoding="utf-8")
    st, _, body = get(site, "/" + urllib.request.quote("한글 문서.htex"))
    assert st == 200 and "한글 이름" in body


def test_head_request(site):
    st, h, body = raw_get(site, "/01-minimal.htex", "HEAD")
    assert st == 200 and body == "" and int(h["Content-Length"]) > 0


def test_post_not_allowed(site):
    st, h, _ = raw_get(site, "/01-minimal.htex", "POST")
    assert st == 405 and "GET" in h["Allow"]


# ---------------------------------------------------------------- 정적·목록
def test_static_file(site):
    st, h, body = get(site, "/physics-notes.hsty")
    assert st == 200
    assert h["Content-Type"].startswith("text/plain")
    assert body == (DOCS / "physics-notes.hsty").read_text(encoding="utf-8")
    assert h["X-Content-Type-Options"] == "nosniff"


def test_static_svg_is_sandboxed(site):
    st, h, _ = get(site, "/evil.svg")
    assert st == 200 and h["Content-Type"].startswith("image/svg+xml")
    assert "default-src 'none'" in h["Content-Security-Policy"]
    assert "script-src" not in h["Content-Security-Policy"]


def test_listing(site):
    st, h, body = get(site, "/")
    assert st == 200 and h["Content-Type"].startswith("text/html")
    assert 'href="11-internal-refs.htex"' in body
    assert "문서 안 참조" in body           # .htex 문서 제목
    assert 'href="sub/"' in body
    assert 'href="physics-notes.hsty"' in body
    assert ".secret" not in body and ".hidden-dir" not in body
    assert "link-out.txt" not in body and "link-dir" not in body   # 루트 밖 링크는 목록에서 뺌


def test_listing_redirect_and_subfolder(site):
    st, h, _ = raw_get(site, "/sub")
    assert st == 301 and h["Location"] == "/sub/"
    st, _, body = get(site, "/sub/")
    assert st == 200 and "child.htex" in body and "하위 문서" in body and 'href="../"' in body


def test_not_found(site):
    st, h, body = get(site, "/nope.htex")
    assert st == 404 and h["Content-Type"].startswith("text/html")


# ---------------------------------------------------------------- 보안
@pytest.mark.parametrize("path", [
    "/../outside.txt",
    "/%2e%2e/outside.txt",
    "/%2E%2E/outside.txt",
    "/sub/../../outside.txt",
    "/sub/%2e%2e/%2e%2e/outside.txt",
    "/..%2foutside.txt",
    "/%2e%2e%2foutside.txt",
    "/..%5coutside.txt",
    "/sub\\..\\..\\outside.txt",
    "/%00",
])
def test_path_traversal_rejected(site, path):
    st, _, body = raw_get(site, path)
    assert st in (400, 403, 404)
    assert "밖의 비밀" not in body


def test_double_encoded_is_literal(site):
    # %252e%252e 는 '%2e%2e' 라는 이름으로 본다: 없는 파일
    st, _, body = raw_get(site, "/%252e%252e/outside.txt")
    assert st == 404 and "밖의 비밀" not in body


def test_absolute_path_rejected(site):
    st, _, body = raw_get(site, "//etc/passwd")
    assert st in (403, 404) and "root:x:0" not in body
    st, _, body = raw_get(site, "/C:/Windows/win.ini")
    assert st in (403, 404)
    st, _, body = raw_get(site, "http://example.com/")
    assert st == 400


def test_symlink_outside_rejected(site):
    if not (site.test_root / "link-out.txt").is_symlink():
        pytest.skip("심볼릭 링크를 만들 수 없는 환경")
    st, _, body = get(site, "/link-out.txt")
    assert st == 403 and "밖의 비밀" not in body
    st, _, body = get(site, "/link-dir/outside.txt")
    assert st == 403 and "밖의 비밀" not in body
    st, _, _ = get(site, "/link-in.hsty")   # 루트 안을 가리키는 링크는 허용
    assert st == 200


def test_hidden_files_rejected(site):
    for p in ("/.secret", "/.hidden-dir/x.txt", "/.git/config", "/sub/.x"):
        st, _, body = get(site, p)
        assert st == 404 and "숨김" not in body.split("<body", 1)[-1].split("</h1>")[-1]


def test_security_headers(site):
    st, h, _ = get(site, "/01-minimal.htex")
    csp = h["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";")[0]
    assert h["X-Content-Type-Options"] == "nosniff"
    for p in ("/", "/__htex/interact.js", "/physics-notes.hsty", "/../x", "/__htex/nope"):
        _, h2, _ = raw_get(site, p)
        assert h2["X-Content-Type-Options"] == "nosniff", p


def test_default_bind_is_localhost():
    import inspect
    from htex.web import server
    assert inspect.signature(server.make_server).parameters["host"].default == "127.0.0.1"
    assert inspect.signature(server.serve).parameters["host"].default == "127.0.0.1"


# ---------------------------------------------------------------- 상호작용 스크립트
def test_interact_js(site):
    st, h, body = get(site, "/__htex/interact.js")
    assert st == 200 and h["Content-Type"].startswith("text/javascript")
    assert "htex-picture-endpoint" in body and "htex-fragment-endpoint" in body
    st, _, _ = get(site, "/__htex/other.js")
    assert st == 404


# ---------------------------------------------------------------- 조각
def test_fragment_same_server(site):
    st, h, body = get(site, "/__htex/fragment?doc=/11-internal-refs.htex&label=eq:H")
    assert st == 200 and h["Content-Type"].startswith("text/html")
    assert body.startswith('<div class="htex-fragment"')
    assert "<math" in body and "H = \\frac" in body
    assert "<html" not in body and "<script" not in body
    # 식 하나만: 다른 식(eq:En)은 들어가지 않는다
    assert "E_n" not in body


def test_fragment_theorem_and_section(site):
    st, _, body = get(site, "/__htex/fragment?doc=/08-theorems.htex&label=thm:lagrange")
    assert st == 200 and "htex-theorem" in body and "정리" in body
    st, _, body = get(site, "/__htex/fragment?doc=/11-internal-refs.htex&label=sec:eigen")
    assert st == 200 and "고윳값" in body


def test_fragment_links_rebased(site):
    st, _, body = get(site, "/__htex/fragment?doc=/11-internal-refs.htex&label=sec:eigen")
    assert st == 200
    assert 'href="/11-internal-refs.htex#eq:H"' in body   # 같은 문서 링크 → 조각 문서 기준
    st, _, body = get(site, "/__htex/fragment?doc=/sub/child.htex&label=sec:a")
    assert st == 200 and 'href="/11-internal-refs.htex#eq:H"' in body   # 상대 주소 → 절대 경로


def test_fragment_same_origin_absolute(site):
    host, port = site.server_address[:2]
    url = urllib.request.quote(f"http://{host}:{port}/11-internal-refs.htex", safe="")
    st, _, body = get(site, f"/__htex/fragment?doc={url}&label=eq:H")
    assert st == 200 and "<math" in body


@pytest.mark.parametrize("doc", [
    "https://example.org/notes/oscillator.htex",
    "htex://example.org/notes/oscillator.htex",
    "http://169.254.169.254/latest/meta-data",
    "file:///etc/passwd",
    "//example.org/x.htex",
    "/../outside.txt",
    "/physics-notes.hsty",
    "11-internal-refs.htex",
    "",
])
def test_fragment_external_or_bad_doc_404(site, doc):
    st, _, body = get(site, "/__htex/fragment?doc=" + urllib.request.quote(doc, safe="") + "&label=eq:H")
    assert st == 404
    assert "밖의 비밀" not in body


def test_fragment_missing_label(site):
    st, _, _ = get(site, "/__htex/fragment?doc=/11-internal-refs.htex&label=eq:nope")
    assert st == 404
    st, _, _ = get(site, "/__htex/fragment?doc=/11-internal-refs.htex")
    assert st == 400


# ---------------------------------------------------------------- 그림
def test_picture_endpoint_format(site):
    st, h, body = get(site, "/__htex/picture/25-parameters.htex?node=n2&omega=2&gamma=0.5")
    if st == 200:  # H 결과가 합쳐진 뒤
        assert h["Content-Type"].startswith("image/svg+xml")
        assert body.lstrip().startswith("<svg") and body.rstrip().endswith("</svg>")
        assert "default-src 'none'" in h["Content-Security-Policy"]
    else:          # 지금은 stub: 4xx 와 짧은 텍스트
        assert 400 <= st < 500
        assert h["Content-Type"].startswith("text/plain")
        assert len(body) < 1000


def test_picture_endpoint_with_renderer(site, monkeypatch):
    seen = {}

    def fake(tree, node, values=None):
        seen["node"], seen["values"] = node, dict(values or {})
        return htex.tikz.PictureResult('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>', [])

    monkeypatch.setattr(htex.tikz, "render_picture_node", fake)
    st, h, body = get(site, "/__htex/picture/25-parameters.htex?node=n2&omega=2.5&gamma=0.1&evil=3")
    assert st == 200 and h["Content-Type"].startswith("image/svg+xml")
    assert body.startswith("<svg")
    assert seen["node"] == "n2"
    assert seen["values"] == {"omega": 2.5, "gamma": 0.1}    # 선언되지 않은 이름은 버린다
    assert h["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("query,status", [
    ("node=n2&omega=abc", 400),
    ("node=n2&omega=nan", 400),
    ("node=n2&omega=inf", 400),
    ("omega=1", 400),
])
def test_picture_bad_query(site, query, status):
    st, _, _ = get(site, "/__htex/picture/25-parameters.htex?" + query)
    assert st == status


def test_picture_bad_document(site):
    assert get(site, "/__htex/picture/nope.htex?node=n2")[0] == 404
    assert raw_get(site, "/__htex/picture/../outside.txt?node=n1")[0] in (403, 404)
    assert raw_get(site, "/__htex/picture/%2e%2e/outside.txt?node=n1")[0] == 403
    assert get(site, "/__htex/picture/physics-notes.hsty?node=n1")[0] == 404
    assert get(site, "/__htex/picture/25-parameters.htex?node=n999")[0] == 404


# ---------------------------------------------------------------- 캐시
def test_cache_refresh(site):
    p = site.test_root / "cache-doc.htex"
    p.write_text("\\title{처음 제목}\n본문.\n", encoding="utf-8")
    st, _, body = get(site, "/cache-doc.htex")
    assert st == 200 and "처음 제목" in body
    entry = site.cache._entries[str(p.resolve())]
    _, _, body2 = get(site, "/cache-doc.htex")
    assert site.cache._entries[str(p.resolve())] is entry    # 그대로면 캐시 사용
    time.sleep(0.01)
    p.write_text("\\title{바뀐 제목입니다}\n본문.\n", encoding="utf-8")
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    _, _, body3 = get(site, "/cache-doc.htex")
    assert "바뀐 제목입니다" in body3 and "처음 제목" not in body3
    # 조각 주소도 새 내용
    p.write_text("\\title{세번째}\n\\section{새 절}\\label{sec:new}\n가.\n", encoding="utf-8")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000))
    st2, _, frag = get(site, "/__htex/fragment?doc=/cache-doc.htex&label=sec:new")
    assert st2 == 200 and "새 절" in frag


# ---------------------------------------------------------------- 오류 페이지
def test_render_exception_gives_error_page(site, monkeypatch):
    import htex.html

    def boom(*a, **k):
        raise RuntimeError("렌더러 고장 <script>")

    monkeypatch.setattr(htex.html, "render", boom)
    p = site.test_root / "boom.htex"
    p.write_text("\\title{터짐}\n본문 <b>.\n", encoding="utf-8")
    st, h, body = get(site, "/boom.htex")
    assert st == 500 and h["Content-Type"].startswith("text/html")
    assert "문서를 표시할 수 없다" in body
    assert "본문 &lt;b&gt;." in body          # 원문을 escape 해서 보인다
    assert "<script>" not in body.split("<body", 1)[1]
    assert "script-src 'self'" in h["Content-Security-Policy"]
    monkeypatch.undo()
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 1_000_000))
    st, _, body = get(site, "/boom.htex")
    assert st == 200 and "터짐" in body


def test_parser_exception_gives_error_page(site, monkeypatch):
    import htex.parser

    def boom(*a, **k):
        raise ValueError("파서 고장")

    monkeypatch.setattr(htex.parser, "parse_file", boom)
    p = site.test_root / "boom2.htex"
    p.write_text("\\title{x}\n", encoding="utf-8")
    st, _, body = get(site, "/boom2.htex")
    assert st == 500 and "파서 예외" in body
    st, _, _ = get(site, "/__htex/fragment?doc=/boom2.htex&label=x")
    assert st == 404
    st, _, body = get(site, "/")        # 목록은 계속 나온다
    assert st == 200


# ---------------------------------------------------------------- 명령줄
def test_cli_has_serve_and_build():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "htex", "serve", "--help"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0 and "--port" in out.stdout and "--host" in out.stdout
    out = subprocess.run([sys.executable, "-m", "htex", "build", "--help"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0 and "-o" in out.stdout
