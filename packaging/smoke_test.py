"""빌드한 뷰어 실행 파일을 화면 없이 띄워 예제 문서를 불러오고 창 스크린숏을 남긴다 (Linux·macOS·Windows).

사용: python packaging/smoke_test.py <실행 파일> [문서] [--out 접두어] [--timeout 초]
  <실행 파일>: dist/htex-viewer/htex-viewer(.exe), dist/HyperTeX.app/Contents/MacOS/htex-viewer, AppImage
  결과: <접두어>.png, <접두어>.json  (기본 접두어: dist/smoke)
성공 조건: 문서 제목이 나오고, 상호작용 스크립트(window.HTEX)가 실행되고, MathML 이 있다.

실행 파일 진입점(packaging/pyinstaller/htex_viewer_entry.py)이 HTEX_SMOKE_OUT 을 보고 동작한다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(exe: Path, doc: Path, out: str, timeout: float) -> dict:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["HTEX_SMOKE_OUT"] = out
    env["HTEX_SMOKE_TIMEOUT_MS"] = str(int(timeout * 1000 * 0.8))
    if sys.platform.startswith("linux"):
        env["HTEX_NO_SANDBOX"] = "1"            # 컨테이너·CI 러너
        env.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
    env.setdefault("XDG_CACHE_HOME", tempfile.mkdtemp(prefix="htex-smoke-cache-"))
    cmd = [str(exe), str(doc)]
    if str(exe).endswith(".AppImage"):
        cmd.insert(1, "--appimage-extract-and-run")     # FUSE 없는 환경
    for suffix in (".json", ".png"):
        Path(out + suffix).unlink(missing_ok=True)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout + 30,
                          errors="replace")
    res_path = Path(out + ".json")
    if not res_path.exists():
        return {"ok": False, "returncode": proc.returncode, "stderr": proc.stderr[-3000:]}
    res = json.loads(res_path.read_text(encoding="utf-8"))
    res["returncode"] = proc.returncode
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exe", type=Path)
    ap.add_argument("doc", type=Path, nargs="?", default=ROOT / "examples" / "oscillator.htex")
    ap.add_argument("--out", default=str(ROOT / "dist" / "smoke"))
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args(argv)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    res = run(a.exe, a.doc.resolve(), a.out, a.timeout)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    js = {}
    try:
        js = json.loads(res.get("js") or "{}")
    except ValueError:
        pass
    ok = bool(res.get("ok")) and res.get("title") and js.get("htex") == "object" and js.get("math", 0) > 0 \
        and Path(a.out + ".png").exists()
    print("스모크 테스트:", "통과" if ok else "실패", f"(스크린숏 {a.out}.png)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
