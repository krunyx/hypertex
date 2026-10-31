"""M: 뷰어에서 Markdown·로컬 HTML 열기와 링크 따라가기.
core 부분은 Qt 없이, 창 부분은 화면 없는 하위 프로세스로 (PySide6 가 없으면 창 부분만 건너뛴다)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from htex.viewer.core import Fetcher, TreeCache, ViewerCore, classify_input, is_doc_path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.unit.test_F_core import FakeOpener  # noqa: E402


# ---------------------------------------------------------------- core (Qt 없음)
def test_md_is_a_document_type():
    assert is_doc_path("/notes/a.md") and is_doc_path("/x/README.markdown")
    assert classify_input("https://ex.org/n.md").url == "htex://ex.org/n.md"


def test_local_markdown_and_html_are_served(tmp_path):
    (tmp_path / "a.md").write_text("# A\n\n[b](b.md) $x$\n", encoding="utf-8")
    (tmp_path / "p.html").write_bytes("<meta charset=euc-kr><title>t</title>".encode())
    (tmp_path / "s.css").write_text("body{}", encoding="utf-8")
    core = ViewerCore(cache=TreeCache())
    url = core.local_url(tmp_path / "a.md")
    r = core.respond(url)
    assert r.status == 200 and r.record.tree["source"]["mode"] == "markdown" and "<math" in r.text
    h = core.respond(core.local_url(tmp_path / "p.html"))
    assert h.status == 200 and h.mime == "text/html" and not h.utf8          # 문서가 인코딩을 정한다
    csp = h.headers["Content-Security-Policy"]
    assert csp.startswith("sandbox allow-scripts") and "allow-same-origin" not in csp
    assert "connect-src 'none'" in csp
    c = core.respond(core.local_url(tmp_path / "s.css"))
    assert c.status == 200 and c.mime == "text/css"
    # 열어 둔 폴더 밖, 다른 출처에서는 안 된다
    bad = core.respond(core.local_url(tmp_path / "s.css"), "https://evil.example")
    assert bad.mime == "text/html" and "body{}" not in bad.text           # 오류 페이지, 파일 내용 아님


def test_remote_md_text_is_parsed_and_html_page_goes_back_to_web():
    op = FakeOpener({"https://ex.org/n.md": ("# 원격\n\n본문", "text/markdown"),
                     "https://ex.org/blob.md": ("<!doctype html><title>GitHub</title>", "text/html")})
    core = ViewerCore(fetcher=Fetcher(op), cache=TreeCache())
    r = core.respond("htex://ex.org/n.md")
    assert r.status == 200 and r.record.tree["source"]["mode"] == "markdown"
    w = core.respond("htex://ex.org/blob.md")
    assert w.redirect == "https://ex.org/blob.md"            # 웹 페이지면 웹으로 (리디렉트는 다시 가로채지 않는다)


# ---------------------------------------------------------------- 창
pytest.importorskip("PySide6.QtWebEngineWidgets")

SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK, bookmarks=BookmarkStore())
    w.resize(1000, 760); w.show()
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    def wait_until(cond, t=8):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(30)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())
    def js(code, t=4):
        tab = w.current_tab(); loop = QEventLoop(); box = {}
        tab.page.runJavaScript(code, 0, lambda v: (box.__setitem__("v", v), loop.quit()))
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); return box.get("v")
    def title():
        return w.current_tab().title()

    # Markdown 열기
    w.navigate(str(WORK / "a.md")); wait_until(lambda: title() == "A 문서")
    wait_until(lambda: bool(w.diag_label.text()))
    res["md"] = {"title": title(), "math": js("document.querySelectorAll('math').length"),
                 "diag": w.diag_label.text(), "info": w.omnibox.info.text(),
                 "watch": [p.name for p in w.current_tab().watched_files()]}
    # 문서 안 앵커
    js("document.querySelector('a[href^=\"#\"]').click()"); pause(0.3)
    res["anchor"] = w.current_tab().current_url().endswith("#둘째-절") or \
        w.current_tab().current_url().endswith("#%EB%91%98%EC%A7%B8-%EC%A0%88")
    # 다른 Markdown 으로
    js("document.querySelector('a[href=\"b.md\"]').click()"); wait_until(lambda: title() == "B 문서")
    res["md_link"] = {"title": title(), "address": w.address.text()}
    w.back(); wait_until(lambda: title() == "A 문서")
    res["back"] = title()
    # 로컬 HTML
    js("document.querySelector('a[href=\"page.html\"]').click()")
    wait_until(lambda: title() == "스크립트 실행됨")
    pause(0.5)
    res["html"] = {"title": title(), "info": w.omnibox.info.text(),
                   "css": js("getComputedStyle(document.querySelector('h1')).color"),
                   "fetch": js("document.getElementById('fetch').textContent"),
                   "img": js("document.querySelector('img').naturalWidth"),
                   "watch": [p.name for p in w.current_tab().watched_files()]}
    # HTML → Markdown 링크
    js("document.querySelector('a[href=\"b.md\"]').click()"); wait_until(lambda: title() == "B 문서")
    res["html_to_md"] = title()
    # 자동 새로고침 (Markdown 저장)
    w.navigate(str(WORK / "a.md")); wait_until(lambda: title() == "A 문서")
    p = WORK / "a.md"; p.write_text(p.read_text(encoding="utf-8").replace("첫 판", "둘째 판"), encoding="utf-8")
    res["reload"] = wait_until(lambda: (js("document.body.textContent.indexOf('둘째 판')>=0", 1) or False), 8)
    # 원본 보기
    w.view_source(); wait_until(lambda: title().startswith("원문"))
    res["source"] = js("document.body.textContent.indexOf('# A 문서')>=0")

    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    w.handler.shutdown()
''')

A_MD = """# A 문서

