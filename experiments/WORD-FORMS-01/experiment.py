#!/usr/bin/env python3
"""WORD-FORMS-01 — English word forms taught (`WordNetExamplesSource`, its nouns): does Lyric read a plural as the noun it is, in every
sense it was said for, from its own memory?

UNDERSTANDS-WORDNET-01's first run asked "Are coiners sources?" and was told "No. No coiners is a source.": the
reader took "coiners" as a new name, and the answer turned it into `coiner` by asking WordNet at runtime, which found
only the forger. On main the plural ending `s` read 517 of the 6,914 words it applies to rightly and was not
productive: WordNet's words ending as plurals do ("glass", "lens", "species") outnumbered the plurals the lessons
showed, and WordNet's pass said plurals only of the nouns no change makes ("Mice are rodents."). `WordNetExamplesSource`
says the plural of every counted noun sense in a fact WordNet holds of it ("Hawks are raptors.", "Hawks are
militarists."). Measured on a copy of main after it is taught, read only:

  A  TAUGHT     every plural said is held for the sense it was said for ("hawks" names the bird and the militarist);
  B  OWN        Lyric's own singular of a word (`held_singular`: a plural it holds as a word, else a held noun the word
                is written in a productive shape of, else the word where it holds it) agrees with WordNet's on the
                plurals taught and the nouns held: bar 99%, set before the run, for `singularise` to stop asking
                WordNet;
  C  SHAPES     plurals never taught, of nouns held, read through a productive shape: measured;
  D  QUESTIONS  "Are hawks raptors?", "Are coiners sources?" and others read as written: checked.

Run (on a copy of main the word forms were taught to):
    POSTGRES_DATABASE=lyric_check2 ./venv_lyric/bin/python3 experiments/WORD-FORMS-01/experiment.py
"""
import asyncio
import logging
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_check2")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(k, v)
if os.environ["POSTGRES_DATABASE"] == "lyric_db":
    sys.exit("WORD-FORMS-01 reads a copy of main, never lyric_db itself")
LOG = HERE / "results" / "run.log"
LOG.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    handlers=[logging.FileHandler(LOG, mode="w")])

from experiments._evidence import RunRecord  # noqa: E402

#: Set before the first run (2026-10-11).
BAR_OWN_SINGULAR = 0.99
SEED = 20261011
#: Plural questions, each fact in words: the plural must be taken to name a sense of the noun.
QUESTIONS = [
    ("Are hawks raptors?", [("isa", "hawk", "raptor")]),
    ("Are coiners sources?", [("isa", "coiner", "source")]),
    ("Are herons birds?", [("isa", "heron", "bird")]),
    ("Are petals parts?", [("isa", "petal", "part")]),
    ("Are beroes ctenophores?", [("isa", "beroe", "ctenophore")]),
    ("Are lockstitches stitches?", [("isa", "lockstitch", "stitch")]),
    ("Are headsmen executioners?", [("isa", "headsman", "executioner")]),
    ("Are titmice birds?", [("isa", "titmouse", "bird")]),
]

EV = RunRecord("WORD-FORMS-01",
               claim=("Taught the plural of every counted noun sense, Lyric holds each plural for the senses it was said "
                      "for, and its own singular of a word agrees with WordNet's often enough for WordNet to leave the "
                      "runtime."),
               hypothesis=("A plural taught not held for its sense, Lyric's own singular agreeing with WordNet's on fewer "
                           "than 99% of the words, or a plural question read otherwise than written, shows here."))


def say(line=""):
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def held_singular(view, agent, word):
    """Lyric's own singular of a word, from what it holds: the singular word of a thing it holds the word as a plural
    of; else a held noun the word is written in a productive shape of; else the word itself where it holds it as a
    noun; None where it holds nothing of it."""
    from core.semantics.derived_reader import _fold, _loose
    word = _fold(word)
    singulars = []
    for lexical in view.lexicals_with_words((word,), loose=True):
        for other in view.lexicals_with_value(lexical.value):
            written = " ".join(_loose(other.words))
            if written != word and " " not in written and view.shape_between(word, written) is not None \
                    or (written != word and " " not in written and written[:2] == word[:2]
                        and not view.shape_between(written, word)):
                if written not in singulars:
                    singulars.append(written)
    noun = lambda w: (agent.word_classes(w) or {}).get("NOUN", 0) > 0
    for base in singulars:
        if noun(base):
            return base
    for base in view.names_of_shape(word):
        if base != word and noun(base):
            return base
    return word if noun(word) or view.lexicals_with_value(word) else None


