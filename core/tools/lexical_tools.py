#!/usr/bin/env python3
"""Lexical lookup — a model-free, offline source of structured 'kind-of' facts.

The substrate can research prose (conduct_research), but prose is something it
can only echo back, not REASON over. To close a declarative gap in a way that
feeds the concept graph, it needs the fact as a STRUCTURED relation: `robin ISA
thrush`, `thrush ISA bird`, and so on. This tool provides exactly that — the
kind-of (hypernym) chain for a term, read from the WordNet lexical database.

It is model-free (a database lookup, no language model), offline (no network,
so it is reproducible and rate-limit-free), and it returns ORDERED edges so the
caller can admit each one and the reasoner can then traverse the chain
transitively (robin -> ... -> animal). WordNet is used here ONLY as a lookup
source the substrate consults through a tool — it is not part of how the
substrate reads sentences.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety

logger = logging.getLogger(__name__)


def _isa_chain(term: str, max_hops: int) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """The ordered kind-of edges for a term, from WordNet hypernyms.

    Returns (edges, gloss). `edges` is [(child, parent), ...] starting at the
    term itself and walking up its first-sense hypernym line; `gloss` is the
    term's definition (for the human-facing 'I looked it up' reply). Empty edges
    means the term is not in the lexicon — an honest gap, never a guess.
    """
    from nltk.corpus import wordnet as wn

    synsets = wn.synsets(term.replace(" ", "_"), pos=wn.NOUN)
    if not synsets:
        return [], None
    sense = synsets[0]
    gloss = sense.definition()

    edges: List[Tuple[str, str]] = []
    child_label = term
    current = sense
    for _ in range(max_hops):
        hypernyms = current.hypernyms()
        if not hypernyms:
            break
        parent = hypernyms[0]
        parent_label = parent.lemmas()[0].name().replace("_", " ")
        edges.append((child_label, parent_label))
        child_label = parent_label
        current = parent
    return edges, gloss


class LexicalLookupTool(Tool):
    """Fetch the structured kind-of (ISA) chain for a term, model-free & offline."""

    def __init__(self):
        self.name = "lexical_lookup"
        self.description = (
            "Look up the kind-of (ISA) chain for a term from the WordNet lexical "
            "database — structured, model-free, offline. Returns ordered "
            "(child, parent) edges the substrate can admit as relations and then "
            "reason over.")
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(name="term", type="string",
                          description="The word or phrase to look up", required=True),
            ToolParameter(name="max_hops", type="integer",
                          description="How far up the kind-of chain to walk",
                          required=False, default=10),
        ]
        super().__init__()
        # Read-only lookup, no side effects.
        self.consequence = ("read", "none")

    async def execute(self, term: str, max_hops: int = 10) -> ToolResult:
        term = (term or "").strip()
        if not term:
            return ToolResult(success=False, output=None,
                              error="lexical_lookup: no term given")
        try:
            edges, gloss = _isa_chain(term, int(max_hops))
        except Exception as error:  # WordNet corpus missing, etc. — honest failure.
            logger.warning("lexical_lookup failed for %r: %s", term, error)
            return ToolResult(success=False, output=None,
                              error=f"lexical_lookup unavailable: {error}")
        if not edges:
            return ToolResult(
                success=False,
                output={"term": term, "isa_chain": [], "gloss": None},
                error=f"'{term}' is not in the lexicon — no kind-of chain to give")
        return ToolResult(
            success=True,
            output={"term": term,
                    "isa_chain": [[child, parent] for child, parent in edges],
                    "gloss": gloss},
            metadata={"source": "wordnet", "model_free": True, "hops": len(edges)})
