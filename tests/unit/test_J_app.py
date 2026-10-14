"""J: 뷰어 창 다듬기 (탭, 찾기, 확대, 테마, 자동 새로고침, 원문 보기, 단일 인스턴스). 화면 없이 하위 프로세스로.
PySide6 가 없으면 건너뛴다."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets")

ROOT = Path(__file__).resolve().parents[2]

WINDOW = textwrap.dedent(r'''
    import json, os, sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer, Qt, QPoint
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app = QApplication([])
    from htex.viewer.app import ViewerWindow, settings
    from htex.viewer.core import ViewerCore, TreeCache
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK)
    w.resize(1000, 760); w.show()
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    def wait_until(cond, t=6):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(30)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())
    def js(code, tab=None, t=4):
        tab = tab or w.current_tab(); loop = QEventLoop(); box = {}
        tab.page.runJavaScript(code, 0, lambda v: (box.__setitem__("v", v), loop.quit()))
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); return box.get("v")
    def titled(tab, title):
        return wait_until(lambda: tab.title() == title and w.tabs.tabText(w.tabs.indexOf(tab)) == title)
    def jj(code, tab=None, t=4):
        v = js("JSON.stringify(" + code + ")", tab, t)
        return json.loads(v) if isinstance(v, str) and v else None

    # 탭 세 개
    w.navigate(str(WORK / "live.htex")); titled(w.current_tab(), "살아 있는 문서")
    t2 = w.new_tab(str(ROOT / "tests/docs/12-cross-doc-refs.htex")); titled(t2, "문서 간 참조")
    t3 = w.new_tab(str(ROOT / "examples/oscillator.htex")); titled(t3, "조화 진동자 노트")
    res["tabs"] = [w.tabs.tabText(i) for i in range(w.tabs.count())]
    res["xref"] = jj("Array.from(document.querySelectorAll('a.htex-xref')).map(a=>a.textContent)", t2)
    # Ctrl+1 / Ctrl+9 / Ctrl+Tab
    QTest.keyClick(w, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier); pause(0.05)
    res["ctrl1"] = w.tabs.currentIndex()
    QTest.keyClick(w, Qt.Key.Key_9, Qt.KeyboardModifier.ControlModifier); pause(0.05)
    res["ctrl9"] = w.tabs.currentIndex()
    QTest.keyClick(w, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier); pause(0.05)
    res["ctrltab"] = w.tabs.currentIndex()
    res["address0"] = w.address.text()

    # 가운데 클릭 → 새 탭 (뒤), 원래 탭 히스토리는 그대로
    w.tabs.setCurrentWidget(t2); pause(0.2)
    rect = json.loads(js("var r=document.querySelector('a.htex-xref').getBoundingClientRect();"
                         "JSON.stringify([r.left+r.width/2,r.top+r.height/2])", t2) or "[0,0]")
    n0 = w.tabs.count()
    target = t2.view.focusProxy() or t2.view
    QTest.mouseClick(target, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(rect[0]), int(rect[1])))
    wait_until(lambda: w.tabs.count() == n0 + 1 and w.tabs.widget(w.tabs.indexOf(t2) + 1).title() == "문서 안 참조")
    res["middle"] = {"count": w.tabs.count() - n0, "current_is_t2": w.current_tab() is t2,
                     "new_title": w.tabs.widget(w.tabs.indexOf(t2) + 1).title(),
                     "t2_history": len(t2.history.entries)}
    # Ctrl+W 로 닫기
    w.tabs.setCurrentIndex(w.tabs.indexOf(t2) + 1); pause(0.05)
    QTest.keyClick(w, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier); pause(0.1)
    res["after_close"] = w.tabs.count() - n0
    # Ctrl+T
    QTest.keyClick(w, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier); pause(0.1)
    res["ctrl_t"] = {"count": w.tabs.count(), "blank": w.current_tab().is_blank(),
                     "address_focus": w.address.hasFocus()}
    w.close_tab(); pause(0.1)

    # 찾기
    w.tabs.setCurrentWidget(t3); pause(0.1)
    QTest.keyClick(w, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier); pause(0.1)
    res["find_visible"] = w.find_bar.isVisible() and w.find_bar.edit.hasFocus()
    w.find_bar.edit.setText("진동")
    wait_until(lambda: w.find_bar.matches[1] > 0)
    res["find1"] = list(w.find_bar.matches) + [w.find_bar.count.text()]
    QTest.keyClick(w.find_bar.edit, Qt.Key.Key_Return); wait_until(lambda: w.find_bar.matches[0] == 2)
    res["find2"] = list(w.find_bar.matches)
    QTest.keyClick(w.find_bar.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    wait_until(lambda: w.find_bar.matches[0] == 1)
    res["find3"] = list(w.find_bar.matches)
    w.find_bar.edit.setText("없는글자열"); wait_until(lambda: w.find_bar.matches[1] == 0)
    res["find_none"] = w.find_bar.count.text()
    QTest.keyClick(w.find_bar.edit, Qt.Key.Key_Escape); pause(0.05)
    res["find_closed"] = not w.find_bar.isVisible()

    # 확대 (탭마다)
    for _ in range(3):
        QTest.keyClick(w, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
    pause(0.1)
    res["zoom"] = [t3.zoom, round(t3.view.zoomFactor(), 3), w.zoom_label.text(), t2.zoom]
    w.tabs.setCurrentWidget(t2); pause(0.05)
    res["zoom_other_label"] = w.zoom_label.text()
    w.tabs.setCurrentWidget(t3); pause(0.05)
    for _ in range(20):
        w.zoom_step(1)
    res["zoom_max"] = t3.zoom
    for _ in range(30):
        w.zoom_step(-1)
    res["zoom_min"] = t3.zoom
    QTest.keyClick(w, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier); pause(0.05)
    res["zoom_reset"] = t3.zoom

    # 테마
    w.set_theme("dark"); pause(0.3)
    res["theme_dark"] = [js("document.documentElement.getAttribute('data-theme')", t) for t in (t2, t3)]
    res["theme_saved"] = settings().value("view/theme")
    w.set_theme("system"); pause(0.3)
    res["theme_system"] = js("document.documentElement.getAttribute('data-theme')", t3)
    w.set_theme("light"); pause(0.2)
    t4 = w.new_tab(str(ROOT / "tests/docs/01-minimal.htex")); wait_until(lambda: bool(t4.title()))
    pause(0.2)
    res["theme_new_tab"] = js("document.documentElement.getAttribute('data-theme')", t4)
    w.set_theme("system")

    # 원문 보기
    w.tabs.setCurrentWidget(t3); pause(0.05)
    QTest.keyClick(w, Qt.Key.Key_U, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: w.tabs.tabText(w.tabs.currentIndex()).startswith("원문: osc"))
    src = w.current_tab()
    res["source"] = {"title": src.title(), "tab": w.tabs.tabText(w.tabs.currentIndex()),
                     "scripts": js("document.scripts.length", src),
                     "has": js("document.body.textContent.indexOf('\\\\documentclass{hypertex}')>=0", src),
                     "address": w.address.text()}

    # 자동 새로고침: 슬라이더 값·스크롤 유지
    t1 = w.tab_list()[0]
    w.tabs.setCurrentWidget(t1); pause(0.1)
    res["watch"] = sorted(p.name for p in t1.watched_files())
    js("HTEX.setParam('k', 2.5); window.scrollTo(0, 400);", t1); pause(0.1)
    res["before"] = jj("[HTEX.getParams().k, Math.round(window.scrollY)]", t1)
    live = WORK / "live.htex"
    live.write_text(live.read_text(encoding="utf-8").replace("첫 판", "둘째 판"), encoding="utf-8")
    t0 = time.monotonic()
    ok = wait_until(lambda: (js("document.body.textContent.indexOf('둘째 판')>=0", t1, 1) or False), 8)
    res["reload1"] = {"ok": ok, "seconds": round(time.monotonic() - t0, 2), "count": t1.auto_reloads}
    pause(0.4)
    res["after"] = jj("[HTEX.getParams().k, Math.round(window.scrollY)]", t1)
    # 의존 파일(\usemacros) 변경도
    (WORK / "macros.htex").write_text("\\newcommand{\\who}{매크로둘}\n", encoding="utf-8")
    ok = wait_until(lambda: (js("document.body.textContent.indexOf('매크로둘')>=0", t1, 1) or False), 8)
    res["reload_dep"] = ok
    # 여러 번 연달아 저장 → 묶어서 한 번
    n = t1.auto_reloads
    for i in range(5):
        live.write_text(live.read_text(encoding="utf-8") + f"\n% {i}\n", encoding="utf-8"); pause(0.03)
    pause(1.2)
    res["debounced"] = t1.auto_reloads - n
    w.grab().save(str(OUT.with_suffix(".png")))
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    w.close()
''')

LIVE = r"""\documentclass{hypertex}
\title{살아 있는 문서}
\usemacros{macros.htex}
\parameter{k}{0}{5}{1}[step=0.5]
\begin{document}
첫 판. 값 $k = \showparam{k}$, \who.
""" + "\n\n".join(f"문단 {i}. " + "긴 줄을 채우는 글자. " * 20 for i in range(40)) + "\n\\end{document}\n"


def _env(d: Path) -> dict:
    return dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox",
                PYTHONPATH=str(ROOT), XDG_CACHE_HOME=str(d / "cache"), XDG_CONFIG_HOME=str(d / "config"),
                HOME=str(d / "home"), HTEX_VIEWER_INSTANCE=f"htex-test-{os.getpid()}-{d.name}")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("jviewer")
    (d / "home").mkdir()
    work = d / "work"
    work.mkdir()
    (work / "live.htex").write_text(LIVE, encoding="utf-8")
    (work / "macros.htex").write_text("\\newcommand{\\who}{매크로하나}\n", encoding="utf-8")
    (d / "run.py").write_text(WINDOW, encoding="utf-8")
    out = d / "result.json"
    proc = subprocess.run([sys.executable, str(d / "run.py"), str(ROOT), str(out), str(work)],
                          cwd=str(ROOT), env=_env(d), capture_output=True, text=True, timeout=29)
    if not out.exists():
        pytest.fail("뷰어 하위 프로세스 실패:\n" + proc.stderr[-3000:])
    return json.loads(out.read_text(encoding="utf-8"))


def test_tabs(run):
    assert run["tabs"] == ["살아 있는 문서", "문서 간 참조", "조화 진동자 노트"]
    assert (run["ctrl1"], run["ctrl9"], run["ctrltab"]) == (0, 2, 0)
    assert run["address0"].endswith("live.htex")
    assert run["after_close"] == 0
    assert run["ctrl_t"]["blank"] and run["ctrl_t"]["address_focus"]


def test_middle_click_opens_background_tab(run):
    m = run["middle"]
    assert m == {"count": 1, "current_is_t2": True, "new_title": "문서 안 참조", "t2_history": 1}


def test_cross_doc_numbers_in_viewer(run):
    assert run["xref"] == ["1", "(eq:aadag)", "2"]


def test_find(run):
    assert run["find_visible"]
    assert run["find1"][1] >= 3 and run["find1"][0] == 1 and run["find1"][2] == f"1/{run['find1'][1]}"
    assert run["find2"][0] == 2 and run["find3"][0] == 1
    assert run["find_none"] == "일치 없음" and run["find_closed"]


def test_zoom(run):
    assert run["zoom"] == [1.5, 1.5, "150%", 1.0]          # 100 → 110 → 125 → 150
    assert run["zoom_other_label"] == "100%"
    assert run["zoom_max"] == 3.0 and run["zoom_min"] == 0.5 and run["zoom_reset"] == 1.0


def test_theme(run):
    assert run["theme_dark"] == ["dark", "dark"]
    assert run["theme_saved"] == "dark"
    assert not run["theme_system"]                   # 속성 없음
    assert run["theme_new_tab"] == "light"


def test_view_source(run):
    s = run["source"]
    assert s["title"] == "원문: oscillator.htex" and s["tab"] == "원문: oscillator.htex"
    assert s["scripts"] == 0 and s["has"] is True
    assert s["address"].startswith("원문: ") and s["address"].endswith("oscillator.htex")


def test_auto_reload(run):
    assert run["watch"] == ["live.htex", "macros.htex"]
    assert run["before"] == [2.5, 400]
    assert run["reload1"]["ok"] and run["reload1"]["count"] == 1
    assert run["after"] == [2.5, 400]          # 슬라이더 값과 스크롤 유지
    assert run["reload_dep"]
    assert run["debounced"] == 1               # 300ms 묶음


# ====================================================================== 단일 인스턴스
FIRST = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2])
    from PySide6.QtCore import QTimer
    import htex.viewer.app as A
    from PySide6.QtWidgets import QApplication
    seen = {}
    orig = A.ViewerWindow.open_targets
    def spy(self, targets, raise_window=True):
        seen.setdefault("calls", []).append(list(targets))
        orig(self, targets, raise_window)
        if len(seen["calls"]) == 1:
            Path(sys.argv[3]).write_text("ready")
        if len(seen["calls"]) == 2:       # 처음 대상 + 두 번째 실행이 넘긴 것
            def done():
                win = self
                seen["tabs"] = [win.tabs.tabText(i) for i in range(win.tabs.count())]
                seen["urls"] = [t.current_url() for t in win.tab_list()]
                OUT.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
                QApplication.instance().quit()
            QTimer.singleShot(2500, done)
    A.ViewerWindow.open_targets = spy
    sys.exit(A.run([sys.argv[4]]))
''')

SECOND = textwrap.dedent(r'''
    import sys, time
    sys.path.insert(0, sys.argv[1])
    import htex.viewer.app as A
    t0 = time.monotonic()
    code = A.run(sys.argv[2:])
    print("EXIT", code, round(time.monotonic() - t0, 2))
''')


def test_second_instance_hands_off(tmp_path):
    (tmp_path / "home").mkdir()
    env = _env(tmp_path)
    (tmp_path / "first.py").write_text(FIRST, encoding="utf-8")
    (tmp_path / "second.py").write_text(SECOND, encoding="utf-8")
    out, ready = tmp_path / "out.json", tmp_path / "ready"
    docs = ROOT / "tests" / "docs"
    first = subprocess.Popen([sys.executable, str(tmp_path / "first.py"), str(ROOT), str(out), str(ready),
                              str(docs / "01-minimal.htex")], cwd=str(ROOT), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline and first.poll() is None:
            time.sleep(0.05)
        assert ready.exists(), first.stderr.read()[-2000:] if first.poll() is not None else "no ready"
        # 두 번째 실행: 다른 현재 폴더에서 상대 경로와 file: URL
        second = subprocess.run([sys.executable, str(tmp_path / "second.py"), str(ROOT),
                                 "11-internal-refs.htex", (docs / "02-metadata.htex").as_uri()],
                                cwd=str(docs), env=env, capture_output=True, text=True, timeout=15)
        assert "EXIT 0" in second.stdout, second.stderr[-2000:]
        assert float(second.stdout.split()[-1]) < 5      # 창을 띄우지 않고 곧 끝난다
        first.wait(timeout=12)
    finally:
        if first.poll() is None:
            first.kill()
    res = json.loads(out.read_text(encoding="utf-8"))
    assert res["calls"][0] == [str(docs / "01-minimal.htex")]
    assert res["calls"][1] == [str(docs / "11-internal-refs.htex"), str(docs / "02-metadata.htex")]
    assert len(res["tabs"]) == 3 and "문서 안 참조" in res["tabs"]


def test_file_open_event_filter():
    """QFileOpenEvent → 대상 문자열 (파일 경로·htex:// URL). 이벤트 객체만 만들면 되므로 창 없이."""
    code = textwrap.dedent(r'''
        import sys, json
        sys.path.insert(0, sys.argv[1])
        from PySide6.QtCore import QUrl, QCoreApplication
        from PySide6.QtGui import QFileOpenEvent
        app = QCoreApplication([])
        from htex.viewer.app import FileOpenFilter
        f = FileOpenFilter()
        got = []
        f.opened.connect(got.append)
        app.installEventFilter(f)
        app.sendEvent(app, QFileOpenEvent("/tmp/a b.htex"))      # 창이 생기기 전 → pending
        f.connected = True
        app.sendEvent(app, QFileOpenEvent(QUrl("htex://ex.org/n/a.htex#eq:1")))
        app.sendEvent(app, QFileOpenEvent(QUrl.fromLocalFile("/tmp/c.htex")))
        print(json.dumps({"pending": f.pending, "got": got}))
    ''')
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT))
    p = subprocess.run([sys.executable, "-c", code, str(ROOT)], env=env, capture_output=True, text=True,
                       timeout=25)
    res = json.loads(p.stdout.strip().splitlines()[-1])
    assert res["pending"] == ["/tmp/a b.htex"]
    assert res["got"] == ["htex://ex.org/n/a.htex#eq:1", "/tmp/c.htex"]
