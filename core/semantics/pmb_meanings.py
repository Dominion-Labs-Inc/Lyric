"""The Parallel Meaning Bank's meanings said in Lyric's meaning language.

THE PARALLEL MEANING BANK (University of Groningen, https://pmb.let.rug.nl; its annotations under the Open Data
Commons Attribution License, ODC-BY 1.0, its texts under their own sources' licences, each noted in the document's
`en.met`) gives English sentences with their whole meaning: every concept a WordNet sense, every participant a
VerbNet role, tense, negation, names, the speaker and the hearer, what a question asks, and which word a pronoun
stands for. 12,053 English documents are checked by hand (gold), 147,445 partly (silver). Lyric's composer learned
what sentences mean from 3,052 lesson sentences, shaped for frames, and read real English to little
(`logs/sense_cap/compose_holes.py`, 2026-10-20): this is English as it is written, with what it means.

A meaning is written in sequence box notation (`en.drs.sbn`): one line for each concept, its roles pointing at other
lines by how far up or down they are (`Agent -1`), constants (`now`, `speaker`, `hearer`, a name, a number, `?` for
what a question asks), and lines opening a box (`NEGATION <1`: what follows is not so). A pointer counts concept
lines only. Each line's comment holds the words it stands for ("the flea market").

SAID AS THE LESSONS SAY IT, so the composer learns one way to say a thing (`docs/TEACHING.md`): a thing "the"
names is known (`given`); a name is itself (`tom`), and "Tom is a boy." `isa(tom, boy)`; a happening is its kind with
who did it (`done_by`), to what (`done_to`), with what (`done_with`), for whom (`done_for`), to whom (`received_by`),
where it went (`moves_to`, `moves_from`, `moves_through`); a present happening has no time said, a past one is before
now (`precedes ?now`), a coming one after (`follows ?now`); a quality is `has_property`, a past state is a state
before now; "of" between two things, which no link kind names, is held as its word (`relation_types.worded`).

WHAT IS NOT YET SAID IS NAMED, never guessed: a sentence holding any of it is said as nothing (`Said.gaps`), so the
composer is never taught a meaning that is not the sentence's. Possibility and necessity ("can", "may", "must") wait
on the meaning language's grammar terms (`docs/research/MEANING_COVERAGE.md` §6); a condition, an alternative, a
proposition another clause holds, a degree, a rate, a comparison of amounts, and the roles still to map are gaps.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

from core.semantics.derived_reader import Meaning, MeaningFact
from core.semantics.relation_types import worded

#: A concept line's sense: `movie.n.01`.
_SENSE = re.compile(r"^(?P<lemma>.+)\.(?P<part>[nvars])\.(?P<number>\d+)$")
#: A pointer to another concept line, or to another box.
_POINTER = re.compile(r"^[+-]\d+$")
_BOX_POINTER = re.compile(r"^[<>]\d+$")
#: The colour codes some comments are written with.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
#: The words that make a thing one both know, as "the" does.
KNOWN = frozenset({"the", "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their"})

#: A happening's roles, and the link each makes from the happening to what fills it.
HAPPENING_ROLES = {
    "Agent": "done_by", "Experiencer": "done_by", "Co-Agent": "done_by", "Causer": "done_by", "Creator": "done_by",
    "Consumer": "done_by", "Pivot": "done_by",
    "Patient": "done_to", "Theme": "done_to", "Stimulus": "done_to", "Co-Patient": "done_to", "Result": "done_to",
    "Product": "done_to", "Co-Theme": "done_to", "Asset": "done_with",
    "Recipient": "received_by", "Beneficiary": "done_for", "Instrument": "done_with", "Location": "located_in",
    "Destination": "moves_to", "Source": "moves_from", "Path": "moves_through", "Goal": "has_purpose",
    "Topic": "about", "Duration": "lasts_for",
}
#: The roles naming who does a happening: where none is said, its Theme does it.
DOERS = frozenset({"Agent", "Experiencer", "Co-Agent", "Causer", "Creator", "Consumer", "Pivot"})
#: A thing's roles, and the link each makes from the thing to what fills it.
THING_ROLES = {
    "PartOf": "part_of", "Part": "has_part", "MadeOf": "made_of", "Material": "made_of", "Owner": "owned_by",
    "User": "owned_by", "Location": "located_in", "SubOf": "member_of", "Sub": "has_member", "Topic": "about",
    "Source": "comes_from",
}
#: The roles naming who or what has a quality ("Mary is arrogant", "I am afraid", "a red ball").
HOLDERS = frozenset({"AttributeOf", "Experiencer", "Theme", "Bearer", "Pivot", "Patient", "ColourOf"})
#: Kinds standing for a thing and nothing more ("he", "it", "someone"): what the words name, never a kind of its own.
BARE = frozenset({"entity.n.01", "person.n.01", "male.n.02", "female.n.02", "thing.n.12", "object.n.01"})
#: The box operators whose clauses each hold as told ("but", "because", "and").
TOLD_TOGETHER = frozenset({"CONTRAST", "CONJUNCTION", "EXPLANATION", "CONSEQUENCE", "ELABORATION", "COMMENTARY",
                           "BACKGROUND", "RESULT"})


@dataclass(frozen=True)
class Concept:
    """One concept line: its sense, its roles (role, what fills it: a pointer, a constant), the words it stands for,
    and the box it is in."""
    sense: str
    roles: Tuple[Tuple[str, str], ...]
    words: str
    box: int


@dataclass(frozen=True)
class Document:
    """One document: its id (`p50/d0779`), its text, its concepts, and its boxes (operator, the box it points at)."""
    id: str
    text: str
    concepts: Tuple[Concept, ...]
    boxes: Tuple[Tuple[str, int], ...]


def read_document(folder: Path, language: str = "en") -> Optional[Document]:
    """A document as its folder holds it (`<language>.raw`, `<language>.drs.sbn`); None where either is missing."""
    raw, sbn = folder / f"{language}.raw", folder / f"{language}.drs.sbn"
    if not raw.exists() or not sbn.exists():
        return None
    text = raw.read_text(encoding="utf-8").strip()
    concepts: List[Concept] = []
    boxes: List[Tuple[str, int]] = [("", 0)]
    for line in sbn.read_text(encoding="utf-8").splitlines():
        if line.startswith("%%%") or not line.strip():
            continue
        body, _, comment = line.partition("%")
        comment = _ANSI.sub("", comment)
        words = re.sub(r"\[\d+-\d+\]", "", comment).strip()
        parts = body.split()
        if not parts:
            continue
        if _SENSE.match(parts[0]):
            rest = parts[1:]
            roles = tuple((rest[k], rest[k + 1]) for k in range(0, len(rest) - 1, 2))
            concepts.append(Concept(parts[0], roles, words, len(boxes) - 1))
        elif len(parts) >= 2 and _BOX_POINTER.match(parts[1]):
            # A box line opens a new box, related to the box its pointer counts back (or on) from the new one.
            opened = len(boxes)
            boxes.append((parts[0], opened - int(parts[1][1:]) if parts[1][0] == "<" else opened + int(parts[1][1:])))
        else:
            # A line neither a concept nor a box: a name or constant the notation spells otherwise. Kept as a gap.
            concepts.append(Concept("?" + parts[0], tuple(), words, len(boxes) - 1))
    parent = folder.parent
    return Document(f"{parent.name}/{folder.name}", text, tuple(concepts), tuple(boxes))


def documents(root: Path, language: str = "en") -> Iterator[Document]:
    """Every document under `root` (`data/en/gold`), in order."""
    for sbn in sorted(root.rglob(f"{language}.drs.sbn")):
        document = read_document(sbn.parent, language)
        if document is not None:
            yield document


def split_ids(path: Path) -> List[str]:
    """The document ids a split file lists (`split/en/train/gold.sbn`: an id line, the text, the meaning)."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if re.match(r"^p\d+/d\d+$", line)]


