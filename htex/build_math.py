"""트리 빌더 도우미: 토큰 → 원문, 수식 검사·행 나누기·문자 체계. (담당: C)

여기의 함수는 모두 순수 함수이고 예외를 던지지 않는다 (잘못된 입력은 결과로 알린다).
"""
from __future__ import annotations

import re
from typing import Optional

from . import commands as C
from .tokens import T, Token, error_token_info

# 수식 안에서만 쓰는 내부 환경. 본문에서 만나면 인라인 수식으로 취급한다.
MATH_INNER_ENVS = frozenset({
    "cases", "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
    "smallmatrix", "aligned", "gathered", "split", "array", "subarray", "alignedat",
})

# 인수를 반드시 받아야 하는 수식 명령 (구문 검사용)
_ARITY = {
    "frac": 2, "dfrac": 2, "tfrac": 2, "cfrac": 2, "binom": 2, "dbinom": 2, "tbinom": 2,
    "overset": 2, "underset": 2, "stackrel": 2,
    "sqrt": 1, "text": 1, "operatorname": 1, "mathbf": 1, "mathrm": 1, "mathit": 1, "mathsf": 1,
    "mathtt": 1, "mathcal": 1, "mathbb": 1, "mathfrak": 1, "mathscr": 1, "boldsymbol": 1,
    "hat": 1, "bar": 1, "vec": 1, "dot": 1, "ddot": 1, "tilde": 1, "widetilde": 1, "widehat": 1,
    "overline": 1, "underline": 1, "overbrace": 1, "underbrace": 1, "label": 1, "tag": 1,
}

_DIM_RE = re.compile(r"^\s*-?[0-9.]+\s*(pt|em|ex|mm|cm|in|bp|pc|mu|sp|dd)\s*$")


def is_word(name: str) -> bool:
    return bool(name) and name.isascii() and name.isalpha()


def _gap(a: Token, b: Token) -> int:
    """제어어 a 뒤에 원문에서 공백이 있었는지 (lexer가 먹은 공백을 위치로 되살린다).
    0 = 없음, 1 = 같은 줄의 공백, 2 = 줄바꿈."""
    if b.span.line == a.span.line:
        return 1 if b.span.col > a.span.col + 1 + len(a.text) else 0
    return 2 if b.span.line > a.span.line else 0


def detok(tokens: list[Token], keep_newlines: bool = False) -> str:
    """tokens.detokenize 와 같되, 제어어 뒤에서 lexer가 먹은 공백을 토큰 위치로 되살린다
    (`\\Psi = x` 가 `\\Psi= x` 가 되지 않게). keep_newlines면 줄바꿈도 살린다 (그림 원문용)."""
    out: list[str] = []
    n = len(tokens)
    for i, t in enumerate(tokens):
        ty = t.type
        info = error_token_info(t)
        if info is not None:  # 확장 상한 등 오류 표지는 원문으로 (렌더러가 수식 오류로 표시)
            out.append(info[1])
        elif ty is T.CS:
            out.append("\\" + t.text)
            if is_word(t.text) and i + 1 < n:
                nxt = tokens[i + 1]
                if nxt.type not in (T.SPACE, T.PAR, T.EOF):
                    if nxt.type is T.CHAR and is_word(nxt.text):
                        out.append(" ")
                    else:
                        g = _gap(t, nxt)
                        if g:
                            out.append("\n" if (g == 2 and keep_newlines) else " ")
        elif ty is T.PARAM:
            out.append("#" + t.text)
        elif ty is T.SPACE or ty is T.PAR:
            if keep_newlines and i + 1 < n and tokens[i + 1].span.line > t.span.line:
                out.append("\n\n" if ty is T.PAR else "\n")
            else:
                out.append(" ")
        elif ty is T.VERB:
            out.append("\\verb|" + t.text + "|")
        elif ty is T.VERBATIM:
            out.append("\\begin{verbatim}\n" + t.text + "\n\\end{verbatim}")
        elif ty is T.EOF:
            pass
        else:
            out.append(t.text)
    return "".join(out)


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


