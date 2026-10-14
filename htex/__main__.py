"""명령줄: python -m htex parse 문서.htex [-o 트리.json]
         python -m htex html 문서.htex [-o 결과.html]"""
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
    args = ap.parse_args(argv)

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
