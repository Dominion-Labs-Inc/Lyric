#!/usr/bin/env python3
"""The lift: what a task that worked did, as a method anyone's work can use.

MEMORY_AGENT_MAP §10.2, SEPARATION_MAP §11.4. A method that worked for one
person is world knowledge once nothing of that person is left in it; a person's
design and content stay theirs. This module is the pure part of that: no store,
no belief.

  shape         what a method does, whoever it was done for: its steps' tools,
                in order, each with the names of the arguments it was given.
  facts         the method as logic atoms, one per step: the tool's own name,
                upper-cased (`tool_registry.predicate_for`), over its argument
                values encoded as constants (`rule_induction.as_constant`).
  vocabulary    the values a method gives its tools that are the tools' own
                words, so no one's particular: a truth value for an argument the
                tool declares boolean, or a value it declares the argument takes.
  lift_one      the first task of a shape that worked, as a method: every value
                not kept becomes a variable, the same value the same variable
                everywhere. The memory agent keeps the tools' vocabulary and what
                the world holds a thing under; nothing else, so nothing of the
                person.
  generalize    two methods of one shape, anti-unified
                (`rule_induction.anti_unify`): every value that differs becomes
                a variable, the same pair of values the same variable everywhere.
  residue       the constants a generalization keeps whose only source is
                people's material: in every instance it came from, the instance
                was a person's work and the person supplied that value. Such a
                term makes the lesson theirs.

A method is lifted from the first task that worked: what Lyric overcame once it
can do again, for the same person and for anyone. Later tasks widen it and move
how well it is believed to work.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from core.learning.rule_induction import from_constant, as_constant
from core.tools.tool_registry import predicate_for
from core.learning.rule_induction import Fact, anti_unify
from core.reasoning.unification import VARIABLE_PREFIX, is_variable

#: Punctuation a word carries at its edges in a sentence: "report.txt." is the
#: word report.txt at the end of a sentence.
_EDGE_PUNCTUATION = ".,;:!?\"'()[]{}"


def value_text(value: Any) -> str:
    """An argument's value as the text a constant encodes. A structured value is
    its canonical JSON, so two equal structures are one constant."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _steps(method: Any) -> Optional[List[Tuple[str, Dict[str, Any]]]]:
    """A method's steps as (tool, arguments), or None when it is not a method:
    no steps, or a step that names no tool."""
    if not isinstance(method, list) or not method:
        return None
    steps = []
    for step in method:
        if not isinstance(step, dict) or not step.get("tool"):
            return None
        args = step.get("args") or {}
        if not isinstance(args, dict):
            return None
        steps.append((str(step["tool"]), args))
    return steps


def shape_of(method: Any) -> Optional[str]:
    """What the method does, whoever it was done for, or None if it is not one."""
    steps = _steps(method)
    if steps is None:
        return None
    return "|".join(f"{predicate_for(tool)}({','.join(sorted(args))})" for tool, args in steps)


def method_facts(method: Any) -> Optional[List[Fact]]:
    """The method as ground facts, one per step, arguments in name order."""
    steps = _steps(method)
    if steps is None:
        return None
    return [Fact(predicate_for(tool), tuple(as_constant(value_text(args[name])) for name in sorted(args)))
            for tool, args in steps]


def vocabulary(method: Any, declared: Callable[[str], Dict[str, Any]]) -> Set[str]:
    """The values a method gives its tools that are the tools' own words, so no
    one's particular: a truth value given to an argument the tool declares
    boolean, or one of the values it declares the argument takes (`enum`).
    `declared(tool)` gives a tool's declared parameters by name."""
    words: Set[str] = set()
    for tool, args in _steps(method) or []:
        params = declared(tool)
        for name, value in args.items():
            param = params.get(name)
            if param is None:
                continue
            boolean = str(getattr(param, "type", "")).lower() == "boolean" and isinstance(value, bool)
            if boolean or value in (getattr(param, "enum", None) or ()):
                words.add(value_text(value))
    return words


def lift_one(facts: Sequence[Fact], kept: Set[str]) -> List[Fact]:
    """One task's method, lifted: every value not in `kept` (values as text,
    `value_text`) becomes a variable, the same value the same variable
    everywhere, numbered as `generalize` numbers them, so a later task is an
    instance of it exactly when `is_instance` says so."""
    named: Dict[str, str] = {}
    lifted = []
    for fact in facts:
        args = []
        for arg in fact.args:
            if is_variable(arg) or from_constant(arg) in kept:
                args.append(arg)
            else:
                args.append(named.setdefault(arg, f"{VARIABLE_PREFIX}V{len(named)}"))
        lifted.append(Fact(fact.predicate, tuple(args)))
    return lifted


def generalize(left: Sequence[Fact], right: Sequence[Fact]) -> Optional[List[Fact]]:
    """The least general method covering both, or None when they are not of one
    shape."""
    if len(left) != len(right):
        return None
    lifted = anti_unify(zip(left, right))
    return None if lifted is None else lifted[0]


def is_instance(general: Sequence[Fact], ground: Sequence[Fact]) -> bool:
    """Whether `ground` is `general` with its variables filled in (consistently)."""
    lifted = generalize(general, ground)
    return lifted is not None and list(lifted) == list(general)


def constants(facts: Iterable[Fact]) -> Set[str]:
    """The values a method keeps as constants, decoded."""
    return {from_constant(arg) for fact in facts for arg in fact.args if not is_variable(arg)}


def person_terms(parts: Iterable[Dict[str, Any]], *also: str) -> Set[str]:
    """Every value a person supplied in an experience: each text in the parts
    that came from the person, whole and word by word, and any further texts
    given (`also`, the request that started the work)."""
    texts: List[str] = list(also)

    def walk(value: Any) -> None:
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif value is not None:
            texts.append(str(value))

    for part in parts:
        if isinstance(part, dict) and part.get("source") == "person":
            walk(part.get("content"))
    terms: Set[str] = set()
    for text in texts:
        if not text:
            continue
        terms.add(text)
        for word in text.split():
            stripped = word.strip(_EDGE_PUNCTUATION)
            if stripped:
                terms.add(stripped)
    return terms


def residue(general: Sequence[Fact], instances: Sequence[Optional[Set[str]]]) -> List[str]:
    """The constants of `general` whose only source is people's material.

    `instances` holds, for each experience the method was lifted from, the
    values its person supplied (`person_terms`), or None when the experience was
    the substrate's own work. A constant is a person's only when every instance
    was a person's work and each of them supplied it: if the substrate's own
    work used the same value, or any person's work used it without that person
    supplying it, it has a source that is not a person.
    """
    if not instances or any(terms is None for terms in instances):
        return []
    return sorted(value for value in constants(general)
                  if all(value in terms for terms in instances))


def formulas(facts: Iterable[Fact]) -> List[str]:
    """The method as it is kept in memory: one formula per step."""
    return [fact.to_formula() for fact in facts]


def from_formulas(steps: Iterable[str]) -> List[Fact]:
    """A kept method back as facts."""
    return [Fact.parse(step) for step in steps]
