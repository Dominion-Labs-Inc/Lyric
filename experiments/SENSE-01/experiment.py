#!/usr/bin/env python3
"""SENSE-01 — the listener takes each word in the sense meant, at an LLM's level, and all of WordNet's kinds of record
go in after the lessons without taking away any English the lessons taught.

A word names several things ("fish": an animal, a food). WordNet names each sense apart: the one the word names most
often by the word itself ("fish"), or the one the lessons are stated to use it in (`data/lessons/senses.json`:
"table" the furniture); each other one by what it is first a kind of ("solid food fish"); a number by its value. The
reader reports every meaning a sentence can have; the listener (`derived_reader.meant`, `heard`) takes one by what
memory holds of what is said, then by how it bears on the rest of what is said and on what was talked of before
(`MemoryAgent.listening_evidence`), then by how often each word was met naming each thing (WordNet's tagged uses and
the lessons'), and leaves open only what none of that settles.

  A  TEACH      every lesson (english_01 on), then WordNet: every record about a sense of a word the lessons or this
                experiment's sentences use, the kinds above those senses, and a uniform sample of the rest (every
                kind of record); then how often each word was met naming each thing
  B  SAID       what a thing is a kind of is said in WordNet's words, as English says it; the other relations are
                measured; none refused
  C  WORDS      a sense named by its word reads in a question never taught ("What is an ocelot?") to that sense; a
                word whose other senses are named apart is still taken one way, never left open
  D  FACTS      the kinds taught are held; unrelated pairs are not
  E  SAY        facts taught are said, and what is said is taken back as the fact taught, a sense named apart
                included
  F  LESSONS    every lesson sentence: taken as before WordNet went in, or in the WordNet sense the lessons are
                stated to use that word in
  G  BLOCKER    the sentences WordNet's senses used to make unreadable are taken in the lessons' sense
  H  UNTAUGHT   the lessons' never-taught sentences are taken as before
  K  LISTENER   sentences an LLM takes the right way without thinking: by what is known ("A mouse is a device."),
                by the conversation before ("An elephant is an animal." then "The trunk is long."), by how a word
                is used; and words that sound alike heard the way that makes sense
  I  COST       seconds per record
  J  MAIN       the main model's store is untouched

Runs in the SANDBOX (`lyric_dev`), emptied first by `scripts/reset_dev_store.py`; the lessons and WordNet's records
taught are kept.

`--k-only` measures the listener (K) alone, on the sandbox as it stands: no reset and no lessons (they must be held
already), only WordNet's records about K's own words and the kinds above them, their usage, then K and J. With
`--fresh` too, the sandbox is emptied and the lessons taught first.

Run: ./venv_lyric/bin/python3 experiments/SENSE-01/experiment.py [--k-only [--fresh]]
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import os
import random
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

LESSONS = sorted((ROOT / "data" / "lessons").glob("english_[0-9][0-9].json"))
DOMAIN = "sense_01"
SAMPLE = 2000
SEED = 20260930

EV = RunRecord(
    "SENSE-01",
    claim=("The listener takes each word in the sense meant: by what memory holds, then by how often the word has "
           "been met naming each thing. With it, WordNet's senses of the lessons' own words, and every kind of "
           "record WordNet has, are taught after the lessons without taking away any reading the lessons taught."),
    hypothesis=("A lesson sentence the listener took one way before WordNet and another way, or not at all, after; a "
                "blocker sentence left open or taken in a sense the lessons never meant; a word left open in a "
                "question; a fact said that is taken back as another; a pair refused; a fact not held or an "
                "unrelated pair answered yes; or a write to the main store would each show here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main_store_rows() -> dict:
    """Rows in each table of the main model's store, counted over its own connection. Each row once: a partitioned
    table's rows are its partitions' (`only`), where counted in both the profiler's 10,211 timings were 20,422."""
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan", database="lyric_db")
    try:
        rows = {}
        for t in await c.fetch(
                "select table_schema s, table_name n from information_schema.tables "
                "where table_schema in ('unified','memory_hot','memory_cold') and table_type='BASE TABLE'"):
            rows[f'{t["s"]}.{t["n"]}'] = await c.fetchval(f'select count(*) from only "{t["s"]}"."{t["n"]}"')
        return rows
    finally:
        await c.close()


def main_store_change(before: dict, after: dict) -> str:
    """Two counts of the main store, said: the totals, and each table whose rows differ. The live substrate writes
    to the same store, so a count that moved names where, for whoever reads the record to tell whose write it was."""
    moved = [f"{t} {before.get(t, 'absent')} to {after.get(t, 'absent')}"
             for t in sorted({*before, *after}) if before.get(t) != after.get(t)]
    return (f"{sum(before.values())} rows before, {sum(after.values())} after"
            + (f": {'; '.join(moved)}" if moved else ""))


