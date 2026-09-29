#!/usr/bin/env python3
"""Where a sentence's pieces begin and end.

`form_of` splits written text into the pieces a sentence is made of -- words,
numbers and marks -- and loses nothing: capitals stay capitals, `3pm` keeps its
3, an apostrophe inside a word stays in the word, and every mark is a piece of
its own. It knows the writing system, not English: a piece is a run of letters
and digits, joined through an apostrophe, a full stop or a hyphen that sits
between two of them, and any other character that is not a space. What the
pieces MEAN, and which of them English treats as one unit (whether `Dr` `.` is
an abbreviation), is learned, not decided here. `surface_of` puts the pieces
back as they were written, with one space wherever there was space.

THE CURSOR MACHINE THAT STOOD HERE IS GONE. `SentenceMachine` (a cursor, three
registers and eight instructions) existed so a reading procedure could be
derived from sentence/meaning pairs written into `derived_reader`. Readings are
learned from taught sentences held in memory now (`derived_reader`), so the
machine had no user left; it is kept in
`archive/superseded_language_2026-09-27/sentence_machine.py`.

STILL HERE UNTIL THEIR CALLERS SWITCH (`docs/research/SHAPES_CHANGE_MAP.md`,
step 3): the fixed closed-class word lists the written reader and `genericity`
consult, `tokenize` (lowercased words, for the conversation's written paths),
and the yes/no verdict reader. They are English written into the code, and they
go when every reading goes through learned patterns.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Optional, Tuple

#: The whole supplied FUNCTION lexicon: closed classes, finite, given -- the same
#: honest boundary the module names (word CLASS of a function word is supplied;
#: open-class content is taught). Prepositions/pronouns/etc. are added here
#: rather than left to be mistaken for content the way "on"/"by" were.
COPULAS = frozenset({"is", "are"})
DETERMINERS = frozenset({"a", "an", "the"})
NEGATORS = frozenset({"not", "never", "n't", "nor"})
#: Prepositions that head a phrase. A preposition is either the relation itself
#: ("the vault is IN the room") or the marker of an adjunct to drop ("sells
#: shells BY the sea"); which one is decided by position (before vs. after the
#: object), not by the word.
PREPOSITIONS = frozenset({
    "about", "above", "across", "after", "against", "along", "alongside",
    "amid", "among", "amongst", "around", "as", "at", "atop", "before",
    "behind", "below", "beneath", "beside", "besides", "between", "beyond",
    "by", "concerning", "despite", "down", "during", "except", "for", "from",
    "in", "inside", "into", "like", "near", "notwithstanding", "of", "off",
    "on", "onto", "opposite", "out", "outside", "over", "past", "per",
    "regarding", "round", "since", "through", "throughout", "till", "to",
    "toward", "towards", "under", "underneath", "unlike", "until", "up",
    "upon", "versus", "via", "with", "within", "without"})
#: Personal pronouns -- a closed class that stands where a noun phrase stands,
#: so a sentence may open with one instead of "the NOUN".
PRONOUNS = frozenset({
    # personal, both cases
    "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them",
    # possessive, standing alone
    "mine", "yours", "his", "hers", "its", "ours", "theirs",
    # reflexive
    "myself", "yourself", "himself", "herself", "itself",
    "ourselves", "yourselves", "themselves",
    # demonstrative and indefinite, standing where a noun phrase stands
    "this", "that", "these", "those",
    "someone", "somebody", "something", "anyone", "anybody", "anything",
    "everyone", "everybody", "everything", "no one", "nobody", "nothing",
    "one", "none", "each", "either", "neither", "both", "all", "some", "any"})
#: Relative pronouns. One opens a CLAUSE INSIDE a noun phrase -- "the valve
#: WHICH leaked is closed" -- which no three-register reading can carry. Declared
#: here with the other closed classes because the machine had no name for them,
#: so `which` and `who` were content words free to be extended into a subject:
#: measured, the derived reading returned `valve_which_leaked_closed`.
RELATIVES = frozenset({"that", "which", "who", "whom", "whose"})
#: Quantifiers that are NOT the universals the reader represents (all/every/no).
#: "SOME metals rust" quantifies existentially and "MOST birds fly" proportionally;
#: neither is a claim about a named subject, and reading them as one produced
#: `some_metal_rust` -- a claim about a thing called "some metal".
QUANTIFIERS = frozenset({"some", "most", "many", "few", "several", "much"})
#: Modals. The reader carries no modality, so "a pump CAN fail" is not the claim
#: that a pump fails, and `valve_may_stick` asserted a relation nobody stated.
MODALS = frozenset({"can", "could", "may", "might", "must", "shall", "should",
                    "will", "would", "ought", "need", "dare"})
#: Past/passive auxiliaries. "the letter WAS WRITTEN BY alice" reverses subject
#: and object, and the reader has no voice, so it read `letter_was_written_by_alice`.
PASSIVE_AUXILIARIES = frozenset({"was", "were", "been", "being", "be"})
#: Coordinators. A sentence joined by one makes more than one claim; the reader
#: that handles that emits more than one reading (not yet -- see multi-emit).
CONJUNCTIONS = frozenset({"and", "or", "but", "nor", "yet", "so"})
#: Subordinators open a clause that DEPENDS on another ("the tank overflowed
#: BECAUSE the valve stuck"). They were absent, so the only conjunctions the
#: machine knew were the three coordinating ones and every subordinate clause
#: was content words.
SUBORDINATORS = frozenset({
    "because", "although", "though", "unless", "while", "whereas", "since",
    "if", "when", "whenever", "where", "wherever", "after", "before", "until",
    "once", "whether", "lest", "provided", "as"})
#: Auxiliary/do-support verbs that OPEN a question ("DOES a kestrel eat mice?")
#: or carry tense without being the relation. They are function words: the
#: relation is the main verb that follows, so the auxiliary is skipped.
AUXILIARIES = frozenset({"do", "does", "did",
                         # HAVE carries perfect tense and was missing, so "the
                         # pump HAS failed" had no auxiliary and `has` stood
                         # where the relation goes.
                         "have", "has", "had", "having"})
#: Wh-openers that ask for the OBJECT of a relation ("WHAT does a kestrel eat?").
#: The reading yields (subject, relation, <unknown>) -- the object is what is
#: being asked, which is exactly the fact a knowledge-gap check looks for.
WH_OBJECT_OPENERS = frozenset({"what", "which", "who", "whom"})


_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_']*")


def tokenize(sentence: str) -> List[str]:
    """Words, lowercased. No parsing: this decides where words END, nothing more."""
    return [w.lower().replace("'", "_") for w in _WORD.findall(sentence)]



#: A bare VERDICT on what was just said -- affirming or denying a PRIOR claim,
#: not asserting a new one. Closed-class and GIVEN, like PRONOUNS: this is the
#: primitive the conversation reads to tell "no, that's wrong" (a verdict on the
#: last turn) from "no man is an island" (a proposition about the world). It
#: carries polarity, never content.
VERDICT_AFFIRMS = frozenset({"yes", "yep", "yeah", "correct", "right",
                             "exactly", "true", "agreed", "affirmative"})
VERDICT_DENIES = frozenset({"no", "nope", "wrong", "incorrect", "false",
                            "untrue", "mistaken", "negative"})
#: Deictic subjects that point BACK at the thing just said rather than naming a
#: new one. Contractions tokenize with a trailing "_s" ("that's" -> "that_s").
DEICTIC = frozenset({"that", "it", "this", "that_s", "it_s", "this_s"})

#: "yes" and "no" are the one ambiguity: a verdict ("no, that's wrong") but also
#: an interjection or quantifier before a NEW subject ("no man is an island").
#: They are read as a verdict only standing alone or pointing back at the
#: exchange -- next to a referring word, never quantifying a fresh noun.
_AMBIGUOUS_LEAD = frozenset({"yes", "no"})
#: Words that point at the exchange or its speakers rather than name a new
#: subject -- what legitimately follows a leading "yes"/"no" verdict.
_REFERRING = DEICTIC | frozenset({"i", "you", "we", "they", "he", "she", "it"})


def evaluative_verdict(sentence: str) -> Optional[bool]:
    """Whether this utterance is a bare VERDICT on what was just said, and which
    way: True affirms it, False denies it, None is not a verdict (an ordinary
    proposition). Structural and model-free, like the question test -- it fires
    only on the recognised evaluative shapes (a leading verdict word, or a
    deictic subject followed by one), never because a larger claim merely
    contains "no" or "right" somewhere inside it. The CONTEXT that makes a
    verdict FEEDBACK -- that there is a prior claim to judge -- is the
    conversation's to supply; this only reads the shape."""
    words = tokenize(sentence)
    if not words:
        return None
    first = words[0]
    if first in _AMBIGUOUS_LEAD:
        # A response particle only when it stands alone or points back at the
        # exchange ("no", "no it isn't", "no, that's wrong") -- not when it
        # quantifies or addresses a new subject ("no man is an island").
        if len(words) == 1 or words[1] in _REFERRING \
                or words[1] in VERDICT_DENIES or words[1] in VERDICT_AFFIRMS:
            return first not in VERDICT_DENIES
        return None
    if first in VERDICT_DENIES:
        return False
    if first in VERDICT_AFFIRMS:
        return True
    if first in DEICTIC:
        for w in words[1:]:
            if w in VERDICT_DENIES:
                return False
            if w in VERDICT_AFFIRMS:
                return True
    return None


