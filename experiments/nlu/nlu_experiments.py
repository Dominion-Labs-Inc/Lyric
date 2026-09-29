#!/usr/bin/env python3
"""Twelve experiments on what the substrate understands of English.

Every one runs against a LIVE substrate through `coordinator.read()` -- the
formalizer chain the running system uses, hand-written patterns first, then the
derived reading. Nothing here reaches into a module to get a better answer than
the substrate would give.

A MEASUREMENT IS NOT A CHECK. Where there is a right answer (this sentence must
read, this one must be refused, these two must agree) it is a check that passes
or fails. Where there is only a number (what share of real prose reads) it is
reported as a note and never dressed up as a pass.
"""
from __future__ import annotations

import statistics
import time
from typing import Dict, List, Optional, Sequence, Tuple

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _nlu_lib import Experiment, reading_of, real_prose, words_of  # noqa: E402


async def _read(coord, sentence: str) -> Tuple[Optional[Tuple[str, ...]], str]:
    return await reading_of(coord, sentence)


# ============================================================ NLU-01
async def nlu_01(coord) -> Experiment:
    x = Experiment("NLU-01", "What share of REAL prose does the substrate read?", faculty="sentence_reader")
    prose = real_prose(limit=300)
    read, declined, raised = [], [], []
    for sentence in prose:
        atoms, source = await _read(coord, sentence)
        if source.startswith("raised:"):
            raised.append((sentence, source))
        elif atoms:
            read.append((sentence, atoms, source))
        else:
            declined.append(sentence)

    yield_pct = 100.0 * len(read) / len(prose)
    x.measure("sentences", len(prose))
    x.measure("read", len(read))
    x.measure("declined", len(declined))
    x.measure("raised", len(raised))
    x.measure("yield_pct", round(yield_pct, 2))
    x.note(f"corpus: {len(prose)} human-written sentences from the repo's docs "
           f"(median {statistics.median(len(words_of(s)) for s in prose):.0f} words)")
    x.note(f"READ {len(read)} ({yield_pct:.1f}%) · DECLINED {len(declined)} "
           f"({100.0*len(declined)/len(prose):.1f}%) · RAISED {len(raised)}")
    by_source: Dict[str, int] = {}
    for _s, _a, src in read:
        by_source[src] = by_source.get(src, 0) + 1
    x.measure("by_reader", by_source)
    if by_source:
        x.note("which reader answered: " + ", ".join(
            f"{k}={v}" for k, v in sorted(by_source.items(), key=lambda p: -p[1])))
    for sentence, atoms, src in read[:4]:
        x.note(f"read  “{sentence[:72]}” -> {atoms[0] if atoms else None} [{src}]")

    # A reading is a PREMISE the solver cannot doubt, so a crash and a confident
    # misreading are both worse than a refusal. Only the crash is checkable here.
    x.check("no sentence made the reader raise", not raised,
            "; ".join(f"{s[:50]!r} {w}" for s, w in raised[:3]))
    x.check("every reading names at least one atom",
            all(all(a for a in atoms) for _s, atoms, _src in read))
    return x


