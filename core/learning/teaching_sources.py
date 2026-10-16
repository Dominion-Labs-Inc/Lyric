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
from typing import Any, Dict, FrozenSet, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

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



class PronunciationSource:
    """How words are said, as the CMU Pronouncing Dictionary writes them (`nltk`'s `cmudict`; 123,455 words, each
    with the phones of every way of saying it, stress marked), with how often real text uses each word (the Brown
    corpus), which the ear weighs a word by when it divides speech into words.

    A source that READS A FORMAT, like every other. It states pronunciations and no facts. `words`: the words to
    state, lowercased (the words a lesson or the reader holds); every word the dictionary holds when None."""

    name: str = "cmudict"
    quality: float = 0.9
    curated: bool = True

    def __init__(self, words: Optional[Iterable[str]] = None):
        self.words = None if words is None else {str(w).strip().lower() for w in words if str(w).strip()}

    def provenance(self):
        return _provenance("cmudict", "cmudict_0.7b", source_type="IMPORTED_KNOWLEDGE")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def pronunciations(self) -> Iterator[Tuple[str, str, int]]:
        from collections import Counter
        from nltk.corpus import brown, cmudict
        said = cmudict.dict()
        used = Counter(w.lower() for w in brown.words())
        for word in sorted(said if self.words is None else self.words & set(said)):
            for way in said[word]:
                yield (word, " ".join(way), used[word])

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


@dataclass
class ListeningSource:
    """What the listener's evidence is worth, counted on the lessons of English a teacher wrote (`--source
    listening`): each lesson's sentences read, the meanings each read to weighed as the listener weighs them, and
    counted by whether each was the one the lesson says was meant (`derived_reader.listening_counts`). A person learns
    what to listen for from being told what was meant. Nothing is taught but the counts: no records."""

    paths: Tuple[str, ...] = ()
    name: str = "listening"
    quality: float = 0.95
    curated: bool = True
    vocabulary_only: bool = True

    def __post_init__(self):
        if not self.paths:
            from pathlib import Path
            self.paths = tuple(str(p) for p in sorted(Path("data/lessons").glob("english_[0-9][0-9].json")))

    def provenance(self):
        return _provenance("lesson", "english lessons", source_type="USER_SUPPLIED")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def listening_pairs(self) -> Iterator[Tuple[str, Any]]:
        """Every sentence of the lessons with the meaning it was taught to have, in the lessons' order."""
        from core.semantics.derived_reader import Meaning
        for path in self.paths:
            with open(path, encoding="utf-8") as handle:
                for record in json.load(handle).get("records", ()):
                    yield record["sentence"], Meaning.from_dict(record["meaning"])


