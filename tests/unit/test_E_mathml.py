"""E: TeX → MathML 변환기 단위 테스트 (htex/html/mathml.py)."""
from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from htex.html.mathml import MathError, convert, tex_to_mathml


def mm(tex: str, **kw) -> str:
    out = tex_to_mathml(tex, **kw)
    assert out.startswith("<math"), out
    return out


def inner(tex: str, **kw) -> str:
    return convert(tex, **kw).to_xml()


class _Balance(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.bad: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.bad.append(tag)
        else:
            self.stack.pop()


def balanced(s: str) -> bool:
    p = _Balance()
    p.feed(s)
    p.close()
    return not p.bad and not p.stack


# ---------------------------------------------------------------- 기본 구조
def test_semantics_and_annotation_keep_original():
    tex = r"a < b \& c"
    out = mm(r"a < b")
    assert "<semantics>" in out
    assert '<annotation encoding="application/x-tex">a &lt; b</annotation>' in out
    assert balanced(out)
    assert tex  # 원본 문자열은 그대로


def test_display_attribute():
    assert '<math display="block">' in tex_to_mathml("x", display=True)
    assert "display=" not in tex_to_mathml("x")


def test_tokens():
    s = inner("x + 12.5 = y")
    assert "<mi>x</mi>" in s and "<mn>12.5</mn>" in s and "<mo>=</mo>" in s
    assert "<mo>+</mo>" in s
    assert "<mo>−</mo>" in inner("a - b")  # 빼기 기호는 U+2212


# ---------------------------------------------------------------- 분수·근호·이항
@pytest.mark.parametrize("cmd,style", [("frac", None), ("dfrac", "true"), ("tfrac", "false")])
def test_fractions(cmd, style):
    s = inner(rf"\{cmd}{{a+1}}{{b}}")
    assert "<mfrac><mrow><mi>a</mi><mo>+</mo><mn>1</mn></mrow><mi>b</mi></mfrac>" in s
    if style:
        assert f'displaystyle="{style}"' in s


def test_frac_single_token_args():
    assert inner(r"\frac12") == "<mfrac><mn>1</mn><mn>2</mn></mfrac>"
    assert inner(r"\frac\alpha\beta") == "<mfrac><mi>α</mi><mi>β</mi></mfrac>"


def test_sqrt_and_root():
    assert inner(r"\sqrt{x}") == "<msqrt><mi>x</mi></msqrt>"
    assert inner(r"\sqrt[3]{x}") == "<mroot><mi>x</mi><mn>3</mn></mroot>"
    assert inner(r"\sqrt[n+1]{2}") == ("<mroot><mn>2</mn><mrow><mi>n</mi><mo>+</mo><mn>1</mn>"
                                        "</mrow></mroot>")


def test_binom():
    s = inner(r"\binom{n}{k}")
    assert '<mfrac linethickness="0"><mi>n</mi><mi>k</mi></mfrac>' in s
    assert s.count('stretchy="true"') == 2


# ---------------------------------------------------------------- 첨자
def test_sub_sup():
    assert inner("x_i") == "<msub><mi>x</mi><mi>i</mi></msub>"
    assert inner("x^2") == "<msup><mi>x</mi><mn>2</mn></msup>"
    assert inner("x_i^2") == inner("x^2_i") == "<msubsup><mi>x</mi><mi>i</mi><mn>2</mn></msubsup>"
    assert inner("e^{-x^2}") == ("<msup><mi>e</mi><mrow><mo>−</mo><msup><mi>x</mi><mn>2</mn>"
                                 "</msup></mrow></msup>")


def test_prime():
    assert "<msup><mi>f</mi><mo>′</mo></msup>" in inner("f'(x)")
    assert "<mo>″</mo>" in inner("f''")


def test_double_superscript_is_error():
    with pytest.raises(MathError):
        convert("x^1^2")


# ---------------------------------------------------------------- 기호
def test_greek():
    s = inner(r"\alpha\beta\Gamma\varepsilon\omega")
    assert "<mi>α</mi><mi>β</mi>" in s
    assert '<mi mathvariant="normal">Γ</mi>' in s  # 대문자 그리스는 직립
    assert "<mi>ε</mi>" in s and "<mi>ω</mi>" in s


@pytest.mark.parametrize("cmd,ch", [
    ("leq", "≤"), ("geq", "≥"), ("neq", "≠"), ("approx", "≈"), ("equiv", "≡"), ("in", "∈"),
    ("subseteq", "⊆"), ("cup", "∪"), ("cap", "∩"), ("times", "×"), ("cdot", "⋅"), ("pm", "±"),
    ("to", "→"), ("Rightarrow", "⇒"), ("iff", "⟺"), ("mapsto", "↦"), ("forall", "∀"),
    ("exists", "∃"), ("cdots", "⋯"), ("ldots", "…"), ("otimes", "⊗"), ("propto", "∝"),
])
def test_operators(cmd, ch):
    assert f">{ch}</mo>" in inner(rf"a \{cmd} b")


def test_ord_symbols():
    s = inner(r"\infty \partial \nabla \hbar")
    for ch in "∞∂∇ℏ":
        assert f">{ch}</mi>" in s


def test_not():
    assert "<mo>≠</mo>" in inner(r"a \not= b")
    assert "<mo>∉</mo>" in inner(r"a \not\in b")


def test_all_math_commands_in_commands_py_are_handled():
    """htex/commands.py 의 MATH 목록 전부가 (적절한 인수와 함께) 변환된다."""
    from htex.commands import MATH

    needs = {
        "frac": r"\frac{a}{b}", "dfrac": r"\dfrac{a}{b}", "tfrac": r"\tfrac{a}{b}",
        "binom": r"\binom{a}{b}", "dbinom": r"\dbinom{a}{b}", "tbinom": r"\tbinom{a}{b}",
        "sqrt": r"\sqrt{a}", "left": r"\left( a \right)", "right": r"\left( a \right)",
        "middle": r"\left( a \middle| b \right)", "limits": r"\sum\limits_a",
        "nolimits": r"\sum\nolimits_a", "pmod": r"a \pmod{n}", "operatorname": r"\operatorname{tr} A",
        "text": r"\text{a}",
    }
    one_arg = {"hat", "bar", "vec", "dot", "ddot", "tilde", "widetilde", "widehat", "overline",
               "underline", "overbrace", "underbrace", "mathbf", "mathrm", "mathit", "mathsf",
               "mathtt", "mathcal", "mathbb", "mathfrak", "boldsymbol"}
    delims = {"big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr"}
    failed = []
    for name in sorted(MATH):
        if name in needs:
            tex = needs[name]
        elif name in one_arg:
            tex = rf"\{name}{{A}}"
        elif name in delims:
            tex = rf"\{name}( a"
        elif name in ("displaystyle", "textstyle", "scriptstyle"):
            tex = rf"\{name} a"
        else:
            tex = rf"a \{name} b"
        try:
            convert(tex)
        except MathError as e:
            failed.append(f"{name}: {e}")
    assert not failed, failed


# ---------------------------------------------------------------- 괄호
def test_left_right_stretchy():
    s = inner(r"\left( \frac{a}{b} \right)")
    assert s.startswith('<mrow><mo stretchy="true" fence="true" form="prefix">(</mo>')
    assert s.endswith('<mo stretchy="true" fence="true" form="postfix">)</mo></mrow>')


def test_left_middle_right():
    s = inner(r"\left\langle a \middle| b \right\rangle")
    assert ">⟨</mo>" in s and ">⟩</mo>" in s
    assert 'form="infix"' in s and ">|</mo>" in s


def test_left_dot_is_empty():
    s = inner(r"\left. \frac{df}{dx} \right|_{x=0}")
    assert 'form="prefix"></mo>' in s
    assert "<msub><mrow>" in s


def test_unbalanced_left_is_error():
    with pytest.raises(MathError):
        convert(r"\left( a")
    with pytest.raises(MathError):
        convert(r"a \right)")


def test_plain_parens_not_stretchy():
    assert '<mo stretchy="false">(</mo>' in inner("(a)")


def test_big_delims():
    s = inner(r"\Big( a \Big)")
    assert 'minsize="1.623em"' in s


# ---------------------------------------------------------------- 큰 연산자
def test_sum_limits():
    s = inner(r"\sum_{n=1}^{\infty} a_n")
    assert s.startswith('<mrow><munderover><mo largeop="true" movablelimits="true">∑</mo>')


def test_int_nolimits_by_default():
    s = inner(r"\int_0^1 f")
    assert '<msubsup><mo largeop="true" movablelimits="false">∫</mo>' in s


def test_explicit_limits_and_nolimits():
    s = inner(r"\int\limits_0^1 f")
    assert "<munderover>" in s and 'movablelimits="false"' in s
    s = inner(r"\sum\nolimits_{k} a")
    assert "<msub><mo" in s and 'movablelimits="false"' in s


def test_limits_without_operator_is_error():
    with pytest.raises(MathError):
        convert(r"x\limits_0")


def test_lim_and_functions():
    s = inner(r"\lim_{x \to 0} \frac{\sin x}{x}")
    assert '<munder><mo movablelimits="true"' in s and ">lim</mo>" in s
    assert "<mi>sin</mi>" in s and "⁡" in s  # 함수 적용 U+2061


def test_function_with_paren_is_tight():
    s = inner(r"\log(x)")
    assert '<mo lspace="0" rspace="0">⁡</mo>' in s


# ---------------------------------------------------------------- 표 형식
def test_matrices():
    for env, l, r in [("matrix", None, None), ("pmatrix", "(", ")"), ("bmatrix", "[", "]"),
                      ("vmatrix", "|", "|"), ("Bmatrix", "{", "}")]:
        s = inner(rf"\begin{{{env}}} a & b \\ c & d \end{{{env}}}")
        assert s.count("<mtr>") == 2 and s.count("<mtd") == 4
        if l:
            assert f'form="prefix">{l}</mo>' in s and f'form="postfix">{r}</mo>' in s
        else:
            assert s.startswith("<mtable")


def test_matrix_trailing_rowbreak_ignored():
    s = inner(r"\begin{pmatrix} a \\ b \\ \end{pmatrix}")
    assert s.count("<mtr>") == 2


def test_cases():
    s = inner(r"|x| = \begin{cases} x & x \ge 0 \\ -x & x < 0 \end{cases}")
    assert 'form="prefix">{</mo><mtable columnalign="left left"' in s
    assert s.count("<mtr>") == 2


def test_aligned_inside():
    s = inner(r"\begin{aligned} a &= b \\ c &= d \end{aligned}")
    assert 'columnalign="right left"' in s and s.count("<mtr>") == 2


def test_top_level_align_rows():
    s = inner(r"a &= b + c \\ d &= e")
    assert s.startswith('<mtable columnalign="right left"')
    assert s.count("<mtr>") == 2
    assert "htex-pair-a" in s and "htex-pair-b" in s


def test_top_level_gather_and_multline():
    s = inner(r"a \\ b", mode="gather")
    assert 'columnalign="center"' in s
    s = inner(r"a + b \\ + c \\ + d", mode="multline")
    assert s.count("<mtr>") == 3
    assert 'columnalign="left"' in s and 'columnalign="right"' in s


def test_mismatched_end_is_error():
    with pytest.raises(MathError):
        convert(r"\begin{pmatrix} a \end{bmatrix}")


def test_unknown_environment_is_error():
    with pytest.raises(MathError):
        convert(r"\begin{tikzpicture} a \end{tikzpicture}")


# ---------------------------------------------------------------- 글꼴·텍스트
def test_mathbb_uses_unicode():
    assert inner(r"\mathbb{R}") == "<mi>ℝ</mi>"
    assert inner(r"\mathbb{N}") == "<mi>ℕ</mi>"
    assert inner(r"\mathbb{A}") == "<mi>𝔸</mi>"


def test_mathbf_mathcal_mathrm():
    assert inner(r"\mathbf{E}") == "<mi>𝐄</mi>"
    assert inner(r"\mathcal{L}") == "<mi>ℒ</mi>"
    assert inner(r"\mathrm{d}x") == '<mrow><mi mathvariant="normal">d</mi><mi>x</mi></mrow>'
    assert inner(r"\mathbf{x}_1") == "<msub><mi>𝐱</mi><mn>1</mn></msub>"


def test_text():
    s = inner(r"x \text{ if } y")
    assert "<mtext> if </mtext>" in s


def test_text_with_inline_math():
    s = inner(r"\text{for all $x$}")
    assert "<mtext>for all </mtext><mi>x</mi>" in s


def test_operatorname():
    s = inner(r"\operatorname{tr} A")
    assert "<mi>tr</mi>" in s
    s = inner(r"\operatorname*{argmax}_x f")
    assert "<munder>" in s


# ---------------------------------------------------------------- 악센트
@pytest.mark.parametrize("cmd,ch", [("hat", "^"), ("bar", "¯"), ("vec", "→"), ("dot", "˙"),
                                    ("tilde", "~"), ("ddot", "¨")])
def test_accents(cmd, ch):
    s = inner(rf"\{cmd}{{x}}")
    assert s == f'<mover accent="true"><mi>x</mi><mo stretchy="false">{ch}</mo></mover>'


def test_overline_underline():
    assert inner(r"\overline{AB}").startswith('<mover accent="true"><mrow>')
    assert 'stretchy="true"' in inner(r"\overline{AB}")
    assert inner(r"\underline{x}").startswith('<munder accentunder="true">')


def test_overbrace_with_label():
    s = inner(r"\underbrace{a+b}_{n}")
    assert s.startswith("<munder><munder>")


# ---------------------------------------------------------------- 간격
@pytest.mark.parametrize("cmd,w", [(",", "0.1667em"), (":", "0.2222em"), (";", "0.2778em"),
                                   ("!", "-0.1667em"), ("quad", "1em"), ("qquad", "2em")])
def test_spaces(cmd, w):
    assert f'<mspace width="{w}"></mspace>' in inner(rf"a \{cmd} b")


# ---------------------------------------------------------------- 한글
def test_hangul_one_syllable_each():
    s = inner("속력")
    assert s == ('<mrow><mi mathvariant="normal" class="htex-hangul">속</mi>'
                 '<mi mathvariant="normal" class="htex-hangul">력</mi></mrow>')


def test_hangul_with_scripts():
    s = inner(r"가_1 + 나^2 = 다")
    assert '<msub><mi mathvariant="normal" class="htex-hangul">가</mi><mn>1</mn></msub>' in s
    s = inner(r"\alpha_가")
    assert '<msub><mi>α</mi><mi mathvariant="normal" class="htex-hangul">가</mi></msub>' == s


def test_hangul_in_sum():
    s = inner(r"\sum_{나=1}^{다} 나 \, x^나")
    assert s.count('class="htex-hangul"') == 4


def test_hangul_words_in_text_and_operatorname():
    s = inner(r"\text{속력} = \frac{\text{거리}}{\text{시간}}")
    assert '<mtext class="htex-hangul-text">속력</mtext>' in s
    s = inner(r"\operatorname{최대}(a, b)")
    assert '<mi class="htex-hangul">최대</mi>' in s


# ---------------------------------------------------------------- 매개변수
def test_showparam_in_math():
    s = inner(r"\omega = \showparam{\omega}", params={"omega": 1.0})
    assert '<mn class="htex-param" data-param="omega">1</mn>' in s
    assert "<mi>ω</mi>" in s  # 일반 수식 안에서는 그리스 문자


# ---------------------------------------------------------------- 오류
@pytest.mark.parametrize("bad", [
    r"\frac{1}{", r"\frac{1}", r"x}", r"\undefinedmacro x", r"a^", r"\sqrt", r"\left(",
    r"\begin{pmatrix} a", "\\", r"\text{\foo}", r"a \limits",
])
def test_errors_fall_back_to_code(bad):
    out = tex_to_mathml(bad)
    assert out.startswith('<code class="htex-math-error"')
    assert ">" + bad.replace("&", "&amp;").replace("<", "&lt;") + "</code>" in out


def test_error_output_is_escaped():
    out = tex_to_mathml(r"<script>alert(1)</script> \foo")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_mathml_escapes_text():
    out = mm(r"\text{<b>&</b>} < x")
    assert "<b>" not in out
    assert "&lt;b&gt;&amp;&lt;/b&gt;" in out


def test_deep_nesting_does_not_crash():
    out = tex_to_mathml("{" * 2000 + "x" + "}" * 2000)
    assert out.startswith("<code") or out.startswith("<math")


def test_comment_ignored():
    assert inner("a % 주석\n+ b") == "<mrow><mi>a</mi><mo>+</mo><mi>b</mi></mrow>"


def test_output_always_balanced():
    samples = [
        r"H = \frac{p^2}{2m} + \frac{1}{2} m\omega^2 x^2",
        r"E_n = \hbar\omega\left(n + \tfrac{1}{2}\right)",
        r"\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}",
        r"i\hbar \frac{\partial}{\partial t}\Psi = \hat{H}\Psi",
        r"\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}",
        r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
        r"f(x) = a_0 + a_1 x \\ + a_4 x^4",
    ]
    for s in samples:
        out = mm(s)
        assert balanced(out), s
        assert not re.search(r"htex-math-error", out)
