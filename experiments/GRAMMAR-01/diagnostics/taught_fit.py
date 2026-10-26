"""How many sentences of a PMB split the grammar reads right whole, as GRAMMAR-01 scores them (senses aside), a
seeded sample of 1,000. Run on `train/gold` it reads back the sentences it was taught. Files only.
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/taught_fit.py train/gold
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
from core.semantics.derived_reader import is_variable
from words import file_words

SPLIT = sys.argv[1]
pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
treebank = ROOT / "test_data" / "syntax" / "UD_English-EWT" / "en_ewt-ud-train.conllu"
t0 = time.perf_counter()
words = file_words(treebank, gm.closed_uses())
ends = rl.sentence_ends(treebank)
view = gm.GrammarView(words)
from core.learning.teaching_sources import PMBDerivationSource
for item in PMBDerivationSource().derived():
    view.hold_derived(item)
lessons = [TaughtSentence(s, m, "lessons") for s, m in ListeningSource(tuple(
    str(p) for p in sorted((ROOT / "data" / "lessons").glob("english_[0-9][0-9].json")))).listening_pairs()]
for taught in lessons + list(PMBSource.of("gold", str(pmb)).taught_sentences()):
    view.hold(taught)
view.learn_waiting()
print(f"built {time.perf_counter() - t0:.0f}s", flush=True)
sense_names = WordNetSource()._sense_names()


def sense_name(sense):
    try:
        return sense_names.get(wn.synset(sense)) or None
    except Exception:
        return None


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
    dev.append((document.text, said.meaning, gm.align_by_anchors(tokens, document.text, anchors)))
held_out = {t.strip() for t, _, _ in dev}


def score():
    out = []
    for text, meaning, at in dev:
        r = view.grammar.read(gm.tokens_of(text, words))
        names = {}
        if r.sign is not None:
            for p in r.sign.pieces:
                if p[0] == "word":
                    for k in range(p[3], p[4]):
                        names.setdefault(k, p[1])
        want = g01.senses_aside(meaning, at, names)
        out.append({"text": text, "right": bool(r.meaning is not None and r.meaning.canonical() == want.canonical()),
                    "read": r.meaning.canonical() if r.meaning else None, "want": want.canonical(),
                    "decided": [(d[0], str(d[1]), d[2], d[3].relation if d[3] else None) for d in r.decided]})
    return out



import random as _r
_r.Random(1).shuffle(dev)
dev = dev[:1000]
out = score()
right = sum(x["right"] for x in out)
whole = sum(1 for x in out if x["read"] is not None)
print(f"{SPLIT}: {len(out)} sentences, given a meaning {whole}, right whole {right} ({right/len(out):.1%})", flush=True)
