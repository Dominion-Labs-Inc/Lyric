"""GRAMMAR-01's measure (the PMB's held-out dev sentences, scored by GRAMMAR-01's own functions) read by the reader
memory holds on the store POSTGRES_DATABASE names, as it is after a warm. Reads only; nothing is written to the store.

WORDS_TEST names the sets of dev documents to read alone, one file or several separated by commas
(`taught_words_test.json`: 100 drawn whose words are all among the 228 it lists, 77 of them with a gold meaning;
`degree_test.json`, `denial_test.json`, `hyphenated_test.json`, `kind_of_test.json`, `clock_test.json`,
`participle_test.json`, each the dev documents of one thing said). Every set is read in one run, each document once,
and scored on its own and on all of them together. RESULTS_OUT, a file each reading is written to. Scored strict,
senses aside (`senses_aside`), kinds aside, by their words with pronouns as unknowns (`named_by_their_words`,
`pronouns_as_unknowns`), and kinds aside with pronouns as unknowns. From the Lyric folder:

    WORDS_TEST=experiments/GRAMMAR-01/taught_words_test.json POSTGRES_DATABASE=lyric_dev2 \
        ./venv_lyric/bin/python3 experiments/GRAMMAR-01/on_store.py
"""
import asyncio, contextlib, io, os, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(os.getcwd())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "GRAMMAR-01"))


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
    print(f"store {os.environ.get('POSTGRES_DATABASE')}: memory warm {time.time() - t0:.0f}s, "
          f"word records {len(agent._grammar_words)}, sentence records {len(agent._grammar_records)}, "
          f"analysed sentences {len(agent.structure_view())}", flush=True)
    import experiment as g01
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import WordNetSource
    from core.semantics import grammar as gm, pmb_meanings as pm
    from core.semantics.derived_reader import is_variable
    pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
    sense_names = WordNetSource()._sense_names()

    def sense_name(sense):
        try:
            return sense_names.get(wn.synset(sense)) or None
        except Exception:
            return None
    dev, doc_ids = [], []
    import json as _json
    sets = [(Path(f.strip()).stem.replace("_test", ""), {d for d, _ in _json.load(open(f.strip()))["drawn"]})
            for f in (os.environ.get("WORDS_TEST") or "").split(",") if f.strip()]
    only = set().union(*(ids for _, ids in sets)) if sets else None
    for doc_id in pm.split_ids(pmb / "split" / "en" / "dev" / "standard.sbn"):
        if only is not None and doc_id not in only:
            continue
        document = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        said = pm.meaning_of(document, sense_name) if document is not None else None
        if said is None or said.meaning is None:
            continue
        tokens = gm.tokens_of(document.text, view.words)
        anchors = tuple((t, tuple((document.concepts[k].span[0], document.concepts[k].span[1], how,
                                   document.concepts[k].marked) for k, how in at if document.concepts[k].span))
                        for t, at in said.anchors.items())
        dev.append((document.text, tokens, said.meaning, gm.align_by_anchors(tokens, document.text, anchors)))
        doc_ids.append(doc_id)
    t1 = time.time()
    readings = [view.grammar.read(tokens) for _, tokens, _, _ in dev]
    print(f"read {len(dev)} PMB dev sentences in {time.time() - t1:.0f}s", flush=True)
    names_of = []
    for r in readings:
        names = {}
        if r.sign is not None:
            for p in r.sign.pieces:
                if p[0] == "word":
                    for k in range(p[3], p[4]):
                        names.setdefault(k, p[1])
        names_of.append(names)
    aside = [g01.senses_aside(m, at, names) for (_, _, m, at), names in zip(dev, names_of)]
    whole = sum(r.sign is not None for r in readings)
    meant = sum(r.meaning is not None for r in readings)
    print(f"read whole {whole} of {len(dev)}; given a meaning {meant}")
    from core.semantics.derived_reader import Meaning, MeaningFact

    def kinds_aside(m):
        # Every kind a thing is named as set aside, in the gold and the reading alike: what is left is how the
        # sentence's things are linked, by which links, when, and what is asked.
        return Meaning(m.act, tuple(MeaningFact(f.relation, f.subject, "_" if f.relation in ("instance_of", "isa")
                                                and not is_variable(f.obj) else f.obj, f.positive, f.condition,
                                                f.alternative, f.unasserted, f.given) for f in m.facts), m.asked)
    senses_named = {}
    for synset, name in sense_names.items():
        senses_named.setdefault(name, []).append(synset)
    sentence_words = [g01.words_of_sentence(tokens) for _, tokens, _, _ in dev]

    def as_words(m, words):
        return g01.pronouns_as_unknowns(g01.named_by_their_words(m, words, senses_named))
    for way, wanted in (("strict", [m for _, _, m, _ in dev]), ("senses aside", aside),
                        ("kinds aside", [kinds_aside(m) for _, _, m, _ in dev]),
                        ("by their words, pronouns as unknowns", [as_words(m, ws) for (_, _, m, _), ws
                                                                   in zip(dev, sentence_words)]),
                        ("kinds aside, pronouns as unknowns", [kinds_aside(g01.pronouns_as_unknowns(m))
                                                               for _, _, m, _ in dev])):
        def scored(which):
            # Of the documents `which` names, how many readings are the meaning wanted whole, and the facts' P, R, F1.
            right = tp = fp = fn = 0
            for doc_id, r, want, ws in zip(doc_ids, readings, wanted, sentence_words):
                if doc_id not in which:
                    continue
                w = g01.grounded(want, is_variable)
                if r.meaning is None:
                    fn += sum(w.values())
                    continue
                got = kinds_aside(r.meaning) if way == "kinds aside" else as_words(r.meaning, ws) \
                    if way.startswith("by their words") else kinds_aside(g01.pronouns_as_unknowns(r.meaning)) \
                    if way == "kinds aside, pronouns as unknowns" else r.meaning
                right += got.canonical() == want.canonical()
                g = g01.grounded(got, is_variable)
                tp += sum((g & w).values()); fp += sum((g - w).values()); fn += sum((w - g).values())
            n = sum(d in which for d in doc_ids)
            p, rc = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
            return (f"whole right {right} of {n} ({right / max(n, 1):.1%}); facts P {p:.1%} R {rc:.1%} "
                    f"F1 {2 * p * rc / max(p + rc, 1e-9):.1%}")
        print(f"  {way}: {scored(set(doc_ids))}")
        for name, ids in sets if len(sets) > 1 else ():
            print(f"      {name}: {scored(ids)}")
    if os.environ.get("RESULTS_OUT"):
        _json.dump([{"text": text, "sets": [name for name, ids in sets if doc_id in ids],
                     "gold": a.canonical(), "read": r.meaning.canonical() if r.meaning else r.why,
                     "right": r.meaning is not None and r.meaning.canonical() == a.canonical(),
                     "gold_words": as_words(m, ws).canonical(),
                     "read_words": as_words(r.meaning, ws).canonical() if r.meaning else r.why,
                     "right_words": r.meaning is not None and as_words(r.meaning, ws).canonical()
                     == as_words(m, ws).canonical()}
                    for (text, _, m, _), r, a, ws, doc_id in zip(dev, readings, aside, sentence_words, doc_ids)],
                   open(os.environ["RESULTS_OUT"], "w"), indent=1)
    why = Counter((r.why or "?") if r.meaning is None else "meaning" for r in readings)
    print("  no meaning, why:", why.most_common(6))
    for (text, _, want, _), r, a in list(zip(dev, readings, aside))[:12]:
        print(f"  {text}\n     gold: {a.canonical()}\n     read: {r.meaning.canonical() if r.meaning else r.why}")


asyncio.run(main())
