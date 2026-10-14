"""문서 트리 → HTML5 문서 (명세 8절). (담당: E)

공개 함수는 render(tree, *, web_fallback=False) 하나. 계약은 htex/html/__init__.py docstring.

설계 메모
- 문서 트리만 본다. TeX를 다시 해석하는 곳은 수식(math.tex → MathML, mathml.py)뿐이다.
- 모든 텍스트·속성값은 _e / _a 로 escape 한다. 주소는 _safe_url 을 통과한 것만 href·src 에 넣는다.
- id 충돌 방지: 노드 id(n1…)와 라벨 앵커는 그대로, 변환기가 새로 만드는 id 는 라벨 문법
  ([A-Za-z0-9가-힣:._-])에 없는 '~' 를 넣어 만든다 (fn~n3, bib~키). 라벨이 다른 노드의 id 와
  같으면 라벨 앵커를 만들지 않고 그 라벨로 가는 링크는 노드 id 로 보낸다.
"""
from __future__ import annotations

import html
import re
from typing import Any, Iterable

from . import mathml
from .style import CSS

__all__ = ["render", "safe_url"]

THEOREM_FALLBACK = "정리"
FLOAT_NAMES = {"figure": "그림", "table": "표"}
DIAG_SEVERITY = {"error": "오류", "warning": "경고"}

_SECTION_TAG = {1: "h2", 2: "h3", 3: "h4", 4: "h5"}


# ====================================================================== escape·주소
def _e(s: Any) -> str:
    """본문 텍스트 escape."""
    return html.escape(str(s), quote=False)


def _a(s: Any) -> str:
    """속성값 escape (큰따옴표 안에 넣는다)."""
    return html.escape(str(s), quote=True)


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_CONTROL = re.compile(r"[\x00-\x20\x7f-\x9f]")


def safe_url(url: Any, *, web_fallback: bool = False) -> str | None:
    """href·src 에 넣어도 되는 주소면 그 주소, 아니면 None.

    허용: htex:, https:, 상대 주소. 공백·제어 문자가 섞였거나 // 로 시작하는(프로토콜 상대) 주소,
    역슬래시가 든 주소는 브라우저마다 해석이 달라 거부한다.
    web_fallback 이면 htex:// 를 https:// 로 바꾼다 (명세 2절).
    """
    if not isinstance(url, str) or not url:
        return None
    if _CONTROL.search(url) or "\\" in url:
        return None
    m = _SCHEME.match(url)
    if m:
        scheme = m.group(1).lower()
        if scheme not in ("htex", "https"):
            return None
        if web_fallback and scheme == "htex":
            return "https" + url[4:]
        return url
    if url.startswith("//"):
        return None
    # 콜론이 첫 / ? # 보다 앞에 있으면 (예: "a:b") 스킴처럼 해석될 수 있으니 거부
    head = re.split(r"[/?#]", url, maxsplit=1)[0]
    if ":" in head:
        return None
    return url


_PERCENT = re.compile(r"^[0-9]+(\.[0-9]+)?%$")


