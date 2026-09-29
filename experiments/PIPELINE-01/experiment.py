#!/usr/bin/env python3
"""PIPELINE-01 — one teaching pipeline, and it owns the policy.

There were seven teaching scripts. `learn_facts()` underneath them was already
the one authority; what was duplicated was the POLICY — which source, what to
harvest, which relations survive, what quality applies, whether the part of
speech lives. Both ConceptNet scripts carried verbatim copies of a `_term()`
that NAMES the part of speech in its own docstring and discards it.

A shared helper would not have fixed that. Seven scripts importing one `_term()`
is seven pipelines agreeing about one function. So the split here is:

    Source        reads a format. Yields records, states its own support.
                  Decides NOTHING about teaching.
    TeachingPass  decides everything else: how much of the source to take and
                  how to sample it, the quality floor, that word classes come
                  from the source's own tags, the one call to the one learning
                  authority, and what the session reports.

  A  A SOURCE DECIDES NOTHING   no domain, floor, limit or authority on it.
  B  THE PART OF SPEECH LIVES   ConceptNet's URI tag reaches the record.
  C  THE WEIGHT BECOMES A       a distribution of qualities, not one unstated
     QUALITY, AND GATES         number; the 0.5-weight tail is refused.
  D  A LIMIT SAMPLES THE WHOLE  the first N of a sorted dump is its alphabetical
     SOURCE, NOT ITS HEAD       head, not a sample of English.
  E  IT TEACHES THROUGH THE     facts and word classes both land, in one pass.
     ONE AUTHORITY
  F  A CROWD GRAPH CANNOT      ConceptNet may not supply the relations the
     BECOME THE REASONING      reasoner walks transitively, however well
     TAXONOMY                  attested -- `apple isa car` is well attested.

Run: PYTHONPATH="$PWD" ./venv_torin/bin/python3 experiments/PIPELINE-01/experiment.py
"""
import asyncio
import contextlib
import inspect
import io
import itertools
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1",
               "TORIN_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, str(ROOT))

from core.learning.teaching import (DEFAULT_QUALITY_FLOOR, Report,  # noqa: E402
                                    TaughtRecord, TeachingPass,
                                    quality_from_corroboration)
from core.learning.teaching_sources import ConceptNetSource  # noqa: E402
from core.learning.unified_learning_system import (  # noqa: E402
    UnifiedLearningSystem)

DUMP = str(ROOT / "data" / "bulk" / "conceptnet-assertions-5.7.0.csv.gz")
PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    good = got == want
    PASS, FAIL = PASS + good, FAIL + (not good)
    print(f"  {'PASS' if good else 'FAIL'}  {label}")
    if not good:
        print(f"          got={got!r}  want={want!r}")


@dataclass
class _Ordered:
    """A stand-in for a SORTED dump: record 0 is the head, 9,999 is the tail."""

    count: int = 10000
    name: str = "ordered"
    curated: bool = True
    #: A SOURCE STATES ITS OWN EVIDENCE QUALITY, and this stub did not. Every
    #: real source declares `quality` (WordNet 0.9, closed-classes 0.95) and the
    #: pass reads it when it teaches that source's word classes, so a stand-in
    #: without it is not standing in for a source -- it raises AttributeError the
    #: moment the pass reaches that step. Stated here at the curated default,
    #: rather than making the pass tolerate a source that cannot say how good its
    #: evidence is: a default that cannot be told from a judgement once it is in
    #: the store is exactly what `_fan_out_learning` removed.
    quality: float = 0.9

    def provenance(self):
        from core.semantics.cognitive_ingress import Provenance
        return Provenance(producer="pipeline01", source_id="ordered",
                          source_type="USER_SUPPLIED")

    def records(self) -> Iterator[TaughtRecord]:
        for i in range(self.count):
            yield TaughtRecord(subject=f"p01x{i:05d}", relation="isa",
                               obj="p01kind", quality=0.9)


print(__doc__.split("Run:")[0].rstrip())

print("\n" + "=" * 72)
print("A  A SOURCE DECIDES NOTHING")
print("=" * 72)
source_fields = set(inspect.signature(ConceptNetSource).parameters)
pass_fields = set(inspect.signature(TeachingPass.__init__).parameters)
print(f"  ConceptNetSource takes : {sorted(source_fields)}")
print(f"  TeachingPass takes     : {sorted(pass_fields - {'self'})}")
check("no policy knob is on the source",
      sorted(source_fields & {"domain", "quality_floor", "limit", "sample"}), [])
check("every policy knob is on the pass",
      sorted(pass_fields & {"domain", "quality_floor", "limit", "sample"}),
      ["domain", "limit", "quality_floor", "sample"])

print("\n" + "=" * 72)
print("B  THE PART OF SPEECH LIVES")
print("=" * 72)
started = time.time()
sample = list(itertools.islice(ConceptNetSource(path=DUMP).records(), 4000))
tagged = [r for r in sample if r.word_classes]
print(f"  read {len(sample):,} ConceptNet records in {time.time() - started:.0f}s")
print(f"  carrying at least one stated word class: {len(tagged):,} "
      f"({100 * len(tagged) / len(sample):.1f}%)")
