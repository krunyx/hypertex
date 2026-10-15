"""문자열 → 토큰 목록. (담당: B. 0단계에서 동작하는 기본판을 제공)

규칙
- 제어어: \\ 뒤 ASCII 글자 연속 (\\section). 뒤따르는 공백은 먹는다.
- 제어기호: \\ 뒤 글자 아닌 문자 하나 (\\\\, \\{, \\%, \\,).
- %부터 줄 끝까지 주석. 주석 뒤 줄바꿈과 다음 줄 앞 공백도 먹는다. 그다음 줄이 빈 줄이면 PAR.
- 빈 줄(공백만 있는 줄 포함) → PAR. 그 외 공백·줄바꿈 연속 → SPACE 하나.
- \\verb<d>…<d> → VERB, \\begin{verbatim}…\\end{verbatim} → CS(begin) … 대신 VERBATIM 하나.
"""
from __future__ import annotations

from .diagnostics import Sink, Span
from .tokens import T, Token

_SINGLE = {"{": T.BGROUP, "}": T.EGROUP, "$": T.MATH, "&": T.ALIGN,
           "^": T.SUP, "_": T.SUB, "~": T.TILDE}

_VERB_BEGIN = "\\begin{verbatim}"
_VERB_END = "\\end{verbatim}"


def tokenize(src: str, sink: Sink | None = None) -> list[Token]:
    sink = sink or Sink()
    src = src.replace("\r\n", "\n").replace("\r", "\n")
    out: list[Token] = []
    i, n = 0, len(src)
    line, col = 1, 1
    at_letter = False  # \makeatletter 구간

    def adv(k: int):
        nonlocal i, line, col
        for _ in range(k):
            if src[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        c = src[i]
        start = Span(line, col)

        # verbatim 환경
        if src.startswith(_VERB_BEGIN, i):
            j = src.find(_VERB_END, i + len(_VERB_BEGIN))
            if j < 0:
                sink.add("unclosed-environment", "verbatim 환경이 닫히지 않았다", start)
                j = n
            body = src[i + len(_VERB_BEGIN):j]
            if body.startswith("\n"):
                body = body[1:]
            if body.endswith("\n"):
                body = body[:-1]
            adv(min(j + len(_VERB_END), n) - i)
            out.append(Token(T.VERBATIM, body, start))
            continue

        if c == "\\":
            if i + 1 >= n:
                adv(1)
                out.append(Token(T.CHAR, "\\", start))
                continue
            d = src[i + 1]
            if (d.isascii() and d.isalpha()) or (d == "@" and at_letter):
                j = i + 1
                while j < n and ((src[j].isascii() and src[j].isalpha())
                                 or (src[j] == "@" and at_letter)):
                    j += 1
                name = src[i + 1:j]
                adv(j - i)
                # \makeatletter … \makeatother: 그 사이에서는 @ 도 제어어 글자 (LaTeX 호환)
                if name == "makeatletter":
                    at_letter = True
                elif name == "makeatother":
                    at_letter = False
                # \verb
                if name == "verb" and i < n:
                    delim = src[i]
                    k = src.find(delim, i + 1)
                    if k < 0 or "\n" in src[i + 1:k]:
                        sink.add("unbalanced-brace", "\\verb의 구분자가 닫히지 않았다", start)
                        out.append(Token(T.CS, name, start))
                        continue
                    out.append(Token(T.VERB, src[i + 1:k], start))
                    adv(k + 1 - i)
                    continue
                out.append(Token(T.CS, name, start))
                # 제어어 뒤 공백 (줄바꿈 하나까지) 먹기. 빈 줄은 남긴다.
                _skip_space_after_cs(src, n, lambda: i, adv)
            else:
                adv(2)
                out.append(Token(T.CS, d, start))
            continue

        if c == "%":
            while i < n and src[i] != "\n":
                adv(1)
            if i < n:
                adv(1)  # 줄바꿈
                while i < n and src[i] in " \t":
                    adv(1)
                # 주석 줄 다음 줄이 빈 줄이면 TeX처럼 단락 구분 (a%\n\nb → a PAR b)
                if i < n and src[i] == "\n":
                    pstart = Span(line, col)
                    while i < n and src[i] in " \t\n":
                        adv(1)
                    out.append(Token(T.PAR, " ", pstart))
            continue

        if c in " \t\n":
            newlines = 0
            while i < n and src[i] in " \t\n":
                if src[i] == "\n":
                    newlines += 1
                adv(1)
            out.append(Token(T.PAR if newlines >= 2 else T.SPACE, " ", start))
            continue

        if c == "#":
            adv(1)
            if i < n and src[i].isdigit():
                num = src[i]
                adv(1)
                out.append(Token(T.PARAM, num, start))
            else:
                out.append(Token(T.PARAM, "", start))
            continue

        if c in _SINGLE:
            adv(1)
            out.append(Token(_SINGLE[c], c, start))
            continue

        adv(1)
        out.append(Token(T.CHAR, c, start))

    out.append(Token(T.EOF, "", Span(line, col)))
    return out


def _skip_space_after_cs(src, n, pos, adv):
    i = pos()
    # 공백·탭, 그리고 줄바꿈 하나까지만
    while i < n and src[i] in " \t":
        adv(1)
        i = pos()
    if i < n and src[i] == "\n":
        # 다음 줄이 빈 줄이면 PAR를 살리기 위해 먹지 않는다
        j = i + 1
        while j < n and src[j] in " \t":
            j += 1
        if j < n and src[j] == "\n":
            return
        adv(1)
        i = pos()
        while i < n and src[i] in " \t":
            adv(1)
            i = pos()
