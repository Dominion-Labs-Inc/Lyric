#!/usr/bin/env python3
"""Recognising a linear equation in text, so the solver can be reached without a model.

The substrate ships a working Z3 backend (`core/reasoning/constraint_solver.py`)
that answers `4x + 8 = 32` correctly, including negative roots. It was
UNREACHABLE without a language model: the only route to it ran through
`_neuro_symbolic_reasoning`, whose first phase is "NEURAL PROPOSES" -- so Z3
could check a model's answer but never produce one. "Lyric can do algebra" was
therefore a model-dependent claim, and severing Z3 would have changed nothing
because the model was doing the work.

This is the missing reading stage, and it is the same shape as genericity:
classify the surface form deterministically, then let the owner of that
capability answer. It does not solve anything itself.

THE GRAMMAR IS DELIBERATELY NARROW -- single variable, integer coefficients,
one occurrence of the variable. Anything else returns None and the request
continues to the ordinary path. A reader that guesses at an equation is worse
than one that declines, because a misread equation produces a confident wrong
number rather than a gap.

WRITTEN MATHEMATICS, WHOLE (`read_formula`, `read_expression`). Beside that
narrow reader stands one for any formula as mathematics writes it: numbers of
any size, letters for unknowns, + - × ÷ ^ and their ASCII spellings, brackets,
|x|, √, n!, n%, the functions (sin, log, ln, sqrt, ...), d/dx, ∫ ... dx, lim,
and the relations = ≠ < > ≤ ≥ between sides. Mathematics' notation is a
writing system with fixed rules of precedence, not English, so it is read by
its rules here, the way `literals` reads a date: nothing is learned or guessed,
and a form that breaks the rules is not a formula. What it reads is a `Term`
tree, as written; computing with it is the symbolic mathematics faculty's.
NOTHING HERE EVALUATES TEXT AS CODE: the tree is built token by token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

#: `[label:] [a]x [+|- b] = c`, with optional whitespace and an optional
#: leading instruction such as "Solve for x:".
_EQUATION = re.compile(
    r"^\s*(?:[^:]*:)?\s*"
    r"(?P<coefficient>[+-]?\d+)?\s*\*?\s*(?P<variable>[a-z])\s*"
    r"(?:(?P<sign>[+-])\s*(?P<constant>\d+)\s*)?"
    r"=\s*(?P<target>[+-]?\d+)\s*$",
    re.IGNORECASE,
)


#: A question naming a run of numbers, e.g. "Next term in the sequence 5, 9, 13".
#: Deliberately requires an explicit cue word: a sentence that merely contains
#: several numbers is not a sequence question, and reading it as one would
#: answer questions nobody asked.
_SEQUENCE_CUE = re.compile(r"\b(sequence|series|next term|comes next)\b", re.IGNORECASE)
_NUMBERS = re.compile(r"-?\d+(?:\.\d+)?")
#: Below this many terms a rule cannot be evidenced -- one step is consistent
#: with infinitely many rules.
MINIMUM_SEQUENCE_TERMS = 3


@dataclass(frozen=True)
class SequenceQuestion:
    """A run of observed terms, and the request for what follows."""

    terms: List[float]
    surface: str

    def as_text(self) -> str:
        return ", ".join(str(int(t) if float(t).is_integer() else t) for t in self.terms)


@dataclass(frozen=True)
class LinearEquation:
    """`coefficient * variable + constant = target`."""

    variable: str
    coefficient: int
    constant: int
    target: int
    surface: str

    def as_text(self) -> str:
        sign = "+" if self.constant >= 0 else "-"
        return (f"{self.coefficient}{self.variable} {sign} {abs(self.constant)} "
                f"= {self.target}")


def read(text: str) -> Optional[LinearEquation]:
    """Read a linear equation, or None if the text is not one.

    None means "not an equation", never "an equation I could not solve" --
    solving is the constraint solver's job and its failures are its own.
    """
    if not text or "=" not in text:
        return None
    match = _EQUATION.match(str(text).strip().rstrip("?."))
    if not match:
        return None

    raw_coefficient = match.group("coefficient")
    coefficient = int(raw_coefficient) if raw_coefficient not in (None, "", "+") else 1
    if raw_coefficient == "-":
        coefficient = -1
    if coefficient == 0:
        return None

    constant = int(match.group("constant") or 0)
    if match.group("sign") == "-":
        constant = -constant

    return LinearEquation(
        variable=match.group("variable").lower(),
        coefficient=coefficient,
        constant=constant,
        target=int(match.group("target")),
        surface=str(text).strip(),
    )


def read_sequence(text: str) -> Optional[SequenceQuestion]:
    """Read a sequence question, or None if the text is not one.

    None means "not a sequence question", never "a sequence I could not
    extend" -- extending is the learning authority's job, and inducing nothing
    from three terms is a real answer it is entitled to give.
    """
    if not text or not _SEQUENCE_CUE.search(str(text)):
        return None
    terms = [float(n) for n in _NUMBERS.findall(str(text))]
    if len(terms) < MINIMUM_SEQUENCE_TERMS:
        return None
    return SequenceQuestion(terms=terms, surface=str(text).strip())


# ---- written mathematics ---------------------------------------------------------------------------------------

#: What a part of a formula is. A number, an unknown's letter, or a constant is a leaf; the rest are made of parts.
NUMBER, SYMBOL, CONSTANT = "number", "symbol", "constant"
SUM, DIFFERENCE, PRODUCT, QUOTIENT, POWER = "sum", "difference", "product", "quotient", "power"
NEGATIVE, FACTORIAL, PERCENT, FUNCTION = "negative", "factorial", "percent", "function"
REMAINDER = "remainder"
DERIVATIVE, INTEGRAL, LIMIT = "derivative", "integral", "limit"

#: The relations one side of a formula may stand in to the next, each as mathematics writes it.
EQUALS, NOT_EQUAL, LESS, GREATER, AT_MOST, AT_LEAST = "=", "≠", "<", ">", "≤", "≥"
RELATIONS = (EQUALS, NOT_EQUAL, LESS, GREATER, AT_MOST, AT_LEAST)
_RELATION_SPELLINGS = {"=": EQUALS, "==": EQUALS, "≠": NOT_EQUAL, "!=": NOT_EQUAL, "<": LESS, ">": GREATER,
                       "≤": AT_MOST, "<=": AT_MOST, "≥": AT_LEAST, ">=": AT_LEAST}

#: The functions written by name. `log` is the logarithm to base 10 and `ln` the natural one, as a calculator
#: keys them; a base is written `log_2`.
FUNCTIONS = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "asin", "acos", "atan",
    "sinh", "cosh", "tanh", "log", "ln", "lg", "exp", "sqrt", "cbrt", "abs", "floor", "ceil", "ceiling",
    "max", "min", "gcd", "lcm", "sgn"})
#: Constants written by name or sign.
CONSTANTS = {"pi": "pi", "π": "pi", "e": "e", "i": "i", "∞": "infinity", "inf": "infinity", "infinity": "infinity"}
_NAMES = sorted(FUNCTIONS | {"pi", "inf", "infinity", "lim"}, key=len, reverse=True)

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_MARKS = {"+": "+", "-": "-", "−": "-", "–": "-", "*": "*", "×": "*", "·": "*", "⋅": "*", "/": "/", "÷": "/",
          "^": "^", "!": "!", "%": "%", "√": "√", "∛": "∛", "(": "(", ")": ")", "[": "(", "]": ")", "{": "(",
          "}": ")", "|": "|", ",": ",", "_": "_", "∫": "∫", "→": "→"}
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+")
_SCIENTIFIC = re.compile(r"[eE][+-]?\d+")
_DERIVATIVE = re.compile(r"(?:d|∂)\s*/\s*(?:d|∂)\s*([A-Za-zα-ωΑ-Ω])")


@dataclass(frozen=True)
class Term:
    """One part of a written formula, the parts it is made of, and how it was written: a number's digits, a
    letter, a function's name, an operation's sign."""

    op: str
    args: Tuple["Term", ...] = ()
    text: str = ""

    def leaves(self) -> Tuple["Term", ...]:
        return (self,) if not self.args else tuple(leaf for arg in self.args for leaf in arg.leaves())

    def unknowns(self) -> Tuple[str, ...]:
        """The letters standing for unknowns, in the order they are first written."""
        out: List[str] = []
        bound = {self.args[1].text} if self.op in (DERIVATIVE, INTEGRAL, LIMIT) else set()
        for leaf in self.leaves():
            if leaf.op == SYMBOL and leaf.text not in out:
                out.append(leaf.text)
        return tuple(name for name in out if name not in bound or self.op != LIMIT)

    def render(self) -> str:
        return render(self)


@dataclass(frozen=True)
class Formula:
    """A written formula: one side alone (an expression), or sides related in turn (`2x + 3 = 7`, `0 < x ≤ 5`)."""

    sides: Tuple[Term, ...]
    relations: Tuple[str, ...] = ()
    surface: str = ""

    @property
    def expression(self) -> Optional[Term]:
        return self.sides[0] if not self.relations else None

    def unknowns(self) -> Tuple[str, ...]:
        out: List[str] = []
        for side in self.sides:
            out.extend(name for name in side.unknowns() if name not in out)
        return tuple(out)

    def render(self) -> str:
        text = render(self.sides[0])
        for relation, side in zip(self.relations, self.sides[1:]):
            text += f" {relation} {render(side)}"
        return text


class _Token(tuple):
    """(kind, text): a number, a name, a letter, a mark, a relation, d/dx, or an integral's dx."""

    @property
    def kind(self) -> str:
        return self[0]

    @property
    def text(self) -> str:
        return self[1]