print(f"  e.g. {tagged[0].subject!r} / {tagged[0].obj!r} -> {tagged[0].word_classes}")
check("the URI's POS tag reaches the record", bool(tagged), True)
# THE CLASSES THE SUBSTRATE ACTUALLY HOLDS, ASKED OF THE AUTHORITY.
#
# This asserted membership of a hardcoded ("NOUN", "VERB", "ADJECTIVE") and
# called them "the classes the lexicon holds". Both halves went stale: there is
# no lexicon (word classes are taught into memory), and the substrate holds
# NINETEEN classes, not three. ConceptNet URIs carry `/r` for adverbs and
# `_POS_CLASS` now maps it, so a perfectly good ADVERB failed a check that was
# describing a world two rebuilds ago. Asking the authority means the check
# cannot go stale again the next time a class is added.
_stated = {c for r in tagged for _, c in r.word_classes}
print(f"  classes stated by the source: {sorted(_stated)}")
check("and every one is a class the substrate holds",
      _stated <= set(UnifiedLearningSystem.WORD_CLASSES), True)

print("\n" + "=" * 72)
print("C  THE WEIGHT BECOMES A QUALITY, AND GATES")
print("=" * 72)
qualities = Counter(round(r.quality, 3) for r in sample)
below = sum(n for q, n in qualities.items() if q < DEFAULT_QUALITY_FLOOR)
print(f"  floor = {DEFAULT_QUALITY_FLOOR}  (= 'one real source asserts this')")
print(f"  qualities seen: {dict(qualities.most_common(5))}")
print(f"  below the floor: {below:,} ({100 * below / len(sample):.1f}%)")
for weight in (0.5, 1.0, 2.0, 4.47):
    print(f"    ConceptNet weight {weight:<5} -> quality "
          f"{quality_from_corroboration(weight):.3f}")
check("a corpus no longer teaches everything at one number",
      len(qualities) > 1, True)
check("the 0.5-weight tail is below the floor",
      quality_from_corroboration(0.5) < DEFAULT_QUALITY_FLOOR, True)
check("one real source clears it",
      quality_from_corroboration(1.0) >= DEFAULT_QUALITY_FLOOR, True)

print("\n" + "=" * 72)
print("D  A LIMIT SAMPLES THE WHOLE SOURCE, NOT ITS HEAD")
print("=" * 72)
head = TeachingPass(_Ordered(), domain="d", limit=100, sample=False)
spread = TeachingPass(_Ordered(), domain="d", limit=100, sample=True)
head_records = head._harvest(Report(source="o", domain="d"))
spread_records = spread._harvest(Report(source="o", domain="d"))


def span(records):
    ordinals = [int(r.subject[4:]) for r in records]
    return min(ordinals), max(ordinals)

print(f"  sample=False -> ordinals {span(head_records)}   (the head)")
print(f"  sample=True  -> ordinals {span(spread_records)}   (across the stream)")
print(f"  real dump: the FIRST english IsA edge is at line 17,111,508, and the")
print(f"             alphabetical head is '0_10_0', '1,000_megawatt_plutonium_reactor'")
check("the head is the head", span(head_records), (0, 99))
check("a sample reaches the far end of the stream",
      span(spread_records)[1] > 9000, True)
check("and takes exactly the asked-for count", len(spread_records), 100)

print("\n" + "=" * 72)
print("E  IT TEACHES THROUGH THE ONE AUTHORITY")
print("=" * 72)


async def teach() -> Report:
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.initialize()

        stamp = time.strftime("%H%M%S")

        @dataclass
        class _Small:
            name: str = "pipeline01"
            curated: bool = True
            #: Declared for the same reason as `_Ordered.quality` above: this
            #: stub DOES reach the word-class step (its records carry
            #: `word_classes`), so the missing attribute stopped the round-trip
            #: check from running at all.
            quality: float = 0.9

            def provenance(self):
                from core.semantics.cognitive_ingress import Provenance
                return Provenance(producer="pipeline01",
                                  source_id=f"pipeline01_{stamp}",
                                  source_type="USER_SUPPLIED")

            def records(self):
                for i in range(6):
                    yield TaughtRecord(
                        subject=f"plk{stamp}n{i}", relation="isa",
                        obj=f"plp{stamp}", quality=0.8,
                        word_classes=((f"plk{stamp}n{i}", "NOUN"),))
                # Below the floor: must be refused BEFORE the round trip.
                yield TaughtRecord(subject=f"plk{stamp}weak", relation="isa",
                                   obj=f"plp{stamp}", quality=0.4)

        return await TeachingPass(_Small(), domain="pipeline01").run(
            system.autonomous_coordinator.learning)


report = asyncio.run(teach())
for line in report.lines():
    print(f"  {line}")
check("the below-floor record never reached the substrate",
      report.below_floor, 1)
