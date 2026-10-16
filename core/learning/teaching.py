#!/usr/bin/env python3
"""Teaching the substrate from a source. ONE pipeline, one owner of the policy.

There were seven teaching scripts. `consider_many()` underneath them was already
the one authority, and that part was right -- what was duplicated was the
POLICY: which source, what to harvest, which relations survive, how a term is
normalised, what quality floor applies, whether the part of speech lives. Every
script decided all of it for itself, which is the same shape as the two speech
renderers: one owner underneath, several callers each re-deriving what the owner
should have settled.

The cost was not hypothetical. Both ConceptNet scripts carried verbatim copies
of a `_term()` that NAMES the part of speech in its own docstring and throws it
away::

    def _term(uri):
        \"\"\"/c/en/hot_dog/n -> 'hot dog'; non-English -> None.\"\"\"
        p = uri.split("/")
        return p[3].replace("_", " ").strip().lower()   # p[4] is the part of speech

The grammar the substrate needs went past that line and onto the floor on every
pass ever run -- while the lexicon arm downstream guessed that same grammar from
a surface that has none.

THE SPLIT THAT MAKES IT ONE PIPELINE. A `Source` READS A FORMAT and nothing
else: it yields records and states its own support for each. `TeachingPass`
DECIDES EVERYTHING ELSE -- how much of the source to take and how to sample it,
the quality floor, that word classes are taught from the source's own tags, that
facts go through the one learning authority, and what the session reports. A
shared helper several scripts import would not be this; that is several
pipelines agreeing about one function. The owner holds the policy, not just the
parsing.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re
from dataclasses import dataclass, field
from typing import (Any, Dict, FrozenSet, Iterable, Iterator, List, Optional,
                    Protocol, Sequence, Tuple)

from core.utils.give_way import GiveWay

logger = logging.getLogger(__name__)

#: A source's normalised support, below which the substrate is told nothing.
#:
#: SET AT "ONE REAL SOURCE ASSERTS THIS", which `quality_from_corroboration`
#: puts at 0.75 for ConceptNet weight 1.0. That is deliberately STRICTER than
#: the cognitive ingress's own `MIN_ADMIT_QUALITY` (0.5): the door's floor is
#: about what may enter the graph at all, and this one is about what a corpus
#: has earned the right to say. ConceptNet's 0.5-weight tail -- a single
#: unreviewed scrape, which is where `oxygen isa book` comes from -- sits at
#: 0.688 and is refused here.
#:
#: It is a floor in ONE place for every source. Before this, no script applied
#: one at all: every fact inherited an unstated 0.9 however well attested it
#: was, which is how a corpus came to set the prior of most of what the
#: substrate believes without anyone choosing it.
DEFAULT_QUALITY_FLOOR = 0.75

#: Facts per call to the learning authority.
#:
#: `consider_many` amortises its fan-out to the END of the batch -- that is what
#: makes a reference-sized teach practical -- so ONE call with 83,024 facts
#: admits everything and moves no belief until the last one lands. Two things
#: follow, and the second is the serious one: the fan-out then runs over 83,024
#: clauses at once (the documented failure "single giant `consider_many` never
#: returns"), and NOTHING is durable until the whole pass completes, so an hour
#: of work is lost to any interruption. Observed on the first attempt at the
#: full WordNet pass: relations climbing past 400 with beliefs still at zero.
#:
#: Batching keeps the amortisation that matters (one fan-out per 5,000, not one
#: per fact) while making progress durable and watchable -- the belief count
#: climbs during the run, which is also the only honest way to see a pass is
#: alive rather than wedged.
DEFAULT_BATCH = 5000


@dataclass(frozen=True)
class TaughtRecord:
    """One thing a source has to say, with the source's own support for it."""

    subject: str
    relation: str
    obj: str
    #: The SOURCE's support for this assertion, already normalised to [0,1].
    #: Only the source knows what its own weight means, so only the source may
    #: map it -- the same rule the evidence producers follow for perception.
    quality: float
    #: `(word, CLASS)` pairs the source STATES, never ones inferred here.
    #: ConceptNet puts the part of speech on the URI; WordNet has its own tags.
    word_classes: Tuple[Tuple[str, str], ...] = ()
    #: THE FACT AS SAID, in English, when the source can say it.
    #:
    #: Without this the surface was synthesised from the triple -- `kidney isa
    #: organ` -- and every word class the substrate derives comes off that
    #: surface. `isa` is a typed relation nobody ever says, so it is never
    #: recorded as a verb, and the object of a kind-relation is always a noun:
    #: the store could therefore only ever learn NOUNS, whatever the source
    #: knew. Measured: after a full pass the store held 199 words and every
    #: single one was a noun, and `_reads_as_verb` then REFUSED every sentence
    #: whose verb had been catalogued.
    #:
    #: A real sentence carries what a triple cannot -- articles, a verb in the
    #: relation slot, and any further claims a definition makes about the kind
    #: it names ("a pump is a device THAT MOVES FLUID"). The pass reads it.
    sentence: Optional[str] = None
    #: WHAT THE SENTENCE MEANS, when the teacher says so (`derived_reader.Meaning`).
    #:
    #: A record that carries its meaning teaches two things at once. Its FACTS,
    #: bound to `situation`, are world knowledge and are taught like any fact.
    #: The sentence with its meaning is a PATTERN -- how English says those
    #: facts -- which is how the substrate learns to read and to speak
    #: (docs/research/SHAPES_CHANGE_MAP.md). Its sentence is NOT read by the
    #: written reader: the teacher gave the meaning, and a second meaning read
    #: beside it could only disagree with it.
    meaning: Optional[Any] = None
    #: What the situation's variables stood for when this was said, e.g.
    #: `(("?speaker", "teacher"), ("?shown", "teachers_shoe"))`. Pointing words
    #: belong to the situation, not the sentence; in text the teacher names them.
    situation: Tuple[Tuple[str, str], ...] = ()
    #: AN EXAMPLE OF ENGLISH, NOT A CLAIM ABOUT THE WORLD. A lesson's "The door
    #: is open." shows how English says a thing is so; it does not say that some
    #: door is open. An example teaches its pattern and nothing it states: none of
    #: its facts, and no rule, is held.
    example: bool = False
    #: HOW THE SOURCE WRITES THE CONCEPTS OF ITS MEANING, where a concept's name
    #: is not its word: WordNet names one sense of "person" `causal agent person`
    #: and writes it "person". `(concept, word)` pairs. A record carrying a
    #: meaning and no sentence is SAID by the substrate, through the frames it
    #: was taught, with these words (`TeachingPass._said`): the source gives what
    #: is so and its words, and English as the substrate holds it gives the
    #: sentence. No sentence is written from a template.
    words: Tuple[Tuple[str, str], ...] = ()
    #: HOW THE SENTENCE WRITES A CONCEPT'S WORD IN A FORM OF ITS OWN: a plural ("mice" for "mouse", "hawks" for
    #: "hawk"), a verb's past or the form it takes for a doing under way ("strolled", "strolling" for "stroll"):
    #: `(concept, form)` pairs. The reader learns a change from the words it holds and reads every other word in a
    #: form by it, so a form is learned from sentences that write it, and one no change makes ("mice", "ran") is a
    #: word of its own.
    forms: Tuple[Tuple[str, str], ...] = ()
    #: HOW THE SOURCE'S WORDS ARE USED, as real English shows it: `(word, use)` pairs, `count` ("a table", "tables"),
    #: `mass` ("furniture": never "a furniture") or `plural` ("cattle"). The reader learns a word's use from the
    #: sentences it holds, and guesses one it holds none of by its ending, `count` when nothing decides; a word the
    #: source states is said as stated (`TeachingPass._said`), and the sentence then teaches its use.
    uses: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self):
        if self.meaning is None:
            if self.situation:
                raise ValueError("a situation binds the variables of a meaning; "
                                 "this record states none")
            if self.example:
                raise ValueError("an example of English is a sentence with its "
                                 "meaning; this record gives no meaning")
            if self.words or self.forms or self.uses:
                raise ValueError("words say how a meaning's concepts are written; "
                                 "this record states no meaning")
            return
        from core.semantics.derived_reader import Meaning
        if not isinstance(self.meaning, Meaning):
            raise ValueError("a record's meaning is a derived_reader.Meaning")


