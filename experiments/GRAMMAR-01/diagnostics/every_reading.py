"""Every reading the grammar can build of each sentence (the chart keeping every distinct one, not the surest of each
category), whether one gives the taught meaning, the one spoken of before scored as an unknown of its own; and each
sentence's chosen reading checked word by word against the PMB 4.0.0 gold CCG derivation
(`test_data/semantics/pmb/pmb-4.0.0`). Writes `every_reading_<split>.json` beside itself. Files only.
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/every_reading.py train/gold 1000
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
    dev.append((document.text, said.meaning, gm.align_by_anchors(tokens, document.text, anchors), doc_id))
held_out = {t[0].strip() for t in dev}


def score():
    out = []
    for text, meaning, at, *_ in dev:
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
from collections import Counter, defaultdict
from core.semantics.grammar import Atom, Joining, Reading, Sign, _key, _substitute, _whole, spell_out
_r.Random(1).shuffle(dev)
dev = dev[:int(sys.argv[2]) if len(sys.argv) > 2 else 1000]
GUARD = 20000  # signs in one sentence's chart past which it is reported as too many to finish, never dropped silently


class TooMany(Exception):
    pass


def every_chart(g, tokens):
    """Grammar.chart, keeping every distinct reading of each stretch (by its category and its pieces), not the surest
    of each category alone."""
    n = len(tokens)
    g._tokens = tuple(tokens)
    cells = defaultdict(lambda: defaultdict(dict))
    count = [0]

    def keep(sign):
        if sign.binding is not None:
            left, right = sign.kids
            sign.pieces = _substitute(left.pieces + right.pieces, sign.binding)
            sign.binding = None
        sig = (_key(sign.cat), sign.pieces)
        cell = cells[(sign.start, sign.end)][_key(sign.cat)]
        if sig in cell:
            if sign.score > cell[sig].score + 1e-9:
                cell[sig] = sign
            return False
        cell[sig] = sign
        count[0] += 1
        if count[0] > GUARD:
            raise TooMany()
        return True
    for i, t in enumerate(tokens):
        if not any(ch.isalnum() for ch in t) and t not in ("'s", "'") and not isinstance(t, Joining):
            keep(Sign(Atom("punct", t, None), (), 0.0, i, i + 1, "lex", (), i, "punct"))
        for end, entry in g.lexicon.entries(tokens, i):
            try:
                sign = g._lexical(tokens, i, end, entry)
            except (ValueError, IndexError):
                continue
            if keep(sign):
                for u in g._unary(sign):
                    keep(u)
    for length in range(2, n + 1):
        for start in range(0, n - length + 1):
            end = start + length
            made = []
            for mid in range(start + 1, end):
                lefts, rights = cells.get((start, mid)), cells.get((mid, end))
                if not lefts or not rights:
                    continue
                for left in [s for c in lefts.values() for s in c.values()]:
                    for right in [s for c in rights.values() for s in c.values()]:
                        made.extend(g._combine(left, right))
            for sign in made:
                if keep(sign):
                    for u in g._unary(sign):
                        keep(u)
    return [s for c in cells.get((0, n), {}).values() for s in c.values() if _whole(s.cat) is not None]


def names_of(sign):
    names = {}
    for p in sign.pieces:
        if p[0] == "word":
            for k in range(p[3], p[4]):
                names.setdefault(k, p[1])
    return names


import re
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
stats = Counter()
missing, extra, closest = Counter(), Counter(), []
records = []
MOD = {"((s\\np)\\(s\\np))/np", "(n\\n)/np", "(np\\np)/np", "((s\\np)/(s\\np))/np", "(s/s)/np", "(s\\s)/np"}


def notation(gold, have):
    if gold == "n" and "np" in have:
        return True
    if gold == "pp/np" and have & MOD:
        return True
    if gold.endswith("/pp") or "/pp)" in gold or "(n/pp)" in gold or gold == "n/pp":
        return True
    return False


def chains(sign, up=()):
    here = up + (sign,) if (up and up[-1].start == sign.start and up[-1].end == sign.end) else (sign,)
    if not sign.kids:
        return [(sign.start, sign.end, [strip(canon_lyric(x.cat, False)) for x in here])]
    out = []
    for k in sign.kids:
        out.extend(chains(k, here))
    return out


def words_checked(doc_id, text, tokens, sign):
    tags = P4 / doc_id / "en.parse.tags"
    if not tags.exists() or sign is None:
        return None
    gold = [(int(a), int(b), c.strip(), w) for c, w, a, b, _ in LEAF.findall(tags.read_text(encoding="utf-8"))]
    spans = offsets(text, tokens)
    by_span = {sp: i for i, sp in enumerate(spans) if sp}
    chosen = {}
    for a_, b_, chain in chains(sign):
        for k in range(a_, b_):
            chosen.setdefault(k, set(chain))
    out = []
    for a, b, c, w in gold:
        if c in ("punct", "comma") or not any(ch.isalnum() for ch in w):
            continue
        i = by_span.get((a, b))
        gc = strip(canon_pmb(pmb_tree(c), False))
        if i is None:
            out.append((w, gc, "split differently"))
            continue
        have = chosen.get(i, set())
        out.append((w, gc, "same" if gc in have or notation(gc, have) else "different: " + "/".join(sorted(have))))
    return out


from core.semantics.derived_reader import Meaning, MeaningFact


def unnamed(meaning):
    """The one spoken of before written as an unknown of its own, as the PMB writes a pronoun (GRAMMAR-01's
    `unnamed_before`)."""
    if meaning is None:
        return None
    rename = {"?previous": "?before"}
    return Meaning(meaning.act, tuple(MeaningFact(f.relation, rename.get(f.subject, f.subject),
                                                  rename.get(f.obj, f.obj), f.positive, f.condition,
                                                  f.alternative, f.unasserted, f.given) for f in meaning.facts),
                   tuple(rename.get(a, a) for a in meaning.asked))


def masked(m):
    """A meaning with each link's name set aside: what things it joins, and the kinds."""
    out = Counter()
    for f in g01.grounded(m, is_variable):
        if f[0] == "instance_of":
            out[f] += g01.grounded(m, is_variable)[f]
        else:
            out[("link",) + tuple(f[1:])] += g01.grounded(m, is_variable)[f]
    return out