def _token(kind: str, text: str) -> _Token:
    return _Token((kind, text))


def _tokens(text: str, letters_multiply: bool = False) -> Optional[List[_Token]]:
    """The tokens of written mathematics, or None when something in the text is not part of that writing."""
    out: List[_Token] = []
    i, n = 0, len(text)
    integrals = 0
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        derivative = _DERIVATIVE.match(text, i)
        if derivative and (i == 0 or not text[i - 1].isalnum()):
            out.append(_token("d/d", derivative.group(1)))
            i = derivative.end()
            continue
        number = _NUMBER.match(text, i)
        if number:
            digits = number.group(0).replace(",", "")
            i = number.end()
            scientific = _SCIENTIFIC.match(text, i)
            if scientific and not (i + len(scientific.group(0)) < n and text[i + len(scientific.group(0))].isalpha()):
                digits += scientific.group(0).lower()
                i = scientific.end()
            out.append(_token("number", digits))
            continue
        if ch.isalpha():
            j = i
            while j < n and text[j].isalpha() and text[j] not in _MARKS:
                j += 1
            run = text[i:j]
            if integrals and len(run) == 2 and run[0] == "d" and (j == n or not text[j].isalnum()):
                out.append(_token("dx", run[1]))
                integrals -= 1
                i = j
                continue
            pieces = _letters(run, after_number=letters_multiply or (bool(out) and out[-1].kind == "number"
                                                                     and not text[i - 1].isspace()),
                              names_joined=letters_multiply)
            if pieces is None:
                return None
            out.extend(pieces)
            i = j
            # A letter written with its index: x1, x_1, x_{12}.
            if out[-1].kind == "letter":
                k = i
                if k < n and text[k] == "_":
                    k += 1
                    brace = k < n and text[k] in "{("
                    k += brace
                    m = re.match(r"[A-Za-z0-9]+", text[k:])
                    if not m:
                        return None
                    k += m.end()
                    if brace:
                        if k >= n or text[k] not in "})":
                            return None
                        k += 1
                    out[-1] = _token("letter", out[-1].text + "_" + m.group(0))
                    i = k
                elif k < n and text[k] in "0123456789" and len(run) == 1:
                    m = re.match(r"\d+", text[k:])
                    if not (k + m.end() < n and (text[k + m.end()].isalpha() or text[k + m.end()] == ".")):
                        out[-1] = _token("letter", out[-1].text + m.group(0))
                        i = k + m.end()
            continue
        if ch in "⁰¹²³⁴⁵⁶⁷⁸⁹⁻":
            j = i
            while j < n and text[j] in "⁰¹²³⁴⁵⁶⁷⁸⁹⁻":
                j += 1
            exponent = text[i:j].translate(_SUPERSCRIPTS)
            if not re.fullmatch(r"-?\d+", exponent):
                return None
            out.append(_token("superscript", exponent))
            i = j
            continue
        two = text[i:i + 2]
        if two in _RELATION_SPELLINGS and len(two) == 2:
            out.append(_token("relation", _RELATION_SPELLINGS[two]))
            i += 2
            continue
        if two == "**":
            out.append(_token("mark", "^"))
            i += 2
            continue
        if two == "->":
            out.append(_token("mark", "→"))
            i += 2
            continue
        if ch in _RELATION_SPELLINGS:
            out.append(_token("relation", _RELATION_SPELLINGS[ch]))
            i += 1
            continue
        if ch in _MARKS:
            out.append(_token("mark", _MARKS[ch]))
            integrals += ch == "∫"
            i += 1
            continue
        if ch in CONSTANTS:
            out.append(_token("constant", CONSTANTS[ch]))
            i += 1
            continue
        return None
    return out