async def main() -> int:
    started = time.time()
    from core.agents.memory_agent import get_memory_agent
    from core.learning.teaching_sources import WordNetExamplesSource
    from core.semantics import lexical_normalization as ln
    from core.semantics import derived_reader as dr
    agent = await get_memory_agent()
    await agent.initialize()
    words = await agent.warm_word_classes()
    view = dr.live_view()
    check("the run reads a copy of main, not main", await EV.verify_database() not in (None, "lyric_db"),
          f"connected to {EV.verified_database}")
    say(f"  the language view holds {words:,} words")

    say("\n== A. The plurals taught ==")
    records = list(WordNetExamplesSource(parts=("n",)).records())
    missing = []
    for record in records:
        concept, plural = record.forms[0]
        values = {str(lexical.value) for lexical in view.lexicals_with_words((dr._fold(plural),), loose=True)}
        if concept not in values:
            missing.append((plural, concept, sorted(values)[:4]))
    for plural, concept, values in missing[:15]:
        say(f"    {plural!r} not held for {concept!r}; held for {values}")
    EV.metric("plurals said, not held for their sense", [{"plural": p, "sense": c, "held for": v} for p, c, v in missing[:200]])
    check("every plural said is held for the sense it was said for", not missing,
          f"{len(records) - len(missing):,} of {len(records):,}")

    say("\n== B. Lyric's own singular against WordNet's ==")
    plurals = {dr._fold(r.plural[0][1]) for r in records}
    nouns = {w for w in agent._word_class_index if w.isalpha() and (agent._word_class_index[w].get("NOUN", 0) > 0)}
    asked = sorted(plurals | nouns)
    agree, differ = 0, []
    for word in asked:
        own = held_singular(view, agent, word)
        theirs = ln._wordnet_singular(word)
        if own == theirs or (own is None and theirs in (None, word)):
            agree += 1
        else:
            differ.append((word, own, theirs))
    random.Random(SEED).shuffle(differ)
    for word, own, theirs in differ[:20]:
        say(f"    {word!r}: Lyric {own!r}, WordNet {theirs!r}")
    share = agree / len(asked)
    EV.metric("Lyric's own singular agrees with WordNet's", f"{agree:,}/{len(asked):,} ({share:.2%})")
    EV.metric("where they differ (sample)", [{"word": w, "lyric": o, "wordnet": t} for w, o, t in differ[:200]])
    check(f"Lyric's own singular agrees with WordNet's on at least {BAR_OWN_SINGULAR:.0%} of the words",
          share >= BAR_OWN_SINGULAR, f"{share:.2%} of {len(asked):,}")

    say("\n== C. Plurals never taught, through a shape ==")
    shapes = view.word_shapes()
    for change in (("s", ""), ("es", ""), ("ies", "y"), ("ks", "k"), ("rs", "r"), ("ns", "n"), ("ts", "t")):
        right, covered = shapes.get(change, (0, 0))
        EV.metric(f"shape {change}", {"right": right, "covered": covered, "productive": view.productive(change)})
        say(f"    {change}: {right:,}/{covered:,} productive={view.productive(change)}")

    say("\n== D. Plural questions ==")
    wrong = []
    for sentence, facts in QUESTIONS:
        utterances = dr.read_text(sentence)
        chosen = await dr.heard(utterances[0].readings) if utterances and utterances[0].understood else None
        ok = chosen is not None and len(chosen.meaning.facts) == len(facts) and all(
            f.relation == r and any(" ".join(dr._loose(l.words)) == s for l in view.lexicals_with_value(f.subject))
            and any(" ".join(dr._loose(l.words)) == o for l in view.lexicals_with_value(f.obj))
            for f, (r, s, o) in zip(chosen.meaning.facts, facts))
        if not ok:
            wrong.append(sentence)
            say(f"    {sentence!r} read {chosen.meaning.canonical() if chosen else 'unread or two ways'}")
    check("plural questions read as written", not wrong, f"{len(QUESTIONS) - len(wrong)} of {len(QUESTIONS)}")

    await agent.stop_memory_loops()
    passed = sum(1 for c in EV.checks if c.passed)
    say(f"\n==== WORD-FORMS-01: {passed}/{len(EV.checks)} checks passed ({time.time() - started:.0f} s) ====")
    say(f"  run record: {EV.write()}")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
