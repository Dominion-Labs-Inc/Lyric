#!/usr/bin/env python3
"""What the substrate knows about individual words, and how it came to know it.

Before this there was nowhere to put a word class. The reader held three closed
function-word sets -- {a, an, the}, {is, are}, {not} -- and every other word was
undifferentiated CONTENT, so "the cold is heavy" and "the tank is heavy" were
indistinguishable and no amount of teaching could show up anywhere.

    A CLASS IS A CLAIM, AND A CLAIM NEEDS A SOURCE.

Every entry records where it came from. A class PROPOSED by a teacher is a
candidate and reads as one; it becomes CONFIRMED only when a sentence that
depends on it actually reads. That is the same rule the rest of the substrate
uses: a model may propose, the world attests.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

logger = logging.getLogger(__name__)

NOUN, ADJECTIVE, VERB = "NOUN", "ADJECTIVE", "VERB"
CLASSES = (NOUN, ADJECTIVE, VERB)

PROPOSED = "proposed"      # a teacher said so; no evidence yet
CONFIRMED = "confirmed"    # a sentence depending on it read successfully
REFUTED = "refuted"        # a sentence depending on it failed to read


@dataclass
class Entry:
    """One word, its class, and the standing of that claim."""

    word: str
    word_class: str
    status: str = PROPOSED
    source: str = ""
    confirmations: int = 0
    contradictions: int = 0
    evidence: list = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether reading may rely on it.

        A proposal is usable -- otherwise nothing could ever be tested and no
        evidence could ever arrive -- but it is never reported as confirmed.
        A refuted entry is not usable: it was tried and the world disagreed.
        """
        return self.status != REFUTED


class Lexicon:
    """The word store. Small, inspectable, and persisted as plain JSON."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else (
            Path(__file__).resolve().parents[2] / "data" / "lexicon.json")
        self._entries: Dict[str, Entry] = {}
        self.load()

    # ── reading ─────────────────────────────────────────────────────────────
    def class_of(self, word: str) -> Optional[str]:
        entry = self._entries.get(word.lower())
        return entry.word_class if entry and entry.usable else None

    def entry(self, word: str) -> Optional[Entry]:
        return self._entries.get(word.lower())

    def words_of_class(self, word_class: str) -> Set[str]:
        return {w for w, e in self._entries.items()
                if e.word_class == word_class and e.usable}

    def known(self) -> Iterable[Entry]:
        return list(self._entries.values())

    # ── writing ─────────────────────────────────────────────────────────────
    def propose(self, word: str, word_class: str, source: str) -> Entry:
        """Record a claim. Proposing does not make it true."""
        if word_class not in CLASSES:
            raise ValueError(f"unknown word class {word_class!r}; expected {CLASSES}")
        key = word.lower()
        existing = self._entries.get(key)
        if existing and existing.word_class != word_class:
            # A second, different proposal does not overwrite the first: two
            # sources disagreeing is information, and silently taking the later
            # one would erase it.
            existing.contradictions += 1
            existing.evidence.append(f"conflicting proposal {word_class} from {source}")
            return existing
        entry = existing or Entry(word=key, word_class=word_class, source=source)
        self._entries[key] = entry
        return entry

    def confirm(self, word: str, evidence: str) -> None:
        entry = self._entries.get(word.lower())
        if not entry:
            return
        entry.confirmations += 1
        entry.status = CONFIRMED
        entry.evidence.append(f"confirmed: {evidence}")

    def refute(self, word: str, evidence: str) -> None:
        entry = self._entries.get(word.lower())
        if not entry:
            return
        entry.contradictions += 1
        entry.evidence.append(f"contradicted: {evidence}")
        # One contradiction does not refute a claim with standing behind it.
        if entry.contradictions > entry.confirmations:
            entry.status = REFUTED

    # ── persistence ─────────────────────────────────────────────────────────
    def load(self) -> int:
        if not self.path.exists():
            return 0
        try:
            blob = json.loads(self.path.read_text())
        except Exception as error:
            logger.warning("lexicon unreadable (%s); starting empty", error)
            return 0
        self._entries = {w: Entry(**e) for w, e in blob.items()}
        return len(self._entries)

    def save(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {w: e.__dict__ for w, e in self._entries.items()}, indent=2))
        return len(self._entries)

    def clear(self) -> None:
        self._entries = {}


_lexicon: Optional[Lexicon] = None


def get_lexicon() -> Lexicon:
    global _lexicon
    if _lexicon is None:
        _lexicon = Lexicon()
    return _lexicon


#: A copular complement's word class is decided by its DETERMINER: "a device" is
#: a kind (NOUN), "red" with no article is a property (ADJECTIVE). Only the
#: relations that copular readings produce use this rule; every other relation
#: takes a thing (NOUN) as its object.
_ARTICLES = ("a", "an", "the")
#: Both the surface copula (from a clause's parts: "is"/"are") and the typed
#: relations a copular reading crystallizes into — either way, the determiner
#: decides kind vs property.
_COPULAR_TYPES = frozenset({"is", "are", "be", "isa", "is_a",
                            "instance_of", "has_property", "member_of"})


def _single_token(term: str) -> Optional[str]:
    """The lexical head to record a class for, or None when the term is not a
    single word — a compound ("external_source") is not one part of speech, so
    recording a class for it would be a guess."""
    head = str(term or "").strip().lower()
    return head if head.isalpha() else None


def _has_article(sentence: str, word: str) -> bool:
    """Whether `word` appears in the surface right after a/an/the — the signal
    that a copular complement names a kind rather than a property."""
    import re
    toks = re.findall(r"[\w'-]+", str(sentence).lower())
    head = str(word or "").split("_")[0].lower()
    return any(t == head and i and toks[i - 1] in _ARTICLES
               for i, t in enumerate(toks))


def observe_proposition(sentence: str, subject: str, relation: str, obj: str,
                        *, source: str = "taught") -> int:
    """Record the word classes a read proposition IMPLIES, so teaching a fact
    also teaches the reader the parts of speech it needs to read the next
    sentence.

    This is the write side the lexicon was built for and never had a caller:
    `propose`/`confirm` existed, nothing fed them, so teaching nine words left
    every unseen word unreadable however many facts were taught. The subject of
    a predication is a thing (NOUN); a copular complement behind an article is a
    kind (NOUN) and one without is a property (ADJECTIVE); the object of any
    other relation is a thing (NOUN). These are PROPOSALS — a later sentence that
    depends on one confirms it, one that fails refutes it — so a wrong guess is
    correctable, not cemented. Returns how many were recorded."""
    lex = get_lexicon()
    proposed = 0

    def _record(term: str, word_class: str) -> None:
        nonlocal proposed
        head = _single_token(term)
        if head:
            lex.propose(head, word_class, source)
            proposed += 1

    _record(subject, NOUN)
    if obj:
        rel = str(relation).strip().lower().replace(" ", "_")
        if rel in _COPULAR_TYPES:
            _record(obj, NOUN if _has_article(sentence, obj) else ADJECTIVE)
        else:
            _record(obj, NOUN)

    if proposed:
        lex.save()
    return proposed
