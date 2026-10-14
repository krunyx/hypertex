"""토큰. lexer → macros → builder 사이의 공통 언어.

TeX의 catcode를 고정된 표로 단순화했다 (\\catcode는 명세상 금지).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .diagnostics import Span


class T(Enum):
    CS = "cs"              # 제어 시퀀스. text = 이름 (역슬래시 제외). 예: "section", "\\" 는 "\\"
    CHAR = "char"          # 일반 문자 하나 (한글, 숫자, 문장부호 포함)
    SPACE = "space"        # 공백·줄바꿈 하나 이상 (하나로 합침)
    PAR = "par"            # 빈 줄 (단락 구분)
    BGROUP = "{"
    EGROUP = "}"
    MATH = "$"             # $ 하나. $$는 lexer가 두 개로 낸다
    ALIGN = "&"
    PARAM = "#"            # text = 매개변수 번호 문자열 ("1"…"9"), 번호가 없으면 ""
    SUP = "^"
    SUB = "_"
    TILDE = "~"
    VERB = "verb"          # \verb|…| 의 내용. text = 원문
    VERBATIM = "verbatim"  # verbatim 환경 본문. text = 원문 (앞뒤 줄바꿈 하나씩 제거)
    EOF = "eof"


@dataclass(frozen=True)
class Token:
    type: T
    text: str
    span: Span

    def is_cs(self, name: str) -> bool:
        return self.type is T.CS and self.text == name

    def __repr__(self) -> str:  # 디버깅 편의
        if self.type is T.CS:
            return f"\\{self.text}@{self.span.line}:{self.span.col}"
        return f"{self.type.value}:{self.text!r}@{self.span.line}:{self.span.col}"


def detokenize(tokens: list[Token]) -> str:
    """토큰을 다시 TeX 문자열로. 수식의 math.tex, 그림의 source를 만들 때 쓴다."""
    out: list[str] = []
    for i, t in enumerate(tokens):
        if t.type is T.CS:
            out.append("\\" + t.text)
            # 제어어 뒤에 글자가 오면 붙어버리므로 공백을 넣는다
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if (t.text.isascii() and t.text.isalpha() and nxt is not None
                    and nxt.type is T.CHAR and nxt.text.isascii() and nxt.text.isalpha()):
                out.append(" ")
        elif t.type is T.PARAM:
            out.append("#" + t.text)
        elif t.type in (T.SPACE, T.PAR):
            out.append(" ")
        elif t.type is T.VERB:
            out.append("\\verb|" + t.text + "|")
        elif t.type is T.VERBATIM:
            out.append("\\begin{verbatim}\n" + t.text + "\n\\end{verbatim}")
        elif t.type is T.EOF:
            pass
        else:
            out.append(t.text)
    return "".join(out).strip()
