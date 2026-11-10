"""R: 북마크 가져오기 (v0.8.1) — 창에서. 메뉴, 북마크바의 중첩 폴더 메뉴, ☆ 상자의 폴더 경로.

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

EXPORT = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
  <DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
  <DL><p>
    <DT><A HREF="https://arxiv.org/">arXiv</A>
    <DT><H3>물리</H3>
    <DL><p>
      <DT><A HREF="https://inspirehep.net/">INSPIRE</A>
      <DT><H3>강의</H3>
      <DL><p><DT><A HREF="https://ocw.mit.edu/">MIT OCW</A></DL><p>
    </DL><p>
  </DL><p>
</DL><p>
"""

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
    store = BookmarkStore(path=None)
    store.add("내 것", "https://mine.example/")
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK, bookmarks=store)
    w.resize(1100, 700); w.show()
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    pause(0.3)

    # 북마크 메뉴에 "북마크 가져오기" 하위 메뉴, 그 안에 HTML 파일 항목
    w._fill_bookmarks_menu()
    subs = {a.text(): a.menu() for a in w.bookmarks_menu.actions() if a.menu() is not None}
    imp = subs.get("북마크 가져오기")
    res["import_menu"] = imp is not None and any(a.text() == "HTML 북마크 파일에서…" for a in imp.actions())

    # 가져오기: 북마크바가 이미 쓰이고 있으므로 폴더 하나에
    res["added"] = w.import_bookmarks_html(str(WORK / "bm.html"))
    res["message"] = w.last_import_message
    res["bar"] = [b.text() for b in w.bookmarks_bar.buttons]

    # 북마크바 폴더 단추 → 하위 폴더는 하위 메뉴, 열 때 채운다
    btn = w.bookmarks_bar.buttons[-1]
    top = btn.menu()
    res["top_menu"] = [a.text() for a in top.actions() if a.text()]
    phys = next(a.menu() for a in top.actions() if a.menu() is not None)
    phys.aboutToShow.emit()
    res["phys_menu"] = [a.text() for a in phys.actions() if a.text()]
    lec = next(a.menu() for a in phys.actions() if a.menu() is not None)
    lec.aboutToShow.emit(); lec.aboutToShow.emit()            # 두 번 열어도 한 번만 채운다
    res["lecture_menu"] = [a.text() for a in lec.actions() if a.text()]
    opened = []
    w.bookmarks_bar.open_requested.disconnect()
    w.bookmarks_bar.open_requested.connect(lambda u, nt: opened.append(u))
    next(a for a in lec.actions() if a.text() == "MIT OCW").trigger()
    res["opened"] = opened

    # ☆ 상자의 폴더 선택: 하위 폴더는 경로로
    w.navigate("https://mine.example/"); pause(0.2)
    from htex.viewer.chrome import BookmarkPopup
    choices = [(store.folder_path(f), f) for f in store.folders()]
    pop = BookmarkPopup(w, "x", choices, None, True)
    res["folder_choices"] = [pop.folder.itemText(i) for i in range(pop.folder.count())]
    pop.close()

    OUT.write_text(json.dumps(res, ensure_ascii=False))
    w.close(); app.quit()
''')


def test_import_from_html_in_window(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "bm.html").write_text(EXPORT, encoding="utf-8")
    script = tmp_path / "probe.py"
    script.write_text(SCRIPT, encoding="utf-8")
    out = tmp_path / "out.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox",
               HOME=str(tmp_path), HTEX_LANG="ko")
    proc = subprocess.run([sys.executable, str(script), str(ROOT), str(out), str(work)],
                          env=env, capture_output=True, text=True, timeout=180)
    assert out.exists(), proc.stderr[-3000:]
    r = json.loads(out.read_text(encoding="utf-8"))

    assert r["import_menu"]
    assert r["added"] == 3 and r["message"] == "북마크 3개를 가져왔습니다."
    assert r["bar"] == ["내 것", "bm에서 가져옴"]
    assert r["top_menu"] == ["arXiv", "물리", "모두 새 탭에서 열기 (1)"]
    assert r["phys_menu"] == ["INSPIRE", "강의", "모두 새 탭에서 열기 (1)"]
    assert r["lecture_menu"] == ["MIT OCW", "모두 새 탭에서 열기 (1)"]
    assert r["opened"] == ["https://ocw.mit.edu/"]
    assert r["folder_choices"] == ["북마크바", "bm에서 가져옴", "bm에서 가져옴 › 물리", "bm에서 가져옴 › 물리 › 강의"]
