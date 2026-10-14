"""전용 뷰어의 Qt 없는 부분 (명세 2, 5, 7, 8절, docs/interaction-protocol.md). (담당: F)

Qt 쪽(app.py)은 요청 주소를 받아 `ViewerCore.respond(url, initiator)` 를 부르고 그 결과를 그대로
돌려주기만 한다. 주소 해석, 가져오기, 캐시, 시간 상한, 접근 규칙, 조각·그림 응답은 모두 여기 있다.

주소 체계 (뷰어 안에서 쓰는 주소 = 웹 엔진이 읽는 주소)
- 원격 문서  htex://호스트/경로        → 전송은 https://호스트/경로 (명세 2절)
- 로컬 문서  htexapp://doc-<뿌리키>/<상대경로>
             <뿌리키>는 사용자가 직접 연 파일의 폴더(뿌리) 하나를 가리킨다. 뿌리마다 출처(origin)가
             달라서 ../ 로 다른 뿌리나 그 위로 나갈 수 없다.
- 그림 주소  htexapp://picture/<문서키>?node=…&이름=값…   (규약 3절)
- 조각 주소  htexapp://fragment/<문서키>?doc=…&label=…   (규약 4절, doc 은 문서키 문서 기준 상대 주소도 됨)
- 스크립트   htexapp://asset/interact.js                    (G 의 htex/web/interact.js)
- 원문 보기  htexapp://source/<문서키>                      (J: 원문을 escape 한 읽기 전용 HTML)

테마 (J): core.theme 이 "light"/"dark" 이면 문서·오류·원문 페이지의 <html> 에 data-theme 을 넣는다
(렌더러 CSS 가 지원). "" 이면 넣지 않는다(시스템 설정, prefers-color-scheme).
다른 문서 참조 번호 (J): page_html 이 htex.linkres 로 다른 문서 \\ref 의 번호를 채운다(resolve_links).

보안 규칙
- 원격은 https 만 (리다이렉트도). 크기 상한 5MB, 시간 제한.
- 원격 문서를 해석할 때 파서의 로컬 파일 읽기 기준 폴더는 빈 임시 폴더 (원격 문서가 로컬 파일을 못 읽게).
- 로컬 문서·이미지는 등록된 뿌리 아래에서만. 웹 페이지(http/https)나 원격 문서(htex:)에서 시작된 요청은
  로컬 주소에 닿지 못한다. 원격 문서의 조각·전사는 원격 문서만 가리킬 수 있다.
- 문서 페이지에는 엄격한 CSP (스크립트는 htexapp: 출처만).
- 해석·변환은 문서당 2초 상한 (넘으면 오류 페이지).
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import posixpath
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .. import __version__
from ..parser import parse_text

USER_AGENT = f"HyperTeX-Viewer/{__version__} (HyperTeX 2.0; +htex)"
MAX_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 10.0
RENDER_LIMIT = 2.0          # 명세 7절: 문서당 렌더링 시간 상한
TRANSCLUDE_BUDGET = 3.0     # 전사 전체에 쓰는 시간 (가져오기 포함)
MAX_TRANSCLUSIONS = 20
REMOTE_TTL = 300.0          # 원격 원문 메모리 보관 시간 (새로고침하면 무시)

DOC_EXTS = (".htex", ".tex")
IMAGE_TYPES = {".svg": "image/svg+xml", ".png": "image/png",
               ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

CSP = ("default-src 'none'; script-src htexapp:; connect-src htexapp:; "
       "img-src htexapp: htex: https: blob:; style-src 'unsafe-inline'; font-src htexapp:; "
       "base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'; "
       "frame-ancestors 'none'")
META_CSP = CSP.replace("; frame-ancestors 'none'", "")   # <meta> 로는 frame-ancestors 를 못 준다

try:
    from ..web import INTERACT_JS_PATH as _INTERACT_JS      # G 의 상호작용 스크립트
except ImportError:                                           # pragma: no cover - G 이전
    _INTERACT_JS = Path(__file__).resolve().parent.parent / "web" / "interact.js"


# ====================================================================== 오류
class ViewerError(Exception):
    """사용자에게 오류 페이지로 보여 줄 문제. code 는 짧은 기계용 이름."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class FetchError(ViewerError):
    pass


class RenderTimeout(ViewerError):
    def __init__(self, limit: float):
        super().__init__("render-timeout",
                         f"문서 해석이 시간 상한({limit:g}초)을 넘어 중단했습니다.", 503)


class WebPage(Exception):
    """htex:// 로 열었지만 실제로는 일반 웹 페이지(HTML)였다. 호출한 쪽은 https 주소로 보낸다."""

    def __init__(self, url: str):
        super().__init__(url)
        self.url = url


# ====================================================================== 주소
@dataclass(frozen=True)
class Target:
    """주소 표시줄 입력을 해석한 결과.
    kind: 'remote' (url=htex://…), 'local' (path=파일), 'web' (url=http(s)://…, 웹 엔진이 그대로 연다)"""
    kind: str
    url: str = ""
    path: Optional[Path] = None


_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:[0-9]{1,5})?$|^\[[0-9A-Fa-f:.]+\](:[0-9]{1,5})?$")
_DOMAINISH = re.compile(r"^[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+(:[0-9]+)?(/|$)")


def is_doc_path(path: str) -> bool:
    p = urllib.parse.unquote(path).lower()
    return p.endswith(DOC_EXTS)


