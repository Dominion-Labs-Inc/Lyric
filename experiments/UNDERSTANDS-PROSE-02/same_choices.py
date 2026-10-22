"""Whether `_least_claimed` grouped by cost leaves each reading exactly the choices of senses it won before: both run
on every call the reader makes while reading sentences outside UNDERSTANDS-PROSE-02 (01's texts and four of
Wikipedia's Volcano lead), and compared choice by choice (lab notebook 2026-10-22 (34)). Read only.

    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/UNDERSTANDS-PROSE-02/same_choices.py
"""
import asyncio
import contextlib
import io
import itertools
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())


def before(alike, view):
    """`_least_claimed` as it was: every choice of every sense tried."""
    from core.semantics import derived_reader as dr
    if len(alike) == 1:
        return list(alike)
    if not alike[0][1].senses:
        return [min(enumerate(alike), key=lambda pair: (dr._supposes(pair[1][1], view), pair[0]))[1]]
    words = [stand_in for stand_in, _, _, _ in alike[0][1].senses]
    each = [sorted({s.lexical.value for read in alike for w, options, _, _ in read[1].senses if w == word
                    for s in options}) for word in words]
    won = {}
    for chosen in itertools.product(*each):
        best = None
        for k, (_, filling) in enumerate(alike):
            narrowed = dr._narrowed(filling, dict(zip(words, (frozenset((v,)) for v in chosen))))
            if any(not options for _, options, _, _ in narrowed.senses):
                continue
            rank = (dr._supposes(narrowed, view), k)
            if best is None or rank < best:
                best = rank
        if best is not None:
            won.setdefault(best[1], []).append(chosen)
    out = []
    for k in sorted(won):
        adjunct, filling = alike[k]
        out.extend((adjunct, dr._narrowed(filling, region)) for region in dr._regions(words, won[k]))
    return out


def covered(alike, out):
    """Each choice of senses an output keeps, with the reading of `alike` it keeps it for."""
    found = set()
    for adjunct, filling in out:
        k = next(i for i, (a, f) in enumerate(alike) if a is adjunct and f.constructions == filling.constructions
                 and f.proposed == filling.proposed)
        values = [sorted({s.lexical.value for s in options}) for _, options, _, _ in filling.senses]
        found.update((k, combo) for combo in itertools.product(*values))
    return found


async def main():
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        agent = await get_memory_agent()
        await agent.initialize()
        await get_uncertainty_system().load_from_db()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
    from core.semantics import derived_reader as dr
    now = dr._least_claimed
    tally = {"calls": 0, "compared": 0, "same": 0, "differ": 0, "too_many_to_compare": 0,
             "seconds_before": 0.0, "seconds_now": 0.0, "largest_compared": 0}
    differ = []

    def both(alike, view):
        tally["calls"] += 1
        started = time.perf_counter()
        new = now(alike, view)
        tally["seconds_now"] += time.perf_counter() - started
        if len(alike) > 1 and alike[0][1].senses:
            words = [w for w, _, _, _ in alike[0][1].senses]
            size = 1
            for word in words:
                size *= len({s.lexical.value for read in alike for w, options, _, _ in read[1].senses if w == word
                             for s in options})
            if size > 20_000:
                tally["too_many_to_compare"] += 1
                return new
            started = time.perf_counter()
            old = before(alike, view)
            tally["seconds_before"] += time.perf_counter() - started
            tally["compared"] += 1
            tally["largest_compared"] = max(tally["largest_compared"], size)
            if covered(alike, old) == covered(alike, new):
                tally["same"] += 1
            else:
                tally["differ"] += 1
                differ.append(words)
        return new
    dr._least_claimed = both

    from core.agents.autonomous.autonomous_coordinator import get_conversation
    texts = json.load(open("experiments/UNDERSTANDS-PROSE-01/texts.json"))
    volcano = [
        "A volcano is a vent or fissure in the crust of a planetary-mass object that allows hot lava, volcanic ash, "
        "and gases to escape from a magma chamber below the surface.",
        "Volcanoes resulting from divergent tectonic activity are usually nonexplosive whereas those resulting from "
        "convergent tectonic activity cause violent eruptions.",
        "Historically, large volcanic eruptions have been followed by volcanic winters which have caused catastrophic "
        "famines.",
        "Large eruptions can affect atmospheric temperature as ash and droplets of sulfuric acid obscure the Sun and "
        "cool Earth's troposphere.",
    ]
    for n, said in enumerate([s for t in texts for s in t["text"]] + volcano):
        conversation = get_conversation(f"same_choices_{n}", remembers=False)
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await conversation.understand(said, look_up=False)
    print(json.dumps(tally, indent=1))
    print("differ on:", differ[:5])


asyncio.run(main())
