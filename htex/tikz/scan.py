"""TikZ 원문 훑기 도우미: 짝 맞추기, 최상위 나누기, 키-값 목록, foreach 변수 치환. (담당: H)

모든 함수는 문자열 위치만 다루며 예외 대신 안전한 값을 돌려준다(짝이 안 맞으면 끝까지).
"""
from __future__ import annotations

import re

_PAIRS = {"{": "}", "[": "]", "(": ")"}


def skip_ws(s: str, i: int, end: int | None = None) -> int:
    end = len(s) if end is None else end
    while i < end:
        c = s[i]
        if c.isspace():
            i += 1
        elif c == "%":                      # 주석 (detok 뒤에는 거의 없지만 안전하게)
            j = s.find("\n", i)
            i = end if j < 0 else j + 1
        else:
            break
    return i


def match(s: str, i: int, end: int | None = None) -> int:
    """s[i] 가 여는 괄호({ [ ( )일 때 짝이 되는 닫는 괄호 다음 위치. 짝이 없으면 end.

    중괄호 안은 다른 괄호를 세지 않는다. 대괄호·괄호 안에서는 중괄호와 같은 종류만 센다.
    역슬래시 다음 한 글자는 건너뛴다.
    """
    end = len(s) if end is None else end
    open_ch = s[i]
    close_ch = _PAIRS[open_ch]
    depth = 0
    brace = 0
    j = i
    while j < end:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if open_ch != "{":
            if c == "{":
                brace += 1
            elif c == "}":
                brace -= 1
            elif brace <= 0:
                if c == open_ch:
                    depth += 1
                elif c == close_ch:
                    depth -= 1
                    if depth == 0:
                        return j + 1
        else:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return j + 1
        j += 1
    return end


def group(s: str, i: int, end: int | None = None) -> tuple[str, int]:
    """s[i] 의 괄호 묶음 안쪽 글과 다음 위치."""
    j = match(s, i, end)
    inner_end = j - 1 if j > i and j <= len(s) and s[j - 1] == _PAIRS[s[i]] else j
    return s[i + 1:inner_end], j


def split_top(text: str, sep: str = ",") -> list[str]:
    """중괄호·대괄호·괄호 바깥의 sep 으로 나눈다."""
    out, depth, cur = [], 0, []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            cur.append(text[i:i + 2])
            i += 2
            continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth = max(0, depth - 1)
        if depth == 0 and text.startswith(sep, i):
            out.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def find_top(text: str, needle: str) -> int:
    """최상위(괄호 밖)에서 needle 의 첫 위치, 없으면 -1."""
    depth, i, n = 0, 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(needle, i):
            return i
        i += 1
    return -1


def strip_braces(t: str) -> str:
    t = t.strip()
    while len(t) >= 2 and t[0] == "{" and match(t, 0) == len(t):
        t = t[1:-1].strip()
    return t


def keyvals(text: str) -> list[tuple[str, str | None]]:
    """'a=1, b, c={x,y}' → [('a','1'), ('b',None), ('c','x,y')]. 키는 공백을 하나로."""
    out: list[tuple[str, str | None]] = []
    for part in split_top(text or ""):
        part = part.strip()
        if not part:
            continue
        k = find_top(part, "=")
        if k < 0:
            out.append((" ".join(part.split()), None))
        else:
            key = " ".join(part[:k].split())
            out.append((key, strip_braces(part[k + 1:])))
    return out


def substitute(text: str, var: str, value: str) -> str:
    """매크로 \\var 를 value 로 바꾼다 (\\var 다음에 글자가 오면 다른 이름). TikZ 의 매크로 확장과 같다."""
    if not var:
        return text
    pat = re.compile(re.escape("\\" + var) + r"(?![A-Za-z@])")
    return pat.sub(lambda m: value, text)


def statement_end(s: str, i: int, end: int) -> int:
    """i 부터 최상위 ';' 위치(없으면 end). 중괄호·대괄호·괄호·$…$ 안은 무시."""
    depth = 0
    j = i
    while j < end:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth = max(0, depth - 1)
        elif c == ";" and depth == 0:
            return j
        j += 1
    return end
