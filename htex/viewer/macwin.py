"""macOS 창 다듬기: 탭 줄을 제목 막대 자리로 올린다 (Chrome 처럼).

Qt 6.9+ 의 ExpandedClientAreaHint(내용을 제목 막대 밑까지 넓힘)와 NoTitleBarBackgroundHint(제목 막대 배경 없앰)를
쓰고, 신호등 단추(닫기·최소화·확대)는 macOS 가 그대로 그린다. Qt 에 없는 두 가지만 Objective-C 런타임을
ctypes 로 직접 부른다(추가 의존성 없음):

- 창 제목 글자 숨기기 (NSWindow.titleVisibility = hidden). 제목은 그대로 두므로 Dock·미션 컨트롤·윈도 메뉴에는 나온다.
- 제목 막대 더블클릭 동작 설정 읽기 (시스템 설정 › 데스크탑 및 Dock › "윈도우 제목 막대를 이중 클릭하여").

다른 운영체제·Qt 6.9 미만·네이티브 호출 실패 때는 모두 조용히 아무것도 하지 않는다 (예전처럼 제목 막대 아래 탭 줄).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Optional

# 신호등 단추 셋이 차지하는 폭 (왼쪽 여백 포함). Chrome·Safari 와 같은 값 근처.
TRAFFIC_LIGHTS_W = 78

_objc = None


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
        path = ctypes.util.find_library("objc")
        if not path:
            raise OSError("libobjc 없음")
        lib = ctypes.cdll.LoadLibrary(path)
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        _objc = lib
    return _objc


def _send(obj: int, selector: str, *args, restype=ctypes.c_void_p, argtypes=()):
    """objc_msgSend 를 정확한 원형으로 부른다 (arm64 에서는 가변 인자로 부르면 안 된다)."""
    lib = _lib()
    fn = ctypes.cast(lib.objc_msgSend,
                     ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
    return fn(obj, lib.sel_registerName(selector.encode()), *args)


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
            return False
        _send(win, "setTitleVisibility:", 1, restype=None, argtypes=(ctypes.c_long,))   # NSWindowTitleHidden
        return True
    except Exception:   # noqa: BLE001
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