# ====================================================================== 렌더러
class _Renderer:
    def __init__(self, tree: dict[str, Any], web_fallback: bool):
        self.tree = tree
        self.web = web_fallback
        self.labels: dict[str, dict[str, Any]] = tree.get("labels") or {}
        self.params = {p["name"]: p.get("default") for p in tree.get("parameters") or []}
        self.bib = tree.get("bibliography") or []
        self.bib_numbers = {b["key"]: b.get("number") for b in self.bib}
        self.node_ids = set(_all_ids(tree))
        # 노드 id → 그 노드를 가리키는 라벨들 (앵커를 만들 것)
        self.anchors_for: dict[str, list[str]] = {}
        for name, tgt in self.labels.items():
            self.anchors_for.setdefault(tgt.get("node", ""), []).append(name)
        self.used_ids: set[str] = set()
        self.footnotes: list[dict[str, Any]] = []
        self.bib_done = False
        self.bib_id_map: dict[str, str] = {}
        for b in self.bib:
            self.bib_id_map.setdefault(b["key"], self._unique("bib~" + _id_part(b["key"])))

    # ------------------------------------------------------------ id
    def _unique(self, base: str) -> str:
        cand, k = base, 2
        while cand in self.used_ids or cand in self.node_ids:
            cand = f"{base}~{k}"
            k += 1
        self.used_ids.add(cand)
        return cand

    def id_attr(self, node: dict[str, Any]) -> str:
        nid = node.get("id")
        if not nid:
            return ""
        self.used_ids.add(nid)
        return f' id="{_a(nid)}"'

    def label_ok(self, label: str) -> bool:
        """라벨을 앵커 id 로 써도 되는가 (노드 id 와 겹치지 않음)."""
        tgt = self.labels.get(label)
        if label in self.node_ids:
            return False
        return tgt is None or True

    def anchors(self, node: dict[str, Any]) -> str:
        """노드의 라벨 앵커들 (<span id="라벨">)."""
        names: list[str] = []
        if node.get("label"):
            names.append(node["label"])
        names.extend(self.anchors_for.get(node.get("id", ""), []))
        out = []
        for name in names:
            if name in self.used_ids or not self.label_ok(name):
                continue
            self.used_ids.add(name)
            out.append(f'<span class="htex-anchor" id="{_a(name)}"></span>')
        return "".join(out)

    def label_href(self, label: str, node: str | None = None) -> str:
        if self.label_ok(label):
            return "#" + label
        tgt = self.labels.get(label)
        return "#" + (node or (tgt or {}).get("node") or label)

    def url(self, url: Any) -> str | None:
        return safe_url(url, web_fallback=self.web)

    # ------------------------------------------------------------ 문서
    def document(self) -> str:
        meta = self.tree.get("meta") or {}
        title_text = _plain(meta.get("title") or []) or "HyperTeX 문서"
        head = [
            "<!doctype html>",
            '<html lang="ko">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            '<meta name="generator" content="HyperTeX 2.0 기준 구현 (htex.html)">',
            '<meta name="color-scheme" content="light dark">',
            f"<title>{_e(title_text)}</title>",
        ]
        if meta.get("keywords"):
            head.append(f'<meta name="keywords" content="{_a(", ".join(meta["keywords"]))}">')
        if meta.get("authors"):
            head.append(f'<meta name="author" content="'
                        f'{_a(", ".join(_plain(a) for a in meta["authors"]))}">')
        src = self.tree.get("source") or {}
        if src.get("url"):
            head.append(f'<meta name="htex-source" content="{_a(src["url"])}">')
        for s in meta.get("styles") or []:
            head.append(f'<meta name="htex-style" content="{_a(s)}">')
        head.append(f"<style>{CSS}</style>")
        head.append("</head>")

        body_cls = ["htex"]
        if (src.get("mode") == "compat"):
            body_cls.append("htex-compat")
        if "hangulmath" in (meta.get("mathExtensions") or []):
            body_cls.append("htex-hangulmath")
        parts = [f'<body class="{_a(" ".join(body_cls))}">', '<article class="htex-doc">']
        parts.append(self.header(meta))
        parts.append(self.parameters_panel())
        parts.append('<div class="htex-body">')
        parts.append(self.blocks(self.tree.get("body") or []))
        parts.append("</div>")
        if self.bib and not self.bib_done:
            parts.append(self.bibliography({"kind": "bibliography"}))
        parts.append(self.footnote_list())
        parts.append(self.diagnostics())
        parts.append("</article>")
        parts.append("</body>")
        parts.append("</html>")
        return "\n".join(head) + "\n" + "\n".join(p for p in parts if p) + "\n"

    def header(self, meta: dict[str, Any]) -> str:
        out = []
        if meta.get("title"):
            out.append(f'<h1 class="htex-title">{self.inlines(meta["title"])}</h1>')
        if meta.get("authors"):
            names = [f'<span class="htex-author">{self.inlines(a)}</span>'
                     for a in meta["authors"]]
            out.append(f'<p class="htex-authors">{"<span class=htex-sep>, </span>".join(names)}</p>'
                       .replace("<span class=htex-sep>", '<span class="htex-sep">'))
        if meta.get("date"):
            out.append(f'<p class="htex-date">{_e(meta["date"])}</p>')
        if meta.get("keywords"):
            kws = "".join(f'<li>{_e(k)}</li>' for k in meta["keywords"])
            out.append(f'<div class="htex-keywords"><span class="htex-kw-label">핵심어</span>'
                       f'<ul>{kws}</ul></div>')
        if meta.get("abstract"):
            out.append('<section class="htex-abstract"><h2>요약</h2>'
                       f'{self.blocks(meta["abstract"])}</section>')
        if not out:
            return ""
        return '<header class="htex-header">' + "".join(out) + "</header>"

    def parameters_panel(self) -> str:
        ps = self.tree.get("parameters") or []
        if not ps:
            return ""
        items = []
        for p in ps:
            name = p["name"]
            sym = mathml.GREEK.get(name, name)
            rng = f'{mathml.format_number(p["min"])}–{mathml.format_number(p["max"])}'
            if "step" in p:
                rng += f', 간격 {mathml.format_number(p["step"])}'
            items.append(
                f'<li><span class="htex-param-name">{_e(sym)}</span> = '
                f'<output class="htex-param" data-param="{_a(name)}" '
                f'data-min="{_a(p["min"])}" data-max="{_a(p["max"])}" '
                f'data-default="{_a(p["default"])}"'
                + (f' data-step="{_a(p["step"])}"' if "step" in p else "")
                + f'>{_e(mathml.format_number(p["default"]))}</output> '
                f'<span class="htex-param-range">({_e(rng)})</span></li>')
        return ('<aside class="htex-parameters" aria-label="매개변수">'
                '<span class="htex-param-label">매개변수 (기본값)</span>'
                f'<ul>{"".join(items)}</ul></aside>')

    # ------------------------------------------------------------ 블록
    def blocks(self, blocks: Iterable[dict[str, Any]]) -> str:
        return "\n".join(self.block(b) for b in blocks)

    def block(self, b: dict[str, Any]) -> str:
        fn = getattr(self, "b_" + str(b.get("kind", "")), None)
        if fn is None:
            return (f'<div class="htex-error"{self.id_attr(b)} data-code="unknown-node">'
                    f'{_e("알 수 없는 노드: " + str(b.get("kind")))}</div>')
        return fn(b)

    def b_section(self, b: dict[str, Any]) -> str:
        level = int(b.get("level", 1))
        tag = _SECTION_TAG.get(level, "h5")
        cls = f"htex-section htex-level-{level}"
        if b.get("appendix"):
            cls += " htex-appendix"
        num = (f'<span class="htex-secnum">{_e(b["number"])}</span> '
               if b.get("number") else "")
        head = (f'<{tag} class="htex-heading">{self.anchors(b)}{num}'
                f'{self.inlines(b.get("title") or [])}</{tag}>')
        return (f'<section class="{cls}"{self.id_attr(b)}>{head}\n'
                f'{self.blocks(b.get("children") or [])}</section>')

    def b_paragraph(self, b: dict[str, Any], prefix: str = "") -> str:
        return f'<p{self.id_attr(b)}>{prefix}{self.inlines(b.get("content") or [])}</p>'

    def b_list(self, b: dict[str, Any]) -> str:
        style = b.get("style")
        items = b.get("items") or []
        if style == "description":
            out = []
            for it in items:
                term = self.inlines(it.get("term") or [])
                out.append(f'<div class="htex-item"{self.id_attr(it)}>'
                           f'<dt>{self.anchors(it)}{term}</dt>'
                           f'<dd>{self.blocks(it.get("children") or [])}</dd></div>')
            return f'<dl class="htex-list htex-description"{self.id_attr(b)}>{"".join(out)}</dl>'
        tag = "ol" if style == "enumerate" else "ul"
        explicit = tag == "ol" and any(it.get("number") for it in items)
        out = []
        for it in items:
            marker = ""
            if explicit and it.get("number"):
                marker = f'<span class="htex-itemnum">{_e(it["number"])}.</span> '
            out.append(f'<li class="htex-item"{self.id_attr(it)}>{self.anchors(it)}{marker}'
                       f'{self.blocks(it.get("children") or [])}</li>')
        cls = f"htex-list htex-{style}" + (" htex-explicit" if explicit else "")
        return f'<{tag} class="{_a(cls)}"{self.id_attr(b)}>{"".join(out)}</{tag}>'

    def b_quote(self, b: dict[str, Any]) -> str:
        return (f'<blockquote class="htex-quote"{self.id_attr(b)}>'
                f'{self.blocks(b.get("children") or [])}</blockquote>')

    def b_verbatim(self, b: dict[str, Any]) -> str:
        return f'<pre class="htex-verbatim"{self.id_attr(b)}><code>{_e(b.get("text", ""))}</code></pre>'

    # -- 수식
    def b_displaymath(self, b: dict[str, Any]) -> str:
        env = b.get("env", "displaymath")
        base = env.rstrip("*")
        rows = b.get("rows") or []
        rendered: list[tuple[dict[str, Any], list[str] | None]] = []
        ncols = 1
        if base == "align":
            for r in rows:
                cells = self.align_cells(r.get("math") or {})
                rendered.append((r, cells))
                if cells:
                    ncols = max(ncols, len(cells))
        else:
            mode = {"gather": "gather", "multline": "multline"}.get(base)
            for r in rows:
                rendered.append((r, [self.math(r.get("math") or {}, display=True, mode=mode)]))
        trs = []
        for r, cells in rendered:
            if cells is None:  # 셀로 나눌 수 없는 행은 한 셀에 통째로
                cells = [self.math(r.get("math") or {}, display=True)]
            tds = []
            if len(cells) == 1:
                tds.append(f'<td class="htex-eqcell htex-c" colspan="{ncols}">{cells[0]}</td>')
            else:
                for ci, c in enumerate(cells):
                    cls = "htex-eqcell " + ("htex-r" if ci % 2 == 0 else "htex-l")
                    if ci and ci % 2 == 0:
                        cls += " htex-gap"
                    tds.append(f'<td class="{cls}">{c}</td>')
                for ci in range(len(cells), ncols):
                    tds.append('<td class="htex-eqcell"></td>')
            num = r.get("number")
            numhtml = f"({_e(num)})" if num else ""
            tex = (r.get("math") or {}).get("tex", "")
            trs.append(
                f'<tr class="htex-eqrow"{self.id_attr(r)} data-tex="{_a(tex)}">'
                f'<td class="htex-eqpad">{self.anchors(r)}</td>{"".join(tds)}'
                f'<td class="htex-eqno">{numhtml}</td></tr>')
        return (f'<div class="htex-display htex-env-{_a(base)}"{self.id_attr(b)} '
                f'data-env="{_a(env)}"><table class="htex-eqtable" role="presentation">'
                f'<tbody>{"".join(trs)}</tbody></table></div>')

    def align_cells(self, m: dict[str, Any]) -> list[str] | None:
        """align 행을 최상위 & 로 나눠 셀마다 <math>. 나눌 수 없거나 변환 실패면 None."""
        tex = m.get("tex", "")
        segs = split_top_level_amp(tex)
        if segs is None or len(segs) == 1:
            return None
        out = []
        for i, seg in enumerate(segs):
            # 오른쪽 셀이 "= …" 처럼 관계 기호로 시작해도 이항 간격이 나오도록 빈 원자를 앞에 둔다
            src = seg if i == 0 else "{}" + seg
            try:
                mathml.convert(src, self.params)
            except Exception:  # noqa: BLE001
                return None
            out.append(self.math(m, display=True, tex_override=src, annotation=seg.strip()))
        return out

    def math(self, m: dict[str, Any], *, display: bool = False, mode: str | None = None,
             tex_override: str | None = None, annotation: str | None = None) -> str:
        tex = m.get("tex", "") if tex_override is None else tex_override
        scripts = m.get("scripts") or []
        cls = "htex-math"
        if "hangul" in scripts:
            cls += " htex-has-hangul"
        attrs = {"class": cls}
        if display:
            attrs["displaystyle"] = "true"
        if m.get("params"):
            attrs["data-params"] = " ".join(m["params"])
        out = mathml.tex_to_mathml(tex, display=False, params=self.params, mode=mode,
                                   attrs=attrs)
        if annotation is not None and out.startswith("<math"):
            out = out.replace(
                f'<annotation encoding="application/x-tex">{_e(tex)}</annotation>',
                f'<annotation encoding="application/x-tex">{_e(annotation)}</annotation>', 1)
        return out

    # -- 정리·증명·상호작용
    def b_theorem(self, b: dict[str, Any]) -> str:
        name = b.get("name") or THEOREM_FALLBACK
        head = f'<strong class="htex-thm-name">{_e(name)}'
        if b.get("number"):
            head += f' <span class="htex-thm-num">{_e(b["number"])}</span>'
        head += "</strong>"
        if b.get("note"):
            head += f' <span class="htex-thm-note">({self.inlines(b["note"])})</span>'
        head = f'<span class="htex-thm-head">{self.anchors(b)}{head}.</span> '
        body = self._with_head(b.get("children") or [], head)
        env = _id_part(b.get("env", "theorem"))
        return (f'<div class="htex-theorem htex-env-{_a(env)}"{self.id_attr(b)} role="group">'
                f'{body}</div>')

    def _with_head(self, children: list[dict[str, Any]], head: str) -> str:
        """첫 블록이 단락이면 머리말을 그 단락 앞에 붙이고, 아니면 따로 둔다."""
        if children and children[0].get("kind") == "paragraph":
            return self.b_paragraph(children[0], prefix=head) + "\n" + self.blocks(children[1:])
        return f'<p class="htex-head-only">{head}</p>' + self.blocks(children)

    def b_proof(self, b: dict[str, Any]) -> str:
        title = self.inlines(b["title"]) if b.get("title") else "증명"
        qed = '<span class="htex-qed" aria-label="증명 끝">∎</span>'
        children = b.get("children") or []
        if b.get("collapsed"):
            return (f'<details class="htex-proof htex-collapsed"{self.id_attr(b)}>'
                    f'<summary><em class="htex-proof-head">{title}</em></summary>'
                    f'{self.blocks(children)}{qed}</details>')
        head = f'<em class="htex-proof-head">{title}.</em> '
        return (f'<div class="htex-proof"{self.id_attr(b)}>{self._with_head(children, head)}'
                f'{qed}</div>')

    def b_collapse(self, b: dict[str, Any]) -> str:
        return (f'<details class="htex-collapse"{self.id_attr(b)}>'
                f'<summary>{self.inlines(b.get("title") or [])}</summary>'
                f'{self.blocks(b.get("children") or [])}</details>')

    def b_steps(self, b: dict[str, Any]) -> str:
        items = []
        steps = b.get("steps") or []
        for i, s in enumerate(steps, 1):
            items.append(f'<li class="htex-step htex-step-{i}"{self.id_attr(s)} data-step="{i}">'
                         f'{self.anchors(s)}{self.blocks(s.get("children") or [])}</li>')
        return (f'<ol class="htex-steps"{self.id_attr(b)} data-steps="{len(steps)}">'
                f'{"".join(items)}</ol>')

    # -- 그림·표
    def b_float(self, b: dict[str, Any]) -> str:
        ft = b.get("floatType", "figure")
        name = FLOAT_NAMES.get(ft, "그림")
        cap = ""
        if b.get("caption") is not None or b.get("number"):
            label = f'<span class="htex-float-name">{_e(name)}'
            if b.get("number"):
                label += f' {_e(b["number"])}'
            label += "</span>"
            text = self.inlines(b.get("caption") or [])
            cap = f"<figcaption>{label}{': ' if text else ''}{text}</figcaption>"
        body = self.blocks(b.get("children") or [])
        inner = (cap + body) if ft == "table" else (body + cap)
        return (f'<figure class="htex-float htex-{_a(ft)}"{self.id_attr(b)}>{self.anchors(b)}'
                f'{inner}</figure>')

    def b_image(self, b: dict[str, Any]) -> str:
        src = self.url(b.get("src"))
        alt = b.get("alt", "")
        if src is None:
            return (f'<span class="htex-error htex-blocked-image"{self.id_attr(b)} '
                    f'title="허용되지 않는 주소">{_e(b.get("src", ""))}</span>')
        style = ""
        w = b.get("width")
        if isinstance(w, str) and _PERCENT.match(w):
            style = f' style="width:{_a(w)}"'
        return (f'<img class="htex-image"{self.id_attr(b)} src="{_a(src)}" alt="{_a(alt)}"'
                f' loading="lazy"{style}>')

    def b_tabular(self, b: dict[str, Any]) -> str:
        cols = b.get("columns") or []
        trs = []
        for row in b.get("rows") or []:
            rcls = []
            if row.get("ruleAbove"):
                rcls.append("htex-rule-above")
            if row.get("ruleBelow"):
                rcls.append("htex-rule-below")
            tds = []
            c = 0
            for cell in row.get("cells") or []:
                span = int(cell.get("colspan", 1) or 1)
                first = cols[c] if c < len(cols) else {}
                last = cols[c + span - 1] if c + span - 1 < len(cols) else {}
                align = cell.get("align") or first.get("align") or "l"
                ccls = [f"htex-{align}"]
                if first.get("ruleLeft"):
                    ccls.append("htex-rule-left")
                if last.get("ruleRight"):
                    ccls.append("htex-rule-right")
                cs = f' colspan="{span}"' if span > 1 else ""
                tds.append(f'<td class="{" ".join(ccls)}"{cs}>'
                           f'{self.inlines(cell.get("content") or [])}</td>')
                c += span
            ra = f' class="{" ".join(rcls)}"' if rcls else ""
            trs.append(f"<tr{ra}>{''.join(tds)}</tr>")
        return (f'<div class="htex-table-wrap"><table class="htex-tabular"{self.id_attr(b)}>'
                f'<tbody>{"".join(trs)}</tbody></table></div>')

    def b_picture(self, b: dict[str, Any]) -> str:
        extra = ""
        if b.get("params"):
            extra += f' data-params="{_a(" ".join(b["params"]))}"'
        if b.get("usesPgfplots"):
            extra += ' data-pgfplots="true"'
        return (f'<figure class="htex-picture"{self.id_attr(b)}{extra}>'
                f'<pre>{_e(b.get("source", ""))}</pre></figure>')

    def b_transclusion(self, b: dict[str, Any]) -> str:
        href = self.url(b.get("href"))
        text = _e(b.get("href", ""))
        link = (f'<a href="{_a(href)}">{text}</a>' if href is not None
                else f'<span class="htex-blocked-url">{text}</span>')
        return (f'<div class="htex-transclusion"{self.id_attr(b)} '
                f'data-href="{_a(b.get("href", ""))}">'
                f'<span class="htex-transclusion-label">가져올 내용:</span> {link}</div>')

    def b_bibliography(self, b: dict[str, Any]) -> str:
        return self.bibliography(b)

    def bibliography(self, b: dict[str, Any]) -> str:
        title = self.inlines(b["title"]) if b.get("title") else "참고문헌"
        items = []
        if not self.bib_done:
            self.bib_done = True
            for e in self.bib:
                num = e.get("number")
                ident = ""
                if e.get("identifier"):
                    ident = " " + self.identifier(e["identifier"])
                items.append(
                    f'<li id="{_a(self.bib_id_map[e["key"]])}" data-key="{_a(e["key"])}">'
                    f'<span class="htex-bibnum">[{_e(num if num else e["key"])}]</span> '
                    f'{self.inlines(e.get("text") or [])}{ident}</li>')
        return (f'<section class="htex-bibliography"{self.id_attr(b)}><h2>{title}</h2>'
                f'<ol class="htex-biblist">{"".join(items)}</ol></section>')

    def identifier(self, ident: dict[str, Any]) -> str:
        scheme, value = ident.get("scheme", ""), ident.get("value", "")
        url = ident.get("url") or _identifier_url(scheme, value)
        text = f"{scheme}:{value}" if scheme in ("arXiv", "doi", "isbn") else value
        href = self.url(url) if url else None
        if href:
            return f'<a class="htex-ident" href="{_a(href)}">{_e(text)}</a>'
        return f'<span class="htex-ident">{_e(text)}</span>'

    def b_error(self, b: dict[str, Any]) -> str:
        return (f'<pre class="htex-error"{self.id_attr(b)} data-code="{_a(b.get("code", ""))}" '
                f'title="{_a(b.get("code", ""))}">{_e(b.get("raw", ""))}</pre>')

    # ------------------------------------------------------------ 인라인
    def inlines(self, xs: Iterable[dict[str, Any]]) -> str:
        return "".join(self.inline(x) for x in xs)

    def inline(self, x: dict[str, Any]) -> str:
        k = x.get("kind")
        if k == "text":
            return _e(x.get("text", ""))
        if k == "styled":
            inner = self.inlines(x.get("children") or [])
            st = x.get("style")
            if st == "emph":
                return f"<em>{inner}</em>"
            if st == "bold":
                return f"<strong>{inner}</strong>"
            if st == "italic":
                return f"<i>{inner}</i>"
            if st == "mono":
                return f'<span class="htex-tt">{inner}</span>'
            if st == "smallcaps":
                return f'<span class="htex-sc">{inner}</span>'
            return f"<span>{inner}</span>"
        if k == "math":
            return self.math(x.get("math") or {})
        if k == "link":
            return self.link(x)
        if k == "footnote":
            self.footnotes.append(x)
            num = _e(x.get("number", "?"))
            fid = x.get("id", "")
            self.used_ids.add(fid)
            return (f'<sup class="htex-fnref">{self.anchors(x)}<a id="{_a(fid)}" href="#{_a(_fn_id(fid))}" '
                    f'role="doc-noteref">{num}</a></sup>')
        if k == "linebreak":
            return "<br>"
        if k == "showparam":
            name = x.get("name", "")
            val = self.params.get(name)
            shown = mathml.format_number(val) if val is not None else "?"
            return f'<output class="htex-param" data-param="{_a(name)}">{_e(shown)}</output>'
        if k == "code":
            return f'<code class="htex-code">{_e(x.get("text", ""))}</code>'
        if k == "error":
            raw = (f'<code class="htex-error" data-code="{_a(x.get("code", ""))}" '
                   f'title="{_a(x.get("code", ""))}">{_e(x.get("raw", ""))}</code>')
            kids = self.inlines(x.get("children") or [])
            return raw + (f'<span class="htex-error-args">{kids}</span>' if kids else "")
        return f'<span class="htex-error" title="알 수 없는 인라인">{_e(k)}</span>'

    # -- 링크
    def link(self, x: dict[str, Any]) -> str:
        lt = x.get("linkType")
        tgt = x.get("target") or {}
        res = x.get("resolved") or {}
        if lt in ("ref", "eqref"):
            return self.ref(x, lt, tgt, res)
        if lt == "cite":
            return self.cite(x, tgt, res)
        url = tgt.get("url", "")
        href = self.url(url)
        if lt == "url":
            text = f'<span class="htex-tt">{_e(url)}</span>'
        else:
            text = self.inlines(x.get("children") or []) or _e(url)
        if href is None:
            return f'<span class="htex-blocked-url" title="허용되지 않는 주소">{text}</span>'
        return f'<a class="htex-link" href="{_a(href)}">{text}</a>'

    def ref(self, x, lt, tgt, res) -> str:
        label = tgt.get("label", "")
        wrap = (lambda s: f"({s})") if lt == "eqref" else (lambda s: s)
        kids = self.inlines(x.get("children") or [])
        if tgt.get("doc") is not None:
            doc = tgt["doc"]
            href = self.url(doc + ("#" + label if label else ""))
            shown = kids or (_e(wrap(res["number"])) if res.get("number")
                             else _e(wrap(label or doc)))
            if href is None:
                return f'<span class="htex-blocked-url">{shown}</span>'
            return (f'<a class="htex-ref htex-xref" href="{_a(href)}" data-doc="{_a(doc)}" '
                    f'data-label="{_a(label)}">{shown}</a>')
        known = self.labels.get(label)
        number = res.get("number") or (known or {}).get("number")
        node = res.get("node") or (known or {}).get("node")
        if res.get("broken") or (known is None and not res.get("node")):
            return (f'<span class="htex-ref htex-broken" title="'
                    f'{_a("깨진 링크: 라벨 " + label + "을(를) 찾을 수 없습니다")}">'
                    f'{_e(wrap("??"))}</span>')
        shown = kids or _e(wrap(number if number else "??"))
        title = (known or {}).get("display")
        tattr = f' title="{_a(title)}"' if title else ""
        return (f'<a class="htex-ref" href="{_a(self.label_href(label, node))}"'
                f'{tattr}>{shown}</a>')

    def cite(self, x, tgt, res) -> str:
        keys = tgt.get("keys") or []
        parts = []
        for k in keys:
            ext = _external_cite(k)
            if ext is not None:
                scheme, value, url = ext
                href = self.url(url) if url else None
                if href:
                    parts.append(f'<a class="htex-cite-ext" href="{_a(href)}">{_e(k)}</a>')
                else:
                    parts.append(f'<span class="htex-cite-ext">{_e(k)}</span>')
                continue
            num = self.bib_numbers.get(k)
            if k in self.bib_id_map:
                parts.append(f'<a href="#{_a(self.bib_id_map[k])}" title="{_a(k)}">'
                             f'{_e(num or k)}</a>')
            else:
                parts.append(f'<span class="htex-broken" title="'
                             f'{_a("깨진 인용: 키 " + k + "을(를) 찾을 수 없습니다")}">??</span>')
        if not keys:
            parts.append('<span class="htex-broken" title="빈 인용">??</span>')
        kids = self.inlines(x.get("children") or [])
        inner = ", ".join(parts)
        return f'<span class="htex-cite">[{inner}]</span>' + (f" {kids}" if kids else "")

    # ------------------------------------------------------------ 끝 부분
    def footnote_list(self) -> str:
        if not self.footnotes:
            return ""
        out = []
        i = 0
        while i < len(self.footnotes):  # 각주 안 각주는 렌더링 중에 목록 뒤에 붙는다
            f = self.footnotes[i]
            i += 1
            fid = f.get("id", "")
            body = self.blocks(f.get("children") or [])
            back = (f'<a class="htex-fnback" href="#{_a(fid)}" role="doc-backlink" '
                    f'aria-label="본문으로">↩</a>')
            out.append(f'<li id="{_a(_fn_id(fid))}"><span class="htex-fnnum">'
                       f'{_e(f.get("number", "?"))}.</span>{body}{back}</li>')
        return ('<section class="htex-footnotes" role="doc-endnotes"><h2>각주</h2>'
                f'<ol>{"".join(out)}</ol></section>')

    def diagnostics(self) -> str:
        ds = self.tree.get("diagnostics") or []
        if not ds:
            return ""
        n_err = sum(1 for d in ds if d.get("severity") == "error")
        n_warn = len(ds) - n_err
        items = []
        for d in ds:
            sev = d.get("severity", "warning")
            where = ""
            sp = d.get("span")
            if sp:
                where = f' <span class="htex-diag-pos">({_e(sp.get("line"))}행 {_e(sp.get("col"))}열)</span>'
            node = ""
            if d.get("node"):
                node = f' <a href="#{_a(d["node"])}">위치로</a>'
            items.append(f'<li class="htex-diag-{_a(sev)}"><span class="htex-diag-sev">'
                         f'{_e(DIAG_SEVERITY.get(sev, sev))}</span> '
                         f'<code>{_e(d.get("code", ""))}</code> {_e(d.get("message", ""))}'
                         f'{where}{node}</li>')
        return (f'<details class="htex-diagnostics"><summary>진단 {len(ds)}건 '
                f'(오류 {n_err}, 경고 {n_warn})</summary><ul>{"".join(items)}</ul></details>')


