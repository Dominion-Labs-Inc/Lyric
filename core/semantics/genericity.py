#!/usr/bin/env python3
"""What proposition a copular sentence expresses. SEMANTICS OWNS THIS.

MOVED OUT OF `core/reasoning/neural_bridge.py` on 2026-08-24. Genericity is a
fact about language -- whether a sentence speaks of a kind, an individual, or
some unnamed thing -- and belongs with the faculty that reads sentences, not
with the one that reasons over what they say.

THE RISK IT GUARDS. "A robin is a bird" needs to become a rule about kinds, and
the cheap way there is to read the article `a` as a quantifier. That turns
"A robin is in the yard" into a law about all robins: an overgeneralization
machine that proves things nobody said.

So classification is its OWN STAGE, kept apart from reading and from
formalizing. A reader says what a sentence relates. This says whether the formal
grammar can carry that relation -- and for EXISTENTIAL and AMBIGUOUS readings it
cannot, because the grammar has no existential quantifier and nothing here may
resolve an ambiguity the sentence left open.

Applied to BOTH readers. The hand-written patterns and the derived reading each
skipped it once, and each produced `robin_yard` -- reading `robin` as a named
individual when the sentence says SOME robin.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── THE WORD CLASSES ────────────────────────────────────────────────────────
# These lived in `lexicon.py` alongside a store of one class per word. The
# store is gone -- classes are observations, held in memory with everything
# else the substrate has learned -- and the names live here, with the two
# functions that read them.
NOUN = "NOUN"
ADJECTIVE = "ADJECTIVE"
VERB = "VERB"
CLASSES = (NOUN, ADJECTIVE, VERB)


#: Locative prepositions and adverbs. A copula that LOCATES is not classifying,
#: so an indefinite subject with one of these is existential, never generic.
_LOCATIVE_PREPOSITIONS = (
    "in", "on", "at", "near", "inside", "outside", "under", "underneath",
    "over", "above", "below", "beside", "behind", "within", "beyond", "by",
    "next", "across", "between", "among", "around",
)
_LOCATIVE_ADVERBS = (
    "here", "there", "nearby", "upstairs", "downstairs", "outside", "inside",
    "abroad", "away", "home",
)

_INDEFINITE = ("a", "an")
_DEFINITE = ("the",)

#: A complement denoting a kind: an indefinite article and a single common noun.
_KIND_COMPLEMENT = re.compile(r"^(?:a|an)\s+([a-z][\w'-]*)$", re.IGNORECASE)
_BARE_WORD = re.compile(r"^[\w'-]+$")


class Genericity(Enum):
    """The proposition type a copular sentence expresses."""

    GENERIC_KIND = "generic_kind"
    INSTANCE = "instance"
    EXISTENTIAL = "existential"
    AMBIGUOUS = "ambiguous"

    @property
    def is_representable(self) -> bool:
        """Whether the current formal language can express this at all.

        EXISTENTIAL is understood and NOT representable -- there is no
        existential quantifier in the propositional grammar the solver takes.
        Those are different failures and must not share an answer: rendering
        "A robin is in the yard" as an atom like `robin_in_yard` would keep the
        pipeline running while quietly discarding the quantifier.
        """
        return self in (Genericity.GENERIC_KIND, Genericity.INSTANCE)


@dataclass(frozen=True)
class GenericityReading:
    """A classification, with the cue that produced it kept for provenance."""

    genericity: Genericity
    subject: str
    complement: str
    #: Why this reading was chosen. Cognition-bearing: a proof that rests on a
    #: universal rule should be able to say why that rule existed.
    cue: str
    determiner: Optional[str] = None
    transformations: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_representable(self) -> bool:
        return self.genericity.is_representable


def _leading_word(text: str) -> str:
    stripped = text.strip()
    return stripped.split()[0].lower() if stripped else ""


def _is_locative(complement: str) -> bool:
    head = _leading_word(complement)
    if head in _LOCATIVE_PREPOSITIONS:
        return True
    return head in _LOCATIVE_ADVERBS and _BARE_WORD.match(complement.strip() or "x") is not None


def unrepresentable_reason(genericity: "Genericity") -> str:
    """The stable name for WHY a reading cannot be represented.

    A caller must be able to test which limit it hit, so these are markers, not
    prose. They were written at one decline site and a second site later grew
    its own wording -- at which point the same refusal had two names and only
    one of them was greppable.
    """
    return ("existential_quantification_not_supported"
            if genericity is Genericity.EXISTENTIAL
            else "ambiguous_quantification_not_resolved")


def _is_habitual_present(relation: Optional[str]) -> bool:
    """Is this relation a PRESENT-TENSE verb, as in "a crucible MELTS ore"?

    English marks the habitual generic with third-person singular present: a
    crucible MELTS ore says what crucibles do, while "a man WALKED in" says that
    one did. Tense is the whole difference and it is carried in the verb's own
    morphology, so it is read off the word rather than guessed from the sentence.

    Imported locally: `lexical_normalization` is reached through the reader,
    which imports this module, and a top-level import here would close the cycle.
    """
    from core.semantics.lexical_normalization import deinflect_verb
    from core.semantics.sentence_machine import (AUXILIARIES, COPULAS, MODALS,
                                                 PASSIVE_AUXILIARIES)

    word = str(relation or "").strip().lower()
    if not word or " " in word or not word.endswith("s") or word.endswith("ss"):
        return False
    # A FUNCTION WORD IS NOT A HABIT. `was`, `is`, `has`, `does` all end in -s
    # and de-inflect to something shorter, so the morphology alone called `was`
    # a present-tense action. These are the closed classes the machine already
    # declares; none of them is the verb of a habitual claim.
    if word in (COPULAS | AUXILIARIES | MODALS | PASSIVE_AUXILIARIES):
        return False
    # It must really de-inflect: `melts` -> `melt`. A plural noun standing where
    # a verb would be also passes, which is why this only ever makes a sentence
    # GENERIC and never decides that a word is a verb.
    return any(len(base) < len(word) for base in deinflect_verb(word))


def classify_genericity(subject: str, complement: str,
             determiner: Optional[str] = None,
             relation: Optional[str] = None) -> GenericityReading:
    """Classify one sentence: `<determiner> <subject> <relation> <complement>`.

    `determiner` is whatever preceded the subject, or None for a bare subject.
    `relation` is the verb or copula relating them, where the caller knows it.
    """
    subject = (subject or "").strip()
    complement = (complement or "").strip().rstrip(".?!")
    determiner_key = (determiner or "").strip().lower() or None
    transformations = ()

    if not subject or not complement:
        return GenericityReading(Genericity.AMBIGUOUS, subject, complement,
                                 "empty subject or complement", determiner_key)

    # A proper noun names an individual, so the sentence is about that
    # individual whatever the complement says. Detected AFTER the determiner is
    # separated, so sentence-initial capitalisation of "A" cannot be mistaken
    # for a proper noun.
    if subject[0].isupper():
        return GenericityReading(Genericity.INSTANCE, subject, complement,
                                 "subject is a proper noun", determiner_key,
                                 transformations)

    if determiner_key in _DEFINITE:
        return GenericityReading(Genericity.INSTANCE, subject, complement,
                                 "definite subject denotes a particular individual",
                                 determiner_key, transformations)

    if determiner_key in _INDEFINITE:
        # Order matters: locative first, because "in a yard" also contains an
        # indefinite article and would otherwise read as a kind.
        if _is_locative(complement):
            return GenericityReading(Genericity.EXISTENTIAL, subject, complement,
                                     "copula locates rather than classifies",
                                     determiner_key, transformations)
        if _KIND_COMPLEMENT.match(complement):
            return GenericityReading(
                Genericity.GENERIC_KIND, subject, complement,
                "both sides denote kinds and the copula classifies",
                determiner_key, transformations + ("generic_class_interpretation",))
        # AN ACTION IN THE PRESENT IS A HABIT, NOT AN ENCOUNTER. The ambiguity
        # below is real for a COPULAR complement -- "A robin is small" is
        # generic, "A doctor is available" is existential -- but it was being
        # applied to ACTION sentences too, where English is not ambiguous: "A
        # crucible melts ore" says what crucibles do. Measured: "The crucible
        # melts ore" read and "A crucible melts ore" did not, for no reason but
        # the article.
        if _is_habitual_present(relation):
            return GenericityReading(
                Genericity.GENERIC_KIND, subject, complement,
                "indefinite subject of a present-tense action states a habit",
                determiner_key, transformations + ("habitual_generic",))
        # A bare adjective is genuinely undecidable: "A robin is small" is
        # generic, "A doctor is available" is existential, and nothing in the
        # surface form separates them. Declining preserves the ambiguity.
        return GenericityReading(Genericity.AMBIGUOUS, subject, complement,
                                 "indefinite subject with a non-classifying "
                                 "complement; generic and existential readings "
                                 "are both available",
                                 determiner_key, transformations)

    # No determiner. A bare common noun subject with a classifying complement
    # is the "Socrates is human" shape without the capital -- an individual.
    return GenericityReading(Genericity.INSTANCE, subject, complement,
                             "bare subject read as an individual",
                             determiner_key, transformations)


def _subject_and_complement(sentence: str,
                           subject: str) -> Tuple[Optional[str], str]:
    """The article framing the subject, and the complement AS WRITTEN.

    Genericity is decided on the complement in the form the sentence used, not
    on the bare term a reading returned. `("robin", "a bird")` classifies as a
    kind; `("robin", "bird")` classifies as AMBIGUOUS and refuses. Passing the
    bare object therefore rejected "a robin is a bird" -- a perfectly
    representable statement about kinds -- for want of the article.

    No pattern is written here. The subject is located in the sentence, the text
    after it is the complement, and a leading copula or negator is dropped using
    the vocabulary the semantics layer already owns.
    """
    from core.semantics.sentence_machine import COPULAS, DETERMINERS, NEGATORS

    words = (sentence or "").strip().split()
    lowered = [w.lower().strip(".,?!") for w in words]
    target = str(subject).lower().strip()

    try:
        at = lowered.index(target)
    except ValueError:
        at = 0

    determiner = (words[at - 1] if at > 0 and lowered[at - 1] in DETERMINERS
                  else None)

    rest = words[at + 1:]
    while rest and rest[0].lower().strip(".,?!") in (COPULAS | NEGATORS):
        rest = rest[1:]
    return determiner, " ".join(rest).strip(".,?!")


@dataclass
class Dependence:
    """What a single reading leaned on, so its outcome can attest to it.

    `consulted` is every RECORDED class the reading actually looked up, with the
    answer it got -- not every word in the sentence. A class that was never
    consulted did not carry the reading and must not be credited by it.

    `blamed` is (word, class, why): the class a refusal was attributed TO. A
    sentence can fail to read for a dozen reasons that say nothing about any
    word's class; only the branches that refuse BECAUSE of a class name it
    here, so a refusal never counts against a word it was not about.

    The CLASS is carried explicitly rather than left inside `why`. It is what
    the refusal is evidence against, and a warm that had to recover it by
    reading English out of a diagnostic string would be guessing.
    """

    consulted: Dict[str, str] = field(default_factory=dict)
    blamed: List[Tuple[str, str, str]] = field(default_factory=list)


#: The reading in progress, or None when nothing is being read. A ContextVar
#: rather than an attribute because the reader is a shared singleton and two
#: concurrent reads must not pool their dependences into one ledger.
_dependence: ContextVar[Optional[Dependence]] = ContextVar("_dependence",
                                                           default=None)


@contextmanager
def depending():
    """Scope one reading, collecting the word classes it leans on.

    THE LEXICON'S CONTRACT NEEDED A WITNESS. `PROPOSED` means a teacher said so;
    `CONFIRMED` means "a sentence depending on it read successfully"; `REFUTED`
    means one "failed to read". Nothing in the substrate ever supplied that
    outcome -- `confirm`/`refute` had no caller outside a retired experiment --
    so 92,404 entries sat as unattested proposals and the scaffold could never
    shrink. This is the missing half: reading is what earns a word its class.

    RE-ENTRANT, AND IT HAS TO BE. A conditional reads its antecedent and its
    consequent back through the same method, so one sentence opens this scope
    three times. Nested scopes would split one reading's dependences into three
    ledgers and attest the sentence three times over -- inflating confirmations
    by the shape of the grammar rather than by what was read. An inner scope
    yields None instead, meaning "you are not the owner, do not attest", and the
    outermost scope alone sees the whole reading.
    """
    existing = _dependence.get()
    if existing is not None:
        yield None
        return
    token = _dependence.set(Dependence())
    try:
        yield _dependence.get()
    finally:
        _dependence.reset(token)


def blame(word: str, word_class: str, why: str) -> None:
    """Attribute a refusal to a word's observed class.

    Called only from the branches that refuse BECAUSE of a class. Outside a
    reading this is a no-op, so the reader behaves identically when nobody is
    collecting.
    """
    dependence = _dependence.get()
    if dependence is not None and word:
        dependence.blamed.append(
            (str(word).strip().lower(), str(word_class).strip().upper(), why))


# ── WHAT A READ PROPOSITION SAYS ABOUT ITS WORDS ────────────────────────────
# Not a second opinion on relation kinds -- `relation_types` owns what a
# relation MEANS; these answer the narrower question of what class its
# words must be. They live beside the READ side of word classes because
# that is who applies them: the classes are derived when the view warms,
# from the substrate's own memories of what it was taught.

#: A BARE copula's complement is decided by its DETERMINER: "a device" is a kind
#: (NOUN), "red" with no article is a property (ADJECTIVE).
_ARTICLES = ("a", "an", "the")
#: A TYPED relation already says what its object is; asking the surface would be
#: both unnecessary and wrong. `isa` means "is a kind of" -- the object names a
#: kind, full stop.
_KIND_RELATIONS = frozenset({"isa", "is_a", "instance_of", "member_of"})
#: `has_property` says so in its name.
_PROPERTY_RELATIONS = frozenset({"has_property"})
#: Only these are genuinely ambiguous -- "the tank is hot" against "the tank is
#: a vessel" -- and only these arise from a sentence someone actually said,
#: where the determiner is really there to read.
_BARE_COPULA = frozenset({"is", "are", "be"})


def _single_token(term: str) -> Optional[str]:
    """The lexical head to record a class for, or None when the term is not a
    single word -- a compound ("external_source") is not one part of speech, so
    recording a class for it would be a guess."""
    head = str(term or "").strip().lower()
    return head if head.isalpha() else None


def _mentions(sentence: str, word: str) -> bool:
    """Whether the surface actually contains the word.

    A synthesised surface either omits the term entirely or states it with no
    determiner it could ever have had, so absence of an article there is not
    evidence of anything.
    """
    import re
    head = str(word or "").split("_")[0].lower()
    return bool(head) and head in re.findall(r"[\w'-]+", str(sentence).lower())


def _has_article(sentence: str, word: str) -> bool:
    """Whether `word` appears in the surface right after a/an/the -- the signal
    that a copular complement names a kind rather than a property."""
    import re
    toks = re.findall(r"[\w'-]+", str(sentence).lower())
    head = str(word or "").split("_")[0].lower()
    return any(t == head and i and toks[i - 1] in _ARTICLES
               for i, t in enumerate(toks))


def classes_implied_by(surface: str, subject: str, relation: str,
                       obj: Optional[str]) -> Dict[str, str]:
    """The word classes a read proposition IMPLIES. {word: CLASS}.

    THE RELATION IS THE VERB, AND IT USED TO BE THROWN AWAY. This recorded the
    subject and the object and used `relation` only to decide the object's
    class, never its own -- so after every data source was dropped the store
    held 199 words and every single one was a NOUN. A lexicon of nothing but
    nouns does not merely fail to help the reader: a word filed as a NOUN makes
    `_reads_as_verb` return False, so "A filter separates particles." read
    correctly while `separates` was unknown and STOPPED reading once the word
    was catalogued.

    A relation is recorded as a VERB only when the surface actually contains
    it. `isa` and `has_property` are typed relations the substrate synthesises;
    they are never words anyone said, and recording them would teach it that
    "isa" is an English verb.
    """
    implied: Dict[str, str] = {}

    def record(term: Optional[str], word_class: str) -> None:
        head = _single_token(term)
        if head:
            implied[head] = word_class

    # The subject of a predication is a thing.
    record(subject, NOUN)

    rel = str(relation or "").strip().lower().replace(" ", "_")

    # The action, when the sentence really says it.
    if rel not in _KIND_RELATIONS and rel not in _PROPERTY_RELATIONS \
            and rel not in _BARE_COPULA and _mentions(surface, rel):
        record(rel, VERB)

    if obj:
        if rel in _PROPERTY_RELATIONS:
            record(obj, ADJECTIVE)
        elif rel in _KIND_RELATIONS:
            # `isa` MEANS "is a kind of"; the object names a kind, full stop.
            record(obj, NOUN)
        elif rel in _BARE_COPULA:
            # THE DETERMINER TEST NEEDS A SENTENCE THAT HAS ONE. Where the
            # surface does not contain the object at all, "no article" was
            # absence of evidence read as evidence of a property -- which is
            # how 314,856 bulk-taught edges each proposed their parent an
            # ADJECTIVE. Nothing is recorded then: an honest gap, not a guess.
            if _mentions(surface, obj):
                record(obj, NOUN if _has_article(surface, obj) else ADJECTIVE)
        else:
            # Every other relation takes a THING as its object.
            record(obj, NOUN)

    return implied


def _word_classes(word: str) -> frozenset:
    """Every class this word has been OBSERVED to have. Possibly several.

    A word is not one part of speech. `filter` is a thing and something one
    does; so are `blocks`, `runs`, `separates`. The store this replaced could
    hold ONE class per word and counted a second as a CONTRADICTION, so real
    English drove real words to REFUTED and out of usability -- and callers
    asking "what class is this" got either a coin-flip or, on even evidence,
    nothing at all.

    Only classes the evidence is net-positive for are returned; a class that
    has been leaned on and failed more often than it has succeeded is not one
    the substrate has observed, it is one it has tried and lost.

    Empty means "never observed", and callers answer that from the sentence's
    own structure rather than guessing a class here.
    """
    from core.agents import memory_agent as _memory

    agent = _memory._memory_agent
    if agent is None:
        return frozenset()

    observed = frozenset(
        cls for cls, net in agent.word_classes(word).items() if net > 0)
    if observed:
        dependence = _dependence.get()
        if dependence is not None:
            # A reading that leaned on membership depends on it just as one that
            # leaned on identity does.
            dependence.consulted[str(word).strip().lower()] = "/".join(sorted(observed))
    return observed


def _word_class(word: str) -> Optional[str]:
    """The class this word has been OBSERVED to have, or None. Never guesses.

    What the substrate has seen a word do is something it LEARNED, so it lives
    in memory with everything else it has learned, and this reads the memory
    authority's warm view of it. There is no lexicon: the file that used to
    answer this held 199 words, all of them NOUN, 197 proposed by a fan-out
    nobody taught, and it survived database wipes -- so a clean store was
    re-poisoned on its first read. Worse than useless, it was SUBTRACTIVE:
    `_reads_as_verb` returns False for a known NOUN, so "A filter separates
    particles." read correctly while `separates` was unknown and stopped
    reading once the file called it a noun.

    None means "not observed", and the reader answers it by reading the
    SENTENCE -- its own structural evidence -- which is why None is safe to
    return when memory is not up yet or has not been warmed. That is a real gap
    honestly reported, not a fallback: nothing is guessed in its place.

    A lookup inside a `depending()` scope is RECORDED, because a reading that
    took this answer is a reading that depends on it.
    """
    from core.agents import memory_agent as _memory

    # The live agent, WITHOUT awaiting one into existence. Reading happens
    # synchronously inside a parse; there is no place to await here, and a
    # reader that blocked on memory coming up would deadlock its own boot.
    agent = _memory._memory_agent
    if agent is None:
        return None

    recorded = agent.word_class(word)
    if not recorded:
        return None

    dependence = _dependence.get()
    if dependence is not None:
        dependence.consulted[str(word).strip().lower()] = recorded
    return recorded
