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
    * (4단계, 실문서 호환) COMPAT_SKIP 표의 명령(\\index, \\setcounter, \\medskip …)을 인수 서명대로
      버린다. \\def\\name#1#2{…} (구분자 없는 인수), \\gdef·\\edef·\\xdef(=\\def로 근사), \\let,
      \\providecommand, \\DeclareRobustCommand, \\newenvironment·\\renewenvironment,
      comment 환경, \\@ifnextchar·\\@ifstar·\\@gobble 류, \\bgroup·\\egroup 을 지원한다.
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

# compat 모드에서 진단 없이 버리는 명령 (4단계 추가): 이름 → 인수 서명
#   '*' 별표(있으면), '[' 선택 인수(있으면), '{' 필수 인수
# 실제 .tex 원고(arXiv 논문, 책)에서 화면 표시와 무관한 조판·색인·카운터·패키지 설정 명령들.
COMPAT_SKIP: dict[str, str] = {
    # 색인·용어·목차
    "index": "{", "indexsee": "{{", "glossary": "{", "printindex": "", "makeindex": "",
    "makeglossaries": "", "tableofcontents": "", "listoffigures": "", "listoftables": "",
    "addcontentsline": "{{{", "addtocontents": "{{", "phantomsection": "",
    # 카운터·길이
    "setcounter": "{{", "addtocounter": "{{", "stepcounter": "{", "refstepcounter": "{",
    "newcounter": "{[", "counterwithin": "*{{", "counterwithout": "*{{", "numberwithin": "[{{",
    "setlength": "{{", "addtolength": "{{", "settowidth": "{{", "settoheight": "{{",
    "newlength": "{", "newsavebox": "{",
    # 정리 모양·참조 설정
    "theoremstyle": "{", "newtheoremstyle": "{{{{{{{{{", "swapnumbers": "",
    "crefname": "{{{", "Crefname": "{{{", "crefformat": "{{", "Crefformat": "{{",
    "creflabelformat": "{{", "externaldocument": "[{", "hypersetup": "{", "urlstyle": "{",
    "setcitestyle": "{", "nocite": "{", "bibliographystyle": "{",
    # 쪽·간격·글자 크기
    "pagenumbering": "{", "enlargethispage": "*{", "cleardoublepage": "",
    "pagebreak": "[", "nopagebreak": "[", "linebreak": "[", "nolinebreak": "[",
    "smallskip": "", "medskip": "", "bigskip": "", "smallbreak": "", "medbreak": "",
    "bigbreak": "", "goodbreak": "", "filbreak": "", "vfill": "", "hfill": "", "hfil": "",
    "indent": "", "raggedright": "", "raggedleft": "", "sloppy": "", "fussy": "",
    "frenchspacing": "", "nonfrenchspacing": "", "raggedbottom": "", "flushbottom": "",
    "onehalfspacing": "", "doublespacing": "", "singlespacing": "", "setstretch": "{",
    "linespread": "{", "fontsize": "{{", "selectfont": "", "normalsize": "", "footnotesize": "",
    "scriptsize": "", "tiny": "", "LARGE": "", "huge": "", "Huge": "",
    "allowdisplaybreaks": "[", "displaybreak": "[",
    # 패키지·문서 설정
    "graphicspath": "{", "DeclareGraphicsExtensions": "{", "includeonly": "{",
    "captionsetup": "[{", "geometry": "{", "definecolor": "{{{", "colorlet": "{{",
    "xyoption": "{", "UseAllTwocells": "", "CompileMatrices": "", "SelectTips": "{{",
    "hyphenation": "{", "VerbatimFootnotes": "", "frontmatter": "", "mainmatter": "",
    "backmatter": "", "makeatletter": "", "makeatother": "", "IfFileExists": "{{{",
    "DeclareMathSymbol": "{{{{", "DeclareSymbolFont": "{{{{{", "SetSymbolFont": "{{{{",
    "DeclareMathAlphabet": "{{{{{", "DeclareFontFamily": "{{{", "DeclareFontShape": "{{{{{{",
    "DeclareOption": "{{", "ProcessOptions": "*", "RequirePackage": "[{[", "NeedsTeXFormat": "{[",
    "ProvidesPackage": "{[", "PassOptionsToPackage": "{{", "AtBeginDocument": "{",
    "AtEndDocument": "{", "newif": "{", "maketitle": "",
    # 아무것도 그리지 않는 명령
    "protect": "", "xspace": "", "qedhere": "", "null": "", "leavevmode": "",
    "ignorespaces": "", "unskip": "", "nobreak": "", "allowbreak": "", "strut": "",
    "normalfont": "", "marginpar": "[{", "markboth": "{{", "markright": "{",
    "crefrangeformat": "{{", "Crefrangeformat": "{{", "crefmultiformat": "{{{{",
    "Crefmultiformat": "{{{{", "crefrangemultiformat": "{{{{", "Crefrangemultiformat": "{{{{",
    "crefalias": "{{", "setlist": "[{", "setitemize": "[{", "setenumerate": "[{",
    "setdescription": "[{", "newaliascnt": "{{", "aliascntresetthe": "{",
    "hfuzz": "", "vfuzz": "", "tolerance": "", "emergencystretch": "", "rule": "[{{",
    "thanks": "{", "relax": "",
}


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
    # compat \def 의 구분자 있는 인수: ("param", n) 또는 ("tok", Token) 의 나열. None이면 보통 인수
    pattern: Optional[list] = None


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
# compat 모드에서 확장기가 직접 처리하는 명령 (정의 본문에 있어도 거부하지 않는다)
_COMPAT_HANDLED = {"input", "include", "def", "gdef", "edef", "xdef", "let", "providecommand",
                   "DeclareRobustCommand", "newenvironment", "renewenvironment", "@ifnextchar",
                   "@ifstar", "@gobble", "@gobbletwo", "@firstofone", "@firstoftwo",
                   "@secondoftwo", "bgroup", "egroup", "iffalse", "iftrue", "fi", "chardef",
                   "if", "ifx", "ifdefined", "ifcsname", "else", "detokenize", "relax"}


