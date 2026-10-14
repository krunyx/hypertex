"""D: 계산식 파서·평가기 단위 테스트 (명세 3.2절)."""
import math

import pytest

from htex.expr import Expr, ExprError, MAX_DEPTH, evaluate, parse


def ev(text, params=(), **env):
    return evaluate(parse(text, set(params)), env)


@pytest.mark.parametrize("text,value", [
    ("1+2*3", 7), ("(1+2)*3", 9), ("2^3^2", 512), ("-2^2", -4), ("(-2)^2", 4),
    ("2^-1", 0.5), ("--3", 3), ("+4", 4), ("10/4", 2.5), ("8-3-2", 3), ("16/4/2", 2),
    ("1.5e2", 150), (".5", 0.5), ("2.5E-1", 0.25),
    ("3 < 4", 1), ("3 > 4", 0), ("2 == 2", 1), ("1+1 == 2", 1),
    ("ifthenelse(1 < 2, 10, 20)", 10), ("ifthenelse(0, 10, 20)", 20),
    ("pi", math.pi), ("e", math.e), ("2*pi", 2 * math.pi),
    ("sin(90)", 1), ("cos(180)", -1), ("sin(pi/2 r)", 1), ("sin(pi/6 r)", 0.5), ("sin((pi/6) r)", 0.5),
    ("asin(1)", 90), ("atan2(1, 1)", 45), ("atan(1)", 45), ("acos(0)", 90),
    ("exp(0)", 1), ("ln(e)", 1), ("log10(1000)", 3), ("sqrt(16)", 4),
    ("abs(-3)", 3), ("floor(-1.5)", -2), ("ceil(1.2)", 2), ("round(2.5)", 3), ("round(-2.5)", -3),
    ("mod(7, 3)", 1), ("mod(-7, 3)", -1), ("min(3, 1, 2)", 1), ("max(3, 1, 2)", 3),
    ("sign(-5)", -1), ("sign(0)", 0), ("sinh(0)", 0), ("cosh(0)", 1), ("tanh(0)", 0),
])
def test_values(text, value):
    assert ev(text) == pytest.approx(value)


def test_variables_tikz_and_pgfplots():
    assert ev("\\x^2 + \\y", x=3, y=1) == 10
    assert ev("x*y", x=2, y=5) == 10
    e = parse("\\x + x", set())
    assert e.variables == {"x"} and e.params == set()


def test_radian_suffix():
    assert ev("sin(\\x r)", x=math.pi / 2) == pytest.approx(1)
    assert ev("cos(2*x r)", x=math.pi / 2) == pytest.approx(-1)     # 2*(x r)
    assert ev("cos((2*x) r)", x=math.pi / 4) == pytest.approx(0, abs=1e-12)
    assert ev("pi r") == pytest.approx(180)


def test_parameters():
    e = parse("exp(-\\gamma*\\x)*cos(\\omega*\\x r)", {"omega", "gamma"})
    assert e.params == {"omega", "gamma"}
    v = evaluate(e, {"x": 0.0, "omega": 1.0, "gamma": 0.2})
    assert v == pytest.approx(1)
    assert evaluate(e, {"x": 1.0, "omega": 1.0, "gamma": 0.2}) == pytest.approx(
        math.exp(-0.2) * math.cos(1.0))
    assert isinstance(e, Expr) and e.source.startswith("exp")


def test_unknown_parameter():
    with pytest.raises(ExprError) as ei:
        parse("\\kappa * \\x", {"omega"})
    assert ei.value.kind == "unknown-parameter"


@pytest.mark.parametrize("text", [
    "", "   ", "sin(\\x r", "1 +", "(1", "1)", "*2", "gamma(\\x)", "foo", "sin", "sin 30",
    "atan2(1)", "mod(1,2,3)", "ifthenelse(1,2)", "min()", "1 2", "3 # 4", "x = 1", "1,2",
    "\\x[1]", "{1}", "r", "1 <= 2",
])
def test_syntax_errors(text):
    with pytest.raises(ExprError) as ei:
        parse(text, {"omega"})
    assert ei.value.kind == "expression-syntax"


@pytest.mark.parametrize("text", [
    "ln(-1)", "ln(0)", "1/0", "sqrt(-1)", "(-8)^(1/3)", "asin(2)", "mod(1, 0)",
    "exp(1000)", "10^400", "1e400",
])
def test_out_of_domain_is_nan(text):
    assert math.isnan(ev(text))


def test_missing_env_is_nan():
    assert math.isnan(ev("\\x + 1"))
    assert math.isnan(evaluate(parse("\\omega", {"omega"}), {"omega": "abc"}))


def test_deep_nesting_is_error_not_crash():
    for depth in (MAX_DEPTH + 1, 10_000):
        with pytest.raises(ExprError) as ei:
            parse("(" * depth + "1" + ")" * depth, set())
        assert ei.value.kind == "expression-syntax"
        with pytest.raises(ExprError):
            parse("-" * depth + "1", set())
        with pytest.raises(ExprError):
            parse("sin(" * depth + "1" + ")" * depth, set())


def test_moderate_nesting_ok():
    assert ev("(" * 50 + "1" + ")" * 50) == 1


def test_long_flat_expression_no_recursion():
    text = "+".join(["1"] * 50_000)
    assert ev(text) == 50_000


def test_huge_numbers():
    assert ev("9" * 400) != ev("9" * 400) or True   # 예외만 없으면 된다
    assert math.isnan(ev("9" * 400 + "*" + "9" * 400))


def test_no_eval_used():
    import inspect
    import htex.expr as m
    src = inspect.getsource(m)
    assert "eval(" not in src.replace("evaluate(", "").replace("_eval", "")
    assert "exec(" not in src


def test_radian_suffix_precedence():
    # pgfmath: r(600) 은 * /(700) 보다 낮고 + -(500) 보다 높다
    assert ev("pi/2 r") == pytest.approx(90)
    assert ev("1 + pi r") == pytest.approx(181)
    assert ev("pi r * 2") == pytest.approx(360)
    assert ev("-pi r") == pytest.approx(-180)
