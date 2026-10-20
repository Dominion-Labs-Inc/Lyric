"""PMB-01: what a sentence means, composed over its structure, learned from the Parallel Meaning Bank.

The composer (`core/semantics/composition.py`) learned from the lessons and from the PMB's English training sentences
(`teaching_sources.PMBSource`: each with its meaning in Lyric's meaning language and where each of its terms is said),
measured on the PMB's dev split, held out: each sentence split as Lyric splits a sentence, read by the structure reader
(learned from UD English EWT's training part; a word the treebank never used limited to the classes WordNet gives it,
standing in for memory's word classes) and laid out with its words named (`composition.lay`), composed, and compared
with its meaning two ways:

- strict: as the PMB says it, each kind named as Lyric names the WordNet sense the PMB gives;
- senses aside: each kind and name a word says named as the composer names that word, so what is compared is how the
  meaning is composed, not which sense a word names (the composer names a word by its word; the PMB names a sense,
  "took" `utilize take`);
- senses aside, the one spoken of before unnamed: as senses aside, the composer's `?previous` taken as a thing of no
  kind, as the PMB leaves a pronoun its document does not tie ("They are blue."): the composer says such a word as
  the lessons and the conversation do, which the PMB's own way counts wrong.

Each way: dev sentences whose whole meaning is right, and of their facts (each variable put as what it is an instance
of) the precision, recall and F1. Learned three ways: the lessons only (what main holds today), with the PMB's gold
training sentences, and with `--silver` its silver ones too (about half an hour more). Then the prose of
UNDERSTANDS-PROSE-01 composed, learned from all, kept beside the record.

Names here are files only: a word's plain form by WordNet (`morphy`), else as the treebank's lemmas have it. On main
the names are memory's.

Run (from the Lyric folder; about five minutes, `--silver` about forty):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/PMB-01/experiment.py [--silver] [--data DIR] [--pmb DIR]
with `--data` (default `test_data/syntax`) holding `UD_English-EWT`, `--pmb` (default
`test_data/semantics/pmb/pmb-5.1.0`) the PMB release 5.1.0, the lessons in `data/lessons/`, and WordNet for `nltk`.
The Parallel Meaning Bank: University of Groningen, annotations ODC-BY 1.0 (Abzianidze et al. 2017).
"""
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMBERS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
                "hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12})


def say(*a):
    print(*a, flush=True)


