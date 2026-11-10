"""방문 기록 (Qt 없음, v0.8.2). 담당: R

Chrome 의 방문 기록(Ctrl+H)처럼: 연 문서·페이지를 시간 순으로 남기고, 기록 페이지(htexapp://start/history)
에서 날짜별로 보고, 찾고, 지운다. 탭마다의 뒤로·앞으로 기록(`History`)과는 다르다.

저장 형식: 사용자 데이터 폴더의 `history.jsonl`, 한 줄에 한 방문 (덧붙이기만 하므로 빠르다).

    {"t": 1794283200.5, "url": "htex://krunyx.com/hypertex/examples/sir.htex", "title": "SIR 모형"}

- `url` 은 북마크와 같은 꼴 (로컬 문서는 파일 경로). 시작 페이지·원문 보기·빈 탭은 남기지 않는다.
- 같은 주소를 30분 안에 다시 열면 새 줄을 만들지 않고 시간·제목만 고친다 (새로고침·앞뒤 이동으로 목록이
  불어나지 않게). 고칠 때와 지울 때는 파일을 다시 쓴다.
- MAX_VISITS 를 넘으면 오래된 것부터 버린다. 깨진 줄은 건너뛴다.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

MAX_VISITS = 10_000
MERGE_SECONDS = 30 * 60


@dataclass
class Visit:
    t: float
    url: str
    title: str = ""
    id: int = 0            # 목록 안의 자리 (기록 페이지의 지우기 단추가 쓴다)


@dataclass
class VisitStore:
    path: Optional[Path] = None
    visits: list[Visit] = field(default_factory=list)
    clock: Callable[[], float] = time.time
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @classmethod
    def load(cls, path: Optional[Path], clock: Callable[[], float] = time.time) -> "VisitStore":
        store = cls(path=Path(path) if path is not None else None, clock=clock)
        if store.path is None:
            return store
        try:
            lines = store.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        for ln in lines:
            try:
                d = json.loads(ln)
                if isinstance(d, dict) and isinstance(d.get("url"), str) and d["url"].strip():
                    store.visits.append(Visit(float(d.get("t") or 0), d["url"][:4000], str(d.get("title") or "")[:300]))
            except (ValueError, TypeError):
                continue
        if len(store.visits) > MAX_VISITS:
            store.visits = store.visits[-MAX_VISITS:]
            store._rewrite()
        store._renumber()
        return store

    # ------------------------------------------------------------ 쓰기
    def _renumber(self) -> None:
        for i, v in enumerate(self.visits):
            v.id = i

    def _line(self, v: Visit) -> str:
        return json.dumps({"t": round(v.t, 1), "url": v.url, "title": v.title}, ensure_ascii=False) + "\n"

    def _rewrite(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text("".join(self._line(v) for v in self.visits), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def _append(self, v: Visit) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(self._line(v))
        except OSError:
            pass

    def record(self, url: str, title: str = "") -> Optional[Visit]:
        """방문 하나. 같은 주소를 MERGE_SECONDS 안에 다시 열었으면 그 줄을 고친다."""
        url = (url or "").strip()
        if not url:
            return None
        now = self.clock()
        with self._lock:
            for v in reversed(self.visits):
                if now - v.t > MERGE_SECONDS:
                    break
                if v.url == url:
                    v.t = now
                    if title:
                        v.title = title[:300]
                    # 맨 뒤로 옮겨 "가장 최근"이 되게
                    self.visits.remove(v)
                    self.visits.append(v)
                    self._renumber()
                    self._rewrite()
                    return v
            v = Visit(now, url[:4000], (title or "")[:300], len(self.visits))
            self.visits.append(v)
            if len(self.visits) > MAX_VISITS:
                del self.visits[:len(self.visits) - MAX_VISITS]
                self._renumber()
                self._rewrite()
            else:
                self._append(v)
            return v

    def set_title(self, url: str, title: str) -> None:
        """문서를 다 불러온 뒤 제목이 정해지면 가장 최근 방문의 제목을 고친다."""
        title = (title or "").strip()[:300]
        if not url or not title:
            return
        with self._lock:
            for v in reversed(self.visits[-50:]):
                if v.url == url:
                    if v.title != title:
                        v.title = title
                        self._rewrite()
                    return

    def remove(self, vid: int) -> bool:
        with self._lock:
            if not 0 <= vid < len(self.visits):
                return False
            del self.visits[vid]
            self._renumber()
            self._rewrite()
        return True

    def clear(self) -> None:
        with self._lock:
            self.visits = []
            self._rewrite()

    # ------------------------------------------------------------ 읽기
    def search(self, query: str = "", limit: int = 1000) -> list[Visit]:
        """새것부터. query 가 있으면 제목·주소에 그 글자들(띄어 쓴 낱말 모두)이 든 것만."""
        words = [w.lower() for w in (query or "").split()]
        out: list[Visit] = []
        with self._lock:
            for v in reversed(self.visits):
                hay = (v.title + " " + v.url).lower()
                if all(w in hay for w in words):
                    out.append(Visit(v.t, v.url, v.title, v.id))
                    if len(out) >= limit:
                        break
        return out
