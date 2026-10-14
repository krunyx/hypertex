"""명령줄: python -m htex parse 문서.htex [-o 트리.json]
         python -m htex html 문서.htex [-o 결과.html]
         python -m htex serve 폴더 [--port 8000] [--host 127.0.0.1]   (웹 폴백 서버, 담당 G)
         python -m htex build 폴더 -o 출력폴더                        (정적 사이트, 담당 G)
         python -m htex view [문서.htex | htex://주소]                (전용 뷰어, PySide6 필요, 담당 F)"""
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
    sp.add_argument("target", nargs="?", help="파일 경로, htex:// 또는 https:// 주소")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from .web.server import serve
        return serve(args.dir, args.host, args.port)
    if args.cmd == "build":
        from .web.build import build
        rep = build(args.dir, args.output, quiet=False)
        return 1 if rep.errors else 0
    if args.cmd == "view":
        return _view(args.target)

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


def _view(target) -> int:
    try:
        import PySide6  # noqa: F401
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "htex view 에는 PySide6(QtWebEngine 포함)가 필요합니다.\n"
            "  설치: python -m pip install PySide6\n"
            "그동안은 'python -m htex html 문서.htex -o 문서.html' 로 만든 HTML 을 브라우저에서 볼 수 있습니다.\n")
        return 2
    from .viewer.app import run
    return run(target)


if __name__ == "__main__":
    sys.exit(main())
