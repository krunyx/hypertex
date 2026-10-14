#!/usr/bin/env python3
"""파서 출력과 정답 트리 대조 (docs/tree-conventions.md "대조할 때 무시하는 것").

    python tools/compare.py                # out/ 과 tests/trees/ 전체
    python tools/compare.py 06 13 -v       # 골라서, 차이를 전부 출력

먼저 python tools/run_all.py 로 out/ 을 만들어 둔다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_WS = re.compile(r"\s+")


def normalize(x, key=None):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k in ("span", "sha256"):
                continue
            v = normalize(v, k)
            if v is not None:
                out[k] = v
        return out
    if isinstance(x, list):
        return [normalize(v) for v in x]
    if isinstance(x, str) and key == "tex":
        return _tex_ws(x)
    if isinstance(x, str) and key == "source":
        return _WS.sub(" ", x).strip()
    if key in ("scripts", "params") and x == []:
        return None
    return x


def _tex_ws(t: str) -> str:
    """수식 모드의 공백은 의미가 없다. 제어어 뒤에 글자가 이어질 때만 구분 공백 하나를 남긴다."""
    t = _WS.sub(" ", t).strip()
    return re.sub(r"(?<!\\)(\\[A-Za-z]+) (?=[A-Za-z])|(?<!\\)(\\[A-Za-z]+)? ",
                  lambda m: (m.group(1) + "\x00") if m.group(1) else (m.group(2) or ""), t).replace("\x00", " ")


def diag_summary(tree):
    return Counter((d["severity"], d["code"]) for d in tree.get("diagnostics", []))


def diff(a, b, path="", out=None, limit=50):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path}: 파서 {_short(a)} / 정답 {_short(b)}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}/{k}: 파서에 없음 (정답 {_short(b[k])})")
            elif k not in b:
                out.append(f"{path}/{k}: 정답에 없음 (파서 {_short(a[k])})")
            else:
                diff(a[k], b[k], f"{path}/{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: 길이 파서 {len(a)} / 정답 {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append(f"{path}: 파서 {_short(a)} / 정답 {_short(b)}")
    return out


def _short(v, n=70):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def compare(cid: str, out_dir: Path):
    a = json.loads((out_dir / f"{cid}.tree.json").read_text(encoding="utf-8"))
    b = json.loads((ROOT / "tests" / "trees" / f"{cid}.tree.json").read_text(encoding="utf-8"))
    problems = []
    da, db = diag_summary(a), diag_summary(b)
    if da != db:
        problems.append(f"진단: 파서 {dict(da)} / 정답 {dict(db)}")
    for t in (a, b):
        t.pop("diagnostics", None)
    problems += diff(normalize(a), normalize(b))
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*")
    ap.add_argument("--out", type=Path, default=ROOT / "out")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    ids = sorted(p.name[: -len(".tree.json")] for p in (ROOT / "tests" / "trees").glob("*.tree.json"))
    ids = [i for i in ids if not args.only or any(i.startswith(o) for o in args.only)]
    same = 0
    for cid in ids:
        if not (args.out / f"{cid}.tree.json").exists():
            print(f"[없음] {cid}")
            continue
        probs = compare(cid, args.out)
        if not probs:
            same += 1
            print(f"[같음] {cid}")
        else:
            print(f"[다름] {cid}  ({len(probs)}곳)")
            for p in probs[: None if args.verbose else 4]:
                print(f"    {p}")
    print(f"\n같음 {same}/{len(ids)}")
    return 0 if same == len(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
