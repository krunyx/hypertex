"""다른 브라우저의 북마크 가져오기 (Qt 없음, v0.8.1). 담당: R

두 가지 길:

1. **Chromium 계열 프로필 직접 읽기** (Chrome, Edge, Brave, Chromium, Vivaldi, Whale):
   프로필 폴더의 `Bookmarks` 파일(JSON)을 읽는다. 브라우저가 열려 있어도 읽을 수 있다(쓰지 않는다).
   `roots.bookmark_bar` 는 북마크바, `roots.other`·`roots.synced`(모바일) 는 "기타 북마크"로.
   프로필 이름은 사용자 데이터 폴더의 `Local State` → `profile.info_cache.<폴더>.name`.
2. **HTML 북마크 파일** (Netscape 형식, 모든 브라우저가 내보내는 꼴): `<DT><H3>폴더</H3><DL>…</DL>`,
   `<DT><A HREF="…">이름</A>`. 북마크바 폴더는 `PERSONAL_TOOLBAR_FOLDER="true"` 표시가 있는 H3
   (Safari 는 이름이 "Favorites"/"즐겨찾기" 인 폴더). 표시가 없으면 맨 위 항목 전체를 북마크바로 본다.

열 수 없는 주소(`javascript:` 북마크릿, `chrome://` 같은 브라우저 내부 주소)는 건너뛴다.
`file://` 주소는 주소창에 넣는 것과 같은 로컬 경로로 바꾼다.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

from .bookmarks import Bookmark

# (화면 이름, 운영체제별 사용자 데이터 폴더). 경로는 홈 폴더 또는 %LOCALAPPDATA% 기준.
_BROWSERS: list[tuple[str, dict[str, str]]] = [
    ("Google Chrome", {"darwin": "Library/Application Support/Google/Chrome",
                       "nt": "Google/Chrome/User Data", "linux": ".config/google-chrome"}),
    ("Microsoft Edge", {"darwin": "Library/Application Support/Microsoft Edge",
                        "nt": "Microsoft/Edge/User Data", "linux": ".config/microsoft-edge"}),
    ("Brave", {"darwin": "Library/Application Support/BraveSoftware/Brave-Browser",
               "nt": "BraveSoftware/Brave-Browser/User Data", "linux": ".config/BraveSoftware/Brave-Browser"}),
    ("Naver Whale", {"darwin": "Library/Application Support/Naver/Whale",
                     "nt": "Naver/Naver Whale/User Data", "linux": ".config/naver-whale"}),
    ("Vivaldi", {"darwin": "Library/Application Support/Vivaldi",
                 "nt": "Vivaldi/User Data", "linux": ".config/vivaldi"}),
    ("Chromium", {"darwin": "Library/Application Support/Chromium",
                  "nt": "Chromium/User Data", "linux": ".config/chromium"}),
]

_SKIP_SCHEMES = ("javascript:", "chrome:", "chrome-extension:", "edge:", "brave:", "vivaldi:", "whale:",
                 "about:", "data:", "place:", "view-source:", "opera:")
MAX_ITEMS = 50_000          # 한 번에 들이는 항목 수 상한 (깨진 파일·거대한 파일 대비)


@dataclass
class BrowserProfile:
    browser: str             # "Google Chrome"
    name: str                # 프로필 이름 ("사용자 1", "Work")
    path: Path               # Bookmarks 파일

    @property
    def label(self) -> str:
        return f"{self.browser} — {self.name}" if self.name else self.browser


@dataclass
class Imported:
    bar: list[Bookmark]      # 북마크바에 둘 것
    other: list[Bookmark]    # 기타 북마크
    count: int               # 북마크 수 (폴더 제외)


# ---------------------------------------------------------------- 주소 다듬기
def clean_url(url: str) -> Optional[str]:
    """가져올 주소로 다듬는다. 열 수 없는 것이면 None."""
    url = (url or "").strip()
    if not url:
        return None
    low = url.lower()
    if low.startswith(_SKIP_SCHEMES):
        return None
    if low.startswith("file:"):
        parts = urlsplit(url)
        path = unquote(parts.path)
        if os.name == "nt" and len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]                     # /C:/x → C:/x
        if parts.netloc and parts.netloc not in ("", "localhost"):
            path = f"//{parts.netloc}{path}"     # 네트워크 공유
        return path or None
    return url[:4000]


# ---------------------------------------------------------------- Chromium JSON
def _from_chromium_node(node: dict, budget: list[int]) -> Optional[Bookmark]:
    if budget[0] <= 0 or not isinstance(node, dict):
        return None
    kind = node.get("type")
    title = str(node.get("name") or "")
    if kind == "folder":
        kids = []
        for c in node.get("children") or []:
            b = _from_chromium_node(c, budget)
            if b is not None:
                kids.append(b)
        return Bookmark(title, children=kids)
    if kind == "url":
        url = clean_url(str(node.get("url") or ""))
        if url is None:
            return None
        budget[0] -= 1
        return Bookmark(title or url, url)
    return None


def _count(items: list[Bookmark]) -> int:
    return sum(_count(b.children or []) if b.is_folder else 1 for b in items)


def read_chromium(path: Path) -> Imported:
    """Chromium 계열 `Bookmarks` 파일. 읽을 수 없으면 ValueError."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(str(e)) from e
    roots = data.get("roots") if isinstance(data, dict) else None
    if not isinstance(roots, dict):
        raise ValueError("roots")
    budget = [MAX_ITEMS]

    def kids(key: str) -> list[Bookmark]:
        node = roots.get(key)
        b = _from_chromium_node(node, budget) if isinstance(node, dict) else None
        return list(b.children or []) if b is not None and b.is_folder else []

    bar = kids("bookmark_bar")
    other = kids("other") + kids("synced")
    return Imported(bar, other, _count(bar) + _count(other))


