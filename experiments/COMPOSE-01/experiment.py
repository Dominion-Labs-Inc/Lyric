"""COMPOSE-01: what a sentence means, composed from how its words go together, learned from the lessons.

Each lesson sentence is split as Lyric splits a sentence (`form_of`, `words_of`), read by the structure reader (learned
from UD English EWT's training part; a word the treebank never used limited to the classes WordNet gives it, standing
in for memory's word classes) and laid out with its words named (`composition.lay`). The composer
(`composition.CompositionView`) is learned from the lessons, with PropBank's arguments behind them
(`argument_structure.learned_from_propbank`). Measured ten ways: learned from nine tenths of the lesson sentences,
each sentence of the tenth held out composed and compared whole with its taught meaning, written canonically; and
with its names aside, where only the names differ (the lessons name some things by sense: "metal" as `metallic
element`, which memory gives and a lemma cannot). The sentences of arithmetic are left to the arithmetic reader.
Then the prose of UNDERSTANDS-PROSE-01 is composed, learned from every lesson, and kept beside the record.

Names here are files only: a word's plain form by WordNet (`morphy`), else as the treebank's lemmas have it; a name of
several words as WordNet holds it. On main the names are memory's.

Run (from the Lyric folder; reads files only, about ten minutes):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/COMPOSE-01/experiment.py [--data DIR] [--lessons DIR]
with `--data` (default `test_data/syntax`) holding `propbank-release`, `propbank-frames` and `UD_English-EWT`, and
`--lessons` (default `data/lessons`) the lessons.
"""
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

#: The kinds that write a number from its parts, which the arithmetic reader reads.
ARITHMETIC = {"has_addend", "has_augend", "has_factor", "has_multiplicand", "has_dividend", "has_divisor",
              "has_minuend", "has_subtrahend", "has_base", "has_exponent", "has_radicand", "has_index", "has_argument"}
NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMBERS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
                "hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12})
FOLDS = 10


def say(*a):
    print(*a, flush=True)


