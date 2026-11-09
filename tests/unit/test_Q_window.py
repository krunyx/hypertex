"""Q: 창 안의 원문 편집기 (왼쪽 원문 · 오른쪽 미리보기). 화면 없이 하위 프로세스로. PySide6 가 없으면 건너뛴다."""
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

DOC = r"""\documentclass{hypertex}
\title{편집 시험}
\begin{document}
\section{첫 절}
조화 진동자의 에너지.
식 \undefinedcmd 와 \href{other.htex}{다른 문서}.
\end{document}
"""
OTHER = r"""\documentclass{hypertex}\title{다른}\begin{document}다른 문서\end{document}"""
REMOTE = r"""\documentclass{article}
\begin{document}
원격 본문. \input{sec1}
\includegraphics{fig.png}
\end{document}
"""

SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1]); sys.path.insert(0, str(Path(sys.argv[1]) / "tests" / "unit"))
    ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache, Fetcher
    from test_F_core import FakeOpener
    REMOTE = (WORK / "remote.tex").read_text("utf-8")
    op = FakeOpener({"https://ex.org/d/r.tex": REMOTE, "https://ex.org/d/sec1.tex": "원격 SECTION",
                     "https://ex.org/d/fig.png": (b"\x89PNG\r\n\x1a\n0000", "image/png")})
    w = ViewerWindow(core=ViewerCore(fetcher=Fetcher(op), cache=TreeCache()), cwd=WORK,
                     bookmarks=BookmarkStore())
    w.set_theme("light")
    w.resize(1300, 800); w.show()
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    def wait_until(cond, t=8):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(30)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())
    def js(page, code, t=4):
        loop = QEventLoop(); box = {}
        page.runJavaScript(code, 0, lambda v: (box.__setitem__("v", v), loop.quit()))
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); return box.get("v")

    # ---- 로컬 문서
    tab = w.current_tab()
    w.navigate(str(WORK / "doc.htex"), tab)
    wait_until(lambda: not tab.loading and tab.title() == "편집 시험")
    res["before"] = {"edit_enabled": w.act_edit.isEnabled(), "save_enabled": w.act_save.isEnabled(),
                     "button": w.navbar.edit.defaultAction() is w.act_edit}
    w.act_edit.trigger()
    pane = tab.editor
    wait_until(lambda: pane.ready)
    wait_until(lambda: (js(pane.page, "document.querySelectorAll('.cm-lint-marker').length") or 0) > 0, 5)
    res["open"] = {"lines": js(pane.page, "HtexEditor.lines()"), "mode": pane.mode,
                   "sizes": tab.splitter.sizes(), "checked": w.act_edit.isChecked(),
                   "save_enabled": w.act_save.isEnabled(), "back_enabled": w.act_back.isEnabled(),
                   "lint": js(pane.page, "document.querySelectorAll('.cm-lint-marker').length"),
                   "bg": js(pane.page, "getComputedStyle(document.querySelector('.cm-editor')).backgroundColor")}
    n0 = tab.preview_refreshes
    js(pane.page, "HtexEditor.typeAt(5, 'NEWTEXT ')")
    wait_until(lambda: tab.preview_refreshes > n0 and not tab.loading, 5)
    wait_until(lambda: js(tab.page, "document.body.innerText.indexOf('NEWTEXT') >= 0"), 5)
    res["typed"] = {"dirty": pane.dirty, "tab": w.tabs.tabText(w.tabs.indexOf(tab)),
                    "preview": js(tab.page, "document.body.innerText.indexOf('NEWTEXT') >= 0"),
                    "file_untouched": "NEWTEXT" not in (WORK / "doc.htex").read_text("utf-8")}
    # Ctrl+F: 편집기에 초점이 있으면 편집기 안 찾기
    pane.focus_editor(); pause(0.3)
    w.find(); pause(0.3)
    res["search_panel"] = js(pane.page, "!!document.querySelector('.cm-search')")
    # Ctrl+S 를 편집기에 (웹 엔진이 가로채지 않고 창의 저장이 받는지)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w.activateWindow(); pane.focus_editor(); pause(0.3)
    QTest.keyClick(pane.view.focusProxy() or pane.view, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: not pane.dirty, 5)
    res["saved"] = {"file": "NEWTEXT" in (WORK / "doc.htex").read_text("utf-8"), "dirty": pane.dirty,
                    "tab": w.tabs.tabText(w.tabs.indexOf(tab)),
                    "backups": len(list((Path(sys.argv[4]) / "hypertex" / "backups").glob("*doc.htex")))}
    # 밖에서 파일을 바꾸면 (고친 것이 없을 때) 편집기도 새 내용
    (WORK / "doc.htex").write_text((WORK / "doc.htex").read_text("utf-8").replace("NEWTEXT", "OUTSIDE"), "utf-8")
    wait_until(lambda: "OUTSIDE" in (js(pane.page, "HtexEditor.getText()") or ""), 6)
    res["outside"] = {"editor": "OUTSIDE" in (js(pane.page, "HtexEditor.getText()") or ""), "dirty": pane.dirty}
    # 미리보기의 다른 문서 링크 → 새 탭 (편집하는 문서는 그대로)
    pause(0.5); wait_until(lambda: not tab.loading); pause(0.3)
    count = w.tabs.count()
    js(tab.page, "document.querySelector('a[href*=\"other\"]').click()")
    wait_until(lambda: w.tabs.count() > count, 5)
    res["link"] = {"new_tab": w.tabs.count() == count + 1, "still": tab.current_url().endswith("doc.htex"),
                   "editor": tab.editor is pane}
    w.tabs.setCurrentWidget(tab)
    # 주소창 이동도 새 탭으로
    count = w.tabs.count()
    w.navigate(str(WORK / "other.htex"))
    res["navigate_new_tab"] = w.tabs.count() == count + 1 and tab.editor is pane
    w.tabs.setCurrentWidget(tab)
    w.set_theme("dark"); pause(0.3)
    res["dark_bg"] = js(pane.page, "getComputedStyle(document.querySelector('.cm-editor')).backgroundColor")
    w.act_edit.trigger(); pause(0.3)
    res["closed"] = {"editor": tab.editor is None, "view_visible": tab.view.isVisible(),
                     "drafts": len(w.core.drafts)}

    # ---- 원격 문서: 다른 이름으로 저장하면 \input·그림도 함께
    t2 = w.new_tab("htex://ex.org/d/r.tex")
    wait_until(lambda: not t2.loading and "SECTION" in (js(t2.page, "document.body.innerText") or ""))
    res["remote_input_shown"] = "SECTION" in (js(t2.page, "document.body.innerText") or "")
    w.act_edit.trigger()
    p2 = t2.editor
    wait_until(lambda: p2.ready)
    js(p2.page, "HtexEditor.typeAt(3, '고침 ')")
    wait_until(lambda: p2.dirty, 5)
    asked_before = len(op.requests)
    pause(0.8)
    res["remote_no_refetch"] = not any(u.endswith("/r.tex") for u, *_ in op.requests[asked_before:])
    dest = WORK / "saved" / "copy.tex"
    dest.parent.mkdir()
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(dest), ""))
    w.act_save.trigger()        # 원격 → 다른 이름으로
    wait_until(lambda: t2.current_url().startswith("htexapp://doc-") and not t2.loading, 10)
    res["remote_saved"] = {"files": sorted(p.name for p in dest.parent.iterdir()),
                           "main": "고침" in dest.read_text("utf-8") if dest.exists() else False,
                           "url_local": t2.current_url().startswith("htexapp://doc-"),
                           "editor_local": p2.local is not None and p2.local.path == dest.resolve(),
                           "dirty": p2.dirty, "drafts": list(w.core.drafts)}
    print(json.dumps(res, ensure_ascii=False))
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    w.close()
    w.handler.shutdown()