# ============================================================ NLU-02
CONSTRUCTIONS: List[Tuple[str, bool, List[str]]] = [
    # (class, is it CLAIMED to be supported, sentences)
    ("copular", True, ["A robin is a bird.", "The vault is locked.",
                       "A crucible is a vessel."]),
    ("copular negated", True, ["A robin is not a mammal.",
                               "The engine is not cold.",
                               "The turbine is not silent."]),
    ("subject-verb-object", True, ["The kidney filters plasma.",
                                   "The tank stores water.",
                                   "A crucible melts ore."]),
    ("yes/no question", True, ["Is the vault locked?", "Is a robin a bird?",
                               "Is the reactor stable?"]),
    ("multi-word subject", True, ["The control rod is heavy.",
                                  "The smoke alarm is red.",
                                  "The heat exchanger is hot."]),
    ("relative clause", False, ["The pump that failed was replaced.",
                                "The valve which leaked is closed.",
                                "The engineer who arrived is waiting."]),
    ("NP coordination", False, ["Dogs and cats are mammals.",
                                "Iron and copper are metals.",
                                "Rain and snow are precipitation."]),
    ("object coordination", False, ["The vault holds gold and silver.",
                                    "The reactor vents steam and heat.",
                                    "The tank stores water and oil."]),
    ("VP coordination", False, ["The valve opens and closes.",
                                "The engine starts and stops.",
                                "The pump primes and runs."]),
    ("subordination", False, ["Because the valve stuck the tank overflowed.",
                              "Although the pump ran the tank stayed empty.",
                              "When the alarm sounded the door closed."]),
    ("complement clause", False, ["Scientists believe the universe is expanding.",
                                  "Engineers know the bridge is safe.",
                                  "The report says the valve is faulty."]),
    ("ditransitive", False, ["Alice gave Bob a book.",
                             "The clerk handed the customer a receipt.",
                             "The teacher told the class a story."]),
    ("apposition", False, ["Paris the capital of France is on the Seine.",
                           "Mercury the smallest planet orbits fastest.",
                           "Copper a soft metal conducts heat."]),
    ("comparative", False, ["Iron is heavier than aluminium.",
                            "Gold is denser than silver.",
                            "Steel is stronger than tin."]),
    ("quantified", False, ["Most birds can fly.", "Some metals rust.",
                           "Many rivers flood."]),
    ("passive", False, ["The letter was written by Alice.",
                        "The bridge was built by engineers.",
                        "The valve was closed by the operator."]),
    ("possessive", False, ["France's capital is Paris.",
                           "The engine's housing is cracked.",
                           "Alice's report is late."]),
    ("modal", False, ["A pump can fail.", "The valve may stick.",
                      "The tank might overflow."]),
    # CLAIMED: `_PREPOSITIONAL` reads "X is PREP Y" as a relation, and the
    # relation is the preposition. Listed as unsupported by mistake, so three
    # correct readings were being scored as guesses.
    ("prepositional claim", True, ["The cup is in the box.",
                                    "The vault is under the bank.",
                                    "The sensor is on the pipe."]),
    ("multi-clause definition", False,
     ["A function is a reusable block of code that encapsulates logic.",
      "A pump is a device that moves fluid through a pipe.",
      "A memristor is a component whose resistance depends on charge."]),
]


async def nlu_02(coord) -> Experiment:
    x = Experiment("NLU-02", "Which CONSTRUCTIONS of English does it hold?", faculty="sentence_reader")
    holds: List[str] = []
    gaps: List[str] = []
    for name, claimed, sentences in CONSTRUCTIONS:
        got = []
        for s in sentences:
            atoms, _src = await _read(coord, s)
            got.append(bool(atoms))
        n = sum(got)
        x.measure(name, {"read": n, "of": len(sentences), "claimed": claimed})
        (holds if n else gaps).append(f"{name} {n}/3")
        if claimed:
            x.check(f"CLAIMED: {name} reads", n >= 2, f"read {n}/3")
        else:
            # Not claimed WHOLE. A segmenting reader may still hold part of the
            # sentence, so the requirement is that whatever it produces is
            # ENTAILED -- see NLU-09, which judges the same property per
            # sentence. Here the weaker form: it must not read ALL of them as
            # though the construction were fully supported.
            x.check(f"not claimed whole: {name}", n < len(sentences),
                    f"read {n}/{len(sentences)} — every one, which would mean "
                    f"the construction is represented rather than segmented")
    x.note("reads: " + ", ".join(holds) if holds else "reads: nothing")
    x.note("refuses entirely: " + ", ".join(g for g in gaps))
    return x


# ============================================================ NLU-03
HELD_OUT = [
    ("The kidney filters plasma.", "kidney", "filter", "plasma", True),
    ("The tank stores water.", "tank", "store", "water", True),
    ("A crucible melts ore.", "crucible", "melt", "ore", True),
    ("The turbine is not silent.", "turbine", None, "silent", False),
    ("The control rod is heavy.", "control_rod", None, "heavy", True),
    ("Is the reactor stable?", "reactor", None, "stable", True),
]


