"""THE ERG'S MEANING AGAINST THE PMB'S GOLD, sentence by sentence, grouped by what differs.

The loop for `core/semantics/erg_meanings.py`: it names what each sentence gets wrong and counts the shapes, so a
convention is found by looking rather than guessed. Files only, no store, no learning -- the ERG uses nothing Lyric
learns, so this runs in seconds.

    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/erg_against_gold.py [N] [--show M]

`N` sentences of the dev split (all of them by default), `--show M` prints the first M that differ.
"""
import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "experiments" / "GRAMMAR-01"))

spec = importlib.util.spec_from_file_location("g01", ROOT / "experiments/GRAMMAR-01/experiment.py")
g01 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g01)

import erg_parse
from core.learning.teaching_sources import WordNetSource, file_words
from core.semantics import erg_meanings as em
from core.semantics import grammar as gm
from core.semantics import pmb_meanings as pm
from delphin import eds as edsmod
from delphin.codecs import simplemrs
from nltk.corpus import wordnet as wn


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 12
    pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
    words = file_words(ROOT / "test_data/syntax/UD_English-EWT/en_ewt-ud-train.conllu", gm.closed_uses())
    sense_names = WordNetSource()._sense_names()

    def sense_name(sense):
        try:
            return sense_names.get(wn.synset(sense)) or None
        except Exception:
            return None

    dev = []
    for doc_id in pm.split_ids(pmb / "split" / "en" / "dev" / "standard.sbn"):
        document = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        said = pm.meaning_of(document, sense_name) if document is not None else None
        if said is None or said.meaning is None:
            continue
        tokens = gm.tokens_of(document.text, words)
        anchors = tuple((t, tuple((document.concepts[k].span[0], document.concepts[k].span[1], how,
                                   document.concepts[k].marked) for k, how in at if document.concepts[k].span))
                        for t, at in said.anchors.items())
        dev.append((document.text, tokens, said.meaning, gm.align_by_anchors(tokens, document.text, anchors)))
        if want and len(dev) >= want:
            break
    print(f"{len(dev):,} dev sentences with a gold meaning", flush=True)

    blocks, _ = erg_parse.read([t for t, _, _, _ in dev], timeout=3600)
    right = unread = gapped = unnamed_right = 0
    shapes: Counter = Counter()
    told: Counter = Counter()
    shown = 0
    for (text, tokens, meaning, at), block in zip(dev, blocks):
        if block is None:
            unread += 1
            shapes["the ERG reads no whole"] += 1
            continue
        try:
            graph = edsmod.from_mrs(simplemrs.decode(block))
        except Exception as problem:
            shapes[f"no EDS: {type(problem).__name__}"] += 1
            continue
        said = em.meaning_of(graph)
        if said.meaning is None:
            gapped += 1
            for gap in said.gaps:
                shapes[f"gap: {gap.split(':')[0]}"] += 1
                told[gap] += 1
            continue
        names = {}
        spans = g01.offsets(text, tokens)
        for node in graph.nodes:
            lemma = em._lemma(node.predicate)
            if lemma is None or node.lnk is None or not node.lnk.data:
                continue
            a, b = node.lnk.data[0], node.lnk.data[-1]
            for k, span in enumerate(spans):
                if span and span[0] >= a and span[1] <= b:
                    names.setdefault(k, lemma[0])
        wanted = g01.senses_aside(meaning, at, names)
        # The one spoken of before taken as an unknown, as the PMB writes a pronoun: canonical renumbering then
        # lines `?previous` up with the gold's own variable (`pronouns_as_unknowns`).
        if g01.pronouns_as_unknowns(said.meaning).canonical() == wanted.canonical():
            unnamed_right += 1
        if said.meaning.canonical() == wanted.canonical():
            right += 1
            continue
        mine = {(f.relation, f.positive) for f in said.meaning.facts}
        theirs = {(f.relation, f.positive) for f in wanted.facts}
        for r, keep in sorted(theirs - mine):
            shapes[f"the gold says {r}{'' if keep else ' (not)'}, the ERG does not"] += 1
        for r, keep in sorted(mine - theirs):
            shapes[f"the ERG says {r}{'' if keep else ' (not)'}, the gold does not"] += 1
        if not (theirs - mine) and not (mine - theirs):
            shapes["the same links, joined otherwise"] += 1
        if shown < show:
            shown += 1
            print(f"\n-- {text!r}\n   gold: {wanted.canonical()}\n   erg : {said.meaning.canonical()}", flush=True)

    n = len(dev)
    print(f"\n{'right whole, senses aside':34} {right:>5} {right / n:>7.1%}")
    print(f"{'+ the one before unnamed':34} {unnamed_right:>5} {unnamed_right / n:>7.1%}")
    print(f"{'the ERG read no whole':34} {unread:>5} {unread / n:>7.1%}")
    print(f"{'the meaning language cannot say':34} {gapped:>5} {gapped / n:>7.1%}")
    print(f"{'read, meaning differs':34} {n - right - unread - gapped:>5} "
          f"{(n - right - unread - gapped) / n:>7.1%}")
    print(f"\nwhat differs, most first:")
    for shape, k in shapes.most_common(26):
        print(f"  {k:>5}  {shape}")
    if told:
        print(f"\nthe gaps by name, most first:")
        for gap, k in told.most_common(14):
            print(f"  {k:>5}  {gap}")


if __name__ == "__main__":
    main()