# ---- the pieces of a sentence ------------------------------------------------

class Piece(NamedTuple):
    """One piece of written text, and whether a space followed it."""

    text: str
    space_after: bool


#: Joins two letters or digits into one piece when it sits BETWEEN them:
#: `U.S`, `four-group`, `3.5`. At the edge of a word it is a mark of its own.
_JOINERS = frozenset(".-")

#: BETWEEN two letters, an apostrophe begins a piece of its own, glued to the
#: one before: `teacher's` is `teacher` + `'s`, `it's` is `it` + `'s`, `don't`
#: is `don` + `'t`. What those pieces mean is learned, like any other word's;
#: the writing only says where they join. At the edge of a word it is a mark.
_APOSTROPHES = frozenset("'\u2019")


def form_of(text: str) -> Tuple[Piece, ...]:
    """The pieces of `text`, in order, with nothing lost or changed."""
    pieces: List[Piece] = []
    text = str(text or "")
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        start = i
        joined = (ch in _APOSTROPHES and i > 0 and text[i - 1].isalnum()
                  and i + 1 < n and text[i + 1].isalnum())
        if ch.isalnum() or joined:
            i += 1
            while i < n:
                if text[i].isalnum():
                    i += 1
                elif (text[i] in _JOINERS and i + 1 < n and text[i + 1].isalnum()
                      and text[i - 1].isalnum()):
                    i += 1
                else:
                    break
        else:
            i += 1
        pieces.append(Piece(text[start:i], i < n and text[i].isspace()))
    return tuple(pieces)


def surface_of(pieces) -> str:
    """The text the pieces were split from: every piece as written, and one
    space wherever there was space between two pieces."""
    return "".join(p.text + (" " if p.space_after else "") for p in pieces).rstrip()



__all__ = ["Piece", "form_of", "surface_of", "tokenize",
           "COPULAS", "DETERMINERS", "NEGATORS", "SUBORDINATORS",
           "PREPOSITIONS", "PRONOUNS", "CONJUNCTIONS", "AUXILIARIES",
           "RELATIVES", "QUANTIFIERS", "MODALS", "PASSIVE_AUXILIARIES",
           "WH_OBJECT_OPENERS", "VERDICT_AFFIRMS", "VERDICT_DENIES", "DEICTIC",
           "evaluative_verdict"]