_ESCAPED = {"_": "_", "%": "%", "#": "#", "&": "&", "$": "$", "{": "{", "}": "}", "~": "~",
            " ": " ", ",": ","}


def raw_text(tokens: list[Token]) -> str:
    """주소·라벨·키 같은 '글자 그대로' 인수를 문자열로. \\_ 같은 이스케이프는 글자로 푼다."""
    out = []
    for t in tokens:
        if t.type is T.CS:
            if t.text in _ESCAPED:
                out.append(_ESCAPED[t.text])
            else:
                out.append("\\" + t.text)
        elif t.type is T.PARAM:
            out.append("#" + t.text)
        elif t.type in (T.SPACE, T.PAR):
            out.append(" ")
        elif t.type is T.VERB:
            out.append(t.text)
        elif t.type is T.EOF:
            pass
        else:
            out.append(t.text)
    return "".join(out)


# ---------------------------------------------------------------- 토큰 목록 위의 작은 도구
def skip_sp(tokens: list[Token], j: int) -> int:
    while j < len(tokens) and tokens[j].type in (T.SPACE, T.PAR):
        j += 1
    return j


def group_end(tokens: list[Token], j: int) -> int:
    """tokens[j]가 '{'일 때 짝 '}'의 다음 위치. 짝이 없으면 -1."""
    depth = 0
    for k in range(j, len(tokens)):
        ty = tokens[k].type
        if ty is T.BGROUP:
            depth += 1
        elif ty is T.EGROUP:
            depth -= 1
            if depth == 0:
                return k + 1
    return -1


def read_arg_at(tokens: list[Token], j: int) -> tuple[list[Token], int]:
    """j 위치(공백 건너뜀)의 인수 하나. ({…} 안의 토큰 또는 토큰 하나, 다음 위치)"""
    j = skip_sp(tokens, j)
    if j >= len(tokens):
        return [], j
    if tokens[j].type is T.BGROUP:
        e = group_end(tokens, j)
        if e < 0:
            return tokens[j + 1:], len(tokens)
        return tokens[j + 1:e - 1], e
    if tokens[j].type is T.EGROUP:
        return [], j
    return [tokens[j]], j + 1


def env_name_at(tokens: list[Token], j: int) -> tuple[Optional[str], int]:
    """tokens[j]가 \\begin 또는 \\end일 때 {이름}을 읽는다. (이름 또는 None, 다음 위치)"""
    k = skip_sp(tokens, j + 1)
    if k >= len(tokens) or tokens[k].type is not T.BGROUP:
        return None, j + 1
    k += 1
    name = []
    while k < len(tokens) and tokens[k].type is T.CHAR and len(name) < 64:
        name.append(tokens[k].text)
        k += 1
    if k >= len(tokens) or tokens[k].type is not T.EGROUP or not name:
        return None, j + 1
    return "".join(name), k + 1