class GateSource:
    """WordNet's records, as `WordNetSource` gives them, narrowed to what this gate teaches: every record about a
    sense of a word the lessons or this experiment's sentences use (the sense the word names, and each sense named
    apart), every record of a kind of one of those senses named apart, every kind above those senses (so what is
    known of them reaches as far as WordNet does), the definitions of those words, and a uniform sample of the
    rest. How often each word was met naming each thing is WordNet's own (`usage`). What words are said of is the
    Brown corpus's, all of it (`said_of`); for it to be weighed, the kinds of what these words are said of are taught,
    and of a uniform sample of everything else said (`SAID_SAMPLE` words a relation), so how often anything at all
    is said of a kind is measured over more than these words."""

    #: Words whose kinds are taught from everything said under each relation K's words are said in.
    SAID_SAMPLE = 100

    def __init__(self, words, sample=SAMPLE):
        from core.learning.teaching_sources import WordNetSource
        self.wordnet = WordNetSource()
        self.name, self.quality, self.curated = self.wordnet.name, self.wordnet.quality, self.wordnet.curated
        self.words = words
        self.sample = sample
        self.kept = None
        self._said = None

    def said_of(self):
        if self._said is None:
            self._said = list(self.wordnet.said_of())
        return iter(self._said)

    def _said_about(self):
        """The words these words are said of, and a uniform sample of the words said under the same relations."""
        mine, every = set(), {}
        for relation, word, side, other, _ in self.said_of():
            every.setdefault((relation, side), set()).add(other)
            if word in self.words:
                mine.add(other)
        rng = random.Random(SEED)
        for (relation, side), others in sorted(every.items()):
            if any(w in self.words for r, w, s, _, _ in self._said if (r, s) == (relation, side)):
                mine.update(rng.sample(sorted(others), min(self.SAID_SAMPLE, len(others))))
        return mine

    def provenance(self):
        return self.wordnet.provenance()

    def word_classes(self):
        """The classes of the words this gate teaches. All of WordNet's 75,834 are one memory each, about an hour and
        a half on an empty store, and only the words taught here are read here."""
        taught = {w.lower() for r in self.records() for w in
                  [r.subject, r.obj, *(word for _, word in r.words)] if w}
        return ((word, c) for word, c in self.wordnet.word_classes() if word in taught)

    def usage(self):
        return self.wordnet.usage()

    def _narrowed(self):
        from nltk.corpus import wordnet as wn
        names = self.wordnet._sense_names()
        apart = {name for synset, name in names.items()
                 if name and name != synset.lemma_names()[0].replace("_", " ").strip().lower()
                 and name.split()[-1] in self.words}
        above, senses = set(), set(self.words)
        for word in self.words:
            for synset in wn.synsets(word.replace(" ", "_")):
                # Every sense the word writes, by the name it is taught under: "bank" writes the financial
                # institution, named `depository financial institution`.
                senses.add(names.get(synset, ""))
                for path in synset.hypernym_paths():
                    above.update(names.get(k, "") for k in path)
        # WHAT THESE WORDS ARE SAID OF, as kinds: the noun senses of each word they are said of, and every kind
        # above them.
        for other in self._said_about():
            for synset in wn.synsets(other.replace(" ", "_"), wn.NOUN):
                for path in synset.hypernym_paths():
                    above.update(names.get(k, "") for k in path)
        above.discard("")
        senses.discard("")
        own, rest = [], []
        for record in self.wordnet.records():
            if record.subject:
                about = (record.subject in senses or record.subject in apart or record.obj in apart
                         or (record.subject in above and record.relation in ("isa", "instance_of"))
                         # A part or member of one of these words' senses ("a trunk is part of an elephant"):
                         # about the word as much as the word's own records are.
                         or (record.obj in self.words and record.relation in ("part_of", "member_of", "made_of")))
            else:
                about = record.sentence.split(" is ", 1)[0].split(" ", 1)[-1].lower() in self.words
            (own if about else rest).append(record)
        rest = random.Random(SEED).sample(rest, min(self.sample, len(rest)))
        return own, rest, apart

    def records(self):
        if self.kept is None:
            own, rest, self.apart = self._narrowed()
            self.own = own
            self.kept = own + rest
        return iter(self.kept)


def held_names() -> frozenset:
    """Every name the view holds now, with the thing it names: `(concept, words)`. Taken before teaching, it tells
    `said_wrongly` which names the teaching brings."""
    from core.semantics.derived_reader import live_view
    view = live_view()
    return frozenset((item.value, tuple(w.lower() for w in item.words)) for item in view.lexicals())


