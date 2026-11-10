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
import math
import os
import re
from collections import Counter, defaultdict
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
#: WHAT ENGLISH'S CLOSED CLASSES ACTUALLY HOLD, counted against the classes themselves. A closed class is finite,
#: so unlike the open ones it can be stated whole and then checked whole -- and checked, this table held 65 of
#: English's 83 one-word prepositions, 39 of its 68 pronouns, 12 of some 45 interjections (neither "wow" nor
#: "ouch"), and 6 of the 7 coordinating conjunctions, wanting "for" (2026-11-08). A closed-class word is in nearly
#: every sentence, so each one missing costs more than a noun missing does.
#: AND A WORD IS EVERY KIND OF WORD IT IS HERE TOO (`WordNetSource._word_classes` says it of the open classes):
#: "his", "this", "all", "both", "some" and "none" were held a determiner or a quantifier and never a pronoun,
#: though "that's his" and "all are ready" are pronouns, and "no" was a determiner and never a negator.
#: STILL NOT HERE: a preposition of several words -- "out of", "because of", "according to", "instead of", "in
#: front of", "rather than". There are about thirty in ordinary use and this table has never held a word of
#: several words in any class, so they are not data alone: the grammar must read the two as one
#: (`grammar.Lexicon._together`), which is its own measurement.
CLOSED_CLASSES: Dict[str, Tuple[str, ...]] = {
    'COPULA': ('is', 'are', 'am', 'was', 'were', 'be', 'been', 'being'),
    'DETERMINER': (
        'a', 'an', 'the', 'this', 'that', 'these', 'those', 'my', 'your', 'his', 'her', 'its', 'our', 'their',
        'each', 'every', 'no', 'any', 'both', 'either', 'neither', 'another', 'such', 'what', 'which', 'whose',
        'all', 'some', 'many', 'much', 'few', 'several', 'enough', 'certain', 'half', 'last', 'next', 'other',
        'same', 'various'
    ),
    'NEGATOR': ('not', 'never', "n't", 'nor', 'none', 'neither', 'no'),
    'PREPOSITION': (
        'about', 'above', 'across', 'after', 'against', 'along', 'alongside', 'amid', 'among', 'amongst', 'around',
        'as', 'at', 'atop', 'before', 'behind', 'below', 'beneath', 'beside', 'besides', 'between', 'beyond', 'by',
        'concerning', 'despite', 'down', 'during', 'except', 'for', 'from', 'in', 'inside', 'into', 'like', 'near',
        'of', 'off', 'on', 'onto', 'opposite', 'out', 'outside', 'over', 'past', 'per', 'regarding', 'round',
        'since', 'through', 'throughout', 'till', 'to', 'toward', 'towards', 'under', 'underneath', 'unlike',
        'until', 'up', 'upon', 'versus', 'via', 'with', 'within', 'without', 'amidst', 'barring', 'but',
        'considering', 'excepting', 'excluding', 'failing', 'following', 'given', 'including', 'minus',
        'notwithstanding', 'pending', 'plus', 'save', 'than', 'unto', 'worth'
    ),
    'PRONOUN': (
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'mine', 'yours', 'hers',
        'ours', 'theirs', 'myself', 'yourself', 'himself', 'herself', 'itself', 'ourselves', 'yourselves',
        'themselves', 'someone', 'somebody', 'something', 'anyone', 'anybody', 'anything', 'everyone', 'everybody',
        'everything', 'nobody', 'nothing', 'one', 'who', 'whom', 'his', 'its', 'this', 'that', 'these', 'those',
        'which', 'what', 'whose', 'all', 'both', 'each', 'either', 'neither', 'few', 'many', 'much', 'several',
        'some', 'none', 'another', 'other', 'such', 'oneself', 'whoever', 'whomever', 'whatever', 'whichever'
    ),
    'RELATIVE': (
        'that', 'which', 'who', 'whom', 'whose', 'where', 'when', 'whoever', 'whomever', 'whatever', 'whichever',
        'why'
    ),
    'QUANTIFIER': (
        'some', 'most', 'many', 'few', 'several', 'much', 'all', 'every', 'any', 'enough', 'plenty', 'both', 'each',
        'either', 'neither', 'no', 'none', 'little', 'less', 'more', 'fewer'
    ),
    'MODAL': ('can', 'could', 'may', 'might', 'must', 'shall', 'should', 'will', 'would', 'ought', 'need', 'dare', 'used'),
    'AUXILIARY': ('do', 'does', 'did', 'doing', 'done', 'have', 'has', 'had', 'having'),
    'CONJUNCTION': ('and', 'or', 'but', 'nor', 'yet', 'so', 'for'),
    'SUBORDINATOR': (
        'because', 'although', 'though', 'unless', 'while', 'whereas', 'since', 'if', 'when', 'whenever', 'where',
        'wherever', 'after', 'before', 'until', 'once', 'whether', 'lest', 'provided', 'as', 'that', 'albeit',
        'assuming', 'supposing', 'given', 'how', 'why', 'whilst', 'than', 'except', 'save'
    ),
    'INTERJECTION': (
        'yes', 'no', 'oh', 'ah', 'well', 'hello', 'goodbye', 'please', 'thanks', 'sorry', 'ok', 'okay', 'wow',
        'ouch', 'ow', 'hey', 'hi', 'bye', 'hmm', 'huh', 'oops', 'ugh', 'uh', 'um', 'phew', 'alas', 'aha', 'ahem',
        'aw', 'boo', 'bravo', 'damn', 'eh', 'er', 'gee', 'golly', 'gosh', 'hurray', 'hooray', 'jeez', 'nope',
        'yeah', 'shh', 'whoa', 'yay', 'yikes'
    ),
    'NUMERAL': (
        'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
        'hundred', 'thousand', 'million', 'billion', 'first', 'second', 'third', 'thirteen', 'fourteen', 'fifteen',
        'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy',
        'eighty', 'ninety', 'trillion', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth'
    ),
    'PARTICLE': (
        'to', 'up', 'off', 'out', 'down', 'away', 'back', 'over', 'along', 'apart', 'around', 'aside', 'forth',
        'in', 'on', 'through', 'together'
    ),
    'PUNCTUATION': ('.', ',', '?', '!', ';', ':', "'", '"', '-', '--', '(', ')', '[', ']', '—', '–', '…'),
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

#: THE PARADIGM OF THE CLOSED CLASSES, each form with WHAT FORM IT IS. A class
#: alone says "am" is a copula; this says it is the copula's first person
#: singular present, and that "me" is accusative where "I" is nominative --
#: which is the part saying and agreement act on every time they choose a word.
#:
#: STATED, BECAUSE NO CORPUS GIVES IT. The forms a word is held in are counted
#: from the treebanks, so the paradigm has exactly the holes and the junk the
#: analysts left behind: UD writes "am" only as an AUXILIARY and never as a
#: copula VERB, while it does write "ai", "art", "r" and "re", so saying "I am
#: intelligent." was not possible at all and "I is intelligent." was the best
#: sentence the grammar could offer, at full confidence because it was the only
#: one (lyric_db, 2026-10-30). Inference is no answer either: run the reader's
#: learned endings backwards and it writes "washs". These forms are finite and
#: nobody discovers them from text, so they are written down -- the same reason
#: `CLOSED_CLASSES` is written down rather than counted.
#:
#: The features are the treebanks' own (UD), so a stated form and a counted one
#: meet as one kind of thing (`word_forms.WordForms`, `Words.form_features`).
#: Each is stated once: a statement that a form exists is not evidence of how
#: often it is used, and the counted forms carry that.
CLOSED_PARADIGM: Tuple[Tuple[str, str, Tuple[Tuple[str, str], ...]], ...] = (
    # THE COPULA, as a verb in its own right ("I am intelligent.") and as the
    # auxiliary it also is ("I am waiting."). UD holds the second and not the
    # first, which is the hole this closes.
    ("be", "VERB", (
        ("am", "Mood=Ind|Number=Sing|Person=1|Tense=Pres|VerbForm=Fin"),
        ("is", "Mood=Ind|Number=Sing|Person=3|Tense=Pres|VerbForm=Fin"),
        ("are", "Mood=Ind|Number=Plur|Person=1|Tense=Pres|VerbForm=Fin"),
        ("are", "Mood=Ind|Number=Sing|Person=2|Tense=Pres|VerbForm=Fin"),
        ("are", "Mood=Ind|Number=Plur|Person=2|Tense=Pres|VerbForm=Fin"),
        ("are", "Mood=Ind|Number=Plur|Person=3|Tense=Pres|VerbForm=Fin"),
        ("was", "Mood=Ind|Number=Sing|Person=1|Tense=Past|VerbForm=Fin"),
        ("was", "Mood=Ind|Number=Sing|Person=3|Tense=Past|VerbForm=Fin"),
        ("were", "Mood=Ind|Number=Plur|Person=1|Tense=Past|VerbForm=Fin"),
        ("were", "Mood=Ind|Number=Sing|Person=2|Tense=Past|VerbForm=Fin"),
        ("were", "Mood=Ind|Number=Plur|Person=2|Tense=Past|VerbForm=Fin"),
        ("were", "Mood=Ind|Number=Plur|Person=3|Tense=Past|VerbForm=Fin"),
        ("be", "VerbForm=Inf"),
        ("been", "Tense=Past|VerbForm=Part"),
        ("being", "VerbForm=Ger"),
    )),
    # DOING AND HAVING, which mark another doing and are also verbs of their
    # own ("I do the dishes.", "I have a dog."): the same third person singular
    # hole as the copula, "does" and "has" against "do" and "have".
    ("do", "VERB", (
        ("do", "Mood=Ind|Number=Sing|Person=1|Tense=Pres|VerbForm=Fin"),
        ("do", "Mood=Ind|Number=Sing|Person=2|Tense=Pres|VerbForm=Fin"),
        ("do", "Mood=Ind|Number=Plur|Person=1|Tense=Pres|VerbForm=Fin"),
        ("do", "Mood=Ind|Number=Plur|Person=2|Tense=Pres|VerbForm=Fin"),
        ("do", "Mood=Ind|Number=Plur|Person=3|Tense=Pres|VerbForm=Fin"),
        ("does", "Mood=Ind|Number=Sing|Person=3|Tense=Pres|VerbForm=Fin"),
        ("did", "Mood=Ind|Tense=Past|VerbForm=Fin"),
        ("do", "VerbForm=Inf"),
        ("done", "Tense=Past|VerbForm=Part"),
        ("doing", "VerbForm=Ger"),
    )),
    ("have", "VERB", (
        ("have", "Mood=Ind|Number=Sing|Person=1|Tense=Pres|VerbForm=Fin"),
        ("have", "Mood=Ind|Number=Sing|Person=2|Tense=Pres|VerbForm=Fin"),
        ("have", "Mood=Ind|Number=Plur|Person=1|Tense=Pres|VerbForm=Fin"),
        ("have", "Mood=Ind|Number=Plur|Person=2|Tense=Pres|VerbForm=Fin"),
        ("have", "Mood=Ind|Number=Plur|Person=3|Tense=Pres|VerbForm=Fin"),
        ("has", "Mood=Ind|Number=Sing|Person=3|Tense=Pres|VerbForm=Fin"),
        ("had", "Mood=Ind|Tense=Past|VerbForm=Fin"),
        ("have", "VerbForm=Inf"),
        ("had", "Tense=Past|VerbForm=Part"),
        ("having", "VerbForm=Ger"),
    )),
    # THE PRONOUNS AND THEIR CASE. Nothing anywhere said that "I" stands in a
    # subject and "me" in an object, so saying offered either and reading
    # accepted either: "They misled i." was said at full confidence, and
    # "Myself wash myself." was read without complaint.
    ("i", "PRONOUN", (
        ("i", "Case=Nom|Number=Sing|Person=1|PronType=Prs"),
        ("me", "Case=Acc|Number=Sing|Person=1|PronType=Prs"),
        ("myself", "Case=Acc|Number=Sing|Person=1|PronType=Prs|Reflex=Yes"),
    )),
    ("we", "PRONOUN", (
        ("we", "Case=Nom|Number=Plur|Person=1|PronType=Prs"),
        ("us", "Case=Acc|Number=Plur|Person=1|PronType=Prs"),
        ("ourselves", "Case=Acc|Number=Plur|Person=1|PronType=Prs|Reflex=Yes"),
    )),
    ("you", "PRONOUN", (
        ("you", "Case=Nom|Person=2|PronType=Prs"),
        ("you", "Case=Acc|Person=2|PronType=Prs"),
        ("yourself", "Case=Acc|Number=Sing|Person=2|PronType=Prs|Reflex=Yes"),
        ("yourselves", "Case=Acc|Number=Plur|Person=2|PronType=Prs|Reflex=Yes"),
    )),
    ("he", "PRONOUN", (
        ("he", "Case=Nom|Gender=Masc|Number=Sing|Person=3|PronType=Prs"),
        ("him", "Case=Acc|Gender=Masc|Number=Sing|Person=3|PronType=Prs"),
        ("himself", "Case=Acc|Gender=Masc|Number=Sing|Person=3|PronType=Prs|Reflex=Yes"),
    )),
    ("she", "PRONOUN", (
        ("she", "Case=Nom|Gender=Fem|Number=Sing|Person=3|PronType=Prs"),
        ("her", "Case=Acc|Gender=Fem|Number=Sing|Person=3|PronType=Prs"),
        ("herself", "Case=Acc|Gender=Fem|Number=Sing|Person=3|PronType=Prs|Reflex=Yes"),
    )),
    ("it", "PRONOUN", (
        ("it", "Case=Nom|Gender=Neut|Number=Sing|Person=3|PronType=Prs"),
        ("it", "Case=Acc|Gender=Neut|Number=Sing|Person=3|PronType=Prs"),
        ("itself", "Case=Acc|Gender=Neut|Number=Sing|Person=3|PronType=Prs|Reflex=Yes"),
    )),
    ("they", "PRONOUN", (
        ("they", "Case=Nom|Number=Plur|Person=3|PronType=Prs"),
        ("them", "Case=Acc|Number=Plur|Person=3|PronType=Prs"),
        ("themselves", "Case=Acc|Number=Plur|Person=3|PronType=Prs|Reflex=Yes"),
    )),
    # "who" and "whom" ask or relate, of one or of many ("Who is she?", "Who
    # are they?"), so both numbers are stated and neither is fixed. Written
    # with case alone, as they first were here, they said a form no subject
    # the treebanks hold was ever written with, which agreement now weighs
    # against rather than passing over: the case had to be said together with
    # what else a subject is marked by.
    ("who", "PRONOUN", (
        ("who", "Case=Nom|Number=Sing|Person=3|PronType=Rel"),
        ("who", "Case=Nom|Number=Plur|Person=3|PronType=Rel"),
        ("whom", "Case=Acc|Number=Sing|Person=3|PronType=Rel"),
        ("whom", "Case=Acc|Number=Plur|Person=3|PronType=Rel"),
    )),
    # THE DEMONSTRATIVES AND THE INDEFINITE PRONOUNS, standing for a thing
    # ("This is intelligent.", "Everybody waited."). The grammar reads each as
    # a thing, and agreement asks what number it is, and nothing anywhere said:
    # of 11,295 subjects memory holds, none disagreed with any verb, so "This
    # am intelligent." and "These is intelligent." were said at full
    # confidence of a thing being intelligent (lyric_db, 2026-10-30).
    #
    # SAID AS THE TREEBANKS SAY A SUBJECT, number alone and no case or person:
    # that is the form 924 singular and 59 plural pronoun subjects are written
    # with there. Agreement weighs a whole form against the subjects written
    # with that same form, so a combination no subject ever had -- a
    # demonstrative given a case, say -- would be weighed against every verb
    # alike and tell nothing apart.
    ("this", "PRONOUN", (
        ("this", "Number=Sing|PronType=Dem"),
        ("these", "Number=Plur|PronType=Dem"),
    )),
    ("that", "PRONOUN", (
        ("that", "Number=Sing|PronType=Dem"),
        ("those", "Number=Plur|PronType=Dem"),
    )),
) + tuple(
    (word, "PRONOUN", ((word, "Number=Sing|PronType=Ind"),))
    # One of them, taken alone, is one thing: "Everybody is here.", never
    # "Everybody are here." "None" is left out, taking its number from what it
    # is none of, as the quantifiers do.
    for word in ("anybody", "anyone", "anything", "everybody", "everyone", "everything",
                 "nobody", "nothing", "somebody", "someone", "something", "one")
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

    def word_forms(self) -> Iterator[Any]:
        """THE FORMS OF THE CLOSED CLASSES AND WHAT FORM EACH IS (`CLOSED_PARADIGM`), as the layer that holds the
        forms counted from the treebanks holds them (`word_forms.WordForms`), so that stated and counted forms meet
        as one kind of thing and whatever reads one reads the other.

        A class alone could not say that "am" is the copula's first person singular, nor that "me" is accusative
        where "I" is nominative, so saying could offer neither the right copula nor the right pronoun: UD holds "am"
        only as an auxiliary, never as a copula verb."""
        from core.semantics.word_forms import WordForms
        for base, word_class, forms in CLOSED_PARADIGM:
            yield WordForms(base=base, word_class=word_class,
                            forms=tuple((form, features, 1) for form, features in forms),
                            counted_from=self.name)



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

    A record may be a `fact` alone, `[subject, relation, object]`, as WordNet's kinds of doing are taught ("stroll
    isa walk"): no frame taught says a doing's kind as a fact ("To stroll is to walk." says it as a rule over each
    doing, which is not held), and "To look up is to research." does not read.
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
            if "fact" in record:
                subject, relation, obj = record["fact"]
                yield TaughtRecord(subject=subject, relation=relation, obj=obj,
                                   quality=float(record.get("quality", self.quality)),
                                   example=bool(record.get("example", self.examples)))
                continue
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


class Built:
    """ITEMS BUILT ONE AT A TIME, THAT STILL SAY HOW MANY THERE WILL BE.

    The teaching spine materialised every item before teaching the first (`list(...)` at four places down the
    chain), so 144,612 word records were built and held before one word was taught: 2.4 hours and 19.5 GB of a
    pass, and nothing durable if it died (2026-11-10). A word is taught as it is recorded.

    What is known cheaply is HOW MANY -- the names are listed before any record is built -- so progress still says
    where a pass is. `__iter__` makes the items afresh each time, so a second pass over it is a second build, never
    a stale list held in memory."""

    __slots__ = ("_make", "_how_many")

    def __init__(self, make: Any, how_many: int) -> None:
        self._make, self._how_many = make, int(how_many)

    def __len__(self) -> int:
        return self._how_many

    def __iter__(self):
        return iter(self._make())


def _a_name_english_writes(name: str) -> bool:
    """Whether a WordNet lemma is a name English writes: every word of it alphabetic, a hyphen allowed inside a
    word, and no more words than the door admits (`MAX_TERM_WORDS`).

    `.isalpha()` STOOD HERE AND WAS FALSE FOR EVERY NAME OF SEVERAL WORDS. The lemma's underscores are turned into
    spaces the line above, and a string holding a space is not alphabetic, so 67,109 of WordNet's 147,306 names --
    "pygmy chimpanzee", "king salmon", "body of water", "kick the bucket" -- were dropped there in silence and have
    never been taught, 46% of the vocabulary. Hyphenated words went the same way, though `word_record_of` spells
    them three ways on purpose.

    NOTHING WAS MISSING BUT THE WORDS. `word_record_of` builds a whole record for a name of several words already
    (it spells the lemma back with underscores to ask WordNet), and the reader has held such names all along --
    `head` reads "body of water" as a body, not as water. Measured on a review of 200 questions: where both terms
    were one word Lyric answered 33 of 33, and 0 of 24 where a term of several words was named; the review asked
    "Is a pygmy chimpanzee a member of a genus Pan?" and misread it, while WordNet holds that very membership and
    the builder extracts it whole (2026-11-09)."""
    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
    words = name.split()
    return (bool(words) and len(words) <= MAX_TERM_WORDS
            and all(part.replace("-", "").isalpha() for part in words))


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

    def _word_classes(self) -> Dict[str, Tuple[str, ...]]:
        """`word -> its CLASSES`: every class WordNet holds each word of letters in, and each verb of several such
        words, the one its senses are tagged in most (falling back to how many senses carry it when nothing is
        tagged) first.

        A WORD IS EVERY KIND OF WORD IT IS. This settled each word to the one class tagged most, and taught only
        that: "research" was a noun alone (52 tagged uses to the verb's 1), so "Research photosynthesis." read as
        nothing, as "Book a flight.", "List the files." and "Order a pizza." did, and "Contact Dana." told that Dana
        is a contact; "plan" was a verb alone, and "Make a plan." told that a plan is an "a". Of WordNet's 77,503
        single words, 7,048 are of more than one class, and each kept one (lyric_dev, 2026-10-24). A class held is
        evidence that a sentence may use the word so, never that it does: the grammar weighs each by how the word
        is used (`grammar.Lexicon._evidence`), and the copula's complement is a quality only where it stands bare
        (`relation_types.complement_class`).

        AND A VERB OF SEVERAL WORDS IS A VERB: "look up", "find out", "sign up". Nothing else teaches one: a verb's
        words are said in its forms and its kinds ("Tom strolled.", "To stroll is to walk."), and neither says a
        verb of several words; the words of several held are nouns', said with their facts ("credit card"). So
        English's grammar, which reads a verb and the word after it as one verb memory holds together
        (`grammar.Lexicon._together`), held none of WordNet's 2,829, and "Look up photosynthesis." read as nothing
        (lyric_dev, 2026-10-24).

        AND SO IS A QUALITY OR AN ADVERB OF SEVERAL WORDS: "fed up", "in love", "out of print", "kind of", "in
        vain", "at last". Nothing else teaches one, and unlike a noun's words nothing else can: a noun of several
        words is named by its facts ("A credit card is a card."), which hold its words together, where a quality
        has no such fact to be named in. Main held "grow up" and "take off" from these lessons, "credit card" and
        "prime minister" through the facts, and nothing at all for "fed up", "in vain", "at last" or "disco music"
        (lyric_db, 2026-10-29), so the grammar's reading of several words as one word of whatever kind memory holds
        them as (`grammar.Lexicon._together`) could offer a thing there and never a quality or an adverb. WordNet
        holds 483 qualities and 704 adverbs of several words of letters, of which 450 and 657 are stated here.

        A NOUN'S WORDS ARE STILL NOT STATED HERE: there are 58,597 of them, fifty times the qualities and adverbs
        together, and the ones a store is taught the facts of are named by them already. Whether the rest are worth
        a vocabulary of that size is its own measurement, which this is not.

        AND NOT A QUALITY OR AN ADVERB WHOSE WORDS HOLD A PRONOUN ("to it" `thereto`, "on it", "under it", "as it
        is", "in his own right"): a pronoun stands for whatever was spoken of, so words holding one are not one
        word, which means the same wherever it is said. WordNet holds 33 such qualities and 47 such adverbs, and
        taught with the rest they cost a sentence of the 231 GRAMMAR-01's sets hold — "I'm totally indifferent to
        it." read "to it" as `thereto` (lyric_dev2, 2026-10-29) — where of the 63 runs the dev split's sentences say
        that the rest of them call one word, 27 are one concept. Most of the 80 are words no reading wants: 22 are
        "one hundred" and the numbers built on it, which the grammar reads as the number they are, and "in that",
        "in this", "on that", "to that", "that much", "one time" say what their words say. A few real ones go with
        them — "one by one", "one after another", "on the one hand", "in his own right", "one and only" — because
        the grammar reads "one", "that" and "this" as pronouns as well as otherwise.

        Said of the lessons and not of the reading, because a word of several words that holds a pronoun may still be
        one elsewhere: a noun keeps its own word ("coal mine", "gold mine"), named by its facts and not stated here,
        and a verb's "it" can be frozen into the verb ("get it" is to understand, "call it a day"). The 43 verbs
        WordNet holds so have been stated since (73) and are left as they were, so this states more and nothing less.

        Worked out once for the source: WordNet reads each tagged count from its files, and a pass asks for the
        classes more than once.
        """
        if "_classes" in self.__dict__:
            return self.__dict__["_classes"]
        from collections import defaultdict
        from nltk.corpus import wordnet as wn

        from core.semantics import grammar as gm
        pronouns = {word for word, uses in gm.closed_uses().items() if "pron" in uses}
        weight: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for synset in wn.all_synsets():
            word_class = _POS_CLASS.get(synset.pos())
            if not word_class:
                continue
            for lemma in synset.lemmas():
                word = lemma.name().replace("_", " ").strip().lower()
                parts = word.split()
                # A WORD OF LETTERS MAY BE JOINED BY HYPHENS ("right-handed", "state-of-the-art"): kept only of letters,
                # WordNet's 5,093 such words were never taught, and main held none of them as a word (2026-10-29).
                if not parts or not all(re.fullmatch(r"[a-z]+(?:-[a-z]+)*", part) for part in parts):
                    continue
                if len(parts) > 1:
                    # A VERB, A QUALITY OR AN ADVERB OF SEVERAL WORDS IS STATED; A NOUN'S WORDS ARE NAMED BY ITS
                    # FACTS, AND A QUALITY'S OR AN ADVERB'S WORDS HOLD NO PRONOUN.
                    if word_class == "NOUN" or (word_class != "VERB" and any(p in pronouns for p in parts)):
                        continue
                # 0.01: a sense carrying no tagged occurrences still counts a little.
                weight[word][word_class] += lemma.count() + 0.01

        held = {word: tuple(c for c, _ in sorted(by_class.items(), key=lambda kv: kv[1], reverse=True))
                for word, by_class in weight.items()}
        self.__dict__["_classes"] = held
        return held

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
    #: WHAT WORDNET ITSELF CALLS A MANNER: an adverb whose definition begins "in a(n) ... manner" (or way, fashion,
    #: style), which is WordNet's own way of saying that this adverb says of a doing what its adjective says of a
    #: thing. 1,511 of its 3,621 adverb senses say so, 1,454 of them with the adjective named as well (a pertainym),
    #: between them 1,948 of its 4,481 adverb words. A degree, a time, a place or a whole-sentence adverb says
    #: nothing of the kind and is said in no frame the lessons hold: "Tom walked hardly." is not English.
    _MANNER = re.compile(r"^in a[n]? .*\b(manner|way|fashion|style)\b", re.I)
    #: THE DOING AN ADVERB IS SAID OF in these examples, and its past: the walking english_12 says an adverb of
    #: ("The cat walked slowly."), as "Tom" is the doer of every verb's (`in_tense`). ONE doing for every adverb,
    #: because the example asserts nothing -- it shows where an adverb stands and which quality it says.
    _MANNER_OF = ("walk", "walked")

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
        # A SENSE ITS NEAREST KIND CANNOT TELL APART is told apart as one across parts of speech is (above): by another
        # word it is written with, no other sense's; else by a kind further up; else, a verb nothing is above, as
        # English names a doing. The most used first, and after every sense named above, so none of theirs is taken.
        # Left unnamed, `make.v.03` (make or cause to be) and three other senses of "make" were all recorded `make`
        # (TRAIN-FORMAT-02, lyric_dev2, 2026-10-26); named so, 570 of the 845 senses unnamed are named, no name held
        # before changed, `make.v.03` "to make" and `make.v.15` "create make". One still unnamed is not taught.
        for name, synset in sorted(qualify, key=lambda q: (-sum(l.count() for l in q[1].lemmas()), q[1].name())):
            if names[synset]:
                continue
            other = next((w for w in (self._written(l).lower() for l in synset.lemma_names())
                          if w != name and w not in taken and _term_words(w) <= MAX_TERM_WORDS), None)
            above = [k for q in self._qualifiers(synset) for k in q.hypernyms() + q.instance_hypernyms()]
            while above and other is None:
                for kind in self._ordered(above):
                    other = next((c for c in (f"{w} {name}" for w in (self._written(l).lower()
                                                                       for l in kind.lemma_names()) if w != name)
                                  if c not in taken and _term_words(c) <= MAX_TERM_WORDS), None)
                    if other:
                        break
                above = [k for kind in above for k in kind.hypernyms() + kind.instance_hypernyms()]
            if other is None and synset.pos() == "v" and f"to {name}" not in taken:
                other = f"to {name}"
            if other:
                names[synset] = other
                taken.add(other)
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
        vocabulary: each word in every class it holds it in."""
        return ((word, word_class) for word, held in self._word_classes().items() for word_class in held)

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
            stated = tuple((word.lower(), word_class) for _, word in written
                           for word_class in classes.get(word.lower(), ()))
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
            and 1,252 of 29,703, 2026-10-12).

            WRITTEN BY THE TEACHER, in english_41's own two frames, as a kind said of many is written (`in_plural`).
            Left to the sayer, a rule was said only where a frame that says it was already held -- and the frame is
            what english_41 teaches. WordNet's adjectives were taught into the main store at 2026-11-07 01:09 and
            that lesson at 2026-11-08 00:07, so for seventeen hours every quality rule went unsaid and no word was
            ever minted from one: 431 of 17,715 adjective senses had a word to be read by, and every filler the
            frame had ever had was one of the lesson's own thirty words. Taught again into the talking store with
            the frame held first, the same 4,000 records admitted no fact at all (3,104 of them already held) and
            still said 855 sentences and minted 854 words -- nothing was missing but the English (2026-11-08).
            A source that writes its own sentence cannot be undone by the order it is taught in."""
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
                sentence = f"To {subject_word} is to {obj_word}."
            else:
                said_as = (MeaningFact("has_property", "?x", child, condition=True),
                           MeaningFact("has_property", "?x", parent))
                sentence = f"To be {subject_word} is to be {obj_word}."
            written = ((child, subject_word), (parent, obj_word))
            return TaughtRecord(subject=child, relation=relation, obj=parent, quality=self.quality,
                                meaning=Meaning("tell", said_as), sentence=sentence, example=True,
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

        def in_manner(synset, word: str) -> Optional[TaughtRecord]:
            """An adverb sense said of a doing, as english_12 says one ("The cat walked slowly."): its words are
            taught for the QUALITY its adjective names, not for a concept of its own. That is what Lyric's meaning
            language holds an adverb to be -- english_12 reads "The dog barked loudly." as `instance_of(?v0, bark) &
            done_by(?v0, ?t0) & has_property(?v0, loud)`, the quality `loud` said of a doing where an adjective says
            it of a thing -- so a sentence said of a doing and a sentence read from one agree on the same concept.

            ONLY WHAT WORDNET CALLS A MANNER (`_MANNER`) AND DERIVES FROM AN ADJECTIVE (a pertainym): 1,454 of its
            3,621 adverb senses, 1,948 of its 4,481 adverb words. WordNet gives an adverb no kind and no plural, so
            nothing else in this source ever places one: 212 of 4,393 adverb words in the main store had any word
            held of them and the four open classes' coverage ran nouns 70.4%, verbs 59.3%, adjectives 22.4%,
            adverbs 4.8% (2026-11-08). The other 2,167 senses wait on a frame: no lesson says a degree, a time or a
            place adverb of a doing, and an example in a frame nothing holds would teach English that is not
            English."""
            if " " in word or not word.isalpha() or word != word.lower():
                return None
            if not self._MANNER.match((synset.definition() or "").strip()):
                return None
            of = order([p.synset() for lemma in synset.lemmas() if self._written(lemma.name()) == word
                        for p in lemma.pertainyms()])
            quality = next((names.get(s, "") for s in of if fits(names.get(s, ""))), "")
            doing, written = self._MANNER_OF
            key = (quality, "manner", word)
            if not quality or key in seen:
                return None
            seen.add(key)
            return TaughtRecord(subject=quality, relation="has_property", obj="", quality=self.quality,
                                meaning=Meaning("tell", (MeaningFact("instance_of", "?v0", doing),
                                                         MeaningFact("done_by", "?v0", "tom"),
                                                         MeaningFact("precedes", "?v0", "?now"),
                                                         MeaningFact("has_property", "?v0", quality))),
                                sentence=f"Tom {written} {word}.",
                                words=((quality, word),) if quality != word else (),
                                forms=((doing, written),), example=True)

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
            if pos == "r":
                # EVERY WORD AN ADVERB SENSE IS WRITTEN WITH, said of a doing ("Tom walked slowly."), as a verb's
                # forms are said of a doer: WordNet places an adverb no other way.
                for written_word in words:
                    found.append(in_manner(synset, written_word))
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
    to walk.", "To be lovely is to be beautiful."); and every adverb WordNet calls a manner, said of a doing ("Tom
    walked slowly.").

    For a store WordNet was taught to before these were said: it teaches the examples, not the facts again, and none
    of what WordNet's pass does besides its records (word classes, usage, what words are said of). `parts`: of those
    parts of speech only ("n" the plurals, "v" the verbs' forms and kinds, "a" the adjectives' likenesses, "r" the
    adverbs said of a doing), as `WordNetSource.parts`."""

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


@dataclass
class WordNetClassesSource:
    """Every class WordNet holds each word in (`WordNetSource.word_classes`), and nothing else, for a store that holds
    the words: one taught each word the one class it was tagged in most, and "research" was no verb
    (`WordNetSource._word_classes`). A verb, a quality and an adverb of several words are stated with them ("look up",
    "fed up", "in vain"), where a noun's words are named by its facts. A class taught already is not taught again
    (`learn_word_classes`)."""

    name: str = "wordnet"
    quality: float = 0.9
    curated: bool = True

    def provenance(self):
        return _provenance("wordnet", "wordnet_3.0")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def word_classes(self) -> Iterator[Tuple[str, str]]:
        return WordNetSource().word_classes()


@dataclass
class WordNetWordsSource:
    """Every word WordNet names, RECORDED WHOLE (`word_record_of`), so a word has the forms English gives it and not
    only the facts said of it.

    THE FORMS LAYER REACHED 12,228 WORDS WHERE THE FACTS LAYER REACHED 147,306, and nothing but a door was missing.
    `word_record_of` builds a whole record for any word, from WordNet's senses and the treebanks' forms, and its only
    caller replayed a frozen `.jsonl` built from the words the corpus SENTENCES happened to use -- so 93% of the words
    WordNet names were held named and numberless. A noun held no number cannot be told from one of the other number,
    so the composer's weighing of what a determiner was said with has nothing to act on ("A whale's a mammals."), and
    neither has the agreement a subject is asked for: of "A cat is not a dog." and "A whale is not a fish." taught in
    one breath, the first came back "A cat never is a dog." and the second "A whale never are a fish.", `cat` being
    recorded and `whale` not (lyric_dev, 2026-11-07).

    A WORD THE CORPUS NEVER SAID STILL COMES OUT WHOLE, because the forms are English's morphology and not a tally:
    `principality` is given both its numbers at a count of nought, `mammal` its plural at two. So the reach of this
    source is WordNet's, not the treebanks'.

    `parts` the parts of speech to state, WordNet's own letters ("n", "v", "a", "r"); every one when None. A lemma
    written as several words is left to the sources that state it with its facts, as `WordNetClassesSource` leaves it.
    """

    parts: Optional[Tuple[str, ...]] = None
    name: str = "wordnet"
    quality: float = 0.9
    curated: bool = True

    def provenance(self):
        return _provenance("wordnet", "wordnet_3.0")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def word_records(self) -> "Built":
        """Every word WordNet names, each RECORDED AS IT IS TAUGHT (`Built`), never all of them first."""
        from nltk.corpus import wordnet as wn
        # THE WORDS ARE TAKEN BEFORE THE FIRST IS RECORDED. `all_lemma_names` walks WordNet's own lemma dictionary
        # as a generator, and recording a word loads more of WordNet, which grows that dictionary under the walk:
        # "RuntimeError: dictionary changed size during iteration" on the first word recorded. The list of every
        # lemma is 147,311 strings and costs nothing to hold -- which is also how many there will be, said without
        # building one of them.
        said: Set[str] = set()
        words: List[str] = []
        for part in (self.parts or ("n", "v", "a", "r")):
            for lemma in list(wn.all_lemma_names(pos=part)):
                word = str(lemma).replace("_", " ")
                if word not in said and _a_name_english_writes(word):
                    said.add(word)
                    words.append(word)
        return Built(lambda: (word_record_of(word) for word in words), len(words))


# ── Treebanks ───────────────────────────────────────────────────────────────

#: A Universal Dependencies treebank's parts of speech, by the names Lyric's classes go by. A proper noun is a NAME;
#: a symbol and a word of no class (a foreign word, a typo) keep the treebank's sense of them.
_UD_CLASS = {"NOUN": "NOUN", "PROPN": "NAME", "VERB": "VERB", "AUX": "AUXILIARY", "ADJ": "ADJECTIVE",
             "ADV": "ADVERB", "PRON": "PRONOUN", "DET": "DETERMINER", "ADP": "PREPOSITION", "CCONJ": "CONJUNCTION",
             "SCONJ": "SUBORDINATOR", "PART": "PARTICLE", "NUM": "NUMERAL", "PUNCT": "PUNCTUATION",
             "INTJ": "INTERJECTION", "SYM": "SYMBOL", "X": "OTHER"}

#: Where the English Web Treebank is kept on disk (datasets are not in the repository): its training part, the one
#: taught. Its other two parts are held out, to measure what was learned (`experiments/STRUCTURE-01`).
EWT_TRAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "test_data", "syntax", "UD_English-EWT", "en_ewt-ud-train.conllu")


def read_conllu(path: str, said_in: str) -> Iterator[Any]:
    """Each sentence of a CoNLL-U file as it was analysed (`structure.Analysed`): its words, their classes by Lyric's
    names, the word each depends on and as what; `said_in` with the file's sentence id. A word written as several
    ("don't": "do" and "n't") is the several; the enhanced graph's added nodes are not words."""
    from core.semantics.structure import Analysed
    words: List[Tuple[str, str, int, str]] = []
    sent_id = ""
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                if words:
                    yield Analysed(tuple(w for w, _, _, _ in words), tuple(c for _, c, _, _ in words),
                                   tuple(h for _, _, h, _ in words), tuple(r for _, _, _, r in words),
                                   f"{said_in}:{sent_id}")
                words, sent_id = [], ""
                continue
            if line.startswith("# sent_id"):
                sent_id = line.split("=", 1)[1].strip()
                continue
            if line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) != 10 or not cols[0].isdigit():
                continue
            if cols[3] not in _UD_CLASS:
                raise ValueError(f"{path}: {cols[3]!r} is not a Universal Dependencies part of speech")
            words.append((cols[1], _UD_CLASS[cols[3]], int(cols[6]), cols[7]))
    if words:
        yield Analysed(tuple(w for w, _, _, _ in words), tuple(c for _, c, _, _ in words),
                       tuple(h for _, _, h, _ in words), tuple(r for _, _, _, r in words), f"{said_in}:{sent_id}")


#: UD's other English treebanks a teaching pass can take, by the name it is asked for: the parts taught (their test
#: part never, it is held out), and the licence each is released under. Each is kept under its own source, so what
#: one taught can be found, and withdrawn, by it: the non-commercial ones (`NC`) are not for a store that is sold.
TREEBANKS = {
    "ewt": ("UD_English-EWT", ("train",), "CC BY-SA 4.0"),
    "gum": ("UD_English-GUM", ("train", "dev"), "CC BY-NC-SA 4.0"),
    "lines": ("UD_English-LinES", ("train", "dev"), "CC BY-NC-SA 4.0"),
    "partut": ("UD_English-ParTUT", ("train", "dev"), "CC BY-NC-SA 4.0"),
    "atis": ("UD_English-Atis", ("train", "dev"), "CC BY-SA 4.0"),
    "eslspok": ("UD_English-ESLSpok", ("train", "dev"), "CC BY-SA 4.0"),
}


@dataclass
class TreebankSource:
    """Sentences analysed by hand, each word's class and the word it depends on and as what: a Universal Dependencies
    treebank (CoNLL-U), the English Web Treebank by default (CC BY-SA 4.0), or another of `TREEBANKS` by its name
    (`of`). It teaches how the words of a sentence go together (`analysed()`, `structure`), and states nothing else,
    so it has no records (`vocabulary_only`).

    More analysed English is what raises the structure reader: learned from EWT with GUM, LinES, ParTUT, Atis and
    ESL Spoken beside it, UAS on EWT dev 78.3% to 80.2%, on PUD 75.5% to 78.7%, on GUM's held-out test 75.7% to 79.4%
    (`experiments/STRUCTURE-03`).

    It teaches the forms its words are written in too (`word_forms()`): each word's base form and features, as the
    treebank's analysts gave them, so "hired" is read as `hire`."""

    path: str = EWT_TRAIN
    name: str = "ud_english_ewt"
    quality: float = 0.9
    curated: bool = True
    vocabulary_only: bool = True
    paths: Tuple[str, ...] = ()

    @classmethod
    def of(cls, treebank: str, data: str = "") -> "TreebankSource":
        """The source teaching the treebank of this name (`TREEBANKS`), from where the datasets are kept."""
        folder, parts, _ = TREEBANKS[treebank]
        root = os.path.join(data or SYNTAX_DATA, folder)
        stem = folder.split("-", 1)[1].lower()
        return cls(path=os.path.join(root, f"en_{stem}-ud-{parts[0]}.conllu"), name=f"ud_english_{stem}",
                   paths=tuple(os.path.join(root, f"en_{stem}-ud-{part}.conllu") for part in parts))

    def provenance(self):
        return _provenance(self.name, "ud_english_ewt_2.18" if self.name == "ud_english_ewt" else self.name)

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def _paths(self) -> Tuple[str, ...]:
        paths = self.paths or (self.path,)
        for path in paths:
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"the treebank is not at {path}; fetch it first (github.com/UniversalDependencies, "
                    f"{os.path.basename(os.path.dirname(path))}). A teaching pass does not reach the network.")
        return paths

    def analysed(self) -> Iterator[Any]:
        return (analysed for path in self._paths() for analysed in read_conllu(path, self.name))

    def word_forms(self) -> Iterator[Any]:
        """Each word of the open classes the treebank wrote in a form other than its base, with every such form and
        what form it is, as the treebank's analysts gave its base form and features (`word_forms`): "hired" is
        `hire` in the past. The same sentences `analysed` gives, their lemma and features columns read too."""
        from core.semantics.word_forms import forms_from_conllu

        def lines():
            for path in self._paths():
                with open(path, encoding="utf-8") as handle:
                    yield from handle
        return iter(forms_from_conllu(lines(), self.name))