async def nlu_03(coord) -> Experiment:
    x = Experiment("NLU-03", "Does it generalise to words it was never taught?", faculty="sentence_reader")
    x.note("every content word below is absent from the reader's evidence, so "
           "nothing here can be answered by having memorised a sentence")
    for sentence, subject, relation, obj, positive in HELD_OUT:
        atoms, src = await _read(coord, sentence)
        if not atoms:
            x.check(f"reads {sentence!r}", False, f"declined [{src}]")
            continue
        atom = atoms[0]
        body = atom[1:] if atom.startswith("~") else atom
        parts = body.split("_")
        ok = (parts[0] == subject.split("_")[0] and obj in body
              and (atom.startswith("~") is not positive)
              and (relation is None or relation in body))
        x.check(f"reads {sentence!r}", ok,
                f"got {atom!r}; expected subject={subject} "
                f"relation={relation} object={obj} positive={positive}")
    return x


# ============================================================ NLU-04
async def nlu_04(coord) -> Experiment:
    x = Experiment("NLU-04", "Does reading survive surface noise?", faculty="sentence_reader")
    base = ["A robin is a bird.", "The kidney filters plasma.",
            "The vault is locked.", "The tank stores water."]
    perturbations = [
        ("uppercase", lambda s: s.upper()),
        ("lowercase", lambda s: s.lower()),
        ("no final stop", lambda s: s.rstrip(".")),
        ("double spaces", lambda s: s.replace(" ", "  ")),
        ("leading/trailing space", lambda s: f"   {s}   "),
        ("doubled final stop", lambda s: s.rstrip(".") + ".."),
    ]
    for sentence in base:
        clean, _src = await _read(coord, sentence)
        if not clean:
            x.note(f"skipped {sentence!r} — not read even clean")
            continue
        for label, fn in perturbations:
            noisy, _s2 = await _read(coord, fn(sentence))
            # A DIFFERENT reading is the failure. Declining under noise is a
            # loss of coverage; reading it as something ELSE puts a premise the
            # sentence never made in front of the solver.
            changed = bool(noisy) and tuple(noisy) != tuple(clean)
            x.check(f"{label}: {sentence[:28]!r} not MISread", not changed,
                    f"clean {clean} -> noisy {noisy}")
    return x


# ============================================================ NLU-05
async def nlu_05(coord) -> Experiment:
    x = Experiment("NLU-05", "Is polarity ever silently wrong?", faculty="sentence_reader")
    cases = [
        ("A robin is a bird.", True),
        ("A robin is not a mammal.", False),
        ("The engine is not cold.", False),
        ("The vault is locked.", True),
        ("The turbine is not silent.", False),
        ("The reactor is stable.", True),
    ]
    for sentence, positive in cases:
        atoms, src = await _read(coord, sentence)
        if not atoms:
            x.note(f"declined {sentence!r} [{src}] — a gap, not a wrong polarity")
            continue
        negated = atoms[0].startswith("~")
        x.check(f"polarity of {sentence!r}", negated is not positive,
                f"got {atoms[0]!r}, expected {'affirmative' if positive else 'negative'}")
    return x


# ============================================================ NLU-06
async def nlu_06(coord) -> Experiment:
    x = Experiment("NLU-06", "Does a question relate the same things as its statement?", faculty="conversation")
    x.note("a question and its statement make the SAME claim and differ only in "
           "what the asker wants done with it, so they must formalise alike")
    pairs = [
        ("The vault is locked.", "Is the vault locked?"),
        ("A robin is a bird.", "Is a robin a bird?"),
        ("The reactor is stable.", "Is the reactor stable?"),
        ("The engine is not cold.", "Is the engine not cold?"),
    ]
    for statement, question in pairs:
        a1, s1 = await _read(coord, statement)
        a2, s2 = await _read(coord, question)
        if not a1 or not a2:
            x.check(f"{question!r} pairs with its statement", False,
                    f"statement={a1} [{s1}] question={a2} [{s2}]")
            continue
        x.check(f"{question!r} pairs with its statement",
                tuple(a1) == tuple(a2), f"{a1} vs {a2}")
    return x


