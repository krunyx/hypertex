"""R: 수식 원문 복사 (v0.8.2) — 우클릭 "수식을 LaTeX로 복사", 골라서 복사하면 수식이 $…$ 로.
같은 문서 참조 링크의 마우스 올림 미리보기(이미 있던 G 기능)가 뷰어에서 뜨는지도 본다.

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

DOC = r"""\title{수식 복사}

앞 글자 $a^2+b^2=c^2$ 뒤 글자.

\begin{equation}\int_0^1 x\,dx = \frac12\label{eq:int}\end{equation}

\begin{align}x&=1\\y&=2\end{align}

식 \eqref{eq:int} 를 보라.
"""

SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer, QPoint
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK, bookmarks=BookmarkStore(path=None))
    w.resize(1000, 760); w.show()
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

    w.navigate(str(WORK / "doc.htex"))
    wait_until(lambda: w.current_tab().title() == "수식 복사")
    wait_until(lambda: js("!!(window.HTEX && HTEX.selectionTeX)"))

    SELECT = """(function(startSel, startOff, endSel, endOff){
      function textNode(el, last){ var w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); var n, keep=null;
        while ((n = w.nextNode())) { if (n.textContent.trim()) { keep = n; if (!last) break; } } return keep; }
      var s = document.querySelector(startSel), e = document.querySelector(endSel);
      var sn = textNode(s, false), en = textNode(e, true);
      var r = document.createRange();
      r.setStart(sn, Math.min(startOff, sn.length));
      r.setEnd(en, Math.min(endOff, en.length));
      var sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
      try { var t = HTEX.selectionTeX(); return t === null ? "<null>" : t; } catch (e) { return "ERR " + e; }
    })"""
    # 글자 + 인라인 수식 + 글자
    res["inline"] = js(SELECT + "('#n1', 0, '#n1', 9999)")
    # 수식 하나 안에서 일부만 → 그 수식 전체
    res["inside"] = js(SELECT + "('#n1 math mi', 0, '#n1 math mn', 1)")
    # 가운데 식과 align 을 걸쳐서
    res["display"] = js(SELECT + "('#n3', 0, '#n6 td.htex-l', 9999)")
    res["no_math"] = js("""(function(){ var p=document.getElementById('n7');
       var t=document.createTreeWalker(p, NodeFilter.SHOW_TEXT).nextNode();
       var r=document.createRange(); r.setStart(t,0); r.setEnd(t,1);
       getSelection().removeAllRanges(); getSelection().addRange(r); var t = HTEX.selectionTeX(); return t === null ? "<null>" : t; })()""")

    # 실제 복사 (Ctrl+C 와 같은 copy 이벤트) → 클립보드 일반 글자
    js(SELECT + "('#n1', 0, '#n1', 9999)")
    QGuiApplication.clipboard().clear()
    w.current_tab().page.triggerAction(w.current_tab().page.WebAction.Copy)
    wait_until(lambda: bool(QGuiApplication.clipboard().text()), 5)
    res["clipboard_copy"] = QGuiApplication.clipboard().text()

    # 우클릭 메뉴: 가운데 식 위에서
    js("getSelection().removeAllRanges()")
    js("document.getElementById('n3').scrollIntoView({block:'center'})"); pause(0.3)
    rect = js("""(function(){ var r=document.querySelector('#n3 math').getBoundingClientRect();
       return Math.round(r.left + r.width/2) + ',' + Math.round(r.top + r.height/2); })()""")
    rect = [int(v) for v in rect.split(',')]
    res["hit"] = js("(function(){var e=document.elementFromPoint(%d,%d); var r=e&&e.closest('tr'); return r?r.id:(e?e.tagName:'');})()" % (rect[0], rect[1]))
    tab = w.current_tab()
    tab.last_context_menu = None
    # 실제 우클릭처럼: 페이지에 contextmenu 이벤트, 그 뒤 엔진이 메뉴 요청 → Tab._context_menu
    from PySide6.QtGui import QContextMenuEvent
    target = tab.view.focusProxy() or tab.view
    pt = QPoint(*rect)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseMove(target, pt); pause(0.1)
    QTest.mousePress(target, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, pt)
    QTest.mouseRelease(target, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, pt)
    if not wait_until(lambda: tab.last_context_menu is not None, 4):
        QApplication.sendEvent(target, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pt, target.mapToGlobal(pt)))
        wait_until(lambda: tab.last_context_menu is not None, 4)
    res["real_request"] = tab.view.lastContextMenuRequest() is not None
    res["rect"] = rect
    acts = [a.text() for a in tab.last_context_menu.actions() if a.text()]
    res["menu_first"] = acts[0] if acts else None
    QGuiApplication.clipboard().clear()
    tab.last_context_menu.actions()[0].trigger()
    res["clipboard_menu"] = QGuiApplication.clipboard().text()
    tab.last_context_menu.close()
    # 글자 위에서는 수식 항목이 없다
    js("""document.getElementById('n1').dispatchEvent(new MouseEvent('contextmenu', {bubbles:true}))""")
    tab.last_context_menu = None
    tab._context_menu(QPoint(5, 5))          # 우클릭 정보 없이 불러도 멈추지 않는다
    wait_until(lambda: tab.last_context_menu is not None)
    res["menu_plain"] = [a.text() for a in tab.last_context_menu.actions()][:1]
    tab.last_context_menu.close()

    # 참조 링크에 마우스를 올리면 미리보기 (이미 있던 기능이 뷰어에서 동작하는지)
    js("""document.querySelector('a.htex-ref').dispatchEvent(new MouseEvent('mouseover', {bubbles:true}))""")
    wait_until(lambda: js("(function(){var p=document.getElementById('htex-preview'); return !!(p && !p.hidden);})()"), 5)
    res["preview"] = js("""(function(){var p=document.getElementById('htex-preview');
       return p && !p.hidden ? p.textContent.replace(/\\s+/g,' ').trim().slice(0, 40) : null;})()""")

    OUT.write_text(json.dumps(res, ensure_ascii=False))
    w.close(); app.quit()
''')


def test_copy_latex(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "doc.htex").write_text(DOC, encoding="utf-8")
    script = tmp_path / "probe.py"
    script.write_text(SCRIPT, encoding="utf-8")
    out = tmp_path / "out.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox",
               HOME=str(tmp_path), HTEX_LANG="ko")
    proc = subprocess.run([sys.executable, str(script), str(ROOT), str(out), str(work)],
                          env=env, capture_output=True, text=True, timeout=180)
    assert out.exists(), proc.stderr[-3000:]
    r = json.loads(out.read_text(encoding="utf-8"))

    assert r["inline"] == "앞 글자 $a^2+b^2=c^2$ 뒤 글자."
    assert r["inside"] == "$a^2+b^2=c^2$"
    assert r["hit"] == "n3"
    assert "$$\\int_0^1 x\\,dx = \\frac12$$" in r["display"]
    assert "$$\\begin{aligned}x&=1\\end{aligned}$$" in r["display"]
    assert "$$\\begin{aligned}y&=2\\end{aligned}$$" in r["display"]
    assert r["no_math"] == "<null>"
    assert r["clipboard_copy"] == "앞 글자 $a^2+b^2=c^2$ 뒤 글자."
    assert r["menu_first"] == "수식을 LaTeX로 복사"
    assert r["clipboard_menu"] == "\\int_0^1 x\\,dx = \\frac12"
    assert r["menu_plain"] != ["수식을 LaTeX로 복사"]
    assert r["preview"] and "1" in r["preview"]