# ── PropBank ────────────────────────────────────────────────────────────────

#: Where PropBank is kept on disk beside the treebank (datasets are not in the repository): its annotations and its
#: frame files, each cloned from github.com/propbank (CC BY-SA 4.0).
SYNTAX_DATA = os.path.dirname(os.path.dirname(EWT_TRAIN))


@dataclass(frozen=True)
class PropBankWord:
    """A word of a treebank sentence PropBank annotates, as UD English EWT writes it: the word, its lemma, its class
    by Lyric's names, the word it depends on (1 for the first, 0 for the root) and as what."""

    form: str
    lemma: str
    word_class: str
    head: int
    relation: str


@dataclass(frozen=True)
class PropBankPredicate:
    """One predicate PropBank annotates: where it stands (0 for the first word), its sense (`give.01`), its Penn tag,
    and its arguments: each label with the spans it covers, (start, end) of the sentence's words."""

    at: int
    roleset: str
    tag: str
    arguments: Tuple[Tuple[str, Tuple[Tuple[int, int], ...]], ...]


def propbank_roles_of_frames(frames: str) -> Dict[Tuple[str, str], Tuple[str, Tuple[str, ...]]]:
    """(sense, ARGn) -> (function tag, VerbNet 3.4 roles), from PropBank's frame files."""
    import xml.etree.ElementTree as ET
    from pathlib import Path
    roles: Dict[Tuple[str, str], Tuple[str, Tuple[str, ...]]] = {}
    for path in Path(frames).glob("*.xml"):
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        for roleset in tree.iter("roleset"):
            for role in roleset.iter("role"):
                verbnet = tuple(sorted({link.text.strip().lower() for link in role.iter("rolelink")
                                        if link.get("resource") == "VerbNet" and link.get("version") == "verbnet3.4"
                                        and link.text}))
                roles[(roleset.get("id"), "ARG" + str(role.get("n")).upper())] = (role.get("f", ""), verbnet)
    return roles


def read_propbank_ewt(release: str, treebank: str
                      ) -> Iterator[Tuple[str, str, int, Tuple[PropBankWord, ...], Tuple[PropBankPredicate, ...]]]:
    """PropBank's annotations of the English Web Treebank with the words and structure of UD English EWT: each
    sentence as (part, document, index, words, predicates), its part UD's (train, dev, test).

    PropBank writes each word `[WORD]`, pointing into the LDC's copy of the text; UD holds the same sentences, matched
    here by document and place, and a sentence is read only where both have the same number of words (16,548 of
    16,579)."""
    from pathlib import Path
    words_of: Dict[Tuple[str, int], Tuple[str, Tuple[PropBankWord, ...]]] = {}
    for part in ("train", "dev", "test"):
        sent_id, words = None, []
        with open(Path(treebank) / f"en_ewt-ud-{part}.conllu", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("# sent_id"):
                    sent_id = line.split("=", 1)[1].strip()
                elif not line.strip():
                    found = re.match(r"[a-z]+-(.+)-(\d+)$", sent_id or "")
                    if found:
                        words_of[(found.group(1), int(found.group(2)) - 1)] = (part, tuple(words))
                    sent_id, words = None, []
                elif not line.startswith("#"):
                    cols = line.rstrip("\n").split("\t")
                    if cols[0].isdigit():
                        words.append(PropBankWord(cols[1], cols[2].lower(), _UD_CLASS.get(cols[3], cols[3]),
                                                  int(cols[6]), cols[7]))
    for path in sorted(Path(release, "data", "google", "ewt").rglob("*.gold_skel")):
        block: List[List[str]] = []
        with open(path, encoding="utf-8") as handle:
            lines = list(handle) + [""]
        for line in lines:
            cols = line.split()
            if cols:
                block.append(cols)
                continue
            if not block:
                continue
            document, index = block[0][0].split("/")[-1].replace(".xml", ""), int(block[0][1])
            found = words_of.get((document, index))
            if found is not None and len(found[1]) == len(block):
                heads = [(i, row[7], row[4]) for i, row in enumerate(block) if row[7] != "-"]
                predicates = []
                for k, (at, roleset, tag) in enumerate(heads):
                    spans: Dict[str, List[Tuple[int, int]]] = {}
                    opened: List[List[Any]] = []
                    for i, row in enumerate(block):
                        cell = row[8 + k] if 8 + k < len(row) else "*"
                        for name in re.findall(r"\(([^*()]+)\*", cell):
                            opened.append([name, i])
                        for _ in range(cell.count(")")):
                            if opened:
                                name, start = opened.pop()
                                spans.setdefault(name, []).append((start, i + 1))
                    predicates.append(PropBankPredicate(at, roleset, tag, tuple(
                        (label, tuple(found_spans)) for label, found_spans in spans.items() if label != "V")))
                yield found[0], document, index, found[1], tuple(predicates)
            block = []


@dataclass
class PropBankSource:
    """What PropBank's annotations of the English Web Treebank say of each happening's arguments (CC BY-SA 4.0): each
    annotated sentence of the training part, with UD's analysis of it and what each argument is said in, in the
    meaning language (`argument_structure.Argued`, `propbank_roles`). It teaches which phrases are a happening's
    arguments and what each is (`argued()`, `argument_structure.ArgumentStructureView`), and states nothing else."""

    data: str = SYNTAX_DATA
    name: str = "propbank_ewt"
    quality: float = 0.9
    curated: bool = True
    vocabulary_only: bool = True

    def provenance(self):
        return _provenance("propbank_ewt", "propbank_release_ewt")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def argued(self) -> Iterator[Any]:
        from core.semantics.argument_structure import argued_from_propbank
        release, frames = os.path.join(self.data, "propbank-release"), os.path.join(self.data, "propbank-frames")
        treebank = os.path.join(self.data, "UD_English-EWT")
        for path in (release, frames, treebank):
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"{path} is not there; fetch it first (github.com/propbank/propbank-release and propbank-frames, "
                    f"UniversalDependencies/UD_English-EWT). A teaching pass does not reach the network.")
        roles = propbank_roles_of_frames(os.path.join(frames, "frames"))
        return iter(argued_from_propbank(list(read_propbank_ewt(release, treebank)), roles))


@dataclass
class CompositionSource:
    """The lessons' sentences, each with the meaning it was taught to have, kept whole so the composer learns from
    them how a sentence's meaning is composed from how its words go together (`composition.TaughtSentence`,
    `composition.CompositionView`). It states nothing else: the facts each sentence states are taught by the lessons
    themselves."""

    paths: Tuple[str, ...] = ()
    name: str = "composition"
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

    def taught_sentences(self) -> Iterator[Any]:
        """Every sentence of the lessons with its taught meaning, each said in its lesson."""
        from core.semantics.composition import TaughtSentence
        for path in self.paths:
            lesson = os.path.splitext(os.path.basename(path))[0]
            for sentence, meaning in ListeningSource(paths=(path,)).listening_pairs():
                yield TaughtSentence(sentence, meaning, lesson)


#: Where the Parallel Meaning Bank is kept on disk (not in the repository): release 5.1.0, from
#: https://pmb.let.rug.nl/releases/pmb-5.1.0.zip, extracted to `pmb-5.1.0/`.
PMB_DATA = os.path.join(os.path.dirname(SYNTAX_DATA), "semantics", "pmb", "pmb-5.1.0")


@dataclass
class PMBSource:
    """English sentences of the Parallel Meaning Bank (University of Groningen; annotations ODC-BY 1.0, texts under
    their sources' licences: attribute the PMB, Abzianidze et al. 2017, in any public use), each with its meaning
    said in Lyric's meaning language (`pmb_meanings.meaning_of`) and where in the sentence each of its terms is said
    (`TaughtSentence.anchors`), kept whole so the composer learns what a sentence means from how its words go
    together (`composition.CompositionView`). Only the training part (`split/en/train`): the dev and test parts are
    held out to measure by (`experiments/PMB-01`). A sentence holding what the meaning language does not say yet is
    left out, never guessed (`pmb_meanings.Said.gaps`). `part` "gold" (checked by hand, 6,822 said whole) or
    "silver" (checked in part, 52,267 said whole). It states nothing else."""

    data: str = PMB_DATA
    part: str = "gold"
    name: str = "parallel_meaning_bank_gold"
    quality: float = 0.95
    curated: bool = True
    vocabulary_only: bool = True

    @classmethod
    def of(cls, part: str, data: str = "") -> "PMBSource":
        """The source teaching this part of the PMB's training sentences: "gold" or "silver"."""
        if part not in ("gold", "silver"):
            raise ValueError(f"the PMB's training part is gold or silver, not {part!r}")
        return cls(data=data or PMB_DATA, part=part, name=f"parallel_meaning_bank_{part}",
                   quality=0.95 if part == "gold" else 0.85, curated=part == "gold")

    def provenance(self):
        return _provenance(self.name, f"pmb_5.1.0_en_train_{self.part}")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def taught_sentences(self) -> Iterator[Any]:
        """Each training sentence of the part said whole, with its meaning and its terms' places, said in its
        document (`pmb/p50/d0779`)."""
        from nltk.corpus import wordnet as wn
        from core.semantics import pmb_meanings
        from core.semantics.composition import TaughtSentence
        listed = os.path.join(self.data, "split", "en", "train", f"{self.part}.sbn")
        if not os.path.exists(listed):
            raise FileNotFoundError(
                f"{listed} is not there; fetch the PMB first (https://pmb.let.rug.nl/releases/pmb-5.1.0.zip, "
                f"extracted under {os.path.dirname(self.data)}). A teaching pass does not reach the network.")
        names = WordNetSource()._sense_names()

        def name_of(sense: str) -> Optional[str]:
            try:
                return names.get(wn.synset(sense)) or None
            except Exception:
                return None
        from pathlib import Path
        root = Path(self.data) / "data" / "en" / self.part
        for doc_id in pmb_meanings.split_ids(Path(listed)):
            document = pmb_meanings.read_document(root / doc_id)
            if document is None:
                continue
            said = pmb_meanings.meaning_of(document, name_of)
            if said.meaning is None:
                continue
            anchors = []
            for term, at in said.anchors.items():
                lines = tuple((c.span[0], c.span[1], how, c.marked)
                              for c, how in ((document.concepts[k], how) for k, how in at) if c.span)
                if lines:
                    anchors.append((term, lines))
            yield TaughtSentence(document.text, said.meaning, f"pmb/{doc_id}", tuple(anchors))


#: Where the PMB's release 4.0.0 is kept on disk beside 5.1.0 (data is not in the repository): its documents' CCG
#: derivations, checked by hand in its gold part (`<doc>/en.parse.tags`).
PMB_DERIVATIONS_DATA = os.path.join(os.path.dirname(PMB_DATA), "pmb-4.0.0")


@dataclass
class PMBDerivationSource:
    """English sentences of the Parallel Meaning Bank as they were derived by hand in a categorial grammar (release
    4.0.0, gold: 10,715 documents checked by hand; University of Groningen, annotations ODC-BY 1.0, attribute the PMB,
    Abzianidze et al. 2017, in any public use): each word with the category it has in its sentence, its part of
    speech, lemma, WordNet sense and VerbNet roles (`pmb_meanings.read_derivations`, `grammar.Derived`). It teaches
    what each word takes beside the words around it, which English's grammar chooses a word's category by
    (`Lexicon.hear_derived`); it states nothing else. Release 5.1.0's dev and test documents (`held_out`) are held
    out to measure by (`experiments/GRAMMAR-01`) and never taught: 1,041 of 5.1.0's 1,194 dev documents are among
    4.0.0's gold."""

    data: str = PMB_DERIVATIONS_DATA
    held_out: str = PMB_DATA
    part: str = "gold"
    name: str = "parallel_meaning_bank_derivations_gold"
    quality: float = 0.95
    curated: bool = True
    vocabulary_only: bool = True

    def provenance(self):
        return _provenance(self.name, f"pmb_4.0.0_en_{self.part}_derivations")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def derived(self) -> Iterator[Any]:
        """Each sentence derived by hand of every document of the part that release 5.1.0 does not hold out, in
        order (`pmb/p00/d0004`)."""
        from pathlib import Path
        from core.semantics import pmb_meanings
        root = Path(self.data) / "data" / "en" / self.part
        splits = Path(self.held_out) / "split" / "en"
        listed = [splits / "dev" / "standard.sbn", splits / "test" / "standard.sbn", splits / "test" / "long.sbn"]
        missing = [str(p) for p in [root] + listed if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"{', '.join(missing)} not there; fetch the PMB first (https://pmb.let.rug.nl/releases/pmb-4.0.0.zip "
                f"and pmb-5.1.0.zip, extracted under {os.path.dirname(self.data)}). A teaching pass does not reach "
                f"the network.")
        held_out = {doc for path in listed for doc in pmb_meanings.split_ids(path)}
        for folder in sorted(root.glob("p*/d*")):
            if f"{folder.parent.name}/{folder.name}" in held_out:
                continue
            yield from pmb_meanings.read_derivations(folder)


# ── ONE SENTENCE, EVERY LAYER: the record Lyric is taught from ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class RecordWord:
    """One word of a sentence recorded whole (`SentenceRecord`): where it is (`at`, and its characters in the text,
    `start` to `end`), how it is written, its base form, its class (Lyric's names: NOUN, NAME, VERB, AUXILIARY,
    PREPOSITION, ...), the source's part of speech (Penn's), what form it is (a treebank's features: "Tense=Past"),
    its category in a categorial grammar as the PMB writes it ("(s:dcl\\np)/np"), the word it is joined to (`head`,
    its position; -1 for the sentence's own word) and as what (`relation`, a treebank's: nsubj, obj, det, case, obl,
    punct, ...). Which sense each word has and what it names is the meaning's (`SentenceRecord.terms`, `facts`), and
    what a verb's places are its word's record's (`WordRecord`): the PMB's WordNet sense, semantic tag and VerbNet
    roles of each word, recorded too until 2026-10-26, repeated them and were read by nothing."""

    at: int
    form: str
    start: int
    end: int
    lemma: str
    word_class: str
    tag: str = ""
    features: str = ""
    category: str = ""
    head: int = -1
    relation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"at": self.at, "form": self.form, "start": self.start, "end": self.end, "lemma": self.lemma,
                "class": self.word_class, "tag": self.tag, "features": self.features, "category": self.category,
                "head": self.head, "relation": self.relation}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecordWord":
        return cls(int(data["at"]), str(data["form"]), int(data["start"]), int(data["end"]), str(data["lemma"]),
                   str(data["class"]), str(data.get("tag") or ""), str(data.get("features") or ""),
                   str(data.get("category") or ""), int(data.get("head", -1)), str(data.get("relation") or ""))


