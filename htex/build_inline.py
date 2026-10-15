"""트리 빌더: 인라인 노드 (텍스트, 서식, 각주, 인라인 수식, 링크, \\showparam, 오류). (담당: C)"""
from __future__ import annotations

import datetime
import re
import unicodedata
from typing import Any, Optional

from .build_math import (check_math, detok, find_showparams, norm_ws, raw_text,
                         scripts_of, split_top_showparam, undefined_in_math)
from .build_state import Target, sanitize_label
from .loader import check_url, classify
from .tokens import T, Token, error_token_info

STYLES = {"emph": "emph", "textbf": "bold", "textit": "italic", "texttt": "mono", "textsc": "smallcaps"}
TRANSPARENT = {"textrm", "textsf", "textup", "textnormal", "mbox", "textmd", "textsl"}

SYMBOLS = {
    "ldots": "…", "dots": "…", "LaTeX": "LaTeX", "TeX": "TeX",
    "quad": " ", "qquad": "  ", ",": " ", ";": " ", ":": " ",
    " ": " ", "!": "", "-": "", "/": "", "@": "",
    "{": "{", "}": "}", "%": "%", "$": "$", "&": "&", "#": "#", "_": "_", "|": "‖",
    "[": "[", "]": "]",
    "textbackslash": "\\", "textasciitilde": "~", "textasciicircum": "^",
    "textendash": "–", "textemdash": "—", "S": "§", "P": "¶",
    "copyright": "©", "dag": "†", "ddag": "‡", "slash": "/",
}
ACCENTS = {"'": "́", "`": "̀", "^": "̂", "\"": "̈", "~": "̃",
           "=": "̄", ".": "̇"}
# 본문에서 인수와 함께 조용히 무시하는 명령 (자리만 차지하는 명령)
IGNORED_WITH_ARG = {"HyperTeXversion"}
IGNORED = {"textwidth", "linewidth", "nonumber", "notag", "hline", "centering", "noindent",
           "and", "maketitle"}

EXTERNAL_PREFIXES = ("arxiv:", "doi:", "isbn:", "htex://", "https://")


def is_space_text(s: str) -> bool:
    return s != "" and s.strip(" ") == ""


def normalize_inlines(nodes: list[dict], trim: bool = True) -> list[dict]:
    """공백 연속을 하나로, 인접 text 합치기, 빈 text 지우기, (trim이면) 앞뒤 공백 제거."""
    out: list[dict] = []
    for n in nodes:
        if n.get("kind") == "text":
            if out and out[-1].get("kind") == "text":
                out[-1] = {"kind": "text", "text": out[-1]["text"] + n["text"]}
            else:
                out.append({"kind": "text", "text": n["text"]})
        else:
            if "children" in n and n.get("kind") in ("styled", "link", "error"):
                n["children"] = normalize_inlines(n["children"], trim=False)
                if not n["children"] and n.get("kind") != "styled":
                    del n["children"]
            out.append(n)
    for i, n in enumerate(out):
        if n.get("kind") == "text":
            n["text"] = re.sub(" {2,}", " ", n["text"])
            # 강제 줄바꿈 앞뒤 공백은 지운다 (LaTeX와 같다)
            if i + 1 < len(out) and out[i + 1].get("kind") == "linebreak":
                n["text"] = n["text"].rstrip(" ")
            if i > 0 and out[i - 1].get("kind") == "linebreak":
                n["text"] = n["text"].lstrip(" ")
    if trim and out:
        if out[0].get("kind") == "text":
            out[0]["text"] = out[0]["text"].lstrip(" ")
        if out[-1].get("kind") == "text":
            out[-1]["text"] = out[-1]["text"].rstrip(" ")
    return [n for n in out if not (n.get("kind") == "text" and n["text"] == "")]