def said_wrongly(records, held: frozenset = None) -> list:
    """The sentences the substrate would say of these records that are wrong English, found with nothing written:
    `(sentence, why)`.

    The substrate says each fact a source states and learns English from what it said (`TeachingPass._said`), so a
    fact said wrongly is taught wrongly, and stays held. On 2026-10-02 two runs of COMPREHENSION-01 taught the
    sandbox "Chore is body of work." and "Kennel is outbuilding." that way, and a rebuild "A substance is a
    matter.". Each record is said here, and each name the teaching brings is judged by how its thing is used:
    - a counted name does not stand bare (first in the sentence, or straight after "is");
    - a name not counted, or only ever plural, does not follow "a", "an", "each" or "every";
    - a name only ever plural is not followed by "is".

    HOW A NAME IS USED IS THE SOURCE'S TO STATE, for the sense the record is about. The view holds a word's use
    over everything written with it ("travel", counted for a trip, uncounted for the act), so it speaks only for
    a name the source states nothing of.

    A NAME HELD FOR ITS THING BEFORE THE TEACHING (`held`, from `held_names`; the view as it stands when not given)
    is said as it is held, and is not judged: the lessons say "Biology is a science.", whatever a source states of
    "science"."""
    import re
    from core.learning.teaching import TeachingPass
    from core.semantics.derived_reader import live_view
    view = live_view()
    # Before the teaching the view speaks for a name the source states nothing of. After it, the view's use of a
    # word is drawn from what was just taught, every word of a thing together, and is not asked.
    first = held is None
    held = held_names() if held is None else held

    def tokens(text):
        return [w.lower() for w in re.findall(r"[^\W_]+(?:['’-][^\W_]+)*", text)]

    wrong = []
    for record in records:
        if record.meaning is None or record.sentence:
            continue
        sentence = TeachingPass._said(record)
        if not sentence:
            continue
        words = tokens(sentence)
        stated = {name.lower(): use for name, use in record.uses}
        written = dict(record.words)
        # The fact's own terms, each as the source writes it: a run of words is one name ("game equipment"), never
        # its first word alone. The longest first, and where it stands is its own: "news" in "A news report is
        # news." is judged where it stands alone.
        terms = {(str(t), str(written.get(t, t)).replace("_", " ")) for f in record.meaning.facts
                 for t in (f.subject, f.obj) if not str(t).startswith("?")}
        taken = set()
        for concept, name in sorted(terms, key=lambda cn: (-len(cn[1].split()), cn)):
            parts = tokens(name)
            if not parts:
                continue
            places = [at for at in range(len(words) - len(parts) + 1)
                      if words[at:at + len(parts)] == parts and not taken & set(range(at, at + len(parts)))]
            taken.update(i for at in places for i in range(at, at + len(parts)))
            if (concept, tuple(parts)) in held:
                continue
            # A word written with a capital is a name unless the source states otherwise.
            known = (view.used_as(parts[0], concept) or view.used_as(parts[0])) \
                if first and len(parts) == 1 and name[:1].islower() else None
            use = stated.get(name.lower()) or known
            # After "are" a name stands for many, in a plural its singular cannot show ("Alewives are fish."): not
            # judged.
            if use == "count" and any((at == 0 or words[at - 1] == "is")
                                      and words[at + len(parts):at + len(parts) + 1] in ([], ["is"])
                                      for at in places):
                wrong.append((sentence, f"'{name}' is counted and stands bare"))
                break
            after = [words[at - 1] for at in places if at > 0 and words[at - 1] in ("a", "an", "each", "every")]
            if use in ("mass", "plural") and after:
                wrong.append((sentence, f"'{name}' is {'not counted' if use == 'mass' else 'a plural'} and follows "
                                        f"'{after[0]}'"))
                break
            if use == "plural" and any(words[at + len(parts):at + len(parts) + 1] == ["is"] for at in places):
                wrong.append((sentence, f"'{name}' is a plural and is followed by 'is'"))
                break
    return wrong


def frame_words() -> frozenset:
    """Every word the frames held now are built from, for `frames_wrongly` to tell what teaching added."""
    from core.semantics.derived_reader import Piece, live_view
    return frozenset(piece.text.lower() for pattern in live_view().item_based() for piece in pattern.form
                     if isinstance(piece, Piece))


def frames_wrongly(before: frozenset) -> list:
    """The frames held now that carry a word of some fact as if it built sentences: `(frame, why)`.

    The learner makes a frame of a sentence it cannot read with what it holds. Taking a name of several words apart
    ("news report", where "report" was already held for it) left "news" in a frame, "A ?slot0 ?slot1 is news.",
    which then said of anything at all that it is news. A frame may hold a word no frame held before teaching
    (`before`, from `frame_words`) only as the word of a thing its meaning names ("A battle is ?slot0.", said of a
    battle only): more such words than things named is a fact's word left in the frame."""
    from core.semantics.derived_reader import Piece, is_variable, live_view
    wrong = []
    for pattern in live_view().item_based():
        added = sorted({piece.text.lower() for piece in pattern.form
                        if isinstance(piece, Piece) and any(c.isalpha() for c in piece.text)} - before)
        named = {t for f in pattern.meaning.facts for t in (f.subject, f.obj) if not is_variable(t)}
        if len(added) > len(named):
            wrong.append((pattern.surface, f"holds {added}, and its meaning names {sorted(named) or 'nothing'}"))
    return wrong


#: The door's reason for refusing a fact about a word the lessons use only to build sentences ("be", "have", "lot").
NAMES_NOTHING = "is made only of words that name nothing"