# ---------------------------------------------------------------- 수식 구문 검사
def check_math(tokens: list[Token]) -> Optional[str]:
    """수식 구문 오류면 사유 문자열, 괜찮으면 None.
    검사: 중괄호 짝, \\left/\\right 짝, \\begin/\\end 짝, 인수가 필요한 명령의 인수 유무,
    ^ _ 뒤의 대상."""
    stack: list = []
    n = len(tokens)
    i = 0

    def closer(tok: Token) -> bool:
        return (tok.type in (T.EGROUP, T.ALIGN, T.SUP, T.SUB)
                or (tok.type is T.CS and tok.text in ("\\", "right", "end")))

    while i < n:
        t = tokens[i]
        ty = t.type
        if ty is T.BGROUP:
            stack.append("{")
        elif ty is T.EGROUP:
            if not stack or stack[-1] != "{":
                return "짝이 없는 }"
            stack.pop()
        elif ty in (T.SUP, T.SUB):
            j = skip_sp(tokens, i + 1)
            if j >= n or closer(tokens[j]):
                return f"{t.text} 뒤에 대상이 없다"
        elif ty is T.CS:
            name = t.text
            if name in ("left", "right", "middle"):
                if name == "right":
                    if not stack or stack[-1] != "left":
                        return "짝이 없는 \\right"
                    stack.pop()
                elif name == "middle" and "left" not in stack:
                    return "\\left 없는 \\middle"
                j = skip_sp(tokens, i + 1)
                if j >= n or tokens[j].type in (T.BGROUP, T.EGROUP, T.SUP, T.SUB, T.ALIGN):
                    return f"\\{name} 뒤에 구분 기호가 없다"
                if name == "left":
                    stack.append("left")
                i = j + 1
                continue
            if name in ("begin", "end"):
                env, j = env_name_at(tokens, i)
                if env is None:
                    return f"\\{name}의 환경 이름이 없다"
                if name == "begin":
                    stack.append(("env", env))
                else:
                    if not stack or stack[-1] != ("env", env):
                        return f"짝이 없는 \\end{{{env}}}"
                    stack.pop()
                i = j
                continue
            if name in _ARITY:
                j = i + 1
                if name == "sqrt":
                    j2 = skip_sp(tokens, j)
                    if j2 < n and tokens[j2].type is T.CHAR and tokens[j2].text == "[":
                        k = j2 + 1
                        while k < n and not (tokens[k].type is T.CHAR and tokens[k].text == "]"):
                            k += 1
                        if k >= n:
                            return "\\sqrt의 [ 가 닫히지 않았다"
                        j = k + 1
                for _ in range(_ARITY[name]):
                    j = skip_sp(tokens, j)
                    if j >= n or closer(tokens[j]):
                        return f"\\{name}의 인수가 모자란다"
                    if tokens[j].type is T.BGROUP:
                        e = group_end(tokens, j)
                        if e < 0:
                            return f"\\{name}의 인수가 닫히지 않았다"
                        j = e
                    else:
                        j += 1
        i += 1
    if stack:
        top = stack[-1]
        if top == "{":
            return "닫히지 않은 {"
        if top == "left":
            return "닫히지 않은 \\left"
        return f"닫히지 않은 \\begin{{{top[1]}}}"
    return None


# ---------------------------------------------------------------- 행 나누기와 표지 떼기
def split_rows(tokens: list[Token]) -> list[list[Token]]:
    """최상위(중괄호·내부 환경·\\left 밖)의 \\\\ 로 행을 나눈다."""
    rows: list[list[Token]] = [[]]
    depth = 0
    for t in tokens:
        ty = t.type
        if ty is T.BGROUP:
            depth += 1
        elif ty is T.EGROUP:
            depth = max(0, depth - 1)
        elif ty is T.CS:
            if t.text in ("begin", "left"):
                depth += 1
            elif t.text in ("end", "right"):
                depth = max(0, depth - 1)
            elif t.text == "\\" and depth == 0:
                rows.append([])
                continue
        rows[-1].append(t)
    return rows


def strip_row_prefix(tokens: list[Token]) -> list[Token]:
    """\\\\ 바로 뒤의 * 와 [간격] 을 뗀다 (\\\\*, \\\\[2pt])."""
    j = 0
    if j < len(tokens) and tokens[j].type is T.CHAR and tokens[j].text == "*":
        j += 1
    k = skip_sp(tokens, j)
    if k < len(tokens) and tokens[k].type is T.CHAR and tokens[k].text == "[":
        m = k + 1
        while m < len(tokens) and not (tokens[m].type is T.CHAR and tokens[m].text == "]"):
            m += 1
        if m < len(tokens) and _DIM_RE.match(raw_text(tokens[k + 1:m])):
            return tokens[m + 1:]
    return tokens[j:]


