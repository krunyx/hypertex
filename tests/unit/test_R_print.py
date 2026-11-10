"""R: 인쇄·PDF로 저장 (v0.8.1). 어두운 테마에서도 흰 종이에 인쇄되는지 PDF 를 그려 확인한다.

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

from htex.html.style import CSS

ROOT = Path(__file__).resolve().parents[2]


def test_print_css_overrides_dark_theme():
    block = CSS[CSS.index("@media print{"):]
    assert ':root[data-theme]' in block and "--bg:#fff" in block and "--fg:#000" in block


SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer, QSize
    from PySide6.QtWidgets import QApplication
    from PySide6.QtPrintSupport import QPrinter
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=WORK, bookmarks=BookmarkStore(path=None))
    w.resize(1000, 700); w.show()
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    def wait_until(cond, t=15):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(50)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())

    def corner_is_white(path):
        try:
            from PySide6.QtPdf import QPdfDocument
        except ImportError:
            return None
        doc = QPdfDocument()
        doc.load(str(path))
        img = doc.render(0, QSize(300, 400))
        doc.close()
        # 여백(투명 = 종이색)과 본문 첫 줄 위(제목 오른쪽 빈 곳)가 어둡지 않아야 한다
        def light(x, y):
            c = img.pixelColor(x, y)
            return c.alpha() == 0 or (c.red() > 240 and c.green() > 240 and c.blue() > 240)
        return light(10, 10) and light(290, 390) and light(150, 60)

    # 시작 페이지는 인쇄하지 않는다
    pause(0.3)
    res["start_refused"] = w.save_pdf(str(WORK / "start.pdf")) is False and not (WORK / "start.pdf").exists()

    w.navigate(str(WORK / "doc.htex"))
    wait_until(lambda: w.current_tab().title() == "인쇄 시험")
    w.set_theme("dark"); pause(0.5)
    res["menu"] = [a.text() for a in w.app_menu.actions() if a.text() in ("인쇄…", "PDF로 저장…")]
    res["shortcut"] = [k.toString() for k in w.act_print.shortcuts()]

    pdf = WORK / "out.pdf"
    w.last_pdf = None
    res["started"] = w.save_pdf(str(pdf))
    wait_until(lambda: w.last_pdf is not None)
    res["pdf_ok"] = bool(w.last_pdf and w.last_pdf[1])
    res["pdf_header"] = pdf.read_bytes()[:5].decode("latin-1") if pdf.exists() else ""
    res["pdf_white"] = corner_is_white(pdf)
    res["pdf_message"] = w.status.currentMessage()

    # 대화상자 없이 PDF 프린터로 (Ctrl+P 의 인쇄 경로)
    printed = WORK / "printed.pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(printed))
    w.last_print_ok = None
    res["print_started"] = w.print_page(printer)
    wait_until(lambda: w.last_print_ok is not None, 30)
    res["print_ok"] = w.last_print_ok
    res["printed_header"] = printed.read_bytes()[:5].decode("latin-1") if printed.exists() else ""

    OUT.write_text(json.dumps(res, ensure_ascii=False))
    w.close(); app.quit()
''')


def test_save_pdf_and_print(tmp_path):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    pytest.importorskip("PySide6.QtPrintSupport")
    work = tmp_path / "work"
    work.mkdir()
    (work / "doc.htex").write_text("\\title{인쇄 시험}\n\n" + "본문 문단. " * 200 + "\n\n$$E = mc^2$$\n",
                                   encoding="utf-8")
    script = tmp_path / "probe.py"
    script.write_text(SCRIPT, encoding="utf-8")
    out = tmp_path / "out.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox",
               HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / "config"), HTEX_LANG="ko")
    proc = subprocess.run([sys.executable, str(script), str(ROOT), str(out), str(work)],
                          env=env, capture_output=True, text=True, timeout=180)
    assert out.exists(), proc.stderr[-3000:]
    r = json.loads(out.read_text(encoding="utf-8"))

    assert r["start_refused"]
    assert r["menu"] == ["인쇄…", "PDF로 저장…"]
    assert "Ctrl+P" in r["shortcut"]
    assert r["started"] and r["pdf_ok"] and r["pdf_header"] == "%PDF-"
    assert r["pdf_white"] in (True, None)             # 어두운 테마여도 흰 종이 (QtPdf 가 없으면 건너뜀)
    assert r["pdf_message"] == "PDF로 저장했습니다: out.pdf"
    assert r["print_started"] and r["print_ok"] is True and r["printed_header"] == "%PDF-"