async def refused_facts(db, since, domain: str) -> tuple:
    """The facts a teaching pass in `domain` had refused since `since`, from the knowledge ledger, as `(for a word
    that names nothing, for any other reason)`: each `subject_id :: reason`.

    A fact about a word English as taught uses only to build sentences is refused by the door
    (`cognitive_ingress.admissible`), as it should be until a lesson uses the word as a thing: "lot" is held only in
    "a lot of". Any other refusal is a defect: on 2026-10-02 37 facts were refused because the pass admitted facts
    before learning the sentences that name their words, and one because the source counted a name's words by
    spaces where the door also parts them at a hyphen."""
    rows = await db.execute_query(
        "SELECT subject_id, detail FROM unified.knowledge_updates WHERE disposition = 'rejected' "
        "AND occurred_at >= $1 AND domain = $2 ORDER BY occurred_at", (since, domain), fetch_all=True) or []
    said = [f"{r['subject_id']} :: {r['detail']}" for r in rows]
    return [r for r in said if NAMES_NOTHING in r], [r for r in said if NAMES_NOTHING not in r]


#: Sentences an LLM takes the right way without thinking, each with the conversation before it, the word that names
#: several things, and the WordNet sense it is meant in, and why.
LISTENER = [
    ((), "A mouse is a rodent.", "mouse", "mouse.n.01", "what is known: a mouse is a rodent"),
    ((), "A mouse is a device.", "mouse", "mouse.n.04", "what is known: the computer's mouse is a device"),
    ((), "A bat is a mammal.", "bat", "bat.n.01", "what is known"),
    ((), "A crane is a bird.", "crane", "crane.n.05", "what is known: the wading bird"),
    ((), "A crane is a device.", "crane", "crane.n.04", "what is known: the lifting device"),
    ((), "A bank is a slope.", "bank", "bank.n.01", "what is known"),
    ((), "A plant is an organism.", "plant", "plant.n.02", "what is known"),
    ((), "All fish can swim.", "fish", "fish.n.01", "how the word is used: the animal"),
    ((), "The table is red.", "table", "table.n.02", "how the lessons use the word: furniture"),
    (("An elephant is an animal.",), "The trunk is long.", "trunk", "proboscis.n.02",
     "the conversation: an elephant's trunk, where a tree's is the word's most used sense"),
    (("A tree is a plant.",), "The trunk is long.", "trunk", "trunk.n.01", "the conversation: a tree's trunk"),
    (("A plane is a vehicle.",), "The wing is long.", "wing", "wing.n.02",
     "the conversation: an airplane's wing, where a bird's is the word's most used sense"),
    (("A bird is an animal.",), "The wing is long.", "wing", "wing.n.01", "the conversation: a bird's wing"),
    (("A computer is a machine.",), "The mouse is small.", "mouse", "mouse.n.04",
     "the conversation: a computer's mouse"),
    # Two an LLM takes from what it knows of the world that WordNet's relations do not hold: that eating is done to
    # food, and that money is kept in a bank. Kept here so the bar is an LLM's, not what is easy.
    ((), "Tom ate the fish.", "fish", "fish.n.02", "what is known of eating: food is eaten"),
    (("Tom has money.",), "The bank is big.", "bank", "depository_financial_institution.n.01",
     "the conversation: money, kept in a bank"),
]
#: Ways of hearing what was said where a word sounds like another, and the way that makes sense.
ALIKE = [
    (("A mouse is a rodent.", "A moose is a rodent."), "A mouse is a rodent.", "what is known"),
    (("A mouse is a deer.", "A moose is a deer."), "A moose is a deer.", "what is known"),
]
PROBE_WORDS = {"mouse", "bat", "crane", "bank", "plant", "fish", "table", "trunk", "wing", "elephant", "tree",
               "plane", "airplane", "bird", "computer", "machine", "vehicle", "animal", "moose", "deer", "rodent",
               "mammal", "device", "slope", "organism", "eat", "food", "money", "red", "big", "long", "small", "swim"}


async def main(k_only: bool = False, fresh: bool = False, listen_only: bool = False) -> int:
    main_before = await main_store_rows()
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()
    where = await db.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the run is in the sandbox", where["d"] == "lyric_dev", f"connected to {where['d']}")
    if where["d"] != "lyric_dev":
        return 1
    import contextlib
    import io
    boot_log = io.StringIO()
    with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
        from core.main import get_system
        system = get_system()
        await system.start()
    check("the substrate is running", system.autonomous_coordinator is not None and system.running)
    try:
        return await (_run_k(db, main_before, fresh, listen_only) if k_only else _run(db, main_before))
    finally:
        with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
            await system.shutdown()


def _taken(sentence, heard=None):
    """What the listener takes the sentence's last utterance to mean: the canonical meaning, or None when it reads
    whole and the listener cannot tell, or "unread"."""
    from core.semantics import derived_reader as dr
    utterances = dr.read_text(sentence)
    if not utterances or not all(u.understood for u in utterances):
        return "unread"
    chosen = dr.meant(utterances[-1].readings, heard=heard)
    return chosen.meaning.canonical() if chosen is not None else None


