"""원문 편집의 Qt 없는 부분 (10단계 Q).

- 로컬 파일: open_local 로 읽고(UTF-8 만, BOM·줄바꿈 기억) save_local 로 저장한다.
  저장은 같은 폴더의 임시 파일에 쓰고 바꿔치기(os.replace)한다. 읽은 뒤 밖에서 파일이 바뀌었으면 Conflict.
  덮어쓰기 전 원본은 이번 실행에서 처음 저장할 때 한 번 백업 폴더(캐시 폴더/backups)에 복사해 둔다.
- 원격 문서(htex://): 서버에는 쓸 수 없으므로 로컬에 사본으로 저장한다. plan_remote_copy 가 본문과 함께
  그 문서가 상대 주소로 부르는 \\input·\\usemacros·\\usestyle·.bbl·그림을 같은 서버에서 가져와 묶고,
  write_copy 가 고른 폴더에 같은 상대 위치로 쓴다. 절대 주소(htex://, https://)로 부르는 것은 그대로 둔다.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterator, Optional

from .. import images
from ..i18n import tr
from .core import (DOC_EXTS, HTML_EXTS, IMAGE_TYPES, MAX_BYTES, ViewerError, htex_to_https, join_url,
                   safe_relative)

EDIT_EXTS = DOC_EXTS + HTML_EXTS
BACKUP_DAYS = 30
BOM = b"\xef\xbb\xbf"


class EditError(Exception):
    """사용자에게 그대로 보일 수 있는 편집·저장 오류."""


class Conflict(EditError):
    """편집기에 읽어 들인 뒤 다른 프로그램이 파일을 바꿨다."""


def editable(path: Path) -> bool:
    return Path(path).suffix.lower() in EDIT_EXTS


def mode_of(name: str) -> str:
    """편집기 문법 강조 이름: tex · md · html."""
    low = name.lower().split("?", 1)[0].split("#", 1)[0]
    if low.endswith((".md", ".markdown")):
        return "md"
    if low.endswith(HTML_EXTS):
        return "html"
    return "tex"


def signature(path: Path) -> Optional[tuple[int, int]]:
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


@dataclass(frozen=True)
class LocalSource:
    path: Path
    text: str                    # 줄바꿈은 \n 으로 (편집기와 같게)
    bom: bool = False
    newline: str = "\n"
    sig: Optional[tuple[int, int]] = None


def split_text(data: bytes, name: str = "") -> tuple[str, bool, str]:
    """바이트 → (\\n 줄바꿈 원문, BOM 여부, 원래 줄바꿈). UTF-8 이 아니면 EditError."""
    bom = data.startswith(BOM)
    if bom:
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise EditError(tr('UTF-8 이 아닌 파일은 편집할 수 없습니다: {name}', name=name)) from None
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), bom, newline


def open_local(path: Path) -> LocalSource:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise EditError(tr('파일이 너무 커서 편집할 수 없습니다: {name}', name=path.name))
        data = path.read_bytes()
    except OSError as e:
        raise EditError(tr('파일을 읽지 못했습니다: {name} ({e})', name=path.name, e=e)) from None
    text, bom, newline = split_text(data, path.name)
    return LocalSource(path, text, bom, newline, signature(path))


def encode_text(text: str, bom: bool = False, newline: str = "\n") -> bytes:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline != "\n":
        text = text.replace("\n", newline)
    return (BOM if bom else b"") + text.encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    """같은 폴더의 임시 파일에 다 쓴 뒤 바꿔치기. 원래 파일의 권한은 유지."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".htex-tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            try:
                shutil.copymode(path, tmp)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def default_backup_dir() -> Path:
    from .core import default_cache_dir
    return default_cache_dir() / "backups"


def backup(path: Path, backup_dir: Path, now: Optional[float] = None) -> Optional[Path]:
    """저장하기 전 원본을 백업 폴더에 복사 (이름: 날짜-경로해시-파일이름). 오래된 백업은 지운다."""
    path = Path(path)
    if not path.is_file():
        return None
    now = time.time() if now is None else now
    backup_dir.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    dest = backup_dir / f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}-{tag}-{path.name}"
    shutil.copy2(path, dest)
    for old in backup_dir.iterdir():
        try:
            if old.is_file() and now - old.stat().st_mtime > BACKUP_DAYS * 86400:
                old.unlink()
        except OSError:
            pass
    return dest


