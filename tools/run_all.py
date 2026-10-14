#!/usr/bin/env python3
"""모든 사례를 파서로 돌려 out/<id>.tree.json 을 만들고 manifest 기대값으로 검사한다.

    python tools/run_all.py                 # 전체
    python tools/run_all.py 15 16 17        # 사례 번호 앞부분으로 골라서
    python tools/run_all.py --quiet         # 실패 사유 없이 표만
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import check  # noqa: E402
from htex import parse_file  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*", help="사례 id 앞부분 (예: 06 또는 06-math)")
    ap.add_argument("--out", type=Path, default=ROOT / "out")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    cases = check.load_manifest()
    selected = [c for cid, c in cases.items()
                if not args.only or any(cid.startswith(p) for p in args.only)]

    passed = 0
    for case in selected:
        out = args.out / f"{case['id']}.tree.json"
        try:
            tree = parse_file(ROOT / "tests" / case["file"])
            out.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
            rep = check.check_file(out, case)
        except Exception:  # 파서가 예외를 던지는 것 자체가 명세 7절 위반
            rep = check.Report(case["id"])
            rep.fail("파서 예외:\n" + traceback.format_exc(limit=3))
        passed += rep.ok
        if args.quiet:
            print(f"[{'PASS' if rep.ok else 'FAIL'}] {case['id']}")
        else:
            rep.print()
    print(f"\n통과 {passed}/{len(selected)}")
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    sys.exit(main())