# ============================================================ NLU-07
ROUND_TRIP = [
    "A robin is a bird.",
    "The vault is locked.",
    "The control rod is heavy.",
    "A dog is an animal.",
    "The engine is not cold.",
    "A robin is not a mammal.",
    "The smoke alarm is red.",
    "The reactor is stable.",
]


async def nlu_07(coord) -> Experiment:
    x = Experiment("NLU-07", "Read -> said -> read: does meaning survive a round trip?", faculty="conversation")
    x.note("`_triple_sentence` is the ONE place a held fact becomes words, so this "
           "measures understanding against expression: what the substrate SAYS of "
           "a claim must read back as the same claim")
    from core.agents.autonomous.autonomous_coordinator import Conversation
    from core.semantics.sentence_reader import SentenceReader

    reader = SentenceReader()
    spoken_forms = []
    for sentence in ROUND_TRIP:
        before, src = await _read(coord, sentence)
        if not before:
            # Not a round-trip failure: there is no claim to say back. Recorded
            # so the count of what this experiment COULD test is visible.
            x.note(f"no reading to say back for {sentence!r} [{src}]")
            continue

        nodes = reader.read_all(sentence)
        parts = nodes[0] if nodes else None
        if not parts:
            x.check(f"can say back: {sentence!r}", False,
                    f"the chain read it as {before} but no clause parts exist "
                    f"to render, so it cannot state what it understood")
            continue

        # `read_all` names the object `obj`. Reading `object` here is what made
        # an earlier version of this experiment skip every sentence and report
        # zero checks -- a measurement that measured nothing and said nothing.
        spoken = Conversation._triple_sentence(
            parts["subject"], parts.get("relation") or "is", parts.get("obj") or "",
            positive=bool(parts.get("positive", True)))
        spoken_forms.append((sentence, spoken))
        after, src2 = await _read(coord, spoken)
        x.check(f"round trip: {sentence!r}",
                bool(after) and tuple(after) == tuple(before),
                f"said “{spoken}” -> {after} [{src2}], wanted {before}")

        # SAYING IT MUST ALSO BE ENGLISH. A form that reads back correctly can
        # still be ungrammatical, and the substrate is judged on what a person
        # would hear, not only on what it can re-parse.
        verdict = _article_before_adjective(spoken, parts.get("obj") or "")
        if verdict is None:
            # ABSTAIN, DO NOT FAIL. The store has no class for this complement,
            # so there is no evidence the article is wrong -- and a check that
            # fails on "I do not know" reports a defect it has not found.
            x.note(f"cannot judge the article in “{spoken}” — the store holds no "
                   f"word class for the complement")
        else:
            x.check(f"says it as English: {sentence!r}", not verdict,
                    f"said “{spoken}” — an indefinite article before a complement "
                    f"the store holds as an adjective")

    for said, form in spoken_forms[:4]:
        x.note(f"said back: {said!r} -> “{form}”")
    return x


def _article_before_adjective(spoken: str, complement: str) -> Optional[bool]:
    """`a vault is a locked` -- an article in front of an adjective complement.

    Three answers, not two: True (the store holds this word as an adjective and
    it took an article), False (no such article), and None (the store holds no
    class for it, so there is nothing to conclude). Decided from the STORE, never
    from a word list written here -- that would be the deleted lexicon returning
    through the side door.
    """
    from core.semantics.genericity import _word_classes

    word = ((complement or "").strip().split() or [""])[-1].lower()
    if not word:
        return False
    tail = spoken.lower().split()
    for i, token in enumerate(tail[:-1]):
        if token in ("a", "an") and tail[i + 1].strip(".,") == word:
            seen = set(_word_classes(word))
            if not seen:
                return None
            return "NOUN" not in seen
    return False


