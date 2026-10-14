"""다른 문서 참조의 번호 채우기 (명세 5절, 스키마 link.resolved). (담당: J)

파서는 같은 문서의 \\ref 만 번호를 채운다. `\\ref{other.htex#eq:H}` 처럼 다른 문서를 가리키는 참조는
"다른 문서는 뷰어가 가져와 채운다"(스키마 resolved 설명). 이 모듈은 그 일을 하는 순수 함수다:

    resolve_cross_refs(tree, loader) -> 새 트리

- loader(doc) : 트리에 적힌 문서 주소(target.doc, 상대·절대 그대로) → 그 문서의 트리 또는 None.
  주소를 어디 기준으로 풀지, 접근해도 되는지, 어떻게 가져올지는 호출한 쪽(뷰어·웹 서버·정적 빌드)이 정한다.
  loader 가 예외를 내도 그 문서만 건너뛴다.
- 문서당 서로 다른 다른 문서는 max_docs(20)개까지, 전체 시간 예산 budget(1초).
  loader 호출은 작업 스레드에서 동시에 돌리고 예산이 끝나면 기다리지 않는다(늦게 끝난 결과는 버린다.
  loader 가 캐시를 채운다면 다음 렌더링에서 쓰인다).
- 대상 문서의 labels[라벨].number 를 resolved.number 로 넣는다. 못 찾으면(문서 실패, 라벨 없음, 번호 없음)
  그 링크는 그대로 둔다 → 렌더러는 라벨 이름을 보인다.
- 다른 문서의 트리는 labels 만 읽고 그 안의 다른 문서 참조는 따라가지 않으므로 순환 참조(A↔B, 자기 자신)도
  한 단계로 끝난다.
- 입력 트리는 바꾸지 않는다(캐시된 트리를 나눠 쓰므로). 바뀐 경로의 노드만 새로 만든다.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import unquote, urlsplit

Loader = Callable[[str], Optional[dict]]

MAX_DOCS = 20
BUDGET = 1.0
_SKIP_KEYS = frozenset({"math", "span", "target", "resolved"})


def cross_doc_targets(tree: dict) -> list[str]:
    """트리의 다른 문서 ref/eqref 가 가리키는 문서 주소들 (나온 순서, 중복 없이)."""
    seen: dict[str, None] = {}
    for link in _iter_links(tree):
        doc = (link.get("target") or {}).get("doc")
        if isinstance(doc, str) and doc and doc not in seen:
            seen[doc] = None
    return list(seen)


def _iter_links(x: Any) -> Iterable[dict]:
    stack = [x]
    while stack:
        y = stack.pop()
        if isinstance(y, dict):
            if (y.get("kind") == "link" and y.get("linkType") in ("ref", "eqref")
                    and isinstance(y.get("target"), dict) and y["target"].get("doc") is not None):
                yield y
            for k, v in y.items():
                if k not in _SKIP_KEYS and isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(y, list):
            stack.extend(reversed(y))


def load_label_tables(docs: list[str], loader: Loader, *, budget: float = BUDGET,
                      clock: Callable[[], float] = time.monotonic) -> dict[str, dict]:
    """문서 주소들 → {주소: labels}. 동시에 불러오고 예산 안에 끝난 것만."""
    results: dict[str, dict] = {}
    lock = threading.Lock()

    def work(doc: str) -> None:
        try:
            t = loader(doc)
        except Exception:   # noqa: BLE001 - 문서 하나 실패는 조용히
            return
        if isinstance(t, dict) and isinstance(t.get("labels"), dict):
            with lock:
                results[doc] = t["labels"]

    deadline = clock() + budget
    threads = []
    for doc in docs:
        th = threading.Thread(target=work, args=(doc,), name="htex-linkres", daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        left = deadline - clock()
        if left <= 0:
            break
        th.join(left)
    with lock:
        return dict(results)


def resolve_cross_refs(tree: dict, loader: Loader, *, max_docs: int = MAX_DOCS,
                       budget: float = BUDGET,
                       clock: Callable[[], float] = time.monotonic) -> dict:
    """다른 문서 ref/eqref 의 resolved.number 를 채운 새 트리 (모듈 설명 참고). 바꿀 것이 없으면 tree 그대로."""
    if not isinstance(tree, dict):
        return tree
    docs = cross_doc_targets(tree)[:max(0, max_docs)]
    if not docs:
        return tree
    tables = load_label_tables(docs, loader, budget=budget, clock=clock)
    if not tables:
        return tree

    def number_for(link: dict) -> Optional[str]:
        tgt = link.get("target") or {}
        labels = tables.get(tgt.get("doc"))
        if not labels:
            return None
        ent = labels.get(tgt.get("label") or "")
        num = ent.get("number") if isinstance(ent, dict) else None
        return num if isinstance(num, str) and num else None

    def walk(x: Any) -> Any:
        if isinstance(x, list):
            out = None
            for i, v in enumerate(x):
                nv = walk(v)
                if nv is not v:
                    if out is None:
                        out = list(x)
                    out[i] = nv
            return x if out is None else out
        if not isinstance(x, dict):
            return x
        new = None
        if (x.get("kind") == "link" and x.get("linkType") in ("ref", "eqref")
                and isinstance(x.get("target"), dict) and x["target"].get("doc") is not None):
            num = number_for(x)
            res = x.get("resolved") or {}
            if num is not None and res.get("number") != num:
                new = dict(x)
                r = dict(res)
                r["number"] = num
                r.pop("broken", None)
                new["resolved"] = r
        for k, v in x.items():
            if k in _SKIP_KEYS or not isinstance(v, (dict, list)):
                continue
            nv = walk(v)
            if nv is not v:
                if new is None:
                    new = dict(x)
                new[k] = nv
        return x if new is None else new

    return walk(tree)


_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
DOC_EXTS = (".htex", ".tex")


def local_doc_for_link(root: Path, doc_path: Path, doc: str) -> Optional[Path]:
    """웹 서버·정적 빌드용: doc_path 문서 안의 다른 문서 주소 doc(상대 주소) → root 안의 문서 파일 경로.
    절대 주소(htex:, https: 등), 루트 밖(.., 심볼릭 링크), 숨김 파일, 없는 파일, 문서가 아닌 파일이면 None."""
    if not isinstance(doc, str) or not doc or _SCHEME.match(doc) or doc.startswith(("/", "\\")):
        return None
    path = unquote(urlsplit(doc).path)
    if not path or "\x00" in path or "\\" in path or not path.lower().endswith(DOC_EXTS):
        return None
    root = Path(root).resolve()
    base = Path(doc_path).resolve().parent
    real = Path(os.path.realpath(base / path))
    if real != root and root not in real.parents:
        return None
    if any(part.startswith(".") for part in real.relative_to(root).parts):
        return None
    return real if real.is_file() else None


__all__ = ["local_doc_for_link", "resolve_cross_refs", "cross_doc_targets", "load_label_tables", "MAX_DOCS", "BUDGET"]
