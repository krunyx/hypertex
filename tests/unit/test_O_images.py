"""O: PDF 그림과 확장자 없는 그림 (\\includegraphics{fig.pdf}, \\includegraphics{fig}).
규칙·정적 빌드는 Qt 없이, PDF 그리기와 창은 PySide6 가 있을 때만."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.parse
from pathlib import Path

import pytest

from htex import images
from htex.html import render
from htex.parser import parse_text
from htex.viewer.core import Fetcher, TreeCache, ViewerCore, viewer_image_url

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.unit.test_F_core import FakeOpener  # noqa: E402

FIG_PDF = ROOT / "packaging" / "smoke" / "figure.pdf"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
                    "0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082")

TEX = r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
\includegraphics{a.svg}
\includegraphics{fig.pdf}
\includegraphics{dot}
\includegraphics[width=0.5\textwidth]{fig}
\includegraphics{missing}
\includegraphics{old.eps}
\end{document}
"""


def _folder(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "a.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>',
                                    encoding="utf-8")
    shutil.copyfile(FIG_PDF, tmp_path / "fig.pdf")
    (tmp_path / "dot.png").write_bytes(PNG)
    (tmp_path / "t.tex").write_text(TEX, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------- 규칙
def test_rules():
    assert images.needs_help("fig.pdf") and images.needs_help("fig") and images.needs_help("d/fig?x=1")
    assert not images.needs_help("a.png") and not images.needs_help("data:image/png;base64,AA")
    m = images.mark("fig.pdf#p")
    assert m == "fig.pdf?htex-image=1#p" and images.has_mark(m)
    assert images.mark("f?a=1") == "f?a=1&htex-image=1"
    assert images.strip_mark("htexapp://doc-x/f.pdf?htex-image=1") == "htexapp://doc-x/f.pdf"
    assert images.is_pdf(b"%PDF-1.7\n...") and not images.is_pdf(PNG)


def test_local_search_order(tmp_path):
    for n in ("f.pdf", "f.png"):
        (tmp_path / n).write_bytes(b"x")
    assert images.find_local(tmp_path / "f").name == "f.png"            # 웹 형식이 먼저
    (tmp_path / "f.svg").write_bytes(b"x")
    assert images.find_local(tmp_path / "f").name == "f.svg"
    assert images.find_local(tmp_path / "g") is None
    assert images.web_substitute(tmp_path / "f.pdf").name == "f.svg"    # 정적 빌드: PDF 대신


def test_viewer_marks_only_what_needs_help():
    assert viewer_image_url("a.png") == "a.png"
    assert viewer_image_url("fig.pdf") == "fig.pdf?htex-image=1"
    assert viewer_image_url("https://ex.org/f.pdf") == "htex://ex.org/f.pdf?htex-image=1"   # 뷰어를 거친다


def test_render_image_url_hook():
    tree = parse_text(r"\documentclass{hypertex}\begin{document}\includegraphics{x.pdf}\end{document}",
                      url="t.htex")
    assert 'src="x.pdf"' in render(tree)
    assert 'src="X"' in render(tree, image_url=lambda s: "X")


def test_eps_is_diagnosed():
    tree = parse_text(TEX, url="t.tex")
    msgs = [d["message"] for d in tree.get("diagnostics", [])]
    assert any("EPS" in m and "old.eps" in m for m in msgs)


# ---------------------------------------------------------------- 뷰어 core
def _get(core: ViewerCore, doc: str, src: str):
    base = doc.rsplit("/", 1)[0] + "/"
    origin = "htexapp://" + urllib.parse.urlsplit(doc).netloc
    return core.respond(base + src.replace("&amp;", "&"), origin)


def test_viewer_serves_local_figures(tmp_path):
    pytest.importorskip("PySide6.QtPdf")
    d = _folder(tmp_path)
    core = ViewerCore(cache=TreeCache())
    doc = core.local_url(d / "t.tex")
    page = core.respond(doc).text
    srcs = re.findall(r'<img[^>]*src="([^"]+)"', page)
    assert srcs == ["a.svg", "fig.pdf?htex-image=1", "dot?htex-image=1", "fig?htex-image=1",
                    "missing?htex-image=1", "old.eps"]
    got = {s: _get(core, doc, s) for s in srcs}
    pdf = got["fig.pdf?htex-image=1"]
    assert pdf.status == 200 and pdf.mime == "image/svg+xml"
    svg = pdf.body.decode()
    # 240×120pt 쪽 → 320×160 CSS px, 안에는 2배 해상도 PNG
    assert 'width="320.00"' in svg and 'height="160.00"' in svg and "data:image/png;base64," in svg
    assert got["fig?htex-image=1"].body == pdf.body                    # 확장자 없음 → fig.pdf
    assert got["dot?htex-image=1"].mime == "image/png"                 # 확장자 없음 → dot.png
    assert got["missing?htex-image=1"].status == 404
    # 그림 표시가 없으면 .pdf 는 예전처럼 문서로 다룬다 (링크로 연 경우)
    assert _get(core, doc, "fig.pdf").mime == "text/html"


def test_viewer_rejects_escape_and_bad_pdf(tmp_path):
    pytest.importorskip("PySide6.QtPdf")
    d = _folder(tmp_path / "doc")
    (tmp_path / "secret.png").write_bytes(PNG)
    (d / "bad.pdf").write_bytes(b"%PDF-1.4 not really")
    core = ViewerCore(cache=TreeCache())
    doc = core.local_url(d / "t.tex")
    assert _get(core, doc, "../secret?htex-image=1").status in (403, 404)
    assert _get(core, doc, "bad.pdf?htex-image=1").status == 415


def test_viewer_remote_pdf_figure():
    pytest.importorskip("PySide6.QtPdf")
    op = FakeOpener({"https://ex.org/f.pdf": (FIG_PDF.read_bytes(), "application/pdf"),
                     "https://ex.org/g": (FIG_PDF.read_bytes(), "application/pdf")})
    core = ViewerCore(fetcher=Fetcher(op), cache=TreeCache())
    for u in ("htex://ex.org/f.pdf?htex-image=1", "htex://ex.org/g?htex-image=1"):
        r = core.respond(u, "htex://ex.org")
        assert r.status == 200 and r.mime == "image/svg+xml"


# ---------------------------------------------------------------- 정적 빌드
def test_static_build_uses_web_substitutes(tmp_path):
    from htex.web.build import build as build_site
    d = _folder(tmp_path / "src")
    (d / "fig.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>',
                               encoding="utf-8")
    rep = build_site(d, tmp_path / "out")
    html = (tmp_path / "out" / "t.html").read_text(encoding="utf-8")
    srcs = re.findall(r'<img[^>]*src="([^"]+)"', html)
    assert srcs == ["a.svg", "fig.svg", "dot.png", "fig.svg", "missing", "old.eps"]
    assert any("missing" in w for w in rep.warnings)


# ---------------------------------------------------------------- 창
SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2]); DOC = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=DOC.parent, bookmarks=BookmarkStore())
    w.resize(1000, 760); w.show()
    def wait_until(cond, t=10):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(50)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())
    def js(code, t=4):
        tab = w.current_tab(); loop = QEventLoop(); box = {}
        tab.page.runJavaScript(code, 0, lambda v: (box.__setitem__("v", v), loop.quit()))
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); return box.get("v")
    w.navigate(str(DOC)); wait_until(lambda: w.current_tab().title() == "PDF figure smoke test")
    code = "JSON.stringify(Array.from(document.querySelectorAll('img.htex-image')).map(i => [i.complete, i.naturalWidth, i.getBoundingClientRect().width]))"
    wait_until(lambda: all(c and n > 0 for c, n, _ in json.loads(js(code, 1) or "[[false,0,0]]")), 10)
    OUT.write_text(js(code) or "[]", encoding="utf-8")
    w.handler.shutdown()
''')


def test_window_shows_pdf_figures(tmp_path):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    pytest.importorskip("PySide6.QtPdf")
    out = tmp_path / "out.json"
    script = tmp_path / "script.py"
    script.write_text(SCRIPT, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu",
               XDG_CONFIG_HOME=str(tmp_path / "config"), XDG_CACHE_HOME=str(tmp_path / "cache"),
               XDG_DATA_HOME=str(tmp_path / "data"), HOME=str(tmp_path))
    p = subprocess.run([sys.executable, str(script), str(ROOT), str(out),
                        str(ROOT / "packaging" / "smoke" / "pdf-figure.tex")],
                       env=env, capture_output=True, text=True, timeout=180)
    if not out.exists():
        pytest.fail("창 스크립트 실패:\n" + p.stdout[-3000:] + p.stderr[-3000:])
    imgs = json.loads(out.read_text(encoding="utf-8"))
    assert len(imgs) == 2
    (c1, n1, w1), (c2, n2, w2) = imgs
    assert c1 and c2 and n1 == 320 and n2 == 320       # SVG 의 고유 크기 (240pt)
    assert 0 < w1 < 320 + 1                             # width=0.5\textwidth 가 먹는다