# ============================================================ NLU-08
async def nlu_08(coord) -> Experiment:
    x = Experiment("NLU-08", "Does it ANSWER the question, or recite what it holds?",
                   writes=True, faculty="conversation")
    x.note("runs the real conversation path — understand() then say() — which "
           "STORES what it is told; the taught claims below enter the store")
    taught = ["A glarnick is a tool.",
              "A glarnick shapes metal.",
              "A glarnick is heavy."]
    for claim in taught:
        await coord.understand(claim, look_up=False)

    asks = [("What does a glarnick shape?", "metal"),
            ("Is a glarnick heavy?", "heavy"),
            ("What is a glarnick?", "tool")]
    for question, wanted in asks:
        understanding = await coord.understand(question, look_up=False)
        reply = coord.say(understanding)
        x.note(f"asked “{question}” -> “{reply[:140]}”")
        x.check(f"answers {question!r}", wanted in reply.lower(),
                f"looked for {wanted!r} in the reply")
        # A reply that recites everything held about the subject has not
        # answered the question -- it has changed the subject to itself.
        recited = sum(1 for w in ("tool", "metal", "heavy") if w in reply.lower())
        x.check(f"does not recite everything for {question!r}", recited <= 2,
                f"reply names {recited} of the 3 held facts")
    return x


# ============================================================ NLU-09
#: For each structure the reader cannot represent WHOLE: the atoms that are
#: nonetheless ENTAILED by the sentence, and may therefore be produced by
#: segmenting it. Anything outside this set is a claim the sentence does not
#: make.
#:
#: THE REQUIREMENT CHANGED WITH THE READER, AND IT GOT STRICTER. It used to be
#: "produce nothing", which was right while a sentence was judged whole: the
#: only safe answer to a structure you cannot hold is silence. A segmenting
#: reader can hold PART of such a sentence, and refusing the parts it genuinely
#: reads would throw away true claims. So the test is no longer whether it
#: speaks, but whether everything it says is true -- which is the property that
#: mattered all along. Silence still passes; a false claim still fails.
ENTAILED: Dict[str, set] = {
    "The pump that failed was replaced.": {"pump_fail"},
    "The valve which leaked is closed.": {"valve_closed", "valve_leak"},
    "The engineer who arrived is waiting.": {"engineer_waiting", "engineer_arrive"},
    "Dogs and cats are mammals.": {"dog_mammal", "cat_mammal"},
    "The vault holds gold and silver.": {"vault_hold_gold", "vault_hold_silver"},
    "The valve opens and closes.": {"valve_open", "valve_close"},
    "Because the valve stuck the tank overflowed.": {"valve_stick", "tank_overflow"},
    "Scientists believe the universe is expanding.": {"universe_expanding"},
    "Alice gave Bob a book.": set(),
    "Paris the capital of France is on the Seine.": {"paris_on_seine",
                                                    "paris_capital"},
    "Iron is heavier than aluminium.": set(),
    "Most birds can fly.": set(),
    "A function is a reusable block of code that encapsulates logic.":
        {"function_block", "function_reusable_block", "block_encapsulate_logic"},
    "why": set(),
}


async def nlu_09(coord) -> Experiment:
    x = Experiment("NLU-09", "Is everything it says about a hard sentence TRUE?", faculty="conversation")
    x.note("a reading becomes a premise the solver cannot doubt, so the safety "
           "number is not how much it says but whether any of it is false")
    unsound, spoke = [], 0
    for sentence, allowed in ENTAILED.items():
        atoms, src = await _read(coord, sentence)
        produced = [a.lstrip("~") for a in (atoms or ())]
        if produced:
            spoke += 1
        wrong = [a for a in produced if a not in allowed]
        if wrong:
            unsound.append((sentence, wrong, src))
        x.check(f"nothing false from {sentence[:44]!r}", not wrong,
                f"produced {wrong} which the sentence does not state "
                f"(entailed: {sorted(allowed) or 'nothing'}) [{src}]")
    rate = 100.0 * len(unsound) / len(ENTAILED)
    x.measure("sentences", len(ENTAILED))
    x.measure("spoke_at_all", spoke)
    x.measure("unsound", len(unsound))
    x.measure("false_claim_rate_pct", round(rate, 2))
    x.note(f"it produced a reading for {spoke}/{len(ENTAILED)} of them; "
           f"{len(unsound)} carried a claim the sentence does not make "
           f"({rate:.1f}%)")
    return x


