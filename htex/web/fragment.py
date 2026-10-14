"""라벨 블록 하나의 HTML 조각 (docs/interaction-protocol.md 4절 조각 주소). (담당: G)

렌더러(htex.html.render._Renderer)를 고치지 않고 읽기만 한다: 문서 전체와 같은 설정으로 렌더러를 만들고,
라벨이 가리키는 노드를 담은 작은 블록을 하나 만들어 그 렌더러의 block()에 넘긴다.

라벨 종류별 조각
- 식 행(displaymath 의 row): 그 행 하나만 담은 같은 환경의 디스플레이 수식.
- 절(section): 제목 + 처음 두 블록 (전체 절은 미리보기로 너무 길다) + "…".
- 목록 항목·단계: 그 항목 하나만 담은 목록.
- 그 밖의 블록(정리, 그림·표, 단락 등): 그 블록 전체.
조각 안의 같은 문서 링크(#라벨)와 상대 주소는 조각 문서 기준 주소로 바꿔, 다른 페이지에 넣어도 맞게 간다.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any, Callable, Optional

SECTION_PREVIEW_BLOCKS = 2


def _find(tree: dict[str, Any], node_id: str):
    """노드 id → (노드, 조상 목록[바깥→안], 그 노드가 담긴 필드 이름)."""
    roots = list(tree.get("body") or [])
    stack: list[tuple[Any, list[dict[str, Any]], str]] = [(b, [], "body") for b in reversed(roots)]
    while stack:
        x, anc, field = stack.pop()
        if isinstance(x, dict):
            if x.get("id") == node_id:
                return x, anc, field
            for k, v in x.items():
                if k in ("math", "target", "resolved", "span"):
                    continue
                if isinstance(v, list):
                    for c in reversed(v):
                        stack.append((c, anc + [x], k))
                elif isinstance(v, dict):
                    stack.append((v, anc + [x], k))
    return None, [], ""


def _label_node(tree: dict[str, Any], label: str) -> Optional[str]:
    tgt = (tree.get("labels") or {}).get(label)
    if isinstance(tgt, dict) and isinstance(tgt.get("node"), str):
        return tgt["node"]
    return None


def fragment_block(tree: dict[str, Any], label: str) -> Optional[dict[str, Any]]:
    """라벨 → 조각으로 렌더할 (얕게 복사한) 블록 노드. 없으면 None."""
    nid = _label_node(tree, label)
    if nid is None:
        return None
    node, anc, field = _find(tree, nid)
    if node is None:
        return None
    parent = anc[-1] if anc else None
    if parent is not None and field == "rows" and parent.get("kind") == "displaymath":
        return dict(parent, rows=[node])
    if parent is not None and field == "items" and parent.get("kind") == "list":
        return dict(parent, items=[node])
    if parent is not None and field == "steps" and parent.get("kind") == "steps":
        return dict(parent, steps=[node])
    if node.get("kind") == "section":
        kids = node.get("children") or []
        cut = dict(node, children=kids[:SECTION_PREVIEW_BLOCKS])
        cut["_truncated"] = len(kids) > SECTION_PREVIEW_BLOCKS
        return cut
    if "kind" in node:
        return node
    # 인라인(각주 등)이나 kind 없는 노드: 가장 가까운 블록 조상
    for a in reversed(anc):
        if a.get("kind") in ("paragraph", "theorem", "float", "displaymath"):
            return a
    return None


_HREF_HASH = re.compile(r'href="#')


def render_fragment(tree: dict[str, Any], label: str, *, doc_href: str = "",
                    web_fallback: bool = True,
                    doc_url: Callable[[str], str] | None = None) -> Optional[str]:
    """라벨 블록 하나의 HTML 조각 문자열. 라벨이 없으면 None.

    doc_href: 조각 문서의 주소(퍼센트 인코딩된 경로나 URL, # 없음). 조각 안의 '#라벨' 링크를
              'doc_href#라벨' 로, 상대 주소를 doc_href 기준으로 바꾼다. 빈 문자열이면 그대로 둔다.
    doc_url: 렌더러의 doc_url 과 같다 (상대 주소 바꾸기 뒤에 한 번 더 적용).
    """
    block = fragment_block(tree, label)
    if block is None:
        return None
    from ..html.render import _Renderer  # 읽기만 한다 (E 담당 모듈)

    def rebase(u: str) -> str:
        if doc_href and not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", u) and not u.startswith("/"):
            u = urllib.parse.urljoin(doc_href, u)
        return doc_url(u) if doc_url is not None else u

    r = _Renderer(tree, web_fallback, "", rebase)
    truncated = bool(block.pop("_truncated", False)) if isinstance(block, dict) else False
    body = r.block(block)
    if truncated and body.endswith("</section>"):
        body = body[:-len("</section>")] + '<p class="htex-fragment-more">…</p></section>'
    notes = r.footnote_list()
    out = body + ("\n" + notes if notes else "")
    if doc_href:
        out = _HREF_HASH.sub(f'href="{html.escape(doc_href, quote=True)}#', out)
    info = (tree.get("labels") or {}).get(label) or {}
    from .common import plain_title
    head = plain_title(tree)
    shown = info.get("display") or label
    head_html = (f'<div class="htex-fragment-head">'
                 f'{html.escape(head + " · " if head else "")}{html.escape(str(shown))}</div>')
    return (f'<div class="htex-fragment" data-label="{html.escape(label, quote=True)}">'
            f'{head_html}\n{out}</div>')
