"""명령줄: python -m htex parse 문서.htex [-o 트리.json]
         python -m htex html 문서.htex [-o 결과.html]
         python -m htex serve 폴더 [--port 8000] [--host 127.0.0.1]   (웹 폴백 서버, 담당 G)
         python -m htex build 폴더 -o 출력폴더                        (정적 사이트, 담당 G)"""
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
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from .web.server import serve
        return serve(args.dir, args.host, args.port)
    if args.cmd == "build":
        from .web.build import build
        rep = build(args.dir, args.output, quiet=False)
        return 1 if rep.errors else 0

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


if __name__ == "__main__":
    sys.exit(main())
