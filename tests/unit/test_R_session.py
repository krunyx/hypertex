"""R: 세션 (v0.8.1) — 다시 켤 때 이전 탭 다시 열기, 닫은 탭 다시 열기(Ctrl+Shift+T), "시작할 때" 설정."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from htex.viewer import session as sl

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 저장 형식 (Qt 없음)
def test_session_round_trip_and_bad_files(tmp_path):
    p = tmp_path / "s" / "session.json"
    s = sl.Session([sl.SessionTab("htex://krunyx.com/a.htex", "A"), sl.SessionTab("/x/b.md", "B")], 1)
    assert sl.save(p, s)
    back = sl.load(p)
    assert [t.url for t in back.tabs] == ["htex://krunyx.com/a.htex", "/x/b.md"] and back.active == 1
    p.write_text("{ 깨진", encoding="utf-8")
    assert sl.load(p).tabs == [] and p.exists()                   # 깨진 파일은 지우지 않는다
    p.write_text(json.dumps({"tabs": [{"url": "  "}, {"url": 3}, {"url": "a"}], "active": 9}), encoding="utf-8")
    back = sl.load(p)
    assert [t.url for t in back.tabs] == ["a"] and back.active == 0
    assert sl.load(None).tabs == [] and not sl.save(None, s)


def test_trivial_session():
    assert sl.Session().is_trivial("htexapp://start/")
    assert sl.Session([sl.SessionTab("htexapp://start/")]).is_trivial("htexapp://start/")
    assert not sl.Session([sl.SessionTab("htexapp://start/"), sl.SessionTab("/a.htex")]).is_trivial(
        "htexapp://start/")


# ---------------------------------------------------------------- 실제로 껐다 켜기
PHASE = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2]); WORK = Path(sys.argv[3]); STEP = sys.argv[4]
    TARGETS = sys.argv[5:]
    from PySide6.QtCore import QTimer, QEventLoop
    from PySide6.QtWidgets import QApplication
    from htex.viewer import app as appmod
    res = {}

    def pause(s):
        loop = QEventLoop(); QTimer.singleShot(int(s * 1000), loop.quit); loop.exec()
    def win():
        return next(w for w in QApplication.instance().topLevelWidgets() if isinstance(w, appmod.ViewerWindow))
    def names(w):
        return [Path(t.current_url()).name if not t.is_start() else "START" for t in w.tab_list()]

    def act():
        w = win(); pause(1.5)
        res["tabs"] = names(w)
        res["active"] = w.tabs.currentIndex()
        res["startup_checked"] = [k for k, a in w.startup_actions.items() if a.isChecked()]
        if STEP == "first":
            w.select_tab(1)
            w.close_tab(2)                              # c.htex 닫기
            res["after_close"] = names(w)
            t = w.reopen_closed_tab(); pause(1)          # 원래 자리(2)에 다시
            res["reopened"] = names(w)
            res["reopened_index"] = w.tabs.indexOf(t)
            w.close_tab(2)                              # 다시 닫고 끝낸다: a, b 가 남고 b 가 지금 탭
            w.select_tab(2)
        if STEP == "newtab":
            appmod.set_startup_mode("newtab")
        if STEP == "third":
            appmod.set_startup_mode("continue")
        OUT.write_text(json.dumps(res, ensure_ascii=False))
        w._quit()

    appmod.register_schemes()
    qapp = appmod.HtexApplication([sys.argv[0]])         # 타이머가 돌도록 앱을 먼저 만든다 (run 이 이것을 쓴다)
    QTimer.singleShot(300, act)
    sys.exit(appmod.run(TARGETS, single_instance=False))
''')


def _env(d: Path) -> dict:
    return dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox",
                XDG_CACHE_HOME=str(d / "cache"), XDG_CONFIG_HOME=str(d / "config"),
                XDG_DATA_HOME=str(d / "data"), HOME=str(d / "home"), HTEX_LANG="ko",
                HTEX_DATA_DIR=str(d / "data"), HTEX_VIEWER_SESSION="1")


def _phase(d: Path, work: Path, step: str, *targets: str) -> dict:
    out = d / f"{step}.json"
    proc = subprocess.run([sys.executable, str(d / "phase.py"), str(ROOT), str(out), str(work), step, *targets],
                          cwd=str(work), env=_env(d), capture_output=True, text=True, timeout=90)
    assert out.exists(), proc.stderr[-3000:]
    return json.loads(out.read_text(encoding="utf-8"))


def test_restart_restores_tabs(tmp_path):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    d = tmp_path
    (d / "home").mkdir()
    work = d / "work"
    work.mkdir()
    for n in "abc":
        (work / f"{n}.htex").write_text(f"\\title{{{n.upper()}}}\n\n본문 {n}.\n", encoding="utf-8")
    (d / "phase.py").write_text(PHASE, encoding="utf-8")

    # 1) 세 파일을 열고 켠다. 닫은 탭 다시 열기, 그 뒤 c 를 닫고 b 를 보던 채로 끈다.
    r1 = _phase(d, work, "first", "a.htex", "b.htex", "c.htex")
    assert r1["tabs"] == ["a.htex", "b.htex", "c.htex"]
    assert r1["startup_checked"] == ["continue"]                     # 기본은 이전 탭 다시 열기
    assert r1["after_close"] == ["a.htex", "b.htex"]
    assert r1["reopened"] == ["a.htex", "b.htex", "c.htex"] and r1["reopened_index"] == 2
    saved = json.loads((d / "data" / "session.json").read_text(encoding="utf-8"))
    assert [Path(t["url"]).name for t in saved["tabs"]] == ["a.htex", "b.htex"] and saved["active"] == 1

    # 2) 대상 없이 다시 켜면 같은 탭, 같은 지금 탭. 이번에는 "새 탭 페이지 열기"로 바꾸고 끈다.
    r2 = _phase(d, work, "newtab")
    assert r2["tabs"] == ["a.htex", "b.htex"] and r2["active"] == 1

    # 3) 새 탭 페이지 설정: 이전 탭 없이 시작 페이지만. 파일을 주면 그 파일만.
    r3 = _phase(d, work, "third", "c.htex")
    assert r3["tabs"] == ["c.htex"] and r3["startup_checked"] == ["newtab"]

    # 4) 다시 "이전 탭"으로 바꿨으니(3에서) 이전 탭(c) 다음에 새로 준 파일(a)
    r4 = _phase(d, work, "fourth", "a.htex")
    assert r4["tabs"] == ["c.htex", "a.htex"]