def _letters(run: str, *, after_number: bool, names_joined: bool = False) -> Optional[List[_Token]]:
    """A run of letters: a function's or a constant's name, one letter standing for an unknown, or -- written
    straight after a number, as in `2xy` -- a product of such letters. Any other run of letters is a word, and a
    word is not mathematics. A name written together with what it applies to (`sinx`) is read so only in a text
    given as a formula (`names_joined`): in a sentence "cost", "mind" and "pip" are words, not cos t, min d, π p."""
    low = run.lower()
    if low == "mod":
        return [_token("mark", "mod")]
    if low in FUNCTIONS or low == "lim":
        return [_token("name", low)]
    if low in CONSTANTS and len(run) > 1:
        return [_token("constant", CONSTANTS[low])]
    if len(run) == 1:
        return [_token("constant", CONSTANTS[run])] if run in CONSTANTS else [_token("letter", run)]
    # A name followed by what it applies to, written together: `sinx`.
    for name in (_NAMES if names_joined else ()):
        if low.startswith(name) and len(run) > len(name) and len(run) - len(name) == 1:
            rest = run[len(name):]
            head = [_token("name", name)] if name in FUNCTIONS or name == "lim" else [_token("constant", CONSTANTS[name])]
            return head + [_token("constant", CONSTANTS[rest])] if rest in CONSTANTS else head + [_token("letter", rest)]
    if after_number and len(run) <= 3:
        return [_token("constant", CONSTANTS[ch]) if ch in CONSTANTS else _token("letter", ch) for ch in run]
    return None


