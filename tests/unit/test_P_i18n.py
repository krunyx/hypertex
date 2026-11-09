"""P: 화면 글자 영어·한국어 (htex/i18n.py), 문서 안 이름은 문서 언어."""
from __future__ import annotations

import ast
import json
import os
import re
import string
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from htex import i18n
from htex.html import render
from htex.i18n_en import EN
from htex.parser import parse_text

ROOT = Path(__file__).resolve().parents[2]
HANGUL = re.compile("[가-힣]")


def _tr_keys() -> dict[str, str]:
    keys = {}
    for f in (ROOT / "htex").rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                keys[n.args[0].value] = f"{f.relative_to(ROOT)}:{n.lineno}"
    return keys


def _fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def test_every_korean_string_has_english():
    keys = _tr_keys()
    assert len(keys) > 200
    missing = {k: where for k, where in keys.items() if HANGUL.search(k) and k not in EN}
    assert not missing, missing
    # 이름으로 나중에 tr() 하는 표 (테마·언어·기본 북마크)
    from htex.viewer.app import LANGUAGES, THEMES
    from htex.viewer.bookmarks import DEFAULT_BOOKMARKS
    for label in [x for _, x in THEMES + LANGUAGES] + [d["title"] for d in DEFAULT_BOOKMARKS]:
        assert not HANGUL.search(label) or label in EN, label


def test_translations_keep_placeholders_and_are_english():
    for ko, en in EN.items():
        assert _fields(ko) == _fields(en), (ko, en)
        if ko != "한국어":
            assert not HANGUL.search(en), en