# ====================================================================== 도우미
def _fn_id(node_id: str) -> str:
    return "fn~" + node_id


def _id_part(s: str) -> str:
    """임의 문자열 → id 에 쓸 수 있는 조각."""
    return re.sub(r"[^A-Za-z0-9가-힣:._-]", lambda m: f"_{ord(m.group()):x}_", s) or "_"


def _all_ids(tree: dict[str, Any]) -> Iterable[str]:
    stack: list[Any] = [tree.get("body") or [], (tree.get("meta") or {}).get("abstract") or []]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            if isinstance(x.get("id"), str):
                yield x["id"]
            for k, v in x.items():
                if k in ("math", "target", "resolved", "span"):
                    continue
                if isinstance(v, (list, dict)):
                    stack.append(v)


def _plain(xs: Iterable[dict[str, Any]]) -> str:
    out = []
    for x in xs:
        k = x.get("kind")
        if k == "text" or k == "code":
            out.append(x.get("text", ""))
        elif k == "math":
            out.append((x.get("math") or {}).get("tex", ""))
        elif k in ("styled", "link", "error"):
            if k == "error":
                out.append(x.get("raw", ""))
            out.append(_plain(x.get("children") or []))
        elif k == "linebreak":
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _identifier_url(scheme: str, value: str) -> str | None:
    if scheme == "arXiv":
        return "https://arxiv.org/abs/" + value
    if scheme == "doi":
        return "https://doi.org/" + value
    if scheme in ("htex", "https"):
        return value if ":" in value else f"{scheme}:{value}"
    return None  # isbn: 해석 주소 없음


