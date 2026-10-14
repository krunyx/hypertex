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
""".split()

MATH = set(_GREEK) | set(_MATH_SYMBOLS)

BUILTIN = PREAMBLE | TEXT | MATH


def is_builtin(name: str) -> bool:
    return name in BUILTIN