class _Parser:
    """Precedence as mathematics fixes it: brackets, then powers (right to left) and what follows a value (n!, n%),
    then signs, then multiplication and division (left to right, a written-together product as one), then addition
    and subtraction (left to right), then the relations between sides."""

    def __init__(self, tokens: List[_Token]):
        self.tokens = tokens
        self.at = 0
        self.bars = 0

    def peek(self, offset: int = 0) -> Optional[_Token]:
        k = self.at + offset
        return self.tokens[k] if k < len(self.tokens) else None

    def take(self) -> _Token:
        token = self.tokens[self.at]
        self.at += 1
        return token

    def is_mark(self, text: str, offset: int = 0) -> bool:
        token = self.peek(offset)
        return token is not None and token.kind == "mark" and token.text == text

    def expect(self, text: str) -> None:
        if not self.is_mark(text):
            raise ValueError(f"expected {text!r}")
        self.at += 1

    def formula(self) -> Formula:
        sides = [self.expression()]
        relations: List[str] = []
        while self.peek() is not None and self.peek().kind == "relation":
            relations.append(self.take().text)
            sides.append(self.expression())
        return Formula(tuple(sides), tuple(relations))

    def expression(self) -> Term:
        term = self.product()
        while self.is_mark("+") or self.is_mark("-"):
            sign = self.take().text
            term = Term(SUM if sign == "+" else DIFFERENCE, (term, self.product()), sign)
        return term

    def product(self) -> Term:
        term = self.signed()
        while True:
            if self.is_mark("*") or self.is_mark("/") or self.is_mark("mod"):
                sign = self.take().text
                op = {"*": PRODUCT, "/": QUOTIENT, "mod": REMAINDER}[sign]
                term = Term(op, (term, self.signed()), sign)
            elif self.starts_factor():
                term = Term(PRODUCT, (term, self.power()), "")
            else:
                return term

    def starts_factor(self) -> bool:
        """Whether what comes next is written against the value before it, multiplying it: `2x`, `3(x + 1)`,
        `(x + 1)(x - 1)`, `2 sin x`, `2|x|`."""
        token = self.peek()
        if token is None:
            return False
        if token.kind in ("letter", "constant", "name", "d/d"):
            return True
        if token.kind == "mark":
            return token.text in ("(", "√", "∛", "∫") or (token.text == "|" and not self.bars)
        return False

    def signed(self) -> Term:
        if self.is_mark("-"):
            self.take()
            return Term(NEGATIVE, (self.signed(),), "-")
        if self.is_mark("+"):
            self.take()
            return self.signed()
        return self.power()

    def power(self) -> Term:
        base = self.postfix()
        if self.is_mark("^"):
            self.take()
            return Term(POWER, (base, self.signed()), "^")
        return base

    def postfix(self) -> Term:
        term = self.primary()
        while True:
            token = self.peek()
            if token is not None and token.kind == "superscript":
                self.take()
                term = Term(POWER, (term, _number(token.text)), "^")
            elif self.is_mark("!"):
                self.take()
                term = Term(FACTORIAL, (term,), "!")
            elif self.is_mark("%"):
                self.take()
                term = Term(PERCENT, (term,), "%")
            else:
                return term

    def primary(self) -> Term:
        token = self.peek()
        if token is None:
            raise ValueError("a value was expected")
        if token.kind == "number":
            self.take()
            return _number(token.text)
        if token.kind == "letter":
            self.take()
            return Term(SYMBOL, (), token.text)
        if token.kind == "constant":
            self.take()
            return Term(CONSTANT, (), token.text)
        if token.kind == "name":
            return self.function()
        if token.kind == "d/d":
            self.take()
            variable = Term(SYMBOL, (), token.text)
            operand = self.group() if self.is_mark("(") else self.expression()
            return Term(DERIVATIVE, (operand, variable), "d/d")
        if token.kind == "mark":
            if token.text == "(":
                return self.group()
            if token.text == "|":
                self.take()
                self.bars += 1
                inner = self.expression()
                self.bars -= 1
                self.expect("|")
                return Term(FUNCTION, (inner,), "abs")
            if token.text in ("√", "∛"):
                self.take()
                radicand = self.group() if self.is_mark("(") else self.postfix()
                return Term(FUNCTION, (radicand,), "sqrt" if token.text == "√" else "cbrt")
            if token.text == "∫":
                return self.integral()
        raise ValueError(f"{token.text!r} cannot begin a value")

    def group(self) -> Term:
        self.expect("(")
        inner = self.expression()
        self.expect(")")
        return inner

    def function(self) -> Term:
        name = self.take().text
        if name == "lim":
            return self.limit()
        base: Optional[Term] = None
        if name == "log" and self.is_mark("_"):
            self.take()
            base = self.group() if self.is_mark("(") else self.primary()
        exponent: Optional[Term] = None
        if self.is_mark("^") and name not in ("sqrt", "cbrt", "abs"):
            self.take()
            exponent = self.signed()
        if self.is_mark("("):
            self.take()
            args = [self.expression()]
            while self.is_mark(","):
                self.take()
                args.append(self.expression())
            self.expect(")")
        else:
            argument = self.power()
            while self.peek() is not None and (self.peek().kind in ("letter", "constant")
                                               or self.is_mark("(")):
                argument = Term(PRODUCT, (argument, self.power()), "")
            args = [argument]
        if name == "log" and len(args) == 2 and base is None:
            args, base = args[:1], args[1]
        if base is not None:
            args.append(base)
        if len(args) > 1 and name not in ("log", "max", "min", "gcd", "lcm"):
            raise ValueError(f"{name} takes one value")
        applied = Term(FUNCTION, tuple(args), name)
        return Term(POWER, (applied, exponent), "^") if exponent is not None else applied

    def limit(self) -> Term:
        self.expect("_")
        closing = None
        if self.is_mark("("):
            self.take()
            closing = ")"
        token = self.take()
        if token.kind != "letter":
            raise ValueError("a limit is taken as a letter approaches a value")
        self.expect("→")
        point = self.expression()
        if closing:
            self.expect(closing)
        operand = self.product()
        return Term(LIMIT, (operand, Term(SYMBOL, (), token.text), point), "lim")

    def integral(self) -> Term:
        self.expect("∫")
        bounds: Tuple[Term, ...] = ()
        if self.is_mark("_"):
            self.take()
            lower = self.group() if self.is_mark("(") else self.signed_primary()
            self.expect("^")
            upper = self.group() if self.is_mark("(") else self.signed_primary()
            bounds = (lower, upper)
        integrand = self.expression()
        token = self.peek()
        if token is None or token.kind != "dx":
            raise ValueError("an integral ends with the d of its variable")
        self.take()
        return Term(INTEGRAL, (integrand, Term(SYMBOL, (), token.text)) + bounds, "∫")

    def signed_primary(self) -> Term:
        if self.is_mark("-"):
            self.take()
            return Term(NEGATIVE, (self.primary(),), "-")
        return self.primary()


