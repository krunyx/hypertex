"""R: 로컬 파일 열기 (v0.8.0) — 주소창 왼쪽 파일 단추, 창·주소창·페이지에 끌어다 놓기.

화면 없이 하위 프로세스로. PySide6 가 없으면 건너뛴다.
"""
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
    OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer, QMimeData, QUrl, QPointF, Qt, QPoint
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer import chrome
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK,
                     bookmarks=BookmarkStore.load(WORK / "bookmarks.json"))
    w.resize(1000, 700); w.show()
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    def wait_until(cond, t=8):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(30)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())
    def mime(paths=None, text=None):
        m = QMimeData()
        if paths is not None:
            m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        if text is not None:
            m.setText(text)
        return m
    def drop(widget, m):
        pos = QPointF(widget.width() / 2, widget.height() / 2)
        ev = QDragEnterEvent(pos.toPoint(), Qt.DropAction.CopyAction, m, Qt.MouseButton.NoButton,
                             Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, ev)
        entered = ev.isAccepted()
        ev = QDropEvent(pos, Qt.DropAction.CopyAction, m, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, ev)
        return entered and ev.isAccepted()
    def urls():
        return [t.current_url().rsplit("/", 1)[-1] for t in w.tab_list()]
    pause(0.5)

    # 파일 단추: 홈 단추와 주소창 사이, 동작은 '파일 열기'(Ctrl+O) 와 같다
    nb = w.navbar
    lay = nb.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]
    res["button_between"] = order.index(nb.home) + 1 == order.index(nb.open) and \
        order.index(nb.open) + 1 == order.index(nb.omnibox)
    res["button_action"] = nb.open.defaultAction() is w.act_open
    res["button_icon"] = not nb.open.icon().isNull()

    # dropped_paths: 로컬 파일만, 폴더·웹 주소·글자는 뺀다
    m = QMimeData(); m.setUrls([QUrl.fromLocalFile(str(WORK / "a.htex")), QUrl.fromLocalFile(str(WORK)),
                                QUrl("https://example.org/x.htex")])
    res["paths"] = [Path(p).name for p in chrome.dropped_paths(m)]
    res["no_paths_text"] = chrome.dropped_paths(mime(text="hello")) == []

    # 주소창에 놓기: 지금(빈) 탭에 연다
    res["addr_drop"] = drop(w.omnibox.edit, mime([WORK / "a.htex"]))
    res["addr_tabs"] = wait_until(lambda: urls() == ["a.htex"]) and urls()

    # 창에 여러 개 놓기: 첫 파일은 지금 탭, 나머지는 새 탭
    res["win_drop"] = drop(w, mime([WORK / "b.md", WORK / "c.htex"]))
    res["win_tabs"] = wait_until(lambda: urls() == ["b.md", "c.htex"]) and urls()

    # 페이지(웹 엔진 안쪽 위젯)에 놓기: 웹 엔진이 아니라 창이 연다
    w.select_tab(0)
    proxy = w.current_tab().view.focusProxy()
    res["page_drop"] = drop(proxy, mime([WORK / "a.htex"]))
    res["page_tabs"] = wait_until(lambda: urls() == ["a.htex", "c.htex"]) and urls()

    # 글자 끌어다 놓기는 가로채지 않는다 (페이지·주소창 몫)
    text_mime = mime(text="hello")        # 이벤트보다 오래 살아 있어야 한다
    ev = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, text_mime, Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier)
    res["text_not_filtered"] = w.current_tab()._drop_filter.eventFilter(proxy, ev) is False

    OUT.write_text(json.dumps(res, ensure_ascii=False))
    w.close(); app.quit()
''')


def test_file_open_button_and_drop(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.htex").write_text("\\title{Alpha}\n\nHello.\n", encoding="utf-8")
    (work / "b.md").write_text("# Beta\n", encoding="utf-8")
    (work / "c.htex").write_text("\\title{Gamma}\n\nHi.\n", encoding="utf-8")
    script = tmp_path / "probe.py"
    script.write_text(SCRIPT, encoding="utf-8")
    out = tmp_path / "out.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox", HOME=str(tmp_path))
    proc = subprocess.run([sys.executable, str(script), str(ROOT), str(out), str(work)],
                          env=env, capture_output=True, text=True, timeout=180)
    assert out.exists(), proc.stderr[-3000:]
    r = json.loads(out.read_text(encoding="utf-8"))

    assert r["button_between"] and r["button_action"] and r["button_icon"]
    assert r["paths"] == ["a.htex"]
    assert r["no_paths_text"]
    assert r["addr_drop"] and r["addr_tabs"] == ["a.htex"]
    assert r["win_drop"] and r["win_tabs"] == ["b.md", "c.htex"]
    assert r["page_drop"] and r["page_tabs"] == ["a.htex", "c.htex"]
    assert r["text_not_filtered"]
