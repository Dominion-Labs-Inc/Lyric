"""The teaching run's snapshot reports every kind of memory the store holds, and not a list written in the script.

Until 2026-10-29 `snapshot()` counted eight things — concepts, relations, beliefs, domains, memberships, taught
statements, words recorded, sentences recorded — and word classes were not one of them. The owner's
`--source wordnet-classes` run on the main store wrote 1,107 word classes and the run printed zeros in every
column, so the only honest reading of its own report was that it had learned nothing. These tests hold the two
properties that stop that happening again for any kind of learning added later: the snapshot asks the store what
it holds, and the report shows a kind written for the first time.
"""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "teach_script", Path(__file__).resolve().parents[1] / "scripts" / "teach.py")
teach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(teach)


class _Store:
    """A store that answers the two questions `snapshot` asks, and records what it was asked."""

    def __init__(self, tags, tables):
        self.tags, self.tables, self.asked = tags, tables, []

    async def execute_query(self, query, params=None, **kwargs):
        self.asked.append(query)
        if "jsonb_array_elements_text" in query:
            return [{"tag": tag, "n": n} for tag, n in self.tags.items()]
        if "pg_class" in query:
            return [{"s": s, "t": t} for s, t in self.tables]
        if "UNION ALL" in query:          # the one question that counts every table
            return [{"t": f"{s}.{t}", "n": self.tables[(s, t)] if isinstance(self.tables, dict) else 0}
                    for s, t in self.tables]
        raise AssertionError(f"unexpected query: {query[:60]}")


@pytest.mark.asyncio
async def test_every_kind_the_store_holds_is_counted_including_ones_this_script_never_names():
    store = _Store(
        tags={"word_class": 94262, "taught_sentence": 9874, "language_pattern": 628380,
              "admitted_proposition": 576968, "a_kind_invented_tomorrow": 3},
        tables={("unified", "concepts"): 115448, ("memory_hot", "memory_hot"): 1482206},
    )
    held = await teach.snapshot(store)

    # the kind whose absence made a run of 1,107 pairs report nothing
    assert held["memory: word_class"] == 94262
    # and a kind no code here knows the name of, counted all the same
    assert held["memory: a_kind_invented_tomorrow"] == 3
    assert len([k for k in held if k.startswith("memory: ")]) == 5
    # every table of the schemas memory is held in, named by the store's catalogue
    assert "table: unified.concepts" in held and "table: memory_hot.memory_hot" in held
    # cold memory is asked about too, so a memory tiered out of hot is not read as one that went missing
    assert "memory_cold.memory_cold" in store.asked[0]


@pytest.mark.asyncio
async def test_the_five_tables_the_old_snapshot_reported_are_all_still_counted():
    was_reported = [("unified", "concepts"), ("unified", "concept_relations"), ("unified", "beliefs"),
                    ("unified", "domains"), ("unified", "concept_domains")]
    held = await teach.snapshot(_Store(tags={}, tables={t: 1 for t in was_reported}))
    for schema, table in was_reported:
        assert f"table: {schema}.{table}" in held, f"{table} was reported before and must still be"


def test_a_kind_written_for_the_first_time_is_shown_from_nothing():
    before = {"memory: taught_sentence": 9874, "table: unified.concepts": 115448}
    after = {"memory: taught_sentence": 9874, "table: unified.concepts": 115448,
             "memory: word_record": 3919}

    moved = teach.what_moved(before, after)

    # the kind the store held none of before this run is reported, not passed over
    assert moved == ["memory: word_record"]
    assert before.get("memory: word_record", 0) == 0 and after["memory: word_record"] == 3919


def test_what_held_still_is_not_reported_and_kinds_come_before_tables():
    before = {"memory: word_class": 93155, "table: unified.beliefs": 10, "memory: said_of": 7}
    after = {"memory: word_class": 94262, "table: unified.beliefs": 11, "memory: said_of": 7}

    assert teach.what_moved(before, after) == ["memory: word_class", "table: unified.beliefs"]


def test_nothing_taught_moves_nothing_and_that_is_a_result():
    held = {"memory: word_class": 94262, "table: unified.concepts": 115448}
    assert teach.what_moved(held, dict(held)) == []


