"""I: OS 등록 파일·빌드 스크립트·워크플로의 정합성 (실행 없이 내용 검사)."""
from __future__ import annotations

import configparser
import plistlib
import os
import re
import sys
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PK = ROOT / "packaging"


def test_icons_present_and_regenerable():
    assert (PK / "icons" / "htex.svg").exists()
    ET.parse(PK / "icons" / "htex.svg")
    for f in ("htex.ico", "htex.icns", "htex.png", "make_icons.py"):
        assert (PK / "icons" / f).exists(), f
    for s in (16, 32, 48, 128, 256, 512, 1024):
        assert (PK / "icons" / "png" / f"htex-{s}.png").exists()
    assert (PK / "icons" / "htex.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert (PK / "icons" / "htex.icns").read_bytes()[:4] == b"icns"


def test_macos_info_plist():
    info = plistlib.loads((PK / "macos" / "Info.plist.in").read_bytes())
    assert info["CFBundleIdentifier"] == "org.hypertex.viewer"
    schemes = [s for t in info["CFBundleURLTypes"] for s in t["CFBundleURLSchemes"]]
    assert schemes == ["htex"]
    docs = {d["CFBundleTypeName"]: d for d in info["CFBundleDocumentTypes"]}
    htex_doc = docs["HyperTeX Document"]
    assert htex_doc["LSItemContentTypes"] == ["org.hypertex.htex"] and htex_doc["LSHandlerRank"] == "Owner"
    tex_doc = docs["TeX Document"]
    assert tex_doc["CFBundleTypeRole"] == "Viewer" and tex_doc["LSHandlerRank"] == "Alternate"
    exported = info["UTExportedTypeDeclarations"][0]
    assert exported["UTTypeIdentifier"] == "org.hypertex.htex"
    assert exported["UTTypeTagSpecification"]["public.filename-extension"] == ["htex"]
    assert exported["UTTypeTagSpecification"]["public.mime-type"] == ["text/x-hypertex"]
    imported = info["UTImportedTypeDeclarations"][0]
    assert imported["UTTypeIdentifier"] in tex_doc["LSItemContentTypes"]
    ent = plistlib.loads((PK / "macos" / "entitlements.plist").read_bytes())
    assert ent["com.apple.security.cs.allow-jit"] is True


def test_spec_uses_plist_and_bundle_id():
    spec = (PK / "pyinstaller" / "htex-viewer.spec").read_text("utf-8")
    assert "Info.plist.in" in spec and 'BUNDLE_ID = "org.hypertex.viewer"' in spec
    assert "htex_viewer_entry.py" in spec and "interact" not in spec.split("datas =")[0][-1:]
    assert "argv_emulation=False" in spec          # 파일 열기 이벤트는 뷰어(J)가 처리
    entry = (PK / "pyinstaller" / "htex_viewer_entry.py").read_text("utf-8")
    assert "gui_main" in entry and "QApplication(" not in entry


def _spec_regex():
    src = (PK / "pyinstaller" / "htex-viewer.spec").read_text("utf-8")
    ns: dict = {"re": re}
    exec(src[src.index("EXCLUDE_QT = ["):src.index("EXCLUDES =")], ns)
    exec(src[src.index("_UNUSED_LIB = re.compile"):src.index("# 뷰어가 쓰지 않는 Qt 플러그인")], ns)
    return ns["_UNUSED_LIB"]


@pytest.mark.parametrize("name", [
    "libQt6Core.so.6", "libQt6Gui.so.6", "libQt6Widgets.so.6", "libQt6Qml.so.6", "libQt6QmlModels.so.6",
    "libQt6QmlMeta.so.6", "libQt6QmlWorkerScript.so.6", "libQt6Quick.so.6", "libQt6QuickWidgets.so.6",
    "libQt6WebEngineCore.so.6", "libQt6WebEngineWidgets.so.6", "libQt6WebChannel.so.6",
    "libQt6Positioning.so.6", "libQt6PrintSupport.so.6", "libQt6OpenGL.so.6", "libQt6Network.so.6",
    "libQt6Svg.so.6", "libQt6XcbQpa.so.6", "Qt6WebEngineCore.dll", "Qt6Qml.dll", "Qt6QuickWidgets.dll",
    "QtWebEngineCore", "QtQuick", "QtQml",
])
def test_spec_keeps_webengine_dependencies(name):
    """QtWebEngine 이 링크하는 Qt 라이브러리를 정리 규칙이 지우면 실행 파일이 뜨지 않는다."""
    assert not _spec_regex().match(name)


@pytest.mark.parametrize("name", ["libQt63DCore.so.6", "libQt6Quick3D.so.6", "libQt6ChartsQml.so.6",
                                  "Qt6Pdf.dll", "libQt6QuickControls2.so.6", "libQt6Multimedia.so.6"])
def test_spec_drops_unused(name):
    assert _spec_regex().match(name)


def test_linux_desktop_entry():
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read(PK / "linux" / "org.hypertex.viewer.desktop", encoding="utf-8")
    e = cp["Desktop Entry"]
    assert e["Type"] == "Application"
    assert e["Exec"] == "htex-viewer %U"           # 파일·주소 여러 개 → gui_main
    mimes = [x for x in e["MimeType"].split(";") if x]
    assert mimes == ["text/x-hypertex", "x-scheme-handler/htex"]
    if shutil.which("desktop-file-validate"):
        r = subprocess.run(["desktop-file-validate", str(PK / "linux" / "org.hypertex.viewer.desktop")],
                           capture_output=True, text=True)
        assert "error" not in (r.stdout + r.stderr).lower()


def test_linux_mime_xml():
    ns = {"m": "http://www.freedesktop.org/standards/shared-mime-info"}
    root = ET.parse(PK / "linux" / "hypertex-mime.xml").getroot()
    t = root.find("m:mime-type", ns)
    assert t.get("type") == "text/x-hypertex"
    assert [g.get("pattern") for g in t.findall("m:glob", ns)] == ["*.htex"]
    assert t.find("m:sub-class-of", ns).get("type") == "text/plain"


def test_xml_comments_have_no_double_hyphen():
    """XML 주석 안의 '--' 는 문서를 깨뜨린다 (update-mime-database·plist 파서가 거부)."""
    for f in [PK / "linux" / "hypertex-mime.xml", PK / "macos" / "Info.plist.in",
              PK / "macos" / "entitlements.plist", PK / "icons" / "htex.svg"]:
        for c in re.findall(r"<!--(.*?)-->", f.read_text("utf-8"), re.S):
            assert "--" not in c, f


@pytest.mark.parametrize("script", ["linux/install.sh", "linux/make-appimage.sh", "linux/make-tarball.sh",
                                    "macos/make-dmg.sh", "macos/sign-and-notarize.sh"])
def test_shell_scripts_parse(script):
    p = PK / script
    if os.name != "nt":  # 윈도 파일 시스템에는 실행 권한 비트가 없다 (git 의 실행 표시는 아래 테스트가 본다)
        assert p.stat().st_mode & 0o111, f"{script} 실행 권한"
    if shutil.which("sh"):
        assert subprocess.run(["sh", "-n", str(p)]).returncode == 0


def test_linux_install_user_scope(tmp_path):
    """임시 HOME 에 --pip 모드(등록만)로 설치·제거. 관리자 권한 없이 ~/.local 아래에만 쓴다."""
    if sys.platform != "linux":
        pytest.skip("리눅스 데스크톱 등록 스크립트")
    if not shutil.which("sh"):
        pytest.skip("sh 없음")
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    fake = home / "bin" / "htex-viewer"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{home / 'bin'}:/usr/bin:/bin", "HTEX_SET_DEFAULT": "0"}
    r = subprocess.run(["sh", str(PK / "linux" / "install.sh"), "--pip"], env=env, capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    share = home / ".local" / "share"
    desktop = (share / "applications" / "org.hypertex.viewer.desktop").read_text("utf-8")
    assert f'Exec="{fake}" %U' in desktop
    assert (share / "mime" / "packages" / "hypertex-mime.xml").exists()
    assert (share / "icons" / "hicolor" / "256x256" / "apps" / "org.hypertex.viewer.png").exists()
    written = {p for p in home.rglob("*") if p.is_file()} - {fake}
    assert all(str(p).startswith(str(home / ".local")) for p in written), written
    r = subprocess.run(["sh", str(PK / "linux" / "install.sh"), "--uninstall"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert not (share / "applications" / "org.hypertex.viewer.desktop").exists()
    assert not (share / "mime" / "packages" / "hypertex-mime.xml").exists()


def test_windows_inno_setup():
    raw = (PK / "windows" / "htex-viewer.iss").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")             # 한글 메시지 → UTF-8 BOM
    iss = raw.decode("utf-8-sig")
    assert "PrivilegesRequired=lowest" in iss          # 사용자 단위 설치
    assert "ChangesAssociations=yes" in iss
    assert re.search(r'Subkey: "Software\\Classes\\htex"; ValueType: string; ValueName: "URL Protocol"', iss)
    assert re.search(r'Subkey: "Software\\Classes\\\.htex"; ValueType: string; ValueName: ""; '
                     r'ValueData: "\{#ProgId\}"', iss)
    # 모든 열기 명령은 인수 하나("%1")를 gui_main 으로 넘긴다
    cmds = re.findall(r'shell\\open\\command"; ValueType: string; ValueName: ""; ValueData: "(.*?)"(?:;|$)', iss)
    assert cmds and all(c == '"""{app}\\{#AppExe}"" ""%1""' or c.endswith('""%1""') for c in cmds), cmds
    # 키를 만든 곳에는 제거 표시가 있다
    for key in ("{#ProgId}", "{#TexProgId}", "htex", "Applications\\{#AppExe}", "HyperTeX\\Capabilities"):
        assert re.search(r'Subkey: "Software\\(Classes\\)?' + re.escape(key) + r'";[^\n]*uninsdeletekey', iss), key
    reg = [l for l in iss.splitlines() if 'Subkey: "Software\\RegisteredApplications"' in l]
    assert reg and all("uninsdeletevalue" in l for l in reg)


def test_workflow_yaml():
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text("utf-8"))
    on = wf.get("on", wf.get(True))                  # YAML 1.1 에서 on 은 True
    assert "v*" in on["push"]["tags"]
    jobs = wf["jobs"]
    assert set(jobs) == {"test", "build", "release"}
    assert {"ubuntu-latest", "macos-latest", "windows-latest"} <= set(jobs["test"]["strategy"]["matrix"]["os"])
    assert jobs["build"]["needs"] == "test" and jobs["release"]["needs"] == "build"
    assert "refs/tags/v" in jobs["release"]["if"]
    steps = " ".join(str(s) for s in jobs["build"]["steps"])
    for needle in ("htex-viewer.spec", "make-dmg.sh", "innosetup", "make-appimage.sh", "make-tarball.sh",
                   "smoke_test.py", "check_bundle.py"):
        assert needle in steps, needle
    # 서명 단계는 비밀값이 있을 때만
    for s in jobs["build"]["steps"]:
        name = s.get("name", "")
        if any(k in name for k in ("서명", "공증", "인증서")):
            assert "HAS_" in s.get("if", ""), name


def test_shell_scripts_executable_in_git():
    """체크아웃한 OS와 무관하게 git 에 실행 표시(100755)로 들어가 있어야 리눅스·맥에서 바로 실행된다."""
    import shutil as _sh
    if not _sh.which("git") or not (PK.parent / ".git").exists():
        pytest.skip("git 저장소 아님")
    out = subprocess.run(["git", "ls-files", "-s", "packaging/linux", "packaging/macos"], cwd=PK.parent,
                         capture_output=True, text=True).stdout
    modes = {ln.split("\t")[1]: ln.split()[0] for ln in out.splitlines() if ln.endswith(".sh")}
    assert modes and all(m == "100755" for m in modes.values()), modes
