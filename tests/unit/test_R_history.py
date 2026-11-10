"""R: 방문 기록 (v0.8.2) — 저장, 합치기, 검색, 기록 페이지, 창에서 Ctrl+H·지우기."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from htex.viewer import historypage, startpage
from htex.viewer.visits import MERGE_SECONDS, VisitStore

ROOT = Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self, t: float = 1_794_283_200.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_record_merge_search_remove_and_reload(tmp_path):
    clk = Clock()
    p = tmp_path / "history.jsonl"
    st = VisitStore.load(p, clock=clk)
    st.record("htex://krunyx.com/a.htex", "A 문서")
    clk.t += 60
    st.record("/home/u/b.md", "")
    st.set_title("/home/u/b.md", "B 노트")
    clk.t += 60
    st.record("htex://krunyx.com/a.htex", "A 문서 (고침)")      # 30분 안: 새 줄 없이 맨 뒤로
    assert [v.url for v in st.search()] == ["htex://krunyx.com/a.htex", "/home/u/b.md"]
    assert st.search()[0].title == "A 문서 (고침)"
    clk.t += MERGE_SECONDS + 1
    st.record("htex://krunyx.com/a.htex", "A 문서")             # 30분 뒤: 새 방문
    assert len(st.visits) == 3
    assert [v.title for v in st.search("노트")] == ["B 노트"]
    assert [v.url for v in st.search("krunyx a.htex")] == ["htex://krunyx.com/a.htex"] * 2
    again = VisitStore.load(p, clock=clk)                        # 파일에서 다시
    assert [(v.url, v.title) for v in again.visits] == [(v.url, v.title) for v in st.visits]
    assert again.remove(again.search("노트")[0].id) and len(again.visits) == 2
    assert not again.remove(99)
    again.clear()
    assert VisitStore.load(p).visits == []


def test_bad_lines_are_skipped_and_empty_urls_ignored(tmp_path):
    p = tmp_path / "history.jsonl"
    p.write_text('{"t": 1, "url": "a"}\n{ 깨진\n{"url": ""}\n[1,2]\n{"t": 2, "url": "b", "title": "B"}\n',
                 encoding="utf-8")
    st = VisitStore.load(p)
    assert [v.url for v in st.visits] == ["a", "b"] and [v.id for v in st.visits] == [0, 1]
    assert st.record("  ") is None


def test_history_page_groups_by_day_and_has_no_scripts():
    now = time.mktime((2026, 11, 10, 15, 0, 0, 0, 0, -1))
    st = VisitStore(clock=lambda: now - 86400)
    st.record("htex://x.org/old.htex", "어제 문서")
    st.clock = lambda: now
    st.record("/home/u/<b>&.md", "오늘 <노트>")
    page = historypage.render(st.search(), "", "dark", now=now)
    assert "<script" not in page and 'data-theme="dark"' in page
    assert page.index("오늘 · 2026년 11월 10일") < page.index("어제 · 2026년 11월 9일")
    assert "오늘 &lt;노트&gt;" in page and "&lt;b&gt;" in page                # 이스케이프
    assert startpage.open_url("/home/u/<b>&.md").replace("&", "&amp;") in page
    assert historypage.forget_url(1) in page and "action?do=history-clear" in page
    empty = historypage.render([], "없는말")
    assert "찾는 기록이 없습니다." in empty and "history-clear" not in empty


def test_forget_request_is_parsed():
    assert startpage.parse_request("htexapp://start/forget?id=12") == ("forget", "12")
    assert startpage.parse_request("htexapp://start/forget?id=x") is None
    assert startpage.parse_request("htexapp://start/history?q=a") is None    # 페이지 자체는 가로채지 않는다


SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    from htex.viewer.visits import VisitStore
    visits = VisitStore.load(WORK / "history.jsonl")
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK, bookmarks=BookmarkStore(path=None), visits=visits)
    w.resize(1000, 700); w.show()
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    def wait_until(cond, t=10):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(40)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())
    def js(code, t=5):
        loop = QEventLoop(); box = {}
        w.current_tab().page.runJavaScript(code, 0, lambda v: (box.__setitem__("v", v), loop.quit()))
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); return box.get("v")

    pause(0.3)
    w.navigate(str(WORK / "a.htex")); wait_until(lambda: w.current_tab().title() == "가 문서")
    w.navigate(str(WORK / "b.htex")); wait_until(lambda: w.current_tab().title() == "나 문서")
    wait_until(lambda: len(visits.visits) == 2)
    res["recorded"] = [(Path(v.url).name, v.title) for v in visits.search()]
    res["menu"] = w.act_history.text() in [a.text() for a in w.app_menu.actions()]
    # 엔진이 주소를 제목처럼 알려 주어도(윈도) 기록 제목이 되지 않는다
    tab = w.current_tab()
    w._on_tab_title(tab, tab.current_url())
    w._on_tab_title(tab, "htexapp://doc-0123/b.htex")
    res["url_title_ignored"] = visits.search()[0].title

    t = w.show_history()
    wait_until(lambda: t.title() == "방문 기록")
    wait_until(lambda: js("document.querySelectorAll('.row').length") == 2)
    res["rows"] = json.loads(js("JSON.stringify([...document.querySelectorAll('.row .title')].map(e => e.textContent))") or "null")
    res["not_recorded"] = len(visits.visits) == 2               # 기록 페이지 자신은 남기지 않는다
    res["same_tab"] = w.show_history() is t and w.tabs.count() == 2

    # 검색 (검색 칸은 form GET → 같은 페이지)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w.activateWindow(); t.view.setFocus(); pause(0.3)
    js("document.querySelector('input[name=q]').focus()"); pause(0.3)
    QTest.keyClicks(t.view.focusProxy(), "b.htex"); QTest.keyClick(t.view.focusProxy(), Qt.Key.Key_Return)
    wait_until(lambda: js("document.querySelectorAll('.row').length") == 1)
    res["search"] = json.loads(js("JSON.stringify([...document.querySelectorAll('.row .title')].map(e => e.textContent))") or "null")

    # × 로 하나 지우기 (페이지가 보낸 요청만 받는다)
    js("document.querySelector('.del').click()")
    wait_until(lambda: len(visits.visits) == 1)
    res["after_forget"] = [Path(v.url).name for v in visits.visits]

    # 링크로 열기
    from htex.viewer.historypage import HISTORY_URL
    w.navigate(HISTORY_URL, tab=t); pause(0.5)
    wait_until(lambda: js("document.querySelectorAll('.row').length") == 1)
    js("document.querySelector('.row .link').click()")
    wait_until(lambda: t.title() == "가 문서")
    res["opened"] = t.title()

    # 모두 지우기 (확인 상자 없이)
    w.clear_history(confirm=False)
    res["cleared"] = visits.visits == [] and not (WORK / "history.jsonl").read_text(encoding="utf-8").strip()

    OUT.write_text(json.dumps(res, ensure_ascii=False))
    w.close(); app.quit()
''')


def test_history_in_window(tmp_path):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.htex").write_text("\\title{가 문서}\n\n가.\n", encoding="utf-8")
    (work / "b.htex").write_text("\\title{나 문서}\n\n나.\n", encoding="utf-8")
    script = tmp_path / "probe.py"
    script.write_text(SCRIPT, encoding="utf-8")
    out = tmp_path / "out.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox",
               HOME=str(tmp_path), HTEX_LANG="ko")
    proc = subprocess.run([sys.executable, str(script), str(ROOT), str(out), str(work)],
                          env=env, capture_output=True, text=True, timeout=180)
    assert out.exists(), proc.stderr[-3000:]
    r = json.loads(out.read_text(encoding="utf-8"))

    assert r["recorded"] == [["b.htex", "나 문서"], ["a.htex", "가 문서"]]
    assert r["menu"]
    assert r["url_title_ignored"] == "나 문서"
    assert r["rows"] == ["나 문서", "가 문서"] and r["not_recorded"] and r["same_tab"]
    assert r["search"] == ["나 문서"]
    assert r["after_forget"] == ["a.htex"]
    assert r["opened"] == "가 문서"
    assert r["cleared"]


# ---------------------------------------------------------------- 제목·주소 신호의 차례 (윈도에서 발견)
class _StubTab:
    def __init__(self):
        self.url = ""
        self.page_title = ""
        self.loading = False
        self.pinned_source = False
        self.crashed_url = None

    def current_url(self):
        return self.url

    def title(self):
        return self.page_title


class _StubWin:
    """ViewerWindow 의 기록 메서드만 빌려 쓴다 (주소 = 탭 주소 그대로)."""
    def __init__(self, store):
        self.visits = store

    def _visit_address(self, tab):
        return tab.url if tab.url.startswith("/") else ""


def _bind(win):
    from htex.viewer.app import ViewerWindow
    for name in ("_record_visit", "_visit_title_changed", "_real_title"):
        setattr(win, name, getattr(ViewerWindow, name).__get__(win) if name != "_real_title"
                else ViewerWindow._real_title)
    return win


def _go(win, tab, url, title, title_first):
    """한 페이지로 가기: 불러오기 시작 → (제목, 주소) 또는 (주소, 제목) → 불러오기 끝."""
    tab.loading = True
    if title_first:
        tab.page_title = title
        win._visit_title_changed(tab, title)
        tab.url = url
        win._record_visit(tab, True, title=False)
    else:
        tab.url = url
        win._record_visit(tab, True, title=False)
        tab.page_title = url                         # 엔진이 먼저 주소를 제목처럼
        win._visit_title_changed(tab, url)
        tab.page_title = title
        win._visit_title_changed(tab, title)
    tab.loading = False


@pytest.mark.parametrize("title_first", [False, True])
def test_titles_match_pages_in_either_signal_order(title_first):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    st = VisitStore(clock=lambda: 1_000_000.0)
    win = _bind(_StubWin(st))
    tab = _StubTab()
    _go(win, tab, "/d/a.htex", "가 문서", title_first)
    _go(win, tab, "/d/b.htex", "나 문서", title_first)
    _go(win, tab, "/d/c.htex", "다 문서", title_first)
    assert [(v.url, v.title) for v in st.search()] == [
        ("/d/c.htex", "다 문서"), ("/d/b.htex", "나 문서"), ("/d/a.htex", "가 문서")]
    # 불러온 뒤 페이지가 제목을 바꾸면(웹 페이지) 그 방문의 제목이 바뀐다
    tab.page_title = "다 문서 (2)"
    win._visit_title_changed(tab, "다 문서 (2)")
    assert st.search()[0].title == "다 문서 (2)" and st.search()[1].title == "나 문서"
