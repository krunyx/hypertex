"""빌드한 뷰어 실행 파일을 화면 없이 띄워 예제 문서를 불러오고 창 스크린숏을 남긴다 (Linux·macOS·Windows).

사용: python packaging/smoke_test.py <실행 파일> [문서] [--out 접두어] [--timeout 초]
  <실행 파일>: dist/htex-viewer/htex-viewer(.exe), dist/HyperTeX.app/Contents/MacOS/htex-viewer, AppImage
  결과: <접두어>.png, <접두어>.json  (기본 접두어: dist/smoke)
성공 조건: 문서 제목이 나오고, 상호작용 스크립트(window.HTEX)가 실행되고, MathML 이 있다.
그다음 PDF 그림(--no-pdf 로 건너뜀)과 원문 편집기(--no-edit 로 건너뜀)도 확인한다.

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


def run(exe: Path, doc: Path, out: str, timeout: float, edit: bool = False) -> dict:
    env = dict(os.environ)
    if edit:
        env["HTEX_SMOKE_EDIT"] = "1"
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
    ap.add_argument("--no-pdf", action="store_true", help="PDF 그림 확인을 건너뛴다")
    ap.add_argument("--no-edit", action="store_true", help="원문 편집기 확인을 건너뛴다")
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
    # https: 운영체제 인증서 저장소(system)나 certifi 를 써야 다른 컴퓨터에서도 인증서를 확인한다
    if ok and res.get("tls") not in ("system", "certifi"):
        print("https 인증서: 실패 (tls =", res.get("tls"), ") — truststore·certifi 가 묶이지 않았다")
        ok = False
    if ok and not a.no_pdf:
        ok = check_pdf_figure(a.exe, a.out + "-pdf", a.timeout)
    if ok and not a.no_edit:
        ok = check_editor(a.exe, a.doc.resolve(), a.out + "-edit", a.timeout)
    return 0 if ok else 1


def check_editor(exe: Path, doc: Path, out: str, timeout: float) -> bool:
    """묶인 앱에서 원문 편집기(QWebChannel + htex/viewer/editor.js)가 뜨고 문서 줄이 보이는지."""
    res = run(exe, doc, out, timeout, edit=True)
    lines = res.get("editor_lines", -1)
    ok = bool(res.get("ok")) and isinstance(lines, (int, float)) and lines > 0
    print(json.dumps({"editor": res}, ensure_ascii=False, indent=2))
    print("원문 편집기:", "통과" if ok else "실패", f"(줄 {lines}, 스크린숏 {out}.png)")
    return ok


def check_pdf_figure(exe: Path, out: str, timeout: float) -> bool:
    """묶인 앱에 QtPdf 가 들어 있어 PDF 그림(확장자 있음·없음)이 그려지는지."""
    res = run(exe, (ROOT / "packaging" / "smoke" / "pdf-figure.tex").resolve(), out, timeout)
    try:
        js = json.loads(res.get("js") or "{}")
    except ValueError:
        js = {}
    imgs = js.get("images") or []
    ok = bool(res.get("ok")) and len(imgs) == 2 and all(w > 0 for w in imgs)
    print(json.dumps({"pdf_figure": res, "images": imgs}, ensure_ascii=False, indent=2))
    print("PDF 그림:", "통과" if ok else "실패", f"(스크린숏 {out}.png)")
    return ok


if __name__ == "__main__":
    sys.exit(main())
