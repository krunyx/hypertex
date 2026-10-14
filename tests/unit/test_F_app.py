"""F: 전용 뷰어 창 (PySide6 + QtWebEngine). 화면 없이 띄워 확인한다. PySide6 가 없으면 건너뛴다.

QtWebEngine 은 사용자 정의 스킴을 QApplication 전에 등록해야 하고, 한 프로세스에서 한 번만 띄울 수 있으므로
창 쪽 확인은 하위 프로세스 하나에서 모두 하고 결과(JSON)를 각 테스트가 나눠 확인한다.
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
    import json, os, sys, urllib.error
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2]); JS = Path(sys.argv[3])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer.core import ViewerCore, TreeCache, Fetcher
    from tests.unit.test_F_core import FakeOpener, DOC_A, DOC_B

    op = FakeOpener({"https://ex.org/n/a.htex": DOC_A, "https://ex.org/n/b.htex": DOC_B})
    core = ViewerCore(fetcher=Fetcher(op), cache=TreeCache(), interact_js=JS)
    w = ViewerWindow(core=core)
    w.resize(1000, 760); w.show()
    res = {}

    def wait_load(fn, t=12):
        loop = QEventLoop(); box = {}
        def done(ok): box["ok"] = ok; loop.quit()
        w.view.loadFinished.connect(done); fn()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec()
        w.view.loadFinished.disconnect(done)
        return box.get("ok")

    def js(code, t=5):
        loop = QEventLoop(); box = {}
        w.page.runJavaScript(code, 0, lambda v: (box.__setitem__("v", v), loop.quit()))
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); return box.get("v")

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()

    def wait_until(cond, t=10):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(30)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())

    def state():
        return {"title": w.view.title(), "url": w.current_url(), "address": w.address.text(),
                "diag": w.diag_label.text(), "back": w.act_back.isEnabled(),
                "forward": w.act_forward.isEnabled()}

    res["open"] = dict(ok=wait_load(lambda: w.navigate(str(ROOT / "examples" / "oscillator.htex"))),
                       **state())
    pause(0.3)
    res["open"]["interact"] = js("window.__probe || null")
    res["open"]["inline_blocked"] = js("document.querySelectorAll('script').length")
    res["inner_anchor"] = js("var a=document.querySelector('a.htex-ref[href^=\"#\"]'); a ? a.getAttribute('href') : null")

    res["cross"] = dict(ok=wait_load(lambda: w.navigate(str(ROOT / "tests/docs/12-cross-doc-refs.htex"))),
                        **state())
    pause(0.3)
    res["cross"]["fragment"] = js("window.__frag || null")
    res["link"] = dict(ok=wait_load(lambda: js("document.querySelector('a[data-doc]').click()")), **state())
    res["back"] = dict(ok=wait_load(w.back), **state())
    res["forward"] = dict(ok=wait_load(w.forward), **state())

    res["remote"] = dict(ok=wait_load(lambda: w.navigate("htex://ex.org/n/a.htex")), **state())
    res["remote_link"] = dict(ok=wait_load(lambda: js("document.querySelector('a[data-doc]').click()")),
                              **state())
    res["https_doc"] = dict(ok=wait_load(lambda: w.navigate("https://ex.org/n/a.htex")), **state())
    js("document.querySelector('a.htex-link[href^=\"https:\"]').click()")
    # 가로챈 https 탐색이 먼저 끝나고(취소), 미룬 htex:// 탐색이 뒤따른다: 제목이 바뀔 때까지 기다린다
    res["https_click"] = dict(ok=wait_until(lambda: w.view.title() == "원격 B"), **state())
    res["fetched"] = [r[0] for r in op.requests]

    res["forbidden"] = dict(ok=wait_load(lambda: w.navigate("htexapp://doc-nothere/a.htex")), **state())
    res["console"] = [m for m in w.page.console_log if "Content Security Policy" in m[1]
                      and "inline" not in m[1]]
    w.grab().save(str(OUT.with_suffix(".png")))
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    w.close()
''')

PROBE_JS = r"""
window.__probe = 'interact';
var fe = document.querySelector('meta[name=htex-fragment-endpoint]');
var x = document.querySelector('a[data-doc]');
if (fe && x) fetch(fe.content + '?doc=' + encodeURIComponent(x.dataset.doc) + '&label=' +
                   encodeURIComponent(x.dataset.label))
  .then(function (r) { return r.text(); }).then(function (t) { window.__frag = t; });
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("viewer")
    (d / "run.py").write_text(SCRIPT, encoding="utf-8")
    (d / "interact.js").write_text(PROBE_JS, encoding="utf-8")
    out = d / "result.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox", PYTHONPATH=str(ROOT),
               XDG_CACHE_HOME=str(d / "cache"))
    proc = subprocess.run([sys.executable, str(d / "run.py"), str(ROOT), str(out), str(d / "interact.js")],
                          cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=28)
    if not out.exists():
        pytest.fail("뷰어 하위 프로세스 실패:\n" + proc.stderr[-3000:])
    return json.loads(out.read_text(encoding="utf-8"))


def test_open_example(run):
    r = run["open"]
    assert r["ok"] and r["title"] == "조화 진동자 노트"
    assert r["url"].startswith("htexapp://doc-") and r["address"].endswith("examples/oscillator.htex")
    assert r["diag"].startswith("진단: 오류 0")
    assert r["interact"] == "interact"        # 호스트 스크립트는 실행된다
    assert r["inline_blocked"] == 1           # 페이지의 스크립트는 그 하나뿐
    assert run["inner_anchor"].startswith("#")
    assert run["console"] == []


def test_internal_link_and_fragment(run):
    assert run["cross"]["ok"] and run["cross"]["title"] == "문서 간 참조"
    assert run["cross"]["fragment"].startswith('<div class="htex-fragment"')
    r = run["link"]
    assert r["ok"] and r["title"] == "문서 안 참조"
    assert r["url"].endswith("/11-internal-refs.htex#eq:H") and r["back"]


def test_back_forward(run):
    assert run["back"]["ok"] and run["back"]["title"] == "문서 간 참조" and run["back"]["forward"]
    assert run["forward"]["ok"] and run["forward"]["title"] == "문서 안 참조"


def test_remote_htex_and_https_interception(run):
    assert run["remote"]["ok"] and run["remote"]["title"] == "원격 A"
    assert run["remote"]["url"] == "htex://ex.org/n/a.htex"
    assert run["remote_link"]["title"] == "원격 B"
    assert run["remote_link"]["url"] == "htex://ex.org/n/b.htex#eq:F"
    # https 의 .htex 주소는 htex:// 로 해석된다
    assert run["https_doc"]["url"] == "htex://ex.org/n/a.htex" and run["https_doc"]["title"] == "원격 A"
    # 문서 안의 https://….htex 링크를 누르면 가로채 htex:// 로 (acceptNavigationRequest)
    assert run["https_click"]["url"] == "htex://ex.org/n/b.htex"
    assert run["https_click"]["title"] == "원격 B"
    assert all(u.startswith("https://ex.org/") for u in run["fetched"])


def test_forbidden_local_root(run):
    assert run["forbidden"]["title"] == "열 수 없음"


def test_view_command_without_pyside(monkeypatch, capsys):
    import builtins
    from htex import __main__ as m
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("PySide6"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert m.main(["view", "x.htex"]) == 2
    assert "PySide6" in capsys.readouterr().err
