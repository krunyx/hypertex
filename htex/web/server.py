"""htex serve: 일반 브라우저용 웹 서버 (명세 원칙 5, docs/interaction-protocol.md). (담당: G)

표준 라이브러리 http.server(ThreadingHTTPServer)만 쓴다.

주소
- /경로/문서.htex, /경로/문서.tex  → 파싱·렌더(web_fallback=True)한 text/html. (수정 시각, 크기)로 캐시.
- /경로/폴더/                       → 목록 페이지 (.htex·.tex 는 제목 표시). 폴더에 index.htex 가 있으면 그 문서.
- 그 밖의 파일                       → 정적 파일.
- /__htex/interact.js               → 상호작용 스크립트.
- /__htex/picture/<문서 경로>?node=…&이름=값  → htex.tikz.render_picture_node, image/svg+xml.
- /__htex/fragment?doc=<문서 주소>&label=<라벨>  → 라벨 블록 하나의 HTML 조각.
  doc 은 같은 서버의 경로(/a/b.htex) 또는 같은 출처의 절대 주소(http://이 서버/a/b.htex)만.
  외부 주소는 404 (서버가 대신 가져오지 않는다: SSRF 방지).

보안 (명세 7절)
- 루트 밖 경로 거부: '..', 인코딩된 %2e%2e, 역슬래시, 드라이브 문자, 루트 밖을 가리키는 심볼릭 링크 → 403.
- 숨김 파일·폴더('.' 으로 시작) → 404.
- 모든 응답에 X-Content-Type-Options: nosniff, HTML 에는 Content-Security-Policy
  (스크립트는 자기 출처만, object-src none, base-uri none, frame-ancestors none), Referrer-Policy.
- 기본 바인딩 127.0.0.1. GET·HEAD 만.
- 파서·렌더러 예외는 500 대신 오류 페이지(200 이 아니라 500 상태지만 HTML 본문은 읽을 수 있는 설명).
"""
from __future__ import annotations

import email.utils
import mimetypes
import math
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, quote, urlsplit

from .common import (CSP_HTML, CSP_SVG, DocCache, PathRejected, error_page, interact_js,
                     is_document, listing_entries, listing_page, plain_title, quick_title,
                     resolve_in_root, split_request_path, url_path, INTERACT_JS_PATH)
from .fragment import render_fragment

PREFIX = "/__htex/"
INTERACT_URL = "/__htex/interact.js"
FRAGMENT_URL = "/__htex/fragment"
PICTURE_URL = "/__htex/picture"
MAX_QUERY = 4096

EXTRA_TYPES = {
    ".htex": "text/x-hypertex; charset=utf-8",
    ".hsty": "text/plain; charset=utf-8",
    ".tex": "text/x-tex; charset=utf-8",
    ".bbl": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}


def head_extra_for(doc_urlpath: str) -> str:
    """서버가 문서마다 넣는 <head> 조각 (규약 2절)."""
    from .common import e
    return (f'<meta name="htex-picture-endpoint" content="{e(PICTURE_URL + doc_urlpath)}">\n'
            f'<meta name="htex-fragment-endpoint" content="{e(FRAGMENT_URL)}">\n'
            f'<script src="{e(INTERACT_URL)}" defer></script>')


class HtexServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, root: Path, addr: tuple[str, int], quiet: bool = False):
        self.root = Path(root).resolve()
        self.cache = DocCache()
        self.quiet = quiet
        super().__init__(addr, Handler)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{port}/"


