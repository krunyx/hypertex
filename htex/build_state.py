"""트리 빌더의 공통 상태: 토큰 커서, 인수 읽기, id, 카운터, 라벨 표. (담당: C)"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Optional

from .build_math import env_name_at, raw_text
from .diagnostics import Span
from .tokens import T, Token

MAX_DEPTH = 16   # 인수·환경 중첩 상한 (파이썬 재귀 한도 안에서 끝나게)

SECTION_LEVELS = {"section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4}

_LABEL_BAD = re.compile(r"[^A-Za-z0-9가-힣:._-]")


def sanitize_label(raw: str) -> str:
    """스키마의 LabelName 패턴에 맞게. 허용되지 않는 글자는 '_' 로 (notes/C-questions.md)."""
    return _LABEL_BAD.sub("_", raw.strip())


def span_json(t: Token) -> dict:
    return {"line": max(1, t.span.line), "col": max(1, t.span.col)}


def alpha_number(n: int) -> str:
    """1 → A, 26 → Z, 27 → AA"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s or "0"


DISPLAY = {
    "section": "{n}절", "equation": "식 ({n})", "figure": "그림 {n}", "table": "표 {n}",
    "item": "항목 {n}", "footnote": "각주 {n}", "step": "단계 {n}",
}


class Target:
    """\\label 이 붙을 대상 (LaTeX의 \\@currentlabel 에 해당)."""
    __slots__ = ("holder", "node_id", "kind", "number", "name")

    def __init__(self, holder: Optional[dict], node_id: str, kind: str,
                 number: Optional[str], name: str = ""):
        self.holder = holder          # label 속성을 가질 dict (footnote는 None)
        self.node_id = node_id
        self.kind = kind
        self.number = number
        self.name = name              # 정리류 표시 이름


