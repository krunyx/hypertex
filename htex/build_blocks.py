"""트리 빌더: 블록 노드 (절, 단락, 환경, 디스플레이 수식, 그림·표, 참고문헌). (담당: C)"""
from __future__ import annotations

import re
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Optional

from .build_inline import normalize_inlines
from .build_math import (MATH_INNER_ENVS, check_math, detok, env_name_at, extract_markers,
                         norm_ws, raw_text, split_rows, strip_row_prefix)
from .build_state import MAX_DEPTH, SECTION_LEVELS, Target, span_json
from .loader import check_url
from .tokens import T, Token

MATH_ENVS = {"equation", "equation*", "align", "align*", "gather", "gather*",
             "multline", "multline*", "displaymath"}
LIST_ENVS = {"itemize", "enumerate", "description"}
LAYOUT_ENVS = {"center", "flushleft", "flushright", "minipage", "small", "footnotesize"}
PICTURE_ENVS = {"axis", "semilogxaxis", "semilogyaxis", "loglogaxis"}
# 환경을 닫히지 않은 것으로 끝내는 절 명령 (\paragraph는 환경 안에 있어도 된다)
BREAKING_SECTIONS = {"section", "subsection", "subsubsection"}

_ID_RE = re.compile(r"\b(doi|arXiv):\s*([^\s,;]+)", re.IGNORECASE)


