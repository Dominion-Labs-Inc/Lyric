#!/usr/bin/env python3
"""POS-01 — a word class is taken from what is known, never guessed from a surface.

Teaching fed the lexicon through `observe_proposition`, which decided a copular
complement's class by looking for an article:

    _record(obj, NOUN if _has_article(sentence, obj) else ADJECTIVE)

Correct for a sentence a person said -- "the beagle is a dog" gives NOUN, "the
tank is hot" gives ADJECTIVE. Systematically wrong for bulk teaching, where the
article CANNOT be present: `learn_fact` synthesises the surface `"beagle isa
dog"`, and `learn_facts` does not even pass the triple -- it passes
`"4000 taught facts"`. So "no article" was absence of evidence read as evidence
of a property, and every one of 314,856 bulk-taught `isa` edges proposed its
parent as an ADJECTIVE.

The damage is on the live store: `dog` carries 163 contradictions, every one
"conflicting proposal ADJECTIVE from taught"; `run` 65, `water` 61,
`alcohol` 42. And it is why `fan_out=False` exists in two teaching scripts --
a workaround for a broken arm of the one path, not laziness.

THE FIX IS NOT A BETTER GUESS. A TYPED relation already says what its object is:
`isa` MEANS "is a kind of", so the object names a kind, and a kind is a noun.
Only a BARE copula is genuinely ambiguous, and only a bare copula arises from a
sentence someone actually said -- where the determiner is really there to read.
Where the surface does not even mention the object, nothing is recorded: an
honest gap rather than a guess.

  A  A TYPED RELATION DECIDES    `X isa Y` proposes Y as a NOUN, from the
     ITSELF                      relation's meaning, with no surface consulted.
  B  A REAL SENTENCE STILL       "the tank is hot" -> hot ADJECTIVE;
     DISCRIMINATES               "a kettle is a container" -> container NOUN.
  C  NO EVIDENCE, NO CLAIM       a bare copula whose object the surface never
                                 mentions records NOTHING.
  D  THE BULK PATH IS CLEAN      teaching a taxonomy through `learn_facts`
                                 proposes no ADJECTIVE at all.

Run: PYTHONPATH="$PWD" ./venv_torin/bin/python3 experiments/POS-01/experiment.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import core.semantics.lexicon as lexmod
from core.semantics.lexicon import ADJECTIVE, Lexicon, NOUN, observe_proposition

# Attestation and proposal both WRITE, so the real 25 MB store is never opened.
_tmp = Path(tempfile.mkdtemp()) / "lexicon.json"
lexmod._lexicon = Lexicon(path=_tmp)
lex = lexmod._lexicon

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
print("A  A TYPED RELATION DECIDES ITSELF")
print("=" * 72)
# Exactly what `learn_fact` synthesises, and what `learn_facts` passes.
observe_proposition("beagle isa dog", "beagle", "isa", "dog", save=False)
observe_proposition("4000 taught facts", "kettle", "isa", "container", save=False)
print(f"  surface 'beagle isa dog'       -> dog       = {lex.class_of('dog')}")
print(f"  surface '4000 taught facts'    -> container = {lex.class_of('container')}")
check("an isa parent is a NOUN, not an ADJECTIVE", lex.class_of("dog"), NOUN)
check("even when the surface never mentions it",
      lex.class_of("container"), NOUN)
check("and the subject is still a NOUN", lex.class_of("beagle"), NOUN)

print("\n" + "=" * 72)
print("B  A REAL SENTENCE STILL DISCRIMINATES")
print("=" * 72)
observe_proposition("the tank is hot", "tank", "is", "hot", save=False)
observe_proposition("a kettle is a vessel", "kettle", "is", "vessel", save=False)
print(f"  'the tank is hot'              -> hot    = {lex.class_of('hot')}")
print(f"  'a kettle is a vessel'         -> vessel = {lex.class_of('vessel')}")
check("a bare complement with no article is a PROPERTY",
      lex.class_of("hot"), ADJECTIVE)
check("a bare complement behind an article is a KIND",
      lex.class_of("vessel"), NOUN)

print("\n" + "=" * 72)
print("C  NO EVIDENCE, NO CLAIM")
print("=" * 72)
# A bare copula taught in bulk: the surface cannot carry a determiner, so there
# is nothing to read. The old code called this ADJECTIVE.
observe_proposition("12 taught facts", "widget", "is", "sturdy", save=False)
print(f"  '12 taught facts' / widget is sturdy -> sturdy = "
      f"{lex.class_of('sturdy')}")
check("nothing is recorded where the surface says nothing",
      lex.class_of("sturdy"), None)

print("\n" + "=" * 72)
print("D  THE BULK PATH IS CLEAN")
print("=" * 72)
TAXONOMY = [("robin", "bird"), ("sparrow", "bird"), ("bird", "animal"),
            ("oak", "tree"), ("tree", "plant"), ("salmon", "fish"),
            ("trout", "fish"), ("fish", "animal")]
for child, parent in TAXONOMY:
    observe_proposition(f"{len(TAXONOMY)} taught facts", child, "isa", parent,
                        save=False)
classes = {w: lex.class_of(w) for _, w in TAXONOMY}
print(f"  parents after a taxonomy teach: {classes}")
adjectives = [w for w, c in lex._entries.items() if c.word_class == ADJECTIVE]
print(f"  ADJECTIVE entries in the whole store: {sorted(adjectives)}")
check("no taxonomy parent became an ADJECTIVE",
      all(c == NOUN for c in classes.values()), True)
check("the only ADJECTIVE is the one a real sentence attested",
      sorted(adjectives), ["hot"])

print("\n" + "=" * 72)
print(f"{PASS}/{PASS + FAIL}")
print("=" * 72)
print(f"throwaway lexicon: {_tmp}")
sys.exit(0 if not FAIL else 1)