class Handler(BaseHTTPRequestHandler):
    server: HtexServer
    server_version = "htex-serve/2.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ 공통
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        if not self.server.quiet:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send(self, status: int, body: bytes | str, ctype: str, *, csp: Optional[str] = None,
             extra: Optional[dict[str, str]] = None) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if csp:
            self.send_header("Content-Security-Policy", csp)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_html(self, status: int, text: str, extra: Optional[dict[str, str]] = None) -> None:
        self.send(status, text, "text/html; charset=utf-8", csp=CSP_HTML,
                  extra={"Cache-Control": "no-cache", **(extra or {})})

    def send_text(self, status: int, text: str) -> None:
        self.send(status, text + "\n", "text/plain; charset=utf-8",
                  csp="default-src 'none'; frame-ancestors 'none'",
                  extra={"Cache-Control": "no-store"})

    def send_error_page(self, status: int, message: str) -> None:
        phrase = HTTPStatus(status).phrase
        self.send_html(status, error_page(f"{status} {phrase}", message))

    # ------------------------------------------------------------ 메서드
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        try:
            self.route()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - 서버는 멈추지 않는다
            try:
                self.send_error_page(500, f"서버 내부 오류: {type(exc).__name__}")
            except Exception:  # noqa: BLE001
                pass

    def _not_allowed(self) -> None:
        self.send(405, "GET, HEAD 만 허용\n", "text/plain; charset=utf-8",
                  extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = _not_allowed  # type: ignore[assignment]

    def do_OPTIONS(self) -> None:
        self._not_allowed()

    # ------------------------------------------------------------ 경로 나누기
    def route(self) -> None:
        raw = self.path
        if not raw.startswith("/"):  # 절대 형식 요청(프록시식 GET http://…)은 받지 않는다
            self.send_error_page(400, "요청 주소는 /로 시작해야 한다.")
            return
        # urlsplit 은 '//호스트/…' 를 주소로 해석하므로 쓰지 않는다
        path, _, query = raw.split("#", 1)[0].partition("?")
        if len(query) > MAX_QUERY:
            self.send_text(414, "질의가 너무 길다")
            return
        if path.startswith(PREFIX) or path == PREFIX.rstrip("/"):
            self.route_internal(path, query)
            return
        try:
            target = resolve_in_root(self.server.root, split_request_path(path))
        except PathRejected as rej:
            self.send_error_page(rej.status, "이 경로는 열 수 없다.")
            return
        if target.is_dir():
            if not path.endswith("/"):
                self.redirect(path + "/" + (("?" + query) if query else ""))
                return
            self.serve_dir(target, path)
        elif target.is_file():
            if is_document(target):
                self.serve_document(target)
            else:
                self.serve_static(target)
        else:
            self.send_error_page(404, "문서를 찾을 수 없다.")

    def redirect(self, location: str) -> None:
        self.send(301, "", "text/plain; charset=utf-8", extra={"Location": location})

    def route_internal(self, path: str, query: str) -> None:
        if path == INTERACT_URL:
            self.send(200, interact_js(), "text/javascript; charset=utf-8",
                      extra={"Cache-Control": "no-cache"})
        elif path == FRAGMENT_URL:
            self.serve_fragment(query)
        elif path.startswith(PICTURE_URL + "/"):
            self.serve_picture(path[len(PICTURE_URL):], query)
        else:
            self.send_text(404, "없는 주소")

    # ------------------------------------------------------------ 문서
    def load_doc(self, target: Path, with_html: bool):
        root = self.server.root
        if with_html:
            def render_html(tree: dict[str, Any], p: Path) -> str:
                from ..html import render
                tree = self.resolve_links(tree, p)      # 다른 문서 참조 번호 (J)
                return render(tree, web_fallback=True, head_extra=head_extra_for(url_path(root, p)))
            return self.server.cache.get(target, render_html)
        return self.server.cache.get(target, None)

    def resolve_links(self, tree: dict[str, Any], doc_path: Path) -> dict[str, Any]:
        """다른 문서 \\ref 의 번호 채우기 (htex.linkres, 담당 J). 같은 루트 안의 상대 주소 문서만 읽는다
        (htex://·https:// 는 서버가 대신 가져오지 않는다: SSRF 방지). 실패하면 라벨 이름 그대로."""
        from ..linkres import local_doc_for_link, resolve_cross_refs

        root = self.server.root

        def loader(doc: str):
            p = local_doc_for_link(root, doc_path, doc)
            if p is None:
                return None
            if p == doc_path.resolve():
                return tree
            return self.load_doc(p, False).tree

        try:
            return resolve_cross_refs(tree, loader)
        except Exception:  # noqa: BLE001
            return tree

    def serve_document(self, target: Path) -> None:
        ent = self.load_doc(target, True)
        if ent.html is not None:
            self.send_html(200, ent.html)
            return
        try:
            source = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = None
        self.send_html(500, error_page("문서를 표시할 수 없다",
                                       "이 문서를 HTML로 바꾸는 중 내부 오류가 났다. 원문을 대신 보인다.",
                                       ent.error or "", source))

    def serve_static(self, target: Path) -> None:
        ext = target.suffix.lower()
        ctype = EXTRA_TYPES.get(ext) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") and "charset" not in ctype:
            ctype += "; charset=utf-8"
        st = target.stat()
        lm = email.utils.formatdate(st.st_mtime, usegmt=True)
        ims = self.headers.get("If-Modified-Since")
        if ims:
            try:
                t = email.utils.parsedate_to_datetime(ims).timestamp()
                if int(st.st_mtime) <= int(t):
                    self.send(304, b"", ctype, extra={"Last-Modified": lm})
                    return
            except (TypeError, ValueError, OverflowError):
                pass
        data = target.read_bytes()
        csp = None
        if ext in (".svg", ".html", ".htm", ".xml", ".xhtml"):
            # 사용자 파일인 SVG·HTML 이 스크립트를 담고 있어도 실행되지 않게
            csp = CSP_SVG if ext == ".svg" else "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; sandbox; frame-ancestors 'none'"
        self.send(200, data, ctype, csp=csp, extra={"Last-Modified": lm, "Cache-Control": "no-cache"})

    def serve_dir(self, target: Path, path: str) -> None:
        for name in ("index.htex", "index.md", "README.md"):
            idx = target / name
            if idx.is_file():
                self.serve_document(idx)
                return
        root = self.server.root

        def title_of(p: Path) -> str:
            if p.stat().st_size > 512 * 1024:
                return quick_title(p)
            ent = self.load_doc(p, False)
            return plain_title(ent.tree) or quick_title(p)

        entries = listing_entries(root, target, title_of, lambda p: quote(p.name))
        shown = "/" + "/".join(target.relative_to(root).parts) if target != root else "/"
        self.send_html(200, listing_page(shown, entries, parent=target != root))

    # ------------------------------------------------------------ 조각
    def doc_from_address(self, doc: str) -> Optional[Path]:
        """조각 주소의 doc 값 → 루트 안 문서 경로. 같은 서버의 문서가 아니면 None."""
        if not doc:
            return None
        u = urlsplit(doc)
        if u.scheme or u.netloc:
            if u.scheme not in ("http", "https"):
                return None
            host = self.headers.get("Host", "")
            if not host or u.netloc.lower() != host.lower():
                return None
        path = u.path
        if not path.startswith("/"):
            return None  # 상대 주소는 기준이 없어 받지 않는다 (스크립트가 절대 주소로 보낸다)
        try:
            p = resolve_in_root(self.server.root, split_request_path(path))
        except PathRejected:
            return None
        if not (p.is_file() and is_document(p)):
            return None
        return p

    def serve_fragment(self, query: str) -> None:
        q = dict(parse_qsl(query, keep_blank_values=True))
        doc, label = q.get("doc", ""), q.get("label", "")
        if not label or len(label) > 256:
            self.send_text(400, "label 이 필요하다")
            return
        p = self.doc_from_address(doc)
        if p is None:
            self.send_text(404, "이 서버의 문서가 아니다")
            return
        ent = self.load_doc(p, False)
        if ent.tree is None:
            self.send_text(404, "문서를 읽을 수 없다")
            return
        try:
            frag = render_fragment(ent.tree, label, doc_href=url_path(self.server.root, p))
        except Exception:  # noqa: BLE001
            self.send_text(500, "조각을 만들 수 없다")
            return
        if frag is None:
            self.send_text(404, "라벨을 찾을 수 없다")
            return
        self.send(200, frag, "text/html; charset=utf-8", csp=CSP_HTML,
                  extra={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------ 그림
    def serve_picture(self, doc_path: str, query: str) -> None:
        try:
            p = resolve_in_root(self.server.root, split_request_path(doc_path))
        except PathRejected as rej:
            self.send_text(rej.status, "이 경로는 열 수 없다")
            return
        if not (p.is_file() and is_document(p)):
            self.send_text(404, "문서를 찾을 수 없다")
            return
        pairs = parse_qsl(query, keep_blank_values=True)
        node = ""
        values: dict[str, float] = {}
        for k, v in pairs:
            if k == "node":
                node = v
                continue
            try:
                f = float(v)
            except ValueError:
                self.send_text(400, f"숫자가 아닌 값: {k}")
                return
            if not math.isfinite(f):
                self.send_text(400, f"유한하지 않은 값: {k}")
                return
            values[k] = f
        if not node:
            self.send_text(400, "node 가 필요하다")
            return
        ent = self.load_doc(p, False)
        if ent.tree is None:
            self.send_text(404, "문서를 읽을 수 없다")
            return
        declared = {pp.get("name") for pp in ent.tree.get("parameters") or []}
        values = {k: v for k, v in values.items() if k in declared}
        try:
            from ..tikz import render_picture_node
            res = render_picture_node(ent.tree, node, values)
        except Exception:  # noqa: BLE001 - 렌더러는 예외를 내지 않는 계약이지만 방어
            self.send_text(500, "그림 렌더러 오류")
            return
        svg = getattr(res, "svg", None)
        if not svg:
            why = "; ".join(getattr(res, "problems", None) or []) or "그림을 그릴 수 없다"
            self.send_text(404 if not _has_picture(ent.tree, node) else 422, why)
            return
        self.send(200, svg, "image/svg+xml; charset=utf-8", csp=CSP_SVG,
                  extra={"Cache-Control": "no-cache"})


def _has_picture(tree: dict[str, Any], node_id: str) -> bool:
    from .fragment import _find
    n, _, _ = _find(tree, node_id)
    return bool(n and n.get("kind") == "picture")


# ====================================================================== 진입점
def make_server(root: Path | str, host: str = "127.0.0.1", port: int = 8000,
                quiet: bool = False) -> HtexServer:
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    return HtexServer(root, (host, port), quiet=quiet)


def serve(root: Path | str, host: str = "127.0.0.1", port: int = 8000) -> int:
    srv = make_server(root, host, port)
    print(f"HyperTeX 문서 폴더 {srv.root} 를 {srv.url} 에서 엽니다 (멈추려면 Ctrl+C).", file=sys.stderr)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("경고: 127.0.0.1 이 아닌 주소에 바인딩했다. 같은 네트워크의 누구나 이 폴더를 읽을 수 있다.",
              file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


def serve_in_thread(root: Path | str, host: str = "127.0.0.1", port: int = 0) -> HtexServer:
    """테스트·뷰어용: 백그라운드 스레드에서 띄우고 서버를 돌려준다 (srv.shutdown() 으로 멈춤)."""
    srv = make_server(root, host, port, quiet=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


__all__ = ["make_server", "serve", "serve_in_thread", "HtexServer", "head_extra_for",
           "INTERACT_URL", "FRAGMENT_URL", "PICTURE_URL", "INTERACT_JS_PATH"]
