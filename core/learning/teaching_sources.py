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
    """All of WordNet: every word it holds, in every part of speech, each sense it names, and what it says of each.

    A hand-built lexical resource, so its assertions are not crowd-sourced
    guesses and do not carry a per-assertion weight -- `quality` is stated once,
    for the resource, rather than invented per edge.

    What it teaches, each sense under the name `_sense_names` gives it:
      * what a thing is a kind of (`isa`), and what a named thing is an instance of (`instance_of`), for nouns
        and verbs;
      * what a thing is part of (`part_of`), a member of (`member_of`) and made of (`made_of`);
      * opposites (`antonym_of`), and the adjectives a satellite is like (`similar_to`);
      * what a verb's doing requires (`requires`, WordNet's entailment) and causes (`causes`);
      * every word a sense is written with, not only its first: "bank" for the financial institution as well as
        for the slope;
      * the word class of every word it settles (`word_classes`).
    A fact a frame the substrate was taught can say carries its meaning and its words, so it teaches English as
    well as the fact; the rest is taught as the fact alone until a lesson teaches the English for it.
    """

    name: str = "wordnet"
    quality: float = 0.9
    #: Hand-built hypernymy. This is the resource the reasoning taxonomy is
    #: supposed to come from.
    curated: bool = True
    #: Where the lessons' teacher states which sense each lesson word is used in (`stated_senses`); the lessons'
    #: own statement when not given.
    senses_path: Optional[str] = None
    #: Offer each definition as a sentence with no meaning given, read or dropped. Off unless asked: read so, a
    #: definition costs seconds and about one in ten reads at all, so all of WordNet's 64,497 would take days and
    #: teach little. A definition is taught once, with its meaning, when its meaning is given.
    definitions: bool = False

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

        Worked out once for the source: WordNet reads each tagged count from its files, and a pass asks for the
        classes more than once.
        """
        if "_classes" in self.__dict__:
            return self.__dict__["_classes"]
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
        self.__dict__["_classes"] = settled
        return settled

    @staticmethod
    def _written(lemma_name: str) -> str:
        return lemma_name.replace("_", " ").strip()

    @staticmethod
    def _ordered(related) -> list:
        """WordNet's related senses in one order every time. NLTK keeps a synset's pointers in a set, so the order
        it hands them over in changed from one process to the next, and with it which qualifier a sense was named
        by and which side of an opposite was taught: the same source taught a different harvest in each process."""
        return sorted(set(related), key=lambda item: item.name() if hasattr(item, "name") else str(item))

    @classmethod
    def _qualifiers(cls, synset) -> list:
        """What a sense can be told apart by, most telling first: what it is a kind of (or an instance of); for an
        adjective, the head adjective it is like, then the attribute it is a value of; for an adverb, the
        adjective it is made from; then the senses WordNet groups it with or refers to."""
        order = cls._ordered
        return (order(synset.hypernyms()) + order(synset.instance_hypernyms()) + order(synset.similar_tos())
                + order(synset.attributes())
                + order(p.synset() for lemma in synset.lemmas() for p in lemma.pertainyms())
                + order(synset.verb_groups()) + order(synset.also_sees()))

    def _sense_names(self) -> Dict[Any, str]:
        """The name each SENSE is taught under, synset by synset; "" for one that cannot be told apart from the
        other senses of its word, and is not taught.

        A word names several things, and each is its own concept: "fish" names an animal and a food, "person" a
        human being, a human body and a grammatical category. A synset's first word alone named them all, and
        that fused the taxonomy: `inheritance.n.01..04` are four kinds (an acquisition, a transferred property, a
        heredity, an attribute) and all reduced to `inheritance`, which then inherited all four parents at once.
        Measured across WordNet's nouns, 8,498 names asserted parents that disagree, and they are the COMMON
        words: `person` came out a kind of `grammatical_category` AND `human_body`.

        So where a word's senses in one part of speech disagree about what they are, THE SENSE THE WORD NAMES
        MOST OFTEN is named by the word itself: by tagged use, then by WordNet's own order of senses, which is by
        frequency. That is the sense an everyday word means, and the one English lessons taught under the same
        name ("fish", the animal), so what the lessons taught and what WordNet says of it are one concept. Each
        OTHER sense is named by what it is first a kind of, before its word ("food fish", "grammatical category
        person"), which is the form the identity authority reads (`classify_qualified_name`). A qualified name
        never takes a name WordNet gives a sense of its own ("food fish" is a fish kept for food, `food_fish.n.01`;
        the food sense of "fish" is then "solid food fish"), nor another sense's: the next qualifier is tried. A
        word's senses in different parts of speech share the word's name where each is its own part's most
        frequent sense ("open" the act and "open" the state), as the lessons hold them.
        Worked out once for the source.
        """
        if "_names" in self.__dict__:
            return self.__dict__["_names"]
        from collections import defaultdict
        from nltk.corpus import wordnet as wn

        def name_of(synset) -> str:
            return self._written(synset.lemma_names()[0]).lower()

        def part(synset) -> str:
            return "a" if synset.pos() == "s" else synset.pos()

        groups: Dict[Tuple[str, str], list] = defaultdict(list)
        names: Dict[Any, str] = {}
        for synset in wn.all_synsets():
            # A NUMBER IS NAMED BY ITS VALUE, as the lessons name numbers ("1", "1000000000000"): WordNet writes
            # `trillion.n.03` "trillion" first and "1000000000000" among its words, and named by the word it would
            # be a second concept beside the number the lessons taught.
            value = next((lemma for lemma in synset.lemma_names() if lemma.isdigit()), None)
            if value is not None:
                names[synset] = str(int(value))
                continue
            name = name_of(synset)
            if name:
                groups[(part(synset), name)].append(synset)
        # THE SENSES THE LESSONS USE THEIR WORDS IN, as their teacher states them (`stated_senses`): such a sense is
        # named by the lessons' word, whatever word WordNet writes it with first ("say" is WordNet's `state.v.01`),
        # and every other sense of that word is named apart. A word the lessons use for none of WordNet's senses
        # ("Tom", a person) leaves every WordNet sense of it named apart.
        stated = self.stated_senses()
        for synset in (s for s in stated.values() if s is not None):
            own = groups.get((part(synset), name_of(synset)))
            if own and synset in own:
                own.remove(synset)
        taken = {name for _, name in groups} | {word for _, word in stated} | set(names.values())
        qualify: list = []
        for (pos, name), senses in sorted(groups.items()):
            if (pos, name) in stated:
                meant = stated[(pos, name)]
                if meant is not None:
                    names[meant] = name
                qualify.extend((name, synset) for synset in senses)
                continue
            if not senses:
                continue
            kinds = {name_of(q) for s in senses for q in self._qualifiers(s)}
            if len(senses) < 2 or len(kinds) < 2:
                for synset in senses:
                    names[synset] = name
                continue
            order = {s: i for i, s in enumerate(wn.synsets(senses[0].lemma_names()[0]))}
            # Most tagged first; then a thing's common name before a person's or a place's ("crane" the bird or the
            # machine, not the writer Stephen Crane, when none was tagged); then WordNet's order, by frequency.
            ranked = sorted(senses, key=lambda s: (-s.lemmas()[0].count(), s.lemma_names()[0][:1].isupper(),
                                                   order.get(s, len(order)), s.name()))
            names[ranked[0]] = name
            qualify.extend((name, synset) for synset in ranked[1:])
        for (pos, word), meant in stated.items():
            if meant is not None and meant not in names:
                names[meant] = word
        for name, synset in qualify:
            names[synset] = ""
            for qualifier in self._qualifiers(synset):
                for lemma in qualifier.lemma_names():
                    word = self._written(lemma).lower()
                    candidate = f"{word} {name}"
                    if word == name or len(candidate.split()) > MAX_TERM_WORDS or candidate in taken:
                        continue
                    names[synset] = candidate
                    taken.add(candidate)
                    break
                if names[synset]:
                    break
        self.__dict__["_names"] = names
        return names

    def stated_senses(self) -> Dict[Tuple[str, str], Any]:
        """`(part of speech, word) -> synset` (None: no WordNet sense) for the words the English lessons use in a
        sense other than the one WordNet's tagged text names most often, as the lessons' teacher states them
        (`data/lessons/senses.json`). Empty when there is no such statement."""
        if "_stated" in self.__dict__:
            return self.__dict__["_stated"]
        from pathlib import Path
        from nltk.corpus import wordnet as wn
        path = Path(self.senses_path) if self.senses_path else \
            Path(__file__).resolve().parents[2] / "data" / "lessons" / "senses.json"
        stated: Dict[Tuple[str, str], Any] = {}
        if path.exists():
            for key, synset in json.loads(path.read_text())["senses"].items():
                word, pos = key.rsplit("|", 1)
                stated[(pos, word.strip().lower())] = wn.synset(synset) if synset else None
        self.__dict__["_stated"] = stated
        return stated

    def usage(self) -> Iterator[Tuple[str, str, int]]:
        """How often each word was met naming each sense, in the text WordNet's senses were tagged in (SemCor, the
        Brown corpus): `(word, sense name, times)`, for every word met at least once. What a person learns from
        hearing English used, given as the count of real uses: "fish" met naming the animal 12 times and the
        food 3; "person" naming a human being 6,833 times. Read by the listener as how often a word names each
        thing (`derived_reader.meant`)."""
        from nltk.corpus import wordnet as wn
        names = self._sense_names()
        met: Dict[Tuple[str, str], int] = {}
        for synset in wn.all_synsets():
            name = names.get(synset, "")
            if not name or len(name.split()) > MAX_TERM_WORDS:
                continue
            for lemma in synset.lemmas():
                times = lemma.count()
                if times > 0:
                    # Senses that share a name (they do not disagree about what they are) are one thing, met as often
                    # as all of them were.
                    key = (self._written(lemma.name()), name)
                    met[key] = met.get(key, 0) + times
        for (word, name), times in met.items():
            yield word, name, times

    def word_classes(self) -> Iterator[Tuple[str, str]]:
        """Every class WordNet settles, INCLUDING adverbs.

        `records()` states a class only for the words in a fact, so a verb, an adjective or an adverb that never
        appears in one was never stated at all. This is the source saying everything it knows about its own
        vocabulary."""
        return iter(self._word_classes().items())

    def records(self) -> Iterator[TaughtRecord]:
        from nltk.corpus import wordnet as wn
        from core.semantics.derived_reader import Meaning, MeaningFact

        classes = self._word_classes()
        names = self._sense_names()
        order = self._ordered
        seen = set()
        opposites = set()

        def fits(name: str) -> bool:
            # The store holds names of at most MAX_TERM_WORDS words. A name past it is not taught: shortening it
            # would name something else.
            return bool(name) and len(name.split()) <= MAX_TERM_WORDS

        def record(relation: str, subject, subject_word: str, obj, obj_word: str, *, said: bool):
            """One fact between two senses, taught once. `said`: a frame the substrate was taught says this
            relation between things of these parts of speech, so the fact carries its meaning and its words and
            teaches its English too (`TeachingPass._said`); otherwise it is the fact alone."""
            child, parent = names.get(subject, ""), names.get(obj, "")
            if not (fits(child) and fits(parent)) or child == parent:
                return None
            if relation in ("isa", "instance_of") and parent.isdigit():
                # NOTHING IS A 7: WordNet files a set of seven under `seven`, but a number is no kind; that a set
                # has seven members is a count, which WordNet does not state as one.
                return None
            key = (child, relation, parent, subject_word.lower(), obj_word.lower() if said else "")
            if key in seen:
                return None
            seen.add(key)
            written = ((child, subject_word), (parent, obj_word))
            stated = tuple((word.lower(), classes[word.lower()]) for _, word in written if word.lower() in classes)
            if not said:
                return TaughtRecord(subject=child, relation=relation, obj=parent, quality=self.quality,
                                    word_classes=stated)
            # WHAT IS SO, AND THE WORDS: the substrate says it through the frames it was taught, so the source
            # writes no English of its own.
            return TaughtRecord(subject=child, relation=relation, obj=parent, quality=self.quality,
                                word_classes=stated,
                                meaning=Meaning("tell", (MeaningFact(relation, child, parent),)),
                                words=tuple((name, word) for name, word in written if name != word))

        for synset in wn.all_synsets():
            if not fits(names.get(synset, "")):
                continue
            pos = "a" if synset.pos() == "s" else synset.pos()
            words = list(dict.fromkeys(self._written(lemma) for lemma in synset.lemma_names()))
            word = words[0]
            found = []
            for hypernym in order(synset.hypernyms()):
                # What a thing is a kind of, said for a noun through "A robin is a bird."; a verb's kind waits for a
                # lesson that says one ("To stroll is to walk.").
                found.append(record("isa", synset, word, hypernym, self._written(hypernym.lemma_names()[0]),
                                    said=pos == "n"))
                # EVERY WORD THE SENSE IS WRITTEN WITH: "auto" and "automobile" name the car as "car" does, and are
                # learned saying the same fact.
                if pos == "n":
                    for other in words[1:]:
                        found.append(record("isa", synset, other, hypernym,
                                            self._written(hypernym.lemma_names()[0]), said=True))
            for hypernym in order(synset.instance_hypernyms()):
                # A NAMED THING ("Paris", "Hussein") is said without an article, and no frame taught yet says a name
                # so: its fact is taught, and its English waits for a lesson with names in it.
                found.append(record("instance_of", synset, word, hypernym,
                                    self._written(hypernym.lemma_names()[0]), said=False))
            for part_of, kind in ((order(synset.part_meronyms()), "part_of"),
                                  (order(synset.member_meronyms()), "member_of")):
                for piece in part_of:
                    # "A wheel is part of a car." "A player is a member of a team."
                    found.append(record(kind, piece, self._written(piece.lemma_names()[0]), synset, word,
                                        said=True))
            for material in order(synset.substance_meronyms()):
                # "A table is made of wood."
                found.append(record("made_of", synset, word, material, self._written(material.lemma_names()[0]),
                                    said=True))
            for head in order(synset.similar_tos()):
                found.append(record("similar_to", synset, word, head, self._written(head.lemma_names()[0]),
                                    said=False))
            for needed in order(synset.entailments()):
                found.append(record("requires", synset, word, needed, self._written(needed.lemma_names()[0]),
                                    said=False))
            for caused in order(synset.causes()):
                found.append(record("causes", synset, word, caused, self._written(caused.lemma_names()[0]),
                                    said=False))
            for lemma in synset.lemmas():
                for opposite in order(lemma.antonyms()):
                    # An opposite is one fact, whichever side it is found from. "Hot is the opposite of cold." says
                    # it of adjectives; of the rest, the fact alone.
                    pair = frozenset((names.get(opposite.synset(), ""), names.get(synset, "")))
                    if pair in opposites:
                        continue
                    opposites.add(pair)
                    found.append(record("antonym_of", synset, self._written(lemma.name()), opposite.synset(),
                                        self._written(opposite.name()), said=pos == "a"))
            for taught in found:
                if taught is not None:
                    yield taught

            # THE DEFINITION, SAID AS A SENTENCE. The facts above say what a thing IS; WordNet's gloss says what
            # it DOES. Taught as a sentence with no triple behind it, so it is READ or it is dropped -- there is no
            # fallback that could file a mis-parsed gloss as a taxonomy edge.
            # THE GLOSS IS ABOUT ONE SENSE, and a sentence written with the word is read as the sense the word
            # names most often. So a gloss is said only of the sense the word itself names; another sense's waits
            # for its meaning to be given with it.
            gloss = (synset.definition() or "").strip().rstrip(".")
            if (self.definitions and pos == "n" and gloss and len(gloss.split()) <= 24
                    and names[synset] == word.lower()):
                yield TaughtRecord(
                    subject="", relation="", obj="", quality=self.quality,
                    sentence=f"{_article(word).capitalize()} {word} is {gloss}.")


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