# ============================================================ NLU-10
async def nlu_10(coord) -> Experiment:
    x = Experiment("NLU-10", "Where BOTH readers apply, do they agree?", faculty="sentence_reader")
    x.note("the written patterns and the derived reading are separate readers; "
           "a rule learned through one must fire on a fact admitted through the "
           "other, which needs one atom vocabulary rather than two")
    from core.reasoning.neural_bridge import (DerivedReadingFormalizer,
                                              DeterministicExtractor)
    sentences = ["A robin is a bird.", "The vault is locked.",
                 "The kidney filters plasma.", "The tank stores water.",
                 "A robin is not a mammal.", "The control rod is heavy.",
                 "Is the vault locked?", "A crucible melts ore."]
    both = 0
    for sentence in sentences:
        written = await DeterministicExtractor().formalize(sentence, [sentence])
        derived = await DerivedReadingFormalizer().formalize(sentence, [sentence])
        if not (written.succeeded and derived.succeeded):
            x.note(f"only one reader applies to {sentence!r} "
                   f"(written={written.succeeded} derived={derived.succeeded})")
            continue
        both += 1
        x.check(f"agree on {sentence!r}",
                written.statement == derived.statement,
                f"written {written.statement!r} vs derived {derived.statement!r}")
    x.note(f"both readers applied to {both}/{len(sentences)} sentences")
    return x


# ============================================================ NLU-11
async def nlu_11(coord) -> Experiment:
    x = Experiment("NLU-11", "Is reading deterministic and order-independent?", faculty="sentence_reader")
    x.note("the same sentence must read the same way however often it is asked "
           "and whatever was asked before it; a reader whose answer drifts makes "
           "every other measurement here unrepeatable")
    sentences = ["A robin is a bird.", "The kidney filters plasma.",
                 "The vault is locked.", "A robin is not a mammal.",
                 "Is the reactor stable?"]
    first: Dict[str, Optional[Tuple[str, ...]]] = {}
    for sentence in sentences:
        atoms, _src = await _read(coord, sentence)
        first[sentence] = tuple(atoms) if atoms else None
    # Repeat, and in reverse, so an order effect shows up as a difference.
    for _round in range(2):
        for sentence in reversed(sentences):
            atoms, _src = await _read(coord, sentence)
            now = tuple(atoms) if atoms else None
            x.check(f"stable: {sentence[:34]!r}", now == first[sentence],
                    f"{first[sentence]} then {now}")
    return x


# ============================================================ NLU-12
async def nlu_12(coord) -> Experiment:
    x = Experiment("NLU-12", "Where in sentence LENGTH does understanding fail?", faculty="sentence_reader")
    prose = real_prose(limit=300)
    buckets: Dict[str, List[bool]] = {}
    for sentence in prose:
        n = len(words_of(sentence))
        key = ("04-08" if n <= 8 else "09-12" if n <= 12 else
               "13-18" if n <= 18 else "19-25" if n <= 25 else "26-40")
        atoms, _src = await _read(coord, sentence)
        buckets.setdefault(key, []).append(bool(atoms))
    for key in sorted(buckets):
        got = buckets[key]
        x.measure(key, {"read": sum(got), "of": len(got),
                        "pct": round(100.0 * sum(got) / len(got), 1)})
        x.note(f"{key} words: {sum(got)}/{len(got)} read "
               f"({100.0*sum(got)/len(got):.0f}%)")
    shortest = buckets.get("04-08", [])
    longest = buckets.get("26-40", [])
    # Not a threshold anyone tuned: if the SHORT bucket does not beat the long
    # one, length is not what limits the reader and the whole framing is wrong.
    if shortest and longest:
        x.check("short sentences read more often than long ones",
                (sum(shortest)/len(shortest)) >= (sum(longest)/len(longest)),
                f"short {sum(shortest)}/{len(shortest)} vs "
                f"long {sum(longest)}/{len(longest)}")
    x.check("every bucket was populated", len(buckets) >= 3,
            f"buckets: {sorted(buckets)}")
    return x


