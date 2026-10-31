"""새 탭·홈 페이지 (htexapp://start/). Qt 없음. (담당: L)

Chrome 의 새 탭 페이지처럼: 가운데 로고, 주소 입력 칸, 바로가기 타일(북마크바의 북마크).
스크립트는 쓰지 않는다 (CSP 로 막는다). 입력 칸과 타일은 아래 주소로 이동을 요청하고,
창(HtexPage)이 그 요청을 가로채 사용자가 직접 입력한 것처럼 연다. 이 주소들은 시작 페이지에서
누른 것만 받는다 (다른 문서가 링크를 걸어도 무시된다).

    htexapp://start/go?q=<입력>        입력 칸 (form GET)
    htexapp://start/open?u=<북마크 주소> 타일
    htexapp://start/action?do=open-file 파일 열기
"""
from __future__ import annotations

import base64
import html
import urllib.parse
from pathlib import Path
from typing import Iterable, Optional

from .bookmarks import Bookmark

START_URL = "htexapp://start/"
START_HOST = "start"
MAX_TILES = 10

CSP = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
       "form-action htexapp:; base-uri 'none'; frame-ancestors 'none'")

_ICON = Path(__file__).resolve().parent / "icon.png"
_TILE_COLORS = ("#1a73e8", "#188038", "#d93025", "#e37400", "#9334e6", "#007b83", "#c5221f", "#5f6368")

CSS = """
:root{color-scheme:light dark;--bg:#ffffff;--fg:#202124;--muted:#5f6368;--box:#f1f3f4;--box-h:#e8eaed;
  --ring:#1a73e8;--tile-h:rgba(60,64,67,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#202124;--fg:#e8eaed;--muted:#9aa0a6;
  --box:#303134;--box-h:#3c4043;--ring:#8ab4f8;--tile-h:rgba(232,234,237,.08)}}
:root[data-theme="dark"]{--bg:#202124;--fg:#e8eaed;--muted:#9aa0a6;--box:#303134;--box-h:#3c4043;
  --ring:#8ab4f8;--tile-h:rgba(232,234,237,.08)}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI","Noto Sans KR","Malgun Gothic",sans-serif}
main{max-width:720px;margin:0 auto;padding:12vh 24px 48px;text-align:center}
.logo{width:88px;height:88px}
h1{font-size:32px;font-weight:500;margin:8px 0 28px;letter-spacing:-.01em}
form{margin:0 auto 36px;max-width:584px}
input{width:100%;height:48px;border-radius:24px;border:1px solid transparent;background:var(--box);
  color:var(--fg);font:inherit;font-size:16px;padding:0 24px;outline:none}
input:hover{background:var(--box-h)}
input:focus{border-color:var(--ring);background:var(--bg);box-shadow:0 1px 6px rgba(32,33,36,.28)}
input::placeholder{color:var(--muted)}
.tiles{display:flex;flex-wrap:wrap;justify-content:center;gap:4px;max-width:560px;margin:0 auto}
.tile{width:112px;height:112px;border-radius:8px;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:10px;text-decoration:none;color:var(--fg)}
.tile:hover{background:var(--tile-h)}
.dot{width:48px;height:48px;border-radius:50%;background:var(--box);display:flex;align-items:center;
  justify-content:center;font-weight:600;font-size:20px;color:#fff}
.dot img{width:28px;height:28px}
.name{font-size:13px;max-width:96px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.empty{color:var(--muted);font-size:14px}
.hint{color:var(--muted);font-size:13px;margin-top:40px}
kbd{font:inherit;font-size:12px;border:1px solid var(--box-h);border-radius:4px;padding:0 4px}
"""


def _logo_data() -> Optional[str]:
    try:
        return "data:image/png;base64," + base64.b64encode(_ICON.read_bytes()).decode("ascii")
    except OSError:
        return None


_LOGO = None


def _is_doc(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path if "://" in url else url
    return path.lower().endswith((".htex", ".tex"))


def _initial(title: str) -> str:
    for ch in title.strip():
        if ch.isalnum():
            return ch.upper()
    return "•"


def open_url(target: str) -> str:
    return START_URL + "open?u=" + urllib.parse.quote(target, safe="")


def parse_request(url: str) -> Optional[tuple[str, str]]:
    """시작 페이지가 보낸 요청 → (종류, 값). 종류: "go" | "open" | "action". 아니면 None."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != "htexapp" or parts.netloc.lower() != START_HOST:
        return None
    q = urllib.parse.parse_qs(parts.query)
    path = parts.path.rstrip("/")
    if path == "/go":
        v = (q.get("q") or [""])[0].strip()
        return ("go", v) if v else None
    if path == "/open":
        v = (q.get("u") or [""])[0].strip()
        return ("open", v) if v else None
    if path == "/action":
        v = (q.get("do") or [""])[0].strip()
        return ("action", v) if v else None
    return None


def render(bookmarks: Iterable[Bookmark], theme: str = "") -> str:
    """시작 페이지 HTML. theme 은 "light" | "dark" | "" (시스템)."""
    global _LOGO
    if _LOGO is None:
        _LOGO = _logo_data() or ""
    tiles = []
    doc_icon = (f'<img src="{_LOGO}" alt="">' if _LOGO else "T")
    items = [b for b in bookmarks if not b.is_folder and b.url][:MAX_TILES]
    for i, b in enumerate(items):
        color = _TILE_COLORS[sum(map(ord, b.title)) % len(_TILE_COLORS)] if not _is_doc(b.url) else ""
        dot = (f'<span class="dot">{doc_icon}</span>' if _is_doc(b.url)
               else f'<span class="dot" style="background:{color}">{html.escape(_initial(b.title))}</span>')
        tiles.append(f'<a class="tile" href="{html.escape(open_url(b.url))}" title="{html.escape(b.url)}">'
                     f'{dot}<span class="name">{html.escape(b.title)}</span></a>')
    tiles.append(f'<a class="tile" href="{START_URL}action?do=open-file" title="파일 열기 (Ctrl+O)">'
                 f'<span class="dot" style="background:#5f6368">+</span>'
                 f'<span class="name">파일 열기</span></a>')
    theme_attr = f' data-theme="{theme}"' if theme in ("light", "dark") else ""
    logo = f'<img class="logo" src="{_LOGO}" alt="">' if _LOGO else ""
    return f"""<!doctype html>
<html lang="ko"{theme_attr}><head><meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<meta http-equiv="Content-Security-Policy" content="{html.escape(CSP)}">
<title>새 탭</title><style>{CSS}</style></head>
<body><main>
{logo}
<h1>HyperTeX</h1>
<form action="{START_URL}go" method="get" autocomplete="off">
<input name="q" type="text" placeholder="htex:// 주소, https 주소 또는 파일 경로 입력" aria-label="주소">
</form>
<nav class="tiles">{"".join(tiles)}</nav>
<p class="hint">북마크바의 북마크가 여기에 바로가기로 보입니다 · 북마크 추가 <kbd>Ctrl</kbd>+<kbd>D</kbd> · 북마크바 보이기 <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd></p>
</main></body></html>"""