def normalize_htex(url: str) -> str:
    """htex:// 주소 정규화: 호스트 소문자, 기본 포트(443) 제거, 경로의 . / .. 정리, 조각(#…) 제거.
    잘못된 주소면 ViewerError."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme.lower() != "htex":
        raise ViewerError("bad-url", f"htex:// 주소가 아닙니다: {url}")
    netloc = parts.netloc
    if not netloc or "@" in netloc or not _HOST_RE.match(netloc):
        raise ViewerError("bad-url", f"호스트가 올바르지 않습니다: {url}")
    host, _, port = netloc.partition(":") if not netloc.startswith("[") else (netloc, "", "")
    host = host.lower().rstrip(".")
    if port == "443":
        port = ""
    if port and not (port.isdigit() and 0 < int(port) < 65536):
        raise ViewerError("bad-url", f"포트가 올바르지 않습니다: {url}")
    path = _norm_path(parts.path or "/")
    netloc = host + (":" + port if port else "")
    return urllib.parse.urlunsplit(("htex", netloc, path, parts.query, ""))


def _norm_path(path: str) -> str:
    trailing = path.endswith("/")
    norm = posixpath.normpath("/" + path.lstrip("/"))
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    if trailing and norm != "/":
        norm += "/"
    return norm


def htex_to_https(url: str) -> str:
    u = normalize_htex(url)
    return "https" + u[len("htex"):]


def https_to_htex(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != "https":
        raise ViewerError("insecure", f"https 주소가 아닙니다: {url}")
    return normalize_htex("htex" + url[len(parts.scheme):].split("#", 1)[0])


def split_fragment(url: str) -> tuple[str, str]:
    base, _, frag = url.partition("#")
    return base, frag


def join_url(base: str, ref: str) -> str:
    """상대 주소 풀기. htex: · htexapp: 처럼 urllib 이 모르는 스킴도 같은 규칙(RFC 3986)으로."""
    if _SCHEME_RE.match(ref):
        return ref
    m = _SCHEME_RE.match(base)
    if not m:
        return urllib.parse.urljoin(base, ref)
    scheme = m.group(1)
    joined = urllib.parse.urljoin("https" + base[len(scheme):], ref)
    return scheme + joined[len("https"):]


def classify_input(text: str, cwd: Optional[Path] = None) -> Target:
    """주소 표시줄·명령줄 입력 → Target.
    htex://…, https://….htex|.tex → remote / http(s)://그 밖 → web / file:… 또는 있는 경로 → local /
    example.org/a.htex 처럼 스킴 없는 도메인 → https 로 보고 위 규칙."""
    s = text.strip()
    if not s:
        raise ViewerError("empty", "주소가 비어 있습니다.")
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    m = _SCHEME_RE.match(s)
    scheme = m.group(1).lower() if m else ""
    if len(scheme) == 1 and len(s) > 2 and s[2] in "\\/":   # 윈도 드라이브 문자 C:\…
        scheme = ""
    if scheme == "htex":
        return Target("remote", normalize_htex(s.split("#", 1)[0]) + _frag(s))
    if scheme in ("https", "http"):
        path = urllib.parse.urlsplit(s).path
        if is_doc_path(path):
            if scheme == "http":
                raise ViewerError("insecure", "HyperTeX 문서는 HTTPS 로만 가져옵니다: " + s)
            return Target("remote", https_to_htex(s) + _frag(s))
        return Target("web", s)
    if scheme == "file":
        p = Path(urllib.request.url2pathname(urllib.parse.urlsplit(s).path))
        return Target("local", path=p.resolve())
    if scheme == "htexapp":
        return Target("internal", s)
    if scheme:
        raise ViewerError("bad-scheme", f"지원하지 않는 주소 형식입니다: {scheme}:")
    p = Path(os.path.expanduser(s))
    if not p.is_absolute():
        p = cwd / p
    if p.exists():
        return Target("local", path=p.resolve())
    if _DOMAINISH.match(s):
        return classify_input("https://" + s, cwd)
    raise ViewerError("not-found", f"파일을 찾을 수 없습니다: {s}", 404)


def _frag(s: str) -> str:
    return "#" + s.split("#", 1)[1] if "#" in s else ""


# ====================================================================== 가져오기
class HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트도 https 로만."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise FetchError("insecure-redirect", f"https 가 아닌 곳으로 리다이렉트: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_opener() -> urllib.request.OpenerDirector:
    # HTTPS 와 리다이렉트만. build_opener 는 file: · ftp: · data: · http: 처리기를 넣으므로 직접 짠다.
    op = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler(), urllib.request.UnknownHandler(),
              urllib.request.HTTPDefaultErrorHandler(), HTTPSOnlyRedirect(),
              urllib.request.HTTPErrorProcessor(), urllib.request.HTTPSHandler()):
        op.add_handler(h)
    return op


@dataclass
class FetchResult:
    url: str                 # 최종 https 주소 (리다이렉트 뒤)
    content: bytes
    content_type: str = ""


class Fetcher:
    """https 가져오기. opener 는 .open(Request, timeout=) → 응답(.read(n), .geturl(), .headers)
    인 무엇이든 된다 (테스트는 가짜를 넣는다)."""

    def __init__(self, opener=None, timeout: float = FETCH_TIMEOUT, max_bytes: int = MAX_BYTES,
                 user_agent: str = USER_AGENT, clock: Callable[[], float] = time.monotonic):
        self.opener = opener if opener is not None else default_opener()
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent
        self.clock = clock

    def fetch(self, url: str, accept: str = "text/x-hypertex, text/plain;q=0.8, */*;q=0.1") -> FetchResult:
        if urllib.parse.urlsplit(url).scheme.lower() != "https":
            raise FetchError("insecure", f"https 주소만 가져옵니다: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": accept})
        deadline = self.clock() + self.timeout
        try:
            resp = self.opener.open(req, timeout=self.timeout)
        except FetchError:
            raise
        except urllib.error.HTTPError as e:
            raise FetchError("http-error", f"서버 응답 {e.code}: {url}", 502) from None
        except (socket.timeout, TimeoutError):
            raise FetchError("timeout", f"시간 제한({self.timeout:g}초)을 넘었습니다: {url}", 504) from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)):
                raise FetchError("timeout", f"시간 제한({self.timeout:g}초)을 넘었습니다: {url}", 504) from None
            if isinstance(e.reason, FetchError):
                raise e.reason from None
            raise FetchError("network", f"가져오지 못했습니다: {url} ({e.reason})", 502) from None
        except (OSError, ValueError) as e:
            raise FetchError("network", f"가져오지 못했습니다: {url} ({e})", 502) from None
        try:
            final = resp.geturl() if hasattr(resp, "geturl") else url
            if urllib.parse.urlsplit(final).scheme.lower() != "https":
                raise FetchError("insecure-redirect", f"https 가 아닌 곳으로 옮겨졌습니다: {final}")
            headers = getattr(resp, "headers", None) or {}
            length = headers.get("Content-Length") if hasattr(headers, "get") else None
            if length and str(length).isdigit() and int(length) > self.max_bytes:
                raise FetchError("too-large", _too_large(self.max_bytes), 413)
            chunks, total = [], 0
            while True:
                if self.clock() > deadline:
                    raise FetchError("timeout", f"시간 제한({self.timeout:g}초)을 넘었습니다: {url}", 504)
                try:
                    chunk = resp.read(65536)
                except (socket.timeout, TimeoutError):
                    raise FetchError("timeout", f"시간 제한({self.timeout:g}초)을 넘었습니다: {url}", 504) from None
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_bytes:
                    raise FetchError("too-large", _too_large(self.max_bytes), 413)
                chunks.append(chunk)
            ctype = headers.get("Content-Type", "") if hasattr(headers, "get") else ""
            return FetchResult(final, b"".join(chunks), ctype or "")
        finally:
            close = getattr(resp, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass


def _too_large(n: int) -> str:
    return f"문서가 크기 상한({n // (1024 * 1024)}MB)을 넘습니다."


# ====================================================================== 시간 상한
def run_with_limit(fn: Callable[[], Any], limit: float) -> Any:
    """fn 을 다른 스레드에서 돌리고 limit 초 안에 끝나지 않으면 RenderTimeout.
    (파이썬 스레드는 죽일 수 없다. 파서는 반드시 끝나므로(명세 1절 원칙 2) 결과만 버린다.)"""
    box: dict[str, Any] = {}

    def work():
        try:
            box["value"] = fn()
        except BaseException as e:   # noqa: BLE001 - 호출한 스레드로 넘긴다
            box["error"] = e

    t = threading.Thread(target=work, name="htex-render", daemon=True)
    t.start()
    t.join(limit)
    if t.is_alive():
        raise RenderTimeout(limit)
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ====================================================================== 캐시
def default_cache_dir() -> Path:
    """플랫폼별 캐시 폴더 (macOS ~/Library/Caches, Windows %LOCALAPPDATA%, 그 밖 XDG)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "HyperTeX"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "HyperTeX" / "Cache"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "hypertex"


