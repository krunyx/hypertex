"""세션: 다시 켤 때 이전 탭을 다시 연다 (Qt 없음, v0.8.1). 담당: R

Chrome 의 "시작할 때 › 중단한 위치에서 계속하기" 와 같다. 저장 형식 (JSON):

    {"version": 1, "active": 1,
     "tabs": [ {"url": "htex://krunyx.com/hypertex/examples/sir.htex", "title": "SIR 모형"},
               {"url": "/Users/u/notes/qft.htex", "title": "QFT"},
               {"url": "htexapp://start/", "title": "새 탭"} ]}

- `url` 은 북마크와 같이 주소창에 넣는 꼴 (로컬 문서는 파일 경로). htexapp://doc-<키>/ 는 실행마다 바뀌므로
  저장하지 않는다. 원문 보기·빈 탭·멈춘 탭은 저장하지 않는다.
- 파일이 깨졌으면 없는 것으로 친다 (지우지 않는다). 쓰기는 임시 파일에 쓰고 이름을 바꾼다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

VERSION = 1
MAX_TABS = 100              # 다시 여는 탭 수 상한
MAX_CLOSED = 25             # 닫은 탭 다시 열기(Ctrl+Shift+T) 로 기억하는 수

STARTUP_CONTINUE = "continue"   # 이전 탭 다시 열기 (기본)
STARTUP_NEW_TAB = "newtab"      # 새 탭 페이지만
STARTUP_MODES = (STARTUP_CONTINUE, STARTUP_NEW_TAB)


@dataclass
class SessionTab:
    url: str
    title: str = ""


@dataclass
class Session:
    tabs: list[SessionTab] = field(default_factory=list)
    active: int = 0

    def to_json(self) -> dict:
        return {"version": VERSION, "active": self.active,
                "tabs": [{"url": t.url, "title": t.title} for t in self.tabs]}

    @staticmethod
    def from_json(d) -> "Session":
        if not isinstance(d, dict) or not isinstance(d.get("tabs"), list):
            return Session()
        tabs = []
        for t in d["tabs"][:MAX_TABS]:
            if isinstance(t, dict) and isinstance(t.get("url"), str) and t["url"].strip():
                tabs.append(SessionTab(t["url"].strip()[:4000], str(t.get("title") or "")[:300]))
        active = d.get("active")
        active = active if isinstance(active, int) and 0 <= active < len(tabs) else 0
        return Session(tabs, active)

    def is_trivial(self, start_url: str) -> bool:
        """다시 열 것이 없다: 탭이 없거나 새 탭 페이지 하나뿐."""
        return not self.tabs or (len(self.tabs) == 1 and self.tabs[0].url.startswith(start_url))


def load(path: Optional[Path]) -> Session:
    if path is None:
        return Session()
    try:
        return Session.from_json(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Session()


def save(path: Optional[Path], session: Session) -> bool:
    if path is None:
        return False
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(session.to_json(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False
