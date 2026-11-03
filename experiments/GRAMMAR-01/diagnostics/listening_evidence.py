"""WHY THE LISTENER'S EVIDENCE IS EMPTY, on the store `POSTGRES_DATABASE` names. Reads only.

`listener_on_store.py` found the listener taking exactly what the reader's own first reading was, on every width, on
both stores, while every sentence traced "memory asked, knew nothing of any reading". This drives the path `meant`
uses -- two composed readings through `listening` on a warmed agent -- to show that is neither a wiring fault nor an
empty store, and what it is:

  1. `listening_worths` is 0 of 10 non-zero, on lyric_dev AND on lyric_db with its 6,137 taught sentences. The three
     channels those gate (`known`, `defined`, `fit`) are multiplied by zero, so what memory holds of a reading's
     facts counts for nothing however firmly it holds it. The pass that learns them exists and has never been run
     (`listening_counts` -> `listening_claim` beliefs -> `listening_worths`).

  2. The two channels that need no worths are computed over `senses` alone -- the things each reading names that the
     others do not (`listening`: `for terms in own.values(): senses.update(terms)`). Readings that differ in HOW THE
     WORDS GO TOGETHER name the same things, so `senses` is empty by construction and `related` and `selected`
     cannot tell them apart at all. `owns(spider, leg)` against `has_part(spider, leg)` names spider and leg either
     way.

So the listener's evidence is built for which thing a word names, and a wide chart hands it readings that differ in
structure. Memory is reachable throughout: `word_kinds('dog')` answers with five kinds in the same process.

    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 \
        experiments/GRAMMAR-01/diagnostics/listening_evidence.py
"""
import asyncio, contextlib, io, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(os.getcwd())))


async def main():
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        agent = await get_memory_agent()
        await agent.initialize()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
    from core.agents.memory_agent import memory_agent
    from core.agents import memory_agent as mod
    from core.semantics.derived_reader import (Meaning, MeaningFact as F, Reading, held_key,
                                               listening, listening_facts)
    inv = agent.pattern_inventory()
    print(f"store {os.environ.get('POSTGRES_DATABASE')}: words {len(agent._grammar_words)}, "
          f"sentences {len(agent._grammar_records)}")
    print(f"  memory_agent() is the warmed agent: {memory_agent() is agent}; module global: {mod._memory_agent is agent}")
    w = inv.listening_worths()
    print(f"  listening worths: {sum(1 for v in w.values() if v)} of {len(w)} non-zero")

    def composed(facts):
        return Reading((), (), Meaning("tell", tuple(facts)), composed=True)

    pairs = {
        "a dog that barks, against a dog that is a kind": (
            composed([F("instance_of", "?v0", "dog"), F("instance_of", "?v1", "bark"),
                      F("done_by", "?v1", "?v0")]),
            composed([F("instance_of", "?v0", "dog"), F("isa", "dog", "bark")])),
        "the spider's legs, owned against part of": (
            composed([F("instance_of", "?v0", "leg"), F("instance_of", "?v1", "spider"),
                      F("owns", "?v1", "?v0")]),
            composed([F("has_part", "spider", "leg")])),
    }
    for name, (a, b) in pairs.items():
        facts = {held_key(f) for r in (a, b) for f in listening_facts(r.meaning)}
        heard = await listening([(a, b)])
        held, related, selected, together, defined = heard
        print(f"\n  {name}")
        print(f"    facts listening would ask about: {len(facts)}  e.g. {sorted(facts)[:2]}")
        print(f"    held     {len(held)}  {dict(list(held.items())[:2]) if held else '{}'}")
        print(f"    related  {len(related)}  {dict(list(related.items())[:3]) if related else '{}'}")
        print(f"    selected {len(selected)}  {dict(list(selected.items())[:2]) if selected else '{}'}")
        print(f"    defined  {len(defined)}  {dict(list(defined.items())[:2]) if defined else '{}'}")
        print(f"    together {len(together)}")
    # Does memory hold anything about a dog at all, asked its own way?
    print(f"\n  agent.word_kinds('dog') -> {agent.word_kinds('dog')[:5]}")

asyncio.run(main())
