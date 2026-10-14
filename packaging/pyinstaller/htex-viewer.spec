# -*- mode: python ; coding: utf-8 -*-
"""HyperTeX 뷰어 PyInstaller 명세 (onedir).

사용 (저장소 뿌리에서):
    python -m pip install ".[viewer,build]"
    python packaging/icons/make_icons.py          # 아이콘이 없거나 원본 SVG 를 바꿨을 때
    pyinstaller --noconfirm --clean packaging/pyinstaller/htex-viewer.spec

결과:
    Linux/Windows: dist/htex-viewer/ (실행 파일 htex-viewer[.exe] + _internal/)
    macOS:         dist/HyperTeX.app

포함하는 것:
    - htex 패키지 전체와 패키지 데이터(htex/web/interact.js 등 .py 아닌 파일)
    - PySide6 훅이 넣는 QtWebEngine 실행에 필요한 것: QtWebEngineProcess, resources/(icudtl.dat,
      qtwebengine_resources*.pak), translations/qtwebengine_locales/
빼는 것: 뷰어가 쓰지 않는 Qt 모듈 (EXCLUDE_QT). 크기 측정은 packaging/README.md.
"""
import os
import plistlib
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]          # noqa: F821 (PyInstaller 가 넣는 이름)
sys.path.insert(0, str(ROOT))
import htex  # noqa: E402

VERSION = htex.__version__
APP_NAME = "HyperTeX"
BUNDLE_ID = "org.hypertex.viewer"
ICONS = ROOT / "packaging" / "icons"

# --- 뷰어가 쓰지 않는 Qt 모듈 (필요해지면 여기서 빼기) ------------------------------------
# QtWebEngine 이 의존하는 QtNetwork, QtPositioning, QtQml/QtQuick(WebEngineCore 링크),
# QtWebChannel, QtPrintSupport, QtOpenGL 은 남겨 둔다. 빼면 QtWebEngineCore 를 불러올 수 없다.
EXCLUDE_QT = [
    "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
    "QtBluetooth", "QtCharts", "QtConcurrent", "QtDataVisualization", "QtDesigner",
    "QtGraphs", "QtGraphsWidgets", "QtHelp", "QtHttpServer", "QtLocation", "QtMultimedia",
    "QtMultimediaWidgets", "QtNfc", "QtPdf", "QtPdfWidgets", "QtQuick3D", "QtQuickControls2",
    "QtQuickTest", "QtRemoteObjects", "QtScxml", "QtSensors",
    "QtSerialBus", "QtSerialPort", "QtSpatialAudio", "QtSql", "QtStateMachine", "QtSvgWidgets",
    "QtTest", "QtTextToSpeech", "QtUiTools", "QtWebSockets", "QtWebView", "QtXml",
    "QtAxContainer", "QtCanvasPainter",
]
EXCLUDES = ["PySide6." + m for m in EXCLUDE_QT] + [
    "tkinter", "unittest", "pydoc", "pytest", "jsonschema", "PIL", "numpy",
]

datas = collect_data_files("htex", includes=["**/*.js", "**/*.css", "**/*.json", "**/*.svg",
                                             "**/*.png", "**/*.txt", "**/*.html"])
hiddenimports = collect_submodules("htex")

