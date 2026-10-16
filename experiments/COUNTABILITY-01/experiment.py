#!/usr/bin/env python3
"""COUNTABILITY-01 — whether a noun sense is counted, decided by what it is a kind of, measured on hand labels it was
not given.

WordNet says what a noun names, never whether it is counted, and a fact said with the wrong one is wrong English the
reader then learns ("A table is a furniture."). `WordNetSource.use_of` states a sense's use: only ever plural or one in
both from real text; else the sense's own hand label in the Bochum English Countability Lexicon (BECL); else what the
labelled senses of its nearest kind carry, within the Tolerance Principle (`_sense_uses`); else the word's uses in the
Brown corpus (`_uses`). The word uncounted in real text comes before the kind for the sense the word is mostly used in.

This measures that on BECL's own counted and uncounted senses, held out five ways by word: each fold's senses are
decided by a source given only the other folds' labels, so neither the sense nor any sense written with the same
word is labelled for it. Five rules decide each held-out sense:

  A  every sense counted
  B  the Brown model alone (the word's uses in real text)
  C  the kind alone (the labelled senses of its nearest kind)
  D  the kind, then the word's uses (the order first built)
  E  the source's chain (`use_of`): the word uncounted first for its main sense, then the kind, then the word

No store, no substrate; nothing is written but the record.

Run: ./venv_lyric/bin/python3 experiments/COUNTABILITY-01/experiment.py
"""
from __future__ import annotations

import collections
import csv
import hashlib
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "COUNTABILITY-01",
    claim=("Whether a noun sense is counted, decided by the hand-labelled senses of its kind, finds more of the "
           "uncounted senses a hand-made lexicon holds than the word's uses in real text, and the source's chain is "
           "right more often than calling every sense counted or than real text alone, on senses whose labels it was "
           "not given."),
    hypothesis=("The kind finding no more held-out uncounted senses than the Brown model, the chain being right no "
                "more often than calling every sense counted, or the word's uncounted use put first being right less "
                "often than the kind first, would each show here."))
TRANSCRIPT = []
FOLDS = 5
#: Senses whose use was looked at by hand when step 1 was written (GENERALIZING_BY_KIND.md §1, HANDOFF.md).
PROBES = (("fish.n.01", "fish"), ("fish.n.02", "fish"), ("rice.n.01", "rice"), ("coffee.n.01", "coffee"),
          ("baggage.n.01", "baggage"), ("impedimenta.n.02", "baggage"), ("chairman.n.01", "chairman"),
          ("water.n.01", "water"), ("furniture.n.01", "furniture"), ("advice.n.01", "advice"),
          ("pisces.n.01", "Fish"), ("table.n.02", "table"))


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def fold_of(word: str) -> int:
    return hashlib.md5(word.encode("utf-8")).digest()[0] % FOLDS