#: Relations the reasoner walks TRANSITIVELY. An edge admitted here is not one
#: fact, it is every conclusion reachable through it.
REASONING_RELATIONS = frozenset({"isa", "is_a", "instance_of"})


class Source(Protocol):
    """Reads a format. Decides nothing about teaching.

    `curated` is the one thing a source must declare about ITSELF, because only
    it knows what it is: a hand-built hypernymy (WordNet, Wikidata) or a crowd
    graph (ConceptNet). See `TeachingPass` for why that answer is load-bearing.

    A source that states classes about its own vocabulary (a `word_classes()`
    method) also declares `quality`, the standing of those classes. Classes
    stated on a record take that record's quality.
    """

    name: str
    curated: bool

    def provenance(self) -> Any: ...

    def records(self) -> Iterator[TaughtRecord]: ...


@dataclass
class Report:
    """What a pass actually did. Every field is an observed count."""

    source: str
    domain: str
    read: int = 0
    below_floor: int = 0
    taught: Dict[str, int] = field(default_factory=dict)
    #: {told, skipped, total} for the word classes the source STATED.
    word_classes: Dict[str, int] = field(default_factory=dict)
    #: {learned, already, refused, total} for the sentences taught WITH their
    #: meaning -- the patterns (`learn_patterns`).
    patterns: Dict[str, int] = field(default_factory=dict)
    #: What became of the facts those meanings state: `bound` (general facts,
    #: taught into the model), `speaker_context` (facts about the situation it
    #: was said in -- the speaker, the listener, what was shown or mentioned --
    #: held in the speaker's context, not the model), `no_speaker` (such facts
    #: from a situation that names no speaker, so they have nowhere to be held),
    #: `open` (an unknown no situation names, so not a fact to hold), and
    #: `not_told` (a question or a request states nothing to hold).
    meanings: Dict[str, int] = field(default_factory=dict)
    #: {observed, already, no_construction, refused, total} for how often the source met each word naming each thing
    #: (`learn_usage`).
    usage: Dict[str, int] = field(default_factory=dict)
    #: {remembered, already, refused, total} for what the source found each word said of (`learn_said`).
    said: Dict[str, int] = field(default_factory=dict)
    #: {observed, withdrawn, refused, total} for what the listener counted its evidence worth on what it was taught
    #: (`learn_listening`), and how many sentences it counted on.
    listening: Dict[str, int] = field(default_factory=dict)
    #: {told, already, skipped, total} for how the source says each word is said (`learn_pronunciations`).
    pronunciations: Dict[str, int] = field(default_factory=dict)
    #: {remembered, already, refused, total} for the sentences the source gave as analysed (`learn_structure`).
    structure: Dict[str, int] = field(default_factory=dict)
    sampled: bool = False
    limit: Optional[int] = None
    #: Whether what the source states about its whole vocabulary was cut to the sample's words (a small pass).
    small: bool = False
    seconds: float = 0.0

    def lines(self) -> List[str]:
        how = (f"a uniform sample of {self.limit:,} drawn across the whole source"
               if self.sampled and self.limit
               else (f"the first {self.limit:,} records" if self.limit
                     else "the whole source"))
        if self.small:
            how += ", and what the source states about its vocabulary only for their words"
        return [
            f"source            : {self.source}",
            f"domain            : {self.domain}",
            f"coverage          : {how}",
            f"records read      : {self.read:,}",
            f"below quality floor: {self.below_floor:,}",
            f"facts             : {self.taught}",
            f"word classes      : {self.word_classes or 'none stated'}",
            f"patterns          : {self.patterns or 'none taught'}",
            f"meaning facts     : {self.meanings or 'none given'}",
            f"word usage        : {self.usage or 'none counted'}",
            f"listening counted : {self.listening or 'nothing'}",
            f"said of           : {self.said or 'none counted'}",
            f"pronunciations    : {self.pronunciations or 'none stated'}",
            f"sentences analysed: {self.structure or 'none given'}",
            f"seconds           : {self.seconds:.1f}",
        ]


def told_events(meaning: Any, sentence: str) -> Dict[str, str]:
    """`{unknown: name}` for each happening a told meaning tells of: an unknown that is one of a kind
    (`instance_of(?v0, eat)`) and that the meaning says something was done by or done to. Its name is its kind and
    the telling it came from (`eat_` and eight hex digits of the sentence and its meaning), so the same sentence taught
    again names the same event, and two tellings name two. Any other unknown is not named."""
    import hashlib
    from core.semantics.derived_reader import EVENT_PARTICIPANTS, SITUATION_VARIABLES, is_variable
    # A happening the telling does not tell as so -- what someone said, thought or wants, what a doing was for -- is
    # not held as one.
    told = [f for f in meaning.facts if not f.unasserted]
    kinds = {f.subject: f.obj for f in told
             if f.relation == "instance_of" and f.positive and is_variable(f.subject) and not is_variable(f.obj)}
    done = {f.subject for f in told if f.relation in EVENT_PARTICIPANTS and is_variable(f.subject)}
    named: Dict[str, str] = {}
    for unknown in sorted(set(kinds) & done):
        if unknown in SITUATION_VARIABLES or unknown in meaning.asked:
            continue
        digest = hashlib.sha1(f"{sentence}|{meaning.canonical()}|{unknown}".encode("utf-8")).hexdigest()[:8]
        named[unknown] = f"{kinds[unknown]}_{digest}"
    return named

