#!/usr/bin/env python3
"""SENSE-RELATED-01 — how what a sense is connected to in the rest of what is said is put together with how often
the sense is met: which way takes the sense meant.

The listener (`derived_reader.meant`) weighs, for a word that names several things, how many of the other things
said each sense is connected to in memory (`MemoryAgent.listening_evidence`, `related`), and how often each sense has
been met under the word (its base level). It took the connections first, as a rank of their own, with the base level
only on a tie. This measures, offline, which way of putting the two together picks the sense WordNet's own authors
tagged, on every noun in WordNet's hand-tagged definitions (the Princeton WordNet Gloss Corpus) whose word has two
or more noun senses, the rest of its definition's tagged words being what else is said:

  A  the most frequent sense alone (WordNet's tagged counts)
  B  the strict order: how many of the other things said a sense is connected to first, frequency only on a tie
  C  one activation, ACT-R's: `ln(1 + uses)` plus, from each other thing said that the sense is connected to, its
     associative strength by ACT-R's own definition, `ln(P(i|j) / P(i))`, with `P(i|j) = 1 / fan_j` (the things j
     is connected to in memory) and `P(i) = 1 / m` (every thing in memory), each source weighted `1 / n` of n

Connected is the listener's relation exactly (`listening_evidence.connected`): one a near kind of the other, or both
near kinds of one thing, or a fact of any kind between them or between their near kinds (`KINDS_NEAR` = 2), over the
relations WordNet teaches (`WordNetSource.records`: isa, instance_of, part_of, member_of, made_of, similar_to,
requires, causes, defined_with, antonym_of). Three sources, none of them the test: how often each sense is met from
WordNet's counts (SemCor), the relations from WordNet and the definitions' links from the Gloss Corpus. A noun whose
connections pass through the sense whose definition it is in is left out, so no definition is read to choose a word
in itself. No store, no substrate; nothing is written but the record.

Run: ./venv_lyric/bin/python3 experiments/SENSE-RELATED-01/experiment.py
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
    "SENSE-RELATED-01",
    claim=("How many of the other things said a sense is connected to, added to how often the sense is met as ACT-R's "
           "spreading activation, takes more of the senses WordNet's authors tagged than taken first with frequency "
           "only on a tie, and more than the most frequent sense alone."),
    hypothesis=("The strict order (B) taking as many tagged senses as the activation (C), or the activation taking no "
                "more than the most frequent sense (A), would each show here."))
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
    from nltk.corpus.reader.wordnet import WordNetError
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordNetSource

    near_depth = MemoryAgent.KINDS_NEAR
    source = WordNetSource()
    every = list(wn.all_synsets())
    index = {s: i for i, s in enumerate(every)}
    m = len(every)
    defined = source._definition_links()
    say_line(f"== Memory as WordNet teaches it: {m} things ==")

    def said_of(s) -> set:
        """What memory holds said of a thing, each relation from it to another (`WordNetSource.records`)."""
        out = set(s.hypernyms()) | set(s.instance_hypernyms()) | set(s.part_holonyms()) | set(s.member_holonyms())
        out |= set(s.substance_meronyms()) | set(s.similar_tos()) | set(s.entailments()) | set(s.causes())
        out |= set(defined.get(s, ()))
        out |= {a.synset() for lemma in s.lemmas() for a in lemma.antonyms()}
        out.discard(s)
        return {index[t] for t in out if t in index}

    said = [said_of(s) for s in every]
    up = [[index[k] for k in s.hypernyms() + s.instance_hypernyms() if k in index] for s in every]
    near = []
    for i in range(m):
        found, frontier = {i}, [i]
        for _ in range(near_depth):
            frontier = [k for f in frontier for k in up[f] if k not in found]
            found.update(frontier)
        near.append(frozenset(found))
    reach = [frozenset(t for k in near[i] for t in said[k]) for i in range(m)]
    inv_near, inv_reach = collections.defaultdict(set), collections.defaultdict(set)
    for i in range(m):
        for x in near[i]:
            inv_near[x].add(i)
        for x in reach[i]:
            inv_reach[x].add(i)

    def connected(a: int, b: int) -> bool:
        return bool(near[a] & near[b] or reach[a] & near[b] or reach[b] & near[a])

    fans = {}

    def fan(j: int) -> int:
        """How many things memory holds connected to j: j's fan."""
        if j not in fans:
            out = set()
            for x in near[j] | reach[j]:
                out |= inv_near[x]
            for x in near[j]:
                out |= inv_reach[x]
            fans[j] = len(out)
        return fans[j]

    def met(synset, lemma) -> float:
        return math.log1p(next((l.count() for l in synset.lemmas() if l.name().lower() == lemma), 0))

    # The nouns: tagged by hand with one sense, their word with two or more; the rest of the definition's tagged
    # words are what else is said.
    corpus = Path(str(nltk.data.find(source.GLOSS_CORPUS)))
    items, skipped = [], 0
    for part in ("noun", "verb", "adj", "adv"):
        for _, element in ET.iterparse(corpus / f"{part}.xml"):
            if element.tag != "synset":
                continue
            owner = wn.synset_from_pos_and_offset(element.get("pos"), int(element.get("ofs")))
            for definition in element.iter("def"):
                tokens = []
                for token in definition.iter():
                    if token.tag not in ("wf", "glob") or token.get("tag") not in ("man", "auto"):
                        continue
                    ids = [i.get("sk") for i in token.findall("id") if i.get("sk")
                           and not i.get("sk").startswith("purposefully_ignored%")]
                    if len(ids) != 1:
                        continue
                    try:
                        lemma = wn.lemma_from_key(ids[0])
                    except WordNetError:
                        continue
                    tokens.append((token.get("tag"), token.get("pos") or "", lemma))
                for at, (tag, pos, lemma) in enumerate(tokens):
                    sense = lemma.synset()
                    word = lemma.name().lower()
                    if tag != "man" or not pos.startswith("NN") or sense.pos() != "n":
                        continue
                    senses = wn.synsets(word, wn.NOUN)
                    if len(senses) < 2 or sense not in senses:
                        continue
                    context = [index[l.synset()] for k, (_, _, l) in enumerate(tokens) if k != at
                               and l.synset() in index and l.synset() not in senses]
                    context = list(dict.fromkeys(context))
                    own = index[owner]
                    if any(own in near[c] for c in context) or any(own in near[index[s]] for s in senses):
                        skipped += 1
                        continue
                    items.append((word, sense, senses, context))
            element.clear()
    say_line(f"== Nouns from the hand-tagged definitions: {len(items)} ({skipped} left out: their connections pass "
             f"through the sense being defined) ==")

    def related(s, context) -> int:
        return sum(1 for j in context if connected(index[s], j))

    def spread(s, context) -> float:
        if not context:
            return 0.0
        return sum(math.log(m / fan(j)) for j in context if connected(index[s], j)) / len(context)

    rules = {
        "A most frequent sense": lambda w, s, ctx: (met(s, w),),
        "B strict: connected first, then frequency": lambda w, s, ctx: (related(s, ctx), met(s, w)),
        "C one activation, ACT-R's spreading activation": lambda w, s, ctx: (met(s, w) + spread(s, ctx),),
    }
    taken, coarse, apart = {}, {}, {}
    differs = [it for it in items if len({related(s, it[3]) for s in it[2]}) > 1]
    say_line(f"== Of those, {len(differs)} where the senses are connected to the rest unequally ==")
    for name, rule in rules.items():
        right = near_right = right_apart = 0
        for word, sense, senses, context in items:
            # In one order, so a tie is broken the same way in every process: WordNet's, by frequency.
            best = max(senses, key=lambda s: rule(word, s, context) + (-senses.index(s),))
            right += best == sense
            near_right += best.lexname() == sense.lexname()
        for word, sense, senses, context in differs:
            best = max(senses, key=lambda s: rule(word, s, context) + (-senses.index(s),))
            right_apart += best == sense
        taken[name[0]], coarse[name[0]], apart[name[0]] = right, near_right, right_apart
        say_line(f"    {name:50s} {right}/{len(items)} ({100 * right / len(items):.1f}%; coarse "
                 f"{100 * near_right / len(items):.1f}%); where connections differ {right_apart}/{len(differs)} "
                 f"({100 * right_apart / max(1, len(differs)):.1f}%)")
        EV.metric(f"{name}", f"{right}/{len(items)}")
        EV.metric(f"{name}, coarse", f"{near_right}/{len(items)}")
        EV.metric(f"{name}, where connections differ", f"{right_apart}/{len(differs)}")

    check("the activation takes more tagged senses than the strict order",
          taken["C"] > taken["B"], f"{taken['C']} against {taken['B']}")
    check("the activation takes more tagged senses than the most frequent sense",
          taken["C"] > taken["A"], f"{taken['C']} against {taken['A']}")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SENSE-RELATED-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
