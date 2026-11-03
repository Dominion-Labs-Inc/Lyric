"""WHICH OF THE READINGS THE LISTENER IS HANDED IT ACTUALLY TAKES, on the store `POSTGRES_DATABASE` names, with
memory up. Reads only; nothing is written.

`nbest.py` measured the two stages a files-only run can reach: whether the right reading is in the chart, and
whether it is among those handed up. It cannot reach the third — what `derived_reader.meant` SELECTS — because four
of the listener's five evidence channels are memory's (`held`, `defined`, `selected`, `related`) and a files-only
reading has no memory. This is that third stage:

  the right reading is among those handed up   - the ceiling the listener receives (nbest.py reached 58.7% at fifty)
  the listener takes the right one             - the actual improvement
  and, per sentence, WHY it took what it took  - `meant`'s own trace (`_listening_said`)

It calls the two functions that decide — `Grammar.readings` and `meant`, with `listening` between them, as
`_read_by_composing` and the conversation call them — and keeps each grammar sign beside its composed reading so the
gold can be scored the way every earlier GRAMMAR-01 number was scored (`senses_aside`, which renames the gold by the
reading's own word names and so cannot be computed from a composed reading alone).

    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 \
        experiments/GRAMMAR-01/diagnostics/listener_on_store.py 400 1,6,25
"""
import asyncio, contextlib, io, json, math, os, random, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(os.getcwd())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "GRAMMAR-01"))

HOW_MANY = int(sys.argv[1]) if len(sys.argv) > 1 else 400
KS = [int(k) for k in (sys.argv[2] if len(sys.argv) > 2 else "1,6,25").split(",")]


