"""전용 뷰어 창 (PySide6 + QtWebEngine). (담당: F, 다듬기 J)

- 일반 웹(http/https)은 QtWebEngine 이 그대로 보여 준다.
- htex:// 문서, .htex/.tex 로 끝나는 https 링크, 로컬 .htex/.tex 파일은 core.ViewerCore 가 해석해 응답한다.
- 사용자 정의 스킴 htex, htexapp 은 QApplication 을 만들기 전에 register_schemes() 로 등록해야 한다
  (run() 이 알아서 한다. 다른 곳에서 창을 띄우면 먼저 register_schemes() 를 부를 것).

J 가 더한 것
- 탭 (탭마다 히스토리·확대 배율·자동 새로고침 감시), 찾기 막대, 확대·축소, 테마(시스템/밝게/어둡게, QSettings),
  로컬 파일 자동 새로고침(QFileSystemWatcher, 300ms 묶음, 스크롤·슬라이더 값 유지), 원문 보기, 메뉴.
- run(targets) : 단일 인스턴스(QLocalServer, 이름은 instance.instance_name()), macOS QFileOpenEvent.

단축키 (Qt 의 Ctrl 은 macOS 에서 Cmd)
  Ctrl+T 새 탭 · Ctrl+W 탭 닫기 · Ctrl+Tab / Ctrl+Shift+Tab (Ctrl+PgDown/PgUp) 탭 전환 · Ctrl+1…8 그 탭, Ctrl+9 마지막 탭
  가운데 클릭·Ctrl+클릭 = 새 탭(뒤), Ctrl+Shift+클릭 = 새 탭(앞)
  Ctrl+F 찾기 · Enter/F3 다음 · Shift+Enter/Shift+F3 이전 · Esc 닫기
  Ctrl+= / Ctrl++ 확대 · Ctrl+- 축소 · Ctrl+0 원래 크기 · Ctrl+U 원문 보기
  Ctrl+O 열기 · Ctrl+L 주소 · Ctrl+R/F5 새로고침 · Alt+←/→ (macOS Cmd+[ ]) 뒤로·앞으로 · Ctrl+Q 끝내기
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtCore import (QBuffer, QByteArray, QEvent, QObject, QSettings, Qt, QTimer, QUrl,
                            QFileSystemWatcher, Signal, Slot)
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
                                     QWebEngineUrlRequestJob, QWebEngineUrlScheme,
                                     QWebEngineUrlSchemeHandler)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QSizePolicy, QTabWidget, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

from .. import __version__
from .core import (DOC_EXTS, History, Response, TreeCache, ViewerCore, ViewerError,
                   default_cache_dir, https_to_htex, is_doc_path, split_fragment)
from .instance import (REPLY_OK, decode_message, encode_message, file_signature, instance_name,
                       local_dependencies, normalize_targets)

SCHEMES = (b"htex", b"htexapp")
APP_NAME = "HyperTeX"
ORG_NAME = "HyperTeX"

ZOOM_MIN, ZOOM_MAX = 0.5, 3.0
ZOOM_STEPS = (0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
THEMES = (("system", "시스템 설정"), ("light", "밝게"), ("dark", "어둡게"))
RELOAD_DEBOUNCE_MS = 300

_registered = False


def register_schemes() -> None:
    """QApplication 이전에 한 번. 두 스킴 모두 보안 출처(SecureScheme)로, fetch·CORS 허용."""
    global _registered
    if _registered:
        return
    for name in SCHEMES:
        s = QWebEngineUrlScheme(name)
        s.setSyntax(QWebEngineUrlScheme.Syntax.Host)
        s.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                   | QWebEngineUrlScheme.Flag.CorsEnabled
                   | QWebEngineUrlScheme.Flag.FetchApiAllowed)
        QWebEngineUrlScheme.registerScheme(s)
    _registered = True


def settings() -> QSettings:
    return QSettings(ORG_NAME, "Viewer")


# ====================================================================== 스킴 처리기
class _Bridge(QObject):
    done = Signal(object, object)    # (job id, Response)


class SchemeHandler(QWebEngineUrlSchemeHandler):
    """htex: · htexapp: 요청을 작업 스레드에서 core.respond 로 처리하고 주 스레드에서 답한다."""

    loaded = Signal(object)          # DocRecord (상태 표시줄용)

    def __init__(self, core: ViewerCore, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.core = core
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="htex-req")
        self.jobs: dict[int, QWebEngineUrlRequestJob] = {}
        self.reload_next: set[str] = set()
        self._next = 0
        self._bridge = _Bridge()
        self._bridge.done.connect(self._finish, Qt.ConnectionType.QueuedConnection)

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:   # noqa: N802 (Qt 이름)
        url = job.requestUrl().toString(QUrl.ComponentFormattingOption.FullyEncoded)
        initiator = job.initiator().toString() if not job.initiator().isEmpty() else ""
        if bytes(job.requestMethod().data()).upper() != b"GET":
            job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
            return
        reload = split_fragment(url)[0] in self.reload_next
        self.reload_next.discard(split_fragment(url)[0])
        self._next += 1
        jid = self._next
        self.jobs[jid] = job
        job.destroyed.connect(lambda *_: self.jobs.pop(jid, None))
        self.pool.submit(self._work, jid, url, initiator, reload)

    def _work(self, jid: int, url: str, initiator: str, reload: bool) -> None:
        resp = self.core.respond(url, initiator, reload=reload)
        self._bridge.done.emit(jid, resp)

    @Slot(object, object)
    def _finish(self, jid: int, resp: Response) -> None:
        job = self.jobs.pop(jid, None)
        if job is None:
            return
        try:
            if resp.redirect:
                job.redirect(QUrl(resp.redirect))
                return
            if resp.fail:
                err = (QWebEngineUrlRequestJob.Error.UrlNotFound if resp.status == 404
                       else QWebEngineUrlRequestJob.Error.RequestDenied if resp.status == 403
                       else QWebEngineUrlRequestJob.Error.RequestFailed)
                job.fail(err)
                return
            if resp.headers:
                job.setAdditionalResponseHeaders(
                    {QByteArray(k.encode()): [QByteArray(v.encode())] for k, v in resp.headers.items()})
            buf = QBuffer(job)
            buf.setData(QByteArray(resp.body))
            buf.open(QBuffer.OpenModeFlag.ReadOnly)
            mime = resp.mime + ("; charset=utf-8" if resp.mime.startswith("text/") else "")
            job.reply(QByteArray(mime.encode()), buf)
        except RuntimeError:     # 그 사이 요청이 취소되어 job 이 사라졌다
            return
        if resp.record is not None:
            self.loaded.emit(resp.record)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


# ====================================================================== 페이지
class HtexPage(QWebEnginePage):
    """https 의 .htex/.tex 링크를 htex:// 로 돌리고, 웹 페이지에서 내부 스킴으로 가는 것을 막는다.
    가운데 클릭·Ctrl+클릭(새 탭)은 createWindow → 탭(J)."""

    redirected = Signal(QUrl)

    def __init__(self, profile, parent=None, tab: Optional["Tab"] = None):
        super().__init__(profile, parent)
        self.tab = tab

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        scheme = url.scheme().lower()
        current = self.url().scheme().lower()
        if scheme in ("http", "https") and is_doc_path(url.path()):
            if not is_main_frame:
                return False
            if scheme == "http":
                return False      # 명세 2절: 문서 전송은 HTTPS 만
            target = https_to_htex(url.toString(QUrl.ComponentFormattingOption.FullyEncoded))
            frag = url.fragment(QUrl.ComponentFormattingOption.FullyEncoded)
            self.redirected.emit(QUrl(target + ("#" + frag if frag else "")))
            return False
        if scheme == "file":
            return False          # 로컬 파일은 htexapp://doc-… 로만 (사용자가 연 폴더)
        if scheme == "htexapp" and current in ("http", "https"):
            return False          # 웹 페이지 → 내부 주소 금지
        if scheme in ("javascript", "data"):
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def createWindow(self, kind):  # noqa: N802 - 가운데 클릭·Ctrl+클릭 (window.open 은 설정으로 막혀 있다)
        win = self.tab.window_ref if self.tab is not None else None
        if win is None:
            return None
        WT = QWebEnginePage.WebWindowType
        if kind not in (WT.WebBrowserTab, WT.WebBrowserBackgroundTab, WT.WebBrowserWindow):
            return None
        tab = win.new_tab(background=(kind == WT.WebBrowserBackgroundTab), focus_address=False)
        return tab.page

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if getattr(self, "console_log", None) is not None:
            self.console_log.append((int(level.value) if hasattr(level, "value") else int(level),
                                     message, line, source))


# ====================================================================== 탭
_SAVE_STATE_JS = ("JSON.stringify({x: window.scrollX, y: window.scrollY, "
                  "p: (window.HTEX && window.HTEX.getParams) ? window.HTEX.getParams() : {}})")


class Tab(QWidget):
    """웹 뷰 하나 + 그 탭의 히스토리·확대 배율·자동 새로고침 감시."""

    title_changed = Signal(object, str)
    url_changed = Signal(object, str)
    load_finished = Signal(object, bool)
    zoom_changed = Signal(object, float)

    def __init__(self, win: "ViewerWindow"):
        super().__init__(win.tabs)
        self.window_ref = win
        self.core = win.core
        self.history = History()
        self._history_nav: Optional[str] = None
        self.zoom = 1.0
        self.pinned_source = False       # 원문 보기 탭
        self.view = QWebEngineView(self)
        self.page = HtexPage(win.profile, self.view, tab=self)
        self.page.console_log = []
        # 탐색 판정 중에 다시 탐색하면 엔진이 멈출 수 있어 한 박자 미룬다
        self.page.redirected.connect(self.navigate_url, Qt.ConnectionType.QueuedConnection)
        s = self.page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.view.setPage(self.page)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

        # 자동 새로고침 (로컬 문서만)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_fs_change)
        self.watcher.directoryChanged.connect(self._on_fs_change)
        self._watch_sig: tuple = ()
        self._watch_files: list[Path] = []
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(RELOAD_DEBOUNCE_MS)
        self._reload_timer.timeout.connect(self._check_reload)
        self._restore: Optional[dict] = None
        self.auto_reloads = 0

        self.view.urlChanged.connect(self._on_url_changed)
        self.view.titleChanged.connect(lambda t: (self.history.set_title(t),
                                                  self.title_changed.emit(self, t)))
        self.view.loadFinished.connect(self._on_load_finished)

    # ------------------------------------------------------------ 이동
    def current_url(self) -> str:
        return self.view.url().toString(QUrl.ComponentFormattingOption.FullyEncoded)

    def title(self) -> str:
        return self.view.title()

    def is_blank(self) -> bool:
        u = self.current_url()
        return (not u or u == "about:blank") and not self.history.entries

    @Slot(QUrl)
    def navigate_url(self, url: QUrl) -> None:
        self.view.setUrl(url)
        self.view.setFocus()

    def go_history(self, entry) -> None:
        if entry is None:
            return
        self._history_nav = entry.url
        self.view.setUrl(QUrl(entry.url))

    def back(self) -> None:
        self.go_history(self.history.back())

    def forward(self) -> None:
        self.go_history(self.history.forward())

    def reload(self, keep_state: bool = False) -> None:
        url = self.current_url()
        base = split_fragment(url)[0]
        if url.startswith(("htex:", "htexapp://doc-")):
            self.core.invalidate(base)
            self.window_ref.handler.reload_next.add(base)
        if keep_state and url.startswith(("htex:", "htexapp:")):
            def go(state):
                try:
                    self._restore = json.loads(state) if isinstance(state, str) else None
                except ValueError:
                    self._restore = None
                self.view.triggerPageAction(QWebEnginePage.WebAction.ReloadAndBypassCache)
            self.page.runJavaScript(_SAVE_STATE_JS, 0, go)
            return
        self.view.triggerPageAction(QWebEnginePage.WebAction.ReloadAndBypassCache)

    # ------------------------------------------------------------ 확대·테마
    def set_zoom(self, z: float) -> None:
        z = max(ZOOM_MIN, min(ZOOM_MAX, round(float(z), 3)))
        self.zoom = z
        self.view.setZoomFactor(z)
        self.zoom_changed.emit(self, z)

    def apply_theme(self, theme: str) -> None:
        if not self.current_url().startswith(("htex:", "htexapp:")):
            return
        if theme in ("light", "dark"):
            js = f"document.documentElement.setAttribute('data-theme', '{theme}')"
        else:
            js = "document.documentElement.removeAttribute('data-theme')"
        self.page.runJavaScript(js, 0)

    # ------------------------------------------------------------ 신호
    def _on_url_changed(self, qurl: QUrl) -> None:
        url = qurl.toString(QUrl.ComponentFormattingOption.FullyEncoded)
        if not url or url == "about:blank":
            return
        if self._history_nav is not None and _same(url, self._history_nav):
            self._history_nav = None
        else:
            self._history_nav = None
            self.history.visit(url, self.view.title())
        self.url_changed.emit(self, url)

    def _on_load_finished(self, ok: bool) -> None:
        if abs(self.view.zoomFactor() - self.zoom) > 1e-3:     # 다른 출처로 옮기면 엔진이 되돌릴 수 있다
            self.view.setZoomFactor(self.zoom)
        self.apply_theme(self.window_ref.theme)
        if self._restore is not None:
            st, self._restore = self._restore, None
            params = st.get("p") or {}
            js = ("(function(s){if(window.HTEX&&window.HTEX.setParam){for(var k in s.p)"
                  "{try{window.HTEX.setParam(k,s.p[k]);}catch(e){}}}"
                  "window.scrollTo(s.x||0,s.y||0);})(" + json.dumps({"x": st.get("x", 0),
                                                                      "y": st.get("y", 0),
                                                                      "p": params}) + ")")
            self.page.runJavaScript(js, 0)
        self._update_watch()
        self.load_finished.emit(self, ok)

    # ------------------------------------------------------------ 자동 새로고침
    def watched_files(self) -> list[Path]:
        return list(self._watch_files)

    def _update_watch(self) -> None:
        files: list[Path] = []
        url = self.current_url()
        if url.startswith("htexapp://doc-"):
            try:
                path = self.core.local_path(split_fragment(url)[0])
            except ViewerError:
                path = None
            if path is not None and path.suffix.lower() in DOC_EXTS and path.is_file():
                files = [path] + local_dependencies(path)
        self._set_watch(files)

    def _set_watch(self, files: list[Path]) -> None:
        old = self.watcher.files() + self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        self._watch_files = files
        self._watch_sig = file_signature(files)
        if files:
            self.watcher.addPaths([str(p) for p in files])
            # 편집기는 흔히 새 파일을 쓰고 이름을 바꾼다 → 파일 감시가 끊기므로 폴더도 본다
            self.watcher.addPaths(sorted({str(p.parent) for p in files}))

    def _on_fs_change(self, _path: str) -> None:
        if self._watch_files:
            self._reload_timer.start()          # 300ms 안의 여러 변경은 한 번으로

    def _check_reload(self) -> None:
        sig = file_signature(self._watch_files)
        # 이름 바꾸기로 끊긴 감시를 다시 건다
        missing = [str(p) for p in self._watch_files
                   if str(p) not in self.watcher.files() and p.exists()]
        if missing:
            self.watcher.addPaths(missing)
        if sig == self._watch_sig:
            return
        if not self._watch_files[0].exists():   # 저장 도중(지웠다 다시 쓰기): 조금 뒤 다시
            self._reload_timer.start()
            return
        self._watch_sig = sig
        self.auto_reloads += 1
        self.reload(keep_state=True)


# ====================================================================== 찾기 막대
class FindBar(QWidget):
    def __init__(self, win: "ViewerWindow"):
        super().__init__(win)
        self.win = win
        self.setObjectName("findbar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)
        lay.addWidget(QLabel("찾기", self))
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("문서에서 찾기")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumWidth(240)
        self.edit.installEventFilter(self)
        self.edit.textChanged.connect(lambda _t: self.find(forward=True, incremental=True))
        lay.addWidget(self.edit)
        self.prev_btn = QToolButton(self)
        self.prev_btn.setText("▲")
        self.prev_btn.setToolTip("이전 (Shift+Enter, Shift+F3)")
        self.prev_btn.clicked.connect(lambda: self.find(forward=False))
        self.next_btn = QToolButton(self)
        self.next_btn.setText("▼")
        self.next_btn.setToolTip("다음 (Enter, F3)")
        self.next_btn.clicked.connect(lambda: self.find(forward=True))
        lay.addWidget(self.prev_btn)
        lay.addWidget(self.next_btn)
        self.count = QLabel("", self)
        self.count.setMinimumWidth(90)
        lay.addWidget(self.count)
        lay.addStretch(1)
        close = QToolButton(self)
        close.setText("✕")
        close.setToolTip("닫기 (Esc)")
        close.setAutoRaise(True)
        close.clicked.connect(self.close_bar)
        lay.addWidget(close)
        self.matches = (0, 0)       # (현재, 전체)
        self._page = None
        self.hide()

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.find(forward=not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                return True
            if k == Qt.Key.Key_Escape:
                self.close_bar()
                return True
        return super().eventFilter(obj, ev)

    def open_bar(self) -> None:
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()
        if self.edit.text():
            self.find(forward=True, incremental=True)

    def close_bar(self) -> None:
        tab = self.win.current_tab()
        if tab is not None:
            tab.page.findText("")
        self.hide()
        self.count.setText("")
        self.matches = (0, 0)
        if tab is not None:
            tab.view.setFocus()

    def _connect(self, page) -> None:
        if self._page is page:
            return
        if self._page is not None:
            try:
                self._page.findTextFinished.disconnect(self._on_result)
            except (RuntimeError, TypeError):
                pass
        self._page = page
        page.findTextFinished.connect(self._on_result)

    def find(self, forward: bool = True, incremental: bool = False) -> None:
        tab = self.win.current_tab()
        if tab is None:
            return
        self._connect(tab.page)
        text = self.edit.text()
        if not text:
            tab.page.findText("")
            self.count.setText("")
            self.matches = (0, 0)
            return
        flags = QWebEnginePage.FindFlag(0)
        if not forward:
            flags |= QWebEnginePage.FindFlag.FindBackward
        tab.page.findText(text, flags)

    def _on_result(self, result) -> None:
        n, i = result.numberOfMatches(), result.activeMatch()
        self.matches = (i, n)
        if not self.edit.text():
            self.count.setText("")
        elif n == 0:
            self.count.setText("일치 없음")
        else:
            self.count.setText(f"{i}/{n}")


# ====================================================================== 창
_profile: Optional[QWebEngineProfile] = None


def shared_profile() -> QWebEngineProfile:
    """앱 전체가 쓰는 프로필 하나 (QApplication 이 소유: 페이지보다 늦게 지워진다)."""
    global _profile
    if _profile is None:
        _profile = QWebEngineProfile(APP_NAME.lower(), QApplication.instance())
        web = default_cache_dir() / "web"
        _profile.setCachePath(str(web / "cache"))
        _profile.setPersistentStoragePath(str(web / "storage"))
    return _profile


class ViewerWindow(QMainWindow):
    def __init__(self, core: Optional[ViewerCore] = None, profile: Optional[QWebEngineProfile] = None,
                 cwd: Optional[Path] = None):
        super().__init__()
        self.core = core or ViewerCore(cache=TreeCache(default_cache_dir()))
        self.cwd = cwd or Path.cwd()

        self.profile = profile = profile or shared_profile()
        if f"HyperTeX/{__version__}" not in profile.httpUserAgent():
            profile.setHttpUserAgent(profile.httpUserAgent() + f" HyperTeX/{__version__}")
        # 처리기는 프로필에 하나 (프로필이 소유). 창이 여럿이어도 같은 core 를 나눠 쓴다.
        handler = profile.urlSchemeHandler(QByteArray(SCHEMES[0]))
        if isinstance(handler, SchemeHandler):
            if core is not None:
                handler.core = self.core
            else:
                self.core = handler.core
        else:
            handler = SchemeHandler(self.core, profile)
            for name in SCHEMES:
                profile.installUrlSchemeHandler(QByteArray(name), handler)
        self.handler = handler

        self.theme = _read_theme()
        self.core.theme = "" if self.theme == "system" else self.theme

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabCloseRequested.connect(lambda i: self.close_tab(i))
        self.tabs.currentChanged.connect(self._on_current_changed)
        self.find_bar = FindBar(self)
        central = QWidget(self)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.find_bar)
        self.setCentralWidget(central)

        self._build_toolbar()
        self._build_menus()
        self.diag_label = QLabel("")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setToolTip("확대 배율 (Ctrl+0 원래 크기)")
        self.statusBar().addPermanentWidget(self.diag_label)
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 820)
        self.apply_window_theme()
        self.new_tab()

    # ------------------------------------------------------------ 호환 (F 의 단일 뷰 이름)
    @property
    def view(self) -> QWebEngineView:
        return self.current_tab().view

    @property
    def page(self) -> HtexPage:
        return self.current_tab().page

    @property
    def history(self) -> History:
        return self.current_tab().history

    # ------------------------------------------------------------ 탭
    def current_tab(self) -> Optional[Tab]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, Tab) else None

    def tab_list(self) -> list[Tab]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def new_tab(self, target: Optional[str] = None, background: bool = False,
                focus_address: bool = True) -> Tab:
        tab = Tab(self)
        tab.title_changed.connect(self._on_tab_title)
        tab.url_changed.connect(self._on_tab_url)
        tab.load_finished.connect(self._on_tab_loaded)
        tab.zoom_changed.connect(self._on_tab_zoom)
        tab.view.loadStarted.connect(lambda t=tab: t is self.current_tab()
                                     and self.statusBar().showMessage("불러오는 중…"))
        tab.page.linkHovered.connect(lambda u, t=tab: t is self.current_tab() and self._on_hover(u))
        cur = self.tabs.currentIndex()
        idx = self.tabs.insertTab(cur + 1 if cur >= 0 else 0, tab, "새 탭")
        if not background:
            self.tabs.setCurrentIndex(idx)
        if target:
            self.navigate(target, tab=tab)
        elif not background and focus_address:
            self._focus_address()
        return tab

    def close_tab(self, index: Optional[int] = None) -> None:
        if index is None:
            index = self.tabs.currentIndex()
        if index < 0:
            return
        tab = self.tabs.widget(index)
        if self.tabs.count() == 1:
            self.close()                 # 마지막 탭을 닫으면 창을 닫는다 (브라우저와 같게)
            return
        self.tabs.removeTab(index)
        if isinstance(tab, Tab):
            tab.watcher.removePaths(tab.watcher.files() + tab.watcher.directories())
            tab.view.setPage(None)
            tab.page.deleteLater()
            tab.deleteLater()

    def select_tab(self, n: int) -> None:
        """Ctrl+1…8 = 그 번호 탭, Ctrl+9 = 마지막 탭 (브라우저 관례)."""
        count = self.tabs.count()
        if count:
            self.tabs.setCurrentIndex(count - 1 if n == 9 else min(n - 1, count - 1))

    def cycle_tab(self, step: int) -> None:
        count = self.tabs.count()
        if count:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % count)

    def open_targets(self, targets: Iterable[str], raise_window: bool = True) -> None:
        """대상들을 새 탭으로 (현재 탭이 비어 있으면 첫 대상은 거기에). 단일 인스턴스·파일 열기 이벤트가 쓴다."""
        first = True
        for t in targets:
            cur = self.current_tab()
            if first and cur is not None and cur.is_blank():
                self.navigate(t, tab=cur)
            else:
                self.new_tab(t, focus_address=False)
            first = False
        if raise_window:
            self.bring_to_front()

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------ 도구 막대·메뉴
    def _act(self, text, tip, keys, slot, add=True) -> QAction:
        a = QAction(text, self)
        a.setToolTip(tip)
        a.setShortcuts([QKeySequence(k) if isinstance(k, str) else k for k in keys])
        a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.triggered.connect(slot)
        if add:
            self.addAction(a)
        return a

    def _build_toolbar(self) -> None:
        tb = QToolBar("탐색", self)
        tb.setMovable(False)
        tb.setObjectName("nav")
        self.addToolBar(tb)
        Std = QKeySequence.StandardKey
        kb = QKeySequence.keyBindings
        self.act_back = self._act("◀", "뒤로", kb(Std.Back), self.back)
        self.act_forward = self._act("▶", "앞으로", kb(Std.Forward), self.forward)
        self.act_reload = self._act("⟳", "새로고침", ["Ctrl+R"] + kb(Std.Refresh), self.reload)
        self.act_open = self._act("열기", "파일 열기", kb(Std.Open), self.open_file)
        self.act_focus = self._act("주소", "주소 표시줄", ["Ctrl+L"], self._focus_address)
        for a in (self.act_back, self.act_forward, self.act_reload):
            tb.addAction(a)
        self.address = QLineEdit(self)
        self.address.setPlaceholderText("htex:// 주소, https 주소, 또는 파일 경로")
        self.address.setClearButtonEnabled(True)
        self.address.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.address.returnPressed.connect(lambda: self.navigate(self.address.text()))
        tb.addWidget(self.address)
        tb.addAction(self.act_open)

    def _build_menus(self) -> None:
        Std = QKeySequence.StandardKey
        kb = QKeySequence.keyBindings
        mb = self.menuBar()
        # 파일
        m = mb.addMenu("파일(&F)")
        m.addAction(self.act_open)
        self.act_new_tab = self._act("새 탭", "새 탭", ["Ctrl+T"], lambda: self.new_tab())
        self.act_close_tab = self._act("탭 닫기", "탭 닫기", ["Ctrl+W"], lambda: self.close_tab())
        self.act_next_tab = self._act("다음 탭", "다음 탭",
                                      ["Ctrl+Tab", "Ctrl+PgDown"] + kb(Std.NextChild),
                                      lambda: self.cycle_tab(1))
        self.act_prev_tab = self._act("이전 탭", "이전 탭",
                                      ["Ctrl+Shift+Tab", "Ctrl+Backtab", "Ctrl+PgUp"] + kb(Std.PreviousChild),
                                      lambda: self.cycle_tab(-1))
        for n in range(1, 10):
            self._act(f"탭 {n}", f"탭 {n}", [f"Ctrl+{n}"], lambda _=False, n=n: self.select_tab(n))
        m.addAction(self.act_new_tab)
        m.addAction(self.act_close_tab)
        m.addSeparator()
        m.addAction(self.act_next_tab)
        m.addAction(self.act_prev_tab)
        m.addSeparator()
        self.act_quit = self._act("끝내기", "끝내기", kb(Std.Quit) or ["Ctrl+Q"], self._quit)
        self.act_quit.setMenuRole(QAction.MenuRole.QuitRole)
        m.addAction(self.act_quit)
        # 편집
        m = mb.addMenu("편집(&E)")
        self.act_find = self._act("찾기…", "문서에서 찾기", kb(Std.Find) or ["Ctrl+F"],
                                  self.find_bar.open_bar)
        self.act_find_next = self._act("다음 찾기", "다음 찾기", ["F3"] + kb(Std.FindNext),
                                       lambda: self._find_step(True))
        self.act_find_prev = self._act("이전 찾기", "이전 찾기", ["Shift+F3"] + kb(Std.FindPrevious),
                                       lambda: self._find_step(False))
        m.addAction(self.act_find)
        m.addAction(self.act_find_next)
        m.addAction(self.act_find_prev)
        # 보기
        m = mb.addMenu("보기(&V)")
        self.act_zoom_in = self._act("확대", "확대", ["Ctrl+=", "Ctrl++"] + kb(Std.ZoomIn),
                                     lambda: self.zoom_step(1))
        self.act_zoom_out = self._act("축소", "축소", ["Ctrl+-"] + kb(Std.ZoomOut),
                                      lambda: self.zoom_step(-1))
        self.act_zoom_reset = self._act("원래 크기", "원래 크기", ["Ctrl+0"],
                                        lambda: self.set_zoom(1.0))
        m.addAction(self.act_zoom_in)
        m.addAction(self.act_zoom_out)
        m.addAction(self.act_zoom_reset)
        m.addSeparator()
        tm = m.addMenu("테마")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for key, label in THEMES:
            a = QAction(label, self, checkable=True)
            a.setChecked(key == self.theme)
            a.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            self.theme_group.addAction(a)
            tm.addAction(a)
            self.theme_actions[key] = a
        m.addSeparator()
        self.act_source = self._act("원본 보기", "현재 문서의 원문을 새 탭에", ["Ctrl+U"], self.view_source)
        m.addAction(self.act_source)
        # 이동
        m = mb.addMenu("이동(&G)")
        m.addAction(self.act_back)
        m.addAction(self.act_forward)
        m.addAction(self.act_reload)
        m.addSeparator()
        m.addAction(self.act_focus)

    def _quit(self) -> None:
        app = QApplication.instance()
        for w in app.topLevelWidgets() if app else []:
            if isinstance(w, ViewerWindow):
                w.close()
        if app:
            app.quit()

    def _find_step(self, forward: bool) -> None:
        if not self.find_bar.isVisible():
            self.find_bar.open_bar()
        else:
            self.find_bar.find(forward=forward)

    def _focus_address(self) -> None:
        self.address.setFocus()
        self.address.selectAll()

    def _update_actions(self) -> None:
        tab = self.current_tab()
        self.act_back.setEnabled(bool(tab and tab.history.can_back()))
        self.act_forward.setEnabled(bool(tab and tab.history.can_forward()))
        url = tab.current_url() if tab else ""
        self.act_source.setEnabled(url.startswith(("htex:", "htexapp://doc-")))

    # ------------------------------------------------------------ 확대·테마·원문
    def set_zoom(self, z: float) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.set_zoom(z)

    def zoom_step(self, direction: int) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        z = tab.zoom
        if direction > 0:
            nxt = next((s for s in ZOOM_STEPS if s > z + 1e-3), ZOOM_MAX)
        else:
            nxt = next((s for s in reversed(ZOOM_STEPS) if s < z - 1e-3), ZOOM_MIN)
        tab.set_zoom(nxt)

    def set_theme(self, theme: str) -> None:
        if theme not in dict(THEMES):
            theme = "system"
        self.theme = theme
        self.core.theme = "" if theme == "system" else theme
        try:
            settings().setValue("view/theme", theme)
        except Exception:   # noqa: BLE001
            pass
        a = self.theme_actions.get(theme)
        if a is not None and not a.isChecked():
            a.setChecked(True)
        for tab in self.tab_list():
            tab.apply_theme(theme)
            if tab.current_url().startswith("htexapp://source/"):
                tab.reload()
        self.apply_window_theme()

    def apply_window_theme(self) -> None:
        """창 테두리(Qt 위젯) 색. Qt 6.8+ 의 styleHints().setColorScheme. 없으면 그대로."""
        app = QApplication.instance()
        hints = app.styleHints() if app else None
        if hints is None or not hasattr(hints, "setColorScheme"):
            return
        try:
            if self.theme == "system":
                hints.unsetColorScheme()
            else:
                hints.setColorScheme(Qt.ColorScheme.Dark if self.theme == "dark" else Qt.ColorScheme.Light)
        except Exception:   # noqa: BLE001
            return
        # 플랫폼 스타일이 색 구성표를 따르지 않으면(리눅스 일부, offscreen) Fusion 팔레트로 맞춘다
        want = {"dark": Qt.ColorScheme.Dark, "light": Qt.ColorScheme.Light}.get(self.theme)
        global _palette_overridden
        if want is not None and hints.colorScheme() != want:
            app.setPalette(_dark_palette() if want == Qt.ColorScheme.Dark else app.style().standardPalette())
            _palette_overridden = True
        elif _palette_overridden:
            app.setPalette(app.style().standardPalette())
            _palette_overridden = False

    def view_source(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        url = self.core.source_url(tab.current_url())
        if url is None:
            self.statusBar().showMessage("원문을 볼 수 있는 HyperTeX 문서가 아닙니다.", 4000)
            return
        src = self.new_tab(focus_address=False)
        src.pinned_source = True
        src.navigate_url(QUrl(url))

    # ------------------------------------------------------------ 이동
    def navigate(self, text: str, tab: Optional[Tab] = None) -> None:
        tab = tab or self.current_tab()
        if tab is None:
            tab = self.new_tab()
        try:
            url = self.core.input_to_url(text, self.cwd)
        except ViewerError as e:
            self.statusBar().showMessage(e.message, 8000)
            return
        tab.navigate_url(QUrl(url))

    @Slot(QUrl)
    def navigate_url(self, url: QUrl) -> None:
        self.current_tab().navigate_url(url)

    def open_file(self) -> None:
        exts = " ".join("*" + e for e in DOC_EXTS)
        path, _ = QFileDialog.getOpenFileName(self, "HyperTeX 문서 열기", str(self.cwd),
                                              f"HyperTeX 문서 ({exts});;모든 파일 (*)")
        if path:
            tab = self.current_tab()
            if tab is not None and tab.is_blank():
                self.navigate(path, tab)
            else:
                self.new_tab(path)

    def back(self) -> None:
        if self.current_tab():
            self.current_tab().back()
        self._update_actions()

    def forward(self) -> None:
        if self.current_tab():
            self.current_tab().forward()
        self._update_actions()

    def reload(self) -> None:
        if self.current_tab():
            self.current_tab().reload()

    def current_url(self) -> str:
        tab = self.current_tab()
        return tab.current_url() if tab else ""

    # ------------------------------------------------------------ 신호
    def _on_current_changed(self, _index: int) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        url = tab.current_url()
        if url and url != "about:blank":
            self.address.setText(urllib.parse.unquote(self.core.display_address(url)))
        else:
            self.address.clear()
        self._set_title(tab.title() if url and url != "about:blank" else "")
        self.zoom_label.setText(f"{round(tab.zoom * 100)}%")
        self._show_diag(tab, True)
        self._update_actions()
        if self.find_bar.isVisible():
            self.find_bar.find(forward=True, incremental=True)

    def _set_title(self, title: str) -> None:
        self.setWindowTitle(f"{title} — {APP_NAME}" if title else APP_NAME)

    def _on_tab_title(self, tab: Tab, title: str) -> None:
        i = self.tabs.indexOf(tab)
        if i >= 0:
            shown = title or "새 탭"
            if tab.pinned_source and not shown.startswith("원문"):
                shown = "원문: " + shown
            self.tabs.setTabText(i, shown if len(shown) <= 28 else shown[:27] + "…")
            self.tabs.setTabToolTip(i, title)
        if tab is self.current_tab():
            self._set_title(title)

    def _on_tab_url(self, tab: Tab, url: str) -> None:
        if tab is self.current_tab():
            if not self.address.hasFocus():
                self.address.setText(urllib.parse.unquote(self.core.display_address(url)))
            self._update_actions()

    def _on_tab_zoom(self, tab: Tab, z: float) -> None:
        if tab is self.current_tab():
            self.zoom_label.setText(f"{round(z * 100)}%")
            self.statusBar().showMessage(f"확대 {round(z * 100)}%", 1500)

    def _on_tab_loaded(self, tab: Tab, ok: bool) -> None:
        if tab is self.current_tab():
            self._show_diag(tab, ok)
            self._update_actions()

    def _show_diag(self, tab: Tab, ok: bool) -> None:
        url = tab.current_url()
        rec = self.core.record_for(url) if url.startswith(("htex:", "htexapp://doc-")) else None
        if rec is not None:
            err, warn = rec.counts()
            mode = "호환 모드 · " if (rec.tree.get("source") or {}).get("mode") == "compat" else ""
            watching = " · 자동 새로고침" if tab.watched_files() else ""
            self.diag_label.setText(f"{mode}진단: 오류 {err} · 경고 {warn}{watching}")
            self.diag_label.setToolTip("\n".join(f'{d.get("severity")}: {d.get("message")}'
                                                 for d in rec.diagnostics[:30]))
            self.statusBar().showMessage(f"해석 {rec.elapsed * 1000:.0f}ms", 4000)
        elif url.startswith(("http:", "https:")):
            self.diag_label.setText("웹 페이지")
            self.diag_label.setToolTip("")
            self.statusBar().showMessage("" if ok else "페이지를 불러오지 못했습니다.", 4000)
        elif url.startswith("htexapp://source/"):
            self.diag_label.setText("원문 (읽기 전용)")
            self.diag_label.setToolTip("")
        else:
            self.diag_label.setText("")
            self.statusBar().clearMessage()

    def _on_hover(self, url: str) -> None:
        if url:
            self.statusBar().showMessage(urllib.parse.unquote(self.core.display_address(url)))
        else:
            self.statusBar().clearMessage()

    def closeEvent(self, ev) -> None:  # noqa: N802
        for tab in self.tab_list():
            tab.watcher.removePaths(tab.watcher.files() + tab.watcher.directories())
        super().closeEvent(ev)


_palette_overridden = False


def _dark_palette():
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    R, C = QPalette.ColorRole, QColor
    for role, col in ((R.Window, "#1f2023"), (R.WindowText, "#e6e6e3"), (R.Base, "#161618"),
                      (R.AlternateBase, "#26272b"), (R.ToolTipBase, "#26272b"), (R.ToolTipText, "#e6e6e3"),
                      (R.Text, "#e6e6e3"), (R.Button, "#2a2b2f"), (R.ButtonText, "#e6e6e3"),
                      (R.BrightText, "#ff8a7a"), (R.Highlight, "#3b6fd1"), (R.HighlightedText, "#ffffff"),
                      (R.Link, "#8ab4f8"), (R.PlaceholderText, "#8a8d93"), (R.Mid, "#3a3a3e"),
                      (R.Dark, "#121214"), (R.Light, "#3a3b40")):
        p.setColor(role, C(col))
    for role in (R.Text, R.ButtonText, R.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, C("#6b6e74"))
    return p


def _read_theme() -> str:
    try:
        v = settings().value("view/theme", "system")
    except Exception:   # noqa: BLE001
        v = "system"
    return v if v in dict(THEMES) else "system"


def _same(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


# ====================================================================== 단일 인스턴스
class InstanceServer(QObject):
    """먼저 뜬 뷰어가 듣는다. 두 번째 실행이 보낸 대상들을 received 로 알린다."""

    received = Signal(list)

    def __init__(self, name: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.name = name
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._on_connection)
        self._bufs: dict[int, bytes] = {}

    def listen(self) -> bool:
        if self.server.listen(self.name):
            return True
        # 앞선 실행이 비정상 종료해 남은 소켓 파일 (유닉스). 아무도 안 듣고 있으면 지우고 다시.
        QLocalServer.removeServer(self.name)
        return self.server.listen(self.name)

    def _on_connection(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            if sock is None:
                break
            key = id(sock)
            self._bufs[key] = b""
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(lambda s=sock: (self._bufs.pop(id(s), None), s.deleteLater()))
            QTimer.singleShot(5000, sock, sock.abort)     # 말없이 붙잡고 있는 연결은 끊는다
            if sock.bytesAvailable():
                self._on_ready(sock)

    def _on_ready(self, sock: QLocalSocket) -> None:
        key = id(sock)
        buf = self._bufs.get(key, b"") + bytes(sock.readAll().data())
        if len(buf) > (1 << 20):
            sock.abort()
            return
        self._bufs[key] = buf
        if b"\n" not in buf:
            return
        msg = decode_message(buf)
        sock.write(REPLY_OK)
        sock.flush()
        sock.disconnectFromServer()
        if msg is not None:
            self.received.emit(msg["targets"])

    def close(self) -> None:
        self.server.close()


def send_to_running(name: str, targets: list[str], timeout_ms: int = 1500) -> bool:
    """떠 있는 뷰어에 대상들을 넘긴다. 넘겼으면 True (그 뷰어가 받았다고 답함)."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False
    try:
        sock.write(encode_message(targets, os.getcwd()))
        sock.flush()
        if not sock.waitForBytesWritten(timeout_ms):
            return False
        reply = b""
        while REPLY_OK not in reply:
            if not sock.waitForReadyRead(timeout_ms):
                break
            reply += bytes(sock.readAll().data())
        return reply.startswith(REPLY_OK)
    finally:
        sock.abort()


