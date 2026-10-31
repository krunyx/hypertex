"""Chrome 모양의 창 부품 (PySide6). (담당: L)

창은 위에서부터 네 줄이다 (Google Chrome 과 같은 순서).

    ┌ 탭 줄 ────────────────────────────────────────────┐  TabStrip: 둥근 탭(아이콘·제목·×) + 새 탭 단추
    ├ 도구줄 ── ← → ⟳ ⌂ (ⓘ 주소 … 150% ☆) ⋮ ──────────┤  NavBar · Omnibox
    ├ 북마크바 ── 북마크 · 폴더 ▾ · » ─────────────────┤  BookmarksBar
    └ 페이지 (탭마다 웹 뷰) + 링크 말풍선, 찾기 상자 ─┘  PageArea · StatusBubble

- 아이콘은 Material Icons (Apache-2.0) 의 SVG 경로를 그대로 써서 테마 색으로 그린다.
- 색은 Chrome 의 밝은·어두운 구성을 따른다 (Palette). 창 테마(시스템·밝게·어둡게)를 바꾸면 다시 칠한다.
- TabStack 은 QTabWidget 과 같은 이름의 메서드를 갖는다 (뷰어 코드·테스트가 쓰는 count, widget, indexOf …).
  탭 막대는 페이지 위가 아니라 창 맨 위 줄에 따로 놓이므로 QTabWidget 대신 막대 + QStackedWidget 으로 만든다.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QByteArray, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QPushButton, QSizePolicy, QStackedWidget, QTabBar, QToolButton,
                               QVBoxLayout, QWidget)

# ====================================================================== 색
@dataclass(frozen=True)
class Palette:
    dark: bool
    frame: str        # 탭 줄 바탕
    toolbar: str      # 선택된 탭·도구줄·북마크바 바탕
    omnibox: str      # 주소창 바탕
    omnibox_hover: str
    fg: str           # 글자
    muted: str        # 흐린 글자·선택 안 된 탭 글자
    icon: str         # 아이콘
    accent: str       # 초점 테두리·진행 표시
    hover: str        # 단추·탭 위에 올렸을 때
    pressed: str
    separator: str
    border: str       # 도구줄 아래 선
    bubble: str       # 링크 말풍선 바탕
    popup: str        # 떠 있는 상자 바탕
    danger: str


LIGHT = Palette(False, frame="#dee1e6", toolbar="#ffffff", omnibox="#f1f3f4", omnibox_hover="#e8eaed",
                fg="#202124", muted="#5f6368", icon="#5f6368", accent="#1a73e8",
                hover="rgba(60,64,67,0.10)", pressed="rgba(60,64,67,0.18)", separator="#a8abaf",
                border="#dadce0", bubble="#f1f3f4", popup="#ffffff", danger="#d93025")
DARK = Palette(True, frame="#202124", toolbar="#35363a", omnibox="#202124", omnibox_hover="#292a2d",
               fg="#e8eaed", muted="#9aa0a6", icon="#c4c7c5", accent="#8ab4f8",
               hover="rgba(232,234,237,0.10)", pressed="rgba(232,234,237,0.18)", separator="#5f6368",
               border="#3c4043", bubble="#2b2c2f", popup="#2b2c2f", danger="#f28b82")


def qcolor(css: str) -> QColor:
    if css.startswith("rgba("):
        r, g, b, a = (x.strip() for x in css[5:-1].split(","))
        c = QColor(int(r), int(g), int(b))
        c.setAlphaF(float(a))
        return c
    return QColor(css)


# ====================================================================== 아이콘 (Material Icons, Apache-2.0)
ICON_PATHS = {
    "back": "M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z",
    "forward": "M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z",
    "reload": ("M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 "
               "6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 "
               "3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"),
    "close": ("M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 "
              "19 17.59 13.41 12z"),
    "home": "M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z",
    "add": "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
    "remove": "M19 13H5v-2h14v2z",
    "more": ("M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 "
             "2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"),
    "star": ("M22 9.24l-7.19-.62L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.63-7.03L22 "
             "9.24zM12 15.4l-3.76 2.27 1-4.28-3.32-2.88 4.38-.38L12 6.1l1.71 4.04 4.38.38-3.32 2.88 1 "
             "4.28L12 15.4z"),
    "star_filled": ("M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 "
                    "4.73L5.82 21z"),
    "folder": ("M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"),
    "doc": ("M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0"
            "-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"),
    "globe": ("M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85"
              "-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1"
              "v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 "
              "2.08-.8 3.97-2.1 5.39z"),
    "lock": ("M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2"
             "V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 "
             "1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"),
    "info": ("M11 7h2v2h-2zm0 4h2v6h-2zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 "
             "18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z"),
    "warning": "M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z",
    "search": ("M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 "
               "16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 "
               "11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"),
    "up": "M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6z",
    "down": "M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z",
    "chevrons": ("M5.59 7.41L10.18 12l-4.59 4.59L7 18l6-6-6-6zM12 6l-1.41 1.41L15.17 12l-4.58 4.59L12 18l"
                 "6-6z"),
}

_icon_cache: dict[tuple, QIcon] = {}


def svg_icon(name: str, color: str, size: int = 20) -> QIcon:
    """Material 아이콘 하나를 color 로 칠한 QIcon (고해상도 화면용 2배 그림 포함)."""
    key = (name, color, size)
    hit = _icon_cache.get(key)
    if hit is not None:
        return hit
    fill = qcolor(color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
           f'<path fill="{fill.name()}" fill-opacity="{fill.alphaF():.3f}" d="{ICON_PATHS[name]}"/></svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    icon = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    _icon_cache[key] = icon
    return icon


# ====================================================================== 스타일시트
def stylesheet(c: Palette) -> str:
    """창 테두리 부품 전체의 QSS. 페이지(웹 뷰) 안은 건드리지 않는다."""
    return f"""