class TreeCache:
    """(주소, 내용 해시) → 문서 트리. 메모리(LRU) + 선택적 디스크.
    디스크에는 원격 문서만 둔다 (로컬 문서는 다른 로컬 파일(\\usemacros, \\input)에 기대어
    내용 해시만으로는 무효화할 수 없다)."""

    def __init__(self, disk_dir: Optional[Path] = None, capacity: int = 64):
        self.disk_dir = Path(disk_dir) if disk_dir else None
        self.capacity = capacity
        self._mem: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(address: str, sha: str) -> str:
        return hashlib.sha256(f"{__version__}\n{address}\n{sha}".encode("utf-8")).hexdigest()

    def get(self, address: str, sha: str) -> Optional[dict]:
        k = self.key(address, sha)
        with self._lock:
            if k in self._mem:
                self._mem.move_to_end(k)
                return self._mem[k]
        if self.disk_dir:
            f = self.disk_dir / "trees" / (k + ".json")
            try:
                tree = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            self._remember(k, tree)
            return tree
        return None

    def put(self, address: str, sha: str, tree: dict, disk: bool = False) -> None:
        k = self.key(address, sha)
        self._remember(k, tree)
        if disk and self.disk_dir:
            d = self.disk_dir / "trees"
            try:
                d.mkdir(parents=True, exist_ok=True)
                tmp = d / (k + f".{os.getpid()}.{threading.get_ident()}.tmp")
                tmp.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, d / (k + ".json"))
            except OSError:
                pass

    def _remember(self, k: str, tree: dict) -> None:
        with self._lock:
            self._mem[k] = tree
            self._mem.move_to_end(k)
            while len(self._mem) > self.capacity:
                self._mem.popitem(last=False)

    def __len__(self) -> int:
        return len(self._mem)


# ====================================================================== 히스토리
@dataclass
class HistoryEntry:
    url: str
    title: str = ""
    scroll: float = 0.0


class History:
    """뒤로·앞으로. visit 는 앞쪽 기록을 지운다. 같은 주소를 연달아 방문하면 하나로 친다."""

    def __init__(self, limit: int = 500):
        self.entries: list[HistoryEntry] = []
        self.index = -1
        self.limit = limit

    @property
    def current(self) -> Optional[HistoryEntry]:
        return self.entries[self.index] if 0 <= self.index < len(self.entries) else None

    def visit(self, url: str, title: str = "") -> HistoryEntry:
        cur = self.current
        if cur is not None and cur.url == url:
            if title:
                cur.title = title
            return cur
        del self.entries[self.index + 1:]
        e = HistoryEntry(url, title)
        self.entries.append(e)
        if len(self.entries) > self.limit:
            del self.entries[0:len(self.entries) - self.limit]
        self.index = len(self.entries) - 1
        return e

    def can_back(self) -> bool:
        return self.index > 0

    def can_forward(self) -> bool:
        return self.index < len(self.entries) - 1

    def back(self) -> Optional[HistoryEntry]:
        if not self.can_back():
            return None
        self.index -= 1
        return self.current

    def forward(self) -> Optional[HistoryEntry]:
        if not self.can_forward():
            return None
        self.index += 1
        return self.current

    def set_title(self, title: str) -> None:
        if self.current:
            self.current.title = title


# ====================================================================== 응답
@dataclass
class Response:
    """Qt 쪽이 그대로 돌려줄 것. fail 이면 요청 실패(fetch 가 거부됨), redirect 면 그 주소로."""
    status: int = 200
    mime: str = "text/html"
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    redirect: Optional[str] = None
    fail: bool = False
    record: Optional["DocRecord"] = None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