async def main():
    quiet = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        agent = await get_memory_agent()
        await agent.initialize()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
    view = agent.grammar_view()
    view.learn_waiting()
    inventory = agent.pattern_inventory()
    print(f"store {os.environ.get('POSTGRES_DATABASE')}: memory warm {time.time() - t0:.0f}s, "
          f"word records {len(agent._grammar_words)}, sentence records {len(agent._grammar_records)}", flush=True)

    # WHAT THE LISTENER'S EVIDENCE IS WORTH, printed first: each channel counts for exactly this, and an unlearned
    # listener values memory knowing a reading's facts at nothing however firmly it holds them.
    worths = inventory.listening_worths()
    print(f"listening worths ({len(worths)} learned): "
          + (", ".join(f"{e}@{l} {v:+.2f}" for (e, l), v in sorted(worths.items())) or "NONE LEARNED"), flush=True)

    import experiment as g01
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import WordNetSource
    from core.semantics import grammar as gm, pmb_meanings as pm
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import Meaning, MeaningFact, Reading, listening, meant
    from core.semantics.composition import ASKING

    pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
    sense_names = WordNetSource()._sense_names()

    def sense_name(sense):
        try:
            return sense_names.get(wn.synset(sense)) or None
        except Exception:
            return None

    def names_of(sign):
        names = {}
        for p in sign.pieces:
            if p[0] == "word":
                for k in range(p[3], p[4]):
                    names.setdefault(k, p[1])
        return names

    def unnamed(meaning):
        """The one spoken of before written as an unknown of its own, as the PMB writes a pronoun."""
        rename = {"?previous": "?before"}
        return Meaning(meaning.act, tuple(MeaningFact(f.relation, rename.get(f.subject, f.subject),
                                                      rename.get(f.obj, f.obj), f.positive, f.condition,
                                                      f.alternative, f.unasserted, f.given)
                                          for f in meaning.facts),
                       tuple(rename.get(a, a) for a in meaning.asked))

    dev = []
    for doc_id in pm.split_ids(pmb / "split" / "en" / "dev" / "standard.sbn"):
        document = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        said = pm.meaning_of(document, sense_name) if document is not None else None
        if said is None or said.meaning is None:
            continue
        tokens = gm.tokens_of(document.text, view.words)
        anchors = tuple((t, tuple((document.concepts[k].span[0], document.concepts[k].span[1], how,
                                   document.concepts[k].marked) for k, how in at if document.concepts[k].span))
                        for t, at in said.anchors.items())
        dev.append((document.text, tokens, said.meaning,
                    gm.align_by_anchors(tokens, document.text, anchors), doc_id))
    random.Random(1).shuffle(dev)
    dev = dev[:HOW_MANY]
    print(f"dev/standard: {len(dev)} sentences, readings asked for {KS}", flush=True)

    out = {}
    for k in KS:
        got = Counter()
        hows = Counter()
        rows, overruled = [], []
        t1 = time.time()
        for text, tokens, gold, at, doc_id in dev:
            # The reader's half, as `_read_by_composing` asks it, each grammar reading kept beside its own sign.
            said, signs = [], []
            first = next((str(t) for t in tokens if any(c.isalnum() for c in str(t))), "").lower()
            for read in view.grammar.readings(tokens, k):
                m = read.meaning
                if m is None or all(f.given for f in m.facts):
                    continue
                if m.act == "ask" and not m.asked and first in ASKING:
                    continue
                said.append(Reading(dr._said_by_words(read), (), m, composed=True,
                                    structure=math.log(read.ranked) if read.ranked > 0 else 0.0))
                signs.append(read.sign)
            if not said:
                got["said nothing"] += 1
                continue
            right = {i for i, (r, sg) in enumerate(zip(said, signs)) if sg is not None
                     and unnamed(r.meaning).canonical() == g01.senses_aside(gold, at, names_of(sg)).canonical()}
            got["handed up"] += len(said)
            got["the reader's own first is right"] += 0 in right  # named FIRST where it is printed
            got["the right reading is among those handed up"] += bool(right)
            # The listener's half, as the conversation asks it.
            heard = await listening([tuple(said)])
            why = {}
            took = meant(said, inventory, heard=heard, why=why)
            hows[why.get("how", "no why")] += 1
            at_took = next((i for i, r in enumerate(said) if r is took), None)
            got["the listener took one"] += took is not None
            got["the listener took the right one"] += at_took in right if at_took is not None else False
            if right and at_took is not None and at_took not in right:
                rows.append({"text": text, "right at": sorted(right), "took": at_took, "how": why.get("how"),
                             "weighed": why.get("weighed", [])[:4], "memory": why.get("memory")})
            # THE LISTENER OVERRULING A READER THAT WAS RIGHT is the only thing that can cost against the reader's
            # own first; everything else it gets wrong, the reader got wrong too.
            if 0 in right and at_took not in (None, 0):
                overruled.append({"text": text, "took": at_took, "how": why.get("how"),
                                  "memory": why.get("memory"), "weighed": why.get("weighed", [])[:4]})
        n = len(dev)
        took_right = got["the listener took the right one"]
        out[k] = {key: got[key] for key in got} | {"sentences": n, "seconds": time.time() - t1,
                                                   "how": dict(hows), "lost": rows[:25],
                                                   "overruled a right reader": overruled}
        print(f"\n  === readings asked for: {k} ===", flush=True)
        print(f"  {got['handed up'] / n:.1f} readings handed up per sentence, said nothing {got['said nothing']}",
              flush=True)
        FIRST = "the reader's own first is right"
        print(f"  the reader's own first is right            {got[FIRST]}/{n} ({got[FIRST] / n:.1%})", flush=True)
        print(f"  the right reading is among those handed up {got['the right reading is among those handed up']}/{n} "
              f"({got['the right reading is among those handed up'] / n:.1%})", flush=True)
        print(f"  THE LISTENER TOOK THE RIGHT ONE            {took_right}/{n} ({took_right / n:.1%})", flush=True)
        print(f"  the listener took something: {got['the listener took one']}/{n}, {time.time() - t1:.0f}s", flush=True)
        print("  how it decided:", flush=True)
        for h, c in hows.most_common(8):
            print(f"      {c:4}  {h}", flush=True)
        if overruled:
            print(f"  IT OVERRULED A READER THAT WAS RIGHT {len(overruled)} times — the whole of what it costs:",
                  flush=True)
            for r in overruled:
                print(f"      {r['text']}", flush=True)
                print(f"        took {r['took']} — {r['how']}; {r['memory']}", flush=True)
                for i, w in enumerate(r["weighed"]):
                    print(f"          [{i}] total {w['total']:+9.4f} = structure {w['structure']:+.4f} "
                          f"+ met/raised {w['activation']:+.4f} + worths "
                          f"{sum(w['worth'].values()):+.2f} (known {w['known']}, defined {w['defined']}, "
                          f"fit {w['fit']}) | {w['meaning'][:62]}", flush=True)
        if rows:
            print(f"  it had the right reading and took another, {len(rows)} times, e.g.:", flush=True)
            for r in rows[:3]:
                print(f"      {r['text']}", flush=True)
                print(f"        right at {r['right at']}, took {r['took']} — {r['how']}; {r['memory']}", flush=True)
                for w in r["weighed"]:
                    print(f"          {w['total']:+8.3f} known {w['known']} worth {w['worth'].get('known', 0):+.2f} "
                          f"| structure {w['structure']:+.2f} | {w['meaning'][:70]}", flush=True)

    where = Path("experiments/GRAMMAR-01/diagnostics/listener_on_store.json")
    where.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {where}", flush=True)


asyncio.run(main())