check("the facts were admitted", report.taught.get("admitted"), 6)
check("and the stated word classes were taught",
      report.word_classes.get("total"), 6)

print("\n" + "=" * 72)
print("F  A CROWD GRAPH CANNOT BECOME THE REASONING TAXONOMY")
print("=" * 72)
# The rule `teach_conceptnet.py` broke: raw `/r/IsA` carries `apple isa car`
# and `dog isa cuter_than_kid`, and the reasoner walks isa TRANSITIVELY, so one
# bad edge is every conclusion reachable through it. The quality gate cannot
# help -- the junk is well attested. Enforced by the owner of the policy, so it
# holds for every source rather than being remembered per script.
crowd = ConceptNetSource(path=DUMP)
print(f"  conceptnet.curated = {crowd.curated}")
refused = None
try:
    TeachingPass(crowd, domain="general", limit=3, sample=False)._guard_reasoning_edges(
        [TaughtRecord("apple", "isa", "car", 0.9)])
except ValueError as error:
    refused = str(error)
print(f"  teaching 'apple isa car' from it -> "
      f"{'REFUSED' if refused else 'ALLOWED'}")
check("an uncurated source may not teach transitive relations",
      refused is not None, True)
check("a curated one may",
      TeachingPass(_Ordered(), domain="d")._guard_reasoning_edges(
          [TaughtRecord("robin", "isa", "bird", 0.9)]) is None, True)

print("\n" + "=" * 72)
print("G  A NAME THE READER SPLIT IS NOT A CLAIM")
print("=" * 72)
# The reader distributes a coordinated subject and truncates a coordinated
# object -- correct for prose ("cats and dogs are animals"), and it has no way
# to know `track and field` is ONE name. The SOURCE does, and says so, and the
# read claims were REPLACING the stated triple.
#
# Measured on WordNet: 115 of 83,093 facts state a subject carrying "and"/"or"
# and 6 state such an object. Small count, unbounded damage -- `isa` is walked
# transitively, so `track isa diversion sport` and `field isa diversion sport`
# drag `field`'s whole subtree under sport. Same shape as the gloss-derived
# `inheritance isa x_linked_recessive` that reparented 65,056 concepts.
#
# The two failures differ in kind. A distributed SUBJECT is visibly wrong. A
# truncated OBJECT is not: `jumping isa track` is a well-formed edge to the
# wrong parent, and nothing about it looks like a parse failure.
_teacher = TeachingPass(_Ordered(), domain="d")
SEGMENTED = [
    # (subject, relation, object, sentence, what the reader does to it)
    ("track and field", "isa", "diversion sport",
     "A track and field is a diversion sport.", "subject distributed"),
    ("bait and switch", "isa", "selling",
     "A bait and switch is a selling.", "subject distributed"),
    ("jumping", "isa", "track and field",
     "A jumping is a track and field.", "object truncated"),
    ("songwriter domino", "isa", "rhythm and blues musician",
     "A songwriter domino is a rhythm and blues musician.", "object truncated"),
    ("track and field track", "isa", "track and field",
     "A track and field track is a track and field.", "both ends"),
    # NOT a coordination. Found by sweeping 3,000 records for over-reach: the
    # reader strips the preposition off a name and `road isa travel` is false
    # where `on the road isa travel` is the fact. Same defect, different word.
    ("on the road", "isa", "travel", "An on the road is a travel.",
     "preposition stripped"),
]
for subject, relation, obj, sentence, how in SEGMENTED:
    record = TaughtRecord(subject=subject, relation=relation, obj=obj,
                          quality=0.9, sentence=sentence)
    read, _blamed = _teacher._read(sentence)
    kept, cut = _teacher._drop_segmented_claims(record, read)
    print(f"  {how:20} {sentence}")
    print(f"      read {[(c[0], c[2]) for c in read]} -> kept {[(c[0], c[2]) for c in kept]}")
    check(f"a segmented reading of {subject!r} teaches nothing", (kept, cut), ([], True))

# AND THE STATED TRIPLE IS NOT LOST WITH IT. A source is never worse off for
# being able to say itself -- the rule the pipeline already states for a
# sentence that does not read at all.
INTACT = [
    ("pump", "isa", "device", "A pump is a device that moves fluid."),
    ("robin", "isa", "bird", "A robin is a bird."),
    ("fundamental quantity", "isa", "abstraction measure",
     "A fundamental quantity is an abstraction measure."),
]
for subject, relation, obj, sentence in INTACT:
    record = TaughtRecord(subject=subject, relation=relation, obj=obj,
                          quality=0.9, sentence=sentence)
    read, _blamed = _teacher._read(sentence)
    kept, cut = _teacher._drop_segmented_claims(record, read)
    check(f"an ordinary reading of {subject!r} survives untouched",
          (kept, cut), (read, False))

print("\n" + "=" * 72)
print(f"{PASS}/{PASS + FAIL}")
print("=" * 72)
sys.exit(0 if not FAIL else 1)