def known_in_lesson(meaning: Any) -> Dict[str, str]:
    """`{unknown: name}` for each known thing a lesson tells of ("the kelt", `given instance_of(?t0, kelt)`): the one
    of its kind Lyric's lessons know, `kelt_1`. A lesson is one telling, so "the kelt" across it is one kelt, and it is
    the same kelt in every lesson that speaks of one (docs/research/SEPARATION_MAP.md §11.10)."""
    from core.semantics.cognitive_ingress import normalize_term
    return {unknown: normalize_term(f"{kind} 1") for unknown, kind in meaning.known_kinds().items()}


class TeachingPass:
    """THE owner of source -> taught knowledge.

    `limit` does NOT mean "the first N". ConceptNet's CSV is sorted by assertion
    URI, so the first N English `IsA` edges are its alphabetical head -- measured
    on the 5.7.0 dump, the first one appears at line 17,111,508 and the head is
    `0_10_0`, `1,000_megawatt_plutonium_reactor`, `00t shirts`, `10 downing
    street`. A pass taught that way has not seen English, it has seen the letter
    A. So a limit RESERVOIR-SAMPLES across the entire stream by default, and the
    report says which was done. `sample=False` asks for the head deliberately
    (a smoke test wanting determinism), and then it says so too.
    """

    def __init__(self, source: Source, *, domain: str,
                 quality_floor: float = DEFAULT_QUALITY_FLOOR,
                 limit: Optional[int] = None, sample: bool = True,
                 small: bool = False,
                 allow_uncurated_reasoning_edges: bool = False,
                 batch_size: int = DEFAULT_BATCH,
                 progress: Optional[Any] = None,
                 seed: int = 20260920) -> None:
        self.source = source
        self.domain = domain
        self.quality_floor = quality_floor
        self.limit = limit
        self.sample = sample
        #: A SMALL PASS: the `limit` records (or all a source cut to some senses offers, `WordNetSource.senses`),
        #: and of what the source states about its whole vocabulary (word classes,
        #: usage, what words are said of, how they are said) only what concerns their words. Every phase a full pass
        #: runs, each at the sample's size, so a check reaches the end in minutes: limited alone, a WordNet pass of
        #: 3,000 records still wrote all 75,834 word classes, one memory each, which is hours on a fresh store.
        self.small = small
        self._sample_words: Optional[FrozenSet[str]] = None
        self.allow_uncurated_reasoning_edges = allow_uncurated_reasoning_edges
        self.batch_size = batch_size
        self.progress = progress
        self.seed = seed
        #: Built on first use: a pass that teaches only triples never needs one.
        #: The memory agent, held for the OBSERVED word classes the relation
        #: authority needs to type a copula. Bound in `run()` once the pass has
        #: taught this source's classes, so a sentence is typed against what the
        #: substrate knows by the time it reads it.
        self._memory_for_classes = None

    def _guard_reasoning_edges(self, records: Sequence[TaughtRecord]) -> None:
        """A CROWD GRAPH MUST NOT BECOME THE REASONING TAXONOMY.

        `docs/TEACHING.md` states this as a hard rule and it was learned
        expensively: raw ConceptNet `/r/IsA` carries `apple isa car`,
        `dog isa cuter_than_kid`, `robin isa band` (the singer). Admitted
        wholesale it produced 450k `isa` edges, a term's ancestor set exploded
        45->681 over one to four hops, and the reasoner confabulated
        `dog isa plant` via organism->system->plan_of_action->plant. The cleanup
        was painful precisely because edges recorded no source and could not be
        retracted selectively.

        The reasoner walks these relations TRANSITIVELY, so one bad edge is not
        one bad fact -- it is every conclusion reachable through it. A curated
        hypernymy may supply them; a crowd graph may not, and the quality gate
        does not help because `apple isa car` is perfectly well attested by
        people who found it funny.

        The old `teach_conceptnet.py` did exactly this, which is how the junk got
        in. Refusing here rather than in a script is the point of one pipeline:
        the rule is applied to every source, once, by the owner of the policy.
        """
        if self.source.curated or self.allow_uncurated_reasoning_edges:
            return
        offending = sorted({r.relation for r in records
                            if r.relation in REASONING_RELATIONS})
        if offending:
            raise ValueError(
                f"source {self.source.name!r} is not curated and may not teach "
                f"{offending} -- the reasoner walks those transitively, and a "
                f"crowd graph poisons every conclusion reachable through a bad "
                f"edge. Map the relation to something non-transitive, or pass "
                f"allow_uncurated_reasoning_edges=True and say why.")

    # ── the harvest ─────────────────────────────────────────────────────────
    def _harvest(self, report: Report) -> List[TaughtRecord]:
        """Every record the source offers, gated on quality, bounded honestly."""
        keep: List[TaughtRecord] = []
        rng = random.Random(self.seed)
        kept_seen = 0

        for record in self.source.records():
            report.read += 1
            if record.quality < self.quality_floor:
                report.below_floor += 1
                continue
            if self.limit is None:
                keep.append(record)
                continue
            if not self.sample:
                keep.append(record)
                if len(keep) >= self.limit:
                    break
                continue
            # Reservoir sampling (Vitter R): a uniform sample of a stream whose
            # length is not known in advance, in one pass and bounded memory.
            kept_seen += 1
            if len(keep) < self.limit:
                keep.append(record)
            else:
                j = rng.randrange(kept_seen)
                if j < self.limit:
                    keep[j] = record

        report.sampled = bool(self.limit) and self.sample
        report.limit = self.limit
        return keep

    # ── the teach ───────────────────────────────────────────────────────────
    async def run(self, learning: Any) -> Report:
        """Harvest, gate, and teach through the ONE learning authority.

        Word classes go in FIRST and authoritatively. They are what the source
        states about its own vocabulary, and the fan-out's proposals are
        ordinary claims -- teaching the tags first means a real lexical tag is
        never contradicted by a weaker guess about the same word.
        """
        import asyncio
        import time

        started = time.time()
        report = Report(source=self.source.name, domain=self.domain)
        # THE HARVEST IS WALKED OFF THE LOOP. A source is its files and its corpus, and nothing in it awaits:
        # WordNet's 199,763 records take ten seconds, and walked on the loop, every job the substrate runs waits
        # for them.
        records = await asyncio.to_thread(self._harvest, report)
        self._guard_reasoning_edges(records)
        if self.small and records:
            self._sample_words = self._words_in(records)
            report.small = True

        # A SOURCE'S POS TAGS ARE TAUGHT, INTO MEMORY, LIKE EVERYTHING ELSE.
        #
        # They used to be written straight into a word store, which is loading a
        # catalogue rather than teaching, and that store is gone. Then they were
        # dropped entirely, and the only classes the substrate could hold were
        # the three that a subject/relation/object slot implies -- so every
        # adverb, determiner, preposition, pronoun, conjunction, auxiliary and
        # modal in English was unlearnable, and lived in frozensets in the
        # reader instead.
        #
        # `learn_word_classes` writes them as ordinary semantic memories, which
        # is what makes them wipeable, recallable, and arguable-with.
        stated = self._stated_classes(records)
        if stated:
            report.word_classes = await self._teach_word_classes(learning, stated)

        # THE CLASSES ARE TAUGHT BEFORE THE FACTS ARE READ, and the reading needs
        # them: typing a copula turns on whether its complement is an ADJECTIVE.
        # Warmed once here rather than per sentence — a cold index answers None
        # for every word, which the relation authority reads as "keep ISA". A
        # warm that fails ends the pass: carried on, it typed every copula as ISA
        # and the pass reported itself taught.
        from core.memory import get_memory_agent
        self._memory_for_classes = await get_memory_agent()
        await self._memory_for_classes.warm_word_classes()

        if records:
            # ONE call, for the whole harvest, through the one authority --
            # which fans out to beliefs, the lexicon, the domain and memory.
            # `quality` is PER PASS here because `consider_many` takes one; where
            # a source states support per record, records are grouped by it so
            # no fact inherits another's standing.
            report.taught = await self._teach(learning, records, report)

        # HOW OFTEN EACH WORD NAMES EACH THING, after the words are learned: a source that counted its words in real
        # use (`usage()`) says so, and the count lands on the construction that says the word names the thing.
        # A source of nothing but what its words are like (`vocabulary_only`) has no records, and is counted all the
        # same, as pronunciations are below.
        if (records or getattr(self.source, "vocabulary_only", False)) and hasattr(self.source, "usage"):
            # Counted off the loop too, as the harvest is: all of WordNet's senses are walked for it.
            usage = [use for use in await asyncio.to_thread(list, self.source.usage()) if self._of_sample(use[0])]
            report.usage = await learning.learn_usage(
                usage, provenance=self.source.provenance(),
                quality=float(self.source.quality))
            await self._flush()

        # WHAT THE LISTENER'S EVIDENCE IS WORTH, from a source of sentences whose meaning it gives
        # (`listening_pairs()`): each read, its meanings weighed as the listener weighs them, and counted by whether
        # each was the one meant (`derived_reader.listening_counts`). Nothing else is taught by it.
        if hasattr(self.source, "listening_pairs"):
            from core.agents.memory_agent import get_memory_agent
            from core.semantics import derived_reader as dr
            pairs = list(self.source.listening_pairs())
            view = await (await get_memory_agent()).language_view()
            counts = await dr.listening_counts(pairs, view, give_way=GiveWay())
            report.listening = await learning.learn_listening(
                counts, provenance=self.source.provenance(), quality=float(self.source.quality))
            report.listening["sentences"] = len(pairs)
            await self._flush()

        # HOW THE WORDS OF A SENTENCE GO TOGETHER, from a source of sentences analysed by hand (`analysed()`: a
        # treebank): each kept by memory whole, as it was analysed, its standing a belief on that memory, and read as
        # memory-based learning reads them (`structure.StructureView`). A limited pass takes the first `limit`.
        if hasattr(self.source, "analysed"):
            analysed = await asyncio.to_thread(list, self.source.analysed())
            if self.limit is not None:
                analysed = analysed[:self.limit]
                report.limit, report.sampled = self.limit, False
            report.structure = await learning.learn_structure(
                analysed, provenance=self.source.provenance(), quality=float(self.source.quality),
                progress=(None if not self.progress else
                          lambda done, of: self.progress(done, of, {"phase": "sentences analysed"})))
            await self._flush()

        # WHAT EACH WORD IS SAID OF, from a source that counted it in real use (`said_of()`): how English uses a word,
        # which the listener goes by where nothing it knows tells two things a word names apart.
        if records and hasattr(self.source, "said_of"):
            said = [use for use in await asyncio.to_thread(list, self.source.said_of()) if self._of_sample(use[1])]
            report.said = await learning.learn_said(
                said, provenance=self.source.provenance(),
                quality=float(self.source.quality),
                progress=(None if not self.progress else
                          lambda done, of: self.progress(done, of, {"phase": "what words are said of"})))

        # HOW EACH WORD IS SAID, from a source that states it (`pronunciations()`: a pronouncing dictionary), so a word
        # is heard by the sounds it is made of, whoever says it. A source of nothing else has no records.
        if hasattr(self.source, "pronunciations"):
            pronounced = [said for said in await asyncio.to_thread(list, self.source.pronunciations())
                          if self._of_sample(said[0])]
            report.pronunciations = await learning.learn_pronunciations(
                pronounced, provenance=self.source.provenance(),
                quality=float(self.source.quality))

        report.seconds = time.time() - started
        return report

    async def _teach(self, learning: Any, records: Sequence[TaughtRecord],
                     report: Report) -> Dict[str, int]:
        """Teach the harvest, grouped so each fact carries ITS OWN quality and
        polarity.

        `consider_many` takes one quality and one polarity for a batch, and a corpus
        has neither: ConceptNet's weights run 0.5 to 4.47 on the same relation,
        and a sentence may deny as well as assert. Teaching a batch at a single
        number is exactly the unstated-0.9 problem in a new costume, so the
        harvest is bucketed by (quality, polarity) and each bucket is taught at
        its own.

        A record that carries its MEANING is not read. Its facts, bound to the
        situation it was said in, go into the buckets, and the sentence with its
        meaning is taught as a pattern before the facts (`learn_patterns`), so
        what its meaning names is named when its facts reach the door; both
        counts land on `report`.

        A bucket is (quality, polarity, whose): None is the model's; a speaker's
        name is that speaker's context (`_bucket_meaning`).
        """
        buckets: Dict[Tuple[float, bool, Optional[str]], List[Tuple[str, ...]]] = {}
        patterns: Dict[float, List[Tuple[str, Any]]] = {}
        meanings = {"bound": 0, "speaker_context": 0, "no_speaker": 0, "open": 0, "not_told": 0,
                    "rule": 0, "rule_not_held": 0, "alternative": 0, "example": 0, "said": 0, "not_said": 0,
                    "unasserted": 0}
        rules: List[Tuple[float, Any, Any, str, Optional[str]]] = []
        read_claims = 0
        unread = 0
        to_say = sum(1 for record in records if record.meaning is not None and not record.sentence)
        said_so_far = 0
        # SAYING EACH FACT IS THE SUBSTRATE'S WORK ON ITS OWN LOOP, and all of WordNet's 157,786 took over an hour with
        # nothing else let run and nothing said of how far it was. It gives way by time (`GiveWay`), and says where it
        # is every thousand.
        give_way = GiveWay()
        for record in records:
            await give_way()
            quality = round(float(record.quality), 3)
            if record.meaning is not None:
                if not record.sentence:
                    said_so_far += 1
                    if self.progress and said_so_far % 1000 == 0:
                        self.progress(said_so_far, to_say, {"phase": "saying the facts"})
                sentence = record.sentence
                if not sentence:
                    # SAID, NOT WRITTEN: through the frames taught, in the source's words. What nothing taught says
                    # teaches no English, and its facts are still the source's to state.
                    sentence = self._said(record)
                    meanings["said" if sentence else "not_said"] += 1
                if sentence:
                    # How the source wrote its concepts in this sentence: a run so written is learned as the
                    # concept's name ("electronic computer"), never split into a frame's word and a filler.
                    names = {**dict(record.words), **dict(record.forms)}
                    if not record.sentence:
                        # A SENTENCE SAID HERE WRITES EACH THING BY THE SOURCE'S WORD, OR BY ITS OWN NAME where the
                        # source gives no other. That name is the teacher's too. Left out, "A news report is news."
                        # was taken apart at "report", a word already held for it, and "news" went into a frame:
                        # "A ?slot0 ?slot1 is news.", which then said of anything that it is news.
                        for fact in record.meaning.facts:
                            for term in (fact.subject, fact.obj):
                                if not str(term).startswith("?"):
                                    names.setdefault(term, str(term).replace("_", " "))
                    patterns.setdefault(quality, []).append((sentence, record.meaning, names))
                if record.example:
                    meanings["example"] += 1
                else:
                    self._bucket_meaning(record, sentence or "", quality, buckets, meanings, rules)
                continue
            asserted = buckets.setdefault((quality, True, None), [])
            # A RECORD THAT CAN SAY ITSELF IN ENGLISH IS READ, NOT ASSUMED.
            #
            # The triple is what the source's format states; the sentence is
            # what the source's own words say, and a definition says MORE than
            # its taxonomy edge does -- "a pump is a device that moves fluid"
            # states the kind AND what the kind does. Reading it is the only way
            # the verb in it is ever learned, because a word class is derived
            # from the surface of a taught proposition and a synthesised surface
            # has no verb in it.
            #
            # The triple stands where the sentence does not read, so a source is
            # never worse off for being able to say itself.
            claims, blamed = (await self._read(record.sentence) if record.sentence
                              else ([], []))
            # A READING THAT SPLITS THE SUBJECT IS A MIS-READING, NOT A RICHER
            # ONE. The reader distributes a coordinated subject -- correct for
            # "cats and dogs are animals" -- and it cannot know that `bait and
            # switch` is ONE name. The source can, and said so.
            #
            # Measured on WordNet: 115 of 83,093 facts name a subject containing
            # "and"/"or", and every one of them read into false claims that
            # REPLACED the correct stated edge. `a track and field is a
            # diversion sport` became `track isa diversion sport` AND `field isa
            # diversion sport` -- and `isa` is walked transitively, so `field`'s
            # whole subtree became a kind of sport. That is the same shape as
            # the gloss-derived `inheritance isa x_linked_recessive` that
            # reparented 65,056 concepts: a small count, unbounded damage.
            #
            # Narrow on purpose. A claim is dropped only when its subject is a
            # whole-word FRAGMENT of the subject the record states -- exactly
            # the segmentation case. A gloss that says something about another
            # term ("a pump is a device that moves fluid" -> `device moves
            # fluid`) is not a fragment and survives untouched.
            claims, split = self._drop_segmented_claims(record, claims)
            if split and record.subject:
                # The reading lost the source's own assertion. Teach it too --
                # the pipeline's stated rule is that a source is never worse off
                # for being able to say itself.
                asserted.append((record.subject, record.relation, record.obj,
                                 record.sentence))
            if claims:
                # EACH CLAIM KEEPS ITS POLARITY. "A robin is not a mammal." is a
                # denial, taught as one; it used to be dropped here, so a taught
                # "is not" taught nothing.
                for subject, relation, obj, said, positive in claims:
                    buckets.setdefault((quality, positive, None), []).append(
                        (subject, relation, obj, said))
                read_claims += len(claims)
                continue
            if split:
                continue      # the stated triple was appended above
            if not record.subject:
                # A SENTENCE-ONLY RECORD IS READ OR IT IS DROPPED. It carries no
                # triple to fall back to, deliberately: a source offering a
                # gloss offers English, and filing a mis-parsed gloss as a
                # taxonomy edge is exactly the guessing this pipeline refuses.
                #
                # DROPPED AS A CLAIM, KEPT AS EVIDENCE ABOUT ENGLISH. The
                # sentence did not read, and the reader named WHICH word class
                # it refused because of. That is the refute half of "reading
                # earns a word class", and it lived only on the conversation
                # path -- so the one learning path threw away the only evidence
                # that ever argues a wrong class down, while chat supplied it.
                # Now the substrate's own corpus reading is what argues, which
                # is where learning belongs.
                unread += 1
                await self._note_unread(record.sentence, blamed)
                continue
            asserted.append((record.subject, record.relation, record.obj,
                             record.sentence))
        if read_claims or unread:
            logger.info("teaching read %d claims from the sources' own "
                        "sentences; %d sentences did not read and were dropped",
                        read_claims, unread)

        totals: Dict[str, int] = {}
        provenance = self.source.provenance()
        done = 0

        # THE PATTERNS, BEFORE THE FACTS THEY STATE. How English said each thing
        # is language knowledge, taught through the same authority; English is
        # its domain, whatever domain the lesson's facts belong to.
        #
        # First, because the door admits a fact only about what something
        # taught names (`cognitive_ingress.admissible`): a word held only
        # inside sentence forms names nothing until a taught meaning uses it
        # as a concept's name. The lessons hold "power", "name" and "front"
        # only so ("to the power of", "My name is", "in front of"). Taught
        # after the facts, WordNet's "Power is a quality." named `power` too
        # late: 37 facts of 13,800 were refused in the sandbox, "influence is
        # power" among them, and `power` was left with no kind.
        taught_patterns: Dict[str, int] = {}
        whole = sum(len(pairs) for pairs in patterns.values())
        before = 0
        for quality, pairs in sorted(patterns.items()):
            counts = await learning.learn_patterns(
                pairs, provenance=provenance, quality=quality,
                progress=(None if not self.progress else
                          lambda done, of, phase=None, at=before: self.progress(
                              done if phase else at + done, of if phase else whole,
                              {"phase": phase or "learning the patterns"})))
            before += len(pairs)
            for key, value in (counts or {}).items():
                taught_patterns[key] = taught_patterns.get(key, 0) + int(value)
            await self._flush()

        from core.agents.memory_agent import memory_agent
        from core.learning.unified_learning_system import Evidence

        def evidence(quality: float) -> Evidence:
            # THE SOURCE IS ONE WITNESS: a lesson, a corpus, however many facts it states and however often it is
            # taught (`consider_many`).
            return Evidence.from_provenance(provenance, quality)

        for (quality, positive, speaker), facts in sorted(
                buckets.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")):
            for start in range(0, len(facts), self.batch_size):
                chunk = facts[start:start + self.batch_size]
                if speaker:
                    # WHAT A SOURCE SAYS OF ITS SPEAKER IS THEIRS ("My dog is brown.", said by them): held in their
                    # context by the memory agent, never the world's (docs/research/SEPARATION_MAP.md §11.3).
                    counts = {"admitted": 0, "refused": 0, "total": 0}
                    for subject, relation, obj, said in chunk:
                        counts["total"] += 1
                        decision = await memory_agent().hold_for_person(
                            speaker, subject, relation, obj, positive=positive, quality=quality,
                            domain=self.domain, surface=said, source=f"lesson:{provenance.source_id}")
                        counts["admitted" if decision.admitted else "refused"] += 1
                else:
                    # THE WORLD'S, judged as every claim is: the one door (`consider_many`).
                    counts = await learning.consider_many(
                        chunk, evidence=evidence(quality), domain=self.domain, positive=positive)
                for key, value in (counts or {}).items():
                    totals[key] = totals.get(key, 0) + int(value)
                # FLUSH PER BATCH. Belief writes are fire-and-forget; without
                # this the count does not climb during a run and there is no
                # way to tell a slow pass from a wedged one.
                await self._flush()
                done += len(chunk)
                if self.progress:
                    self.progress(done, len(records), totals)

        # THE RULES, after the facts: a speaker's own held in their context, the world's through the one door.
        for quality, condition, then, sentence, whose in rules:
            antecedent = {"subject": condition.subject, "relation": condition.relation, "obj": condition.obj,
                          "positive": condition.positive}
            consequent = {"subject": then.subject, "relation": then.relation, "obj": then.obj,
                          "positive": then.positive}
            if whose:
                await memory_agent().hold_rule_for_person(
                    whose, antecedent, consequent, quality=quality, domain=self.domain, surface=sentence)
            else:
                await learning.consider_rule(antecedent, consequent, surface=sentence, evidence=evidence(quality),
                                             domain=self.domain)
        if rules:
            await self._flush()

        report.patterns = taught_patterns
        report.meanings = meanings if patterns else {}
        return totals

    @staticmethod
    def _said(record: "TaughtRecord") -> str:
        """The record's meaning, said through the frames the substrate was taught, each concept written as the source
        writes it (`TaughtRecord.words`): the best sentence that writes every one of those words as it is, or nothing
        when nothing taught says it so ("Ocelots are wildcats." says `isa(ocelot, wildcat)` but writes no
        "ocelot")."""
        from dataclasses import replace
        from core.semantics.derived_reader import Meaning, is_variable, live_view, say
        from core.semantics.sentence_machine import form_of
        words = dict(record.words)
        facts = tuple(replace(f, subject=words.get(f.subject, f.subject), obj=words.get(f.obj, f.obj))
                      for f in record.meaning.facts)
        # A KIND OR A QUALITY THE SOURCE WRITES AS A DAY, A TIME OR A NUMBER CANNOT BE SAID AS ONE: "Guy Fawkes Day
        # is a November 5" puts a date where a kind stands, which no meaning holds (`Meaning`). The fact is still the
        # source's to state, as the fact; it is no example of English.
        from core.semantics.derived_reader import _quantity, _temporal
        if any(f.relation in ("isa", "instance_of", "has_property") and (_quantity(f.obj) or _temporal(f.obj))
               for f in facts):
            return ""
        written = Meaning(record.meaning.act, facts, record.meaning.asked)
        view = live_view()
        # The words this pair teaches are written as the source writes them; a concept already held is said as it
        # is held ("tools" for `tool`). The SUBJECT never is: the record is about the thing its word names, so that
        # word is written as the source writes it, held or not. Held only as "Mice", `mouse` said as held taught
        # "Mice" for the animal and then for the person a mouse also names ("Mice are one."), and no reading of "a
        # mouse" reached either.
        subjects = {f.subject for f in facts if not is_variable(f.subject)}
        terms = {t for f in facts for t in (f.subject, f.obj)}
        wanted = [tuple(p.text.lower() for p in form_of(str(term).replace("_", " ")))
                  for term in terms
                  if not is_variable(term) and (term in subjects or not view.lexicals_with_value(term))]
        # A LONGER NAME THAT HOLDS THE WORD IS NOT THE WORD. A thing is held under several names ("sedative",
        # "sedative drug"; "wave to" beside "wave"), and a sentence that writes the longer one does not write the
        # source's: "A sedative drug is a medicine." teaches nothing of "sedative".
        longer = {tuple(p.text.lower() for p in lexical.form)
                  for term in terms if not is_variable(term) for lexical in view.lexicals_with_value(term)}

        def stands(name: Tuple[str, ...], pieces: Tuple[str, ...]) -> bool:
            for at in range(len(pieces) - len(name) + 1):
                if pieces[at:at + len(name)] != name:
                    continue
                if not any(len(run) > len(name) and pieces[start:start + len(run)] == run
                           for run in longer for start in range(max(0, at + len(name) - len(run)), at + 1)):
                    return True
            return False
        # A COUNTED THING NEVER STANDS BARE. What is said here is learned as English, so a sentence that writes a
        # name the source states is counted with nothing before it, first ("Soul is an organism.") or as what
        # something is ("A stock is security."), is not said: taught, it stays held and is said again. The source
        # speaks for the record's own sense; the sayer, holding the word for another sense ("security", safety),
        # would say it as that one is used.
        stated = dict(record.uses)

        def use_stated(term: str) -> Optional[str]:
            name = str(term).replace("_", " ").lower()
            words = name.split()
            last = next((words[at - 1] for at in range(1, len(words)) if view.is_structure(words[at])),
                        words[-1] if words else "")
            return stated.get(name) or (stated.get(last) if last else None)

        counted = [tuple(p.text.lower() for p in form_of(str(term).replace("_", " ")))
                   for term in {t for f in facts for t in (f.subject, f.obj)}
                   if not is_variable(term) and str(term).split() and use_stated(term) == "count"]
        # THE SOURCE'S WORD FOR A THING IS NOT THE THING THAT WORD NAMES. "wave", the source's word for a hairdo, is
        # held for a greeting ("wave to"); said as held, the hairdo was "A wave to is a hairdo.", and "matter", what
        # things are made of, was counted as an affair is: "A substance is a matter.". A word the source wrote for
        # one of its own things is written as it is (`say`, `apart`).
        # So is a name nothing holds yet: it is the source's, whole, a word that builds sentences inside it and all
        # ("body of water").
        apart = {word for concept, word in words.items() if word != concept} \
            | {term for fact in facts for term in (fact.subject, fact.obj)
               if not is_variable(term) and not view.lexicals_with_value(term)}
        # A thing held under several words is said with the one the source wrote here ("weather", not "weather
        # condition", held for it too): `say`, `named`.
        called = {term: str(term).replace("_", " ") for fact in facts for term in (fact.subject, fact.obj)
                  if not is_variable(term)}
        for sentence in say(written, view, uses=stated, named=called, apart=apart):
            pieces = tuple(p.text.lower() for p in form_of(sentence))
            if any(
                    pieces[at:at + len(name)] == name and (at == 0 or pieces[at - 1] == "is")
                    and pieces[at + len(name):at + len(name) + 1] in ((), (".",), ("is",))
                    for name in counted for at in range(len(pieces) - len(name) + 1)):
                continue
            if all(stands(name, pieces) for name in wanted):
                return sentence
        return ""

    @staticmethod
    def _bucket_meaning(record: "TaughtRecord", sentence: str, quality: float,
                        buckets: Dict[Tuple[float, bool, Optional[str]], List[Tuple[str, ...]]],
                        meanings: Dict[str, int],
                        rules: List[Tuple[float, Any, Any, str, Optional[str]]]) -> None:
        """The facts a meaning states, bound to the situation it was said in, into
        the buckets they are taught from.

        A question or a request states nothing to hold. A fact that still names
        an unknown after binding -- "some shoe is black" introduces `?x`, which
        no situation names -- is not a fact the store can hold, and is counted
        as `open` rather than filed under an invented name.

        A HAPPENING TOLD OF IS ONE EVENT, held under the name of its telling
        (`told_events`, decided 2026-10-04): "The wug ate a fep." tells of one
        eating, done by the wug, done to a fep, and those are facts about that
        eating. Only a happening is named, an unknown the meaning says something
        was done by or done to; "some shoe" stays open.

        WHOSE A FACT IS, THE MEANING SAYS.
        A fact about the situation it was said in -- one that names the speaker,
        the listener, what was shown or what was mentioned before ("This is my
        shoe.": the teacher's shoe, owned by the teacher) -- is about that
        situation, not about the world: it is held in the SPEAKER's context, the
        `?speaker` the situation names. A fact that names none of them ("A robin
        is a bird.") is the model's. No word list decides this; the meaning's own
        variables do. A situational fact from a situation that names no speaker
        has nobody to belong to, and is counted, not held.
        """
        from core.semantics.derived_reader import SITUATION_VARIABLES, is_variable
        # A number the meaning builds from numbers is held as its value: "Twenty-one is a number." is `21`'s.
        meaning = record.meaning.evaluated()
        if meaning.act != "tell":
            meanings["not_told"] += len(meaning.facts)
            return
        situation = dict(record.situation)
        speaker = situation.get("?speaker")
        # WHAT A KNOWN THING IS, IS SO WHATEVER ELSE IS SAID: "If the valve is closed, the tank is full." takes a
        # valve and a tank as known, and holds that they are a valve and a tank outright; the rule is about them.
        known = known_in_lesson(meaning)
        if meaning.condition:
            # A CONDITIONAL STATES NO FACT OUTRIGHT: what it says holds when its condition does. It is held as a
            # rule, one fact a side, as a told rule is held; a side of several facts, or one still naming an unknown,
            # is counted, not held.
            bound = dict(zip(meaning.facts, meaning.bound(situation, known)))
            for given in meaning.given:
                fact = bound[given]
                if not given.unasserted and not is_variable(fact.subject):
                    buckets.setdefault((quality, True, None), []).append(
                        (fact.subject, fact.relation, fact.obj, sentence))
                    meanings["bound"] += 1
            condition = [bound[f] for f in meaning.condition if not f.given]
            then = [bound[f] for f in meaning.asserted if not f.given]
            if len(condition) != 1 or len(then) != 1 or any(
                    is_variable(t) for f in condition + then for t in f.terms()):
                meanings["rule_not_held"] += 1
                return
            situational = any(t in SITUATION_VARIABLES for f in meaning.facts for t in f.terms())
            if situational and not speaker:
                meanings["no_speaker"] += 1
                return
            rules.append((quality, condition[0], then[0], sentence, speaker if situational else None))
            meanings["rule"] += 1
            return
        events = told_events(meaning, sentence)
        for said, fact in zip(meaning.facts, meaning.bound(situation, known)):
            fact = fact.renamed(events) if events else fact
            if said.unasserted:
                # WHAT IS NOT TOLD AS SO IS NOT HELD AS HOLDING: `Tom said, "The dog barked."` and "Tom said that the
                # dog barked." hold a saying, done by Tom; that the dog barked is his to have said (the teammate's
                # decisions, 2026-10-05). So for what someone thinks, asks or wants, and what a doing was for.
                meanings["unasserted"] += 1
                continue
            if said.alternative:
                # OF ALTERNATIVES, ONE HOLDS; none is stated, so none is held as a fact.
                meanings["alternative"] += 1
                continue
            if is_variable(fact.subject) or is_variable(fact.obj):
                meanings["open"] += 1
                continue
            situational = said.subject in SITUATION_VARIABLES or said.obj in SITUATION_VARIABLES
            if situational and not speaker:
                meanings["no_speaker"] += 1
                continue
            whose = speaker if situational else None
            buckets.setdefault((quality, fact.positive, whose), []).append(
                (fact.subject, fact.relation, fact.obj, sentence))
            meanings["speaker_context" if situational else "bound"] += 1

    @staticmethod
    def _words_in(records: Sequence[TaughtRecord]) -> FrozenSet[str]:
        """Every word the records say anything with: their terms and their sentences."""
        words = set()
        for record in records:
            for text in (record.subject, record.obj, record.sentence or ""):
                words.update(re.findall(r"[a-z0-9']+", str(text).lower().replace("_", " ")))
        return frozenset(words)

    def _of_sample(self, term: str) -> bool:
        """Whether a term the source states about its whole vocabulary is one a small pass's records say anything
        with, every word of it. Every term, in any other pass."""
        if self._sample_words is None:
            return True
        words = re.findall(r"[a-z0-9']+", str(term).lower().replace("_", " "))
        return bool(words) and all(word in self._sample_words for word in words)

    def _stated_classes(self, records: Sequence[TaughtRecord]) -> Dict[Tuple[str, str], float]:
        """Every `(word, CLASS)` the source states, deduplicated, with the
        standing of whoever stated it.

        Deduplicated because teaching is not an epoch: the same pair arriving
        twice is one thing the source says, not two witnesses to it -- so a pair
        keeps the best standing it was stated with, once.

        A class stated on a RECORD has that record's quality, exactly as the
        record's fact does. A class the source states about its own vocabulary
        (`word_classes()`) has the source's declared `quality`. This read one
        source-level `quality` for all of them, which ConceptNet -- whose
        records each carry their own corroboration -- does not declare, so a
        ConceptNet pass stating classes raised AttributeError before teaching
        anything, and a weak scrape's class stood as high as a strong one's.
        """
        stated: Dict[Tuple[str, str], float] = {}

        def state(word, word_class, quality):
            key = (str(word).strip().lower(), str(word_class).strip().upper())
            if key[0] and key[1]:
                stated[key] = max(stated.get(key, 0.0), float(quality))

        source_level = getattr(self.source, "word_classes", None)
        if callable(source_level):
            for word, word_class in source_level():
                if self._of_sample(word):
                    state(word, word_class, self.source.quality)
        for record in records:
            for word, word_class in record.word_classes or ():
                state(word, word_class, record.quality)
        return stated

    async def _teach_word_classes(self, learning: Any,
                                  stated: Dict[Tuple[str, str], float]) -> Dict[str, int]:
        """Teach the stated classes grouped by standing, each group at ITS
        quality (`learn_word_classes` takes one per call, as `consider_many`
        does), and add up what each group did."""
        buckets: Dict[float, List[Tuple[str, str]]] = {}
        for pair, quality in stated.items():
            buckets.setdefault(round(quality, 3), []).append(pair)
        totals: Dict[str, int] = {}
        whole = sum(len(pairs) for pairs in buckets.values())
        before = 0
        for quality, pairs in sorted(buckets.items()):
            counts = await learning.learn_word_classes(
                pairs, provenance=self.source.provenance(), quality=quality,
                progress=(None if not self.progress else
                          lambda done, _total, at=before: self.progress(
                              at + done, whole, {"phase": "word classes"})))
            before += len(pairs)
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + int(value)
        return totals

    def _typed_relation(self, relation: str, obj: str) -> str:
        """The relation this predicate actually states, decided by the ONE
        relation authority with the object's OBSERVED word class.

        Only the bare copula is ambiguous; every other surface types itself. The
        What the complement is being used AS is decided by `complement_class`
        (determiner -> kind, bare + adjective-capable -> property); this only
        supplies the observed evidence and hands the verdict to `classify`.
        """
        rel = str(relation or "").strip().lower()
        if rel not in ("is", "are"):
            return rel
        from core.semantics.relation_types import classify, complement_class
        return classify(rel, object_word_class=complement_class(
            obj, self._class_evidence)).relation.value

    def _class_evidence(self, word: str):
        """Every class this word has been OBSERVED in, with its counts, from
        memory. Empty when it has not been observed — never a guess."""
        agent = self._memory_for_classes
        if agent is None:
            return {}
        return agent.word_classes(word)

    async def _note_unread(self, sentence: str, blamed) -> None:
        """Remember a corpus sentence the reader could not read, with the word
        classes its refusal was attributed to.

        `warm_word_classes` subtracts a point from every class named here, so a
        word wrongly catalogued breaks real sentences and each break argues it
        down until it stops being usable. The record is the substrate's own
        reading of its own corpus -- the learning path -- not somebody talking.
        """
        if not sentence:
            return
        from core.memory import Origin
        from core.semantics.cognitive_ingress import (get_cognitive_ingress,
                                                      Provenance)
        await get_cognitive_ingress().remember_told(
            sentence, Provenance(producer="teaching",
                                 source_id=self.source.name,
                                 source_type="USER_SUPPLIED"),
            blamed=[list(b) for b in (blamed or [])],
            origin=Origin.own("teaching"))

    #: Stripped before a read term is compared with a stated one. The reader
    #: renders an object with its article ("a device"); a source states the bare
    #: term ("device"), and they are the same term.
    _LEADING_DETERMINERS = ("a ", "an ", "the ")

    @classmethod
    def _bare(cls, term: Any) -> str:
        text = str(term or "").strip().lower()
        for determiner in cls._LEADING_DETERMINERS:
            if text.startswith(determiner):
                return text[len(determiner):].strip()
        return text

    @staticmethod
    def _fragments_of(term: str) -> set:
        """Every whole-word sub-span of a multi-word term, except the term."""
        words = term.split()
        if len(words) < 2:
            return set()
        return {" ".join(words[i:j])
                for i in range(len(words))
                for j in range(i + 1, len(words) + 1)} - {term}

    @classmethod
    def _drop_segmented_claims(cls, record: "TaughtRecord", claims: List[tuple]
                               ) -> Tuple[List[tuple], bool]:
        """Claims still about what the record is about, and whether any were cut.

        A claim is cut when its subject or its object is a whole-word FRAGMENT
        of the term the record STATES for that slot -- the reader having
        segmented a multi-word name it had no way to know was one name.

        BOTH ENDS, because the reader damages them differently and both were
        measured on WordNet. A coordinated SUBJECT is distributed ("A track and
        field is a diversion sport." -> `track isa diversion sport` AND `field
        isa diversion sport`); a coordinated OBJECT is TRUNCATED ("A jumping is
        a track and field." -> `jumping isa track`), which is worse in kind
        because nothing looks wrong about the claim that survives -- it is a
        well-formed edge to the wrong parent, and `isa` is walked transitively.

        Narrow on purpose: a gloss that says something about another term ("a
        pump is a device that moves fluid" -> `device moves fluid`) is not a
        fragment of either stated term and survives untouched.
        """
        subject_fragments = cls._fragments_of(
            str(getattr(record, "subject", "") or "").strip().lower())
        object_fragments = cls._fragments_of(cls._bare(getattr(record, "obj", "")))
        if not subject_fragments and not object_fragments:
            return claims, False
        kept = [c for c in claims
                if cls._bare(c[0]) not in subject_fragments
                and cls._bare(c[2] if len(c) > 2 else "") not in object_fragments]
        return kept, len(kept) != len(claims)

    async def _read(self, sentence: str
                    ) -> Tuple[List[Tuple[str, str, str, str, bool]], List[tuple]]:
        """Every claim a source's own sentence states, as facts carrying it,
        read by the one reader (`derived_reader`), and the word classes a
        refusal was attributed to -- none: constructions, not word classes,
        decide what reads.

        One sentence is not one claim: a definition states the kind and then
        says something about the kind. Each claim is taught with THE WHOLE
        SENTENCE as its surface, because that is what it was said in.

        Only what a telling states outright between named things is a claim,
        taken as a listener with memory at hand takes it
        (`derived_reader.heard_stated`): where a word names several things,
        memory is asked which was meant; a sentence whose meaning still cannot
        be told is not taught either way, because which one the source meant is
        not this pass's to guess.
        """
        from core.semantics.derived_reader import heard_stated
        return [(f.subject, f.relation, f.obj, sentence, f.positive)
                for f in await heard_stated(sentence)], []

    async def _flush(self) -> None:
        """Write what the pass believes. A flush that fails ends the pass: the
        beliefs it moved would be gone at the next start, and the pass would
        have reported them taught."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        await get_uncertainty_system().flush_pending_writes()


def quality_from_corroboration(weight: float, *, floor: float = 0.6,
                               cap: float = 0.95) -> float:
    """A crowd-sourced assertion's weight, as an evidence quality in [0,1].

    STATED, NOT INHERITED. Every teaching pass until now handed the substrate an
    unstated 0.9 for every fact regardless of how well attested it was, and that
    number became the prior of most of what the substrate believes. ConceptNet
    ships a weight on every assertion -- 1.0 for a single contributor, higher as
    independent sources corroborate -- and it was read by nothing.

    Logarithmic because corroboration has diminishing returns: the second source
    to agree is worth far more than the twentieth. `weight=1.0` maps to 0.75 (one
    real source: admissible, and well short of certain), 2.0 to ~0.84, and the
    heavily corroborated tail is capped so no crowd-sourced claim ever presents
    as near-certain.

    This curve is a JUDGEMENT and is written down so it can be argued with and
    recalibrated, which is precisely what an unstated default could never be.
    """
    if weight <= 0:
        return 0.0
    return min(cap, floor + 0.15 * math.log2(weight + 1.0))