def test_no_untranslated_korean_left_in_ui_code():
    """docstring·주석이 아닌 한국어 문자열은 tr() 안에만 (표로 두고 쓸 때 tr() 하는 것은 예외)."""
    allowed = {"시스템 설정", "밝게", "어둡게", "시작하기", "시스템 언어", "한국어", "언어 · Language"}
    files = list((ROOT / "htex" / "viewer").glob("*.py")) + list((ROOT / "htex" / "web").glob("*.py")) + \
        [ROOT / "htex" / "__main__.py"]
    bad = []
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        docs, inside = set(), set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and \
                    isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                docs.add(id(n.body[0].value))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr":
                inside |= {id(m) for m in ast.walk(n)}
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and \
                    isinstance(n.func.value, ast.Name) and n.func.value.id == "re":
                inside |= {id(m) for m in ast.walk(n)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and HANGUL.search(n.value) \
                    and id(n) not in docs and id(n) not in inside and n.value not in allowed:
                bad.append(f"{f.name}:{n.lineno} {n.value[:40]!r}")
    assert not bad, bad


def test_tr_switches_language(monkeypatch):
    monkeypatch.delenv("HTEX_LANG", raising=False)
    try:
        assert i18n.set_language("en") == "en"
        assert i18n.tr("새 탭") == "New Tab"
        assert i18n.tr("탭 {n}", n=3) == "Tab 3"
        assert i18n.tr("없는 문장") == "없는 문장"            # 표에 없으면 원문
        assert i18n.set_language("ko") == "ko"
        assert i18n.tr("탭 {n}", n=3) == "탭 3"
        monkeypatch.setenv("HTEX_LANG", "en")
        assert i18n.set_language("auto") == "en"
        monkeypatch.setenv("LANG", "ko_KR.UTF-8")
        monkeypatch.delenv("HTEX_LANG")
        monkeypatch.setattr(i18n, "detect_system", lambda: "ko")
        assert i18n.set_language(None) == "ko"
    finally:
        os.environ["HTEX_LANG"] = "ko"
        i18n.set_language(None)


def test_system_language_from_env(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_qt(name, *a, **k):
        if name.startswith("PySide6"):
            raise ImportError
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_qt)
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    assert i18n.detect_system() == "ko"
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.detect_system() == "en"
    monkeypatch.setenv("LANG", "C")
    assert i18n.detect_system() == "en"


def test_document_language():
    assert i18n.doc_language("조화 진동자의 에너지는 E = mc^2 이다") == "ko"
    assert i18n.doc_language("The energy of a harmonic oscillator, 에너지") == "en"
    en = parse_text(r"""\documentclass{article}\usepackage{graphicx}\begin{document}
\begin{abstract}We study waves.\end{abstract}
\begin{figure}\includegraphics{a.png}\caption{Waves}\end{figure}
\begin{proof}Obvious.\end{proof}
\end{document}""", url="t.tex")
    html = re.sub(r"<style>.*?</style>", "", render(en), flags=re.S)     # CSS 주석은 빼고
    assert '<html lang="en">' in html and "Figure" in html and "Abstract" in html and "Proof" in html
    assert not re.search("그림|요약|증명", html)
    ko = parse_text(r"""\documentclass{hypertex}\begin{document}
\begin{abstract}파동을 공부한다.\end{abstract}
\begin{figure}\includegraphics{a.png}\caption{파동 그림}\end{figure}
\end{document}""", url="t.htex")
    html = render(ko)
    assert '<html lang="ko">' in html and "그림" in html and "요약" in html


# ---------------------------------------------------------------- 영어 창
pytest.importorskip("PySide6.QtWebEngineWidgets")

SCRIPT = textwrap.dedent(r'''
    import json, re, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    OUT = Path(sys.argv[2])
    from htex.viewer.app import register_schemes
    register_schemes()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from htex.viewer.app import ViewerWindow
    from htex.viewer.bookmarks import BookmarkStore
    from htex.viewer.core import ViewerCore, TreeCache
    w = ViewerWindow(core=ViewerCore(cache=TreeCache()), cwd=Path("."), bookmarks=BookmarkStore())
    w.resize(1000, 700); w.show()
    def wait_until(cond, t=8):
        loop = QEventLoop(); timer = QTimer(); timer.setInterval(30)
        timer.timeout.connect(lambda: cond() and loop.quit()); timer.start()
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); timer.stop()
        return bool(cond())
    def js(code, t=4):
        tab = w.current_tab(); loop = QEventLoop(); box = {}
        tab.page.runJavaScript(code, 0, lambda v: (box.__setitem__("v", v), loop.quit()))
        QTimer.singleShot(int(t * 1000), loop.quit); loop.exec(); return box.get("v")
    w.new_tab()
    wait_until(lambda: w.current_tab().title() == "New Tab")
    texts = []
    def walk(menu):
        for a in menu.actions():
            if a.text(): texts.append(a.text())
            if a.menu(): walk(a.menu())
    walk(w.navbar.menu.menu())
    tips = [b.toolTip() for b in (w.navbar.back, w.navbar.forward, w.navbar.home, w.tab_strip.new_btn)]
    res = {"title": w.current_tab().title(), "menu": texts, "tips": tips,
           "placeholder": js("document.querySelector('input[name=q]').placeholder"),
           "lang": js("document.documentElement.lang")}
    OUT.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    w.handler.shutdown()
''')


def test_window_in_english(tmp_path):
    out = tmp_path / "out.json"
    script = tmp_path / "script.py"
    script.write_text(SCRIPT, encoding="utf-8")
    env = dict(os.environ, HTEX_LANG="en", QT_QPA_PLATFORM="offscreen",
               QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu",
               XDG_CONFIG_HOME=str(tmp_path / "config"), XDG_CACHE_HOME=str(tmp_path / "cache"),
               XDG_DATA_HOME=str(tmp_path / "data"), HOME=str(tmp_path))
    p = subprocess.run([sys.executable, str(script), str(ROOT), str(out)], env=env,
                       capture_output=True, text=True, timeout=180)
    if not out.exists():
        pytest.fail("창 스크립트 실패:\n" + p.stdout[-3000:] + p.stderr[-3000:])
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["title"] == "New Tab" and r["lang"] == "en"
    assert r["placeholder"].startswith("Enter an htex:// address")
    assert "Language" in r["menu"] and "Theme" in r["menu"] and "Find…" in r["menu"]
    korean = [t for t in r["menu"] + r["tips"] if HANGUL.search(t) and t != "한국어"]
    assert not korean, korean


def test_theorem_names_follow_document_language():
    en = parse_text(r"""\documentclass{hypertex}\begin{document}
\begin{theorem}A.\end{theorem}\begin{lemma}B.\end{lemma}\begin{proposition}C.\end{proposition}
\begin{definition}D.\end{definition}\newtheorem{conj}{Conjecture}\begin{conj}E.\end{conj}
\end{document}""", url="t.htex")
    html = re.sub(r"<style>.*?</style>", "", render(en), flags=re.S)
    for word in ("Theorem", "Lemma", "Proposition", "Definition", "Conjecture"):
        assert f'htex-thm-name">{word}' in html, word
    assert not HANGUL.search(html.split("<body", 1)[1])
    ko = parse_text(r"""\documentclass{hypertex}\begin{document}\begin{theorem}한글 정리 본문.\end{theorem}
\begin{lemma}보조 내용.\end{lemma}\end{document}""", url="t.htex")
    html = render(ko)
    assert 'htex-thm-name">정리' in html and 'htex-thm-name">보조정리' in html