async def _listened(sentence, context=()):
    """As every reading that can wait for memory listens (`derived_reader.listening`): memory asked what it knows of
    each way the words can be taken, against the rest of what is said and `context`, then the listener's choice."""
    from core.semantics import derived_reader as dr
    utterances = dr.read_text(sentence)
    return _taken(sentence, await dr.listening([u.readings for u in utterances], context))


def _lesson_words():
    words = set(PROBE_WORDS)
    for path in LESSONS:
        for record in json.loads(path.read_text())["records"]:
            for fact in record["meaning"]["facts"]:
                words.update(t.lower() for t in fact[1:3] if not str(t).startswith("?"))
    return words


async def _run(db, main_before: dict) -> int:
    from core.learning import get_learning_authority
    from core.learning.teaching import TeachingPass
    from core.learning.teaching_sources import LessonSource, WordNetSource
    from core.memory import get_memory_agent
    from core.reasoning.concept_graph_reasoning import answer_over_graph
    from core.reasoning.relation_algebra import TRUE
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import Meaning, MeaningFact
    from core.semantics.relation_types import SemanticRelation
    import importlib.util
    spec = importlib.util.spec_from_file_location("sl09", ROOT / "experiments" / "SHAPES-LEARN-09" / "experiment.py")
    sl09 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sl09)
    agent = await get_memory_agent()
    learning = get_learning_authority()

    say_line("== A. The lessons, then WordNet, through the one teaching path ==")
    taught = []
    for path in LESSONS:
        source = LessonSource(str(path))
        lesson = list(source.records())
        report = await TeachingPass(source, domain=DOMAIN, sample=False).run(learning)
        taught.extend(lesson)
        check(f"{path.name} is learned, none refused",
              report.patterns.get("refused") == 0 and report.patterns.get("total") == len(lesson),
              f"{report.patterns}")
    # How the listener takes every lesson sentence, and the never-taught ones, before WordNet goes in.
    before = {r.sentence: _taken(r.sentence) for r in taught}
    probes = sl09.FUNCTION + sl09.NAMES
    untaught_before = {s: _taken(s) for s, _ in probes}

    source = GateSource(_lesson_words())
    wordnet = TeachingPass(source, domain=DOMAIN, sample=False)
    harvest = list(source.records())
    said_kind = [r for r in harvest if r.meaning is not None]
    facts_only = [r for r in harvest if r.meaning is None and r.subject]
    glosses = [r for r in harvest if not r.subject]
    say_line(f"    taught from WordNet: {len(harvest)} records -- {len(source.own)} about the lessons' words and "
             f"their senses ({len(source.apart)} senses named apart), {len(harvest) - len(source.own)} sampled; "
             f"{len(said_kind)} said through frames, {len(facts_only)} facts alone, {len(glosses)} definitions")
    spoken = [(r, TeachingPass._said(r)) for r in said_kind]
    view = agent.pattern_inventory()
    judged = []
    for record, sentence in spoken:
        word = dict(record.words).get(record.subject, record.subject)
        parent = dict(record.words).get(record.obj, record.obj)
        held = bool(view.lexicals_with_value(record.subject) or view.lexicals_with_words((word.lower(),), loose=True))
        judged.append((record, sentence, word, parent, None if held else view.use_of(word), view.use_of(parent)))
    started = time.time()
    report = await wordnet.run(learning)
    seconds = time.time() - started
    for line in report.lines():
        say_line(f"    {line}")
    check("no pair said is refused", report.patterns.get("refused") == 0, f"{report.patterns}")

    say_line("\n== B. Said through the frames taught ==")
    said = report.meanings.get("said", 0)
    kinds_said = [s for r, s in spoken if r.relation == "isa"]
    check("what a thing is a kind of is said in WordNet's words, through the frames taught",
          said == sum(1 for _, s in spoken if s) and sum(1 for s in kinds_said if s) >= 0.9 * len(kinds_said),
          f"kinds said {sum(1 for s in kinds_said if s)}/{len(kinds_said)}; all said {said}/{len(said_kind)}")
    EV.metric("facts said through frames", f"{said}/{len(said_kind)}")
    # The other relations' frames were taught with a few examples each ("A wheel is part of a car."), so a pair of
    # words never held is said through them only where the frame takes it; a fact not said is still taught, as a
    # fact. Measured, not judged.
    for relation in sorted({r.relation for r, _ in spoken}):
        of = [s for r, s in spoken if r.relation == relation]
        EV.metric(f"said: {relation}", f"{sum(1 for s in of if s)}/{len(of)}")
        say_line(f"    {relation}: said {sum(1 for s in of if s)}/{len(of)}")
    wrong, bare, lettered = [], [], []
    for record, sentence, word, parent, use, parent_use in judged:
        if not sentence or record.relation != "isa":
            continue
        if use in ("name", "mass") and sl09._after_a(sentence, word):
            wrong.append(sentence)
        if (use == "count" and sl09._bare(sentence, word)) \
                or (parent_use == "count" and sl09._bare(sentence, parent, at_start=False)):
            bare.append(sentence)
    for _, sentence in spoken:
        if sentence and sl09._against_the_letter(sentence):
            lettered.append(sentence)
    check("what is said is said as English says it: 'a' and 'an' where they go, and only there",
          not (wrong or bare or lettered), f"after 'a': {wrong[:3]}; bare: {bare[:3]}; against the letter: {lettered[:3]}")
    by_kind = {}
    for record, sentence in spoken:
        if sentence and len(by_kind.setdefault(record.relation, [])) < 3:
            by_kind[record.relation].append(sentence)
    say_line(f"    said, for example: {by_kind}")

    say_line("\n== C. Every word taught, in a question never taught ==")
    view = agent.pattern_inventory()
    right, open_, asked, missed = 0, 0, 0, []
    for record, sentence in spoken:
        if not sentence or record.relation != "isa":
            continue
        word = dict(record.words).get(record.subject, record.subject)
        article = view.shape_before("a", word[:1]) if word[:1].isalpha() else "a"
        question = f"What is {article} {word}?"
        got = _taken(question)
        asked += 1
        if record.subject == word.lower() or record.subject == word:
            wanted = Meaning("ask", (MeaningFact("isa", record.subject, "?x"),), ("?x",)).canonical()
            if got is not None and got != "unread" and got.lower() == wanted.lower():
                right += 1
            elif len(missed) < 12:
                missed.append((question, record.subject, got))
        elif got not in (None, "unread"):
            right += 1
        else:
            open_ += 1
            if len(missed) < 12:
                missed.append((question, record.subject, got))
    for question, sense, got in missed:
        say_line(f"    {question!r} (taught of {sense!r}) -> {got}")
    check("each word taught reads in a question never taught: to its sense where the word names it, one way "
          "where its senses are named apart", right == asked, f"{right}/{asked}; left open {open_}")
    EV.metric("words taught read in a question never taught", f"{right}/{asked}")

    say_line("\n== D. The facts are held ==")
    rng = random.Random(SEED)
    kinds = [r for r in harvest if r.subject and r.relation in ("isa", "instance_of")]
    probed = rng.sample(kinds, min(200, len(kinds)))
    held = 0
    for record in probed:
        answer = await answer_over_graph(db, record.subject, SemanticRelation(record.relation), record.obj,
                                         max_hops=4)
        held += answer.verdict == TRUE
    check("the reasoning authority answers yes to the kinds taught", held == len(probed), f"{held}/{len(probed)}")
    related = {(r.subject, r.obj) for r in kinds}
    subjects, objects = [r.subject for r in kinds], [r.obj for r in kinds]
    controls, guard = [], 0
    while len(controls) < 200 and guard < 20000:
        guard += 1
        s, o = rng.choice(subjects), rng.choice(objects)
        if s != o and (s, o) not in related:
            controls.append((s, o))
    invented = 0
    for s, o in controls:
        answer = await answer_over_graph(db, s, SemanticRelation.ISA, o, max_hops=4)
        invented += answer.verdict == TRUE
    check("for pairs WordNet does not relate it does not answer yes", invented == 0,
          f"{invented}/{len(controls)} answered yes")
    EV.metric("kinds held", f"{held}/{len(probed)}")

    say_line("\n== E. Facts taught, said back, taken back by the listener ==")
    back, total, shown = 0, 0, 0
    apart_back, apart_total = 0, 0
    for record, _ in [(r, s) for r, s in spoken if s][:300]:
        sentences = dr.say(record.meaning)
        got = await _listened(sentences[0]) if sentences else None
        ok = got is not None and got != "unread" and got.lower() == record.meaning.canonical().lower()
        total += 1
        back += ok
        if record.subject in source.apart or record.obj in source.apart:
            apart_total += 1
            apart_back += ok
        if (not ok and shown < 10) or shown < 4:
            say_line(f"    {'ok ' if ok else 'BAD'} {record.meaning.canonical()} -> {sentences[:1]} -> {got}")
            shown += 1
    check("each fact taught is said, and taken back as the fact taught", back == total, f"{back}/{total}")
    EV.metric("facts said and taken back", f"{back}/{total}")
    EV.metric("of them, about a sense named apart", f"{apart_back}/{apart_total}")

    say_line("\n== F. The lessons, as the listener took them before WordNet ==")
    after = {r.sentence: await _listened(r.sentence) for r in taught}
    changed = [(s, before[s], after[s]) for s in before if after[s] != before[s]]
    # Taken in another sense of a word: the same words said of the same things but for which thing one word names
    # (the lessons' "hard" for a bench taken as WordNet's resisting-pressure sense). A listener weighing what it now
    # knows may take a word so; that is listed, never counted as lost. Lost is a sentence that read to a meaning
    # before and reads to none, or is left open, or to a meaning that says something else.
    lost, resensed = [], []
    for s_, b, a_ in changed:
        if b in (None, "unread"):
            continue
        if a_ in (None, "unread"):
            lost.append((s_, b, a_))
            continue
        readings = [r for u in dr.read_text(s_) for r in u.readings]
        by_meaning = {r.meaning.canonical(): r for r in readings}
        if b in by_meaning and a_ in by_meaning and dr.sense_choices([by_meaning[b], by_meaning[a_]]):
            resensed.append((s_, b, a_))
        else:
            lost.append((s_, b, a_))
    for s_, b, a_ in lost[:10]:
        say_line(f"    LOST {s_!r}: before {b} -> after {a_}")
    for s_, b, a_ in resensed[:15]:
        say_line(f"    another sense {s_!r}: {b} -> {a_}")
    check("no lesson sentence the listener took before WordNet is lost: each is taken as before, or in another "
          "sense of a word", not lost,
          f"{len(before) - len(changed)}/{len(before)} the same; {len(resensed)} in another sense; {len(lost)} lost")
    EV.metric("lesson sentences taken as before", f"{len(before) - len(changed)}/{len(before)}")
    EV.metric("lesson sentences taken in another sense of a word", len(resensed))
    as_taught = sum(1 for r in taught if (after[r.sentence] or "").lower() == r.meaning.canonical().lower())
    say_line(f"    taken as taught: {as_taught}/{len(taught)} (before WordNet: "
             f"{sum(1 for r in taught if (before[r.sentence] or '').lower() == r.meaning.canonical().lower())})")

    say_line("\n== G. The sentences WordNet's senses used to make unreadable ==")
    blocker = {"All fish can swim.": Meaning("tell", (MeaningFact("capable_of", "fish", "swim"),)),
               "A trillion is a number.": Meaning("tell", (MeaningFact("isa", "1000000000000", "number"),)),
               "Every cat is an animal.": Meaning("tell", (MeaningFact("isa", "cat", "animal"),)),
               "A Bostonian is a person.": Meaning("tell", (MeaningFact("isa", "bostonian", "person"),))}
    bad = []
    for sentence, wanted in blocker.items():
        got = await _listened(sentence)
        senses = len({r.meaning.canonical() for u in dr.read_text(sentence) for r in u.readings})
        say_line(f"    {sentence!r}: {senses} meaning(s) read; taken as {got}")
        if (got or "").lower() != wanted.canonical().lower():
            bad.append((sentence, got))
    check("each is taken in the lessons' sense", not bad, f"{bad}")

    say_line("\n== H. The never-taught sentences ==")
    untaught_after = {s: await _listened(s) for s, _ in probes}

    def right_of(taken, wanted):
        return (taken or "").lower() == wanted.canonical().lower()

    moved = [(s, untaught_before[s], untaught_after[s]) for s in untaught_before
             if untaught_after[s] != untaught_before[s]]
    for s, b, a in moved:
        say_line(f"    {s!r}: before {b} -> after {a}")
    was = sum(1 for s, wanted in probes if right_of(untaught_before[s], wanted))
    now = sum(1 for s, wanted in probes if right_of(untaught_after[s], wanted))
    lost = [s for s, wanted in probes if right_of(untaught_before[s], wanted) and not right_of(untaught_after[s], wanted)]
    check("every never-taught sentence the lessons read right before WordNet is still read right", not lost,
          f"right before {was}/{len(probes)}, after {now}/{len(probes)}; lost {lost}")

    await _listener_bar(source, report)

    say_line("\n== I. The cost ==")
    per_record = seconds / max(1, len(harvest))
    offered = sum(1 for _ in WordNetSource().records())
    say_line(f"    {seconds:.0f} s for {len(harvest)} records: {per_record * 1000:.0f} ms each; all {offered:,} of "
             f"WordNet's records would take about {per_record * offered / 3600:.1f} h at this rate")
    EV.metric("seconds per WordNet record", round(per_record, 4))
    EV.metric("hours for all of WordNet's records, at this rate", round(per_record * offered / 3600, 2))

    return await _finish(main_before)


