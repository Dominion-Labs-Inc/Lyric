#!/usr/bin/env python3
"""Written mathematics: read by its own rules, worked by the symbolic mathematics faculty, exact at any size.

A formula is read token by token into the tree its precedence makes (`arithmetic_reading.read_formula`), never
evaluated as code; a sentence carries a formula as one term (`sentence_machine.form_of`, `literals`); and the
faculty works it -- calculated in the order of operations, solved the way its kind is solved, broken down into
what it is made of -- with every answer put back to check it.
"""

import pytest

from core.reasoning.arithmetic_reading import read_expression, read_formula
from core.semantics.literals import classify_literal
from core.semantics.sentence_machine import form_of
from core.tools.symbolic_math_faculty import break_down, calculate, mathematics_of, solve


@pytest.mark.parametrize("written, read", [
    ("2+3*4", "2 + 3 × 4"),
    ("(2+3)*4", "(2 + 3) × 4"),
    ("3x² + 2x − 5 = 0", "3x^2 + 2x - 5 = 0"),
    ("2^3^2", "2^(3^2)"),
    ("-x^2", "-x^2"),
    ("sin x cos x", "sin(x) × cos(x)"),
    ("log_2 8", "log_2(8)"),
    ("|x - 3|", "|x - 3|"),
    ("√16", "√16"),
    ("0 < x <= 5", "0 < x ≤ 5"),
    ("d/dx x^3 + 2x", "d/dx(x^3 + 2x)"),
    ("∫_0^1 x^2 dx", "∫_0^1 x^2 dx"),
    ("1,000,000 * 3", "1,000,000 × 3"),
])
def test_a_formula_is_read_by_the_rules_of_its_writing(written, read):
    assert read_formula(written).render() == read


@pytest.mark.parametrize("words", ["ray", "the", "x-ray", "xy + 1", "12 3", "__import__('os')"])
def test_words_and_code_are_not_mathematics(words):
    assert read_formula(words) is None


@pytest.mark.parametrize("sentence, pieces", [
    ("What is 2 + 3?", ["What", "is", "2 + 3", "?"]),
    ("Solve 2x + 3 = 7.", ["Solve", "2x + 3", "=", "7", "."]),
    ("There are 1,000,000 dogs.", ["There", "are", "1,000,000", "dogs", "."]),
    ("What is d/dx x^3?", ["What", "is", "d/dx x^3", "?"]),
    ("I have 5!", ["I", "have", "5", "!"]),
    ("The x-ray is old.", ["The", "x", "-", "ray", "is", "old", "."]),
    ("It rained on 2026-09-29.", ["It", "rained", "on", "2026-09-29", "."]),
    # English words are words: "cost" is not cos t, "pip" not π p, "mind" not min d, and "a T" is no product.
    ("What is a cost accounting?", ["What", "is", "a", "cost", "accounting", "?"]),
    ("What is a pip?", ["What", "is", "a", "pip", "?"]),
    ("What is a T cell?", ["What", "is", "a", "T", "cell", "?"]),
    ("What is sin x?", ["What", "is", "sin x", "?"]),
])
def test_a_formula_in_a_sentence_is_one_piece(sentence, pieces):
    assert [p.text for p in form_of(sentence)] == pieces


def test_a_formula_is_one_thing_however_it_is_spaced():
    assert classify_literal("2+3").canonical == classify_literal("2 + 3").canonical == "2 + 3"
    assert classify_literal("1,000,000").canonical == "1000000"
    assert classify_literal("9/11") is None and classify_literal("3pm") is None


@pytest.mark.parametrize("formula, answer", [
    ("2 + 3 × 4", "14"),
    ("-3 + 5 × (2 - 8)", "-33"),
    ("3,000,000,000,000 × 1,000,000,000,000", "3,000,000,000,000,000,000,000,000"),
    ("2^100", "1,267,650,600,228,229,401,496,703,205,376"),
    ("0.1 + 0.2", "0.3"),
    ("1/3 + 1/6", "1/2"),
    ("15% × 240", "36"),
    ("sqrt(16) + 2^3", "12"),
    ("log(1000)", "3"),
    ("d/dx x^3 + 2x", "3x^2 + 2"),
    ("∫_0^1 x^2 dx", "1/3"),
])
def test_calculating_is_exact_at_any_size(formula, answer):
    assert calculate(formula).answer == [answer]


def test_the_order_of_operations_is_the_order_of_the_steps():
    assert calculate("2 + 3 × 4").steps == ["3 × 4 = 12, so it is 2 + 12", "2 + 12 = 14"]


@pytest.mark.parametrize("equation, answer", [
    ("2x + 3 = 7", ["x = 2"]),
    ("x^2 - 5x + 6 = 0", ["x = 2", "x = 3"]),
    ("x^2 + 2x - 1 = 0", ["x = -1 - √2", "x = -1 + √2"]),
    ("x^2 + 1 = 0", ["x = -i", "x = i"]),
    ("sqrt(x + 3) = x - 3", ["x = 6"]),
    ("2^x = 32", ["x = 5"]),
    ("-2x + 3 ≥ 7", ["x ≤ -2"]),
    ("x + 1 = x + 2", ["no value of x"]),
])
def test_an_equation_is_solved_and_every_answer_checked(equation, answer):
    worked = solve(equation)
    assert worked.answer == answer
    assert not any("NOT" in line for line in worked.check)


def test_equations_are_solved_together_by_substitution():
    worked = solve(["x + y = 10", "x - y = 2"])
    assert worked.answer == ["x = 6; y = 4"]
    assert worked.steps[0] == "From x + y = 10: x = 10 - y"


def test_a_root_that_does_not_check_is_no_solution():
    worked = solve("sqrt(x + 3) = x - 3")
    assert any("x = 1 does not solve the original equation" in step for step in worked.steps)


def test_breaking_down_says_what_a_formula_is_made_of_and_works_it():
    worked = break_down("3x^2 + 2x - 5 = 0")
    assert worked.parts[0] == "3x^2 + 2x - 5 = 0 is a quadratic equation in x"
    assert "Factor: (x - 1)(3x + 5) = 0" in worked.steps
    assert worked.answer == ["x = -5/3", "x = 1"]


def test_a_meaning_about_numbers_is_worked_and_one_about_things_is_not():
    from core.semantics.derived_reader import Meaning, MeaningFact as F
    asked = Meaning("ask", (F("equals", "?v0", "?v2"), F("has_augend", "?v0", "2"), F("has_addend", "?v0", "?v1"),
                            F("has_multiplicand", "?v1", "3"), F("has_factor", "?v1", "4")), ("?v2",))
    assert mathematics_of(asked).answer == ["14"]
    given = Meaning("ask", (F("equals", "2x + 3", "7", True, True), F("equals", "x", "?v0")), ("?v0",))
    assert mathematics_of(given).answer == ["2"]
    assert mathematics_of(Meaning("ask", (F("isa", "dog", "?x"),), ("?x",))) is None
