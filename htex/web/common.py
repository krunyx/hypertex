"""서버와 정적 빌드가 함께 쓰는 도우미. (담당: G)

- 경로 안전 검사(resolve_request_path): 요청 경로 → 루트 폴더 안의 실제 경로, 아니면 거부 사유.
- 문서 캐시(DocCache): 파일 수정 시각(ns)+크기로 파싱 결과와 HTML을 캐시. 스레드 안전.
- 목록 페이지·오류 페이지 HTML. 본문 CSS는 렌더러(htex.html.style.CSS)를 그대로 쓴다.
"""
from __future__ import annotations

import html
import os
import posixpath
import re
import threading
import traceback
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote, unquote

INTERACT_JS_PATH = Path(__file__).with_name("interact.js")
DOC_EXTENSIONS = (".htex", ".tex")

# 웹 서버 응답 헤더 (명세 7절: 문서에는 스크립트가 없다. 스크립트는 호스트가 넣는 같은 출처 파일뿐)
CSP_HTML = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https:; font-src 'self' https:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
CSP_SVG = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
# 정적 사이트용 <meta http-equiv> (frame-ancestors 는 meta 로 줄 수 없어 뺀다)
CSP_META = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https:; font-src 'self' https:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'")


def interact_js() -> str:
    return INTERACT_JS_PATH.read_text(encoding="utf-8")


def is_document(path: Path | str) -> bool:
    return str(path).lower().endswith(DOC_EXTENSIONS)


def e(s: Any) -> str:
    return html.escape(str(s), quote=True)


# ====================================================================== 경로
class PathRejected(Exception):
    """요청 경로를 거부한다. status 는 응답 코드(403 또는 404)."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def split_request_path(raw_path: str) -> list[str]:
    """퍼센트 인코딩된 요청 경로 → 안전한 경로 조각 목록. 위험하면 PathRejected.

    - 한 번만 디코딩한다 (%252e%252e 는 '%2e%2e' 라는 이름의 파일로 본다: 상위 이동이 아니다).
    - 디코딩 전후 어디에든 '..' / '.' 조각, NUL, 역슬래시가 있으면 403.
    - '.' 으로 시작하는 조각(숨김 파일·폴더)은 404.
    """
    if "\x00" in raw_path:
        raise PathRejected(403, "NUL 문자")
    try:
        decoded = unquote(raw_path, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        raise PathRejected(404, "UTF-8 이 아닌 경로") from None
    if "\x00" in decoded or "\\" in decoded or "\\" in raw_path:
        raise PathRejected(403, "허용되지 않는 문자")
    parts = []
    for seg in decoded.split("/"):
        if seg == "":
            continue
        if seg in (".", ".."):
            raise PathRejected(403, "상위 폴더 이동")
        if seg.startswith("."):
            raise PathRejected(404, "숨김 파일")
        if re.match(r"^[A-Za-z]:", seg):  # 윈도 드라이브 문자
            raise PathRejected(403, "절대 경로")
        parts.append(seg)
    return parts


def resolve_in_root(root: Path, parts: list[str]) -> Path:
    """루트 + 조각 → 실제 경로. 심볼릭 링크를 따라간 결과가 루트 밖이면 403."""
    root = root.resolve()
    target = root.joinpath(*parts) if parts else root
    real = Path(os.path.realpath(target))
    if real != root and root not in real.parents:
        raise PathRejected(403, "루트 폴더 밖")
    # 심볼릭 링크로 숨김 파일을 가리키는 경우도 막는다
    rel = real.relative_to(root).parts if real != root else ()
    if any(p.startswith(".") for p in rel):
        raise PathRejected(404, "숨김 파일")
    return real


def resolve_request_path(root: Path, raw_path: str) -> Path:
    return resolve_in_root(root, split_request_path(raw_path))


def url_path(root: Path, path: Path) -> str:
    """루트 안의 실제 경로 → '/a/b.htex' 꼴 URL 경로 (퍼센트 인코딩)."""
    rel = path.resolve().relative_to(root.resolve())
    return "/" + "/".join(quote(p) for p in rel.parts)


# ====================================================================== 문서 캐시
@dataclass
class DocEntry:
    key: tuple[int, int]          # (mtime_ns, size)
    tree: Optional[dict[str, Any]]
    html: Optional[str]           # 렌더 결과 (head_extra 포함)
    error: Optional[str] = None   # 파싱·렌더 예외 (오류 페이지용)


class DocCache:
    """경로 → DocEntry. 파일의 (수정 시각, 크기)가 바뀌면 다시 파싱한다.

    주의: \\usemacros·\\usestyle·\\transclude·\\input 으로 읽은 다른 파일이 바뀐 것은 모른다
    (notes/G-questions.md).
    """

    def __init__(self, max_entries: int = 128):
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, DocEntry]" = OrderedDict()
        self._path_locks: dict[str, threading.Lock] = {}

    def get(self, path: Path, render_html: Callable[[dict[str, Any], Path], str] | None) -> DocEntry:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
        k = str(path)
        with self._lock:
            ent = self._entries.get(k)
            if ent is not None and ent.key == key and (render_html is None or ent.html or ent.error):
                self._entries.move_to_end(k)
                return ent
            plock = self._path_locks.setdefault(k, threading.Lock())
        with plock:  # 같은 문서를 여러 스레드가 동시에 파싱하지 않게
            with self._lock:
                ent = self._entries.get(k)
                if ent is not None and ent.key == key and (render_html is None or ent.html or ent.error):
                    return ent
            ent = _load(path, key, render_html, ent if ent is not None and ent.key == key else None)
            with self._lock:
                self._entries[k] = ent
                self._entries.move_to_end(k)
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
            return ent

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _load(path: Path, key, render_html, old: Optional[DocEntry]) -> DocEntry:
    from ..parser import parse_file
    tree = old.tree if old is not None else None
    if tree is None:
        try:
            tree = parse_file(path)
        except Exception:  # noqa: BLE001 - 파서는 예외를 내지 않는 계약이지만 방어
            return DocEntry(key, None, None, "파서 예외\n" + traceback.format_exc(limit=5))
    if render_html is None:
        return DocEntry(key, tree, None)
    try:
        out = render_html(tree, path)
    except Exception:  # noqa: BLE001
        return DocEntry(key, tree, None, "HTML 변환 예외\n" + traceback.format_exc(limit=5))
    return DocEntry(key, tree, out)


# ====================================================================== 제목
def plain_title(tree: Optional[dict[str, Any]]) -> str:
    if not tree:
        return ""
    from ..html.render import _plain  # 읽기만 한다
    try:
        return _plain((tree.get("meta") or {}).get("title") or [])
    except Exception:  # noqa: BLE001
        return ""


_TITLE_RE = re.compile(r"\\title\s*\{((?:[^{}]|\{[^{}]*\})*)\}")


def quick_title(path: Path) -> str:
    """큰 문서용 대충 제목: 앞부분의 \\title{…} 원문."""
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            head = f.read(8192)
    except OSError:
        return ""
    m = _TITLE_RE.search(head)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# ====================================================================== 페이지
_PAGE_CSS = None


def _css() -> str:
    global _PAGE_CSS
    if _PAGE_CSS is None:
        from ..html.style import CSS
        _PAGE_CSS = CSS + """
