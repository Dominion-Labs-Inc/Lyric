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


def test_the_mark_is_asked_of_the_store_and_costs_no_fetch():
    """A question that costs the fetch cannot save it. The three sets the warm works the classes out of are
    592,253 memories and 176 MB, and the only thing worth knowing before reading them is whether they have
    CHANGED -- so the mark is counted in the store and nothing comes back but a number for each tag.

    It is counted over the same tables and owners `_rows_tagged` reads, or it would answer for a different set
    of memories than the work is done from. A count alone would serve a stale answer wherever a memory was
    replaced rather than added, so the ids are summed too; summed rather than hashed in order, because nothing
    guarantees the order rows come back in between starts."""
    import asyncio

    class Store:
        def __init__(self):
            self.asked = []
            self.counts = {"admitted_proposition": (592233, 111), "told_but_unread": (20, 7),
                           "word_class": (94683, 55)}

        def maintained_stores(self):
            return ["main"]

        async def execute_query(self, query, params=None, **kw):
            import json
            assert "count(*)" in query and "md5(memory_id)" in query, query
            assert "memory_hot" in query or "memory_cold" in query, "both tiers are read"
            assert "user_id" in query, "the same owners `_rows_tagged` reads"
            tag = json.loads(params[0])[0]
            self.asked.append((tag, "memory_hot" in query))
            n, s = self.counts.get(tag, (0, 0))
            return [{"n": n if "memory_hot" in query else 0, "s": s if "memory_hot" in query else 0}]

    agent = MemoryAgent.__new__(MemoryAgent)
    store = Store()
    agent._memory_db = lambda: store
    mark = asyncio.run(agent._tagged_mark("admitted_proposition", "told_but_unread", "word_class"))
    assert mark == "592233:111|20:7|94683:55", mark
    # Both tiers of each store, for each tag, and nothing else.
    assert len(store.asked) == 6, store.asked
    # One memory more and the mark differs, so the work is done again.
    store.counts["admitted_proposition"] = (592234, 111)
    assert asyncio.run(agent._tagged_mark("admitted_proposition", "told_but_unread", "word_class")) != mark
    # One memory REPLACED: the count is the same and the sum is not.
    store.counts["admitted_proposition"] = (592233, 112)
    assert asyncio.run(agent._tagged_mark("admitted_proposition", "told_but_unread", "word_class")) != mark


def test_the_index_is_read_back_only_where_the_memories_are_the_same():
    """And a half-written answer is never read back: the rows and the count of words are written together, so
    disagreeing means a write was cut short."""
    import asyncio

    class Store:
        def __init__(self, mark, words, rows, sentences=686936):
            self.mark, self.words, self.rows = mark, words, rows
            self.sentences, self.reads = sentences, 0

        async def execute_query(self, query, params=None, **kw):
            q = query.strip()
            if q.startswith(("CREATE", "DELETE", "INSERT", "ALTER")):
                return None
            if "word_class_index_from" in q:
                return [{"mark": self.mark, "words": self.words, "sentences": self.sentences}]
            self.reads += 1
            return self.rows

    agent = MemoryAgent.__new__(MemoryAgent)
    agent._word_class_index_schema_ready = True
    rows = [{"word": "dog", "word_class": "NOUN", "seen": 3},
            {"word": "barked", "word_class": "VERB", "seen": 2}]

    store = Store("the-same", 2, rows)
    agent._memory_db = lambda: store
    index, worked_out_from = asyncio.run(agent._word_classes_worked_out_before("the-same"))
    assert index == {"dog": {"NOUN": 3}, "barked": {"VERB": 2}}, index
    # HOW MANY MEMORIES IT WAS WORKED OUT FROM COMES BACK WITH IT. On this path the memories are never
    # fetched, so the warm has no count of its own: reporting the sets' lengths said "197127 word(s) ...
    # worked out of 0 sentence(s)" about a complete index (2026-11-19 12:28).
    assert worked_out_from == 686936, worked_out_from

    # An index kept before the count was recorded says so rather than claiming a number.
    store = Store("the-same", 2, rows, sentences=None)
    agent._memory_db = lambda: store
    assert asyncio.run(agent._word_classes_worked_out_before("the-same"))[1] is None

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


def test_the_names_those_sentences_hold_are_kept_beside_the_classes():
    """Everything the warm takes from a taught proposition is the classes it implies and the names it holds.
    Keeping the classes alone would have left the warm fetching 176 MB of sentences for the names and nothing
    else, so the names are kept under the same mark and read back with them."""
    import asyncio

    class Store:
        def __init__(self):
            self.rows, self.many, self.deleted = [], [], []

        async def execute_query(self, query, params=None, **kw):
            q = query.strip()
            if q.startswith("DELETE"):
                self.deleted.append(q)
            elif q.startswith("SELECT") and "names_memory_holds" in q:
                return self.rows
            return None

        async def execute_many(self, query, rows):
            self.many.extend(rows)
            return len(rows)

    agent = MemoryAgent.__new__(MemoryAgent)
    agent._word_class_index_schema_ready = True
    store = Store()
    agent._memory_db = lambda: store

    holds = frozenset({("credit", "card"), ("hair", "dryer")})
    particular = frozenset({("marie", "curie")})
    kept = asyncio.run(agent._keep_names(holds, particular))
    assert kept == 3, kept
    assert sorted(store.many) == [("holds", "credit card"), ("holds", "hair dryer"),
                                  ("particular", "marie curie")]
    assert store.deleted, "the old names go first, so one no longer held does not linger"

    # And read back, each name as its words again.
    store.rows = [{"which": "holds", "name": "credit card"}, {"which": "holds", "name": "hair dryer"},
                  {"which": "particular", "name": "marie curie"}]
    back_holds, back_particular = asyncio.run(agent._names_worked_out_before())
    assert back_holds == holds, back_holds
    assert back_particular == particular, back_particular