def _number(digits: str) -> Term:
    return Term(NUMBER, (), digits)


def read_formula(text: str, *, letters_multiply: bool = False) -> Optional[Formula]:
    """The formula `text` writes, or None when it is not written mathematics. A lone number or letter is a
    formula too; what reads it decides whether that is worth calling one (`read_expression`).

    Letters written together multiply only after a number (`2xy`), unless `letters_multiply`: in a sentence
    "is x" must stay a word and a letter, and only a text given as a formula may write `xy` for x times y."""
    if not text or not str(text).strip():
        return None
    tokens = _tokens(str(text).strip(), letters_multiply)
    if not tokens:
        return None
    parser = _Parser(tokens)
    try:
        formula = parser.formula()
    except (ValueError, IndexError):
        return None
    if parser.at != len(tokens):
        return None
    return Formula(formula.sides, formula.relations, str(text).strip())


def read_expression(text: str) -> Optional[Term]:
    """The expression `text` writes -- a formula with no relation in it that does something to what it is
    made of (`2 + 3`, `x^2`, `5!`, `sqrt 16`) -- or None. A number alone, or a letter alone, is a number or a
    letter, not an expression."""
    formula = read_formula(text)
    if formula is None or formula.relations:
        return None
    term = formula.sides[0]
    return term if term.args else None


