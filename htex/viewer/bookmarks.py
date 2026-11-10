"""북마크 저장소 (Qt 없음). 뷰어의 북마크바·별 단추·시작 페이지가 함께 쓴다. (담당: L)

저장 형식 (JSON, 사람이 읽고 고칠 수 있게):

    {"version": 1,
     "bar": [ {"title": "HyperTeX", "url": "https://krunyx.com/hypertex/"},
              {"title": "논문", "children": [ {"title": "…", "url": "…"} ]} ]}

- 항목은 북마크(`url` 있음) 또는 폴더(`children` 있음). 폴더 안에 폴더를 둘 수 있다 (Chrome 처럼, v0.8.1).
  너무 깊은 것은 MAX_DEPTH 단계에서 자른다 (그 아래 폴더는 버리지 않고 북마크만 위로 올린다).
- `url` 은 주소 표시줄에 넣는 것과 같은 꼴로 둔다: htex://…, https://…, 로컬 파일 경로.
  (htexapp://doc-<키>/ 는 실행마다 바뀌므로 저장하지 않는다. 뷰어가 display_address 로 바꿔 넘긴다.)
- 파일이 깨졌으면 지우지 않고 `bookmarks.json.broken` 으로 옮긴 뒤 빈 목록으로 시작한다.
- 쓰기는 임시 파일에 쓰고 이름을 바꾼다 (중간에 꺼져도 앞 판이 남는다).
"""
from __future__ import annotations
from ..i18n import tr

import json
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

VERSION = 1
MAX_DEPTH = 8          # 폴더 깊이 (북마크바 = 0)

# 처음 실행할 때 북마크바에 넣는 것 (사용자가 지우면 다시 생기지 않는다)
DEFAULT_BOOKMARKS = [
    {"title": "HyperTeX", "url": "https://krunyx.com/hypertex/"},
    {"title": "시작하기", "url": "https://krunyx.com/hypertex/getting-started/"},
    {"title": "krunyx", "url": "https://krunyx.com/"},
]


