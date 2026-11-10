"""R: 새 버전 알림 (v0.8.2) — 버전 비교, 릴리스 응답 읽기, 창의 "업데이트" 단추. 인터넷은 쓰지 않는다."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from htex.viewer import updates as up

ROOT = Path(__file__).resolve().parents[2]


def test_versions():
    assert up.parse_version("v0.8.2") == (0, 8, 2) and up.parse_version("1.0") == (1, 0, 0)
    assert up.parse_version("0.9.0-rc1") is None and up.parse_version("") is None
    assert up.is_newer("v0.8.10", "0.8.9") and up.is_newer("v1.0.0", "0.8.2")
    assert not up.is_newer("v0.8.2", "0.8.2") and not up.is_newer("v0.8.1", "0.8.2")
    assert not up.is_newer("nightly", "0.8.2")


def test_due():
    assert up.due(0, 1000)
    assert not up.due(1000, 1000 + up.CHECK_INTERVAL - 1)
    assert up.due(1000, 1000 + up.CHECK_INTERVAL)
    assert up.due(5000, 1000)                        # 시계가 뒤로 갔으면 다시 확인


def _release(tmp_path, tag, **extra) -> str:
    p = tmp_path / f"latest-{tag}.json"
    p.write_text(json.dumps(dict({"tag_name": tag, "html_url": f"https://github.com/krunyx/hypertex/releases/tag/{tag}",
                                  "draft": False, "prerelease": False}, **extra)), encoding="utf-8")
    return p.as_uri()


def test_latest_reads_release(tmp_path):
    info = up.latest("0.8.2", _release(tmp_path, "v0.8.3"))
    assert info.version == "0.8.3" and info.page == up.DOWNLOAD_PAGE and info.notes.endswith("/v0.8.3")
    assert up.latest("0.8.2", _release(tmp_path, "v0.8.2")) is None
    with pytest.raises(up.UpdateError):
        up.latest("0.8.2", _release(tmp_path, "v0.9.0", prerelease=True))
    bad = tmp_path / "bad.json"
    bad.write_text("<html>", encoding="utf-8")
    with pytest.raises(up.UpdateError):
        up.latest("0.8.2", bad.as_uri())
    with pytest.raises(up.UpdateError):
        up.latest("0.8.2", "http://example.org/latest")          # https 만
    info = up.latest("0.8.2", _release(tmp_path, "v0.9.0", html_url="javascript:alert(1)"))
    assert info.notes == ""


def test_auto_check_switch(monkeypatch):
    monkeypatch.setenv("HTEX_UPDATE_CHECK", "0")
    assert not up.auto_check_allowed()
    monkeypatch.setenv("HTEX_UPDATE_CHECK", "1")
    assert up.auto_check_allowed()
    monkeypatch.setenv("HTEX_UPDATE_URL", "file:///x.json")
    assert up.check_url() == "file:///x.json"


SCRIPT = textwrap.dedent(r'''
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2]); NEW = sys.argv[3]; SAME = sys.argv[4]; MISSING = sys.argv[5]
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from htex.viewer import app as appmod
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    w = appmod.ViewerWindow(core=ViewerCore(cache=TreeCache()), bookmarks=BookmarkStore(path=None))
    w.resize(1000, 700); w.show()
    res = {}

    def wait_until(cond, t=10):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(30)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())

    res["hidden_at_start"] = w.update_btn.isHidden()
    res["menu"] = [a.text() for a in w.update_menu.actions()]
    res["auto_checked"] = w.act_auto_update.isChecked()

    # 최신이면 단추 없음, 사용자가 누른 확인이면 상태 줄에 알림
    w.last_update_result = None
    w.check_updates(manual=True, url=SAME)
    wait_until(lambda: w.last_update_result is not None)
    res["same"] = [w.last_update_result, w.update_btn.isHidden(), w.status.currentMessage()]

    # 새 버전: 단추가 보이고, 누르면 받기 페이지를 연다
    w.last_update_result = None
    w.check_updates(url=NEW)
    wait_until(lambda: w.last_update_result is not None)
    res["new"] = [w.last_update_result, not w.update_btn.isHidden(), w.act_check_update.text()]
    opened = []
    w.navigate = lambda text, tab=None: opened.append(text)
    w.update_btn.click()
    res["opened"] = opened

    # 확인 실패 (없는 파일)
    w.last_update_result = None
    w.check_updates(manual=True, url=MISSING)
    wait_until(lambda: w.last_update_result is not None)
    res["error"] = [w.last_update_result, w.status.currentMessage()]

    # 하루 한 번: 방금 확인했으니 지금은 하지 않는다. 자동 확인을 끄면 하지 않는다.
    import os
    os.environ["HTEX_UPDATE_CHECK"] = "1"
    res["due_now"] = w.check_updates_if_due()
    appmod.settings().setValue("update/last_check", 0)
    w.act_auto_update.setChecked(False)
    res["off"] = w.check_updates_if_due()
    w.act_auto_update.setChecked(True)
    res["on"] = w.check_updates_if_due()
    wait_until(lambda: not w.update_checking)

    OUT.write_text(json.dumps(res, ensure_ascii=False))
    w.close(); app.quit()
''')


def test_update_button_in_window(tmp_path):
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    from htex import __version__
    major, minor, patch = up.parse_version(__version__)
    newer = f"v{major}.{minor}.{patch + 1}"
    new = _release(tmp_path, newer)
    same = _release(tmp_path, f"v{__version__}")
    script = tmp_path / "probe.py"
    script.write_text(SCRIPT, encoding="utf-8")
    out = tmp_path / "out.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox",
               HOME=str(tmp_path), HTEX_LANG="ko", HTEX_DATA_DIR=str(tmp_path / "data"),
               HTEX_UPDATE_URL=same)
    missing = (tmp_path / "none.json").as_uri()
    proc = subprocess.run([sys.executable, str(script), str(ROOT), str(out), new, same, missing],
                          env=env, capture_output=True, text=True, timeout=120)
    assert out.exists(), proc.stderr[-3000:]
    r = json.loads(out.read_text(encoding="utf-8"))

    assert r["hidden_at_start"]
    assert r["menu"] == ["업데이트 확인", "업데이트 자동 확인"] and r["auto_checked"]
    assert r["same"] == ["latest", True, f"최신 버전입니다 ({__version__})."]
    assert r["new"] == [newer[1:], True, f"새 버전 {newer[1:]} 받기…"]
    assert r["opened"] == [up.DOWNLOAD_PAGE]
    assert r["error"][0] == "error" and "확인하지 못했습니다" in r["error"][1]
    assert r["due_now"] is False and r["off"] is False and r["on"] is True
