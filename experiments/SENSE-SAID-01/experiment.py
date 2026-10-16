#!/usr/bin/env python3
"""SENSE-SAID-01 — what a word is said of, and how often a sense is met: which way of putting them together takes
the sense meant.

The listener (`derived_reader.meant`) weighs, for a word that names several things, how often each thing has been
met under the word (its base level) and how much more likely each is given what the sentence's other word is said
of (`MemoryAgent.said_selection`, Resnik 1997). This measures, offline, which way of putting the two together picks
the sense WordNet's own authors tagged, on every adjective–noun and verb–object pair in WordNet's hand-tagged
definitions (the Princeton WordNet Gloss Corpus) whose noun has two or more senses and whose adjective or verb the
Brown corpus says of something:

  A  the most frequent sense alone (WordNet's tagged counts)
  B  the strict order: what the word is said of first, frequency only on a tie
  C  one activation, `ln(1 + uses) + ln(P(k|w) / P(k))`, at the kind Resnik's association picks
  D  one activation, at the sense's most specific kind anything is said of
  E  one activation, averaged over every kind the sense is (the listener's)

Three sources, none of them the test: what words are said of from the Brown corpus (`WordNetSource.said_of`), how
often each sense is met from WordNet's counts (SemCor), each sense's kinds from WordNet. The definitions were tagged
by hand, apart from all three. No store, no substrate; nothing is written but the record.

Run: ./venv_lyric/bin/python3 experiments/SENSE-SAID-01/experiment.py
"""
from __future__ import annotations