#tabstrip {{ background: {c.frame}; }}
#navbar, #bookmarks {{ background: {c.toolbar}; }}
#bookmarks {{ border-bottom: 1px solid {c.border}; }}
#navbar QToolButton, #bookmarks QToolButton, #tabstrip QToolButton#newtab {{
  border: none; border-radius: 16px; padding: 0; background: transparent; color: {c.fg}; }}
#navbar QToolButton:hover, #tabstrip QToolButton#newtab:hover {{ background: {c.hover}; }}
#navbar QToolButton:pressed, #tabstrip QToolButton#newtab:pressed {{ background: {c.pressed}; }}
#navbar QToolButton:disabled {{ background: transparent; }}
#navbar QToolButton::menu-indicator {{ image: none; width: 0; }}
#bookmarks QToolButton {{ border-radius: 14px; padding: 0 8px; font-size: 12px; }}
#bookmarks QToolButton:hover {{ background: {c.hover}; }}
#bookmarks QToolButton:pressed, #bookmarks QToolButton:checked {{ background: {c.pressed}; }}
#bookmarks QToolButton::menu-indicator {{ image: none; width: 0; }}
#bookmarks QLabel#bmhint {{ color: {c.muted}; font-size: 12px; padding-left: 6px; }}
#omnibox {{ background: {c.omnibox}; border: 2px solid transparent; border-radius: 18px; }}
#omnibox:hover {{ background: {c.omnibox_hover}; }}
#omnibox[focused="true"] {{ background: {c.toolbar}; border-color: {c.accent}; }}
#omnibox QLineEdit {{ background: transparent; border: none; color: {c.fg}; font-size: 14px;
  selection-background-color: {c.accent}; selection-color: {"#202124" if c.dark else "#ffffff"};
  padding: 0 2px; }}
#omnibox QToolButton {{ border: none; border-radius: 13px; background: transparent; color: {c.fg};
  padding: 0 6px; font-size: 12px; }}
#omnibox QToolButton:hover {{ background: {c.hover}; }}
#omnibox QToolButton#pageinfo[warn="true"] {{ color: {c.danger}; }}
#statusbubble {{ background: {c.bubble}; color: {c.fg}; border: 1px solid {c.border};
  border-top-right-radius: 6px; padding: 2px 8px; font-size: 12px; }}
#findbar, #popup {{ background: {c.popup}; color: {c.fg}; border: 1px solid {c.border}; border-radius: 8px; }}
#findbar QLineEdit, #popup QLineEdit {{ background: {c.omnibox}; color: {c.fg};
  border: 1px solid {c.border}; border-radius: 4px; padding: 4px 6px; }}
#findbar QLineEdit:focus, #popup QLineEdit:focus {{ border-color: {c.accent}; }}
#findbar QToolButton {{ border: none; border-radius: 14px; background: transparent; color: {c.fg}; }}
#findbar QToolButton:hover {{ background: {c.hover}; }}
#findbar QLabel, #popup QLabel {{ color: {c.fg}; background: transparent; }}
#popup QLabel[muted="true"] {{ color: {c.muted}; }}
#popup QLabel#popuptitle {{ font-size: 15px; font-weight: 500; }}
#popup QPushButton {{ border: 1px solid {c.border}; border-radius: 16px; padding: 6px 16px;
  background: transparent; color: {c.accent}; }}
#popup QPushButton:default {{ background: {c.accent}; color: {"#202124" if c.dark else "#ffffff"};
  border-color: {c.accent}; }}
#popup QPushButton:hover {{ background: {c.hover}; }}
#popup QPushButton:default:hover {{ background: {c.accent}; }}
#zoomrow QToolButton {{ border: 1px solid {c.border}; border-radius: 4px; min-width: 28px;
  min-height: 24px; background: transparent; color: {c.fg}; }}
