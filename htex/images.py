"""그림 파일 규칙 (Qt 없음). \\includegraphics·Markdown 그림이 쓰는 주소를 다룬다.

브라우저 엔진이 <img> 로 바로 그릴 수 있는 형식(WEB_EXTS)과, LaTeX 원고에 흔하지만 그대로는 못 그리는 형식:

- PDF 그림 (pdflatex 원고): 뷰어는 첫 쪽을 PNG 로 그려 보여 준다 (htex/viewer/pdfimage.py, QtPdf).
  정적 빌드(htex build)는 Qt 가 없으므로 같은 이름의 SVG·PNG 가 있으면 그것을 쓰고, 없으면 경고.
- 확장자 없는 그림 (\\includegraphics{fig}): LaTeX 처럼 SEARCH_ORDER 순서로 파일을 찾는다.
  웹 형식을 먼저 찾으므로 fig.svg 와 fig.pdf 가 함께 있으면 fig.svg 를 쓴다.
- EPS 는 지원하지 않는다 (변환 도구가 따로 필요). 진단만.

뷰어 안에서 PDF·확장자 없는 그림은 주소에 MARK 질의(?htex-image=1)를 붙여 요청한다. 같은 .pdf 를
링크로 열 때(문서 탐색)와 그림으로 불러올 때를 뷰어가 구별하려고.
"""
from __future__ import annotations

import posixpath
import urllib.parse
from pathlib import Path
from typing import Optional

WEB_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico")
SEARCH_ORDER = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf")
CONVERT_EXTS = (".pdf",)
UNSUPPORTED_EXTS = (".eps", ".ps")
MARK = "htex-image=1"


def _path_ext(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return posixpath.splitext(urllib.parse.unquote(parts.path))[1].lower()


def ext_of(url: str) -> str:
    """주소의 확장자 (질의·조각 무시, 소문자). 없으면 ""."""
    return _path_ext(url)


def needs_help(url: str) -> bool:
    """브라우저가 그대로는 못 그리는 그림 주소인가 (PDF·확장자 없음)."""
    if url.startswith(("data:", "blob:")):
        return False
    ext = _path_ext(url)
    return ext in CONVERT_EXTS or ext == ""


def mark(url: str) -> str:
    """그림으로 불러온다는 표시를 붙인다. 조각(#…)은 뒤에 그대로."""
    base, hash_, frag = url.partition("#")
    if has_mark(base):
        return url
    return base + ("&" if "?" in base else "?") + MARK + hash_ + frag


def has_mark(url: str) -> bool:
    q = urllib.parse.urlsplit(url).query
    return MARK in q.split("&")


def strip_mark(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    q = "&".join(x for x in parts.query.split("&") if x and x != MARK)
    return urllib.parse.urlunsplit(parts._replace(query=q))


def find_local(path: Path) -> Optional[Path]:
    """확장자 없는 그림 경로 → 실제 파일 (SEARCH_ORDER). 이미 있으면 그대로."""
    if path.is_file():
        return path
    if path.suffix.lower() in SEARCH_ORDER:
        return None
    for ext in SEARCH_ORDER:
        cand = path.with_name(path.name + ext)
        if cand.is_file():
            return cand
    return None


def web_substitute(path: Path) -> Optional[Path]:
    """PDF·확장자 없는 그림 대신 쓸 웹 형식 파일 (같은 이름의 .svg·.png·.jpg …). 정적 빌드용."""
    stem = path.with_suffix("") if path.suffix.lower() in CONVERT_EXTS else path
    if stem.suffix.lower() in WEB_EXTS and stem.is_file():
        return stem
    for ext in SEARCH_ORDER:
        if ext in CONVERT_EXTS:
            continue
        cand = stem.with_name(stem.name + ext)
        if cand.is_file():
            return cand
    return None


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(b"%PDF-")