.htex-listing{list-style:none;padding:0;font-family:var(--sans-font)}
.htex-listing li{padding:.35rem 0;border-bottom:1px solid var(--rule);display:flex;gap:1rem;align-items:baseline;flex-wrap:wrap}
.htex-listing .htex-listing-name{font-family:var(--mono-font);font-size:.9rem}
.htex-listing .htex-listing-title{color:var(--fg)}
.htex-listing .htex-listing-kind{color:var(--muted);font-size:.85rem;margin-left:auto}
.htex-errorpage pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--panel);padding:.75rem;border-radius:.4rem;font-size:.85rem}
"""
    return _PAGE_CSS


def page(title: str, body: str, head_extra: str = "") -> str:
    return ("<!doctype html>\n<html lang=\"ko\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<meta name=\"color-scheme\" content=\"light dark\">\n"
            f"<title>{e(title)}</title>\n<style>{_css()}</style>\n{head_extra}</head>\n"
            f"<body class=\"htex\"><article class=\"htex-doc\">\n{body}\n</article></body>\n</html>\n")


@dataclass
class ListingEntry:
    name: str          # 표시 이름 (폴더는 끝에 /)
    href: str          # 상대 주소 (퍼센트 인코딩)
    kind: str          # "folder" | "document" | "file"
    title: str = ""


def listing_page(display_path: str, entries: list[ListingEntry], parent: bool) -> str:
    items = []
    if parent:
        items.append('<li><a class="htex-listing-name" href="../">../</a>'
                     '<span class="htex-listing-kind">상위 폴더</span></li>')
    kinds = {"folder": "폴더", "document": "문서", "file": "파일"}
    for en in entries:
        title = (f'<span class="htex-listing-title">{e(en.title)}</span>' if en.title else "")
        items.append(f'<li><a class="htex-listing-name" href="{e(en.href)}">{e(en.name)}</a>'
                     f'{title}<span class="htex-listing-kind">{kinds.get(en.kind, "")}</span></li>')
    body = (f'<header class="htex-header"><h1 class="htex-title">{e(display_path)}</h1>'
            f'<p class="htex-date">HyperTeX 문서 목록</p></header>'
            f'<ul class="htex-listing">{"".join(items)}</ul>')
    return page(display_path, body)


def error_page(title: str, message: str, detail: str = "", source: str | None = None) -> str:
    body = [f'<header class="htex-header"><h1 class="htex-title">{e(title)}</h1></header>',
            f'<div class="htex-errorpage"><p>{e(message)}</p>']
    if detail:
        body.append(f"<details><summary>자세히</summary><pre>{e(detail)}</pre></details>")
    if source is not None:
        body.append(f"<h2>원문</h2><pre>{e(source)}</pre>")
    body.append("</div>")
    return page(title, "\n".join(body))


def sort_key(p: Path):
    return (not p.is_dir(), p.name.lower())


def listing_entries(root: Path, folder: Path, title_of: Callable[[Path], str],
                    href_of: Callable[[Path], str]) -> list[ListingEntry]:
    out: list[ListingEntry] = []
    try:
        children = sorted(folder.iterdir(), key=sort_key)
    except OSError:
        return out
    for c in children:
        if c.name.startswith("."):
            continue
        try:  # 루트 밖을 가리키는 심볼릭 링크는 목록에서 뺀다
            real = resolve_in_root(root, list(c.relative_to(root.resolve()).parts))
        except (PathRejected, ValueError):
            continue
        if real.is_dir():
            out.append(ListingEntry(c.name + "/", quote(c.name) + "/", "folder"))
        elif real.is_file():
            if is_document(c):
                out.append(ListingEntry(c.name, href_of(c), "document", title_of(real)))
            else:
                out.append(ListingEntry(c.name, quote(c.name), "file"))
    return out


def rel_href(from_dir: str, to_path: str) -> str:
    """정적 사이트 안에서 from_dir(폴더, '/a/b') → to_path('/x/y.js') 상대 주소."""
    rel = posixpath.relpath(to_path, from_dir or "/")
    return quote(rel)
