#!/usr/bin/env python3
"""HyperTeX 2.0 문서 트리 검사기.

파서 구현이 만든 문서 트리(JSON)를
  1) 스키마에 맞는지,
  2) 내부 일관성(노드 id 유일, 라벨이 실제 노드를 가리킴)이 있는지,
  3) tests/manifest.json의 기대값과 일치하는지
확인한다.

사용법
  python tools/check.py TREE.json                      # 스키마 + 일관성만
  python tools/check.py TREE.json --case 06-math-basic # 기대값까지
  python tools/check.py --all TREE_DIR                 # TREE_DIR/<id>.tree.json 전체

필요 패키지: jsonschema (pip install jsonschema)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover
    sys.exit("jsonschema가 필요합니다: pip install jsonschema")

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "document-tree.schema.json"
MANIFEST_PATH = ROOT / "tests" / "manifest.json"

# 블록 안에서 자식 노드가 들어 있는 키
CHILD_KEYS = ("children", "content", "title", "caption", "note", "term")


# ---------------------------------------------------------------- 트리 순회
def walk(node):
    """트리의 모든 dict 노드를 문서 순서대로 낸다 (행·항목·단계 포함)."""
    if isinstance(node, list):
        for x in node:
            yield from walk(x)
        return
    if not isinstance(node, dict):
        return
    yield node
    for key in CHILD_KEYS:
        if key in node:
            yield from walk(node[key])
    for key in ("items", "steps", "rows"):
        if key in node:
            yield from walk(node[key])
    if "cells" in node:
        for cell in node["cells"]:
            yield from walk(cell.get("content", []))
    # math, target, resolved 등은 노드가 아니므로 내려가지 않는다


def body_nodes(tree):
    yield from walk(tree["body"])
    meta = tree.get("meta", {})
    yield from walk(meta.get("abstract", []))


# ---------------------------------------------------------------- 검사
class Report:
    def __init__(self, name: str):
        self.name = name
        self.errors: list[str] = []

    def fail(self, msg: str):
        self.errors.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors

    def print(self):
        mark = "PASS" if self.ok else "FAIL"
        print(f"[{mark}] {self.name}")
        for e in self.errors:
            print(f"    - {e}")


def check_schema(tree, rep: Report):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errs = sorted(validator.iter_errors(tree), key=lambda e: list(e.absolute_path))
    for e in errs[:20]:
        # oneOf 실패는 가장 그럴듯한 하위 오류를 보여줘야 원인이 보인다
        e = _deepest(e)
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        rep.fail(f"스키마: {path}: {e.message[:200]}")
    if len(errs) > 20:
        rep.fail(f"스키마: 그 외 {len(errs) - 20}건")
    return not errs


def _deepest(err):
    """oneOf의 모든 하위 오류 중 문서 안 가장 깊은 위치의 것. 그것이 실제 원인일 가능성이 높다."""
    best, stack = err, [err]
    while stack:
        e = stack.pop()
        if len(e.absolute_path) > len(best.absolute_path):
            best = e
        stack.extend(e.context)
    return best


def check_consistency(tree, rep: Report):
    ids = Counter(n["id"] for n in body_nodes(tree) if "id" in n)
    for i, c in ids.items():
        if c > 1:
            rep.fail(f"일관성: 노드 id {i}가 {c}번 쓰였다")
    for label, tgt in tree["labels"].items():
        if tgt["node"] not in ids:
            rep.fail(f"일관성: 라벨 {label}이 없는 노드 {tgt['node']}를 가리킨다")
    for d in tree["diagnostics"]:
        if "node" in d and d["node"] not in ids:
            rep.fail(f"일관성: 진단 {d['code']}이 없는 노드 {d['node']}를 가리킨다")
    names = {p["name"] for p in tree["parameters"]}
    for n in body_nodes(tree):
        for p in n.get("params", []) + n.get("math", {}).get("params", []):
            if p not in names:
                rep.fail(f"일관성: 선언되지 않은 매개변수 {p}를 참조한다")
        if n.get("kind") == "showparam" and n["name"] not in names:
            rep.fail(f"일관성: \\showparam이 선언되지 않은 {n['name']}를 가리킨다 (오류 노드여야 함)")
    for p in tree["parameters"]:
        if not (p["min"] <= p["default"] <= p["max"]):
            rep.fail(f"일관성: 매개변수 {p['name']}의 기본값이 범위 밖이다")


def _subset(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and _subset(v, actual[k]) for k, v in expected.items())
    return expected == actual


def check_expect(tree, exp: dict, rep: Report):
    nodes = list(body_nodes(tree))
    by_id = {n["id"]: n for n in nodes if "id" in n}

    if "mode" in exp:
        mode = tree.get("source", {}).get("mode")
        if mode != exp["mode"]:
            rep.fail(f"mode: 기대 {exp['mode']}, 실제 {mode}")

    for k, v in exp.get("meta", {}).items():
        if tree["meta"].get(k) != v:
            rep.fail(f"meta.{k}: 기대 {v!r}, 실제 {tree['meta'].get(k)!r}")
    for k, v in exp.get("metaLengths", {}).items():
        n = len(tree["meta"].get(k, []))
        if n != v:
            rep.fail(f"meta.{k} 개수: 기대 {v}, 실제 {n}")

    kinds = Counter(n.get("kind") for n in nodes)
    for k, v in exp.get("count", {}).items():
        if kinds[k] != v:
            rep.fail(f"{k} 노드 수: 기대 {v}, 실제 {kinds[k]}")

    for label, want in exp.get("labels", {}).items():
        got = tree["labels"].get(label)
        if got is None:
            rep.fail(f"라벨 {label} 없음")
        elif not _subset(want, got):
            rep.fail(f"라벨 {label}: 기대 {want}, 실제 {{kind: {got.get('kind')}, number: {got.get('number')}}}")

    if exp.get("labels") == {} and tree["labels"]:
        rep.fail(f"라벨이 없어야 하는데 {len(tree['labels'])}개 있다")

    links = [n for n in nodes if n.get("kind") == "link"]
    for want in exp.get("links", []):
        if not any(_link_matches(want, l) for l in links):
            rep.fail(f"링크 없음: {want}")

    if "bibKeys" in exp:
        keys = [b["key"] for b in tree["bibliography"]]
        if keys != exp["bibKeys"]:
            rep.fail(f"참고문헌 키: 기대 {exp['bibKeys']}, 실제 {keys}")

    if "parameters" in exp:
        got = tree["parameters"]
        if len(got) != len(exp["parameters"]):
            rep.fail(f"매개변수 수: 기대 {len(exp['parameters'])}, 실제 {len(got)}")
        for want, g in zip(exp["parameters"], got):
            if not _subset(want, g):
                rep.fail(f"매개변수: 기대 {want}, 실제 {g}")

    if "pictures" in exp:
        n = sum(1 for x in nodes if x.get("kind") == "picture" and x.get("usesPgfplots"))
        if n != exp["pictures"]["usesPgfplots"]:
            rep.fail(f"pgfplots 그림 수: 기대 {exp['pictures']['usesPgfplots']}, 실제 {n}")

    if "collapsedProofs" in exp:
        n = sum(1 for x in nodes if x.get("kind") == "proof" and x.get("collapsed"))
        if n != exp["collapsedProofs"]:
            rep.fail(f"접힌 증명 수: 기대 {exp['collapsedProofs']}, 실제 {n}")

    for label, scripts in exp.get("mathScripts", {}).items():
        tgt = tree["labels"].get(label)
        node = by_id.get(tgt["node"]) if tgt else None
        got = (node or {}).get("math", {}).get("scripts", [])
        missing = [s for s in scripts if s not in got]
        if missing:
            rep.fail(f"{label} 수식의 문자 체계에 {missing} 없음 (실제 {got})")

    diag = exp.get("diagnostics")
    if diag is not None:
        got = Counter(d["code"] for d in tree["diagnostics"])
        if "exact" in diag:
            if dict(got) != diag["exact"]:
                rep.fail(f"진단: 기대 정확히 {diag['exact']}, 실제 {dict(got)}")
        for code, n in diag.get("atLeast", {}).items():
            if got[code] < n:
                rep.fail(f"진단 {code}: 기대 {n}개 이상, 실제 {got[code]}")


def _link_matches(want: dict, link: dict) -> bool:
    if link["linkType"] != want["linkType"]:
        return False
    tgt, res = link.get("target", {}), link.get("resolved", {})
    for key in ("doc", "label", "url", "keys"):
        if key in want and tgt.get(key) != want[key]:
            return False
    if "number" in want and res.get("number") != want["number"]:
        return False
    if want.get("broken") and not res.get("broken"):
        return False
    return True


# ---------------------------------------------------------------- 실행
def load_manifest():
    return {c["id"]: c for c in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["cases"]}


def check_file(path: Path, case: dict | None) -> Report:
    rep = Report(f"{path.name}" + (f"  ({case['id']})" if case else ""))
    try:
        tree = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        rep.fail(f"읽기 실패: {e}")
        return rep
    if check_schema(tree, rep):  # 스키마가 깨지면 나머지 검사는 의미가 없다
        check_consistency(tree, rep)
        if case:
            check_expect(tree, case["expect"], rep)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tree", nargs="?", type=Path, help="검사할 문서 트리 JSON")
    ap.add_argument("--case", help="manifest의 사례 id")
    ap.add_argument("--all", type=Path, metavar="DIR", help="DIR/<id>.tree.json 전체 검사")
    args = ap.parse_args(argv)

    cases = load_manifest()
    reports: list[Report] = []

    if args.all:
        missing = []
        for cid, case in cases.items():
            p = args.all / f"{cid}.tree.json"
            if p.exists():
                reports.append(check_file(p, case))
            else:
                missing.append(cid)
        for r in reports:
            r.print()
        passed = sum(r.ok for r in reports)
        print(f"\n통과 {passed}/{len(cases)}, 실패 {len(reports) - passed}, 트리 없음 {len(missing)}")
        return 0 if passed == len(reports) else 1

    if not args.tree:
        ap.error("TREE.json 또는 --all DIR이 필요합니다")
    if args.case and args.case not in cases:
        ap.error(f"manifest에 없는 사례: {args.case}")
    rep = check_file(args.tree, cases.get(args.case) if args.case else None)
    rep.print()
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
