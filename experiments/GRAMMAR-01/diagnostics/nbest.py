"""WHAT KEEPING MORE THAN ONE READING OF EACH CATEGORY BUYS, measured stage by stage over the PMB's held-out dev part.

The chart kept one reading of each category of each stretch, the surest (Viterbi's), so a reading of the whole that
needed a stretch read otherwise was never built: the grammar chose right for 54.2% of these sentences where a chart
keeping EVERY reading held the right one for 61.8% (`every_reading.py`, 2026-11-03). `Grammar.charts` now keeps
`how_many` of each. This sweeps it and reports, for each:

  reading the grammar puts first is right   - what the reader alone gains from searching wider
  right among the readings handed up        - the ceiling a listener that receives them could reach
  seconds per sentence                      - what it costs

Files only; asks memory nothing, so it does not measure which of the readings handed up a listener would TAKE
(`derived_reader.meant` weighs what memory knows of what each says, and there is no memory here). That is the next
stage and it needs a store.

    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/nbest.py dev/standard 400 1,2,3,4
"""
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
S = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "GRAMMAR-01"))
spec = importlib.util.spec_from_file_location("rl", ROOT / "experiments" / "READ-LEARN-01" / "experiment.py")
rl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rl)
g01 = rl.g01

from nltk.corpus import wordnet as wn
from core.learning.teaching_sources import ListeningSource, PMBSource, WordNetSource
from core.semantics import grammar as gm
from core.semantics import pmb_meanings as pm
from core.semantics.composition import TaughtSentence
from core.semantics.derived_reader import Meaning, MeaningFact
from words import file_structure, file_words

SPLIT = sys.argv[1]
HOW_MANY = int(sys.argv[2]) if len(sys.argv) > 2 else 400
KS = [int(k) for k in (sys.argv[3] if len(sys.argv) > 3 else "1,2,3").split(",")]
pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
treebank = ROOT / "test_data" / "syntax" / "UD_English-EWT" / "en_ewt-ud-train.conllu"
t0 = time.perf_counter()
words = file_words(treebank, gm.closed_uses())
view = gm.GrammarView(words, structure=file_structure(treebank))
lessons = [TaughtSentence(s, m, "lessons") for s, m in ListeningSource(tuple(
    str(p) for p in sorted((ROOT / "data" / "lessons").glob("english_[0-9][0-9].json")))).listening_pairs()]
for taught in lessons + list(PMBSource.of("gold", str(pmb)).taught_sentences()):
    view.hold(taught)
view.learn_waiting()
g = view.grammar
print(f"built {time.perf_counter() - t0:.0f}s", flush=True)
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
    if meaning is None:
        return None
    rename = {"?previous": "?before"}
    return Meaning(meaning.act, tuple(MeaningFact(f.relation, rename.get(f.subject, f.subject),
                                                  rename.get(f.obj, f.obj), f.positive, f.condition,
                                                  f.alternative, f.unasserted, f.given) for f in meaning.facts),
                   tuple(rename.get(a, a) for a in meaning.asked))


dev = []
for doc_id in pm.split_ids(pmb / "split" / "en" / (SPLIT + ".sbn")):
    document = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
    said = pm.meaning_of(document, sense_name) if document is not None else None
    if said is None or said.meaning is None:
        continue
    tokens = gm.tokens_of(document.text, words)
    anchors = tuple((t, tuple((document.concepts[k].span[0], document.concepts[k].span[1], how,
                               document.concepts[k].marked) for k, how in at if document.concepts[k].span))
                    for t, at in said.anchors.items())
    dev.append((document.text, said.meaning, gm.align_by_anchors(tokens, document.text, anchors), doc_id))
random.Random(1).shuffle(dev)
dev = dev[:HOW_MANY]
print(f"{SPLIT}: {len(dev)} sentences, k in {KS}", flush=True)

rows = {}
for k in KS:
    first_right = found = handed = nothing = 0
    at_rank = {}
    t1 = time.perf_counter()
    for done, (text, meaning, at, doc_id) in enumerate(dev):
        tokens = gm.tokens_of(text, words)
        readings = g.readings(tokens, k)
        handed += sum(1 for r in readings if r.meaning is not None)
        said = [r for r in readings if r.meaning is not None and r.sign is not None]
        if not said:
            nothing += 1
            continue
        right = [i for i, r in enumerate(said)
                 if unnamed(r.meaning).canonical()
                 == g01.senses_aside(meaning, at, names_of(r.sign)).canonical()]
        first_right += bool(right and right[0] == 0 and said[0] is readings[0])
        if right:
            found += 1
            at_rank[min(right)] = at_rank.get(min(right), 0) + 1
    took = time.perf_counter() - t1
    n = len(dev)
    rows[k] = {"first right": first_right / n, "right among those handed up": found / n,
               "meanings handed up per sentence": handed / n, "said nothing": nothing / n,
               "seconds per sentence": took / n, "where the right one ranked": at_rank}
    print(f"  k={k}: first right {first_right}/{n} ({first_right/n:.1%}), right among those handed up "
          f"{found}/{n} ({found/n:.1%}), {handed/n:.1f} meanings each, nothing {nothing}, "
          f"{took/n:.2f}s each ({took:.0f}s)", flush=True)
    print(f"        the right reading ranked: "
          f"{', '.join(f'{r}: {c}' for r, c in sorted(at_rank.items()))}", flush=True)

out = S / f"nbest_{SPLIT.replace('/', '_')}.json"
out.write_text(json.dumps(rows, indent=1))
print(f"wrote {out}", flush=True)
