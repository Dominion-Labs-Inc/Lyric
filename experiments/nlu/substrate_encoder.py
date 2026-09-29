#!/usr/bin/env python3
"""A representation built ONLY from what the substrate was taught.

The question this exists to answer: the substrate holds a pretrained
sentence-transformer (all-MiniLM-L6-v2) for memory retrieval, dedup/merge,
concept vectors and analogy. Those are the last jobs in the system done by a
model. Can the substrate's own taught knowledge do them?

A term's meaning here is THE COMPANY IT KEEPS IN WHAT IT WAS TAUGHT: the terms
that co-occurred with it in a proposition the substrate actually admitted. No
pretrained weights, no subword tables, nothing imported.

ABSTENTION IS PART OF THE CONTRACT, not a refinement of it. An earlier version
encoded a sentence full of words it had never been taught as a vector of the
FUNCTION words alone, so two claims about different unknown things came back at
cosine 1.000 -- confident identity between two things it knew nothing about.
That is the false-positive this substrate's rules forbid, and it is worse than
being wrong: a merge would have destroyed one of the two memories. `encode`
returns None when it holds no content term for a text, and `similarity` returns
None when either side abstains. "I cannot judge this" is an answer.
"""
from __future__ import annotations

import collections
import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

#: Words that carry grammar rather than subject matter. A vector built out of
#: these says only that both texts are English.
#:
#: NEGATORS ARE NOT HERE, AND THE OMISSION IS THE POINT. `not` is grammar, but
#: it is grammar that CHANGES THE CLAIM. Stripping it as a function word made
#: "the vault is locked" and "the vault is NOT locked" identical -- cosine
#: 1.000, above the merge bar, on the write path. This substrate already
#: measured why that matters: a statement and its denial score 0.948 to a
#: pretrained encoder, "no threshold recovers polarity, and a bigger model makes
#: it worse", which is why `claim_shape` exists at all.
_FUNCTION = frozenset({
    "a", "an", "the", "is", "are", "am", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "by", "for", "with", "from", "into", "as",
    "and", "or", "but", "that", "which", "who", "this", "these", "those",
    "it", "its", "their", "his", "her", "any", "some", "all", "what", "does",
    "do", "did", "has", "have", "had", "can", "may", "will", "would", "there",
})

#: A denial is not a weak version of the claim, so polarity is not a token to be
#: outweighed by the rest of the sentence. It is read as STRUCTURE and compared
#: before any vector is: two texts that disagree in polarity are not similar at
#: any cosine.
_NEGATORS = frozenset({"not", "never", "no", "nor", "n't", "cannot"})


def tokens(text: str) -> List[str]:
    return re.findall(r"[a-z']+", str(text or "").lower())


class SubstrateEncoder:
    """Representation derived from taught propositions. No pretrained weights."""

    #: How much a term's NEIGHBOURS contribute relative to the term itself.
    #: Below 1 because what a word was taught alongside is weaker evidence of
    #: meaning than the word being present.
    NEIGHBOUR_WEIGHT = 0.35

    def __init__(self) -> None:
        self.assoc: Dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter)
        self.vocab: set = set()
        self.df: collections.Counter = collections.Counter()
        self.documents = 0
        self.idf: Dict[str, float] = {}

    def learn(self, readings: Sequence[Tuple[str, str, str]]) -> None:
        """Every taught proposition is one context. Terms that appear together
        in one are taught about each other."""
        for reading in readings:
            terms = [w for part in reading if part for w in tokens(part)]
            if not terms:
                continue
            self.vocab.update(terms)
            self.documents += 1
            for term in set(terms):
                self.df[term] += 1
            for a in terms:
                for b in terms:
                    if a != b:
                        self.assoc[a][b] += 1

    def finalise(self) -> None:
        """Inverse-frequency weights. A term taught about everything carries
        almost no information about any one thing."""
        n = max(1, self.documents)
        self.idf = {t: math.log(n / (1 + self.df[t])) + 1e-6 for t in self.vocab}

    def content_terms(self, text: str) -> List[str]:
        """The terms in `text` this encoder has actually been taught, grammar
        excluded. Empty means it has no representation for this text."""
        return [w for w in tokens(text)
                if w in self.vocab and w not in _FUNCTION]

    def encode(self, text: str) -> Optional[collections.Counter]:
        """The taught terms this text mentions, plus what those terms were
        taught alongside at lower weight. None when it holds no content term --
        an honest gap, never a vector of function words."""
        content = self.content_terms(text)
        if not content:
            return None
        vector: collections.Counter = collections.Counter()
        for word in content:
            weight = self.idf.get(word, 0.0)
            vector[word] += weight
            neighbours = self.assoc[word]
            total = sum(neighbours.values()) or 1
            for neighbour, count in neighbours.items():
                if neighbour in _FUNCTION:
                    continue          # grammar is not what a word means
                vector[neighbour] += (self.NEIGHBOUR_WEIGHT * weight
                                      * (count / total)
                                      * self.idf.get(neighbour, 0.0))
        return vector or None

    @staticmethod
    def polarity(text: str) -> bool:
        """True when the text AFFIRMS. Read structurally, never from a vector."""
        return not any(w in _NEGATORS for w in tokens(text))

    def similarity(self, left: str, right: str) -> Optional[float]:
        """Cosine, or None where either side has no representation.

        POLARITY DECIDES FIRST. A claim and its denial are about the same
        subject in the same words, so every distributional signal says they are
        the same thing -- which is exactly the error that must not reach a merge.
        """
        if self.polarity(left) != self.polarity(right):
            if self.encode(left) is None and self.encode(right) is None:
                return None       # still nothing to judge; abstain honestly
            return 0.0            # they disagree; that is not a near-match
        a, b = self.encode(left), self.encode(right)
        if a is None or b is None:
            return None
        shared = set(a) & set(b)
        if not shared:
            return 0.0
        dot = sum(a[k] * b[k] for k in shared)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0


async def taught_readings(limit: int = 40000) -> List[Tuple[str, str, str]]:
    """Every proposition the substrate has been taught, as (subject, relation,
    object). Read from MEMORY, which is the only store."""
    from core.database.unified_database_postgres import LyricUnifiedDatabasePostgres
    db = LyricUnifiedDatabasePostgres()
    await db.initialize()
    rows = await db.query(
        "SELECT metadata->>'reading' AS reading FROM memory_hot.memory_hot "
        "WHERE tags @> '[\"admitted_proposition\"]'::jsonb "
        f"AND metadata->>'reading' IS NOT NULL LIMIT {int(limit)}")
    out = []
    for row in rows:
        parts = [p.strip() for p in str(row["reading"]).split("|")]
        if len(parts) >= 2:
            out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return out