class Said(NamedTuple):
    """What a document means in Lyric's meaning language; None, with the gaps that keep it from being said."""
    meaning: Optional[Meaning]
    gaps: Tuple[str, ...]


def _date(said: Mapping[str, str]) -> Optional[str]:
    """A time a line names, written as the reader writes it (`literals.classify_literal`): a year (1990), a day of a
    month (`--10-06`), a clock time (`7:30 p.m.`); None where it names none or names it otherwise."""
    from core.semantics.literals import classify_literal
    year, month, day, clock = (said.get(k) for k in ("YearOfCentury", "MonthOfYear", "DayOfMonth", "ClockTime"))
    if clock and not (year or month or day):
        literal = classify_literal(clock)
        return literal.canonical if literal is not None and literal.kind == "time" else None
    if year and not (month or day or clock):
        return year if year.isdigit() else None
    if month and day and not (year or clock) and month.isdigit() and day.isdigit():
        return f"--{int(month):02d}-{int(day):02d}"
    return None


def _number(text: str) -> Optional[str]:
    try:
        value = float(text)
    except ValueError:
        return None
    return str(int(value)) if value == int(value) else str(value)


def meaning_of(document: Document, name_of: Callable[[str], Optional[str]]) -> Said:
    """What a document means, said in Lyric's meaning language (`Said`). `name_of(sense)` is the concept Lyric holds a
    WordNet sense under (`WordNetSource._sense_names`), or None where Lyric holds none."""
    gaps: List[str] = []
    concepts = document.concepts
    n = len(concepts)
    boxes = document.boxes
    for operator, _ in boxes[1:]:
        if operator == "NEGATION" or operator in TOLD_TOGETHER:
            continue
        if operator == "CONTINUATION":
            continue
        gaps.append(f"box:{operator}")

    def target(at: int, pointer: str) -> Optional[int]:
        k = at + int(pointer)
        return k if 0 <= k < n else None

    # ── what each concept stands for ──
    term: Dict[int, str] = {}
    asked: Set[str] = set()
    same: Dict[int, int] = {}
    facts: List[MeaningFact] = []
    for k, c in enumerate(concepts):
        if c.sense.startswith("?"):
            gaps.append("line:unread")
            continue
        for role, value in c.roles:
            if role == "Name" and value == "?":
                term[k] = f"?v{k}"
                asked.add(term[k])
            elif role == "Name" and value.startswith('"'):
                term[k] = value.strip('"').lower()
            elif role == "EQU" and value == "speaker":
                term[k] = "?speaker"
            elif role == "EQU" and value == "hearer":
                term[k] = "?listener"
            elif role == "EQU" and value == "?":
                term[k] = f"?v{k}"
                asked.add(term[k])
            elif role in ("ANA", "EQU") and _POINTER.match(value):
                if target(k, value) is not None:
                    same[k] = target(k, value)
            elif role == "EQU" and _number(value) is not None:
                term[k] = _number(value)
        term.setdefault(k, f"?v{k}")

    def root(k: int) -> int:
        seen = set()
        while k in same and k not in seen:
            seen.add(k)
            k = same[k]
        return k

    def term_of(k: int) -> str:
        return term[root(k)]

    # ── kinds, and the time each happening and state is at ──
    def part(c: Concept) -> str:
        m = _SENSE.match(c.sense)
        return m.group("part") if m else ""

    times: Dict[int, str] = {}
    dates: Dict[int, str] = {}
    for k, c in enumerate(concepts):
        if c.sense == "time.n.08":
            said = dict(c.roles)
            for role, value in c.roles:
                if role == "EQU" and value == "now":
                    times[k] = "present"
                elif role == "TPR" and value == "now":
                    times[k] = "past"
                elif role == "TSU" and value == "now":
                    times[k] = "future"
                elif role in ("YearOfCentury", "ClockTime", "MonthOfYear", "DayOfMonth"):
                    continue
                else:
                    gaps.append(f"time:{role}")
            day = _date(said)
            if day is not None:
                dates[k] = day
            elif any(r in said for r in ("YearOfCentury", "ClockTime", "MonthOfYear", "DayOfMonth")):
                gaps.append("time:date")
    # A NEGATION INSIDE A NEGATION IS "EVERY" ("Everybody loves Tom.": nobody who does not), which the meaning
    # language says only of kinds: a gap, never read as not so.
    def negations(b: int) -> int:
        count, seen = 0, set()
        while b and b not in seen:
            seen.add(b)
            operator, up = boxes[b]
            count += operator == "NEGATION"
            b = up if 0 <= up < len(boxes) else 0
        return count
    for b in range(1, len(boxes)):
        if negations(b) > 1:
            gaps.append("box:universal")
            break
    negated = {k for k, c in enumerate(concepts) if negations(c.box) == 1}

    def add(relation: str, subject: str, obj: str, k: int, given: bool = False) -> None:
        # WHAT A NEGATED CLAUSE PREDICATES IS NOT SO, what its things are and whose they are stays so: "I have
        # never seen a giraffe" is no seeing, and a giraffe is a giraffe; "Tom doesn't know Mary's phone number" is
        # no knowing, and the number is still Mary's. A happening's or a quality's facts are what it predicates.
        holds = k not in negated or part(concepts[k]) == "n"
        try:
            fact = MeaningFact(relation, subject, obj, holds, given=given)
        except ValueError:
            gaps.append(f"fact:{relation}")
            return
        if fact not in facts:
            facts.append(fact)

    def tense(k: int, subject: str) -> None:
        for role, value in concepts[k].roles:
            if role == "Time" and _POINTER.match(value):
                t = target(k, value)
                when = times.get(t) if t is not None else None
                if when == "past":
                    add("precedes", subject, "?now", k)
                elif when == "future":
                    add("follows", subject, "?now", k)
                elif when == "present" and concepts[k].words.split()[-1:] and \
                        concepts[k].words.split()[-1].rstrip(".,!?").endswith("ing"):
                    # "The dog is running.": during now; "The dog barks." says no time (the lessons).
                    add("during", subject, "?now", k)
                if t is not None and t in dates:
                    add("during", subject, dates[t], k)

    for k, c in enumerate(concepts):
        if c.sense.startswith("?") or c.sense == "time.n.08":
            continue
        p = part(c)
        name = name_of(c.sense)
        here = term_of(k)
        if p == "n":
            if c.sense in BARE or root(k) != k or here.startswith("?speaker") or here == "?listener" \
                    or not here.startswith("?"):
                continue
            if not name:
                gaps.append(f"sense:{c.sense}")
                continue
            first = c.words.split()[0].lower() if c.words else ""
            add("instance_of", here, name, k, given=first in KNOWN and here not in asked)
        elif p == "v":
            lemma = _SENSE.match(c.sense).group("lemma")
            if lemma in ("be", "have"):
                continue
            if not name:
                gaps.append(f"sense:{c.sense}")
                continue
            add("instance_of", here, name, k)
            tense(k, here)
        elif p in ("a", "s", "r"):
            if not name:
                gaps.append(f"sense:{c.sense}")
                continue

    # ── the roles ──
    for k, c in enumerate(concepts):
        if c.sense.startswith("?") or c.sense == "time.n.08":
            continue
        p = part(c)
        here = term_of(k)
        lemma = _SENSE.match(c.sense).group("lemma")
        roles = dict()
        for role, value in c.roles:
            roles.setdefault(role, value)
        for role, value in c.roles:
            if role in ("Name", "ANA", "Time") or role == "EQU":
                continue
            other = target(k, value) if _POINTER.match(value) else None
            if role == "Quantity":
                count = _number(value)
                if value == "?":
                    asked_count = f"?q{k}"
                    asked.add(asked_count)
                    add("has_count", here, asked_count, k)
                elif count is not None:
                    add("has_count", here, count, k)
                elif other is not None and _number(term_of(other) or "") is not None:
                    add("has_count", here, term_of(other), k)
                else:
                    gaps.append(f"quantity:{value}")
                continue
            if role == "Sub" and value == "speaker":
                add("has_member", here, "?speaker", k)
                continue
            if other is None:
                gaps.append(f"role:{role}:{'const' if not _BOX_POINTER.match(value) else 'box'}")
                continue
            there = term_of(other)
            if p == "v":
                if lemma == "be":
                    if role == "Co-Theme" and "Theme" in roles and _POINTER.match(roles["Theme"]):
                        subject = target(k, roles["Theme"])
                        kind = concepts[other]
                        kind_name = name_of(kind.sense) if part(kind) == "n" and kind.sense not in BARE else None
                        if subject is not None and kind_name and term_of(other).startswith("?") \
                                and not concepts[other].words.split()[:1] == ["the"]:
                            who = term_of(subject)
                            add("isa" if not who.startswith("?") else "instance_of", who, kind_name, k)
                        elif subject is not None:
                            same[root(other)] = root(subject)
                    elif role in ("Location", "Source") and "Theme" in roles and _POINTER.match(roles["Theme"]):
                        subject = target(k, roles["Theme"])
                        if subject is not None:
                            add("located_in" if role == "Location" else "comes_from", term_of(subject), there, k)
                    elif role not in ("Theme", "Co-Theme"):
                        gaps.append(f"be:{role}")
                    continue
                if lemma == "have":
                    if role == "Theme" and "Pivot" in roles and _POINTER.match(roles["Pivot"]):
                        owner = target(k, roles["Pivot"])
                        if owner is not None:
                            add("owns", term_of(owner), there, k)
                    elif role != "Pivot":
                        gaps.append(f"have:{role}")
                    continue
                if role == "Manner":
                    if part(concepts[other]) == "n":
                        add("has_property", here, there, k)
                    else:
                        quality = name_of(concepts[other].sense)
                        if quality:
                            add("has_property", here, quality, k)
                        else:
                            gaps.append("manner:sense")
                    continue
                if role == "Theme" and not any(r in roles for r in DOERS):
                    # THE ONE WHO GOES, COMES, ARRIVES: a happening's only participant, its Theme, does it ("Let's
                    # go.": done by us), as "The dog barks." is done by the dog.
                    add("done_by", here, there, k)
                    continue
                if part(concepts[other]) in ("a", "s", "r"):
                    # A ROLE FILLED BY A QUALITY ("dyed my hair blonde": the hair comes to be blond) is said by the
                    # quality's own line of what has it; the quality is no thing the happening is done to.
                    continue
                link = HAPPENING_ROLES.get(role)
                if link is None:
                    gaps.append(f"role:{role}")
                    continue
                add(link, here, there, k)
            elif p in ("a", "s"):
                if role in HOLDERS:
                    quality = name_of(c.sense)
                    if not quality:
                        continue
                    when = next((times.get(target(k, v)) for r, v in c.roles if r == "Time" and _POINTER.match(v)),
                                None)
                    degree = next((target(k, v) for r, v in c.roles if r == "Degree" and _POINTER.match(v)), None)
                    if degree is not None:
                        how = name_of(concepts[degree].sense)
                        if not how or how in ("more", "most", "less", "least"):
                            gaps.append("quality:comparison")
                            continue
                        # "Mary is somewhat arrogant.": a degree of arrogance, that is somewhat, Mary's
                        # (`derived_reader._role_of_term`: a degree's own word is what the degree has).
                        held = f"?d{k}"
                        add("has_degree", there, held, k)
                        add("instance_of", held, quality, k)
                        add("has_property", held, how, k)
                    elif when == "past":
                        state = f"?s{k}"
                        add("instance_of", state, quality, k)
                        add("precedes", state, "?now", k)
                        add("state_of", state, there, k)
                    else:
                        add("has_property", there, quality, k)
                elif role == "Stimulus":
                    holder = next((target(k, v) for r, v in c.roles if r in HOLDERS and _POINTER.match(v)), None)
                    if holder is not None:
                        add("about", term_of(holder), there, k)
                elif role in ("Degree",):
                    continue
                else:
                    gaps.append(f"quality:{role}")
            elif p == "n":
                if role == "Of":
                    add(worded("of"), here, there, k)
                elif role in ("Role",):
                    same[root(other)] = root(k)
                elif role in ("Colour", "Attribute"):
                    quality = name_of(concepts[other].sense)
                    if quality:
                        add("has_property", here, quality, k)
                elif role == "InstanceOf":
                    kind = name_of(concepts[other].sense)
                    if kind:
                        add("isa", here, kind, k)
                elif role == "Creator":
                    add("creates", there, here, k)
                elif role in THING_ROLES:
                    add(THING_ROLES[role], here, there, k)
                else:
                    gaps.append(f"thing:{role}")
            else:
                gaps.append(f"{p}:{role}")
    if gaps:
        return Said(None, tuple(sorted(set(gaps))))
    # Terms renamed once coreference is known: a pronoun is what it stands for.
    names = {term[k]: term_of(k) for k in range(n) if k in term and term[k] != term_of(k)}
    facts = [MeaningFact(f.relation, names.get(f.subject, f.subject), names.get(f.obj, f.obj), f.positive,
                         f.condition, f.alternative, f.unasserted, f.given and names.get(f.subject, f.subject)
                         .startswith("?")) for f in facts]
    facts = list(dict.fromkeys(facts))
    act = "ask" if document.text.rstrip().endswith("?") else "tell"
    asked_now = tuple(sorted({names.get(a, a) for a in asked if any(names.get(a, a) in f.terms() for f in facts)}))
    if not facts:
        return Said(None, ("nothing said",))
    try:
        return Said(Meaning(act, tuple(facts), asked_now if act == "ask" else ()), ())
    except ValueError as error:
        return Said(None, (f"meaning:{str(error)[:60]}",))


def gap_counts(saids: Sequence[Said]) -> Counter:
    """How many documents each gap keeps from being said."""
    counted: Counter = Counter()
    for said in saids:
        for gap in said.gaps:
            counted[gap.split(":")[0] + ":" + gap.split(":")[1] if ":" in gap else gap] += 1
    return counted