''')


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("q")
    work = tmp / "work"
    work.mkdir()
    (work / "doc.htex").write_text(DOC, encoding="utf-8")
    (work / "other.htex").write_text(OTHER, encoding="utf-8")
    (work / "remote.tex").write_text(REMOTE, encoding="utf-8")
    out = tmp / "out.json"
    script = tmp / "script.py"
    script.write_text(SCRIPT, encoding="utf-8")
    cache = tmp / "cache"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu",
               XDG_CONFIG_HOME=str(tmp / "config"), XDG_CACHE_HOME=str(cache),
               XDG_DATA_HOME=str(tmp / "data"), HOME=str(tmp))
    p = subprocess.run([sys.executable, str(script), str(ROOT), str(out), str(work), str(cache)], env=env,
                       capture_output=True, text=True, timeout=240)
    if not out.exists():
        pytest.fail("창 스크립트 실패:\n" + p.stdout[-3000:] + p.stderr[-4000:])
    return json.loads(out.read_text(encoding="utf-8"))


def test_open_editor_side_by_side(result):
    assert result["before"] == {"edit_enabled": True, "save_enabled": False, "button": True}
    o = result["open"]
    assert o["lines"] == 8 and o["mode"] == "tex" and o["checked"] and o["save_enabled"]
    assert not o["back_enabled"]
    a, b = o["sizes"]
    assert a > 200 and b > 200 and abs(a - b) < 40          # 나란히 반반
    assert o["lint"] >= 1                                   # \undefinedcmd 진단이 줄에
    assert o["bg"] == "rgb(255, 255, 255)"
    assert result["dark_bg"] != o["bg"]


def test_typing_updates_preview_not_file(result):
    t = result["typed"]
    assert t["dirty"] and t["tab"].startswith("● ") and t["preview"] and t["file_untouched"]
    assert result["search_panel"]


def test_save_writes_file_and_backup(result):
    s = result["saved"]
    assert s["file"] and not s["dirty"] and not s["tab"].startswith("●")
    assert s["backups"] == 1


def test_outside_change_reloads_clean_editor(result):
    assert result["outside"] == {"editor": True, "dirty": False}


def test_preview_links_and_address_open_new_tabs(result):
    assert result["link"] == {"new_tab": True, "still": True, "editor": True}
    assert result["navigate_new_tab"]
    assert result["closed"] == {"editor": True, "view_visible": True, "drafts": 0}


def test_remote_document_saved_locally_with_inputs(result):
    assert result["remote_input_shown"] and result["remote_no_refetch"]
    r = result["remote_saved"]
    assert r["files"] == ["copy.tex", "fig.png", "sec1.tex"]
    assert r["main"] and r["url_local"] and r["editor_local"] and not r["dirty"] and r["drafts"] == []