# ---------------------------------------------------------------- HTML (Netscape)
# 표시(PERSONAL_TOOLBAR_FOLDER) 없이 내보내는 브라우저(Safari 등)의 북마크바 폴더 이름.
# Chrome·Edge·Firefox 는 표시를 달아 내보내므로 이름은 거의 필요 없다. 한국어 이름은 notes/R-questions.md 2절.
_BAR_NAMES = {"favorites", "favourites", "favorites bar", "bookmarks bar", "bookmarks toolbar"}


class _NetscapeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Bookmark("", children=[])
        self.stack: list[Bookmark] = [self.root]
        self.pending: Optional[Bookmark] = None      # H3 를 읽었고 그 DL 을 기다리는 폴더
        self.toolbar: Optional[Bookmark] = None
        self.text_into: Optional[str] = None          # "folder" | "link"
        self.cur_link: Optional[Bookmark] = None
        self.cur_folder: Optional[Bookmark] = None
        self.items = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "h3":
            f = Bookmark("", children=[])
            self.stack[-1].children.append(f)
            self.cur_folder = f
            self.text_into = "folder"
            if a.get("personal_toolbar_folder", "").lower() == "true" and self.toolbar is None:
                self.toolbar = f
        elif tag == "a":
            url = clean_url(a.get("href", ""))
            if url is not None and self.items < MAX_ITEMS:
                b = Bookmark("", url)
                self.stack[-1].children.append(b)
                self.cur_link = b
                self.text_into = "link"
                self.items += 1
            else:
                self.cur_link = None
                self.text_into = None
        elif tag == "dl":
            # H3 다음에 오는 DL 이 그 폴더의 내용. 아니면(맨 바깥 DL) 지금 자리 그대로.
            if self.cur_folder is not None:
                self.stack.append(self.cur_folder)
                self.cur_folder = None
            else:
                self.stack.append(self.stack[-1])

    def handle_endtag(self, tag):
        if tag == "dl" and len(self.stack) > 1:
            self.stack.pop()
        elif tag in ("h3", "a"):
            self.text_into = None

    def handle_data(self, data):
        if self.text_into == "folder" and self.cur_folder is not None:
            self.cur_folder.title += data
        elif self.text_into == "link" and self.cur_link is not None:
            self.cur_link.title += data


def _tidy(items: list[Bookmark]) -> list[Bookmark]:
    out = []
    for b in items:
        b.title = " ".join(b.title.split())[:300]
        if b.is_folder:
            b.children = _tidy(b.children or [])
            b.title = b.title or "Folder"
        else:
            b.title = b.title or b.url
        out.append(b)
    return out


def read_html(text: str) -> Imported:
    """HTML 북마크 파일의 글. 북마크가 하나도 없으면 ValueError."""
    p = _NetscapeParser()
    p.feed(text)
    p.close()
    top = _tidy(p.root.children or [])
    bar_folder = p.toolbar
    if bar_folder is None:
        for b in top:
            if b.is_folder and b.title.strip().lower() in _BAR_NAMES:
                bar_folder = b
                break
    if bar_folder is not None and any(b is bar_folder for b in top):
        bar = list(bar_folder.children or [])
        other = [b for b in top if b is not bar_folder]
    elif bar_folder is not None:          # 깊은 곳에 있는 표시 — 그 폴더만 북마크바로, 나머지는 그대로
        bar = list(bar_folder.children or [])
        bar_folder.children = []
        other = top
    else:
        bar, other = top, []
    n = _count(bar) + _count(other)
    if n == 0:
        raise ValueError("no bookmarks")
    return Imported(bar, other, n)


def read_html_file(path: Path) -> Imported:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949", "latin-1"):
        try:
            return read_html(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    raise ValueError("encoding")


# ---------------------------------------------------------------- 프로필 찾기
def _platform_key() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if os.name == "nt":
        return "nt"
    return "linux"


def _user_data_dir(rel: str, key: str, home: Path) -> Path:
    if key == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / rel
    return home / rel


def find_profiles(home: Optional[Path] = None) -> list[BrowserProfile]:
    """이 컴퓨터에 있는 Chromium 계열 브라우저 프로필 중 북마크 파일이 있는 것."""
    home = Path(home) if home is not None else Path.home()
    key = _platform_key()
    found: list[BrowserProfile] = []
    for browser, rels in _BROWSERS:
        rel = rels.get(key)
        if not rel:
            continue
        root = _user_data_dir(rel, key, home)
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        names: dict[str, str] = {}
        try:
            state = json.loads((root / "Local State").read_text(encoding="utf-8"))
            cache = state.get("profile", {}).get("info_cache", {})
            if isinstance(cache, dict):
                names = {k: str(v.get("name") or "") for k, v in cache.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            pass
        dirs = []
        try:
            for d in sorted(root.iterdir()):
                if d.name == "Default" or d.name.startswith("Profile "):
                    dirs.append(d)
        except OSError:
            continue
        dirs.sort(key=lambda d: (d.name != "Default", len(d.name), d.name))
        for d in dirs:
            bm = d / "Bookmarks"
            if bm.is_file():
                found.append(BrowserProfile(browser, names.get(d.name, "") or d.name, bm))
    return found