import collections
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "SENSE-SAID-01",
    claim=("What a word is said of, added to how often each sense is met as one activation, takes more of the senses "
           "WordNet's authors tagged than how often each sense is met alone; taken first, with frequency only on a "
           "tie, it takes fewer."),
    hypothesis=("The listener's activation (E) taking no more tagged senses than the most frequent sense (A), or the "
                "strict order (B) taking as many, would each show here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    import nltk
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import WordNetSource

    source = WordNetSource()
    said = collections.defaultdict(collections.Counter)
    for relation, word, _, other, times in source.said_of():
        said[(relation, word)][other] += times
    say_line(f"== What words are said of, from Brown: {sum(sum(c.values()) for c in said.values())} uses of "
             f"{len(said)} words ==")

    kinds_of = {}

    def kinds(synset):
        if synset not in kinds_of:
            kinds_of[synset] = {k for path in synset.hypernym_paths() for k in path}
        return kinds_of[synset]

    def spread(others):
        """How uses are spread over kinds, a word shared among its noun senses; and how many uses."""
        out, total = collections.Counter(), 0
        for word, times in others.items():
            senses = wn.synsets(word, wn.NOUN)
            if not senses:
                continue
            total += times
            for synset in senses:
                for kind in kinds(synset):
                    out[kind] += times / len(senses)
        return ({k: v / total for k, v in out.items()} if total else {}), total

    prior = {}
    for relation in ("has_property", "done_to"):
        every = collections.Counter()
        for (r, _), others in said.items():
            if r == relation:
                every.update(others)
        prior[relation] = spread(every)[0]
    given_of = {}

    def given(relation, word):
        if (relation, word) not in given_of:
            given_of[(relation, word)] = spread(said[(relation, word)])
        return given_of[(relation, word)]

    def likely(relation, word, kind):
        """`P(k|w)` with one use spread as anything is, as the listener has it."""
        shares, uses = given(relation, word)
        return (uses * shares.get(kind, 0.0) + prior[relation][kind]) / (uses + 1)

    def lift(relation, word, kind):
        return math.log(likely(relation, word, kind) / prior[relation][kind])

    def kinds_said(relation, synset):
        # In one order, so the same sums come out the same in every process.
        return sorted((k for k in kinds(synset) if prior[relation].get(k)), key=lambda k: k.name())

    def resnik(relation, word, synset):
        shares, _ = given(relation, word)
        return max((shares[k] * math.log(shares[k] / prior[relation][k]) for k in kinds_said(relation, synset)
                    if shares.get(k)), default=0.0)

    def at_resnik_kind(relation, word, synset):
        found = kinds_said(relation, synset)
        if not found:
            return 0.0
        best = max(found, key=lambda k: (likely(relation, word, k) * lift(relation, word, k), k.name()))
        return lift(relation, word, best)

    def at_own_kind(relation, word, synset):
        found = sorted(kinds_said(relation, synset), key=lambda k: (-k.max_depth(), k.name()))
        return lift(relation, word, found[0]) if found else 0.0

    def averaged(relation, word, synset):
        found = kinds_said(relation, synset)
        return sum(lift(relation, word, k) for k in found) / len(found) if found else 0.0

    def met(synset, lemma):
        return math.log1p(next((l.count() for l in synset.lemmas() if l.name().lower() == lemma), 0))

    # The pairs: an adjective or a verb, then the noun it stands before, the noun tagged by hand with one sense.
    corpus = Path(str(nltk.data.find(source.GLOSS_CORPUS)))
    pairs = []
    for part in ("noun", "verb", "adj", "adv"):
        for _, element in ET.iterparse(corpus / f"{part}.xml"):
            if element.tag != "synset":
                continue
            for definition in element.iter("def"):
                tokens = [t for t in definition if t.tag == "wf"]
                for before, noun in zip(tokens, tokens[1:]):
                    ids = noun.findall("id")
                    if noun.get("tag") != "man" or not (noun.get("pos") or "").startswith("NN") or len(ids) != 1:
                        continue
                    try:
                        sense = wn.lemma_from_key(ids[0].get("sk")).synset()
                    except Exception:
                        continue
                    lemma = ids[0].get("lemma", "").replace(" ", "_").lower()
                    if sense.pos() != "n" or len(wn.synsets(lemma, wn.NOUN)) < 2:
                        continue
                    tag, written = before.get("pos") or "", (before.text or "").strip().lower()
                    if tag == "JJ":
                        relation, word = "has_property", wn.morphy(written, wn.ADJ)
                    elif tag.startswith("VB"):
                        relation, word = "done_to", wn.morphy(written, wn.VERB)
                    else:
                        continue
                    if word and said.get((relation, word)):
                        pairs.append((relation, word, lemma, sense))
            element.clear()
    by_relation = collections.Counter(p[0] for p in pairs)
    say_line(f"== Pairs from the hand-tagged definitions: {len(pairs)} ({dict(by_relation)}) ==")

    rules = {
        "A most frequent sense": lambda r, w, l, s: (met(s, l),),
        "B strict: said of first, then frequency": lambda r, w, l, s: (round(resnik(r, w, s), 9), met(s, l)),
        "C activation at Resnik's kind": lambda r, w, l, s: (met(s, l) + at_resnik_kind(r, w, s),),
        "D activation at the sense's own kind": lambda r, w, l, s: (met(s, l) + at_own_kind(r, w, s),),
        "E activation over every kind (the listener's)": lambda r, w, l, s: (met(s, l) + averaged(r, w, s),),
    }
    taken, coarse = {}, {}
    for name, rule in rules.items():
        right, near = collections.Counter(), collections.Counter()
        for relation, word, lemma, sense in pairs:
            best = max(wn.synsets(lemma, wn.NOUN), key=lambda s: rule(relation, word, lemma, s))
            right[relation] += best == sense
            # The coarse sense: WordNet's lexicographer class ("noun.artifact", "noun.food").
            near[relation] += best.lexname() == sense.lexname()
        taken[name[0]], coarse[name[0]] = right, near
        shown = "  ".join(f"{r} {right[r]}/{by_relation[r]} ({100 * right[r] / by_relation[r]:.1f}%; coarse "
                          f"{100 * near[r] / by_relation[r]:.1f}%)" for r in sorted(by_relation))
        say_line(f"    {name:48s} {shown}")
        for r in sorted(by_relation):
            EV.metric(f"{name}: {r}", f"{right[r]}/{by_relation[r]}")
            EV.metric(f"{name}: {r}, coarse", f"{near[r]}/{by_relation[r]}")

    check("the listener's activation takes more tagged senses than the most frequent sense, for both relations",
          all(taken["E"][r] > taken["A"][r] for r in by_relation),
          ", ".join(f"{r} {taken['E'][r]} against {taken['A'][r]}" for r in sorted(by_relation)))
    check("the strict order takes fewer than the most frequent sense, for both relations",
          all(taken["B"][r] < taken["A"][r] for r in by_relation),
          ", ".join(f"{r} {taken['B'][r]} against {taken['A'][r]}" for r in sorted(by_relation)))

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SENSE-SAID-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