#zoomrow QToolButton:hover {{ background: {c.hover}; }}
#zoomrow QLabel {{ color: {c.fg}; }}
"""


# ====================================================================== 탭 막대
TAB_MAX_W, TAB_MIN_W, TAB_PINNED_W = 240, 56, 48
TAB_H = 36            # 탭 줄 위 여백 6 + 탭 30
TAB_TOP = 6


class ChromeTabBar(QTabBar):
    """Chrome 처럼 그리는 탭 막대: 둥근 위 모서리와 아래 곡선, 아이콘 + 왼쪽 정렬 제목 + ×, 사이 구분선."""

    context_requested = Signal(int, QPoint)        # 탭 번호(-1: 빈 곳), 화면 좌표
    new_tab_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.palette_: Palette = LIGHT
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.hovered = -1
        self.available_width: Callable[[], int] = lambda: 1000
        self._spin = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(40)
        self._spin_timer.timeout.connect(self._tick)
        f = QFont(self.font())
        f.setPointSizeF(max(8.0, f.pointSizeF() * 0.95))
        self.setFont(f)

    # ------------------------------------------------------------ 크기
    def tabSizeHint(self, index: int) -> QSize:   # noqa: N802
        n = max(1, self.count())
        w = int(max(TAB_MIN_W, min(TAB_MAX_W, self.available_width() / n)))
        return QSize(w, TAB_H)

    def minimumTabSizeHint(self, index: int) -> QSize:   # noqa: N802
        return QSize(TAB_MIN_W, TAB_H)

    def relayout(self) -> None:
        """폭이 바뀌면 탭 폭을 다시 정한다 (QTabBar 는 크기 변화만으로는 탭 폭을 다시 묻지 않는다)."""
        self.setIconSize(self.iconSize())
        self.updateGeometry()
        self.update()

    # ------------------------------------------------------------ 탭별 상태 (tabData)
    def _state(self, i: int) -> dict:
        d = self.tabData(i)
        return d if isinstance(d, dict) else {}

    def set_loading(self, i: int, loading: bool) -> None:
        st = dict(self._state(i))
        st["loading"] = loading
        self.setTabData(i, st)
        if any(self._state(k).get("loading") for k in range(self.count())):
            if not self._spin_timer.isActive():
                self._spin_timer.start()
        else:
            self._spin_timer.stop()
        self.update()

    def _tick(self) -> None:
        self._spin = (self._spin + 24) % 360
        self.update()

    # ------------------------------------------------------------ 닫기 단추
    def tabInserted(self, index: int) -> None:   # noqa: N802
        super().tabInserted(index)
        btn = QToolButton(self)
        btn.setObjectName("tabclose")
        btn.setAutoRaise(True)
        btn.setFixedSize(20, 20)
        btn.setIconSize(QSize(14, 14))
        btn.setIcon(svg_icon("close", self.palette_.icon, 16))
        btn.setToolTip("탭 닫기 (Ctrl+W)")
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(f"QToolButton{{border:none;border-radius:10px;background:transparent}}"
                          f"QToolButton:hover{{background:{self.palette_.hover}}}")
        btn.clicked.connect(lambda _=False, b=btn: self._close_from(b))
        self.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)
        self.setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)
        self.relayout()

    def tabRemoved(self, index: int) -> None:   # noqa: N802
        super().tabRemoved(index)
        self.hovered = -1
        self.relayout()

    def _close_from(self, btn: QToolButton) -> None:
        for i in range(self.count()):
            if self.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self.tabCloseRequested.emit(i)
                return

    def set_palette(self, c: Palette) -> None:
        self.palette_ = c
        for i in range(self.count()):
            b = self.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if isinstance(b, QToolButton):
                b.setIcon(svg_icon("close", c.icon, 16))
                b.setStyleSheet(f"QToolButton{{border:none;border-radius:10px;background:transparent}}"
                                f"QToolButton:hover{{background:{c.hover}}}")
        self.update()

    # ------------------------------------------------------------ 마우스
    def mouseMoveEvent(self, e) -> None:   # noqa: N802
        h = self.tabAt(e.position().toPoint())
        if h != self.hovered:
            self.hovered = h
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e) -> None:   # noqa: N802
        self.hovered = -1
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e) -> None:   # noqa: N802
        if e.button() == Qt.MouseButton.MiddleButton:       # 가운데 클릭 = 탭 닫기 (Chrome)
            i = self.tabAt(e.position().toPoint())
            if i >= 0:
                self.tabCloseRequested.emit(i)
                return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:   # noqa: N802
        if self.tabAt(e.position().toPoint()) < 0:
            self.new_tab_requested.emit()
            return
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e) -> None:   # noqa: N802
        self.context_requested.emit(self.tabAt(e.pos()), e.globalPos())

    # ------------------------------------------------------------ 그리기
    def _shape(self, r: QRect, flare: bool) -> QPainterPath:
        """선택된 탭: 위는 둥글게, 아래는 바깥으로 휘어 도구줄과 이어진다."""
        rad = 8.0
        top, bottom = float(r.top() + TAB_TOP), float(r.bottom() + 1)
        left, right = float(r.left()), float(r.right() + 1)
        path = QPainterPath()
        if flare:
            path.moveTo(left - rad, bottom)
            path.quadTo(left, bottom, left, bottom - rad)
        else:
            path.moveTo(left, bottom)
        path.lineTo(left, top + rad)
        path.quadTo(left, top, left + rad, top)
        path.lineTo(right - rad, top)
        path.quadTo(right, top, right, top + rad)
        if flare:
            path.lineTo(right, bottom - rad)
            path.quadTo(right, bottom, right + rad, bottom)
        else:
            path.lineTo(right, bottom)
        path.closeSubpath()
        return path

    def paintEvent(self, e) -> None:   # noqa: N802
        c = self.palette_
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cur = self.currentIndex()
        n = self.count()
        # 구분선: 선택·마우스 올린 탭의 양옆은 그리지 않는다
        p.setPen(QPen(qcolor(c.separator), 1))
        for i in range(n - 1):
            if i in (cur, self.hovered) or i + 1 in (cur, self.hovered):
                continue
            r = self.tabRect(i)
            x = r.right() + 0.5
            mid = r.top() + TAB_TOP + (r.height() - TAB_TOP) / 2
            p.drawLine(QPointF(x, mid - 9), QPointF(x, mid + 9))
        order = [i for i in range(n) if i != cur] + ([cur] if cur >= 0 else [])
        for i in order:
            r = self.tabRect(i)
            if i == cur:
                p.fillPath(self._shape(r, flare=True), qcolor(c.toolbar))
            elif i == self.hovered:
                hr = QRect(r.left() + 2, r.top() + TAB_TOP + 2, r.width() - 4, r.height() - TAB_TOP - 6)
                path = QPainterPath()
                path.addRoundedRect(QRectF(hr), 8, 8)
                p.fillPath(path, qcolor(c.hover))
            self._paint_label(p, i, r, i == cur)
        p.end()

    def _paint_label(self, p: QPainter, i: int, r: QRect, selected: bool) -> None:
        c = self.palette_
        body = QRect(r.left(), r.top() + TAB_TOP, r.width(), r.height() - TAB_TOP)
        x = body.left() + 12
        cy = body.center().y() + 1
        btn = self.tabButton(i, QTabBar.ButtonPosition.RightSide)
        narrow = r.width() < 88
        if btn is not None:
            btn.setVisible(selected or not narrow)
        right = (btn.geometry().left() - 6) if (btn is not None and btn.isVisible()) else body.right() - 8
        st = self._state(i)
        if st.get("loading"):
            pen = QPen(qcolor(c.accent), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(x + 1, cy - 7, 14, 14), int(-self._spin * 16), int(270 * 16))
        else:
            icon = self.tabIcon(i)
            if not icon.isNull():
                icon.paint(p, QRect(x, cy - 8, 16, 16))
        if narrow and not selected:
            return
        tx = x + 16 + 8
        fm = QFontMetrics(self.font())
        text = fm.elidedText(self.tabText(i), Qt.TextElideMode.ElideRight, max(0, right - tx))
        p.setPen(qcolor(c.fg if selected else c.muted))
        p.setFont(self.font())
        p.drawText(QRect(tx, body.top(), max(0, right - tx), body.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)


class TabStrip(QWidget):
    """탭 줄 한 줄: [탭들][+]. 탭이 많으면 줄어들고, 최소 폭 아래로는 스크롤 단추가 생긴다."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("tabstrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TAB_H + 4)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 0)
        lay.setSpacing(4)
        self.bar = ChromeTabBar(self)
        self.bar.available_width = lambda: max(TAB_MIN_W, self.width() - 16 - 4 - 36 - 8)
        self.new_btn = QToolButton(self)
        self.new_btn.setObjectName("newtab")
        self.new_btn.setFixedSize(30, 30)
        self.new_btn.setIconSize(QSize(18, 18))
        self.new_btn.setToolTip("새 탭 (Ctrl+T)")
        self.new_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addWidget(self.new_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)

    def resizeEvent(self, e) -> None:   # noqa: N802
        super().resizeEvent(e)
        self.bar.relayout()

    def set_palette(self, c: Palette) -> None:
        self.bar.set_palette(c)
        self.new_btn.setIcon(svg_icon("add", c.icon))