@dataclass(frozen=True)
class RecordFact:
    """One fact of a recorded sentence's meaning, in Lyric's meaning language (`derived_reader.MeaningFact`), and the
    words that say it: its terms' words and the words saying the link ("with" for `done_with`, "the" for a thing
    given, the verb and its auxiliaries for when)."""

    relation: str
    subject: str
    obj: str
    positive: bool = True
    condition: bool = False
    alternative: bool = False
    unasserted: bool = False
    given: bool = False
    words: Tuple[int, ...] = ()

    def fact(self):
        from core.semantics.derived_reader import MeaningFact
        return MeaningFact(self.relation, self.subject, self.obj, self.positive, self.condition, self.alternative,
                           self.unasserted, self.given)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"relation": self.relation, "subject": self.subject, "object": self.obj,
                                "words": list(self.words)}
        for flag in ("condition", "alternative", "unasserted", "given"):
            if getattr(self, flag):
                data[flag] = True
        if not self.positive:
            data["positive"] = False
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecordFact":
        return cls(str(data["relation"]), str(data["subject"]), str(data["object"]), bool(data.get("positive", True)),
                   bool(data.get("condition")), bool(data.get("alternative")), bool(data.get("unasserted")),
                   bool(data.get("given")), tuple(int(k) for k in data.get("words") or ()))


#: Terms of a meaning no word of the sentence need say: now, who speaks, who listens, the one spoken of before.
_UNSAID_TERMS = frozenset({"?now", "?speaker", "?listener", "?previous", "?there"})


@dataclass(frozen=True)
class SentenceRecord:
    """ONE SENTENCE AS LYRIC IS TAUGHT IT, EVERY LAYER BY WORD POSITION: its words (`RecordWord`: form, base, class,
    form features, category, the word it is joined to and as what), how its words were
    combined (`tree`, the PMB's derivation by word positions: `grammar.Derived.tree`), its names of several words
    (`names`: first and last word, the name), and its meaning in Lyric's meaning language (`act`, `facts`, `asked`),
    each term of it with the words saying it (`terms`: a pronoun's term with the words of what it stands for, "?speaker"
    with "I"). Where it came from (`source`, `licence`), and whether it is taught or held out to measure by
    (`split`).

    Every part of reading learns from its layer of the same records (`analysed`, `derived`, `taught`, `forms`):
    learned each from a source of its own, written each its own way, the layers were joined by conventions written by
    hand (2026-10-26); here they are one sentence's, aligned once, checked (`problems`)."""

    id: str
    text: str
    act: str
    words: Tuple[RecordWord, ...]
    facts: Tuple[RecordFact, ...]
    terms: Tuple[Tuple[str, Tuple[int, ...]], ...]
    tree: Any = ()
    names: Tuple[Tuple[int, int, str], ...] = ()
    asked: Tuple[str, ...] = ()
    source: str = ""
    licence: str = ""
    split: str = "train"

    # ── what it is ──
    def document(self) -> Tuple[str, int]:
        """The document and which of its sentences ("pmb/p24/d3535#1": pmb/p24/d3535, 1)."""
        document, _, part = self.id.partition("#")
        return document, int(part or 1)

    def key(self) -> str:
        import hashlib
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()[:32]

    def identity(self) -> Optional[Tuple[str, str]]:
        """What it is a record of: one sentence of a document. Recorded again otherwise, it corrects the memory holding
        the first (`MemoryAgent._remember_whole`)."""
        return ("record", self.id)

    def claim(self) -> str:
        """What it was taught as, as the knowledge ledger records it: the sentence as recorded, every layer."""
        return f'"{self.text}" as recorded whole ({self.id}, {self.key()[:8]})'

    def said(self) -> str:
        """The sentence and its meaning: memory keeps a record, never reads it as a claim."""
        return f'"{self.text}"\nrecorded whole: means {self.meaning().canonical()}'

    def meaning(self):
        from core.semantics.derived_reader import Meaning
        return Meaning(self.act, tuple(f.fact() for f in self.facts), tuple(self.asked))

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "source": self.source, "licence": self.licence, "split": self.split,
                "text": self.text, "act": self.act, "words": [w.to_dict() for w in self.words],
                "tree": self.tree, "names": [list(n) for n in self.names],
                "facts": [f.to_dict() for f in self.facts], "asked": list(self.asked),
                "terms": [[t, list(at)] for t, at in self.terms]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SentenceRecord":
        from core.semantics.grammar import _tupled
        return cls(str(data["id"]), str(data["text"]), str(data["act"]),
                   tuple(RecordWord.from_dict(w) for w in data["words"]),
                   tuple(RecordFact.from_dict(f) for f in data["facts"]),
                   tuple((str(t), tuple(int(k) for k in at)) for t, at in data.get("terms") or ()),
                   _tupled(data.get("tree") or ()),
                   tuple((int(n[0]), int(n[1]), str(n[2])) for n in data.get("names") or ()),
                   tuple(data.get("asked") or ()), str(data.get("source") or ""), str(data.get("licence") or ""),
                   str(data.get("split") or "train"))

    # ── checked ──
    def problems(self) -> List[str]:
        """What is wrong with the record, each said: an empty list where every layer is whole and aligned."""
        from core.semantics.derived_reader import is_variable
        out: List[str] = []
        n = len(self.words)
        if not n:
            return ["no words"]
        if self.act not in ("tell", "ask", "request"):
            out.append(f"act {self.act!r} is none of tell, ask, request")
        for k, w in enumerate(self.words):
            if w.at != k:
                out.append(f"word {k} says it is at {w.at}")
            if self.text[w.start:w.end] != w.form:
                out.append(f"word {k} {w.form!r} is not at {w.start}-{w.end} of the text "
                           f"({self.text[w.start:w.end]!r})")
            if not w.lemma or not w.word_class or not w.relation:
                out.append(f"word {k} {w.form!r} lacks its base, class or relation")
            if not w.category:
                out.append(f"word {k} {w.form!r} has no category")
            if not -1 <= w.head < n or w.head == k:
                out.append(f"word {k} {w.form!r} is joined to {w.head}")
        roots = [w.at for w in self.words if w.head == -1]
        if len(roots) != 1:
            out.append(f"{len(roots)} words are the sentence's own (one is)")
        for w in self.words:
            seen, at = set(), w.at
            while at != -1 and at not in seen:
                seen.add(at)
                at = self.words[at].head
            if at != -1:
                out.append(f"word {w.at} {w.form!r} is joined round in a circle")
                break
        leaves: List[int] = []

        def walk(node: Any) -> None:
            if isinstance(node, int):
                leaves.append(node)
            elif node:
                for kid in node[2:]:
                    if not isinstance(kid, str):
                        walk(kid)
        walk(self.tree)
        # The derivation counts its words as `derived` gives them, a name of several words one: "Did you bring a hair
        # dryer?" is six. Compared with the record's places, every sentence with such a name before its last word
        # was refused.
        if sorted(leaves) != list(range(len(self._derived_positions()))):
            out.append("the derivation does not combine every word once")
        aligned = dict(self.terms)
        for f in self.facts:
            for term in (f.subject, f.obj):
                if term in _UNSAID_TERMS or (not is_variable(term) and term.lower() in ("true", "false")):
                    continue
                if term not in aligned:
                    out.append(f"{f.relation}({f.subject}, {f.obj}): no word says {term}")
            if not f.words:
                out.append(f"{f.relation}({f.subject}, {f.obj}): no word said to say it")
            if any(not 0 <= k < n for k in f.words):
                out.append(f"{f.relation}({f.subject}, {f.obj}): a word out of the sentence")
        for t, at in self.terms:
            if not at or any(not 0 <= k < n for k in at):
                out.append(f"term {t} said by no word of the sentence")
        for first, last, name in self.names:
            if not 0 <= first < last < n:
                out.append(f"name {name!r} spans {first}-{last}")
        for t in self.asked:
            if not any(t in (f.subject, f.obj) for f in self.facts):
                out.append(f"{t} is asked but no fact holds it")
        return out

    def _derived_positions(self) -> List[int]:
        """Each word's place as the derivation counts them: a name of several words is one."""
        inside = {k for first, last, _ in self.names for k in range(first + 1, last + 1)}
        return [k for k in range(len(self.words)) if k not in inside]

    # ── each layer, as the part of reading that learns from it takes it ──
    def analysed(self):
        """The words, classes and what each is joined to, as the structure reader learns them (`structure.Analysed`:
        heads from 1, 0 for the sentence's own)."""
        from core.semantics.structure import Analysed
        return Analysed(tuple(w.form for w in self.words), tuple(w.word_class for w in self.words),
                        tuple(w.head + 1 for w in self.words), tuple(w.relation for w in self.words),
                        said_in=self.id)

    def derived(self):
        """The derivation, as English's grammar learns each word's category beside the words around it
        (`grammar.Derived`): a name of several words one word, its parts joined by "~", as the PMB writes it."""
        from core.semantics.grammar import Derived
        firsts = {first: (last, name) for first, last, name in self.names}
        words, categories, tags, lemmas, spans = [], [], [], [], []
        k = 0
        while k < len(self.words):
            last = firsts.get(k, (k, ""))[0]
            part = self.words[k:last + 1]
            heading = self.words[last]
            words.append("~".join(w.form for w in part))
            categories.append(heading.category)
            tags.append(heading.tag)
            lemmas.append("~".join(w.lemma for w in part))
            spans.append((part[0].start, part[-1].end))
            k = last + 1
        document, part_of = self.document()
        # A derivation holds a sense, roles and a semantic tag for each word; the grammar reads none of them.
        none = tuple("" for _ in words)
        return Derived(self.text, tuple(words), tuple(categories), tuple(tags), tuple(lemmas), none,
                       tuple(() for _ in words), none, tuple(spans), self.tree, document, part_of)

    def taught(self):
        """The sentence and its meaning, each term at the characters of the words saying it, as English's grammar
        learns what each link says (`composition.TaughtSentence`), said in the document its derivation is."""
        from core.semantics.composition import TaughtSentence
        anchors = []
        for term, at in self.terms:
            said = tuple((self.words[k].start, self.words[k].end, "head", ()) for k in at)
            anchors.append((term, said))
        return TaughtSentence(self.text, self.meaning(), self.document()[0], tuple(anchors))

    def verb_uses(self) -> List[Tuple[str, str, str, str]]:
        """Each verb of the sentence in the sense its meaning names, with what is in its places, as English's grammar
        learns which sense a sentence means (`GrammarView.hold_use`): (the verb's word, its sense, subject or object,
        the thing: its kind's name, or its name) — ("fastened", `fasten`, object, `award decoration`)."""
        from core.semantics.derived_reader import is_variable
        words_of = {k: t for t, at in self.terms for k in at}
        named: Dict[str, str] = {}
        for f in self.facts:
            if f.relation == "instance_of" and f.positive and not is_variable(f.obj):
                named.setdefault(f.subject, f.obj)

        def concept(k: int) -> str:
            term = words_of.get(k, "")
            return named.get(term, "" if is_variable(term) else term)
        out = []
        for w in self.words:
            if w.word_class != "VERB" or not concept(w.at):
                continue
            for d in self.words:
                slot = {"nsubj": "subject", "obj": "object", "nsubj:pass": "object"}.get(d.relation)
                if d.head == w.at and slot and concept(d.at):
                    out.append((w.form, concept(w.at), slot, concept(d.at)))
        return out

    def forms(self) -> List[Any]:
        """Each word's form, as the forms memory holds words written in (`word_forms.WordForms`): its base, class
        and features."""
        from core.semantics.word_forms import WordForms
        return [WordForms(w.lemma.lower(), w.word_class, ((w.form.lower(), w.features, 1),), f"{self.id}@{w.at}")
                for w in self.words if w.word_class not in ("PUNCTUATION", "SYMBOL")]


@dataclass
class RecordSource:
    """Words and sentences recorded whole (`WordRecord`, `SentenceRecord`), one a line of a JSON Lines file: every
    layer of each, as every part of reading learns from it. `split` "train" teaches the records taught; the held-out ones are only measured
    by."""

    path: str
    split: str = "train"
    name: str = "sentence_records"
    quality: float = 0.95
    curated: bool = True
    vocabulary_only: bool = True

    def provenance(self):
        return _provenance(self.name, os.path.basename(self.path))

    def records(self) -> Iterator[TaughtRecord]:
        """EACH SENTENCE RECORDED WHOLE, WITH ITS MEANING, so the constructions it is read through are learned from
        the same lesson as its words (`learn_patterns`).

        This returned nothing at all, and that is why no store ever held a construction: `patterns` is filled only
        from this stream, so `learn_patterns` was never called by the one format Lyric is taught from, and every
        teaching session reported "patterns: none taught" in the words of a run that was asked and failed. Nothing
        was missing from the standard -- a `SentenceRecord` already carries the sentence (`text`) and its meaning
        (`meaning`), which is all a pattern is learned from.

        `example` is set, so the facts are NOT taught again here: they are the record's own and reach memory through
        `learn_records`, which holds every layer of it. Only the pattern is learned from this."""
        for record in self.sentence_records():
            # HOW THIS SENTENCE WRITES EACH THING ITS MEANING NAMES, from the record's own alignment of terms to
            # word positions (`terms`): a run of words saying one thing is learned as that thing's name and never
            # taken apart into a frame's word and a filler ("the medal" one thing, not a slot holding "medal").
            at = {word.at: word.form for word in record.words}
            written = tuple((term, " ".join(at[i] for i in places if i in at))
                            for term, places in record.terms if any(i in at for i in places))
            yield TaughtRecord(subject="", relation="", obj="",
                               quality=float(self.quality),
                               sentence=record.text,
                               meaning=record.meaning(),
                               words=tuple((term, word) for term, word in written if word),
                               example=True)

    def sentence_records(self) -> Iterator[SentenceRecord]:
        """The sentences recorded whole of the file's split."""
        for data in self._lines():
            if "word" not in data:
                record = SentenceRecord.from_dict(data)
                if record.split == self.split:
                    yield record

    def word_records(self) -> Iterator["WordRecord"]:
        """The words recorded whole of the file's split (a line holding `word`), taught before any sentence."""
        for data in self._lines():
            if "word" in data:
                record = WordRecord.from_dict(data)
                if record.split == self.split:
                    yield record

    def _lines(self) -> Iterator[Dict[str, Any]]:
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


#: A word's class by the part of speech the PMB gives it (Penn's), as Lyric's classes go; a form of "be", and of
#: "have" and "do" taking a doing, is an AUXILIARY, and a preposition taking a sentence a SUBORDINATOR
#: (`record_of_pmb`).
_PENN_CLASS = {"NN": "NOUN", "NNS": "NOUN", "NNP": "NAME", "NNPS": "NAME", "VB": "VERB", "VBD": "VERB",
               "VBG": "VERB", "VBN": "VERB", "VBP": "VERB", "VBZ": "VERB", "MD": "AUXILIARY", "JJ": "ADJECTIVE",
               "JJR": "ADJECTIVE", "JJS": "ADJECTIVE", "RB": "ADVERB", "RBR": "ADVERB", "RBS": "ADVERB",
               "WRB": "ADVERB", "PRP": "PRONOUN", "PRP$": "PRONOUN", "WP": "PRONOUN", "WP$": "PRONOUN",
               "EX": "PRONOUN", "DT": "DETERMINER", "PDT": "DETERMINER", "WDT": "DETERMINER", "IN": "PREPOSITION",
               "TO": "PARTICLE", "RP": "PARTICLE", "POS": "PARTICLE", "CC": "CONJUNCTION", "CD": "NUMERAL",
               "UH": "INTERJECTION", "SYM": "SYMBOL", "FW": "OTHER"}
#: What form a word is, by its Penn tag, as a treebank writes it.
_PENN_FEATURES = {"NN": "Number=Sing", "NNS": "Number=Plur", "NNP": "Number=Sing", "NNPS": "Number=Plur",
                  "VB": "VerbForm=Inf", "VBD": "Mood=Ind|Tense=Past|VerbForm=Fin", "VBG": "VerbForm=Ger",
                  "VBN": "Tense=Past|VerbForm=Part", "VBP": "Mood=Ind|Tense=Pres|VerbForm=Fin",
                  "VBZ": "Mood=Ind|Number=Sing|Person=3|Tense=Pres|VerbForm=Fin", "JJ": "Degree=Pos",
                  "JJR": "Degree=Cmp", "JJS": "Degree=Sup", "RBR": "Degree=Cmp", "RBS": "Degree=Sup"}
#: The classes a treebank joins to the word they mark, not what they mark to them ("in" to "park").
_MARKING_CLASSES = frozenset({"PREPOSITION", "SUBORDINATOR", "DETERMINER", "AUXILIARY", "CONJUNCTION", "PARTICLE"})
_TIME_RELATIONS = frozenset({"precedes", "follows", "during"})


def record_of_pmb(derived: Any, taught: Any, split: str = "train") -> SentenceRecord:
    """A PMB sentence recorded whole (`SentenceRecord`) from its checked derivation (release 4.0.0, `grammar.Derived`)
    and its checked meaning (5.1.0, `composition.TaughtSentence`, as Lyric's meaning language says it). THE ONE PLACE
    WHERE THE PMB'S WAYS ARE PUT AS LYRIC'S: a word's class from its part of speech; what it is joined to, as a
    treebank joins words, from how the derivation combined it (a modifier and a word that only marks another,
    "the", "with", "was", joined to what they take; punctuation to the sentence's own word); as what, from how; a
    name of several words ("Burt~Lancaster") its words, one name; each term of the meaning at the words its lines
    say it, the words the lines mark ("the", "with") apart; each fact with the words saying it."""
    from core.semantics import grammar as gm
    from core.semantics.derived_reader import is_variable
    # Each derivation word as the text's words: a name of several its parts.
    words: List[Dict[str, Any]] = []
    names: List[Tuple[int, int, str]] = []
    place: List[int] = []
    for k, (word, (start, end)) in enumerate(zip(derived.words, derived.spans)):
        parts = word.split("~")
        lemmas = derived.lemmas[k].split("~") if derived.lemmas[k].count("~") == len(parts) - 1 else \
            [p.lower() for p in parts]
        first = len(words)
        at = start
        for p, part in enumerate(parts):
            found = derived.text.find(part, at)
            s = found if found >= 0 else at
            words.append({"form": part, "start": s, "end": s + len(part), "lemma": lemmas[p] or part.lower(),
                          "tag": derived.tags[k], "category": derived.categories[k]})
            at = s + len(part)
        if len(parts) > 1:
            names.append((first, len(words) - 1, " ".join(parts).lower()))
        place.append(len(words) - 1)
    n = len(words)

    def category(text: str) -> Optional[Any]:
        try:
            return gm.bank_category(text)
        except (ValueError, IndexError):
            return None
    for w in words:
        cls = _PENN_CLASS.get(w["tag"])
        if cls is None:
            cls = "PUNCTUATION" if not any(ch.isalnum() for ch in w["form"]) else "OTHER"
        cat = category(w["category"])
        takes_doing = isinstance(cat, gm.Fn) and gm._clausal(cat.arg) and cat.slash == "/"
        if w["lemma"] == "be" or (cls == "VERB" and w["lemma"] in ("have", "do") and takes_doing
                                  and gm._same_shape(cat.res, cat.arg)):
            cls = "AUXILIARY"
        if cls == "PREPOSITION" and isinstance(cat, gm.Fn) and isinstance(cat.arg, gm.Atom) and cat.arg.base == "S":
            cls = "SUBORDINATOR"
        w["class"] = cls
        w["features"] = _PENN_FEATURES.get(w["tag"], "")
    # What each word is joined to, and how, from how the derivation combined them.
    head: List[int] = [-1] * n
    how: List[str] = [""] * n
    marks: List[int] = []

    def walk(node: Any) -> Tuple[int, Optional[Any]]:
        if isinstance(node, int):
            return place[node], category(derived.categories[node])
        kids = [walk(k) for k in node[2:] if not isinstance(k, str)]
        cat = category(node[1])
        if len(kids) == 1:
            return kids[0][0], cat
        rule = node[0]
        if rule in ("rp", "lp"):
            keep, mark = (kids[0], kids[1]) if rule == "rp" else (kids[1], kids[0])
            marks.append(mark[0])
            return keep[0], cat
        if rule == "conj":
            joined, word = kids[1], kids[0]
            head[word[0]], how[word[0]] = joined[0], "cc"
            return joined[0], cat
        f, a = (0, 1) if rule in ("fa", "fc", "fxc", "gfc") else (1, 0)
        functor, argument = kids[f], kids[a]
        fcat = functor[1]
        nodes = [k for k in node[2:] if not isinstance(k, str)]
        if isinstance(nodes[f], tuple) and nodes[f] and nodes[f][0] == "conj":
            # Things joined by "and": the second joined to the first.
            head[functor[0]], how[functor[0]] = argument[0], "conj"
            return argument[0], cat
        modifier = isinstance(fcat, gm.Fn) and gm._same_shape(fcat.res, fcat.arg)
        if modifier or words[functor[0]]["class"] in _MARKING_CLASSES:
            top, below = argument, functor
            kind = "mod" if modifier else "mark"
        else:
            top, below = functor, argument
            kind = "subj" if (rule == "ba" and isinstance(fcat, gm.Fn) and fcat.slash == "\\"
                              and gm._clausal(fcat.res)) else "arg"
        head[below[0]], how[below[0]] = top[0], kind
        return top[0], cat
    root, _ = walk(derived.tree)
    for k in marks:
        head[k], how[k] = root, "punct"
    for first, last, _ in names:
        for k in range(first, last):
            head[k], how[k] = last, "flat"
    # As what each is joined, as a treebank says it.
    cased = {head[k] for k in range(n) if words[k]["class"] == "PREPOSITION"}
    passive = {k for k in range(n) if words[k]["category"].startswith("s:pss") or ":pss" in words[k]["category"]
               .split("/")[0].split("\\")[0]}
    for k, w in enumerate(words):
        cls, h, kind = w["class"], head[k], how[k]
        hcls = words[h]["class"] if h >= 0 else ""
        if h < 0:
            rel = "root"
        elif kind in ("punct", "cc", "conj", "flat"):
            rel = kind
        elif cls == "DETERMINER":
            rel = "det"
        elif cls == "PREPOSITION":
            rel = "case"
        elif cls == "SUBORDINATOR" or (cls == "PARTICLE" and w["tag"] == "TO"):
            rel = "mark"
        elif cls == "PARTICLE" and w["tag"] == "POS":
            rel = "case"
        elif cls == "PARTICLE":
            rel = "compound:prt"
        elif cls == "AUXILIARY":
            rel = "cop" if hcls not in ("VERB",) and w["lemma"] == "be" else (
                "aux:pass" if h in passive and w["lemma"] == "be" else "aux")
        elif cls == "PRONOUN" and w["tag"] == "PRP$":
            rel = "nmod:poss"
        elif cls in ("NOUN", "NAME", "PRONOUN", "NUMERAL") and kind == "subj":
            rel = "nsubj:pass" if h in passive else "nsubj"
        elif cls in ("NOUN", "NAME", "PRONOUN") and hcls in ("VERB", "ADJECTIVE", "AUXILIARY"):
            rel = "obl" if k in cased else "obj"
        elif cls in ("NOUN", "NAME", "PRONOUN") and hcls in ("NOUN", "NAME", "PRONOUN", "NUMERAL"):
            rel = "nmod" if k in cased else "compound"
        elif cls == "NUMERAL":
            rel = "nummod"
        elif cls == "ADJECTIVE" and hcls in ("NOUN", "NAME", "PRONOUN"):
            rel = "amod"
        elif cls == "ADVERB":
            rel = "advmod"
        elif cls == "VERB" and kind == "subj":
            rel = "csubj"
        elif cls in ("VERB", "ADJECTIVE") and hcls in ("NOUN", "NAME", "PRONOUN"):
            rel = "acl"
        elif cls in ("VERB", "ADJECTIVE"):
            rel = "xcomp" if kind == "arg" else "advcl"
        else:
            rel = "dep"
        w["relation"] = rel
    # Each term of the meaning at the words saying it, its marked words aside; each fact with its words.
    term_words: Dict[str, List[int]] = {}
    for term, anchors in taught.anchors:
        for start, end, kind, marked in anchors:
            inside = [k for k, w in enumerate(words) if start <= w["start"] and w["end"] <= end]
            marked_low = {m.lower() for m in marked}
            own = ([k for k in inside if words[k]["form"].lower() in marked_low] if kind == "marked" else
                   [k for k in inside if words[k]["form"].lower() not in marked_low] or inside)
            for k in own:
                term_words.setdefault(term, [])
                if k not in term_words[term]:
                    term_words[term].append(k)
    for f in taught.meaning.facts:
        # A thing named by its kind's word: the kind's words say the thing (the PMB's lines name the kind).
        if f.relation == "instance_of" and f.subject not in term_words and f.obj in term_words:
            term_words[f.subject] = list(term_words[f.obj])
    facts: List[RecordFact] = []
    for f in taught.meaning.facts:
        said: List[int] = []
        for term in (f.subject, f.obj):
            said.extend(term_words.get(term, ()))
        ends = set(term_words.get(f.obj, ())) | set(term_words.get(f.subject, ()))
        said.extend(k for k in range(n) if head[k] in ends and words[k]["class"] in ("PREPOSITION", "SUBORDINATOR")
                    and f.relation != "instance_of")
        if f.given:
            said.extend(k for k in range(n) if head[k] in ends and words[k]["class"] == "DETERMINER")
        if f.relation in _TIME_RELATIONS and f.obj == "?now":
            said.extend(k for k in range(n) if head[k] in ends and words[k]["class"] == "AUXILIARY")
        if not said and f.relation in ("has_property",) and f.obj in ("false",):
            said.extend(k for k in range(n) if words[k]["lemma"] in ("not", "n't", "no", "never"))
        facts.append(RecordFact(f.relation, f.subject, f.obj, f.positive, f.condition, f.alternative, f.unasserted,
                                f.given, tuple(sorted(set(said)))))
    record_words = tuple(RecordWord(k, w["form"], w["start"], w["end"], w["lemma"], w["class"], w["tag"],
                                    w["features"], w["category"], head[k], w["relation"]) for k, w in enumerate(words))
    terms = tuple((t, tuple(sorted(at))) for t, at in term_words.items()
                  if any(t in (f.subject, f.obj) for f in taught.meaning.facts))
    tree = derived.tree
    return SentenceRecord(f"{derived.said_in}#{derived.part}", derived.text, taught.meaning.act, record_words,
                          tuple(facts), terms, tree, tuple(names), tuple(taught.meaning.asked),
                          "PMB 4.0.0 gold derivation, 5.1.0 gold meaning (both checked by hand)",
                          "PMB annotations ODC-BY 1.0; attribute the PMB, Abzianidze et al. 2017", split)


# ── ONE WORD, EVERYTHING READING ASKS OF IT: the record Lyric is taught a word from ───────────────────────────────

