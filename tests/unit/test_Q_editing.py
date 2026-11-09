"""Q: 원문 편집의 Qt 없는 부분 — 편집 중 원문(draft), 원격 문서의 \\input 가져오기, 저장."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from htex.viewer import editing
from htex.viewer.core import Fetcher, TreeCache, ViewerCore, safe_relative
from tests.unit.test_F_core import FakeOpener

MAIN = r"""\documentclass{article}
\begin{document}
본문 시작.
\input{sec1}
\includegraphics{fig/a.png}
\includegraphics{fig/b}
\includegraphics{https://other.org/c.png}
\includegraphics{missing.png}
\end{document}
"""
SEC1 = r"""첫 절 ALPHA. \input{parts/two}"""
TWO = r"""둘째 BETA."""
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def _texts(tree) -> str:
    return json.dumps(tree, ensure_ascii=False)


def remote(**extra):
    routes = {"https://ex.org/d/main.tex": MAIN, "https://ex.org/d/sec1.tex": SEC1,
              "https://ex.org/d/parts/two.tex": TWO,
              "https://ex.org/d/fig/a.png": (PNG, "image/png"),
              "https://ex.org/d/fig/b": (b"%PDF-1.4 x", "application/pdf")}
    routes.update(extra)
    op = FakeOpener(routes)
    return ViewerCore(fetcher=Fetcher(op), cache=TreeCache()), op


def test_remote_input_is_fetched_from_same_server():
    core, op = remote()
    rec = core.load("htex://ex.org/d/main.tex")
    s = _texts(rec.tree)
    assert "ALPHA" in s and "BETA" in s
    asked = [u for u, *_ in op.requests]
    assert "https://ex.org/d/sec1.tex" in asked and "https://ex.org/d/parts/two.tex" in asked
    assert not any(d["code"] == "missing-resource" and "sec1" in d["message"] for d in rec.diagnostics)


def test_remote_input_cannot_leave_folder_or_read_local(tmp_path, monkeypatch):
    secret = tmp_path / "secret.tex"
    secret.write_text("SECRET", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    doc = "\\documentclass{article}\\begin{document}\\input{../up}\\input{secret}\\end{document}"
    core, op = remote(**{"https://ex.org/d/x.tex": doc})
    rec = core.load("htex://ex.org/d/x.tex")
    assert "SECRET" not in _texts(rec.tree)
    asked = [u for u, *_ in op.requests]
    assert not any("up" in u for u in asked)          # ../ 는 가져오지도 않는다


def test_safe_relative():
    assert safe_relative("a/b.tex") == "a/b.tex"
    assert safe_relative("./a//b.tex") == "a/b.tex"
    for bad in ("../a", "a/../../b", "/etc/passwd", "https://x/a", "C:/x", "", "a\x00b"):
        assert safe_relative(bad) is None, bad


def test_draft_replaces_local_and_remote_text(tmp_path):
    f = tmp_path / "a.htex"
    f.write_text("\\documentclass{hypertex}\\begin{document}ORIGINAL\\end{document}", encoding="utf-8")
    core, op = remote()
    url = core.local_url(f)
    assert "ORIGINAL" in _texts(core.load(url).tree)
    core.set_draft(url, "\\documentclass{hypertex}\\begin{document}EDITED\\end{document}")
    assert "EDITED" in _texts(core.load(url).tree)
    core.set_draft(url, None)
    assert "ORIGINAL" in _texts(core.load(url).tree)
    # 원격: 처음 한 번만 가져오고 편집 중에는 서버에 다시 묻지 않는다
    core.load("htex://ex.org/d/main.tex")
    n = len(op.requests)
    core.set_draft("htex://ex.org/d/main.tex", MAIN.replace("본문 시작", "GAMMA"))
    s = _texts(core.load("htex://ex.org/d/main.tex", reload=False).tree)
    assert "GAMMA" in s and "ALPHA" in s
    assert not any(u.endswith("main.tex") for u, *_ in op.requests[n:])


def test_local_html_draft(tmp_path):
    f = tmp_path / "p.html"
    f.write_text("<p>OLD</p>", encoding="utf-8")
    core = ViewerCore(cache=TreeCache())
    url = core.local_url(f)
    assert b"OLD" in core.respond(url).body
    core.set_draft(url, "<p>NEW</p>")
    assert b"NEW" in core.respond(url).body


# ---------------------------------------------------------------- 로컬 저장
def test_save_keeps_bom_and_crlf_and_backs_up(tmp_path):
    f = tmp_path / "a.tex"
    f.write_bytes(editing.BOM + "가\r\n나\r\n".encode("utf-8"))
    src = editing.open_local(f)
    assert src.text == "가\n나\n" and src.bom and src.newline == "\r\n"
    backups = tmp_path / "bk"
    new = editing.save_local(src, "가\n나\n다\n", backup_dir=backups)
    assert f.read_bytes() == editing.BOM + "가\r\n나\r\n다\r\n".encode("utf-8")
    kept = list(backups.iterdir())
    assert len(kept) == 1 and kept[0].read_bytes() == editing.BOM + "가\r\n나\r\n".encode("utf-8")
    assert new.sig == editing.signature(f)
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".htex-tmp")]


def test_save_detects_outside_change(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("one", encoding="utf-8")
    src = editing.open_local(f)
    time.sleep(0.01)
    f.write_text("changed elsewhere", encoding="utf-8")
    os.utime(f, ns=(src.sig[0] + 10**9, src.sig[0] + 10**9))
    with pytest.raises(editing.Conflict):
        editing.save_local(src, "two")
    editing.save_local(src, "two", force=True)
    assert f.read_text(encoding="utf-8") == "two"


def test_non_utf8_is_not_editable(tmp_path):
    f = tmp_path / "a.tex"
    f.write_bytes("한글".encode("cp949"))
    with pytest.raises(editing.EditError):
        editing.open_local(f)


def test_old_backups_are_pruned(tmp_path):
    bk = tmp_path / "bk"
    bk.mkdir()
    old = bk / "old.tex"
    old.write_text("x")
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    f = tmp_path / "a.tex"
    f.write_text("y")
    editing.backup(f, bk)
    assert not old.exists() and len(list(bk.iterdir())) == 1


def test_mode_of():
    assert editing.mode_of("a.tex") == "tex" and editing.mode_of("a.htex") == "tex"
    assert editing.mode_of("A.MD") == "md" and editing.mode_of("x.markdown") == "md"
    assert editing.mode_of("p.html") == "html" and editing.mode_of("p.htm#x") == "html"


# ---------------------------------------------------------------- 원격 → 로컬 사본
def test_remote_copy_brings_inputs_and_figures(tmp_path):
    core, _ = remote()
    edited = MAIN.replace("본문 시작", "고친 본문")
    copy = editing.plan_remote_copy(core, "htex://ex.org/d/main.tex", edited, "paper.tex")
    assert set(copy.files) == {"paper.tex", "sec1.tex", "parts/two.tex", "fig/a.png", "fig/b.pdf"}
    assert copy.files["paper.tex"].decode("utf-8") == edited
    assert copy.failed == ["missing.png"]
    out = tmp_path / "out"
    out.mkdir()
    (out / "sec1.tex").write_text("old")
    assert editing.existing_files(out, copy) == ["sec1.tex"]
    written = editing.write_copy(out, copy)
    assert len(written) == 5
    assert (out / "parts" / "two.tex").read_text(encoding="utf-8") == TWO
    assert (out / "fig" / "a.png").read_bytes() == PNG
    # 저장한 사본을 로컬 문서로 열면 같은 내용이 보인다
    s = _texts(core.load(core.local_url(out / "paper.tex")).tree)
    assert "고친 본문" in s and "ALPHA" in s and "BETA" in s


def test_copy_targets_stay_inside(tmp_path):
    copy = editing.RemoteCopy("a.tex", {"a.tex": b"x", "../evil.tex": b"y", "/abs.tex": b"z"})
    assert set(editing.copy_targets(tmp_path, copy)) == {"a.tex"}


def test_editor_bundle_is_shipped():
    root = Path(__file__).resolve().parents[2]
    js = root / "htex" / "viewer" / "editor.js"
    lic = (root / "htex" / "viewer" / "editor.LICENSE.txt").read_text(encoding="utf-8")
    assert js.is_file() and 200_000 < js.stat().st_size < 2_000_000
    assert js.read_text(encoding="utf-8").startswith("/* HyperTeX editor: CodeMirror 6")
    assert "@codemirror/view" in lic and "MIT" in lic
    core = ViewerCore(cache=TreeCache())
    r = core.respond("htexapp://asset/editor.js", "htexapp://editor")
    assert r.status == 200 and r.mime == "text/javascript" and r.body == js.read_bytes()
