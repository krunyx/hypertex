"""htex build: 정적 사이트 만들기 (명세 원칙 5). (담당: G)

DIR 아래 모든 파일을 OUT 으로:
- .htex/.tex → 같은 상대 경로의 .html (render(web_fallback=True, doc_url=…)).
  다른 문서 링크 `x.htex#lab`·`x.tex#lab` → `x.html#lab` (상대 주소만; htex:// 와 https:// 는 그대로).
  같은 이름의 .htex 와 .tex 가 함께 있으면 .htex 가 x.html, .tex 는 x.tex.html (경고).
- 그 밖의 파일 → 그대로 복사 (숨김 파일, 루트 밖을 가리키는 심볼릭 링크, OUT 자신은 건너뜀).
- _htex/interact.js 복사, 문서마다 <script src="(상대)/_htex/interact.js" defer>.
  정적 사이트에는 그림 주소·조각 주소가 없으므로 그 meta 는 넣지 않는다(규약 2절):
  슬라이더는 숫자만 바뀌고 그림은 기본값, 다른 문서 미리보기는 없다.
- 폴더마다 index.html 이 없으면 목록 페이지 index.html 을 만든다 (index.htex 가 있으면 그것이 index.html).
- 각 HTML 에 CSP <meta http-equiv> (스크립트는 자기 출처만, object-src none, base-uri none).
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, unquote, urlsplit

from .common import (CSP_META, INTERACT_JS_PATH, PathRejected, e, error_page, is_document,
                     ListingEntry, listing_page, plain_title, resolve_in_root, rel_href)

ASSET_DIR = "_htex"


@dataclass
class BuildReport:
    documents: list[str] = field(default_factory=list)   # 만든 .html (OUT 기준 상대 경로)
    copied: list[str] = field(default_factory=list)
    listings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)       # 오류 페이지로 대체한 문서
    warnings: list[str] = field(default_factory=list)

    @property
    def files(self) -> list[str]:
        return sorted(self.documents + self.copied + self.listings)


def _doc_html_name(rel: str, taken: set[str]) -> str:
    base = rel.rsplit(".", 1)[0]
    cand = base + ".html"
    if cand in taken:
        cand = rel + ".html"
    return cand


def make_doc_url(rel_dir: str, html_names: dict[str, str]):
    """렌더러 doc_url: 상대 주소의 .htex/.tex 문서 링크를 .html 로."""

    def doc_url(u: str) -> str:
        if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", u) or u.startswith("#") or u.startswith("/"):
            return u
        sp = urlsplit(u)
        if not is_document(sp.path):
            return u
        target = os.path.normpath(os.path.join(rel_dir, unquote(sp.path))).replace(os.sep, "/")
        mapped = html_names.get(target)
        if mapped is None:
            # 사이트 안에 없는 문서: 확장자만 바꾼다 (그래도 .htex 로 두면 브라우저가 내려받기만 한다)
            mapped_path = re.sub(r"\.(htex|tex)$", ".html", sp.path, flags=re.I)
        else:
            mapped_path = quote(os.path.relpath(mapped, rel_dir or ".").replace(os.sep, "/"))
        out = mapped_path
        if sp.query:
            out += "?" + sp.query
        if sp.fragment:
            out += "#" + sp.fragment
        return out

    return doc_url


def build(root: Path | str, out: Path | str, *, quiet: bool = True) -> BuildReport:
    from ..html import render
    from ..parser import parse_file

    root = Path(root).resolve()
    out = Path(out).resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    if out == root:
        raise ValueError("출력 폴더가 입력 폴더와 같다")
    rep = BuildReport()

    # 1) 파일 모으기
    docs: list[str] = []
    statics: list[str] = []
    folders: set[str] = {""}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        d = Path(dirpath)
        if d.resolve() == out or out in d.resolve().parents:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(n for n in dirnames if not n.startswith(".")
                             and not (n == ASSET_DIR and d == root)
                             and (d / n).resolve() != out
                             and _inside(root, d / n))
        rel_d = d.relative_to(root).as_posix()
        rel_d = "" if rel_d == "." else rel_d
        folders.add(rel_d)
        for n in sorted(filenames):
            if n.startswith("."):
                continue
            p = d / n
            if not _inside(root, p) or not p.resolve().is_file():
                rep.warnings.append(f"건너뜀(루트 밖 링크): {(rel_d + '/' if rel_d else '') + n}")
                continue
            rel = (rel_d + "/" if rel_d else "") + n
            (docs if is_document(n) else statics).append(rel)

    # 2) 문서 → html 이름 (.htex 우선)
    html_names: dict[str, str] = {}
    taken = {s for s in statics if s.lower().endswith(".html")}
    for rel in sorted(docs, key=lambda r: (not r.lower().endswith(".htex"), r)):
        name = _doc_html_name(rel, taken)
        if name != rel.rsplit(".", 1)[0] + ".html":
            rep.warnings.append(f"이름 충돌: {rel} → {name}")
        taken.add(name)
        html_names[rel] = name

    out.mkdir(parents=True, exist_ok=True)
    # 3) 정적 파일
    for rel in statics:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, dst)
        rep.copied.append(rel)
    (out / ASSET_DIR).mkdir(exist_ok=True)
    shutil.copyfile(INTERACT_JS_PATH, out / ASSET_DIR / "interact.js")
    rep.copied.append(f"{ASSET_DIR}/interact.js")

    # 4) 문서
    titles: dict[str, str] = {}
    trees: dict[Path, Any] = {}       # 다른 문서 번호 채우기용 트리 캐시 (J)
    for rel, name in html_names.items():
        rel_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        script = rel_href("/" + rel_dir, f"/{ASSET_DIR}/interact.js")
        head = (f'<meta http-equiv="Content-Security-Policy" content="{e(CSP_META)}">\n'
                f'<script src="{e(script)}" defer></script>')
        try:
            tree = parse_file(root / rel)
            titles[rel] = plain_title(tree)
            tree = _resolve_links(tree, root, root / rel, parse_file, trees)   # 다른 문서 번호 (J)
            text = render(tree, web_fallback=True, head_extra=head,
                          doc_url=make_doc_url(rel_dir, html_names))
        except Exception as exc:  # noqa: BLE001
            rep.errors.append(f"{rel}: {type(exc).__name__}: {exc}")
            src = (root / rel).read_text(encoding="utf-8", errors="replace")
            text = error_page("문서를 표시할 수 없다", "HTML 변환 중 오류가 났다. 원문을 대신 보인다.",
                              f"{type(exc).__name__}: {exc}", src)
        dst = out / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        rep.documents.append(name)

    # 5) 폴더 목록
    produced = set(rep.documents) | set(rep.copied)
    for folder in sorted(folders):
        idx = (folder + "/" if folder else "") + "index.html"
        if idx in produced:
            continue
        entries: list[ListingEntry] = []
        subs = sorted(f for f in folders
                      if f and (f.rsplit("/", 1)[0] if "/" in f else "") == folder)
        for f in subs:
            n = f.rsplit("/", 1)[-1]
            entries.append(ListingEntry(n + "/", quote(n) + "/index.html", "folder"))
        for rel, name in sorted(html_names.items()):
            if (rel.rsplit("/", 1)[0] if "/" in rel else "") != folder:
                continue
            entries.append(ListingEntry(rel.rsplit("/", 1)[-1], quote(name.rsplit("/", 1)[-1]),
                                        "document", titles.get(rel, "")))
        for rel in statics:
            if (rel.rsplit("/", 1)[0] if "/" in rel else "") != folder:
                continue
            n = rel.rsplit("/", 1)[-1]
            entries.append(ListingEntry(n, quote(n), "file"))
        text = listing_page("/" + folder, entries, parent=bool(folder))
        text = text.replace('href="../"', 'href="../index.html"')
        dst = out / idx
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        rep.listings.append(idx)

    if not quiet:
        for w in rep.warnings:
            print("경고:", w, file=sys.stderr)
        for er in rep.errors:
            print("오류:", er, file=sys.stderr)
        print(f"문서 {len(rep.documents)}개, 파일 {len(rep.copied)}개, 목록 {len(rep.listings)}개 → {out}",
              file=sys.stderr)
    return rep


def _resolve_links(tree: dict[str, Any], root: Path, doc_path: Path, parse_file,
                   trees: dict[Path, Any]) -> dict[str, Any]:
    """다른 문서 \\ref 의 번호 채우기 (htex.linkres, 담당 J). 사이트 안의 상대 주소 문서만 읽는다
    (빌드는 네트워크에 접근하지 않는다). 실패하면 라벨 이름 그대로."""
    from ..linkres import local_doc_for_link, resolve_cross_refs

    def loader(doc: str):
        p = local_doc_for_link(root, doc_path, doc)
        if p is None:
            return None
        if p == doc_path.resolve():
            return tree
        if p not in trees:
            try:
                trees[p] = parse_file(p)
            except Exception:  # noqa: BLE001
                trees[p] = None
        return trees[p]

    try:
        return resolve_cross_refs(tree, loader)
    except Exception:  # noqa: BLE001
        return tree


def _inside(root: Path, p: Path) -> bool:
    try:
        resolve_in_root(root, list(p.relative_to(root).parts))
        return True
    except (PathRejected, ValueError):
        return False