@dataclass(frozen=True)
class WordForm:
    """One way a recorded word is written (`WordRecord`): the form, as which class, what form it is (a treebank's
    features: "Tense=Past", "Number=Plur"), and how often a treebank wrote it so; how it is said (`sounds`, the CMU
    Pronouncing Dictionary's phones of each way of saying it); of a form the analysts mark nothing apart from another
    form of the word ("a" and "an"), the first sound of the word said after it, how often each (`before`); and of a
    finite form of a verb, the subjects that took it, by their class and the features they share with verbs, how often
    each (`subjects`: "is" a NOUN `Number=Sing`, "am" a PRONOUN `Number=Sing|Person=1`); of a determiner, the nouns it
    was said with, by the same (`nouns`: "a" a NOUN `Number=Sing`); of a copula, what it said a thing to be and the
    thing, each by the same (`predicated`: "are" a NOUN `Number=Plur` of a NOUN `Number=Plur`); and of a verb, what
    stood as its object, by the same (`objects`: "misled" a PRONOUN `Case=Acc|Number=Sing|Person=1`), which is what
    says a thing standing after a verb is written as "me" and not as "I"."""

    form: str
    word_class: str
    features: str = ""
    count: int = 0
    sounds: Tuple[str, ...] = ()
    before: Tuple[Tuple[str, int], ...] = ()
    subjects: Tuple[Tuple[str, str, int], ...] = ()
    nouns: Tuple[Tuple[str, str, int], ...] = ()
    predicated: Tuple[Tuple[str, str, str, str, int], ...] = ()
    objects: Tuple[Tuple[str, str, int], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"form": self.form, "class": self.word_class, "features": self.features,
                               "count": self.count}
        # A layer the form has none of is not written: a record made before the layer is the same record.
        if self.sounds:
            out["sounds"] = list(self.sounds)
        if self.before:
            out["before"] = [list(b) for b in self.before]
        if self.subjects:
            out["subjects"] = [list(s) for s in self.subjects]
        if self.nouns:
            out["nouns"] = [list(s) for s in self.nouns]
        if self.predicated:
            out["predicated"] = [list(s) for s in self.predicated]
        if self.objects:
            out["objects"] = [list(s) for s in self.objects]
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordForm":
        return cls(str(data["form"]), str(data["class"]), str(data.get("features") or ""), int(data.get("count") or 0),
                   tuple(str(s) for s in data.get("sounds") or ()),
                   tuple((str(b[0]), int(b[1])) for b in data.get("before") or ()),
                   tuple((str(s[0]), str(s[1]), int(s[2])) for s in data.get("subjects") or ()),
                   tuple((str(s[0]), str(s[1]), int(s[2])) for s in data.get("nouns") or ()),
                   tuple((str(s[0]), str(s[1]), str(s[2]), str(s[3]), int(s[4])) for s in data.get("predicated") or ()),
                   tuple((str(s[0]), str(s[1]), int(s[2])) for s in data.get("objects") or ()))