def argument(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def main() -> int:
    from experiments._evidence import RunRecord
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import ListeningSource, propbank_roles_of_frames, read_conllu, \
        read_propbank_ewt
    from core.semantics import composition as cp
    from core.semantics.argument_structure import learned_from_propbank
    from core.semantics.sentence_machine import form_of
    from core.semantics.structure import StructureView, words_of
    data = Path(argument("--data") or ROOT / "test_data" / "syntax")
    lessons = Path(argument("--lessons") or ROOT / "data" / "lessons")
    EV = RunRecord("COMPOSE-01",
                   claim="what a sentence means is composed from how its words go together, learned from the lessons",
                   hypothesis="learned from nine tenths of the lessons, the composer gives the held-out tenth's "
                              "taught meanings, and composes the prose of UNDERSTANDS-PROSE-01 (no bar: measured)")
    started = time.perf_counter()

    # ── names, from files ─────────────────────────────────────────────────────────────────────────────────────────
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

    # ── the structure, the arguments, the lessons ──────────────────────────────────────────────────────────────
    structure = StructureView()
    for analysed in read_conllu(str(data / "UD_English-EWT" / "en_ewt-ud-train.conllu"), "ud_english_ewt"):
        structure.add(analysed)
    structure.held_classes = wordnet_classes
    roles = propbank_roles_of_frames(str(data / "propbank-frames" / "frames"))
    arguments = learned_from_propbank(list(read_propbank_ewt(str(data / "propbank-release"),
                                                             str(data / "UD_English-EWT"))), roles)
    say(f"PropBank's arguments learned from {len(arguments):,} candidates, {time.perf_counter() - started:.0f}s")

    def laid_of(sentence):
        words = words_of(form_of(sentence))
        read = structure.read(words)
        return cp.lay(read.words, read.classes, read.heads, read.relations, name_of, known_name)

    source = ListeningSource(tuple(str(p) for p in sorted(lessons.glob("english_[0-9][0-9].json"))))
    pairs = [(sentence, meaning, laid_of(sentence)) for sentence, meaning in source.listening_pairs()]
    arithmetic = [any(f.relation in ARITHMETIC for f in meaning.facts) for _, meaning, _ in pairs]
    say(f"{len(pairs):,} lesson sentences read ({sum(arithmetic):,} of arithmetic), "
        f"{time.perf_counter() - started:.0f}s")
    EV.check("the lessons are on disk", len(pairs) > 0, f"{len(source.paths)} lessons, {len(pairs):,} sentences")

    # ── the lessons, held out ten ways ─────────────────────────────────────────────────────────────────────────
    def names_aside(text):
        return re.sub(r"(?<=[(, ])(?!\?)[^(),?][^(),]*(?=[,)])", "C", text)

    def taught(meaning, laid):
        names = laid.names
        return type(meaning)(meaning.act, tuple(
            type(f)(f.relation, cp.taught_name(f.subject, names), cp.taught_name(f.obj, names), f.positive,
                    f.condition, f.alternative, f.unasserted, f.given) for f in meaning.facts), meaning.asked)

    order = list(range(len(pairs)))
    random.Random(7).shuffle(order)
    counts = Counter()
    missed = []
    for fold in range(FOLDS):
        held = set(order[fold::FOLDS])
        view = cp.CompositionView(arguments)
        for k in order:
            if k not in held and not arithmetic[k]:
                view.learn(pairs[k][2], pairs[k][1])
        for k in sorted(held):
            if arithmetic[k]:
                continue
            sentence, meaning, laid = pairs[k]
            want = taught(meaning, laid).canonical()
            try:
                got = view.compose(laid).canonical()
            except ValueError as e:
                got = f"(no meaning: {e})"
            counts["sentences"] += 1
            counts["as taught"] += got == want
            counts["names aside"] += names_aside(got) == names_aside(want)
            counts["no meaning"] += got.startswith("(no meaning")
            if got != want:
                missed.append({"sentence": sentence, "taught": want, "composed": got})
    n = counts["sentences"]
    for what in ("as taught", "names aside", "no meaning"):
        EV.metric(f"lessons held out: {what}", round(counts[what] / n, 4), unit="fraction", note=f"{counts[what]}/{n}")
        say(f"  lessons held out, {what:12} {counts[what]:,} of {n:,} ({counts[what] / n:.1%})")

    # ── the prose ──────────────────────────────────────────────────────────────────────────────────────────────
    view = cp.CompositionView(arguments)
    for k, (sentence, meaning, laid) in enumerate(pairs):
        if not arithmetic[k]:
            view.learn(laid, meaning)
    from core.semantics import derived_reader
    derived_reader.MAX_FREE_VARIABLES = 99      # to show a long sentence's facts; nothing is compared
    prose = []
    texts = json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-01" / "texts.json").read_text())
    for text in texts:
        for sentence in text["text"]:
            laid = laid_of(sentence)
            try:
                composed = view.compose(laid)
                said = f"{composed.act}: " + " & ".join(f.render() for f in composed.facts)
            except ValueError as e:
                said = f"(no meaning: {e})"
            prose.append({"sentence": sentence, "composed": said})
            say(f"  {sentence}\n      {said}")
    EV.metric("prose sentences composed to a meaning", sum(not p["composed"].startswith("(no") for p in prose),
              unit="sentences", note=f"of {len(prose)}")
    EV.check("a meaning was composed for some lesson held out", counts["as taught"] > 0, f"{counts['as taught']:,}")
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (results / f"{stamp}_prose.json").write_text(json.dumps(prose, indent=1))
    random.Random(7).shuffle(missed)
    (results / f"{stamp}_missed.json").write_text(json.dumps(missed[:300], indent=1))
    say(f"\n  run record: {EV.write()}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