class BlockMixin:
    # ------------------------------------------------------------ 단락과 블록 배치
    def open_para(self) -> None:
        self.para = {"kind": "paragraph", "id": self.new_id(), "span": span_json(self.cur),
                     "content": []}
        self.out.append(self.para)

    def close_para(self) -> None:
        p = self.para
        if p is None:
            return
        self.para = None
        p["content"] = normalize_inlines(p["content"])
        if not p["content"] and self.out and self.out[-1] is p:
            self.out.pop()

    def begin_block(self, node: dict) -> None:
        """블록을 현재 자리에 놓는다. 인라인 문맥이면 end_block에서 인라인으로 펼친다."""
        if self.inl_out is None:
            self.close_para()
            self.out.append(node)

    def end_block(self, node: dict) -> None:
        if self.inl_out is not None:
            self.inl_out.extend(flatten(node))

    @contextmanager
    def container(self, lst: list):
        saved = (self.out, self.para, self.inl_out, self.brace_depth)
        self.out, self.para, self.inl_out, self.brace_depth = lst, None, None, 0
        try:
            yield
        finally:
            self.close_para()
            self.flush_braces()
            self.out, self.para, self.inl_out, self.brace_depth = saved

    @contextmanager
    def keep_target(self):
        saved = self.target
        try:
            yield
        finally:
            self.target = saved

    def flush_braces(self) -> None:
        if self.brace_depth > 0:
            self.sink.add("unbalanced-brace", "닫히지 않은 { 를 단락 끝에서 닫았다", self.cur.span)
        self.brace_depth = 0

    # ------------------------------------------------------------ 하위 해석
    def blocks_seq(self, tokens: list[Token]) -> list[dict]:
        if self.too_deep():
            return [{"kind": "paragraph", "id": self.new_id(),
                     "content": normalize_inlines([{"kind": "text", "text": detok(tokens)}])}]
        out: list[dict] = []
        with self.stream(tokens), self.container(out):
            self.run_plain()
        return out

    def inline_seq(self, tokens: list[Token], trim: bool = True) -> list[dict]:
        if self.too_deep():
            return normalize_inlines([{"kind": "text", "text": detok(tokens)}], trim=trim)
        saved = (self.out, self.para, self.inl_out, self.brace_depth)
        self.out, self.para, self.inl_out, self.brace_depth = [], None, [], 0
        try:
            with self.stream(tokens):
                self.run_plain()
                self.flush_braces()
            return normalize_inlines(self.inl_out, trim=trim)
        finally:
            self.out, self.para, self.inl_out, self.brace_depth = saved

    def run_plain(self) -> None:
        while self.cur.type is not T.EOF:
            self.step()

    # ------------------------------------------------------------ 최상위
    def run_top(self) -> None:
        body = self.out
        stack: list[dict] = []
        while True:
            t = self.cur
            if t.type is T.EOF:
                break
            if t.type is T.CS:
                if t.text == "end":
                    name, j = env_name_at(self.toks, self.pos)
                    if name == "document":
                        break
                if t.text in SECTION_LEVELS:
                    self.close_para()
                    self.flush_braces()
                    level = SECTION_LEVELS[t.text]
                    while stack and stack[-1]["level"] >= level:
                        stack.pop()
                    self.out = stack[-1]["children"] if stack else body
                    node = self.section(t)
                    stack.append(node)
                    self.out = node["children"]
                    continue
            self.step()
        self.close_para()
        self.flush_braces()

    def section(self, tok: Token) -> dict:
        level = SECTION_LEVELS[tok.text]
        self.adv()
        star = self.take_star()
        node: dict = {"kind": "section", "id": self.new_id(), "level": level,
                      "span": span_json(tok), "title": [], "children": []}
        number: Optional[str] = None
        if not star and level <= 3:
            if level == 1 and self.appendix:
                node["appendix"] = True
            self.sec[level - 1] += 1
            for k in range(level, 3):
                self.sec[k] = 0
            number = self.section_number_str(level)
            node["number"] = number
            self.reset_dependents(("section", "subsection", "subsubsection")[level - 1])
        elif level == 1 and self.appendix:
            node["appendix"] = True
        self.out.append(node)
        self.target = Target(node, node["id"], "section", number)
        self.read_opt()
        node["title"] = self.inline_seq(self.read_group())
        return node

    # ------------------------------------------------------------ 토큰 하나 처리
    def step(self) -> None:
        t = self.cur
        ty = t.type
        if ty is T.SPACE:
            self.adv()
            self.add_text(" ")
        elif ty is T.CHAR:
            self.text_char()
        elif ty is T.PAR:
            self.adv()
            if self.inl_out is not None:
                self.add_text(" ")
            else:
                self.close_para()
            self.flush_braces()
        elif ty is T.TILDE:
            self.adv()
            self.add_text(" ")
        elif ty is T.MATH:
            self.dollar_math(t)
        elif ty is T.BGROUP:
            self.adv()
            self.brace_depth += 1
        elif ty is T.EGROUP:
            self.adv()
            if self.brace_depth > 0:
                self.brace_depth -= 1
            else:
                self.sink.add("unbalanced-brace", "짝이 없는 } 를 무시했다", t.span)
        elif ty is T.VERB:
            self.adv()
            self.emit({"kind": "code", "text": t.text})
        elif ty is T.VERBATIM:
            self.adv()
            if self.inl_out is not None:
                self.emit({"kind": "code", "text": t.text})
            else:
                node = {"kind": "verbatim", "id": self.new_id(), "span": span_json(t), "text": t.text}
                self.begin_block(node)
        elif ty is T.CS:
            self.command(t)
        elif ty is T.PARAM:
            self.adv()
            self.add_text("#" + t.text)
        elif ty is T.EOF:
            pass
        else:  # SUP, SUB, ALIGN: 본문에서는 글자 그대로
            self.adv()
            self.add_text(t.text)

    def command(self, tok: Token) -> None:
        from . import commands as C
        from .build_meta import DEFINITION_COMMANDS, META_COMMANDS
        from .macros import COMPAT_IGNORED, EXCLUDED
        name = tok.text
        if name == "begin":
            self.begin_env(tok)
        elif name == "end":
            env, j = env_name_at(self.toks, self.pos)
            self.pos = j if env else self.pos + 1
            if env != "document":
                self.sink.add("unclosed-environment", f"짝이 없는 \\end{{{env}}}를 무시했다", tok.span)
        elif name in SECTION_LEVELS:          # 최상위가 아닌 곳의 절: 중첩 없이 그 자리에
            self.close_para()
            saved = self.out
            node = self.section(tok)
            self.out = saved
            if self.inl_out is not None:
                self.out.remove(node)
                self.inl_out.extend(flatten(node))
        elif name in DEFINITION_COMMANDS:
            self.skip_definition()
        elif name in META_COMMANDS:
            self.meta_command()
        elif name in EXCLUDED or name in COMPAT_IGNORED:
            # B가 소비해야 할 명령. 진단은 B의 몫이므로 여기서는 인수만 조용히 버린다.
            self.adv()
            while self.cur.type is T.BGROUP:
                self.read_group(report=False)
        elif name == "[":
            self.adv()
            body, closed = self.collect_until_cs("]")
            raw = "\\[" + detok(body) + ("\\]" if closed else "")
            if not closed:
                self.sink.add("math-syntax", "\\[ 가 닫히지 않았다", tok.span)
                self.error_block("math-syntax", raw, tok)
            else:
                self.display_math("displaymath", body, tok, raw)
        elif name == "]" or name == ")":
            self.adv()
            self.add_text(name)
        elif name == "appendix":
            self.adv()
            if not self.appendix:
                self.appendix = True
                self.sec = [0, 0, 0]
        elif name == "par":
            self.adv()
            if self.inl_out is None:
                self.close_para()
        elif name == "includegraphics":
            self.includegraphics(tok)
        elif name == "transclude":
            self.adv()
            href = norm_ws(raw_text(self.read_group()))
            if check_url(href, tok.span, self.sink):
                node = {"kind": "transclusion", "id": self.new_id(), "span": span_json(tok), "href": href}
            else:
                node = {"kind": "error", "id": self.new_id(), "span": span_json(tok),
                        "code": "insecure-resource", "raw": f"\\transclude{{{href}}}"}
            self.begin_block(node)
            self.end_block(node)
        elif name == "bibliography":
            self.bibliography_command(tok)
        elif name == "caption":
            self.adv()
            self.read_opt()
            inl = self.inline_seq(self.read_group())
            if self.float_stack:
                self.float_stack[-1]["caption"] = inl
            else:
                for n in inl:
                    self.emit(n)
        elif name in ("item", "step", "bibitem"):   # 해당 환경 밖: 명령만 버린다
            self.adv()
            self.read_opt()
            if name == "bibitem":
                self.read_group()
        elif self.inline_command(tok):
            pass
        elif name in C.MATH and name not in C.TEXT:
            self.math_command_in_text(tok)
        elif C.is_builtin(name):
            self.adv()
        else:
            self.undefined_command(tok)

    # ------------------------------------------------------------ 수식
    def collect_until_cs(self, name: str) -> tuple[list[Token], bool]:
        start = self.pos
        i = start
        while True:
            t = self.at(i)
            if t.type is T.EOF or (t.type is T.CS and (t.text in BREAKING_SECTIONS)) \
                    or self.is_end_document_at(i):
                self.pos = i
                return self.toks[start:i], False
            if t.type is T.CS and t.text == name:
                self.pos = i + 1
                return self.toks[start:i], True
            i += 1

    def dollar_math(self, tok: Token) -> None:
        self.adv()
        if self.cur.type is T.MATH:  # $$ … $$
            self.adv()
            start = self.pos
            i = start
            while True:
                t = self.at(i)
                if t.type in (T.EOF, T.PAR):
                    self.pos = i
                    body = self.toks[start:i]
                    self.sink.add("math-syntax", "$$ 수식이 닫히지 않았다", tok.span)
                    self.error_block("math-syntax", "$$" + detok(body), tok)
                    return
                if t.type is T.MATH:
                    body = self.toks[start:i]
                    self.pos = i + 1
                    if self.cur.type is T.MATH:
                        self.adv()
                    self.display_math("displaymath", body, tok, "$$" + detok(body) + "$$")
                    return
                i += 1
        body, closed = self.collect_until(lambda t: t.type is T.MATH)
        body, labels, _, _ = self._inline_labels(body)
        for lb in labels:
            self.register_label(lb, self.target, tok)
        self.inline_math(body, tok, "$", "$", closed)

    def _inline_labels(self, body):
        if any(t.type is T.CS and t.text == "label" for t in body):
            return extract_markers(body)
        return body, [], False, None

    def display_math(self, env: str, body: list[Token], tok: Token, raw: str) -> None:
        err = check_math(body)
        if err:
            self.sink.add("math-syntax", f"수식 구문 오류: {err}", tok.span)
            self.error_block("math-syntax", raw, tok)
            return
        self.report_undefined_math(body)
        base = env.rstrip("*")
        starred = env.endswith("*") or env == "displaymath"
        if base in ("align", "gather"):
            rows = split_rows(body)
            rows = [rows[0]] + [strip_row_prefix(r) for r in rows[1:]]
            while len(rows) > 1 and not any(
                    t.type not in (T.SPACE, T.PAR) and not (t.type is T.CS and t.text in ("hline",))
                    for t in rows[-1]):
                rows.pop()
        else:
            rows = [body]
        node = {"kind": "displaymath", "id": self.new_id(), "span": span_json(tok), "env": env, "rows": []}
        self.begin_block(node)
        for r in rows:
            toks, labels, nonumber, tag = extract_markers(r)
            row: dict = {"id": self.new_id(), "math": self.math_source(toks, tok)}
            if tag is not None:
                row["number"] = tag
            elif not starred and not nonumber:
                row["number"] = self.next_number("equation")
            for lb in labels:
                self.register_label(lb, Target(row, row["id"], "equation", row.get("number")), tok)
            node["rows"].append(row)
        self.end_block(node)

    def error_block(self, code: str, raw: str, tok: Token) -> None:
        if self.inl_out is not None:
            self.emit({"kind": "error", "code": code, "raw": raw})
            return
        node = {"kind": "error", "id": self.new_id(), "span": span_json(tok), "code": code, "raw": raw}
        self.begin_block(node)

    # ------------------------------------------------------------ 환경
    def collect_env(self, env: str) -> tuple[list[Token], bool]:
        """\\begin{env} 뒤에서 짝 \\end{env} 까지의 토큰 (원문 수집용)."""
        start = self.pos
        depth = 1
        i = start
        toks = self.toks
        while True:
            t = toks[i]
            if t.type is T.EOF:
                break
            if t.type is T.CS:
                if t.text in ("begin", "end"):
                    name, j = env_name_at(toks, i)
                    if name == env:
                        if t.text == "begin":
                            depth += 1
                        else:
                            depth -= 1
                            if depth == 0:
                                self.pos = j
                                return toks[start:i], True
                        i = j
                        continue
                    if name == "document" and t.text == "end":
                        break
                elif t.text in BREAKING_SECTIONS and env not in ("verbatim",):
                    break
            i += 1
        self.pos = i
        return toks[start:i], False

    def body_until(self, env: str, stop_cs: frozenset = frozenset()) -> str:
        """현재 컨테이너에 블록을 쌓으며 \\end{env} 까지. 'closed' | 'unclosed' | 'stop'"""
        self.env_stack.append(env)
        self.depth += 1
        try:
            while True:
                t = self.cur
                if t.type is T.EOF:
                    return "unclosed"
                if t.type is T.CS:
                    if t.text == "end":
                        name, j = env_name_at(self.toks, self.pos)
                        if name == env:
                            self.pos = j
                            return "closed"
                        if name == "document" or name in self.env_stack[:-1]:
                            return "unclosed"
                    elif t.text in BREAKING_SECTIONS:
                        return "unclosed"
                    elif t.text in stop_cs:
                        return "stop"
                self.step()
        finally:
            self.depth -= 1
            self.env_stack.pop()

    def unclosed(self, env: str, tok: Token) -> None:
        self.sink.add("unclosed-environment", f"환경 {env}이 닫히지 않아 여기서 닫았다", tok.span)

    def env_body(self, env: str, tok: Token, lst: list) -> None:
        with self.container(lst):
            if self.body_until(env) == "unclosed":
                self.unclosed(env, tok)

    def begin_env(self, tok: Token) -> None:
        env, j = env_name_at(self.toks, self.pos)
        if env is None:
            self.adv()
            self.sink.add("undefined-command", "\\begin 뒤에 환경 이름이 없다", tok.span)
            return
        self.pos = j
        if env == "document":
            return
        if self.depth >= MAX_DEPTH or len(self.env_stack) >= MAX_DEPTH:
            self.depth += 1
            try:
                if self.too_deep():
                    body, _ = self.collect_env(env)
                    self.add_text(detok(body))
                    return
            finally:
                self.depth -= 1
        if env in MATH_ENVS:
            body, closed = self.collect_env(env)
            if not closed:
                self.unclosed(env, tok)
            raw = f"\\begin{{{env}}}" + detok(body) + (f"\\end{{{env}}}" if closed else "")
            self.display_math(env, body, tok, raw)
        elif env in MATH_INNER_ENVS:
            body, closed = self.collect_env(env)
            if not closed:
                self.unclosed(env, tok)
            raw = f"\\begin{{{env}}}" + detok(body) + f"\\end{{{env}}}"
            for n in self.math_nodes(self._env_tokens(env, body, tok), tok, raw):
                self.emit(n)
        elif env in LIST_ENVS:
            self.list_env(env, tok)
        elif env in ("quote", "quotation", "quotation*"):
            node = {"kind": "quote", "id": self.new_id(), "span": span_json(tok), "children": []}
            self.begin_block(node)
            with self.keep_target():
                self.env_body(env, tok, node["children"])
            self.end_block(node)
        elif env in self.theorem_envs:
            self.theorem_env(env, tok)
        elif env == "proof":
            opt = self.read_opt()
            node: dict = {"kind": "proof", "id": self.new_id(), "span": span_json(tok),
                          "collapsed": False, "children": []}
            if opt is not None:
                if norm_ws(raw_text(opt)) == "collapsed":
                    node["collapsed"] = True
                else:
                    node["title"] = self.inline_seq(opt)
            self.begin_block(node)
            with self.keep_target():
                self.env_body(env, tok, node["children"])
            self.end_block(node)
        elif env == "collapse":
            node = {"kind": "collapse", "id": self.new_id(), "span": span_json(tok),
                    "title": [], "children": []}
            self.begin_block(node)
            node["title"] = self.inline_seq(self.read_group())
            with self.keep_target():
                self.env_body(env, tok, node["children"])
            self.end_block(node)
        elif env == "steps":
            self.steps_env(tok)
        elif env in ("figure", "figure*", "table", "table*"):
            self.float_env(env, tok)
        elif env in ("tabular", "tabular*"):
            self.tabular_env(env, tok)
        elif env == "thebibliography":
            self.read_group()
            body, closed = self.collect_env(env)
            if not closed:
                self.unclosed(env, tok)
            node = {"kind": "bibliography", "id": self.new_id(), "span": span_json(tok)}
            self.begin_block(node)
            self.parse_bibitems(body)
            self.end_block(node)
        elif env == "abstract":
            self.env_body(env, tok, self.meta.setdefault("abstract", []))
        elif env == "tikzpicture":
            self.picture(env, tok)
        elif env == "verbatim":   # lexer가 VERBATIM으로 바꾸지 못한 경우 (확장 결과 등)
            body, closed = self.collect_env(env)
            node = {"kind": "verbatim", "id": self.new_id(), "span": span_json(tok), "text": detok(body)}
            self.begin_block(node)
            self.end_block(node)
        else:
            from . import commands as C
            if env not in LAYOUT_ENVS and env not in PICTURE_ENVS and env not in C.ENVIRONMENTS:
                self.sink.add("undefined-command", f"정의되지 않은 환경: {env}", tok.span)
            if env == "minipage":
                self.read_opt()
                self.read_group()
            # 알 수 없는 환경은 투명하게: 내용만 그 자리에
            with self.keep_target():
                if self.body_until(env) == "unclosed":
                    self.unclosed(env, tok)

    def _env_tokens(self, env: str, body: list[Token], tok: Token) -> list[Token]:
        """\\begin{env}…\\end{env} 토큰을 다시 만든다 (본문의 cases 등을 인라인 수식으로)."""
        sp = tok.span
        def mk(ty, text):
            return Token(ty, text, sp)
        head = [mk(T.CS, "begin"), mk(T.BGROUP, "{")] + [mk(T.CHAR, c) for c in env] + [mk(T.EGROUP, "}")]
        tail = [mk(T.CS, "end"), mk(T.BGROUP, "{")] + [mk(T.CHAR, c) for c in env] + [mk(T.EGROUP, "}")]
        return head + list(body) + tail

    # ------------------------------------------------------------ 목록·단계
    def list_env(self, env: str, tok: Token) -> None:
        node = {"kind": "list", "id": self.new_id(), "span": span_json(tok), "style": env, "items": []}
        self.begin_block(node)
        count = 0
        with self.keep_target():
            pre: list = []
            with self.container(pre):
                status = self.body_until(env, frozenset({"item"}))
            if pre:
                node["items"].append({"id": self.new_id(), "children": pre})
            while status == "stop":
                self.adv()                       # \item
                opt = self.read_opt()
                item: dict = {"id": self.new_id(), "children": []}
                number = None
                if env == "enumerate" and opt is None:
                    count += 1
                    number = str(count)
                    item["number"] = number
                if opt is not None:
                    term = self.inline_seq(opt)
                    item["term"] = term
                node["items"].append(item)
                self.target = Target(item, item["id"], "item", number)
                with self.container(item["children"]):
                    status = self.body_until(env, frozenset({"item"}))
            if status == "unclosed":
                self.unclosed(env, tok)
        self.end_block(node)

    def steps_env(self, tok: Token) -> None:
        node = {"kind": "steps", "id": self.new_id(), "span": span_json(tok), "steps": []}
        self.begin_block(node)
        with self.keep_target():
            pre: list = []
            with self.container(pre):
                status = self.body_until("steps", frozenset({"step"}))
            if pre:
                node["steps"].append({"id": self.new_id(), "children": pre})
            while status == "stop":
                self.adv()
                self.read_opt()
                st: dict = {"id": self.new_id(), "children": []}
                node["steps"].append(st)
                self.target = Target(st, st["id"], "step", str(len(node["steps"])))
                with self.container(st["children"]):
                    status = self.body_until("steps", frozenset({"step"}))
            if status == "unclosed":
                self.unclosed("steps", tok)
        if not node["steps"]:
            node["steps"].append({"id": self.new_id(), "children": []})
        self.end_block(node)

    # ------------------------------------------------------------ 정리
    def theorem_env(self, env: str, tok: Token) -> None:
        name, numbered = self.theorem_envs[env]
        opt = self.read_opt()
        node: dict = {"kind": "theorem", "id": self.new_id(), "span": span_json(tok),
                      "env": env, "name": name, "children": []}
        number = self.next_number("theorem") if numbered else None
        if number is not None:
            node["number"] = number
        self.begin_block(node)
        with self.keep_target():
            self.target = Target(node, node["id"], "theorem", number, name)
            if opt is not None:
                note = self.inline_seq(opt)
                if note:
                    node["note"] = note
            self.env_body(env, tok, node["children"])
        self.end_block(node)

    # ------------------------------------------------------------ 그림·표
    def float_env(self, env: str, tok: Token) -> None:
        ftype = env.rstrip("*")
        self.read_opt()
        node: dict = {"kind": "float", "id": self.new_id(), "span": span_json(tok),
                      "floatType": ftype, "children": []}
        node["number"] = self.next_number(ftype)
        self.begin_block(node)
        with self.keep_target():
            self.target = Target(node, node["id"], ftype, node["number"])
            self.float_stack.append(node)
            try:
                self.env_body(env, tok, node["children"])
            finally:
                self.float_stack.pop()
        self.end_block(node)

    def includegraphics(self, tok: Token) -> None:
        start = self.pos
        self.adv()
        self.take_star()
        opt = self.read_opt()
        src = norm_ws(raw_text(self.read_group()))
        if not src or not check_url(src, tok.span, self.sink):
            if not src:
                self.sink.add("missing-resource", "\\includegraphics에 주소가 없다", tok.span)
                return
            self.emit({"kind": "error", "code": "insecure-resource",
                       "raw": detok(self.toks[start:self.pos])})
            return
        node: dict = {"kind": "image", "id": self.new_id(), "span": span_json(tok), "src": src}
        if opt is not None:
            for kv in raw_text(opt).split(","):
                if "=" not in kv:
                    continue
                k, v = (x.strip() for x in kv.split("=", 1))
                if k == "width":
                    node["width"] = width_value(v)
                elif k == "alt":
                    node["alt"] = v
        self.begin_block(node)
        self.end_block(node)

    def picture(self, env: str, tok: Token) -> None:
        body, closed = self.collect_env(env)
        if not closed:
            self.unclosed(env, tok)
        source = detok(body, keep_newlines=True).strip()
        node: dict = {"kind": "picture", "id": self.new_id(), "span": span_json(tok), "source": source}
        self.begin_block(node)
        declared = {p["name"] for p in self.parameters}
        try:
            from .picture import check_picture
            info = check_picture(source, set(declared), tok.span, self.sink)
            if getattr(info, "uses_pgfplots", False):
                node["usesPgfplots"] = True
            ps = [p for p in (getattr(info, "params", None) or []) if p in declared]
            if ps:
                node["params"] = list(dict.fromkeys(ps))
        except Exception as e:  # D의 모듈이 예외를 내더라도 트리는 끝까지
            node.pop("usesPgfplots", None)
            del e
        self.end_block(node)

    def tabular_env(self, env: str, tok: Token) -> None:
        if env == "tabular*":
            self.read_group()
        self.read_opt()
        spec = self.read_group()
        body, closed = self.collect_env(env)
        if not closed:
            self.unclosed(env, tok)
        node: dict = {"kind": "tabular", "id": self.new_id(), "span": span_json(tok),
                      "columns": parse_colspec(spec), "rows": []}
        self.begin_block(node)
        raw_rows = split_table(body, "\\")
        rows = node["rows"]
        for idx, r in enumerate(raw_rows):
            if idx > 0:
                r = strip_row_prefix(r)
            k = 0
            rule = False
            while True:
                while k < len(r) and r[k].type in (T.SPACE, T.PAR):
                    k += 1
                if k < len(r) and r[k].type is T.CS and r[k].text == "hline":
                    rule = True
                    k += 1
                    continue
                if k < len(r) and r[k].type is T.CS and r[k].text == "cline":
                    k += 1
                    while k < len(r) and r[k].type is T.SPACE:
                        k += 1
                    if k < len(r) and r[k].type is T.BGROUP:
                        while k < len(r) and r[k].type is not T.EGROUP:
                            k += 1
                        k += 1
                    continue
                break
            rest = r[k:]
            empty = all(t.type in (T.SPACE, T.PAR) for t in rest)
            if empty and idx == len(raw_rows) - 1:
                if rule and rows:
                    rows[-1]["ruleBelow"] = True
                continue
            row: dict = {"cells": []}
            if rule:
                row["ruleAbove"] = True
            for cell in split_table(rest, "&"):
                row["cells"].append(self.table_cell(cell))
            rows.append(row)
        self.end_block(node)

    def table_cell(self, cell: list[Token]) -> dict:
        k = 0
        while k < len(cell) and cell[k].type in (T.SPACE, T.PAR):
            k += 1
        if k < len(cell) and cell[k].type is T.CS and cell[k].text == "multicolumn":
            with self.stream(cell[k + 1:]):
                n = raw_text(self.read_group()).strip()
                spec = parse_colspec(self.read_group())
                content = self.read_group()
                rest = self.toks[self.pos:]
            out: dict = {"content": self.inline_seq(content + rest)}
            try:
                c = int(n)
                if c >= 1:
                    out["colspan"] = c
            except ValueError:
                pass
            if spec:
                out["align"] = spec[0]["align"]
            return {k2: out[k2] for k2 in ("colspan", "align", "content") if k2 in out}
        return {"content": self.inline_seq(cell)}

    # ------------------------------------------------------------ 참고문헌
    def parse_bibitems(self, body: list[Token]) -> None:
        items: list[list[Token]] = []
        depth = 0
        for t in body:
            if t.type is T.BGROUP:
                depth += 1
            elif t.type is T.EGROUP:
                depth -= 1
            if t.type is T.CS and t.text == "bibitem" and depth == 0:
                items.append([])
                continue
            if items:
                items[-1].append(t)
        known = {b["key"] for b in self.bibliography}
        for it in items:
            with self.stream(it):
                self.read_opt()
                key = norm_ws(raw_text(self.read_group()))
                text_toks = self.toks[self.pos:]
            self.no_labels += 1
            try:
                text = self.inline_seq(text_toks)
            finally:
                self.no_labels -= 1
            if not key or key in known:
                continue
            known.add(key)
            entry: dict = {"key": key, "number": str(len(self.bibliography) + 1), "text": text}
            m = _ID_RE.search(raw_text(text_toks))
            if m:
                scheme = "doi" if m.group(1).lower() == "doi" else "arXiv"
                entry["identifier"] = {"scheme": scheme, "value": m.group(2).rstrip(".")}
            self.bibliography.append(entry)

    def bibliography_command(self, tok: Token) -> None:
        self.adv()
        names = [x.strip() for x in raw_text(self.read_group()).split(",") if x.strip()]
        node = {"kind": "bibliography", "id": self.new_id(), "span": span_json(tok)}
        self.begin_block(node)
        from .lexer import tokenize
        for nm in names:
            base = nm[:-4] if nm.endswith(".bbl") else nm
            text = self.ctx.loader.read_text(base, tok.span, self.sink, extensions=(".bbl",))
            if text is None:
                continue
            toks = tokenize(text, self.sink)
            for i, t in enumerate(toks):
                if t.type is T.CS and t.text == "begin":
                    env, j = env_name_at(toks, i)
                    if env == "thebibliography":
                        with self.stream(toks[j:]):
                            self.read_group()
                            body, _ = self.collect_env("thebibliography")
                        self.parse_bibitems(body)
                        break
        self.end_block(node)


