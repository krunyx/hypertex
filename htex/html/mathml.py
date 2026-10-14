"""TeX 수식 문자열 → MathML (명세 3절 범위, 8절 한글 수식). (담당: E)

외부 라이브러리 없이 동작하는 작은 재귀 하강 변환기다.

공개 함수
- tex_to_mathml(tex, display=False, params=None, mode=None, attrs=None) -> str
    완결된 <math> 요소 문자열. 변환하지 못하면 <code class="htex-math-error">원본</code>.
    결과에는 <semantics> 와 <annotation encoding="application/x-tex">원본</annotation> 이 들어 있어
    원본 TeX를 복사할 수 있다.
- convert(tex, params=None, mode=None) -> El
    <math> 안쪽 내용(표현 MathML 트리). 실패하면 MathError. 단위 테스트용.

mode는 최상위의 & 와 \\\\ 를 어떻게 정렬할지 정한다.
  None/"align": & 로 나눈 열을 오른쪽·왼쪽 번갈아 정렬 (align 계열)
  "gather": 가운데, "multline": 첫 행 왼쪽·마지막 행 오른쪽·나머지 가운데.

MathML Core(크롬)와 Firefox 모두에서 비슷하게 보이도록,
- \\mathbb 등 글꼴 명령은 mathvariant 대신 유니코드 수학 영숫자 문자로 바꾼다 (Core는 mathvariant="normal"만 지원).
- 표의 열 정렬은 columnalign 속성과 함께 mtd의 class(htex-l/c/r)로도 표시해 CSS로 맞춘다.
"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Any, Iterable

__all__ = ["MathError", "El", "convert", "tex_to_mathml"]


class MathError(ValueError):
    """수식을 변환할 수 없음."""


# ====================================================================== 요소
_TOKEN_TAGS = {"mi", "mn", "mo", "mtext", "ms"}


class El:
    """작은 MathML 요소. children은 El 또는 (토큰 요소라면) 문자열."""

    __slots__ = ("tag", "attrs", "children", "limits", "largeop")

    def __init__(self, tag: str, children: Iterable[Any] = (), **attrs: Any):
        self.tag = tag
        self.children = list(children) if not isinstance(children, str) else [children]
        self.attrs = {k.rstrip("_").replace("_", "-"): v for k, v in attrs.items() if v is not None}
        # 첨자 배치: None=보통(msubsup), "auto"=movablelimits, "limits"=항상 위아래, "nolimits"
        self.limits: str | None = None
        self.largeop = False

    def to_xml(self) -> str:
        out: list[str] = []
        self._emit(out)
        return "".join(out)

    def _emit(self, out: list[str]) -> None:
        out.append("<" + self.tag)
        for k, v in self.attrs.items():
            out.append(f' {k}="{html.escape(str(v), quote=True)}"')
        out.append(">")
        for c in self.children:
            if isinstance(c, El):
                c._emit(out)
            else:
                out.append(html.escape(str(c), quote=False))
        out.append(f"</{self.tag}>")

    def text(self) -> str:
        return "".join(c.text() if isinstance(c, El) else str(c) for c in self.children)

    def __repr__(self) -> str:  # pragma: no cover - 디버그용
        return self.to_xml()


def mrow(items: list[El]) -> El:
    if len(items) == 1:
        return items[0]
    return El("mrow", items)


def mo(ch: str, **attrs: Any) -> El:
    return El("mo", [ch], **attrs)


def mi(ch: str, **attrs: Any) -> El:
    return El("mi", [ch], **attrs)


def mspace(width: str) -> El:
    return El("mspace", width=width)


# ====================================================================== 기호 표
GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "varkappa": "ϰ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π",
    "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ",
    "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "digamma": "ϝ",
}

# 보통 기호(ord)로 쓰는 것 → mi
ORD_SYMBOLS = {
    "infty": "∞", "partial": "∂", "nabla": "∇", "hbar": "ℏ", "hslash": "ℏ", "ell": "ℓ",
    "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ", "beth": "ℶ", "wp": "℘", "emptyset": "∅",
    "varnothing": "∅", "angle": "∠", "imath": "ı", "jmath": "ȷ", "top": "⊤", "bot": "⊥",
    "Box": "□", "square": "□", "triangle": "△", "flat": "♭", "sharp": "♯", "natural": "♮",
    "clubsuit": "♣", "diamondsuit": "♢", "heartsuit": "♡", "spadesuit": "♠",
    "complement": "∁", "eth": "ð", "mho": "℧", "Finv": "Ⅎ", "Game": "⅁",
}

# 연산자·관계·화살표 → mo
OPERATORS = {
    # 이항 연산
    "cdot": "⋅", "times": "×", "div": "÷", "pm": "±", "mp": "∓", "circ": "∘",
    "bullet": "∙", "star": "⋆", "ast": "∗", "oplus": "⊕", "ominus": "⊖", "otimes": "⊗",
    "oslash": "⊘", "odot": "⊙", "cup": "∪", "cap": "∩", "setminus": "∖", "smallsetminus": "∖",
    "wedge": "∧", "vee": "∨", "land": "∧", "lor": "∨", "sqcup": "⊔", "sqcap": "⊓",
    "uplus": "⊎", "amalg": "⨿", "dagger": "†", "ddagger": "‡", "wr": "≀", "diamond": "⋄",
    "bigtriangleup": "△", "bigtriangledown": "▽", "triangleleft": "◃", "triangleright": "▹",
    "lhd": "⊲", "rhd": "⊳", "unlhd": "⊴", "unrhd": "⊵", "boxplus": "⊞", "boxtimes": "⊠",
    "cdotp": "⋅", "centerdot": "⋅",
    # 관계
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠", "leqslant": "⩽",
    "geqslant": "⩾", "approx": "≈", "equiv": "≡", "sim": "∼", "simeq": "≃", "cong": "≅",
    "propto": "∝", "ll": "≪", "gg": "≫", "prec": "≺", "succ": "≻", "preceq": "⪯",
    "succeq": "⪰", "in": "∈", "notin": "∉", "ni": "∋", "owns": "∋", "subset": "⊂",
    "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇", "subsetneq": "⊊", "supsetneq": "⊋",
    "sqsubset": "⊏", "sqsupset": "⊐", "sqsubseteq": "⊑", "sqsupseteq": "⊒",
    "mid": "∣", "nmid": "∤", "parallel": "∥", "nparallel": "∦", "perp": "⊥", "models": "⊨",
    "vdash": "⊢", "dashv": "⊣", "asymp": "≍", "doteq": "≐", "bowtie": "⋈", "smile": "⌣",
    "frown": "⌢", "lt": "<", "gt": ">", "coloneqq": "≔", "eqqcolon": "≕", "triangleq": "≜",
    "lesssim": "≲", "gtrsim": "≳", "approxeq": "≊", "thicksim": "∼", "nsim": "≁",
    "ncong": "≇", "nleq": "≰", "ngeq": "≱", "nless": "≮", "ngtr": "≯",
    "nsubseteq": "⊈", "nsupseteq": "⊉",
    # 논리
    "forall": "∀", "exists": "∃", "nexists": "∄", "neg": "¬", "lnot": "¬",
    "therefore": "∴", "because": "∵",
    # 화살표
    "to": "→", "gets": "←", "mapsto": "↦", "longmapsto": "⟼", "implies": "⟹", "impliedby": "⟸",
    "iff": "⟺", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒", "Leftarrow": "⇐",
    "leftrightarrow": "↔", "Leftrightarrow": "⇔", "longrightarrow": "⟶",
    "longleftarrow": "⟵", "Longrightarrow": "⟹", "Longleftarrow": "⟸",
    "longleftrightarrow": "⟷", "Longleftrightarrow": "⟺", "uparrow": "↑", "downarrow": "↓",
    "Uparrow": "⇑", "Downarrow": "⇓", "updownarrow": "↕", "Updownarrow": "⇕",
    "nearrow": "↗", "searrow": "↘", "swarrow": "↙", "nwarrow": "↖",
    "hookrightarrow": "↪", "hookleftarrow": "↩", "rightharpoonup": "⇀",
    "rightleftharpoons": "⇌", "leadsto": "⇝", "rightsquigarrow": "⇝",
    "twoheadrightarrow": "↠", "rightrightarrows": "⇉", "leftrightarrows": "⇆",
    "leftleftarrows": "⇇", "rightleftarrows": "⇄",
    # 점
    "ldots": "…", "dots": "…", "dotsc": "…", "dotso": "…", "dotsb": "⋯", "dotsm": "⋯",
    "dotsi": "⋯", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱", "mathellipsis": "…",
    # 기타
    "prime": "′", "backslash": "\\", "colon": ":", "S": "§", "P": "¶",
    "surd": "√", "checkmark": "✓", "degree": "°",
}

# 괄호류 (\left 등에서 쓸 수 있는 것)
FENCES = {
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "vert": "|", "Vert": "‖", "lvert": "|", "rvert": "|", "lVert": "‖", "rVert": "‖",
    "lbrace": "{", "rbrace": "}", "{": "{", "}": "}", "|": "‖", "lbrack": "[", "rbrack": "]",
    "ulcorner": "⌜", "urcorner": "⌝", "llcorner": "⌞", "lrcorner": "⌟",
    "lgroup": "⟮", "rgroup": "⟯", "lmoustache": "⎰", "rmoustache": "⎱",
    "backslash": "\\", "uparrow": "↑", "downarrow": "↓", "updownarrow": "↕",
    "Uparrow": "⇑", "Downarrow": "⇓",
}
CHAR_FENCES = set("()[]|/<>.")
_CHAR_FENCE_MAP = {"<": "⟨", ">": "⟩", ".": ""}

# 큰 연산자: 이름 → (문자, 기본 첨자 배치)
BIG_OPS = {
    "sum": ("∑", "auto"), "prod": ("∏", "auto"), "coprod": ("∐", "auto"),
    "bigcup": ("⋃", "auto"), "bigcap": ("⋂", "auto"), "bigoplus": ("⨁", "auto"),
    "bigotimes": ("⨂", "auto"), "bigodot": ("⨀", "auto"), "biguplus": ("⨄", "auto"),
    "bigsqcup": ("⨆", "auto"), "bigvee": ("⋁", "auto"), "bigwedge": ("⋀", "auto"),
    "int": ("∫", "nolimits"), "iint": ("∬", "nolimits"), "iiint": ("∭", "nolimits"),
    "oint": ("∮", "nolimits"), "oiint": ("∯", "nolimits"), "intop": ("∫", "auto"),
}

# 함수 이름 (첨자는 옆에)
FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh",
    "tanh", "coth", "exp", "log", "ln", "lg", "dim", "ker", "deg", "arg", "hom", "sgn",
}
# 함수 이름 (디스플레이에서 첨자가 아래로)
LIMIT_FUNCTIONS = {
    "lim": "lim", "limsup": "lim sup", "liminf": "lim inf", "sup": "sup",
    "inf": "inf", "max": "max", "min": "min", "det": "det", "Pr": "Pr", "gcd": "gcd",
    "argmax": "arg max", "argmin": "arg min", "injlim": "inj lim",
    "projlim": "proj lim",
}

# 간격 명령 → 폭
SPACES = {
    ",": "0.1667em", "thinspace": "0.1667em", ":": "0.2222em", ">": "0.2222em",
    "medspace": "0.2222em", ";": "0.2778em", "thickspace": "0.2778em", "!": "-0.1667em",
    "negthinspace": "-0.1667em", "negmedspace": "-0.2222em", "negthickspace": "-0.2778em",
    " ": "0.3333em", "enspace": "0.5em", "quad": "1em", "qquad": "2em",
}

# 악센트: 이름 → (문자, 늘어나는가, 위(True)/아래(False))
ACCENTS = {
    "hat": ("^", False, True), "widehat": ("^", True, True), "check": ("ˇ", False, True),
    "widecheck": ("ˇ", True, True), "tilde": ("~", False, True), "widetilde": ("~", True, True),
    "bar": ("¯", False, True), "vec": ("→", False, True), "dot": ("˙", False, True),
    "ddot": ("¨", False, True), "dddot": ("⃛", False, True), "breve": ("˘", False, True),
    "acute": ("´", False, True), "grave": ("`", False, True), "mathring": ("˚", False, True),
    "overline": ("‾", True, True), "underline": ("_", True, False),
    "overrightarrow": ("→", True, True), "overleftarrow": ("←", True, True),
    "overleftrightarrow": ("↔", True, True), "underrightarrow": ("→", True, False),
    "underleftarrow": ("←", True, False),
    "overbrace": ("⏞", True, True), "underbrace": ("⏟", True, False),
}

# 글꼴 명령 → 내부 이름
FONT_COMMANDS = {
    "mathbf": "bf", "mathrm": "rm", "mathit": "it", "mathsf": "sf", "mathtt": "tt",
    "mathcal": "cal", "mathscr": "cal", "mathbb": "bb", "mathfrak": "frak",
    "boldsymbol": "bfit", "bm": "bfit", "mathnormal": None, "mathup": "rm", "mathbfit": "bfit",
}

TEXT_COMMANDS = {"text", "textrm", "textnormal", "mbox", "textup", "textbf", "textit", "textsf",
                 "texttt", "emph", "hbox"}

# 크기 지정 괄호
BIG_SIZES = {"big": "1.2em", "Big": "1.623em", "bigg": "2.047em", "Bigg": "2.470em"}

# \not 과 합친 문자
NEGATED = {"=": "≠", "<": "≮", ">": "≯", "≤": "≰", "≥": "≱", "∈": "∉", "∋": "∌", "⊂": "⊄",
           "⊃": "⊅", "⊆": "⊈", "⊇": "⊉", "≡": "≢", "∼": "≁", "≈": "≉", "≃": "≄", "≅": "≇",
           "∣": "∤", "∥": "∦", "∃": "∄", "≺": "⊀", "≻": "⊁"}

# 글자 하나짜리 연산자
CHAR_OPS = {"+": "+", "-": "−", "=": "=", "<": "<", ">": ">", ",": ",", ";": ";", ":": ":",
            "!": "!", "?": "?", "(": "(", ")": ")", "[": "[", "]": "]", "|": "|", "/": "/",
            "*": "∗", ".": ".", "@": "@", '"': '"', "′": "′"}
_FENCE_CHARS = set("()[]|{}⟨⟩⌊⌋⌈⌉‖")

# 유니코드 수학 영숫자: 글꼴 → (대문자 시작, 소문자 시작, 숫자 시작, 예외)
_ALNUM = {
    "bf": (0x1D400, 0x1D41A, 0x1D7CE, {}),
    "it": (0x1D434, 0x1D44E, None, {"h": "ℎ"}),
    "bfit": (0x1D468, 0x1D482, 0x1D7CE, {}),
    "cal": (0x1D49C, 0x1D4B6, None, {"B": "ℬ", "E": "ℰ", "F": "ℱ", "H": "ℋ", "I": "ℐ",
                                     "L": "ℒ", "M": "ℳ", "R": "ℛ", "e": "ℯ", "g": "ℊ", "o": "ℴ"}),
    "frak": (0x1D504, 0x1D51E, None, {"C": "ℭ", "H": "ℌ", "I": "ℑ", "R": "ℜ", "Z": "ℨ"}),
    "bb": (0x1D538, 0x1D552, 0x1D7D8, {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ",
                                       "R": "ℝ", "Z": "ℤ"}),
    "sf": (0x1D5A0, 0x1D5BA, 0x1D7E2, {}),
    "tt": (0x1D670, 0x1D68A, 0x1D7F6, {}),
}
# 그리스 문자 굵은 글꼴: 글꼴 → (대문자 시작, 소문자 시작)
_GREEK_ALNUM = {"bf": (0x1D6A8, 0x1D6C2), "bfit": (0x1D71C, 0x1D736)}


def map_font(ch: str, font: str | None) -> str | None:
    """글꼴에 맞는 유니코드 수학 문자. 대응이 없으면 None."""
    if font not in _ALNUM:
        if font in _GREEK_ALNUM:
            pass
        else:
            return None
    if "A" <= ch <= "Z" or "a" <= ch <= "z" or "0" <= ch <= "9":
        if font not in _ALNUM:
            return None
        cap, small, digit, exc = _ALNUM[font]
        if ch in exc:
            return exc[ch]
        if "A" <= ch <= "Z":
            return chr(cap + ord(ch) - 65)
        if "a" <= ch <= "z":
            return chr(small + ord(ch) - 97)
        return chr(digit + ord(ch) - 48) if digit else None
    if font in _GREEK_ALNUM:
        cap, small = _GREEK_ALNUM[font]
        o = ord(ch)
        if 0x391 <= o <= 0x3A9:
            return chr(cap + o - 0x391)
        if 0x3B1 <= o <= 0x3C9:
            return chr(small + o - 0x3B1)
    return None


def is_hangul(ch: str) -> bool:
    o = ord(ch)
    return 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F


def has_hangul(s: str) -> bool:
    return any(is_hangul(c) for c in s)


def hangul_mi(ch: str) -> El:
    return mi(ch, mathvariant="normal", class_="htex-hangul")


# ====================================================================== 파서
_ENV_DELIMS = {
    "matrix": ("", ""), "pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"), "Vmatrix": ("‖", "‖"), "smallmatrix": ("", ""),
}
_MAX_DEPTH = 200


class _Parser:
    def __init__(self, src: str, params: dict[str, Any] | None, depth: int = 0):
        self.s = src
        self.i = 0
        self.n = len(src)
        self.font: str | None = None
        self.params = params or {}
        self.depth = depth

    # ------------------------------------------------------------ 글자 단위
    def _skip_ws(self) -> None:
        s, n = self.s, self.n
        while self.i < n:
            c = s[self.i]
            if c.isspace():
                self.i += 1
            elif c == "%":  # 주석: 줄 끝까지
                while self.i < n and s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def peek(self) -> tuple[str, str] | None:
        """다음 토큰 (종류, 값). 종류는 "cmd" 또는 "char". 끝이면 None."""
        save = self.i
        tok = self.next()
        self.i = save
        return tok

    def next(self) -> tuple[str, str] | None:
        self._skip_ws()
        if self.i >= self.n:
            return None
        s = self.s
        c = s[self.i]
        if c == "\\":
            j = self.i + 1
            if j >= self.n:
                raise MathError("수식 끝의 역슬래시")
            if s[j].isascii() and s[j].isalpha():
                k = j
                while k < self.n and s[k].isascii() and s[k].isalpha():
                    k += 1
                self.i = k
                return ("cmd", s[j:k])
            self.i = j + 1
            return ("cmd", s[j])
        self.i += 1
        return ("char", c)

    def at_star(self) -> bool:
        """명령 바로 뒤의 * (예: \\operatorname*)."""
        if self.i < self.n and self.s[self.i] == "*":
            self.i += 1
            return True
        return False

    def read_raw_group(self) -> str:
        """{…} 안의 원문을 그대로 읽는다 (중괄호 균형). 중괄호가 없으면 다음 토큰 하나."""
        self._skip_ws()
        if self.i >= self.n:
            raise MathError("인수가 없다")
        if self.s[self.i] != "{":
            start = self.i
            tok = self.next()
            if tok is None or tok == ("char", "}"):
                raise MathError("인수가 없다")
            return self.s[start:self.i]
        depth = 0
        start = self.i + 1
        j = self.i
        while j < self.n:
            c = self.s[j]
            if c == "\\":
                j += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    self.i = j + 1
                    return self.s[start:j]
            j += 1
        raise MathError("닫히지 않은 중괄호")

    def read_optional_raw(self) -> str | None:
        """[…] 선택 인수 원문. 없으면 None."""
        save = self.i
        self._skip_ws()
        if self.i < self.n and self.s[self.i] == "[":
            depth = 0
            j = self.i + 1
            while j < self.n:
                c = self.s[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                elif c == "]" and depth == 0:
                    raw = self.s[self.i + 1:j]
                    self.i = j + 1
                    return raw
                j += 1
            raise MathError("닫히지 않은 [")
        self.i = save
        return None

    def sub(self, src: str) -> El:
        """다른 원문 조각을 같은 설정으로 변환."""
        p = _Parser(src, self.params, self.depth + 1)
        p.font = self.font
        if p.depth > _MAX_DEPTH:
            raise MathError("너무 깊은 중첩")
        items, term = p.parse_seq()
        if term is not None:
            raise MathError(f"예상하지 못한 {term}")
        return mrow(items) if items else El("mrow")

    # ------------------------------------------------------------ 순서열
    def parse_seq(self) -> tuple[list[El], str | None]:
        """종결자까지 읽는다. 종결자: '}', '&', '\\\\', 'end', 'right', 'middle', 끝(None).
        종결자 토큰은 소비하지 않는다."""
        self.depth += 1
        if self.depth > _MAX_DEPTH:
            raise MathError("너무 깊은 중첩")
        try:
            items: list[El] = []
            while True:
                tok = self.peek()
                if tok is None:
                    return items, None
                kind, val = tok
                if kind == "char" and val in "}&":
                    return items, val
                if kind == "cmd" and val in ("\\", "end", "right", "middle"):
                    return items, val
                if kind == "char" and val in "^_'":
                    base = items.pop() if items else El("mrow")
                    items.append(self.parse_scripts(base))
                    continue
                if kind == "cmd" and val in ("limits", "nolimits"):
                    self.next()
                    if not items or not (items[-1].largeop or items[-1].limits):
                        raise MathError(f"\\{val}는 큰 연산자 뒤에만 쓸 수 있다")
                    items[-1].limits = "limits" if val == "limits" else "nolimits"
                    continue
                if kind == "cmd" and val in ("displaystyle", "textstyle", "scriptstyle",
                                              "scriptscriptstyle"):
                    self.next()
                    rest, term = self.parse_seq()
                    attrs = {
                        "displaystyle": dict(displaystyle="true", scriptlevel="0"),
                        "textstyle": dict(displaystyle="false", scriptlevel="0"),
                        "scriptstyle": dict(displaystyle="false", scriptlevel="1"),
                        "scriptscriptstyle": dict(displaystyle="false", scriptlevel="2"),
                    }[val]
                    items.append(El("mstyle", rest, **attrs))
                    return items, term
                atom = self.parse_atom()
                if atom is not None:
                    items.append(atom)
        finally:
            self.depth -= 1

    def parse_group_body(self) -> El:
        """'{' 를 읽은 뒤 '}' 까지."""
        items, term = self.parse_seq()
        if term != "}":
            raise MathError("닫히지 않은 중괄호" if term is None else f"중괄호 안의 {term}")
        self.next()
        return mrow(items) if items else El("mrow")

    def read_arg(self) -> El:
        """명령의 인수 하나: {…} 또는 토큰 하나."""
        tok = self.peek()
        if tok is None:
            raise MathError("인수가 없다")
        if tok == ("char", "{"):
            self.next()
            return self.parse_group_body()
        if tok[0] == "char" and tok[1] in "}&^_":
            raise MathError("인수가 없다")
        if tok[0] == "cmd" and tok[1] in ("\\", "end", "right", "middle"):
            raise MathError("인수가 없다")
        atom = self.parse_atom(single=True)
        return atom if atom is not None else El("mrow")

    def parse_scripts(self, base: El) -> El:
        sub = sup = None
        primes = 0
        while True:
            tok = self.peek()
            if tok == ("char", "'"):
                if sup is not None:
                    raise MathError("프라임과 윗첨자 순서 오류")
                self.next()
                primes += 1
            elif tok == ("char", "^"):
                if sup is not None:
                    raise MathError("윗첨자가 두 번")
                self.next()
                sup = self.read_arg()
            elif tok == ("char", "_"):
                if sub is not None:
                    raise MathError("아래첨자가 두 번")
                self.next()
                sub = self.read_arg()
            else:
                break
        if primes:
            pr = mo({1: "′", 2: "″", 3: "‴", 4: "⁗"}.get(primes, "′" * primes))
            sup = El("mrow", [pr, sup]) if sup is not None else pr
        mode = base.limits
        if mode in ("auto", "limits"):
            if mode == "limits" and base.tag == "mo":
                base.attrs["movablelimits"] = "false"
            if sub is not None and sup is not None:
                return El("munderover", [base, sub, sup])
            if sub is not None:
                return El("munder", [base, sub])
            return El("mover", [base, sup])
        if mode == "nolimits" and base.tag == "mo" and "movablelimits" in base.attrs:
            base.attrs["movablelimits"] = "false"
        if sub is not None and sup is not None:
            return El("msubsup", [base, sub, sup])
        if sub is not None:
            return El("msub", [base, sub])
        return El("msup", [base, sup])

    # ------------------------------------------------------------ 원자
    def letter(self, ch: str) -> El:
        if is_hangul(ch):
            return hangul_mi(ch)
        mapped = map_font(ch, self.font)
        if mapped is not None:
            return mi(mapped) if not ch.isdigit() else El("mn", [mapped])
        if self.font == "rm":
            return mi(ch, mathvariant="normal")
        if self.font in ("bf", "bfit") and not ch.isascii():
            return mi(ch, mathvariant="normal", style="font-weight:bold") if self.font == "bf" \
                else mi(ch, style="font-weight:bold")
        return mi(ch)

    def parse_atom(self, single: bool = False) -> El | None:
        tok = self.next()
        if tok is None:
            raise MathError("수식이 끝났다")
        kind, val = tok
        if kind == "char":
            return self.parse_char(val, single)
        return self.parse_command(val)

    def parse_char(self, c: str, single: bool) -> El | None:
        if c == "{":
            return self.parse_group_body()
        if c == "}":
            raise MathError("짝 없는 }")
        if c.isdigit() and c.isascii():
            if single:
                return self.number(c)
            j = self.i
            s = self.s
            while j < self.n and (s[j].isdigit() and s[j].isascii()
                                  or (s[j] == "." and j + 1 < self.n and s[j + 1].isdigit())):
                j += 1
            num = c + s[self.i:j]
            self.i = j
            return self.number(num)
        if c.isascii() and c.isalpha():
            return self.letter(c)
        if is_hangul(c):
            return hangul_mi(c)
        if c == "~":
            return El("mtext", [" "])
        if c in ("#", "$"):
            raise MathError(f"수식 안의 {c}")
        if c in CHAR_OPS:
            ch = CHAR_OPS[c]
            if c in "()[]|":
                return mo(ch, stretchy="false")
            if c == "/":
                return mo(ch, stretchy="false")
            return mo(ch)
        cat = unicodedata.category(c)
        if cat.startswith("L"):
            return self.letter(c)
        if cat.startswith("N"):
            return El("mn", [c])
        if cat == "Mn":  # 결합 문자 단독
            return mo(c)
        return mo(c)

    def number(self, num: str) -> El:
        if self.font in _ALNUM and _ALNUM[self.font][2] is not None:
            return El("mn", ["".join(map_font(d, self.font) or d for d in num)])
        return El("mn", [num])

    # ------------------------------------------------------------ 명령
    def parse_command(self, name: str) -> El | None:  # noqa: C901 - 분기 표
        if name in GREEK:
            ch = GREEK[name]
            mapped = map_font(ch, self.font)
            if mapped:
                return mi(mapped)
            if name[0].isupper():
                return mi(ch, mathvariant="normal")
            return mi(ch)
        if name in ORD_SYMBOLS:
            ch = ORD_SYMBOLS[name]
            return mi(ch, mathvariant="normal") if len(ch) == 1 else mi(ch)
        if name in BIG_OPS:
            ch, lim = BIG_OPS[name]
            el = mo(ch, largeop="true", movablelimits="true" if lim == "auto" else None)
            if lim == "nolimits":
                el.attrs["movablelimits"] = "false"
            el.largeop = True
            el.limits = lim
            return el
        if name in LIMIT_FUNCTIONS:
            el = mo(LIMIT_FUNCTIONS[name], movablelimits="true", form="prefix",
                    lspace="0.1667em", rspace="0.1667em")
            el.largeop = True
            el.limits = "auto"
            return el
        if name in FUNCTIONS:
            return self.function_name(name)
        if name in OPERATORS:
            ch = OPERATORS[name]
            return mo(ch, stretchy="false") if ch in _FENCE_CHARS else mo(ch)
        if name in FENCES:
            return mo(FENCES[name], stretchy="false")
        if name in SPACES:
            return mspace(SPACES[name])
        if name in ("{", "}"):
            return mo(name, stretchy="false")
        if name in ("%", "$", "&", "#", "_"):
            return mi(name) if name != "_" else mi("_")
        if name in ACCENTS:
            return self.accent(name)
        if name in FONT_COMMANDS:
            return self.font_group(FONT_COMMANDS[name])
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            num = self.read_arg()
            den = self.read_arg()
            el = El("mfrac", [num, den])
            if name == "dfrac" or name == "cfrac":
                return El("mstyle", [el], displaystyle="true", scriptlevel="0")
            if name == "tfrac":
                return El("mstyle", [el], displaystyle="false", scriptlevel="0")
            return el
        if name in ("binom", "dbinom", "tbinom"):
            top = self.read_arg()
            bot = self.read_arg()
            el = El("mrow", [mo("(", stretchy="true", fence="true", form="prefix"),
                             El("mfrac", [top, bot], linethickness="0"),
                             mo(")", stretchy="true", fence="true", form="postfix")])
            if name == "dbinom":
                return El("mstyle", [el], displaystyle="true", scriptlevel="0")
            if name == "tbinom":
                return El("mstyle", [el], displaystyle="false", scriptlevel="0")
            return el
        if name == "sqrt":
            idx = self.read_optional_raw()
            body = self.read_arg()
            if idx is not None and idx.strip():
                return El("mroot", [body, self.sub(idx)])
            return El("msqrt", [body])
        if name in TEXT_COMMANDS:
            return self.text_command(name)
        if name == "operatorname":
            star = self.at_star()
            raw = self.read_raw_group()
            word = _plain_text(raw)
            if not word:
                raise MathError("빈 \\operatorname")
            if star:
                el = mo(word, movablelimits="true", form="prefix", lspace="0.1667em",
                        rspace="0.1667em")
                if has_hangul(word):
                    el.attrs["class"] = "htex-hangul"
                el.largeop = True
                el.limits = "auto"
                return el
            return self.function_name(word)
        if name in ("left", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr",
                    "biggl", "biggr", "Biggl", "Biggr", "bigm", "Bigm", "biggm", "Biggm"):
            if name == "left":
                return self.left_right()
            size = BIG_SIZES[name.rstrip("lrm")]
            d = self.delimiter()
            form = {"l": "prefix", "r": "postfix", "m": "infix"}.get(name[-1]) \
                if name[-1] in "lrm" and name not in BIG_SIZES else None
            return mo(d, stretchy="true", symmetric="true", minsize=size, maxsize=size,
                      form=form)
        if name == "begin":
            return self.environment()
        if name == "not":
            nxt = self.parse_atom(single=True)
            if nxt is None or nxt.tag not in ("mo", "mi") or len(nxt.children) != 1:
                raise MathError("\\not 뒤에 기호가 없다")
            ch = str(nxt.children[0])
            return mo(NEGATED.get(ch, ch + "̸"))
        if name == "pmod":
            arg = self.read_arg()
            return El("mrow", [mspace("1em"), mo("(", stretchy="false"),
                               mo("mod", lspace="0", rspace="0.3333em"), arg,
                               mo(")", stretchy="false")])
        if name == "bmod":
            return mo("mod", lspace="0.2222em", rspace="0.2222em")
        if name == "mod":
            return El("mrow", [mspace("1em"), mo("mod", lspace="0", rspace="0.3333em")])
        if name in ("overset", "underset", "stackrel"):
            over = self.read_arg()
            base = self.read_arg()
            el = El("munder" if name == "underset" else "mover", [base, over])
            return el
        if name == "showparam":
            raw = self.read_raw_group().strip()
            pname = raw[1:] if raw.startswith("\\") else raw
            if pname in self.params:
                return El("mn", [format_number(self.params[pname])], class_="htex-param",
                          data_param=pname)
            return El("merror", [El("mtext", ["\\showparam{" + raw + "}"])],
                      class_="htex-param-error")
        # 통합 단계에서 추가: 빌더(C)가 commands.MATH 에 넣은 명령
        if name == "boxed":
            return El("menclose", [self.read_arg()], notation="box")
        if name == "phantom":
            return El("mphantom", [self.read_arg()])
        if name == "hphantom":
            return El("mpadded", [El("mphantom", [self.read_arg()])], height="0", depth="0")
        if name == "vphantom":
            return El("mpadded", [El("mphantom", [self.read_arg()])], width="0")
        if name == "smash":
            self.read_optional_raw()
            return El("mpadded", [self.read_arg()], height="0", depth="0")
        if name == "hspace":
            self.at_star()
            return mspace(_css_length(self.read_raw_group()))
        if name == "substack":
            raw = self.read_raw_group()
            rows = [self.sub(r) for r in _split_rows(raw)]
            table = El("mtable", [El("mtr", [El("mtd", [r])]) for r in rows], rowspacing="0.1em")
            return El("mstyle", [table], scriptlevel="1")
        if name in ("xrightarrow", "xleftarrow"):
            below = self.read_optional_raw()
            above = self.read_arg()
            arrow = mo("→" if name == "xrightarrow" else "←", stretchy="true", minsize="2em")
            if below is not None and below.strip():
                return El("munderover", [arrow, self.sub(below), above])
            return El("mover", [arrow, above])
        if name in ("label", "tag"):
            raise MathError(f"수식 안의 \\{name}")
        if name in ("nonumber", "notag", "hline", "allowbreak", "nobreak", "relax"):
            return None
        if name == "\\":
            raise MathError("예상하지 못한 \\\\")
        raise MathError(f"모르는 명령 \\{name}")

    def function_name(self, word: str) -> El:
        attrs = {}
        if len(word) == 1:
            attrs["mathvariant"] = "normal"
        if has_hangul(word):
            attrs["class"] = "htex-hangul"
        el = mi(word, **attrs)
        # 괄호가 바로 오면 간격 없이, 아니면 얇은 간격 (TeX의 Op 뒤 간격)
        tok = self.peek()
        tight = tok in (("char", "("), ("char", "["), ("char", "^"), ("char", "_"),
                        ("cmd", "left"), ("cmd", "{"), ("cmd", "big"), ("cmd", "Big"),
                        ("cmd", "bigl"), ("cmd", "Bigl"), ("cmd", "langle")) or tok is None \
            or tok in (("char", "}"), ("char", "&"))
        if tok in (("char", "^"), ("char", "_")):
            # 첨자는 함수 이름에 붙고 그 뒤에 간격: 첨자를 먼저 처리한다
            el = self.parse_scripts(el)
            tok = self.peek()
            tight = tok is None or tok in (("char", "("), ("char", "["), ("cmd", "left"),
                                           ("char", "}"), ("char", "&"))
        return El("mrow", [el, mo("⁡", lspace="0", rspace="0" if tight else "0.1667em")])

    def accent(self, name: str) -> El:
        ch, stretch, over = ACCENTS[name]
        base = self.read_arg()
        op = mo(ch, stretchy="true" if stretch else "false")
        if name in ("overbrace", "underbrace"):
            el = El("mover" if over else "munder", [base, op])
            el.limits = "limits"
            return El("mrow", [el]) if False else el
        if over:
            el = El("mover", [base, op], accent="true")
        else:
            el = El("munder", [base, op], accentunder="true")
        return el

    def font_group(self, font: str | None) -> El:
        save = self.font
        self.font = font
        try:
            return self.read_arg()
        finally:
            self.font = save

    def text_command(self, name: str) -> El:
        raw = self.read_raw_group()
        parts = _split_text_math(raw)
        out: list[El] = []
        style = {"textbf": "font-weight:bold", "textit": "font-style:italic",
                 "emph": "font-style:italic", "texttt": "font-family:monospace"}.get(name)
        for is_math, seg in parts:
            if is_math:
                out.append(self.sub(seg))
            else:
                txt = _plain_text(seg)
                if not txt:
                    continue
                if txt[0] == " ":
                    txt = " " + txt[1:]
                if txt[-1] == " ":
                    txt = txt[:-1] + " "
                attrs: dict[str, str] = {}
                if style:
                    attrs["style"] = style
                if has_hangul(txt):
                    attrs["class"] = "htex-hangul-text"
                out.append(El("mtext", [txt], **attrs))
        if not out:
            return El("mtext", [""])
        return mrow(out)

    def delimiter(self) -> str:
        tok = self.next()
        if tok is None:
            raise MathError("괄호가 없다")
        kind, val = tok
        if kind == "char" and val in CHAR_FENCES:
            return _CHAR_FENCE_MAP.get(val, val)
        if kind == "cmd" and val in FENCES:
            return FENCES[val]
        raise MathError(f"괄호로 쓸 수 없는 {val}")

    def left_right(self) -> El:
        items: list[El] = []
        opening = self.delimiter()
        items.append(mo(opening, stretchy="true", fence="true", form="prefix"))
        while True:
            seq, term = self.parse_seq()
            items.extend(seq)
            if term == "middle":
                self.next()
                items.append(mo(self.delimiter(), stretchy="true", form="infix",
                                lspace="0.05em", rspace="0.05em"))
                continue
            if term == "right":
                self.next()
                items.append(mo(self.delimiter(), stretchy="true", fence="true",
                                form="postfix"))
                return El("mrow", items)
            raise MathError("\\left에 짝이 되는 \\right가 없다")

    # ------------------------------------------------------------ 환경
    def environment(self) -> El:
        env = self.read_raw_group().strip()
        if env in _ENV_DELIMS:
            rows = self.table_rows(env)
            ncols = max((len(r) for r in rows), default=1)
            table = build_table(rows, ["c"] * ncols, small=(env == "smallmatrix"))
            left, right = _ENV_DELIMS[env]
            if not left:
                return table
            return El("mrow", [mo(left, stretchy="true", fence="true", form="prefix"), table,
                               mo(right, stretchy="true", fence="true", form="postfix")])
        if env in ("cases", "dcases", "rcases"):
            rows = self.table_rows(env)
            ncols = max((len(r) for r in rows), default=1)
            table = build_table(rows, ["l"] * ncols, colgap="1em")
            if env == "rcases":
                return El("mrow", [table, mo("}", stretchy="true", fence="true",
                                             form="postfix")])
            return El("mrow", [mo("{", stretchy="true", fence="true", form="prefix"), table,
                               mo("", stretchy="true", fence="true", form="postfix")])
        if env in ("aligned", "split", "alignedat"):
            if env == "alignedat":
                self.read_raw_group()
            rows = self.table_rows(env)
            ncols = max((len(r) for r in rows), default=1)
            return build_table(rows, align_columns(ncols), colgap="0", display=True)
        if env in ("gathered",):
            rows = self.table_rows(env)
            return build_table(rows, ["c"], display=True)
        if env in ("array", "subarray"):
            spec = self.read_raw_group()
            cols = [c for c in spec if c in "lcr"]
            if not cols:
                raise MathError("array 열 지정이 없다")
            rows = self.table_rows(env)
            ncols = max((len(r) for r in rows), default=1)
            cols = (cols + ["c"] * ncols)[:max(ncols, len(cols))]
            return build_table(rows, cols, small=(env == "subarray"))
        raise MathError(f"수식 안에서 쓸 수 없는 환경 {env}")

    def table_rows(self, env: str | None) -> list[list[El]]:
        """& 와 \\\\ 로 나뉜 행렬. env가 None이면 문자열 끝까지 (최상위)."""
        rows: list[list[El]] = []
        row: list[El] = []
        while True:
            seq, term = self.parse_seq()
            row.append(mrow(seq) if seq else El("mrow"))
            if term == "&":
                self.next()
                continue
            if term == "\\":
                self.next()
                self.read_optional_raw()  # \\[2pt]
                rows.append(row)
                row = []
                continue
            if env is None and term is None:
                break
            if env is not None and term == "end":
                self.next()
                name = self.read_raw_group().strip()
                if name != env:
                    raise MathError(f"\\begin{{{env}}}을 \\end{{{name}}}로 닫았다")
                break
            if term is None:
                raise MathError(f"닫히지 않은 환경 {env}")
            raise MathError(f"예상하지 못한 {term}")
        # 끝의 \\ 뒤 빈 행은 버린다
        if not (len(row) == 1 and row[0].tag == "mrow" and not row[0].children and rows):
            rows.append(row)
        return rows


def align_columns(n: int) -> list[str]:
    return ["r" if k % 2 == 0 else "l" for k in range(n)]


def build_table(rows: list[list[El]], cols: list[str], *, colgap: str | None = None,
                small: bool = False, display: bool = False,
                row_aligns: list[str] | None = None) -> El:
    trs = []
    for ri, row in enumerate(rows):
        tds = []
        for ci, cell in enumerate(row):
            a = row_aligns[ri] if row_aligns else (cols[ci] if ci < len(cols) else "c")
            cls = "htex-" + a
            if colgap == "0":
                # align 쌍: 오른쪽 열과 왼쪽 열을 붙인다
                cls += " htex-pair-" + ("a" if ci % 2 == 0 else "b")
            tds.append(El("mtd", [cell], class_=cls,
                          columnalign={"l": "left", "c": "center", "r": "right"}[a]))
        trs.append(El("mtr", tds))
    attrs: dict[str, str] = {
        "columnalign": " ".join({"l": "left", "c": "center", "r": "right"}[c] for c in cols),
    }
    if colgap == "0":
        attrs["columnspacing"] = " ".join("0" if k % 2 == 0 else "2em"
                                          for k in range(max(len(cols) - 1, 1)))
    elif colgap:
        attrs["columnspacing"] = colgap
    if display:
        attrs["displaystyle"] = "true"
    table = El("mtable", trs, **attrs)
    if small:
        return El("mstyle", [table], scriptlevel="1")
    return table


# ====================================================================== 텍스트 도우미
_TEXT_ESCAPES = {"{": "{", "}": "}", "%": "%", "$": "$", "&": "&", "#": "#", "_": "_",
                 " ": " ", ",": " ", ";": " ", ":": " ", "!": "",
                 "\\": "\n", "-": ""}
_TEXT_WORDS = {"textbf", "textit", "textrm", "textsf", "texttt", "emph", "textnormal",
               "textup", "mbox"}
_TEXT_SYMBOLS = {"quad": " ", "qquad": "  ", "ldots": "…", "dots": "…",
                 "textbackslash": "\\", "LaTeX": "LaTeX", "TeX": "TeX", "S": "§",
                 "textendash": "–", "textemdash": "—", "textasciitilde": "~"}


def _split_text_math(raw: str) -> list[tuple[bool, str]]:
    """\\text 안의 원문을 (수식인가, 조각) 목록으로. 이스케이프된 \\$ 는 글자."""
    parts: list[tuple[bool, str]] = []
    buf: list[str] = []
    in_math = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            buf.append(raw[i:i + 2])
            i += 2
            continue
        if c == "$":
            parts.append((in_math, "".join(buf)))
            buf = []
            in_math = not in_math
            i += 1
            continue
        buf.append(c)
        i += 1
    if in_math:
        raise MathError("\\text 안의 닫히지 않은 $")
    parts.append((False, "".join(buf)))
    return [p for p in parts if p[1] or p[0]]


def _plain_text(raw: str) -> str:
    """\\text·\\operatorname 인수의 원문 → 글자. 모르는 명령이면 MathError."""
    out: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == "\\":
            if i + 1 >= n:
                raise MathError("끝의 역슬래시")
            d = raw[i + 1]
            if d.isascii() and d.isalpha():
                j = i + 1
                while j < n and raw[j].isascii() and raw[j].isalpha():
                    j += 1
                word = raw[i + 1:j]
                i = j
                if word in _TEXT_WORDS:
                    continue  # 뒤의 {…}는 중괄호로 처리된다
                if word in _TEXT_SYMBOLS:
                    out.append(_TEXT_SYMBOLS[word])
                    while i < n and raw[i] == " ":
                        i += 1
                    continue
                if word in GREEK:
                    out.append(GREEK[word])
                    continue
                raise MathError(f"\\text 안의 모르는 명령 \\{word}")
            if d in _TEXT_ESCAPES:
                out.append(_TEXT_ESCAPES[d])
                i += 2
                continue
            raise MathError(f"\\text 안의 \\{d}")
        if c in "{}":
            i += 1
            continue
        if c == "~":
            out.append(" ")
            i += 1
            continue
        if raw.startswith("---", i):
            out.append("—")
            i += 3
            continue
        if raw.startswith("--", i):
            out.append("–")
            i += 2
            continue
        if c.isspace():
            if not out or out[-1] != " ":
                out.append(" ")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _css_length(raw: str) -> str:
    """\\hspace 의 TeX 길이 → CSS 길이. 알 수 없으면 0.5em."""
    m = re.fullmatch(r"\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*(em|ex|pt|cm|mm|in|mu)\s*", raw or "")
    if not m:
        return "0.5em"
    v, u = float(m.group(1)), m.group(2)
    if u == "mu":
        return f"{v / 18:.4g}em"
    return f"{v:g}{u}"


def _split_rows(raw: str) -> list[str]:
    """최상위(중괄호 바깥)의 \\\\ 로 나눈다."""
    rows, depth, cur, i = [], 0, [], 0
    while i < len(raw):
        if raw.startswith("\\\\", i) and depth == 0:
            rows.append("".join(cur))
            cur = []
            i += 2
            continue
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            cur.append(raw[i:i + 2])
            i += 2
            continue
        depth += ch == "{"
        depth -= ch == "}"
        cur.append(ch)
        i += 1
    rows.append("".join(cur))
    return [r for r in rows if r.strip()]


def format_number(v: Any) -> str:
    """매개변수 값 표시: 1.0 → "1", 0.2 → "0.2"."""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(v)
    return str(v)


# ====================================================================== 공개 함수
def convert(tex: str, params: dict[str, Any] | None = None, mode: str | None = None) -> El:
    """TeX → <math> 안쪽 표현 MathML. 실패하면 MathError."""
    p = _Parser(tex, params)
    try:
        rows = p.table_rows(None)
    except RecursionError as e:  # pragma: no cover - 방어
        raise MathError("너무 깊은 중첩") from e
    if len(rows) == 1 and len(rows[0]) == 1:
        return rows[0][0]
    ncols = max(len(r) for r in rows)
    if mode == "gather":
        return build_table(rows, ["c"] * ncols, display=True)
    if mode == "multline":
        aligns = ["l" if i == 0 else "r" if i == len(rows) - 1 else "c"
                  for i in range(len(rows))]
        t = build_table(rows, ["c"] * ncols, display=True, row_aligns=aligns)
        t.attrs["width"] = "100%"
        t.attrs["class"] = "htex-multline"
        return t
    return build_table(rows, align_columns(ncols), colgap="0", display=True)


def tex_to_mathml(tex: str, display: bool = False, params: dict[str, Any] | None = None,
                  mode: str | None = None, attrs: dict[str, str] | None = None) -> str:
    """TeX → <math> 문자열. 실패하면 <code class="htex-math-error">원본</code>."""
    try:
        body = convert(tex, params, mode)
    except Exception as e:  # noqa: BLE001 - 어떤 입력도 렌더링을 멈추지 않는다 (명세 7절)
        msg = str(e) if isinstance(e, MathError) else "수식을 변환할 수 없다"
        return (f'<code class="htex-math-error" title="{html.escape(msg, quote=True)}">'
                f"{html.escape(tex, quote=False)}</code>")
    if body.tag != "mrow":
        body = El("mrow", [body])
    sem = El("semantics", [body, El("annotation", [tex], encoding="application/x-tex")])
    math_attrs: dict[str, str] = {}
    if display:
        math_attrs["display"] = "block"
    math_attrs.update(attrs or {})
    return El("math", [sem], **{k.replace("-", "_"): v for k, v in math_attrs.items()}).to_xml()


_WS = re.compile(r"\s+")
