"""명령줄: python -m htex parse 문서.htex [-o 트리.json]
         python -m htex html 문서.htex [-o 결과.html]
         python -m htex serve 폴더 [--port 8000] [--host 127.0.0.1]   (웹 폴백 서버, 담당 G)
         python -m htex build 폴더 -o 출력폴더                        (정적 사이트, 담당 G)
         python -m htex view [문서.htex | htex://주소 …]              (전용 뷰어, PySide6 필요, 담당 F)
         htex-viewer [문서.htex | htex://주소 …]                      (GUI 진입점 gui_main, 담당 I)"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .parser import parse_file


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="htex")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("parse", "html"):
        sp = sub.add_parser(name)
        sp.add_argument("file", type=Path)
        sp.add_argument("-o", "--output", type=Path)
    # --- G: 웹 폴백 ---
    sp = sub.add_parser("serve", help="폴더의 HyperTeX 문서를 일반 브라우저용으로 제공")
    sp.add_argument("dir", type=Path)
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--host", default="127.0.0.1")
    sp = sub.add_parser("build", help="폴더를 정적 HTML 사이트로")
    sp.add_argument("dir", type=Path)
    sp.add_argument("-o", "--output", type=Path, required=True)
    # --- F: 전용 뷰어 ---
    sp = sub.add_parser("view", help="전용 뷰어로 열기 (PySide6 필요)")
    sp.add_argument("targets", nargs="*", metavar="target",
                    help="파일 경로, htex:// 또는 https:// 주소 (여러 개 가능)")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from .web.server import serve
        return serve(args.dir, args.host, args.port)
    if args.cmd == "build":
        from .web.build import build
        rep = build(args.dir, args.output, quiet=False)
        return 1 if rep.errors else 0
    if args.cmd == "view":
        return _view(args.targets)

    tree = parse_file(args.file)
    if args.cmd == "parse":
        out = json.dumps(tree, ensure_ascii=False, indent=2)
    else:
        from .html import render
        out = render(tree)
    if args.output:
        args.output.write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out + "\n")
    return 0


def _view(targets) -> int:
    """전용 뷰어를 띄운다. targets: 파일 경로·주소 목록 (비어 있으면 빈 창)."""
    targets = [str(t) for t in (targets or [])]
    try:
        import PySide6  # noqa: F401
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        _err(
            "htex view 에는 PySide6(QtWebEngine 포함)가 필요합니다.\n"
            "  설치: python -m pip install PySide6   (또는 pip install 'htex[viewer]')\n"
            "그동안은 'python -m htex html 문서.htex -o 문서.html' 로 만든 HTML 을 브라우저에서 볼 수 있습니다.\n")
        return 2
    from .viewer.app import run
    return _call_run(run, targets)


def _err(msg: str) -> None:
    # GUI 실행(pythonw, PyInstaller --windowed)에서는 sys.stderr 가 None 일 수 있다.
    if sys.stderr is not None:
        sys.stderr.write(msg)


def _call_run(run, targets: list) -> int:
    """run(targets) 호출. (I·J 사이 약속: run 은 list[str] 를 받는다.)

    호환: J 의 변경이 합쳐지기 전의 run(target: str | None) 이면 첫 번째 대상만 넘긴다.
    J 결과가 합쳐지면 이 함수는 `return run(targets)` 한 줄로 정리한다."""
    import inspect
    try:
        params = list(inspect.signature(run).parameters.values())
    except (TypeError, ValueError):
        params = []
    first = params[0] if params else None
    takes_list = first is not None and (
        first.name in ("targets", "target_list")
        or "list" in str(first.annotation).lower()
        or "sequence" in str(first.annotation).lower()
        or "iterable" in str(first.annotation).lower())
    if takes_list:
        return run(targets)
    if len(targets) > 1:
        _err("htex: 이 뷰어 버전은 대상을 하나만 엽니다. 첫 번째만 엽니다: %s\n" % targets[0])
    return run(targets[0] if targets else None)


def gui_main(argv=None) -> int:
    """GUI 진입점 (htex-viewer, PyInstaller 실행 파일, OS 파일·URL 연결).

    인수 = 파일 경로나 주소 여러 개. 옵션 해석은 하지 않는다 (OS 가 넘기는 인수를 그대로 받는다).
    macOS 가 붙이는 -psn_… 인수와 Qt/Chromium 옵션(-로 시작)은 대상에서 뺀다."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in (["--version"], ["-V"]):
        from . import __version__
        if sys.stdout is not None:
            sys.stdout.write("HyperTeX viewer %s\n" % __version__)
        return 0
    targets = [a for a in args if a and not a.startswith("-")]
    return _view(targets)


if __name__ == "__main__":
    sys.exit(main())
