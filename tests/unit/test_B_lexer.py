"""B: lexer 단위 테스트."""
from htex.diagnostics import Sink
from htex.lexer import tokenize
from htex.tokens import T


def kinds(src):
    return [(t.type, t.text) for t in tokenize(src)]


def test_control_word_eats_space():
    assert kinds(r"\alpha  x") == [(T.CS, "alpha"), (T.CHAR, "x"), (T.EOF, "")]


def test_control_symbol_keeps_space():
    assert kinds(r"\, x")[:3] == [(T.CS, ","), (T.SPACE, " "), (T.CHAR, "x")]


def test_par_and_space():
    ts = kinds("a \n b\n\n  c")
    assert [k for k, _ in ts] == [T.CHAR, T.SPACE, T.CHAR, T.PAR, T.CHAR, T.EOF]


def test_cs_before_blank_line_keeps_par():
    assert [t.type for t in tokenize("\\foo\n\nx")] == [T.CS, T.PAR, T.CHAR, T.EOF]


def test_comment():
    assert kinds("a%c\n  b") == [(T.CHAR, "a"), (T.CHAR, "b"), (T.EOF, "")]


def test_comment_then_blank_line_is_par():
    assert [t.type for t in tokenize("a%c\n\nb")] == [T.CHAR, T.PAR, T.CHAR, T.EOF]


def test_params_and_specials():
    ts = kinds("#1#{}$&^_~")
    assert [k for k, _ in ts][:-1] == [T.PARAM, T.PARAM, T.BGROUP, T.EGROUP, T.MATH,
                                       T.ALIGN, T.SUP, T.SUB, T.TILDE]
    assert ts[0][1] == "1" and ts[1][1] == ""


def test_verb_and_verbatim():
    ts = tokenize("\\verb|\\x{|\n\\begin{verbatim}\n a\\b\n\\end{verbatim}")
    assert ts[0].type is T.VERB and ts[0].text == "\\x{"
    vb = [t for t in ts if t.type is T.VERBATIM]
    assert vb and vb[0].text == " a\\b"


def test_unclosed_verb_diagnostic():
    s = Sink()
    tokenize("\\verb|abc\n|", s)
    assert [d.code for d in s.items] == ["unbalanced-brace"]


def test_spans():
    ts = tokenize("ab\n\\c")
    assert ts[3].type is T.CS and (ts[3].span.line, ts[3].span.col) == (2, 1)


def test_never_raises_on_odd_input():
    for src in ["\\", "\\verb", "#", "%", "\\begin{verbatim}", "\r\n\r\n", ""]:
        assert tokenize(src)[-1].type is T.EOF