@dataclass
class DocRecord:
    key: str
    address: str                 # htex://… 또는 htexapp://doc-…/…
    tree: dict
    remote: bool
    elapsed: float = 0.0
    html: Optional[str] = None
    source: str = ""             # 원문 (원문 보기용)

    @property
    def diagnostics(self) -> list[dict]:
        return self.tree.get("diagnostics") or []

    def counts(self) -> tuple[int, int]:
        ds = self.diagnostics
        err = sum(1 for d in ds if d.get("severity") == "error")
        return err, len(ds) - err

    @property
    def title(self) -> str:
        from ..html.render import _plain
        return _plain((self.tree.get("meta") or {}).get("title") or []) or ""


def _empty_dir() -> Path:
    global _EMPTY
    try:
        return _EMPTY
    except NameError:
        pass
    _EMPTY = Path(tempfile.mkdtemp(prefix="htex-viewer-empty-"))
    return _EMPTY


# ====================================================================== 핵심
class ViewerCore:
    def __init__(self, fetcher: Optional[Fetcher] = None, cache: Optional[TreeCache] = None,
                 parse: Callable[..., dict] = parse_text, render_limit: float = RENDER_LIMIT,
                 transclude_budget: float = TRANSCLUDE_BUDGET,
                 picture_renderer: Optional[Callable[..., Any]] = None,
                 interact_js: Optional[Path] = None, clock: Callable[[], float] = time.monotonic,
                 link_budget: float = 1.0):
        self.fetcher = fetcher or Fetcher()
        self.cache = cache if cache is not None else TreeCache()
        self.parse = parse
        self.render_limit = render_limit
        self.transclude_budget = transclude_budget
        self.picture_renderer = picture_renderer
        self.interact_js = interact_js or _INTERACT_JS
        self.clock = clock
        self.link_budget = link_budget
        self.theme = ""              # "", "light", "dark" (J)
        self.roots: dict[str, Path] = {}
        self.records: "OrderedDict[str, DocRecord]" = OrderedDict()
        self.by_address: dict[str, str] = {}
        self._remote_text: dict[str, tuple[float, str, str]] = {}   # 주소 → (시각, 최종 주소, 원문)
        self._lock = threading.RLock()

    # ------------------------------------------------------------ 로컬 뿌리
    def allow_root(self, folder: Path) -> str:
        root = Path(folder).resolve()
        key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
        with self._lock:
            self.roots[key] = root
        return key

    def local_url(self, path: Path, register: bool = True) -> str:
        """사용자가 직접 연 로컬 파일 → htexapp://doc-<뿌리키>/<이름>. register 면 그 폴더를 뿌리로 등록."""
        p = Path(path).resolve()
        with self._lock:
            for key, root in self.roots.items():
                if _under(p, root):
                    rel = p.relative_to(root).as_posix()
                    return f"htexapp://doc-{key}/" + urllib.parse.quote(rel)
        if not register:
            raise ViewerError("forbidden", f"열어 둔 폴더 밖의 파일입니다: {p}", 403)
        key = self.allow_root(p.parent)
        return f"htexapp://doc-{key}/" + urllib.parse.quote(p.name)

    def local_path(self, url: str) -> Path:
        """htexapp://doc-<키>/<경로> → 파일 경로. 뿌리 밖·모르는 뿌리면 ViewerError(403)."""
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc.lower()
        if not host.startswith("doc-"):
            raise ViewerError("bad-url", f"로컬 문서 주소가 아닙니다: {url}")
        root = self.roots.get(host[4:])
        if root is None:
            raise ViewerError("forbidden", "열어 둔 폴더가 아닙니다.", 403)
        rel = urllib.parse.unquote(parts.path).lstrip("/")
        if "\x00" in rel or "\\" in rel:
            raise ViewerError("forbidden", "허용되지 않는 경로입니다.", 403)
        p = (root / rel).resolve()
        if not _under(p, root):
            raise ViewerError("forbidden", "열어 둔 폴더 밖의 파일입니다.", 403)
        return p

    def display_address(self, url: str) -> str:
        """주소 표시줄에 보일 주소. 로컬 문서는 파일 경로, 원문 보기는 "원문: <문서 주소>"."""
        if url.startswith("htexapp://source/"):
            rec = self._record_from_path(urllib.parse.urlsplit(url).path)
            if rec is not None:
                return "원문: " + self.display_address(rec.address)
        if url.startswith("htexapp://doc-"):
            base, frag = split_fragment(url)
            try:
                return str(self.local_path(base)) + ("#" + frag if frag else "")
            except ViewerError:
                return url
        return url

    def input_to_url(self, text: str, cwd: Optional[Path] = None) -> str:
        """주소 표시줄 입력 → 웹 엔진에 줄 주소."""
        t = classify_input(text, cwd)
        if t.kind == "local":
            return self.local_url(t.path)
        return t.url

    # ------------------------------------------------------------ 불러오기
    def load(self, address: str, reload: bool = False) -> DocRecord:
        """문서 주소(조각 없이) → DocRecord. 실패하면 ViewerError, 웹 페이지면 WebPage."""
        address = split_fragment(address)[0]
        if address.lower().startswith("htex:"):
            address = normalize_htex(address)
            text, address = self._remote_source(address, reload)
            remote = True
            base_dir, parse_url = _empty_dir(), address
        elif address.startswith("htexapp://doc-"):
            path = self.local_path(address)
            if path.suffix.lower() not in DOC_EXTS:
                raise ViewerError("not-document", f"HyperTeX 문서가 아닙니다: {path.name}", 415)
            text = _read_local(path)
            remote = False
            base_dir, parse_url = path.parent, path.name
        else:
            raise ViewerError("bad-url", f"문서 주소가 아닙니다: {address}")

        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = hashlib.sha256(f"{address}\n{sha}".encode("utf-8")).hexdigest()[:20]
        with self._lock:
            rec = self.records.get(key)
            if rec is not None and not reload:
                self.records.move_to_end(key)
                self.by_address[address] = key
                return rec
        tree = None if reload else self.cache.get(address, sha)
        t0 = self.clock()
        if tree is None:
            tree = run_with_limit(lambda: self.parse(text, url=parse_url, base_dir=base_dir),
                                  self.render_limit)
            self.cache.put(address, sha, tree, disk=remote)
        rec = DocRecord(key, address, tree, remote, elapsed=self.clock() - t0, source=text)
        with self._lock:
            self.records[key] = rec
            self.by_address[address] = key
            while len(self.records) > 200:
                self.records.popitem(last=False)
        return rec

    def _remote_source(self, address: str, reload: bool) -> tuple[str, str]:
        now = self.clock()
        with self._lock:
            hit = self._remote_text.get(address)
        if hit and not reload and now - hit[0] < REMOTE_TTL:
            return hit[2], hit[1]
        res = self.fetcher.fetch(htex_to_https(address))
        ctype = res.content_type.split(";")[0].strip().lower()
        if ctype in ("text/html", "application/xhtml+xml"):
            raise WebPage(res.url)
        final = https_to_htex(res.url)
        text = _decode(res.content)
        with self._lock:
            self._remote_text[address] = (now, final, text)
            self._remote_text[final] = (now, final, text)
        return text, final

    def has_remote(self, address: str) -> bool:
        """그 원격 문서의 원문을 이미 가져와 메모리에 두었나 (시간이 지났어도)."""
        with self._lock:
            return normalize_htex(address) in self._remote_text

    def record_for(self, url: str) -> Optional[DocRecord]:
        base = split_fragment(url)[0]
        if base.lower().startswith("htex:"):
            try:
                base = normalize_htex(base)
            except ViewerError:
                return None
        with self._lock:
            key = self.by_address.get(base)
            return self.records.get(key) if key else None

    def invalidate(self, url: str) -> None:
        base = split_fragment(url)[0]
        with self._lock:
            self._remote_text.pop(base, None)
            key = self.by_address.pop(base, None)
            if key:
                self.records.pop(key, None)

    # ------------------------------------------------------------ 페이지
    def head_extra(self, rec: DocRecord) -> str:
        return "\n".join([
            f'<meta http-equiv="Content-Security-Policy" content="{_a(META_CSP)}">',
            f'<meta name="htex-picture-endpoint" content="htexapp://picture/{rec.key}">',
            f'<meta name="htex-fragment-endpoint" content="htexapp://fragment/{rec.key}">',
            f"<style>{VIEWER_CSS}</style>",
            '<script src="htexapp://asset/interact.js" defer></script>',
        ])

    def page_html(self, rec: DocRecord) -> str:
        if rec.html is not None:
            return rec.html
        from ..html import render
        tree = self.resolve_links(rec)
        page = run_with_limit(lambda: render(tree, head_extra=self.head_extra(rec)),
                              self.render_limit)
        page = self._fill_transclusions(rec, page)
        rec.html = page
        return page

    def link_target(self, base: "DocRecord", doc: str) -> str:
        """base 문서 기준 다른 문서 주소 doc → 불러올 수 있는 문서 주소. 접근 규칙을 어기면 ViewerError."""
        target = join_url(base.address, doc) if doc else base.address
        target = split_fragment(target)[0]
        if target.lower().startswith("https:"):
            target = https_to_htex(target)
        if target.lower().startswith("htex:"):
            target = normalize_htex(target)
        if base.remote and not target.lower().startswith("htex:"):
            raise ViewerError("forbidden", "원격 문서는 로컬 문서를 가리킬 수 없습니다.", 403)
        if (not base.remote and target.startswith("htexapp://")
                and urllib.parse.urlsplit(target).netloc != urllib.parse.urlsplit(base.address).netloc):
            raise ViewerError("forbidden", "다른 폴더의 로컬 문서는 가리킬 수 없습니다.", 403)
        if not (target.lower().startswith("htex:") or target.startswith("htexapp://doc-")):
            raise ViewerError("bad-url", f"문서 주소가 아닙니다: {target}")
        return target

    def resolve_links(self, rec: "DocRecord") -> dict:
        """다른 문서 \\ref 의 번호 채우기 (htex.linkres, J). 다른 문서는 이 core 의 캐시·가져오기로 불러오고,
        실패(네트워크, 접근 금지, 시간 예산 1초 초과)는 조용히 넘어간다 → 라벨 이름이 보인다."""
        from ..linkres import resolve_cross_refs

        def loader(doc: str) -> Optional[dict]:
            try:
                target = self.link_target(rec, doc)
                if target == rec.address:
                    return rec.tree
                if not rec.remote and target.lower().startswith("htex:") and not self.has_remote(target):
                    return None     # 로컬 문서를 열었다고 네트워크에 나가지 않는다 (이미 가져온 것만)
                return self.load(target).tree
            except (ViewerError, WebPage):
                return None

        try:
            return resolve_cross_refs(rec.tree, loader, budget=self.link_budget)
        except Exception:   # noqa: BLE001 - 번호 채우기 실패로 문서가 안 보이면 안 된다
            return rec.tree

    _TRANSCLUSION = re.compile(
        r'<div class="htex-transclusion"( id="[^"]*")? data-href="([^"]*)">.*?</div>', re.S)

    def _fill_transclusions(self, rec: DocRecord, page: str) -> str:
        """전사 자리 표시를 대상 블록으로 바꾼다 (한 단계만, 전사된 조각 안의 전사는 링크로 둔다)."""
        deadline = self.clock() + self.transclude_budget
        count = 0

        def repl(m: re.Match) -> str:
            nonlocal count
            count += 1
            href = _html.unescape(m.group(2))
            if count > MAX_TRANSCLUSIONS or self.clock() > deadline:
                return m.group(0)
            try:
                frag = self.fragment_for(rec, href, budget_deadline=deadline)
            except (ViewerError, WebPage):
                frag = None
            if frag is None:
                return m.group(0).replace('class="htex-transclusion"',
                                          'class="htex-transclusion htex-transclusion-failed"', 1)
            frag = _FRAG_HEAD.sub("", frag, count=1)
            target = _a(self._absolute(rec, href))
            return (f'<div class="htex-transclusion htex-transcluded"{m.group(1) or ""} '
                    f'data-href="{m.group(2)}">{frag}'
                    f'<a class="htex-transclusion-source" href="{target}">출처: {_e(href)}</a></div>')

        return self._TRANSCLUSION.sub(repl, page)

    def _absolute(self, rec: DocRecord, href: str) -> str:
        return join_url(rec.address, href)

    def fragment_for(self, base: DocRecord, href: str, label: Optional[str] = None,
                     budget_deadline: Optional[float] = None) -> Optional[str]:
        """base 문서 기준 href(문서#라벨) 의 라벨 블록 HTML 조각. 라벨이 없으면 None."""
        doc, frag = split_fragment(href)
        label = label if label is not None else urllib.parse.unquote(frag)
        if not label:
            return None
        target = join_url(base.address, doc) if doc else base.address
        if target.lower().startswith("https:"):
            target = https_to_htex(target)
        if base.remote and not target.lower().startswith("htex:"):
            raise ViewerError("forbidden", "원격 문서는 로컬 문서를 가리킬 수 없습니다.", 403)
        if (not base.remote and target.startswith("htexapp://")
                and urllib.parse.urlsplit(target).netloc != urllib.parse.urlsplit(base.address).netloc):
            raise ViewerError("forbidden", "다른 폴더의 로컬 문서는 가리킬 수 없습니다.", 403)
        if not (target.lower().startswith("htex:") or target.startswith("htexapp://doc-")):
            raise ViewerError("bad-url", f"문서 주소가 아닙니다: {target}")
        if budget_deadline is not None and self.clock() > budget_deadline:
            return None
        rec = base if target == base.address else self.load(target)
        return fragment_html(rec.tree, label, rec.address)

    # ------------------------------------------------------------ 요청 응답
    def respond(self, url: str, initiator: str = "", reload: bool = False) -> Response:
        """웹 엔진의 htex: · htexapp: 요청 하나에 대한 응답. 예외를 던지지 않는다."""
        init = (initiator or "").lower()
        if init in ("null",):
            init = ""
        try:
            parts = urllib.parse.urlsplit(url)
            scheme = parts.scheme.lower()
            if scheme == "htex":
                return self._respond_htex(url, init, reload)
            if scheme == "htexapp":
                host = parts.netloc.lower()
                if host.startswith("doc-"):
                    return self._respond_local(url, host, init, reload)
                if init and not init.startswith(("htex:", "htexapp:")):
                    return _fail(403, "웹 페이지에서는 쓸 수 없는 주소입니다.")
                if host == "asset":
                    return self._respond_asset(parts.path)
                if host == "picture":
                    return self._respond_picture(parts, init)
                if host == "fragment":
                    return self._respond_fragment(parts, init)
                if host == "source":
                    return self._respond_source(parts, init)
            return _fail(404, "알 수 없는 주소입니다.")
        except Exception as e:   # noqa: BLE001 - 뷰어가 멈추지 않게
            return self._error(ViewerError("internal", f"내부 오류: {type(e).__name__}: {e}", 500), url)

    def themed(self, page: str) -> str:
        """<html> 에 data-theme (J). 시스템 설정이면 그대로."""
        return with_theme(page, self.theme)

    def _page_response(self, rec: DocRecord, url: str) -> Response:
        try:
            page = self.page_html(rec)
        except ViewerError as e:
            return self._error(e, url)
        return Response(200, "text/html", self.themed(page).encode("utf-8"),
                        {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                         "Referrer-Policy": "no-referrer"}, record=rec)

    def _respond_htex(self, url: str, init: str, reload: bool) -> Response:
        try:
            address = normalize_htex(split_fragment(url)[0])
        except ViewerError as e:
            return self._error(e, url)
        path = urllib.parse.urlsplit(address).path
        ext = posixpath.splitext(urllib.parse.unquote(path))[1].lower()
        if ext in IMAGE_TYPES:
            try:
                res = self.fetcher.fetch(htex_to_https(address), accept="image/*")
            except ViewerError:
                return _fail(502, "그림을 가져오지 못했습니다.")
            ctype = res.content_type.split(";")[0].strip().lower()
            if ctype not in IMAGE_TYPES.values():
                ctype = IMAGE_TYPES[ext]
            return Response(200, ctype, res.content, {"X-Content-Type-Options": "nosniff",
                                                      "Content-Security-Policy": "default-src 'none'"})
        try:
            rec = self.load(address, reload=reload)
        except WebPage as w:
            return Response(302, redirect=w.url)
        except ViewerError as e:
            return self._error(e, url)
        if rec.address != address:          # 리다이렉트로 주소가 바뀌었다
            frag = split_fragment(url)[1]
            return Response(302, redirect=rec.address + ("#" + frag if frag else ""))
        return self._page_response(rec, url)

    def _respond_local(self, url: str, host: str, init: str, reload: bool) -> Response:
        # 로컬 문서에는 사용자가 직접 연 것(initiator 없음)이나 같은 뿌리의 문서만 닿는다.
        if init and init != f"htexapp://{host}":
            return self._error(ViewerError("forbidden", "다른 출처에서 로컬 파일을 열 수 없습니다.", 403), url)
        try:
            path = self.local_path(split_fragment(url)[0])
        except ViewerError as e:
            return self._error(e, url)
        ext = path.suffix.lower()
        if ext in IMAGE_TYPES:
            try:
                if path.stat().st_size > MAX_BYTES:
                    return _fail(413, _too_large(MAX_BYTES))
                return Response(200, IMAGE_TYPES[ext], path.read_bytes(),
                                {"X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "default-src 'none'"})
            except OSError:
                return _fail(404, "그림 파일이 없습니다.")
        try:
            rec = self.load(split_fragment(url)[0], reload=reload)
        except ViewerError as e:
            return self._error(e, url)
        return self._page_response(rec, url)

    def _error(self, err: ViewerError, url: str = "") -> Response:
        r = error_page(err, url)
        if self.theme:
            r.body = self.themed(r.text).encode("utf-8")
        return r

    def _respond_source(self, parts, init: str) -> Response:
        """원문 보기 (J): 원문을 escape 해 <pre> 로. 스크립트는 아무것도 실행되지 않는다(CSP default-src 'none')."""
        rec = self._record_from_path(parts.path)
        if rec is None:
            return _fail(404, "문서를 찾을 수 없습니다.")
        if init.startswith("htex:") and not rec.remote:
            return _fail(403, "허용되지 않는 요청입니다.")
        page = source_page(rec.source, self.display_address(rec.address), rec.title)
        return Response(200, "text/html", self.themed(page).encode("utf-8"),
                        {"Content-Security-Policy": SOURCE_CSP, "X-Content-Type-Options": "nosniff"})

    def source_url(self, url: str) -> Optional[str]:
        """문서 주소 → 그 문서의 원문 보기 주소 (불러온 문서가 아니면 None)."""
        rec = self.record_for(url)
        return f"htexapp://source/{rec.key}" if rec is not None else None

    def _respond_asset(self, path: str) -> Response:
        if path.strip("/") != "interact.js":
            return _fail(404, "없는 자원입니다.")
        try:
            body = self.interact_js.read_bytes()
        except OSError:
            body = b"/* htex/web/interact.js \xec\x97\x86\xec\x9d\x8c (G) */\n"
        return Response(200, "text/javascript", body, {"X-Content-Type-Options": "nosniff"})

    def _cors(self, init: str) -> dict[str, str]:
        return {"Access-Control-Allow-Origin": init} if init else {}

    def _record_from_path(self, path: str) -> Optional[DocRecord]:
        key = path.strip("/")
        with self._lock:
            return self.records.get(key)

    def _respond_picture(self, parts, init: str) -> Response:
        rec = self._record_from_path(parts.path)
        if rec is None:
            return _fail(404, "문서를 찾을 수 없습니다.")
        if init.startswith("htex:") and not rec.remote:
            return _fail(403, "허용되지 않는 요청입니다.")
        q = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        node = (q.pop("node", [""]) or [""])[0]
        if not node:
            return _fail(400, "node 가 없습니다.")
        values: dict[str, float] = {}
        for k, v in q.items():
            try:
                values[k] = float(v[-1])
            except ValueError:
                return _fail(400, f"값이 수가 아닙니다: {k}")
        if node not in _picture_ids(rec.tree):
            return _fail(404, "그 그림이 없습니다.")
        svg = picture_svg(rec.tree, node, values, self.picture_renderer)
        if svg is None:
            return _fail(422, "그림을 그리지 못했습니다.")     # G 서버와 같은 코드
        headers = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                   "X-Content-Type-Options": "nosniff", **self._cors(init)}
        return Response(200, "image/svg+xml", svg.encode("utf-8"), headers)

    def _respond_fragment(self, parts, init: str) -> Response:
        rec = self._record_from_path(parts.path)
        q = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        doc = (q.get("doc") or [""])[0]
        label = (q.get("label") or [""])[0]
        if rec is None:
            return _fail(404, "문서를 찾을 수 없습니다.")
        if not label and "#" in doc:
            doc, label = doc.split("#", 1)
        if not label:
            return _fail(400, "label 이 없습니다.")
        if init.startswith("htex:") and not rec.remote:
            return _fail(403, "허용되지 않는 요청입니다.")
        try:
            frag = self.fragment_for(rec, doc, label=label)
        except WebPage:
            return _fail(404, "HyperTeX 문서가 아닙니다.")
        except ViewerError as e:
            return _fail(e.status if 400 <= e.status < 600 else 400, e.message)
        if frag is None:
            return _fail(404, "라벨을 찾을 수 없습니다.")
        return Response(200, "text/html", frag.encode("utf-8"),
                        {"X-Content-Type-Options": "nosniff", **self._cors(init)})


# ====================================================================== 조각·그림
_FRAG_HEAD = re.compile(r'<div class="htex-fragment-head">.*?</div>\n?', re.S)
_TAG = re.compile(r"<[A-Za-z][^<>]*>")
_ID_ATTR = re.compile(r'\s(?:id|for|aria-labelledby|aria-describedby)="[^"]*"')
_SAME_DOC_HREF = re.compile(r'(\shref=")#')


def _rewrite_tags(body: str, address: str) -> str:
    """태그 안에서만: id 류 속성 지우기, 같은 문서 링크(#…)를 address#… 로.
    (본문 텍스트의 < 는 모두 escape 되어 있으므로 태그 경계가 분명하다.)"""
    def fix(m: re.Match) -> str:
        tag = _ID_ATTR.sub("", m.group(0))
        if tag.startswith("<a "):
            tag = _SAME_DOC_HREF.sub(lambda h: h.group(1) + _a(address) + "#", tag)
        return tag
    return _TAG.sub(fix, body)


def fragment_html(tree: dict, label: str, address: str) -> Optional[str]:
    """문서 트리의 라벨 블록 하나 → HTML 조각 (규약 4절). G 의 htex.web.render_fragment 를 쓰고,
    - 상대 주소는 address 기준으로 (urljoin 은 htex: · htexapp: 를 몰라 join_url 로 직접),
    - id 류 속성은 지운다 (끼워 넣을 문서의 id 와 겹치지 않게)."""
    from ..web import render_fragment
    try:
        body = render_fragment(tree, label, doc_href=address, web_fallback=False,
                               doc_url=lambda u: join_url(address, u))
    except Exception:   # noqa: BLE001 - 조각 하나 실패로 뷰어가 멈추지 않게
        return None
    if body is None:
        return None
    body = _rewrite_tags(body, address)
    return body.replace('<div class="htex-fragment"',
                        f'<div class="htex-fragment" data-source="{_a(address)}"', 1)


def _picture_ids(tree: dict) -> set[str]:
    out: set[str] = set()
    stack: list[Any] = list(tree.get("body") or [])
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("kind") == "picture" and x.get("id"):
                out.add(x["id"])
            stack.extend(v for k, v in x.items() if isinstance(v, (list, dict)) and k != "math")
        elif isinstance(x, list):
            stack.extend(x)
    return out


def picture_svg(tree: dict, node_id: str, values: dict[str, float],
                renderer: Optional[Callable[..., Any]] = None) -> Optional[str]:
    """그림 주소 응답 본문. htex.tikz.render_picture_node 결과의 svg (stub 이면 None)."""
    if renderer is None:
        from ..tikz import render_picture_node as renderer
    try:
        result = run_with_limit(lambda: renderer(tree, node_id, values), RENDER_LIMIT)
    except Exception:   # noqa: BLE001
        return None
    svg = getattr(result, "svg", None)
    if not isinstance(svg, str) or not svg.lstrip().startswith("<svg"):
        return None
    return svg


# ====================================================================== 도우미
def _under(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def _read_local(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ViewerError("too-large", _too_large(MAX_BYTES), 413)
        return _decode(path.read_bytes())
    except FileNotFoundError:
        raise ViewerError("not-found", f"파일이 없습니다: {path.name}", 404) from None
    except IsADirectoryError:
        raise ViewerError("not-found", f"폴더입니다: {path.name}", 404) from None
    except OSError as e:
        raise ViewerError("io", f"파일을 읽지 못했습니다: {path.name} ({e})", 500) from None


def _decode(data: bytes) -> str:
    """UTF-8 고정 (명세 2절). BOM 은 떼고, 깨진 바이트는 대체 문자로."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", "replace")


def _e(s: Any) -> str:
    return _html.escape(str(s), quote=False)


def _a(s: Any) -> str:
    return _html.escape(str(s), quote=True)


def _fail(status: int, message: str) -> Response:
    return Response(status, "text/plain", message.encode("utf-8"), fail=True)


def error_page(err: ViewerError, url: str = "") -> Response:
    page = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<meta http-equiv="Content-Security-Policy" content="{_a("default-src 'none'; style-src 'unsafe-inline'")}">
<title>열 수 없음</title>
<style>{ERROR_CSS}</style></head>
<body><main class="htex-viewer-error" data-code="{_a(err.code)}">
<p class="code">{_e(err.status)} · {_e(err.code)}</p>
<h1>문서를 열 수 없습니다</h1>
<p class="msg">{_e(err.message)}</p>
{f'<p class="url"><code>{_e(url)}</code></p>' if url else ''}
</main></body></html>
"""
    return Response(200, "text/html", page.encode("utf-8"),
                    {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


_HTML_TAG = re.compile(r"<html\b([^>]*)>", re.I)


def with_theme(page: str, theme: str) -> str:
    """첫 <html …> 태그에 data-theme 을 넣는다 (light/dark 만, 이미 있으면 바꾼다)."""
    if theme not in ("light", "dark"):
        return page

    def fix(m: re.Match) -> str:
        attrs = re.sub(r'\sdata-theme="[^"]*"', "", m.group(1))
        return f'<html{attrs} data-theme="{theme}">'
    return _HTML_TAG.sub(fix, page, count=1)


SOURCE_CSP = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"


def source_page(text: str, address: str, title: str = "") -> str:
    """원문 보기 페이지 (읽기 전용, 고정폭, 줄 번호). 원문은 모두 escape 한다."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    width = len(str(max(1, len(lines))))
    rows = "".join(f'<span class="l" style="--w:{width + 2}ch"><span class="ln">{i:>{width}}</span>{_e(line)}\n</span>'
                   for i, line in enumerate(lines, 1))
    name = re.split(r"[/\\]", address)[-1] or address   # 윈도 경로(\)도
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<meta http-equiv="Content-Security-Policy" content="{_a("default-src 'none'; style-src 'unsafe-inline'")}">
<title>원문: {_e(name)}</title>
<style>{SOURCE_CSS}</style></head>
<body><header class="htex-source-head"><strong>원문 (읽기 전용)</strong> <code>{_e(address)}</code>{(" · " + _e(title)) if title else ""}</header>
<pre class="htex-source">{rows}</pre></body></html>
"""


VIEWER_CSS = """
.htex-transclusion.htex-transcluded{border:0;border-left:3px solid var(--accent,currentColor);
 border-radius:0 6px 6px 0;padding:.3rem 1rem .5rem;font-family:inherit;font-size:inherit}
.htex-transcluded .htex-theorem{border-left:0;padding-left:0;margin:.4rem 0}
.htex-transclusion-source{display:block;font-family:var(--sans-font,sans-serif);font-size:.78em;
 opacity:.75;margin-top:.2rem;text-align:right}
.htex-transclusion-failed{opacity:.75}
"""

_THEME_VARS = """
:root{color-scheme:light dark;--fg:#1f2328;--muted:#656d76;--bg:#fbfaf7;--accent:#b42318;--rule:#d8d6d0}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fg:#e6e6e6;--muted:#9aa1a9;--bg:#16171a;--accent:#ff8a7a;--rule:#33353a}}
:root[data-theme="dark"]{color-scheme:dark;--fg:#e6e6e6;--muted:#9aa1a9;--bg:#16171a;--accent:#ff8a7a;--rule:#33353a}
:root[data-theme="light"]{color-scheme:light}"""

SOURCE_CSS = _THEME_VARS + """
body{margin:0;background:var(--bg);color:var(--fg)}
.htex-source-head{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--rule);
 padding:.5rem 1rem;font:13px/1.5 system-ui,-apple-system,"Segoe UI","Noto Sans KR",sans-serif}
.htex-source-head code{color:var(--muted);word-break:break-all}
.htex-source{margin:0;padding:.75rem 1rem 2rem;font:13px/1.55 ui-monospace,"SF Mono",Menlo,Consolas,"D2Coding","Noto Sans Mono CJK KR",monospace;
 white-space:pre-wrap;overflow-wrap:anywhere;tab-size:4}
.l{display:block;padding-left:var(--w);text-indent:calc(-1 * var(--w))}
.ln{display:inline-block;width:var(--w);text-indent:0;padding-right:2ch;box-sizing:border-box;color:var(--muted);opacity:.6;
 user-select:none;-webkit-user-select:none;text-align:right}
"""

ERROR_CSS = _THEME_VARS + """
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI","Noto Sans KR",sans-serif}
main{max-width:40rem;margin:12vh auto;padding:0 1.5rem}
h1{font-size:1.5rem;margin:.2em 0 .6em}
.code{color:var(--accent);font:600 .85rem ui-monospace,monospace;letter-spacing:.04em;margin:0}
.msg{margin:0 0 1em}
.url code{color:var(--muted);word-break:break-all;font-size:.85rem}
"""