a = Analysis(                                                       # noqa: F821
    [str(ROOT / "packaging" / "pyinstaller" / "htex_viewer_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "packaging" / "pyinstaller" / "hooks")],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)


# Qt 모듈을 import 단계에서 빼도 QML 플러그인을 따라 공유 라이브러리·번역이 딸려 온다. 이름으로 한 번 더 거른다.
# (리눅스 PySide6 6.12 에서 libQt6WebEngineCore 와 위젯·플랫폼 플러그인의 의존성 닫힘을 readelf 로 구해
#  거기 들지 않는 것만 골랐다. QtQuick·QtQuickWidgets·QtQml·QmlModels·QmlMeta·QmlWorkerScript 는 WebEngineCore/Widgets 가
#  링크하므로 남긴다. 빠진 것이 없는지는 packaging/check_bundle.py 가 빌드 뒤에 확인한다.)
import re  # noqa: E402

_UNUSED_LIB = re.compile(
    r"^(lib)?Qt6?("
    r"3D\w*|Quick3D\w*|QuickControls2\w*|QuickDialogs2\w*|QuickTemplates2|QuickEffects|QuickLayouts"
    r"|QuickParticles|QuickShapes\w*|QuickTimeline\w*|QuickVectorImage\w*|QuickTest"
    r"|Labs\w*|ShaderTools|WaylandCompositor\w*|WebEngineQuick\w*|WebViewQuick|WebChannelQuick"
    r"|[A-Z][A-Za-z]*Qml|PdfQuick|MultimediaQuick|PositioningQuick|SensorsQuick|Graphs\w*|QmlCore|QmlDesignSupport"
    r"|QmlLocalStorage|QmlNetwork|QmlXmlListModel|OpenGLWidgets|VirtualKeyboard\w*"
    r"|" + "|".join(m[2:] for m in EXCLUDE_QT if m.startswith("Qt")) + r")"
    r"(d)?(\.so[.\d]*|\.dll|\.dylib)?$")
# 뷰어가 쓰지 않는 Qt 플러그인 폴더
_UNUSED_PLUGIN_DIRS = ("qmltooling", "wayland-graphics-integration-server", "sceneparsers", "renderers",
                       "geometryloaders", "multimedia", "sqldrivers", "designer", "assetimporters",
                       "texttospeech", "canbus", "sensors", "geoservices", "virtualkeyboard",
                       "renderplugins")
# QtWebEngine 의 Chromium 로캘(.pak, 하나에 수백 KB, 모두 44MB). 없는 로캘은 en-US 로 대신한다.
# HTEX_WEBENGINE_LOCALES=all 이면 모두 넣는다.
_LOCALES = os.environ.get("HTEX_WEBENGINE_LOCALES",
                          "en-US,en-GB,ko,ja,zh-CN,zh-TW,de,fr,es,it,pt-BR,ru")
_KEEP_LOCALES = None if _LOCALES == "all" else {x.strip() + ".pak" for x in _LOCALES.split(",")}


def _drop(toc):
    out = []
    for entry in toc:
        name = entry[0].replace("\\", "/")
        parts = name.split("/")
        base = parts[-1]
        if _UNUSED_LIB.match(base) or _UNUSED_LIB.match(base.split(".framework")[0]):
            continue
        if any(f"{d}.framework" in name and _UNUSED_LIB.match(d) for d in parts):
            continue                          # macOS: Qt 프레임워크 폴더
        if "qml" in parts:
            continue                          # 뷰어는 QML 을 쓰지 않는다
        if "plugins" in parts and any(d in parts for d in _UNUSED_PLUGIN_DIRS):
            continue
        if "platforminputcontexts" in parts and "virtualkeyboard" in base.lower():
            continue
        if "translations" in parts:
            if "qtwebengine_locales" in parts:
                if _KEEP_LOCALES is not None and base not in _KEEP_LOCALES:
                    continue
            elif not base.startswith(("qtbase_", "qt_", "qtwebengine_")):
                continue                      # 다른 Qt 모듈의 번역
        out.append(entry)
    return out


a.binaries = _drop(a.binaries)
a.datas = _drop(a.datas)

pyz = PYZ(a.pure)                                                   # noqa: F821

if sys.platform == "win32":
    icon = str(ICONS / "htex.ico")
elif sys.platform == "darwin":
    icon = str(ICONS / "htex.icns")
else:
    icon = str(ICONS / "htex.png")

exe = EXE(                                                          # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="htex-viewer",
    debug=False,
    strip=False,
    upx=False,                 # UPX 는 Qt 라이브러리를 깨뜨리는 일이 잦다
    console=False,             # GUI 앱 (windowed)
    icon=icon,
    argv_emulation=False,      # macOS 파일 열기 이벤트는 뷰어(QFileOpenEvent)가 직접 처리 (담당 J)
    codesign_identity=os.environ.get("HTEX_CODESIGN_IDENTITY") or None,
    entitlements_file=(str(ROOT / "packaging" / "macos" / "entitlements.plist")
                       if sys.platform == "darwin" else None),
)

coll = COLLECT(                                                     # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="htex-viewer",
)

if sys.platform == "darwin":
    with open(ROOT / "packaging" / "macos" / "Info.plist.in", "rb") as f:
        info = plistlib.load(f)
    info["CFBundleShortVersionString"] = VERSION
    info["CFBundleVersion"] = VERSION
    app = BUNDLE(                                                   # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist=info,
    )
