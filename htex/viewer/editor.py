"""원문 편집기 칸 (10단계 Q). 탭 왼쪽에 놓고 오른쪽 미리보기와 나란히 쓴다.

편집기는 CodeMirror 6 (tools/editor 에서 묶은 htex/viewer/editor.js, 약 0.6MB) 을 별도 웹 페이지에 띄운다.
그 페이지에만 QWebChannel 로 bridge 객체를 준다 — 문서 페이지(미리보기·다른 탭)는 저장 기능에 닿을 수 없다.
파일 쓰기는 모두 Python 쪽(app.py 의 저장 → editing.py)에서 사용자가 연 파일·고른 경로에만 한다.

    JS → Python  bridge.init() 처음 상태 · bridge.created() 준비됨 · bridge.touched() 첫 수정 · bridge.changed(text) 내용 (잠깐 멈추면)
    Python → JS  HtexEditor.setText / setDiagnostics / setDark / openSearch / gotoLine / focus / getText
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..i18n import ui_language
from .editing import LocalSource, mode_of

EDITOR_URL = "htexapp://editor/"
CHANGE_DELAY_MS = 300           # 입력을 멈추고 이만큼 지나면 미리보기를 다시 그린다
_CSP = "default-src 'none'; script-src 'unsafe-inline' htexapp:; style-src 'unsafe-inline'; img-src data:"


def _qwebchannel_js() -> str:
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        return ""
    try:
        return bytes(f.readAll().data()).decode("utf-8")
    finally:
        f.close()


def editor_html(dark: bool) -> str:
    bg = "#282c34" if dark else "#ffffff"
    return f"""<!doctype html>