async def _run_k(db, main_before: dict, fresh: bool = False, listen_only: bool = False) -> int:
    """K alone: WordNet's records about K's own words and the kinds above them, and WordNet's usage, are taught; then
    K. On the sandbox as it stands, where the lessons must be held already; or, `fresh`, on the emptied sandbox with
    the lessons taught first; or, `listen_only`, nothing taught, where the lessons and K's words must be held
    already: how the listener takes K, after a change to the listener alone."""
    from core.learning import get_learning_authority
    from core.learning.teaching import TeachingPass
    from core.learning.teaching_sources import LessonSource
    from core.memory import get_memory_agent
    agent = await get_memory_agent()
    if fresh:
        say_line("== A. The lessons, on the emptied sandbox ==")
        for path in LESSONS:
            source = LessonSource(str(path))
            lesson = list(source.records())
            report = await TeachingPass(source, domain=DOMAIN, sample=False).run(get_learning_authority())
            check(f"{path.name} is learned, none refused",
                  report.patterns.get("refused") == 0 and report.patterns.get("total") == len(lesson),
                  f"{report.patterns}")
    view = await agent.language_view()
    say_line("== A. K's words from WordNet" + ("" if fresh else ", on the sandbox as it stands") + " ==")
    check("the lessons are held already", len(view) > 0, f"{len(view)} constructions and links in the view")
    source = GateSource(set(PROBE_WORDS), sample=0)
    if listen_only:
        unheld = sorted(w for w in PROBE_WORDS if not view.lexicals_with_words((w,), loose=True))
        check("K's words are held already", not unheld, f"not held: {unheld}" if unheld else "")
        await _listener_bar(source, None)
        return await _finish(main_before)
    harvest = list(source.records())
    say_line(f"    taught from WordNet: {len(harvest)} records about K's {len(PROBE_WORDS)} words, their senses "
             f"({len(source.apart)} named apart) and the kinds above them")
    wrong = said_wrongly(harvest)
    check("every fact is said as its words are used, before anything is taught", not wrong,
          f"{len(wrong)} wrong: {wrong[:4]}" if wrong else "")
    if wrong:
        say_line("    NOTHING FROM WORDNET IS TAUGHT: what would be said of it is wrong English, and would be learned")
        return await _finish(main_before)
    started = time.time()
    since = datetime.now(timezone.utc)
    built_from = frame_words()
    report = await TeachingPass(source, domain=DOMAIN, sample=False).run(get_learning_authority())
    say_line(f"    taught in {time.time() - started:.0f} s")
    for line in report.lines():
        say_line(f"    {line}")
    check("no pair said is refused", report.patterns.get("refused") == 0, f"{report.patterns}")
    # WHAT TEACHING LEFT HELD, CHECKED TOO. Saying first shows what will be taught; it cannot show what the learner
    # makes of it: a frame built around a fact's word.
    odd = frames_wrongly(built_from)
    check("no frame made while it was taught holds a fact's word", not odd, f"{len(odd)}: {odd[:4]}" if odd else "")
    guarded, other = await refused_facts(db, since, DOMAIN)
    EV.metric("facts refused: about a word that names nothing", guarded)
    check("no fact is refused but about a word the lessons use only to build sentences", not other,
          f"{len(other)} refused otherwise: {other[:4]}; {len(guarded)} about such words: "
          f"{[g.split(' :: ')[0] for g in guarded]}")
    await _listener_bar(source, report)
    return await _finish(main_before)


