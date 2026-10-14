"""pytest 출력(tee로 저장한 파일)에서 실패·시간 초과를 찾아 GitHub Actions 주석(::error)으로 낸다.

로그 파일을 내려받지 않고도 실패 내용을 GitHub 화면과 check-run 주석 API에서 바로 볼 수 있게 하려는 것.
사용: python .github/ci_annotate.py pytest.log [제목 접두어]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MAX = 3500  # 주석 하나에 담을 최대 글자 수


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def emit(title: str, body: str) -> None:
    body = body.strip()
    if len(body) > MAX:
        body = "…" + body[-MAX:]
    print(f"::error title={esc(title)}::{esc(body)}")


def main() -> int:
    path = Path(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else "pytest"
    if not path.exists():
        emit(f"{prefix}: 로그 없음", f"{path} 이 없다")
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    n = 0
    # 1) 실패한 테스트별 상세 (==== FAILURES ==== 아래 ____ 이름 ____ 블록)
    for m in re.finditer(r"^_{3,} (.+?) _{3,}\n(.*?)(?=^_{3,} |^={3,} )", text, re.S | re.M):
        name, body = m.group(1), m.group(2)
        emit(f"{prefix}: {name}", body)
        n += 1
        if n >= 10:
            break
    # 2) pytest-timeout 이 남긴 스택 (+++++ Timeout +++++)
    for m in re.finditer(r"^\++ Timeout \++\n(.*?)(?=^\++ Timeout \++|\Z)", text, re.S | re.M):
        emit(f"{prefix}: 시간 초과", m.group(1)[:MAX])
        n += 1
    # 3) 요약 줄
    summary = [ln for ln in text.splitlines() if re.match(r"^(FAILED|ERROR) ", ln)]
    tail = "\n".join(text.splitlines()[-30:])
    if summary:
        emit(f"{prefix}: 요약", "\n".join(summary[:40]))
    elif n == 0:
        emit(f"{prefix}: 마지막 출력", tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
