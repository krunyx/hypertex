"""방문 기록 페이지 (htexapp://start/history). Qt 없음, 스크립트 없음. 담당: R (v0.8.2)

시작 페이지와 같은 방식이다: 링크와 검색 칸만 있고, 창(HtexPage)이 아래 주소를 가로채 처리한다.
이 주소들은 시작 페이지·기록 페이지 자신이 보낸 것만 받는다.

    htexapp://start/history?q=<찾을 글자>      기록 페이지 (검색)
    htexapp://start/open?u=<주소>              항목 열기 (시작 페이지 타일과 같다)
    htexapp://start/forget?id=<번호>           항목 하나 지우기
    htexapp://start/action?do=history-clear    모두 지우기 (창이 확인을 받는다)
"""
from __future__ import annotations

import html
import time
import urllib.parse
from typing import Iterable

from ..i18n import tr, ui_language
from .startpage import CSP, CSS as START_CSS, START_URL, open_url
from .visits import Visit

HISTORY_URL = START_URL + "history"

CSS = START_CSS + """
main.history{max-width:840px;padding:32px 24px 64px;text-align:left}
.top{display:flex;align-items:center;gap:16px;margin-bottom:24px}
.top h1{margin:0;font-size:22px;flex:0 0 auto}
.top form{margin:0;flex:1 1 auto;max-width:none}
.top input{height:40px;border-radius:20px;font-size:15px}
.clear{flex:0 0 auto;color:var(--ring);text-decoration:none;font-size:14px;white-space:nowrap}
.clear:hover{text-decoration:underline}
section{background:var(--box);border-radius:12px;margin:0 0 16px;padding:8px 0}
section h2{font-size:14px;font-weight:600;margin:6px 20px 8px;color:var(--fg)}
.row{display:flex;align-items:center;gap:14px;padding:6px 12px 6px 20px;min-height:40px}
.row:hover{background:var(--tile-h)}
.time{color:var(--muted);font-size:13px;width:3.6em;flex:0 0 auto;font-variant-numeric:tabular-nums}
.link{flex:1 1 auto;min-width:0;display:flex;gap:10px;align-items:baseline;text-decoration:none;color:var(--fg)}
.title{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:60%}
.url{color:var(--muted);font-size:13px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;flex:1 1 auto}
.link:hover .title{text-decoration:underline}
.del{flex:0 0 auto;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  color:var(--muted);text-decoration:none;font-size:18px;line-height:1}
.del:hover{background:var(--box-h);color:var(--fg)}
.none{color:var(--muted);text-align:center;margin-top:48px}
"""


def forget_url(vid: int) -> str:
    return f"{START_URL}forget?id={int(vid)}"


def _day_label(t: float, now: float) -> str:
    lt, ln = time.localtime(t), time.localtime(now)
    date = tr('{y}년 {m}월 {d}일', y=lt.tm_year, m=lt.tm_mon, d=lt.tm_mday)
    day = (lt.tm_year, lt.tm_yday)
    if day == (ln.tm_year, ln.tm_yday):
        return tr('오늘') + " · " + date
    yest = time.localtime(now - 86400)
    if day == (yest.tm_year, yest.tm_yday):
        return tr('어제') + " · " + date
    return date


def _short(url: str) -> str:
    """보일 주소: 웹은 호스트와 경로, 로컬은 경로 그대로."""
    if "://" in url:
        p = urllib.parse.urlsplit(url)
        return urllib.parse.unquote(p.netloc + p.path)
    return url


def render(visits: Iterable[Visit], query: str = "", theme: str = "", now: float | None = None) -> str:
    """기록 페이지 HTML. visits 는 새것부터 (VisitStore.search 의 결과)."""
    now = time.time() if now is None else now
    groups: list[tuple[str, list[str]]] = []
    for v in visits:
        label = _day_label(v.t, now)
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        title = v.title or _short(v.url)
        groups[-1][1].append(
            f'<div class="row"><span class="time">{time.strftime("%H:%M", time.localtime(v.t))}</span>'
            f'<a class="link" href="{html.escape(open_url(v.url))}" title="{html.escape(v.url)}">'
            f'<span class="title">{html.escape(title)}</span><span class="url">{html.escape(_short(v.url))}</span></a>'
            f'<a class="del" href="{forget_url(v.id)}" title="{html.escape(tr("기록에서 삭제"))}" '
            f'aria-label="{html.escape(tr("기록에서 삭제"))}">×</a></div>')
    if groups:
        body = "".join(f'<section><h2>{html.escape(label)}</h2>{"".join(rows)}</section>' for label, rows in groups)
    elif query:
        body = f'<p class="none">{html.escape(tr("찾는 기록이 없습니다."))}</p>'
    else:
        body = f'<p class="none">{html.escape(tr("방문 기록이 없습니다."))}</p>'
    theme_attr = f' data-theme="{theme}"' if theme in ("light", "dark") else ""
    clear = (f'<a class="clear" href="{START_URL}action?do=history-clear">{html.escape(tr("방문 기록 삭제"))}</a>'
             if groups and not query else "")
    return f"""<!doctype html>
<html lang="{ui_language()}"{theme_attr}><head><meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<meta http-equiv="Content-Security-Policy" content="{html.escape(CSP)}">
<title>{html.escape(tr("방문 기록"))}</title><style>{CSS}</style></head>
<body><main class="history">
<div class="top"><h1>{html.escape(tr("방문 기록"))}</h1>
<form action="{HISTORY_URL}" method="get" autocomplete="off">
<input name="q" type="search" value="{html.escape(query)}" placeholder="{html.escape(tr("기록 검색"))}" aria-label="{html.escape(tr("기록 검색"))}">
</form>{clear}</div>
{body}
</main></body></html>"""
