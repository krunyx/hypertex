"""macOS 창 다듬기: 탭 줄을 제목 막대 자리로 올린다 (Chrome 처럼).

Qt 6.9+ 의 ExpandedClientAreaHint(내용을 제목 막대 밑까지 넓힘)와 NoTitleBarBackgroundHint(제목 막대 배경 없앰)를
쓰고, 신호등 단추(닫기·최소화·확대)는 macOS 가 그대로 그린다. Qt 에 없는 두 가지만 Objective-C 런타임을
ctypes 로 직접 부른다(추가 의존성 없음):

- 창 제목 글자 숨기기 (NSWindow.titleVisibility = hidden). 제목은 그대로 두므로 Dock·미션 컨트롤·윈도 메뉴에는 나온다.
- 신호등 단추를 탭 줄 높이에 맞춰 내리기 (Chrome·Electron 과 같은 방법: 제목 막대 컨테이너를 탭 줄 높이로 키우고
  단추의 세로 위치를 옮긴다. AppKit 이 크기 바꿀 때마다 되돌리므로 창이 그때마다 다시 부른다).
- 제목 막대 더블클릭 동작 설정 읽기 (시스템 설정 › 데스크탑 및 Dock › "윈도우 제목 막대를 이중 클릭하여").

다른 운영체제·Qt 6.9 미만·네이티브 호출 실패 때는 모두 조용히 아무것도 하지 않는다 (예전처럼 제목 막대 아래 탭 줄).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from typing import Optional

# 신호등 단추 셋이 차지하는 폭 (왼쪽 여백 포함). Chrome·Safari 와 같은 값 근처.
TRAFFIC_LIGHTS_W = 78

_objc = None
last_error = ""          # 마지막 네이티브 호출 실패 (진단용. HTEX_DEBUG=1 이면 표준 오류에도 쓴다)


def _fail(where: str, exc: BaseException) -> None:
    global last_error
    last_error = f"{where}: {type(exc).__name__}: {exc}"
    if os.environ.get("HTEX_DEBUG"):
        print("[macwin]", last_error, file=sys.stderr)


class NSPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class NSSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class NSRect(ctypes.Structure):
    _fields_ = [("origin", NSPoint), ("size", NSSize)]


def _cocoa() -> bool:
    """실제 macOS 창인가 (offscreen 등 다른 Qt 플랫폼에서는 winId 가 NSView 가 아니다)."""
    if sys.platform != "darwin":
        return False
    try:
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.platformName() == "cocoa"
    except Exception:   # noqa: BLE001
        return False


def supported() -> bool:
    """이 플랫폼·Qt 에서 제목 막대 탭을 쓸 수 있는가."""
    if not _cocoa():
        return False
    try:
        from PySide6.QtCore import Qt
        return hasattr(Qt.WindowType, "ExpandedClientAreaHint") and hasattr(Qt.WindowType,
                                                                            "NoTitleBarBackgroundHint")
    except Exception:   # noqa: BLE001
        return False


def _lib():
    global _objc
    if _objc is None:
        # 묶인 앱(PyInstaller)에서는 find_library 가 못 찾을 수 있다. 시스템 경로는 dyld 공유 캐시로 늘 열린다.
        path = ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib"
        lib = ctypes.cdll.LoadLibrary(path)
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        _objc = lib
    return _objc


def _send(obj: int, selector: str, *args, restype=ctypes.c_void_p, argtypes=()):
    """objc_msgSend 를 정확한 원형으로 부른다 (arm64 에서는 가변 인자로 부르면 안 된다).
    Intel 맥에서 NSRect 처럼 큰 구조체를 돌려받을 때는 objc_msgSend_stret 를 쓴다."""
    lib = _lib()
    entry = lib.objc_msgSend
    if restype is NSRect and _is_x86():
        entry = lib.objc_msgSend_stret
    fn = ctypes.cast(entry,
                     ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
    return fn(obj, lib.sel_registerName(selector.encode()), *args)


def _is_x86() -> bool:
    import platform
    return platform.machine() in ("x86_64", "i386")


def _ns_window(widget) -> Optional[int]:
    view = int(widget.winId())          # macOS 에서 winId 는 NSView*
    if not view:
        return None
    return _send(view, "window") or None


def hide_title_text(widget) -> bool:
    """제목 막대의 제목 글자만 숨긴다. 실패하면 False (제목이 탭 위에 겹쳐 보일 뿐 동작은 그대로)."""
    if not _cocoa():
        return False
    try:
        win = _ns_window(widget)
        if not win:
            raise RuntimeError("NSWindow 없음")
        _send(win, "setTitleVisibility:", 1, restype=None, argtypes=(ctypes.c_long,))   # NSWindowTitleHidden
        return _send(win, "titleVisibility", restype=ctypes.c_long) == 1
    except Exception as e:   # noqa: BLE001
        _fail("hide_title_text", e)
        return False


def place_traffic_lights(widget, strip_height: float, center_from_top: float) -> bool:
    """신호등 단추의 가운데가 창 위에서 center_from_top(pt) 에 오게 한다.

    단추는 제목 막대 컨테이너 안에만 그려지므로, 컨테이너를 탭 줄 높이(strip_height)로 키워 창 맨 위에 붙이고
    단추의 y 만 옮긴다. x 는 macOS 가 정한 그대로. 전체 화면에서는 부르지 않는다."""
    if not _cocoa():
        return False
    try:
        win = _ns_window(widget)
        if not win:
            raise RuntimeError("NSWindow 없음")
        close = _send(win, "standardWindowButton:", 0, argtypes=(ctypes.c_ulong,))
        if not close:
            raise RuntimeError("단추 없음")
        titlebar_view = _send(close, "superview")
        container = _send(titlebar_view, "superview") if titlebar_view else None
        if not container:
            raise RuntimeError("제목 막대 컨테이너 없음")
        win_frame = _send(win, "frame", restype=NSRect)
        frame = _send(container, "frame", restype=NSRect)
        frame.size.height = float(strip_height)
        frame.origin.y = win_frame.size.height - frame.size.height      # AppKit 좌표: 아래가 0
        _send(container, "setFrame:", frame, restype=None, argtypes=(NSRect,))
        for kind in (0, 1, 2):          # 닫기 · 최소화 · 확대
            b = _send(win, "standardWindowButton:", kind, argtypes=(ctypes.c_ulong,))
            if not b:
                continue
            bf = _send(b, "frame", restype=NSRect)
            y = frame.size.height - center_from_top - bf.size.height / 2.0
            _send(b, "setFrameOrigin:", NSPoint(bf.origin.x, y), restype=None, argtypes=(NSPoint,))
        return True
    except Exception as e:   # noqa: BLE001
        _fail("place_traffic_lights", e)
        return False


def double_click_action() -> str:
    """제목 막대 더블클릭 때 할 일: "zoom" | "minimize" | "none" (시스템 설정을 따른다)."""
    if sys.platform != "darwin":
        return "zoom"
    try:
        lib = _lib()
        defaults = _send(lib.objc_getClass(b"NSUserDefaults"), "standardUserDefaults")
        key = _send(lib.objc_getClass(b"NSString"), "stringWithUTF8String:", b"AppleActionOnDoubleClick",
                    argtypes=(ctypes.c_char_p,))
        value = _send(defaults, "stringForKey:", key, argtypes=(ctypes.c_void_p,))
        if not value:
            # 예전 설정 이름 (켜져 있으면 최소화)
            key = _send(lib.objc_getClass(b"NSString"), "stringWithUTF8String:", b"AppleMiniaturizeOnDoubleClick",
                        argtypes=(ctypes.c_char_p,))
            on = _send(defaults, "boolForKey:", key, restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,))
            return "minimize" if on else "zoom"
        text = _send(value, "UTF8String", restype=ctypes.c_char_p) or b""
        return action_from_setting(text.decode("utf-8", "replace"))
    except Exception:   # noqa: BLE001
        return "zoom"


def action_from_setting(value: str) -> str:
    v = value.strip().lower()
    if v == "minimize":
        return "minimize"
    if v in ("none", "do nothing"):
        return "none"
    return "zoom"            # "Maximize" (기본) · "Fill" (macOS 15) · 모르는 값
