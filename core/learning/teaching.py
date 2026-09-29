#!/usr/bin/env python3
"""Teaching the substrate from a source. ONE pipeline, one owner of the policy.

There were seven teaching scripts. `learn_facts()` underneath them was already
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

import logging
import math
import random
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, Iterator, List, Optional, Protocol,
                    Sequence, Tuple)

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
#: `learn_facts` amortises its fan-out to the END of the batch -- that is what
#: makes a reference-sized teach practical -- so ONE call with 83,024 facts
#: admits everything and moves no belief until the last one lands. Two things
#: follow, and the second is the serious one: the fan-out then runs over 83,024
#: clauses at once (the documented failure "single giant `learn_facts` never
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

    def __post_init__(self):
        if self.meaning is None:
            if self.situation:
                raise ValueError("a situation binds the variables of a meaning; "
                                 "this record states none")
            if self.example:
                raise ValueError("an example of English is a sentence with its "
                                 "meaning; this record gives no meaning")
            if self.words:
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
    sampled: bool = False
    limit: Optional[int] = None
    seconds: float = 0.0

    def lines(self) -> List[str]:
        how = (f"a uniform sample of {self.limit:,} drawn across the whole source"
               if self.sampled and self.limit
               else (f"the first {self.limit:,} records" if self.limit
                     else "the whole source"))
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
            f"seconds           : {self.seconds:.1f}",
        ]


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
                 allow_uncurated_reasoning_edges: bool = False,
                 batch_size: int = DEFAULT_BATCH,
                 progress: Optional[Any] = None,
                 seed: int = 20260920) -> None:
        self.source = source
        self.domain = domain
        self.quality_floor = quality_floor
        self.limit = limit
        self.sample = sample
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
        import time

        started = time.time()
        report = Report(source=self.source.name, domain=self.domain)
        records = self._harvest(report)
        self._guard_reasoning_edges(records)

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
        # for every word, which the relation authority reads as "keep ISA", so a
        # missed warm would quietly reinstate the defect this ordering exists to
        # fix rather than failing loudly.
        try:
            from core.memory import get_memory_agent
            self._memory_for_classes = await get_memory_agent()
            await self._memory_for_classes.warm_word_classes()
        except Exception as error:
            logger.warning(
                "word classes could not be warmed (%s); copular predications "
                "will be typed as ISA by default this pass", error)
            self._memory_for_classes = None

        if records:
            # ONE call, for the whole harvest, through the one authority --
            # which fans out to beliefs, the lexicon, the domain and memory.
            # `quality` is PER PASS here because `learn_facts` takes one; where
            # a source states support per record, records are grouped by it so
            # no fact inherits another's standing.
            report.taught = await self._teach(learning, records, report)

        report.seconds = time.time() - started
        return report

    async def _teach(self, learning: Any, records: Sequence[TaughtRecord],
                     report: Report) -> Dict[str, int]:
        """Teach the harvest, grouped so each fact carries ITS OWN quality and
        polarity.

        `learn_facts` takes one quality and one polarity for a batch, and a corpus
        has neither: ConceptNet's weights run 0.5 to 4.47 on the same relation,
        and a sentence may deny as well as assert. Teaching a batch at a single
        number is exactly the unstated-0.9 problem in a new costume, so the
        harvest is bucketed by (quality, polarity) and each bucket is taught at
        its own.

        A record that carries its MEANING is not read. Its facts, bound to the
        situation it was said in, go into the buckets, and the sentence with its
        meaning is taught as a pattern after the facts (`learn_patterns`); both
        counts land on `report`.

        A bucket is (quality, polarity, whose): None is the model's; a speaker's
        name is that speaker's context (`_bucket_meaning`).
        """
        buckets: Dict[Tuple[float, bool, Optional[str]], List[Tuple[str, ...]]] = {}
        patterns: Dict[float, List[Tuple[str, Any]]] = {}
        meanings = {"bound": 0, "speaker_context": 0, "no_speaker": 0, "open": 0, "not_told": 0,
                    "rule": 0, "rule_not_held": 0, "alternative": 0, "example": 0, "said": 0, "not_said": 0}
        rules: List[Tuple[float, Any, Any, str, Optional[str]]] = []
        read_claims = 0
        unread = 0
        for record in records:
            quality = round(float(record.quality), 3)
            if record.meaning is not None:
                sentence = record.sentence
                if not sentence:
                    # SAID, NOT WRITTEN: through the frames taught, in the source's words. What nothing taught says
                    # teaches no English, and its facts are still the source's to state.
                    sentence = self._said(record)
                    meanings["said" if sentence else "not_said"] += 1
                if sentence:
                    patterns.setdefault(quality, []).append((sentence, record.meaning))
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
            claims, blamed = (self._read(record.sentence) if record.sentence
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
        for (quality, positive, speaker), facts in sorted(
                buckets.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")):
            for start in range(0, len(facts), self.batch_size):
                chunk = facts[start:start + self.batch_size]
                # `actor` is whose these facts are: None, the model's; a speaker,
                # their context (the learning authority's router keeps it there).
                counts = await learning.learn_facts(
                    chunk, provenance=provenance, domain=self.domain,
                    quality=quality, positive=positive, actor=speaker)
                for key, value in (counts or {}).items():
                    totals[key] = totals.get(key, 0) + int(value)
                # FLUSH PER BATCH. Belief writes are fire-and-forget; without
                # this the count does not climb during a run and there is no
                # way to tell a slow pass from a wedged one.
                await self._flush()
                done += len(chunk)
                if self.progress:
                    self.progress(done, len(records), totals)

        # THE RULES, after the facts, through the same authority the conversation holds a told rule through.
        for quality, condition, then, sentence, whose in rules:
            await learning.learn_rule(
                {"subject": condition.subject, "relation": condition.relation, "obj": condition.obj,
                 "positive": condition.positive},
                {"subject": then.subject, "relation": then.relation, "obj": then.obj,
                 "positive": then.positive},
                surface=sentence, provenance=provenance, domain=self.domain, actor=whose, quality=quality)
        if rules:
            await self._flush()

        # THE PATTERNS, after the facts they state. How English said each thing
        # is language knowledge, taught through the same authority; English is
        # its domain, whatever domain the lesson's facts belong to.
        taught_patterns: Dict[str, int] = {}
        for quality, pairs in sorted(patterns.items()):
            counts = await learning.learn_patterns(
                pairs, provenance=provenance, quality=quality)
            for key, value in (counts or {}).items():
                taught_patterns[key] = taught_patterns.get(key, 0) + int(value)
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
        written = Meaning(record.meaning.act, facts, record.meaning.asked)
        view = live_view()
        # The words this pair teaches are written as the source writes them; a concept already held is said as it
        # is held ("tools" for `tool`).
        wanted = [tuple(p.text.lower() for p in form_of(str(term).replace("_", " ")))
                  for term in {t for f in facts for t in (f.subject, f.obj)}
                  if not is_variable(term) and not view.lexicals_with_value(term)]
        for sentence in say(written, view):
            pieces = tuple(p.text.lower() for p in form_of(sentence))
            if all(any(pieces[i:i + len(w)] == w for i in range(len(pieces) - len(w) + 1)) for w in wanted):
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
        if record.meaning.act != "tell":
            meanings["not_told"] += len(record.meaning.facts)
            return
        situation = dict(record.situation)
        speaker = situation.get("?speaker")
        if record.meaning.condition:
            # A CONDITIONAL STATES NO FACT OUTRIGHT: what it says holds when its condition does. It is held as a
            # rule, one fact a side, as a told rule is held; a side of several facts, or one still naming an unknown,
            # is counted, not held.
            bound = dict(zip(record.meaning.facts, record.meaning.bound(situation)))
            condition = [bound[f] for f in record.meaning.condition]
            then = [bound[f] for f in record.meaning.asserted]
            if len(condition) != 1 or len(then) != 1 or any(
                    is_variable(t) for f in condition + then for t in f.terms()):
                meanings["rule_not_held"] += 1
                return
            situational = any(t in SITUATION_VARIABLES for f in record.meaning.facts for t in f.terms())
            if situational and not speaker:
                meanings["no_speaker"] += 1
                return
            rules.append((quality, condition[0], then[0], sentence, speaker if situational else None))
            meanings["rule"] += 1
            return
        for said, fact in zip(record.meaning.facts, record.meaning.bound(situation)):
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
                state(word, word_class, self.source.quality)
        for record in records:
            for word, word_class in record.word_classes or ():
                state(word, word_class, record.quality)
        return stated

    async def _teach_word_classes(self, learning: Any,
                                  stated: Dict[Tuple[str, str], float]) -> Dict[str, int]:
        """Teach the stated classes grouped by standing, each group at ITS
        quality (`learn_word_classes` takes one per call, as `learn_facts`
        does), and add up what each group did."""
        buckets: Dict[float, List[Tuple[str, str]]] = {}
        for pair, quality in stated.items():
            buckets.setdefault(round(quality, 3), []).append(pair)
        totals: Dict[str, int] = {}
        for quality, pairs in sorted(buckets.items()):
            counts = await learning.learn_word_classes(
                pairs, provenance=self.source.provenance(), quality=quality)
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
        try:
            return agent.word_classes(word)
        except Exception as error:
            logger.debug("word classes for %r unreadable: %s", word, error)
            return {}

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
        try:
            from core.memory import Origin
            from core.semantics.cognitive_ingress import (get_cognitive_ingress,
                                                          Provenance)
            await get_cognitive_ingress().remember_told(
                sentence, Provenance(producer="teaching",
                                     source_id=self.source.name,
                                     source_type="USER_SUPPLIED"),
                blamed=[list(b) for b in (blamed or [])],
                origin=Origin.own("teaching"))
        except Exception as error:
            logger.debug("could not record an unread teaching sentence: %s", error)

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

    def _read(self, sentence: str
              ) -> Tuple[List[Tuple[str, str, str, str, bool]], List[tuple]]:
        """Every claim a source's own sentence states, as facts carrying it,
        read by the one reader (`derived_reader`), and the word classes a
        refusal was attributed to -- none: constructions, not word classes,
        decide what reads.

        One sentence is not one claim: a definition states the kind and then
        says something about the kind. Each claim is taught with THE WHOLE
        SENTENCE as its surface, because that is what it was said in.

        Only what a telling states outright between named things is a claim
        (`derived_reader.stated`): a sentence read to more than one meaning is
        not taught either way, because which one the source meant is not this
        pass's to decide.
        """
        from core.semantics.derived_reader import stated
        return [(f.subject, f.relation, f.obj, sentence, f.positive) for f in stated(sentence)], []

    async def _flush(self) -> None:
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        try:
            await get_uncertainty_system().flush_pending_writes()
        except Exception as error:      # a flush failing must not lose the pass
            logger.debug("teaching flush skipped: %s", error)


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
