#!/usr/bin/env python3
"""The one door knowledge comes through.

A sentence that has been READ is not yet knowledge. Something has to admit it,
and until now nothing did: `read()` produced an atom like `cup_in_cabinet`,
handed it to its caller, and the caller dropped it. A thirty-minute teaching run
wrote 1,326 rows to a JSON file while the concept store, the memory system and
the evidence log recorded nothing -- measured directly as 0 concepts, 0
memories, 0 evidence. The substrate was never taught anything.

    THE READER INTERPRETS. THE INGRESS ADMITS. REASONING CONSUMES.

Those are three jobs and they were collapsed into one. This is the middle one,
and it is the only place a proposition enters the system. It admits each
proposition ONCE, with provenance, and propagates it to every store that has a
stake in it:

    concepts   the terms become things that exist, with the relation between
               them -- via ConceptIngestionService, which declares itself the
               only writer of unified.concepts, so this does not write there
    aliases    the surface word binds to the concept it denotes, which is what
               makes a word mean something rather than merely parse
    evidence   the sentence is the root: why any of it is believed
    memory     the episode, so it can be recalled and asked about later

WHAT THIS DOES NOT DO. It does not decide whether the proposition is TRUE. A
teacher's sentence is admitted as an observation with the teacher as its source
and one evidence root; the epistemic status the concept store assigns follows
from how much independent evidence accumulates, not from who said it.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


#: Minimum evidence quality for a proposition to be ADMITTED as knowledge. Below
#: this, the gate refuses (true absence) instead of minting a weakly-held belief.
#: A conservative default floor — it stops clearly-unsupported input (coin-flip or
#: worse) from ever touching the concept graph or belief store; a deployment that
#: needs a stricter "never contaminate authoritative state" posture raises it
#: toward the point where OOD-admission approaches zero (at the cost of rejecting
#: more genuine-but-low-confidence input, the cheaper error).
MIN_ADMIT_QUALITY: float = 0.5


@dataclass
class Provenance:
    """Where a proposition came from. Required -- there is no anonymous entry."""

    producer: str                      # "qwen_teacher", "observation", "user"
    source_id: str                     # the sentence, file, or episode id
    source_type: str = "USER_SUPPLIED"  # an EvidenceSourceType member name
    derived_from: Tuple[str, ...] = ()


@dataclass
class Admission:
    """What admitting one proposition actually did. Every field is a count."""

    proposition: str
    surface: str
    admitted: bool = False
    already_present: bool = False
    concepts_created: List[str] = field(default_factory=list)
    concepts_reinforced: List[str] = field(default_factory=list)
    aliases_bound: int = 0
    memories: int = 0
    #: The id of the SEMANTIC memory this admission created (via `_remember`),
    #: or None if nothing was retained. Surfaced so a later turn can point back
    #: at the exact memory this interaction made -- which is what lets
    #: conversational feedback ("no, that's wrong") FLAG the memory the claim
    #: already produced rather than mint a second, parallel record of it.
    memory_id: Optional[str] = None
    evidence_id: str = ""
    polarity: str = "positive"
    #: Set when this admission puts the store in conflict with itself. Surfaced,
    #: never silently resolved -- picking a winner here would hide the fact that
    #: two sources disagree.
    contradicts: Optional[Dict[str, Any]] = None
    refusals: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        conflict = "  CONTRADICTS PRIOR CLAIM" if self.contradicts else ""
        return (f"{self.proposition}[{self.polarity}]: "
                f"+{len(self.concepts_created)} concepts, "
                f"~{len(self.concepts_reinforced)} reinforced, "
                f"{self.aliases_bound} aliases, {self.memories} memories{conflict}")


#: Words that never name a thing. A concept called `you` or `the` is not a
#: concept; it is a reading that went wrong and was written down anyway.
NEVER_A_TERM = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "not", "no", "and", "or", "but", "that", "this", "these", "those",
    "it", "its", "you", "your", "i", "me", "my", "we", "us", "our",
    "he", "she", "they", "them", "their", "him", "her", "who", "which",
    "what", "when", "where", "how", "why", "of", "to", "for", "with",
    "as", "at", "by", "from", "in", "on",
})

#: Words a term may contain. Past this it is a clause, not a name: the store
#: holds things, and `which_lines_belong_to_which_block` is a sentence someone
#: stapled together with underscores.
MAX_TERM_WORDS = 4

#: Words a relation may contain. `is beside`, `is a kind of` -- past this it is
#: a clause the reader failed to segment.
MAX_RELATION_WORDS = 4


def admissible(term: str) -> Tuple[bool, str]:
    """Whether a term may name a concept, and why not when it may not.

    THE DOOR CHECKS, NOT THE CALLER. Every caller had its own idea of what was
    worth writing down, and the one that guessed hardest wrote the most. This
    is the shape test, in the one place everything passes through, so a bad
    reading is refused no matter which path produced it.
    """
    cleaned = term.strip().strip(".,;:!?").lower()
    if not cleaned:
        return False, "empty"
    # A NUMBER OR A DATE NAMES A THING -- a quantity, a point in time. The store
    # holds it as a typed literal, so a recognised numeral or date is admitted
    # here rather than refused as "a bare number that names no thing". A run of
    # digits that is NOT a well-formed literal still falls through to refusal.
    from core.semantics.literals import classify_literal
    if classify_literal(cleaned) is not None:
        return True, ""
    words = [w for w in cleaned.replace("_", " ").split() if w]
    if not words:
        return False, "empty"
    if len(words) > MAX_TERM_WORDS:
        return False, f"{len(words)} words is a clause, not a name"
    # WHAT NAMES NOTHING IS WHAT ENGLISH TAUGHT BUILDS SENTENCES WITH: a word the
    # substrate holds only as part of its sentence forms, and that no taught
    # meaning uses as a concept's name ("the", "is", "my"). Nothing is listed here.
    from core.semantics.derived_reader import live_view
    view = live_view()
    if all(view.names_nothing(w) for w in words):
        return False, f"{cleaned!r} is made only of words that name nothing"
    if any(character.isdigit() for character in cleaned) and len(words) == 1 \
            and cleaned.isdigit():
        return False, "a bare number names no thing"
    return True, ""


def admissible_relation(relation: str) -> Tuple[bool, str]:
    """Whether a relation may be recorded.

    A RELATION IS NOT A TERM AND THE TESTS ARE DIFFERENT. `is`, `in`, `on`, `of`
    are exactly what relations look like -- `robin is a bird` is the commonest
    shape there is -- while the same words never name a thing. Running terms'
    test over relations refused every copula sentence, which is most of them.

    What disqualifies a relation is being a clause: `a function count_o` is a
    fragment of a sentence nobody managed to read.
    """
    cleaned = " ".join(str(relation).strip().strip(".,;:!?").lower().replace("_", " ").split())
    if not cleaned:
        return False, "empty"
    words = cleaned.split()
    if len(words) > MAX_RELATION_WORDS:
        return False, f"{len(words)} words is a clause, not a relation"
    if any(w in ("a", "an", "the") for w in words):
        return False, f"{cleaned!r} carries a determiner, so it is a phrase that was cut mid-term"
    return True, ""


def normalize_term(term: str) -> str:
    """The canonical form of a term, so it names the same thing every time.

    `the ladder` and `ladder` are one thing. Admitting both leaves two concepts
    that never corroborate each other, and a relation pointing at
    `target_surface = 'the ladder'` never resolves to the `ladder` concept --
    which is how an edge ends up dangling forever.

    DELEGATED, BECAUSE THIS DOOR WAS THE ONE PLACE THE INVARIANT HAD TO HOLD.
    `lexical_normalization` states it: one surface form has one canonical
    interpretation across every cognitive path, written after `socrates_man`
    and `socrates_men` split and modus ponens had nothing to fire on. This had
    its own implementation, which stripped determiners and NEVER SINGULARISED
    -- so `bird` and `birds` entered as two concepts at the single door all
    knowledge passes through, which is exactly the split that module exists to
    prevent.

    `canonical_term` is the grammatical core (determiners, plurals, case,
    punctuation). It deliberately does NOT apply `canonical_label`'s
    document heuristics, which would reduce `nervous system` to `nervous` and
    `lithium battery` to `lithium` -- correct for a label scraped from a paper,
    destructive for a term read out of a sentence.
    """
    from core.semantics.lexical_normalization import canonical_term

    return canonical_term(term)


def shape_proposition(subject: Any, relation: Any, obj: Any
                      ) -> Tuple[str, str, Optional[str], Optional[str]]:
    """The door's SHAPE test for one proposition: its canonical parts, and why
    it is refused (None when it is not).

    ONE TEST, EVERY WAY IN. A fact, each clause of a conditional, and a user's
    scoped telling all pass through it. The scoped path used to skip it, so a
    user's context held what this door refuses (a subject that names nothing,
    a clause for a relation) with `admitted=True`, and stored raw terms --
    `isoprobe wren isa an isoprobe bird` -- that the graph overlay, which walks
    canonical concept names, could never reach (measured 2026-09-26,
    SYSTEM-CONVERSATION-01)."""
    subject = normalize_term(str(subject or ""))
    obj = normalize_term(str(obj)) if obj else None
    relation = " ".join(str(relation or "").replace("_", " ").split())
    # A PROPOSITION HAS A SUBJECT. An empty subject once slipped through the
    # loop's skip for a unary proposition (no object) and was admitted -- a
    # relation about nothing, with only its object entering the graph
    # (measured 2026-09-26, SYSTEM-LEARNING-01).
    if not subject:
        return subject, relation, obj, \
            "subject is empty: a proposition about nothing is not admitted"
    for name, term in (("subject", subject), ("object", obj)):
        if not term:
            continue
        allowed, why = admissible(term)
        if not allowed:
            return subject, relation, obj, f"{name} {term!r} not admitted: {why}"
    allowed, why = admissible_relation(relation)
    if not allowed:
        return subject, relation, obj, f"relation {relation!r} not admitted: {why}"
    return subject, relation, obj, None


def _parse(proposition: str) -> Optional[Tuple[str, str, Optional[str], bool]]:
    """`cup_in_cabinet` -> (cup, in, cabinet, positive). `~x_hot` -> negative.

    The atom is the reader's output and its shape is the reader's contract, so
    this reads it rather than re-deriving anything from the sentence.
    """
    negated = proposition.startswith("~")
    body = proposition.lstrip("~")
    parts = [p for p in body.split("_") if p]
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        return parts[0], "is", parts[1], not negated
    return parts[0], "_".join(parts[1:-1]), parts[-1], not negated


class CognitiveIngress:
    """Admits propositions. One instance, one door."""

    def __init__(self, db_manager=None):
        self._db = db_manager
        self._service = None
        self._seen: set = set()

    async def _ingestion(self):
        if self._service is None:
            from core.database import get_database_manager
            from core.domain.concept_ingestion import ConceptIngestionService

            self._service = ConceptIngestionService(self._db or get_database_manager())
        return self._service

    async def admit(self, proposition: str, surface: str,
                    provenance: Provenance,
                    word_class_of=None) -> Admission:
        """Admit one read proposition. Idempotent per (proposition, source)."""
        from core.domain.concept_ingestion import EvidenceEnvelope, EvidenceSourceType

        result = Admission(proposition=proposition, surface=surface)

        key = hashlib.sha256(
            f"{proposition}|{provenance.source_id}".encode()).hexdigest()[:16]
        if key in self._seen:
            # ADMITTED ONCE. A sentence read twice is one fact, not two, and
            # counting it twice would inflate the evidence behind it.
            result.already_present = True
            return result

        try:
            source_type = EvidenceSourceType[provenance.source_type]
        except KeyError:
            result.refusals.append(
                f"unknown evidence source {provenance.source_type!r}; "
                f"expected one of {[e.name for e in EvidenceSourceType]}")
            return result

        parsed = _parse(proposition)
        if parsed is None:
            result.refusals.append(f"proposition {proposition!r} has no relation to admit")
            return result
        subject, relation, obj, positive = parsed
        self._seen.add(key)
        result = await self._admit_parts(
            subject, relation, obj, positive, surface, provenance,
            source_type, key, result, word_class_of)
        # A REFUSAL IS NOT A PRESENCE. The key was marked seen before the gates
        # ran, so a refused proposition told again read `already_present` --
        # reported as held when it was never admitted.
        if not result.admitted and not result.already_present:
            self._seen.discard(key)
        return result

    async def admit_relation(self, subject: str, relation: str, obj: str,
                             surface: str, provenance: Provenance,
                             positive: bool = True,
                             description: str = "",
                             domain: str = "language",
                             word_class_of=None,
                             quality: float = 1.0) -> Admission:
        """Admit a proposition already split into its parts.

        The atom form (`cup_in_cabinet`) is one way to say a proposition and a
        lossy one -- a multi-word subject cannot survive it. A caller that
        already knows the seams passes them straight through rather than
        encoding them into a string for this to decode again.

        ADMISSION ALWAYS REMEMBERS. There was a `remember=False` that admitted a
        fact into the concept graph WITHOUT a recallable episode, on two stated
        grounds: that a reference taxonomy is knowledge rather than something the
        substrate was told, and that embedding tens of thousands of episodes is
        slow.

        The first is answered by `_remember` itself, which does not store an
        event -- it stores a SEMANTIC memory, for the express reason that what
        was learned "has to be findable later by MEANING ... that is the whole
        point of storing it, and the substrate's alternative to baking knowledge
        into weights". Turning it off for a whole corpus leaves that corpus
        reachable only by naming a concept exactly, never by meaning.

        The second was measured rather than argued: 12.5 facts/s with the
        episode against 18.4 without, so the full 314,856-edge taxonomy costs
        about 7.0h instead of 4.7h. Real, and not a reason to hold two grades of
        knowledge -- four of five corpus passes set it False, so most of what the
        substrate knows it could state and had no recollection of learning.

        A fact is a fact however it arrived. There is no solo teaching: admission
        touches every system, or it is a database write wearing the word
        "teaching".
        """
        from core.domain.concept_ingestion import EvidenceSourceType

        result = Admission(proposition=f"{subject}|{relation}|{obj}", surface=surface)
        try:
            source_type = EvidenceSourceType[provenance.source_type]
        except KeyError:
            result.refusals.append(f"unknown evidence source {provenance.source_type!r}")
            return result

        # SUPPORT FLOOR — insufficiently-supported input is REFUSED, not admitted as
        # a weak belief. This is the difference between representing "I don't know"
        # as ABSENCE (no concept, no belief) versus a low-posterior belief that has
        # already contaminated the concept graph. The one gate every producer funnels
        # through is the only place refusal yields true absence, because the belief
        # fan-out downstream runs only when `admitted` is True. `quality` is the
        # producer's evidence quality (a classifier's recognition confidence, a
        # source's reliability); below the floor the door does not open.
        if quality < MIN_ADMIT_QUALITY:
            result.refusals.append(
                f"insufficient support: quality {quality:.3f} < floor {MIN_ADMIT_QUALITY}")
            return result

        key = hashlib.sha256(
            f"{subject}|{relation}|{obj}|{provenance.source_id}".encode()).hexdigest()[:16]
        if key in self._seen:
            result.already_present = True
            return result
        self._seen.add(key)
        result = await self._admit_parts(
            subject, relation, obj, positive, surface, provenance,
            source_type, key, result, word_class_of, description, domain)
        # A REFUSAL IS NOT A PRESENCE. The key was marked seen before the gates
        # ran, so a refused proposition told again read `already_present` --
        # reported as held when it was never admitted.
        if not result.admitted and not result.already_present:
            self._seen.discard(key)
        return result

    #: How far up a kind chain the cycle check walks. MEASURED, not chosen: the
    #: cost knees hard once the frontier reaches the dense upper taxonomy, where
    #: everything converges on `entity`/`abstraction`.
    #:
    #:     depth  4   0.5 ms/check    9/11 known cycle-closing edges caught
    #:     depth  6   1.0 ms/check   11/11
    #:     depth 10  12.0 ms/check   11/11      (~21 min per 105k admissions)
    #:     depth 16  78.0 ms/check   11/11      (~136 min — doubles a teach run)
    #:
    #: Six catches every cycle the live store actually contains for ~2 minutes
    #: across a full curriculum pass. It is a BOUND, so a loop longer than six
    #: hops still gets through; that is stated rather than implied, and the
    #: honest reason is that a deeper walk costs more than the loops it finds.
    MAX_KIND_DEPTH = 6

    async def _would_close_a_cycle(self, relation: str, subject: str,
                                   obj: str) -> Optional[str]:
        """Does `obj` already reach `subject` by the same ALWAYS-transitive
        relation? Returns the path as text when it does, else None.

        Only ALWAYS-transitive relations are checked, and `relation_types` says
        which those are -- today that is `isa` alone, so nothing else pays for
        this. `UNION` (not `UNION ALL`) dedups the frontier, which matters: 24%
        of concepts have more than one parent, and the path count is exponential
        where the node count is not.
        """
        from core.semantics.relation_types import SPEC, classify, Transitivity
        spec = SPEC[classify(relation).relation]
        if spec.transitivity is not Transitivity.ALWAYS:
            return None
        db = self._db
        if db is None:
            from core.database import get_database_manager
            db = get_database_manager()
        if not getattr(db, "initialized", False):
            return None
        try:
            rows = await db.execute_query(
                """
                WITH RECURSIVE up(name, depth) AS (
                    SELECT $1::text, 0
                  UNION
                    SELECT r.target_surface, up.depth + 1
                    FROM up
                    JOIN unified.concepts c ON c.name = up.name
                    JOIN unified.concept_relations r
                      ON r.source_concept_id = c.concept_id
                    WHERE r.relation = $3 AND r.polarity IS DISTINCT FROM 'negative'
                      AND up.depth < $4 AND r.target_surface IS NOT NULL
                )
                SELECT depth FROM up WHERE name = $2 LIMIT 1
                """,
                (obj, subject, str(relation).strip().lower(), self.MAX_KIND_DEPTH))
        except Exception as error:
            # THE GUARD COULD NOT RUN, AND THAT IS SAID OUT LOUD. Admitting
            # anyway is the lesser harm -- refusing every edge because the store
            # hiccuped would stop teaching outright -- but an invariant nobody
            # can confirm is not an invariant, so it is never silent.
            logger.warning(
                "kind-cycle guard could not run for %r isa %r (%s); the edge is "
                "admitted UNCHECKED and the hierarchy may not be acyclic",
                subject, obj, error)
            return None
        if not rows:
            return None
        return f"{obj} -> ... -> {subject} in {rows[0]['depth']} step(s)"

    async def _admit_parts(self, subject, relation, obj, positive, surface,
                           provenance, source_type, key, result,
                           word_class_of=None, description: str = "",
                           domain: str = "language") -> Admission:
        """The one admission. Every caller funnels here."""
        from core.domain.concept_ingestion import EvidenceEnvelope

        # A negated proposition is a claim that something is NOT so, and it is
        # admitted as such -- `unified.concept_relations.polarity` carries the
        # denial. This used to be dropped to an episode because the store could
        # only represent things that hold, which meant "the mug is not in the
        # cupboard" taught the substrate nothing it could later be asked.

        subject, relation, obj, refusal = shape_proposition(subject, relation, obj)
        if refusal:
            result.refusals.append(refusal)
            return result

        # A KIND HIERARCHY MUST NOT HAVE CYCLES.
        #
        # `isa` is the one ALWAYS-transitive relation (`relation_types.SPEC`),
        # and the reasoner walks it. "X is a kind of Y" together with "Y is a
        # kind of X" says the two are the same kind, and a walker that believes
        # both makes every member of the loop an ancestor of every other.
        #
        # Measured on the live store before this: 17 cycles over 2,073 concepts
        # in `general`, the largest a single 2,039-node component. Nothing was
        # wrong with the SOURCE — WordNet is consistent at the SYNSET level
        # (`testimony.n.02 -> assertion.n.01 -> declaration.n.01`, and separately
        # `declaration.n.02 -> testimony.n.01`). The store keys concepts on the
        # WORD, so distinct senses fuse and the chain closes on itself. The
        # existing hygiene guard cannot see this: it gates on whether a SOURCE is
        # curated, and a curated source is exactly what produced these.
        #
        # So the invariant belongs here, at the one admission, on the STRUCTURE
        # rather than the provenance: the edge that would close a loop is the one
        # refused, with its reason recorded. First path wins, which is arbitrary
        # between two senses but sound, and leaves the graph walkable.
        if positive and obj:
            closes = await self._would_close_a_cycle(relation, subject, obj)
            if closes:
                result.refusals.append(
                    f"{subject!r} isa {obj!r} would close a kind cycle "
                    f"({closes}); a thing cannot be a kind of something that is "
                    f"already a kind of it")
                return result

        from core.semantics.literals import classify_literal

        terms = [t for t in (subject, obj) if t]
        concepts = []
        for term in terms:
            attributes: Dict[str, Any] = {}
            literal = classify_literal(term)
            if literal is not None:
                # A number or date is filed under its own type, carrying the
                # parsed value so a later stage can compare dates or count -- not
                # just hold the surface string.
                kind = literal.concept_type
                attributes = {"literal_type": literal.kind,
                              "literal_value": str(literal.value)}
            elif word_class_of:
                got = word_class_of(term)
                kind = {"NOUN": "entity", "ADJECTIVE": "property",
                        "VERB": "process"}.get(got or "", "entity")
            else:
                kind = "entity"
            concepts.append({
                "label": term,
                "kind": kind,
                "domains": [domain],
                "description": description or f"met in use: {surface!r}",
                "attributes": attributes,
            })
        if obj:
            concepts[0]["relationships"] = [
                [relation, obj, "positive" if positive else "negative"]]

        # IDEMPOTENT ACROSS PROCESSES AND INSTANCES, not only within one. `_seen`
        # is what THIS process admitted; the graph is what every process did. An
        # edge that this very evidence (this proposition, from this source) put
        # in the graph means it is held from this source already -- a second
        # telling is one fact, not a second witness. Without this, re-teaching a
        # held fact after a restart (or on another instance) reinforced its
        # concepts, came back `admitted`, moved its belief again and went into
        # the ledger as NEW. Checked against the EDGE, not the evidence record,
        # so a proposition whose edge has since been removed is taught again.
        if obj and await self._edge_from(f"read_{key}"):
            result.already_present = True
            result.evidence_id = f"read_{key}"
            return result

        envelope = EvidenceEnvelope(
            evidence_id=f"read_{key}",
            source_type=source_type,
            source_id=provenance.source_id,
            content=surface,
            producer=provenance.producer,
            structured_data={"concepts": concepts},
            derived_from=provenance.derived_from,
        )

        try:
            service = await self._ingestion()
            ingested = await service.ingest(envelope)
            result.evidence_id = ingested.evidence_id
            result.concepts_created = list(ingested.created)
            result.concepts_reinforced = list(ingested.reinforced)
            for name, reason in ingested.rejected:
                result.refusals.append(f"{name}: {reason}")
            for name, reason in getattr(ingested, "unreadable", ()) or ():
                result.refusals.append(f"{name} could not read the evidence: {reason}")
        except Exception as error:
            result.refusals.append(f"concept ingestion failed: {error}")
            logger.warning("ingress: concept ingestion failed for %r: %s",
                           result.proposition, error)

        from core.memory import Origin
        result.memories = await self._remember(
            result.proposition, surface, provenance, result,
            origin=Origin.own("learning"))
        result.aliases_bound = await self._bind_aliases(terms, provenance)
        result.polarity = "positive" if positive else "negative"
        result.contradicts = await self._contradiction_check(
            subject, relation, obj) if obj else None
        # ADMITTED MEANS THE KNOWLEDGE STORE TOOK IT, and nothing weaker.
        #
        # This counted a stored MEMORY as admission, which made the flag report
        # success for a claim the concept graph had refused outright: every
        # caller reads `admitted` as "it is in", and `learn_fact` gates the whole
        # fan-out (belief, lexicon, domain) on it. Measured: a derived naming
        # whose lineage did not resolve came back `admitted=True` carrying
        # "concept ingestion failed: dangling lineage ..." in `refusals`, the
        # belief moved, and `instance_predicates` — the thing the reasoner reads —
        # never saw the edge. The claim was held and unusable at the same time.
        #
        # A memory is a record of having been TOLD something, which is worth
        # keeping and is not the same as holding it: recall can hand it back,
        # the reasoner cannot walk it. So it stays counted in `memories` and no
        # longer decides this. `refusals` says why when the answer is no.
        result.admitted = bool(result.concepts_created or result.concepts_reinforced)
        return result

    async def remember_told(self, sentence: str,
                            provenance: "Provenance",
                            blamed: Optional[List[tuple]] = None, *,
                            origin: "Origin") -> "Admission":
        """Remember being told something, WITHOUT having understood it.

        TWO DIFFERENT THINGS WERE BOTH CALLED ADMITTING, and one of them was
        silently enforcing the other. Refusing to invent structure for a
        sentence the reader could not parse is right — `teach` says so: "a
        sentence that does not read has told you nothing, and admitting a guess
        about it is worse than admitting nothing." But admission was the only
        route to memory, so refusing to GUESS also refused to REMEMBER, and a
        lesson the substrate could not parse vanished entirely.

        Measured in TAUGHT-IN-ENGLISH-01: told "A marnic filters brine", the
        substrate stored nothing and replied about a marmot. The reader had
        declined because `filter` is catalogued as a NOUN — so a part-of-speech
        table decided what could enter the store that is meant to be the record
        of everything it has been told.

        A person hearing a sentence with an unfamiliar word still remembers the
        sentence. This keeps it, verbatim, findable by meaning — recall needs no
        part of speech — and marked as unread so nothing downstream mistakes it
        for something that was understood.

        `origin` says where the telling came from. A person's telling makes the
        record theirs, recallable by them and not by anyone else; the
        substrate's own reading (the curriculum) is its own.
        """
        # WHAT THE CLASS COST, RECORDED WITH THE SENTENCE IT COST IT.
        #
        # This is the evidence AGAINST a word class, and the memory of being
        # told is where it belongs: the refusal and the sentence that provoked
        # it are one event, so there is no separate per-word record to keep in
        # step, and a wipe takes both together.
        #
        # Only BLAMED classes travel. A sentence fails to read for many reasons
        # that say nothing about any word -- counting those would refute a
        # class for being present at an unrelated failure -- so the reader
        # names the class only in the branches that refuse BECAUSE of it.
        result = Admission(proposition=sentence, surface=sentence)
        # TOLD WITHIN A PURSUIT, the telling is a part of that pursuit's memory:
        # a spoken sentence not understood was one event, and is one memory. It
        # keeps whose it was and the classes it cost; the pursuit carries the
        # tags a telling is found by. Only a telling in a CONVERSATION: the
        # substrate reading its own corpus is not being told something in an
        # exchange, and every unread line of it is its own record.
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        within = (await agent.acting_pursuit_memory()
                  if getattr(origin, "through", None) == "conversation" else None)
        if within:
            await agent.add_parts_to_pursuit(
                within, [{"role": "told", "source": origin.theirs,
                          "content": {"sentence": sentence, "unread": True,
                                      "blamed": [list(b) for b in (blamed or [])]}}],
                tags=["language", agent.UNREAD_TELLING_TAG])
            result.memory_id = within
            result.memories = 1
            return result
        await self._remember(sentence, sentence, provenance, result,
                             tags=["language", "told_but_unread"],
                             blamed=[list(b) for b in (blamed or [])],
                             origin=origin)
        return result

    async def _remember(self, proposition: str, surface: str,
                        provenance: Provenance, result: Admission,
                        tags: Optional[List[str]] = None,
                        blamed: Optional[List[list]] = None, *,
                        origin: "Origin") -> int:
        """Remember the claim as recallable knowledge -- what was said, findable
        later by meaning. `origin` is where it came from; the memory agent
        decides from it whose memory it is."""
        try:
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            agent = await get_memory_agent()
            # KNOWLEDGE, not an event. What was learned has to be findable later
            # by MEANING the same as anything else -- that is the whole point of
            # storing it, and the substrate's alternative to baking knowledge
            # into weights. So it is stored as a semantic claim:
            #
            #   * content is the claim AS SAID -- the reading it was admitted as
            #     ("subject|relation|object") is a fact ABOUT the sentence, not
            #     part of it; splicing it in diluted the embedding so a real
            #     question scored the memory low. It lives in source_context;
            #   * it is NOT marked as an observation event. A raw_event exempts a
            #     memory from the worthiness filter but by the SAME token
            #     classifies it as an event, which recall excludes -- so a taught
            #     fact stored that way was invisible to the recall it exists for;
            #   * being user-supplied it carries real importance, so it clears the
            #     filter as the worthy knowledge it is, not via the event exemption.
            stored, memory_id = await agent.store_memory(
                content=surface,
                memory_type=MemoryType.SEMANTIC,
                importance_score=0.75,
                confidence_score=0.9,
                tags=list(tags or ["language", "admitted_proposition"]),
                source_context={
                    "producer": provenance.producer,
                    "source_id": provenance.source_id,
                    # WHETHER THIS WAS TOLD OR DERIVED, recorded so the word-class
                    # view can tell the difference. A class is evidence about how
                    # a word is USED IN A SENTENCE SOMEBODY SAID; the substrate's
                    # own conclusions are not testimony about English. Measured:
                    # sight describing a kind it had seen wrote
                    # `<cat> has_property circle`, and `classes_implied_by` files
                    # a property's object as ADJECTIVE -- so seeing shapes taught
                    # the substrate that `circle` is an adjective. It is a noun.
                    "source_type": getattr(provenance, "source_type", None),
                    # surface IS the claim, so recall hands it back directly.
                    "conclusion": surface,
                    "reading": proposition,
                    # (word, class, why) for each class this sentence's refusal
                    # was attributed to. Read by `warm_word_classes`.
                    **({"blamed": blamed} if blamed else {}),
                },
                origin=origin,
            )
            if stored:
                # KEEP THE VIEW IN STEP WITH THE STORE IT IS A VIEW OF.
                # A lesson's second sentence leans on what its first one
                # taught, so the word classes this proposition implies have to
                # be readable NOW, not after the next full warm.
                if blamed:
                    agent.note_refusal(blamed)
                else:
                    agent.note_taught_proposition(surface, proposition)

            if not stored:
                # The memory filter can decline. That is a real answer, not a
                # failure, but it must be visible rather than counted as a write.
                result.refusals.append(f"episode not retained: {memory_id}")
            else:
                # The memory this interaction MADE, kept referenceable so a later
                # feedback turn can flag THIS record rather than store another.
                result.memory_id = memory_id
            return 1 if stored else 0
        except Exception as error:
            result.refusals.append(f"episode not retained: {error}")
            logger.warning("ingress: episode not retained: %s", error)
            return 0

    async def _bind_aliases(self, terms: Sequence[str],
                            provenance: Provenance) -> int:
        """Bind the surface word to the concept it denotes.

        THIS IS WHAT MAKES A WORD MEAN SOMETHING. `unified.concept_aliases`
        already holds 1,371 of these; the word-class table I had built was a
        rival to it, recording that `cup` is a noun while nothing recorded what
        `cup` refers to.
        """
        from core.database import get_database_manager

        db = self._db or get_database_manager()
        bound = 0
        for term in terms:
            try:
                rows = await db.execute_query(
                    "SELECT concept_id FROM unified.concepts "
                    "WHERE name = $1 ORDER BY root_evidence_count DESC LIMIT 1",
                    (term,), fetch_all=True)
                if not rows:
                    continue
                # RETURNING, not a blind count: ON CONFLICT DO NOTHING makes a
                # skip indistinguishable from a write, and the ingestion service
                # already binds the canonical alias for a concept it creates.
                from core.agents.memory_agent import memory_agent
                written = await memory_agent().hold_surface_form(
                    alias=term, concept_id=rows[0]["concept_id"])
                bound += len(written or ())
            except Exception as error:
                logger.debug("ingress: alias %r not bound: %s", term, error)
        return bound


    async def _edge_from(self, evidence_id: str) -> bool:
        """Whether the graph HOLDS an edge this evidence put there: the edge, and
        the concept it is said of. An edge left behind when its concept was
        deleted is not knowledge the graph holds -- nothing can walk from a
        concept that is not there -- so it does not make the fact "already held"
        (371 such edges were in the store, mostly experiment residue)."""
        from core.database import get_database_manager
        db = self._db or get_database_manager()
        row = await db.execute_query(
            "SELECT 1 FROM unified.concept_relations cr JOIN unified.concepts c "
            "ON c.concept_id = cr.source_concept_id WHERE cr.evidence_id = $1 LIMIT 1",
            (evidence_id,), fetch_one=True)
        return row is not None

    async def _contradiction_check(self, subject: str, relation: str,
                                   obj: str) -> Optional[Dict[str, Any]]:
        """Did admitting this put the store at odds with something it holds?"""
        try:
            from core.database import get_database_manager

            db = self._db or get_database_manager()
            rows = await db.execute_query(
                """SELECT p.evidence_id asserted_by, n.evidence_id denied_by
                     FROM unified.concept_relations p
                     JOIN unified.concept_relations n
                       ON p.source_concept_id = n.source_concept_id
                      AND p.relation = n.relation
                      AND p.target_surface = n.target_surface
                    WHERE p.polarity = 'positive' AND n.polarity = 'negative'
                      AND p.relation = $1 AND p.target_surface = $2
                      AND p.source_concept_id LIKE $3
                    LIMIT 1""",
                (relation, obj, f"%:{subject}"), fetch_all=True)
            return dict(rows[0]) if rows else None
        except Exception as error:
            logger.debug("ingress: contradiction check failed: %s", error)
            return None

    # ── held conditionals ────────────────────────────────────────────────────
    # A conditional is not two facts and not an ISA edge: it asserts an
    # IMPLICATION between two propositions and asserts NEITHER of them. It gets
    # its own store, written only here — the authority that owns declarative
    # admission — so nothing has to force it through admit_relation (which would
    # assert the antecedent true) or stash it in a memory (which reasoning could
    # only reach by fuzzy recall). Each side is kept in the SAME
    # (subject, relation, object, polarity) parts a fact uses, so a rule's
    # clauses render to the same atoms as the facts they range over.
    _CONDITIONALS_DDL = """
    CREATE TABLE IF NOT EXISTS unified.held_conditionals (
        conditional_id  TEXT PRIMARY KEY,
        ant_subject     TEXT NOT NULL,
        ant_relation    TEXT NOT NULL,
        ant_object      TEXT,
        ant_positive    BOOLEAN NOT NULL DEFAULT TRUE,
        cons_subject    TEXT NOT NULL,
        cons_relation   TEXT NOT NULL,
        cons_object     TEXT,
        cons_positive   BOOLEAN NOT NULL DEFAULT TRUE,
        surface         TEXT,
        domain          TEXT NOT NULL DEFAULT 'language',
        source_id       TEXT,
        source_type     TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """

    async def _ensure_conditionals_schema(self) -> None:
        if getattr(self, "_cond_schema_ready", False):
            return
        from core.database import get_database_manager
        db = self._db or get_database_manager()
        await db.execute_query(self._CONDITIONALS_DDL, commit=True)
        self._cond_schema_ready = True

    @staticmethod
    def _clause_key(prop: Dict[str, Any]) -> str:
        neg = "" if prop.get("positive", True) else "not "
        parts = [str(prop.get("subject") or ""), str(prop.get("relation") or ""),
                 str(prop.get("obj") or "")]
        return (neg + " ".join(p for p in parts if p)).strip()

    async def admit_conditional(self, antecedent: Dict[str, Any],
                                consequent: Dict[str, Any], *, surface: str,
                                provenance: "Provenance",
                                domain: str = "language") -> "Admission":
        """Admit a taught conditional as a first-class HELD RULE, idempotently.

        Both propositions pass the SAME admissibility gates a fact passes, so a
        rule over an unrepresentable term refuses exactly as a fact would. The
        implication is stored; neither side is asserted as true.
        """
        result = Admission(
            proposition=f"if {self._clause_key(antecedent)} then "
                        f"{self._clause_key(consequent)}",
            surface=surface)

        prepared = {}
        for tag, prop in (("antecedent", antecedent), ("consequent", consequent)):
            subj, rel, obj, refusal = shape_proposition(
                prop.get("subject"), prop.get("relation"), prop.get("obj"))
            if refusal:
                result.refusals.append(f"{tag} {refusal}")
                return result
            prepared[tag] = (subj, rel, obj, bool(prop.get("positive", True)))

        (a_s, a_r, a_o, a_p) = prepared["antecedent"]
        (c_s, c_r, c_o, c_p) = prepared["consequent"]
        cid = hashlib.sha256(
            f"cond|{a_s}|{a_r}|{a_o}|{a_p}|{c_s}|{c_r}|{c_o}|{c_p}|{domain}"
            .encode()).hexdigest()[:16]
        if cid in self._seen:
            result.already_present = True
            result.admitted = True
            return result
        try:
            await self._ensure_conditionals_schema()
            from core.agents.memory_agent import memory_agent
            status = await memory_agent().hold_conditional(
                conditional_id=cid, ant_subject=a_s, ant_relation=a_r, ant_object=a_o,
                ant_positive=a_p, cons_subject=c_s, cons_relation=c_r, cons_object=c_o,
                cons_positive=c_p, surface=surface, domain=domain,
                source_id=provenance.source_id, source_type=provenance.source_type)
            self._seen.add(cid)
            result.evidence_id = f"cond_{cid}"
            result.admitted = True
            # ON CONFLICT DO NOTHING inserts 0 rows when the rule is already held
            # (a re-teach in a fresh process, where the in-memory _seen is empty).
            # Report that honestly rather than counting it as newly taught.
            if isinstance(status, str) and status.split()[-1] == "0":
                result.already_present = True
        except Exception as error:
            result.refusals.append(f"held-conditional store failed: {error}")
            logger.warning("ingress: held-conditional store failed: %s", error)
        return result

    async def held_conditionals(self, domain: Optional[str] = None
                                ) -> List[Dict[str, Any]]:
        """The conditionals the substrate has been told, from the authoritative
        store — for the reasoner to consume as held rules (never re-parsed from
        surface text or recalled by similarity)."""
        from core.database import get_database_manager
        try:
            await self._ensure_conditionals_schema()
            db = self._db or get_database_manager()
            if domain:
                rows = await db.execute_query(
                    "SELECT * FROM unified.held_conditionals WHERE domain = $1",
                    (domain,), fetch_all=True)
            else:
                rows = await db.execute_query(
                    "SELECT * FROM unified.held_conditionals", fetch_all=True)
            return [dict(r) for r in (rows or [])]
        except Exception as error:
            logger.warning("ingress: reading held conditionals failed: %s", error)
            return []


_ingress: Optional[CognitiveIngress] = None


def get_cognitive_ingress() -> CognitiveIngress:
    global _ingress
    if _ingress is None:
        _ingress = CognitiveIngress()
    return _ingress