# ---- writing a formula back -------------------------------------------------------------------------------------

_BINDING = {SUM: 1, DIFFERENCE: 1, PRODUCT: 2, QUOTIENT: 2, REMAINDER: 2, NEGATIVE: 3, POWER: 4, FACTORIAL: 5,
            PERCENT: 5}
_SIGNS = {SUM: "+", DIFFERENCE: "-", QUOTIENT: "/"}


def _binding(term: Term) -> int:
    if term.op == NUMBER:
        # A value written as a fraction binds as a division does, and a negative one as a sign does.
        return 2 if "/" in term.text else 3 if term.text.startswith("-") else 6
    return _BINDING.get(term.op, 6)


def _grouped(term: Term, least: int, *, right: bool = False) -> str:
    text = render(term)
    tight = _binding(term)
    if right and text.startswith("-") and least >= 1:
        return f"({text})"          # 5 × (-6), 3 + (-2): a sign never follows an operation's sign unbracketed
    return f"({text})" if tight < least or (right and tight == least and term.op not in (POWER,)) else text


def _grouped_number(digits: str) -> str:
    """A whole number of five or more digits written in groups of three, as it is read: 1,000,000."""
    sign, body = ("-", digits[1:]) if digits.startswith("-") else ("", digits)
    if body.isdigit() and len(body) >= 5:
        return sign + f"{int(body):,}"
    return digits


