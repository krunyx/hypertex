"""단일 인스턴스 메시지와 대상 문자열 정규화, 자동 새로고침용 의존 파일 찾기 (Qt 없이). (담당: J)

단일 인스턴스 (app.run 이 쓴다)
- 서버 이름: instance_name(). 환경 변수 HTEX_VIEWER_INSTANCE 가 있으면 그 값(테스트·여러 프로필용),
  없으면 "hypertex-viewer-" + sha256(사용자 이름 + 홈 폴더)[:16]. 사용자마다 다르고 같은 사용자의
  두 실행은 같은 이름을 쓴다. (Qt QLocalServer: 유닉스는 임시 폴더의 소켓 파일, 윈도는 이름 있는 파이프.)
- 메시지: UTF-8 JSON 한 줄 + "\\n".  {"v": 1, "cmd": "open", "targets": [...], "cwd": "..."}
  targets 는 보내는 쪽에서 normalize_target 으로 이미 절대 경로·주소로 바꾼 것. 받는 쪽은 "ok\\n" 으로 답한다.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

PROTOCOL_VERSION = 1
MAX_MESSAGE = 1 << 20          # 1MB: 그보다 긴 메시지는 버린다
MAX_TARGETS = 64
REPLY_OK = b"ok\n"

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")


def instance_name() -> str:
    env = os.environ.get("HTEX_VIEWER_INSTANCE")
    if env:
        return re.sub(r"[^A-Za-z0-9_.\-]", "_", env)[:80]
    try:
        user = getpass.getuser()
    except Exception:   # noqa: BLE001
        user = ""
    who = f"{user}\n{Path.home()}"
    return "hypertex-viewer-" + hashlib.sha256(who.encode("utf-8")).hexdigest()[:16]


# ====================================================================== 대상 문자열
def normalize_target(text: str, cwd: Optional[Path] = None) -> str:
    """명령줄·OS 가 넘긴 대상 하나 → 다른 프로세스(다른 현재 폴더)에서도 같은 뜻인 문자열.
    - htex:// · https:// · http:// (그 밖의 스킴 포함): 앞뒤 공백만 뗀다 (해석은 뷰어가).
    - file: URL → 파일 경로 (조각 #… 은 유지).
    - 경로: ~ 풀기, 상대 경로는 cwd 기준 절대 경로로. 단 그런 파일이 없고 'example.org/a.htex' 처럼
      도메인 모양이면 그대로 둔다 (뷰어가 https 로 본다)."""
    s = (text or "").strip()
    if not s:
        return ""
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    m = _SCHEME_RE.match(s)
    scheme = m.group(1).lower() if m else ""
    if len(scheme) == 1:                      # 윈도 드라이브 문자 C:\…, C:/…
        scheme = ""
    if scheme == "file":
        parts = urllib.parse.urlsplit(s)
        path = urllib.request.url2pathname(parts.path)
        if parts.netloc and parts.netloc.lower() not in ("", "localhost"):
            path = "//" + parts.netloc + path          # UNC (윈도 공유 폴더)
        return path + ("#" + parts.fragment if parts.fragment else "")
    if scheme:
        return s
    base, frag = s, ""
    if "#" in s and not Path(os.path.expanduser(s)).exists():
        base, _, frag = s.partition("#")
    p = Path(os.path.expanduser(base))
    if not p.is_absolute():
        cand = cwd / p
        if not cand.exists() and _looks_like_domain(base):
            return s
        p = cand
    return os.path.normpath(str(p)) + ("#" + frag if frag else "")


def _looks_like_domain(s: str) -> bool:
    if "/" not in s and s.lower().endswith((".htex", ".tex")):
        return False            # 'a.htex' 는 파일 이름이다 ('example.org/a.htex' 는 주소)
    return bool(re.match(r"^[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+(:[0-9]+)?(/|$)", s)) and not s.startswith(".")


def normalize_targets(targets: Iterable[str] | str | None, cwd: Optional[Path] = None) -> list[str]:
    if targets is None:
        return []
    if isinstance(targets, str):
        targets = [targets]
    out = []
    for t in targets:
        n = normalize_target(t, cwd)
        if n:
            out.append(n)
    return out[:MAX_TARGETS]


# ====================================================================== 메시지
def encode_message(targets: list[str], cwd: Optional[str] = None) -> bytes:
    msg = {"v": PROTOCOL_VERSION, "cmd": "open", "targets": list(targets)[:MAX_TARGETS],
           "cwd": str(cwd if cwd is not None else os.getcwd())}
    data = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(data) > MAX_MESSAGE:
        raise ValueError("message too large")
    return data


def decode_message(data: bytes) -> Optional[dict]:
    """한 줄 메시지 → {"cmd", "targets", "cwd"}. 형식이 틀리면 None (받는 쪽은 무시)."""
    if not data or len(data) > MAX_MESSAGE:
        return None
    line = data.split(b"\n", 1)[0]
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict) or msg.get("v") != PROTOCOL_VERSION or msg.get("cmd") != "open":
        return None
    targets = msg.get("targets")
    if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
        return None
    cwd = msg.get("cwd")
    return {"cmd": "open", "targets": [t for t in targets if t.strip()][:MAX_TARGETS],
            "cwd": cwd if isinstance(cwd, str) else ""}


# ====================================================================== 자동 새로고침
_DEP_RE = re.compile(
    r"\\(usemacros|usestyle|input|include|bibliography|ref|eqref|transclude)\s*\{([^{}\n]*)\}")
_DEP_EXTS = {"usemacros": ("", ".htex"), "usestyle": ("", ".hsty"), "input": ("", ".tex"),
             "include": ("", ".tex"), "bibliography": (".bbl",)}
MAX_DEPS = 64


def local_dependencies(path: Path, text: Optional[str] = None) -> list[Path]:
    """로컬 문서가 읽을 같은 폴더(그 아래 포함) 파일들, 알 수 있는 범위에서 (원문을 정규식으로 훑는다).
    \\usemacros(.htex) · \\usestyle(.hsty) · \\input/\\include(.tex) · \\bibliography(.bbl), 그리고 번호·전사를
    가져오는 다른 로컬 문서(\\ref{x.htex#…}, \\transclude{x.htex#…}). 있는 파일만, 문서 폴더 밖은 빼고.
    매크로가 만들어 낸 이름이나 \\input 안의 \\input 은 모른다(한 단계)."""
    path = Path(path).resolve()
    folder = path.parent
    if text is None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    out: dict[Path, None] = {}
    for m in _DEP_RE.finditer(_strip_comments(text)):
        cmd, arg = m.group(1), m.group(2).strip()
        names = [a.strip() for a in arg.split(",")] if cmd == "bibliography" else [arg]
        for name in names:
            if not name or _SCHEME_RE.match(name) or name.startswith(("/", "\\")):
                continue
            if cmd in ("ref", "eqref", "transclude"):
                if "#" not in name:
                    continue
                name = urllib.parse.unquote(name.split("#", 1)[0])
                if not name.lower().endswith((".htex", ".tex")):
                    continue
                exts = ("",)
            else:
                exts = _DEP_EXTS[cmd]
            for ext in exts:
                p = (folder / (name + ext)).resolve()
                if p != path and folder in p.parents and p.is_file():
                    out[p] = None
                    break
        if len(out) >= MAX_DEPS:
            break
    return list(out)


def _strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", text)


def file_signature(paths: Iterable[Path]) -> tuple:
    """파일들의 (경로, 수정 시각 ns, 크기). 없는 파일은 (경로, None, None)."""
    sig = []
    for p in paths:
        try:
            st = os.stat(p)
            sig.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((str(p), None, None))
    return tuple(sig)


__all__ = ["instance_name", "normalize_target", "normalize_targets", "encode_message",
           "decode_message", "local_dependencies", "file_signature", "REPLY_OK"]