readings_n = []
examples = []
t1 = time.perf_counter()
for done, (text, meaning, at, doc_id) in enumerate(dev):
    if done and done % 100 == 0:
        print(f"  {done} read, top right {stats['top right']}, right among readings {stats['right among its readings']}, too many {stats['too many readings to finish']}, {time.perf_counter() - t1:.0f}s", flush=True)
    tokens = gm.tokens_of(text, words)
    top = g.read(tokens)
    top_right = False
    if top.meaning is not None and top.sign is not None:
        top_right = unnamed(top.meaning).canonical() == g01.senses_aside(meaning, at, names_of(top.sign)).canonical()
    stats["top right"] += top_right
    record = {"doc": doc_id, "text": text, "top_right": top_right,
              "words": words_checked(doc_id, text, tokens, top.sign),
              "want": g01.senses_aside(meaning, at, names_of(top.sign)).canonical() if top.sign is not None else None,
              "read": unnamed(top.meaning).canonical() if top.meaning is not None else None}
    records.append(record)
    try:
        whole = every_chart(g, tokens)
    except TooMany:
        stats["too many readings to finish"] += 1
        record["class"] = "too many readings"
        continue
    readings_n.append(len(whole))
    if not whole:
        stats["no whole reading"] += 1
        record["class"] = "no whole reading"
        continue
    found = shaped = False
    best_overlap, best_m, best_want = -1.0, None, None
    for sign in whole:
        reading = Reading(tuple(tokens), sign, None)
        try:
            m = spell_out(g.lexicon, sign, tokens, reading)
        except ValueError:
            continue
        if m is None:
            continue
        m = unnamed(m)
        want = g01.senses_aside(meaning, at, names_of(sign))
        if m.canonical() == want.canonical():
            found = True
            break
        if masked(m) == masked(want):
            shaped = True
        gm_, gw = g01.grounded(m, is_variable), g01.grounded(want, is_variable)
        overlap = sum((gm_ & gw).values()) / max(sum((gm_ | gw).values()), 1)
        if overlap > best_overlap:
            best_overlap, best_m, best_want = overlap, m, want
    stats["right among its readings"] += found
    if found and not top_right and len(examples) < 15:
        examples.append(text)
    record["class"] = ("right" if top_right else "right among its readings" if found
                       else "a link named wrong" if shaped else "no reading joins the right things")
    if not found:
        stats["right things joined, a link named wrong"] += shaped
        stats["no reading joins the right things"] += not shaped
        if best_m is not None:
            gm_, gw = g01.grounded(best_m, is_variable), g01.grounded(best_want, is_variable)
            for f in (gw - gm_):
                missing[f[0]] += 1
            for f in (gm_ - gw):
                extra[f[0]] += 1
            if len(closest) < 40:
                closest.append((text, best_want.canonical(), best_m.canonical(), shaped))
n = len(dev)
readings_n.sort()
print(f"{SPLIT}: {n} sentences, {time.perf_counter() - t1:.0f}s", flush=True)
for k in ("top right", "right among its readings", "right things joined, a link named wrong",
          "no reading joins the right things", "no whole reading", "too many readings to finish"):
    print(f"  {k}: {stats[k]} ({stats[k] / n:.1%})", flush=True)
if readings_n:
    print(f"  whole readings per sentence: median {readings_n[len(readings_n) // 2]}, p90 {readings_n[int(.9 * len(readings_n))]}, max {readings_n[-1]}", flush=True)
print("  right among its readings but not chosen, e.g.:")
for e in examples:
    print("    " + e, flush=True)
print("  facts the closest reading lacks, by link:", missing.most_common(15), flush=True)
print("  facts the closest reading has that the meaning does not:", extra.most_common(15), flush=True)
import json as _j
(Path(__file__).resolve().parent / ("every_reading_closest_" + SPLIT.replace("/", "_") + ".json")).write_text(_j.dumps(closest, indent=1))
(Path(__file__).resolve().parent / ("every_reading_" + SPLIT.replace("/", "_") + ".json")).write_text(_j.dumps(records))