def argument(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def grounded(meaning, is_variable):
    """A meaning's facts with each variable put as what it is an instance of (or `?`): comparable across meanings."""
    kind = {}
    for f in meaning.facts:
        if f.relation == "instance_of" and is_variable(f.subject) and not is_variable(f.obj):
            kind.setdefault(f.subject, f.obj)
    out = Counter()
    for f in meaning.facts:
        if f.relation == "instance_of" and is_variable(f.subject):
            out[("instance_of", f.obj, f.positive)] += 1
            continue
        s = kind.get(f.subject, "?") if is_variable(f.subject) else f.subject
        o = kind.get(f.obj, "?") if is_variable(f.obj) else f.obj
        out[(f.relation, s, o, f.positive)] += 1
    return out


def main() -> int:
    from experiments._evidence import RunRecord
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import ListeningSource, PMBSource, read_conllu
    from core.semantics import composition as cp
    from core.semantics import pmb_meanings as pm
    from core.semantics.derived_reader import Meaning, MeaningFact, is_variable
    from core.semantics.sentence_machine import form_of
    from core.semantics.structure import StructureView, words_of
    data = Path(argument("--data") or ROOT / "test_data" / "syntax")
    pmb = Path(argument("--pmb") or ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0")
    silver = "--silver" in sys.argv
    EV = RunRecord("PMB-01",
                   claim="what a sentence means is composed over its structure, each word's standing and each near "
                         "pair's facts learned from sentences aligned word by word to their meanings",
                   hypothesis="learned from the PMB's gold training sentences, more of its held-out dev meanings are "
                              "composed right whole than by the composer before this one (8.0% on main, 2026-10-20), "
                              "and more again with its silver ones")
    started = time.perf_counter()
    EV.check("the PMB is on disk", (pmb / "split" / "en" / "dev" / "standard.sbn").exists(), str(pmb))

    # ── names and structure, from files ───────────────────────────────────────────────────────────────────────────
    ud_classes = {"NOUN": "NOUN", "PROPN": "NAME", "VERB": "VERB", "ADJ": "ADJECTIVE", "ADV": "ADVERB",
                  "AUX": "AUXILIARY", "PRON": "PRONOUN", "DET": "DETERMINER", "NUM": "NUMERAL", "ADP": "PREPOSITION",
                  "CCONJ": "CONJUNCTION", "SCONJ": "SUBORDINATOR", "PART": "PARTICLE", "PUNCT": "PUNCTUATION",
                  "SYM": "SYMBOL", "INTJ": "INTERJECTION", "X": "OTHER"}
    lemmas, endings = defaultdict(Counter), defaultdict(Counter)
    with open(data / "UD_English-EWT" / "en_ewt-ud-train.conllu", encoding="utf-8") as handle:
        for line in handle:
            cols = line.rstrip("\n").split("\t")
            if len(cols) == 10 and cols[0].isdigit():
                form, lemma, cls = cols[1].lower(), cols[2].lower(), ud_classes.get(cols[3], cols[3])
                lemmas[(form, cls)][lemma] += 1
                lemmas[(form, "")][lemma] += 1
                k = 0
                while k < min(len(form), len(lemma)) and form[k] == lemma[k]:
                    k += 1
                endings[(form[-3:], cls)][(len(form) - k, lemma[k:])] += 1
    by_class = {"NOUN": wn.NOUN, "VERB": wn.VERB, "ADJECTIVE": wn.ADJ, "ADVERB": wn.ADV}

    def name_of(word, cls):
        w = word.lower()
        if w in NUMBERS and cls in ("NUMERAL", "NOUN", "DETERMINER", "PRONOUN", "NAME", "ADJECTIVE"):
            return str(NUMBERS[w])
        if re.fullmatch(r"-?\d+(\.\d+)?", w):
            return w
        if cls in by_class:
            found = wn.morphy(w, by_class[cls])
            if found:
                return found
        got = lemmas.get((w, cls)) or lemmas.get((w, ""))
        if got:
            return got.most_common(1)[0][0]
        change = endings.get((w[-3:], cls))
        if change:
            cut, add = change.most_common(1)[0][0]
            return w[:len(w) - cut] + add
        return w

    def known_name(words):
        return bool(wn.synsets("_".join(w.lower() for w in words)))

    wordnet_as = {"n": ("NOUN", "NAME"), "v": ("VERB",), "a": ("ADJECTIVE",), "s": ("ADJECTIVE",), "r": ("ADVERB",)}

    def wordnet_classes(word):
        counts = {}
        for synset in wn.synsets(word.lower()):
            for cls in wordnet_as.get(synset.pos(), ()):
                counts[cls] = counts.get(cls, 0) + 1
        return counts

    structure = StructureView()
    for analysed in read_conllu(str(data / "UD_English-EWT" / "en_ewt-ud-train.conllu"), "ud_english_ewt"):
        structure.add(analysed)
    structure.held_classes = wordnet_classes

    def laid_of(sentence):
        words = words_of(form_of(sentence))
        if not words:
            return None
        read = structure.read(words)
        return cp.lay(read.words, read.classes, read.heads, read.relations, name_of, known_name)

    # ── what is learned from, and what is measured on ─────────────────────────────────────────────────────────────
    lessons = [(laid_of(s), m) for s, m in ListeningSource(tuple(
        str(p) for p in sorted((ROOT / "data" / "lessons").glob("english_[0-9][0-9].json")))).listening_pairs()]
    gold = [(laid_of(t.sentence), t) for t in PMBSource.of("gold", str(pmb)).taught_sentences()]
    say(f"lessons {len(lessons):,}, PMB gold training sentences said whole {len(gold):,}, "
        f"{time.perf_counter() - started:.0f}s")
    from core.learning.teaching_sources import WordNetSource
    sense_names = WordNetSource()._sense_names()

    def sense_name(sense):
        try:
            return sense_names.get(wn.synset(sense)) or None
        except Exception:
            return None
    dev = []
    listed = pm.split_ids(pmb / "split" / "en" / "dev" / "standard.sbn")
    for doc_id in listed:
        document = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        said = pm.meaning_of(document, sense_name) if document is not None else None
        if said is None or said.meaning is None:
            continue
        laid = laid_of(document.text)
        if laid is None:
            continue
        anchors = tuple((t, tuple((document.concepts[k].span[0], document.concepts[k].span[1], how,
                                   document.concepts[k].marked) for k, how in at if document.concepts[k].span))
                        for t, at in said.anchors.items())
        dev.append((document.text, laid, said.meaning, cp.words_by_anchors(laid, document.text, anchors)))
    EV.metric("PMB dev sentences said whole", len(dev), unit="sentences", note=f"of {len(listed):,} listed")
    say(f"PMB dev said whole {len(dev):,} of {len(listed):,}")

    def senses_aside(laid, meaning, words):
        """The meaning with each kind and name a word says named as the composer names that word."""
        at = {t: ws[0] for t, ws in words.items() if ws}
        renamed = {}
        for f in meaning.facts:
            w = at.get(f.obj, at.get(f.subject))
            if f.relation == "instance_of" and is_variable(f.subject) and w is not None and laid.names[w]:
                renamed[(f.subject, f.obj)] = laid.names[w]
        constants = {t: laid.names[w] for t, w in at.items() if not is_variable(t) and laid.names[w]
                     and not t.replace(".", "").isdigit()}
        kinds = {f.obj for f in meaning.facts if f.relation == "instance_of"}
        facts = []
        for f in meaning.facts:
            if (f.subject, f.obj) in renamed:
                f = MeaningFact(f.relation, f.subject, renamed[(f.subject, f.obj)], f.positive, f.condition,
                                f.alternative, f.unasserted, f.given)
            else:
                subject = constants.get(f.subject, f.subject) if f.subject not in kinds else f.subject
                obj = constants.get(f.obj, f.obj) if (f.relation != "instance_of" or f.obj not in kinds
                                                     or not is_variable(f.subject)) else f.obj
                f = MeaningFact(f.relation, subject, obj, f.positive, f.condition, f.alternative, f.unasserted,
                                f.given)
            facts.append(f)
        try:
            return Meaning(meaning.act, tuple(dict.fromkeys(facts)), meaning.asked)
        except ValueError:
            return meaning

    aside = [senses_aside(laid, meaning, words) for _, laid, meaning, words in dev]

    def unnamed_before(meaning):
        """The meaning with the one spoken of before held as a thing of no kind."""
        if meaning is None:
            return None
        rename = {"?previous": "?before"}
        return Meaning(meaning.act, tuple(MeaningFact(f.relation, rename.get(f.subject, f.subject),
                                                      rename.get(f.obj, f.obj), f.positive, f.condition,
                                                      f.alternative, f.unasserted, f.given) for f in meaning.facts),
                       tuple(rename.get(a, a) for a in meaning.asked))

    def measure(label, view):
        out = {}
        for way, wanted in (("strict", [m for _, _, m, _ in dev]), ("senses aside", aside),
                            ("senses aside, the one spoken of before unnamed", aside)):
            right = composed = tp = fp = fn = 0
            for (_, laid, _, _), want in zip(dev, wanted):
                try:
                    got = view.compose(laid)
                except ValueError:
                    got = None
                if got is not None and way.endswith("unnamed"):
                    got = unnamed_before(got)
                w = grounded(want, is_variable)
                if got is None:
                    fn += sum(w.values())
                    continue
                composed += 1
                right += got.canonical() == want.canonical()
                g = grounded(got, is_variable)
                tp += sum((g & w).values())
                fp += sum((g - w).values())
                fn += sum((w - g).values())
            p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
            f1 = 2 * p * r / max(p + r, 1e-9)
            out[way] = right / len(dev)
            EV.metric(f"{label}, {way}: whole meaning right", round(right / len(dev), 4), unit="fraction",
                      note=f"{right}/{len(dev)}")
            EV.metric(f"{label}, {way}: facts precision / recall / F1", [round(p, 4), round(r, 4), round(f1, 4)],
                      unit="fraction")
            say(f"  {label}, {way}: composed {composed:,}; whole right {right:,} ({right / len(dev):.1%}); facts "
                f"precision {p:.1%}, recall {r:.1%}, F1 {f1:.1%}")
        return out

    view = cp.CompositionView()
    for laid, meaning in lessons:
        if laid is not None:
            view.learn(laid, meaning)
    by_lessons = measure("the lessons", view)
    for laid, taught in gold:
        if laid is not None:
            view.learn(laid, taught.meaning, cp.words_by_anchors(laid, taught.sentence, taught.anchors))
    by_gold = measure("the lessons and the PMB's gold training sentences", view)
    EV.check("learned from the PMB's gold sentences, more dev meanings right whole than the composer before this one "
             "(8.0% on main, 2026-10-20)", by_gold["strict"] > 0.080, f"{by_gold['strict']:.1%}")
    EV.check("learned from the PMB's gold sentences, more right than from the lessons alone",
             by_gold["senses aside"] > by_lessons["senses aside"],
             f"{by_lessons['senses aside']:.1%} -> {by_gold['senses aside']:.1%}")
    if silver:
        learned = 0
        for taught in PMBSource.of("silver", str(pmb)).taught_sentences():
            laid = laid_of(taught.sentence)
            if laid is not None:
                view.learn(laid, taught.meaning, cp.words_by_anchors(laid, taught.sentence, taught.anchors))
                learned += 1
        say(f"PMB silver training sentences learned {learned:,}, {time.perf_counter() - started:.0f}s")
        EV.metric("PMB silver training sentences learned", learned, unit="sentences")
        by_silver = measure("the lessons and the PMB's gold and silver training sentences", view)
        EV.check("more data, more right: with the silver sentences more right than with the gold alone",
                 by_silver["senses aside"] > by_gold["senses aside"],
                 f"{by_gold['senses aside']:.1%} -> {by_silver['senses aside']:.1%}")

    # ── the prose, and what was missed ────────────────────────────────────────────────────────────────────────────
    from core.semantics import derived_reader
    derived_reader.MAX_FREE_VARIABLES = 99      # to show a long sentence's facts; nothing is compared
    prose = []
    for text in json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-01" / "texts.json").read_text()):
        for sentence in text["text"] + [q["q"] for q in text.get("questions", [])]:
            laid = laid_of(sentence)
            try:
                m = view.compose(laid)
                said = f"{m.act}: " + " & ".join(f.render() for f in m.facts) + (
                    f" ? {', '.join(m.asked)}" if m.asked else "")
            except (ValueError, TypeError) as e:
                said = f"(no meaning: {e})"
            prose.append({"sentence": sentence, "composed": said})
    missed = []
    for (text, laid, meaning, _), want in zip(dev, aside):
        try:
            got = view.compose(laid).canonical()
        except ValueError:
            got = None
        if got != want.canonical():
            missed.append({"sentence": text, "meaning": want.canonical(), "composed": got})
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (results / f"{stamp}_prose.json").write_text(json.dumps(prose, indent=1))
    random.Random(7).shuffle(missed)
    (results / f"{stamp}_missed.json").write_text(json.dumps(missed[:300], indent=1))
    say(f"\n  run record: {EV.write()}  ({time.perf_counter() - started:.0f}s)")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