@dataclass(frozen=True)
class WordPlace:
    """One place a sense of a verb has (PropBank's): its argument, who fills it (PropBank's description) and the
    thing that is (`fills`: the description's word as WordNet's sense of it, Lyric's name), its function tag, the
    prepositions its examples say it with and whether they say it bare, what VerbNet says may fill it (`restricted`:
    "+concrete" and the WordNet sense it is, Lyric's name), and where the grammar holds it (`slots`: subject, object,
    "by" for a doer said after "by", "pp:with" for one said after "with") with what Lyric's meaning language says of it
    there. A place where the function tag and the preposition do not agree gets no slot (`_PLACE_LINKS`)."""

    arg: str
    who: str
    function: str = ""
    prepositions: Tuple[str, ...] = ()
    bare: bool = False
    slots: Tuple[Tuple[str, str], ...] = ()
    fills: str = ""
    restricted: Tuple[Tuple[str, str], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"arg": self.arg, "who": self.who, "function": self.function, "prepositions": list(self.prepositions),
                "bare": self.bare, "slots": [list(s) for s in self.slots], "fills": self.fills,
                "restricted": [list(r) for r in self.restricted]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordPlace":
        return cls(str(data["arg"]), str(data.get("who") or ""), str(data.get("function") or ""),
                   tuple(data.get("prepositions") or ()), bool(data.get("bare")),
                   tuple((str(s[0]), str(s[1])) for s in data.get("slots") or ()), str(data.get("fills") or ""),
                   tuple((str(r[0]), str(r[1])) for r in data.get("restricted") or ()))


@dataclass(frozen=True)
class WordSense:
    """One meaning of a recorded word: its WordNet sense, as which class, the name Lyric gives the thing it means
    (`concept`, `WordNetSource._sense_names`), what it means (WordNet's definition), everything it is a kind of up
    WordNet's chain, nearest first (each WordNet sense and Lyric's name for it), how often it is used so (WordNet's
    tagged count), WordNet's examples, the frames its verb is used in (the grammar's names); and for a verb the
    PropBank sense it is (`roleset`, `use`: what PropBank says it means), through VerbNet (`verbnet`: the class whose
    member it is), with that sense's places."""

    id: str
    word_class: str
    concept: str
    means: str
    kind_of: Tuple[Tuple[str, str], ...] = ()
    used: int = 0
    examples: Tuple[str, ...] = ()
    frames: Tuple[str, ...] = ()
    roleset: str = ""
    use: str = ""
    verbnet: str = ""
    places: Tuple[WordPlace, ...] = ()
    #: WHAT THE SENSE WAS SEEN USED WITH, in sentences tagged with their senses (SemCor): (slot, the other WordNet
    #: sense, Lyric's name for it and for everything it is a kind of, how often) — the verb `coat paint` with a house
    #: as what it was done to (`"subject"`, `"object"`), a quality or an adverb with what it was said of
    #: (`"said_of"`: a quality of a thing, an adverb of a doing). Which sense a sentence means is chosen by them
    #: (`Lexicon.sense_of`, `Lexicon.thing_sense_of`, `Lexicon.quality_sense_of`).
    seen_with: Tuple[Tuple[str, str, Tuple[str, ...], int], ...] = ()
    #: HOW MUCH OF WHAT IS SAID A NOUN SENSE AND EACH OF ITS KINDS COVER: for the sense, then each kind in `kind_of`,
    #: how many uses SemCor tagged of it or of anything that is a kind of it, each WordNet noun sense counted once
    #: more, so none covers nothing. The rarer a kind a sense shares with a thing said beside it, the more that thing
    #: says the sense is meant (Resnik 1995, the information a shared kind carries): "a second coat of paint", the
    #: coat a coating, as paint is. Which sense a sentence means is chosen by them (`Lexicon.thing_sense_of`).
    covers: Tuple[int, ...] = ()
    #: WordNet's key for the word in this sense ("paint%2:35:00::"), and every other way WordNet relates it
    #: (`_WORDNET_LEMMA_RELATIONS`, `_WORDNET_SENSE_RELATIONS`): (relation, the other sense, Lyric's name for it, the
    #: other word where the relation is the word's own) — "paint" `derivationally_related_forms` "painter".
    key: str = ""
    related: Tuple[Tuple[str, str, str, str], ...] = ()
    #: WHAT AN ADJECTIVE IS OF, AND WHAT THAT IS A KIND OF (WordNet's pertainyms: "Norwegian" of Norway, a European
    #: country): (the sense, Lyric's name for it, everything it is a kind of, nearest first). WordNet gives an
    #: adjective no kinds, so reading weighs one by what it is of, as it weighs one memory holds defined with a thing
    #: (`GrammarView._count_word`): a link learned of "an Algerian author" (`comes_from`) is then the link of "a
    #: Norwegian town", never seen.
    pertains_to: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = ()
    #: THE VERBNET CLASSES THE SENSE IS A MEMBER OF, as VerbNet lists its WordNet key (or, where no class names any
    #: sense of the word, the classes listing the word alone): their frames say what each of its places is
    #: (`WordRecord.frames_said`).
    verbnet_classes: Tuple[str, ...] = ()
    #: WHICH OF `kind_of` WORDNET MARKS THE SENSE AN INSTANCE OF rather than a kind of, as Lyric names them (its
    #: instance hypernyms): Oceania is one archipelago, Germany one European country, neither a kind of anything.
    #: A sense naming one thing is a name, and reading weighs a word written capitalised inside a sentence by what
    #: memory holds its thing to be (`GraphKnowledge.capitalized`: a thing held an instance of a kind is a name, one
    #: held a kind of a kind a common noun). Recorded as kinds alike, 518 of the 666 names taught were read as
    #: common nouns, and for 505 of them no treebank had ever seen the word written as one: "Germany" was a kind of
    #: thing 27 times over against the treebanks' 17 sayings of it as a name, "Jesus" 189 against 7, and "Africa"
    #: stayed a name by nine (2026-11-04).
    one_of: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return ({"key": self.key} if self.key else {}) | ({"related": [list(r) for r in self.related]}
                                                          if self.related else {}) | (
            {"one_of": list(self.one_of)} if self.one_of else {}) | (
            {"pertains_to": [[sense, name, list(kinds)] for sense, name, kinds in self.pertains_to]}
            if self.pertains_to else {}) | (
            {"verbnet_classes": list(self.verbnet_classes)} if self.verbnet_classes else {}) | {
            "id": self.id, "class": self.word_class, "concept": self.concept, "means": self.means,
                "kind_of": [list(k) for k in self.kind_of], "used": self.used, "examples": list(self.examples),
                "frames": list(self.frames), "roleset": self.roleset, "use": self.use, "verbnet": self.verbnet,
                "places": [p.to_dict() for p in self.places],
                "seen_with": [[slot, sense, list(kinds), n] for slot, sense, kinds, n in self.seen_with],
                "covers": list(self.covers)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordSense":
        return cls(str(data["id"]), str(data["class"]), str(data.get("concept") or ""), str(data.get("means") or ""),
                   tuple((str(k[0]), str(k[1])) for k in data.get("kind_of") or ()), int(data.get("used") or 0),
                   tuple(data.get("examples") or ()), tuple(data.get("frames") or ()), str(data.get("roleset") or ""),
                   str(data.get("use") or ""), str(data.get("verbnet") or ""),
                   tuple(WordPlace.from_dict(p) for p in data.get("places") or ()),
                   tuple((str(w[0]), str(w[1]), tuple(w[2]), int(w[3])) for w in data.get("seen_with") or ()),
                   tuple(int(c) for c in data.get("covers") or ()), str(data.get("key") or ""),
                   tuple((str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in data.get("related") or ()),
                   tuple((str(p[0]), str(p[1]), tuple(str(k) for k in p[2])) for p in data.get("pertains_to") or ()),
                   tuple(str(c) for c in data.get("verbnet_classes") or ()),
                   tuple(str(k) for k in data.get("one_of") or ()))


#: HOW OFTEN A SENSE MUST HAVE BEEN USED FOR ITS COUNT TO BE EVIDENCE (`WordRecord.names`). SemCor tags a sense's
#: uses, and the count was taken as evidence however small it was, so ONE use beat NONE: "whale" as a noun named
#: `large person giant` (`giant.n.04`, used 1) over the cetacean (`whale.n.02`, used 0), and the prose benchmark's
#: whales text read `done_by(?v0, large person giant)` and said back "Large Person Giant lives in the ocean." --
#: saying faithfully, the reading wrong (UNDERSTANDS-PROSE-01, 2026-11-05).
#:
#: Under the bar the count is silence, and what breaks the silence is the sense NAMED FOR THE WORD ITSELF, which is
#: the basic sense of a word WordNet names a synset after. Not the whole rule on its own: asked of 5,370 pairs, that
#: alone agreed 53.1% and differed 7.7%, and 135 of 411 disagreements overturned a CORRECT choice -- `seem` ->
#: `be look` (607 against 0), `do` -> `make` (526 against 134), `begin` -> `start` (375 against 57). Every one of
#: those failures has an overwhelming count, which is why a bar and not a preference.
#:
#: THREE, measured over all 13,867 (word, class) pairs the store holds: 827 change (5.96%), `whale` among them,
#: and none of the cases the earlier measurement showed correct. Every change sampled at two and three is better or
#: neutral -- `canary` from `fink` to the bird, `taurus` from `sanchez`, `programming` from `scheduling`,
#: `differential` from `derivative`. FIVE begins to lose good choices ("o" from `oxygen`, "through" from `done`),
#: and TWENTY loses more ("release" from `let go of`, "a" from `angstrom`), so the bar sits under them.
USED_BEFORE_DECIDING = 3


@dataclass(frozen=True)
class WordUse:
    """A sense a verb is used in as PropBank annotates it that no VerbNet class joins to any WordNet sense of the word:
    its places count for the verb, not for any one sense."""

    id: str
    means: str
    places: Tuple[WordPlace, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "means": self.means, "places": [p.to_dict() for p in self.places]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordUse":
        return cls(str(data["id"]), str(data.get("means") or ""),
                   tuple(WordPlace.from_dict(p) for p in data.get("places") or ()))


#: The classes a word record's senses may be of (WordNet's), and the classes of the words WordNet has none of,
#: recorded from how the treebanks use them ("for", "the", "is").
_OPEN_CLASSES = frozenset({"NOUN", "VERB", "ADJECTIVE", "ADVERB"})
_CLOSED_CLASSES = frozenset({"PREPOSITION", "SUBORDINATOR", "CONJUNCTION", "DETERMINER", "PRONOUN", "AUXILIARY",
                             "PARTICLE", "NUMERAL", "INTERJECTION"})


#: The ways WordNet relates a word in a sense to another word in a sense (`Lemma`) and a sense to another sense
#: (`Synset`), each kept in the word's record (`WordSense.related`). Not kept: a sense's narrower senses
#: (`hyponyms`, `instance_hyponyms`) and a domain's members, which each narrower word's and each member's own record
#: says of itself (`kind_of`, its domains).
_WORDNET_LEMMA_RELATIONS = ("antonyms", "derivationally_related_forms", "pertainyms")
_WORDNET_SENSE_RELATIONS = ("also_sees", "similar_tos", "entailments", "causes", "verb_groups", "attributes",
                            "part_meronyms", "substance_meronyms", "member_meronyms", "part_holonyms",
                            "substance_holonyms", "member_holonyms", "topic_domains", "region_domains", "usage_domains")

#: EVERY COLUMN OF EVERY SOURCE A WORD'S RECORD IS MADE FROM, and the layer that carries it, or why none does. A record
#: made from its sources says how much it carried of each (`WordRecord.covered`), and one that leaves a column out is
#: refused (`problems`): a word recorded whole carries everything said of it, never only what a sentence was found
#: to need. Built a layer at a time as sentences failed, the record missed how each word is joined, its case, its
#: fine tag, everything STREUSLE and GUM say of it, WordNet's relations but kinds, PropBank's aliases and VerbNet's
#: frames, each found only when a sentence was read wrong or said wrong (2026-10-28).
_RECORD_COLUMNS: Dict[Tuple[str, str], str] = {
    ("UD", "ID"): "joined_as", ("UD", "FORM"): "forms", ("UD", "LEMMA"): "word", ("UD", "UPOS"): "forms",
    ("UD", "XPOS"): "tags", ("UD", "FEATS"): "forms", ("UD", "HEAD"): "joined_as", ("UD", "DEPREL"): "related_as",
    ("UD", "DEPS"): "enhanced", ("UD", "MISC"): "misc",
    ("WordNet", "synset"): "senses", ("WordNet", "definition"): "senses", ("WordNet", "examples"): "senses",
    ("WordNet", "hypernyms"): "senses", ("WordNet", "lemma count"): "senses", ("WordNet", "verb frames"): "senses",
    ("WordNet", "lemma key"): "senses", ("WordNet", "relations"): "senses",
    ("WordNet", "hyponyms"): "not here: each narrower sense's record says what it is a kind of",
    ("WordNet", "domain members"): "not here: each member's record says its domain",
    ("PropBank", "roleset"): "rolesets", ("PropBank", "roles"): "senses, uses", ("PropBank", "aliases"): "rolesets",
    ("PropBank", "FrameNet"): "rolesets", ("PropBank", "examples"): "senses, uses (the prepositions they begin with)",
    ("VerbNet", "members"): "senses", ("VerbNet", "restrictions"): "senses", ("VerbNet", "frames"): "verbnet_frames",
    ("CMUdict", "phones"): "forms", ("SemCor", "tags"): "senses", ("STREUSLE", "SNACS"): "joins_things",
    ("PMB", "meaning"): "means",
    ("PMB", "derivation"): "not here: each PMB sentence is recorded whole (`SentenceRecord`) and taught after the words; "
                           "counted here too, every sentence of it would count twice"}


def _pro_form(features: str) -> bool:
    """A form of an open class standing for a thing said or asked elsewhere, as the analysts mark one (`PronType`):
    "how" `PronType=Int`, "here" `PronType=Dem`. WordNet gives no sense of such a word; the grammar its meaning."""
    return any(f.startswith("PronType=") for f in features.split("|"))


@dataclass(frozen=True)
class WordRecord:
    """ONE WORD AS LYRIC IS TAUGHT IT: every way it is written (`forms`), every meaning it has (`senses`: what each
    means, everything it is a kind of, how often it is used so, and for a verb how it is used and who fills each of its
    places), where each came from. Taught before any sentence it is in: a sentence teaches how known words go
    together, never a word it does not hold ("Roy painted the medal." was misread where only "fasten" had been taught,
    TRAIN-FORMAT-01, 2026-10-26). Every part of reading learns from it (`forms_held`, `classes`, `names`, `frames`,
    `links`, `prepositions`, the senses' kinds and places); checked whole before memory takes it (`problems`)."""

    word: str
    forms: Tuple[WordForm, ...]
    senses: Tuple[WordSense, ...]
    uses: Tuple[WordUse, ...] = ()
    #: How the treebanks used each of its forms, named as the grammar's entries name their uses (`HeldWords.use_of`):
    #: (form, use, how often) — "for" a PREPOSITION, a `sub`, a `mark:purpose`.
    used_as: Tuple[Tuple[str, str, int], ...] = ()
    #: What it says joining a doing to a thing, as PropBank's arguments it opens are tagged (`_PLACE_LINKS`): (link,
    #: how often) — "for" `done_for`, `has_purpose`.
    joins: Tuple[Tuple[str, int], ...] = ()
    source: str = ""
    licence: str = ""
    split: str = "train"
    #: What it says joining a thing to a thing, as STREUSLE's annotators said each use of it in English Web Treebank
    #: text (`_SNACS_LINKS`): (link, what it took and everything that is a kind of, how often) — "layers of cheese"
    #: `made_of` cheese, "the side of the road" `part_of`, "a lot of us" no link Lyric holds (`word_of`).
    joins_things: Tuple[Tuple[str, Tuple[str, ...], int], ...] = ()
    #: A WORD OF SEVERAL WORDS ("make it"): how often its words were said as it, and how often its first word was said
    #: with the same words after it as a word of its own, as SemCor's annotators tagged them; then the same two where
    #: the clause ended after them ("We made it!"). The reader reads them as one by it (`Lexicon.entries`, a verb and
    #: the word after it).
    together: Tuple[int, ...] = ()
    #: Of its uses (`used_as`), how often a doing's -ing form was said next, and how often in a sentence that asks:
    #: (form, use, how often), as the grammar weighs a use beside what follows it and in a question
    #: (`Words.doing_after`, `asking`): "is" before "painting" a `be:ng`, never a `be:np`.
    used_before_doing: Tuple[Tuple[str, str, int], ...] = ()
    used_asking: Tuple[Tuple[str, str, int], ...] = ()
    #: Of each noun form, how often it was said with nothing before it saying which ("walls are"), and how often with
    #: a word that does ("the wall", "my wall"): (form, bare, determined), as reading weighs a kind said bare
    #: (`Words.noun_alone`). Untaught, "Wall is a partition." cost no more than "A wall is a partition." (2026-10-28).
    said_alone: Tuple[Tuple[str, int, int], ...] = ()
    #: AS THE GRAMMAR COUNTS AN ANALYSED SENTENCE (`HeldWords`), what a word's record carries of it: each form written
    #: with a capital inside a sentence, used as which kind of word (written, kind, how often: "Wall" a NAME, of Wall
    #: Street; `Words.capitalized`); each -ing or participle form of the verb, standing as a thing, after a thing,
    #: before one or as a doing (form, shape, how often; `verb_shapes`); each noun form said of a doing with no
    #: preposition and otherwise (form, so, otherwise; "last week", `bare_modifier`); and each word said right after the
    #: verb, as one with it and apart (word, as one, apart; "up" in "pick up", `said_together`). The grammar read these
    #: only from sentences analysed, so a store taught words recorded whole held none of them (lyric_dev2, 2026-10-28).
    capitalized: Tuple[Tuple[str, str, int], ...] = ()
    shapes: Tuple[Tuple[str, str, int], ...] = ()
    said_of_doing: Tuple[Tuple[str, int, int], ...] = ()
    said_after: Tuple[Tuple[str, int, int], ...] = ()
    #: WHAT IT SAYS IN WHAT IS MEANT, as a grammar learns it from sentences taught with their meanings (`Grammar.learn`
    #: over the Parallel Meaning Bank's gold training sentences, `_pmb_meant`): each thing learned of the word as a word
    #: of a class (`_MEANT_BY`), with the rest of what it was learned beside and what it said, how often: (table,
    #: class, rest of the key, what it said, how often) — "know" as a VERB, its clause `asserted`; "with" as a
    #: PREPOSITION joining a doing to a thing, `done_with`. The grammar names the word as it names it (`_count_word`).
    #: Learned only from sentences taught with meanings, so a store taught words recorded whole held none of it: what
    #: an adverb, a possessor or a quality says, a verb's clause, a verb said as a link (lyric_dev2, 2026-10-28).
    means: Tuple[Tuple[str, str, Tuple[Any, ...], Any, int], ...] = ()
    #: EVERYTHING ELSE THE TREEBANKS' ANALYSTS WROTE OF IT (`_record_joins`): each form's fine tag (form, class, tag,
    #: how often); how it was joined, as the structure reader counts two words of a sentence, at the levels naming
    #: the word (level, situation, how often met, how often joined) and as what (level, situation, relation, how
    #: often), which `StructureView.hold_joins` learns; its enhanced relations (form, relation, how often); what the
    #: last column says of the word (form, key, value, how often: a supersense, the parts it is made of, the kind of
    #: thing it names). "a blue hat" was read as one kind, "blue hat", where nothing said how the words join
    #: (lyric_dev2, 2026-10-28).
    tags: Tuple[Tuple[str, str, str, int], ...] = ()
    joined_as: Tuple[Tuple[str, Tuple[Any, ...], int, int], ...] = ()
    related_as: Tuple[Tuple[str, Tuple[Any, ...], str, int], ...] = ()
    enhanced: Tuple[Tuple[str, str, int], ...] = ()
    misc: Tuple[Tuple[str, str, str, int], ...] = ()
    #: Every PropBank sense of it (id, what it means, the words it is said as with their classes, the FrameNet frames
    #: its places link to), and each VerbNet frame of the classes it is a member of (class, primary and secondary
    #: description, example, what each of its places says: `_frame_places`).
    rolesets: Tuple[Tuple[str, str, Tuple[Tuple[str, str], ...], Tuple[str, ...]], ...] = ()
    verbnet_frames: Tuple[Tuple[str, str, str, str, Tuple[Tuple[str, str], ...]], ...] = ()
    #: How much it carried of each column of each source it is made from (`_RECORD_COLUMNS`): (source, column, how
    #: many). Empty only for a record made by hand.
    covered: Tuple[Tuple[str, str, int], ...] = ()

    def key(self) -> str:
        import hashlib
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()[:32]

    def identity(self) -> Optional[Tuple[str, str]]:
        """What it is a record of: one word. Recorded again otherwise, it corrects the memory holding the first."""
        return ("word", self.word)

    def claim(self) -> str:
        """What it was taught as, as the knowledge ledger records it: the word as recorded."""
        return f'the word "{self.word}" as recorded ({self.key()[:8]})'

    def said(self) -> str:
        """The word and its meanings: memory keeps a record, never reads it as a claim."""
        return f'the word "{self.word}": ' + "; ".join(f"{s.word_class.lower()} {s.concept}: {s.means}"
                                                     for s in self.senses)[:900]

    def to_dict(self) -> Dict[str, Any]:
        return {"word": self.word, "source": self.source, "licence": self.licence, "split": self.split,
                "forms": [f.to_dict() for f in self.forms], "senses": [s.to_dict() for s in self.senses],
                "uses": [u.to_dict() for u in self.uses], "used_as": [list(u) for u in self.used_as],
                "joins": [list(j) for j in self.joins],
                "joins_things": [[link, list(names), k] for link, names, k in self.joins_things],
                "together": list(self.together)} | ({
                    "used_before_doing": [list(u) for u in self.used_before_doing],
                    "used_asking": [list(u) for u in self.used_asking]}
                    if self.used_before_doing or self.used_asking else {}) | (
                    {"said_alone": [list(a) for a in self.said_alone]} if self.said_alone else {}) | {
                    layer: [list(x) for x in getattr(self, layer)]
                    for layer in ("capitalized", "shapes", "said_of_doing", "said_after") if getattr(self, layer)} | (
                    {"means": [[table, cls, list(rest), list(said) if isinstance(said, tuple) else said, n]
                               for table, cls, rest, said, n in self.means]} if self.means else {}) | {
                    layer: [list(x) for x in getattr(self, layer)]
                    for layer in ("tags", "joined_as", "related_as", "enhanced", "misc", "verbnet_frames", "covered")
                    if getattr(self, layer)} | (
                    {"rolesets": [[r, means, [list(a) for a in aliases], list(frames)]
                                  for r, means, aliases, frames in self.rolesets]} if self.rolesets else {})

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WordRecord":
        return cls(str(data["word"]), tuple(WordForm.from_dict(f) for f in data.get("forms") or ()),
                   tuple(WordSense.from_dict(s) for s in data.get("senses") or ()),
                   tuple(WordUse.from_dict(u) for u in data.get("uses") or ()),
                   tuple((str(u[0]), str(u[1]), int(u[2])) for u in data.get("used_as") or ()),
                   tuple((str(j[0]), int(j[1])) for j in data.get("joins") or ()), str(data.get("source") or ""),
                   str(data.get("licence") or ""), str(data.get("split") or "train"),
                   tuple((str(j[0]), tuple(str(x) for x in j[1]), int(j[2])) for j in data.get("joins_things") or ()),
                   tuple(int(n) for n in data.get("together") or ()),
                   tuple((str(u[0]), str(u[1]), int(u[2])) for u in data.get("used_before_doing") or ()),
                   tuple((str(u[0]), str(u[1]), int(u[2])) for u in data.get("used_asking") or ()),
                   tuple((str(a[0]), int(a[1]), int(a[2])) for a in data.get("said_alone") or ()),
                   tuple((str(c[0]), str(c[1]), int(c[2])) for c in data.get("capitalized") or ()),
                   tuple((str(s[0]), str(s[1]), int(s[2])) for s in data.get("shapes") or ()),
                   tuple((str(b[0]), int(b[1]), int(b[2])) for b in data.get("said_of_doing") or ()),
                   tuple((str(a[0]), int(a[1]), int(a[2])) for a in data.get("said_after") or ()),
                   tuple((str(m[0]), str(m[1]), _held_tuple(m[2]), _held_tuple(m[3]), int(m[4]))
                         for m in data.get("means") or ()),
                   tags=tuple((str(t[0]), str(t[1]), str(t[2]), int(t[3])) for t in data.get("tags") or ()),
                   joined_as=tuple((str(j[0]), _held_tuple(j[1]), int(j[2]), int(j[3]))
                                   for j in data.get("joined_as") or ()),
                   related_as=tuple((str(r[0]), _held_tuple(r[1]), str(r[2]), int(r[3]))
                                    for r in data.get("related_as") or ()),
                   enhanced=tuple((str(e[0]), str(e[1]), int(e[2])) for e in data.get("enhanced") or ()),
                   misc=tuple((str(m[0]), str(m[1]), str(m[2]), int(m[3])) for m in data.get("misc") or ()),
                   rolesets=tuple((str(r[0]), str(r[1]), tuple((str(a[0]), str(a[1])) for a in r[2]),
                                   tuple(str(f) for f in r[3])) for r in data.get("rolesets") or ()),
                   verbnet_frames=tuple((str(v[0]), str(v[1]), str(v[2]), str(v[3]),
                                         tuple((str(p[0]), str(p[1])) for p in (v[4] if len(v) > 4 else ())))
                                        for v in data.get("verbnet_frames") or ()),
                   covered=tuple((str(c[0]), str(c[1]), int(c[2])) for c in data.get("covered") or ()))

    def problems(self) -> List[str]:
        """What is wrong with the record, each said: an empty list where it is whole."""
        out: List[str] = []
        if not self.word or self.word != self.word.strip() or self.word.lower() != self.word:
            out.append(f"the word {self.word!r} is not written in lowercase, alone")
        if not self.forms:
            out.append("no form")
        if not self.senses and any(f.word_class in _OPEN_CLASSES and not _pro_form(f.features) for f in self.forms):
            out.append("no sense")
        classes = {s.word_class for s in self.senses}
        for f in self.forms:
            if f.word_class not in _OPEN_CLASSES | _CLOSED_CLASSES | {"NAME"}:
                out.append(f"form {f.form!r} of class {f.word_class!r}")
            elif f.word_class in _OPEN_CLASSES and f.word_class not in classes and not _pro_form(f.features):
                out.append(f"form {f.form!r} as a {f.word_class.lower()}, which no sense of the word is")
            if any(not s.strip() for s in f.sounds) or any(not s or n <= 0 for s, n in f.before):
                out.append(f"form {f.form!r}: a way of saying it, or a sound said after it, that is none")
            if f.subjects and ("VerbForm=Fin" not in f.features.split("|") or any(
                    not c or n <= 0 for c, _, n in f.subjects)):
                out.append(f"form {f.form!r}: subjects that took it, but it is no finite form, or one never taken")
        written = {f.form for f in self.forms}
        for form, use, n in self.used_as:
            if form not in written or n <= 0 or not use:
                out.append(f"used as {use!r} written {form!r} {n} times, no form of the word or never")
        used = {(form, use): n for form, use, n in self.used_as}
        for form, use, n in self.used_before_doing + self.used_asking:
            if not 0 < n <= used.get((form, use), 0):
                out.append(f"used as {use!r} written {form!r} {n} times so, more than it was used so at all")
        nouns = {f.form for f in self.forms if f.word_class == "NOUN"}
        for form, bare, determined in self.said_alone:
            if form not in nouns or min(bare, determined) < 0 or bare + determined <= 0:
                out.append(f"said alone {bare} and with a word saying which {determined} times written {form!r}, "
                           f"no noun form of the word or never")
        for capital, kind, n in self.capitalized:
            if capital.lower() not in written or not capital[:1].isupper() or not kind or n <= 0:
                out.append(f"written {capital!r} as a {kind!r} {n} times: no form of the word with a capital, or never")
        verbs = {f.form for f in self.forms if f.word_class == "VERB"}
        for form, shape, n in self.shapes:
            if form not in verbs or not shape or n <= 0:
                out.append(f"the doing {form!r} standing as {shape!r} {n} times: no verb form of the word, or never")
        things = nouns | {f.form for f in self.forms if f.word_class == "NAME"}
        for form, so, otherwise in self.said_of_doing:
            if form not in things or min(so, otherwise) < 0 or so + otherwise <= 0:
                out.append(f"{form!r} said of a doing {so} times and otherwise {otherwise}: no noun of the word, or never")
        if self.covered:
            held = {(source, column) for source, column, _ in self.covered}
            for source, column in _RECORD_COLUMNS:
                if (source, column) not in held:
                    out.append(f"{source}'s {column}: neither carried nor said why not")
            for source, column, n in self.covered:
                if (source, column) not in _RECORD_COLUMNS or n < 0:
                    out.append(f"{source}'s {column} carried {n} times: no column a record is made from, or never")
        for _, _, met, joined in self.joined_as:
            if not 0 <= joined <= met:
                out.append(f"joined {joined} times of {met} met: more than met, or never")
        classes_of = {f.word_class for f in self.forms}
        for table, cls, rest, said, n in self.means:
            if cls not in _MEANT_BY.get(table, ()) or cls not in classes_of or n <= 0:
                out.append(f"means {said!r} in {table!r} as a {cls!r} {n} times: no such table for the class, no form "
                           f"of the class, or never")
        for after, one, apart in self.said_after:
            if not verbs or not after or min(one, apart) < 0 or one + apart <= 0:
                out.append(f"{after!r} said after the verb {one} times as one and {apart} apart: no verb, or never")
        for link, n in self.joins:
            if not link or n <= 0:
                out.append(f"joins as {link!r} {n} times")
        for link, names, n in self.joins_things:
            if not link or n <= 0:
                out.append(f"joins a thing as {link!r} {n} times")
        if (" " in self.word) != bool(self.together) or (self.together and (
                len(self.together) != 4 or min(self.together) < 0 or self.together[2] > self.together[0]
                or self.together[3] > self.together[1])):
            out.append("a word of several words, and how often its words were said as it, are not given together")
        for c in classes:
            if not any(f.word_class == c and f.form == self.word for f in self.forms):
                out.append(f"the word itself is not among its forms as a {c.lower()}")
        for s in self.senses:
            if s.word_class not in _OPEN_CLASSES:
                out.append(f"sense {s.id} of class {s.word_class!r}")
            if not s.concept or not s.means:
                out.append(f"sense {s.id} lacks its name or what it means")
            if (s.places or s.roleset) and s.word_class != "VERB":
                out.append(f"sense {s.id} has a verb's places but is no verb")
            if bool(s.roleset) != bool(s.places):
                out.append(f"sense {s.id}: a PropBank sense without places, or places without one")
            if s.covers and (s.word_class != "NOUN" or len(s.covers) != 1 + len(s.kind_of)
                             or s.covers[0] <= 0 or any(c < s.covers[0] for c in s.covers[1:])):
                out.append(f"sense {s.id}: what it covers is not a count for it and one, no smaller, for each kind")
        if self.uses and "VERB" not in classes:
            out.append("uses of a verb, but no sense of the word is a verb")
        for place in [p for s in self.senses for p in s.places] + [p for u in self.uses for p in u.places]:
            for slot, link in place.slots:
                if not slot or not link:
                    out.append(f"{place.arg}: a slot without a link or a link without a slot")
        if len({s.id for s in self.senses}) != len(self.senses):
            out.append("a sense held twice")
        return out

    # ── each layer, as the part of reading that learns from it takes it ──
    def forms_held(self) -> List[Any]:
        """Its forms, as the forms memory holds words written in (`word_forms.WordForms`), a class each."""
        from core.semantics.word_forms import WordForms
        by_class: Dict[str, List[Tuple[str, str, int]]] = {}
        for f in self.forms:
            by_class.setdefault(f.word_class, []).append((f.form.lower(), f.features, max(1, f.count)))
        return [WordForms(self.word, cls, tuple(forms), f"word:{self.word}") for cls, forms in by_class.items()]

    def classes(self) -> Dict[str, Dict[str, int]]:
        """Each way it is written, and the classes it is used as so, how often (one at least)."""
        out: Dict[str, Dict[str, int]] = {}
        for f in self.forms:
            bucket = out.setdefault(f.form.lower(), {})
            bucket[f.word_class] = bucket.get(f.word_class, 0) + max(1, f.count)
        return out

    def names(self) -> Dict[str, str]:
        """What it names as each class: the thing its most used sense of the class means, and where no sense of the
        class was used often enough for that to be evidence (`USED_BEFORE_DECIDING`), the sense NAMED FOR THE WORD
        ITSELF -- the one whose concept's own name is the word ("whale" of `whale.n.02`, where `giant.n.04` is named
        `large person giant`)."""
        out: Dict[str, str] = {}
        for c in sorted({s.word_class for s in self.senses}):
            senses = [s for s in self.senses if s.word_class == c]
            most = max(senses, key=lambda s: (s.used, -senses.index(s)))
            itself = next((s for s in senses if str(s.concept).split()[-1:] == [str(self.word).lower()]), None)
            spoken = max(s.used for s in senses) >= USED_BEFORE_DECIDING
            out[c] = most.concept if spoken or itself is None else itself.concept
        return out

    def frames(self) -> Dict[str, int]:
        """How often its verb is used in each frame, its senses' uses each counting (one at least)."""
        out: Dict[str, int] = {}
        for s in self.senses:
            for frame in s.frames:
                out[frame] = out.get(frame, 0) + max(1, s.used)
        return out

    def _places(self) -> List[WordPlace]:
        return [p for s in self.senses for p in s.places] + [p for u in self.uses for p in u.places]

    def links(self) -> Dict[Tuple[str, str], int]:
        """What each of its verb's places the grammar holds as a place of the verb says (subject, object, "by"), how
        often: (slot, link) -> how many of its senses' places say it."""
        out: Dict[Tuple[str, str], int] = {}
        for p in self._places():
            for slot, link in p.slots:
                if not slot.startswith("pp:"):
                    out[(slot, link)] = out.get((slot, link), 0) + 1
        return out

    def frames_said(self) -> Dict[str, Counter]:
        """WHAT EACH PLACE OF ITS VERB SAYS, BY THE PLACES SAID WITH IT (VerbNet's frames, as the PMB's roles are; Boxer
        gives a verb's roles by the frame its category is, Bos 2008): for each verb sense (its name), the places of
        each frame of the classes it is a member of and of the classes those are part of; for the word (""), of every
        frame of its classes. Each frame's places as `_frame_places` says them -> how many frames say just those.
        Linked by the place alone, whatever was said with it, a verb's object was linked as the PMB links it 80.8% of
        the time over the PMB's 9,552 train sentences; by the frames of the sense the PMB gives, 86.5%; of WordNet's
        most used sense of the word, 85.4% (`GRAMMAR-01/diagnostics/verb_places.py`, 2026-10-29)."""
        out: Dict[str, Counter] = defaultdict(Counter)
        for cls, _, _, _, places in self.verbnet_frames:
            if not places:
                continue
            out[""][places] += 1
            for s in self.senses:
                if s.word_class == "VERB" and any(c == cls or c.startswith(cls + "-") for c in s.verbnet_classes):
                    out[s.concept][places] += 1
        return dict(out)

    def prepositions(self) -> Dict[Tuple[str, str], int]:
        """What a preposition after its verb says, as its places say it: (preposition, link) -> how many say it."""
        out: Dict[Tuple[str, str], int] = {}
        for p in self._places():
            for slot, link in p.slots:
                if slot.startswith("pp:"):
                    out[(slot[3:], link)] = out.get((slot[3:], link), 0) + 1
        return out


#: A WordNet frame as the grammar names verbs' frames: "Somebody %s something" a verb taking a thing.
def _frame_named(frame: str) -> Optional[str]:
    text = " ".join(frame.replace("%s", "----s").split())
    if " that CLAUSE" in text:
        return "that"
    if "to INFINITIVE" in text:
        return "to"
    if "VERB-ing" in text:
        return "ing"
    after = text.split("----s", 1)[1].strip() if "----s" in text else ""
    if not after:
        return "intransitive"
    words = after.split()
    if len(words) >= 2 and words[0] in ("somebody", "something") and words[1] in ("somebody", "something"):
        return "ditransitive"
    if words[0] in ("somebody", "something"):
        return "transitive"
    return "intransitive"


_WORDNET_CLASS = {"n": "NOUN", "v": "VERB", "a": "ADJECTIVE", "s": "ADJECTIVE", "r": "ADVERB"}

#: WHAT A VERB'S PLACE SAYS IN LYRIC'S MEANING LANGUAGE, by PropBank's function tag and the preposition its examples
#: say it with, the one table: a place where the two do not agree gets no link (paint.02's "benefactive", tagged a
#: goal, is said "in oils"). The doer (`PAG`) said bare is the subject, said after "by" the passive's doer; the thing
#: done to (`PPT`) said bare, the object.
_PLACE_LINKS = {
    ("PAG", ""): ("subject", "done_by"), ("PAG", "by"): ("by", "done_by"),
    ("PPT", ""): ("object", "done_to"),
    **{("GOL", p): (f"pp:{p}", "moves_to") for p in ("to", "into", "onto", "toward", "towards")},
    ("GOL", "for"): ("pp:for", "done_for"),
    **{("SRC", p): (f"pp:{p}", "moves_from") for p in ("from", "off", "out")},
    **{("DIR", p): (f"pp:{p}", "moves_to") for p in ("to", "into", "onto", "toward", "towards")},
    ("DIR", "from"): ("pp:from", "moves_from"),
    # WHERE A THING IS AND WHAT IT IS IN ARE NOT ONE LINK. Every locative preposition was mapped to `located_in`, so
    # "on the table" and "in the box" became the same relation, and the word said back was then whichever
    # `Lexicon.saying` offered first for it: "The book is on the table." came back "The book in the table." and "The
    # ring is in the box." came back "The ring on the box.", the two stores differing only in which guess won.
    # `located_in` also chains ALWAYS, which `Transitivity` names unsound for "on" -- "the book on the table on the
    # floor" -- so the collapse licensed the inference that enum warns against. Split as `relation_types` already
    # states it and `propbank_roles` already reads it: containment `located_in`, support or position `located_at`,
    # which chains NEVER.
    **{("LOC", p): (f"pp:{p}", "located_in") for p in ("in", "inside", "within")},
    **{("LOC", p): (f"pp:{p}", "located_at") for p in ("on", "at")},
    ("MNR", "with"): ("pp:with", "done_with"),
    ("PRP", "for"): ("pp:for", "has_purpose"), ("PNC", "for"): ("pp:for", "has_purpose"),
    **{("TMP", p): (f"pp:{p}", "during") for p in ("during", "in", "on", "at")},
}

#: VerbNet's roles the PMB names otherwise (its roles are VerbNet's, `--roles verbnet`): VerbNet 3's `Initial_Location`
#: the PMB's `Source`, its `Trajectory` the PMB's `Path`.
_VERBNET_AS_PMB = {"Initial_Location": "Source", "Trajectory": "Path"}


def _frame_places(frame: Any) -> Tuple[Tuple[str, str], ...]:
    """WHAT EACH PLACE OF A VERBNET FRAME SAYS, as the grammar names the place and the PMB links the role VerbNet gives
    it (`pmb_meanings.happening_link`): the thing before the verb its `subject`; of the things after it, one its
    `object`, two the `second` and the `object` ("give him a book", as the grammar's entry takes them); one after a
    preposition `pp:` it ("at", or `pp:*` where the frame names none). A Theme is who does a happening where no role
    of the frame does it ("NP:Theme V", "The bus collided with a truck."), and an Experiencer beside a doer is what
    it is done to ("NP:Agent V NP:Experiencer", "The tiger licked him."), as the PMB's meanings say them. A role with
    no link Lyric holds (`Attribute`, `Extent`) says nothing. The frame's places as `NP V PP` written in its syntax:
    "NP:Agent VERB LEX:at NP:Patient" ("Paula swatted at the fly") is `subject` done_by, `pp:at` done_to."""
    from core.semantics.pmb_meanings import happening_link
    said = [(el.tag, str(el.get("value") or "")) for el in (frame.find("SYNTAX") if frame.find("SYNTAX") is not None
                                                            else ())]
    verb = next((k for k, (tag, _) in enumerate(said) if tag == "VERB"), None)
    if verb is None:
        return ()
    roles: Dict[str, str] = {}
    before = [v for tag, v in said[:verb] if tag == "NP"]
    if before:
        roles["subject"] = before[-1]
    pending: List[str] = []
    bare: List[str] = []
    for tag, v in said[verb + 1:]:
        if tag == "PREP" or (tag == "LEX" and v.lower() in _PREPOSITIONS_WRITTEN):
            pending = [p for p in re.split(r"[ |]+", v.lower()) if p] or ["*"]
        elif tag == "NP":
            if pending:
                for p in pending:
                    roles[f"pp:{p}"] = v
                pending = []
            else:
                bare.append(v)
    if len(bare) == 1:
        roles["object"] = bare[0]
    elif len(bare) >= 2:
        roles["second"], roles["object"] = bare[0], bare[1]
    roles = {slot: _VERBNET_AS_PMB.get(r.lstrip("?"), r.lstrip("?")) for slot, r in roles.items()}
    out = []
    for slot, role in roles.items():
        link = happening_link(role, roles.values())
        if link:
            out.append((slot, link))
    return tuple(sorted(out))


def _treebank_uses(word: str, written: Set[str], treebanks: Sequence[str], cache: Dict[str, Any]
                   ) -> Tuple[Dict[Tuple[str, str], int], Dict[str, Counter], Dict[str, Counter], Dict[str, Counter],
                              Dict[str, Counter], Dict[str, Counter], Dict[str, Counter], Dict[str, Counter],
                              Dict[str, Counter]]:
    """How UD's English treebanks used each form of a word: as which class, how often ((form, class) -> n), and as
    which use, named as the grammar's entries name their uses (form -> use -> n), counted as the grammar counts an
    analysed sentence (`grammar_words.HeldWords`, over the sentences holding a form of the word); and of those, how
    often a doing's -ing form came next, and how often the sentence asked (form -> use -> n each), as the grammar
    weighs a use beside what follows it and in a question (`Words.doing_after`, `asking`); and of each noun form, how
    often it was said with nothing before it saying which and how often with a word that does (`Words.noun_alone`:
    "bare", "determined"). And as `HeldWords` counts them for the grammar: each form written with a capital inside a
    sentence, used as which kind of word (`Words.capitalized`: written -> kind -> n); each -ing or participle form of
    the verb, standing as which shape (`verb_shapes`: a thing, after a thing, before one, a doing); each noun form said
    of a doing with no preposition, or otherwise (`bare_modifier`); and each word said right after the verb, said
    with it as one or apart (`said_together`: next word -> True/False -> n). A WORD IS COUNTED WHERE
    THE ANALYSTS GAVE IT AS THIS WORD (its base form): "and" analysed once as a form of `a` brought every "and" into the
    record of "a", 295 of them before a doing, and the possessive "'s" every one into the record of "be"."""
    from core.semantics.grammar import closed_uses
    from core.semantics.grammar_words import _BARE_OF_A_DOING, HeldWords, MARKS, _shape_of
    if "sentences" not in cache:
        sentences, holding = [], {}
        for treebank in treebanks:
            for analysed in TreebankSource.of(treebank).analysed():
                k = len(sentences)
                sentences.append(analysed)
                for w in {w.lower() for w in analysed.words}:
                    holding.setdefault(w, []).append(k)
        # Each sentence's base forms, as the analysts gave them: the same sentences, read the same way.
        bases = [tuple(base for _, base, _, _, _, _ in sentence) for sentence in _treebank_words(treebanks, cache)]
        if len(bases) != len(sentences) or any(len(b) != len(a.words) for b, a in zip(bases, sentences)):
            raise ValueError("the treebanks' sentences and their base forms do not read as the same sentences")
        cache["sentences"], cache["holding"], cache["bases"] = sentences, holding, bases
    ids = sorted({k for form in written for k in cache["holding"].get(form, ())})
    held = [cache["sentences"][k] for k in ids]
    of_word = [cache["bases"][k] for k in ids]
    single = " " not in word
    classes: Dict[Tuple[str, str], int] = {}
    for analysed, bases in zip(held, of_word):
        for w, c, base in zip(analysed.words, analysed.classes, bases):
            if w.lower() in written and (base == word or not single):
                classes[(w.lower(), c)] = classes.get((w.lower(), c), 0) + 1
    counted = HeldWords(held, closed_uses(), lambda w, c: w.lower())
    uses: Dict[str, Counter] = {form: Counter() for form in written}
    doing: Dict[str, Counter] = {form: Counter() for form in written}
    asking: Dict[str, Counter] = {form: Counter() for form in written}
    alone: Dict[str, Counter] = {form: Counter() for form in written}
    capital: Dict[str, Counter] = defaultdict(Counter)
    shapes: Dict[str, Counter] = defaultdict(Counter)
    of_doing: Dict[str, Counter] = defaultdict(Counter)
    after: Dict[str, Counter] = defaultdict(Counter)
    for analysed, bases in zip(held, of_word):
        words, cls, heads, relations = analysed.words, analysed.classes, analysed.heads, analysed.relations
        under: Dict[int, List[int]] = defaultdict(list)
        for i, h in enumerate(heads):
            if h:
                under[h - 1].append(i)
        asks = words[-1] == "?"
        for i, w in enumerate(words):
            if w.lower() not in written or cls[i] in MARKS or (single and bases[i] != word):
                continue
            use = counted.use_of(words, cls, heads, relations, under, asks, i)
            uses[w.lower()][use] += 1
            if cls[i] == "NOUN" and not relations[i].startswith("compound"):
                alone[w.lower()]["determined" if any(relations[k] in ("det", "det:poss", "nmod:poss")
                                                     for k in under[i]) else "bare"] += 1
            doing[w.lower()][use] += i + 1 < len(words) and cls[i + 1] == "VERB" and words[i + 1].lower().endswith("ing")
            asking[w.lower()][use] += asks
            if i > 0 and w[:1].isupper() and words[i - 1] not in ('"', ":", "``"):
                capital[w][use.split(":")[0]] += 1
            if cls[i] == "VERB":
                if w.lower().endswith("ing") or counted._form_of(words, cls, heads, relations, under, i) == "participle":
                    shapes[w.lower()][_shape_of(relations[i])] += 1
                if i + 1 < len(words) and cls[i + 1] not in MARKS:
                    after[words[i + 1].lower()][heads[i + 1] == i + 1 and relations[i + 1] == "compound:prt"] += 1
            if cls[i] in ("NOUN", "NAME") and not relations[i].startswith("compound"):
                of_doing[w.lower()]["modifier" if relations[i] in _BARE_OF_A_DOING else "otherwise"] += 1
    return classes, uses, doing, asking, alone, capital, shapes, of_doing, after


#: WHAT A SENTENCE'S MEANING TEACHES A GRAMMAR OF ONE WORD (`Grammar.learn`), each table by the class of the word its
#: key begins with: a verb's (its clause told as so or not, `clause`; said as a link, `verb`; its places, `role`; a
#: preposition after it, `prep_of`), a noun's (`prep_of`; what its possessor is to it, `poss`), an adjective's
#: (`quality`), an adverb's (`adv`), a preposition's (what it joins, `prep`, `prep_to`; a holder, `holder`). What is
#: learned of English and of no one word (`be`, a quality by what it is of, a time) is not any word's.
_MEANT_BY = {"clause": ("VERB",), "verb": ("VERB",), "role": ("VERB",), "prep_of": ("VERB", "NOUN"),
             "poss": ("NOUN",), "quality": ("ADJECTIVE",), "adv": ("ADVERB",), "prep": ("PREPOSITION",),
             "prep_to": ("PREPOSITION",), "holder": ("PREPOSITION",)}


def _held_tuple(value: Any) -> Any:
    """A value read back from JSON as it was held: every list a tuple."""
    return tuple(_held_tuple(v) for v in value) if isinstance(value, list) else value


def _pmb_meant(cache: Dict[str, Any]) -> Tuple[Any, Dict[str, Counter]]:
    """WHAT THE PARALLEL MEANING BANK'S GOLD TRAINING SENTENCES TEACH A GRAMMAR, as main's grammar learns from them
    (`GrammarView.hold`, `Grammar.learn`, with the PMB's derivations held first, as GRAMMAR-01 learns): the grammar's
    words held from files (`file_words`, to name a word as that grammar names it), and every thing learned ((table,
    key, what it said) -> how often), by the name its key begins with. Learned once a process: a few minutes."""
    if "meant" not in cache:
        from pathlib import Path
        from core.semantics import grammar as gm
        ewt = Path(SYNTAX_DATA) / "UD_English-EWT" / "en_ewt-ud-train.conllu"
        words = file_words(ewt, gm.closed_uses())
        view = gm.GrammarView(words, structure=file_structure(ewt))
        for item in PMBDerivationSource().derived():
            view.hold_derived(item)
        for taught in PMBSource.of("gold").taught_sentences():
            view.hold(taught)
        view.learn_waiting()
        by_first: Dict[str, Counter] = defaultdict(Counter)
        for entries in view._counted.values():
            for table, key, said in entries:
                if table in _MEANT_BY and key and isinstance(key[0], str):
                    by_first[key[0]][(table, tuple(key), said)] += 1
        cache["meant"] = (words, dict(by_first))
    return cache["meant"]


#: THE FORMS ENGLISH GIVES A VERB beside the one it is written as, each with the features the treebanks write on it
#: (`WordForm`): what one does now, what was done, what was done to something, and the doing itself. The same form
#: stands twice where English writes one for two (`surrounded` a past and a participle), as the treebanks record it.
_VERB_FORMS_ENGLISH: Tuple[Tuple[str, str], ...] = (
    ("s", "Mood=Ind|Number=Sing|Person=3|Tense=Pres|VerbForm=Fin"),
    ("ed", "Mood=Ind|Number=Sing|Person=3|Tense=Past|VerbForm=Fin"),
    ("ed", "Tense=Past|VerbForm=Part|Voice=Pass"),
    ("ing", "VerbForm=Ger"),
    ("ing", "Tense=Pres|VerbForm=Part"),
)


def _written_with(word: str, ending: str) -> str:
    """The word written with an ending as English spells it: "es" after a hiss, a consonant and "y" turned to "ie"
    before "s" and to "ied" before "ed", a silent "e" dropped before a vowel. Where English writes it otherwise --
    a last letter doubled ("stopped", "barred", "preferred"), a form of its own ("went") -- WordNet holds that form
    as an exception, so what is written here is not read back and is not kept (`_forms_english_gives`)."""
    if ending == "s":
        if re.search(r"(s|x|z|ch|sh|o)$", word):
            return word + "es"
        if re.search(r"[^aeiou]y$", word):
            return word[:-1] + "ies"
        return word + "s"
    if re.search(r"[^aeiou]y$", word) and ending == "ed":
        return word[:-1] + "ied"
    if word.endswith("e") and len(word) > 2 and not re.search(r"(ee|oe|ye)$", word):
        # A WORD OF TWO LETTERS KEEPS ITS "e": dropped, "be" was written "bing", which the dictionary holds as a
        # word of its own and would have kept. So does a word whose "e" follows a vowel ("see", "free", "hoe"),
        # which keeps it before "ing" ("seeing") and would otherwise have been written "seing" and lost.
        return word[:-1] + ending
    return word + ending


def _written_otherwise(form: str, ending: str) -> bool:
    """Whether a form English writes otherwise stands where this ending would: what one does now ends in "s", the
    doing itself in "ing", and what was done in neither of them ("bought", "knew", "gone")."""
    third = form.endswith("s") and not form.endswith("ss")
    if ending == "s":
        return third
    if ending == "ing":
        return form.endswith("ing")
    return not third and not form.endswith("ing")


#: The endings of a scientific name above a species -- a family, a subfamily, an order -- which name one group and
#: take no plural in English ("Melanthiaceae", "Nostocaceae", "Muridae").
_TAXONOMIC_ENDINGS = ("aceae", "idae", "ales", "inae", "oideae", "aceous")
#: The endings of an abstract noun English counts as a mass ("abrasiveness", "austerity", "ayurveda" by its kind):
#: a plural written for one is a word English does not say.
_MASS_ENDINGS = ("ness", "ity", "ism", "ology", "ics", "hood", "ship", "dom")
#: How often real text must write a noun before how rarely it writes the plural is read as English not counting it
#: ("cattle" 97 times in the Brown corpus and "cattles" never). Below it, a noun written three times and no plural
#: says nothing -- "balustrade" is written three times there and takes "balustrades".
_MASS_IF_NEVER_PLURAL = 8
#: How often such a noun must be written in the plural, against its singular, for English to be counting it. A mass
#: noun is written in the plural ALMOST never rather than never: "moneys" twice against "money" 265 times, where the
#: nouns English counts are written 0.40 to 1.44 as often plural as singular ("car" 112/274, "year" 950/658). Asked
#: as never, "moneys", "informations" and "equipments" were all written (2026-11-08).
_COUNTED_IF_PLURAL_SHARE = 0.02


def _uncounted(cache: Dict[str, Any]) -> Set[str]:
    """The nouns NO plural is written for where the pronouncing dictionary has not heard of the word
    (`_plural_english_gives`): a named individual, a scientific name, a noun the countability lexicon marks a mass,
    and an abstract noun by its ending.

    A NAMED INDIVIDUAL IS ONE THING AND HAS NO PLURAL: WordNet marks a sense of one by what it is an instance of
    rather than a kind of (`instance_hypernyms`), so "Aquinas", "Baltimore", "Beatrice", "Clytemnestra", "Leyte" and
    "Tewkesbury" are told from the nouns by the store's own structure and not by their spelling, which
    `all_lemma_names` writes in lower case. 4,525 of the 42,498 the pronouncing dictionary refused are these. A word
    that names an individual in one sense and a kind in another ("china" the country and the clay) is counted, and
    takes the plural its kind sense has.

    Worked out once for the pass: every noun sense is read to tell the individuals from the kinds, and the
    countability lexicon is read for its labels."""
    if "uncounted" in cache:
        return cache["uncounted"]
    from nltk.corpus import wordnet as wn
    individual: Set[str] = set()
    a_kind: Set[str] = set()
    for synset in wn.all_synsets("n"):
        into = individual if synset.instance_hypernyms() else a_kind
        for lemma in synset.lemmas():
            into.add(lemma.name().replace("_", " ").lower())
    mass: Set[str] = set()
    counted: Set[str] = set()
    for synset, label in WordNetSource()._becl().items():
        for lemma in synset.lemmas():
            (mass if label == "mass" else counted).add(lemma.name().replace("_", " ").lower())
    # AND A NOUN REAL TEXT WRITES OFTEN AND NEVER IN THE PLURAL IS ONE ENGLISH DOES NOT COUNT. The countability
    # lexicon labels 9,537 senses, which leaves the common mass nouns it never reached: nothing in it says "cattle"
    # or "whey" is a mass, and the rule wrote "cattles" and "wheys", the two the pronouncing dictionary was there to
    # refuse. The Brown corpus writes "cattle" 97 times and "cattles" none, which says it where no lexicon does.
    # Read only of a noun written `_MASS_IF_NEVER_PLURAL` times or more: below that, no plural is no evidence.
    # A noun whose plural English writes otherwise ("child", "woman") is given it before this is asked.
    from collections import Counter as _Counter
    from nltk.corpus import brown
    written = _Counter(w.lower() for w in brown.words())
    by_use = {word for word, times in written.items()
              if times >= _MASS_IF_NEVER_PLURAL and word.isalpha()
              and _written_with(word, "s") != word
              and written[_written_with(word, "s")] / times < _COUNTED_IF_PLURAL_SHARE}
    out = (individual - a_kind) | (mass - counted) | by_use
    cache["uncounted"] = out
    return out


def _plural_english_gives(word: str, cache: Dict[str, Any]) -> Optional[str]:
    """THE PLURAL ENGLISH GIVES THE NOUN that no treebank here wrote; None where English gives it none here.

    The verb half of this was done on 2026-11-04 (`_forms_english_gives`) and the noun half was not, so a noun held
    only what a treebank happened to write: "whale" is held `Number=Sing` and "whales" is held nothing at all, nor
    is "mammal" held any number. A number is what tells "a mammal" from "a mammals", and the grammar already counts
    what each determiner was said with -- "a" before a singular noun 7,339 times against a plural 170 -- so with no
    number on the word the count cannot be used. Asked "Are whales mammals?", Lyric found the right fact and said
    **"A whale's a mammals."** (lyric_db, 2026-11-06).

    Where English writes the plural otherwise than a rule would ("children", "mice"), WordNet holds that form as an
    exception and it is taken in the rule's place; where it holds more than one, nothing it holds says which, so
    neither is taken. Otherwise the rule writes it (`_written_with`, which spells a noun's plural already: "es"
    after a hiss, a consonant and "y" turned to "ies").

    AND WHERE THE RULE WRITES NOTHING ENGLISH KEEPS, THE TWO FORMS IT CANNOT WRITE: the plain "s" where the rule
    chose "es" ("tattoos", "videos", "casinos") and "man" -> "men" ("salesmen", "gunmen", "women"). Asking the
    exceptions alone missed "women", which WordNet does not hold as one -- it reads it back to "woman" by a rule --
    while the spelling rule wrote "womans" and the pronouncing dictionary refused it. Swept over the 54,891 nouns
    WordNet holds, the two add a plural to 208 and change none (2026-11-06).

    KEPT ONLY WHERE THE CMU PRONOUNCING DICTIONARY SAYS IT IS A WORD, as the verb's forms are, and only where
    WordNet's own morphology reads it back as this word. That is what keeps a noun English does not count from
    being given one: "cattles" and "wheys" are in no pronouncing dictionary. WordNet's `morphy` cannot be asked
    instead of CMU -- it reads the ending off and asks only whether what is left is a word."""
    from nltk.corpus import wordnet as wn
    wn.ensure_loaded()
    if not word.isalpha() or word != word.lower() or len(word) < 3:
        return None
    otherwise = sorted({form for form, bases in wn._exception_map["n"].items()
                        if word in bases and form != word})
    if otherwise:
        return otherwise[0] if len(otherwise) == 1 else None
    form = _written_with(word, "s")
    if form != word and form in _pronounced(cache) and word in wn._morphy(form, wn.NOUN):
        return form
    # THE RULE FIRST, AND ONLY WHAT THE RULE CANNOT WRITE AFTER IT. Asked together they disagree wherever two of
    # English's rules each write a form English keeps -- "belief" takes "beliefs" by the rule and "believes" by
    # "ves" -> "f" -- and nothing in either says which is the plural, so 19 common words lost the plural they
    # already had ("boys", "allies", "beliefs", "chefs"). Asked after it, most of the table is redundant: it reads
    # "es" off a hiss and "ies" off a "y", which `_written_with` already spells. What is left is the plain "s"
    # where the rule chose "es" ("tattooes" is in no pronouncing dictionary, "tattoos" is) and "man" -> "men",
    # which no rule here spells. Read backwards the rest write what English does not: "grieves" for "grief",
    # "reves" for "ref" (2026-11-06, swept over the 54,891 nouns WordNet holds: 235 gained, none lost).
    written = {word + "s"} if not word.endswith("s") else set()
    if word.endswith("man"):
        written.add(word[:-3] + "men")
    said = sorted(other for other in written
                  if other != word and other in _pronounced(cache)
                  and word in wn._morphy(other, wn.NOUN))
    if said:
        return said[0] if len(said) == 1 else None
    # AND WHERE THE PRONOUNCING DICTIONARY HAS SIMPLY NOT HEARD OF THE WORD, the plural the rule writes, unless what
    # the noun IS says English does not count it (`_uncounted`). CMU holds 123,455 words and was the only thing
    # allowed to say a written plural is English, so it answered for the whole vocabulary: of WordNet's 55,191 single
    # nouns only 11,635 were given a plural and 42,498 had one written and refused -- "backhands", "balustrades",
    # "austerities", "behests", "applecarts", "barkeeps", "analysers", every one of them English (2026-11-08). A
    # dictionary not listing a word is not evidence against it, where a named individual, a scientific name, a noun
    # the countability lexicon marks a mass and an abstract noun's ending all are. Of the 42,498, that leaves 28,498
    # a plural is written for and 14,000 it still is not.
    rule = _written_with(word, "s")
    if (rule != word and not word.endswith(_TAXONOMIC_ENDINGS) and not word.endswith(_MASS_ENDINGS)
            and word not in _uncounted(cache) and word in wn._morphy(rule, wn.NOUN)):
        return rule
    return None


def _forms_english_gives(word: str, cache: Dict[str, Any]) -> List[Tuple[str, str]]:
    """EVERY FORM ENGLISH GIVES THE VERB that no treebank here wrote, with the features a treebank writes on it.

    Where English writes a form otherwise than a rule would -- a last letter doubled ("stopped"), a form of its own
    ("knew", "went") -- WordNet holds that form as an exception, and it is taken in the rule's place. Where English
    writes TWO of them there ("knew" and "known", "went" and "gone"), nothing WordNet holds says which is which, so
    neither is taken and the treebanks are left to say it: a form written wrong is worse than a form missing.

    Otherwise the rule writes it (`_written_with`), kept only where the CMU Pronouncing Dictionary says it is a word
    (`_pronounced`, which the record already reads for how each form is said). WordNet's own `morphy` cannot be asked
    instead: it reads the ending off and asks only whether what is left is a word, so it takes "stoped", "goed" and
    "hited" for real ones.

    A word's forms were those the treebanks happened to write and nothing else: 2,264 of the 3,106 verbs taught held
    fewer than the four a regular verb has, and "bark" held none but the word itself. `A dog barked.` was read whole
    (`instance_of(?v0, utter bark) & done_by(?v0, ?v1)`) and could not be said at all, while `Tom chased a cat.`,
    whose verb the treebanks had written every way, was said straight back in a second (lyric_db, 2026-11-04)."""
    from nltk.corpus import wordnet as wn
    wn.ensure_loaded()
    said = _pronounced(cache)
    otherwise = {form for form, bases in wn._exception_map["v"].items() if word in bases and form != word}
    out: List[Tuple[str, str]] = []
    for ending, features in _VERB_FORMS_ENGLISH:
        stands_there = sorted(f for f in otherwise if _written_otherwise(f, ending))
        if stands_there:
            if len(stands_there) == 1:
                out.append((stands_there[0], features))
            continue
        form = _written_with(word, ending)
        if form != word and form in said:
            out.append((form, features))
    return out


def _base_written(word: str, cls: str, treebanks: Sequence[str], cache: Dict[str, Any]) -> Counter:
    """How often UD's English treebanks wrote a word as its own base, as a word of this class, with each set of
    features: "like" as a verb `VerbForm=Inf` and `Mood=Ind|Tense=Pres|VerbForm=Fin`."""
    if "base_written" not in cache:
        held: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        for sentence in _treebank_words(treebanks, cache):
            for form, base, of_class, features, _, _ in sentence:
                if form == base:
                    held[(form, of_class)][features] += 1
        cache["base_written"] = held
    return cache["base_written"].get((word, cls), Counter())


#: The closed classes whose words UD's English treebanks write in forms of their own, each with its features: "is",
#: "am", "were" of `be`; "an" of `a`; "me", "my" of `I`.
_FORMED_CLOSED = frozenset({"AUXILIARY", "DETERMINER", "PRONOUN"})


def _treebank_words(treebanks: Sequence[str], cache: Dict[str, Any]
                    ) -> List[List[Tuple[str, str, str, str, int, str]]]:
    """UD's English treebanks' sentences (the parts taught, as `TreebankSource` reads them), each word as its analysts
    wrote it: (form lowered, base form lowered, class by Lyric's names, features, the word it depends on (1 the first,
    0 the root), as what)."""
    if "treebank_words" not in cache:
        sentences: List[List[Tuple[str, str, str, str, int, str]]] = []
        for treebank in treebanks:
            for path in TreebankSource.of(treebank)._paths():
                sentence: List[Tuple[str, str, str, str, int, str]] = []
                with open(path, encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            if sentence:
                                sentences.append(sentence)
                            sentence = []
                            continue
                        cols = line.rstrip("\n").split("\t")
                        if line.startswith("#") or len(cols) != 10 or not cols[0].isdigit():
                            continue
                        sentence.append((cols[1].lower(), cols[2].lower(), _UD_CLASS.get(cols[3], "OTHER"),
                                         "" if cols[5] == "_" else cols[5], int(cols[6]), cols[7]))
                if sentence:
                    sentences.append(sentence)
        cache["treebank_words"] = sentences
    return cache["treebank_words"]


def _treebank_rows(treebanks: Sequence[str], cache: Dict[str, Any]) -> Tuple[List[List[List[str]]], Dict[str, List[int]]]:
    """UD's English treebanks' sentences as `_treebank_words` reads them, each word with all ten of its columns as the
    analysts wrote them; and of each base form (lowered), the sentences holding it."""
    if "treebank_rows" not in cache:
        sentences: List[List[List[str]]] = []
        for treebank in treebanks:
            for path in TreebankSource.of(treebank)._paths():
                sentence: List[List[str]] = []
                with open(path, encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            if sentence:
                                sentences.append(sentence)
                            sentence = []
                            continue
                        cols = line.rstrip("\n").split("\t")
                        if line.startswith("#") or len(cols) != 10 or not cols[0].isdigit():
                            continue
                        sentence.append(cols)
                if sentence:
                    sentences.append(sentence)
        holding: Dict[str, List[int]] = defaultdict(list)
        for k, sentence in enumerate(sentences):
            for base in dict.fromkeys(cols[2].lower() for cols in sentence):
                holding[base].append(k)
        cache["treebank_rows"] = (sentences, dict(holding))
    return cache["treebank_rows"]


#: WHAT THE TREEBANKS' LAST COLUMN (MISC) SAYS OF A WORD, kept in its record: how it is written beside the next
#: (`SpaceAfter`), STREUSLE's annotations of EWT (the supersense of a noun, verb or preposition, the preposition's
#: relation, the expression of several words it is in, the construction it stands in, a temporal adjunct), GUM's (the
#: parts it is made of, `MSeg`; a negation; the kind of thing it names, `Entity`), and the form meant where it was
#: mistyped. GUM's discourse, PDTB, XML, bridging and split antecedents are said of the text, not the word, and are not
#: kept; nor are EWT's places of a preposition's governor and object (`PRel[gov]`, `PRel[obj]`), said in `joined_as`.
_MISC_OF_THE_WORD = frozenset({"SpaceAfter", "Supersense", "Supersense[coding]", "Supersense[scene]",
                               "PRel[config]", "MWECat", "MWELemma", "MWELen", "Cxn", "CxnElt", "CorrectForm",
                               "TemporalNPAdjunct", "MSeg", "Negation", "Entity"})


def _record_joins(word: str, treebanks: Sequence[str], cache: Dict[str, Any]
                  ) -> Tuple[Counter, Dict[Tuple[str, Tuple], List[int]], Counter, Counter, Counter]:
    """WHAT THE TREEBANKS' ANALYSTS WROTE OF EACH USE OF A WORD BEYOND ITS FORM, CLASS AND FEATURES (the word as each
    sentence's base form): its fine tag (XPOS: (form, class, tag) -> how often); how it was joined (HEAD, DEPREL, by
    ID), as the structure reader counts two words of a sentence (`structure._Pairs`): each situation it stood in as one
    of a pair at the levels naming it (as the dependent, "dependent word", with every other word of the sentence as the
    head it might have had; as the head, "head word", with every word it might have taken; both words, "words", where
    it is the dependent), how often met and how often joined, kept as the reader keeps them (joined, or met
    `KEPT_UNJOINED` times or more); as what each was joined at the same levels ((level, situation, relation) -> how
    often); its enhanced relations (DEPS: (form, relation) -> how often); and what the last column says of the word
    (`_MISC_OF_THE_WORD`: (form, key, value) -> how often; GUM's `Entity` by the kind it names)."""
    from core.semantics.structure import KEPT_UNJOINED, _Pairs
    sentences, holding = _treebank_rows(treebanks, cache)
    tags: Counter = Counter()
    joined: Dict[Tuple[str, Tuple], List[int]] = defaultdict(lambda: [0, 0])
    said: Counter = Counter()
    enhanced: Counter = Counter()
    misc: Counter = Counter()
    for k in holding.get(word, ()):
        sentence = sentences[k]
        forms = [cols[1] for cols in sentence]
        classes = [_UD_CLASS.get(cols[3], "OTHER") for cols in sentence]
        heads = [int(cols[6]) if cols[6].isdigit() else 0 for cols in sentence]
        relations = [cols[7] for cols in sentence]
        laid = _Pairs.laid(forms, classes)
        n = len(sentence)
        for at, cols in enumerate(sentence):
            if cols[2].lower() != word or "Typo=Yes" in cols[5].split("|"):
                continue
            form = cols[1].lower()
            tags[(form, classes[at], cols[4])] += 1
            if cols[8] != "_":
                for arc in cols[8].split("|"):
                    enhanced[(form, arc.split(":", 1)[1] if ":" in arc else arc)] += 1
            if cols[9] != "_":
                for kv in cols[9].split("|"):
                    key, _, value = kv.partition("=")
                    if key == "Entity":
                        for kind in re.findall(r"\(\d+-([a-z]+)", value):
                            misc[(form, key, kind)] += 1
                    elif key in _MISC_OF_THE_WORD:
                        misc[(form, key, value)] += 1
            d = at + 1
            for h in range(n + 1):
                if h == d:
                    continue
                for level in ("dependent word", "words"):
                    held = joined[(level, _Pairs._situation(laid, h, d, level))]
                    held[0] += 1
                    held[1] += heads[at] == h
            for other in range(1, n + 1):
                if other != d:
                    held = joined[("head word", _Pairs._situation(laid, d, other, "head word"))]
                    held[0] += 1
                    held[1] += heads[other - 1] == d
            # As what: a pair's situations, ungrouped, are both words, the dependent's word, the head's word, then
            # the classes alone (`_Pairs._relation_situations`).
            situations = _Pairs._relation_situations(laid, heads[at], d)
            said[("words", situations[0], relations[at])] += 1
            said[("dependent word", situations[1], relations[at])] += 1
            for other in range(1, n + 1):
                if heads[other - 1] == d:
                    said[("head word", _Pairs._relation_situations(laid, d, other)[2], relations[other - 1])] += 1
    kept = {key: held for key, held in joined.items() if held[1] > 0 or held[0] >= KEPT_UNJOINED}
    return tags, kept, said, enhanced, misc


def _closed_forms(word: str, treebanks: Sequence[str], cache: Dict[str, Any]) -> Counter:
    """THE FORMS OF A CLOSED WORD, as the treebanks' analysts gave each its base form and features (`_FORMED_CLOSED`):
    (form, class, features) -> how often. "is" `Number=Sing|Person=3|Tense=Pres` of `be`, "an" of `a`. A misspelling
    (`Typo=Yes`) is no form of the word; a form not written as words are ("’s") is not counted."""
    from core.semantics.word_forms import _written
    if "closed_forms" not in cache:
        held: Dict[str, Counter] = {}
        for sentence in _treebank_words(treebanks, cache):
            for form, base, cls, features, _, _ in sentence:
                if cls in _FORMED_CLOSED and _written(form) and "Typo=Yes" not in features.split("|"):
                    held.setdefault(base, Counter())[(form, cls, features)] += 1
        cache["closed_forms"] = held
    return cache["closed_forms"].get(word, Counter())


def _subjects_taking(word: str, treebanks: Sequence[str], cache: Dict[str, Any]) -> Dict[Tuple[str, str, str], Counter]:
    """THE SUBJECTS EACH FINITE FORM OF A VERB TOOK in the treebanks: (form, class, features) -> (the subject's class,
    the features it shares with verbs) -> how often. A subject (`nsubj`, `nsubj:pass`) takes the finite verb of its
    clause: the word it depends on where that is finite (`VerbForm=Fin`), else that word's first finite auxiliary or
    copula ("A wall is a partition.": "wall" depends on "partition", "is" its copula). The features a subject shares
    with verbs are those the treebanks write on most finite verbs taking a subject and on subjects too, by name (number
    and person: "I" `Number=Sing|Person=1`, "walls" `Number=Plur`, "you" `Person=2`); a feature written on both now
    and then is no agreement ("r" for "are" and "u" for "you" both `Abbr=Yes`). And the features that mark a subject
    as one: of the words written with a feature both as a finite verb's subject and as an object (`obj`, `iobj`), most
    written most often with one value of it as the subject and another as the object (case: "I" `Case=Nom`, "me"
    `Case=Acc`, both of `I`). Kept to number and person, "me" took a finite verb as "I" does, and "Me loves the moon."
    was said of the speaker loving the moon (lyric_dev2, 2026-10-28)."""
    if "subjects" not in cache or "shared" not in cache:
        pairs: List[Tuple[str, str, str, str, str, str]] = []
        on_verbs: Counter = Counter()
        on_subjects: Set[str] = set()
        as_subject: Dict[Tuple[str, str], Counter] = {}
        as_object: Dict[Tuple[str, str], Counter] = {}
        for sentence in _treebank_words(treebanks, cache):
            under: Dict[int, List[int]] = {}
            for k, (_, _, _, _, head, relation) in enumerate(sentence):
                if head:
                    under.setdefault(head - 1, []).append(k)
            for k, (_, base, _, features, head, relation) in enumerate(sentence):
                if relation in ("obj", "iobj") and head and "Typo=Yes" not in features.split("|"):
                    for f in features.split("|"):
                        if "=" in f:
                            as_object.setdefault((base, f.split("=")[0]), Counter())[f.split("=")[1]] += 1
            for k, (_, base, cls, features, head, relation) in enumerate(sentence):
                if relation not in ("nsubj", "nsubj:pass") or not head:
                    continue
                h = head - 1
                finite = [h] if "VerbForm=Fin" in sentence[h][3].split("|") else [
                    j for j in under.get(h, ()) if sentence[j][5] in ("aux", "aux:pass", "cop")
                    and "VerbForm=Fin" in sentence[j][3].split("|")][:1]
                if not finite:
                    continue
                verb = sentence[finite[0]]
                if "Typo=Yes" in verb[3].split("|"):
                    continue
                pairs.append((verb[1], verb[0], verb[2], verb[3], cls, features))
                on_verbs.update({f.split("=")[0] for f in verb[3].split("|") if f})
                on_subjects |= {f.split("=")[0] for f in features.split("|") if f}
                if "Typo=Yes" not in features.split("|"):
                    for f in features.split("|"):
                        if "=" in f:
                            as_subject.setdefault((base, f.split("=")[0]), Counter())[f.split("=")[1]] += 1
        both: Counter = Counter()
        apart: Counter = Counter()
        for (base, name), values in as_subject.items():
            if (base, name) in as_object:
                both[name] += 1
                apart[name] += (max(values.items(), key=lambda x: (x[1], x[0]))[0] !=
                                max(as_object[(base, name)].items(), key=lambda x: (x[1], x[0]))[0])
        marking = {name for name, n in apart.items() if 2 * n > both[name]}
        shared = ({name for name, n in on_verbs.items() if 2 * n > len(pairs)} & on_subjects) | marking
        held: Dict[str, Dict[Tuple[str, str, str], Counter]] = {}
        for base, form, cls, features, of_class, of_features in pairs:
            kept = "|".join(f for f in of_features.split("|") if f and f.split("=")[0] in shared)
            held.setdefault(base, {}).setdefault((form, cls, features), Counter())[(of_class, kept)] += 1
        cache["subjects"] = held
        cache["shared"] = shared
    return cache["subjects"].get(word, {})


def _agreeing(word: str, treebanks: Sequence[str], cache: Dict[str, Any]
              ) -> Tuple[Dict[Tuple[str, str, str], Counter], Dict[Tuple[str, str, str], Counter],
                         Dict[Tuple[str, str, str], Counter]]:
    """WHAT ELSE AGREES IN THE TREEBANKS, as a subject agrees with its verb (`_subjects_taking`), by the features
    subjects share with verbs (number and person): (form, class, features) of the word -> how often each. Of a
    determiner, the nouns each form was said with (`det`: "a" a NOUN `Number=Sing`), by their class and those features.
    Of a copula, what it said a thing to be, with the thing (a subject, `nsubj`, of a word with the copula, `cop`: "A
    wall is a partition.", "partition" a NOUN `Number=Sing`, "wall" one too), each by class and those features. And
    of a verb, what stood as its object (`obj`, `iobj`: "misled" a PRONOUN `Case=Acc|Number=Sing|Person=1`), by the
    same -- the features kept being those that mark a subject as one as well as those subjects share with verbs, so
    the case a thing is written in after a verb is counted here and nowhere else. Counted nowhere, nothing weighed a
    thing standing after a verb and "They misled me." was said back as "They misled i." (lyric_db, 2026-10-30)."""
    if "agreeing" not in cache:
        _subjects_taking(word, treebanks, cache)
        shared = cache["shared"]

        def kept(features: str) -> str:
            return "|".join(f for f in features.split("|") if f and f.split("=")[0] in shared)
        nouns: Dict[str, Dict[Tuple[str, str, str], Counter]] = {}
        predicated: Dict[str, Dict[Tuple[str, str, str], Counter]] = {}
        objects: Dict[str, Dict[Tuple[str, str, str], Counter]] = {}
        for sentence in _treebank_words(treebanks, cache):
            subject_of: Dict[int, int] = {}
            for k, (_, _, _, _, head, relation) in enumerate(sentence):
                if relation in ("nsubj", "nsubj:pass") and head:
                    subject_of.setdefault(head - 1, k)
            for k, (form, base, cls, features, head, relation) in enumerate(sentence):
                if not head or "Typo=Yes" in features.split("|"):
                    continue
                said = sentence[head - 1]
                if relation == "det":
                    nouns.setdefault(base, {}).setdefault((form, cls, features), Counter())[
                        (said[2], kept(said[3]))] += 1
                elif relation == "cop" and head - 1 in subject_of:
                    subject = sentence[subject_of[head - 1]]
                    predicated.setdefault(base, {}).setdefault((form, cls, features), Counter())[
                        (said[2], kept(said[3]), subject[2], kept(subject[3]))] += 1
                elif relation in ("obj", "iobj"):
                    # Held of the VERB, as its subjects are, and counting the thing that stood after it: the word
                    # whose form record it is, with what it was said with.
                    objects.setdefault(said[1], {}).setdefault((said[0], said[2], said[3]), Counter())[
                        (cls, kept(features))] += 1
        cache["agreeing"] = (nouns, predicated, objects)
    nouns, predicated, objects = cache["agreeing"]
    return nouns.get(word, {}), predicated.get(word, {}), objects.get(word, {})


def _pronounced(cache: Dict[str, Any]) -> Dict[str, List[List[str]]]:
    """The CMU Pronouncing Dictionary (`PronunciationSource`'s): every word it writes, with the phones of each way of
    saying it. Read once."""
    if "cmudict" not in cache:
        from nltk.corpus import cmudict
        cache["cmudict"] = cmudict.dict()
    return cache["cmudict"]


def _sounds_of(form: str, cache: Dict[str, Any]) -> Tuple[str, ...]:
    """How a form is said, as the CMU Pronouncing Dictionary writes it: each way, its phones; a form of several words
    each way of saying its words, one after another. None where it says a word of it no way."""
    import itertools
    said = _pronounced(cache)
    ways = [said.get(w, []) for w in form.split(" ")]
    if not all(ways):
        return ()
    return tuple(dict.fromkeys(" ".join(p for way in combined for p in way) for combined in itertools.product(*ways)))


def _told_apart(said: Sequence[Counter]) -> float:
    """HOW MUCH THE SOUND AFTER TELLS WHICH OF SEVERAL FORMS WAS SAID: of the uncertainty which form it was, the share
    knowing the first sound of the word after it takes away (their mutual information over the forms' entropy), less
    what forms and sounds share by chance in as few sayings (Miller and Madow's correction, (forms - 1) (sounds - 1)
    over twice the sayings): 1 where the sound always tells, 0 where it never does or too little was said to know."""
    total = sum(sum(c.values()) for c in said)
    sounds = {s for c in said for s in c}
    if total <= 0 or len(said) < 2 or not sounds:
        return 0.0

    def entropy(counts: Sequence[float]) -> float:
        n = sum(counts)
        return -sum(k / n * math.log(k / n) for k in counts if k > 0) if n > 0 else 0.0
    whole = entropy([sum(c.values()) for c in said])
    if whole <= 0:
        return 0.0
    given = sum(sum(c.get(s, 0) for c in said) / total * entropy([c.get(s, 0) for c in said]) for s in sounds)
    chance = (len(said) - 1) * (len(sounds) - 1) / (2.0 * total)
    return max(0.0, whole - given - chance) / whole


def _said_before(word: str, forms: Set[Tuple[str, str]], treebanks: Sequence[str], cache: Dict[str, Any]
                 ) -> Dict[Tuple[str, str], Counter]:
    """THE FIRST SOUND OF THE WORD SAID AFTER EACH OF THESE FORMS of a word (form, class), in the treebanks: its first
    phone as the CMU Pronouncing Dictionary says it, stress aside, each way it says it once: "an" before "hour" AW,
    "a" before "unicorn" Y. A word after it the dictionary does not say is not counted."""
    said = _pronounced(cache)
    out: Dict[Tuple[str, str], Counter] = {}
    for sentence in _treebank_words(treebanks, cache):
        for k in range(len(sentence) - 1):
            form, base, cls = sentence[k][:3]
            if base != word or (form, cls) not in forms or "Typo=Yes" in sentence[k][3].split("|"):
                continue
            for first in {way[0].rstrip("012") for way in said.get(sentence[k + 1][0], ()) if way}:
                out.setdefault((form, cls), Counter())[first] += 1
    return out


def _semcor_sentences(cache: Dict[str, Any]) -> List[Tuple[Tuple[str, ...], Tuple[Optional[Any], ...]]]:
    """SemCor's sentences, each its words and the WordNet lemma each was tagged with (None where none): the words of a
    word of several words each tagged with it."""
    from nltk.corpus import semcor
    from nltk.corpus.reader.wordnet import Lemma
    from nltk.tree import Tree
    if "semcor" not in cache:
        sentences = []
        for sent in semcor.tagged_sents(tag="sem"):
            words: List[str] = []
            tags: List[Optional[Any]] = []
            for chunk in sent:
                leaves = chunk.leaves() if isinstance(chunk, Tree) else (chunk if isinstance(chunk, list) else [chunk])
                label = chunk.label() if isinstance(chunk, Tree) and isinstance(chunk.label(), Lemma) else None
                for leaf in leaves:
                    words.extend(str(leaf).split())
                    tags.extend([label] * len(str(leaf).split()))
            sentences.append((tuple(words), tuple(tags)))
        cache["semcor"] = sentences
    return cache["semcor"]


def _grouped(places: Sequence[Tuple[int, int]]) -> Iterator[Tuple[int, List[int]]]:
    """Places in SemCor (`sentence`, `word`) gathered by their sentence, in the order the sentences stand."""
    out: Dict[int, List[int]] = {}
    for n, k in places:
        out.setdefault(n, []).append(k)
    return iter(out.items())


def _semcor_seen(word: str, cache: Dict[str, Any]) -> Dict[str, Counter]:
    """WHAT EACH SENSE OF A WORD WAS SEEN USED WITH in SemCor (Brown corpus text, each word tagged with its WordNet
    sense by hand), by the structure the reader learned from UD English EWT (`StructureView`).

    OF A VERB: the words joined to it as its subject and its object (`nsubj`, `obj`; a passive's subject its object),
    each by the sense SemCor tagged it with. `("subject", the thing's sense)`, `("object", ...)`.

    OF A QUALITY OR AN ADVERB: what it is said of (`"said_of"`) -- a quality said of a thing, an adverb of a doing:
    the word joined to it ("a red ball", "walks quickly"), and, where a copula says it of a thing ("The ball is
    red."), that thing. WordNet gives an adjective no kinds, so this is the only thing a quality's sense can be
    taken by, and with nothing held of it every quality and every adverb was read under the sense its word names
    most often, whatever it was said of (2026-10-31).

    sense -> (slot, the other sense) -> how often."""
    _semcor_sentences(cache)
    if "structure" not in cache:
        from core.semantics.structure import StructureView
        view = StructureView()
        for analysed in TreebankSource.of("ewt").analysed():
            view.add(analysed)
        cache["structure"] = view
    out: Dict[str, Counter] = {}
    # A SEMCOR SENTENCE IS READ ONCE, NOT ONCE FOR EVERY WORD TAGGED IN IT. What the structure says of a sentence
    # depends on the sentence and not on the word being asked after, and a sentence of twenty words is asked after
    # by each of them, so every sentence was read again for each: of 689.9s spent recording sixty words, 684.7s
    # (99.2%) was this function, and of that 667.5s was 173 structural reads -- about three a word, every one of
    # them a sentence another word had already read or would. Held by the sentence it is of, a sweep reads each of
    # SemCor's sentences once and asks after it as often as it likes; a single word still reads only its own.
    # None marks a sentence the structure read to a different length than SemCor tagged, which is passed over as
    # it was before.
    reads: Dict[int, Any] = cache.setdefault("semcor_read", {})
    # AND THE SENTENCES A WORD IS TAGGED IN ARE LOOKED UP, NOT SEARCHED FOR. Every word walked all of SemCor to find
    # which sentences tag it, so the walk was done once for each word asked after and all but a few hundred of its
    # sentences tag no word being asked about. Held once, by the name the tag carries: a sweep over WordNet asks
    # after 147,311 words and would have read every sentence's tags once for each of them.
    if "semcor_at" not in cache:
        where: Dict[str, List[Tuple[int, int]]] = {}
        for n, (_, tags) in enumerate(cache["semcor"]):
            for k, t in enumerate(tags):
                if t is not None and t.synset().pos() in ("v", "a", "s", "r"):
                    where.setdefault(t.name().lower(), []).append((n, k))
        cache["semcor_at"] = where
    for n, group in _grouped(cache["semcor_at"].get(word, ())):
        words, tags = cache["semcor"][n]
        at = list(group)
        if not at:
            continue
        if n not in reads:
            got = cache["structure"].read(words)
            reads[n] = got if len(got.heads) == len(tags) else None
        read = reads[n]
        if read is None:
            continue
        for k in at:
            of = tags[k].synset()
            sense = of.name()
            if of.pos() == "v":
                for d, h in enumerate(read.heads):
                    if h - 1 != k or tags[d] is None or tags[d].synset().pos() != "n":
                        continue
                    relation = read.relations[d]
                    slot = "subject" if relation == "nsubj" else "object" if relation in ("obj", "nsubj:pass") else ""
                    if slot:
                        out.setdefault(sense, Counter())[(slot, tags[d].synset().name())] += 1
                continue
            # A quality is said of a thing, an adverb of a doing: its head where the structure joins it to one, and
            # the subject said of it where a copula says it of one. A satellite adjective ("s") is an adjective.
            wanted = "n" if of.pos() in ("a", "s") else "v"
            said_of = []
            head = read.heads[k] - 1
            if 0 <= head < len(tags) and tags[head] is not None and tags[head] is not tags[k] \
                    and tags[head].synset().pos() == wanted:
                said_of.append(tags[head].synset().name())
            for d, h in enumerate(read.heads):
                if h - 1 == k and read.relations[d] in ("nsubj", "nsubj:pass") and tags[d] is not None \
                        and tags[d] is not tags[k] and tags[d].synset().pos() == wanted:
                    said_of.append(tags[d].synset().name())
            for other in said_of:
                out.setdefault(sense, Counter())[("said_of", other)] += 1
    return out


def _semcor_together(lemma_name: str, head: str, rest: Sequence[str], cache: Dict[str, Any]) \
        -> Tuple[Counter, Tuple[int, int, int, int]]:
    """A WORD OF SEVERAL WORDS IN SEMCOR: each way its words were written as it (lowered: "made it", "make it"), how
    often; how often they were said as it; how often its first word, tagged as a word of its own, had the same words
    after it ("made it clear", `make`); and those two where the clause ended after them (a mark, or nothing, next)."""
    written: Counter = Counter()
    counted: Counter = Counter()
    for words, tags in _semcor_sentences(cache):
        lowered = [w.lower() for w in words]
        for k, t in enumerate(tags):
            if t is None:
                continue
            name = t.name().lower()
            if name == lemma_name and (k == 0 or tags[k - 1] is not t):
                end = k
                while end < len(tags) and tags[end] is t:
                    end += 1
                written[" ".join(lowered[k:end])] += 1
                counted[(True, end >= len(lowered) or not any(ch.isalnum() for ch in lowered[end]))] += 1
            elif name == head and t.synset().pos() == "v" and lowered[k + 1:k + 1 + len(rest)] == list(rest) \
                    and (k + 1 >= len(tags) or tags[k + 1] is not t):
                end = k + 1 + len(rest)
                counted[(False, end >= len(lowered) or not any(ch.isalnum() for ch in lowered[end]))] += 1
    as_one, apart = counted[(True, True)] + counted[(True, False)], counted[(False, True)] + counted[(False, False)]
    return written, (as_one, apart, counted[(True, True)], counted[(False, True)])


STREUSLE_DATA = os.path.join(SYNTAX_DATA, "streusle")

#: WHAT A PREPOSITION SAYS JOINING A THING TO A THING, as Lyric's links: STREUSLE's adposition supersenses (SNACS 2.5,
#: Schneider et al. 2018), each a scene role of the thing it takes, that is one of them; any other is the word's own
#: link (`relation_types.worded`), its kind not known. From the thing it is said of to the thing it takes: "the side
#: of the road" Whole, the side `part_of` the road; "the car of my friend" Possessor, `owned_by`; "the owners of the
#: store" Org, `member_of`; "a record of a reversal" Topic, `about`; "layers of cheese" Stuff, `made_of`; "a piece
#: of the cake" PartPortion, `part_of`; "the city of Paris" Identity, `equals`; "a man from Paris" Source,
#: `comes_from`; "my uncle in Paris" Locus, `located_in`. Possession is not owning: "the delivery of their gift" is
#: the gift handed over.
_SNACS_LINKS = {"p.Whole": "part_of", "p.Possessor": "owned_by", "p.Org": "member_of", "p.Topic": "about",
                "p.Stuff": "made_of", "p.PartPortion": "part_of", "p.Identity": "equals", "p.Source": "comes_from",
                "p.Locus": "located_in"}

#: STREUSLE's noun supersenses, as WordNet's lexicographer files name them: what a thing taken is read as.
_NOUN_SUPERSENSES = {"n.TOPS": "noun.Tops"}


def _streusle_joins(word: str, split: str, cache: Dict[str, Any]) -> List[Tuple[str, str, int]]:
    """EACH USE OF A PREPOSITION JOINING A THING TO A THING in STREUSLE's English Web Treebank text (`split`), as its
    annotators said it: (Lyric's link, `_SNACS_LINKS`, else the word's own; the WordNet sense of what it took, the
    first of its word's whose lexicographer file is the noun supersense the annotators gave it, "" where they gave
    none; how often). A use said of a doing or a quality, or taking a clause, is not a thing's."""
    import json as _json
    from pathlib import Path
    from nltk.corpus import wordnet as wn
    from core.semantics.relation_types import worded
    key = f"streusle:{split}"
    if key not in cache:
        path = Path(STREUSLE_DATA) / split / f"streusle.ud_{split}.govobj.json"
        cache[key] = _json.loads(path.read_text(encoding="utf-8"))
    out: Counter = Counter()
    for sentence in cache[key]:
        toks = {t["#"]: t for t in sentence["toks"]}
        expressions = list(sentence.get("swes", {}).values()) + list(sentence.get("smwes", {}).values())
        supersense = {n: e.get("ss") for e in expressions for n in e.get("toknums", ())[:1]}
        for e in expressions:
            relation = e.get("heuristic_relation") or {}
            if e.get("lexlemma") != word or e.get("lexcat") != "P" or relation.get("config") != "default":
                continue
            gov, obj = toks.get(relation.get("gov")), toks.get(relation.get("obj"))
            if gov is None or obj is None or gov["upos"] in ("VERB", "AUX", "ADJ", "ADV"):
                continue
            ss = supersense.get(obj["#"]) or ""
            taken = ""
            if ss.startswith("n."):
                lexname = _NOUN_SUPERSENSES.get(ss, "noun." + ss[2:].lower())
                taken = next((s.name() for s in wn.synsets(str(obj["lemma"]).lower().replace(" ", "_"), "n")
                              if s.lexname() == lexname), "")
            out[(_SNACS_LINKS.get(str(e.get("ss") or "")) or worded(word), taken)] += 1
    return [(link, taken, n) for (link, taken), n in out.most_common()]


def _propbank_joins(cache: Dict[str, Any]) -> Dict[str, Counter]:
    """For each preposition, how often PropBank's arguments it opens are tagged each function, over every frame file:
    the numbered ones by their role's tag, the others by their own (`ARGM-PRP`: PRP)."""
    import xml.etree.ElementTree as ET
    from pathlib import Path
    if "propbank_joins" not in cache:
        out: Dict[str, Counter] = {}
        for path in sorted((Path(SYNTAX_DATA) / "propbank-frames" / "frames").glob("*.xml")):
            try:
                tree = ET.parse(path)
            except ET.ParseError:
                continue
            for roleset in tree.iter("roleset"):
                tags = {"ARG" + str(r.get("n")).upper(): str(r.get("f") or "").upper() for r in roleset.iter("role")}
                for example in roleset.iter("example"):
                    for arg in example.iter("arg"):
                        kind = str(arg.get("type") or "")
                        function = tags.get(kind, "") if kind.startswith("ARG") and not kind.startswith("ARGM") \
                            else kind.split("-", 1)[1].upper() if kind.startswith("ARGM-") else ""
                        first = (arg.text or "").strip().split(" ")[0].lower()
                        if function and first in _PREPOSITIONS_WRITTEN:
                            out.setdefault(first, Counter())[function] += 1
        cache["propbank_joins"] = out
    return cache["propbank_joins"]

#: What VerbNet's restrictions on what fills a place are, as WordNet's senses (Lyric names each, `_sense_names`):
#: "+concrete" a physical entity, "+animate" a living thing.
_RESTRICTED_AS = {"+concrete": "physical_entity.n.01", "+animate": "living_thing.n.01", "+human": "person.n.01",
                  "+organization": "organization.n.01", "+abstract": "abstraction.n.06",
                  "+body_part": "body_part.n.01", "+int_control": "living_thing.n.01",
                  "+location": "location.n.01", "+place": "location.n.01", "+solid": "solid.n.01",
                  "+comestible": "food.n.01", "+machine": "machine.n.01", "+vehicle": "vehicle.n.01",
                  "+time": "time_period.n.01", "+communication": "communication.n.02",
                  "+substance": "substance.n.01", "+garment": "garment.n.01", "+plant": "plant.n.02",
                  "+animal": "animal.n.01", "+container": "container.n.01", "+refl": ""}


def _rolesets(frame_file) -> "Iterator[Any]":
    """The rolesets of a PropBank frame file, and NONE where the file is not well formed.

    PropBank's own `check.xml` and `rend.xml` are malformed (a mismatched tag; found 2026-10-29). Parsed without
    this, the error came out of the whole word: `check` -- the 61st most written word of UD EWT and GUM -- was
    refused a record entirely, losing its forms, its senses and their kinds along with the places the broken file
    was to supply (2026-11-01). A word is worth more than one of its layers, so a file that cannot be read costs
    that word its PropBank places and nothing else, as it already did everywhere the frames are read over all the
    files at once (`propbank_roles_of_frames`, `_propbank_joins`).
    """
    import xml.etree.ElementTree as ET
    try:
        return list(ET.parse(frame_file).iter("roleset"))
    except ET.ParseError:
        return []


def word_record_of(word: str, treebanks: Sequence[str] = ("ewt", "gum"), split: str = "train",
                   _cache: Dict[str, Any] = {}) -> WordRecord:
    """A word recorded whole (`WordRecord`) from what was made by hand of it, never written here: its forms as UD's
    English treebanks wrote them (each form a word was written in, its features, how often; `word_forms`), its senses
    as WordNet 3.0 gives them (definition, every kind up its chain, tagged count, examples, frames), Lyric's name for
    each (`WordNetSource._sense_names`), and for a verb sense the PropBank sense it is and that sense's places, joined
    through VerbNet (a PropBank sense's links to VerbNet classes, a VerbNet member's WordNet senses; each WordNet sense
    takes, of the PropBank senses joined to it, the one joined to fewest WordNet senses). THE ONE PLACE WHERE THESE
    SOURCES' WAYS ARE PUT AS LYRIC'S: a WordNet frame as the grammar's frame; a place's link by its function tag and
    preposition (`_PLACE_LINKS`); what may fill it by VerbNet's restrictions (`_RESTRICTED_AS`) and by PropBank's
    description's word."""
    import dataclasses
    import xml.etree.ElementTree as ET
    from nltk.corpus import wordnet as wn
    from nltk.corpus.reader.wordnet import VERB_FRAME_STRINGS
    from pathlib import Path
    if "names" not in _cache:
        _cache["names"] = WordNetSource()._sense_names()
    names = _cache["names"]
    if "forms" not in _cache:
        held: Dict[Tuple[str, str], Dict[Tuple[str, str], int]] = {}
        for treebank in treebanks:
            for item in TreebankSource.of(treebank).word_forms():
                bucket = held.setdefault((item.base, item.word_class), {})
                for form, features, n in item.forms:
                    bucket[(form, features)] = bucket.get((form, features), 0) + n
        _cache["forms"] = held
    if "verbnet" not in _cache:
        from nltk.corpus import LazyCorpusLoader
        from nltk.corpus.reader import VerbnetCorpusReader
        _cache["verbnet"] = LazyCorpusLoader("verbnet3", VerbnetCorpusReader, r"(?!\.).*\.xml")
    verbnet = _cache["verbnet"]

    def named(synset: Any) -> str:
        # A SENSE NOTHING TELLS APART FROM ITS WORD'S OTHERS has no name (`_sense_names`), and is not taught: named by
        # its word, four senses of "make" were one, `make` (TRAIN-FORMAT-02, lyric_dev2, 2026-10-26).
        return names.get(synset, "")

    def kinds_of(synset: Any) -> Tuple[Tuple[str, str], ...]:
        out, frontier, seen = [], [synset], {synset}
        while frontier:
            nxt = []
            for s in frontier:
                # In one order every time (`WordNetSource._ordered`): in NLTK's set order, "game" and "sport" came
                # either way, and each build of a word was a different record, corrected at every teaching.
                for h in WordNetSource._ordered(s.hypernyms() + s.instance_hypernyms()):
                    if h not in seen:
                        seen.add(h)
                        if named(h):
                            out.append((h.name(), named(h)))
                        nxt.append(h)
            frontier = nxt
        return tuple(out)

    def names_one(synset: Any) -> Tuple[str, ...]:
        """WHICH OF ITS KINDS WORDNET MARKS THE SENSE AN INSTANCE OF, as Lyric names them (`WordSense.one_of`):
        Oceania is one archipelago, not a kind of one. Empty for a sense that is a kind, and for one whose instance
        hypernyms are senses nothing tells apart from their word's others (`named`), which nothing is taught of."""
        return tuple(dict.fromkeys(named(h) for h in WordNetSource._ordered(synset.instance_hypernyms())
                                   if named(h)))

    # A WORD OF SEVERAL WORDS ("make it", "pass away") is WordNet's lemma written with underscores, its first word the
    # one inflected ("made it").
    lemma_name = word.replace(" ", "_")
    head, *rest = word.split(" ")
    # A WORD JOINED BY A HYPHEN is one WordNet may write with its parts together or apart: "bullet-proof" is its
    # `bulletproof`, "semi-final" `semifinal`, "ice-cream" `ice_cream`. Taken only as written, 9 of the 16 such words
    # of the PMB's dev sentences had no sense (2026-10-29).
    spellings = (lemma_name,) + ((lemma_name.replace("-", ""), lemma_name.replace("-", "_"))
                                 if "-" in lemma_name.strip("-") else ())

    def of_the_word(example: str, pos: str) -> bool:
        # A SENSE'S EXAMPLE IS ONE OF THIS WORD where the word is written in it, in any form: WordNet gives a sense's
        # examples for all its words, and "do nothing" was read back as an example of `make` (engage in).
        said = re.findall(r"[a-z]+(?:-[a-z]+)*", example.lower())
        return any((w == head or wn.morphy(w, pos) == head) and said[k + 1:k + 1 + len(rest)] == rest
                   for k, w in enumerate(said))

    if "covers" not in _cache:
        # WHAT EACH NOUN SENSE AND KIND COVERS of what SemCor tagged (WordNet's counts are SemCor's): every use of a
        # sense counted for it and for each kind it is, each sense once more.
        covered: Counter = Counter()
        for synset in wn.all_synsets("n"):
            n = sum(l.count() for l in synset.lemmas()) + 1
            for c in {synset} | set(synset.closure(lambda x: x.hypernyms() + x.instance_hypernyms())):
                covered[c.name()] += n
        _cache["covers"] = covered
    covered = _cache["covers"]

    synsets = [s for s in dict.fromkeys(s for spelled in spellings for s in wn.synsets(spelled))
               if any(l.name().lower() in spellings for l in s.lemmas()) and named(s)]
    senses: List[WordSense] = []
    for s in synsets:
        cls = _WORDNET_CLASS[s.pos()]
        lemma = next(l for l in s.lemmas() if l.name().lower() in spellings)
        frames = tuple(dict.fromkeys(f for f in (_frame_named(VERB_FRAME_STRINGS[k]) for k in lemma.frame_ids()
                                                  if 0 < k < len(VERB_FRAME_STRINGS)) if f)) if cls == "VERB" else ()
        kinds = kinds_of(s)
        related = tuple((rel, other.synset().name(), named(other.synset()), other.name().lower())
                        for rel in _WORDNET_LEMMA_RELATIONS for other in getattr(lemma, rel)()) + tuple(
            (rel, other.name(), named(other), "") for rel in _WORDNET_SENSE_RELATIONS
            for other in WordNetSource._ordered(getattr(s, rel)()))
        pertains_to = tuple(dict.fromkeys((other.synset().name(), named(other.synset()), tuple(
            n for _, n in kinds_of(other.synset()))) for other in lemma.pertainyms() if named(other.synset())))
        # AN ADVERB NAMES THE QUALITY ITS ADJECTIVE NAMES, wherever WordNet says which adjective it is of (a
        # pertainym: 2,498 of its 3,621 adverb senses). Lyric's meaning language holds no adverb apart:
        # `_role_of_term` takes whatever a thing OR A HAPPENING `has_property` as one part and names an adverb among
        # its own examples, and english_12 reads "The dog barked loudly." as `has_property(?v0, loud)`. Named after
        # its own sense, the record offered reading `slowly` where teaching had said `slow`, so teaching and reading
        # could never resolve one sentence to one concept, however many senses were held.
        #
        # THE PERTAINYM AND NOT THE MANNER GLOSS, which is the guard the teaching route uses (`in_manner`) and is
        # the wrong one here: that route must write true English, and "Tom walked hardly." is none, while this only
        # answers which concept a word names. Asked for a manner gloss, the two adverbs english_12 itself teaches
        # were missed -- "slowly" is glossed "without speed" and "loudly" "with relatively high volume", neither of
        # them "in a ... manner" -- and 1,044 of the 2,498 with an adjective named went unbound. A degree adverb is
        # no loss: a degree is said through `has_degree` and not through this, and where one does come this way the
        # answer it had was a concept invented from its own spelling (2026-11-08).
        concept = named(s)
        if cls == "ADVERB" and pertains_to:
            concept = pertains_to[0][1]
        senses.append(WordSense(s.name(), cls, concept, s.definition(), kinds, lemma.count(),
                                tuple(e for e in s.examples() if of_the_word(e, s.pos())), frames,
                                covers=(tuple(covered[c] for c in [s.name()] + [k for k, _ in kinds])
                                        if cls == "NOUN" else ()), key=lemma.key(), related=related,
                                pertains_to=pertains_to, one_of=names_one(s)))
    # VERBNET: each class the word is a member of, the WordNet senses the membership is (`wn` keys), and what each of
    # the class's roles may be filled with.
    classes_of: Dict[str, Set[str]] = {}
    restrictions: Dict[Tuple[str, str], Tuple[str, ...]] = {}
    try:
        class_ids = verbnet.classids(lemma_name)
    except Exception:
        class_ids = []
    # EACH CLASS'S FRAMES, the ways its verbs are said ("NP V NP PP.instrument"), with those of the classes it is
    # part of: (the class whose frame it is, its primary and secondary description, its example, what each of its
    # places says, `_frame_places`).
    verbnet_frames: List[Tuple[str, str, str, str, Tuple[Tuple[str, str], ...]]] = []
    for cid in class_ids:
        up = cid
        while up:
            try:
                frames_of = verbnet.vnclass(up).find("FRAMES")
            except Exception:
                break
            for frame in (frames_of.findall("FRAME") if frames_of is not None else ()):
                described = frame.find("DESCRIPTION")
                example = frame.find("EXAMPLES/EXAMPLE")
                held = (up, str(described.get("primary") or "") if described is not None else "",
                        str(described.get("secondary") or "") if described is not None else "",
                        (example.text or "").strip() if example is not None else "", _frame_places(frame))
                if held not in verbnet_frames:
                    verbnet_frames.append(held)
            parent = up.rsplit("-", 1)[0]
            up = parent if parent != up and re.search(r"-\d", parent) else ""
    # A CLASS LISTING THE WORD WITH NO WORDNET SENSE ("pass_away", a member of `die-42.4-1`) says no sense is its
    # member: where no class names any sense of the word, it is the class of each. Given to each sense no class
    # names where others are named, "call" was a member of `initiate_communication-37.4.2-1` as "predict" and
    # "postpone" (PMB train, `GRAMMAR-01/diagnostics/verb_places.py`: objects 85.8% linked as the PMB links them,
    # 86.5% without; 2026-10-29).
    keyless: List[str] = []
    for cid in class_ids:
        vc = verbnet.vnclass(cid)
        for member in vc.iter("MEMBER"):
            if member.get("name") != lemma_name:
                continue
            if not (member.get("wn") or "").split() and cid not in keyless:
                keyless.append(cid)
            for key in (member.get("wn") or "").split():
                try:
                    classes_of.setdefault(cid, set()).add(wn.lemma_from_key(key.lstrip("?") + "::").synset().name())
                except Exception:
                    continue
        for role in vc.iter("THEMROLE"):
            restrictions[(cid, str(role.get("type")).lower())] = tuple(
                f"{r.get('Value')}{r.get('type')}" for r in role.iter("SELRESTR"))
    # PROPBANK: each sense of the verb, its places, and the VerbNet classes it is linked to (by its places' links,
    # the classes VerbNet says the word is a member of).
    frame_file = Path(SYNTAX_DATA) / "propbank-frames" / "frames" / f"{head}.xml"
    rolesets: List[Tuple[str, str, List[Tuple[Any, Dict[str, List[str]]]], Set[str]]] = []
    if any(s.word_class == "VERB" for s in senses) and frame_file.exists():
        for roleset in _rolesets(frame_file):
            if not str(roleset.get("id", "")).startswith(lemma_name + "."):
                continue
            said: Dict[str, List[str]] = {}
            for example in roleset.iter("example"):
                for arg in example.iter("arg"):
                    said.setdefault(str(arg.get("type") or ""), []).append(
                        (arg.text or "").strip().split(" ")[0].lower())
            linked = {str(link.get("class")) for link in roleset.iter("rolelink")
                      if link.get("resource") == "VerbNet" and str(link.get("class")) in classes_of}
            rolesets.append((str(roleset.get("id")), str(roleset.get("name") or ""),
                             [(role, said) for role in roleset.iter("role")], linked))

    def place_of(role: Any, said: Dict[str, List[str]], linked: Set[str]) -> WordPlace:
        arg = "ARG" + str(role.get("n")).upper()
        function = str(role.get("f") or "").upper()
        firsts = said.get(arg, [])
        prepositions = tuple(sorted({f for f in firsts if f in _PREPOSITIONS_WRITTEN}))
        bare = any(f and f not in _PREPOSITIONS_WRITTEN for f in firsts)
        slots = []
        if bare and (function, "") in _PLACE_LINKS and arg in ("ARG0", "ARG1"):
            slots.append(_PLACE_LINKS[(function, "")])
        for p in prepositions:
            if (function, p) in _PLACE_LINKS:
                slots.append(_PLACE_LINKS[(function, p)])
        who = str(role.get("descr") or "")
        head = who.split(",")[-1].strip().split(" ")[0] if who else ""
        fills = ""
        found = wn.synsets(head, "n") if head.isalpha() else []
        if found:
            fills = named(found[0])
        restricted = []
        for link in role.iter("rolelink"):
            cid = str(link.get("class"))
            if cid in linked and link.text:
                for r in restrictions.get((cid, link.text.strip().lower()), ()):
                    if _RESTRICTED_AS.get(r):
                        restricted.append((r, named(wn.synset(_RESTRICTED_AS[r]))))
        return WordPlace(arg, who, function, prepositions, bare, tuple(dict.fromkeys(slots)), fills,
                         tuple(dict.fromkeys(restricted)))
    # EVERY PROPBANK SENSE OF THE WORD, as its frame file gives it: (its id, what it means, the words it is said as with
    # their classes, the FrameNet frames its places are linked to) — paint.01 said as "painting" a noun too.
    propbank: List[Tuple[str, str, Tuple[Tuple[str, str], ...], Tuple[str, ...]]] = []
    if frame_file.exists() and not rest:
        for roleset in _rolesets(frame_file):
            if str(roleset.get("id", "")).startswith(lemma_name + "."):
                propbank.append((str(roleset.get("id")), str(roleset.get("name") or ""),
                                 tuple((str(a.text or "").strip(), str(a.get("pos") or "")) for a in roleset.iter("alias")),
                                 tuple(sorted({str(r.get("class")) for r in roleset.iter("rolelink")
                                               if r.get("resource") == "FrameNet"}))))
    for k, s in enumerate(senses):
        if s.word_class == "VERB":
            member = tuple(sorted(cid for cid, ids in classes_of.items() if s.id in ids)) or (
                tuple(keyless) if not classes_of else ())
            if member:
                senses[k] = dataclasses.replace(s, verbnet_classes=member)
    joined: Dict[str, Set[str]] = {}
    for rid, _, _, linked in rolesets:
        joined[rid] = {sense for cid in linked for sense in classes_of.get(cid, ())}
    uses: List[WordUse] = []
    for k, s in enumerate(senses):
        if s.word_class != "VERB":
            continue
        mine = [r for r in rolesets if s.id in joined[r[0]]]
        if not mine:
            continue
        rid, means, roles, linked = min(mine, key=lambda r: (len(joined[r[0]]), rolesets.index(r)))
        cid = next((c for c in sorted(linked) if s.id in classes_of.get(c, ())), "")
        senses[k] = dataclasses.replace(s, roleset=rid, use=means, verbnet=cid,
                                        places=tuple(place_of(role, said, linked) for role, said in roles))
    # WHAT EACH SENSE WAS SEEN USED WITH (SemCor).
    seen = _semcor_seen(lemma_name, _cache)
    for k, s in enumerate(senses):
        if s.id in seen:
            with_kinds = tuple((slot, filler, (named(wn.synset(filler)),) + tuple(n for _, n in kinds_of(
                wn.synset(filler))), n) for (slot, filler), n in sorted(seen[s.id].items(), key=lambda x: (-x[1], x[0])))
            senses[k] = dataclasses.replace(s, seen_with=with_kinds)
    taken = {s.roleset for s in senses if s.roleset}
    for rid, means, roles, linked in rolesets:
        if rid not in taken:
            uses.append(WordUse(rid, means, tuple(place_of(role, said, linked) for role, said in roles)))
    by_class = {s.word_class for s in senses}
    inflected = {cls: _cache["forms"].get((word, cls), {}) for cls in by_class}
    together: Tuple[int, ...] = ()
    if rest:
        # A WORD OF SEVERAL WORDS, as SemCor's annotators found it written, each form with what form its first word is
        # in the treebanks; and how often its words were said as it, against its first word said with the same words
        # after it as a word of its own ("made it" `make_it` 20 times in SemCor; "made it clear" `make`).
        written_as, together = _semcor_together(lemma_name, head, rest, _cache)
        for cls in by_class:
            head_forms = _cache["forms"].get((head, cls), {})
            inflected[cls] = {}
            for form, n in written_as.items():
                first = form.split(" ")[0]
                features = max(((f, k) for (w, f), k in head_forms.items() if w == first), key=lambda x: x[1],
                               default=("VerbForm=Inf" if first == head and cls == "VERB" else "", 0))[0]
                inflected[cls][(form, features)] = inflected[cls].get((form, features), 0) + n
    closed_written = _closed_forms(word, treebanks, _cache) if not rest else Counter()
    written = {word} | {form for forms_of in inflected.values() for form, _ in forms_of} | \
        {form for form, _, _ in closed_written}
    classes, uses_of, doing_of, asking_of, alone_of, capital_of, shapes_of, of_doing, after_of = _treebank_uses(
        word, written, treebanks, _cache)
    forms: List[WordForm] = []
    for cls in sorted(by_class):
        base_features = {"VERB": "VerbForm=Inf", "NOUN": "Number=Sing", "ADJECTIVE": "Degree=Pos"}.get(cls, "")
        if not any(form == word for form, _ in inflected[cls]):
            # THE WORD WRITTEN AS ITS BASE IS EVERY FORM THE TREEBANKS USED IT AS, each with its features: "like" the
            # infinitive and the present ("I like"), as the analysts wrote it. Held only as the infinitive (the forms
            # of a word count only those written otherwise), "I like disco music." and "You reek of alcohol." were
            # read as told of the past (lyric_dev2, 2026-10-28).
            as_base = _base_written(word, cls, treebanks, _cache)
            for features, n in (sorted(as_base.items(), key=lambda x: (-x[1], x[0])) if as_base else
                                ((base_features, classes.get((word, cls), 0)),)):
                forms.append(WordForm(word, cls, features, n))
        for (form, features), n in sorted(inflected[cls].items(), key=lambda x: (-x[1], x[0])):
            forms.append(WordForm(form, cls, features, n))
        if cls == "VERB":
            # AND EVERY OTHER FORM ENGLISH GIVES IT (`_forms_english_gives`), counted none, so a form a treebank
            # actually wrote stands before one only English gives, and a word written every way is unchanged.
            held = {(f.form, f.features) for f in forms if f.word_class == cls}
            for form, features in _forms_english_gives(word, _cache):
                if (form, features) not in held:
                    forms.append(WordForm(form, cls, features, 0))
                    held.add((form, features))
        if cls == "NOUN":
            # AND THE NUMBER ENGLISH GIVES A NOUN, BOTH OF THEM, counted none, the same way and for the same reason
            # (`_plural_english_gives`): a noun held with no number cannot be told from one of the other number, and
            # what a determiner was said with is counted and then cannot be weighed. "whale" was held `Number=Sing`
            # and "whales" nothing; "mammal" was held no number at all.
            held = {(f.form, f.features) for f in forms if f.word_class == cls}
            said = _plural_english_gives(word, _cache)
            if said is not None and (said, "Number=Plur") not in held:
                forms.append(WordForm(said, cls, "Number=Plur", 0))
                held.add((said, "Number=Plur"))
            # The word itself is the singular, said where nothing wrote a number on it. A form a treebank wrote
            # with its features stands before this, which is counted none.
            if said is not None and not any(form == word and "Number=" in features for form, features in held):
                forms.append(WordForm(word, cls, "Number=Sing", 0))
    # THE CLASSES WORDNET HAS NONE OF, as the treebanks used the word: "for" a preposition, a subordinator; of a class
    # whose words take forms (`_FORMED_CLOSED`), each form the analysts gave the word as its base, with its features
    # ("is", "am", "was" of `be` as an auxiliary; "an" of `a`). Without them "is", "am" and "are" were one word to
    # the grammar, and it said "Wall'm the the a partition." (lyric_dev2, 2026-10-27).
    for (form, cls), n in sorted(classes.items(), key=lambda x: (-x[1], x[0])):
        if cls in _CLOSED_CLASSES and form == word and cls not in _FORMED_CLOSED:
            forms.append(WordForm(form, cls, "", n))
    # AND AN OPEN CLASS'S PRO-FORMS WORDNET HAS NONE OF, whose meaning the grammar gives (`_pro_form`): "how", "when",
    # "where", "why" as adverbs, each with the features the analysts wrote on the word as its base ("how"
    # `PronType=Int` 426 times, `PronType=Rel` 131). Left out with every class WordNet has no sense of, those words had
    # no record at all, and no question asking how, when, where or why was taught a word of it (lyric_dev2, 2026-10-28).
    for cls in sorted({c for (form, c) in classes if form == word and c in _OPEN_CLASSES} - by_class):
        for features, n in sorted(_base_written(word, cls, treebanks, _cache).items(), key=lambda x: (-x[1], x[0])):
            if _pro_form(features) and "Typo=Yes" not in features.split("|"):
                forms.append(WordForm(word, cls, features, n))
    # AND HOW OFTEN EACH FORM WAS A NAME, as the treebanks used it ("Wall" of Wall Street, "Picture" a title): what
    # memory holds of the word's classes then holds its names apart from its nouns (`MemoryAgent._held_word_classes`),
    # as the treebanks do. Counted, and left out of the record with every class WordNet has none of, a noun was held a
    # name as often as a noun, and "Picture is a representation." was read with "Picture" a name (lyric_dev2,
    # 2026-10-28).
    for (form, cls), n in sorted(classes.items(), key=lambda x: (-x[1], x[0])):
        if cls == "NAME":
            forms.append(WordForm(form, cls, "", n))
    for (form, cls, features), n in sorted(closed_written.items(), key=lambda x: (-x[1], x[0])):
        forms.append(WordForm(form, cls, features, n))
    # HOW EACH FORM IS SAID; the subjects each finite form took; and of forms the analysts mark nothing apart (each
    # written most often with the same features as the other: "a" and "an", "is" and "'s"; not "was" and "were", though
    # "was" is now and then written plural), the first sound of the word said after each.
    subjects = _subjects_taking(word, treebanks, _cache) if not rest else {}
    nouns, predicated, objects = _agreeing(word, treebanks, _cache) if not rest else ({}, {}, {})
    most: Dict[Tuple[str, str], WordForm] = {}
    for f in forms:
        if (f.form, f.word_class) not in most or f.count > most[(f.form, f.word_class)].count:
            most[(f.form, f.word_class)] = f
    marked: Dict[Tuple[str, str], Set[str]] = {}
    for f in most.values():
        marked.setdefault((f.word_class, f.features), set()).add(f.form)
    alike = {key for key, f in most.items() if len(marked[(f.word_class, f.features)]) > 1}
    before = _said_before(word, alike, treebanks, _cache) if alike else {}
    # KEPT ONLY WHERE THE SOUND AFTER DECIDES WHICH FORM IS SAID (`_told_apart`): "a" and "an" 0.95; "is" and "'s"
    # 0.07, "am" and "'m" 0.07, said alike before any sound. Weighed by it, every way of saying a thing was kept
    # apart by the sound it begins with, and saying a wall was a partition took 49 s, not 4 (lyric_dev2, 2026-10-27).
    for (cls, _), group in marked.items():
        held = [before.get((form, cls), Counter()) for form in group]
        if len(group) > 1 and _told_apart(held) <= 0.5:
            for form in group:
                before.pop((form, cls), None)
    forms = [dataclasses.replace(
        f, sounds=_sounds_of(f.form, _cache),
        before=tuple(sorted(before.get((f.form, f.word_class), Counter()).items(), key=lambda x: (-x[1], x[0]))),
        subjects=tuple((c, feats, n) for (c, feats), n in sorted(
            subjects.get((f.form, f.word_class, f.features), Counter()).items(), key=lambda x: (-x[1], x[0])))
        if "VerbForm=Fin" in f.features.split("|") else (),
        nouns=tuple((c, feats, n) for (c, feats), n in sorted(
            nouns.get((f.form, f.word_class, f.features), Counter()).items(), key=lambda x: (-x[1], x[0])))
        if f.word_class == "DETERMINER" else (),
        predicated=tuple(said + (n,) for said, n in sorted(
            predicated.get((f.form, f.word_class, f.features), Counter()).items(), key=lambda x: (-x[1], x[0])))
        if f.word_class == "AUXILIARY" else (),
        objects=tuple((c, feats, n) for (c, feats), n in sorted(
            objects.get((f.form, f.word_class, f.features), Counter()).items(), key=lambda x: (-x[1], x[0])))
        if f.word_class in ("VERB", "AUXILIARY") else ()) for f in forms]
    kept = {f.word_class for f in forms}
    as_class = {(f.form, f.word_class) for f in forms}
    closed_forms = {f.form for f in forms if f.word_class in _CLOSED_CLASSES}

    def ours(form: str, use: str) -> bool:
        # A USE IS THIS WORD'S where its form is the word as that class: "painting" used as a noun is the noun
        # "painting", not "paint"; a use named for no class ("sub", "mark:purpose") is a closed form's.
        cls = use.split(":")[0]
        return (form, cls) in as_class if cls in _OPEN_CLASSES | _CLOSED_CLASSES | {"NAME"} else form in closed_forms
    used_as = tuple((form, use, n) for form in sorted(written) for use, n in uses_of.get(form, {}).most_common()
                    if n > 0 and ours(form, use))
    used_before_doing = tuple((form, use, doing_of[form][use]) for form, use, _ in used_as if doing_of[form][use] > 0)
    used_asking = tuple((form, use, asking_of[form][use]) for form, use, _ in used_as if asking_of[form][use] > 0)
    said_alone = tuple((form, alone_of[form]["bare"], alone_of[form]["determined"]) for form in sorted(written)
                       if (form, "NOUN") in as_class and sum(alone_of[form].values()) > 0)
    capitalized = tuple((w, kind, n) for w in sorted(capital_of) for kind, n in sorted(
        capital_of[w].items(), key=lambda x: (-x[1], x[0])) if n > 0 and w.lower() in written)
    shapes = tuple((form, shape, n) for form in sorted(shapes_of) for shape, n in sorted(
        shapes_of[form].items(), key=lambda x: (-x[1], x[0])) if n > 0 and (form, "VERB") in as_class)
    said_of_doing = tuple((form, of_doing[form]["modifier"], of_doing[form]["otherwise"]) for form in sorted(of_doing)
                          if ((form, "NOUN") in as_class or (form, "NAME") in as_class)
                          and sum(of_doing[form].values()) > 0)
    said_after = tuple((nxt, after_of[nxt][True], after_of[nxt][False]) for nxt in sorted(after_of)
                       if "VERB" in kept and not rest and sum(after_of[nxt].values()) > 0)
    means: List[Tuple[str, str, Tuple[Any, ...], Any, int]] = []
    if not rest:
        file_named, by_first = _pmb_meant(_cache)
        taken: Set[Tuple[str, Tuple[Any, ...], Any]] = set()
        # A key names its first word by name alone (`prep_of`: "pictured on" and "a picture on" both `picture`), so of
        # the word's classes it is first the one the word is used as most: "picture" a noun 57 times and a verb 4,
        # "make" a verb. Taken in a fixed order, "a picture of" was the verb's, or "painted by" the noun's.
        used = Counter()
        for (_, cls), n in classes.items():
            used[cls] += n
        for cls in sorted({c for table in _MEANT_BY.values() for c in table} & kept, key=lambda c: (-used[c], c)):
            for (table, key, said), n in sorted(by_first.get(file_named.name(word, cls), {}).items(),
                                                key=lambda x: (-x[1], repr(x[0]))):
                if cls in _MEANT_BY[table] and (table, key, said) not in taken:
                    taken.add((table, key, said))
                    means.append((table, cls, key[1:], said, n))
    joins: Dict[str, int] = {}
    if "PREPOSITION" in kept or "SUBORDINATOR" in kept:
        for function, n in _propbank_joins(_cache).get(word, {}).items():
            link = _PLACE_LINKS.get((function, word))
            if link:
                joins[link[1]] = joins.get(link[1], 0) + n
    joins_things: Counter = Counter()
    if "PREPOSITION" in kept:
        for link, synset, k in _streusle_joins(word, split, _cache):
            took = wn.synset(synset) if synset else None
            what = (((named(took),) if named(took) else ()) + tuple(n for _, n in kinds_of(took))) if took else ()
            joins_things[(link, what)] += k
    tags, joined_so, said_so, enhanced, misc = _record_joins(word, treebanks, _cache) if not rest else (
        Counter(), {}, Counter(), Counter(), Counter())
    layers = dict(
        tags=tuple(k + (n,) for k, n in sorted(tags.items(), key=lambda x: (-x[1], x[0]))),
        joined_as=tuple((level, situation, held[0], held[1]) for (level, situation), held in sorted(
            joined_so.items(), key=lambda x: (-x[1][1], -x[1][0], repr(x[0])))),
        related_as=tuple(k + (n,) for k, n in sorted(said_so.items(), key=lambda x: (-x[1], repr(x[0])))),
        enhanced=tuple(k + (n,) for k, n in sorted(enhanced.items(), key=lambda x: (-x[1], x[0]))),
        misc=tuple(k + (n,) for k, n in sorted(misc.items(), key=lambda x: (-x[1], x[0]))),
        rolesets=tuple(propbank), verbnet_frames=tuple(verbnet_frames))
    carried = {
        ("UD", "ID"): len(layers["joined_as"]), ("UD", "FORM"): len({f.form for f in forms}),
        ("UD", "LEMMA"): int(bool(_treebank_rows(treebanks, _cache)[1].get(word))),
        ("UD", "UPOS"): len({c for (_, c) in classes}), ("UD", "XPOS"): len(layers["tags"]),
        ("UD", "FEATS"): len({f.features for f in forms if f.features}), ("UD", "HEAD"): len(layers["joined_as"]),
        ("UD", "DEPREL"): len(layers["related_as"]), ("UD", "DEPS"): len(layers["enhanced"]),
        ("UD", "MISC"): len(layers["misc"]),
        ("WordNet", "synset"): len(senses), ("WordNet", "definition"): sum(bool(s.means) for s in senses),
        ("WordNet", "examples"): sum(len(s.examples) for s in senses),
        ("WordNet", "hypernyms"): sum(len(s.kind_of) for s in senses),
        ("WordNet", "lemma count"): sum(s.used for s in senses), ("WordNet", "verb frames"): sum(
            len(s.frames) for s in senses), ("WordNet", "lemma key"): sum(bool(s.key) for s in senses),
        ("WordNet", "relations"): sum(len(s.related) for s in senses), ("WordNet", "hyponyms"): 0,
        ("WordNet", "domain members"): 0,
        ("PropBank", "roleset"): len(propbank), ("PropBank", "roles"): sum(len(s.places) for s in senses) + sum(
            len(u.places) for u in uses), ("PropBank", "aliases"): sum(len(r[2]) for r in propbank),
        ("PropBank", "FrameNet"): sum(len(r[3]) for r in propbank),
        ("PropBank", "examples"): sum(len(p.prepositions) for s in senses for p in s.places),
        ("VerbNet", "members"): sum(bool(s.verbnet) for s in senses),
        ("VerbNet", "restrictions"): sum(len(p.restricted) for s in senses for p in s.places),
        ("VerbNet", "frames"): len(verbnet_frames),
        ("CMUdict", "phones"): sum(bool(f.sounds) for f in forms),
        ("SemCor", "tags"): sum(len(s.seen_with) for s in senses),
        ("STREUSLE", "SNACS"): len(joins_things), ("PMB", "meaning"): len(means), ("PMB", "derivation"): 0}
    layers["covered"] = tuple((source, column, n) for (source, column), n in carried.items())
    # WHAT EACH SOURCE GAVE FOR THIS WORD, AND WHICH GAVE NOTHING. The record has counted this all along
    # (`carried`, kept as `covered`) and the teaching module never said it, so a word taught with half its sources
    # silent looked exactly like a word taught whole, and the shortfall showed up only much later as something the
    # substrate could not do: "bark" was built with the treebanks having written one form of it, nothing said so,
    # and `A dog barked.` was read and could not be said at all (2026-11-04).
    gave_nothing = sorted(f"{source}/{column}" for (source, column), n in carried.items() if not n)
    logger.info("teaching: built %r -- %d forms, %d senses, %d of %d source columns filled",
                word, len(forms), len(senses), len(carried) - len(gave_nothing), len(carried))
    if gave_nothing:
        logger.info("teaching:   gave nothing for %r: %s", word, ", ".join(gave_nothing))
    return WordRecord(word, tuple(forms), tuple(senses), tuple(uses), used_as,
                      tuple(sorted(joins.items(), key=lambda x: (-x[1], x[0]))),
                      "WordNet 3.0 (senses, definitions, kinds, counts, frames); UD English EWT and GUM (forms); "
                      "SemCor (what each verb sense was seen used with); "
                      "PropBank frames (senses of the verb, places; what a preposition opens); VerbNet 3.3 (which "
                      "PropBank sense is which WordNet sense, what may fill a place); UD English EWT and GUM (how "
                      "each form is used, as the grammar names its uses); STREUSLE 4.6 (what a preposition says "
                      "joining a thing to a thing)",
                      "WordNet licence (Princeton); UD EWT CC BY-SA 4.0, GUM CC BY-NC-SA 4.0; PropBank CC BY-SA 4.0; "
                      "VerbNet (University of Colorado); STREUSLE CC BY-SA 4.0", split,
                      tuple((link, names, k) for (link, names), k in sorted(joins_things.items(),
                                                                          key=lambda x: (-x[1], x[0]))),
                      together, used_before_doing, used_asking, said_alone, capitalized, shapes, said_of_doing,
                      said_after, tuple(means), **layers)


#: Prepositions as PropBank's examples begin an argument with them ("in oils", "by the playwright").
_PREPOSITIONS_WRITTEN = frozenset({"about", "above", "across", "after", "against", "along", "among", "around", "as",
                                   "at", "before", "behind", "below", "beneath", "beside", "between", "beyond", "by",
                                   "despite", "down", "during", "for", "from", "in", "inside", "into", "like", "near",
                                   "of", "off", "on", "onto", "out", "outside", "over", "past", "since", "through",
                                   "throughout", "to", "toward", "towards", "under", "until", "up", "upon", "with",
                                   "within", "without"})


#: Where the word groups counted from WikiText-103 are kept on disk (data is not in the repository;
#: `experiments/GROUPS-01` writes them): `groups_<n>.tsv`, a word and its group a line, a file for each count of groups.
WORD_GROUPS_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "data", "word_groups")


@dataclass
class WordGroupsSource:
    """Words grouped by the company they keep in WikiText-103's raw training text (about 100 million words of
    Wikipedia, CC BY-SA), counted, no model learned (`word_groups.counted_groups`, `experiments/GROUPS-01`): the
    100,000 most frequent words, into 256 groups and into 48. It teaches which words keep the same company
    (`word_groups()`), for the structure reader to weigh a word it met rarely or never by its group, and states
    nothing else. Counted, not checked by hand: it is not curated."""

    data: str = WORD_GROUPS_DATA
    name: str = "wikitext_103_word_groups"
    quality: float = 0.9
    curated: bool = False
    vocabulary_only: bool = True

    def provenance(self):
        return _provenance("word_groups", "wikitext_103_raw_v1")

    def records(self) -> Iterator[TaughtRecord]:
        return iter(())

    def word_groups(self) -> Iterator[Any]:
        """Every group of every count, the fewest groups' first."""
        from core.semantics.word_groups import groups_of, read_groups
        counted = sorted((int(m.group(1)), name) for name in (os.listdir(self.data) if os.path.isdir(self.data) else ())
                         for m in [re.fullmatch(r"groups_(\d+)\.tsv", name)] if m)
        if not counted:
            raise FileNotFoundError(
                f"no word groups in {self.data}; count them first (experiments/GROUPS-01 writes groups_256.tsv and "
                f"groups_48.tsv there). A teaching pass does not reach the network.")
        for of, name in counted:
            yield from groups_of(read_groups(os.path.join(self.data, name)), of, "wikitext_103")


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

# ── English's grammar held from files ───────────────────────────────────────────────────────────────────────────────
# What a grammar holds of each word, from UD English EWT's training part and WordNet, read the way main reads them
# (moved here from GRAMMAR-01's `words.py`, which imports it): the grammar the PMB's gold sentences are learned by
# when a word record's meanings are counted (`_pmb_meant`), and GRAMMAR-01's. How each word is used is counted by
# `grammar_words.HeldWords` (`read_conllu`), the forms each word is written in by `word_forms`; what each word's thing
# is comes from `grammar_words.GraphKnowledge` holding WordNet's links (`isa`, `instance_of`, `defined_with`); a word
# is named by WordNet's plain form (`morphy`), else as the treebank's lemmas have it. WordNet's links are kept beside
# the treebank (`grammar_wordnet_links.pkl`, never pushed) once read: about a minute.

_NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUMBER_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
                      "ninety": 90, "hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12})
_FILE_UD = {"NOUN": "NOUN", "PROPN": "NAME", "VERB": "VERB", "ADJ": "ADJECTIVE", "ADV": "ADVERB", "NUM": "NUMERAL",
            "ADP": "PREPOSITION", "AUX": "VERB"}


def file_structure(ewt: Path):
    """The structure view as memory holds it (`structure.StructureView`), from the treebank at `ewt`: which of two
    readings the grammar reads as surely it keeps (`Grammar._joined`)."""
    from core.semantics.structure import StructureView
    view = StructureView()
    for analysed in read_conllu(str(ewt), "ewt"):
        view.add(analysed)
    return view


def file_words(ewt: Path, closed):
    """The words as GRAMMAR-01 holds them (`HeldWords`), from the treebank at `ewt` and WordNet."""
    import pickle
    from nltk.corpus import wordnet as wn
    from core.semantics.grammar_words import GraphKnowledge, HeldWords
    lemmas: Dict = defaultdict(Counter)
    endings: Dict = defaultdict(Counter)
    with open(ewt, encoding="utf-8") as handle:
        for line in handle:
            cols = line.rstrip("\n").split("\t")
            if len(cols) == 10 and cols[0].isdigit() and cols[3] in _FILE_UD:
                form, lemma, cls = cols[1].lower(), cols[2].lower(), _FILE_UD[cols[3]]
                lemmas[(form, cls)][lemma] += 1
                k = 0
                while k < min(len(form), len(lemma)) and form[k] == lemma[k]:
                    k += 1
                endings[(form[-3:], cls)][(len(form) - k, lemma[k:])] += 1
    by_class = {"NOUN": wn.NOUN, "VERB": wn.VERB, "ADJECTIVE": wn.ADJ, "ADVERB": wn.ADV}

    def name_of(word: str, cls: str) -> str:
        w = word.lower()
        if w in _NUMBER_WORDS and cls == "NUMERAL":
            return str(_NUMBER_WORDS[w])
        if re.fullmatch(r"-?\d+(\.\d+)?", w):
            return w
        got = lemmas.get((w, cls))
        if cls == "VERB" and got:
            # A verb's form as the treebank's lemmas have it first ("found": find, "saw": see), as memory names a
            # verb by the word it is a shape of (`MemoryAgent.name_of`).
            return got.most_common(1)[0][0]
        if cls in by_class:
            found = wn.morphy(w, by_class[cls])
            if found:
                return found.replace("_", " ")
        if got:
            return got.most_common(1)[0][0]
        change = endings.get((w[-3:], cls))
        if change:
            cut, add = change.most_common(1)[0][0]
            return w[:len(w) - cut] + add
        return w

    def classes(word: str) -> Dict[str, float]:
        """The kinds of word WordNet holds this very word as (a lemma of it, as memory holds the words taught; never
        through WordNet's own undoing of forms: "giggling" is no verb held, "giggle" is)."""
        out: Dict[str, float] = {}
        w = word.lower().replace(" ", "_")
        for synset in wn.synsets(w):
            if w not in (l.lower() for l in synset.lemma_names()):
                continue
            c = {"n": "NOUN", "v": "VERB", "a": "ADJECTIVE", "s": "ADJECTIVE", "r": "ADVERB"}[synset.pos()]
            out[c] = out.get(c, 0.0) + 1.0
        return out

    def names(words: Sequence[str]) -> Dict[str, str]:
        """Each kind of word WordNet holds these words as one word of, with the name it holds them under, as memory
        answers it (`MemoryAgent._held_names`): the words as written, and for a thing the last word as its base
        ("gold medals" `gold medal`)."""
        said = [w.lower() for w in words]
        out: Dict[str, str] = {}
        for cls, part in by_class.items():
            mine = said[:-1] + [wn.morphy(said[-1], wn.NOUN) or said[-1]] if cls == "NOUN" else said
            joined = "_".join(mine)
            if wn.synsets(joined, part):
                out[cls] = joined.replace("_", " ")
        return out

    #: WHAT A THING IS SAID WITH, the other way round from `name_of` (`HeldWords.words_for`: "What `Grammar.say`
    #: says a thing with"). Memory answers this from its word records and the names its sentences give; from files
    #: there was nothing to answer it with, so `written_for` was never passed, `words_for` returned [] for EVERY
    #: thing, and saying could name nothing at all: it said something for 5 of 394 meanings read right whole and
    #: said "Myself am from Russia." for "I am from Russia." -- a figure of the harness and not of the grammar
    #: (`on_store.py`, 2026-10-29). Saying was measurable only against a store holding words, so it could not be
    #: worked on from files the way reading is.
    #:
    #: Built as the EXACT INVERSE of `name_of` over the treebank's words and WordNet's lemmas, so every word offered
    #: for a thing is one that names that thing when read back; the most used first, as memory orders them. A thing
    #: no word is held for is said by ITS OWN NAME where that word names itself -- the fallback that carries main,
    #: which holds 94,262 word classes and no word records and still says as much as a sandbox with 559 records.
    #: Built on first ask and kept, so a run that only reads never pays for it.
    written: Dict[Tuple[str, str], List[str]] = {}

    def written_for(name: str, cls: str) -> List[str]:
        if not written:
            counted: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
            for (form, c), these in lemmas.items():
                counted[(name_of(form, c), c)][form] += sum(these.values())
            for c, part in by_class.items():
                for synset in wn.all_synsets(part):
                    for lemma in synset.lemma_names():
                        word = lemma.lower().replace("_", " ")
                        counted[(word if " " in word else name_of(word, c), c)].setdefault(word, 0)
            written.update({key: [w for w, _ in found.most_common()] for key, found in counted.items()})
        held = written.get((name, cls))
        if held:
            return list(held)
        return [name] if name_of(name, cls) == name else []

    knowledge = GraphKnowledge(classes=classes, names=names)
    held = ewt.parent.parent / "grammar_wordnet_links.pkl"
    if held.exists():
        links = pickle.loads(held.read_bytes())
    else:
        links = [(r.subject, r.relation, r.obj) for r in WordNetSource().records()
                 if r.relation in ("isa", "instance_of", "defined_with")]
        held.write_bytes(pickle.dumps(links))
    for subject, relation, obj in links:
        knowledge.add(subject, relation, obj)
    from core.semantics.word_forms import HeldForms, forms_from_conllu
    forms = HeldForms()
    with open(ewt, encoding="utf-8") as handle:
        for item in forms_from_conllu(handle, "ud_english_ewt"):
            forms.hold(item)
    return HeldWords(read_conllu(str(ewt), "ud_english_ewt"), closed, name_of, knowledge, forms,
                     written_for=written_for)
