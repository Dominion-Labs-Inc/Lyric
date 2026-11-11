#!/usr/bin/env python3
"""UNDERSTANDS-WORDNET-01 — does the substrate UNDERSTAND what WordNet taught it, shown in what it answers?

Probes past P1 ask in the one form P1 shows the substrate reads ("Is a X a Y?"): asked "a kind of", every inference
came back unread (the first full run, 2026-10-11), which measures the form again, not inference.

KNOWS-WORDNET-01 asks whether a fact is HELD. This asks whether it is UNDERSTOOD: asked in English the way a person
asks, in forms the teaching never used, does it answer right, reason past what it was told, tell a word's senses apart,
refuse what is not so, and say it does not know what it was never taught?

Every question goes through the one conversation path (`Conversation.understand`), each in a conversation of its own,
with nothing looked up (`look_up=False`): only what the substrate holds can answer. An answer is read off the turn's
own verdicts (`Answer.verdict`: True holds, False the denial is held, None not known), never off the reply's wording.

THE TRUTH IS WORDNET ITSELF (nltk), not the store: "yes" is right when some sense of the word has the class among its
ancestors; a pair is a NEGATIVE only when no sense of either word reaches the other. Each probe has its control:

  P1 TAUGHT      a direct "is a", asked four ways the teaching never said it      should be YES
  P2 INFERRED    an ancestor two or three steps up, never taught as one fact       should be YES (reasoning)
  P3 UNRELATED   real words WordNet does not relate                                must NOT be yes
  P4 NONCE       a word that is no word                                            must NOT be yes; should be unknown
  P5 SENSES      one word, two of its senses, asked about each                     both should be YES
  P6 PARTS       "Is a X part of a Y?" from WordNet's parts, and unrelated pairs   YES / not yes
  P7 OPPOSITES   "Is X the opposite of Y?" from WordNet's antonyms, and unrelated  YES / not yes
  P8 WHAT IS     "What is a X?": the class it names must be an ancestor of X      right / wrong / none

ASKED WITHOUT BEING REMEMBERED, SO IT RUNS ON MAIN. Each conversation is held with `remembers=False`: it reads,
recalls and answers as any other, and stores no turn and takes in nothing it is told. No substrate is started (its
own loops write), only memory, the beliefs and the language view are loaded. The store's write counters
(`pg_stat_user_tables`) are read before and after; any table written to while the questions were asked is reported,
and the run fails its first check.

    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/UNDERSTANDS-WORDNET-01/experiment.py [N]
"""
import asyncio
import contextlib
import io
import json
import logging
import math
import os
import random
import re
import sys
import time
from typing import Any, Dict, List
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
LOG = HERE / "results" / "run.log"
LOG.parent.mkdir(exist_ok=True)
# Its own log, set before anything imports core.main (whose basicConfig then adds nothing).
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler(LOG, mode="w")])

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
SEED = 20261010

#: Fixed before the run: what a reader that understood would reach.
BARS = {
    "P1 taught, asked new ways: yes": 0.90,
    "P2 inferred: yes": 0.80,
    "P3 unrelated: yes (must be low)": 0.02,
    "P4 nonce: yes (must be zero)": 0.0,
    "P5 both senses: yes": 0.80,
    "P6 parts: yes": 0.80,
    "P6 parts, unrelated: yes (must be low)": 0.05,
    "P7 opposites: yes": 0.80,
    "P7 opposites, unrelated: yes (must be low)": 0.05,
    "P8 what is: right": 0.80,
    "P8 what is: wrong (must be low)": 0.05,
}


def say(*a):
    print(*a, flush=True)


def wilson(k: int, n: int):
    if not n:
        return (0.0, 0.0)
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def article(word: str) -> str:
    return "an" if word[0] in "aeiou" else "a"


def plural(word: str):
    """A plural only where English is regular and certain; None where it is not."""
    if re.search(r"(s|x|z|ch|sh|y|f|fe|o|man|um|us|is|on|a)$", word):
        return None
    return word + "s"


# ── the truth: WordNet itself ───────────────────────────────────────────────

