"""전용 뷰어 창 (PySide6 + QtWebEngine). (담당: F)

- 일반 웹(http/https)은 QtWebEngine 이 그대로 보여 준다.
- htex:// 문서, .htex/.tex 로 끝나는 https 링크, 로컬 .htex/.tex 파일은 core.ViewerCore 가 해석해 응답한다.
- 사용자 정의 스킴 htex, htexapp 은 QApplication 을 만들기 전에 register_schemes() 로 등록해야 한다
  (run() 이 알아서 한다. 다른 곳에서 창을 띄우면 먼저 register_schemes() 를 부를 것).
"""
from __future__ import annotations

import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QBuffer, QByteArray, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
                                     QWebEngineUrlRequestJob, QWebEngineUrlScheme,
                                     QWebEngineUrlSchemeHandler)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QLineEdit, QMainWindow,
                               QToolBar, QWidget, QSizePolicy)

from .. import __version__
from .core import (DOC_EXTS, History, Response, TreeCache, ViewerCore, ViewerError,
                   default_cache_dir, https_to_htex, is_doc_path, split_fragment)

SCHEMES = (b"htex", b"htexapp")
APP_NAME = "HyperTeX"

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
    """https 의 .htex/.tex 링크를 htex:// 로 돌리고, 웹 페이지에서 내부 스킴으로 가는 것을 막는다."""

    redirected = Signal(QUrl)

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

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if getattr(self, "console_log", None) is not None:
            self.console_log.append((int(level.value) if hasattr(level, "value") else int(level),
                                     message, line, source))


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
        self.history = History()
        self._history_nav: Optional[str] = None
        self._last_record = None

        self.profile = profile = profile or shared_profile()
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
        self.handler.loaded.connect(self._on_record)

        self.view = QWebEngineView(self)
        self.page = HtexPage(profile, self.view)
        self.page.console_log = []
        # 탐색 판정 중에 다시 탐색하면 엔진이 멈출 수 있어 한 박자 미룬다
        self.page.redirected.connect(self.navigate_url, Qt.ConnectionType.QueuedConnection)
        s = self.page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.view.setPage(self.page)
        self.setCentralWidget(self.view)

        self._build_toolbar()
        self.diag_label = QLabel("")
        self.statusBar().addPermanentWidget(self.diag_label)

        self.view.urlChanged.connect(self._on_url_changed)
        self.view.titleChanged.connect(self._on_title)
        self.view.loadStarted.connect(lambda: self.statusBar().showMessage("불러오는 중…"))
        self.view.loadFinished.connect(self._on_load_finished)
        self.page.linkHovered.connect(self._on_hover)
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 820)

    # ------------------------------------------------------------ 도구 막대
    def _build_toolbar(self) -> None:
        tb = QToolBar("탐색", self)
        tb.setMovable(False)
        tb.setObjectName("nav")
        self.addToolBar(tb)

        def act(text, tip, keys, slot):
            a = QAction(text, self)
            a.setToolTip(tip)
            a.setShortcuts(keys)
            a.triggered.connect(slot)
            self.addAction(a)
            return a

        Std = QKeySequence.StandardKey
        self.act_back = act("◀", "뒤로", QKeySequence.keyBindings(Std.Back), self.back)
        self.act_forward = act("▶", "앞으로", QKeySequence.keyBindings(Std.Forward), self.forward)
        self.act_reload = act("⟳", "새로고침", [QKeySequence("Ctrl+R")]
                              + QKeySequence.keyBindings(Std.Refresh), self.reload)
        self.act_open = act("열기", "파일 열기", QKeySequence.keyBindings(Std.Open), self.open_file)
        self.act_focus = act("주소", "주소 표시줄", [QKeySequence("Ctrl+L")], self._focus_address)
        for a in (self.act_back, self.act_forward, self.act_reload):
            tb.addAction(a)
        self.address = QLineEdit(self)
        self.address.setPlaceholderText("htex:// 주소, https 주소, 또는 파일 경로")
        self.address.setClearButtonEnabled(True)
        self.address.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.address.returnPressed.connect(lambda: self.navigate(self.address.text()))
        tb.addWidget(self.address)
        tb.addAction(self.act_open)
        self._update_actions()

    def _focus_address(self) -> None:
        self.address.setFocus()
        self.address.selectAll()

    def _update_actions(self) -> None:
        self.act_back.setEnabled(self.history.can_back())
        self.act_forward.setEnabled(self.history.can_forward())

    # ------------------------------------------------------------ 이동
    def navigate(self, text: str) -> None:
        try:
            url = self.core.input_to_url(text, self.cwd)
        except ViewerError as e:
            self.statusBar().showMessage(e.message, 8000)
            return
        self.navigate_url(QUrl(url))

    @Slot(QUrl)
    def navigate_url(self, url: QUrl) -> None:
        self.view.setUrl(url)
        self.view.setFocus()

    def open_file(self) -> None:
        exts = " ".join("*" + e for e in DOC_EXTS)
        path, _ = QFileDialog.getOpenFileName(self, "HyperTeX 문서 열기", str(self.cwd),
                                              f"HyperTeX 문서 ({exts});;모든 파일 (*)")
        if path:
            self.navigate(path)

    def _go_history(self, entry) -> None:
        if entry is None:
            return
        self._history_nav = entry.url
        self.view.setUrl(QUrl(entry.url))
        self._update_actions()

    def back(self) -> None:
        self._go_history(self.history.back())

    def forward(self) -> None:
        self._go_history(self.history.forward())

    def reload(self) -> None:
        url = self.current_url()
        base = split_fragment(url)[0]
        if url.startswith(("htex:", "htexapp://doc-")):
            self.core.invalidate(base)
            self.handler.reload_next.add(base)
        self.view.triggerPageAction(QWebEnginePage.WebAction.ReloadAndBypassCache)

    def current_url(self) -> str:
        return self.view.url().toString(QUrl.ComponentFormattingOption.FullyEncoded)

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
        if not self.address.hasFocus():
            self.address.setText(urllib.parse.unquote(self.core.display_address(url)))
        self._update_actions()

    def _on_title(self, title: str) -> None:
        self.history.set_title(title)
        self.setWindowTitle(f"{title} — {APP_NAME}" if title else APP_NAME)

    @Slot(object)
    def _on_record(self, rec) -> None:
        self._last_record = rec

    def _on_load_finished(self, ok: bool) -> None:
        url = self.current_url()
        rec = self.core.record_for(url) if url.startswith(("htex:", "htexapp:")) else None
        if rec is not None:
            err, warn = rec.counts()
            mode = "호환 모드 · " if (rec.tree.get("source") or {}).get("mode") == "compat" else ""
            self.diag_label.setText(f"{mode}진단: 오류 {err} · 경고 {warn}")
            self.diag_label.setToolTip("\n".join(f'{d.get("severity")}: {d.get("message")}'
                                                 for d in rec.diagnostics[:30]))
            self.statusBar().showMessage(f"해석 {rec.elapsed * 1000:.0f}ms", 4000)
        elif url.startswith(("http:", "https:")):
            self.diag_label.setText("웹 페이지")
            self.diag_label.setToolTip("")
            self.statusBar().showMessage("" if ok else "페이지를 불러오지 못했습니다.", 4000)
        else:
            self.diag_label.setText("")
            self.statusBar().clearMessage()

    def _on_hover(self, url: str) -> None:
        if url:
            self.statusBar().showMessage(urllib.parse.unquote(self.core.display_address(url)))
        else:
            self.statusBar().clearMessage()



def _same(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


# ====================================================================== 실행
def run(target: Optional[str] = None, argv: Optional[list[str]] = None) -> int:
    register_schemes()
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    win = ViewerWindow()
    win.show()
    if target:
        win.navigate(target)
    else:
        win._focus_address()
    try:
        return app.exec()
    finally:
        win.handler.shutdown()