def main() -> int:
    from nltk.corpus import wordnet as wn
    from nltk.corpus.reader.wordnet import WordNetError
    from core.learning.teaching_sources import WordNetSource

    started = time.monotonic()
    whole = WordNetSource()
    becl = Path(str(__import__("nltk").data.find(WordNetSource.BECL)))
    with open(becl, encoding="latin-1", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        fields, rows = reader.fieldnames, list(reader)

    # Each labelled sense once, with the word it is written with, held out with every other sense of that word.
    labels, word_of, classes = {}, {}, collections.Counter()
    for row in rows:
        try:
            synset = wn.synset(row["sense_synset"])
        except (WordNetError, ValueError, KeyError):
            continue
        classes[row["major_class"]] += 1
        use = {"regular_count": "count", "regular_mass": "mass"}.get(row["major_class"])
        if use and synset not in labels:
            labels[synset], word_of[synset] = use, row["lemma"]
    fold = {synset: fold_of(word_of[synset]) for synset in labels}
    say_line(f"== BECL: {len(rows)} rows, {dict(classes)}; {len(labels)} counted or uncounted senses held out "
             f"{FOLDS} ways by word ==")
    EV.metric("labelled senses", len(labels))
    EV.metric("of them uncounted", sum(use == "mass" for use in labels.values()))

    # The Brown model reads no lexicon: worked out once and given to every fold's source.
    brown = whole._uses()
    say_line(f"== The Brown model states {len(brown)} words ({dict(collections.Counter(brown.values()))}), "
             f"{time.monotonic() - started:.0f} s ==")

    def written(synset, word):
        # The word as the source writes it for this sense: WordNet's own spelling of it ("Fish" for Pisces).
        return next((WordNetSource._written(name) for name in synset.lemma_names() if name.lower() == word.lower()),
                    word)

    decided = {rule: {} for rule in "ABCDEF"}
    capitals = set()
    with tempfile.TemporaryDirectory() as scratch:
        for held in range(FOLDS):
            out = Path(scratch) / f"becl_without_{held}.csv"
            with open(out, "w", encoding="latin-1", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
                writer.writeheader()
                for row in rows:
                    try:
                        synset = wn.synset(row["sense_synset"])
                    except (WordNetError, ValueError, KeyError):
                        synset = None
                    if synset is None or fold.get(synset) != held:
                        writer.writerow(row)
            source = WordNetSource(becl_path=str(out))
            source.__dict__["_noun_uses"] = brown
            sense_uses = source._sense_uses()
            test = [s for s in labels if fold[s] == held]
            for synset in test:
                word = written(synset, word_of[synset])
                head = word.split()[-1]
                if head != head.lower():
                    capitals.add(synset)
                decided["A"][synset] = "count"
                decided["B"][synset] = brown.get(head) if head == head.lower() else None
                decided["C"][synset] = sense_uses.get(synset)
                said = brown.get(head)
                decided["D"][synset] = (None if head != head.lower() else said if said in ("plural", "invariant")
                                        else (sense_uses.get(synset) or said))
                decided["E"][synset] = source.use_of(synset, word)
                # F: the word uncounted in real text decides every sense of it with no label, not its main sense
                # only; else as E.
                decided["F"][synset] = ("mass" if head == head.lower() and said == "mass" and " " not in word
                                        and not source._becl().get(synset) else decided["E"][synset])
            say_line(f"    fold {held}: {len(test)} senses held out, {time.monotonic() - started:.0f} s")

    names = {"A": "A every sense counted", "B": "B the Brown model alone", "C": "C the kind alone",
             "D": "D the kind, then the word", "E": "E the source's chain (use_of)",
             "F": "F as E, the word uncounted for every sense"}
    mass = sum(use == "mass" for use in labels.values())
    scored = {}
    say_line("\n== Held out ==")
    for rule, got in decided.items():
        stated = [s for s in labels if got[s] in ("count", "mass")]
        other = sum(got[s] in ("plural", "invariant") for s in labels)
        right = sum(got[s] == labels[s] for s in stated)
        found = sum(got[s] == "mass" and labels[s] == "mass" for s in labels)
        said_mass = sum(got[s] == "mass" for s in labels)
        # Over every held-out sense, what a rule leaves counted, as calling it counted would.
        overall = sum((got[s] if got[s] in ("count", "mass") else "count") == labels[s] for s in labels)
        scored[rule] = dict(stated=len(stated), right=right, found=found, said_mass=said_mass, overall=overall,
                            other=other)
        say_line(f"    {names[rule]:34s} decides {len(stated):5d}/{len(labels)} ({100 * len(stated) / len(labels):.1f}%)"
                 f"  right {right}/{len(stated) or 1} ({100 * right / (len(stated) or 1):.1f}%)"
                 f"  uncounted found {found}/{mass}, said {said_mass}"
                 f"  overall {100 * overall / len(labels):.1f}%"
                 + (f"  said plural or one in both {other}" if other else ""))
        EV.metric(f"{names[rule]}: decides", f"{len(stated)}/{len(labels)}")
        EV.metric(f"{names[rule]}: right where it decides", f"{right}/{len(stated)}")
        EV.metric(f"{names[rule]}: uncounted found", f"{found}/{mass}")
        EV.metric(f"{names[rule]}: said uncounted", said_mass)
        EV.metric(f"{names[rule]}: overall, the rest taken as counted", f"{overall}/{len(labels)}")
        if other:
            EV.metric(f"{names[rule]}: said plural or one in both", other)

    # A word WordNet writes capitalized is given no use: the senses that leaves out, and how their kind would take them.
    kinds_right = sum(decided["C"][s] == labels[s] for s in capitals)
    instances = sum(bool(s.instance_hypernyms()) for s in capitals)
    say_line(f"\n== Written capitalized: {len(capitals)} labelled senses ({instances} named things), given no use; "
             f"their kind decides {sum(decided['C'][s] in ('count', 'mass') for s in capitals)} and is right "
             f"{kinds_right}: " + ", ".join(f"{written(s, word_of[s])} ({s.name()} {labels[s]})"
                                           for s in sorted(capitals, key=lambda s: s.name())[:10]) + " ==")
    EV.metric("labelled senses written capitalized, given no use", len(capitals))
    EV.metric("of them named things", instances)
    EV.metric("of them the kind takes right", kinds_right)

    # Where the chain is wrong, by what WordNet files the sense under, so the errors are read as patterns.
    wrong = [s for s in labels if decided["E"][s] in ("count", "mass") and decided["E"][s] != labels[s]]
    by_file = collections.Counter((s.lexname(), labels[s]) for s in wrong)
    say_line(f"\n== The chain's {len(wrong)} wrong, by WordNet's file and the label ==")
    for (lexname, label), times in by_file.most_common(12):
        say_line(f"    {lexname:22s} labelled {label:5s} {times}")
    EV.metric("the chain's wrong, by file and label",
              {f"{lexname} {label}": times for (lexname, label), times in by_file.most_common(12)})
    for label in ("mass", "count"):
        sample = sorted((s for s in wrong if labels[s] == label), key=lambda s: s.name())[:12]
        say_line(f"    labelled {label}, said otherwise: "
                 + ", ".join(f"{word_of[s]} ({s.name()})" for s in sample))

    # What BECL labels both or neither, as the whole source states it.
    whole_uses = collections.defaultdict(collections.Counter)
    for row in rows:
        if row["major_class"] in ("both_mass_count", "neither_mass_count"):
            try:
                synset = wn.synset(row["sense_synset"])
            except (WordNetError, ValueError, KeyError):
                continue
            whole_uses[row["major_class"]][whole.use_of(synset, written(synset, row["lemma"])) or "none"] += 1
    for label, uses in sorted(whole_uses.items()):
        say_line(f"    BECL {label}: the source states {dict(uses)}")
        EV.metric(f"BECL {label}, as the source states it", dict(uses))

    say_line("\n== Probes, as the whole source states them ==")
    for name, word in PROBES:
        try:
            synset = wn.synset(name)
        except (WordNetError, ValueError):
            say_line(f"    {name}: no such sense")
            continue
        use = whole.use_of(synset, word)
        say_line(f"    {word:10s} {name:20s} {use}   ({synset.definition()[:60]})")
        EV.metric(f"probe {word} {name}", use)
    nouns = list(wn.all_synsets("n"))
    stated = sum(bool(whole.use_of(s, WordNetSource._written(s.lemma_names()[0]))) for s in nouns)
    say_line(f"    noun senses the whole source states a use for, by their first word: {stated}/{len(nouns)}")
    EV.metric("noun senses with a stated use", f"{stated}/{len(nouns)}")

    say_line("")
    a, b, c, d, e = (scored[r] for r in "ABCDE")
    check("the kind finds more held-out uncounted senses than the Brown model",
          c["found"] > b["found"], f"{c['found']} against {b['found']} of {mass}")
    check("the chain is right more often than calling every sense counted",
          e["overall"] > a["overall"], f"{e['overall']} against {a['overall']} of {len(labels)}")
    check("the chain is right more often than the Brown model alone",
          e["overall"] > b["overall"], f"{e['overall']} against {b['overall']} of {len(labels)}")
    check("the word's uncounted use first is right at least as often as the kind first",
          e["overall"] >= d["overall"], f"{e['overall']} against {d['overall']} of {len(labels)}")
    EV.metric("seconds", round(time.monotonic() - started))

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# COUNTABILITY-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
