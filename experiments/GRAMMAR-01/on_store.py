"""GRAMMAR-01's measure (the PMB's held-out dev sentences, scored by GRAMMAR-01's own functions) read by the reader
memory holds on the store POSTGRES_DATABASE names, as it is after a warm. Reads only; nothing is written to the store.

WORDS_TEST names the sets of dev documents to read alone, one file or several separated by commas
(`taught_words_test.json`: 100 drawn whose words are all among the 228 it lists, 77 of them with a gold meaning;
`degree_test.json`, `denial_test.json`, `hyphenated_test.json`, `kind_of_test.json`, `clock_test.json`,
`participle_test.json`, `several_words_test.json`, each the dev documents of one thing said); unset, every dev
document with a gold meaning. Every set is read in one run, each document once, and scored on its own and on all of
them together, and the error budget printed by the link each fact says. RESULTS_OUT, a file each reading is written
to. SAY_BACK says back the meanings read right whole, senses aside, and scores how many the grammar says any sentence
for and whether the sentence it says first is the one the meaning was read from: a count of meanings to ask ("all" for
every one), each one's cost printed as it lands. It bounds how many are ASKED and never how long the grammar may
search, saying being unbounded where it fails (lab notebook (86)). Scored strict, senses aside (`senses_aside`), kinds aside, by their words with pronouns as unknowns (`named_by_their_words`,
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
    dev, doc_ids, unnamed = [], [], Counter()
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
        for c in document.concepts:
            if pm._SENSE.match(c.sense):
                unnamed["no name" if sense_name(c.sense) is None else "named"] += 1
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
        # sentence's things are linked, by which links, when, and what is asked. Two facts the kinds told apart are
        # one once they are set aside ("eighteen gold medals", a medal of gold), and a meaning says a fact once.
        return Meaning(m.act, tuple(dict.fromkeys(
            MeaningFact(f.relation, f.subject, "_" if f.relation in ("instance_of", "isa")
                        and not is_variable(f.obj) else f.obj, f.positive, f.condition,
                        f.alternative, f.unasserted, f.given) for f in m.facts)), m.asked)
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
    # THE ERROR BUDGET, the headline way: of the facts the gold says, how many the reading says, by the link each
    # says. A sentence is right only where every one of its facts is, so what a decision costs is what a sentence
    # costs: a share p of facts right is about p to the power of the facts a sentence says.
    budget: dict = {}
    per_sentence, facts_right, facts_said = Counter(), 0, 0
    for r, (_, _, m, _), ws in zip(readings, dev, sentence_words):
        want = g01.grounded(as_words(m, ws), is_variable)
        got = g01.grounded(as_words(r.meaning, ws), is_variable) if r.meaning is not None else Counter()
        for key, n in want.items():
            budget.setdefault(key[0], Counter())["gold"] += n
        for key, n in got.items():
            budget.setdefault(key[0], Counter())["read"] += n
        for key, n in (got & want).items():
            budget.setdefault(key[0], Counter())["right"] += n
        facts_right += sum((got & want).values())
        facts_said += sum(want.values())
        per_sentence[(sum((got & want).values()), sum(want.values()))] += 1
    print(f"\n  the error budget by the link said, {len(dev)} documents "
          f"({unnamed['named']} of the gold's concepts named by a sense of the measure's table, "
          f"{unnamed['no name']} it has no name for):")
    print(f"      {'link':22} {'gold':>6} {'read':>6} {'right':>6}   {'P':>6} {'R':>6} {'F1':>6}")
    for link, c in sorted(budget.items(), key=lambda x: -x[1]["gold"]):
        p = c["right"] / max(c["read"], 1)
        rc = c["right"] / max(c["gold"], 1)
        print(f"      {link:22} {c['gold']:6} {c['read']:6} {c['right']:6}   {p:6.1%} {rc:6.1%} "
              f"{2 * p * rc / max(p + rc, 1e-9):6.1%}")
    whole = sum(n for (right, said), n in per_sentence.items() if right == said and said)
    share = facts_right / max(facts_said, 1)
    says = facts_said / max(len(dev), 1)
    print(f"      facts right {facts_right} of {facts_said} ({share:.1%}); a sentence says {says:.1f} of them, "
          f"so {share ** says:.1%} of sentences would be right were they decided apart, and {whole} "
          f"({whole / max(len(dev), 1):.1%}) are")
    print("      sentences by how many of their facts are right: " + ", ".join(
        f"{right}/{said}: {n}" for (right, said), n in sorted(per_sentence.items(), key=lambda x: -x[1])[:10]))
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
    # SAID BACK (`SAY_BACK=1`): of the meanings read right whole, senses aside, how many the grammar says any
    # sentence for, and whether the sentence it says first is the one the meaning was read from.
    #
    # ON A STORE AND NOT FROM FILES, because what a thing is said WITH comes from memory and nowhere else
    # (`MemoryAgent.words_for`, "What `Grammar.say` says a thing with"): the word records' senses of the class, the
    # names the sentence records give, and -- where neither holds one -- THE THING'S OWN NAME, where memory names that
    # word as itself. GRAMMAR-01's file-held words pass no `written_for` at all, so `HeldWords.words_for` returns []
    # for every thing: measured files-only first, the grammar said something for 5 of 394 and said "Myself am from
    # Russia." for "I am from Russia.", which is the harness's figure and not the grammar's (2026-10-29).
    #
    # THE OWN-NAME FALLBACK IS WHAT CARRIES A STORE HOLDING NO RECORDS. Main (0 word records, 0 sentences recorded
    # whole, 94,262 word classes) says as many of its read-right meanings as the sandbox does with 559 records and
    # 6,137 record names -- 6 of 12 each -- and says them FASTER, because a thing with more words for it is a bigger
    # search: "I wash myself." 0.3s on main against 183.6s on the sandbox, "Your arm's broken." 0.0s against 267.2s.
    if os.environ.get("SAY_BACK"):
        t2 = time.time()
        asked = [(text, a) for (text, _, _, _), r, a in zip(dev, readings, aside)
                 if r.meaning is not None and r.meaning.canonical() == a.canonical()]
        # HOW MANY ARE ASKED, not how long each may take. `SAY_BACK` is a count ("all" for every one): the grammar is
        # left to search as far as it searches, because a meaning it cannot say is one it exhausts the agenda for, and
        # a cap here would report that as nothing said rather than as what it costs. Asked blind the first time, 39
        # minutes went into the first meanings of 35 and the run said nothing at all (2026-10-29).
        how_many = os.environ["SAY_BACK"]
        if how_many.strip().isdigit():
            asked = asked[:int(how_many)]
        plainly = lambda t: " ".join(str(t or "").strip().rstrip(".").lower().split())
        said_any = first_gold = among_gold = 0
        shown = []
        print(f"      saying back {len(asked)} of the meanings read right; each one's cost as it lands", flush=True)
        why_counts = Counter()
        for text, want in asked:
            at = time.time()
            # WHY, WHERE NOTHING IS SAID (`Grammar.say`'s `why`): seven different reasons used to arrive as the same
            # empty list, so half the meanings said nothing for a cause nobody could name.
            why_said: dict = {}
            sentences = list(view.say(want, why=why_said))
            # EACH ONE'S COST AS IT LANDS, never a cap: saying is chart generation and a meaning the grammar has many
            # words for is a real search. Measured blind the first time, 36 minutes said nothing at all (2026-10-29).
            reason = "" if sentences else str(why_said.get("why") or "?")
            if reason:
                why_counts[reason] += 1
            print(f"      {time.time() - at:7.1f}s  {len(sentences):3} said  {text[:44]:46}{reason}", flush=True)
            if reason and why_said.get("thing"):
                print(f"                 no word for: {why_said['thing']}", flush=True)
            if reason and "items" in why_said:
                # Not gated on anything being unsaid: where every word was said and reading refused every whole
                # sentence, `unsaid` is empty and this line is the only report of what it built (2026-10-30).
                print(f"                 {why_said.get('items', 0)} item(s) kept, {why_said.get('refused', 0)} "
                      f"read back otherwise {why_said.get('read_back_otherwise') or ''}"
                      + (f"; no word said for {why_said['unsaid']}" if why_said.get("unsaid") else ""), flush=True)
            said_any += bool(sentences)
            first_gold += bool(sentences) and plainly(sentences[0]) == plainly(text)
            among_gold += plainly(text) in {plainly(x) for x in sentences}
            if len(shown) < 12:
                shown.append((text, sentences[:2]))
        n = max(len(asked), 1)
        print(f"  said back, of the {len(asked)} read right whole senses aside ({time.time() - t2:.0f}s):")
        print(f"      says any sentence at all {said_any} ({said_any / n:.1%}); the gold sentence first "
              f"{first_gold} ({first_gold / n:.1%}); the gold sentence at all {among_gold} ({among_gold / n:.1%})")
        for reason, n in why_counts.most_common():
            print(f"      said nothing, why: {n:3}  {reason}")
        print(f"      words memory holds for things: {len(agent._grammar_words)} word record(s), "
              f"{len(agent._record_names)} name(s) the sentence records give")
        for text, sentences in shown:
            print(f"      {text}\n         said: {sentences}")
    why = Counter((r.why or "?") if r.meaning is None else "meaning" for r in readings)
    print("  no meaning, why:", why.most_common(6))
    for (text, _, want, _), r, a in list(zip(dev, readings, aside))[:12]:
        print(f"  {text}\n     gold: {a.canonical()}\n     read: {r.meaning.canonical() if r.meaning else r.why}")


asyncio.run(main())