def _is_control_word(name: str) -> bool:
    return bool(name) and name.isascii() and name.isalpha()


def _one_group(toks: list[Token]) -> bool:
    """toks 전체가 짝 맞는 {…} 하나인가."""
    depth = 0
    for i, t in enumerate(toks):
        if t.type is T.BGROUP:
            depth += 1
        elif t.type is T.EGROUP:
            depth -= 1
            if depth == 0 and i != len(toks) - 1:
                return False
    return depth == 0


def _substitute(m: "Macro", args: list[list[Token]], span: Span) -> list[Token]:
    out: list[Token] = []
    for b in m.body:
        if b.type is T.PARAM and b.text.isdigit() and 1 <= int(b.text) <= m.nargs:
            out.extend(args[int(b.text) - 1])
        else:
            out.append(Token(b.type, b.text, span))
    return out


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
        self._conds: list[bool] = []   # compat TeX 조건문의 열린 가지
        # compat \newenvironment: 이름 → (시작 매크로, 끝 토큰, comment 환경인가)
        self.envs: dict[str, tuple[Macro, list[Token], bool]] = {}
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
        if self.mode == "compat" and self._compat_cs(t):
            return
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
        elif self.mode == "compat" and (name in COMPAT_IGNORED or name in COMPAT_SKIP):
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
        if m.pattern is not None:
            return self._match_pattern(m.pattern, m.nargs)
        args: list[list[Token]] = []
        k = m.nargs
        if m.default is not None and k >= 1:
            opt = self._read_optional()
            args.append(opt if opt is not None else list(m.default))
            k -= 1
        for _ in range(k):
            args.append(self._read_arg())
        return args

    def _match_pattern(self, pattern: list, nargs: int) -> list[list[Token]]:
        """TeX의 구분자 인수 맞추기 (\\def\\a#1.#2\\end{…}).
        - 인수 앞의 구분자는 입력과 그대로 맞춰 소비한다 (맞지 않으면 거기서 멈춘다).
        - 뒤에 구분자가 오는 인수: 중괄호 깊이 0에서 그 구분자가 나올 때까지. 전체가 {…} 하나면 벗긴다.
        - 뒤에 구분자가 없는 인수: 보통 인수 하나."""
        args: list[list[Token]] = [[] for _ in range(nargs)]

        def same(a: Token, b: Token) -> bool:
            if a.type is T.SPACE and b.type is T.SPACE:
                return True
            return a.type is b.type and a.text == b.text

        k = 0
        while k < len(pattern):
            kind, val = pattern[k]
            if kind == "tok":
                nxt = self.inp.peek()
                if val.type is not T.SPACE and nxt.type is T.SPACE:
                    self._skip_spaces()
                    nxt = self.inp.peek()
                if not same(val, nxt):
                    return args  # 정의와 맞지 않는 사용: 읽은 데까지만
                self.inp.next()
                k += 1
                continue
            # 인수
            delim = []
            j = k + 1
            while j < len(pattern) and pattern[j][0] == "tok":
                delim.append(pattern[j][1])
                j += 1
            if not delim:
                args[val - 1] = self._read_arg()
                k += 1
                continue
            got: list[Token] = []
            depth = 0
            while True:
                u = self.inp.peek()
                if u.type is T.EOF or len(got) > self.limits.tokens_per_expansion:
                    break
                if depth == 0 and all(same(d, self.inp.peek(i)) for i, d in enumerate(delim)):
                    break
                self.inp.next()
                got.append(u)
                if u.type is T.BGROUP:
                    depth += 1
                elif u.type is T.EGROUP:
                    depth -= 1
            # 앞뒤 공백을 걷고, 전체가 {…} 하나면 중괄호를 벗긴다
            while got and got[0].type is T.SPACE:
                got.pop(0)
            if (len(got) >= 2 and got[0].type is T.BGROUP and got[-1].type is T.EGROUP
                    and _one_group(got)):
                got = got[1:-1]
            args[val - 1] = got
            k += 1  # 구분자는 다음 차례에 "tok"로 소비한다
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
        if self.mode == "compat":
            # 4단계: 실제 원고의 매크로는 \@ifnextchar 로 보호된 재귀(\prd → \prd@parens → …)나
            # 비교 대상으로서의 자기 이름(\@ifnextchar\prd)을 흔히 쓴다. 무한 확장은 확장 상한이
            # 막으므로 compat 에서는 순환 검사를 하지 않는다 (notes/K-questions.md).
            for r in refs:
                if (r in EXCLUDED and r not in _COMPAT_HANDLED and r not in COMPAT_SKIP
                        and r not in COMPAT_IGNORED):
                    self.sink.add("excluded-command",
                                  f"\\{name}의 정의가 제외된 명령 \\{r}을 쓴다", at.span)
                    return False
            self.table.define(m)
            return True
        for r in refs:
            if r == name:
                self.sink.add("macro-recursion", f"\\{name}의 정의가 자기 자신을 부른다", at.span)
                return False
        for r in refs:
            if self._can_reference(r) or self.table.is_defined(r):
                continue
            if self.mode == "compat" and (r in COMPAT_IGNORED or r in COMPAT_SKIP
                                          or r in _COMPAT_HANDLED):
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
            return
        for ch in COMPAT_SKIP.get(name, ""):
            if ch == "*":
                self._skip_star()
            elif ch == "[":
                self._read_optional()
            else:
                self._skip_spaces()
                if self.inp.peek().type in (T.BGROUP, T.CS, T.CHAR):
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
        """\\def\\name{…}, \\def\\name#1#2{…}, \\def\\name[#1]#2.{…} (구분자 있는 인수) → 매크로.
        매개변수 번호가 차례대로가 아니면 제외한다."""
        self._skip_spaces()
        nt = self.inp.peek()
        if nt.type is not T.CS:
            self._excluded(t)
            return
        k, n = 1, 0
        pattern: list = []
        delimited = False
        while True:
            u = self.inp.peek(k)
            if u.type in (T.BGROUP, T.EOF, T.PAR) or k > 64:
                break
            if u.type is T.PARAM:
                if u.text != str(n + 1) or n >= 9:
                    self._excluded(t)  # 번호가 차례대로가 아닌 매개변수 글
                    return
                n += 1
                pattern.append(("param", n))
            elif u.type is T.SPACE and (not pattern or pattern[-1][0] == "param"):
                pass  # 이름·매개변수 바로 뒤 공백은 TeX도 무시한다
            else:
                pattern.append(("tok", u))
                delimited = True
            k += 1
        if self.inp.peek(k).type is not T.BGROUP:
            self._excluded(t)
            return
        for _ in range(k):
            self.inp.next()
        body = self._read_arg()
        m = Macro(nt.text, n, None, body, t.span, pattern if delimited else None)
        self._try_define(m, True, t)

    # ---- 4단계: 실문서 호환
    def _compat_cs(self, t: Token) -> bool:
        """compat 모드에서만 하는 처리. 처리했으면 True."""
        name = t.text
        if name in ("gdef", "edef", "xdef"):
            self._compat_def(t)
        elif name == "let":
            self._compat_let(t)
        elif name in ("providecommand", "DeclareRobustCommand"):
            self._define_command(Token(T.CS, "renewcommand" if name == "DeclareRobustCommand"
                                       else "newcommand", t.span))
        elif name in ("newenvironment", "renewenvironment"):
            self._compat_newenv(t)
        elif name == "begin":
            return self._compat_begin(t)
        elif name == "end":
            return self._compat_end(t)
        elif name == "@ifnextchar":
            self._ifnextchar(t)
        elif name == "@ifstar":
            yes, no = self._read_arg(), self._read_arg()
            if self.inp.peek().type is T.CHAR and self.inp.peek().text == "*":
                self.inp.next()
                self._push_expansion(t, yes)
            else:
                self._push_expansion(t, no)
        elif name in ("@gobble", "@gobbletwo"):
            self._read_arg()
            if name == "@gobbletwo":
                self._read_arg()
        elif name in ("@firstofone", "@firstoftwo", "@secondoftwo"):
            a = self._read_arg()
            if name == "@firstofone":
                self._push_expansion(t, a)
            else:
                b = self._read_arg()
                self._push_expansion(t, a if name == "@firstoftwo" else b)
        elif name == "iffalse":
            self._cond_branch(False)
        elif name == "iftrue":
            self._cond_branch(True)
        elif name == "if":
            a, b = self._cond_operand(), self._cond_operand()
            same = (a is not None and b is not None and
                    (a.type is T.CS and b.type is T.CS or a.type is b.type and a.text == b.text))
            self._cond_branch(same)
        elif name == "ifx":
            a, b = self.inp.next(), self.inp.next()
            self._cond_branch(self._same_meaning(a, b))
        elif name in ("ifdefined", "ifcsname"):
            if name == "ifcsname":
                self._cond_branch(False)
                return True
            a = self.inp.next()
            self._cond_branch(a.type is T.CS and (a.text in self.table.macros
                                                   or commands.is_builtin(a.text)))
        elif name == "else":
            if self._conds:
                self._conds.pop()
                self._skip_conditional(stop_at_else=False)
            # 짝 없는 \else 는 버린다
        elif name == "fi":
            if self._conds:
                self._conds.pop()
        elif name == "detokenize":
            arg = self._read_arg()
            chars: list[Token] = []
            for u in arg:
                txt = ("\\" + u.text + (" " if u.text[:1].isalpha() else "")) \
                    if u.type is T.CS else u.text
                chars.extend(Token(T.CHAR if c != " " else T.SPACE, c, t.span) for c in txt)
            self._push_expansion(t, chars)
        elif name == "chardef":
            # \chardef\bslash=`\\  또는 \chardef\x=65 → 글자 하나로 확장하는 매크로
            self._skip_spaces()
            nt = self.inp.peek()
            if nt.type is not T.CS:
                return True
            self.inp.next()
            self._skip_char("=")
            self._skip_spaces()
            u = self.inp.next()
            ch = None
            if u.type is T.CHAR and u.text == "`":
                v = self.inp.next()
                ch = v.text if v.type in (T.CS, T.CHAR) else None
            else:
                digits = u.text if u.type is T.CHAR else ""
                while self.inp.peek().type is T.CHAR and self.inp.peek().text.isdigit():
                    digits += self.inp.next().text
                if digits.isdigit():
                    ch = chr(int(digits))
            if ch:
                self._try_define(Macro(nt.text, 0, None, [Token(T.CHAR, ch, t.span)], t.span),
                                 True, t)
        elif name in ("bgroup", "egroup"):
            self._emit(Token(T.BGROUP if name == "bgroup" else T.EGROUP,
                             "{" if name == "bgroup" else "}", t.span))
        else:
            return False
        return True

    def _push_expansion(self, t: Token, tokens: list[Token]) -> None:
        """확장 결과처럼 대기열에 넣는다 (확장 횟수 상한을 같이 센다)."""
        if self.total_expansions >= self.limits.total_expansions:
            self.sink.add("expansion-limit",
                          f"문서 전체 확장 횟수 {self.limits.total_expansions}회를 넘었다"
                          f" (\\{t.text})", t.span)
            return
        self.total_expansions += 1
        if self._region is None:
            self._region = t
            self._buffer = []
        self.inp.push(list(tokens))
        self._check_size()

    def _compat_let(self, t: Token) -> None:
        """\\let\\a=\\b, \\let\\a\\b: \\b가 매크로면 그 정의를 복사, 아니면 \\a → \\b 로."""
        self._skip_spaces()
        nt = self.inp.peek()
        if nt.type is not T.CS:
            self._excluded(t)
            return
        self.inp.next()
        self._skip_spaces()
        self._skip_char("=")
        if self.inp.peek().type is T.SPACE:
            self.inp.next()
        src = self.inp.peek()
        if src.type in (T.EOF, T.PAR):
            return
        self.inp.next()
        if src.type is T.CS and src.text == nt.text:
            return
        if src.type is T.CS and src.text in self.table.macros:
            m = self.table.macros[src.text]
            self._try_define(Macro(nt.text, m.nargs, m.default, list(m.body), t.span,
                                   m.pattern), True, t)
        elif src.type in (T.CS, T.CHAR):
            self._try_define(Macro(nt.text, 0, None, [src], t.span), True, t)

    def _env_name_ahead(self) -> tuple[Optional[str], int]:
        """대기열 앞의 {이름} 을 소비하지 않고 읽는다. (이름, 그 뒤 위치)"""
        k = 0
        while self.inp.peek(k).type is T.SPACE:
            k += 1
        if self.inp.peek(k).type is not T.BGROUP:
            return None, 0
        k += 1
        chars = []
        while True:
            u = self.inp.peek(k)
            if u.type is T.EGROUP:
                return "".join(chars).strip(), k + 1
            if u.type not in (T.CHAR, T.SPACE) or len(chars) > 64:
                return None, 0
            chars.append(u.text)
            k += 1

    def _compat_newenv(self, t: Token) -> None:
        renew = t.text == "renewenvironment"
        self._skip_star()
        name, k = self._env_name_ahead()
        if name is None:
            self._read_arg()
        else:
            for _ in range(k):
                self.inp.next()
        nargs, default = 0, None
        opt = self._read_optional()
        if opt is not None:
            s = self._arg_text(opt)
            nargs = int(s) if s.isdigit() and int(s) <= 9 else 0
            default = self._read_optional()
        begin = self._read_arg()
        end = self._read_arg()
        if not name or name in commands.ENVIRONMENTS or name == "document":
            return
        if name in self.envs and not renew:
            return
        comment = [u.text for u in begin if u.type is T.CS] == ["comment"]
        self.envs[name] = (Macro(name, nargs, default, begin, t.span), end, comment)

    def _compat_begin(self, t: Token) -> bool:
        name, k = self._env_name_ahead()
        if name is None:
            return False
        if name == "comment" or (name in self.envs and self.envs[name][2]):
            for _ in range(k):
                self.inp.next()
            self._skip_environment(name)
            return True
        if name not in self.envs:
            return False
        for _ in range(k):
            self.inp.next()
        m = self.envs[name][0]
        self._expand_macro(t, m)
        return True

    def _compat_end(self, t: Token) -> bool:
        name, k = self._env_name_ahead()
        if name is None or name not in self.envs:
            return False
        for _ in range(k):
            self.inp.next()
        self._push_expansion(t, self.envs[name][1])
        return True

    def _skip_environment(self, name: str) -> None:
        """\\begin{name} 다음부터 짝이 맞는 \\end{name} 까지 버린다 (comment 환경)."""
        depth = 1
        while not self.inp.at_eof():
            u = self.inp.next()
            if u.type is T.CS and u.text in ("begin", "end"):
                nm, k = self._env_name_ahead()
                if nm == name:
                    for _ in range(k):
                        self.inp.next()
                    depth += 1 if u.text == "begin" else -1
                    if depth == 0:
                        return

    # ---- TeX 조건문 (compat): \if \ifx \ifdefined \iftrue \iffalse \else \fi
    #  self._conds 는 "지금 살아 있는 가지"의 쌓임. 참 가지 끝의 \else 를 만나면 \fi 까지 버린다.
    def _cond_branch(self, true: bool) -> None:
        if true:
            self._conds.append(True)
        elif self._skip_conditional(stop_at_else=True):
            self._conds.append(True)   # \else 가지가 살아 있다

    def _skip_conditional(self, stop_at_else: bool) -> bool:
        """짝 맞는 \\fi 까지 버린다. stop_at_else 이고 같은 깊이의 \\else 를 만나면 거기서 멈추고 True."""
        depth = 1
        while not self.inp.at_eof():
            u = self.inp.next()
            if u.type is not T.CS:
                continue
            if u.text.startswith("if") and u.text != "iff" and u.text.isalpha():
                depth += 1
            elif u.text == "fi":
                depth -= 1
                if depth == 0:
                    return False
            elif u.text == "else" and depth == 1 and stop_at_else:
                return True
        return False

    def _cond_operand(self) -> Optional[Token]:
        """\\if 의 비교 대상: 매크로와 \\detokenize 를 펼친 뒤의 첫 토큰."""
        for _ in range(64):
            u = self.inp.next()
            if u.type is T.EOF:
                return None
            if u.type is T.CS and u.text in self.table.macros:
                m = self.table.macros[u.text]
                self.inp.push(_substitute(m, self._read_macro_args(m), u.span))
                continue
            if u.type is T.CS and u.text == "detokenize":
                self._compat_cs(u)
                continue
            if u.type is T.SPACE:
                return Token(T.CHAR, " ", u.span)
            return u
        return None

    def _same_meaning(self, a: Token, b: Token) -> bool:
        if a.type is b.type and a.text == b.text:
            return True
        if a.type is T.CS and b.type is T.CS:
            ma, mb = self.table.macros.get(a.text), self.table.macros.get(b.text)
            if ma and mb:
                return (ma.nargs == mb.nargs and [(x.type, x.text) for x in ma.body]
                        == [(x.type, x.text) for x in mb.body])
        return False

    def _ifnextchar(self, t: Token) -> None:
        """\\@ifnextchar X{있을 때}{없을 때}: 공백 뒤 다음 토큰이 X인지 본다."""
        self._skip_spaces()
        ch = self.inp.next()
        yes, no = self._read_arg(), self._read_arg()
        self._skip_spaces()
        nxt = self.inp.peek()
        if ch.type is T.CS and ch.text == "bgroup":
            match = nxt.type is T.BGROUP
        else:
            match = nxt.type is ch.type and nxt.text == ch.text
        self._push_expansion(t, yes if match else no)
