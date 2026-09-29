#!/usr/bin/env python3
"""ATTEST-01 — a word class is EARNED by reading, not just asserted by a teacher.

The lexicon has always defined itself in terms of reading. Its statuses say so
verbatim: PROPOSED is "a teacher said so; no evidence yet", CONFIRMED is "a
sentence depending on it read successfully", REFUTED is one that "failed to
read". Its module docstring states the thesis outright -- "a model may propose,
the world attests."

None of it was wired. `confirm()` and `refute()` had NO caller anywhere in
`core/`; the only call sites in the repo were in EDU-16, an experiment built on
the now-deleted LLM teacher. So the substrate read constantly and earned
nothing. Measured on the live store before this: 92,404 PROPOSED, 65 CONFIRMED
(residue from those EDU-16 runs), 1 REFUTED -- 99.93% scaffold that had never
been tested against use, in a design whose stated goal is that the scaffold
could eventually be unplugged.

This is the missing half, and the thesis it serves is NO MODEL IN THE MIDDLE.
Whoever produced the sentence -- a person, a corpus, a model -- is irrelevant to
what the substrate ends up holding: the class is credited because the
substrate's OWN parse leaned on it and worked. A model can hand it the world;
it never hands it the knowledge.

  A  READING CONFIRMS        a sentence that reads credits every recorded class
                             it actually consulted.
  B  A BLAMED CLASS IS       a refusal ATTRIBUTED to a class counts against that
     REFUTED                 class -- which is how a noun wrongly recorded
                             ADJECTIVE by bulk teaching corrects itself.
  C  NO FALSE REFUTATION     a sentence that fails for any OTHER reason attests
                             nothing; the classes it consulted keep their
                             standing.
  D  ONE SENTENCE, ONE       a conditional reads through the reader three times
     ATTESTATION             and must be credited once, not three times.
  E  IT IS THE CHOKEPOINT    attestation hangs on the method every caller
                             actually uses, not only the public entry.

Run: PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/ATTEST-01/experiment.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import core.semantics.lexicon as lexmod
from core.semantics.lexicon import CONFIRMED, PROPOSED, REFUTED, Lexicon

# A THROWAWAY STORE, INSTALLED BEFORE ANYTHING READS. The real lexicon is 25 MB
# of taught vocabulary and an experiment must never mutate it -- attestation
# WRITES, so running this against the singleton would edit production data.
_tmp = Path(tempfile.mkdtemp()) / "lexicon.json"
lexmod._lexicon = Lexicon(path=_tmp)
lex = lexmod._lexicon

from core.semantics.sentence_reader import SentenceReader  # noqa: E402

reader = SentenceReader()
PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    good = got == want
    PASS, FAIL = PASS + good, FAIL + (not good)
    print(f"  {'PASS' if good else 'FAIL'}  {label}")
    if not good:
        print(f"          got={got!r}  want={want!r}")


print(__doc__.split("Run:")[0].rstrip())
print("\n" + "=" * 72)
print("A  READING CONFIRMS")
print("=" * 72)
lex.propose("tank", "NOUN", "taught")
lex.propose("heavy", "ADJECTIVE", "taught")
print(f"  before: tank={lex.entry('tank').status}, heavy={lex.entry('heavy').status}")
node = reader._parse_statement("the tank is heavy")
print(f"  'the tank is heavy' -> {None if node is None else node.get('kind')}")
check("the subject's NOUN is confirmed", lex.entry("tank").status, CONFIRMED)
check("the complement's ADJECTIVE is confirmed", lex.entry("heavy").status, CONFIRMED)

print("\n" + "=" * 72)
print("B  A BLAMED CLASS IS REFUTED  (the bulk-teaching defect, self-correcting)")
print("=" * 72)
# Exactly what teaching did to every isa parent it saw: `learn_facts` synthesises
# "beagle isa dog" as the surface, the fan-out looks for an article to tell a
# kind from a property, an article CANNOT be there, and the parent is proposed
# ADJECTIVE. `dog` carries 163 such proposals on the live store.
lex.propose("dog", "ADJECTIVE", "taught")
print(f"  before: dog={lex.entry('dog').word_class}/{lex.entry('dog').status}")
node = reader._parse_statement("the dog is heavy")
print(f"  'the dog is heavy' -> {None if node is None else node.get('kind')}"
      f" ({None if node is None else node.get('reason')})")
check("an ordinary sentence refused BECAUSE of the class refutes it",
      lex.entry("dog").status, REFUTED)
check("and reading stops relying on it", lex.entry("dog").usable, False)

print("\n" + "=" * 72)
print("C  NO FALSE REFUTATION")
print("=" * 72)
# `sprocket` is consulted and PASSES (it is a noun, so the adjective-subject
# branch does not fire); the sentence is then refused for a reason that has
# nothing to do with it. Refuting everything a failed reading consulted would
# unseat correct classes wholesale and the reader would stop reading forms it
# used to handle.
lex.propose("sprocket", "NOUN", "taught")
before = (lex.entry("sprocket").status, lex.entry("sprocket").confirmations,
          lex.entry("sprocket").contradictions)
node = reader._parse_statement("the sprocket is in")
print(f"  'the sprocket is in' -> {None if node is None else node.get('kind')}"
      f" ({None if node is None else node.get('reason')})")
after = (lex.entry("sprocket").status, lex.entry("sprocket").confirmations,
         lex.entry("sprocket").contradictions)
check("a failure it was not blamed for leaves it exactly as it was", after, before)

print("\n" + "=" * 72)
print("D  ONE SENTENCE, ONE ATTESTATION  (re-entrancy)")
print("=" * 72)
lex.propose("pump", "NOUN", "taught")
lex.propose("hot", "ADJECTIVE", "taught")
lex.propose("valve", "NOUN", "taught")
node = reader._parse_statement("if the pump is hot then the valve is hot")
print(f"  conditional -> {None if node is None else node.get('kind')}")
check("the antecedent's subject is credited once", lex.entry("pump").confirmations, 1)
check("the consequent's subject is credited once", lex.entry("valve").confirmations, 1)

print("\n" + "=" * 72)
print("E  IT IS THE CHOKEPOINT, NOT THE FRONT DOOR")
print("=" * 72)
# `read_all` is the documented public entry and has three call sites. The
# PRIVATE `_parse_statement` has five, in memory_agent, neural_bridge,
# concept_ingestion and the coordinator. Hanging attestation on the public entry
# would leave reading done by memory, reasoning and ingestion earning nothing
# while the loop looked wired -- a return value faking success.
lex.propose("rotor", "NOUN", "taught")
lex.propose("bent", "ADJECTIVE", "taught")
reader.read_all("the rotor is bent")
check("read_all attests too", lex.entry("rotor").status, CONFIRMED)

lex.propose("spindle", "NOUN", "taught")
lex.propose("warm", "ADJECTIVE", "taught")
# The way memory_agent, neural_bridge and concept_ingestion all call it.
SentenceReader()._parse_statement("the spindle is warm")
check("and so does a direct call to the private method",
      lex.entry("spindle").status, CONFIRMED)

print("\n" + "=" * 72)
print(f"{PASS}/{PASS + FAIL}")
print("=" * 72)
print(f"throwaway lexicon: {_tmp}")
print("the real store at data/lexicon.json was not opened for writing.")
sys.exit(0 if not FAIL else 1)