class StateMixin:
    toks: list[Token]
    pos: int

    def _init_state(self, tokens: list[Token], ctx) -> None:
        self.ctx = ctx
        self.sink = ctx.sink
        toks = list(tokens)
        if not toks or toks[-1].type is not T.EOF:
            sp = toks[-1].span if toks else Span(1, 1)
            toks.append(Token(T.EOF, "", sp))
        self.toks = toks
        self.pos = 0
        self.skip_close: set[int] = set()
        self.env_stack: list[str] = []
        self.depth = 0
        self.depth_reported = False
        # 번호
        self.sec = [0, 0, 0]
        self.appendix = False
        self.cnt = {"equation": 0, "figure": 0, "table": 0, "theorem": 0, "footnote": 0}
        self.num_templates: dict[str, str] = {}
        # 라벨·참조
        self.labels: dict[str, dict] = {}
        self.target: Optional[Target] = None
        self.no_labels = 0            # >0 이면 \label 을 등록하지 않는다 (참고문헌 본문)
        self.pending_refs: list[tuple[dict, str, Token]] = []
        self.pending_cites: list[tuple[dict, list[str], Token]] = []
        self.float_stack: list[dict] = []

    # ------------------------------------------------------------ 커서
    @property
    def cur(self) -> Token:
        return self.toks[self.pos]

    def at(self, i: int) -> Token:
        return self.toks[i] if i < len(self.toks) else self.toks[-1]

    def adv(self, k: int = 1) -> None:
        self.pos = min(self.pos + k, len(self.toks) - 1)

    def new_id(self) -> str:
        return self.ctx.new_id()

    @contextmanager
    def stream(self, tokens: list[Token]):
        """토큰 부분 목록을 따로 해석한다 (인수의 내용 등)."""
        saved = (self.toks, self.pos, self.skip_close, self.env_stack)
        toks = [t for t in tokens if t.type is not T.EOF]
        sp = toks[-1].span if toks else self.cur.span
        toks.append(Token(T.EOF, "", sp))
        self.toks, self.pos, self.skip_close, self.env_stack = toks, 0, set(), []
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1
            self.toks, self.pos, self.skip_close, self.env_stack = saved

    def too_deep(self) -> bool:
        """중첩 상한. 넘으면 그 부분은 해석하지 않고 원문 텍스트로 둔다 (한 번만 진단)."""
        if self.depth < MAX_DEPTH:
            return False
        if not self.depth_reported:
            self.depth_reported = True
            self.sink.add("render-timeout", f"중첩이 {MAX_DEPTH}단계를 넘어 안쪽은 원문으로 두었다",
                          self.cur.span)
        return True

    def skip_sp(self, par: bool = False) -> None:
        while self.cur.type is T.SPACE or (par and self.cur.type is T.PAR):
            self.adv()

    def is_section_at(self, i: int) -> bool:
        t = self.at(i)
        return t.type is T.CS and t.text in SECTION_LEVELS

    def is_end_document_at(self, i: int) -> bool:
        t = self.at(i)
        if t.type is T.CS and t.text == "end":
            name, _ = env_name_at(self.toks, i)
            return name == "document"
        return False

    def peek_char(self, ch: str) -> bool:
        """공백 뒤 다음 토큰이 글자 ch 인지 (커서는 그대로)."""
        i = self.pos
        while self.at(i).type is T.SPACE:
            i += 1
        t = self.at(i)
        return t.type is T.CHAR and t.text == ch

    def take_star(self) -> bool:
        if self.cur.type is T.CHAR and self.cur.text == "*":
            self.adv()
            return True
        return False

    # ------------------------------------------------------------ 인수 읽기
    def read_group(self, allow_par: bool = False, report: bool = True) -> list[Token]:
        """{…} 인수 하나 (중괄호 제외). 중괄호가 아니면 토큰 하나.
        닫히지 않으면 단락 끝(allow_par면 다음 절·문서 끝)에서 닫고 unbalanced-brace."""
        self.skip_sp()
        t = self.cur
        if t.type is T.BGROUP:
            start = self.pos
            depth = 0
            i = start
            toks = self.toks
            while True:
                u = toks[i]
                ty = u.type
                if ty is T.EOF:
                    break
                if ty is T.PAR and not allow_par:
                    break
                if allow_par and depth >= 1 and i > start and (
                        self.is_section_at(i) or self.is_end_document_at(i)):
                    break
                if ty is T.BGROUP:
                    depth += 1
                elif ty is T.EGROUP:
                    depth -= 1
                    if depth == 0:
                        self.pos = i + 1
                        return toks[start + 1:i]
                i += 1
            if report:
                self.sink.add("unbalanced-brace", "닫는 중괄호가 없어 단락 끝에서 닫았다", t.span)
            self.pos = i
            return _drop_unmatched_open(toks[start + 1:i])
        if t.type in (T.EGROUP, T.EOF, T.PAR):
            return []
        self.adv()
        return [t]

    def read_opt(self) -> Optional[list[Token]]:
        """[…] 선택 인수. 없으면 None (커서 그대로)."""
        save = self.pos
        self.skip_sp()
        t = self.cur
        if not (t.type is T.CHAR and t.text == "["):
            self.pos = save
            return None
        open_at = self.pos
        i = open_at + 1
        depth = 0
        toks = self.toks
        while True:
            u = toks[i]
            if u.type in (T.EOF, T.PAR):
                self.pos = save
                return None
            if u.type is T.BGROUP:
                depth += 1
            elif u.type is T.EGROUP:
                depth -= 1
                if depth < 0:
                    self.pos = save
                    return None
            elif u.type is T.CHAR and u.text == "]" and depth == 0:
                self.pos = i + 1
                return toks[open_at + 1:i]
            i += 1

    def read_text_arg(self) -> str:
        return raw_text(self.read_group()).strip()

    # ------------------------------------------------------------ 번호
    def fmt_number(self, counter: str, value: int) -> str:
        tpl = self.num_templates.get(counter)
        if not tpl:
            return str(value)

        def rep(m: re.Match) -> str:
            w = m.group(0)
            if w == counter:
                return str(value)
            if w == "section":
                return self.section_number_str(1) or "0"
            if w == "subsection":
                return str(self.sec[1])
            if w == "subsubsection":
                return str(self.sec[2])
            if w in self.cnt:
                return str(self.cnt[w])
            return w
        return re.sub(r"[A-Za-z]+", rep, tpl)

    def section_number_str(self, level: int) -> str:
        first = alpha_number(self.sec[0]) if self.appendix else str(self.sec[0])
        parts = [first] + [str(x) for x in self.sec[1:level]]
        return ".".join(parts)

    def reset_dependents(self, word: str) -> None:
        for c, tpl in self.num_templates.items():
            if c in self.cnt and re.search(rf"\b{word}\b", tpl):
                self.cnt[c] = 0

    def next_number(self, counter: str) -> str:
        self.cnt[counter] = self.cnt.get(counter, 0) + 1
        return self.fmt_number(counter, self.cnt[counter])

    # ------------------------------------------------------------ 라벨
    def register_label(self, raw: str, target: Optional[Target], tok: Token) -> None:
        if self.no_labels or target is None:
            return
        name = sanitize_label(raw)
        if not name:
            return
        if name in self.labels:
            self.sink.add("duplicate-label", f"라벨 {name}이 이미 있다", tok.span)
            return
        entry: dict[str, Any] = {"node": target.node_id, "kind": target.kind}
        if target.number is not None:
            entry["number"] = target.number
            if target.kind == "theorem":
                entry["display"] = f"{target.name} {target.number}".strip()
            else:
                entry["display"] = DISPLAY[target.kind].format(n=target.number)
        self.labels[name] = entry
        if target.holder is not None and "label" not in target.holder:
            target.holder["label"] = name


def _drop_unmatched_open(toks: list[Token]) -> list[Token]:
    """닫히지 않은 그룹 안의 짝 없는 '{' 를 지운다 (같은 오류를 두 번 보고하지 않게)."""
    stack: list[int] = []
    drop: set[int] = set()
    for i, t in enumerate(toks):
        if t.type is T.BGROUP:
            stack.append(i)
        elif t.type is T.EGROUP:
            if stack:
                stack.pop()
            else:
                drop.add(i)
    drop.update(stack)
    return [t for i, t in enumerate(toks) if i not in drop]