# ---------------------------------------------------------------- 순수 도우미
def width_value(v: str) -> str:
    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*\\(textwidth|linewidth|columnwidth)\s*$", v)
    if m:
        try:
            pct = (Decimal(m.group(1)) * 100).normalize()
            s = format(pct, "f")
            if "." in s:
                s = s.rstrip("0").rstrip(".")
            return s + "%"
        except InvalidOperation:
            pass
    m = re.match(r"^\s*\\(textwidth|linewidth|columnwidth)\s*$", v)
    if m:
        return "100%"
    return v.strip()


def parse_colspec(spec: list[Token]) -> list[dict]:
    cols: list[dict] = []
    pending_left = False
    toks = [t for t in spec if t.type not in (T.SPACE, T.PAR)]
    i = 0
    guard = 0
    while i < len(toks) and guard < 10_000:
        guard += 1
        t = toks[i]
        c = t.text if t.type is T.CHAR else None
        if c == "|":
            if cols and not pending_left and _after_col(toks, i):
                cols[-1]["ruleRight"] = True
            else:
                pending_left = True
            i += 1
            continue
        if c in ("l", "c", "r", "p", "m", "b", "X"):
            col: dict = {"align": c if c in ("l", "c", "r") else "l"}
            if pending_left:
                col["ruleLeft"] = True
                pending_left = False
            cols.append(col)
            i += 1
            if c in ("p", "m", "b") and i < len(toks) and toks[i].type is T.BGROUP:
                i = _skip_group(toks, i)
            continue
        if c in ("@", "!", ">", "<"):
            i += 1
            if i < len(toks) and toks[i].type is T.BGROUP:
                i = _skip_group(toks, i)
            continue
        if c == "*":
            star_at = i
            i += 1
            if i < len(toks) and toks[i].type is T.BGROUP:
                e = _skip_group(toks, i)
                try:
                    n = int(raw_text(toks[i + 1:e - 1]).strip())
                except ValueError:
                    n = 1
                if e < len(toks) and toks[e].type is T.BGROUP:
                    e2 = _skip_group(toks, e)
                    inner = toks[e + 1:e2 - 1]
                    toks = toks[:star_at] + inner * max(0, min(n, 100)) + toks[e2:]
                    i = star_at
                else:
                    i = e
            continue
        i += 1
    return cols