def render(term: Term) -> str:
    """The term written as mathematics writes it, with the brackets its precedence needs and no others."""
    op, args = term.op, term.args
    if op == NUMBER:
        return _grouped_number(term.text)
    if op == SYMBOL:
        return term.text
    if op == CONSTANT:
        return {"pi": "π", "infinity": "∞"}.get(term.text, term.text)
    if op in (SUM, DIFFERENCE):
        left = _grouped(args[0], 1)
        right = _grouped(args[1], 1, right=op == DIFFERENCE)
        if right.startswith("-"):
            right = f"({right})"
        return f"{left} {_SIGNS[op]} {right}"
    if op == PRODUCT:
        left, right = args
        written_together = (left.op in (NUMBER, SYMBOL, CONSTANT, POWER, PRODUCT, FACTORIAL)
                            and right.op in (SYMBOL, CONSTANT, FUNCTION)
                            or (right.op == POWER and right.args[0].op in (SYMBOL, CONSTANT)))
        if written_together and left.op == PRODUCT and left.args[1].op == NUMBER:
            written_together = False
        if right.op == NUMBER or (right.op == POWER and right.args[0].op == NUMBER):
            written_together = False
        if written_together and _binding(left) >= 2 and left.op != QUOTIENT:
            return f"{_grouped(left, 2)}{render(right) if right.op != PRODUCT else _grouped(right, 3)}"
        if right.op in (SUM, DIFFERENCE) and left.op not in (QUOTIENT, NUMBER) or \
                (right.op in (SUM, DIFFERENCE) and left.op == NUMBER and "/" not in left.text):
            return f"{_grouped(left, 2)}({render(right)})"
        return f"{_grouped(left, 2)} × {_grouped(right, 2, right=True)}"
    if op == QUOTIENT:
        if args[0].op == NUMBER and args[1].op == NUMBER and "/" not in args[0].text + args[1].text:
            return f"{render(args[0])}/{render(args[1])}"      # a fraction of numbers, 3/4, is written as one
        return f"{_grouped(args[0], 2)} / {_grouped(args[1], 2, right=True)}"
    if op == REMAINDER:
        return f"{_grouped(args[0], 2)} mod {_grouped(args[1], 2, right=True)}"
    if op == NEGATIVE:
        # -(ab) is (-a)b and -(a/b) is (-a)/b: only a sum needs its brackets after a sign.
        inner = render(args[0])
        return f"-({inner})" if args[0].op in (SUM, DIFFERENCE) or inner.startswith("-") else f"-{inner}"
    if op == POWER:
        base = render(args[0])
        if args[0].op not in (NUMBER, SYMBOL, CONSTANT, FUNCTION) or base.startswith("-"):
            base = f"({base})"
        exponent = render(args[1])
        if args[1].op not in (NUMBER, SYMBOL, CONSTANT):
            exponent = f"({exponent})"
        return f"{base}^{exponent}"
    if op == FACTORIAL:
        return f"{_grouped(args[0], 6)}!"
    if op == PERCENT:
        return f"{_grouped(args[0], 6)}%"
    if op == FUNCTION:
        if term.text == "abs":
            return f"|{render(args[0])}|"
        if term.text == "sqrt":
            inner = render(args[0])
            return f"√{inner}" if args[0].op in (NUMBER, SYMBOL, CONSTANT) and not inner.startswith("-") \
                else f"√({inner})"
        if term.text == "log" and len(args) == 2:
            return f"log_{_grouped(args[1], 6)}({render(args[0])})"
        return f"{term.text}({', '.join(render(a) for a in args)})"
    if op == DERIVATIVE:
        return f"d/d{args[1].text}({render(args[0])})"
    if op == INTEGRAL:
        bounds = f"_{_grouped(args[2], 6)}^{_grouped(args[3], 6)}" if len(args) == 4 else ""
        return f"∫{bounds} {render(args[0])} d{args[1].text}"
    if op == LIMIT:
        return f"lim_({args[1].text} → {render(args[2])}) {_grouped(args[0], 2)}"
    raise ValueError(f"{op!r} is not a part of a formula")


__all__ = ["LinearEquation", "SequenceQuestion", "read", "read_sequence",
           "MINIMUM_SEQUENCE_TERMS",
           "Term", "Formula", "read_formula", "read_expression", "render", "RELATIONS", "FUNCTIONS",
           "NUMBER", "SYMBOL", "CONSTANT", "SUM", "DIFFERENCE", "PRODUCT", "QUOTIENT", "POWER", "NEGATIVE",
           "FACTORIAL", "PERCENT", "FUNCTION", "DERIVATIVE", "INTEGRAL", "LIMIT", "REMAINDER",
           "EQUALS", "NOT_EQUAL", "LESS", "GREATER", "AT_MOST", "AT_LEAST"]
