#!/usr/bin/env python3
"""READ-LEARN-01: whether Lyric's English gets better by reading, as a person's does.

Claim. Reading teaches: how a sentence Lyric reads and is sure of used its words is counted beside the treebank's
(`grammar.GrammarView._learn_from_reading`, inside `grammar.reading_teaches`), so a word met in reading is known from
then on and how words are used is learned from what is read; and what a sentence read says a named thing is ("Tom is
a teacher.") memory takes in, and the grammar knows it at once (`MemoryAgent.link_concepts`, `Words.hear_kind`), so a
phrase about it reads by what it is (`grammar.Lexicon.selected`). With nothing but reading between them, the grammar
reads held-out English better after reading than before.

Measured as GRAMMAR-01 measures (files only, no store): the grammar built as memory builds it (the English Web
Treebank's sentences, WordNet's links, learned from the lessons and the PMB's gold training sentences), scored on the
PMB's dev split (held out); then it reads raw English it was never taught, the PMB's silver documents' sentences (their
text alone, never their meanings, none of them a dev sentence), and is scored again on the same dev split after each
stretch of reading. Scoring teaches nothing: only what is read inside `reading_teaches` does. Standing in for memory,
the experiment gives the grammar's words each kind a sentence read whole tells of a named thing, as memory's one
writer of links does on main. A document is read
sentence by sentence, as Lyric reads one (`derived_reader.read_text` cuts a text where an utterance can end): it is cut
after each mark the treebank's sentences end on (`sentence_ends`).

Run (from the Lyric folder):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/READ-LEARN-01/experiment.py [--read 2000,5000,10000]
"""
import importlib.util
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "GRAMMAR-01"))
_spec = importlib.util.spec_from_file_location("grammar_01", ROOT / "experiments" / "GRAMMAR-01" / "experiment.py")
g01 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g01)

#: The seed the silver documents are drawn by.
SEED = 20261025


def say(*a):
    print(*a, flush=True)


