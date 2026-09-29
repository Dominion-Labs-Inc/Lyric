#!/usr/bin/env python3
"""Sources a teaching pass can read. Each READS A FORMAT and decides nothing.

A source yields `TaughtRecord`s and states its own support for each. It does not
choose a domain, a quality floor, how much of itself to take, or how any of it
reaches the substrate -- all of that belongs to `TeachingPass`, which is the one
owner of the policy. That split is what stops this becoming several pipelines
agreeing about one function again.

What a source DOES own is the meaning of its own numbers. ConceptNet's weight is
ConceptNet's; only it can say what a 2.0 means, so only it maps that to an
evidence quality. That is the same rule the evidence producers already follow
for perception: "the producer is the only party that knows how good its evidence
is, so it is the party that has to say".
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Sequence, Tuple

from core.learning.teaching import TaughtRecord, quality_from_corroboration
#: The store's own limit on how many words a concept name may have. Read
#: from the authority that enforces it rather than restated here — a
#: sense-qualified name is longer than a bare one and must still fit.
from core.semantics.cognitive_ingress import MAX_TERM_WORDS

logger = logging.getLogger(__name__)

#: ConceptNet and WordNet both tag a part of speech, and every one of them now
#: has somewhere to go. `r` (adverb) used to be DROPPED -- "no home", said the
#: comment that stood here -- which threw away 3,630 words WordNet knows the
#: class of, because a class could only be derived from a proposition's
#: subject/relation/object and an adverb never stands in one. Word classes are
#: taught into memory directly now, so an adverb is as learnable as a noun.
_POS_CLASS = {"n": "NOUN", "v": "VERB", "a": "ADJECTIVE", "s": "ADJECTIVE",
              "r": "ADVERB"}


#: The closed classes of English: finite, enumerable, and TOLD to the substrate
#: rather than compiled into it.
#:
#: These were frozensets inside `sentence_machine` -- a lexicon written in code.
#: That is a second authority beside memory: a wipe could not clear it, teaching
#: could not grow it, and no evidence could argue with it. The words are the
#: same; where they live is the whole point. Taught here, a determiner is
#: knowledge the substrate holds and can be asked about, like everything else it
#: knows.
CLOSED_CLASSES: Dict[str, Tuple[str, ...]] = {
    "COPULA": ("is", "are", "am", "was", "were", "be", "been", "being"),
    "DETERMINER": ("a", "an", "the", "this", "that", "these", "those",
                   "my", "your", "his", "her", "its", "our", "their",
                   "each", "every", "no", "any", "both", "either", "neither",
                   "another", "such", "what", "which", "whose"),
    "NEGATOR": ("not", "never", "n't", "nor", "none"),
    "PREPOSITION": (
        "about", "above", "across", "after", "against", "along", "alongside",
        "amid", "among", "amongst", "around", "as", "at", "atop", "before",
        "behind", "below", "beneath", "beside", "besides", "between", "beyond",
        "by", "concerning", "despite", "down", "during", "except", "for",
        "from", "in", "inside", "into", "like", "near", "of", "off", "on",
        "onto", "opposite", "out", "outside", "over", "past", "per",
        "regarding", "round", "since", "through", "throughout", "till", "to",
        "toward", "towards", "under", "underneath", "unlike", "until", "up",
        "upon", "versus", "via", "with", "within", "without"),
    "PRONOUN": ("i", "you", "he", "she", "it", "we", "they",
                "me", "him", "her", "us", "them",
                "mine", "yours", "hers", "ours", "theirs",
                "myself", "yourself", "himself", "herself", "itself",
                "ourselves", "yourselves", "themselves",
                "someone", "somebody", "something", "anyone", "anybody",
                "anything", "everyone", "everybody", "everything",
                "nobody", "nothing", "one", "who", "whom"),
    "RELATIVE": ("that", "which", "who", "whom", "whose", "where", "when"),
    "QUANTIFIER": ("some", "most", "many", "few", "several", "much", "all",
                   "every", "any", "enough", "plenty"),
    "MODAL": ("can", "could", "may", "might", "must", "shall", "should",
              "will", "would", "ought", "need", "dare"),
    "AUXILIARY": ("do", "does", "did", "have", "has", "had", "having"),
    "CONJUNCTION": ("and", "or", "but", "nor", "yet", "so"),
    "SUBORDINATOR": ("because", "although", "though", "unless", "while",
                     "whereas", "since", "if", "when", "whenever", "where",
                     "wherever", "after", "before", "until", "once", "whether",
                     "lest", "provided", "as", "that"),
    "INTERJECTION": ("yes", "no", "oh", "ah", "well", "hello", "goodbye",
                     "please", "thanks", "sorry", "ok", "okay"),
    "NUMERAL": ("zero", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten", "eleven", "twelve", "hundred",
                "thousand", "million", "billion", "first", "second", "third"),
    "PARTICLE": ("to", "up", "off", "out", "down", "away", "back", "over"),
    "PUNCTUATION": (".", ",", "?", "!", ";", ":", "'", '"', "-", "--",
                    "(", ")", "[", "]", "\u2014", "\u2013", "\u2026"),
}

#: What each mark DOES, said as a sentence. A class alone says a full stop is
#: punctuation; these say what it is FOR, which is the part the reader acts on
#: every time it decides where one claim ends.
PUNCTUATION_FACTS: Tuple[str, ...] = (
    "A full stop ends a sentence.",
    "A question mark ends a question.",
    "An exclamation mark ends an exclamation.",
    "A comma separates a clause.",
    "A semicolon joins two clauses.",
    "A colon introduces a list.",
    "An apostrophe marks a possessive.",
    "A quotation mark encloses speech.",
    "A hyphen joins two words.",
    "A dash breaks a sentence.",
    "A bracket encloses an aside.",
)


@dataclass
class ClosedClassSource:
    """The closed classes of English, said plainly.

    A source that READS A FORMAT, like every other -- the format here is a
    table, because closed classes are finite and nobody discovers them from a
    corpus. It states classes and no facts: there is no such thing as a
    taxonomy edge for `the`.
    """

    name: str = "closed-classes"
    quality: float = 0.95
    curated: bool = True

    def provenance(self):
        return _provenance("closed-classes", "english_closed_classes",
                           source_type="USER_SUPPLIED")

    def records(self) -> Iterator[TaughtRecord]:
        """What each punctuation mark is FOR, said in English and read."""
        for sentence in PUNCTUATION_FACTS:
            yield TaughtRecord(subject="", relation="", obj="",
                               quality=self.quality, sentence=sentence)

    def word_classes(self) -> Iterator[Tuple[str, str]]:
        for word_class, words in CLOSED_CLASSES.items():
            for word in words:
                yield (word, word_class)


@dataclass
class LessonSource:
    """A lesson a teacher wrote: sentences in the order they are said, each with what it means.

    The format is a JSON file: `name`, `quality`, `examples`, and `records`, each record a `sentence`, its
    `meaning` written as the reading engine writes one (`Meaning.to_dict`), and, where the sentence points, the
    `situation` that names what it points at. A lesson of English sets `examples`: its sentences show how English
    says things and state nothing about the world, so only how they are said is learned (`TaughtRecord.example`).
    A record may say otherwise for itself.
    """

    path: str
    curated: bool = True

    def __post_init__(self):
        with open(self.path, encoding="utf-8") as handle:
            self._lesson = json.load(handle)
        self.name = str(self._lesson.get("name") or os.path.basename(self.path))
        self.quality = float(self._lesson.get("quality", 0.95))
        self.examples = bool(self._lesson.get("examples", False))

    def provenance(self):
        return _provenance("lesson", self.name, source_type="USER_SUPPLIED")

    def records(self) -> Iterator[TaughtRecord]:
        from core.semantics.derived_reader import Meaning
        for record in self._lesson.get("records", ()):
            yield TaughtRecord(
                subject="", relation="", obj="",
                quality=float(record.get("quality", self.quality)),
                sentence=record["sentence"],
                meaning=Meaning.from_dict(record["meaning"]),
                situation=tuple(sorted((record.get("situation") or {}).items())),
                example=bool(record.get("example", self.examples)))


def _provenance(producer: str, source_id: str, source_type: str = "IMPORTED_KNOWLEDGE"):
    from core.semantics.cognitive_ingress import Provenance
    return Provenance(producer=producer, source_id=source_id,
                      source_type=source_type)



def _article(word: str) -> str:
    """`a` or `an` for a word, so a taught sentence is real English.

    THE ARTICLE IS NOT DECORATION. The substrate derives a word's class from the
    surface of a taught proposition, and `_has_article` is what separates a KIND
    from a PROPERTY there -- so a sentence written without one teaches the wrong
    class, and a triple written with no sentence at all teaches nothing but
    nouns.
    """
    return "an" if str(word or "")[:1].lower() in "aeiou" else "a"


def _states(subject: str, obj: str) -> str:
    """`pump`, `device` -> `A pump is a device.` -- the fact, said."""
    return f"{_article(subject).capitalize()} {subject} is {_article(obj)} {obj}."


# ── ConceptNet ──────────────────────────────────────────────────────────────

@dataclass
class ConceptNetSource:
    """The ConceptNet 5.7 assertions dump, streamed once, offline.

    THE PART OF SPEECH IS ON THE URI AND IS NOW KEPT. `/c/en/dog/n` carries it in
    the fifth segment, and both previous ConceptNet scripts read the fourth and
    dropped the fifth -- in a `_term()` whose own docstring printed the tag it
    was discarding. Measured on the dump: 75% of English `IsA` subjects carry
    one.

    THE WEIGHT IS ON THE SAME LINE AND IS NOW READ. It ran 0.5 to 4.47 on `IsA`
    and was ignored entirely, so `oxygen isa book` (a 0.50 dbpedia scrape)
    entered at the same standing as an assertion three independent sources
    agreed on.
    """

    path: str
    relations: Dict[str, str] = None            # ConceptNet relation -> substrate
    language: str = "en"
    name: str = "conceptnet"
    #: A CROWD GRAPH. Its `/r/IsA` carries `apple isa car` and
    #: `dog isa cuter_than_kid` alongside real hypernymy, so it may not supply
    #: the relations the reasoner walks transitively. `TeachingPass` enforces
    #: that; this is the source telling the truth about what it is.
    curated: bool = False

    #: Named relation sets, because WHICH relations to take is the decision
    #: ConceptNet actually forces, and it is not one decision.
    #:
    #: `apple isa car`, `18_foot_potato UsedFor intimidate_angry_leprechauns`,
    #: `123 MadeOf troll` and `abottle MadeOf glass` are all in here. So the
    #: noise is not confined to the taxonomy -- what the taxonomy has that the
    #: rest does not is TRANSITIVITY, and that is what turns one bad edge from
    #: one bad fact into every conclusion reachable through it.
    #:
    #: GRAMMAR is a different kind of claim altogether. `/r/FormOf` is
    #: morphology (`cats/n -> cat`), mechanically derived rather than asserted
    #: by contributors, so it does not carry jokes -- and 378,859 English edges
    #: of it is exactly the number and countability the renderer lacks: a noun
    #: with a plural form is a COUNT noun, one without is MASS. That is the gap
    #: behind "an andaman islands is found in a bay of bengal".
    RELATION_SETS = {
        # Morphology. Safe, mechanical, and the highest value per edge.
        "grammar": {"/r/FormOf": "form_of"},
        # World knowledge the substrate has almost none of. Crowd-noisy but
        # NON-transitive, so a bad edge stays one bad fact.
        "practical": {"/r/AtLocation": "at_location",
                      "/r/UsedFor": "used_for",
                      "/r/CapableOf": "capable_of",
                      "/r/PartOf": "part_of",
                      "/r/MadeOf": "made_of",
                      "/r/HasProperty": "has_property",
                      "/r/Causes": "causes"},
        # The taxonomy. REFUSED by `TeachingPass` unless explicitly overridden,
        # and named here so the refusal is a decision rather than an omission.
        "taxonomy": {"/r/IsA": "isa"},
    }
    DEFAULT_RELATIONS = RELATION_SETS["grammar"]

    def __post_init__(self):
        if self.relations is None:
            self.relations = dict(self.DEFAULT_RELATIONS)

    def provenance(self):
        return _provenance("conceptnet", "conceptnet_5.7.0")

    def _term(self, uri: str) -> Tuple[Optional[str], Optional[str]]:
        """`/c/en/hot_dog/n` -> `("hot dog", "NOUN")`.

        Returns the term AND the class, which is the whole difference from the
        version this replaces.
        """
        parts = uri.split("/")
        if len(parts) < 4 or parts[2] != self.language:
            return None, None
        term = parts[3].replace("_", " ").strip().lower()
        word_class = _POS_CLASS.get(parts[4]) if len(parts) > 4 else None
        return (term or None), word_class

    def records(self) -> Iterator[TaughtRecord]:
        if not os.path.exists(self.path):
            raise FileNotFoundError(
                f"ConceptNet dump not found at {self.path}. It is a one-time "
                f"download and this pass is offline; nothing is fetched here.")
        seen = set()
        with gzip.open(self.path, "rt", encoding="utf-8") as stream:
            for line in stream:
                columns = line.rstrip("\n").split("\t")
                if len(columns) < 5:
                    continue
                relation = self.relations.get(columns[1])
                if relation is None:
                    continue
                subject, subject_class = self._term(columns[2])
                obj, object_class = self._term(columns[3])
                if not subject or not obj or subject == obj:
                    continue
                if not subject[0].isalnum():
                    continue
                key = (subject, relation, obj)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    weight = float(json.loads(columns[4]).get("weight", 1.0))
                except Exception:
                    weight = 1.0
                classes = tuple(
                    (word, word_class)
                    for word, word_class in ((subject, subject_class),
                                             (obj, object_class))
                    if word_class and " " not in word and word.isalpha())
                yield TaughtRecord(subject=subject, relation=relation, obj=obj,
                                   quality=quality_from_corroboration(weight),
                                   word_classes=classes)


# ── WordNet ─────────────────────────────────────────────────────────────────

@dataclass
class WordNetSource:
    """WordNet's noun taxonomy and its own part-of-speech tags.

    A hand-built lexical resource, so its assertions are not crowd-sourced
    guesses and do not carry a per-assertion weight -- `quality` is stated once,
    for the resource, rather than invented per edge.
    """

    name: str = "wordnet"
    quality: float = 0.9
    #: Hand-built hypernymy. This is the resource the reasoning taxonomy is
    #: supposed to come from.
    curated: bool = True

    def provenance(self):
        return _provenance("wordnet", "wordnet_3.0")

    def _word_classes(self) -> Dict[str, str]:
        """`word -> CLASS` for every single alpha word with a CLEAR dominant class.

        A lemma is scored per part of speech by tagged-corpus frequency (falling
        back to how many senses carry it when nothing is tagged). The class with
        the most weight wins; a tie -- a word as much a noun as a verb -- is
        SKIPPED, so an ambiguous word is settled by reading rather than stamped
        here. That abstention is deliberate and load-bearing: measured against
        the 315 words bulk teaching had wrongly marked ADJECTIVE, WordNet has no
        clear class for 310 of them.
        """
        from collections import defaultdict
        from nltk.corpus import wordnet as wn

        weight: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for synset in wn.all_synsets():
            word_class = _POS_CLASS.get(synset.pos())
            if not word_class:
                continue
            for lemma in synset.lemmas():
                word = lemma.name().replace("_", " ").strip().lower()
                if " " in word or not word.isalpha():
                    continue
                # 0.01: a sense carrying no tagged occurrences still counts a little.
                weight[word][word_class] += lemma.count() + 0.01

        settled: Dict[str, str] = {}
        for word, by_class in weight.items():
            ranked = sorted(by_class.items(), key=lambda kv: kv[1], reverse=True)
            if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
                continue
            settled[word] = ranked[0][0]
        return settled

    def _ambiguous_names(self) -> set:
        """Names whose noun senses DISAGREE about what kind they are.

        Two synsets sharing a first lemma are only a problem when their parents
        differ: `bank.n.01` and `bank.n.09` are genuinely different kinds, while
        two senses that hang off the same parent lose nothing by sharing a node.
        So this is the exact set that needs qualifying, and nothing wider --
        8,498 of 67,186 names, carrying the 23,291 edges that were asserting
        several kinds at once.
        """
        from collections import defaultdict
        from nltk.corpus import wordnet as wn

        def first_lemma(synset) -> str:
            return synset.lemma_names()[0].replace("_", " ").strip().lower()

        senses = defaultdict(list)
        for synset in wn.all_synsets("n"):
            name = first_lemma(synset)
            if name:
                senses[name].append(synset)

        contested = set()
        for name, group in senses.items():
            if len(group) < 2:
                continue
            parents = {first_lemma(h) for s in group
                       for h in s.hypernyms() + s.instance_hypernyms()}
            if len(parents) > 1:
                contested.add(name)
        return contested

    def word_classes(self) -> Iterator[Tuple[str, str]]:
        """Every class WordNet settles, INCLUDING adverbs.

        `records()` states a class only for the two nouns in a taxonomy edge, so
        a verb, an adjective or an adverb that never appears in one was never
        stated at all. This is the source saying everything it knows about its
        own vocabulary."""
        return iter(self._word_classes().items())

    def records(self) -> Iterator[TaughtRecord]:
        from nltk.corpus import wordnet as wn

        classes = self._word_classes()
        ambiguous = self._ambiguous_names()

        def name_of(synset) -> str:
            """The name this SENSE is taught under.

            A synset's first lemma is its conventional name, and using it alone
            is what fused the taxonomy: `inheritance.n.01..04` are four kinds
            (an acquisition, a transferred property, a heredity, an attribute)
            and they all reduced to `inheritance`, which then inherited all four
            parents at once. Measured across WordNet's nouns, 8,498 names ended
            up asserting parents that disagree — and they are the COMMON words,
            the ones the rest of the taxonomy hangs off: `person` came out a kind
            of `grammatical_category` AND `human_body`; `man` a kind of
            `game_equipment` AND `island`.

            A sense whose name is contested is therefore taught QUALIFIED BY WHAT
            IT IS A KIND OF — `causal_agent person`, `grammatical_category
            person`. The qualifier goes FIRST because that is the form the
            identity authority already reads: `classify_qualified_name` treats
            `<qualifier>_<head>` as a SPECIALIZATION_OF the head (head-first is a
            different claim — `pressure_loss` is a loss, not a pressure). So the
            bare word still reaches every sense through `resolve_query`, and no
            sense inherits another's parents.

            Measured on this scheme: the 8,498 disagreeing names fall to 50, and
            84,061 of 84,427 edges survive.
            """
            name = synset.lemma_names()[0].replace("_", " ").strip().lower()
            if not name or name not in ambiguous:
                return name
            hypernyms = synset.hypernyms() + synset.instance_hypernyms()
            if not hypernyms:
                # Nothing to qualify BY. A contested name with no parent cannot
                # be told from its siblings, so it is not taught rather than
                # taught as one of them.
                return ""
            qualifier = hypernyms[0].lemma_names()[0].replace("_", " ").strip().lower()
            return f"{qualifier} {name}" if qualifier else ""

        def word_of(synset) -> str:
            """The word a sense is written with: its first lemma, whatever name it is taught under."""
            return synset.lemma_names()[0].replace("_", " ").strip()

        from core.semantics.derived_reader import Meaning, MeaningFact
        seen = set()
        for synset in wn.all_synsets("n"):
            child = name_of(synset)
            if not child or len(child.split()) > MAX_TERM_WORDS:
                # The store holds names of at most MAX_TERM_WORDS words, and a
                # qualified sense can exceed it. Shortening the identifier is not
                # available here -- the qualifier IS what tells the sense apart --
                # so the edge is dropped rather than taught under a name that
                # means something else. 363 of 84,427 edges, measured.
                continue
            for hypernym in synset.hypernyms() + synset.instance_hypernyms():
                parent = name_of(hypernym)
                if not parent or parent == child:
                    continue
                if len(parent.split()) > MAX_TERM_WORDS:
                    continue
                key = (child, parent)
                if key in seen:
                    continue
                seen.add(key)
                written = ((child, word_of(synset)), (parent, word_of(hypernym)))
                stated = tuple((word.lower(), classes[word.lower()])
                               for _, word in written if word.lower() in classes)
                if hypernym in synset.instance_hypernyms():
                    # A NAMED THING ("Paris", "Hussein") is said without an article, and no frame taught yet says
                    # a name so: its fact is taught, and its English waits for a lesson with names in it.
                    yield TaughtRecord(subject=child, relation="isa", obj=parent,
                                       quality=self.quality, word_classes=stated)
                    continue
                # WHAT IS SO, AND THE WORDS: the substrate says it through the
                # frames it was taught (`TeachingPass._said`), so the source
                # writes no English of its own.
                yield TaughtRecord(subject=child, relation="isa", obj=parent,
                                   quality=self.quality, word_classes=stated,
                                   meaning=Meaning("tell", (MeaningFact("isa", child, parent),)),
                                   words=tuple((name, word) for name, word in written if name != word))

            # THE DEFINITION, SAID AS A SENTENCE. The taxonomy edge above says
            # what a thing IS; WordNet's gloss says what it DOES, and that is
            # the only place a VERB ever appears in this source. Taught as a
            # sentence with no triple behind it, so it is READ or it is dropped
            # -- there is no fallback that could file a mis-parsed gloss as a
            # taxonomy edge.
            # THE GLOSS IS ABOUT ONE SENSE, so it is said of that sense. Said of
            # the bare word it would put the definitional edge straight back on
            # the fused node -- "A person is a human being." and "A person is a
            # grammatical category." are both WordNet glosses of `person`, and
            # admitting both is the collapse this method just took apart.
            gloss = (synset.definition() or "").strip().rstrip(".")
            if (gloss and len(gloss.split()) <= 24 and child
                    and len(child.split()) <= MAX_TERM_WORDS):
                yield TaughtRecord(
                    subject="", relation="", obj="", quality=self.quality,
                    sentence=f"{_article(child).capitalize()} {child} is {gloss}.")


# ── Wikidata ────────────────────────────────────────────────────────────────

@dataclass
class WikidataSource:
    """`subclass of` (P279) edges, from a cache fetched once.

    Hand-built like WordNet, and with no per-edge weight, so its quality is
    stated for the resource. Fetching is NOT this class's business: a source
    reads what it is given, and the cache is built by the script that owns the
    network call.
    """

    cache_path: str
    #: A cache may hold SEVERAL sections keyed by subject area
    #: (`{"mathematics": [...], "computer_science": [...]}`), because one fetch
    #: covers several root sets. Naming the section selects one; None takes
    #: every edge in the file.
    section: Optional[str] = None
    name: str = "wikidata"
    quality: float = 0.9
    #: `subclass of` (P279) is curated by editors, not crowd free text.
    curated: bool = True

    def provenance(self):
        return _provenance("wikidata", "wikidata_p279")

    def sections(self) -> Sequence[str]:
        """The sections this cache offers, so a caller can name one."""
        with open(self.cache_path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        return sorted(cached) if isinstance(cached, dict) else []

    def records(self) -> Iterator[TaughtRecord]:
        if not os.path.exists(self.cache_path):
            raise FileNotFoundError(
                f"Wikidata edge cache not found at {self.cache_path}; fetch it "
                f"first. A teaching pass does not reach the network.")
        with open(self.cache_path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        if isinstance(cached, dict):
            if self.section is not None:
                if self.section not in cached:
                    raise KeyError(
                        f"{self.cache_path} has no section {self.section!r}; "
                        f"it offers {sorted(cached)}")
                edges = cached[self.section]
            else:
                edges = [edge for part in cached.values() for edge in part]
        else:
            edges = cached
        seen = set()
        for edge in edges:
            if not isinstance(edge, (list, tuple)) or len(edge) < 2:
                continue
            child = str(edge[0]).strip().lower()
            parent = str(edge[1]).strip().lower()
            if not child or not parent or child == parent:
                continue
            key = (child, parent)
            if key in seen:
                continue
            seen.add(key)
            yield TaughtRecord(subject=child, relation="isa", obj=parent,
                               quality=self.quality)