def _term_words(name: str) -> int:
    """How many words the store counts in a name, as its door counts them (`cognitive_ingress.admissible`): a hyphen
    parts words too, so "raiders-front" is two. Counted by spaces, "islamic great eastern raiders-front" was taught
    as four words and refused at the door as five."""
    from core.semantics.cognitive_ingress import normalize_term
    return len(normalize_term(name).replace("_", " ").split())


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
                # A record whose weight does not read is a corrupt record, and
                # read as 1.0 it was taught as a single contributor's word.
                weight = float(json.loads(columns[4]).get("weight", 1.0))
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
      * the senses each sense's definition is written with (`defined_with`, `_definition_links`): the bank that
        keeps money is defined with money, eating with food;
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
    #: Where the countability lexicon is (`_becl`); NLTK's data when not given.
    becl_path: Optional[str] = None
    #: Offer each definition as a sentence with no meaning given, read or dropped. Off unless asked: read so, a
    #: definition costs seconds and about one in ten reads at all, so all of WordNet's 64,497 would take days and
    #: teach little. A definition is taught once, with its meaning, when its meaning is given.
    definitions: bool = False
    #: Teach only these senses (`peoples.n.01`): every fact one of them is in, either side. For a sense taught under
    #: a name the door wrote wrong, taught again once the door writes it right; the rest of WordNet as it was.
    senses: Tuple[str, ...] = ()
    #: Teach only the senses of these parts of speech ("v", "a"): every fact a sense of them states, and every
    #: sentence it is said in. A store taught WordNet whole before its verbs and adjectives were said is taught them
    #: so, without saying every noun again.
    parts: Tuple[str, ...] = ()

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

    def _plurals(self) -> Dict[str, Tuple[str, ...]]:
        """`word -> its plurals` that no change of its ending makes, as WordNet lists them (`noun.exc`): "mice" for
        "mouse", "wolves" for "wolf", "criteria" for "criterion". Read once for the source.

        A FORM REAL TEXT WRITES OTHERWISE IS NOT ONE. The list holds "crying" and "cryings" for "cry", and taught,
        they said "Crying are utterances.". A form is kept where the Brown corpus writes it as a plural, or where
        Brown writes neither it nor any plural of its word ("stemmata"): not where Brown writes it only as
        something else, nor where Brown writes the word's plural otherwise ("cries")."""
        if "_plural_forms" in self.__dict__:
            return self.__dict__["_plural_forms"]
        from nltk.corpus import wordnet as wn

        written_as, written = self._brown_plurals()
        forms: Dict[str, set] = {}
        for line in wn.open("noun.exc"):
            words = line.split()
            if len(words) < 2 or "_" in words[0]:
                continue
            for base in words[1:]:
                if "_" in base or base == words[0]:
                    continue
                plural = words[0]
                if plural in written_as.get(base, {}) or (plural not in written and not written_as.get(base)):
                    forms.setdefault(base, set()).add(plural)
        plurals = {base: tuple(sorted(made)) for base, made in forms.items()}
        self.__dict__["_plural_forms"] = plurals
        return plurals

    def _brown_plurals(self) -> Tuple[Dict[str, Dict[str, int]], frozenset]:
        """How the Brown corpus writes each noun in the plural, `(word -> {plural: times}, every word it writes)`: a
        word tagged plural (`NNS`), under each noun WordNet takes it to be a form of ("women", `woman`). Read once."""
        if "_brown_plural_forms" not in self.__dict__:
            from collections import Counter
            from nltk.corpus import brown, wordnet as wn
            plural_of: Dict[str, Counter] = {}
            written = set()
            for word, tag in brown.tagged_words():
                word = word.lower()
                written.add(word)
                if tag.split("-")[0] != "NNS" or not word.isalpha():
                    continue
                for base in wn._morphy(word, wn.NOUN):
                    plural_of.setdefault(base, Counter())[word] += 1
            self.__dict__["_brown_plural_forms"] = ({base: dict(c) for base, c in plural_of.items()},
                                                    frozenset(written))
        return self.__dict__["_brown_plural_forms"]

    def _plural_written(self, word: str) -> Optional[str]:
        """The plural of a one-word noun as it is written: the one form no change makes, where WordNet lists one
        alone; else the form real text writes most ("women" for "woman", which WordNet makes by a rule and lists
        nowhere); None where neither says."""
        made = self._plurals().get(word, ())
        if len(made) == 1:
            return made[0]
        if made or " " in word:
            return None
        forms = self._brown_plurals()[0].get(word)
        return max(sorted(forms), key=forms.get) if forms else None

    #: The sounds a plural takes "es" after ("boxes", "churches", "judges"): CMU's phones for s, z, sh, zh, ch, j.
    _HISSES = frozenset({"S", "Z", "SH", "ZH", "CH", "JH"})

    def _pronounced(self) -> Dict[str, list]:
        """The CMU Pronouncing Dictionary (`PronunciationSource`'s): every word it writes, with the phones of each
        way of saying it. Read once."""
        if "_cmu" not in self.__dict__:
            from nltk.corpus import cmudict
            self.__dict__["_cmu"] = cmudict.dict()
        return self.__dict__["_cmu"]

    def _spelled_plural(self, word: str) -> Optional[str]:
        """The plural of a noun no list and no text writes, as English writes it, by the evidence nearest it:
          1. a form the CMU Pronouncing Dictionary writes, of the ones English could make: a compound of a noun
             with a plural of its own ("headsman" ends in "man": "headsmen"; "grandchildren"), "es" or "s"
             ("stomachs", "churches"), "ies", one "z" doubled ("quizzes");
          2. else, and not for a word ending in a consonant and "s", mostly a plural already ("spareribs"), as its
             last sound asks where CMU says the word: "es" after a hiss ("boxes"), else "s";
          3. else as its letters settle it: a compound, "es" after "s", "x", "zz", "sh" or "tch", "ies" after a
             consonant and "y", else "s". Not where they do not settle it: "ch" ("stomachs", "beaches"), a consonant
             and "o" ("heroes", "pianos") and one "z".
        A compound's plural that is a noun of its own ("dolmen" is no plural of "dolman") is none. Kept only where
        WordNet's own morphology reads the form back as the word."""
        from nltk.corpus import wordnet as wn
        if not word.isalpha() or word != word.lower() or len(word) < 3:
            return None
        said = self._pronounced()
        if "_noun_lemmas" not in self.__dict__:
            self.__dict__["_noun_lemmas"] = frozenset(wn.all_lemma_names(pos="n"))
        lemmas = self.__dict__["_noun_lemmas"]
        compound = None
        for size in range(len(word) - 3, 2, -1):
            head, base = word[:-size], word[-size:]
            # The base's own plural as written ("men", "children", and "women", which WordNet makes by a rule and
            # Brown writes), where spelling would not make it.
            form = self._plural_written(base) if base in lemmas else None
            spelled = {base + "s", base + "es", base[:-1] + "ies"}
            if form and form not in spelled and wn.synsets(head) and head + form not in lemmas:
                compound = head + form
                break
        regular = []
        if word.endswith("y") and word[-2] not in "aeiou":
            regular.append(word[:-1] + "ies")
        elif word.endswith("z") and not word.endswith("zz") and word[-2] in "aeiou":
            regular += [word + "zes", word + "es"]
        else:
            regular += ([word + "es", word + "s"] if word.endswith(("s", "x", "z", "ch", "sh", "o"))
                        else [word + "s"])
        candidates = ([compound] if compound else []) + regular

        def kept(made):
            return made if made and word in wn._morphy(made, wn.NOUN) else None

        for made in candidates:
            if made in said:
                return kept(made)
        if compound:
            return kept(compound)
        if word.endswith("y") and word[-2] not in "aeiou":
            return kept(word[:-1] + "ies")
        # A word ending in a consonant and "s" is mostly a plural already ("spareribs", "hijinks", "antitrades"):
        # with no form written, none is made of it.
        if word.endswith("s") and not word.endswith(("ss", "us", "as")):
            return None
        if word in said:
            if (word.endswith("o") and word[-2] not in "aeiou") or (word.endswith("z") and not word.endswith("zz")):
                return None
            last = {phones[-1].rstrip("012") for phones in said[word]}
            if len(last) != 1:
                return None
            hiss = next(iter(last)) in self._HISSES
            return kept(word + ("s" if word.endswith("e") or not hiss else "es"))
        if word.endswith(("s", "x", "zz", "sh", "tch")):
            return kept(word + "es")
        if word.endswith(("ch", "z")) or (word.endswith("o") and word[-2] not in "aeiou"):
            return None
        return kept(word + "s")

    def _kind_said_of_many(self, sense, word: str) -> Optional[str]:
        """How a kind is written when things of it are said of many ("Hawks are raptors."): in its plural where it
        is counted, a name of several words in the plural of the word it is used as (`_head`: "birds of prey",
        "measuring instruments"); as it is where it is not counted, or only ever plural ("cattle", "swine",
        "short pants"); None where it is counted and no plural of it is known, and for a name written with a
        capital ("Hawks are White." said the kind as a name)."""
        if word != word.lower():
            return None
        if self.use_of(sense, word, in_plural=True) != "count":
            return word
        head = self._head(word)
        if not head or head != head.lower():
            return None
        made = self._plurals().get(head, ())
        if len(made) > 1:
            return None
        if made:
            plural = made[0]
        else:
            forms = self._brown_plurals()[0].get(head)
            plural = max(sorted(forms), key=forms.get) if forms else self._spelled_plural(head)
        if not plural:
            return None
        words = word.split()
        at = len(words) - 1 - words[::-1].index(head)
        return " ".join(words[:at] + [plural] + words[at + 1:])

    #: Brown's tags for a verb's forms: its past ("ran"), the form it takes for a doing under way ("running"), and
    #: the one it takes said of one doer now ("runs"). "have" and "do" are tagged apart ("had" `HVD`, "did" `DOD`),
    #: and are verbs all the same: "Tom had them." says a having.
    _VERB_TAGS = {"past": ("VBD", "HVD", "DOD"), "under way": ("VBG", "HVG"), "now": ("VBZ", "HVZ", "DOZ")}
    #: Who does a verb's doing, as WordNet's sentence frames for each sense give it (`Lemma.frame_ids`), in the order
    #: a sense with several is said by: someone ("Somebody ----s", "Somebody ----s PP"); someone to something
    #: ("Somebody ----s something", "... somebody", and the frames that add more to them); nothing ("It is
    #: ----ing", "It ----s that CLAUSE": the weather); something to something ("Something ----s something", said
    #: of someone as English does: "Tom defined them."); something ("Something ----s", "Something is ----ing PP").
    #: A sense with none of these ("Somebody ----s Adjective": "seem") is said in no frame the lessons hold.
    _DOERS = (("someone", frozenset({2, 22})),
              ("someone to something", frozenset({8, 9, 14, 15, 16, 17, 18, 19, 20, 21, 24, 25, 30, 31})),
              ("nothing", frozenset({3, 34})),
              ("someone to something", frozenset({10, 11})),
              ("something", frozenset({1, 4})))

    def _brown_verb_forms(self) -> Dict[str, Dict[str, Dict[str, int]]]:
        """How the Brown corpus writes each verb in each of its forms, `{form: {verb: {written: times}}}` (`_VERB_TAGS`),
        under each verb WordNet takes the word to be a form of ("ran", `run`). A word written as a verb is is its
        form only where WordNet takes it to be no other verb's: "put" is the past of `put`, "found" is not one of
        `found` but of `find`, and "lay" of `lie`. Read once."""
        if "_brown_verbs" not in self.__dict__:
            from collections import Counter
            from nltk.corpus import brown, wordnet as wn
            tags = {tag: form for form, tagged in self._VERB_TAGS.items() for tag in tagged}
            forms: Dict[str, Dict[str, Counter]] = {form: {} for form in self._VERB_TAGS}
            for word, tag in brown.tagged_words():
                form = tags.get(tag.split("-")[0])
                if form is None or not word.isalpha():
                    continue
                word = word.lower()
                verbs = set(wn._morphy(word, wn.VERB))
                for verb in verbs:
                    if verb == word and len(verbs) > 1:
                        continue
                    forms[form].setdefault(verb, Counter())[word] += 1
            self.__dict__["_brown_verbs"] = {form: {verb: dict(c) for verb, c in held.items()}
                                             for form, held in forms.items()}
        return self.__dict__["_brown_verbs"]

    def _verbs_listed(self) -> Dict[str, Tuple[str, ...]]:
        """`verb -> its forms` that no change of its ending makes, as WordNet lists them (`verb.exc`): "ran" and "run"
        for "run", "stopped" and "stopping" for "stop", "abetted" for "abet". Read once."""
        if "_verb_forms" not in self.__dict__:
            from nltk.corpus import wordnet as wn
            listed: Dict[str, set] = {}
            for line in wn.open("verb.exc"):
                words = line.split()
                if len(words) < 2 or "_" in words[0]:
                    continue
                for verb in words[1:]:
                    if "_" not in verb and verb != words[0]:
                        listed.setdefault(verb, set()).add(words[0])
            self.__dict__["_verb_forms"] = {verb: tuple(sorted(made)) for verb, made in listed.items()}
        return self.__dict__["_verb_forms"]

    @staticmethod
    def _verb_spelled(word: str, form: str) -> str:
        """A verb's form as spelling makes it, a change at its end: "strolled", "computing", "carries"."""
        consonant_y = len(word) > 1 and word.endswith("y") and word[-2] not in "aeiou"
        if form == "past":
            return word + "d" if word.endswith("e") else word[:-1] + "ied" if consonant_y else word + "ed"
        if form == "under way":
            return (word[:-2] + "ying" if word.endswith("ie")
                    else word[:-1] + "ing" if word.endswith("e") and not word.endswith(("ee", "oe", "ye"))
                    else word + "ing")
        return (word[:-1] + "ies" if consonant_y
                else word + "es" if word.endswith(("s", "x", "z", "ch", "sh", "o")) else word + "s")

    def _verb_written(self, word: str, form: str) -> Optional[str]:
        """A one-word verb as it is written in one of its forms (`_VERB_TAGS`), by the evidence nearest it:
          1. the way real text writes it most (the Brown corpus);
          2. the one WordNet lists ending as the form does ("stopped", "stopping", "panicked");
          3. in the past, a compound of a verb whose past no change makes, written with that past ("reread",
             "overate", "outran");
          4. as spelling makes it (`_verb_spelled`), but not the past of a verb WordNet lists another form of that no
             change makes: "forsake" lists "forsook" and "forsaken", which is the past it does not say, and
             "forsaked" is none.
        Kept only where WordNet's own morphology reads it back as the verb. None where nothing says."""
        from nltk.corpus import wordnet as wn
        if not word.isalpha() or word != word.lower() or len(word) < 2:
            return None
        brown = self._brown_verb_forms()
        written = brown[form].get(word)
        if written:
            return max(sorted(written), key=written.get)

        def kept(made: Optional[str]) -> Optional[str]:
            return made if made and word in wn._morphy(made, wn.VERB) else None
        listed = self._verbs_listed().get(word, ())
        ends = [made for made in listed if made.endswith({"past": "ed", "under way": "ing", "now": "s"}[form])]
        if ends:
            return kept(ends[0]) if len(ends) == 1 else None
        if form == "past":
            for size in range(len(word) - 2, 1, -1):
                head, base = word[:-size], word[-size:]
                past = brown["past"].get(base)
                if not past or not wn.synsets(head):
                    continue
                irregular = max(sorted(past), key=past.get)
                if irregular != self._verb_spelled(base, form):
                    # Its past is the compound's, or, where WordNet cannot read that back ("overate"), none: never
                    # the change a regular verb takes ("overeated").
                    return kept(head + irregular)
            if any(not made.endswith(("ed", "ing", "s")) for made in listed):
                return None
        return kept(self._verb_spelled(word, form))

    def _plurals_said(self, sense, word: str) -> Tuple[str, ...]:
        """The plurals `sense`, written `word`, is said with of many: each form no change makes ("mice"); else, for a
        one-word noun counted in this sense (`use_of`), the form real text writes most, or as spelling makes it
        (`_spelled_plural`: "hawks"). A noun not counted has none ("wheys" is no English, nor "cattles"), nor one
        whose use nothing states."""
        made = self._plurals().get(word, ())
        if made:
            return made
        if " " in word or self.use_of(sense, word) != "count":
            return ()
        forms = self._brown_plurals()[0].get(word)
        written = max(sorted(forms), key=forms.get) if forms else self._spelled_plural(word)
        return (written,) if written else ()

    #: Words before a noun that count it ("a table", "every dog"), and that measure it uncounted ("much money").
    _COUNTING = frozenset({"a", "an", "every", "each", "another", "one", "either", "neither"})
    _MEASURING = frozenset({"much", "less", "little"})
    #: "a piece of furniture", "an amount of money": the noun after "of" is uncounted.
    _PORTIONS = frozenset({"piece", "pieces", "amount", "amounts", "deal", "quantity", "quantities", "bit", "item",
                           "items", "lot"})
    #: Brown's tags for what stands before a noun and settles it: articles, determiners, numbers, possessives.
    _DETERMINER_TAGS = frozenset({"AT", "DT", "DTI", "DTS", "DTX", "CD", "PP$", "PP$$", "NP$", "NN$", "NNS$", "WDT",
                                  "WP$", "AP", "ABN", "ABX"})

    def _uses(self) -> Dict[str, str]:
        """`word -> use` for WordNet's one-word nouns, as real English uses them: `count`, `mass`, `plural` (only
        ever plural: "cattle", "clothes") or `invariant` (one form for both: "means", "series").

        WordNet says what a noun names, never whether it is counted, and a sentence said with the wrong one is wrong
        English the reader then learns ("A table is a furniture.", "Oxen are cattles."). So it is read from use: the
        Brown corpus (a million words of tagged English) and WordNet's own definitions and examples. Counted: after
        "a", "every", "one" ... (not in the plural: uncounted words take one too). Uncounted: after "much" or "a
        piece of", or bare where a counted noun takes a determiner ("they bought furniture"), a modifier of a
        following noun ("water pipe"), a word set off by punctuation ("Yes, sir.") and a word in a title ("Bureau")
        aside. A noun is uncounted within
        Yang's tolerance: its counted uses at most N / ln N of its N uses, as the reader decides an ending's use;
        counted on any counted use otherwise.
        A noun with no use found is not stated, and the reader decides it as for any word it holds nothing of.
        Read once for the source."""
        if "_noun_uses" in self.__dict__:
            return self.__dict__["_noun_uses"]
        import math
        import re
        from collections import Counter
        from nltk.corpus import brown, wordnet as wn

        nouns = {lemma.lower() for synset in wn.all_synsets("n") for lemma in synset.lemma_names()
                 if "_" not in lemma and lemma.isalpha()}
        counted, uncounted, plural_as_is, singular = Counter(), Counter(), Counter(), Counter()
        tagged = [(word.lower(), "TITLE" if ("-TL" in tag or "-HL" in tag) else tag.split("-")[0])
                  for word, tag in brown.tagged_words()]
        for at, (word, tag) in enumerate(tagged):
            if tag == "NNS":
                # A PLURAL IS NO EVIDENCE OF COUNTING: uncounted nouns take one too ("waters", "wines"), and counting
                # them so found a fifth of the uncounted words a hand-made lexicon holds (COUNTABILITY-01).
                if word in nouns:
                    plural_as_is[word] += 1
                continue
            if tag != "NN" or word not in nouns or len(word) < 3:
                continue
            singular[word] += 1
            after = tagged[at + 1][1] if at + 1 < len(tagged) else ""
            if after.startswith("NN") or after.startswith("NP"):
                continue
            # The article of a noun stands before all that describes it: adjectives, ordinals, and nouns before it
            # ("the board chairman", "their 25th anniversary", "the summer sun"), not between them and it.
            before = at - 1
            while before >= 0 and tagged[before][1] in ("JJ", "JJR", "JJS", "VBN", "VBG", "QL", "OD"):
                before -= 1
            compound = before >= 0 and tagged[before][1] in ("NN", "NNS", "NP")
            while before >= 0 and tagged[before][1] in ("JJ", "JJR", "JJS", "VBN", "VBG", "QL", "OD", "NN", "NNS",
                                                        "NP"):
                before -= 1
            word_before, tag_before = tagged[before] if before >= 0 else ("", "")
            if word_before in self._COUNTING:
                counted[word] += 1
            elif word_before in self._MEASURING or (
                    word_before == "of" and before >= 1 and tagged[before - 1][0] in self._PORTIONS):
                uncounted[word] += 1
            elif tag_before in (",", "``", "''", "(", ".", ":", "--", "") or after in (",", "."):
                continue
            # A role after "be" goes bare whether counted or not ("he is chairman of the board").
            elif tag_before.startswith("BE"):
                continue
            # After a preposition a single noun says nothing ("by car", "at home"); a phrase of nouns, with no
            # article before it, stands bare ("for world peace").
            elif tag_before not in self._DETERMINER_TAGS and word_before != "the" and (tag_before != "IN" or compound):
                uncounted[word] += 1
        for synset in wn.all_synsets():
            for text in (synset.definition(), *synset.examples()):
                words = re.findall(r"[a-z]+", (text or "").lower())
                for at, word in enumerate(words):
                    if word in nouns:
                        word_before = words[at - 1] if at else ""
                        if word_before in self._COUNTING:
                            counted[word] += 1
                        elif word_before in self._MEASURING or (
                                word_before == "of" and at >= 2 and words[at - 2] in self._PORTIONS):
                            uncounted[word] += 1

        # WordNet lists a word the same in both ("deer deer") where its plural is itself.
        same_both = {written[0] for written in (line.split() for line in wn.open("noun.exc"))
                     if len(written) >= 2 and written[0] in written[1:]}
        uses: Dict[str, str] = {}
        for noun in nouns:
            many, few = counted[noun], uncounted[noun]
            if plural_as_is[noun] >= 2 and singular[noun] == 0:
                uses[noun] = "plural"
            elif noun in same_both or (plural_as_is[noun] >= 2 and singular[noun] >= 2):
                uses[noun] = "invariant"
            elif many + few >= 3 and few > many and many <= (many + few) / math.log(many + few):
                uses[noun] = "mass"
            # COUNTED ON ANY COUNTED USE. Counted by the Tolerance Principle too, as uncounted is, Brown counted 412
            # fewer words, right as often as wrong overall (COUNTABILITY-01's fourth run); and a sense nothing else
            # states is said by the reader's guess from its ending, which takes "property" (an attribute) as "beauty"
            # and "safety" are used: "A manner is property.". Taken back the same day.
            elif many:
                uses[noun] = "count"
        self.__dict__["_noun_uses"] = uses
        return uses

    #: Where the Bochum English Countability Lexicon is kept, under NLTK's data (`_sense_uses`).
    BECL = "corpora/becl/BECL_2.1_master.csv"
    BECL_URL = "https://github.com/Linguistic-Data-Science-Lab/BECL"
    #: How far up its kinds a sense is followed to find senses labelled like it (`_sense_uses`).
    KINDS_FOR_USE = 4

    def _becl(self) -> Dict[Any, str]:
        """`synset -> "count" | "mass"` as the Bochum English Countability Lexicon labels WordNet's noun senses by hand
        (Kiss et al. 2016; 11,869 senses): "luggage, baggage" uncounted, `fish.n.01` counted. A sense labelled both,
        or neither ("the sun"), is left for its kind to decide. Kept beside WordNet in NLTK's data and not fetched
        here. Read once for the source."""
        if "_becl_labels" in self.__dict__:
            return self.__dict__["_becl_labels"]
        import csv
        from pathlib import Path
        import nltk
        from nltk.corpus import wordnet as wn
        from nltk.corpus.reader.wordnet import WordNetError
        if self.becl_path:
            where = Path(self.becl_path)
        else:
            try:
                where = Path(str(nltk.data.find(self.BECL)))
            except LookupError:
                raise FileNotFoundError(
                    f"the Bochum English Countability Lexicon is not under NLTK's data ({self.BECL}); put "
                    f"BECL_2.1_master.csv from {self.BECL_URL} there first. A teaching pass does not reach the "
                    f"network.") from None
        labels: Dict[Any, str] = {}
        with open(where, encoding="latin-1", newline="") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                use = {"regular_count": "count", "regular_mass": "mass"}.get(row.get("major_class", ""))
                if not use:
                    continue
                try:
                    labels[wn.synset(row["sense_synset"])] = use
                except (WordNetError, ValueError, KeyError):
                    continue
        self.__dict__["_becl_labels"] = labels
        return labels

    def _sense_uses(self) -> Dict[Any, str]:
        """`synset -> "count" | "mass"` for WordNet's noun senses: how a sense is used, as its own label says, else as
        the senses of its kind are used.

        A record is about a sense, and a word's senses are used differently ("a fish", the animal; "fish", the
        food). So the use is the sense's: the hand label where there is one (`_becl`); else what most labelled
        senses under its nearest kind carry, within the Tolerance Principle (exceptions at most N / ln N of N), as
        a speaker takes an unknown "cricket equipment" to be used as equipment is; else none, and the word's own
        uses in real text decide (`_uses`). Measured on the lexicon's own senses held out by word, its kind decides
        91.4% of them and is right 88.5% of those, and finds 56% of the uncounted ones, where real text found 13%
        (COUNTABILITY-01). Worked out once for the source."""
        if "_sense_use_map" in self.__dict__:
            return self.__dict__["_sense_use_map"]
        import math
        import sys
        from nltk.corpus import wordnet as wn
        labels = self._becl()
        below: Dict[Any, FrozenSet] = {}
        empty: FrozenSet = frozenset()

        def labelled_below(synset) -> FrozenSet:
            # The labelled senses at and under a kind, worked out once each, leaves first.
            if synset in below:
                return below[synset]
            found = set([synset]) if synset in labels else set()
            for kind in synset.hyponyms() + synset.instance_hyponyms():
                found |= labelled_below(kind)
            below[synset] = frozenset(found) if found else empty
            return below[synset]

        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(limit, 10000))
        try:
            for root in wn.all_synsets("n"):
                if not root.hypernyms() and not root.instance_hypernyms():
                    labelled_below(root)
        finally:
            sys.setrecursionlimit(limit)

        def by_kind(synset) -> Optional[str]:
            frontier = [synset]
            for _ in range(self.KINDS_FOR_USE):
                # In one order: a sense with two kinds takes the first that tells, the same in every process.
                frontier = self._ordered(k for s in frontier for k in s.hypernyms() + s.instance_hypernyms())
                for kind in frontier:
                    like = [labels[s] for s in labelled_below(kind) if s != synset]
                    if len(like) >= 2:
                        use, held = max(((u, like.count(u)) for u in set(like)), key=lambda uh: (uh[1], uh[0]))
                        return use if len(like) - held <= len(like) / math.log(len(like)) else None
            return None

        uses: Dict[Any, str] = {}
        for synset in wn.all_synsets("n"):
            use = labels.get(synset) or by_kind(synset)
            if use:
                uses[synset] = use
        self.__dict__["_sense_use_map"] = uses
        return uses

    def use_of(self, sense, word: str, *, in_plural: bool = False) -> Optional[str]:
        """How `word`, written for `sense`, is used, stated by the word it ends in ("cricket equipment" as
        "equipment"); None where nothing states it, and the reader decides.

        Only ever plural ("clothes") or one in both ("deer"), the word is, whatever its sense. Else, by how close the
        evidence is to the sense:
          1. the sense's own label (`_becl`);
          2. the word uncounted in real text, where the sense is the one the word is mostly used in ("advice",
             "rice"): an uncounted use is decided past the Tolerance Principle, and the word's uses are its main
             sense's;
          3. as the senses of its kind are used (`_sense_uses`: "fish" the animal counted);
          4. as the word is in real text (`_uses`), where a single counted use counts it.
        Measured on the lexicon's senses held out by word, this order is right 85.5% of the time and the kind before
        the word 85.3% (COUNTABILITY-01). A word one in both is stated so ("A deer is a ruminant."), which no lesson
        can show; said of many, it is plural ("Teeth are means.")."""
        from nltk.corpus import wordnet as wn
        # COUNTING IS A NOUN'S. A verb or an adjective is no counted thing, whatever its word is in real text ("a
        # cold"): stated "count", "To be acold is to be cold." and "To stroll is to walk." were refused for writing a
        # counted word bare, and WordNet's verbs and adjectives were said in no sentence (2026-10-12).
        if sense.pos() != "n":
            return None
        head = self._head(word)
        if not head or head != head.lower():
            return None
        use = self._uses().get(head)
        if use not in ("plural", "invariant") and sense.pos() == "n":
            labelled = self._becl().get(sense)
            if labelled:
                use = labelled
            elif " " in word and self._kind_named(sense, head) is not None:
                # A NAME THAT ENDS IN ITS OWN KIND'S WORD IS USED AS THAT WORD IS: "bedroom furniture" is furniture,
                # said as "furniture" is; "a long bone" is a bone. Its kind's other members ("a bed", "a chair")
                # say how things of the kind are used under names of their own, not how the kind's word is.
                return self.use_of(self._kind_named(sense, head), head, in_plural=in_plural)
            elif not (use == "mass" and self._main_sense(head) == sense):
                use = self._sense_uses().get(sense) or use
        # A NAME ENDING IN A PLURAL ("bottom lurkers"): its last word no noun of its own, WordNet reads it as another
        # noun's plural, so the name is said of many ("Bottom lurkers are fish.").
        if use is None and " " in word:
            bases = wn._morphy(head, wn.NOUN)
            if bases and head not in bases:
                use = "plural"
        if use == "invariant" and in_plural:
            use = "plural"
        return use

    def _head(self, name: str) -> str:
        """The word a name of several words is used as: its last, the one the rest describe ("cricket equipment"),
        or the one before a preposition inside it ("roll of tobacco", a roll; "work of art", a work). Taken as its
        last word, "roll of tobacco" was used as "tobacco" is: "A cigaret is roll of tobacco."."""
        words = name.split()
        for at in range(1, len(words) - 1):
            if words[at] in self._prepositions():
                return words[at - 1]
        return words[-1] if words else ""

    def _prepositions(self) -> frozenset:
        """The words real text uses as a preposition more than as anything else: the Brown corpus's tag `IN`, on
        words met often enough for the tally to tell (the hundred times a word of a name is not). Read once."""
        if "_preposition_words" not in self.__dict__:
            from collections import Counter
            from nltk.corpus import brown
            tags: Dict[str, Counter] = {}
            for word, tag in brown.tagged_words():
                tags.setdefault(word.lower(), Counter())[tag.split("-")[0]] += 1
            self.__dict__["_preposition_words"] = frozenset(
                word for word, counts in tags.items()
                if sum(counts.values()) >= 100 and counts.most_common(1)[0][0] == "IN")
        return self.__dict__["_preposition_words"]

    def _kind_named(self, sense, word: str):
        """The nearest kind of `sense`, up to `KINDS_FOR_USE` levels, that `word` is a name of; None when none is."""
        frontier = [sense]
        for _ in range(self.KINDS_FOR_USE):
            frontier = self._ordered(k for s in frontier for k in s.hypernyms() + s.instance_hypernyms())
            for kind in frontier:
                if any(self._written(name).lower() == word for name in kind.lemma_names()):
                    return kind
        return None

    def _main_sense(self, word: str):
        """The noun sense `word` is mostly used in: by tagged use, then WordNet's order. None if it names none."""
        mains = self.__dict__.setdefault("_main_senses", {})
        if word not in mains:
            from nltk.corpus import wordnet as wn
            senses = wn.synsets(word, wn.NOUN)
            mains[word] = max(senses, key=lambda s: sum(lemma.count() for lemma in s.lemmas()
                                                        if lemma.name().lower() == word)) if senses else None
        return mains[word]

    #: Brown's tags for what may stand between a verb and the noun it is done to ("ate the small fish").
    _BETWEEN_TAGS = _DETERMINER_TAGS | frozenset({"OD", "JJ", "JJR", "JJS", "VBN", "VBG"})
    #: Verbs that carry another verb or say what a thing is, not something done to a thing.
    _AUXILIARIES = frozenset({"be", "is", "am", "are", "was", "were", "been", "being", "have", "has", "had",
                              "having", "do", "does", "did"})

    def said_of(self) -> Iterator[Tuple[str, str, str, str, int]]:
        """What each word is said of in real English, as the Brown corpus uses it: `(relation, word, side, other,
        times)`, the word standing on `side` of the relation and `other` on the far side. "red wine", met 16 times:
        `("has_property", "red", "object", "wine", 16)`, red said of wine; "ate the bread":
        `("done_to", "eat", "subject", "bread", 1)`; "the dog barked": `("done_by", "bark", "subject", "dog", 1)`.

        Not facts: that red is said of wine is no fact about wine. Read by the listener as what a word is said of
        (Resnik 1997), which of a word's senses fits what is said of it: red is said of physical things, so the
        table that is red is the furniture. Counted at the head of each phrase only: an adjective before the noun
        that ends its phrase, the noun a verb is done to past its determiners and modifiers, the noun that ends
        its phrase before a verb; each word as WordNet writes its base form."""
        from collections import Counter
        from nltk.corpus import brown, wordnet as wn

        def base(word: str, pos: str) -> Optional[str]:
            return wn.morphy(word, pos) if word.isalpha() else None

        counted: Counter = Counter()
        for sentence in brown.tagged_sents():
            tagged = [(word.lower(), tag.split("-")[0]) for word, tag in sentence] + [("", ""), ("", "")]
            for at, (word, tag) in enumerate(tagged[:-2]):
                after, then = tagged[at + 1][1], tagged[at + 2][1]
                if tag == "JJ" and after in ("NN", "NNS") and not then.startswith("NN"):
                    noun, said = base(tagged[at + 1][0], wn.NOUN), base(word, wn.ADJ)
                    if noun and said:
                        counted[("has_property", said, "object", noun)] += 1
                if tag in ("NN", "NNS") and after in ("VBD", "VBZ") and tagged[at + 1][0] not in self._AUXILIARIES:
                    noun, verb = base(word, wn.NOUN), base(tagged[at + 1][0], wn.VERB)
                    if noun and verb:
                        counted[("done_by", verb, "subject", noun)] += 1
                if tag in ("VB", "VBD", "VBZ", "VBG", "VBN") and word not in self._AUXILIARIES:
                    end = at + 1
                    while tagged[end][1] in self._BETWEEN_TAGS:
                        end += 1
                    if tagged[end][1] in ("NN", "NNS") and not tagged[end + 1][1].startswith("NN"):
                        verb, noun = base(word, wn.VERB), base(tagged[end][0], wn.NOUN)
                        if verb and noun:
                            counted[("done_to", verb, "subject", noun)] += 1
        for (relation, word, side, other), times in counted.items():
            yield relation, word, side, other, times

    #: Where the Princeton WordNet Gloss Corpus is kept, under NLTK's data (`definition_links`).
    GLOSS_CORPUS = "corpora/glosstag/WordNet-3.0/glosstag/merged"
    GLOSS_CORPUS_URL = "https://wordnetcode.princeton.edu/glosstag-files/WordNet-3.0-glosstag.tar.bz2"

    def _definition_links(self) -> Dict[Any, Tuple[Any, ...]]:
        """`synset -> the senses its definition is written with`, as WordNet's own authors linked each word of every
        definition to the sense it is used in there (the Princeton WordNet Gloss Corpus, 2008): the bank that
        "accepts deposits and channels the money into lending activities" is defined with `money.n.01`; to eat is to
        "take in solid food", `consume.v.02` and `food.n.02`. A word linked by hand or, where it has one sense only,
        by the corpus itself; a word left unlinked, and the definition's examples (in which only the sense's own
        words were linked), give nothing. The corpus is kept beside WordNet in NLTK's data and is not fetched here.
        Read once for the source."""
        if "_definitions" in self.__dict__:
            return self.__dict__["_definitions"]
        import xml.etree.ElementTree as ET
        from pathlib import Path
        import nltk
        from nltk.corpus import wordnet as wn
        from nltk.corpus.reader.wordnet import WordNetError
        try:
            where = Path(str(nltk.data.find(self.GLOSS_CORPUS)))
        except LookupError:
            raise FileNotFoundError(
                f"the WordNet Gloss Corpus is not under NLTK's data ({self.GLOSS_CORPUS}); unpack "
                f"{self.GLOSS_CORPUS_URL} into nltk_data/corpora/glosstag first. A teaching pass does not reach the "
                f"network.") from None

        def sense_of(key: str):
            try:
                return wn.lemma_from_key(key).synset()
            except WordNetError:
                # THE CORPUS WRITES A SATELLITE ADJECTIVE AS A HEAD ONE ("able%3:00:00:capable:00"): a key naming a
                # head adjective is a satellite's (type 5) by WordNet's own definition of a sense key.
                lemma, fields = key.split("%", 1)[0], key.split("%", 1)[1].split(":")
                if fields[0] == "3" and len(fields) > 3 and fields[3]:
                    return wn.lemma_from_key(f"{lemma}%5:{':'.join(fields[1:])}").synset()
                raise

        links: Dict[Any, Tuple[Any, ...]] = {}
        for part in ("noun", "verb", "adj", "adv"):
            for _, element in ET.iterparse(where / f"{part}.xml"):
                if element.tag != "synset":
                    continue
                synset = wn.synset_from_pos_and_offset(element.get("pos"), int(element.get("ofs")))
                found = []
                for definition in element.iter("def"):
                    for token in definition.iter():
                        if token.tag not in ("wf", "glob") or token.get("tag") not in ("man", "auto"):
                            continue
                        for sense in token.findall("id"):
                            key = sense.get("sk", "")
                            # The annotators' mark for a word they chose to leave unlinked; it names no sense.
                            if key and not key.startswith("purposefully_ignored%"):
                                found.append(sense_of(key))
                links[synset] = tuple(s for s in dict.fromkeys(found) if s != synset)
                element.clear()
        self.__dict__["_definitions"] = links
        return links

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

        from core.semantics.derived_reader import _temporal
        groups: Dict[Tuple[str, str], list] = defaultdict(list)
        names: Dict[Any, str] = {}
        dated: list = []
        for synset in wn.all_synsets():
            # A NUMBER IS NAMED BY ITS VALUE, as the lessons name numbers ("1", "1000000000000"): WordNet writes
            # `trillion.n.03` "trillion" first and "1000000000000" among its words, and named by the word it would
            # be a second concept beside the number the lessons taught.
            value = next((lemma for lemma in synset.lemma_names() if lemma.isdigit()), None)
            if value is not None:
                names[synset] = str(int(value))
                continue
            name = name_of(synset)
            # A NAME A DAY OR A TIME IS WRITTEN IN IS THAT DAY'S OR TIME'S: "november 5" is read as the 5th of
            # November, and a date is no kind ("Guy Fawkes Day is a november 5" was refused, and stopped the pass).
            # Such a sense is named apart, by what it is a kind of, as any sense whose name is taken.
            if name and _temporal(name):
                dated.append((name, synset))
                continue
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
        qualify: list = list(dated)
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
                    if word == name or _term_words(candidate) > MAX_TERM_WORDS or candidate in taken:
                        continue
                    names[synset] = candidate
                    taken.add(candidate)
                    break
                if names[synset]:
                    break
        # ONE CONCEPT PER SENSE, ACROSS PARTS OF SPEECH. Named within each part of speech, a noun and a verb written
        # alike were one concept ("bird" the animal and to watch birds; "watch" the timepiece and to look), and their
        # kinds chained across: a crane, a wading bird, a bird, observing, watching, a timepiece, a device. The name
        # stays with the part of speech the lessons use the word in (`_lesson_parts`), else with the one whose
        # senses the word names most often, as tagged; the senses of the others are named apart by what they are
        # first a kind of, as above. A number is named by its value in every part of speech, and stays one.
        lesson_parts = self._lesson_parts()
        rank = {"n": 0, "v": 1, "a": 2, "r": 3}
        by_part: Dict[str, Dict[str, list]] = {}
        for synset, name in names.items():
            if name and not name.isdigit():
                by_part.setdefault(name, {}).setdefault(part(synset), []).append(synset)
        for name, parts in sorted(by_part.items()):
            if len(parts) < 2:
                continue

            def met(pos: str) -> int:
                return sum(lemma.count() for synset in parts[pos] for lemma in synset.lemmas()
                           if self._written(lemma.name()).lower() == name)

            keep = (lesson_parts.get(name, set()) & set(parts)) or {max(parts, key=lambda p: (met(p), -rank[p]))}
            for pos in sorted(set(parts) - keep):
                for synset in sorted(parts[pos], key=lambda s: s.name()):
                    names[synset] = ""
                    for qualifier in self._qualifiers(synset):
                        for lemma in qualifier.lemma_names():
                            word = self._written(lemma).lower()
                            candidate = f"{word} {name}"
                            if word == name or _term_words(candidate) > MAX_TERM_WORDS or candidate in taken:
                                continue
                            names[synset] = candidate
                            taken.add(candidate)
                            break
                        if names[synset]:
                            break
                    if not names[synset]:
                        # Else another word it is written with, no other sense's ("data file" for a file); else a kind
                        # further up, where its nearest kind already names a sibling ("implement bolt" beside "bar
                        # bolt").
                        other = next((w for w in (self._written(l).lower() for l in synset.lemma_names())
                                      if w != name and w not in taken and _term_words(w) <= MAX_TERM_WORDS), None)
                        if other is None:
                            above = [k for q in self._qualifiers(synset) for k in q.hypernyms() + q.instance_hypernyms()]
                            while above and other is None:
                                for kind in self._ordered(above):
                                    candidates = (f"{self._written(l).lower()} {name}" for l in kind.lemma_names())
                                    other = next((c for c in candidates if c not in taken
                                                  and _term_words(c) <= MAX_TERM_WORDS), None)
                                    if other:
                                        break
                                above = [k for kind in above for k in kind.hypernyms() + kind.instance_hypernyms()]
                        if other:
                            names[synset] = other
                            taken.add(other)
                    if not names[synset] and pos == "v" and f"to {name}" not in taken:
                        # A verb nothing is above ("watch", to look): named as English names a doing, "to watch".
                        names[synset] = f"to {name}"
                        taken.add(names[synset])
                    if not names[synset]:
                        # Nothing it is a kind of tells it apart: it stays one with the others, as before.
                        names[synset] = name
        # NAMES AS THE DOOR WRITES THEM. Every name is written at the door as `normalize_term` writes it, its last
        # word in the singular: "blues" (the music) comes in as `blue`, the colour, "glasses" as `glass`, "aids" as
        # `aid`. A name the door writes as another sense's is one name, and the sense it was rewritten from is
        # named apart, as any colliding sense is, by what it is first a kind of: "music genre blues", which the door
        # writes `music_genre_blue`, no other's.
        from core.semantics.cognitive_ingress import normalize_term
        at_door: Dict[str, set] = {}
        for name in names.values():
            if name:
                at_door.setdefault(normalize_term(name), set()).add(name)
        taken_at_door = set(at_door)
        def rewritten(name: str) -> bool:
            # The door changed the name's last word, not only dropped an article before it ("a few", `few`).
            return normalize_term(name).split("_")[-1] != name.lower().replace("-", " ").split()[-1]

        for synset in sorted((s for s, n in names.items() if n), key=lambda s: s.name()):
            name = names[synset]
            door = normalize_term(name)
            # Renamed where the door made it another name that is written as the door writes it ("blues" beside
            # "blue"); two writings of one word ("after-hours", "after hours") are one name.
            if not rewritten(name) or not any(not rewritten(other) for other in at_door[door] if other != name):
                continue
            names[synset] = ""
            for qualifier in self._qualifiers(synset):
                for lemma in qualifier.lemma_names():
                    word = self._written(lemma).lower()
                    candidate = f"{word} {name}"
                    if _term_words(candidate) > MAX_TERM_WORDS or normalize_term(candidate) in taken_at_door:
                        continue
                    names[synset] = candidate
                    taken_at_door.add(normalize_term(candidate))
                    break
                if names[synset]:
                    break
            if not names[synset]:
                # Nothing it is a kind of names it apart ("sometimes", "beads"): it keeps its name, one with the other
                # at the door as before, rather than go untaught.
                names[synset] = name
        self.__dict__["_names"] = names
        return names

    #: Relations whose subject is a doing, beside who did it and what it was done to (`done_*`, `moves_*`): the kind
    #: of that event is a verb's. Not "before now" alone, which a thing that was is too ("There was a bird.").
    _EVENT_RELATIONS = frozenset({"received_by", "has_purpose", "lasts_until", "lasts_since", "lasts_for"})

    def _lesson_parts(self) -> Dict[str, set]:
        """`word -> {part of speech}` ("n", "v", "a") the English lessons use each of their words in most, read from what
        their meanings say of it: the kind of a doing is a verb's ("Tom kicked the ball.": `kick`), what a thing can do too
        ("Fish can swim."), a property an adjective's ("The ball is red."), a kind or a thing a noun's. Beside the
        lessons' stated senses (`stated_senses`). Read once for the source."""
        if "_lesson_part_map" in self.__dict__:
            return self.__dict__["_lesson_part_map"]
        from pathlib import Path
        lessons = (Path(self.senses_path).parent if self.senses_path else
                   Path(__file__).resolve().parents[2] / "data" / "lessons")
        seen: Dict[str, Dict[str, int]] = {}

        def note(term: Any, pos: str) -> None:
            if isinstance(term, str) and term and not term.startswith("?"):
                counts = seen.setdefault(term.strip().lower(), {})
                counts[pos] = counts.get(pos, 0) + 1

        for path in sorted(lessons.glob("english_[0-9][0-9].json")):
            for record in json.loads(path.read_text()).get("records", ()):
                facts = [f for f in (record.get("meaning") or {}).get("facts", ()) if len(f) >= 3]
                events = {f[1] for f in facts if str(f[0]).startswith(("done_", "moves_"))
                          or f[0] in self._EVENT_RELATIONS}
                states = {f[1] for f in facts if f[0] == "state_of"}
                # A DEGREE ("The car is faster than the bike.", "Tom is the most famous boy.") is of a quality:
                # `has_degree(car, ?d)`, `instance_of(?d, fast)`. Counted a thing's kind, every adjective the lessons
                # compare was a noun here, and "fast" stayed with fasting, the noun: "Cars are fast." read as cars
                # being abstinences (2026-10-12).
                degrees = {f[2] for f in facts if f[0] == "has_degree"}
                for relation, subject, obj, *_ in facts:
                    if relation == "instance_of":
                        # A doing's kind is a verb's; a state's ("The door was open.") or a degree's an adjective's.
                        note(obj, "v" if subject in events else "a" if subject in states or subject in degrees
                             else "n")
                    elif relation == "state_of":
                        note(obj, "n")
                    elif relation == "has_property":
                        note(subject, "n")
                        note(obj, "a")
                    elif relation == "capable_of":
                        note(subject, "n")
                        note(obj, "v")
                    elif str(relation).startswith(("done_", "moves_")) or relation == "received_by":
                        note(obj, "n")       # who did it, what it was done to: things
                    elif not (str(relation).startswith(("done_", "moves_")) or relation in self._EVENT_RELATIONS):
                        note(subject, "n")
                        note(obj, "n")
        # The part of speech the lessons use a word in most: one concept per sense, and the lessons' word names one.
        rank = {"n": 0, "v": 1, "a": 2}
        parts = {word: {max(counts, key=lambda p: (counts[p], -rank[p]))} for word, counts in seen.items()}
        self.__dict__["_lesson_part_map"] = parts
        return parts

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

    def usage(self) -> Iterator[Tuple[str, str, int, Tuple[str, ...]]]:
        """How often each word was met naming each sense, in the text WordNet's senses were tagged in (SemCor, the
        Brown corpus): `(word, sense name, times, its forms)`, for every word met at least once. What a person learns
        from hearing English used, given as the count of real uses: "fish" met naming the animal 12 times and the
        food 3; "person" naming a human being 6,833 times. Read by the listener as how often a word names each
        thing (`derived_reader.meant`).

        A VERB'S COUNT IS OF THE VERB IN EVERY FORM, as SemCor tags each form with its verb ("had" is `have`): so the
        forms come with it, as the lessons write them (`_verb_written`: "had", "has", "having"), for the count to
        land where the verb is held only in them ("Tom had them.")."""
        from nltk.corpus import wordnet as wn
        names = self._sense_names()
        met: Dict[Tuple[str, str], int] = {}
        verbs: Set[Tuple[str, str]] = set()
        for synset in wn.all_synsets():
            name = names.get(synset, "")
            if not name or _term_words(name) > MAX_TERM_WORDS:
                continue
            if self.parts and ("a" if synset.pos() == "s" else synset.pos()) not in self.parts:
                continue
            for lemma in synset.lemmas():
                times = lemma.count()
                if times > 0:
                    # Senses that share a name (they do not disagree about what they are) are one thing, met as often
                    # as all of them were.
                    key = (self._written(lemma.name()), name)
                    met[key] = met.get(key, 0) + times
                    if synset.pos() == "v":
                        verbs.add(key)
        for (word, name), times in met.items():
            forms: Tuple[str, ...] = ()
            if (word, name) in verbs and " " not in word and word.isalpha():
                forms = tuple(dict.fromkeys(written for form in self._VERB_TAGS
                                            if (written := self._verb_written(word, form))))
            yield word, name, times, forms

    def word_classes(self) -> Iterator[Tuple[str, str]]:
        """Every class WordNet settles, INCLUDING adverbs.

        `records()` states a class only for the words in a fact, so a verb, an adjective or an adverb that never
        appears in one was never stated at all. This is the source saying everything it knows about its own
        vocabulary."""
        return iter(self._word_classes().items())

    def records(self, *, examples_only: bool = False) -> Iterator[TaughtRecord]:
        """Every record WordNet teaches (`_records`), or of `senses` only those each is in."""
        if not self.senses:
            yield from self._records(examples_only=examples_only)
            return
        from nltk.corpus import wordnet as wn
        names = self._sense_names()
        only = {names.get(wn.synset(sense), "") for sense in self.senses} - {""}
        for taught in self._records(examples_only=examples_only):
            if taught.subject in only or taught.obj in only:
                yield taught

    def _records(self, *, examples_only: bool = False) -> Iterator[TaughtRecord]:
        """Every record WordNet teaches; `examples_only`, only its examples of English (`WordNetExamplesSource`), for a
        store that holds its facts: the plurals of its nouns, the forms of its verbs, its verbs' kinds and its
        adjectives' likenesses said as rules. Each built as the whole pass builds it, so the same."""
        from nltk.corpus import wordnet as wn
        from core.semantics.derived_reader import Meaning, MeaningFact

        classes = self._word_classes()
        names = self._sense_names()
        definitions = {} if examples_only else self._definition_links()
        # A NAME SHARED BY SENSES IN DIFFERENT PARTS OF SPEECH ("mouse" the animal, and "mouse" the moving of a
        # computer's mouse) is one concept, and a definition taught of it is said of every sense it holds: the
        # verb's computer became what the animal is near. The name is defined by the sense its word names most
        # often, as tagged, as `_sense_names` gives the plain name within one part of speech.
        part_order = {"n": 0, "v": 1, "a": 2, "s": 2, "r": 3}
        defines: Dict[str, Any] = {}
        for synset, name in sorted(names.items(), key=lambda kv: kv[0].name()):
            if not name:
                continue
            met = sum(lemma.count() for lemma in synset.lemmas() if self._written(lemma.name()).lower() == name)
            held = defines.get(name)
            if held is None or (-met, part_order[synset.pos()]) < held[0]:
                defines[name] = ((-met, part_order[synset.pos()]), synset)
        order = self._ordered
        seen = set()
        opposites = set()

        def uses_of(written, *, in_plural: bool = False) -> Tuple[Tuple[str, str], ...]:
            """How the words of a record are used, `(sense, word)` each: `(name, use)`, the name as written
            (`use_of`)."""
            out = []
            for sense, word in written:
                use = self.use_of(sense, word, in_plural=in_plural)
                if use:
                    # Under the whole name: "long bone", counted, and "bone", the stuff, end in one word and are
                    # used differently.
                    out.append((word.lower(), use))
            return tuple(dict.fromkeys(out))

        def fits(name: str) -> bool:
            # The store holds names of at most MAX_TERM_WORDS words. A name past it is not taught: shortening it
            # would name something else.
            return bool(name) and _term_words(name) <= MAX_TERM_WORDS

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
            senses = ((subject, subject_word), (obj, obj_word))
            stated = tuple((word.lower(), classes[word.lower()]) for _, word in written if word.lower() in classes)
            if not said:
                return TaughtRecord(subject=child, relation=relation, obj=parent, quality=self.quality,
                                    word_classes=stated)
            # WHAT IS SO, AND THE WORDS: the substrate says it through the frames it was taught, so the source
            # writes no English of its own.
            return TaughtRecord(subject=child, relation=relation, obj=parent, quality=self.quality,
                                word_classes=stated,
                                meaning=Meaning("tell", (MeaningFact(relation, child, parent),)),
                                words=tuple((name, word) for name, word in written if name != word),
                                uses=uses_of(senses))

        def as_rule(part: str, relation: str, subject, subject_word: str, obj, obj_word: str):
            """A fact between two senses said as the rule it is over a doing or a quality, as english_41 says it: a
            verb's kind, "To stroll is to walk." (whatever strolling is done is a walking), and an adjective's
            likeness, "To be lovely is to be beautiful." (whatever is lovely is beautiful). An example of English
            only, one for each word the sense is written with: the fact is taught once, by its own record. Said as
            `isa` or `similar_to`, the words stood where kinds do, and an adjective read through its slot was a kind
            ("Faith is central."); unsaid, almost no verb or adjective sense had a word to be read by (44 of 24,467
            and 1,252 of 29,703, 2026-10-12)."""
            child, parent = names.get(subject, ""), names.get(obj, "")
            if not (fits(child) and fits(parent)) or child == parent:
                return None
            key = (child, "rule", parent, subject_word.lower(), obj_word.lower())
            if key in seen:
                return None
            seen.add(key)
            if part == "doing":
                said_as = (MeaningFact("instance_of", "?e", child, condition=True),
                           MeaningFact("done_by", "?e", "?x", condition=True), MeaningFact("instance_of", "?e", parent))
            else:
                said_as = (MeaningFact("has_property", "?x", child, condition=True),
                           MeaningFact("has_property", "?x", parent))
            written = ((child, subject_word), (parent, obj_word))
            return TaughtRecord(subject=child, relation=relation, obj=parent, quality=self.quality,
                                meaning=Meaning("tell", said_as), example=True,
                                words=tuple((name, word) for name, word in written if name != word),
                                uses=uses_of(((subject, subject_word), (obj, obj_word))))

        def in_plural(subject, subject_word: str, obj, obj_word: str, plural: str):
            """The same fact said of many ("Wolves are canines.", "Hawks are raptors."). An example of English only:
            the fact is taught once, by the record that says it in the singular.

            WRITTEN BY THE TEACHER, in the frame the lessons teach a kind said of many in ("Birds are animals."), as
            a lesson writes its sentences. Left to the sayer, it was said only where the sayer could already write
            the plural by a learned shape, and that shape is what the sentence teaches: of a thousand, 285 were not
            said at all ("All rushlight are candle." has no plural in it to put the source's in place of)."""
            child, parent = names.get(subject, ""), names.get(obj, "")
            if not (fits(child) and fits(parent)) or child == parent or parent.isdigit():
                return None
            key = (child, "plural", parent, subject_word.lower(), plural)
            if key in seen:
                return None
            seen.add(key)
            written = ((child, subject_word), (parent, obj_word))
            # The kind is said of many too ("Housewives are wives."), in its plural as written; a name of several
            # words in the plural of the word it is used as ("birds of prey"); a kind not counted as it is used
            # ("Oxen are cattle."). A counted kind with no plural known is not said wrong: no sentence.
            kind_written = self._kind_said_of_many(obj, obj_word)
            if kind_written is None:
                return None
            kind = ((parent, kind_written),) if kind_written != obj_word else ()
            return TaughtRecord(subject=child, relation="isa", obj=parent, quality=self.quality,
                                meaning=Meaning("tell", (MeaningFact("isa", child, parent),)),
                                sentence=f"{plural[:1].upper()}{plural[1:]} are {kind_written}.",
                                words=tuple((name, word) for name, word in written if name != word),
                                forms=((child, plural),) + kind, example=True,
                                uses=uses_of(((subject, subject_word), (obj, obj_word)), in_plural=True))

        def in_tense(synset, word: str) -> List[Optional[TaughtRecord]]:
            """A verb sense written `word`, in each of its forms (`_verb_written`), said as the lessons say a doing:
            now ("The dog barks."), before now ("Tom ran.") and under way ("Tom is working."), and by the doer the
            sense's own frames give it (`_DOERS`): someone ("Tom strolled."), someone to something ("Tom bought
            them.", as "The dog chased them."), nothing ("It drizzled.", as "It rained.") or something ("It
            curdled."). Examples of English only. A past said in no sentence was no change the reader could apply:
            WordNet's adjectives written as pasts ("concealed") outnumbered the pasts the lessons showed, the change
            `ed` was not productive (8 of 986 words read rightly), and "compiled" read as a new name."""
            name = names.get(synset, "")
            if not fits(name) or " " in word or not word.isalpha() or word != word.lower():
                return []
            frames = {frame for lemma in synset.lemmas() if self._written(lemma.name()) == word
                      for frame in lemma.frame_ids()}
            doer = next((how for how, of in self._DOERS if frames & of), None)
            if doer is None:
                return []
            out = []
            for form, said, when in (("now", "{}", None), ("past", "{}", "precedes"), ("under way", "is {}", "during")):
                written = self._verb_written(word, form)
                key = (name, "form", word, written or "", doer)
                if not written or key in seen:
                    continue
                seen.add(key)
                facts = [MeaningFact("instance_of", "?v0", name)]
                if doer in ("someone", "someone to something"):
                    facts.append(MeaningFact("done_by", "?v0", "tom"))
                elif doer == "something":
                    facts.append(MeaningFact("done_by", "?v0", "?previous"))
                if doer == "someone to something":
                    facts.append(MeaningFact("done_to", "?v0", "?previous"))
                if when:
                    facts.append(MeaningFact(when, "?v0", "?now"))
                sentence = " ".join(part for part in (
                    "Tom" if doer.startswith("someone") else "It", said.format(written),
                    "them" if doer == "someone to something" else "") if part) + "."
                out.append(TaughtRecord(subject=name, relation="instance_of", obj="", quality=self.quality,
                                        meaning=Meaning("tell", tuple(facts)), sentence=sentence,
                                        words=((name, word),) if name != word else (), forms=((name, written),),
                                        example=True))
            return out

        for synset in wn.all_synsets():
            if not fits(names.get(synset, "")):
                continue
            pos = "a" if synset.pos() == "s" else synset.pos()
            if self.parts and pos not in self.parts:
                continue
            words = list(dict.fromkeys(self._written(lemma) for lemma in synset.lemma_names()))
            word = words[0]
            found = []
            if pos == "v":
                # THE FORMS OF EVERY WORD THE SENSE IS WRITTEN WITH ("Tom strolled.", "Tom sauntered."), as the
                # plurals of a noun's are said (below).
                for written_word in words:
                    found.extend(in_tense(synset, written_word))
            for hypernym in order(synset.hypernyms()):
                # What a thing is a kind of, said for a noun through "A robin is a bird."; a verb's kind as the rule
                # it is over a doing, "To stroll is to walk." (english_41), for every word the sense is written with:
                # said in no sentence, almost no verb sense had a word to be read by (44 of 24,467, 2026-10-12).
                found.append(record("isa", synset, word, hypernym, self._written(hypernym.lemma_names()[0]),
                                    said=pos == "n"))
                if pos == "v":
                    for written_word in words:
                        found.append(as_rule("doing", "isa", synset, written_word, hypernym,
                                             self._written(hypernym.lemma_names()[0])))
                # EVERY WORD THE SENSE IS WRITTEN WITH: "auto" and "automobile" name the car as "car" does, and are
                # learned saying the same fact.
                if pos == "n":
                    for other in words[1:]:
                        found.append(record("isa", synset, other, hypernym,
                                            self._written(hypernym.lemma_names()[0]), said=True))
                    # THE PLURAL OF EVERY WORD THE SENSE IS WRITTEN WITH, in this sense ("Mice are rodents.", "Hawks
                    # are raptors.", "Hawks are militarists."). Only the forms no change makes were said, the rest
                    # left to a word shape: but WordNet's own words ending as plurals do ("glass", "lens",
                    # "species") outnumbered the plurals the lessons showed, the shape `s` was no longer productive,
                    # and "hawks" read as a new name, its sense and every other unreachable (LAB_NOTEBOOK
                    # 2026-10-11 (2)). A word read through its plural reaches only the senses it was said for.
                    for written_word in words:
                        for plural in self._plurals_said(synset, written_word):
                            found.append(in_plural(synset, written_word, hypernym,
                                                   self._written(hypernym.lemma_names()[0]), plural))
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
                # What an adjective is like, as the rule it is over a quality: "To be lovely is to be beautiful."
                # (english_41), for every word the sense is written with. Said in no sentence, almost no adjective
                # sense had a word to be read by (1,252 of 29,703). A SATELLITE IS LIKE ITS HEAD, not the head like
                # it: WordNet lists the pair from both sides, and "To be beautiful is to be lovely." is not so. A
                # number is no quality ("two", like "cardinal"): its likeness is the fact alone.
                found.append(record("similar_to", synset, word, head, self._written(head.lemma_names()[0]),
                                    said=False))
                if synset.pos() == "s" and not names.get(synset, "").isdigit() and not names.get(head, "").isdigit():
                    for written_word in words:
                        found.append(as_rule("quality", "similar_to", synset, written_word, head,
                                             self._written(head.lemma_names()[0])))
            for needed in order(synset.entailments()):
                found.append(record("requires", synset, word, needed, self._written(needed.lemma_names()[0]),
                                    said=False))
            for caused in order(synset.causes()):
                found.append(record("causes", synset, word, caused, self._written(caused.lemma_names()[0]),
                                    said=False))
            for used in (definitions.get(synset, ()) if defines[names[synset]][1] == synset else ()):
                # What the sense is near, in the order its definition says it: what memory relates a sense to when
                # the rest of what is said is about money, or food.
                found.append(record("defined_with", synset, word, used, self._written(used.lemma_names()[0]),
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
                if taught is not None and (taught.example or not examples_only):
                    yield taught

            # THE DEFINITION, SAID AS A SENTENCE. The facts above say what a thing IS; WordNet's gloss says what
            # it DOES. Taught as a sentence with no triple behind it, so it is READ or it is dropped -- there is no
            # fallback that could file a mis-parsed gloss as a taxonomy edge.
            # THE GLOSS IS ABOUT ONE SENSE, and a sentence written with the word is read as the sense the word
            # names most often. So a gloss is said only of the sense the word itself names; another sense's waits
            # for its meaning to be given with it.
            gloss = (synset.definition() or "").strip().rstrip(".")
            if (self.definitions and not examples_only and pos == "n" and gloss and len(gloss.split()) <= 24
                    and names[synset] == word.lower()):
                yield TaughtRecord(
                    subject="", relation="", obj="", quality=self.quality,
                    sentence=f"{_article(word).capitalize()} {word} is {gloss}.")


@dataclass
@dataclass
class WordNetExamplesSource:
    """WordNet's examples of English, each beside the fact WordNet's pass taught (`WordNetSource.records(
    examples_only=True)`): the plural of every noun sense counted, said in a fact WordNet holds of it ("Hawks are
    raptors.", "Mice are rodents."); every verb sense's forms, said of a doer its frames give it ("Tom strolls.",
    "Tom strolled.", "Tom is strolling."); its verbs' kinds and its adjectives' likenesses said as rules ("To stroll is
    to walk.", "To be lovely is to be beautiful.").

    For a store WordNet was taught to before these were said: it teaches the examples, not the facts again, and none
    of what WordNet's pass does besides its records (word classes, usage, what words are said of). `parts`: of those
    parts of speech only ("n" the plurals, "v" the verbs' forms and kinds, "a" the adjectives' likenesses), as
    `WordNetSource.parts`."""

    parts: Tuple[str, ...] = ()
    name: str = "wordnet"
    quality: float = 0.9
    curated: bool = True

    def provenance(self):
        return _provenance("wordnet", "wordnet_3.0")

    def records(self) -> Iterator[TaughtRecord]:
        return WordNetSource(parts=self.parts).records(examples_only=True)


@dataclass
class WordNetUsageSource:
    """How often WordNet's words were met naming each sense, in the text its senses were tagged in (SemCor): its
    usage only (`WordNetSource.usage`), for a store that holds the words. `parts`: of those parts of speech only.

    WordNet's examples were taught with no usage (`WordNetExamplesSource`), so every sense of a verb or adjective
    they gave words to was met as often as another: "Tom compiled them." could not be told from compiling a book or
    rolling something up, and "Are" from the are, a hundred square metres. A source of nothing else, it has no
    records, and the pass counts its usage all the same (`vocabulary_only`)."""

    parts: Tuple[str, ...] = ()
    name: str = "wordnet"
    quality: float = 0.9
    curated: bool = True
    vocabulary_only: bool = True

    def provenance(self):
        return _provenance("wordnet", "wordnet_3.0")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def usage(self) -> Iterator[Tuple[str, str, int, Tuple[str, ...]]]:
        return WordNetSource(parts=self.parts).usage()


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