# ====================================================================== macOS 파일 열기 이벤트
class FileOpenFilter(QObject):
    """QApplication 이벤트 필터. Finder 의 .htex 열기, htex:// 링크(CFBundleURLTypes) → opened(대상).
    창이 생기기 전에 온 것은 pending 에 모았다가 창이 생기면 넘긴다."""

    opened = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.pending: list[str] = []
        self.connected = False

    @staticmethod
    def target_of(ev) -> str:
        url = ev.url()
        if url.isValid() and url.scheme() and url.scheme().lower() != "file":
            return url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
        return ev.file() or (url.toLocalFile() if url.isValid() else "")

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.FileOpen:
            t = self.target_of(ev)
            if t:
                if self.connected:
                    self.opened.emit(t)
                else:
                    self.pending.append(t)
            return True
        return False


# ====================================================================== 실행
def run(targets: "list[str] | str | None" = None, argv: Optional[list[str]] = None, *,
        single_instance: Optional[bool] = None) -> int:
    """뷰어를 띄운다. targets = 파일 경로·file: URL·htex://·https:// 주소 여러 개 (str 하나도 받는다).

    단일 인스턴스: 같은 사용자의 뷰어가 이미 떠 있으면 대상을 그쪽으로 넘기고 바로 0 을 돌려준다.
    single_instance=None 이면 켠다(환경 변수 HTEX_VIEWER_SINGLE=0 이면 끈다)."""
    if isinstance(targets, str):
        targets = [targets]
    cwd = Path.cwd()
    norm = normalize_targets(targets or [], cwd)
    if single_instance is None:
        single_instance = os.environ.get("HTEX_VIEWER_SINGLE", "1") not in ("0", "false", "no")

    register_schemes()
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)

    file_filter = FileOpenFilter(app)
    app.installEventFilter(file_filter)

    server = None
    if single_instance:
        name = instance_name()
        if send_to_running(name, norm):
            return 0
        server = InstanceServer(name, app)
        if not server.listen():
            server = None        # 듣지 못해도 뷰어는 그냥 뜬다

    win = ViewerWindow(cwd=cwd)
    file_filter.opened.connect(lambda t: win.open_targets([t]))
    file_filter.connected = True
    if server is not None:
        server.received.connect(lambda ts: win.open_targets(ts))
    win.show()
    initial = norm + file_filter.pending
    file_filter.pending = []
    if initial:
        win.open_targets(initial, raise_window=False)
    try:
        return app.exec()
    finally:
        if server is not None:
            server.close()
        win.handler.shutdown()