def _after_col(toks: list[Token], i: int) -> bool:
    """i 위치의 '|' 뒤에 열 지정이 더 없으면 True (오른쪽 세로선)."""
    for t in toks[i + 1:]:
        if t.type is T.CHAR and t.text in ("l", "c", "r", "p", "m", "b", "X"):
            return False
    return True


def _skip_group(toks: list[Token], i: int) -> int:
    depth = 0
    for k in range(i, len(toks)):
        if toks[k].type is T.BGROUP:
            depth += 1
        elif toks[k].type is T.EGROUP:
            depth -= 1
            if depth == 0:
                return k + 1
    return len(toks)


def split_table(tokens: list[Token], sep: str) -> list[list[Token]]:
    """표 본문을 최상위의 \\\\ (sep='\\\\') 또는 & (sep='&')로 나눈다.
    중괄호, 내부 환경, 수식($…$) 안의 구분자는 나누지 않는다."""
    parts: list[list[Token]] = [[]]
    depth = 0
    in_math = False
    for t in tokens:
        ty = t.type
        if ty is T.BGROUP:
            depth += 1
        elif ty is T.EGROUP:
            depth = max(0, depth - 1)
        elif ty is T.MATH:
            in_math = not in_math
        elif ty is T.CS and t.text == "begin":
            depth += 1
        elif ty is T.CS and t.text == "end":
            depth = max(0, depth - 1)
        if depth == 0 and not in_math:
            if sep == "\\" and ty is T.CS and t.text in ("\\", "tabularnewline"):
                parts.append([])
                continue
            if sep == "&" and ty is T.ALIGN:
                parts.append([])
                continue
        parts[-1].append(t)
    return parts


def flatten(node: dict) -> list[dict]:
    """블록을 인라인으로 펼친다 (인라인만 허용되는 자리에 블록 환경이 왔을 때)."""
    k = node.get("kind")
    if k == "paragraph":
        return list(node.get("content", [])) + [{"kind": "text", "text": " "}]
    if k == "displaymath":
        return [{"kind": "math", "math": r["math"]} for r in node.get("rows", [])]
    if k == "verbatim":
        return [{"kind": "code", "text": node.get("text", "")}]
    if k == "error":
        return [{"kind": "error", "code": node["code"], "raw": node["raw"]}]
    out: list[dict] = []
    if k == "section":
        out.extend(node.get("title", []))
        out.append({"kind": "text", "text": " "})
    for key in ("children",):
        for c in node.get(key, []):
            out.extend(flatten(c))
    for it in node.get("items", []) + node.get("steps", []):
        out.extend(it.get("term", []))
        for c in it.get("children", []):
            out.extend(flatten(c))
    for r in node.get("rows", []) if k == "tabular" else []:
        for c in r.get("cells", []):
            out.extend(c.get("content", []))
            out.append({"kind": "text", "text": " "})
    return out
