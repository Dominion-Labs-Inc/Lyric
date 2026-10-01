"""Symbolic mathematics faculty — a real CAS the substrate owns.

Deterministic symbolic algebra via SymPy: simplify, expand, factor,
differentiate, integrate, solve, limit, series. Every result here is
COMPUTED by the computer-algebra system, never generated as text by a
model. The faculty also emits the SymPy code that reproduces the
computation, so a caller that asks for code receives a faithful
serialization of a real run rather than a guess.

This is not a solver-of-last-resort: an operation the CAS cannot carry out
returns an honest error, never a fabricated answer.

READ BY THE RULES OF MATHEMATICS' WRITING, NEVER AS CODE. A formula reaches
the algebra system through `arithmetic_reading.read_formula`, which builds its
tree token by token; SymPy's own text parser evaluates the text it is given as
Python, and is not used on anything written to the substrate.

WORKED, NOT ONLY ANSWERED (`calculate`, `solve`, `break_down`). Beside the
single operations stand the ones a person asks for when they ask about a
formula: what it comes to, what makes it true, and what it is made of, each
with the steps that get there in the order a person would take them, and the
answer checked by putting it back. Numbers are exact at any size: a trillion
times a trillion is 10^24, not a float.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import sympy as sp

from core.reasoning.arithmetic_reading import (
    CONSTANT, DERIVATIVE, DIFFERENCE, FACTORIAL, FUNCTION, INTEGRAL, LIMIT, NEGATIVE, NUMBER, PERCENT, POWER,
    PRODUCT, QUOTIENT, REMAINDER, SUM, SYMBOL, Formula, Term, read_formula, render,
)

#: Operations the faculty supports, each backed by a real SymPy call.
OPERATIONS = (
    "simplify", "expand", "factor",
    "differentiate", "integrate",
    "solve", "limit", "series",
)


@dataclass
class SymbolicResult:
    operation: str
    expression: str
    variable: Optional[str]
    result: Optional[str] = None      # symbolic result rendered as a string
    numeric: Optional[str] = None     # numeric value, when the result is a number
    steps: List[str] = field(default_factory=list)
    code: Optional[str] = None        # SymPy code that reproduces the computation
    ok: bool = True
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "operation": self.operation,
            "expression": self.expression,
            "variable": self.variable,
            "result": self.result,
            "numeric": self.numeric,
            "steps": self.steps,
            "code": self.code,
            "ok": self.ok,
            "error": self.error,
        }


# ---- from a written formula to the algebra system, and back ----------------------------------------------------

def _log10(value):
    return sp.log(value, 10)


def _cube_root(value):
    # The cube root of -8 is -2, as a person means it, not the principal complex root.
    return sp.real_root(value, 3) if value.is_real else sp.cbrt(value)


_FUNCTIONS = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "cot": sp.cot, "sec": sp.sec, "csc": sp.csc,
    "arcsin": sp.asin, "asin": sp.asin, "arccos": sp.acos, "acos": sp.acos, "arctan": sp.atan, "atan": sp.atan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh, "exp": sp.exp, "sqrt": sp.sqrt, "cbrt": _cube_root,
    "abs": sp.Abs, "floor": sp.floor, "ceil": sp.ceiling, "ceiling": sp.ceiling, "sgn": sp.sign,
    "ln": sp.log, "log": _log10, "lg": _log10,
}
_MANY = {"max": sp.Max, "min": sp.Min, "gcd": sp.gcd, "lcm": sp.lcm}
_CONSTANTS = {"pi": sp.pi, "e": sp.E, "i": sp.I, "infinity": sp.oo}


def _symbol(name: str, real: bool) -> sp.Symbol:
    return sp.Symbol(name, real=True) if real else sp.Symbol(name)


def to_sympy(term: Term, *, real: bool = False) -> sp.Expr:
    """The algebra system's expression for a written term. `real` makes every letter a real number, which an
    inequality needs."""
    op, args = term.op, term.args
    if op == NUMBER:
        return sp.Rational(Decimal(term.text)) if "e" in term.text else sp.Rational(term.text)
    if op == SYMBOL:
        return _symbol(term.text, real)
    if op == CONSTANT:
        return _CONSTANTS[term.text]
    values = [to_sympy(a, real=real) for a in args] if op not in (DERIVATIVE, INTEGRAL, LIMIT) else []
    if op == SUM:
        return values[0] + values[1]
    if op == DIFFERENCE:
        return values[0] - values[1]
    if op == PRODUCT:
        return values[0] * values[1]
    if op == QUOTIENT:
        return values[0] / values[1]
    if op == REMAINDER:
        return sp.Mod(values[0], values[1])
    if op == POWER:
        return values[0] ** values[1]
    if op == NEGATIVE:
        return -values[0]
    if op == FACTORIAL:
        return sp.factorial(values[0])
    if op == PERCENT:
        return values[0] / 100
    if op == FUNCTION:
        if term.text in _MANY:
            return _MANY[term.text](*values)
        if term.text == "log" and len(values) == 2:
            return sp.log(values[0], values[1])
        return _FUNCTIONS[term.text](values[0])
    variable = _symbol(args[1].text, real)
    body = to_sympy(args[0], real=real)
    if op == DERIVATIVE:
        return sp.diff(body, variable)
    if op == INTEGRAL:
        if len(args) == 4:
            return sp.integrate(body, (variable, to_sympy(args[2], real=real), to_sympy(args[3], real=real)))
        return sp.integrate(body, variable)
    if op == LIMIT:
        return sp.limit(body, variable, to_sympy(args[2], real=real))
    raise ValueError(f"{op!r} is not a part of a formula")


_RELATIONS = {"=": sp.Eq, "≠": sp.Ne, "<": sp.Lt, ">": sp.Gt, "≤": sp.Le, "≥": sp.Ge}


def relations_of(formula: Formula, *, real: bool = False) -> List[sp.Basic]:
    """Each relation a formula states, between each side and the next: `0 < x ≤ 5` is 0 < x and x ≤ 5."""
    sides = [to_sympy(s, real=real) for s in formula.sides]
    return [_RELATIONS[r](sides[k], sides[k + 1], evaluate=False) for k, r in enumerate(formula.relations)]


def _number_term(value: sp.Rational) -> Term:
    if value.q == 1:
        return Term(NUMBER, (), str(value.p))
    return Term(NUMBER, (), f"{value.p}/{value.q}")


def term_of(value) -> Term:
    """A written term for what the algebra system holds, so an answer is written as a person writes it:
    `x^2 - 4`, `(x - 2)(x + 2)`, `-1 + √2`, never `x**2 - 4`."""
    value = sp.sympify(value)
    if value.is_Rational:
        return _number_term(value)
    if value.is_Float:
        text = format(Decimal(str(value)).normalize(), "f")
        return Term(NUMBER, (), text)
    if value is sp.pi:
        return Term(CONSTANT, (), "pi")
    if value is sp.E:
        return Term(CONSTANT, (), "e")
    if value is sp.I:
        return Term(CONSTANT, (), "i")
    if value is sp.oo:
        return Term(CONSTANT, (), "infinity")
    if value is sp.S.NegativeInfinity:
        return Term(NEGATIVE, (Term(CONSTANT, (), "infinity"),), "-")
    if value.is_Symbol:
        return Term(SYMBOL, (), value.name)
    if value.is_Add:
        parts = value.as_ordered_terms()
        if not value.free_symbols:
            # A number written as a sum, -1 + √2: its whole part first, as it is said.
            parts = sorted(parts, key=lambda p: 0 if p.is_Rational else 1)
        out = term_of(parts[0])
        for part in parts[1:]:
            if part.could_extract_minus_sign():
                out = Term(DIFFERENCE, (out, term_of(-part)), "-")
            else:
                out = Term(SUM, (out, term_of(part)), "+")
        return out
    if value.is_Mul:
        coefficient, rest = value.as_coeff_Mul()
        if coefficient.is_Rational and coefficient.is_negative and coefficient != -1 and coefficient.q == 1 \
                and rest != 1 and sp.fraction(rest)[1] == 1:
            return Term(PRODUCT, (_number_term(coefficient), term_of(rest)), "")
        if value.could_extract_minus_sign():
            inner = term_of(-value)
            return Term(NEGATIVE, (inner,), "-")
        numerator, denominator = sp.fraction(value)
        if denominator != 1:
            return Term(QUOTIENT, (term_of(numerator), term_of(denominator)), "/")
        factors = value.as_ordered_factors()
        out = term_of(factors[0])
        for factor in factors[1:]:
            out = Term(PRODUCT, (out, term_of(factor)), "")
        return out
    if value.is_Pow:
        base, exponent = value.args
        if exponent == sp.Rational(1, 2):
            return Term(FUNCTION, (term_of(base),), "sqrt")
        if exponent == sp.Rational(-1, 2):
            return Term(QUOTIENT, (Term(NUMBER, (), "1"), Term(FUNCTION, (term_of(base),), "sqrt")), "/")
        if exponent.is_Rational and exponent.is_negative:
            return Term(QUOTIENT, (Term(NUMBER, (), "1"), term_of(base ** -exponent)), "/")
        return Term(POWER, (term_of(base), term_of(exponent)), "^")
    if isinstance(value, sp.exp):
        return Term(POWER, (Term(CONSTANT, (), "e"), term_of(value.args[0])), "^")
    if isinstance(value, sp.factorial):
        return Term(FACTORIAL, (term_of(value.args[0]),), "!")
    if isinstance(value, sp.Mod):
        return Term(REMAINDER, tuple(term_of(a) for a in value.args), "mod")
    if isinstance(value, sp.Abs):
        return Term(FUNCTION, (term_of(value.args[0]),), "abs")
    if isinstance(value, sp.log):
        return Term(FUNCTION, (term_of(value.args[0]),), "ln")
    if isinstance(value, sp.Derivative):
        return Term(DERIVATIVE, (term_of(value.args[0]), term_of(value.args[1][0])), "d/d")
    if isinstance(value, sp.Integral):
        (variable, *bounds) = value.limits[0]
        return Term(INTEGRAL, (term_of(value.function), term_of(variable)) + tuple(term_of(b) for b in bounds),
                    "∫")
    if isinstance(value, sp.Function) or isinstance(value, (sp.Max, sp.Min)):
        name = {"asin": "arcsin", "acos": "arccos", "atan": "arctan", "ceiling": "ceil", "sign": "sgn"}.get(
            type(value).__name__.lower(), type(value).__name__.lower())
        return Term(FUNCTION, tuple(term_of(a) for a in value.args), name)
    raise ValueError(f"no written form for {type(value).__name__}")


def written(value) -> str:
    """What the algebra system holds, written as mathematics writes it; the system's own spelling only for a
    result with no written form here (a piecewise answer), which is still the result it computed."""
    try:
        return render(term_of(value))
    except (ValueError, TypeError, AttributeError):
        return sp.sstr(value)


def approximately(value, digits: int = 15) -> Optional[str]:
    """A decimal for a number whose exact form is not already one: 1/3, √2, π. None for a whole number or a
    decimal that ends, which say themselves."""
    value = sp.sympify(value)
    if not getattr(value, "is_number", False) or value.has(sp.zoo, sp.nan) or value.is_infinite:
        return None
    if value.is_Integer:
        return None
    if value.is_Rational and _as_decimal(value) is not None:
        return _as_decimal(value)
    if value.is_real is False:
        re_exact, im_exact = value.as_real_imag()
        if re_exact.is_Rational and im_exact.is_Rational:
            return None
    number = sp.N(value, digits)
    if number.is_real is False and not number.is_real:
        re_part, im_part = number.as_real_imag()
        return f"{_decimal(re_part)} {'+' if im_part >= 0 else '-'} {_decimal(abs(im_part))}i"
    return _decimal(number)


def _decimal(number) -> str:
    text = format(Decimal(str(sp.Float(number, 15))).normalize(), "f")
    return text


def _as_decimal(value) -> Optional[str]:
    """A rational whose decimal ends, written as that decimal: 7/2 as 3.5."""
    value = sp.sympify(value)
    if not value.is_Rational or value.is_Integer:
        return None
    q = value.q
    while q % 2 == 0:
        q //= 2
    while q % 5 == 0:
        q //= 5
    return format(Decimal(value.p) / Decimal(value.q), "f") if q == 1 else None


# ---- what the faculty did, and how -------------------------------------------------------------------------------

@dataclass
class Worked:
    """A formula worked: what was asked of it, the answer, the steps that reach it in the order a person takes
    them, what the formula is made of, and the answer checked by putting it back."""

    task: str
    formula: str
    answer: List[str] = field(default_factory=list)
    approximate: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    parts: List[str] = field(default_factory=list)
    check: List[str] = field(default_factory=list)
    values: Dict[str, List[sp.Basic]] = field(default_factory=dict)
    exact: Optional[sp.Basic] = None
    #: For a relation checked and found false, what its first side really comes to, written: `2 + 2 = 5` is
    #: false, and 2 + 2 is 4.
    correction: Optional[str] = None
    #: That, written as the first side equal to what it comes to: `2 + 2 = 4`.
    corrected: Optional[str] = None
    #: Whether the decimal given beside the answer is the answer exactly (7/2 = 3.5), not near it (22/7 ≈ 3.142857).
    exactly: bool = False
    ok: bool = True
    error: Optional[str] = None

    def lines(self) -> List[str]:
        """Everything worked, in the order it is said: what it is made of, the steps, the answer, the check."""
        out = list(self.parts) + list(self.steps)
        if self.answer:
            out.append("Answer: " + "; ".join(self.answer)
                       + (f" ({', '.join(self.approximate)})" if self.approximate else ""))
        return out + list(self.check)


def _failed(task: str, formula: str, error: str) -> Worked:
    return Worked(task=task, formula=formula, ok=False, error=error)


def _formula(text_or_formula) -> Optional[Formula]:
    """A formula given to be worked: here letters written together multiply, `xy` as x times y."""
    return (text_or_formula if isinstance(text_or_formula, Formula)
            else read_formula(str(text_or_formula), letters_multiply=True))


def _had_decimals(formula: Formula) -> bool:
    return any(leaf.op == NUMBER and "." in leaf.text for side in formula.sides for leaf in side.leaves())


def _shown(value, decimals: bool) -> str:
    """Written, with every fraction whose decimal ends written as that decimal when the formula was written in
    decimals: 0.5x = 1.75, not x / 2 = 7/4."""
    value = sp.sympify(value)
    if decimals:
        swaps = {r: sp.Float(_as_decimal(r)) for r in value.atoms(sp.Rational) if _as_decimal(r)}
        value = value.xreplace(swaps) if swaps else value
    return written(value)


def _value_text(value, decimals: bool) -> str:
    if decimals:
        as_decimal = _as_decimal(value)
        if as_decimal is not None:
            return as_decimal
    return written(value)


# ---- calculating: the order of operations, one at a time ------------------------------------------------------

_READY = (SUM, DIFFERENCE, PRODUCT, QUOTIENT, POWER, NEGATIVE, FACTORIAL, PERCENT, FUNCTION, REMAINDER)


def _exact_number(term: Term) -> bool:
    """A value already written as a number: 12, -7, or a fraction of whole numbers, 1/3."""
    if term.op == NUMBER:
        return True
    if term.op == NEGATIVE:
        return _exact_number(term.args[0])
    return term.op == QUOTIENT and all(a.op == NUMBER and a.text.isdigit() for a in term.args) \
        and int(term.args[1].text) != 0 and int(term.args[0].text) % int(term.args[1].text) != 0


def _next_step(term: Term) -> Optional[Tuple[Term, ...]]:
    """The path to the operation done next: the leftmost one whose parts are all numbers already. The tree
    holds the brackets and the precedence, so the leftmost ready operation is the one the order of operations
    does first."""
    for k, arg in enumerate(term.args):
        inner = _next_step(arg)
        if inner is not None:
            return (term,) + inner
    if term.op in _READY and term.args and all(_exact_number(a) for a in term.args) and not _exact_number(term):
        return (term,)
    return None


def _replaced(term: Term, target: Term, value: Term) -> Term:
    if term is target:
        return value
    return Term(term.op, tuple(_replaced(a, target, value) for a in term.args), term.text)


def _evaluation_steps(term: Term, decimals: bool) -> Tuple[List[str], Term]:
    steps: List[str] = []
    current = term
    for _ in range(500):
        path = _next_step(current)
        if path is None:
            break
        node = path[-1]
        try:
            value = sp.nsimplify(to_sympy(node)) if node.op == PERCENT else to_sympy(node)
        except (ValueError, ZeroDivisionError, TypeError):
            break
        if value.has(sp.zoo, sp.nan) or not value.is_Rational:
            break
        as_decimal = _as_decimal(value)
        leaf = Term(NUMBER, (), (as_decimal if as_decimal and (decimals or node.op == PERCENT) else
                                  _number_term(value).text))
        steps.append(f"{render(node)} = {render(leaf)}")
        current = _replaced(current, node, leaf)
        if current.op == NUMBER:
            break
        steps[-1] += f", so it is {render(current)}"
    return steps, current


def _calculus_steps(term: Term) -> List[str]:
    """A derivative or an integral taken a term at a time, as a person takes it: each term of a sum on its own."""
    body, variable = term.args[0], term.args[1]
    x = sp.Symbol(variable.text)
    terms = _terms_of(body)
    if term.op == LIMIT:
        return [f"As {variable.text} approaches {render(term.args[2])}, {render(body)} approaches "
                f"{written(to_sympy(term))}"]
    steps: List[str] = []
    if len(terms) < 2:
        terms = []
    for sign, part in terms:
        value = to_sympy(part)
        if term.op == DERIVATIVE:
            steps.append(f"d/d{x}({render(part)}) = {written(sp.diff(value, x))}")
        elif len(term.args) == 2:
            steps.append(f"∫ {render(part)} d{x} = {written(sp.integrate(value, x))}")
    if len(term.args) == 4:
        antiderivative = sp.integrate(to_sympy(body), x)
        low, high = (to_sympy(b) for b in term.args[2:])
        steps.append(f"An antiderivative is {written(antiderivative)}; at {written(high)} it is "
                     f"{written(antiderivative.subs(x, high))} and at {written(low)} it is "
                     f"{written(antiderivative.subs(x, low))}, and the integral is the difference")
    return steps


def calculate(text_or_formula) -> Worked:
    """What an expression comes to, exactly, with each operation in the order of operations; or, for one
    with letters in it, the simplest form it takes."""
    formula = _formula(text_or_formula)
    if formula is None:
        return _failed("calculate", str(text_or_formula), "this is not written mathematics")
    if formula.relations:
        return check(formula)
    term = formula.sides[0]
    shown = render(term)
    decimals = _had_decimals(formula)
    try:
        value = (to_sympy(term) if term.op in (DERIVATIVE, INTEGRAL, LIMIT) or not term.unknowns()
                 else sp.simplify(to_sympy(term)))
    except (ValueError, TypeError, ZeroDivisionError, NotImplementedError) as error:
        return _failed("calculate", shown, f"the algebra system could not work it out: {error}")
    if value.has(sp.zoo) or value is sp.nan or value.has(sp.nan):
        return Worked(task="calculate", formula=shown, answer=["undefined"],
                      steps=["It divides by zero, which has no value."], exact=value)
    worked = Worked(task="calculate", formula=shown, exact=value)
    if term.op in (DERIVATIVE, INTEGRAL, LIMIT):
        worked.steps = _calculus_steps(term)
    elif not term.unknowns():
        worked.steps, _ = _evaluation_steps(term, decimals)
    elif written(value) != shown:
        worked.steps = [f"{shown} simplifies to {written(value)}"]
    worked.answer = [_value_text(value, decimals)]
    approx = approximately(value)
    if term.op == INTEGRAL and len(term.args) == 2:
        # An indefinite integral is every function whose derivative this is: one of them, plus any constant.
        worked.answer = [f"{worked.answer[0]} + C"]
    if approx is not None and approx != worked.answer[0]:
        worked.approximate = [approx]
        worked.exactly = _as_decimal(value) is not None
    return worked


def check(text_or_formula) -> Worked:
    """Whether a formula with no unknowns holds: `2 + 2 = 5` does not, `3 < 4` does."""
    formula = _formula(text_or_formula)
    if formula is None:
        return _failed("check", str(text_or_formula), "this is not written mathematics")
    if formula.unknowns():
        return solve(formula)
    shown = formula.render()
    sides = [to_sympy(s) for s in formula.sides]
    decimals = _had_decimals(formula)
    worked = Worked(task="check", formula=shown)
    for side, value in zip(formula.sides, sides):
        if side.args:
            steps, _ = _evaluation_steps(side, decimals)
            worked.steps.extend(steps)
    holds = all(bool(relation.doit()) for relation in relations_of(formula))
    if not holds and len(formula.sides) == 2:
        worked.steps.append(f"{_value_text(sides[0], decimals)} {formula.relations[0]} "
                            f"{_value_text(sides[1], decimals)} does not hold")
    if not holds and len(formula.sides) == 2 and formula.relations[0] == "=":
        worked.correction = _value_text(sides[0], decimals)
        worked.corrected = f"{render(formula.sides[0])} = {worked.correction}"
    worked.answer = ["true" if holds else "false"]
    worked.exact = sp.true if holds else sp.false
    return worked


# ---- solving ---------------------------------------------------------------------------------------------------

def _linear_steps(left: sp.Expr, right: sp.Expr, x: sp.Symbol, relation: str,
                  decimals: bool = False) -> Tuple[List[str], Optional[sp.Basic]]:
    """The steps a person takes with a first-degree equation or inequality in one unknown: multiply out the
    brackets, gather the unknown on the left and the numbers on the right, divide by what multiplies it."""
    steps: List[str] = []
    turned = {"<": ">", ">": "<", "≤": "≥", "≥": "≤"}

    def said(one, other, rel):
        return f"{_shown(one, decimals)} {rel} {_shown(other, decimals)}"

    def moved(amount) -> str:
        return (f"Add {_shown(-amount, decimals)} to both sides" if amount.could_extract_minus_sign()
                else f"Subtract {_shown(amount, decimals)} from both sides")

    expanded_left, expanded_right = sp.expand(left), sp.expand(right)
    if said(expanded_left, expanded_right, relation) != said(left, right, relation):
        steps.append(f"Multiply out: {said(expanded_left, expanded_right, relation)}")
    a, b = expanded_left.coeff(x, 1), expanded_left.coeff(x, 0)
    c, d = expanded_right.coeff(x, 1), expanded_right.coeff(x, 0)
    if c != 0:
        steps.append(f"{moved(c * x)}: {said((a - c) * x + b, d, relation)}")
        a, c = a - c, 0
    if b != 0:
        steps.append(f"{moved(b)}: {said(a * x, d - b, relation)}")
        d, b = d - b, 0
    if a == 0:
        holds = bool(_RELATIONS[relation](0, d))
        steps.append(f"The unknown is gone and {said(sp.S(0), d, relation)} is {'true' if holds else 'false'}, "
                     f"so {'every' if holds else 'no'} value of {x} makes it true")
        return steps, (sp.S.Reals if holds else sp.S.EmptySet)
    if a != 1:
        flip = relation in turned and a < 0
        new_relation = turned[relation] if flip else relation
        steps.append(f"Divide both sides by {_shown(a, decimals)}"
                     + (", which turns the inequality around because it is negative" if flip else "")
                     + f": {said(x, d / a, new_relation)}")
        relation = new_relation
    return steps, _RELATIONS[relation](x, d / a, evaluate=False)


def _polynomial_steps(expression: sp.Expr, x: sp.Symbol) -> Tuple[List[str], List[sp.Expr]]:
    """Steps for `expression = 0`, a polynomial in x of degree two or more: factor it and set each factor to
    zero; a quadratic that does not factor over the rationals by the formula."""
    steps: List[str] = []
    polynomial = sp.Poly(expression, x)
    factored = sp.factor(expression)
    factors = [f for f, _ in sp.factor_list(expression)[1]]
    if len(factors) > 1 or (factors and sp.Poly(factors[0], x).degree() < polynomial.degree()):
        steps.append(f"Factor: {written(factored)} = 0")
        steps.append("A product is 0 only when one of its factors is: "
                     + " or ".join(f"{written(f)} = 0" for f in factors))
        roots: List[sp.Expr] = []
        for factor in factors:
            roots.extend(r for r in sp.solve(factor, x) if r not in roots)
        return steps, _ordered(roots)
    if polynomial.degree() == 2:
        a, b, c = polynomial.all_coeffs()
        discriminant = sp.expand(b ** 2 - 4 * a * c)
        steps.append(f"It does not factor over the whole numbers, so use the quadratic formula "
                     f"x = (-b ± √(b^2 - 4ac)) / 2a with a = {written(a)}, b = {written(b)}, c = {written(c)}")
        steps.append(f"The discriminant b^2 - 4ac is {written(discriminant)}"
                     + (", which is negative, so the two solutions are complex" if discriminant < 0 else
                        ", which is 0, so the two solutions are one" if discriminant == 0 else ""))
        steps.append(f"x = ({written(-b)} ± √{_grouped_value(discriminant)}) / {written(2 * a)}")
        roots = [sp.together(sp.simplify((-b + sign * sp.sqrt(discriminant)) / (2 * a))) for sign in (-1, 1)]
        return steps, _ordered(list(dict.fromkeys(roots)))
    steps.append(f"It does not factor over the whole numbers; the algebra system finds its roots")
    return steps, sp.solve(expression, x)


def _ordered(roots: Sequence[sp.Expr]) -> List[sp.Expr]:
    """Real roots from least to greatest, then the complex ones."""
    real = [r for r in roots if r.is_real]
    rest = [r for r in roots if not r.is_real]
    return sorted(real, key=lambda r: float(sp.N(r))) + rest


def _grouped_value(value) -> str:
    text = written(value)
    return text if sp.sympify(value).is_Atom and not text.startswith("-") else f"({text})"


def _solution_text(x, roots: Sequence[sp.Expr], decimals: bool) -> Tuple[List[str], List[str]]:
    answer = [f"{x} = {_value_text(r, decimals)}" for r in roots]
    approx = [f"{x} ≈ {a}" for r, a in ((r, approximately(r)) for r in roots)
              if a is not None and a != _value_text(r, decimals)]
    return answer, approx


def _put_back(formula: Formula, assignment: Dict[sp.Symbol, sp.Expr], decimals: bool = False) -> str:
    relations = relations_of(formula)
    outcome = all(bool(sp.simplify(r.lhs.subs(assignment) - r.rhs.subs(assignment)) == 0)
                  if isinstance(r, sp.Eq) else bool(r.subs(assignment)) for r in relations)
    given = ", ".join(f"{k} = {_value_text(v, decimals)}" for k, v in assignment.items())
    sides = " and ".join(f"{render(side)} is {_value_text(sp.simplify(to_sympy(side).subs(assignment)), decimals)}"
                         for side in formula.sides if side.args or side.op == SYMBOL)
    return f"Check {given}: {sides}" + ("" if outcome else ", which does NOT hold")


def solve(text_or_formulas, unknowns: Optional[Sequence[str]] = None) -> Worked:
    """What makes one formula, or several at once, true: an equation's roots, an inequality's range, a system's
    common solution; each with the steps a person would take and every answer put back to check it."""
    formulas = [text_or_formulas] if isinstance(text_or_formulas, (str, Formula)) else list(text_or_formulas)
    read = [_formula(f) for f in formulas]
    shown = "; ".join(f.render() if f else str(t) for f, t in zip(read, formulas))
    if any(f is None for f in read):
        return _failed("solve", shown, "this is not written mathematics")
    if any(not f.relations for f in read):
        return _failed("solve", shown, "an expression with no = or < in it states nothing to make true")
    names: List[str] = list(unknowns or [])
    for f in read:
        names.extend(n for n in f.unknowns() if n not in names)
    if not names:
        return check(read[0]) if len(read) == 1 else _failed("solve", shown, "there is no unknown to find")
    decimals = any(_had_decimals(f) for f in read)
    inequality = any(r != "=" for f in read for r in f.relations)
    try:
        if inequality:
            return _solve_inequality(read, names, shown, decimals)
        if len(read) == 1 and len(read[0].relations) == 1 and len(names) == 1:
            return _solve_one(read[0], names[0], shown, decimals)
        return _solve_system(read, names, shown, decimals)
    except (NotImplementedError, ValueError, TypeError, sp.PolynomialError) as error:
        return _failed("solve", shown, f"the algebra system could not solve it: {error}")


def _solve_one(formula: Formula, name: str, shown: str, decimals: bool) -> Worked:
    """One equation in one unknown, solved the way its kind is solved: gathered and divided when it is of the
    first degree; factored, or by the quadratic formula, when it is a polynomial; squared when the unknown is
    under a root; the logarithm taken when it is in an exponent; brought over one denominator when it divides by
    the unknown. Every root is put back, and one that fails is said to be no solution."""
    x = sp.Symbol(name)
    left, right = (to_sympy(s) for s in formula.sides)
    worked = Worked(task="solve", formula=shown)
    steps, roots, done = _solving(left, right, x, decimals)
    worked.steps = steps
    if done is not None:
        worked.answer = [done]
        return worked
    if roots is None:
        general = sp.solveset(sp.Eq(left, right), x, sp.S.Reals)
        if isinstance(general, (sp.ImageSet, sp.Union)):
            worked.answer = [_general_solution(x, general)]
            worked.steps.append("It repeats: every solution is one of these plus a whole number of periods")
            return worked
        if general is sp.S.EmptySet and not sp.solveset(sp.Eq(left, right), x, sp.S.Complexes):
            worked.answer = [f"no value of {x}"]
            return worked
        numeric = _numeric_roots(left - right, x)
        if not numeric:
            return _failed("solve", shown, "the algebra system found no closed form and no root numerically")
        worked.steps.append("It has no solution written in closed form, so its roots are found numerically")
        worked.answer = [f"{x} ≈ {_decimal(r)}" for r in numeric]
        worked.values = {name: list(numeric)}
        worked.check = [f"Check {x} ≈ {_decimal(r)}: the two sides differ by less than 10^-9" for r in numeric]
        return worked
    kept, dropped = [], []
    for root in roots:
        (kept if _holds(left, right, x, root) else dropped).append(root)
    if dropped:
        worked.steps.append("Putting each back, " + " and ".join(f"{x} = {written(r)}" for r in dropped)
                            + (" does" if len(dropped) == 1 else " do") + " not solve the original equation, "
                            "so " + ("it is" if len(dropped) == 1 else "they are") + " no solution")
    roots = _ordered(kept)
    periodic = _periodic(left, right, x)
    if periodic is not None:
        worked.answer = [periodic]
        worked.steps.append("Within one period the solutions are "
                            + " and ".join(f"{x} = {written(r)}" for r in roots))
        worked.values = {name: roots}
        return worked
    worked.values = {name: roots}
    if not roots:
        worked.answer = [f"no value of {x}"]
        return worked
    worked.answer, worked.approximate = _solution_text(x, roots, decimals)
    if not any(r.is_real for r in roots):
        worked.steps.append("No real number solves it; its solutions are complex")
    worked.check = [_put_back(formula, {x: r}, decimals) for r in roots if r.is_real][:4]
    return worked


def _holds(left, right, x, root, assignment: Optional[Dict] = None) -> bool:
    difference = sp.simplify((left - right).subs(assignment if assignment is not None else {x: root}))
    if difference == 0:
        return True
    value = sp.N(difference)
    return bool(value.is_number and abs(value) < 1e-12)


def _periodic(left, right, x) -> Optional[str]:
    if not (left - right).has(sp.sin, sp.cos, sp.tan, sp.cot, sp.sec, sp.csc):
        return None
    general = sp.solveset(sp.Eq(left, right), x, sp.S.Reals)
    parts = general.args if isinstance(general, sp.Union) else (general,)
    if any(isinstance(p, sp.ImageSet) for p in parts):
        return _general_solution(x, general)
    return None


def _solving(left: sp.Expr, right: sp.Expr, x: sp.Symbol, decimals: bool
             ) -> Tuple[List[str], Optional[List[sp.Expr]], Optional[str]]:
    """(steps, roots, a whole answer when there are no roots to list). Roots None: no method here writes them in
    closed form, and the caller looks further."""
    steps: List[str] = []
    moved = sp.expand(left - right)
    if moved.is_polynomial(x) and moved.free_symbols <= {x}:
        degree = sp.Poly(moved, x).degree() if moved != 0 else 0
        if degree <= 1:
            steps, outcome = _linear_steps(left, right, x, "=", decimals)
            if outcome in (sp.S.Reals, sp.S.EmptySet):
                return steps, [], (f"every value of {x}" if outcome is sp.S.Reals else f"no value of {x}")
            return steps, [outcome.rhs], None
        if right != 0 or written(sp.expand(left)) != written(left):
            steps.append(f"Move every term to one side: {_shown(moved, decimals)} = 0")
        if sp.Poly(moved, x).LC() < 0:
            moved = -moved
            steps.append(f"Multiply both sides by -1: {_shown(moved, decimals)} = 0")
        more, roots = _polynomial_steps(moved, x)
        return steps + more, roots, None
    # The unknown under a square root, the root alone on one side: square both sides.
    for root_side, other in ((left, right), (right, left)):
        if isinstance(root_side, sp.Pow) and root_side.exp == sp.Rational(1, 2) and root_side.has(x):
            squared_left, squared_right = root_side.base, sp.expand(other ** 2)
            steps.append(f"Square both sides: {written(squared_left)} = {written(squared_right)}")
            more, roots, done = _solving(squared_left, squared_right, x, decimals)
            return steps + more, roots, done
    # The unknown in an exponent over a number: take that number's logarithm of both sides.
    for power_side, other in ((left, right), (right, left)):
        if isinstance(power_side, sp.Pow) and power_side.base.is_number and power_side.exp.has(x) \
                and other.is_number:
            base = power_side.base
            value = sp.simplify(sp.log(other, base))
            steps.append(f"Take the logarithm to base {written(base)} of both sides: "
                         f"{written(power_side.exp)} = log_{written(base)}({written(other)}) = {written(value)}")
            more, roots, done = _solving(power_side.exp, value, x, decimals)
            return steps + more, roots, done
    # The unknown in a denominator: over one denominator, a fraction is 0 where its top is and its bottom is not.
    together = sp.together(left - right)
    numerator, denominator = sp.fraction(together)
    if denominator.has(x) and sp.expand(numerator).is_polynomial(x):
        top = sp.expand(numerator)
        steps.append(f"Bring it over one denominator: ({written(top)}) / ({written(sp.factor(denominator))}) = 0")
        steps.append(f"A fraction is 0 where its top is 0 and its bottom is not, so solve {written(top)} = 0")
        more, roots, done = _solving(top, sp.S(0), x, decimals)
        if roots:
            roots = [r for r in roots if sp.simplify(denominator.subs(x, r)) != 0]
        return steps + more, roots, done
    try:
        roots = sp.solve(sp.Eq(left, right), x)
    except NotImplementedError:
        return steps, None, None
    if not roots:
        return steps, None, None
    return steps, [sp.nsimplify(r) if r.is_Float else r for r in roots], None


def _general_solution(x, solutions) -> str:
    parts = solutions.args if isinstance(solutions, sp.Union) else (solutions,)
    written_parts = []
    for part in parts:
        if isinstance(part, sp.ImageSet):
            n = part.lamda.variables[0]
            whole = sp.Symbol("n")
            written_parts.append(f"{x} = {written(part.lamda.expr.subs(n, whole))}")
        else:
            written_parts.extend(f"{x} = {written(v)}" for v in part)
    return " or ".join(written_parts) + ", for any whole number n"


def _numeric_roots(expression: sp.Expr, x: sp.Symbol) -> List[sp.Float]:
    """Roots of a real expression found numerically from a spread of starting points, each one kept only when
    putting it back gives zero."""
    found: List[sp.Float] = []
    for start in (0, 1, -1, 2, -2, 5, -5, 10, -10, 0.5, -0.5):
        try:
            root = sp.nsolve(expression, x, start)
        except (ValueError, ZeroDivisionError, TypeError):
            continue
        if not root.is_real or abs(sp.N(expression.subs(x, root))) > 1e-9:
            continue
        if all(abs(root - r) > 1e-9 for r in found):
            found.append(sp.Float(root, 15))
    return sorted(found)


def _solve_system(formulas: List[Formula], names: List[str], shown: str, decimals: bool) -> Worked:
    symbols = [sp.Symbol(n) for n in names]
    equations = [r for f in formulas for r in relations_of(f)]
    worked = Worked(task="solve", formula=shown)
    if len(equations) < len(symbols):
        # Fewer equations than unknowns: the first unknowns in terms of the rest.
        wanted = symbols[:len(equations)]
        found = sp.solve(equations, wanted, dict=True)
        if not found:
            worked.answer = ["no solution"]
            return worked
        worked.answer = ["; ".join(f"{k} = {written(v)}" for k, v in solution.items()) for solution in found]
        worked.steps.append(f"There are fewer equations than unknowns, so {', '.join(map(str, wanted))} "
                            f"{'is' if len(wanted) == 1 else 'are'} found in terms of the rest")
        worked.values = {str(k): [s[k] for s in found] for k in wanted}
        return worked
    worked_through = _substitution(equations, symbols, decimals)
    if worked_through is not None:
        worked.steps, found = worked_through
        found = [f for f in found if all(_holds(e.lhs, e.rhs, None, None, f) for e in equations)]
    else:
        worked.steps.append("No unknown stands alone to the first power, so the algebra system solves them together")
        found = sp.solve(equations, symbols, dict=True)
    if not found:
        worked.answer = ["no solution"]
        if not any("no values make every equation" in step for step in worked.steps):
            worked.steps.append("No values make every equation true at once")
        return worked
    worked.answer = ["; ".join(f"{k} = {_value_text(v, decimals)}" for k, v in solution.items())
                     for solution in found]
    worked.values = {str(k): [s[k] for s in found if k in s] for k in symbols}
    for solution in found[:2]:
        if all(v.is_real is not False for v in solution.values()):
            worked.check.extend(_put_back(f, solution, decimals) for f in formulas)
    return worked


def _substitution(equations: List[sp.Eq], symbols: List[sp.Symbol], decimals: bool
                  ) -> Optional[Tuple[List[str], List[Dict[sp.Symbol, sp.Expr]]]]:
    """Equations solved together by substitution, as a person does it: take an equation in which an unknown
    stands alone to the first power, write that unknown in terms of the others, put it into the rest, and repeat
    until one equation in one unknown is left; solve that one by its own kind, then work back. None when no
    unknown stands alone to the first power anywhere, which leaves the algebra system to it."""
    steps: List[str] = []
    pending = [(e.lhs, e.rhs) for e in equations]
    chain: List[Tuple[sp.Symbol, sp.Expr]] = []
    remaining = list(symbols)

    def unknown_in(pair) -> set:
        return (pair[0] - pair[1]).free_symbols & set(remaining)

    while pending and (len(pending) > 1 or len(unknown_in(pending[0])) > 1):
        best = None
        for k, (l, r) in enumerate(pending):
            expression = sp.expand(l - r)
            for x in remaining:
                if not expression.has(x) or not expression.is_polynomial(x) or sp.Poly(expression, x).degree() != 1:
                    continue
                coefficient = sp.Poly(expression, x).LC()
                if not coefficient.is_number:
                    continue
                score = (abs(coefficient) != 1, len(expression.free_symbols))
                if best is None or score < best[0]:
                    best = (score, k, x)
        if best is None:
            return None
        _, k, x = best
        l, r = pending.pop(k)
        value = sp.solve(sp.Eq(l, r), x)[0]
        steps.append(f"From {_shown(l, decimals)} = {_shown(r, decimals)}: {x} = {_shown(value, decimals)}")
        chain.append((x, value))
        remaining.remove(x)
        substituted = []
        for l2, r2 in pending:
            l3, r3 = sp.expand(l2.subs(x, value)), sp.expand(r2.subs(x, value))
            steps.append(f"Put {x} = {_shown(value, decimals)} into {_shown(l2, decimals)} = {_shown(r2, decimals)}: "
                         f"{_shown(l3, decimals)} = {_shown(r3, decimals)}")
            if not (l3 - r3).free_symbols:
                if sp.simplify(l3 - r3) != 0:
                    steps.append("That is false, so no values make every equation true at once")
                    return steps, []
                steps.append("That is always true, so that equation says nothing more")
                continue
            substituted.append((l3, r3))
        pending = substituted
    if not pending:
        # Every equation left said again what an earlier one said: the unknowns taken are fixed by the rest.
        free = [x for x in remaining]
        if not chain or not free:
            return None
        steps.append(f"The equations say the same thing, so "
                     + ", ".join(f"{x} = {_shown(v, decimals)}" for x, v in chain)
                     + f" for any {' and '.join(map(str, free))}")
        known: Dict[sp.Symbol, sp.Expr] = {}
        for x, value in reversed(chain):
            known[x] = sp.simplify(value.subs(known))
        return steps, [known]
    (l, r), = pending
    (y,) = unknown_in(pending[0])
    more, roots, done = _solving(l, r, y, decimals)
    steps.extend(more)
    if roots is None:
        return None
    solutions = []
    for root in _ordered(roots):
        known = {y: root}
        for x, value in reversed(chain):
            known[x] = sp.simplify(value.subs(known))
            if value.free_symbols:
                steps.append(f"Work back with {y} = {_shown(root, decimals)}: {x} = {_shown(value, decimals)} = "
                             f"{_shown(known[x], decimals)}")
        solutions.append({s: known[s] for s in symbols if s in known})
    return steps, solutions


def _solve_inequality(formulas: List[Formula], names: List[str], shown: str, decimals: bool) -> Worked:
    worked = Worked(task="solve", formula=shown)
    if len(names) != 1:
        return _failed("solve", shown, "inequalities are solved here in one unknown")
    x = sp.Symbol(names[0], real=True)
    relations = [r for f in formulas for r in relations_of(f, real=True)]
    if len(relations) == 1 and len(formulas) == 1:
        relation = relations[0]
        left, right = relation.lhs, relation.rhs
        moved = sp.expand(left - right)
        if moved.is_polynomial(x) and sp.Poly(moved, x).degree() == 1:
            worked.steps, outcome = _linear_steps(left, right, x, formulas[0].relations[0], decimals)
            worked.answer = [_relation_text(outcome) if outcome not in (sp.S.Reals, sp.S.EmptySet) else
                             (f"every value of {x}" if outcome is sp.S.Reals else f"no value of {x}")]
            return worked
    solution = sp.reduce_inequalities(relations, x)
    worked.answer = [_range_text(solution, x)]
    worked.steps.append("The algebra system finds where every inequality holds at once")
    return worked


def _range_text(solution, x) -> str:
    if solution is sp.true:
        return f"every value of {x}"
    if solution is sp.false:
        return f"no value of {x}"
    if isinstance(solution, sp.And):
        bounds = sorted(solution.args, key=lambda r: 0 if (r.rhs == x or r.lhs != x) else 1)
        low = [r for r in solution.args if r.rhs == x and r.lhs.is_number]
        high = [r for r in solution.args if r.lhs == x and r.rhs.is_number]
        if len(low) == 1 and len(high) == 1:
            return f"{written(low[0].lhs)} {_sign(low[0])} {x} {_sign(high[0])} {written(high[0].rhs)}"
        return " and ".join(_relation_text(r) for r in bounds)
    if isinstance(solution, sp.Or):
        return " or ".join(_range_text(part, x) for part in solution.args)
    return _relation_text(solution)


def _sign(relation) -> str:
    return {sp.StrictLessThan: "<", sp.LessThan: "≤", sp.StrictGreaterThan: ">", sp.GreaterThan: "≥",
            sp.Equality: "=", sp.Unequality: "≠"}[type(relation)]


def _relation_text(relation) -> str:
    if isinstance(relation, sp.Rel):
        left, right = relation.lhs, relation.rhs
        if right.is_Symbol and not left.is_Symbol:
            flipped = {"<": ">", ">": "<", "≤": "≥", "≥": "≤", "=": "=", "≠": "≠"}[_sign(relation)]
            return f"{written(right)} {flipped} {written(left)}"
        return f"{written(left)} {_sign(relation)} {written(right)}"
    return written(relation)


# ---- breaking a formula down ----------------------------------------------------------------------------------

_DEGREES = {1: "linear", 2: "quadratic", 3: "cubic", 4: "quartic", 5: "quintic"}
_FAMILIES = ((sp.sin, "trigonometric"), (sp.cos, "trigonometric"), (sp.tan, "trigonometric"),
             (sp.exp, "exponential"), (sp.log, "logarithmic"))


def _terms_of(term: Term) -> List[Tuple[str, Term]]:
    """The terms a side adds up, each with the sign it is written with: 3x^2 + 2x - 5 is +3x^2, +2x, -5."""
    if term.op == SUM:
        return _terms_of(term.args[0]) + [("+", term.args[1])]
    if term.op == DIFFERENCE:
        return _terms_of(term.args[0]) + [("-", term.args[1])]
    return [("+", term)]


def _kind_of(expression: sp.Expr, unknowns: Sequence[sp.Symbol]) -> str:
    if not unknowns:
        return "arithmetic"
    if expression.is_polynomial(*unknowns):
        degree = sp.Poly(expression, *unknowns).total_degree()
        return _DEGREES.get(degree, f"polynomial of degree {degree}") if degree > 0 else "constant"
    for function, family in _FAMILIES:
        if expression.has(function):
            return family
    numerator, denominator = sp.fraction(sp.together(expression))
    if denominator.free_symbols & set(unknowns):
        return "rational"
    if any(p.exp.is_Rational and not p.exp.is_Integer for p in expression.atoms(sp.Pow)):
        return "radical"
    return "algebraic"


def _describe_term(sign: str, term: Term) -> str:
    shown = ("-" if sign == "-" else "") + render(term)
    if term.op == PRODUCT and term.args[0].op == NUMBER:
        return f"{shown} ({term.args[0].text} times {render(term.args[1])})"
    if term.op == POWER:
        return f"{shown} ({render(term.args[0])} to the power {render(term.args[1])})"
    return shown


def break_down(text_or_formula) -> Worked:
    """What a formula is and what it is made of -- its sides, its terms, what multiplies what, what kind of
    formula it is -- and then worked: calculated when it has no unknown, solved when it relates sides."""
    formula = _formula(text_or_formula)
    if formula is None:
        return _failed("break down", str(text_or_formula), "this is not written mathematics")
    shown = formula.render()
    unknowns = [sp.Symbol(n) for n in formula.unknowns()]
    parts: List[str] = []
    whole = sum((to_sympy(s) for s in formula.sides), sp.S(0)) if formula.relations else to_sympy(formula.sides[0])
    moved = (to_sympy(formula.sides[0]) - to_sympy(formula.sides[1])) if formula.relations else whole
    kind = _kind_of(sp.expand(moved) if not moved.has(sp.Derivative, sp.Integral) else moved, unknowns)
    what = ("an equation" if formula.relations and set(formula.relations) == {"="} else
            "an inequality" if formula.relations else "an expression")
    top = formula.sides[0]
    if not formula.relations and top.op in (DERIVATIVE, INTEGRAL, LIMIT):
        body, variable = render(top.args[0]), top.args[1].text
        parts.append(f"{shown} is " + (
            f"the derivative of {body} with respect to {variable}" if top.op == DERIVATIVE else
            f"the integral of {body} with respect to {variable}"
            + (f", from {render(top.args[2])} to {render(top.args[3])}" if len(top.args) == 4 else "")
            if top.op == INTEGRAL else
            f"the limit of {body} as {variable} approaches {render(top.args[2])}"))
        worked = calculate(formula)
        worked.task, worked.parts = "break down", parts
        return worked
    about = f" in {', '.join(map(str, unknowns))}" if unknowns else ""
    noun = what.split(" ", 1)[1]
    parts.append(f"{shown} is {'an' if kind[0] in 'aeiou' else 'a'} {kind} {noun}{about}"
                 if kind != "algebraic" else f"{shown} is {what}{about}")
    if formula.relations:
        for side_name, side in (("left", formula.sides[0]), ("right", formula.sides[-1])):
            terms = _terms_of(side)
            listed = ", ".join(_describe_term(sign, t) for sign, t in terms)
            parts.append(f"Its {side_name} side, {render(side)}, "
                         + (f"has {len(terms)} terms: {listed}" if len(terms) > 1 else f"is {listed}"))
    else:
        terms = _terms_of(formula.sides[0])
        if len(terms) > 1:
            parts.append(f"It adds up {len(terms)} terms: "
                         + ", ".join(_describe_term(sign, t) for sign, t in terms))
        else:
            top = formula.sides[0]
            names = {PRODUCT: "a product", QUOTIENT: "a quotient", POWER: "a power", FUNCTION: "a function",
                     FACTORIAL: "a factorial", PERCENT: "a percentage", NEGATIVE: "a negative",
                     REMAINDER: "a remainder", DERIVATIVE: "a derivative", INTEGRAL: "an integral",
                     LIMIT: "a limit"}
            if top.op == FUNCTION:
                parts.append(f"It applies {top.text} to " + " and ".join(render(a) for a in top.args))
            elif top.op in names:
                parts.append(f"It is {names[top.op]} of " + " and ".join(render(a) for a in top.args))
    worked = (calculate(formula) if not formula.relations else
              check(formula) if not unknowns else solve(formula))
    worked.task = "break down"
    worked.parts = parts
    return worked


# ---- the single operations -----------------------------------------------------------------------------------

def _parse(expr_str: str):
    formula = read_formula(expr_str)
    if formula is None or formula.relations:
        raise ValueError("not an expression as mathematics writes it")
    return to_sympy(formula.sides[0])


def _resolve_var(expr, variable: Optional[str]):
    """Pick the symbol an operation acts on: given, or the lone free symbol."""
    if variable:
        return sp.Symbol(variable)
    free = sorted(expr.free_symbols, key=lambda s: s.name)
    if len(free) == 1:
        return free[0]
    return None


def _numeric(value) -> Optional[str]:
    """A numeric rendering when the result is a concrete number."""
    try:
        if getattr(value, "is_number", False):
            return str(sp.N(value))
    except Exception:
        return None
    return None


def _symbols_decl(expr) -> str:
    names = sorted({s.name for s in expr.free_symbols})
    if not names:
        return ""
    joined = ", ".join(names)
    return f"{joined} = sp.symbols('{' '.join(names)}')\n"


def compute(expression: str,
            operation: str,
            variable: Optional[str] = None,
            point: Optional[str] = None,
            order: int = 6) -> SymbolicResult:
    """Run one symbolic operation and return the CAS result plus reproducing code."""
    operation = (operation or "").strip().lower()
    res = SymbolicResult(operation=operation, expression=expression, variable=variable)

    if operation not in OPERATIONS:
        res.ok = False
        res.error = f"unsupported operation {operation!r}; supported: {', '.join(OPERATIONS)}"
        return res

    # ----- solve accepts an equation "lhs = rhs" as well as an expression -----
    try:
        if operation == "solve" and "=" in expression:
            lhs_str, rhs_str = expression.split("=", 1)
            lhs, rhs = _parse(lhs_str), _parse(rhs_str)
            target = sp.Eq(lhs, rhs)
            free_expr = lhs - rhs
        else:
            target = _parse(expression)
            free_expr = target
    except Exception as e:
        res.ok = False
        res.error = f"could not parse {expression!r}: {e}"
        return res

    # Operations that need a variable.
    needs_var = operation in ("differentiate", "integrate", "solve", "limit", "series")
    var = _resolve_var(free_expr, variable) if needs_var else None
    if needs_var and var is None:
        res.ok = False
        res.error = ("this operation needs a variable and the expression has "
                     f"{len(free_expr.free_symbols)} symbols; pass `variable`")
        return res
    res.variable = var.name if var is not None else variable

    try:
        if operation == "simplify":
            out = sp.simplify(target)
            call = "sp.simplify(expr)"
        elif operation == "expand":
            out = sp.expand(target)
            call = "sp.expand(expr)"
        elif operation == "factor":
            out = sp.factor(target)
            call = "sp.factor(expr)"
        elif operation == "differentiate":
            out = sp.diff(target, var)
            call = f"sp.diff(expr, {var})"
        elif operation == "integrate":
            out = sp.integrate(target, var)
            call = f"sp.integrate(expr, {var})"
        elif operation == "solve":
            out = sp.solve(target, var)
            call = f"sp.solve(expr, {var})"
        elif operation == "limit":
            pt = _parse(point) if point is not None and point != "oo" else sp.oo
            out = sp.limit(target, var, pt)
            call = f"sp.limit(expr, {var}, {sp.srepr(pt)})"
        elif operation == "series":
            pt = _parse(point) if point is not None else sp.Integer(0)
            out = sp.series(target, var, pt, order)
            call = f"sp.series(expr, {var}, {sp.srepr(pt)}, {order})"
        else:  # unreachable given the guard above
            raise RuntimeError(operation)
    except Exception as e:
        res.ok = False
        res.error = f"CAS could not perform {operation}: {e}"
        return res

    res.result = str(out)
    res.numeric = _numeric(out)

    # SymPy code that reproduces the run — a serialization of a real computation, written in SymPy's own
    # constructors (`srepr`), so it runs as Python whatever notation the formula was written in.
    res.code = (
        "import sympy as sp\n"
        "from sympy import *\n"
        + f"expr = {sp.srepr(target)}\n"
        + f"result = {call}\n"
        + "print(result)\n"
    )
    res.steps = [f"parsed: {target}", f"{operation} -> {out}"]
    return res


class SymbolicMath:
    """Object handle over the CAS faculty (mirrors the other reasoning faculties)."""

    OPERATIONS = OPERATIONS

    def compute(self, expression: str, operation: str, variable: Optional[str] = None,
                point: Optional[str] = None, order: int = 6) -> SymbolicResult:
        return compute(expression, operation, variable, point, order)

    def calculate(self, formula) -> Worked:
        return calculate(formula)

    def solve(self, formulas, unknowns: Optional[Sequence[str]] = None) -> Worked:
        return solve(formulas, unknowns)

    def check(self, formula) -> Worked:
        return check(formula)

    def break_down(self, formula) -> Worked:
        return break_down(formula)


_INSTANCE: Optional[SymbolicMath] = None


def get_symbolic_math() -> SymbolicMath:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SymbolicMath()
    return _INSTANCE


# ---- mathematics said in English -------------------------------------------------------------------------------
#
# A sentence about numbers is read, through what the substrate was taught, into facts: "What is two plus three?"
# asks for the ?v1 that EQUALS the sum whose augend is 2 and whose addend is 3; "Solve 2x + 3 = 7." asks the
# listener to solve, where 2x + 3 EQUALS 7. Those facts are a formula, and here they are worked as one.

#: The two places of each operation said in words, and the operation they make.
_PLACED = {("has_augend", "has_addend"): SUM, ("has_minuend", "has_subtrahend"): DIFFERENCE,
           ("has_multiplicand", "has_factor"): PRODUCT, ("has_dividend", "has_divisor"): QUOTIENT,
           ("has_base", "has_exponent"): POWER}
_PLACES = frozenset(p for pair in _PLACED for p in pair) | {"has_radicand", "has_index", "has_argument"}
#: Functions named in words, as the concept a lesson names them by.
_NAMED_FUNCTIONS = {"sine": "sin", "cosine": "cos", "tangent": "tan", "logarithm": "log",
                    "natural logarithm": "ln", "absolute value": "abs", "exponential": "exp"}
#: What a person asks to be done to a formula, as the event's concept, and the work it names.
ACTS = {"solve": "solve", "calculate": "calculate", "work out": "calculate", "evaluate": "calculate",
        "simplify": "simplify", "expand": "expand", "factor": "factor", "break down": "break down",
        "differentiate": "differentiate", "integrate": "integrate"}
#: Properties of a whole number that are decided, not looked up.
_NUMBER_PROPERTIES = {"prime", "even", "odd", "positive", "negative", "composite"}
_MATH_KINDS = _PLACES | {"equals"}


def _is_var(term: str) -> bool:
    return str(term).startswith("?")


class _Reading:
    """The facts of one meaning, as mathematics: which terms are numbers, formulas and unknowns, and what each
    operation said in words is made of."""

    def __init__(self, facts):
        self.facts = list(facts)
        self.by_subject: Dict[str, list] = {}
        for f in self.facts:
            self.by_subject.setdefault(f.subject, []).append(f)

    def kind_of(self, node: str) -> Optional[str]:
        return next((f.obj for f in self.by_subject.get(node, ()) if f.relation == "instance_of"), None)

    def term(self, name: str, seen: frozenset = frozenset()) -> Optional[Term]:
        """The written term a meaning's term stands for: a number, a formula, a letter for an unknown, or an
        operation said in words, built from its places; None for a thing that is not mathematics."""
        if name in seen:
            return None
        own = [f for f in self.by_subject.get(name, ()) if f.relation in _PLACES and f.positive]
        if own and _is_var(name):
            return self._operation(name, own, seen | {name})
        if _is_var(name):
            return None
        from core.semantics.literals import classify_literal
        literal = classify_literal(name)
        if literal is not None:
            if literal.kind == "expression":
                return literal.value
            if literal.kind in ("cardinal", "decimal"):
                return Term(NUMBER, (), literal.canonical) if not literal.canonical.startswith("-") else \
                    Term(NEGATIVE, (Term(NUMBER, (), literal.canonical[1:]),), "-")
            return None
        formula = read_formula(name)
        if formula is not None and not formula.relations:
            return formula.sides[0]
        return None

    def _operation(self, node: str, own, seen) -> Optional[Term]:
        places = {f.relation: f.obj for f in own}
        addends = [f.obj for f in own if f.relation == "has_addend"]
        factors = [f.obj for f in own if f.relation == "has_factor"]
        if "has_argument" in places:
            argument = self.term(places["has_argument"], seen)
            kind = self.kind_of(node)
            if argument is None or kind is None:
                return None
            if kind == "factorial":
                return Term(FACTORIAL, (argument,), "!")
            if kind in ("derivative", "integral"):
                unknowns = argument.unknowns()
                if not unknowns:
                    return None
                variable = Term(SYMBOL, (), unknowns[0])
                return Term(DERIVATIVE if kind == "derivative" else INTEGRAL, (argument, variable), kind)
            if kind in _NAMED_FUNCTIONS:
                return Term(FUNCTION, (argument,), _NAMED_FUNCTIONS[kind])
            return None
        if "has_radicand" in places:
            radicand = self.term(places["has_radicand"], seen)
            index = places.get("has_index", "2")
            if radicand is None:
                return None
            if index == "2":
                return Term(FUNCTION, (radicand,), "sqrt")
            if index == "3":
                return Term(FUNCTION, (radicand,), "cbrt")
            degree = self.term(index, seen)
            return Term(POWER, (radicand, Term(QUOTIENT, (Term(NUMBER, (), "1"), degree), "/")), "^") \
                if degree is not None else None
        for (first, second), op in _PLACED.items():
            if first in places:
                left = self.term(places[first], seen)
                rights = addends if op == SUM else factors if op == PRODUCT else [places.get(second)]
                if left is None or not rights or any(r is None for r in rights):
                    return None
                out = left
                for right in rights:
                    value = self.term(right, seen)
                    if value is None:
                        return None
                    out = Term(op, (out, value), {SUM: "+", DIFFERENCE: "-", PRODUCT: "×", QUOTIENT: "/",
                                                  POWER: "^"}[op])
                return out
        # A sum or a product said only by its parts: the numbers "twenty-one" is made of.
        for kind, parts, op in (("has_addend", addends, SUM), ("has_factor", factors, PRODUCT)):
            if len(parts) >= 2 and len(places) == 1:
                terms = [self.term(p, seen) for p in parts]
                if any(t is None for t in terms):
                    return None
                out = terms[0]
                for t in terms[1:]:
                    out = Term(op, (out, t), "+" if op == SUM else "×")
                return out
        return None

    def relation(self, f) -> Optional[Formula]:
        """A fact relating two numbers, as the formula that writes it: equals as =, exceeds as >, each denied
        as its opposite."""
        if f.relation not in ("equals", "exceeds"):
            return None
        left, right = self.term(f.subject), self.term(f.obj)
        if left is None or right is None:
            return None
        sign = ("=" if f.positive else "≠") if f.relation == "equals" else (">" if f.positive else "≤")
        return Formula((left, right), (sign,))


def mathematics_of(meaning, listeners: Sequence[str] = ("?listener",)) -> Optional[Worked]:
    """A meaning worked as mathematics, or None when it is not about numbers (`problem_of`)."""
    problem = problem_of(meaning, listeners)
    return problem() if problem is not None else None


def is_mathematics(meaning, listeners: Sequence[str] = ("?listener",)) -> bool:
    """Whether a meaning is about numbers in a way the faculty works, decided without working it."""
    return problem_of(meaning, listeners) is not None


def problem_of(meaning, listeners: Sequence[str] = ("?listener",)) -> Optional[Callable[[], Worked]]:
    """The work a meaning asks for when it is about numbers, ready to do; None when it is not.

    What is asked decides the work: a question for what something EQUALS is calculated, with what its condition
    says solved first ("What is x if 2x + 3 = 7?"); a yes/no question about numbers is checked; a request to the
    listener to solve, calculate, simplify, expand, factor, break down, differentiate or integrate is done."""
    facts = list(getattr(meaning, "facts", ()) or ())
    if not facts:
        return None
    reading = _Reading(facts)
    act = getattr(meaning, "act", "")
    asked = tuple(getattr(meaning, "asked", ()) or ())
    conditions = [f for f in facts if f.condition]
    stated = [f for f in facts if not f.condition]
    # What an "if" says: its relations between numbers, and the parts of the operations they relate.
    if any(f.relation not in ("equals", "exceeds") and not (_is_var(f.subject) and f.relation in _PLACES
                                                              | {"instance_of"}) for f in conditions):
        return None
    givens = [reading.relation(f) for f in conditions if f.relation in ("equals", "exceeds")]
    if any(g is None for g in givens):
        return None

    if act == "request":
        events = [f.subject for f in stated if f.relation == "instance_of" and f.obj in ACTS]
        if len(events) != 1:
            return None
        event = events[0]
        work = ACTS[reading.kind_of(event)]
        if not any(f.relation == "done_by" and f.subject == event and f.obj in listeners for f in stated):
            return None
        targets = [f.obj for f in stated if f.relation == "done_to" and f.subject == event]
        if work in ("solve", "break down") and givens:
            names = [n for n in (reading.term(t) for t in targets) if n is not None and n.op == SYMBOL]

            def solving() -> Worked:
                worked = solve(givens, [n.text for n in names] or None)
                if work == "break down":
                    worked.parts = [line for g in givens for line in break_down(g).parts]
                    worked.task = "break down"
                return worked
            return solving
        if len(targets) != 1:
            return None
        target = reading.term(targets[0])
        if target is None:
            return None
        formula = Formula((target,), ())
        if work == "calculate":
            return lambda: calculate(formula)
        if work == "break down":
            return lambda: break_down(formula)
        return lambda: _single(work, target)

    if act == "ask":
        if len(asked) == 1:
            wanted = asked[0]
            about = [f for f in stated if wanted in (f.subject, f.obj)]
            if len(about) != 1:
                return None
            (fact,) = about
            if fact.relation == "equals":
                target = reading.term(fact.obj if fact.subject == wanted else fact.subject)
                if target is None or (target.op == SYMBOL and not givens):
                    return None      # a letter alone, with nothing that fixes it, comes to nothing to work out
                return lambda: _value_given(target, givens)
            if fact.relation == "has_factor" and fact.subject != wanted:
                target = reading.term(fact.subject)
                return (lambda: _factors(target)) if target is not None else None
            return None
        if asked or not stated:
            return None
        relations = []
        for f in stated:
            if f.relation in ("equals", "exceeds"):
                formula = reading.relation(f)
                if formula is None:
                    return None
                relations.append(formula)
            elif f.relation == "has_property" and f.obj in _NUMBER_PROPERTIES and len(stated) == 1:
                target = reading.term(f.subject)
                return (lambda: _property(target, f.obj, f.positive)) if target is not None else None
            elif _is_var(f.subject) and f.relation in _PLACES | {"instance_of"}:
                continue            # the parts of an operation said in words
            else:
                return None
        if len(relations) != 1:
            return None
        (relation,) = relations
        if givens:
            return lambda: _checked_given(relation, givens)
        return (lambda: check(relation)) if not relation.unknowns() else None

    if act == "tell" and not conditions:
        # Told a relation between numbers: checked, never taken on the teller's word; told one with an unknown in
        # it, what it makes the unknown.
        relations = []
        for f in stated:
            if f.relation in ("equals", "exceeds"):
                formula = reading.relation(f)
                if formula is None:
                    return None
                relations.append(formula)
            elif not (_is_var(f.subject) and f.relation in _PLACES | {"instance_of"}):
                return None
        if not relations:
            return None
        if any(r.unknowns() for r in relations):
            return lambda: solve(relations)
        return (lambda: check(relations[0])) if len(relations) == 1 else None
    return None


def _value_given(target: Term, givens: List[Formula]) -> Worked:
    """What a term comes to; where it has unknowns and conditions fix them, the conditions solved first."""
    if not givens:
        return calculate(Formula((target,), ()))
    solved = solve(givens)
    if not solved.ok or not solved.values:
        return solved
    shown = render(target)
    values = {sp.Symbol(k): v for k, v in solved.values.items() if v}
    if any(len(v) != 1 for v in values.values()):
        # More than one solution: the term's value under each.
        results = []
        for k, roots in values.items():
            for root in roots:
                results.append(f"{shown} = {written(sp.simplify(to_sympy(target).subs(k, root)))}")
        solved.answer = results
        return solved
    assignment = {k: v[0] for k, v in values.items()}
    value = sp.simplify(to_sympy(target).subs(assignment))
    if target.op != SYMBOL:
        solved.steps.append(f"So {shown} = {written(value)}")
    solved.answer = [written(value)]
    solved.approximate = [a for a in [approximately(value)] if a]
    solved.exactly = _as_decimal(value) is not None
    solved.exact = value
    solved.task = "calculate"
    return solved


def _checked_given(relation: Formula, givens: List[Formula]) -> Worked:
    solved = solve(givens)
    if not solved.values or any(len(v) != 1 for v in solved.values.values()):
        return solved
    assignment = {sp.Symbol(k): v[0] for k, v in solved.values.items()}
    holds = all(bool(sp.simplify(r.lhs.subs(assignment) - r.rhs.subs(assignment)) == 0) if isinstance(r, sp.Eq)
                else bool(r.subs(assignment)) for r in relations_of(relation))
    solved.answer = ["true" if holds else "false"]
    solved.exact = sp.true if holds else sp.false
    solved.task = "check"
    return solved


def _single(work: str, target: Term) -> Worked:
    """One operation on an expression, with its result written as mathematics writes it."""
    shown = render(target)
    value = to_sympy(target)
    worked = Worked(task=work, formula=shown)
    unknowns = target.unknowns()
    try:
        if work == "simplify":
            out = sp.simplify(value)
        elif work == "expand":
            out = sp.expand(value)
            if value.is_Pow and value.exp.is_Integer and value.base.is_Add:
                worked.steps.append(f"{shown} is {render(target.args[0]) if target.op == POWER else shown} "
                                    f"multiplied by itself {value.exp} times")
        elif work == "factor":
            if not unknowns and value.is_Integer:
                return _prime_factors(value, shown)
            out = sp.factor(value)
            common = sp.factor_terms(value)
            if common != value and written(common) != written(out):
                worked.steps.append(f"Take out what every term shares: {written(common)}")
        elif work in ("differentiate", "integrate"):
            if not unknowns:
                return _failed(work, shown, "there is no unknown to do it with respect to")
            x = sp.Symbol(unknowns[0])
            op_term = Term(DERIVATIVE if work == "differentiate" else INTEGRAL, (target, Term(SYMBOL, (), x.name)))
            worked = calculate(Formula((op_term,), ()))
            worked.task = work
            return worked
        else:
            return _failed(work, shown, f"{work} is not something done here")
    except (NotImplementedError, ValueError, TypeError) as error:
        return _failed(work, shown, f"the algebra system could not {work} it: {error}")
    worked.answer = [written(out)]
    worked.exact = out
    if written(out) == shown:
        worked.steps.append(f"{shown} is already as {'simple' if work == 'simplify' else work + 'ed'} as it goes")
    return worked


def _prime_factors(value: sp.Integer, shown: str) -> Worked:
    """A whole number as the product of its primes, found by dividing out the smallest prime again and again."""
    worked = Worked(task="factor", formula=shown, exact=value)
    n = int(value)
    if abs(n) < 2:
        worked.answer = [str(n)]
        return worked
    remaining = abs(n)
    for prime, times in sorted(sp.factorint(remaining).items()):
        for _ in range(times):
            if remaining != prime:
                worked.steps.append(f"{_grouped_number(remaining)} = {prime} × {_grouped_number(remaining // prime)}")
            remaining //= prime
    parts = [f"{p}^{t}" if t > 1 else f"{p}" for p, t in sorted(sp.factorint(abs(n)).items())]
    worked.answer = [("-" if n < 0 else "") + " × ".join(parts)]
    return worked


def _grouped_number(n: int) -> str:
    return f"{n:,}" if abs(n) >= 10000 else str(n)


def _factors(target: Term) -> Worked:
    """The factors of a whole number (every number it divides by) or of an expression (what it factors into)."""
    shown = render(target)
    value = to_sympy(target)
    worked = Worked(task="factor", formula=shown, exact=value)
    if not target.unknowns() and value.is_Integer:
        divisors = sp.divisors(abs(int(value)))
        worked.answer = [", ".join(_grouped_number(d) for d in divisors)]
        worked.steps.append(f"{shown} divides evenly by each of them, and by nothing else")
        return worked
    factors = [f for f, _ in sp.factor_list(value)[1]]
    worked.answer = [", ".join(written(f) for f in factors)]
    worked.steps.append(f"{shown} = {written(sp.factor(value))}")
    return worked


def _property(target: Term, prop: str, positive: bool) -> Optional[Worked]:
    value = to_sympy(target)
    shown = render(target)
    if not value.is_number:
        return None
    worked = Worked(task="check", formula=f"{shown} is {prop}")
    if prop in ("prime", "composite", "even", "odd") and not value.is_Integer:
        worked.answer = ["false"]
        worked.steps.append(f"{shown} is not a whole number")
        return worked
    holds = {"prime": lambda v: sp.isprime(v), "composite": lambda v: v > 1 and not sp.isprime(v),
             "even": lambda v: v % 2 == 0, "odd": lambda v: v % 2 == 1,
             "positive": lambda v: v > 0, "negative": lambda v: v < 0}[prop](value)
    holds = bool(holds) == positive
    if prop in ("prime", "composite") and value.is_Integer and value > 1 and not sp.isprime(value):
        smallest = min(sp.factorint(int(value)))
        worked.steps.append(f"{shown} = {smallest} × {int(value) // smallest}")
    elif prop == "prime" and value.is_Integer and sp.isprime(value):
        worked.steps.append(f"{shown} divides evenly only by 1 and by itself")
    worked.answer = ["true" if holds else "false"]
    worked.exact = sp.true if holds else sp.false
    return worked