def argument(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def sentence_ends(conllu: Path) -> frozenset:
    """The marks the treebank's sentences end on: each mark most of whose uses end a sentence ("." but not ",")."""
    final, seen, sentence = {}, {}, []
    for line in conllu.read_text(encoding="utf-8").splitlines() + [""]:
        if not line.strip():
            for k, (form, use) in enumerate(sentence):
                if use == "PUNCT":
                    seen[form] = seen.get(form, 0) + 1
                    final[form] = final.get(form, 0) + (k == len(sentence) - 1)
            sentence = []
        elif not line.startswith("#"):
            cols = line.split("\t")
            if cols[0].isdigit():
                sentence.append((cols[1], cols[3]))
    return frozenset(form for form, n in seen.items() if final[form] * 2 > n)


def sentences_of(text: str, ends: frozenset) -> list:
    """A document's sentences, as written: Lyric's pieces (`sentence_machine.form_of`) cut after each mark a sentence
    ends on."""
    from core.semantics.sentence_machine import form_of
    out, current = [], ""
    for piece in form_of(text):
        current += piece.text + (" " if piece.space_after else "")
        if piece.text in ends:
            out.append(current.strip())
            current = ""
    if current.strip():
        out.append(current.strip())
    return out


def told_kinds(reading, words) -> list:
    """What a sentence read whole tells a thing is ("Whales are mammals.": `isa(whale, mammal)`), each given to the
    grammar's words as memory gives a kind it takes in (`Words.hear_kind`); a named thing's kind as memory holds a
    particular's, `instance_of` ("Tom is a teacher."; on main a text read by composing knows no names yet)."""
    from core.semantics.derived_reader import is_variable
    told = []
    if reading.meaning is None or reading.sign is None:
        return told
    names = {str(p[1]) for p in reading.sign.pieces if (p[0] == "word" and p[2] == "NAME") or p[0] == "named"}
    for f in reading.meaning.facts:
        if f.relation in ("isa", "instance_of") and f.positive and not (f.condition or f.unasserted or f.alternative) \
                and not is_variable(f.subject) and not is_variable(f.obj):
            relation = "instance_of" if f.relation == "isa" and str(f.subject) in names else f.relation
            words.hear_kind(f.subject, relation, f.obj)
            told.append((f.subject, relation, f.obj))
    return told


def main() -> int:
    from experiments._evidence import RunRecord
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import ListeningSource, PMBSource, WordNetSource
    from core.semantics import grammar as gm
    from core.semantics import pmb_meanings as pm
    from core.semantics.composition import TaughtSentence
    from core.semantics.derived_reader import is_variable
    from words import file_words
    stretches = [int(n) for n in (argument("--read") or "2000,5000,10000").split(",")]
    pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
    EV = RunRecord("READ-LEARN-01",
                   claim="Lyric's English gets better by reading: how a sentence it reads and is sure of used its words "
                         "is counted beside the treebank's, and held-out English is read better after reading",
                   hypothesis="with nothing but reading raw English between them, more of the PMB's held-out dev "
                              "meanings are read right whole after reading than before (senses aside), and the facts "
                              "read are no less right (F1)")
    started = time.perf_counter()
    treebank = ROOT / "test_data" / "syntax" / "UD_English-EWT" / "en_ewt-ud-train.conllu"
    words = file_words(treebank, gm.closed_uses())
    ends = sentence_ends(treebank)
    view = gm.GrammarView(words)
    lessons = [TaughtSentence(s, m, "lessons") for s, m in ListeningSource(tuple(
        str(p) for p in sorted((ROOT / "data" / "lessons").glob("english_[0-9][0-9].json")))).listening_pairs()]
    gold = list(PMBSource.of("gold", str(pmb)).taught_sentences())
    for taught in lessons + gold:
        view.hold(taught)
    view.learn_waiting()
    say(f"the grammar as memory builds it: learned from {view.learned_from:,} taught sentences, "
        f"{time.perf_counter() - started:.0f}s")

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
        dev.append((document.text, said.meaning, gm.align_by_anchors(tokens, document.text, anchors)))
    held_out = {text.strip() for text, _, _ in dev}
    EV.metric("PMB dev sentences scored", len(dev), unit="sentences")

    def score(label: str) -> dict:
        """The dev split read now, as GRAMMAR-01 scores it: whole meanings right, senses aside, and facts' F1."""
        readings = [view.grammar.read(gm.tokens_of(text, words)) for text, _, _ in dev]
        right = tp = fp = fn = whole = 0
        for (text, meaning, at), r in zip(dev, readings):
            names = {}
            if r.sign is not None:
                whole += 1
                for p in r.sign.pieces:
                    if p[0] == "word":
                        for k in range(p[3], p[4]):
                            names.setdefault(k, p[1])
            want = g01.senses_aside(meaning, at, names)
            w = g01.grounded(want, is_variable)
            if r.meaning is None:
                fn += sum(w.values())
                continue
            right += r.meaning.canonical() == want.canonical()
            g = g01.grounded(r.meaning, is_variable)
            tp += sum((g & w).values())
            fp += sum((g - w).values())
            fn += sum((w - g).values())
        p, rc = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        out = {"read_whole": whole, "right": right, "right_share": round(right / len(dev), 4),
               "precision": round(p, 4), "recall": round(rc, 4), "f1": round(2 * p * rc / max(p + rc, 1e-9), 4)}
        EV.metric(f"{label}: dev read whole / right whole (senses aside) / facts F1",
                  [whole, right, out["f1"]], note=f"precision {out['precision']}, recall {out['recall']}")
        say(f"  {label}: read whole {whole:,}, right whole {right:,} ({out['right_share']:.1%}), facts precision "
            f"{p:.1%}, recall {rc:.1%}, F1 {out['f1']:.1%}")
        return out

    before = score("before reading")

    # ── the reading: the PMB's silver documents, their text alone ──
    raws = sorted((pmb / "data" / "en" / "silver").rglob("en.raw"))
    random.Random(SEED).shuffle(raws)
    known_before = set(words.form_uses)
    after, read, taught, total, kinds = {}, 0, 0, 0.0, 0
    waiting: list = []
    with gm.reading_teaches():
        for stretch in stretches:
            t0 = time.perf_counter()
            while read < stretch and (waiting or raws):
                if not waiting:
                    text = " ".join(raws.pop().read_text(encoding="utf-8").split())
                    if not text or text in held_out:
                        continue
                    waiting = sentences_of(text, ends)
                    continue
                read += 1
                before_count = len(view._read)
                reading = view.read(waiting.pop(0))
                taught += len(view._read) - before_count
                kinds += len(told_kinds(reading, view.words))
            total += time.perf_counter() - t0
            new_words = len(set(words.form_uses) - known_before)
            EV.metric(f"after reading {read:,}: sentences that taught (read whole), new words known, kinds of "
                      f"named things taken in", [taught, new_words, kinds], note=f"{total:.0f}s reading")
            say(f"read {read:,} sentences ({taught:,} read whole, teaching how their words are used; {new_words:,} "
                f"words known now that were not; {kinds:,} kinds of named things taken in), {total:.0f}s")
            after[read] = score(f"after reading {read:,}")
    last = after[max(after)]
    EV.check("more held-out meanings read right whole after reading than before (senses aside)",
             last["right"] > before["right"], f"{before['right']} -> {last['right']}")
    EV.check("the facts read are no less right after reading (F1)", last["f1"] >= before["f1"],
             f"{before['f1']} -> {last['f1']}")
    EV.note("the dev split is held out: no dev sentence is read, and scoring reads with `grammar.read`, which teaches "
            "nothing; only `GrammarView.read` inside `reading_teaches` does")
    path = EV.write()
    say(f"run record: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