첫 판. 수식 $E = mc^2$ 와

$$
\\int_0^1 x\\,dx = \\tfrac12
$$

[둘째 절로](#둘째-절) · [B 로](b.md) · [HTML 로](page.html)

## 둘째 절

![작은 그림](dot.png)
"""
B_MD = "# B 문서\n\n[A 로 돌아가기](a.md#둘째-절)\n"
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>처음 제목</title>
<link rel="stylesheet" href="style.css"></head><body><h1>로컬 HTML</h1>
<p id="fetch">대기</p><img src="dot.png"><p><a href="b.md">B 문서</a></p>
<script>
document.title = "스크립트 실행됨";
fetch("a.md").then(function(){ document.getElementById("fetch").textContent = "읽힘"; })
  .catch(function(){ document.getElementById("fetch").textContent = "막힘"; });
</script></body></html>"""
# 1×1 빨간 PNG
DOT = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
                    "0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    work = tmp_path_factory.mktemp("m-viewer")
    (work / "a.md").write_text(A_MD, encoding="utf-8")
    (work / "b.md").write_text(B_MD, encoding="utf-8")
    (work / "page.html").write_text(PAGE, encoding="utf-8")
    (work / "style.css").write_text("h1 { color: rgb(200, 0, 0); }", encoding="utf-8")
    (work / "dot.png").write_bytes(DOT)
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


def test_open_markdown(run):
    m = run["md"]
    assert m["title"] == "A 문서" and m["math"] == 2
    assert m["diag"].startswith("Markdown · 진단: 오류 0") and m["info"] == "Markdown"
    assert m["watch"] == ["a.md"]


def test_markdown_links_anchor_and_back(run):
    assert run["anchor"]
    assert run["md_link"]["title"] == "B 문서" and run["md_link"]["address"].endswith("b.md")
    assert run["back"] == "A 문서"


def test_local_html_runs_sandboxed(run):
    h = run["html"]
    assert h["title"] == "스크립트 실행됨" and h["info"] == "로컬 HTML"
    assert h["css"] == "rgb(200, 0, 0)" and h["img"] == 1
    assert h["fetch"] == "막힘"                      # 다른 파일을 스크립트로 읽을 수 없다
    assert h["watch"] == ["page.html"]


def test_html_links_back_to_markdown(run):
    assert run["html_to_md"] == "B 문서"


def test_markdown_auto_reload_and_source(run):
    assert run["reload"] and run["source"]
