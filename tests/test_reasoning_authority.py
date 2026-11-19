#!/usr/bin/env python3
"""The reasoning authority is the only thing that reaches for the graph oracle.

There is ONE reasoning authority, `NeuralSymbolicBridge.reason()`
(`core/tools/reasoning_tools.py`: "THROUGH THE REASONING AUTHORITY, NOT AROUND IT. ... This used to call
get_proof_engine() directly ... so a proof obtained through this tool was unverified, unrecorded, and off the
one path the architecture is built around").

`concept_graph_reasoning.answer_over_graph` derives a verdict over the concept graph -- TRUE, FALSE or unknown,
open-world, denials loaded, up to six hops. That is reasoning. A caller that imports it takes a verdict off the
one path: unrecorded, no kind of thinking selected for it, and nothing able to say afterwards how it was
reached. Two callers did, and each was a different kind of mistake:

  * `review_learned` answered its own 200 questions with it, so a review measured how far a graph walk reaches
    and wrote that down as the domain's COMPETENCE -- 0.4859 to 0.4346 on 2026-11-19 -- without the authority
    being consulted once. `denied: 0` beside `not_derived: 34` is the signature: nothing was ever asked to
    derive anything. That one belongs in `reason()`, and is there now.
  * the learning door's contradiction check (`_held_against`) derived FALSE with it at every admission. That
    one does NOT belong in `reason()`: it runs once per fact, a reference corpus is 83,093 facts, and a
    reasoning each would add some seventeen minutes to a teach and write a record per taught fact. It is a
    READ, so the authority publishes the read (`what_the_graph_holds`) and the gate is on the path by
    construction and pays nothing.

So the rule is not "everything goes through `reason()`" -- it is that the oracle has one owner, and the owner
decides what a caller may have. These tests hold that, and that the scanner enforcing it actually works.

Nothing here needs a store.
"""
import importlib.util
import inspect
import os
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _scanner():
    spec = importlib.util.spec_from_file_location(
        "separation_map", os.path.join(ROOT, "scripts", "separation_map.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_the_authority_reaches_for_the_graph_oracle():
    outside = _scanner().graph_oracle_outside_the_authority()
    assert outside == [], "the graph oracle is reached from outside the reasoning authority:\n" + "\n".join(
        f"  {f}:{line} {how}" for f, line, how in outside)


def test_the_scanner_finds_a_bypass_however_it_is_written(tmp_path):
    """Imported, named, or reached as an attribute -- all three are a caller taking the oracle."""
    module = tmp_path / "bypass.py"
    module.write_text(textwrap.dedent('''
        from core.reasoning.concept_graph_reasoning import answer_over_graph

        async def one(db):
            return await answer_over_graph(db, "a", "isa", "b")

        async def two(db, mod):
            return await mod.answer_over_graph(db, "a", "isa", "b")
    '''))
    found = _scanner().oracle_references(module.read_text(), "bypass.py")
    assert {how for _f, _line, how in found} == {
        "imports answer_over_graph", "names answer_over_graph", "reaches .answer_over_graph"}, found


def test_a_note_about_the_oracle_is_not_a_use_of_it(tmp_path):
    """Read from the syntax, not the text. A scanner matching the name anywhere flagged the very docstrings
    written to record that the bypass was closed."""
    module = tmp_path / "note.py"
    module.write_text(textwrap.dedent('''
        def held():
            """This used to call `answer_over_graph` directly, which was the bypass."""
            # answer_over_graph is the authority's, not ours
            return None
    '''))
    assert _scanner().oracle_references(module.read_text(), "note.py") == []


def test_the_authority_publishes_the_read_a_gate_needs():
    from core.reasoning.neural_bridge import NeuralSymbolicBridge
    assert hasattr(NeuralSymbolicBridge, "what_the_graph_holds")
    signature = inspect.signature(NeuralSymbolicBridge.what_the_graph_holds)
    # Scoped as `reason()` scopes it: whose context is in play, and what was said but not taken in whole.
    for scoped in ("actor", "not_taken_in", "max_hops"):
        assert scoped in signature.parameters, scoped


def test_the_published_read_records_nothing_and_selects_nothing():
    """It is a read. A reasoning that selected kinds or wrote a record here would be the cost the gate cannot
    pay, and would make every admission a reasoning."""
    from core.reasoning.neural_bridge import NeuralSymbolicBridge
    source = inspect.getsource(NeuralSymbolicBridge.what_the_graph_holds)
    body = source.split('"""')[-1]
    for costly in ("_select_strategies", "take_in_reasoning", "remember_experience",
                   "create_task", "ReasoningRequest"):
        assert costly not in body, f"{costly} makes this a reasoning, not a read"


def test_the_gate_asks_the_authority():
    from core.learning.unified_learning_system import UnifiedLearningSystem
    source = inspect.getsource(UnifiedLearningSystem._held_against)
    assert "what_the_graph_holds" in source
    assert "import answer_over_graph" not in source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