def extract_markers(tokens: list[Token]) -> tuple[list[Token], list[str], bool, Optional[str]]:
    """\\label{…}, \\nonumber, \\notag, \\tag{…} 를 떼어 낸다.
    (남은 토큰, 라벨들, nonumber 여부, tag 값)"""
    out: list[Token] = []
    labels: list[str] = []
    nonumber = False
    tag: Optional[str] = None
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t.type is T.CS and t.text in ("label", "tag"):
            j = i + 1
            if t.text == "tag" and j < n and tokens[j].type is T.CHAR and tokens[j].text == "*":
                j += 1
            arg, j = read_arg_at(tokens, j)
            if t.text == "label":
                labels.append(raw_text(arg).strip())
            else:
                tag = norm_ws(raw_text(arg))
            # 라벨 앞뒤로 남는 공백이 겹치지 않게
            if out and out[-1].type is T.SPACE and j < n and tokens[j].type is T.SPACE:
                j += 1
            i = j
            continue
        if t.type is T.CS and t.text in ("nonumber", "notag"):
            nonumber = True
            i += 1
            continue
        out.append(t)
        i += 1
    return out, labels, nonumber, tag


def find_showparams(tokens: list[Token]) -> list[str]:
    """수식 안 어디에든 있는 \\showparam{\\k} 의 이름들."""
    names = []
    for i, t in enumerate(tokens):
        if t.type is T.CS and t.text == "showparam":
            arg, _ = read_arg_at(tokens, i + 1)
            names.append(param_name(arg))
    return names


def param_name(arg: list[Token]) -> str:
    arg = [t for t in arg if t.type not in (T.SPACE, T.PAR)]
    if len(arg) == 1 and arg[0].type is T.CS:
        return arg[0].text
    return norm_ws(raw_text(arg)).lstrip("\\")


def split_top_showparam(tokens: list[Token]) -> list[tuple]:
    """최상위의 \\showparam{…} 로 수식을 자른다.
    [("math", 토큰들) | ("param", 이름, 원문 토큰들), …]"""
    segs: list[tuple] = []
    cur: list[Token] = []
    depth = 0
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t.type is T.BGROUP:
            depth += 1
        elif t.type is T.EGROUP:
            depth = max(0, depth - 1)
        elif t.type is T.CS and t.text in ("begin", "left"):
            depth += 1
        elif t.type is T.CS and t.text in ("end", "right"):
            depth = max(0, depth - 1)
        elif t.type is T.CS and t.text == "showparam" and depth == 0:
            arg, j = read_arg_at(tokens, i + 1)
            segs.append(("math", cur))
            segs.append(("param", param_name(arg), tokens[i:j]))
            cur = []
            i = j
            continue
        cur.append(t)
        i += 1
    segs.append(("math", cur))
    return segs


# ---------------------------------------------------------------- 문자 체계와 미정의 명령
_SKIP_ARG = {"begin": 1, "end": 1, "label": 1, "tag": 1, "hspace": 1, "vspace": 1}


def scripts_of(tokens: list[Token]) -> list[str]:
    found: set[str] = set()
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t.type is T.CS:
            if t.text in _SKIP_ARG:
                env = None
                if t.text == "begin":
                    env, _ = env_name_at(tokens, i)
                _, i = read_arg_at(tokens, i + 1)
                if env in ("array", "subarray", "alignedat"):
                    _, i = read_arg_at(tokens, i)   # 열 지정
                continue
            if t.text in C.GREEK:
                found.add("greek")
        elif t.type is T.CHAR:
            c = t.text
            if c.isascii() and c.isalpha():
                found.add("latin")
            elif "\uac00" <= c <= "\ud7a3":
                found.add("hangul")
        i += 1
    return [s for s in ("latin", "greek", "hangul") if s in found]


def undefined_in_math(tokens: list[Token]) -> list[Token]:
    """수식 안의 정의되지 않은 제어어 (내장 명령이 아닌 것). \\showparam 인수는 제외."""
    out = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type is T.CS and t.text == "showparam":
            _, i = read_arg_at(tokens, i + 1)
            continue
        if t.type is T.CS and is_word(t.text) and not C.is_known_in_math(t.text):
            out.append(t)
        i += 1
    return out