async def _finish(main_before: dict) -> int:
    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          main_store_change(main_before, main_after))

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SENSE-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


async def _listener_bar(source, report) -> None:
    from core.semantics import derived_reader as dr
    say_line("\n== K. The listener, against what an LLM takes without thinking ==")
    names = source.wordnet._sense_names()
    from nltk.corpus import wordnet as wn
    from core.main import get_system
    coord = get_system().autonomous_coordinator
    right, shown = 0, []
    for number, (before_it, sentence, word, sense, why) in enumerate(LISTENER):
        conversation = coord.conversation(f"SENSE-01-{SEED}-{number}")
        for said in before_it:
            await conversation._listen(said)
        await conversation._listen(sentence)
        meaning = conversation._meaning(sentence)
        wanted = names.get(wn.synset(sense), "")
        taken = sorted({t for f in dr.listening_facts(meaning) for t in f.terms()}) if meaning is not None else None
        ok = taken is not None and wanted in taken
        right += ok
        say_line(f"    {'ok ' if ok else 'BAD'} {' '.join(before_it)} {sentence!r}: {word!r} wanted {wanted!r} "
                 f"({why}); taken {meaning.canonical() if meaning is not None else None}")
    check("each sentence is taken in the sense an LLM takes it in", right == len(LISTENER), f"{right}/{len(LISTENER)}")
    EV.metric("listener against an LLM's taking", f"{right}/{len(LISTENER)}")
    heard_right = 0
    for ways, wanted, why in ALIKE:
        got = await dr.heard_which(list(ways))
        heard_right += got == wanted
        say_line(f"    {'ok ' if got == wanted else 'BAD'} heard as {list(ways)} -> {got!r} (wanted {wanted!r}, {why})")
    check("words that sound alike are heard the way that makes sense", heard_right == len(ALIKE),
          f"{heard_right}/{len(ALIKE)}")
    if report is not None:
        say_line(f"    word usage taught: {report.usage}")


if __name__ == "__main__":
    listen_only = "--listen-only" in sys.argv[1:]
    k_only = "--k-only" in sys.argv[1:] or listen_only
    fresh = "--fresh" in sys.argv[1:] and not listen_only
    if not k_only or fresh:
        reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")],
                               capture_output=True, text=True)
        print(reset.stdout.strip() or reset.stderr.strip())
        if reset.returncode != 0:
            sys.exit("the sandbox could not be emptied; not running")
    sys.exit(asyncio.run(main(k_only, fresh, listen_only)))