def default_data_dir() -> Path:
    """플랫폼별 사용자 데이터 폴더 (캐시와 달리 지우면 안 되는 것)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "HyperTeX"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "HyperTeX"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "hypertex"


@dataclass
class Bookmark:
    title: str
    url: str = ""
    children: Optional[list["Bookmark"]] = None      # 폴더면 목록

    @property
    def is_folder(self) -> bool:
        return self.children is not None

    def to_json(self) -> dict:
        if self.is_folder:
            return {"title": self.title, "children": [c.to_json() for c in self.children or []]}
        return {"title": self.title, "url": self.url}

    @staticmethod
    def from_json(d: dict, depth: int = 0) -> Optional["Bookmark"]:
        if not isinstance(d, dict):
            return None
        title = str(d.get("title") or "")[:300]
        if isinstance(d.get("children"), list):
            if depth >= MAX_DEPTH:
                return None
            kids = [b for b in (Bookmark.from_json(c, depth + 1) for c in d["children"]) if b]
            return Bookmark(title or tr('새 폴더'), children=kids)
        url = d.get("url")
        if not isinstance(url, str) or not url.strip():
            return None
        return Bookmark(title or url, url.strip()[:4000])


def same_address(a: str, b: str) -> bool:
    """북마크 비교: 앞뒤 공백·끝의 / 차이는 같다고 본다."""
    def norm(s: str) -> str:
        s = s.strip()
        return s[:-1] if s.endswith("/") and not s.endswith("://") else s
    return norm(a) == norm(b)


@dataclass
class BookmarkStore:
    """북마크바 목록. path 가 None 이면 메모리에만 (테스트·저장 실패 시)."""

    path: Optional[Path] = None
    bar: list[Bookmark] = field(default_factory=list)
    _listeners: list[Callable[[], None]] = field(default_factory=list, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # ------------------------------------------------------------ 불러오기·저장
    @classmethod
    def load(cls, path: Optional[Path] = None, seed: bool = True) -> "BookmarkStore":
        if path is None:
            path = default_data_dir() / "bookmarks.json"
        store = cls(path=Path(path))
        if store.path.exists():
            try:
                data = json.loads(store.path.read_text(encoding="utf-8"))
                items = data.get("bar") if isinstance(data, dict) else None
                if not isinstance(items, list):
                    raise ValueError(tr('bar 가 목록이 아니다'))
                store.bar = [b for b in (Bookmark.from_json(d) for d in items) if b]
            except (OSError, ValueError):
                try:
                    store.path.replace(store.path.with_name(store.path.name + ".broken"))
                except OSError:
                    pass
                store.bar = []
        elif seed:
            store.bar = [b for b in (Bookmark.from_json(dict(d, title=tr(d["title"]))) for d in DEFAULT_BOOKMARKS)
                         if b]   # 이름은 처음 실행할 때의 화면 언어로
            store.save()
        return store

    def save(self) -> bool:
        if self.path is None:
            return True
        with self._lock:
            data = {"version": VERSION, "bar": [b.to_json() for b in self.bar]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.path)
            return True
        except OSError:
            return False

    def on_change(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def _changed(self) -> None:
        self.save()
        for fn in list(self._listeners):
            fn()

    # ------------------------------------------------------------ 읽기
    def snapshot(self) -> list[Bookmark]:
        """다른 스레드(시작 페이지 응답)에서 읽을 복사본."""
        def copy(b: Bookmark) -> Bookmark:
            return Bookmark(b.title, b.url, None if b.children is None else [copy(c) for c in b.children])
        with self._lock:
            return [copy(b) for b in self.bar]

    def iter_folders(self) -> Iterator[tuple[int, Bookmark]]:
        """(깊이, 폴더) 모두, 위에서부터 차례로. 북마크바 바로 아래 폴더의 깊이가 0."""
        def walk(items: list[Bookmark], depth: int) -> Iterator[tuple[int, Bookmark]]:
            for b in items:
                if b.is_folder:
                    yield depth, b
                    yield from walk(b.children or [], depth + 1)
        yield from walk(self.bar, 0)

    def folders(self) -> list[Bookmark]:
        """모든 폴더 (하위 폴더 포함, 위에서부터 차례로)."""
        return [f for _, f in self.iter_folders()]

    def iter_all(self) -> Iterator[tuple[Optional[Bookmark], Bookmark]]:
        """(들어 있는 폴더 또는 None, 북마크) 모두. 하위 폴더 안의 것까지."""
        def walk(items: list[Bookmark], parent: Optional[Bookmark]):
            for b in items:
                if b.is_folder:
                    yield from walk(b.children or [], b)
                else:
                    yield parent, b
        yield from walk(self.bar, None)

    def find(self, url: str) -> Optional[tuple[Optional[Bookmark], Bookmark]]:
        if not url:
            return None
        for folder, b in self.iter_all():
            if same_address(b.url, url):
                return folder, b
        return None

    def contains(self, url: str) -> bool:
        return self.find(url) is not None

    # ------------------------------------------------------------ 고치기
    def add(self, title: str, url: str, folder: Optional[Bookmark] = None,
            index: Optional[int] = None) -> Bookmark:
        """이미 있는 주소면 그 북마크를 돌려준다 (Chrome 처럼 별을 두 번 눌러도 하나)."""
        hit = self.find(url)
        if hit is not None:
            return hit[1]
        b = Bookmark((title or url).strip()[:300] or url, url.strip())
        with self._lock:
            target = folder.children if folder is not None and folder.is_folder else self.bar
            target.insert(len(target) if index is None else max(0, min(index, len(target))), b)
        self._changed()
        return b

    def add_folder(self, title: str, index: Optional[int] = None,
                   parent: Optional[Bookmark] = None) -> Bookmark:
        """parent 를 주면 그 폴더 안에 (너무 깊으면 북마크바에)."""
        f = Bookmark((title or tr('새 폴더')).strip()[:300] or tr('새 폴더'), children=[])
        with self._lock:
            if parent is not None and (not parent.is_folder or self.depth_of(parent) + 1 >= MAX_DEPTH):
                parent = None
            target = parent.children if parent is not None else self.bar
            target.insert(len(target) if index is None else max(0, min(index, len(target))), f)
        self._changed()
        return f

    def remove(self, item: Bookmark) -> bool:
        with self._lock:
            if item in self.bar:
                self.bar.remove(item)
            else:
                parent = self.parent_of(item)
                if parent is None:
                    return False
                parent.children.remove(item)
        self._changed()
        return True

    def remove_url(self, url: str) -> bool:
        hit = self.find(url)
        return self.remove(hit[1]) if hit else False

    def update(self, item: Bookmark, title: Optional[str] = None, url: Optional[str] = None,
               folder: "Optional[Bookmark] | str" = "keep") -> None:
        """이름·주소를 바꾸고, folder 를 주면 그 폴더로(None 이면 북마크바 맨 끝으로) 옮긴다."""
        with self._lock:
            if title is not None and title.strip():
                item.title = title.strip()[:300]
            if url is not None and url.strip() and not item.is_folder:
                item.url = url.strip()
            if folder != "keep" and not item.is_folder:
                cur = self.parent_of(item)
                if cur is not folder:
                    (cur.children if cur is not None else self.bar).remove(item)
                    (folder.children if folder is not None else self.bar).append(item)
        self._changed()

    def move(self, item: Bookmark, index: int) -> None:
        """북마크바 안에서 자리 옮기기 (끌어서 놓기)."""
        with self._lock:
            if item not in self.bar:
                return
            self.bar.remove(item)
            self.bar.insert(max(0, min(index, len(self.bar))), item)
        self._changed()

    def parent_of(self, item: Bookmark) -> Optional[Bookmark]:
        """item 이 들어 있는 폴더 (북마크바에 있거나 없으면 None). 같은 객체로 찾는다."""
        for f in self.folders():
            if any(c is item for c in f.children or []):
                return f
        return None

    def depth_of(self, folder: Bookmark) -> int:
        """폴더의 깊이 (북마크바 바로 아래 = 0, 없으면 -1)."""
        for d, f in self.iter_folders():
            if f is folder:
                return d
        return -1

    def folder_path(self, folder: Bookmark) -> str:
        """화면에 보일 폴더 경로: "논문 › 2026"."""
        names = []
        cur: Optional[Bookmark] = folder
        while cur is not None:
            names.append(cur.title)
            cur = self.parent_of(cur)
        return " › ".join(reversed(names))

    # ------------------------------------------------------------ 가져오기
    def import_items(self, bar_items: list[Bookmark], other_items: list[Bookmark], source: str) -> int:
        """다른 브라우저의 북마크를 들인다. 들인 북마크 수를 돌려준다 (이미 있는 주소는 건너뛴다).

        Chrome 의 가져오기처럼: 북마크바가 비었거나 처음 넣어 둔 기본 북마크뿐이면 북마크바 항목을 그대로
        북마크바에 놓고, 아니면 "<source>에서 가져옴" 폴더 하나에 넣는다. 북마크바 밖의 것(Chrome 의
        "기타 북마크")은 그 안의 "기타 북마크" 폴더로.
        """
        seen = {b.url.strip().rstrip("/") for _, b in self.iter_all()}
        count = 0

        def fresh(items: list[Bookmark], depth: int) -> list[Bookmark]:
            nonlocal count
            out: list[Bookmark] = []
            for b in items:
                if b.is_folder:
                    kids = fresh(b.children or [], depth + 1)
                    if not kids:
                        continue
                    if depth >= MAX_DEPTH:      # 너무 깊으면 북마크만 위로
                        out.extend(kids)
                    else:
                        out.append(Bookmark(b.title[:300] or tr('새 폴더'), children=kids))
                else:
                    key = b.url.strip().rstrip("/")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    out.append(Bookmark((b.title or b.url).strip()[:300], b.url.strip()[:4000]))
                    count += 1
            return out

        default_urls = {d["url"].rstrip("/") for d in DEFAULT_BOOKMARKS}
        with self._lock:
            only_defaults = all(not b.is_folder and b.url.rstrip("/") in default_urls for b in self.bar)
            direct = only_defaults
            top = fresh(bar_items, 0 if direct else 1)
            other_depth = 1 if direct else 2
            other = fresh(other_items, other_depth)
            if other:
                top.append(Bookmark(tr('기타 북마크'), children=other))
            if not top:
                return 0
            if direct:
                self.bar.extend(top)
            else:
                self.bar.append(Bookmark(tr('{source}에서 가져옴', source=source), children=top))
        self._changed()
        return count
