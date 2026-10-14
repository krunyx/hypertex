"""매크로 정의와 확장 (명세 4절). (담당: B)

1단계 상태: 아래 계약대로 구현했다 (B). 모호한 점과 임시 가정은 notes/B-questions.md.

계약 (Expander.expand가 지켜야 할 것)
- 입력: lexer 토큰 전체. 출력: 빌더(C)가 받을 토큰 목록.
- \\newcommand, \\renewcommand, \\DeclareMathOperator 정의를 소비해 출력에서 없앤다.
  \\DeclareMathOperator{\\Tr}{Tr} 의 \\Tr 는 \\operatorname{Tr} 로 확장한다.
- 정의 본문이 자기 자신을 부르거나 이미 정의된 매크로를 통해 순환을 만들면 정의를 거부하고
  macro-recursion 진단 (사례 16). 모르는 명령을 부르는 것은 허용한다 (2026-10-14 결정: 그 명령은
  쓰는 자리에서 빌더가 undefined-command로 표시). 거부된 이름은 정의되지 않은 상태로 남는다.
- 사용자 매크로를 확장한다. 문서 전체 확장 횟수 100,000회, 한 번의 최상위 확장 결과
  10,000토큰을 넘으면 그 호출만 expansion-limit 진단을 내고, 그 자리에 오류 표지 토큰
  (tokens.error_token)을 남긴다. 빌더가 이것을 빨간 오류 노드로 만든다 (사례 17, 2026-10-14 결정).
- \\usemacros{주소}: loader로 읽어 그 문서의 전문(\\begin{document} 앞, 또는 첫 본문 명령 앞)의
  정의만 가져온다. 명령 자체는 출력에 남겨 빌더가 meta.macroImports를 채우게 한다 (사례 18).
- 명세가 제외한 명령(EXCLUDED)은 인수까지 소비하고 excluded-command 진단 (사례 20).
  단, mode == "compat"이면:
    * \\input{f}, \\include{f}: loader로 f(.tex 생략 가능)를 읽어 토큰을 그 자리에 펼친다.
      재귀 깊이 8 제한. 파일이 없으면 missing-resource.
    * \\def\\name{body} (인수 없는 것): \\newcommand로 취급.
    * \\newpage, \\clearpage, \\pagestyle 등 페이지 명령: 진단 없이 버린다.
- 수식 안팎을 구분할 필요는 없다. 확장은 문맥과 무관하다.
- 매개변수(\\parameter로 선언된 이름)와 같은 이름의 매크로는 만들지 않는다. 그리스 문자 등
  내장 명령은 확장하지 않고 그대로 둔다.

구현 메모 (B, 1단계)
- 입력은 "대기열(pending, 확장 결과) + 원래 토큰 목록"으로 읽는다 (TeX의 입력 스택과 같다).
  매크로 확장 결과는 대기열 앞에 다시 넣어 재검토하므로, 본문 끝의 매크로가 본문 뒤의 인수를
  읽는 것(\\newcommand{\\a}{\\ket} \\a{x})도 TeX처럼 동작한다.
- "한 번의 최상위 확장": 대기열이 비어 있을 때 일어난 확장부터 대기열이 다시 빌 때까지.
  그 사이 나온 토큰은 따로 모아 두었다가 끝나면 출력에 붙인다. 모은 토큰 + 대기열 길이가
  10,000을 넘거나 문서 전체 확장 횟수가 100,000을 넘으면 모은 것과 대기열을 버리고
  expansion-limit 진단 하나를 그 최상위 호출 위치로 낸다.
- 확장 결과(본문에서 온 토큰)의 span은 호출 위치로 바꾼다. 인수 토큰은 원래 span을 유지한다.
- 정의 거부 검사: 본문(과 기본값)의 제어어(ASCII 글자 이름)가 자기 자신이거나, 내장도 매개변수도
  정의된 매크로도 아니면 macro-recursion. \\renewcommand로 생기는 간접 순환도 이미 정의된
  매크로 본문을 따라가 찾아낸다. 제어기호(\\|, \\, 등)는 미정의 검사에서 뺀다.
- 내장 명령, 제외 명령, \\parameter 이름으로는 매크로를 만들지 않는다 (진단 없이 정의만 소비).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

from . import commands
from .diagnostics import Sink, Span
from .tokens import T, Token, error_token

if TYPE_CHECKING:
    from .loader import Loader

# 명세 3절 "의도적으로 제외" + 보안 관련. (native 모드 기준)
EXCLUDED = {
    "def", "edef", "gdef", "xdef", "let", "catcode", "input", "include", "write", "immediate",
    "openin", "openout", "read", "csname", "expandafter", "newpage", "clearpage",
    "pagestyle", "thispagestyle", "vspace",
}
# 주의: \pgfmathdeclarefunction, \pgfkeys, \addplot3 은 tikzpicture 안에서만 의미가 있으므로
# 그림 검사(D, picture.py)가 맡는다. 여기서 소비하면 진단이 두 번 난다.
# compat 모드에서 진단 없이 버리는 명령
COMPAT_IGNORED = {"newpage", "clearpage", "pagestyle", "thispagestyle", "bibliographystyle",
                  "vspace", "hspace", "noindent", "centering", "small", "large", "Large"}


@dataclass
class Limits:
    total_expansions: int = 100_000
    tokens_per_expansion: int = 10_000
    input_depth: int = 8


@dataclass
class Macro:
    name: str
    nargs: int
    default: Optional[list[Token]]  # 첫 인수 기본값. None이면 선택 인수 없음
    body: list[Token]
    span: Span


@dataclass
class MacroTable:
    macros: dict[str, Macro] = field(default_factory=dict)

    def is_defined(self, name: str) -> bool:
        return name in self.macros

    def define(self, m: Macro) -> None:
        self.macros[m.name] = m




_DEFINERS = {"newcommand", "renewcommand"}
_INPUT_END = "\x00input-end"  # compat \input 펼친 구간의 끝 표지 (EOF 토큰의 text)
_IGNORED_WITH_ARG = {"pagestyle", "thispagestyle", "bibliographystyle", "vspace", "hspace"}


def _is_control_word(name: str) -> bool:
    return bool(name) and name.isascii() and name.isalpha()


def _refs(tokens: list[Token]) -> list[str]:
    return [t.text for t in tokens if t.type is T.CS]


class _Input:
    """대기열(확장 결과, 뒤집어 저장) + 원래 토큰 목록."""

    def __init__(self, base: list[Token], eof: Token):
        self.base = base
        self.i = 0
        self.pending: list[Token] = []
        self.eof = eof

    def peek(self, k: int = 0) -> Token:
        np = len(self.pending)
        if k < np:
            return self.pending[np - 1 - k]
        j = self.i + k - np
        return self.base[j] if j < len(self.base) else self.eof

    def next(self) -> Token:
        if self.pending:
            return self.pending.pop()
        if self.i < len(self.base):
            t = self.base[self.i]
            self.i += 1
            return t
        return self.eof

    def at_eof(self) -> bool:
        return not self.pending and self.i >= len(self.base)

    def push(self, tokens: list[Token]) -> None:
        self.pending.extend(reversed(tokens))

    def splice(self, tokens: list[Token]) -> None:
        """파일 내용을 다음 위치에 끼워 넣는다 (확장 결과가 아니므로 대기열에 넣지 않는다)."""
        if self.pending:
            self.push(tokens)
        else:
            self.base[self.i:self.i] = tokens


class Expander:
    def __init__(self, table: MacroTable, sink: Sink, loader: "Loader",
                 mode: str = "native", limits: Limits | None = None):
        self.table = table
        self.sink = sink
        self.loader = loader
        self.mode = mode
        self.limits = limits or Limits()
        self.parameters: set[str] = set()
        self.total_expansions = 0
        self._imported: set[str] = set()
        self._import_depth = 0
        self._input_depth = 0               # compat \input 중첩 깊이
        # 최상위 확장 구간
        self._region: Optional[Token] = None
        self._buffer: list[Token] = []
        self._out: list[Token] = []
        self.inp = _Input([], Token(T.EOF, "", Span(1, 1)))

    # ------------------------------------------------------------ 진입점
    def expand(self, tokens: list[Token]) -> list[Token]:
        base = list(tokens)
        eof = base.pop() if base and base[-1].type is T.EOF else Token(
            T.EOF, "", base[-1].span if base else Span(1, 1))
        self.inp = _Input(base, eof)
        self._out = []
        self._region = None
        self._buffer = []
        try:
            self._run()
        except Exception:  # 명세 7절: 어떤 입력에도 토큰 목록을 돌려준다
            self._flush()
            rest = list(reversed(self.inp.pending)) + self.inp.base[self.inp.i:]
            self._out.extend(t for t in rest if t.type is not T.EOF)
        self._out.append(eof)
        return self._out

    # ------------------------------------------------------------ 주 반복
    def _run(self) -> None:
        inp = self.inp
        while True:
            if self._region is not None and not inp.pending:
                self._flush()
            if inp.at_eof():
                break
            t = inp.next()
            if t.type is T.EOF:
                if t.text == _INPUT_END:
                    self._input_depth = max(0, self._input_depth - 1)
                continue
            if t.type is not T.CS:
                self._emit(t)
                continue
            self._handle_cs(t)

    def _handle_cs(self, t: Token) -> None:
        name = t.text
        if name in _DEFINERS:
            self._define_command(t)
        elif name == "DeclareMathOperator":
            self._declare_operator(t)
        elif name == "usemacros":
            self._emit(t)
            self._usemacros(t)
        elif name == "parameter":
            self._emit(t)
            self._note_parameter()
        elif self.mode == "compat" and name in ("input", "include"):
            self._compat_input(t)
        elif self.mode == "compat" and name == "def":
            self._compat_def(t)
        elif self.mode == "compat" and name in COMPAT_IGNORED:
            self._skip_ignored(name)
        elif name in EXCLUDED:
            self._excluded(t)
        elif name in self.table.macros:
            self._expand_macro(t, self.table.macros[name])
        else:
            self._emit(t)

    # ------------------------------------------------------------ 출력과 확장 구간
    def _emit(self, t: Token) -> None:
        if self._region is not None:
            self._buffer.append(t)
            self._check_size()
        else:
            self._out.append(t)

    def _flush(self) -> None:
        if self._region is not None:
            self._out.extend(self._buffer)
        self._buffer = []
        self._region = None

    def _check_size(self) -> bool:
        if self._region is None:
            return True
        if len(self._buffer) + len(self.inp.pending) > self.limits.tokens_per_expansion:
            self._abort(f"\\{self._region.text}의 확장 결과가 "
                        f"{self.limits.tokens_per_expansion}토큰을 넘었다")
            return False
        return True

    def _abort(self, message: str) -> None:
        region = self._region
        span = region.span if region is not None else None
        self.sink.add("expansion-limit", message, span)
        self._buffer = []
        self.inp.pending.clear()
        self._region = None
        if region is not None:
            # 사용자 결정 (2026-10-14): 그 자리를 비우지 않고 빨간 오류로 표시한다 (명세 7절).
            self._out.append(error_token("expansion-limit", "\\" + region.text, region.span))

    def _expand_macro(self, t: Token, m: Macro) -> None:
        args = self._read_macro_args(m)
        if self.total_expansions >= self.limits.total_expansions:
            if self._region is not None:
                self._abort(f"문서 전체 확장 횟수 {self.limits.total_expansions}회를 넘었다")
            else:
                self.sink.add("expansion-limit",
                              f"문서 전체 확장 횟수 {self.limits.total_expansions}회를 넘었다"
                              f" (\\{t.text})", t.span)
                self._out.append(error_token("expansion-limit", "\\" + t.text, t.span))
            return
        self.total_expansions += 1
        result: list[Token] = []
        for b in m.body:
            if b.type is T.PARAM and b.text.isdigit() and 1 <= int(b.text) <= m.nargs:
                result.extend(args[int(b.text) - 1])
            else:
                result.append(Token(b.type, b.text, t.span))
        if self._region is None:
            self._region = t
            self._buffer = []
        self.inp.push(result)
        self._check_size()

    def _read_macro_args(self, m: Macro) -> list[list[Token]]:
        args: list[list[Token]] = []
        k = m.nargs
        if m.default is not None and k >= 1:
            opt = self._read_optional()
            args.append(opt if opt is not None else list(m.default))
            k -= 1
        for _ in range(k):
            args.append(self._read_arg())
        return args

    # ------------------------------------------------------------ 인수 읽기
    def _skip_spaces(self) -> None:
        while self.inp.peek().type is T.SPACE:
            self.inp.next()

    def _read_group_body(self) -> list[Token]:
        """BGROUP을 읽은 직후 호출. 짝 맞는 EGROUP까지 (괄호 제외). 닫히지 않으면 단락 끝에서 멈춘다."""
        out: list[Token] = []
        depth = 0
        while True:
            t = self.inp.peek()
            if t.type is T.EOF or (t.type is T.PAR and depth == 0):
                self.sink.add("unbalanced-brace", "인수의 중괄호가 닫히지 않았다", t.span)
                return out
            self.inp.next()
            if t.type is T.BGROUP:
                depth += 1
            elif t.type is T.EGROUP:
                if depth == 0:
                    return out
                depth -= 1
            out.append(t)

    def _read_arg(self) -> list[Token]:
        """필수 인수: 중괄호 그룹 또는 토큰 하나. 인수가 없으면(}, 빈 줄, 끝) 빈 목록."""
        self._skip_spaces()
        t = self.inp.peek()
        if t.type in (T.EOF, T.PAR, T.EGROUP):
            return []
        self.inp.next()
        if t.type is T.BGROUP:
            return self._read_group_body()
        return [t]

    def _read_optional(self) -> Optional[list[Token]]:
        """[ … ] 선택 인수. 중첩 대괄호·중괄호를 고려한다. 없거나 닫히지 않으면 None (아무것도 소비하지 않음)."""
        k = 0
        while self.inp.peek(k).type is T.SPACE:
            k += 1
        t = self.inp.peek(k)
        if not (t.type is T.CHAR and t.text == "["):
            return None
        start = k
        k += 1
        brace = bracket = 0
        while True:
            u = self.inp.peek(k)
            if u.type in (T.EOF, T.PAR):
                return None
            if u.type is T.BGROUP:
                brace += 1
            elif u.type is T.EGROUP:
                brace -= 1
                if brace < 0:
                    return None
            elif u.type is T.CHAR and brace == 0:
                if u.text == "[":
                    bracket += 1
                elif u.text == "]":
                    if bracket == 0:
                        break
                    bracket -= 1
            k += 1
        for _ in range(start + 1):
            self.inp.next()
        body = [self.inp.next() for _ in range(k - start - 1)]
        self.inp.next()  # ]
        # 전체가 중괄호 하나로 싸여 있으면 한 겹 벗긴다 ([{a]b}])
        if (len(body) >= 2 and body[0].type is T.BGROUP and body[-1].type is T.EGROUP
                and self._outer_group_spans_all(body)):
            body = body[1:-1]
        return body

    @staticmethod
    def _outer_group_spans_all(body: list[Token]) -> bool:
        depth = 0
        for idx, t in enumerate(body):
            if t.type is T.BGROUP:
                depth += 1
            elif t.type is T.EGROUP:
                depth -= 1
                if depth == 0 and idx != len(body) - 1:
                    return False
        return True

    def _skip_star(self) -> bool:
        t = self.inp.peek()
        if t.type is T.CHAR and t.text == "*":
            self.inp.next()
            return True
        return False

    def _read_name(self) -> Optional[str]:
        """\\newcommand{\\foo} 또는 \\newcommand\\foo 의 이름."""
        self._skip_spaces()
        t = self.inp.peek()
        if t.type is T.CS:
            self.inp.next()
            return t.text
        if t.type is T.BGROUP:
            self.inp.next()
            inner = [u for u in self._read_group_body() if u.type is not T.SPACE]
            if len(inner) == 1 and inner[0].type is T.CS:
                return inner[0].text
        return None

    def _arg_text(self, tokens: list[Token]) -> str:
        return "".join(t.text for t in tokens if t.type is not T.CS).strip()

    # ------------------------------------------------------------ 정의
    def _define_command(self, t: Token) -> None:
        renew = t.text == "renewcommand"
        self._skip_star()
        name = self._read_name()
        nargs = 0
        bad = False
        opt = self._read_optional()
        if opt is not None:
            s = self._arg_text(opt)
            if s.isdigit() and 0 <= int(s) <= 9:
                nargs = int(s)
            else:
                bad = True
        default = self._read_optional() if opt is not None else None
        body = self._read_arg()
        if name is None or bad:
            return  # 형식이 틀린 정의: 소비만 한다 (notes/B-questions.md Q4)
        if default is not None and nargs == 0:
            default = None
        self._try_define(Macro(name, nargs, default, body, t.span), renew, t)

    def _declare_operator(self, t: Token) -> None:
        star = self._skip_star()
        name = self._read_name()
        content = self._read_arg()
        if name is None:
            return
        sp = t.span
        body = [Token(T.CS, "operatorname", sp)]
        if star:
            body.append(Token(T.CHAR, "*", sp))
        body += [Token(T.BGROUP, "{", sp), *content, Token(T.EGROUP, "}", sp)]
        self._try_define(Macro(name, 0, None, body, sp), False, t)

    def _can_reference(self, name: str) -> bool:
        return commands.is_builtin(name) or name in self.parameters

    def _try_define(self, m: Macro, renew: bool, at: Token) -> bool:
        name = m.name
        if (commands.is_builtin(name) or name in self.parameters or name in EXCLUDED
                or name in _DEFINERS or name in ("DeclareMathOperator", "usemacros", "parameter")):
            return False  # Q2: 진단 없이 무시
        if not renew and self.table.is_defined(name):
            return False  # LaTeX처럼 기존 정의 유지 (Q3)
        refs = _refs(m.body) + (_refs(m.default) if m.default else [])
        for r in refs:
            if r == name:
                self.sink.add("macro-recursion", f"\\{name}의 정의가 자기 자신을 부른다", at.span)
                return False
        for r in refs:
            if self._can_reference(r) or self.table.is_defined(r):
                continue
            if self.mode == "compat" and (r in COMPAT_IGNORED or r in ("input", "include", "def")):
                continue
            if r in EXCLUDED:
                self.sink.add("excluded-command",
                              f"\\{name}의 정의가 제외된 명령 \\{r}을 쓴다", at.span)
                return False
            # 사용자 결정 (2026-10-14): 모르는 명령을 부르는 정의도 받아들인다.
            # 그 명령은 쓰는 자리에서 빌더가 undefined-command로 표시한다. 순환만 거부한다.
        if self._reaches(refs, name):
            self.sink.add("macro-recursion", f"\\{name}의 정의가 순환을 만든다", at.span)
            return False
        self.table.define(m)
        return True

    def _reaches(self, refs: list[str], target: str) -> bool:
        seen: set[str] = set()
        stack = [r for r in refs if self.table.is_defined(r)]
        while stack:
            r = stack.pop()
            if r == target:
                return True
            if r in seen:
                continue
            seen.add(r)
            m = self.table.macros.get(r)
            if m is None:
                continue
            for x in _refs(m.body) + (_refs(m.default) if m.default else []):
                if x == target:
                    return True
                if self.table.is_defined(x) and x not in seen:
                    stack.append(x)
        return False

    def _note_parameter(self) -> None:
        """\\parameter{\\name}… 의 이름을 기억만 한다 (토큰은 소비하지 않음)."""
        k = 0
        while self.inp.peek(k).type is T.SPACE:
            k += 1
        t = self.inp.peek(k)
        if t.type is T.BGROUP:
            k += 1
            while self.inp.peek(k).type is T.SPACE:
                k += 1
            t = self.inp.peek(k)
        if t.type is T.CS:
            self.parameters.add(t.text)

    # ------------------------------------------------------------ \usemacros
    def _usemacros(self, at: Token) -> None:
        # 인수는 출력에 남겨야 하므로 소비하지 않고 들여다본다
        k = 0
        while self.inp.peek(k).type is T.SPACE:
            k += 1
        if self.inp.peek(k).type is not T.BGROUP:
            return
        k += 1
        parts: list[str] = []
        depth = 0
        while True:
            u = self.inp.peek(k)
            if u.type in (T.EOF, T.PAR):
                return
            if u.type is T.BGROUP:
                depth += 1
            elif u.type is T.EGROUP:
                if depth == 0:
                    break
                depth -= 1
            if u.type is not T.CS:
                parts.append(u.text)
            k += 1
        self._import_macros("".join(parts).strip(), at.span)

    def _import_macros(self, url: str, span: Span) -> None:
        if not url or url in self._imported or self._import_depth >= self.limits.input_depth:
            return
        self._imported.add(url)
        text = self.loader.read_text(url, span, self.sink, extensions=("", ".htex"))
        if text is None:
            return
        from .lexer import tokenize
        toks = tokenize(text, Sink())  # 가져온 문서의 어휘 오류는 이 문서의 진단이 아니다
        saved = (self.inp, self._region, self._buffer)
        self.inp = _Input(toks[:-1] if toks and toks[-1].type is T.EOF else toks, Token(T.EOF, "", span))
        self._region, self._buffer = None, []
        self._import_depth += 1
        try:
            self._scan_preamble()
        finally:
            self._import_depth -= 1
            self.inp, self._region, self._buffer = saved

    def _scan_preamble(self) -> None:
        """가져온 문서의 전문에서 정의만 처리한다. \\begin 이나 첫 본문 요소에서 멈춘다."""
        inp = self.inp
        while not inp.at_eof():
            t = inp.peek()
            if t.type in (T.SPACE, T.PAR):
                inp.next()
                continue
            if t.type is not T.CS:
                return
            name = t.text
            if name in _DEFINERS:
                inp.next()
                self._define_command(t)
            elif name == "DeclareMathOperator":
                inp.next()
                self._declare_operator(t)
            elif name == "usemacros":
                inp.next()
                self._usemacros(t)
                self._skip_cmd_args()
            elif name in commands.PREAMBLE and name not in ("begin", "end"):
                inp.next()
                self._skip_cmd_args()
            else:
                return

    def _skip_cmd_args(self) -> None:
        """뒤따르는 [..] 와 {..} 를 모두 건너뛴다."""
        while True:
            k = 0
            while self.inp.peek(k).type is T.SPACE:
                k += 1
            u = self.inp.peek(k)
            if u.type is T.BGROUP:
                self._read_arg()
            elif u.type is T.CHAR and u.text == "[":
                if self._read_optional() is None:
                    return
            elif u.type is T.CHAR and u.text == "*":
                self._skip_spaces()
                self.inp.next()
            else:
                return

    # ------------------------------------------------------------ 제외 명령
    def _excluded(self, t: Token) -> None:
        name = t.text
        self.sink.add("excluded-command", f"\\{name}은 HyperTeX에서 쓸 수 없다", t.span)
        self._consume_excluded_args(name)

    def _consume_excluded_args(self, name: str) -> None:
        if name in ("def", "edef", "gdef", "xdef"):
            self._skip_spaces()
            if self.inp.peek().type is T.CS:
                self.inp.next()
            self._skip_param_text()
            if self.inp.peek().type is T.BGROUP:
                self._read_arg()
        elif name == "let":
            self._skip_spaces()
            if self.inp.peek().type is T.CS:
                self.inp.next()
            self._skip_spaces()
            self._skip_char("=")
            if self.inp.peek().type is T.SPACE:
                self.inp.next()
            if self.inp.peek().type not in (T.EOF, T.PAR):
                self.inp.next()
        elif name == "catcode":
            self._skip_number()
            self._skip_char("=")
            self._skip_number()
        elif name in ("input", "include"):
            self._skip_filename()
        elif name == "write":
            self._skip_number()
            self._skip_spaces()
            if self.inp.peek().type is T.BGROUP:
                self._read_arg()
        elif name in ("openin", "openout"):
            self._skip_number()
            self._skip_char("=")
            self._skip_filename()
        elif name == "read":
            self._skip_number()
            self._skip_spaces()
            if self._peek_chars("to"):
                self.inp.next()
                self.inp.next()
            self._skip_spaces()
            if self.inp.peek().type is T.CS:
                self.inp.next()
        elif name == "csname":
            while True:
                u = self.inp.peek()
                if u.type in (T.EOF, T.PAR):
                    break
                self.inp.next()
                if u.is_cs("endcsname"):
                    break
        elif name in ("pagestyle", "thispagestyle", "vspace"):
            self._skip_star()
            self._read_arg()
        # immediate, expandafter, newpage, clearpage: 인수 없음

    def _skip_param_text(self) -> None:
        while True:
            u = self.inp.peek()
            if u.type in (T.BGROUP, T.EOF, T.PAR):
                return
            self.inp.next()

    def _skip_char(self, ch: str) -> None:
        self._skip_spaces()
        u = self.inp.peek()
        if u.type is T.CHAR and u.text == ch:
            self.inp.next()
            self._skip_spaces()

    def _peek_chars(self, s: str) -> bool:
        return all(self.inp.peek(i).type is T.CHAR and self.inp.peek(i).text == c
                   for i, c in enumerate(s))

    def _skip_number(self) -> None:
        self._skip_spaces()
        u = self.inp.peek()
        if u.type is T.CHAR and u.text == "`":
            self.inp.next()
            if self.inp.peek().type not in (T.EOF, T.PAR):
                self.inp.next()
        elif u.type is T.CS:
            self.inp.next()
        else:
            if u.type is T.CHAR and u.text in "+-":
                self.inp.next()
            while self.inp.peek().type is T.CHAR and self.inp.peek().text.isdigit():
                self.inp.next()
        self._skip_spaces()

    def _skip_filename(self) -> list[Token]:
        self._skip_spaces()
        if self.inp.peek().type is T.BGROUP:
            return self._read_arg()
        out = []
        while self.inp.peek().type in (T.CHAR, T.SUB, T.TILDE):
            out.append(self.inp.next())
        return out

    def _skip_ignored(self, name: str) -> None:
        if name in _IGNORED_WITH_ARG:
            self._skip_star()
            self._read_arg()

    # ------------------------------------------------------------ 호환 모드
    def _compat_input(self, t: Token) -> None:
        toks = self._skip_filename()
        fname = "".join(u.text for u in toks if u.type is not T.CS).strip()
        if not fname:
            return
        if self._input_depth >= self.limits.input_depth:
            self.sink.add("expansion-limit",
                          f"\\{t.text}의 중첩이 {self.limits.input_depth}단계를 넘었다: {fname}", t.span)
            return
        text = self.loader.read_text(fname, t.span, self.sink, extensions=("", ".tex"))
        if text is None:
            return
        from .lexer import tokenize
        sub = tokenize(text, self.sink)
        end = sub.pop() if sub and sub[-1].type is T.EOF else Token(T.EOF, "", t.span)
        # 파일 끝 표지: 주 반복이 만나면 깊이를 하나 줄이고 버린다 (출력에 나가지 않음)
        sub.append(Token(T.EOF, _INPUT_END, end.span))
        self._input_depth += 1
        self.inp.splice(sub)

    def _compat_def(self, t: Token) -> None:
        self._skip_spaces()
        nt = self.inp.peek()
        if nt.type is not T.CS:
            self._excluded(t)
            return
        k = 1
        while self.inp.peek(k).type is T.SPACE:
            k += 1
        if self.inp.peek(k).type is not T.BGROUP:
            self._excluded(t)  # 인수 있는 \def 는 변환하지 않는다
            return
        self.inp.next()
        body = self._read_arg()
        self._try_define(Macro(nt.text, 0, None, body, t.span), True, t)