def _external_cite(key: str) -> tuple[str, str, str | None] | None:
    """외부 식별자 인용이면 (scheme, value, 주소)."""
    for prefix, scheme in (("arXiv:", "arXiv"), ("arxiv:", "arXiv"), ("doi:", "doi"),
                           ("isbn:", "isbn")):
        if key.startswith(prefix):
            value = key[len(prefix):]
            return scheme, value, _identifier_url(scheme, value)
    if key.startswith("htex://"):
        return "htex", key, key
    if key.startswith("https://"):
        return "https", key, key
    return None


def split_top_level_amp(tex: str) -> list[str] | None:
    """최상위 & 로 나눈다 (중괄호·\\begin…\\end 안의 & 는 그대로). 균형이 깨졌으면 None."""
    segs, buf = [], []
    depth = 0
    env = 0
    i, n = 0, len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", tex[i:], re.S)
            word = m.group(1) if m else ""
            if word == "begin":
                env += 1
            elif word == "end":
                env -= 1
            elif word == "\\" and depth == 0 and env == 0:
                return None  # 최상위 줄바꿈: 행 하나로 다룰 수 없다
            tok = m.group(0) if m else c
            buf.append(tok)
            i += len(tok)
            continue
        if c == "%":
            j = tex.find("\n", i)
            j = n if j < 0 else j
            buf.append(tex[i:j])
            i = j
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return None
        elif c == "&" and depth == 0 and env == 0:
            segs.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    if depth != 0 or env != 0:
        return None
    segs.append("".join(buf))
    return segs


def render(tree: dict[str, Any], *, web_fallback: bool = False) -> str:
    """문서 트리 → 완결된 HTML5 문서 하나. web_fallback 이면 htex:// 주소를 https:// 로 바꾼다."""
    return _Renderer(tree, web_fallback).document()
