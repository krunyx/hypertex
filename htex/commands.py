"""내장 명령 목록 (명세 3절). (담당: C. B는 읽기만 하고, 추가가 필요하면 보고)

매크로 확장기(B)는 "정의되지 않은 명령 참조"를 판단할 때,
트리 빌더(C)는 undefined-command 진단을 낼 때 이 목록을 쓴다.
"""
from __future__ import annotations

# 전문(preamble) 명령
PREAMBLE = {
    "documentclass", "HyperTeXversion", "title", "author", "date", "keywords", "abstract",
    "usestyle", "usemacros", "usemath", "usetikzlibrary", "usepackage",
    "newcommand", "renewcommand", "DeclareMathOperator", "newtheorem", "parameter",
    "maketitle", "begin", "end",
}

# 구조·텍스트 (본문)
TEXT = {
    "section", "subsection", "subsubsection", "paragraph", "appendix",
    "emph", "textbf", "textit", "texttt", "textsc", "textrm", "textsf", "footnote",
    "\\", "item", "caption", "includegraphics", "label", "ref", "eqref", "href", "url",
    "cite", "bibitem", "bibliography", "transclude", "showparam", "step",
    "hline", "multicolumn", "nonumber", "notag", "textwidth", "linewidth",
    "ldots", "dots", "LaTeX", "TeX", "today", "quad", "qquad",
    "{", "}", "%", "$", "&", "#", "_", " ", ",", ";", ":", "!", "-",
    # C가 추가: 본문 기호·악센트·여러 줄 수식 보조 (빌더가 처리한다)
    "[", "]", "(", ")", "/", "@", "'", "`", "^", "\"", "~", "=", ".", "|",
    "textbackslash", "textasciitilde", "textasciicircum", "textendash", "textemdash",
    "S", "P", "copyright", "dag", "ddag", "slash", "par", "and",
    "textup", "textnormal", "mbox", "tag", "cline",
}

# 환경 이름
ENVIRONMENTS = {
    "document", "itemize", "enumerate", "description", "quote", "verbatim",
    "equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*",
    "displaymath", "cases", "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
    "smallmatrix", "aligned", "gathered", "split", "array",
    "theorem", "lemma", "proposition", "corollary", "definition", "example", "remark", "proof",
    "figure", "table", "tabular", "thebibliography", "abstract",
    "tikzpicture", "axis", "semilogxaxis", "semilogyaxis", "loglogaxis",
    "collapse", "steps",
}

# 정리류 기본 환경과 표시 이름
THEOREM_NAMES = {
    "theorem": "정리", "lemma": "보조정리", "proposition": "명제", "corollary": "따름정리",
    "definition": "정의", "example": "예", "remark": "참고",
}

_GREEK = """alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa
lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega
Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega""".split()

_MATH_SYMBOLS = """
frac dfrac tfrac sqrt sum prod coprod int iint iiint oint lim limsup liminf sup inf max min
sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh coth exp log ln det dim ker deg
arg gcd hom Pr
left right middle big Big bigg Bigg bigl bigr Bigl Bigr
cdot cdots ldots vdots ddots times div pm mp circ bullet star ast oplus otimes odot
le leq ge geq ne neq approx equiv sim simeq cong propto ll gg prec succ
in notin ni subset subseteq supset supseteq cup cap setminus emptyset varnothing
forall exists nexists neg land lor implies iff to mapsto rightarrow leftarrow
Rightarrow Leftarrow leftrightarrow Leftrightarrow longrightarrow Longrightarrow uparrow downarrow
infty partial nabla hbar ell Re Im aleph wp angle perp parallel mid nmid
langle rangle lfloor rfloor lceil rceil vert Vert lvert rvert lVert rVert backslash
hat bar vec dot ddot tilde widetilde widehat overline underline overbrace underbrace
mathbf mathrm mathit mathsf mathtt mathcal mathbb mathfrak boldsymbol operatorname text
displaystyle textstyle scriptstyle limits nolimits
binom dbinom tbinom pmod bmod mod
quad qquad
dagger ddagger prime
mathscr overset underset stackrel cfrac substack phantom hphantom vphantom smash boxed
bigcup bigcap bigoplus bigotimes bigvee bigwedge sqcup uplus wedge vee lnot colon vdash models
therefore because lesssim gtrsim leftrightarrows hookrightarrow xrightarrow xleftarrow not
imath jmath top bot triangle square Box diamond flat sharp natural dots dotsc dotsb dotsm
digamma varkappa leqslant geqslant nleq ngeq subsetneq supsetneq triangleq coloneqq
hspace mathring breve check acute grave overrightarrow overleftarrow Pr arg sgn
lbrace rbrace lbrack rbrack
""".split()

GREEK = frozenset(_GREEK)
MATH = set(_GREEK) | set(_MATH_SYMBOLS)

# 수식 → MathML 변환기가 그릴 줄 아는 명령은 모두 수식 명령으로 본다.
# (목록을 두 곳에서 따로 관리하면 변환기가 그리는 기호도 빌더는 "정의되지 않음"으로 진단한다.)
# htex.html.mathml 은 표준 라이브러리만 쓰고 htex 핵심을 가져오지 않으므로 순환이 없다.
from .html.mathml import HANDLED_COMMANDS as _MATHML_COMMANDS  # noqa: E402
from .html.mathml import TEXTLIKE_COMMANDS as _TEXTLIKE  # noqa: E402

# 수식 전용 기호·명령 (본문에 나오면 빌더가 인라인 수식으로 감싼다)
MATH |= set(_MATHML_COMMANDS) - set(_TEXTLIKE)
# 수식 안에서 알아듣는 본문류 명령 (\rm, \mbox, \index …): 수식 안 진단에서만 쓴다
MATH_TEXTLIKE = frozenset(_TEXTLIKE)

BUILTIN = PREAMBLE | TEXT | MATH


def is_builtin(name: str) -> bool:
    return name in BUILTIN


def is_known_in_math(name: str) -> bool:
    """수식 안에서 정의된 명령인가 (내장 + 변환기가 아는 본문류 명령)."""
    return name in BUILTIN or name in MATH_TEXTLIKE
