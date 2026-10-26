"""Each word of a PMB split's sentences: the category the PMB 4.0.0 gold CCG derivation gives it, the categories
Lyric's grammar lists and derives for it (`Grammar._unary`), and the ones its chosen reading uses over it. Writes
`categories_<split>.json` beside itself. Files only.
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/categories.py dev/standard
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
from words import file_structure, file_words

SPLIT = sys.argv[1]
pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
treebank = ROOT / "test_data" / "syntax" / "UD_English-EWT" / "en_ewt-ud-train.conllu"
t0 = time.perf_counter()
words = file_words(treebank, gm.closed_uses())
ends = rl.sentence_ends(treebank)
view = gm.GrammarView(words, structure=file_structure(treebank))
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




import re
from collections import Counter, defaultdict
from core.semantics.grammar import Atom, Fn
P4 = ROOT / "test_data" / "semantics" / "pmb" / "pmb-4.0.0" / "data" / "en" / "gold"
LEAF = re.compile(r"t\(([^,]+?), '((?:[^'\\]|\\.)*)', \[from:(\d+), to:(\d+), pos:'([^']*)'")


def pmb_tree(text):
    """A meaning-bank category as a tree: atoms like s:dcl, np; slashes left-associative."""
    toks = re.findall(r"\(|\)|/|\\|[a-z]+(?::[a-z]+)?", text)
    at = [0]

    def primary():
        if toks[at[0]] == "(":
            at[0] += 1
            c = expr()
            at[0] += 1
            return c
        t = toks[at[0]]
        at[0] += 1
        return ("atom",) + tuple(t.split(":")) if ":" in t else ("atom", t, None)

    def expr():
        c = primary()
        while at[0] < len(toks) and toks[at[0]] in ("/", "\\"):
            s = toks[at[0]]
            at[0] += 1
            c = ("fn", c, s, primary())
        return c
    return expr()


def canon_pmb(t, feats):
    if t[0] == "atom":
        return t[1] + (":" + t[2] if feats and t[2] else "")
    return "(" + canon_pmb(t[1], feats) + t[2] + canon_pmb(t[3], feats) + ")"


def canon_lyric(c, feats):
    if isinstance(c, Atom):
        f = c.feat
        return c.base.lower() + (":" + f if feats and isinstance(f, str) and f.islower() else "")
    return "(" + canon_lyric(c.res, feats) + c.slash + canon_lyric(c.arg, feats) + ")"


def strip(s):
    return s[1:-1] if s.startswith("(") and s.endswith(")") else s


def offsets(text, tokens):
    out, at = [], 0
    for t in tokens:
        w = str(t)
        k = text.find(w, at)
        if k < 0:
            k = text.lower().find(w.lower(), at)
        if k < 0:
            out.append(None)
            continue
        out.append((k, k + len(w)))
        at = k + len(w)
    return out


def leaves(sign):
    if sign.rule in ("lex", "punct") or not sign.kids:
        return [sign]
    return [x for k in sign.kids for x in leaves(k)]


g = view.grammar
import json


def closure(sign):
    """A lexical sign and every category its rules make of it over the same words."""
    out, todo, seen = [], [sign], set()
    while todo:
        x = todo.pop()
        k = canon_lyric(x.cat, False)
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
        todo.extend(u for u in g._unary(x) if u.start == x.start and u.end == x.end)
    return out


def chains(sign, up=()):
    """For each word of a reading: the categories from its word's sign up through every sign over the same words."""
    here = up + (sign,) if (up and up[-1].start == sign.start and up[-1].end == sign.end) else (sign,)
    if not sign.kids:
        return [(sign.start, sign.end, sign.rule, [strip(canon_lyric(x.cat, False)) for x in here])]
    out = []
    for k in sign.kids:
        out.extend(chains(k, here))
    return out


records = []
for doc_id in pm.split_ids(pmb / "split" / "en" / (SPLIT + ".sbn")):
    tags = P4 / doc_id / "en.parse.tags"
    raw = pmb / "data" / "en" / "gold" / doc_id / "en.raw"
    if not tags.exists() or not raw.exists():
        continue
    text = raw.read_text(encoding="utf-8").strip()
    gold = [(int(a), int(b), c.strip(), w, pos) for c, w, a, b, pos in LEAF.findall(tags.read_text(encoding="utf-8"))]
    tokens = gm.tokens_of(text, words)
    spans = offsets(text, tokens)
    by_span = {sp: i for i, sp in enumerate(spans) if sp}
    g._tokens = tuple(tokens)
    r = g.read(tokens)
    chosen = {}
    if r.sign is not None:
        for a_, b_, rule, chain in chains(r.sign):
            for k in range(a_, b_):
                chosen.setdefault(k, (b_ - a_, rule, chain))
    for a, b, c, w, pos in gold:
        if c in ("punct", "comma") or not any(ch.isalnum() for ch in w):
            continue
        i = by_span.get((a, b))
        rec = {"doc": doc_id, "text": text, "word": w, "pos": pos, "gold": strip(canon_pmb(pmb_tree(c), False)),
               "gold_feats": strip(canon_pmb(pmb_tree(c), True)), "read": r.sign is not None, "at": i}
        if i is not None:
            listed, derived = set(), set()
            for end, entry in g.lexicon.entries(tokens, i):
                if end != i + 1:
                    continue
                try:
                    sg = g._lexical(tokens, i, end, entry)
                except (ValueError, IndexError):
                    continue
                listed.add(strip(canon_lyric(sg.cat, False)))
                derived.update(strip(canon_lyric(x.cat, False)) for x in closure(sg))
            rec["listed"], rec["derived"] = sorted(listed), sorted(derived)
            ch = chosen.get(i)
            rec["chosen_width"], rec["chosen_rule"], rec["chosen_chain"] = (ch if ch else (None, None, []))
        records.append(rec)
(Path(__file__).resolve().parent / ("categories_" + SPLIT.replace("/", "_") + ".json")).write_text(json.dumps(records))
print(f"records {len(records)}", flush=True)
