"""매크로 정의와 확장 (명세 4절). (담당: B)

0단계 상태: 인터페이스와 통과(pass-through) 구현만 있다. 확장은 하지 않고,
정의 명령도 그대로 흘려보낸다. B가 아래 docstring의 계약대로 채운다.

계약 (Expander.expand가 지켜야 할 것)
- 입력: lexer 토큰 전체. 출력: 빌더(C)가 받을 토큰 목록.
- \\newcommand, \\renewcommand, \\DeclareMathOperator 정의를 소비해 출력에서 없앤다.
  \\DeclareMathOperator{\\Tr}{Tr} 의 \\Tr 는 \\operatorname{Tr} 로 확장한다.
- 정의 본문이 "자기 자신" 또는 "내장 명령도 아니고 이미 정의된 매크로도 아닌 명령"을
  참조하면 정의를 거부하고 macro-recursion 진단 (사례 16). 거부된 이름은 정의되지 않은 상태로 남는다.
- 사용자 매크로를 확장한다. 문서 전체 확장 횟수 100,000회, 한 번의 최상위 확장 결과
  10,000토큰을 넘으면 그 호출만 expansion-limit 진단을 내고 CS 토큰 하나(이름 그대로)를
  남기지 말고 아무것도 남기지 않는다 (사례 17).
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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from .diagnostics import Sink, Span
from .tokens import T, Token

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


class Expander:
    def __init__(self, table: MacroTable, sink: Sink, loader: "Loader",
                 mode: str = "native", limits: Limits | None = None):
        self.table = table
        self.sink = sink
        self.loader = loader
        self.mode = mode
        self.limits = limits or Limits()

    def expand(self, tokens: list[Token]) -> list[Token]:
        """0단계: 통과. B가 위 계약대로 구현한다."""
        return list(tokens)