# ── NLU-13 ────────────────────────────────────────────────────────────────────
#: The jobs a representation actually does in this substrate, and what each one
#: needs. These are not general "embedding quality" tests: each family is a
#: decision the substrate already makes with a vector, and gets wrong when the
#: vector is wrong.
#:
#: (left, right, want, family, why)
#:   HIGH   -> these must come back close
#:   LOW    -> these must come back apart
#:   ABSTAIN-> the encoder holds nothing for this and must SAY so
ENCODER_CASES = [
    # KEPT APART. Two different claims read as one would make recall return one
    # for the other. (This family was "merge safety" while the memory agent
    # merged memories by likeness; it merges nothing now.)
    ("A kidney is an organ.", "A liver is an organ.", "LOW", "kept apart",
     "two different things of the same kind are two claims, not one"),
    ("The vault is locked.", "The vault is not locked.", "LOW", "polarity",
     "a claim and its denial must never read as one; measured at 0.948 by cosine"),
    ("A robin is a bird.", "A robin is not a bird.", "LOW", "polarity",
     "same, on a taught kind"),
    ("Iron is a metal.", "Copper is a metal.", "LOW", "kept apart",
     "different subjects, same predicate"),

    # RECALL. A question must reach the fact that answers it, or taught
    # knowledge is unreachable by meaning.
    ("what is a kidney", "A kidney is an organ.", "HIGH", "recall",
     "the question and its answer are about one thing"),
    ("what does a pump do", "A pump is a device that moves fluid.", "HIGH",
     "recall", "a question reaching a definition"),
    ("tell me about metals", "Iron is a metal.", "HIGH", "recall",
     "a loose question reaching an instance"),

    # PARAPHRASE. Two ways of saying one thing must be close, or dedup keeps
    # both and the store grows a duplicate for every rewording.
    ("A dog is an animal.", "A dog is a kind of animal.", "HIGH", "paraphrase",
     "the same claim, worded twice"),
    ("The engine is hot.", "The engine is not cold.", "HIGH", "paraphrase",
     "a claim and its double negative"),

    # SUBJECT SEPARATION. Unrelated subject matter must be far apart, or
    # retrieval returns anything for anything.
    ("A kidney is an organ.", "A hammer is a tool.", "LOW", "separation",
     "unrelated subjects"),
    ("The vault is locked.", "A robin is a bird.", "LOW", "separation",
     "nothing in common but grammar"),

    # ABSTENTION. Words the substrate was never taught. A taught-only encoder
    # MUST report that it cannot judge -- the earlier version returned cosine
    # 1.000 here, confident identity between two things it knew nothing about.
    ("A marnic filters brine.", "A zorbic filters brine.", "ABSTAIN",
     "abstention", "two unknown subjects: not the same, and not judgeable"),
    ("A threlp is a dovick.", "A marnic is a zorbic.", "ABSTAIN", "abstention",
     "nothing in either sentence was ever taught"),
    ("A glarnick shapes metal.", "A glarnick bends metal.", "ABSTAIN",
     "abstention", "an unknown subject, however familiar the rest"),
]

#: Cosine at or above which two readings count as one. It was the memory
#: agent's merge bar; the memory agent merges nothing now, and the bar stays
#: the line these cases are measured against.
_MERGE_BAR = 0.75


