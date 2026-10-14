"""PyInstaller 결과물 점검: QtWebEngine 실행에 필요한 파일과 htex 패키지 데이터가 들어 있는지,
(리눅스) 동봉한 ELF 들이 찾는 Qt 라이브러리가 모두 있는지 확인한다.

사용: python packaging/check_bundle.py dist/htex-viewer        (Linux/Windows)
      python packaging/check_bundle.py dist/HyperTeX.app       (macOS)
문제가 있으면 목록을 찍고 1 로 끝난다. CI 빌드 단계에서 돈다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _any(root: Path, pattern: str) -> list[Path]:
    return list(root.rglob(pattern))


def check(root: Path) -> list[str]:
    problems: list[str] = []
    if not root.exists():
        return [f"없음: {root}"]
    need = {
        "htex/web/interact.js": "interact.js",
        "QtWebEngineProcess": "QtWebEngineProcess*",
        "icudtl.dat": "icudtl.dat",
        "qtwebengine_resources.pak": "qtwebengine_resources.pak",
        "qtwebengine_locales/en-US.pak": "en-US.pak",
    }
    for what, pat in need.items():
        if not _any(root, pat):
            problems.append(f"빠짐: {what}")
    js = _any(root, "interact.js")
    if js and js[0].parent.name != "web":
        problems.append(f"interact.js 위치가 htex/web 이 아님: {js[0]}")
    if sys.platform.startswith("linux"):
        problems += _check_elf(root)
    return problems


def _check_elf(root: Path) -> list[str]:
    """번들 안 ELF 가 NEEDED 로 찾는 libQt6*·libpyside6*·libshiboken6* 가 번들에 있는지."""
    have = {p.name for p in root.rglob("*") if p.is_file()}
    missing: dict[str, set[str]] = {}
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            with open(p, "rb") as f:
                if f.read(4) != b"\x7fELF":
                    continue
        except OSError:
            continue
        try:
            out = subprocess.run(["readelf", "-d", str(p)], capture_output=True, text=True).stdout
        except FileNotFoundError:
            return []                       # readelf 없음: 건너뜀
        for line in out.splitlines():
            if "(NEEDED)" not in line:
                continue
            lib = line.split("[", 1)[1].rstrip("]")
            if lib.startswith(("libQt6", "libpyside6", "libshiboken6", "libicu")) and lib not in have:
                missing.setdefault(lib, set()).add(p.name)
    # Qt 플러그인 중 쓰지 않는 플랫폼(eglfs 등)이 빠진 라이브러리를 찾는 것은 문제 아님. 핵심 모듈만 오류로.
    core = ("libQt6WebEngine", "libQt6Widgets", "libQt6Gui", "libQt6Core", "libQt6Quick", "libQt6Qml",
            "libQt6Network", "libQt6WebChannel", "libQt6Positioning", "libQt6PrintSupport", "libQt6OpenGL",
            "libQt6XcbQpa", "libpyside6", "libshiboken6")
    out = []
    for lib, users in sorted(missing.items()):
        users_core = {u for u in users if u.startswith(core) or u.endswith(".abi3.so")
                      or u in ("QtWebEngineProcess", "libqxcb.so", "libqoffscreen.so")}
        if users_core:
            out.append(f"라이브러리 빠짐: {lib} (필요: {', '.join(sorted(users_core))})")
    return out


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    root = Path(args[0])
    problems = check(root)
    size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    print(f"{root}: {size / 1e6:.0f} MB")
    for p in problems:
        print("  - " + p)
    print("문제 없음" if not problems else f"문제 {len(problems)}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
