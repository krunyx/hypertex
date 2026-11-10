"""새 버전 알림 (Qt 없음, v0.8.2). 담당: R

설치 파일이 아직 코드 서명되지 않았으므로 몰래 내려받아 바꾸지 않는다. 대신 GitHub 의 최신 릴리스를 하루에
한 번 확인하고, 지금보다 새 버전이 있으면 창이 도구줄에 "업데이트" 단추를 띄워 받기 페이지로 안내한다.

- 확인 주소: GitHub REST `releases/latest` (초안·시험판은 나오지 않는다). 환경 변수 HTEX_UPDATE_URL 로 바꿀 수
  있다 (테스트는 file: 주소로 가짜 응답을 준다). HTEX_UPDATE_CHECK=0 이면 자동 확인을 하지 않는다.
- 보내는 것은 요청 하나뿐 (User-Agent 에 버전). 쿠키·식별자는 없다.
- 버전은 "v0.8.2" → (0, 8, 2). 꼬리표가 붙은 시험판("0.9.0-rc1")은 새 버전으로 치지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LATEST_URL = "https://api.github.com/repos/krunyx/hypertex/releases/latest"
DOWNLOAD_PAGE = "https://krunyx.com/hypertex/download/"
CHECK_INTERVAL = 24 * 3600          # 자동 확인 간격 (초)
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str             # "0.8.3"
    page: str                # 받기 페이지
    notes: str = ""          # 릴리스 노트 주소


def parse_version(s: str) -> Optional[tuple[int, int, int]]:
    m = _VERSION.match((s or "").strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def check_url() -> str:
    return os.environ.get("HTEX_UPDATE_URL") or LATEST_URL


def auto_check_allowed() -> bool:
    return os.environ.get("HTEX_UPDATE_CHECK", "1") not in ("0", "false", "no")


def due(last_check: float, now: float) -> bool:
    return not last_check or now - last_check >= CHECK_INTERVAL or now < last_check


def _read(url: str, current: str, timeout: float) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "file":                      # 테스트용 (HTEX_UPDATE_URL)
        try:
            return Path(urllib.request.url2pathname(parts.path)).read_bytes()
        except OSError as e:
            raise UpdateError(str(e)) from e
    if parts.scheme != "https":
        raise UpdateError("https only")
    from .core import tls_context
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"HyperTeX/{current}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=tls_context()[0]) as r:
            return r.read(1_000_000)
    except Exception as e:   # noqa: BLE001 - 네트워크 오류는 모두 "확인 못 함"
        raise UpdateError(str(e)) from e


def latest(current: str, url: Optional[str] = None, timeout: float = 10) -> Optional[UpdateInfo]:
    """새 버전이 있으면 UpdateInfo, 지금이 최신이면 None. 확인하지 못하면 UpdateError."""
    raw = _read(url or check_url(), current, timeout)
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise UpdateError("bad response") from e
    if not isinstance(d, dict) or d.get("draft") or d.get("prerelease"):
        raise UpdateError("no release")
    tag = str(d.get("tag_name") or "")
    if parse_version(tag) is None:
        raise UpdateError("bad version")
    if not is_newer(tag, current):
        return None
    notes = str(d.get("html_url") or "")
    if not notes.startswith("https://"):
        notes = ""
    return UpdateInfo(tag.lstrip("v"), DOWNLOAD_PAGE, notes)