class TabStack(QWidget):
    """탭 막대(따로 놓인 ChromeTabBar)와 페이지 더미(QStackedWidget)를 묶은 것. QTabWidget 과 같은 이름을 쓴다."""

    currentChanged = Signal(int)
    tabCloseRequested = Signal(int)

    def __init__(self, bar: ChromeTabBar, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.bar = bar
        self.stack = QStackedWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        bar.currentChanged.connect(self._on_bar_current)
        bar.tabCloseRequested.connect(self.tabCloseRequested)
        bar.tabMoved.connect(self._on_moved)

    def _on_bar_current(self, i: int) -> None:
        if 0 <= i < self.stack.count():
            self.stack.setCurrentIndex(i)
        self.currentChanged.emit(i)

    def _on_moved(self, frm: int, to: int) -> None:
        w = self.stack.widget(frm)
        if w is None:
            return
        self.stack.removeWidget(w)
        self.stack.insertWidget(to, w)
        self.stack.setCurrentIndex(self.bar.currentIndex())

    # ---- QTabWidget 과 같은 이름
    def tabBar(self) -> ChromeTabBar:   # noqa: N802
        return self.bar

    def count(self) -> int:
        return self.bar.count()

    def currentIndex(self) -> int:   # noqa: N802
        return self.bar.currentIndex()

    def setCurrentIndex(self, i: int) -> None:   # noqa: N802
        self.bar.setCurrentIndex(i)

    def widget(self, i: int) -> Optional[QWidget]:
        return self.stack.widget(i) if 0 <= i < self.stack.count() else None

    def currentWidget(self) -> Optional[QWidget]:   # noqa: N802
        return self.widget(self.bar.currentIndex())

    def setCurrentWidget(self, w: QWidget) -> None:   # noqa: N802
        i = self.indexOf(w)
        if i >= 0:
            self.setCurrentIndex(i)

    def indexOf(self, w: QWidget) -> int:   # noqa: N802
        return self.stack.indexOf(w)

    def insertTab(self, i: int, w: QWidget, text: str) -> int:   # noqa: N802
        i = max(0, min(i, self.stack.count()))
        self.stack.insertWidget(i, w)
        return self.bar.insertTab(i, text)

    def addTab(self, w: QWidget, text: str) -> int:   # noqa: N802
        return self.insertTab(self.count(), w, text)

    def removeTab(self, i: int) -> None:   # noqa: N802
        w = self.widget(i)
        if w is None:
            return
        self.stack.removeWidget(w)        # 먼저 더미에서 빼야 막대의 currentChanged 때 번호가 맞는다
        self.bar.removeTab(i)
        self.stack.setCurrentIndex(self.bar.currentIndex())

    def tabText(self, i: int) -> str:   # noqa: N802
        return self.bar.tabText(i)

    def setTabText(self, i: int, text: str) -> None:   # noqa: N802
        self.bar.setTabText(i, text)

    def setTabToolTip(self, i: int, tip: str) -> None:   # noqa: N802
        self.bar.setTabToolTip(i, tip)

    def setTabIcon(self, i: int, icon: QIcon) -> None:   # noqa: N802
        self.bar.setTabIcon(i, icon)


# ====================================================================== 도구줄·주소창
def nav_button(parent: QWidget, size: int = 32) -> QToolButton:
    b = QToolButton(parent)
    b.setFixedSize(size, size)
    b.setIconSize(QSize(20, 20))
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    return b


class AddressEdit(QLineEdit):
    """주소 입력: 마우스로 처음 누르면 전체 선택 (Chrome), Esc 는 원래 주소로 되돌리기."""

    escaped = Signal()
    focus_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._select_on_release = False

    def focusInEvent(self, e) -> None:   # noqa: N802
        super().focusInEvent(e)
        if e.reason() == Qt.FocusReason.MouseFocusReason:
            self._select_on_release = True
        self.focus_changed.emit(True)

    def focusOutEvent(self, e) -> None:   # noqa: N802
        super().focusOutEvent(e)
        self.deselect()
        self.setCursorPosition(0)
        self.focus_changed.emit(False)

    def mouseReleaseEvent(self, e) -> None:   # noqa: N802
        super().mouseReleaseEvent(e)
        if self._select_on_release and not self.hasSelectedText():
            self.selectAll()
        self._select_on_release = False

    def keyPressEvent(self, e) -> None:   # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.escaped.emit()
            return
        super().keyPressEvent(e)


class Omnibox(QFrame):
    """알약 모양 주소창: [페이지 정보][주소 입력][확대 배율][☆]."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("omnibox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 6, 0)
        lay.setSpacing(2)
        self.info = QToolButton(self)
        self.info.setObjectName("pageinfo")
        self.info.setFixedHeight(26)
        self.info.setMinimumWidth(26)
        self.info.setIconSize(QSize(16, 16))
        self.info.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.info.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.info.setToolTip("페이지 정보")
        self.edit = AddressEdit(self)
        self.edit.setPlaceholderText("htex:// 주소, https 주소 또는 파일 경로 입력")
        self.edit.setFrame(False)
        self.zoom = QToolButton(self)
        self.zoom.setObjectName("zoomchip")
        self.zoom.setFixedHeight(26)
        self.zoom.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom.setToolTip("확대 배율 · 누르면 원래 크기 (Ctrl+0)")
        self.zoom.setText("100%")
        self.zoom.hide()
        self.star = QToolButton(self)
        self.star.setObjectName("star")
        self.star.setFixedSize(28, 26)
        self.star.setIconSize(QSize(18, 18))
        self.star.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.star.setToolTip("이 탭을 북마크에 추가 (Ctrl+D)")
        lay.addWidget(self.info)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.zoom)
        lay.addWidget(self.star)
        self.edit.focus_changed.connect(self._on_focus)
        self.palette_ = LIGHT
        self.starred = False

    def _on_focus(self, on: bool) -> None:
        self.setProperty("focused", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_starred(self, on: bool) -> None:
        self.starred = on
        c = self.palette_
        self.star.setIcon(svg_icon("star_filled", c.accent) if on else svg_icon("star", c.icon))
        self.star.setToolTip("이 탭의 북마크 수정 (Ctrl+D)" if on else "이 탭을 북마크에 추가 (Ctrl+D)")

    def set_info(self, kind: str, text: str = "", warn: bool = False) -> None:
        """kind: doc | web | secure | start | source | error."""
        c = self.palette_
        name = {"doc": "doc", "web": "globe", "secure": "lock", "start": "search", "source": "doc",
                "error": "warning"}.get(kind, "info")
        self.info.setIcon(svg_icon(name, c.danger if warn else c.icon, 16))
        self.info.setText(text)
        self.info.setProperty("warn", "true" if warn else "false")
        self.info.style().unpolish(self.info)
        self.info.style().polish(self.info)
        self.info.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text
                                     else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.info_kind = kind

    def set_palette(self, c: Palette) -> None:
        self.palette_ = c
        self.set_starred(self.starred)
        self.set_info(getattr(self, "info_kind", "start"), self.info.text(),
                      self.info.property("warn") == "true")


class NavBar(QWidget):
    """← → ⟳ ⌂ [주소창] ⋮"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("navbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(46)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(4)
        self.back = nav_button(self)
        self.forward = nav_button(self)
        self.reload = nav_button(self)
        self.home = nav_button(self)
        self.omnibox = Omnibox(self)
        self.menu = nav_button(self)
        self.menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu.setToolTip("HyperTeX 설정 및 기타")
        for w in (self.back, self.forward, self.reload, self.home):
            lay.addWidget(w)
        lay.addSpacing(4)
        lay.addWidget(self.omnibox, 1)
        lay.addSpacing(4)
        lay.addWidget(self.menu)


# ====================================================================== 북마크바
class BookmarksBar(QWidget):
    """북마크바: 북마크·폴더 단추가 왼쪽부터, 넘치면 » 메뉴로. 우클릭으로 고치기."""

    open_requested = Signal(str, bool)          # 주소, 새 탭인가
    edit_requested = Signal(object)             # Bookmark
    remove_requested = Signal(object)
    add_page_requested = Signal()
    add_folder_requested = Signal()
    toggle_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("bookmarks")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(34)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 2, 8, 3)
        self.lay.setSpacing(0)
        self.buttons: list[QToolButton] = []
        self.items: list = []
        self.hint = QLabel("빠르게 이동하려면 북마크를 여기 북마크바에 추가하세요. (Ctrl+D)", self)
        self.hint.setObjectName("bmhint")
        self.more = QToolButton(self)
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more.setFixedSize(28, 28)
        self.more.setToolTip("다른 북마크")
        self.more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more.hide()
        self.palette_ = LIGHT
        self.doc_icon: Optional[QIcon] = None
        self.favicon_for: Callable[[str], Optional[QIcon]] = lambda url: None

    def set_items(self, items: list) -> None:
        for b in self.buttons:
            b.deleteLater()
        self.buttons = []
        self.items = list(items)
        while self.lay.count():
            self.lay.takeAt(0)
        for it in self.items:
            self.buttons.append(self._button(it))
            self.lay.addWidget(self.buttons[-1])
        self.lay.addWidget(self.hint)
        self.hint.setVisible(not self.items)
        self.lay.addStretch(1)
        self.lay.addWidget(self.more)
        self._fit()

    def _icon_for(self, item) -> QIcon:
        c = self.palette_
        if item.is_folder:
            return svg_icon("folder", c.icon, 16)
        fav = self.favicon_for(item.url)
        if fav is not None and not fav.isNull():
            return fav
        low = item.url.lower().split("#")[0].split("?")[0]
        if low.endswith((".htex", ".tex")) and self.doc_icon is not None:
            return self.doc_icon
        return svg_icon("globe", c.icon, 16)

    def _button(self, item) -> QToolButton:
        b = QToolButton(self)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setIconSize(QSize(16, 16))
        b.setFixedHeight(28)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setIcon(self._icon_for(item))
        fm = QFontMetrics(b.font())
        b.setText(fm.elidedText(item.title, Qt.TextElideMode.ElideRight, 160).replace("&", "&&"))
        b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        b.customContextMenuRequested.connect(lambda pos, it=item, w=b: self._item_menu(it, w.mapToGlobal(pos)))
        if item.is_folder:
            b.setToolTip(item.title)
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            b.setMenu(self._folder_menu(item))
        else:
            b.setToolTip(f"{item.title}\n{item.url}")
            b.clicked.connect(lambda _=False, u=item.url: self.open_requested.emit(
                u, bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)))
            b.installEventFilter(self)
        return b

    def eventFilter(self, obj, ev):  # noqa: N802 - 가운데 클릭 = 새 탭
        if (ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.MiddleButton
                and isinstance(obj, QToolButton) and obj in self.buttons):
            it = self.items[self.buttons.index(obj)]
            if not it.is_folder:
                self.open_requested.emit(it.url, True)
                return True
        return super().eventFilter(obj, ev)

    def _folder_menu(self, folder) -> QMenu:
        m = QMenu(self)
        if not folder.children:
            a = m.addAction("(비어 있음)")
            a.setEnabled(False)
        for ch in folder.children or []:
            a = m.addAction(self._icon_for(ch), ch.title.replace("&", "&&"))
            a.setToolTip(ch.url)
            a.triggered.connect(lambda _=False, u=ch.url: self.open_requested.emit(u, False))
        if folder.children:
            m.addSeparator()
            a = m.addAction(f"모두 새 탭에서 열기 ({len(folder.children)})")
            a.triggered.connect(lambda _=False, f=folder: [self.open_requested.emit(c.url, True)
                                                           for c in f.children or []])
        return m

    def _item_menu(self, item, pos: QPoint) -> None:
        m = QMenu(self)
        if not item.is_folder:
            m.addAction("열기").triggered.connect(lambda: self.open_requested.emit(item.url, False))
            m.addAction("새 탭에서 열기").triggered.connect(lambda: self.open_requested.emit(item.url, True))
            m.addSeparator()
            m.addAction("수정…").triggered.connect(lambda: self.edit_requested.emit(item))
        else:
            m.addAction("이름 바꾸기…").triggered.connect(lambda: self.edit_requested.emit(item))
        m.addAction("삭제").triggered.connect(lambda: self.remove_requested.emit(item))
        m.addSeparator()
        self._common_actions(m)
        m.exec(pos)

    def _common_actions(self, m: QMenu) -> None:
        m.addAction("이 페이지 북마크에 추가…").triggered.connect(self.add_page_requested)
        m.addAction("폴더 추가…").triggered.connect(self.add_folder_requested)
        m.addSeparator()
        a = m.addAction("북마크바 표시")
        a.setCheckable(True)
        a.setChecked(True)
        a.triggered.connect(self.toggle_requested)

    def contextMenuEvent(self, e) -> None:   # noqa: N802
        m = QMenu(self)
        self._common_actions(m)
        m.exec(e.globalPos())

    def resizeEvent(self, e) -> None:   # noqa: N802
        super().resizeEvent(e)
        self._fit()

    def _fit(self) -> None:
        """다 들어가지 않으면 뒤쪽 단추를 숨기고 » 메뉴에 넣는다."""
        avail = self.width() - 16 - 32
        used = 0
        hidden = []
        for b, it in zip(self.buttons, self.items):
            w = b.sizeHint().width()
            if used + w <= avail:
                b.show()
                used += w
            else:
                b.hide()
                hidden.append(it)
        if hidden:
            m = QMenu(self)
            for it in hidden:
                if it.is_folder:
                    sub = self._folder_menu(it)
                    sub.setTitle(it.title.replace("&", "&&"))
                    sub.setIcon(self._icon_for(it))
                    m.addMenu(sub)
                else:
                    a = m.addAction(self._icon_for(it), it.title.replace("&", "&&"))
                    a.triggered.connect(lambda _=False, u=it.url: self.open_requested.emit(u, False))
            self.more.setMenu(m)
            self.more.show()
        else:
            self.more.hide()

    def set_palette(self, c: Palette) -> None:
        self.palette_ = c
        self.more.setIcon(svg_icon("chevrons", c.icon, 18))
        self.set_items(self.items)


