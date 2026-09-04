#!/usr/bin/env python3
"""TEACH the substrate English from WordNet, through its ONE learning path.

WordNet is a hand-built lexical resource -- it is knowledge, so the substrate
learns it the same way it learns anything, through the learning authority. Two
things are taught, and they are kept apart on purpose:

  1. PARTS OF SPEECH (`learning.learn_words`) -- every single-word lemma with a
     clear dominant class (noun / verb / adjective), so the reader can read a
     sentence built from words it was never shown one at a time. WordNet's own
     POS tags are the source; a word used in more than one class with no clear
     winner is left for the reader to settle in context (the lexicon's
     confirm/refute) rather than guessed here.

  2. THE NOUN TAXONOMY (`learning.learn_facts`) -- `<child> isa <parent>` edges
     from hypernyms, into the concept graph the reasoner walks. Taught with
     remember=False (a reference taxonomy is knowledge, not a conversation to
     recall) and fan_out=False (the class of every term is taught directly in
     step 1, correctly, instead of being guessed from an article that a bare
     `child isa parent` surface does not have).

  --limit N   teach only the first N of each (smoke test)
Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 scripts/teach_wordnet_taxonomy.py [--limit N]
"""
import os, sys, asyncio, io, contextlib, time
os.environ.setdefault("TQDM_DISABLE", "1")

_POS_CLASS = {"n": "NOUN", "v": "VERB", "a": "ADJECTIVE", "s": "ADJECTIVE"}


def _name(syn):
    return syn.lemma_names()[0].replace("_", " ").strip().lower()


def build_edges():
    """`(child, parent)` ISA edges from noun hypernyms and instance-hypernyms."""
    from nltk.corpus import wordnet as wn
    edges = set()
    for syn in wn.all_synsets("n"):
        child = _name(syn)
        if not child:
            continue
        for hyper in syn.hypernyms() + syn.instance_hypernyms():
            parent = _name(hyper)
            if parent and parent != child:
                edges.add((child, parent))
    return sorted(edges)


def build_pos():
    """`(word, CLASS)` for every single alpha word with a clear dominant class.

    A lemma is scored per part of speech by its tagged-corpus frequency (falling
    back to how many senses carry it when nothing is tagged). The class with the
    most weight wins; a tie -- a word as much a noun as a verb -- is skipped, so
    an ambiguous word is learned from use, not stamped here."""
    from nltk.corpus import wordnet as wn
    from collections import defaultdict
    weight = defaultdict(lambda: defaultdict(float))
    for syn in wn.all_synsets():
        cls = _POS_CLASS.get(syn.pos())
        if not cls:
            continue
        for lemma in syn.lemmas():
            word = lemma.name().replace("_", " ").strip().lower()
            if " " in word or not word.isalpha():
                continue
            weight[word][cls] += lemma.count() + 0.01   # 0.01: a sense with no tags still counts a little
    out = []
    for word, by_class in weight.items():
        ranked = sorted(by_class.items(), key=lambda kv: kv[1], reverse=True)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue                                     # genuinely ambiguous -> learn in context
        out.append((word, ranked[0][0]))
    return sorted(out)


async def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        s = get_system(); await s.initialize()
        learning = s.autonomous_coordinator.learning
        from core.semantics.cognitive_ingress import Provenance

    # ── 1. parts of speech ────────────────────────────────────────────────
    pos = build_pos()
    if limit:
        pos = pos[:limit]
    print(f"teaching {len(pos):,} parts of speech through learn_words…", flush=True)
    t0 = time.monotonic()
    pc = learning.learn_words(pos, source="wordnet", authoritative=True)
    print(f"  parts of speech: proposed={pc['proposed']:,} already={pc['already']:,} "
          f"refused={pc['refused']:,} of {pc['total']:,}  "
          f"({pc['total'] / max(0.001, time.monotonic() - t0):.0f}/s)", flush=True)

    # ── 2. noun taxonomy ──────────────────────────────────────────────────
    edges = build_edges()
    if limit:
        edges = edges[:limit]
    prov = Provenance(producer="lexical", source_id="wordnet", source_type="USER_SUPPLIED")
    total = len(edges)
    print(f"teaching {total:,} WordNet ISA facts through learn_facts…", flush=True)
    t1 = time.monotonic()

    def report(c):
        rate = c["total"] / max(0.001, time.monotonic() - t1)
        eta = (total - c["total"]) / max(0.001, rate)
        print(f"  {c['total']:,}/{total:,}  admitted={c['admitted']:,} "
              f"already={c['already']:,} refused={c['refused']:,}  "
              f"({rate:.0f}/s, eta {eta/60:.0f}m)", flush=True)

    facts = ((child, "isa", parent) for child, parent in edges)
    counts = await learning.learn_facts(facts, provenance=prov, domain="lexical",
                                        fan_out=False, remember=False, progress=report)
    report(counts)
    print(f"done: taxonomy {counts['admitted']:,} admitted / {counts['already']:,} held / "
          f"{counts['refused']:,} refused of {counts['total']:,}; "
          f"vocabulary +{pc['proposed']:,} words", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
