"""I: 파이썬 패키지 — wheel 내용, 깨끗한 가상환경 설치, 콘솔·GUI 스크립트, interact.js 제공.

기본 실행: wheel 을 만들어(네트워크 없이) 시스템 패키지가 없는 가상환경에 설치하고 `htex html`,
`htex serve`(+ /__htex/interact.js), `htex-viewer`(PySide6 없을 때 안내) 를 확인한다.
느린 것(HTEX_SLOW=1 일 때만): `pip install .[viewer]` (PyPI 필요), PyInstaller 빌드와 스모크 테스트.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SLOW = os.environ.get("HTEX_SLOW") == "1"


def _version() -> str:
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', (ROOT / "htex" / "__init__.py").read_text("utf-8"), re.M)
    assert m
    return m.group(1)


def _data_files() -> set[str]:
    """htex/ 아래 .py 아닌 파일 (캐시 제외) — wheel 에 모두 들어가야 한다."""
    out = set()
    for p in (ROOT / "htex").rglob("*"):
        if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts:
            out.add(p.relative_to(ROOT).as_posix())
    return out


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("wheel")
    # 격리 없이(네트워크 불필요) 현재 setuptools 로 만든다. 소스 트리에 build/ 를 남기지 않게 복사본에서.
    src = out / "src"
    import shutil
    shutil.copytree(ROOT, src, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", "build", "dist", "*.egg-info", ".pytest_cache", "out", ".tools"))
    # 먼저 격리 없이(네트워크 불필요) 현재 setuptools 로. 시스템 setuptools 가 너무 오래되었거나 배포판이
    # 고친 것이라 실패하면(예: Debian setuptools 68 의 install_layout 오류) 격리 빌드(PyPI 에서 setuptools)로.
    errors = []
    for isolation in (["--no-build-isolation"], []):
        proc = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", *isolation,
                               "--wheel-dir", str(out), str(src)], capture_output=True, text=True, timeout=300)
        if proc.returncode == 0:
            break
        errors.append(proc.stdout[-1500:] + proc.stderr[-1500:])
    else:
        pytest.fail("wheel 빌드 실패:\n" + "\n----\n".join(errors))
    whls = list(out.glob("htex-*.whl"))
    assert len(whls) == 1
    return whls[0]


def test_wheel_contents(wheel):
    assert wheel.name == f"htex-{_version()}-py3-none-any.whl"   # 버전은 htex/__init__.py 한곳에서
    with zipfile.ZipFile(wheel) as z:
        names = set(z.namelist())
        ep = z.read(f"htex-{_version()}.dist-info/entry_points.txt").decode()
        meta = z.read(f"htex-{_version()}.dist-info/METADATA").decode()
    assert "htex/web/interact.js" in names
    missing = _data_files() - names
    assert not missing, f"wheel 에 빠진 패키지 데이터 (pyproject.toml package-data 에 추가): {missing}"
    assert not [n for n in names if n.startswith(("tests/", "packaging/", "examples/"))]
    assert re.search(r"\[console_scripts\]\s*htex = htex.__main__:main", ep)
    assert re.search(r"\[gui_scripts\]\s*htex-viewer = htex.__main__:gui_main", ep)
    # 런타임 의존성 없음, PySide6 는 viewer 선택 의존성
    requires = [l for l in meta.splitlines() if l.startswith("Requires-Dist:")]
    assert all("extra ==" in l for l in requires), requires
    assert any(l.startswith("Requires-Dist: PySide6") and "extra == \"viewer\"" in l for l in requires)


@pytest.fixture(scope="module")
def env(wheel, tmp_path_factory):
    """시스템 site-packages 없는 깨끗한 가상환경에 wheel 만 설치 (의존성이 없으므로 --no-index 로 충분)."""
    d = tmp_path_factory.mktemp("venv")
    venv.EnvBuilder(with_pip=True, system_site_packages=False, symlinks=os.name != "nt").create(d)
    bindir = d / ("Scripts" if os.name == "nt" else "bin")
    py = bindir / ("python.exe" if os.name == "nt" else "python")
    proc = subprocess.run([str(py), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
                          capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        pytest.fail("설치 실패:\n" + proc.stderr[-2000:])
    return bindir, py


def _exe(bindir: Path, name: str) -> str:
    return str(bindir / (name + (".exe" if os.name == "nt" else "")))


def _clean_env() -> dict:
    e = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    e["PYTHONUTF8"] = "1"
    return e


def test_installed_html(env, tmp_path):
    bindir, py = env
    out = tmp_path / "o.html"
    # 소스 트리가 아니라 설치본을 쓰는지: 다른 폴더에서 실행
    proc = subprocess.run([_exe(bindir, "htex"), "html", str(ROOT / "examples" / "oscillator.htex"),
                           "-o", str(out)], cwd=str(tmp_path), env=_clean_env(),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    html = out.read_text("utf-8")
    assert "<math" in html and "조화 진동자 노트" in html
    loc = subprocess.run([str(py), "-c", "import htex,sys; print(htex.__file__); print(htex.__version__)"],
                         cwd=str(tmp_path), env=_clean_env(), capture_output=True, text=True)
    path, ver = loc.stdout.split()
    assert not Path(path).resolve().is_relative_to(ROOT) and ver == _version()
    # PySide6 같은 다른 패키지가 없는 환경인지
    pyside = subprocess.run([str(py), "-c", "import PySide6"], env=_clean_env(), capture_output=True)
    assert pyside.returncode != 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_installed_serve_and_interact_js(env, tmp_path):
    bindir, _ = env
    site = tmp_path / "site"
    site.mkdir()
    (site / "a.htex").write_text((ROOT / "examples" / "oscillator.htex").read_text("utf-8"), "utf-8")
    port = _free_port()
    proc = subprocess.Popen([_exe(bindir, "htex"), "serve", str(site), "--port", str(port)],
                            cwd=str(tmp_path), env=_clean_env(), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        base = f"http://127.0.0.1:{port}"
        body = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(base + "/__htex/interact.js", timeout=2) as r:
                    body = r.read().decode("utf-8")
                    ctype = r.headers.get("Content-Type", "")
                break
            except OSError:
                if proc.poll() is not None:
                    pytest.fail("서버가 끝남: " + proc.stderr.read().decode()[-2000:])
                time.sleep(0.1)
        assert body is not None, "서버 응답 없음"
        assert body == (ROOT / "htex" / "web" / "interact.js").read_text("utf-8")
        assert "javascript" in ctype
        with urllib.request.urlopen(base + "/a.htex", timeout=5) as r:
            page = r.read().decode("utf-8")
        assert "/__htex/interact.js" in page and "<math" in page
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_installed_viewer_without_pyside(env, tmp_path):
    bindir, _ = env
    exe = _exe(bindir, "htex-viewer") if os.name != "nt" else str(bindir / "htex-viewer.exe")
    assert Path(exe).exists()
    proc = subprocess.run([exe, str(ROOT / "examples" / "oscillator.htex")], env=_clean_env(),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
    if os.name != "nt":                    # 윈도의 GUI 스크립트는 stderr 가 없다
        assert "PySide6" in proc.stderr and "htex[viewer]" in proc.stderr
    v = subprocess.run([exe, "--version"], env=_clean_env(), capture_output=True, text=True, timeout=60)
    assert v.returncode == 0
    if os.name != "nt":
        assert v.stdout.strip() == f"HyperTeX viewer {_version()}"


# ---------------------------------------------------------------- 느린 것
@pytest.mark.slow
@pytest.mark.skipif(not SLOW, reason="느린 테스트: HTEX_SLOW=1 로 실행 (PyPI 필요)")
def test_install_viewer_extra(wheel, tmp_path):
    d = tmp_path / "v"
    venv.EnvBuilder(with_pip=True).create(d)
    py = d / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(py), "-m", "pip", "install", f"{wheel}[viewer]"], check=True, timeout=900)
    r = subprocess.run([str(py), "-c", "from PySide6 import QtWebEngineWidgets; import htex.viewer.app"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.slow
@pytest.mark.skipif(not SLOW, reason="느린 테스트: HTEX_SLOW=1 로 실행 (PyInstaller 필요, 1–2분)")
def test_pyinstaller_build_and_smoke(tmp_path):
    pytest.importorskip("PyInstaller")
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    dist, work = tmp_path / "dist", tmp_path / "build"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(dist),
                    "--workpath", str(work), str(ROOT / "packaging" / "pyinstaller" / "htex-viewer.spec")],
                   check=True, cwd=str(ROOT), capture_output=True, timeout=1200)
    bundle = dist / ("HyperTeX.app" if sys.platform == "darwin" else "htex-viewer")
    chk = subprocess.run([sys.executable, str(ROOT / "packaging" / "check_bundle.py"), str(bundle)],
                         capture_output=True, text=True)
    assert chk.returncode == 0, chk.stdout
    exe = (bundle / "Contents" / "MacOS" / "htex-viewer" if sys.platform == "darwin"
           else bundle / ("htex-viewer.exe" if os.name == "nt" else "htex-viewer"))
    out = tmp_path / "smoke"
    r = subprocess.run([sys.executable, str(ROOT / "packaging" / "smoke_test.py"), str(exe),
                        "--out", str(out)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    res = json.loads(Path(str(out) + ".json").read_text("utf-8"))
    assert res["frozen"] and res["title"] == "조화 진동자 노트"