def test_every_field_of_a_pass_report_reaches_the_lines_it_prints():
    """The other half of the same defect, guarded rather than rewritten.

    `Report.lines()` names all 24 of its fields today (checked 2026-10-29), so a pass says everything it did. A
    field added without a line would be learning the run performed and did not report, which is exactly what the
    snapshot did with word classes.
    """
    import dataclasses
    import inspect

    from core.learning.teaching import Report

    # THE WHOLE PRINTED PATH, not `lines` alone. A field reported THROUGH the helper every line uses (`_said`,
    # which says "NOT TAUGHT HERE -- ..." out of `not_offered`) reaches the lines a pass prints, and reading only
    # `lines` called it unreported -- the real run prints it ten times over.
    printed = inspect.getsource(Report.lines) + inspect.getsource(Report._said)
    unreported = [f.name for f in dataclasses.fields(Report) if f"self.{f.name}" not in printed]
    assert not unreported, f"a pass writes these and never reports them: {unreported}"


def test_every_layer_of_a_word_recorded_whole_is_read_by_a_check():
    """A LAYER NO CHECK READS IS A HOLE NOBODY SEES. The standard format Lyric is taught from was proven on one
    example and mirrored, so a layer of the record -- or a kind of question -- that no example happened to use is
    verified by nothing. Measured 2026-11-02 on a store taught from nothing: 19 words recorded whole went in with 0
    refused, every sentence read, and "What is paint?" was answered "There was nothing in that I could resolve."
    against records holding seven senses with their definitions and every kind up their chains.

    EACH CHECK SAYS WHICH LAYERS IT READS (`RunRecord.check(..., reads=...)`), and coverage is counted from that.
    It was first counted by matching the record's field names against the checks' English, which is no measure at
    all: it missed layers that ARE checked under prose ("used_as", by "the grammar holds how the treebanks used
    each form") and would have passed a label that merely mentioned a word. The round-trip check reads no layer on
    purpose -- that the format survives being written and read back is a different property, and counting it would
    mark all 27 verified while nothing read one.

    Every layer is one of three things and nothing else: PROVENANCE (where the record came from, read by no part of
    reading), read by a check that says so, or named in `NOT_YET_CHECKED` -- taught today and verified by nothing,
    written out so it is a list someone can work through instead of a hole. **That list only shrinks.**
    """
    import ast
    import dataclasses

    from core.learning.teaching_sources import WordRecord

    #: Layers that say where the record CAME FROM, read by no part of reading, so no check reads them.
    PROVENANCE = {"source", "licence", "split"}
    #: TAUGHT AND VERIFIED BY NOTHING (2026-11-02). Each is written into memory by `GrammarView._count_word` or
    #: `MemoryAgent._learn_word_record` and read by some part of reading -- `joined_as` and `related_as` by the
    #: structure view that weighs which word takes which, `misc` by the morphological segmentation, `tags` by the
    #: treebank's own tags -- and no check asks whether what went in comes back. ONLY SHRINKS.
    NOT_YET_CHECKED = {
        "uses", "joins_things", "together", "used_before_doing", "used_asking", "said_alone", "capitalized",
        "shapes", "said_of_doing", "said_after", "means", "tags", "joined_as", "related_as", "enhanced", "misc",
        "covered",
    }

    experiment = Path(__file__).resolve().parents[1] / "experiments" / "TRAIN-FORMAT-02" / "experiment.py"
    tree = ast.parse(experiment.read_text(encoding="utf-8"))
    read_by_a_check: set = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "check"):
            continue
        for keyword in node.keywords:
            if keyword.arg != "reads":
                continue
            for element in getattr(keyword.value, "elts", ()):
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    read_by_a_check.add(element.value)
    assert read_by_a_check, "no check says which layers it reads; coverage cannot be counted"

    layers = {f.name for f in dataclasses.fields(WordRecord)}
    named = sorted(layer for layer in read_by_a_check if layer not in layers)
    assert not named, (
        f"these checks say they read layers WordRecord does not have: {', '.join(named)}. A check that reads a "
        "layer by the wrong name verifies nothing and reports that it did."
    )

    unaccounted = sorted(layers - PROVENANCE - NOT_YET_CHECKED - read_by_a_check)
    assert not unaccounted, (
        "every layer of a word recorded whole must be read by a check that says so, or named as provenance, or "
        f"written into NOT_YET_CHECKED: {', '.join(unaccounted)} is none of the three. A layer taught and read by "
        "nothing measurable is learning nobody can verify."
    )

    earned = sorted(NOT_YET_CHECKED & read_by_a_check)
    assert not earned, (
        f"these layers are now read by a check and must come out of NOT_YET_CHECKED: {', '.join(earned)}. The list "
        "only shrinks, so it says what is still unverified and not what once was."
    )

    gone = sorted((NOT_YET_CHECKED | PROVENANCE) - layers)
    assert not gone, (
        f"these are named here but are no longer layers of WordRecord: {', '.join(gone)}. A list that outlives "
        "what it describes is the defect this test exists to stop."
    )
