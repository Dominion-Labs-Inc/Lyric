#!/usr/bin/env python3
"""What each word has been seen used as is worked out once and kept.

Working it out is the largest thing an ordinary start pays. Measured on the World Model, 2026-11-19: the
classes implied by the taught sentences took 37.8s of a 140.9s warm and the classes stated outright another
1.3s -- between them 39.1s, every start, over memories that had not changed since the last one. The ANSWER is
197,127 words; the WORKING is 592,233 taught sentences shaped one by one through `classes_implied_by`.

Kept WITH WHAT IT WAS WORKED OUT FROM. An index read back where the memories have moved on is worse than no
index: it is wrong in a way nothing downstream can see.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agents.memory_agent import MemoryAgent  # noqa: E402


def _rows(*ids):
    return [SimpleNamespace(memory_id=i, metadata={}) for i in ids]


def test_the_mark_says_which_memories_the_index_came_from():
    """One memory more, one fewer, or one replaced, and the mark differs -- so the work is done again. It does
    NOT depend on the order the rows came back in, because nothing guarantees that order between starts."""
    mark = MemoryAgent._word_class_mark
    taught, unread, stated = _rows("m1", "m2", "m3"), _rows("u1"), _rows("s1", "s2")
    same = mark(taught, unread, stated)

    assert mark(_rows("m3", "m1", "m2"), unread, stated) == same, "the order rows come back in is not meaning"
    assert mark(_rows("m1", "m2"), unread, stated) != same, "one memory fewer is other evidence"
    assert mark(_rows("m1", "m2", "m3", "m4"), unread, stated) != same, "one memory more is other evidence"
    assert mark(_rows("m1", "m2", "mX"), unread, stated) != same, "one memory replaced is other evidence"
    assert mark(taught, unread, _rows("s1")) != same, "each kind counts apart from the others"

    # DETERMINISTIC ACROSS PROCESSES. Python's own `hash` of a string is keyed per process, so a mark built
    # with it would differ at every start and the index would never once be read back.
    import subprocess
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r)\n"
         "from types import SimpleNamespace\n"
         "from core.agents.memory_agent import MemoryAgent\n"
         "r = lambda *i: [SimpleNamespace(memory_id=x, metadata={}) for x in i]\n"
         "print(MemoryAgent._word_class_mark(r('m1','m2','m3'), r('u1'), r('s1','s2')))"
         % str(Path(__file__).resolve().parents[1])],
        capture_output=True, text=True, env={"PYTHONHASHSEED": "1", "PATH": "/usr/bin:/bin"})
    assert out.stdout.strip() == same, f"the mark must not depend on the process: {out.stdout!r} {out.stderr[-300:]}"


def test_the_index_is_read_back_only_where_the_memories_are_the_same():
    """And a half-written answer is never read back: the rows and the count of words are written together, so
    disagreeing means a write was cut short."""
    import asyncio

    class Store:
        def __init__(self, mark, words, rows):
            self.mark, self.words, self.rows = mark, words, rows
            self.reads = 0

        async def execute_query(self, query, params=None, **kw):
            q = query.strip()
            if q.startswith(("CREATE", "DELETE", "INSERT")):
                return None
            if "word_class_index_from" in q:
                return [{"mark": self.mark, "words": self.words}]
            self.reads += 1
            return self.rows

    agent = MemoryAgent.__new__(MemoryAgent)
    agent._word_class_index_schema_ready = True
    rows = [{"word": "dog", "word_class": "NOUN", "seen": 3},
            {"word": "barked", "word_class": "VERB", "seen": 2}]

    store = Store("the-same", 2, rows)
    agent._memory_db = lambda: store
    got = asyncio.run(agent._word_classes_worked_out_before("the-same"))
    assert got == {"dog": {"NOUN": 3}, "barked": {"VERB": 2}}, got

    # A different mark: the memories moved on, so the work is done again.
    store = Store("something-else", 2, rows)
    agent._memory_db = lambda: store
    assert asyncio.run(agent._word_classes_worked_out_before("the-same")) is None
    assert store.reads == 0, "it does not even read the rows where the mark differs"

    # The mark matches but the rows are not all there: a write was cut short.
    store = Store("the-same", 9999, rows)
    agent._memory_db = lambda: store
    assert asyncio.run(agent._word_classes_worked_out_before("the-same")) is None


def test_keeping_it_writes_every_word_and_the_mark_together():
    import asyncio

    class Store:
        def __init__(self):
            self.statements, self.many = [], []

        async def execute_query(self, query, params=None, **kw):
            self.statements.append((query.strip().split()[0], params))
            return None

        async def execute_many(self, query, rows):
            self.many.extend(rows)
            return len(rows)

    agent = MemoryAgent.__new__(MemoryAgent)
    agent._word_class_index_schema_ready = True
    store = Store()
    agent._memory_db = lambda: store

    index = {"dog": {"NOUN": 3}, "barked": {"VERB": 2, "NOUN": 1}}
    kept = asyncio.run(agent._keep_word_classes(index, "a-mark"))
    assert kept == 3, kept
    assert sorted(store.many) == [("barked", "NOUN", 1), ("barked", "VERB", 2), ("dog", "NOUN", 3)]
    # The old rows go first, so a word that stopped being seen as a class does not linger.
    assert store.statements[0][0] == "DELETE"
    # And the mark is written with how many words it covers, so a cut-short write can be told.
    assert any(verb == "INSERT" and params and params[0] == "a-mark" and params[1] == 2
               for verb, params in store.statements), store.statements
