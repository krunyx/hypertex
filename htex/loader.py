"""관련 파일 가져오기와 주소 검사 (명세 2절 URL 스킴, 7절 보안).

\\usemacros, \\usestyle, \\includegraphics, \\input(호환 모드), \\transclude 가 쓴다.
파서는 네트워크에 접근하지 않는다: 상대 주소만 로컬에서 읽고, htex:// · https:// 는
주소만 기록한다 (가져오기는 뷰어의 일).
"""
from __future__ import annotations

import contextvars
import re
from pathlib import Path
from typing import Optional

from .diagnostics import Sink, Span

_FORBIDDEN = re.compile(r"^(javascript|data|file|http|ftp|vbscript):", re.IGNORECASE)
_ABSOLUTE = re.compile(r"^(htex|https)://", re.IGNORECASE)

# 찾지 못한 상대 주소를 모을 목록 (뷰어가 원격 문서의 \input 등을 가져오려고 파싱 동안 넣어 둔다, 10단계 Q).
# 목록이 있으면 read_text 가 (주소, 시도한 확장자들) 을 더한다. 파서는 여전히 네트워크에 닿지 않는다.
MISSING: "contextvars.ContextVar[Optional[list]]" = contextvars.ContextVar("htex_loader_missing", default=None)


def classify(url: str) -> str:
    """'forbidden' | 'absolute' | 'relative'"""
    u = url.strip()
    if _FORBIDDEN.match(u):
        return "forbidden"
    if _ABSOLUTE.match(u):
        return "absolute"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", u):  # 그 밖의 스킴 (mailto: 등)
        return "forbidden"
    return "relative"


def check_url(url: str, span: Optional[Span], sink: Sink) -> bool:
    """허용되는 주소면 True. 아니면 insecure-resource 진단을 남기고 False."""
    if classify(url) == "forbidden":
        sink.add("insecure-resource", f"허용되지 않는 주소: {url}", span)
        return False
    return True


class Loader:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()

    def read_text(self, url: str, span: Optional[Span], sink: Sink,
                  extensions: tuple[str, ...] = ("",)) -> Optional[str]:
        """상대 주소의 파일을 읽는다. 금지 주소 → insecure-resource, 절대 주소 → None(진단 없음),
        없는 파일 → missing-resource. extensions는 확장자 생략 시 시도할 것 (예: ("", ".tex"))."""
        kind = classify(url)
        if kind == "forbidden":
            sink.add("insecure-resource", f"허용되지 않는 주소: {url}", span)
            return None
        if kind == "absolute":
            return None
        for ext in extensions:
            p = (self.base_dir / (url + ext)).resolve()
            # 문서 폴더 밖으로 나가는 상대 경로(../../etc/passwd)는 막는다
            if self.base_dir not in p.parents and p != self.base_dir:
                sink.add("insecure-resource", f"문서 폴더 밖의 경로: {url}", span)
                return None
            if p.is_file():
                return p.read_text(encoding="utf-8")
        missing = MISSING.get()
        if missing is not None:
            missing.append((url, tuple(extensions)))
        sink.add("missing-resource", f"파일을 찾을 수 없다: {url}", span)
        return None
