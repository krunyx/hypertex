"""실제 LaTeX 원고로 호환 모드(명세 9절)를 시험한다.

공개 저장소의 원고를 GitHub에서 받아 `.cache/realworld/` 에 두고 (저장소에는 넣지 않는다:
원고마다 라이선스가 다르다), 파싱·HTML 변환을 돌려 다음을 잰다.

- 예외 없이 끝나는가, 걸린 시간
- 진단 수 (심각도·코드별), 가장 흔한 정의되지 않은 명령
- 수식 가운데 MathML로 바뀌지 못하고 원문으로 남은 비율

    python tools/realworld.py                 # 받기(처음 한 번) + 전체 보고
    python tools/realworld.py --only stacks   # 이름에 stacks 가 든 문서만
    python tools/realworld.py --html out/rw   # 각 문서의 HTML도 써 둔다
    python tools/realworld.py --check         # 아래 BUDGET 을 넘으면 종료 코드 1 (회귀 검사)

새 원고는 CORPUS 에 (이름, 주 파일, [받을 파일들]) 로 더한다.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from htex import parse_file  # noqa: E402
from htex.html import render  # noqa: E402

RAW = "https://raw.githubusercontent.com/"
CACHE = ROOT / ".cache" / "realworld"

# (이름, 주 파일, {저장 경로: 내려받을 주소 또는 None(직접 만든 파일)})
HOTT_MAIN = (
    "\\documentclass{book}\n\\usepackage{amsmath,amssymb,amsthm,hyperref}\n"
    "\\input{macros}\n\\begin{document}\n\\input{basics}\n\\input{logic}\n\\end{document}\n"
)
CORPUS: list[tuple[str, str, dict[str, str | None]]] = [
    ("latex-small2e", "small2e.tex",
     {"small2e.tex": RAW + "latex3/latex2e/main/base/small2e.tex"}),
    ("latex-sample2e", "sample2e.tex",
     {"sample2e.tex": RAW + "latex3/latex2e/develop/base/sample2e.tex"}),
    ("amsmath-testmath", "testmath.tex",
     {"testmath.tex": RAW + "latex3/latex2e/develop/required/amsmath/testmath.tex"}),
    ("pandoc-latex-reader", "latex-reader.tex",
     {"latex-reader.tex": RAW + "jgm/pandoc/main/test/latex-reader.latex"}),
    ("hott-book", "hott/main.tex",
     {"hott/macros.tex": RAW + "HoTT/book/master/macros.tex",
      "hott/basics.tex": RAW + "HoTT/book/master/basics.tex",
      "hott/logic.tex": RAW + "HoTT/book/master/logic.tex",
      "hott/main.tex": None}),
    ("stacks-sets", "stacks/sets.tex",
     {"stacks/preamble.tex": RAW + "stacks/stacks-project/master/preamble.tex",
      "stacks/sets.tex": RAW + "stacks/stacks-project/master/sets.tex"}),
    ("stacks-categories", "stacks/categories.tex",
     {"stacks/preamble.tex": RAW + "stacks/stacks-project/master/preamble.tex",
      "stacks/categories.tex": RAW + "stacks/stacks-project/master/categories.tex"}),
]
GENERATED = {"hott/main.tex": HOTT_MAIN}

# 회귀 검사 한도 (2026-10-15 측정값에 여유를 둔 것): 이름 → (오류 진단 최대, 수식 실패 최대 %)
BUDGET = {
    "latex-small2e": (0, 0.0), "latex-sample2e": (2, 0.0), "amsmath-testmath": (20, 1.0),
    "pandoc-latex-reader": (15, 0.0), "hott-book": (90, 1.0), "stacks-sets": (0, 0.0),
    "stacks-categories": (10, 0.5),
}


def fetch(files: dict[str, str | None]) -> bool:
    ok = True
    for rel, url in files.items():
        dest = CACHE / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url is None:
            dest.write_text(GENERATED[rel], encoding="utf-8")
            continue
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                dest.write_bytes(r.read())
        except Exception as e:  # noqa: BLE001
            print(f"  받기 실패: {url}: {e}", file=sys.stderr)
            ok = False
    return ok


def measure(path: Path, html_dir: Path | None, name: str) -> dict:
    t0 = time.time()
    tree = parse_file(path)
    t1 = time.time()
    html = render(tree)
    t2 = time.time()
    if html_dir is not None:
        html_dir.mkdir(parents=True, exist_ok=True)
        (html_dir / f"{name}.html").write_text(html, encoding="utf-8")
    diags = tree["diagnostics"]
    sev = collections.Counter(d["severity"] for d in diags)
    codes = collections.Counter(d["code"] for d in diags)
    undefined = collections.Counter()
    for d in diags:
        if d["code"] == "undefined-command":
            m = re.search(r"\\([A-Za-z@]+)", d["message"])
            if m:
                undefined[m.group(1)] += 1
    ok_math = html.count("<math")
    bad_math = html.count('class="htex-math-error"')
    unknown = html.count('class="htex-unknown"')
    return {
        "parse": t1 - t0, "render": t2 - t1, "errors": sev.get("error", 0),
        "warnings": sev.get("warning", 0), "codes": codes, "undefined": undefined,
        "math": ok_math, "math_failed": bad_math, "unknown_in_math": unknown,
        "math_fail_pct": 100 * bad_math / max(1, ok_math + bad_math),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="이름에 이 글자가 든 문서만")
    ap.add_argument("--html", type=Path, help="HTML 을 쓸 폴더")
    ap.add_argument("--check", action="store_true", help="BUDGET 을 넘으면 실패")
    args = ap.parse_args()

    failed = []
    for name, main_file, files in CORPUS:
        if args.only and args.only not in name:
            continue
        if not fetch(files):
            print(f"== {name}: 원고를 받지 못해 건너뜀")
            continue
        try:
            r = measure(CACHE / main_file, args.html, name)
        except Exception as e:  # noqa: BLE001 - 어떤 원고도 예외를 내면 안 된다 (명세 7절)
            print(f"== {name}: 예외 {type(e).__name__}: {e}")
            failed.append(name)
            continue
        print(f"== {name}  파싱 {r['parse']:.2f}s · HTML {r['render']:.2f}s")
        print(f"   오류 {r['errors']} · 경고 {r['warnings']} · {dict(r['codes'].most_common(6))}")
        print(f"   수식 {r['math']} · 원문으로 남음 {r['math_failed']} ({r['math_fail_pct']:.1f}%)"
              f" · 수식 안 모르는 명령 {r['unknown_in_math']}")
        if r["undefined"]:
            print("   정의되지 않은 명령:", ", ".join(f"\\{k} {v}" for k, v in
                                                r["undefined"].most_common(10)))
        if args.check and name in BUDGET:
            max_err, max_pct = BUDGET[name]
            if r["errors"] > max_err or r["math_fail_pct"] > max_pct:
                print(f"   ✗ 한도 초과: 오류 ≤{max_err}, 수식 실패 ≤{max_pct}%")
                failed.append(name)
    if failed:
        print("\n실패:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