# ====================================================================== 페이지 영역·말풍선
class StatusBubble(QLabel):
    """페이지 왼쪽 아래에 잠깐 뜨는 말풍선 (링크 주소, 짧은 알림). QStatusBar 의 showMessage 와 같은 이름."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("statusbubble")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clearMessage)
        self.hide()

    def showMessage(self, text: str, timeout: int = 0) -> None:   # noqa: N802
        if not text:
            self.clearMessage()
            return
        parent = self.parentWidget()
        maxw = max(120, int(parent.width() * 0.6)) if parent else 600
        fm = QFontMetrics(self.font())
        self.setText(fm.elidedText(text, Qt.TextElideMode.ElideMiddle, maxw - 20))
        self.setToolTip(text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        if timeout:
            self._timer.start(timeout)
        else:
            self._timer.stop()

    def currentMessage(self) -> str:   # noqa: N802
        return self.toolTip() if self.isVisible() else ""

    def clearMessage(self) -> None:   # noqa: N802
        self._timer.stop()
        self.hide()
        self.setToolTip("")

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.move(0, parent.height() - self.height())


class PageArea(QWidget):
    """페이지 더미 + 그 위에 떠 있는 것들(링크 말풍선, 찾기 상자)."""

    def __init__(self, stack: TabStack, parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(stack)
        self.stack = stack
        self.bubble = StatusBubble(self)
        self.overlay_top_right: Optional[QWidget] = None

    def resizeEvent(self, e) -> None:   # noqa: N802
        super().resizeEvent(e)
        self.bubble.reposition()
        self.place_overlay()

    def place_overlay(self) -> None:
        w = self.overlay_top_right
        if w is not None:
            w.adjustSize()
            w.move(max(0, self.width() - w.width() - 28), 0)
            w.raise_()


# ====================================================================== 떠 있는 상자
class Popup(QFrame):
    """단추 아래에 뜨는 상자 (북마크 편집, 페이지 정보). 밖을 누르면 닫힌다."""

    def __init__(self, parent: QWidget, width: int = 340):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("popup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedWidth(width)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 16, 20, 16)
        self.lay.setSpacing(10)

    def title(self, text: str) -> QLabel:
        lab = QLabel(text, self)
        lab.setObjectName("popuptitle")
        self.lay.addWidget(lab)
        return lab

    def label(self, text: str, muted: bool = False, wrap: bool = True) -> QLabel:
        lab = QLabel(text, self)
        lab.setWordWrap(wrap)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if muted:
            lab.setProperty("muted", "true")
        self.lay.addWidget(lab)
        return lab

    def closeEvent(self, e) -> None:   # noqa: N802
        # 상자가 닫히면 창이 다시 키보드를 받게 (몇몇 플랫폼은 스스로 돌려주지 않는다)
        win = self.parentWidget().window() if self.parentWidget() else None
        super().closeEvent(e)
        if win is not None and win.isVisible():
            win.activateWindow()

    def show_under(self, anchor: QWidget, align_right: bool = True) -> None:
        self.adjustSize()
        g = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        x = g.x() + anchor.width() - self.width() if align_right else g.x()
        screen = anchor.screen().availableGeometry() if anchor.screen() else None
        if screen is not None:
            x = max(screen.left() + 4, min(x, screen.right() - self.width() - 4))
        self.move(x, g.y())
        self.show()


class BookmarkPopup(Popup):
    """☆ 를 누르면: "북마크 추가됨" 이름·폴더 고치기, 삭제·완료 (Chrome 과 같다)."""

    def __init__(self, parent: QWidget, title: str, folders: list, current_folder, new: bool):
        super().__init__(parent)
        self.title("북마크 추가됨" if new else "북마크 수정")
        row = QHBoxLayout()
        row.setSpacing(8)
        name_lab = QLabel("이름", self)
        name_lab.setFixedWidth(40)
        self.name = QLineEdit(title, self)
        self.name.selectAll()
        row.addWidget(name_lab)
        row.addWidget(self.name, 1)
        self.lay.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(8)
        f_lab = QLabel("폴더", self)
        f_lab.setFixedWidth(40)
        self.folder = QComboBox(self)
        self.folder.addItem("북마크바", None)
        for f in folders:
            self.folder.addItem(f.title, f)
        if current_folder is not None:
            for i in range(self.folder.count()):
                if self.folder.itemData(i) is current_folder:
                    self.folder.setCurrentIndex(i)
        row.addWidget(f_lab)
        row.addWidget(self.folder, 1)
        self.lay.addLayout(row)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.remove_btn = QPushButton("삭제", self)
        self.done_btn = QPushButton("완료", self)
        self.done_btn.setDefault(True)
        btns.addWidget(self.remove_btn)
        btns.addWidget(self.done_btn)
        self.lay.addLayout(btns)
        self.name.returnPressed.connect(self.done_btn.click)
        self.name.setFocus()


class ZoomRow(QWidget):
    """⋮ 메뉴 안의 '확대/축소   −  100%  +' 한 줄."""

    def __init__(self, parent: QWidget, zoom_out: Callable, zoom_in: Callable, reset: Callable):
        super().__init__(parent)
        self.setObjectName("zoomrow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 4, 12, 4)
        lay.addWidget(QLabel("확대/축소", self))
        lay.addStretch(1)
        self.minus = QToolButton(self)
        self.minus.setText("−")
        self.minus.setToolTip("축소 (Ctrl+-)")
        self.value = QToolButton(self)
        self.value.setToolTip("원래 크기 (Ctrl+0)")
        self.value.setMinimumWidth(52)
        self.plus = QToolButton(self)
        self.plus.setText("+")
        self.plus.setToolTip("확대 (Ctrl+=)")
        self.minus.clicked.connect(zoom_out)
        self.plus.clicked.connect(zoom_in)
        self.value.clicked.connect(reset)
        for w in (self.minus, self.value, self.plus):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(w)


def is_mac() -> bool:
    return sys.platform == "darwin"