async def nlu_13(coord) -> Experiment:
    x = Experiment("NLU-13", "Can the substrate's OWN knowledge replace the model?", faculty="memory_encoder")
    x.note("all-MiniLM-L6-v2 is the last model in the system. It does memory "
           "retrieval, concept vectors and analogy. This asks "
           "whether what the substrate was TAUGHT can do those jobs instead.")

    from experiments.nlu.substrate_encoder import SubstrateEncoder, taught_readings
    from core.memory.utils.embedding_service import get_embedding_service
    import math as _math

    readings = await taught_readings()
    encoder = SubstrateEncoder()
    encoder.learn(readings)
    encoder.finalise()
    x.note(f"learned from {len(readings):,} taught proposition(s); "
           f"{len(encoder.vocab):,} term(s) of vocabulary")
    x.measure("corpus", {"propositions": len(readings),
                         "vocabulary": len(encoder.vocab)})

    mini = get_embedding_service()
    mini.initialize()

    def mini_cos(left: str, right: str) -> float:
        u, v = mini.generate_embedding(left), mini.generate_embedding(right)
        dot = sum(a * b for a, b in zip(u, v))
        nu = _math.sqrt(sum(a * a for a in u))
        nv = _math.sqrt(sum(b * b for b in v))
        return dot / (nu * nv) if nu and nv else 0.0

    def verdict(score, want: str) -> bool:
        """Did this encoder do the job the substrate needs here?"""
        if want == "ABSTAIN":
            return score is None
        if score is None:
            return False          # it had something to judge and did not
        return score < _MERGE_BAR if want == "LOW" else score >= _MERGE_BAR

    rows = []
    mini_right = native_right = 0
    for left, right, want, family, why in ENCODER_CASES:
        m = mini_cos(left, right)
        n = encoder.similarity(left, right)
        m_ok, n_ok = verdict(m, want), verdict(n, want)
        mini_right += bool(m_ok)
        native_right += bool(n_ok)
        rows.append({"family": family, "want": want, "left": left,
                     "right": right, "minilm": round(m, 3),
                     "native": (None if n is None else round(n, 3)),
                     "minilm_ok": m_ok, "native_ok": n_ok})
        # THE CHECK IS ON THE SUBSTRATE'S OWN ENCODER. MiniLM is the control and
        # is recorded, never asserted -- an experiment that failed when the
        # model did would be measuring the model, not the substrate.
        x.check(f"{family}: {want} — {left[:34]!r} vs {right[:34]!r}", n_ok,
                f"native={'abstained' if n is None else round(n, 3)} "
                f"(minilm={round(m, 3)}, {'ok' if m_ok else 'wrong'})")

    x.measure("cases", rows)
    x.measure("score", {"minilm": mini_right, "native": native_right,
                        "of": len(ENCODER_CASES)})
    x.note(f"MiniLM {mini_right}/{len(ENCODER_CASES)} · "
           f"SUBSTRATE {native_right}/{len(ENCODER_CASES)} "
           f"(bar: {_MERGE_BAR}, the line two readings count as one)")

    # THE ONE THING A TAUGHT-ONLY ENCODER MUST NEVER DO.
    confident_on_nothing = [r for r in rows
                            if r["want"] == "ABSTAIN" and r["native"] is not None]
    x.check("never claims to judge what it was never taught",
            not confident_on_nothing,
            f"{len(confident_on_nothing)} case(s) scored instead of abstaining")

    # POLARITY IS THE KNOWN KILLER: a claim and its denial differ by one token.
    polarity = [r for r in rows if r["family"] == "polarity"]
    x.check("a claim and its denial never reach the merge bar",
            all(r["native"] is None or r["native"] < _MERGE_BAR for r in polarity),
            "; ".join(f"{r['left'][:24]!r} {r['native']}" for r in polarity))
    x.measure("polarity", {"minilm": [r["minilm"] for r in polarity],
                           "native": [r["native"] for r in polarity]})
    return x

ALL = [nlu_01, nlu_02, nlu_03, nlu_04, nlu_05, nlu_06,
       nlu_07, nlu_08, nlu_09, nlu_10, nlu_11, nlu_12, nlu_13]
