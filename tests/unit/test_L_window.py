"""L: Chrome 모양 창 (탭 줄 · 도구줄 · 북마크바 · 페이지). 화면 없이 하위 프로세스로. PySide6 가 없으면 건너뛴다."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets")

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer, Qt, QPoint
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app = QApplication([])
    from htex.viewer.app import ViewerWindow, START_URL
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    bm = BookmarkStore.load(WORK / "bookmarks.json")
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK, bookmarks=bm)
    w.resize(1100, 760); w.show()
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    def wait_until(cond, t=8):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(30)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())
    def js(code, tab=None, t=4):
        tab = tab or w.current_tab(); loop = QEventLoop(); box = {}
        tab.page.runJavaScript(code, 0, lambda v: (box.__setitem__("v", v), loop.quit()))
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); return box.get("v")
    def y(widget):
        return widget.mapTo(w, QPoint(0, 0)).y()

    w.activateWindow(); w.raise_()
    wait_until(lambda: QApplication.activeWindow() is w, 3); pause(0.2)

    # 네 줄의 순서 (위에서 아래로)
    res["order"] = [y(w.tab_strip) < y(w.navbar) < y(w.bookmarks_bar) < y(w.page_area)]
    res["menubar_hidden"] = not w.menuBar().isVisible()
    res["nav_buttons"] = [b.defaultAction().text() for b in (w.navbar.back, w.navbar.forward,
                                                             w.navbar.reload, w.navbar.home)]
    res["bar_items"] = [b.text() for b in w.bookmarks_bar.buttons]

    # 새 탭 = 시작 페이지, 비어 있는 탭으로 본다, 주소창에 초점
    QTest.keyClick(w, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    t = w.current_tab()
    wait_until(lambda: t.title() == "새 탭" and not t.loading)
    res["start"] = {"url": t.current_url(), "blank": t.is_blank(), "focus": w.address.hasFocus(),
                    "address": w.address.text(), "tiles": js("document.querySelectorAll('a.tile').length", t),
                    "tab_text": w.tabs.tabText(w.tabs.currentIndex())}

    # 시작 페이지의 입력 칸에 파일 경로를 넣고 Enter → 그 문서가 열린다
    doc = str(ROOT / "examples/oscillator.htex")
    js("var i=document.querySelector('input[name=q]'); i.value=" + json.dumps(doc) + "; i.form.submit();", t)
    ok = wait_until(lambda: t.title() == "조화 진동자 노트")
    res["start_go"] = {"ok": ok, "address": w.address.text(), "back": w.act_back.isEnabled()}

    # 별: 북마크에 추가 → 북마크바에 생기고 별이 채워진다. Ctrl+D 상자의 삭제로 지운다
    n0 = len(bm.bar)
    w.omnibox.star.click(); pause(0.2)
    res["star_add"] = {"added": len(bm.bar) - n0, "starred": w.omnibox.starred,
                       "last_button": w.bookmarks_bar.buttons[-1].text(),
                       "popup": w.last_popup.isVisible(), "saved": doc in (WORK / "bookmarks.json").read_text("utf-8")}
    w.last_popup.remove_btn.click(); pause(0.1)
    res["star_remove"] = {"count": len(bm.bar) - n0, "starred": w.omnibox.starred}
    w.bookmark_page(); w.last_popup.name.setText("진동자"); w.last_popup.done_btn.click(); pause(0.1)
    res["star_rename"] = bm.find(doc)[1].title

    # 북마크바 단추로 열기 (새 탭에서: 가운데 클릭 대신 신호)
    n = w.tabs.count()
    w.open_bookmark(doc, True); pause(0.2)
    res["open_bg"] = {"count": w.tabs.count() - n, "current_same": w.current_tab() is t}

    # 다른 문서가 시작 페이지 주소로 링크를 걸어도 무시한다
    calls = []
    t.page.start_request.connect(lambda k, v: calls.append((k, v)))
    js("location.href='htexapp://start/open?u=%2Fetc%2Fpasswd'", t); pause(0.5)
    res["start_from_doc"] = {"calls": calls, "title": t.title()}

    # 확대 배율 칩: 100% 면 숨기고 아니면 보인다
    w.zoom_step(1); pause(0.05)
    res["zoom_chip"] = [w.zoom_label.isVisible(), w.zoom_label.text()]
    w.set_zoom(1.0); pause(0.05)
    res["zoom_chip"] += [w.zoom_label.isVisible()]

    # 페이지 정보 단추 (진단)
    res["info"] = {"kind": w.omnibox.info_kind, "diag": w.diag_label.text()}
    w.show_page_info(); pause(0.1)
    res["info_popup"] = w.last_popup.isVisible(); w.last_popup.close()

    # 찾기 상자: 페이지 오른쪽 위
    w.find_bar.open_bar(); pause(0.1)
    fb = w.find_bar.geometry(); area = w.page_area.rect()
    res["find_pos"] = [fb.top() == 0, area.width() - fb.right() < 60, w.find_bar.parentWidget() is w.page_area]
    w.find_bar.close_bar()

    # 북마크바 숨기기·보이기 (Ctrl+Shift+B)
    QTest.keyClick(w, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    pause(0.05)
    res["bar_toggle"] = [w.bookmarks_bar.isVisible()]
    w.toggle_bookmarks_bar(); pause(0.05)
    res["bar_toggle"] += [w.bookmarks_bar.isVisible()]

    # 홈 = 시작 페이지
    w.act_home.trigger()
    wait_until(lambda: w.current_tab().is_start() and not w.current_tab().loading)
    res["home"] = {"start": w.current_tab().is_start(), "address": w.address.text()}
    w.back(); wait_until(lambda: w.current_tab().title() == "조화 진동자 노트")
    res["home_back"] = w.current_tab().title()

    # 탭 옮기기: 막대와 페이지 더미의 순서가 같이 바뀐다
    tabs_before = w.tab_list()
    w.tab_strip.bar.moveTab(0, w.tabs.count() - 1); pause(0.05)
    res["move"] = {"same_order": [w.tabs.widget(i) for i in range(w.tabs.count())] == tabs_before[1:] + tabs_before[:1],
                   "current_ok": w.tabs.currentWidget() is w.tab_list()[w.tabs.currentIndex()]}

    # 탭 많이: 최소 폭까지 줄어든다
    for _ in range(25):
        w.new_tab(focus_address=False, start_page=False)
    pause(0.1)
    bar = w.tab_strip.bar
    res["many"] = {"w": bar.tabRect(0).width(), "count": w.tabs.count()}
    # 다른 탭 닫기
    w.close_other_tabs(w.tabs.indexOf(t)); pause(0.1)
    res["close_others"] = [w.tabs.count(), w.current_tab() is t]
    # 가운데 클릭으로 탭 닫기 (하나 더 만들어서)
    t2 = w.new_tab(focus_address=False); pause(0.2)
    r = bar.tabRect(w.tabs.indexOf(t2))
    QTest.mouseClick(bar, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, r.center())
    pause(0.1)
    res["middle_close"] = w.tabs.count()

    # 테마: 창 테두리 색이 바뀐다
    w.set_theme("dark"); pause(0.1)
    res["dark"] = [w.chrome_palette.dark, "#202124" in w.styleSheet()]
    w.set_theme("light"); pause(0.1)
    res["light"] = [w.chrome_palette.dark, "#dee1e6" in w.styleSheet()]
    w.set_theme("system")

    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    w.handler.shutdown()
''')


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    work = tmp_path_factory.mktemp("l-window")
    out = work / "out.json"
    script = work / "script.py"
    script.write_text(SCRIPT, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu",
               XDG_CONFIG_HOME=str(work / "config"), XDG_CACHE_HOME=str(work / "cache"),
               XDG_DATA_HOME=str(work / "data"), HOME=str(work))
    p = subprocess.run([sys.executable, str(script), str(ROOT), str(out), str(work)],
                       env=env, capture_output=True, text=True, timeout=240)
    if not out.exists():
        pytest.fail("창 스크립트 실패:\n" + p.stdout[-3000:] + p.stderr[-3000:])
    return json.loads(out.read_text(encoding="utf-8"))


def test_four_rows_like_chrome(run):
    assert run["order"] == [True]
    assert run["menubar_hidden"] or sys.platform == "darwin"
    assert run["nav_buttons"] == ["뒤로", "앞으로", "새로고침", "홈"]
    assert run["bar_items"] == ["HyperTeX", "시작하기", "krunyx"]       # 처음 실행 기본 북마크


def test_new_tab_is_start_page(run):
    s = run["start"]
    assert s["url"] == "htexapp://start/" and s["blank"] and s["focus"]
    assert s["address"] == "" and s["tab_text"] == "새 탭"
    assert s["tiles"] == 4                                                # 북마크 3 + 파일 열기


def test_start_page_input_opens_document(run):
    g = run["start_go"]
    assert g["ok"] and g["address"].endswith("oscillator.htex") and g["back"]


def test_star_adds_edits_and_removes_bookmark(run):
    a = run["star_add"]
    assert a == {"added": 1, "starred": True, "last_button": "조화 진동자 노트", "popup": True, "saved": True}
    assert run["star_remove"] == {"count": 0, "starred": False}
    assert run["star_rename"] == "진동자"


def test_bookmark_in_new_tab(run):
    assert run["open_bg"] == {"count": 1, "current_same": True}


def test_start_requests_from_other_pages_are_ignored(run):
    assert run["start_from_doc"]["calls"] == []
    assert run["start_from_doc"]["title"] == "조화 진동자 노트"


def test_zoom_chip_and_page_info(run):
    assert run["zoom_chip"] == [True, "110%", False]
    assert run["info"]["kind"] == "doc" and run["info"]["diag"].startswith("진단: 오류 0")
    assert run["info_popup"]


def test_find_box_top_right(run):
    assert run["find_pos"] == [True, True, True]


def test_bookmarks_bar_toggle_and_home(run):
    assert run["bar_toggle"] == [False, True]
    assert run["home"] == {"start": True, "address": ""}
    assert run["home_back"] == "조화 진동자 노트"


def test_tabs_move_shrink_and_close(run):
    assert run["move"] == {"same_order": True, "current_ok": True}
    assert run["many"]["w"] <= 60 and run["many"]["count"] >= 27
    assert run["close_others"] == [1, True]
    assert run["middle_close"] == 1


def test_window_theme_colors(run):
    assert run["dark"] == [True, True] and run["light"] == [False, True]