class InlineMixin:
    # ------------------------------------------------------------ 출력
    def add_text(self, s: str) -> None:
        if not s:
            return
        dest = self.inline_dest(opening=not is_space_text(s))
        if dest is None:
            return
        if dest and dest[-1].get("kind") == "text":
            dest[-1]["text"] += s
        else:
            dest.append({"kind": "text", "text": s})

    def emit(self, node: dict) -> None:
        dest = self.inline_dest(opening=True)
        if dest is not None:
            dest.append(node)

    def inline_dest(self, opening: bool) -> Optional[list]:
        if self.inl_out is not None:
            return self.inl_out
        if self.para is None:
            if not opening:
                return None
            self.open_para()
        return self.para["content"]

    # ------------------------------------------------------------ 글자
    def text_char(self) -> None:
        t = self.cur
        if t.text in ("`", "'") and self.ctx.mode == "compat":
            # LaTeX 따옴표 합자: `` → “, '' → ”, ` → ‘ (홑 ' 는 그대로 둔다)
            nxt = self.at(self.pos + 1)
            if nxt.type is T.CHAR and nxt.text == t.text:
                self.adv(2)
                self.add_text("“" if t.text == "`" else "”")
                return
            if t.text == "`":
                self.adv()
                self.add_text("‘")
                return
        if t.text == "-":
            k = 0
            while self.at(self.pos + k).type is T.CHAR and self.at(self.pos + k).text == "-" and k < 3:
                k += 1
            self.adv(k)
            self.add_text({1: "-", 2: "–", 3: "—"}[k])
            return
        self.adv()
        self.add_text(t.text)

    # ------------------------------------------------------------ 인라인 명령
    def inline_command(self, tok: Token) -> bool:
        """본문 인라인 명령을 처리했으면 True."""
        info = error_token_info(tok)
        if info is not None:  # 확장기가 남긴 오류 표지 (진단은 이미 확장기가 냈다)
            self.adv()
            self.emit({"kind": "error", "code": info[0], "raw": info[1]})
            return True
        name = tok.text
        if name in STYLES:
            self.adv()
            arg = self.read_group()
            self.emit({"kind": "styled", "style": STYLES[name],
                       "children": self.inline_seq(arg, trim=False)})
            return True
        if name in TRANSPARENT:
            self.adv()
            arg = self.read_group()
            for n in self.inline_seq(arg, trim=False):
                if n.get("kind") == "text":
                    self.add_text(n["text"])
                else:
                    self.emit(n)
            return True
        if name in SYMBOLS:
            self.adv()
            self.add_text(SYMBOLS[name])
            return True
        if name in ACCENTS:
            self.adv()
            arg = self.read_group()
            s = raw_text(arg)
            if s:
                self.add_text(unicodedata.normalize("NFC", s[0] + ACCENTS[name] + s[1:]))
            return True
        if name == "today":
            self.adv()
            self.add_text(datetime.date.today().isoformat())
            return True
        if name in ("\\", "newline"):
            self.adv()
            if name == "\\":
                self.take_star()
                save = self.pos
                opt = self.read_opt()
                if opt is not None and not re.match(r"^\s*-?[0-9.]+\s*[a-z]{2}\s*$", raw_text(opt)):
                    self.pos = save
            if self.inl_out is not None or self.para is not None:
                self.emit({"kind": "linebreak"})
            return True
        if name == "footnote":
            self.footnote(tok)
            return True
        if name in ("ref", "eqref"):
            self.ref_link(tok)
            return True
        if name == "href":
            self.href_link(tok)
            return True
        if name == "url":
            self.adv()
            url = norm_ws(raw_text(self.read_group()))
            if check_url(url, tok.span, self.sink):
                self.emit({"kind": "link", "linkType": "url", "target": {"url": url}})
            else:
                self.emit({"kind": "error", "code": "insecure-resource", "raw": f"\\url{{{url}}}"})
            return True
        if name == "cite":
            self.cite_link(tok)
            return True
        if name == "showparam":
            self.adv()
            arg = self.read_group()
            self.showparam_node(arg, tok, f"\\showparam{{{raw_text(arg)}}}")
            return True
        if name == "label":
            self.adv()
            self.register_label(raw_text(self.read_group()), self.target, tok)
            return True
        if name in IGNORED:
            self.adv()
            return True
        if name in IGNORED_WITH_ARG:
            self.adv()
            self.read_group()
            return True
        if name == "tag":
            self.adv()
            self.take_star()
            self.read_group()
            return True
        if name == "multicolumn":   # 표 밖: 내용만
            self.adv()
            self.read_group()
            self.read_group()
            for n in self.inline_seq(self.read_group(), trim=False):
                self.emit(n) if n.get("kind") != "text" else self.add_text(n["text"])
            return True
        if name == "cline":
            self.adv()
            self.read_group()
            return True
        if name in ("(", ")") and name == "(":
            self.adv()
            body, closed = self.collect_until(lambda t: t.type is T.CS and t.text == ")")
            self.inline_math(body, tok, "\\(", "\\)" if closed else "", closed)
            return True
        return False

    # ------------------------------------------------------------ 각주
    def footnote(self, tok: Token) -> None:
        self.adv()
        self.read_opt()
        dest = self.inline_dest(opening=True)
        node = {"kind": "footnote", "id": self.new_id(), "number": "", "children": []}
        node["number"] = self.next_number("footnote")
        saved = self.target
        self.target = Target(None, node["id"], "footnote", node["number"])
        arg = self.read_group(allow_par=True)
        if dest is not None:
            dest.append(node)
        node["children"] = self.blocks_seq(arg)
        self.target = saved

    # ------------------------------------------------------------ 수식
    def collect_until(self, pred, stop_par: bool = True) -> tuple[list[Token], bool]:
        """pred를 만족하는 토큰까지 모은다 (그 토큰은 소비). (토큰들, 닫혔는지)"""
        start = self.pos
        i = start
        while True:
            t = self.at(i)
            if t.type is T.EOF or (stop_par and t.type is T.PAR):
                self.pos = i
                return self.toks[start:i], False
            if pred(t):
                self.pos = i + 1
                return self.toks[start:i], True
            i += 1

    def math_nodes(self, body: list[Token], tok: Token, raw: str) -> list[dict]:
        """인라인 수식 → 노드들 (math, showparam, 오류)."""
        err = check_math(body)
        if err:
            self.sink.add("math-syntax", f"수식 구문 오류: {err}", tok.span)
            return [{"kind": "error", "code": "math-syntax", "raw": raw}]
        self.report_undefined_math(body)
        out: list[dict] = []
        for seg in split_top_showparam(body):
            if seg[0] == "math":
                m = self.math_source(seg[1], tok)
                if m["tex"]:
                    out.append({"kind": "math", "math": m})
            else:
                out.extend(self.showparam_nodes(seg[1], tok, detok(seg[2])))
        if not out:
            out.append({"kind": "math", "math": {"tex": ""}})
        return out

    def math_source(self, tokens: list[Token], tok: Token) -> dict:
        m: dict[str, Any] = {"tex": detok(tokens).strip()}
        sc = scripts_of(tokens)
        if sc:
            m["scripts"] = sc
        params = []
        for p in find_showparams(tokens):
            if p in self.param_names:
                if p not in params:
                    params.append(p)
            else:
                self.sink.add("unknown-parameter", f"선언되지 않은 매개변수: {p}", tok.span)
        if params:
            m["params"] = params
        return m

    def report_undefined_math(self, body: list[Token]) -> None:
        for t in undefined_in_math(body):
            self.sink.add("undefined-command", f"정의되지 않은 명령: \\{t.text}", t.span)

    def inline_math(self, body, tok, open_d, close_d, closed) -> None:
        raw = open_d + detok(body) + close_d
        if not closed:
            self.sink.add("math-syntax", "수식이 닫히지 않았다", tok.span)
            self.emit({"kind": "error", "code": "math-syntax", "raw": raw})
            return
        for n in self.math_nodes(body, tok, raw):
            self.emit(n)

    def math_command_in_text(self, tok: Token) -> None:
        """본문에 나온 수식 전용 명령 (\\alpha 등): 바로 뒤 {…} 인수와 함께 인라인 수식으로."""
        start = self.pos
        self.adv()
        while self.cur.type is T.BGROUP:
            self.read_group()
        body = self.toks[start:self.pos]
        for n in self.math_nodes(body, tok, detok(body)):
            self.emit(n)

    # ------------------------------------------------------------ 매개변수
    def showparam_nodes(self, name: str, tok: Token, raw: str) -> list[dict]:
        if name in self.param_names:
            return [{"kind": "showparam", "name": name}]
        self.sink.add("unknown-parameter", f"선언되지 않은 매개변수: {name}", tok.span)
        return [{"kind": "error", "code": "unknown-parameter", "raw": raw}]

    def showparam_node(self, arg: list[Token], tok: Token, raw: str) -> None:
        from .build_math import param_name
        for n in self.showparam_nodes(param_name(arg), tok, raw):
            self.emit(n)

    # ------------------------------------------------------------ 링크
    def ref_link(self, tok: Token) -> None:
        self.adv()
        self.take_star()
        raw = norm_ws(raw_text(self.read_group()))
        kind = tok.text
        if "#" in raw:
            doc, label = raw.split("#", 1)
            doc, label = doc.strip(), sanitize_label(label)
            if not check_url(doc, tok.span, self.sink):
                self.emit({"kind": "error", "code": "insecure-resource", "raw": f"\\{kind}{{{raw}}}"})
                return
            target: dict = {"label": label} if label else {}
            if doc:
                target = {"doc": doc, **target} if classify(doc) != "forbidden" else target
                self.emit({"kind": "link", "linkType": kind, "target": target})
                return
            raw = label
        label = sanitize_label(raw)
        node = {"kind": "link", "linkType": kind, "target": {"label": label} if label else {}}
        self.emit(node)
        self.pending_refs.append((node, label, tok))

    def href_link(self, tok: Token) -> None:
        self.adv()
        url = norm_ws(raw_text(self.read_group()))
        text_toks = self.read_group()
        children = self.inline_seq(text_toks)
        if check_url(url, tok.span, self.sink):
            node = {"kind": "link", "linkType": "href", "target": {"url": url}}
            if children:
                node["children"] = children
            self.emit(node)
        else:
            node = {"kind": "error", "code": "insecure-resource",
                    "raw": f"\\href{{{url}}}{{{detok(text_toks)}}}"}
            if children:
                node["children"] = children
            self.emit(node)

    def cite_link(self, tok: Token) -> None:
        self.adv()
        self.read_opt()
        keys = [k.strip() for k in raw_text(self.read_group()).split(",")]
        keys = [k for k in keys if k]
        node = {"kind": "link", "linkType": "cite", "target": {"keys": keys}}
        self.emit(node)
        bib = [k for k in keys if not k.lower().startswith(EXTERNAL_PREFIXES)]
        if bib:
            self.pending_cites.append((node, bib, tok))

    # ------------------------------------------------------------ 정의되지 않은 명령
    def undefined_command(self, tok: Token) -> None:
        self.adv()
        self.take_star()
        children: list[dict] = []
        while self.cur.type is T.BGROUP or (self.cur.type is T.CHAR and self.cur.text == "["
                                             and self.read_opt_peek()):
            if self.cur.type is T.BGROUP:
                children.extend(self.inline_seq(self.read_group(), trim=False))
            else:
                opt = self.read_opt()
                children.extend(self.inline_seq(opt or [], trim=False))
        self.sink.add("undefined-command", f"정의되지 않은 명령: \\{tok.text}", tok.span)
        node = {"kind": "error", "code": "undefined-command", "raw": "\\" + tok.text}
        if children:
            node["children"] = children
        self.emit(node)

    def read_opt_peek(self) -> bool:
        save = self.pos
        ok = self.read_opt() is not None
        self.pos = save
        return ok
