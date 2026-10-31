"""Markdown → 문서 트리 (6단계, 담당 M). 표준 라이브러리만 쓴다.

`.md` · `.markdown` 파일을 HyperTeX 문서 트리로 바꾼다. 트리가 같으므로 HTML·MathML 변환, 뷰어의 탭·찾기·
테마·자동 새로고침, `htex serve`·`htex build` 가 그대로 쓴다. source.mode 는 "markdown".

받는 문법 (CommonMark 의 자주 쓰는 부분 + GitHub 식 + 수식)
- 블록: 제목(# …, 밑줄 ===/---), 문단, 목록(-, *, +, 1. 1), 중첩, 할 일 [ ] [x]), 인용(>), 코드 블록(``` ~~~, 들여쓰기 4칸),
  표(GitHub 식), 각주 정의([^1]: …), 링크 정의([id]: 주소), 머리말(--- YAML ---: title, author, date, tags/keywords),
  수식 블록($$ … $$, \\[ … \\], ```math, \\begin{equation|align|gather|multline}), MkDocs 알림(!!! note "제목", ??? 접기),
  <details><summary> 접기, 가로줄(---, 버린다).
- 글 안: *기울임* _기울임_ **굵게** __굵게__ ~~취소선~~, `코드`, $수식$, \\(수식\\), [링크](주소 "제목"),
  [링크][id], ![그림](주소), <https://…> 와 맨 https:// 주소, [^각주], 두 칸 공백·\\ 줄바꿈, HTML 엔티티,
  <br>, <a href>, <img>. 그 밖의 HTML 태그는 지우고 글자만 남긴다 (HTML 을 그대로 넣지 않는다: 보안).

정한 것 (notes/M-questions.md)
- 제목: 문서 첫 블록이 # 제목 하나뿐이면 meta.title 로 쓰고 나머지 제목을 한 단계씩 올린다. 절 번호는 붙이지 않는다.
- 제목마다 GitHub 식 앵커(소문자, 공백→-, 문장부호 삭제)를 라벨로 단다. [x](#앵커) 는 문서 안 참조가 된다.
- http:// 링크·그림은 https:// 로 올린다 (Chrome 의 HTTPS 우선과 같다). mailto: 등 다른 스킴은 글자로만 둔다.
- 수식 $…$: 여는 $ 뒤와 닫는 $ 앞에 공백이 없고, 닫는 $ 뒤가 숫자가 아니어야 한다 (pandoc 규칙, "$5 와 $10" 은 글자).
"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

from .diagnostics import Sink
from .loader import classify

MD_EXTENSIONS = (".md", ".markdown")
MAX_DEPTH = 40            # 중첩 인용·목록 한도 (악의적 입력 방어)

_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_DISPLAY_ENVS = {"equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*"}

# ---- 블록 정규식
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^`]*?)[ \t]*$")
_BULLET = re.compile(r"^( {0,3})([-+*])([ \t]+|$)(.*)$")
_ORDERED = re.compile(r"^( {0,3})(\d{1,9})([.)])([ \t]+|$)(.*)$")
_QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
_LINKDEF = re.compile(r"^ {0,3}\[([^\]^][^\]]*)\]:[ \t]*<?([^\s>]+)>?(?:[ \t]+(\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$")
_FOOTDEF = re.compile(r"^ {0,3}\[\^([^\]]+)\]:[ \t]?(.*)$")
_TABLE_SEP = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_ADMON = re.compile(r"^(!!!|\?\?\?\+?)[ \t]+([\w-]+)(?:[ \t]+\"([^\"]*)\")?[ \t]*$")
_BEGIN_ENV = re.compile(r"^ {0,3}\\begin\{([a-zA-Z*]+)\}")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def is_markdown(url_or_name: str) -> bool:
    return url_or_name.lower().split("#", 1)[0].split("?", 1)[0].endswith(MD_EXTENSIONS)


def slugify(text: str) -> str:
    """GitHub 식 앵커: 소문자, 공백→-, 글자·숫자·-·_ 만 (한글 포함). 라벨 이름 규칙 밖의 글자는 버린다."""
    out = []
    for ch in text.strip().lower():
        if ch in (" ", "\t"):
            out.append("-")
        elif ch in "-_" or ch.isascii() and ch.isalnum() or "가" <= ch <= "힣":
            out.append(ch)
    return "".join(out)


def _expand_tabs(line: str) -> str:
    return line.expandtabs(4) if "\t" in line else line


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank(line: str) -> bool:
    return not line.strip()


# ====================================================================== 변환기
class _Converter:
    def __init__(self, text: str, url: str, sink: Sink):
        self.sink = sink
        self.url = url
        self.linkdefs: dict[str, tuple[str, str]] = {}
        self.footdefs: dict[str, list[str]] = {}
        self.footnotes_used: dict[str, dict] = {}
        self.slugs: dict[str, int] = {}
        self.labels: dict[str, dict] = {}       # 이름 → 노드(아직 id 없음)
        self.meta: dict[str, Any] = {"documentclass": "hypertex"}
        self.depth = 0
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "�")
        lines = [_expand_tabs(x) for x in text.split("\n")]
        lines = self._front_matter(lines)
        lines = self._collect_defs(lines)
        self.lines = lines

    # ------------------------------------------------------------ 머리말·정의
    def _front_matter(self, lines: list[str]) -> list[str]:
        if not lines or lines[0].strip() != "---":
            return lines
        for k in range(1, min(len(lines), 200)):
            if lines[k].strip() in ("---", "..."):
                self._yaml(lines[1:k])
                return lines[k + 1:]
        return lines

    def _yaml(self, rows: list[str]) -> None:
        """머리말의 단순한 key: value 와 - 목록만 읽는다."""
        data: dict[str, Any] = {}
        key = None
        for row in rows:
            if not row.strip() or row.lstrip().startswith("#"):
                continue
            m = re.match(r"^([A-Za-z_][\w-]*)[ \t]*:[ \t]*(.*)$", row)
            if m and not row.startswith((" ", "\t")):
                key, val = m.group(1).lower(), m.group(2).strip()
                if val.startswith("[") and val.endswith("]"):
                    data[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                elif val:
                    data[key] = val.strip("'\"")
                else:
                    data[key] = []
            elif key and re.match(r"^[ \t]*-[ \t]+", row) and isinstance(data.get(key), list):
                data[key].append(re.sub(r"^[ \t]*-[ \t]+", "", row).strip().strip("'\""))
        if isinstance(data.get("title"), str):
            self.meta["title"] = self.inlines(data["title"])
        authors = data.get("author", data.get("authors"))
        if isinstance(authors, str):
            authors = [a.strip() for a in re.split(r"\s+and\s+|;", authors) if a.strip()]
        if isinstance(authors, list) and authors:
            self.meta["authors"] = [[{"kind": "text", "text": a}] for a in authors if isinstance(a, str)]
        if isinstance(data.get("date"), str):
            self.meta["date"] = data["date"]
        kw = data.get("keywords", data.get("tags"))
        if isinstance(kw, str):
            kw = [k.strip() for k in kw.split(",") if k.strip()]
        if isinstance(kw, list) and kw:
            self.meta["keywords"] = [str(k) for k in kw]
        if isinstance(data.get("abstract"), str):
            self.meta["abstract"] = [{"kind": "paragraph", "content": self.inlines(data["abstract"])}]

    def _collect_defs(self, lines: list[str]) -> list[str]:
        """링크 정의·각주 정의를 먼저 모은다 (문서 어디에 있든 쓸 수 있게). 코드 블록 안은 건너뛴다."""
        out: list[str] = []
        i, n = 0, len(lines)
        fence = None
        while i < n:
            line = lines[i]
            fm = _FENCE.match(line)
            if fence is None and fm:
                fence = fm.group(2)[0] * len(fm.group(2))
            elif fence is not None and line.strip().startswith(fence) and set(line.strip()) <= {fence[0]}:
                fence = None
            elif fence is None:
                m = _FOOTDEF.match(line)
                if m:
                    body = [m.group(2)]
                    j = i + 1
                    while j < n and (_is_blank(lines[j]) and j + 1 < n and _indent(lines[j + 1]) >= 4
                                     or not _is_blank(lines[j]) and _indent(lines[j]) >= 4):
                        body.append(lines[j][4:] if not _is_blank(lines[j]) else "")
                        j += 1
                    self.footdefs.setdefault(m.group(1).strip().lower(), body)
                    i = j
                    continue
                m = _LINKDEF.match(line)
                if m:
                    title = (m.group(3) or "")[1:-1]
                    self.linkdefs.setdefault(_norm_ref(m.group(1)), (m.group(2), title))
                    i += 1
                    continue
            out.append(line)
            i += 1
        return out

    # ------------------------------------------------------------ 블록
    def blocks(self, lines: list[str]) -> list[dict]:
        self.depth += 1
        try:
            if self.depth > MAX_DEPTH:
                return [self._para(lines)] if any(not _is_blank(x) for x in lines) else []
            return self._blocks(lines)
        finally:
            self.depth -= 1

    def _blocks(self, lines: list[str]) -> list[dict]:  # noqa: C901 - 줄 단위 상태 기계
        out: list[dict] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if _is_blank(line):
                i += 1
                continue
            # 코드 울타리 (```math 는 수식)
            m = _FENCE.match(line)
            if m:
                ind, fence, info = len(m.group(1)), m.group(2), m.group(3).strip().lower()
                body = []
                j = i + 1
                while j < n:
                    s = lines[j].strip()
                    if s.startswith(fence[0] * len(fence)) and set(s) <= {fence[0]}:
                        break
                    body.append(lines[j][min(ind, _indent(lines[j])):])
                    j += 1
                text = "\n".join(body)
                if info.split(" ")[0] in ("math", "latex", "tex-math", "katex"):
                    out.append(self._display_math(text, "displaymath"))
                else:
                    out.append({"kind": "verbatim", "text": text})
                i = j + 1
                continue
            # 들여쓴 코드
            if _indent(line) >= 4:
                body = []
                j = i
                while j < n and (_is_blank(lines[j]) or _indent(lines[j]) >= 4):
                    body.append(lines[j][4:])
                    j += 1
                while body and not body[-1].strip():
                    body.pop()
                out.append({"kind": "verbatim", "text": "\n".join(body)})
                i = j
                continue
            # 수식 블록 $$ … $$ / \[ … \]
            s = line.strip()
            if s.startswith("$$") or s.startswith("\\["):
                close = "$$" if s.startswith("$$") else "\\]"
                first = s[2:]
                if first.rstrip().endswith(close) and len(first.rstrip()) >= len(close):
                    out.append(self._display_math(first.rstrip()[:-len(close)], "displaymath"))
                    i += 1
                    continue
                body = [first]
                j = i + 1
                while j < n and close not in lines[j]:
                    body.append(lines[j])
                    j += 1
                if j < n:
                    body.append(lines[j][:lines[j].index(close)])
                out.append(self._display_math("\n".join(body), "displaymath"))
                i = j + 1
                continue
            # \begin{equation} … \end{equation}
            m = _BEGIN_ENV.match(line)
            if m and (m.group(1) in _DISPLAY_ENVS or m.group(1) in ("aligned", "eqnarray", "eqnarray*")):
                env = m.group(1)
                end = f"\\end{{{env}}}"
                body = [line.strip()[len(f"\\begin{{{env}}}"):]]
                j = i
                if end not in line:
                    j = i + 1
                    while j < n and end not in lines[j]:
                        body.append(lines[j])
                        j += 1
                    if j < n:
                        body.append(lines[j][:lines[j].index(end)])
                else:
                    body = [line.strip()[len(f"\\begin{{{env}}}"):line.strip().index(end)]]
                kind = env if env in _DISPLAY_ENVS else "align*"
                out.append(self._display_math("\n".join(body), kind))
                i = j + 1
                continue
            # 제목
            m = _ATX.match(line)
            if m:
                out.append({"kind": "_heading", "level": len(m.group(1)), "text": (m.group(2) or "").strip()})
                i += 1
                continue
            if _HR.match(line):
                i += 1
                continue
            # 인용
            if _QUOTE.match(line):
                body = []
                j = i
                while j < n and not _is_blank(lines[j]):
                    qm = _QUOTE.match(lines[j])
                    if qm:
                        body.append(qm.group(1))
                    elif body and not self._starts_block(lines[j]):
                        body.append(lines[j])       # 게으른 이어짐
                    else:
                        break
                    j += 1
                kids = self.blocks(body)
                alert = self._github_alert(kids)
                out.append(alert or {"kind": "quote", "children": kids})
                i = j
                continue
            # MkDocs 알림 !!! note "제목" / ??? 접기
            m = _ADMON.match(line)
            if m:
                body = []
                j = i + 1
                while j < n and (_is_blank(lines[j]) or _indent(lines[j]) >= 4):
                    body.append(lines[j][4:] if not _is_blank(lines[j]) else "")
                    j += 1
                title = m.group(3) if m.group(3) is not None else m.group(2).capitalize()
                kids = self.blocks(body)
                if m.group(1).startswith("???"):
                    out.append({"kind": "collapse", "title": self.inlines(title), "children": kids})
                else:
                    head = [{"kind": "paragraph", "content": [{"kind": "styled", "style": "bold",
                                                               "children": self.inlines(title)}]}] if title else []
                    out.append({"kind": "quote", "children": head + kids})
                i = j
                continue
            # <details><summary>제목</summary> … </details>
            if line.strip().lower().startswith("<details"):
                j = i
                body = []
                depth = 0
                while j < n:
                    low = lines[j].lower()
                    depth += low.count("<details") - low.count("</details")
                    body.append(lines[j])
                    j += 1
                    if depth <= 0:
                        break
                raw = "\n".join(body)
                sm = re.search(r"<summary>(.*?)</summary>", raw, re.S | re.I)
                inner = re.sub(r"^\s*<details[^>]*>", "", raw, flags=re.I)
                inner = re.sub(r"</details>\s*$", "", inner, flags=re.I)
                inner = re.sub(r"<summary>.*?</summary>", "", inner, count=1, flags=re.S | re.I)
                out.append({"kind": "collapse", "title": self.inlines(sm.group(1).strip() if sm else "자세히"),
                            "children": self.blocks(inner.split("\n"))})
                i = j
                continue
            # 목록
            if _BULLET.match(line) or _ORDERED.match(line):
                block, i = self._list(lines, i)
                out.append(block)
                continue
            # 표
            if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
                block, j = self._table(lines, i)
                if block is not None:
                    out.append(block)
                    i = j
                    continue
            # HTML 주석만 있는 줄
            if line.strip().startswith("<!--"):
                j = i
                raw = []
                while j < n:
                    raw.append(lines[j])
                    j += 1
                    if "-->" in raw[-1]:
                        break
                rest = _HTML_COMMENT.sub("", "\n".join(raw)).strip()
                if rest:
                    out.append(self._para([rest]))
                i = j
                continue
            # 문단 (밑줄 제목 포함)
            body = [line]
            j = i + 1
            while j < n and not _is_blank(lines[j]):
                sm = _SETEXT.match(lines[j])
                if sm and not (sm.group(1)[0] == "-" and len(body) == 0):
                    level = 1 if sm.group(1)[0] == "=" else 2
                    out.append({"kind": "_heading", "level": level, "text": " ".join(x.strip() for x in body)})
                    body = []
                    j += 1
                    break
                if self._starts_block(lines[j], in_para=True):
                    break
                body.append(lines[j])
                j += 1
            if body:
                out.append(self._para(body))
            i = j
        return out

    def _starts_block(self, line: str, in_para: bool = False) -> bool:
        if _ATX.match(line) or _FENCE.match(line) or _QUOTE.match(line) or _HR.match(line):
            return True
        s = line.strip()
        if s.startswith(("$$", "\\[")) or _BEGIN_ENV.match(line):
            return True
        if _BULLET.match(line):
            return not in_para or bool(_BULLET.match(line).group(4).strip())
        m = _ORDERED.match(line)
        if m:
            return not in_para or (m.group(2) == "1" and bool(m.group(5).strip()))
        return False

    def _github_alert(self, kids: list[dict]) -> Optional[dict]:
        """> [!NOTE] 첫 줄 (GitHub 알림) → 굵은 제목이 붙은 인용."""
        if not kids or kids[0].get("kind") != "paragraph":
            return None
        c = kids[0]["content"]
        if not c or c[0].get("kind") != "text":
            return None
        m = re.match(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", c[0]["text"])
        if not m:
            return None
        names = {"NOTE": "참고", "TIP": "팁", "IMPORTANT": "중요", "WARNING": "경고", "CAUTION": "주의"}
        rest = dict(c[0], text=c[0]["text"][m.end():])
        content = ([rest] if rest["text"] else []) + c[1:]
        head = {"kind": "paragraph", "content": [{"kind": "styled", "style": "bold",
                                                   "children": [{"kind": "text", "text": names[m.group(1)]}]}]}
        body = ([{"kind": "paragraph", "content": content}] if content else []) + kids[1:]
        return {"kind": "quote", "children": [head] + body}

    def _list(self, lines: list[str], i: int) -> tuple[dict, int]:
        n = len(lines)
        first = lines[i]
        bm, om = _BULLET.match(first), _ORDERED.match(first)
        ordered = om is not None and bm is None
        delim = om.group(3) if ordered else bm.group(2)
        items: list[dict] = []
        number = int(om.group(2)) if ordered else 0
        while i < n:
            line = lines[i]
            bm, om = _BULLET.match(line), _ORDERED.match(line)
            if ordered and (om is None or om.group(3) != delim):
                break
            if not ordered and (bm is None or bm.group(2) != delim):
                break
            if ordered:
                pre, content = len(om.group(1)) + len(om.group(2)) + 1, om.group(5)
                gap = len(om.group(4))
            else:
                pre, content = len(bm.group(1)) + 1, bm.group(4)
                gap = len(bm.group(3))
            width = pre + (gap if 0 < gap <= 4 else 1)
            body = [content]
            j = i + 1
            while j < n:
                nxt = lines[j]
                if _is_blank(nxt):
                    # 빈 줄 다음이 같은 항목의 들여쓴 이어짐이면 포함
                    k = j
                    while k < n and _is_blank(lines[k]):
                        k += 1
                    if k < n and _indent(lines[k]) >= width:
                        body.extend([""] * (k - j))
                        j = k
                        continue
                    break
                if _indent(nxt) >= width:
                    body.append(nxt[width:])
                elif not self._starts_block(nxt) and body and not _is_blank(body[-1]):
                    body.append(nxt.strip())          # 게으른 이어짐
                else:
                    break
                j += 1
            check = re.match(r"^\[([ xX])\][ \t]+", body[0])
            prefix = None
            if check:
                prefix = "☑ " if check.group(1) in "xX" else "☐ "
                body[0] = body[0][check.end():]
            kids = self.blocks(body)
            if prefix:
                if kids and kids[0].get("kind") == "paragraph":
                    kids[0]["content"].insert(0, {"kind": "text", "text": prefix})
                else:
                    kids.insert(0, {"kind": "paragraph", "content": [{"kind": "text", "text": prefix}]})
            item: dict = {"children": kids}
            if ordered:
                item["number"] = str(number)
                number += 1
            items.append(item)
            # 다음 항목 (사이의 빈 줄 건너뛰기)
            k = j
            while k < n and _is_blank(lines[k]):
                k += 1
            if k < n and (_BULLET.match(lines[k]) or _ORDERED.match(lines[k])) and _indent(lines[k]) < width:
                i = k
                continue
            i = j
            break
        if ordered and items and items[0]["number"] == "1" and all(
                it["number"] == str(k + 1) for k, it in enumerate(items)):
            for it in items:                 # 1부터 차례면 번호를 렌더러에 맡긴다
                del it["number"]
        return {"kind": "list", "style": "enumerate" if ordered else "itemize", "items": items}, i

    def _table(self, lines: list[str], i: int) -> tuple[Optional[dict], int]:
        head = _split_row(lines[i])
        aligns = []
        for c in _split_row(lines[i + 1]):
            c = c.strip()
            aligns.append("c" if c.startswith(":") and c.endswith(":") else "r" if c.endswith(":") else "l")
        if len(aligns) != len(head):
            return None, i
        rows = [{"cells": [{"content": [{"kind": "styled", "style": "bold", "children": self.inlines(c)}]}
                           for c in head], "ruleAbove": True, "ruleBelow": True}]
        j = i + 2
        while j < len(lines) and not _is_blank(lines[j]) and "|" in lines[j] and not self._starts_block(lines[j]):
            cells = _split_row(lines[j])
            cells = (cells + [""] * len(aligns))[:len(aligns)]
            rows.append({"cells": [{"content": self.inlines(c)} for c in cells]})
            j += 1
        rows[-1]["ruleBelow"] = True
        return {"kind": "tabular", "columns": [{"align": a} for a in aligns], "rows": rows}, j

    def _para(self, body: list[str]) -> dict:
        # 줄 끝 두 칸 공백 = 줄바꿈 표지를 지키려고 앞쪽만 다듬는다
        text = "\n".join(re.sub(r"^[ \t]+", "", x) for x in body)
        content = self.inlines(text, keep_images=True)
        imgs = [x for x in content if x.get("kind") == "_image"]
        rest = [x for x in content if x.get("kind") != "_image"
                and not (x.get("kind") == "text" and not x["text"].strip()) and x.get("kind") != "linebreak"]
        if imgs and not rest:                        # 그림만 있는 문단 → 그림 블록
            return {"kind": "_images", "items": [dict(x, kind="image") for x in imgs]}
        return {"kind": "paragraph", "content": _fix_images(content)}

    def _display_math(self, tex: str, env: str) -> dict:
        tex = tex.strip()
        err = _math_error(tex)
        if err:
            self.sink.add("math-syntax", f"수식 구문 오류: {err}")
            return {"kind": "_error_block", "code": "math-syntax", "raw": "$$" + tex + "$$"}
        self._report_math(tex)
        m = _math_source(tex)
        if env in ("align", "align*", "gather", "gather*", "multline", "multline*"):
            rows = [r for r in re.split(r"\\\\(?:\[[^\]]*\])?", tex) if r.strip()] or [tex]
            out_rows = []
            for k, r in enumerate(rows):
                row: dict = {"math": _math_source(r.strip())}
                if not env.endswith("*") and "\\nonumber" not in r and "\\notag" not in r:
                    row["_numbered"] = True
                out_rows.append(row)
            return {"kind": "displaymath", "env": env, "rows": out_rows}
        row = {"math": m}
        if env == "equation":
            row["_numbered"] = True
        return {"kind": "displaymath", "env": env, "rows": [row]}

    def _report_math(self, tex: str) -> None:
        from .build_math import undefined_in_math
        from .lexer import tokenize
        for t in undefined_in_math(tokenize(tex, Sink())):
            self.sink.add("undefined-command", f"정의되지 않은 명령: \\{t.text}")

    # ------------------------------------------------------------ 글 안
    def inlines(self, text: str, keep_images: bool = False) -> list[dict]:
        """글 안 노드들. keep_images 가 아니면 그림은 그림으로 가는 링크(링크 안이면 대체 글)로 바꾼다."""
        self.depth += 1
        try:
            if self.depth > MAX_DEPTH:
                return [{"kind": "text", "text": text}]
            items = _merge(_emphasis(self._scan(text)))
            return items if keep_images else _fix_images(items)
        finally:
            self.depth -= 1

    def _scan(self, s: str) -> list:  # noqa: C901 - 글자 단위 상태 기계
        items: list = []
        buf: list[str] = []
        n = len(s)
        i = 0

        def flush():
            if buf:
                items.append({"kind": "text", "text": "".join(buf)})
                buf.clear()

        def emit(node):
            flush()
            items.append(node)

        while i < n:
            c = s[i]
            # 줄바꿈
            if c == "\n":
                hard = len(buf) >= 2 and buf[-1] == " " and buf[-2] == " "
                while buf and buf[-1] == " ":
                    buf.pop()
                if hard:
                    emit({"kind": "linebreak"})
                else:
                    buf.append(" ")
                i += 1
                while i < n and s[i] == " ":
                    i += 1
                continue
            # 역슬래시
            if c == "\\" and i + 1 < n:
                d = s[i + 1]
                if d == "\n":
                    emit({"kind": "linebreak"})
                    i += 2
                    continue
                if d in "([":
                    close = "\\)" if d == "(" else "\\]"
                    k = s.find(close, i + 2)
                    if k > 0:
                        emit(self._inline_math(s[i + 2:k], display=(d == "[")))
                        i = k + 2
                        continue
                if d in _PUNCT:
                    buf.append(d)
                    i += 2
                    continue
                buf.append("\\")
                i += 1
                continue
            # 코드
            if c == "`":
                k = i
                while k < n and s[k] == "`":
                    k += 1
                tick = s[i:k]
                end = s.find(tick, k)
                while end >= 0 and end + len(tick) < n and s[end + len(tick)] == "`":
                    end = s.find(tick, end + len(tick) + 1)
                if end >= 0:
                    code = s[k:end].replace("\n", " ")
                    if len(code) >= 2 and code[0] == " " and code[-1] == " " and code.strip():
                        code = code[1:-1]
                    emit({"kind": "code", "text": code})
                    i = end + len(tick)
                    continue
                buf.append(tick)
                i = k
                continue
            # 수식 $…$ / $$…$$
            if c == "$":
                node, k = self._dollar(s, i)
                if node is not None:
                    emit(node)
                    i = k
                    continue
                buf.append("$")
                i += 1
                continue
            # 그림·링크
            if c == "!" and i + 1 < n and s[i + 1] == "[":
                res = self._link(s, i + 1, image=True)
                if res is not None:
                    emit(res[0])
                    i = res[1]
                    continue
            if c == "[":
                if i + 1 < n and s[i + 1] == "^":
                    k = s.find("]", i + 2)
                    if k > 0:
                        emit(self._footnote_ref(s[i + 2:k]))
                        i = k + 1
                        continue
                res = self._link(s, i, image=False)
                if res is not None:
                    emit(res[0])
                    i = res[1]
                    continue
            # <자동 링크>, HTML
            if c == "<":
                res = self._angle(s, i)
                if res is not None:
                    if res[0] is not None:
                        emit(res[0])
                    i = res[1]
                    continue
            # 강조 표지
            if c in "*_~":
                k = i
                while k < n and s[k] == c:
                    k += 1
                run = k - i
                before = s[i - 1] if i > 0 else " "
                after = s[k] if k < n else " "
                left = not after.isspace() and (not _is_punct(after) or before.isspace() or _is_punct(before))
                right = not before.isspace() and (not _is_punct(before) or after.isspace() or _is_punct(after))
                if c == "_":
                    can_open = left and (not right or _is_punct(before))
                    can_close = right and (not left or _is_punct(after))
                else:
                    can_open, can_close = left, right
                if c == "~" and run not in (1, 2):
                    can_open = can_close = False
                flush()
                items.append({"_delim": c, "n": run, "open": can_open, "close": can_close, "orig": run})
                i = k
                continue
            # 엔티티
            if c == "&":
                m = re.match(r"&(#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});", s[i:])
                if m:
                    buf.append(html.unescape(m.group(0)))
                    i += m.end()
                    continue
            # 맨 주소 (GitHub)
            if c in "hw" and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] in "/:")):
                m = re.match(r"(https?://|www\.)[^\s<]+", s[i:])
                if m:
                    url = m.group(0)
                    while url and url[-1] in ".,:;!?\"'*_~":
                        url = url[:-1]
                    while url.endswith(")") and url.count(")") > url.count("("):
                        url = url[:-1]
                    if url and url not in ("https://", "http://", "www."):
                        emit(self._url_link(url if "://" in url else "https://" + url, url))
                        i += len(url)
                        continue
            buf.append(c)
            i += 1
        flush()
        return items

    def _dollar(self, s: str, i: int) -> tuple[Optional[dict], int]:
        n = len(s)
        if s.startswith("$$", i):
            k = s.find("$$", i + 2)
            if k > i + 2:
                return self._inline_math(s[i + 2:k], display=True), k + 2
            return None, i
        if i + 1 >= n or s[i + 1].isspace() or (i > 0 and s[i - 1] == "\\"):
            return None, i
        k = i + 1
        while k < n:
            if s[k] == "\\":
                k += 2
                continue
            if s[k] == "$":
                if not s[k - 1].isspace() and not (k + 1 < n and s[k + 1].isdigit()):
                    return self._inline_math(s[i + 1:k]), k + 1
                return None, i
            if s[k] == "\n" and k + 1 < n and s[k + 1] == "\n":
                break
            k += 1
        return None, i

    def _inline_math(self, tex: str, display: bool = False) -> dict:
        tex = tex.strip()
        err = _math_error(tex)
        if err:
            self.sink.add("math-syntax", f"수식 구문 오류: {err}")
            return {"kind": "error", "code": "math-syntax", "raw": "$" + tex + "$"}
        self._report_math(tex)
        return {"kind": "math", "math": _math_source(("\\displaystyle " if display else "") + tex)}

    def _footnote_ref(self, label: str) -> dict:
        key = label.strip().lower()
        if key in self.footnotes_used:
            # 같은 각주를 두 번 부르면 두 번째는 같은 번호의 위 첨자 글자로
            return {"kind": "text", "text": f"[{self.footnotes_used[key]['number']}]"}
        body = self.footdefs.get(key)
        if body is None:
            self.sink.add("broken-ref", f"각주 정의를 찾을 수 없다: [^{label}]", None)
            return {"kind": "text", "text": f"[^{label}]"}
        node = {"kind": "footnote", "number": "", "children": []}
        self.footnotes_used[key] = node
        node["number"] = str(len(self.footnotes_used))
        node["children"] = [x for b in self.blocks(body) for x in self._finish_block(b)]
        return node

    def _link(self, s: str, i: int, image: bool) -> Optional[tuple[dict, int]]:
        """s[i] == '['. [글](주소 "제목") · [글][이름] · [글][] · [이름]."""
        n = len(s)
        depth = 0
        k = i
        while k < n:
            ch = s[k]
            if ch == "\\":
                k += 2
                continue
            if ch == "`":
                e = s.find("`", k + 1)
                k = e + 1 if e > 0 else k + 1
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if k >= n:
            return None
        label = s[i + 1:k]
        j = k + 1
        dest = title = None
        if j < n and s[j] == "(":
            m = re.match(r"\(\s*(<[^>\n]*>|(?:[^\s()\\]|\\.|\([^\s()]*\))*)"
                         r"(?:\s+(\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)", s[j:])
            if not m:
                return None
            dest = m.group(1).strip("<>")
            title = (m.group(2) or "")[1:-1]
            end = j + m.end()
        else:
            ref = None
            end = j
            if j < n and s[j] == "[":
                e = s.find("]", j + 1)
                if e > 0:
                    ref = s[j + 1:e] or label
                    end = e + 1
            if ref is None:
                ref = label
            hit = self.linkdefs.get(_norm_ref(ref))
            if hit is None:
                return None
            dest, title = hit
        dest = re.sub(r"\\(.)", r"\1", dest)
        if image:
            src = self._fix_url(dest)
            alt = _plain(self.inlines(label)) if label else ""
            if src is None:
                return {"kind": "text", "text": alt}, end
            node = {"kind": "_image", "src": src}
            if alt:
                node["alt"] = alt
            return node, end
        kids = _fix_images(self.inlines(label, keep_images=True), in_link=True)
        return self._href(dest, kids), end

    def _angle(self, s: str, i: int) -> Optional[tuple[Optional[dict], int]]:
        m = re.match(r"<([A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\s<>]*)>", s[i:])
        if m:
            return self._url_link(m.group(1), m.group(1)), i + m.end()
        m = re.match(r"<([A-Za-z0-9.!#$%&'*+/=?^_`{|}~\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)>", s[i:])
        if m:
            return {"kind": "text", "text": m.group(1)}, i + m.end()
        m = re.match(r"<!--.*?-->", s[i:], re.S)
        if m:
            return None, i + m.end()
        m = re.match(r"<br\s*/?>", s[i:], re.I)
        if m:
            return {"kind": "linebreak"}, i + m.end()
        m = re.match(r"<a\s[^>]*?href\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)[^>]*>(.*?)</a\s*>", s[i:], re.I | re.S)
        if m:
            href = html.unescape(m.group(1).strip("\"'"))
            kids = _fix_images(self.inlines(m.group(2), keep_images=True), in_link=True)
            return self._href(href, kids), i + m.end()
        m = re.match(r"<img\s[^>]*?src\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)[^>]*?/?>", s[i:], re.I)
        if m:
            src = self._fix_url(html.unescape(m.group(1).strip("\"'")))
            am = re.search(r"alt\s*=\s*(\"[^\"]*\"|'[^']*')", m.group(0), re.I)
            if src is None:
                return None, i + m.end()
            node = {"kind": "_image", "src": src}
            if am and am.group(1)[1:-1]:
                node["alt"] = html.unescape(am.group(1)[1:-1])
            return node, i + m.end()
        m = re.match(r"</?[A-Za-z][A-Za-z0-9\-]*(?:\s[^<>]*)?/?>", s[i:])
        if m:                                     # 그 밖의 태그: 지우고 글자만
            return None, i + m.end()
        return None

    # ------------------------------------------------------------ 주소
    def _fix_url(self, url: str) -> Optional[str]:
        """http → https, 금지 스킴 → None."""
        u = url.strip()
        if re.match(r"^http://", u, re.I):
            u = "https://" + u[7:]
        if classify(u) == "forbidden":
            return None
        return u

    def _url_link(self, url: str, shown: str) -> dict:
        fixed = self._fix_url(url)
        if fixed is None:
            return {"kind": "text", "text": shown}
        return {"kind": "link", "linkType": "url" if shown == url else "href", "target": {"url": fixed},
                **({} if shown == url else {"children": [{"kind": "text", "text": shown}]})}

    def _href(self, dest: str, kids: list[dict]) -> dict:
        if dest.startswith("#"):
            return {"kind": "_anchor", "label": dest[1:], "children": kids}
        if re.match(r"^(mailto|tel):", dest, re.I):
            return {"kind": "styled", "style": "emph", "children": kids} if kids else {"kind": "text", "text": dest}
        fixed = self._fix_url(dest)
        if fixed is None:
            self.sink.add("insecure-resource", f"허용되지 않는 주소: {dest}")
            return {"kind": "error", "code": "insecure-resource", "raw": dest, **({"children": kids} if kids else {})}
        node = {"kind": "link", "linkType": "href", "target": {"url": fixed}}
        if kids:
            node["children"] = kids
        return node

    # ------------------------------------------------------------ 마무리
    def build(self) -> dict:
        raw = self.blocks(self.lines)
        heads = [b for b in raw if b.get("kind") == "_heading"]
        shift = 0
        if raw and raw[0].get("kind") == "_heading" and raw[0]["level"] == 1 and \
                sum(1 for h in heads if h["level"] == 1) == 1 and "title" not in self.meta:
            self.meta["title"] = self.inlines(raw[0]["text"])
            raw = raw[1:]
            shift = 1
        body = self._sections(raw, shift)
        return body

    def _sections(self, raw: list[dict], shift: int) -> list[dict]:
        """제목으로 나뉜 평평한 블록 → 절 중첩 (절 번호 없음)."""
        body: list[dict] = []
        stack: list[dict] = []
        for b in raw:
            if b.get("kind") == "_heading":
                level = max(1, min(4, b["level"] - shift))
                title = self.inlines(b["text"])
                node = {"kind": "section", "level": level, "title": title, "children": []}
                slug = slugify(_plain(title)) or "section"
                k = self.slugs.get(slug, 0)
                self.slugs[slug] = k + 1
                label = slug if k == 0 else f"{slug}-{k}"
                node["label"] = label
                self.labels[label] = node
                while stack and stack[-1]["level"] >= level:
                    stack.pop()
                (stack[-1]["children"] if stack else body).append(node)
                stack.append(node)
            else:
                (stack[-1]["children"] if stack else body).extend(self._finish_block(b))
        return body

    def _finish_block(self, b: dict) -> list[dict]:
        k = b.get("kind")
        if k == "_images":
            return b["items"]
        if k == "_error_block":
            return [{"kind": "error", "code": b["code"], "raw": b["raw"], "_block": True}]
        if k == "_heading":          # 인용·목록 안의 제목: 굵은 문단으로
            return [{"kind": "paragraph", "content": [{"kind": "styled", "style": "bold",
                                                       "children": self.inlines(b["text"])}]}]
        for key in ("children",):
            if key in b and isinstance(b[key], list):
                b[key] = [x for c in b[key] for x in self._finish_block(c)]
        if k == "list":
            for it in b["items"]:
                it["children"] = [x for c in it["children"] for x in self._finish_block(c)]
        return [b]


# ====================================================================== 도우미
def _fix_images(nodes: list[dict], in_link: bool = False) -> list[dict]:
    """글 안의 그림 → 그림으로 가는 링크 (그림은 블록만 된다). 링크 안이면 대체 글만."""
    out = []
    for x in nodes:
        if x.get("kind") == "_image":
            alt = x.get("alt") or "그림"
            if in_link:
                out.append({"kind": "text", "text": alt})
            else:
                out.append({"kind": "link", "linkType": "href", "target": {"url": x["src"]},
                            "children": [{"kind": "text", "text": "🖼 " + alt}]})
            continue
        if isinstance(x.get("children"), list):
            x = dict(x, children=_fix_images(x["children"], in_link or x.get("kind") == "link"))
        out.append(x)
    return _merge(out)


def _norm_ref(s: str) -> str:
    return " ".join(s.lower().split())


def _is_punct(ch: str) -> bool:
    return ch in _PUNCT or unicodedata.category(ch).startswith("P")


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, k = [], [], 0
    while k < len(s):
        if s[k] == "\\" and k + 1 < len(s) and s[k + 1] == "|":
            cur.append("|")
            k += 2
            continue
        if s[k] == "`":
            e = s.find("`", k + 1)
            if e > 0:
                cur.append(s[k:e + 1])
                k = e + 1
                continue
        if s[k] == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(s[k])
        k += 1
    cells.append("".join(cur).strip())
    return cells


def _plain(nodes: list[dict]) -> str:
    out = []
    for x in nodes:
        if x.get("kind") == "text":
            out.append(x["text"])
        elif x.get("kind") == "code":
            out.append(x["text"])
        elif x.get("kind") == "math":
            out.append(x["math"]["tex"])
        elif x.get("children"):
            out.append(_plain(x["children"]))
    return "".join(out)


def _math_error(tex: str) -> Optional[str]:
    from .build_math import check_math
    from .lexer import tokenize
    if not tex.strip():
        return "빈 수식"
    return check_math(tokenize(tex, Sink()))


def _math_source(tex: str) -> dict:
    from .build_math import scripts_of
    from .lexer import tokenize
    m: dict = {"tex": " ".join(tex.split())}
    sc = scripts_of(tokenize(tex, Sink()))
    if sc:
        m["scripts"] = sc
    return m


def _emphasis(items: list) -> list:
    """CommonMark 의 강조 짝 맞추기 (간단판). *·_ 하나 = 기울임, 둘 = 굵게, ~~ = 취소선."""
    i = 0
    while i < len(items):
        cl = items[i]
        if not (isinstance(cl, dict) and "_delim" in cl and cl["close"] and cl["n"] > 0):
            i += 1
            continue
        j = i - 1
        found = -1
        while j >= 0:
            op = items[j]
            if isinstance(op, dict) and op.get("_delim") == cl["_delim"] and op["open"] and op["n"] > 0:
                both = (op["open"] and op["close"]) or (cl["open"] and cl["close"])
                if not (both and (op["orig"] + cl["orig"]) % 3 == 0 and not (op["orig"] % 3 == 0 and cl["orig"] % 3 == 0)):
                    found = j
                    break
            j -= 1
        if found < 0:
            i += 1
            continue
        op = items[found]
        if cl["_delim"] == "~":
            if op["n"] != cl["n"]:
                i += 1
                continue
            use = op["n"]
        else:
            use = 2 if op["n"] >= 2 and cl["n"] >= 2 else 1
        inner = [x for x in items[found + 1:i] if not (isinstance(x, dict) and "_delim" in x and x["n"] == 0)]
        inner = _literal_delims(inner)
        if cl["_delim"] == "~":
            node = {"kind": "styled", "style": "strike", "children": _merge(inner)}
        else:
            node = {"kind": "styled", "style": "bold" if use == 2 else "emph", "children": _merge(inner)}
        op["n"] -= use
        cl["n"] -= use
        items[found + 1:i] = [node]
        i = found + 2
    return _merge(_literal_delims(items))


def _literal_delims(items: list) -> list:
    out = []
    for x in items:
        if isinstance(x, dict) and "_delim" in x:
            if x["n"] > 0:
                out.append({"kind": "text", "text": x["_delim"] * x["n"]})
        elif isinstance(x, dict) and x.get("kind") == "_group":
            out.extend(x["children"])
        else:
            out.append(x)
    return out


def _merge(items: list) -> list[dict]:
    out: list[dict] = []
    for x in _literal_delims(items):
        if x.get("kind") == "text":
            if not x["text"]:
                continue
            if out and out[-1].get("kind") == "text":
                out[-1] = {"kind": "text", "text": out[-1]["text"] + x["text"]}
                continue
        out.append(x)
    return out


# ====================================================================== 공개 함수
def parse_markdown(text: str, url: str = "", base_dir: Optional[Path] = None) -> dict[str, Any]:
    """Markdown 원문 → 문서 트리 (schema/document-tree.schema.json)."""
    sink = Sink()
    try:
        conv = _Converter(text, url, sink)
        body = conv.build()
        meta, labels_raw = conv.meta, conv.labels
    except RecursionError:
        sink.add("render-timeout", "문서 중첩이 너무 깊어 해석을 멈췄다")
        body, meta, labels_raw = [], {"documentclass": "hypertex"}, {}
    except Exception as e:   # noqa: BLE001 - 어떤 입력에도 트리를 낸다 (명세 7절)
        sink.add("render-timeout", f"Markdown 변환 내부 오류: {type(e).__name__}: {e}")
        body, meta, labels_raw = [], {"documentclass": "hypertex"}, {}
    ids = _Ids()
    ids.walk(body)
    if meta.get("abstract"):
        ids.walk(meta["abstract"])
    labels = {}
    for name, node in labels_raw.items():
        if "id" in node:
            labels[name] = {"node": node["id"], "kind": "section"}
    _resolve_anchors(body, labels, sink)
    _number_equations(body)
    return {
        "hypertex": "2.0",
        "source": {"url": url, "mode": "markdown",
                   "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
        "meta": meta,
        "labels": labels,
        "parameters": [],
        "bibliography": [],
        "body": body,
        "diagnostics": sink.to_json(),
    }


class _Ids:
    """문서 순서대로 n1, n2, … (블록·목록 항목·수식 행·각주)."""

    def __init__(self):
        self.n = 0

    def new(self) -> str:
        self.n += 1
        return f"n{self.n}"

    def walk(self, x) -> None:
        if isinstance(x, list):
            for y in x:
                self.walk(y)
            return
        if not isinstance(x, dict):
            return
        k = x.get("kind")
        if k in ("section", "paragraph", "list", "quote", "verbatim", "displaymath", "collapse", "image",
                 "tabular", "footnote") or (k == "error" and x.pop("_block", False)):
            x["id"] = self.new()
        if k == "section":
            self.walk(x["title"])
            self.walk(x["children"])
            return
        if k == "list":
            for it in x["items"]:
                it["id"] = self.new()
                self.walk(it["children"])
            return
        if k == "displaymath":
            for r in x["rows"]:
                r["id"] = self.new()
            return
        for key in ("title", "content", "children"):
            if isinstance(x.get(key), list):
                self.walk(x[key])
        if k == "tabular":
            for r in x["rows"]:
                for c in r["cells"]:
                    self.walk(c["content"])


def _resolve_anchors(x, labels: dict, sink: Sink) -> None:
    """[글](#앵커) → 같은 문서의 절 참조 (없는 앵커는 그냥 #링크)."""
    if isinstance(x, list):
        for k, y in enumerate(x):
            if isinstance(y, dict) and y.get("kind") == "_anchor":
                name = y["label"]
                lab = name if name in labels else slugify(urllib_unquote(name))
                if lab in labels:
                    node = {"kind": "link", "linkType": "ref", "target": {"label": lab},
                            "resolved": {"node": labels[lab]["node"]}}
                else:
                    node = {"kind": "link", "linkType": "href", "target": {"url": "#" + name}}
                if y.get("children"):
                    node["children"] = y["children"]
                x[k] = node
                _resolve_anchors(node.get("children"), labels, sink)
            else:
                _resolve_anchors(y, labels, sink)
    elif isinstance(x, dict):
        for key, v in x.items():
            if isinstance(v, (list, dict)) and key != "math":
                _resolve_anchors(v, labels, sink)


def urllib_unquote(s: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(s)


def _number_equations(body: list) -> None:
    """번호 있는 수식 행(\\begin{equation} 등)에 문서 전체 일련번호."""
    count = [0]

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            if x.get("kind") == "displaymath":
                for r in x["rows"]:
                    if r.pop("_numbered", False):
                        count[0] += 1
                        r["number"] = str(count[0])
                return
            for key, v in x.items():
                if isinstance(v, (list, dict)) and key != "math":
                    walk(v)
    walk(body)