def save_local(src: LocalSource, text: str, backup_dir: Optional[Path] = None,
               force: bool = False) -> LocalSource:
    """편집한 원문을 그 파일에 저장. 읽은 뒤 밖에서 바뀌었으면(force 아니면) Conflict.
    backup_dir 이 있으면 덮어쓰기 전 원본을 복사해 둔다."""
    cur = signature(src.path)
    if not force and cur is not None and src.sig is not None and cur != src.sig:
        raise Conflict(tr('다른 프로그램이 파일을 바꿨습니다: {name}', name=src.path.name))
    try:
        if backup_dir is not None and cur is not None:
            try:
                backup(src.path, backup_dir)
            except OSError:
                pass                    # 백업을 못 해도 저장은 한다
        atomic_write(src.path, encode_text(text, src.bom, src.newline))
    except OSError as e:
        raise EditError(tr('저장하지 못했습니다: {name} ({e})', name=src.path.name, e=e)) from None
    return replace(src, text=text.replace("\r\n", "\n").replace("\r", "\n"), sig=signature(src.path))


# ====================================================================== 원격 문서 → 로컬 사본
@dataclass
class RemoteCopy:
    main: str                                        # 본문 파일 이름 (고른 이름)
    files: dict[str, bytes] = field(default_factory=dict)   # 상대 경로 → 내용 (본문 포함)
    failed: list[str] = field(default_factory=list)  # 가져오지 못한 상대 주소


def image_sources(tree: dict) -> Iterator[str]:
    """트리 안 그림 주소들 (중복 없이, 나온 차례)."""
    seen: set[str] = set()
    stack = [tree]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("kind") == "image" and isinstance(x.get("src"), str) and x["src"] not in seen:
                seen.add(x["src"])
                yield x["src"]
            stack.extend(reversed(list(x.values())))
        elif isinstance(x, list):
            stack.extend(reversed(x))


def _ext_for(ctype: str) -> str:
    ctype = ctype.split(";")[0].strip().lower()
    if ctype == "application/pdf":
        return ".pdf"
    for ext, t in IMAGE_TYPES.items():
        if t == ctype:
            return ext
    return ""


def plan_remote_copy(core, address: str, text: str, main: str) -> RemoteCopy:
    """원격 문서 address 의 원문 text(편집한 것)를 main 이름으로, 그것이 부르는 파일과 함께 묶는다.
    네트워크를 쓰므로 작업 스레드에서 부른다."""
    tree, deps = core.remote_parse(address, text)
    copy = RemoteCopy(main, {main: encode_text(text)})
    for name, body in deps.items():
        if name != main:
            copy.files[name] = encode_text(body)
    for src in image_sources(tree):
        name = safe_relative(src)
        if name is None or name in copy.files:
            continue                    # 절대 주소·위로 나가는 주소는 그대로 둔다
        ext = images.ext_of(name)
        tries = [name] if ext else [name] + [name + e for e in images.SEARCH_ORDER]
        for cand in tries:
            try:
                res = core.fetcher.fetch(htex_to_https(join_url(address, cand)),
                                         accept="image/*,application/pdf")
            except ViewerError:
                continue
            got = _ext_for(res.content_type)
            if res.content_type.split(";")[0].strip().lower() in ("text/html", "application/xhtml+xml"):
                continue
            if not images.ext_of(cand) and got:
                cand += got             # 확장자 없는 그림: 받은 형식의 확장자를 붙여 둔다 (뷰어가 찾는다)
            copy.files[cand] = res.content
            break
        else:
            copy.failed.append(src)
    return copy


def copy_targets(dest_dir: Path, copy: RemoteCopy) -> dict[str, Path]:
    """상대 경로 → 쓸 파일 경로 (dest_dir 밖으로 나가는 것은 뺀다)."""
    root = Path(dest_dir).resolve()
    out = {}
    for name in copy.files:
        p = (root / name).resolve()
        if p == root or root not in p.parents:
            continue
        out[name] = p
    return out


def existing_files(dest_dir: Path, copy: RemoteCopy) -> list[str]:
    """덮어쓰게 될 파일 (본문 제외: 본문은 저장 대화상자가 이미 물었다)."""
    return [n for n, p in copy_targets(dest_dir, copy).items() if n != copy.main and p.exists()]


def write_copy(dest_dir: Path, copy: RemoteCopy, overwrite: bool = True) -> list[Path]:
    written = []
    for name, p in copy_targets(dest_dir, copy).items():
        if p.exists() and not overwrite and name != copy.main:
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(p, copy.files[name])
        except OSError as e:
            raise EditError(tr('저장하지 못했습니다: {name} ({e})', name=name, e=e)) from None
        written.append(p)
    return written
