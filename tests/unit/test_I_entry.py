"""I: 실행 진입점 — `htex view [대상…]`, GUI 진입점 gui_main, run(targets) 호환 호출."""
from __future__ import annotations

import sys
import types
from typing import Optional

import pytest

import htex.__main__ as m


def _install_fake_viewer(monkeypatch, run):
    """PySide6 없이도 _view 를 시험하도록 가짜 모듈을 끼운다."""
    pyside = types.ModuleType("PySide6")
    pyside.QtWebEngineWidgets = types.ModuleType("PySide6.QtWebEngineWidgets")
    monkeypatch.setitem(sys.modules, "PySide6", pyside)
    monkeypatch.setitem(sys.modules, "PySide6.QtWebEngineWidgets", pyside.QtWebEngineWidgets)
    app = types.ModuleType("htex.viewer.app")
    app.run = run
    monkeypatch.setitem(sys.modules, "htex.viewer.app", app)
    import htex.viewer as viewer_pkg
    monkeypatch.setattr(viewer_pkg, "app", app, raising=False)


def test_call_run_new_signature():
    seen = []

    def run(targets: list[str], argv: Optional[list[str]] = None) -> int:
        seen.append(targets)
        return 7
    assert m._call_run(run, ["a.htex", "htex://x/b.htex"]) == 7
    assert seen == [["a.htex", "htex://x/b.htex"]]
    assert m._call_run(run, []) == 7 and seen[-1] == []


def test_call_run_new_signature_by_name_only():
    seen = []

    def run(targets=None):
        seen.append(targets)
        return 0
    m._call_run(run, ["a", "b"])
    assert seen == [["a", "b"]]


def test_call_run_old_signature(capsys):
    """J 의 변경 전: run(target: Optional[str]) — 첫 번째만 넘기고 알린다."""
    seen = []

    def run(target: Optional[str] = None, argv: Optional[list[str]] = None) -> int:
        seen.append(target)
        return 0
    m._call_run(run, ["a.htex", "b.htex"])
    m._call_run(run, [])
    assert seen == ["a.htex", None]
    assert "첫 번째만" in capsys.readouterr().err


def test_view_subcommand_many_targets(monkeypatch):
    seen = []

    def run(targets: list[str]) -> int:
        seen.append(targets)
        return 0
    _install_fake_viewer(monkeypatch, run)
    assert m.main(["view", "a.htex", "htex://ex.org/b.htex"]) == 0
    assert m.main(["view"]) == 0
    assert seen == [["a.htex", "htex://ex.org/b.htex"], []]


def test_gui_main_filters_os_arguments(monkeypatch):
    seen = []

    def run(targets: list[str]) -> int:
        seen.append(targets)
        return 0
    _install_fake_viewer(monkeypatch, run)
    # macOS Finder 가 붙이는 -psn_0_12345, Qt/Chromium 옵션은 대상이 아니다
    assert m.gui_main(["-psn_0_12345", "/tmp/가 나.htex", "htex://ex.org/a.htex#eq:1",
                       "--no-sandbox"]) == 0
    assert seen == [["/tmp/가 나.htex", "htex://ex.org/a.htex#eq:1"]]


def test_gui_main_version(capsys):
    from htex import __version__
    assert m.gui_main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"HyperTeX viewer {__version__}"


def test_gui_main_without_stderr(monkeypatch):
    """pythonw·windowed 실행에서는 sys.stderr 가 None 이다. PySide6 가 없어도 죽지 않고 2."""
    monkeypatch.setitem(sys.modules, "PySide6", None)       # import 실패
    monkeypatch.setattr(sys, "stderr", None)
    assert m.gui_main(["a.htex"]) == 2


def test_real_run_signature_is_supported():
    """지금 저장소의 htex.viewer.app.run 이 어느 서명이든 _call_run 이 다룰 수 있다."""
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    import inspect
    from htex.viewer.app import run
    params = list(inspect.signature(run).parameters)
    assert params and params[0] in ("target", "targets")
