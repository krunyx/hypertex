"""N: macOS 에서 탭 줄을 제목 막대 자리로 (Chrome). 실제 제목 막대는 맥에서만 보이므로, 여기서는
설정값 해석과 창 쪽 논리(플래그·신호등 자리·빈 곳 끌기/더블클릭)를 화면 없이 확인한다."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from htex.viewer import macwin

ROOT = Path(__file__).resolve().parents[2]


def test_native_struct_layout():
    # NSRect 는 double 넷 (arm64·x86_64 공통). 틀리면 맥에서 단추가 엉뚱한 데로 간다.
    assert ctypes.sizeof(macwin.NSRect) == 32 and ctypes.sizeof(macwin.NSPoint) == 16


def test_native_calls_are_noops_off_cocoa():
    assert macwin.hide_title_text(None) is False
    assert macwin.place_traffic_lights(None, 40, 25) is False


def test_double_click_setting_values():
    assert macwin.action_from_setting("Maximize") == "zoom"
    assert macwin.action_from_setting("Fill") == "zoom"          # macOS 15
    assert macwin.action_from_setting("Minimize") == "minimize"
    assert macwin.action_from_setting("None") == "none"
    assert macwin.action_from_setting("") == "zoom"


@pytest.mark.skipif(sys.platform == "darwin", reason="맥이 아닌 곳의 동작")
def test_not_supported_off_mac():
    assert not macwin.supported()
    assert macwin.double_click_action() == "zoom"


@pytest.mark.skipif(sys.platform != "darwin", reason="Objective-C 런타임은 맥에만")
def test_reads_mac_double_click_setting():
    # ctypes 로 NSUserDefaults 를 실제로 부른다 (원형이 틀리면 여기서 죽는다)
    assert macwin.double_click_action() in ("zoom", "minimize", "none")


pytest.importorskip("PySide6.QtWebEngineWidgets")

SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer, Qt, QPoint
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app = QApplication([])
    from htex.viewer import app as appmod
    from htex.viewer.app import ViewerWindow
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()

    res = {}
    # 기본값: 맥이 아니면 예전처럼
    plain = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK, bookmarks=BookmarkStore())
    res["default"] = {"on": plain.titlebar_tabs, "inset": plain.tab_strip.left_inset,
                      "expanded": bool(plain.windowFlags() & Qt.WindowType.ExpandedClientAreaHint)}

    # 강제로 켠 창 (맥에서 하는 일과 같은 경로)
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK, bookmarks=BookmarkStore(), titlebar_tabs=True)
    w.resize(1000, 700); w.show(); pause(0.3)
    flags = w.windowFlags()
    res["flags"] = [bool(flags & Qt.WindowType.ExpandedClientAreaHint),
                    bool(flags & Qt.WindowType.NoTitleBarBackgroundHint),
                    not w.testAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea)]
    # 탭 줄 위에는 아무것도 없다. (offscreen 맥에서는 메뉴 막대가 화면 위가 아니라 창 안에 들어가므로 그 높이만 뺀다)
    mb = w.menuBar()
    in_window_menu = mb.height() if (mb.isVisible() and mb.geometry().top() == 0 and mb.actions()) else 0
    res["strip_top"] = w.tab_strip.mapTo(w, QPoint(0, 0)).y() - in_window_menu
    res["inset"] = w.tab_strip.left_inset
    res["tab_center"] = w.tab_strip.tab_center_y()
    first = w.tab_strip.bar.tabRect(0).topLeft()
    res["first_tab_x"] = w.tab_strip.bar.mapTo(w, first).x()

    # 빈 곳 더블클릭 → 제목 막대처럼 (새 탭이 아니다)
    n = w.tabs.count()
    calls = []
    w.tab_strip.titlebar_double_clicked.connect(lambda: calls.append(1))
    empty = QPoint(w.tab_strip.width() - 20, w.tab_strip.height() // 2)
    QTest.mouseDClick(w.tab_strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
    pause(0.2)
    res["dclick"] = {"signals": len(calls), "tabs_same": w.tabs.count() == n}

    # 빈 곳 누르기 → 운영체제 창 끌기 요청
    moves = []
    handle = w.windowHandle()
    orig = w.tab_strip.start_window_drag
    w.tab_strip.start_window_drag = lambda: (moves.append(1), orig())[1] or True
    QTest.mousePress(w.tab_strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
    QTest.mouseRelease(w.tab_strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
    res["drag_requested"] = len(moves)

    # 탭 위 클릭은 여전히 탭 선택
    w.new_tab(); pause(0.2)
    r = w.tab_strip.bar.tabRect(0)
    QTest.mouseClick(w.tab_strip.bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    pause(0.1)
    res["tab_click"] = w.tabs.currentIndex()

    # 전체 화면이면 신호등 자리를 비우지 않는다
    w.showFullScreen(); pause(0.3)
    res["fullscreen_inset"] = w.tab_strip.left_inset
    w.showNormal(); pause(0.3)
    res["normal_inset"] = w.tab_strip.left_inset

    # 끈 창: 빈 곳 더블클릭 신호 없음
    calls.clear()
    QTest.mouseDClick(plain.tab_strip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
    res["plain_dclick"] = len(calls)

    OUT.write_text(json.dumps(res), encoding="utf-8")
    w.handler.shutdown()
''')


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    work = tmp_path_factory.mktemp("n-titlebar")
    out = work / "out.json"
    script = work / "script.py"
    script.write_text(SCRIPT, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu",
               XDG_CONFIG_HOME=str(work / "config"), XDG_CACHE_HOME=str(work / "cache"),
               XDG_DATA_HOME=str(work / "data"), HOME=str(work))
    p = subprocess.run([sys.executable, str(script), str(ROOT), str(out), str(work)],
                       env=env, capture_output=True, text=True, timeout=180)
    if not out.exists():
        pytest.fail("창 스크립트 실패:\n" + p.stdout[-3000:] + p.stderr[-3000:])
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.skipif(sys.platform == "darwin", reason="맥에서는 기본값이 켜짐")
def test_default_off_mac(run):
    assert run["default"] == {"on": False, "inset": 0, "expanded": False}


def test_titlebar_mode_window(run):
    assert run["flags"] == [True, True, True]
    assert run["strip_top"] == 0                       # 탭 줄이 창 맨 위
    assert run["inset"] == macwin.TRAFFIC_LIGHTS_W
    assert 20 <= run["tab_center"] <= 30                # 신호등 단추를 맞출 탭 몸통 가운데 (pt)
    assert run["first_tab_x"] >= macwin.TRAFFIC_LIGHTS_W   # 첫 탭이 신호등 단추와 겹치지 않는다


def test_empty_area_acts_as_titlebar(run):
    assert run["dclick"] == {"signals": 1, "tabs_same": True}
    assert run["drag_requested"] == 1
    assert run["tab_click"] == 0
    assert run["plain_dclick"] == 0


def test_fullscreen_drops_inset(run):
    assert run["fullscreen_inset"] == 0
    assert run["normal_inset"] == macwin.TRAFFIC_LIGHTS_W


COCOA_SCRIPT = textwrap.dedent(r'''
    import json, sys, ctypes
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtCore import Qt, QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
    app = QApplication([])
    from htex.viewer import macwin
    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    w = QMainWindow(); w.setCentralWidget(QWidget())
    w.setWindowFlag(Qt.WindowType.ExpandedClientAreaHint, True)
    w.setWindowFlag(Qt.WindowType.NoTitleBarBackgroundHint, True)
    w.setWindowTitle("제목"); w.resize(600, 400); w.show(); pause(0.5)
    res = {"platform": app.platformName(), "supported": macwin.supported()}
    res["hidden"] = macwin.hide_title_text(w)
    res["placed"] = macwin.place_traffic_lights(w, 40, 25)
    pause(0.2)
    win = macwin._ns_window(w)
    close = macwin._send(win, "standardWindowButton:", 0, argtypes=(ctypes.c_ulong,))
    bf = macwin._send(close, "frame", restype=macwin.NSRect)
    cf = macwin._send(macwin._send(close, "superview"), "frame", restype=macwin.NSRect)
    res["center_from_top"] = cf.size.height - (bf.origin.y + bf.size.height / 2)
    res["error"] = macwin.last_error
    print(json.dumps(res))
''')


@pytest.mark.skipif(sys.platform != "darwin", reason="실제 맥 창이 있어야 한다")
def test_real_cocoa_window(tmp_path):
    """GitHub 맥 실행기에는 화면 세션이 있다: 실제 NSWindow 에 네이티브 호출이 먹는지 본다."""
    script = tmp_path / "cocoa.py"
    script.write_text(COCOA_SCRIPT, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    p = subprocess.run([sys.executable, str(script), str(ROOT)], env=env, capture_output=True, text=True,
                       timeout=120)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("{")]
    if not lines:
        pytest.skip("맥 화면 세션 없음:\n" + p.stderr[-1500:])
    res = json.loads(lines[-1])
    if res["platform"] != "cocoa":
        pytest.skip("cocoa 아님")
    assert res["supported"] and res["hidden"] and res["placed"], res
    assert abs(res["center_from_top"] - 25) < 1.5, res
