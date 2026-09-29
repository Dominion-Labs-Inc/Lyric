#!/usr/bin/env python3
"""Oracles for the semantic-extraction typed contract.

  CONTRACT  the typed result cannot express a self-contradictory state

The LLM `SemanticExtractor` was retired on 2026-08-28: concept extraction is
substrate-first now (the deterministic `ConceptExtractor` is the sole production
writer — see tests/test_e2e and `concept_ingestion.ConceptExtractor`). What
survives here is the model-neutral typed contract (`ExtractionResult`).

THE EXTRACTION-MODE TEST IS GONE, and so is its subject. It pinned a chat-template
flag on `core.services.unified_llm`, guarding "the one remaining model consumer,
in the teacher" -- and that module, the teacher, and `TeacherPolicy` were all
deleted on 2026-09-13 when the substrate became model-free by construction. The
test had raised ModuleNotFoundError on every run since. There is no model
consumer left to bound, so the guard is not restored, it is retired.
"""

import pytest


# ---------------------------------------------------------------- contract

def test_result_cannot_express_a_contradictory_state():
    from core.domain.semantic_extraction import (
        ExtractionExecutionStatus as S, ExtractionSemanticOutcome as O,
        ExtractionResult)

    base = dict(evidence_id="e", extractor_id="x", extractor_version="1")

    # A failure that claims to have observed something.
    with pytest.raises(ValueError):
        ExtractionResult(execution_status=S.TIMEOUT,
                         semantic_outcome=O.NO_CONCEPTS, **base)

    # "Found concepts" with none.
    with pytest.raises(ValueError):
        ExtractionResult(execution_status=S.SUCCESS,
                         semantic_outcome=O.CONCEPTS_FOUND, **base)

    # A legitimate negative IS representable, and is distinguishable from failure.
    ok = ExtractionResult(execution_status=S.SUCCESS,
                          semantic_outcome=O.NO_CONCEPTS, **base)
    assert ok.observed_absence is True

    broke = ExtractionResult(execution_status=S.EMPTY_CONTENT,
                             semantic_outcome=O.UNKNOWN, **base)
    assert broke.observed_absence is False, (
        "an extractor that never produced output must not read as evidence that "
        "the text contained no concepts")
    assert broke.is_retryable is True


def test_no_concepts_is_never_retried():
    """Retrying until concepts appear is sampling, not retry."""
    from core.domain.semantic_extraction import (
        ExtractionExecutionStatus as S, ExtractionSemanticOutcome as O,
        ExtractionResult, RETRYABLE)

    assert S.SUCCESS not in RETRYABLE
    r = ExtractionResult(execution_status=S.SUCCESS, semantic_outcome=O.NO_CONCEPTS,
                         evidence_id="e", extractor_id="x", extractor_version="1")
    assert r.is_retryable is False