<html lang="{ui_language()}"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{_CSP}">
<style>html,body{{margin:0;height:100%;overflow:hidden;background:{bg}}}#editor{{height:100%}}</style>
<script>{_qwebchannel_js()}</script>
<script src="htexapp://asset/editor.js"></script>
</head><body><div id="editor"></div></body></html>"""


class _Bridge(QObject):
    def __init__(self, pane: "EditorPane"):
        super().__init__(pane)
        self.pane = pane

    @Slot(result=str)
    def init(self) -> str:
        return json.dumps(self.pane.init_state(), ensure_ascii=False)

    @Slot()
    def created(self) -> None:
        self.pane._on_created()

    @Slot()
    def touched(self) -> None:
        self.pane._on_touched()

    @Slot(str)
    def changed(self, text: str) -> None:
        self.pane._on_changed(text)


class EditorPage(QWebEnginePage):
    """편집기 페이지: 처음 setHtml 말고는 어디로도 가지 않는다. 새 창도 없다."""

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self.loaded_once = False
        self.console_log: list = []

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        if not self.loaded_once and is_main_frame and url.scheme().lower() in ("data", "htexapp"):
            self.loaded_once = True
            return True
        return False

    def createWindow(self, kind):  # noqa: N802
        return None

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        self.console_log.append((message, line, source))


class EditorPane(QWidget):
    """편집하는 문서 하나. address 는 그 문서의 주소(htexapp://doc-… 또는 htex://…).
    local 은 로컬 파일이면 그 파일 정보(LocalSource), 원격이면 None (저장은 '다른 이름으로')."""

    dirty_changed = Signal(bool)
    text_changed = Signal(str)          # 입력을 멈췄을 때 지금 원문
    created = Signal()                  # 편집기가 준비됨

    def __init__(self, profile, address: str, text: str, local: Optional[LocalSource] = None,
                 dark: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.address = address
        self.local = local
        self.saved_text = text           # 마지막으로 저장한(또는 읽은) 원문
        self.text = text                 # 편집기의 지금 원문 (입력을 멈출 때마다 갱신)
        self.dirty = False
        self.ready = False
        self.backed_up = False           # 이번 실행에서 원본을 백업했나
        self.dark = dark
        self._pending: list[str] = []    # 준비되기 전에 부른 JS
        self.view = QWebEngineView(self)
        self.page = EditorPage(profile, self.view)
        s = self.page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.channel = QWebChannel(self.page)
        self.bridge = _Bridge(self)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)
        self.view.setPage(self.page)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.page.setHtml(editor_html(dark), QUrl(EDITOR_URL))

    # ------------------------------------------------------------ 상태
    @property
    def mode(self) -> str:
        return mode_of(str(self.local.path) if self.local else self.address)

    @property
    def is_remote(self) -> bool:
        return self.local is None

    @property
    def name(self) -> str:
        if self.local is not None:
            return self.local.path.name
        tail = self.address.split("#", 1)[0].split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        return tail or "document.htex"

    def init_state(self) -> dict:
        return {"text": self.text, "mode": self.mode, "dark": self.dark, "lang": ui_language(),
                "delay": CHANGE_DELAY_MS}

    def _on_created(self) -> None:
        self.ready = True
        for js in self._pending:
            self.page.runJavaScript(js, 0)
        self._pending = []
        self.created.emit()

    def _js(self, code: str, callback: Optional[Callable] = None) -> None:
        if not self.ready:
            if callback is None:
                self._pending.append(code)
                return
        if callback is None:
            self.page.runJavaScript(code, 0)
        else:
            self.page.runJavaScript(code, 0, callback)

    def _set_dirty(self, on: bool) -> None:
        if on != self.dirty:
            self.dirty = on
            self.dirty_changed.emit(on)

    def _on_touched(self) -> None:
        self._set_dirty(True)

    def _on_changed(self, text: str) -> None:
        self.text = text
        self._set_dirty(text != self.saved_text)
        self.text_changed.emit(text)

    # ------------------------------------------------------------ 창이 부르는 것
    def current_text(self, callback: Callable[[str], None]) -> None:
        """편집기의 바로 지금 원문 (아직 보내지 않은 입력 포함)."""
        if not self.ready:
            callback(self.text)
            return

        def got(v):
            if isinstance(v, str):
                self.text = v
            callback(self.text)
        self.page.runJavaScript("HtexEditor.getText()", 0, got)

    def mark_saved(self, text: str, local: Optional[LocalSource] = None, address: Optional[str] = None) -> None:
        self.saved_text = text
        if local is not None:
            self.local = local
        if address is not None:
            self.address = address
        if self.text == text:
            self._set_dirty(False)
            self._js("HtexEditor.markClean()")

    def replace_text(self, text: str, local: Optional[LocalSource] = None) -> None:
        """밖에서 파일이 바뀌었을 때(고친 것이 없으면) 다시 읽어 넣는다."""
        self.text = self.saved_text = text
        if local is not None:
            self.local = local
        self._js("HtexEditor.setText(" + json.dumps(text, ensure_ascii=False) + ")")
        self._set_dirty(False)

    def set_diagnostics(self, diags: list[dict]) -> None:
        items = []
        for d in diags or []:
            sp = d.get("span") or {}
            if not sp.get("line"):
                continue
            items.append({"line": sp.get("line"), "col": sp.get("col"), "endLine": sp.get("endLine"),
                          "endCol": sp.get("endCol"), "severity": d.get("severity"),
                          "message": d.get("message") or d.get("code")})
        self._js("HtexEditor.setDiagnostics(" + json.dumps(items, ensure_ascii=False) + ")")

    def set_dark(self, on: bool) -> None:
        self.dark = on
        self._js(f"HtexEditor.setDark({'true' if on else 'false'})")

    def open_search(self) -> None:
        self._js("HtexEditor.openSearch()")

    def goto_line(self, n: int) -> None:
        self._js(f"HtexEditor.gotoLine({int(n)})")

    def focus_editor(self) -> None:
        self.view.setFocus()
        self._js("HtexEditor.focus()")

    def has_focus(self) -> bool:
        w = self.view.focusProxy() or self.view
        return w.hasFocus() or self.view.hasFocus()

    def shutdown(self) -> None:
        self.view.setPage(None)
        self.page.deleteLater()
