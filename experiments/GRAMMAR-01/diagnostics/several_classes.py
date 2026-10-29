"""WHAT THE CLASS LESSONS' QUALITIES AND ADVERBS OF SEVERAL WORDS CALL ONE WORD, and how many of them are (2026-10-29,
lab notebook (81)): every run of two or three words a split's sentences say that WordNet holds as an adjective's or an
adverb's lemma of several words — which is what `WordNetSource._word_classes` states, and the only route to such a
word for a store with no record of it — against what the gold makes of that run, by `several_words.py`'s own reckoning
of a concept's own words (the words of its span no tighter span covers and the line does not mark as the grammar's).

A run is counted as the lessons state it: none whose words hold a pronoun ("to it" `thereto`, "on it"), which stands
for whatever was spoken of. `--with-pronouns` counts them as the lessons were first written, before the sentence they
cost was traced to one ("I'm totally indifferent to it.", lyric_dev2).

What a run is called here is what the grammar is OFFERED, not what it reads: an entry is weighed against the words
apart (`Lexicon._together`), and "kind of" before a noun is the grammar's own (`subkind`, lab notebook (75)), so a run
counted wrong here is not a reading gone wrong.

    ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/several_classes.py dev
"""
import collections, os, sys
from pathlib import Path
ROOT = Path(os.getcwd())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "GRAMMAR-01"))
sys.path.insert(0, str(ROOT / "experiments" / "GRAMMAR-01" / "diagnostics"))
from nltk.corpus import wordnet as wn
from core.semantics import pmb_meanings as pm
import several_words as sw

pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
PARTS = {"ADJECTIVE": (wn.ADJ, wn.ADJ_SAT), "ADVERB": (wn.ADV,)}


from core.semantics import grammar as gm
PRON = {w for w, uses in gm.closed_uses().items() if "pron" in uses}
WITH_PRONOUNS = "--with-pronouns" in sys.argv


def held_as(words):
    """Each kind of word WordNet holds the words as of several words, as the class lessons state them: none where a
    word of them is a pronoun, unless `--with-pronouns` asks for the lessons as they were first written."""
    if not WITH_PRONOUNS and {w.lower() for w in words} & PRON:
        return set()
    joined = "_".join(w.lower() for w in words)
    return {cls for cls, parts in PARTS.items() if any(wn.synsets(joined, p) for p in parts)}


def main(split: str) -> None:
    ids = pm.split_ids(pmb / "split" / "en" / split / ("gold.sbn" if split == "train" else "standard.sbn"))
    called: collections.Counter = collections.Counter()
    right: collections.Counter = collections.Counter()
    shapes: collections.Counter = collections.Counter()
    missed: collections.Counter = collections.Counter()
    examples: dict = collections.defaultdict(list)
    n_docs = 0
    for doc_id in ids:
        d = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        if d is None:
            continue
        n_docs += 1
        written = sw.words_of(d.text)
        one = sw.own_words(d, written)
        # What the gold makes one concept of, keyed by the words themselves, which is what the reader asks under.
        gold_runs = {}
        for at, (c, part, mine, with_marked) in one.items():
            senses = sw.senses_for(d, c)
            if len(with_marked) > len(mine) and sw.spelled_so(senses, with_marked) \
                    and not sw.spelled_so(senses, mine):
                mine = with_marked
            if len(mine) < 2:
                continue
            named = bool(getattr(c, "name", None))
            gold_runs[" ".join(w.lower() for w in mine)] = sw.shape_of(part, mine, named)
        words = [w for w, _, _ in written]
        for n in (2, 3):
            for k in range(len(words) - n + 1):
                run = words[k:k + n]
                if not all(w.isalpha() for w in run):
                    continue
                said = " ".join(w.lower() for w in run)
                for cls in held_as(run):
                    called[(n, cls)] += 1
                    shape = gold_runs.get(said)
                    if shape is None:
                        missed[(cls, said)] += 1
                        if len(examples[("wrong", cls)]) < 12:
                            examples[("wrong", cls)].append((said, d.text))
                        continue
                    right[(n, cls)] += 1
                    shapes[(cls, shape)] += 1
                    if len(examples[("right", cls)]) < 12:
                        examples[("right", cls)].append((said, shape))
    print(f"{n_docs} documents ({split}); every run of two or three words WordNet holds as a quality or an adverb of "
          f"several words, which the class lessons now state:")
    for cls in ("ADJECTIVE", "ADVERB"):
        for n in (2, 3):
            c, r = called[(n, cls)], right[(n, cls)]
            print(f"  {cls:10s} {n} words: calls {c:5d} one word, of them {r:4d} are "
                  f"({(100.0 * r / c if c else 0):.1f}%)")
        print("      the gold's shape where it is one: "
              + ", ".join(f"{shape} {times}" for (c2, shape), times in shapes.most_common() if c2 == cls))
        print("      most called wrongly: "
              + ", ".join(f"{said!r} {times}" for (c2, said), times in missed.most_common(10) if c2 == cls))
    for key in (("right", "ADJECTIVE"), ("wrong", "ADJECTIVE"), ("right", "ADVERB"), ("wrong", "ADVERB")):
        print(f"  {key[1]}, {key[0]}: " + "; ".join(f"{a!r} {b!r}"[:70] for a, b in examples[key][:6]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "dev")