def ground_truth(rng):
    from nltk.corpus import wordnet as wn

    def single(lemma) -> bool:
        name = lemma.name()
        return name.isalpha() and name.islower() and 3 <= len(name) <= 14

    def words_of(synset):
        return [l.name() for l in synset.lemmas() if single(l)]

    def ancestors(word):
        """Every word naming an ancestor of any noun sense of `word`, with its fewest steps up."""
        seen = {}
        for s in wn.synsets(word, pos=wn.NOUN):
            frontier, depth = [s], 0
            visited = {s}
            while frontier:
                depth += 1
                nxt = []
                for f in frontier:
                    for h in f.hypernyms() + f.instance_hypernyms():
                        if h in visited:
                            continue
                        visited.add(h)
                        nxt.append(h)
                        for w in words_of(h):
                            seen[w] = min(seen.get(w, depth), depth)
                frontier = nxt
        return seen

    def ancestor_names(word):
        """Every name of every ancestor of any noun sense of `word`, words of several included ("reproductive
        structure"): what "What is a X?" may rightly answer. The first run graded against single words only and
        marked "A testa is a kind of reproductive structure." wrong."""
        names = set()
        for s in wn.synsets(word, pos=wn.NOUN):
            for h in s.closure(lambda x: x.hypernyms() + x.instance_hypernyms()):
                names.update(l.name().replace("_", " ").lower() for l in h.lemmas())
        return names

    def related(a, b):
        """Whether WordNet relates two words at all, either way, in any sense, or makes them one."""
        if a == b:
            return True
        if b in ancestors(a) or a in ancestors(b):
            return True
        for s in wn.synsets(a):
            if b in [l.name() for l in s.lemmas()]:
                return True
        return False

    # THINGS, asked about as things: nouns under `object` (artifacts, organisms, people, body parts, natural
    # objects) take "a" in English. An abstract or mass noun asked as "Is a sternness a severeness?" is no question a
    # person asks; it is out of this experiment's scope, not asked badly.
    thing = wn.synset("object.n.01")

    def concrete(synset) -> bool:
        return any(thing in path for path in synset.hypernym_paths())

    nouns = [s for s in wn.all_synsets(wn.NOUN) if words_of(s) and concrete(s)]
    rng.shuffle(nouns)
    vocab = sorted({w for s in nouns[:20000] for w in words_of(s)})

    # EVERY PROBE ITS OWN SUBJECTS. The substrate remembers each turn, and recall answers from what it remembers
    # ("I remember: A senior is a kind of undergraduate."), so a word asked about in one probe would carry an answer
    # into another. No word is the subject of two probes.
    used = set()
    taught, inferred, what_is = [], [], []
    for s in nouns:
        if len(taught) >= N * 4 and len(inferred) >= N and len(what_is) >= N:
            break
        w = words_of(s)[0]
        if w in used:
            continue
        anc = ancestors(w)
        direct = [x for x, d in anc.items() if d == 1 and x != w]
        far = [x for x, d in anc.items() if d in (2, 3) and x != w]
        if direct and len(taught) < N * 4:
            taught.append((w, rng.choice(direct)))
        elif far and len(inferred) < N:
            inferred.append((w, rng.choice(far)))
        elif anc and len(what_is) < N:
            what_is.append((w, ancestor_names(w)))
        else:
            continue
        used.add(w)

    unrelated, guard = [], 0
    while len(unrelated) < N * 2 and guard < 100000:
        guard += 1
        a, b = rng.choice(vocab), rng.choice(vocab)
        if a not in used and not related(a, b):
            unrelated.append((a, b))
            used.add(a)

    letters_c, letters_v = "bdfgklmnprstvz", "aeiou"
    nonce = []
    while len(nonce) < max(10, N // 2):
        w = "".join(rng.choice(letters_c) + rng.choice(letters_v) for _ in range(3)) + rng.choice(letters_c)
        if not wn.synsets(w):
            nonce.append((w, rng.choice(taught)[1]))

    senses, sensed = [], set()
    for s in nouns:
        if len(senses) >= N // 2:
            break
        w = words_of(s)[0]
        if w in sensed or w in used:
            continue
        heads = []
        for t in wn.synsets(w, pos=wn.NOUN):
            hyp = [x for h in t.hypernyms() for x in words_of(h) if x != w]
            if hyp and all(not related(hyp[0], other) for other in heads):
                heads.append(hyp[0])
        if len(heads) >= 2:
            sensed.add(w)
            used.add(w)
            senses.append((w, heads[0], heads[1]))

    parts = []
    for s in nouns:
        if len(parts) >= N:
            break
        for p in s.part_meronyms():
            if words_of(p) and words_of(s) and concrete(p):
                parts.append((words_of(p)[0], words_of(s)[0]))
                break
    part_controls = []
    while len(part_controls) < N:
        a, b = rng.choice(parts)[0], rng.choice(parts)[1]
        if not related(a, b) and (a, b) not in parts:
            part_controls.append((a, b))

    adjectives = [s for s in wn.all_synsets(wn.ADJ)]
    rng.shuffle(adjectives)
    opposites = []
    for s in adjectives:
        if len(opposites) >= N:
            break
        for l in s.lemmas():
            # Opposites in use: both words met in SemCor, so "Is hot the opposite of cold?", not a coinage.
            if (single(l) and l.antonyms() and single(l.antonyms()[0])
                    and l.count() > 0 and l.antonyms()[0].count() > 0):
                pair = (l.name(), l.antonyms()[0].name())
                if pair not in opposites and pair[::-1] not in opposites:
                    opposites.append(pair)
                break
    adj_words = [a for pair in opposites for a in pair]
    antonym_pairs = {frozenset(p) for p in opposites}
    opposite_controls = []
    while len(opposite_controls) < N:
        a, b = rng.choice(adj_words), rng.choice(adj_words)
        lemmas_a = {x.name() for s in wn.synsets(a) for l in s.lemmas() for x in l.antonyms()}
        if a != b and frozenset((a, b)) not in antonym_pairs and b not in lemmas_a:
            opposite_controls.append((a, b))

    # COMMON OR RARE, reported apart: a word met in SemCor at least once, or never.
    common = {w for w, _ in taught + inferred if sum(l.count() for s in wn.synsets(w, pos=wn.NOUN)
                                                     for l in s.lemmas() if l.name() == w) > 0}
    return {"taught": taught[:N * 4], "inferred": inferred[:N], "unrelated": unrelated[:N * 2],
            "nonce": nonce, "senses": senses, "parts": parts[:N], "part_controls": part_controls[:N],
            "opposites": opposites[:N], "opposite_controls": opposite_controls[:N], "what_is": what_is,
            "common": common}


# ── asking ──────────────────────────────────────────────────────────────────

def taught_forms(subject: str, cls: str):
    """Four ways to ask a taught "is a", none of them the sentence the teaching said ("A frog is an amphibian.")."""
    forms = [("is a", f"Is {article(subject)} {subject} {article(cls)} {cls}?"),
             ("a kind of", f"Is {article(subject)} {subject} a kind of {cls}?"),
             ("embedded", f"Is it true that {article(subject)} {subject} is {article(cls)} {cls}?")]
    ps, pc = plural(subject), plural(cls)
    if ps and pc:
        forms.append(("plural", f"Are {ps} {pc}?"))
    return forms


async def main() -> int:
    from experiments._evidence import RunRecord
    EV = RunRecord("UNDERSTANDS-WORDNET-01",
                   claim="the substrate understands what WordNet taught it: it answers taught facts asked in new "
                         "forms, reasons past them, tells senses apart, refuses what is not so, and says it does "
                         "not know what it was never taught",
                   hypothesis="each probe reaches its bar, fixed before the run (BARS)")
    rng = random.Random(SEED)
    say(f"building the questions from WordNet (seed {SEED}, N={N})…")
    truth = await asyncio.to_thread(ground_truth, rng)
    say("  " + ", ".join(f"{k} {len(v)}" for k, v in truth.items()))

    quiet = io.StringIO()
    say("loading memory, the beliefs and the language view (no substrate is started)…")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.autonomous.autonomous_coordinator import get_conversation
        from core.agents.memory_agent import get_memory_agent
        from core.database import get_unified_db
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        agent = await get_memory_agent()
        await agent.initialize()
        await get_uncertainty_system().load_from_db()
        # THE LANGUAGE VIEW FIRST: asked before it is warm, every question came back "I don't know 'Is', 'a', … yet"
        # in 0.02 s (the first smoke run).
        words = await agent.warm_word_classes()
        # ITS OWN LOOPS STOPPED: the pool's worker decides what waited before this run began, and writes as it does.
        # Nothing here needs them, and what is counted after is then the questions' alone.
        await agent.stop_memory_loops()
        db = await get_unified_db()
        if not getattr(db, "initialized", False):
            await db.initialize()
    say(f"  the language view holds {words:,} words")
    EV.check("the run is on the store it says", await EV.verify_database() is not None,
          f"connected to {EV.verified_database}")

    async def written() -> Dict[str, int]:
        """Rows inserted, updated and deleted so far in each table of this store, as the server counts them."""
        rows = await db.execute_query(
            "SELECT schemaname || '.' || relname AS name, n_tup_ins + n_tup_upd + n_tup_del AS n "
            "FROM pg_stat_user_tables")
        return {row["name"]: int(row["n"]) for row in rows or ()}
    before = await written()

    asked_count = [0]
    examples = {}
    #: Every question asked, with what came back: written beside the run record so a failing rate can be read
    #: question by question instead of inferred from one example of each label.
    asked_questions: List[Dict[str, Any]] = []

    async def ask(probe: str, sentence: str):
        """One question, in a conversation of its own: (verdict, understanding, seconds). Verdict: yes, no, unknown,
        unread. The conversation holds this one question, so any verdict in the turn is its answer, whichever
        relation the store answered it through (an individual's "is a" is `instance_of`, a part may be held from
        the whole's side)."""
        asked_count[0] += 1
        logging.getLogger("UNDERSTANDS-WORDNET-01").info("question %d (%s): %s", asked_count[0], probe, sentence)
        if asked_count[0] % 25 == 0:
            say(f"    {time.strftime('%H:%M:%S')}  {asked_count[0]} questions asked")
        conversation = get_conversation(f"understands_wordnet_01_{asked_count[0]}", remembers=False)
        started = time.perf_counter()
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            understanding = await conversation.understand(sentence, look_up=False)
        took = time.perf_counter() - started
        answers = list(understanding.answers or [])
        if any(a.verdict is True for a in answers):
            verdict = "yes"
        elif any(a.verdict is False for a in answers):
            verdict = "no"
        elif understanding.reading is None and not understanding.answers:
            verdict = "unread"
        else:
            verdict = "unknown"
        reply = understanding.reply or ""
        why = ""
        if verdict in ("unread", "unknown"):
            # WHY, in the substrate's own words: each is a different failure to fix.
            why = ("read two ways, would not guess" if "more than one way" in reply else
                   "a word with no name yet" if "no name for" in reply else
                   "words not known" if reply.startswith("I don't know '") else
                   "recalled, gave no verdict" if reply.startswith("I remember") else
                   "said nothing" if not reply.strip() else "other")
            tally(f"{probe} not answered, why", why)
            examples.setdefault((probe, f"{verdict}: {why}"), (sentence, reply[:160]))
        else:
            examples.setdefault((probe, verdict), (sentence, reply[:160]))
        # EVERY QUESTION KEPT, NOT ONE EXAMPLE OF EACH. The tallies say 115 of P1's 121 non-answers said
        # something that was not an answer, and one example of that cannot say what the 115 have in common:
        # which relation each was answered through instead, whether the words resolved, what was said back. A day
        # went on inferring from the samples what the record would have stated (2026-11-10). Written beside the run
        # record, as UNDERSTANDS-PROSE-02 writes its transcript.
        # WHAT THE QUESTION WAS READ TO MEAN, which is what tells a question answered through the wrong relation
        # from one never read as the right one. Asked whether a flower is part of an angiosperm, the reply was
        # "A flower's a angiosperm." -- an `isa` answer to a `part_of` question -- and nothing recorded said
        # whether the part was asked for and not found, or never read at all (2026-11-10).
        meant = conversation._meaning(sentence)
        asked_questions.append({
            "probe": probe, "question": sentence, "verdict": verdict, "why": why, "reply": reply,
            "seconds": round(took, 3),
            "meant": ([f.render() for f in meant.facts] if meant is not None else None),
            "meant_act": (meant.act if meant is not None else None),
            "read": list(understanding.reading) if understanding.reading else None,
            # WHICH THING EACH WORD TURNED OUT TO BE, not merely that it was known. A word is held under one of its
            # senses, and the link asked may be held under another, so the concept each phrase resolved to is what
            # says whether the question could have been found at all.
            "resolved": [{"phrase": r.phrase, "known": bool(r.known), "concept_id": r.concept_id, "how": r.how}
                         for r in understanding.resolved],
            "answers": [{"about": a.about, "relation": a.relation, "others": list(a.others),
                         "verdict": a.verdict, "told": a.told, "conclusion": a.conclusion,
                         "support": list(a.support)} for a in answers],
            # WHY NOTHING WAS ANSWERED, in the substrate's own words, one entry per path that found nothing.
            # `why` above says what the REPLY looked like; this says where the answering stopped.
            "why_not": list(understanding.why_not),
        })
        return verdict, understanding, took

    tallies = {}
    times = []

    def tally(name: str, verdict: str):
        bucket = tallies.setdefault(name, {} if name.endswith("why") else
                                    {"yes": 0, "no": 0, "unknown": 0, "unread": 0})
        bucket[verdict] = bucket.get(verdict, 0) + 1

    async def yes_no(name, pairs, make):
        for pair in pairs:
            verdict, _, took = await ask(name, make(*pair))
            tally(name, verdict)
            times.append(took)
        say(f"  {name}: {tallies.get(name)}")

    say("asking…")
    # P1: four forms, a quarter of the taught facts each (the plural only where English is regular).
    for i, (s, c) in enumerate(truth["taught"]):
        forms = taught_forms(s, c)
        form, sentence = forms[i % len(forms)]
        verdict, _, took = await ask("P1", sentence)
        tally("P1 taught", verdict)
        tally(f"P1 form: {form}", verdict)
        tally(f"P1 {'common' if s in truth['common'] else 'rare'} words", verdict)
        times.append(took)
    say(f"  P1 taught: {tallies.get('P1 taught')}")
    for s, c in truth["inferred"]:
        verdict, _, took = await ask("P2", f"Is {article(s)} {s} {article(c)} {c}?")
        tally("P2 inferred", verdict)
        tally(f"P2 {'common' if s in truth['common'] else 'rare'} words", verdict)
        times.append(took)
    say(f"  P2 inferred: {tallies.get('P2 inferred')}")
    await yes_no("P3 unrelated", truth["unrelated"],
                 lambda s, c: f"Is {article(s)} {s} {article(c)} {c}?")
    await yes_no("P4 nonce", truth["nonce"],
                 lambda s, c: f"Is {article(s)} {s} {article(c)} {c}?")
    both = 0
    for w, h1, h2 in truth["senses"]:
        v1, _, t1 = await ask("P5", f"Is {article(w)} {w} {article(h1)} {h1}?")
        v2, _, t2 = await ask("P5", f"Is {article(w)} {w} {article(h2)} {h2}?")
        tally("P5 each sense", v1)
        tally("P5 each sense", v2)
        both += (v1 == "yes" and v2 == "yes")
        times += [t1, t2]
    say(f"  P5 each sense: {tallies.get('P5 each sense')}, both senses yes {both}/{len(truth['senses'])}")
    await yes_no("P6 parts", truth["parts"],
                 lambda p, w: f"Is {article(p)} {p} part of {article(w)} {w}?")
    await yes_no("P6 parts, unrelated", truth["part_controls"],
                 lambda p, w: f"Is {article(p)} {p} part of {article(w)} {w}?")
    await yes_no("P7 opposites", truth["opposites"],
                 lambda a, b: f"Is {a} the opposite of {b}?")
    await yes_no("P7 opposites, unrelated", truth["opposite_controls"],
                 lambda a, b: f"Is {a} the opposite of {b}?")

    right = wrong = none = 0
    for w, ancestors in truth["what_is"]:
        _, understanding, took = await ask("P8", f"What is {article(w)} {w}?")
        times.append(took)
        named = {str(o).replace("_", " ").lower() for a in (understanding.answers or []) if a.relation in ("isa", "instance_of")
                 for o in a.others}
        named = {n for n in named if n and n != w}
        if not named:
            none += 1
            examples.setdefault(("P8", "none"), (f"What is {article(w)} {w}?", (understanding.reply or "")[:160]))
        elif any(n == x or n.endswith(" " + x) for n in named for x in ancestors):
            right += 1
            examples.setdefault(("P8", "right"), (f"What is {article(w)} {w}?", (understanding.reply or "")[:160]))
        else:
            wrong += 1
            examples.setdefault(("P8", "wrong"), (f"What is {article(w)} {w}? (WordNet: {sorted(ancestors)[:4]})",
                                                  (understanding.reply or "")[:160]))
    tallies["P8 what is"] = {"right": right, "wrong": wrong, "none": none}
    say(f"  P8 what is: {tallies['P8 what is']}")

    # ── the verdict against the bars ───────────────────────────────────────
    def rate(name, key):
        t = tallies.get(name) or {}
        n = sum(t.values())
        return (t.get(key, 0), n)

    measured = {
        "P1 taught, asked new ways: yes": rate("P1 taught", "yes"),
        "P2 inferred: yes": rate("P2 inferred", "yes"),
        "P3 unrelated: yes (must be low)": rate("P3 unrelated", "yes"),
        "P4 nonce: yes (must be zero)": rate("P4 nonce", "yes"),
        "P5 both senses: yes": (both, len(truth["senses"])),
        "P6 parts: yes": rate("P6 parts", "yes"),
        "P6 parts, unrelated: yes (must be low)": rate("P6 parts, unrelated", "yes"),
        "P7 opposites: yes": rate("P7 opposites", "yes"),
        "P7 opposites, unrelated: yes (must be low)": rate("P7 opposites, unrelated", "yes"),
        "P8 what is: right": (right, right + wrong + none),
        "P8 what is: wrong (must be low)": (wrong, right + wrong + none),
    }
    say("\n==== UNDERSTANDS-WORDNET-01 ====")
    for label, (k, n) in measured.items():
        low, high = wilson(k, n)
        value = k / n if n else 0.0
        must_be_low = "must be" in label
        ok = (value <= BARS[label]) if must_be_low else (value >= BARS[label])
        say(f"  {'PASS' if ok else 'FAIL'}  {label:46} {k:4}/{n:<4} {value:6.1%}  "
            f"(95% {low:.1%}–{high:.1%}; bar {'≤' if must_be_low else '≥'} {BARS[label]:.0%})")
        EV.check(f"{label} {'≤' if must_be_low else '≥'} {BARS[label]:.0%}", ok,
                 f"{k}/{n} = {value:.1%} (95% {low:.1%}–{high:.1%})")
        EV.metric(label, round(value, 4), unit="fraction", note=f"{k}/{n}")
    say("\n  every tally (yes / no / unknown / unread):")
    for name, t in tallies.items():
        say(f"    {name:34} {t}")
        EV.note(f"{name}: {t}")
    times.sort()
    if times:
        say(f"\n  {len(times)} questions; seconds a question: median {times[len(times) // 2]:.2f}, "
            f"p95 {times[int(len(times) * .95)]:.2f}, max {times[-1]:.2f}")
        EV.metric("seconds a question, median", round(times[len(times) // 2], 3), unit="s")
    say("\n  one of each (question → reply):")
    for (probe, verdict), (q, r) in sorted(examples.items()):
        say(f"    [{probe} {verdict}] {q} → {r}")
        EV.note(f"[{probe} {verdict}] {q} → {r}")
    # NOTHING WRITTEN: the server's counters, a moment after the last question, against the ones before the first.
    await asyncio.sleep(1)
    after = await written()
    moved = {name: after[name] - before.get(name, 0) for name in after if after[name] != before.get(name, 0)}
    EV.check("the questions wrote nothing to the store", not moved,
          "; ".join(f"{name} +{n}" for name, n in sorted(moved.items())) or "no table written to")
    path = EV.write()
    say(f"\n  run record: {path}")
    questions_path = str(path).replace(".json", "_questions.jsonl")
    with open(questions_path, "w", encoding="utf-8") as record:
        for asked_one in asked_questions:
            record.write(json.dumps(asked_one, ensure_ascii=False) + "\n")
    say(f"  every question: {questions_path}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
