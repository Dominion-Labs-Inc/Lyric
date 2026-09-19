#!/usr/bin/env python3
"""Concept correspondence is scored exactly, off stored vectors.

The scorer never reads a pair it can prove cannot pass, and rescored pairs are
exact. Each test compares it against the definition written out pair by pair:

    per text: absent on either side -> 0, identical key -> 1,
              otherwise cosine clamped to [0, 1]
    semantic = max(name, 0.3 name + 0.7 description)
    score    = round(min(0.6 semantic + min(1, semantic / 0.35) * structure, 1), 4)
    structure = 0.2 key-Jaccard + 0.1 type match + 0.1 (1 - |level difference|)

No model is loaded: vectors are synthetic unit vectors.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.domain.domain_types import (  # noqa: E402
    ConceptType, DomainConcept, semantic_floor)
from core.integration import universal_domain_master as udm  # noqa: E402

DIM = 8
TYPES = [ConceptType.ENTITY, ConceptType.PROCESS]
KEYSETS = [{}, {"relationships": [["isa", "x"]]}, {"source": 1, "relationships": 2}]
WORDS = ["pump", "heart", "valve", "  ", "", "Pump ", "pipe", "vessel"]


def _unit(rng):
    v = rng.standard_normal(DIM)
    return (v / np.linalg.norm(v)).astype(np.float32)


def _concepts(rng, prefix, n):
    concepts, vectors = [], {}
    for k in range(n):
        name = WORDS[rng.integers(len(WORDS))]
        desc = WORDS[rng.integers(len(WORDS))]
        c = DomainConcept(
            concept_id=f"{prefix}:{k}", name=name, domain_id=prefix,
            concept_type=TYPES[rng.integers(2)], description=desc,
            properties=dict(KEYSETS[rng.integers(3)]),
            abstraction_level=float(rng.choice([0.5, 0.2, 0.9])))
        concepts.append(c)
        vectors[c.concept_id] = (_unit(rng) if name.strip() else None,
                                 _unit(rng) if desc.strip() else None)
    return concepts, vectors


def _reference(a, b, va, vb):
    def text_sim(ta, tb, xa, xb):
        if not ta.strip() or not tb.strip():
            return 0.0
        if ta.strip().lower() == tb.strip().lower():
            return 1.0
        return max(0.0, min(1.0, float(np.dot(xa.astype(np.float64), xb.astype(np.float64)))))

    name = text_sim(a.name, b.name, va[0], vb[0])
    desc = text_sim(a.description, b.description, va[1], vb[1])
    semantic = max(name, 0.3 * name + 0.7 * desc)
    ka, kb = set(a.properties), set(b.properties)
    jaccard = len(ka & kb) / len(ka | kb) if ka and kb else 0.0
    structure = (0.2 * jaccard + 0.1 * (a.concept_type == b.concept_type)
                 + 0.1 * (1 - min(1.0, abs(a.abstraction_level - b.abstraction_level))))
    score = 0.6 * semantic + min(1.0, semantic / 0.35) * structure
    return float(np.round(min(score, 1.0), 4))


def _sides(src_concepts, tgt_concepts, vectors):
    store = udm._ConceptVectorStore()
    store.put([(c.concept_id, c.name, c.description, *vectors[c.concept_id])
               for c in src_concepts + tgt_concepts])

    def side(concepts):
        rows = np.array([store.index[c.concept_id] for c in concepts], dtype=np.int64)
        return udm._build_side(concepts, rows, store.names, store.descriptions,
                               store.name_keys, store.description_keys)
    return side(src_concepts), side(tgt_concepts)


@pytest.fixture
def small_blocks(monkeypatch):
    # Several blocks per side, so block boundaries and the rising floor are exercised.
    monkeypatch.setattr(udm, "_BLOCK_ELEMENTS", 64)


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("threshold", [0.3, 0.5, 0.6])
def test_scores_match_the_definition_pair_by_pair(small_blocks, seed, threshold):
    rng = np.random.default_rng(seed)
    src_concepts, src_vectors = _concepts(rng, "s", 37)
    tgt_concepts, tgt_vectors = _concepts(rng, "t", 29)
    vectors = {**src_vectors, **tgt_vectors}
    src, tgt = _sides(src_concepts, tgt_concepts, vectors)

    reference = [(_reference(a, b, vectors[a.concept_id], vectors[b.concept_id]), i, j)
                 for i, a in enumerate(src_concepts) for j, b in enumerate(tgt_concepts)]
    passing = [r for r in reference if r[0] > threshold]
    # strongest first, ties in source-then-target order
    expected = [(s, src_concepts[i].concept_id, tgt_concepts[j].concept_id)
                for s, i, j in sorted(passing, key=lambda r: (-r[0], r[1], r[2]))[:7]]

    top = udm._score_correspondence(src, tgt, threshold, 7, False)
    assert top["strongest"] == expected

    counted = udm._score_correspondence(src, tgt, threshold, 7, True)
    assert counted["strongest"] == expected
    assert counted["pairs"] == len(passing)
    assert counted["total"] == pytest.approx(sum(r[0] for r in passing), abs=1e-9)


def test_identical_text_scores_one_and_absent_text_scores_zero():
    rng = np.random.default_rng(0)
    a = DomainConcept(concept_id="a", name="Heart ", domain_id="s",
                      concept_type=ConceptType.ENTITY, description="")
    b = DomainConcept(concept_id="b", name="heart", domain_id="t",
                      concept_type=ConceptType.ENTITY, description="")
    vectors = {"a": (_unit(rng), None), "b": (-_unit(rng), None)}
    src, tgt = _sides([a], [b], vectors)
    found = udm._score_correspondence(src, tgt, 0.0, 1, True)
    # name identical -> 1 despite opposed vectors; no descriptions -> 0;
    # semantic 1, structure 0 + 0.1 type + 0.1 level -> 0.6 + 0.2
    assert found["strongest"] == [(_reference(a, b, vectors["a"], vectors["b"]), "a", "b")]
    assert found["strongest"][0][0] == 0.8


def test_ties_keep_source_then_target_order(small_blocks):
    rng = np.random.default_rng(1)
    shared = _unit(rng)
    src_concepts = [DomainConcept(concept_id=f"s{k}", name=f"n{k}", domain_id="s",
                                  concept_type=ConceptType.ENTITY, description="d")
                    for k in range(12)]
    tgt_concepts = [DomainConcept(concept_id=f"t{k}", name=f"m{k}", domain_id="t",
                                  concept_type=ConceptType.ENTITY, description="d")
                    for k in range(9)]
    vectors = {c.concept_id: (shared, shared) for c in src_concepts + tgt_concepts}
    src, tgt = _sides(src_concepts, tgt_concepts, vectors)
    found = udm._score_correspondence(src, tgt, 0.5, 5, False)
    assert [(s, t) for _, s, t in found["strongest"]] == [
        ("s0", "t0"), ("s0", "t1"), ("s0", "t2"), ("s0", "t3"), ("s0", "t4")]


def test_the_floor_never_excludes_a_passing_pair():
    rng = np.random.default_rng(2)
    for _ in range(20000):
        semantic, structure = rng.random(), rng.random() * 0.4
        threshold = rng.random()
        score = 0.6 * semantic + min(1.0, semantic / 0.35) * structure
        if round(min(score, 1.0), 4) > threshold:
            assert semantic > semantic_floor(threshold, structure) - 1e-12


def test_a_vector_that_disagrees_with_its_text_is_refused():
    store = udm._ConceptVectorStore()
    with pytest.raises(ValueError):
        store.put([("c", "pump", "", None, None)])
    with pytest.raises(ValueError):
        store.put([("c", "", "", np.ones(DIM, dtype=np.float32), None)])



# ------------------------------------------------------ incremental updates

def _state_sides(src_items, tgt_items):
    """Sides for ordered (concept, vectors) lists, as a registry holds them."""
    store = udm._ConceptVectorStore()
    store.put([(c.concept_id, c.name, c.description, *v) for c, v in src_items + tgt_items])

    def side(items):
        concepts = [c for c, _v in items]
        rows = np.array([store.index[c.concept_id] for c in concepts], dtype=np.int64)
        return udm._build_side(concepts, rows, store.names, store.descriptions,
                               store.name_keys, store.description_keys)
    return side(src_items), side(tgt_items)


def _fresh(rng, prefix, serial):
    concepts, vectors = _concepts(rng, prefix, 1)
    concept = concepts[0]
    concept.concept_id = f"{prefix}:{serial}"
    return concept, vectors[f"{prefix}:0"]


def _mutate(rng, items, prefix, serial):
    """One registry change: a concept joins, leaves, or is rewritten (and so
    re-registered at the end). Returns the changed concept id."""
    action = rng.integers(3) if len(items) > 3 else 0
    if action == 0:
        concept, vectors = _fresh(rng, prefix, serial)
        items.append((concept, vectors))
        return concept.concept_id
    position = int(rng.integers(len(items)))
    concept, _vectors = items.pop(position)
    if action == 1:
        return concept.concept_id
    rewritten, vectors = _fresh(rng, prefix, serial)
    rewritten.concept_id = concept.concept_id
    items.append((rewritten, vectors))
    return concept.concept_id


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("count_all", [False, True])
def test_updating_for_changed_concepts_equals_scoring_again(small_blocks, seed, count_all):
    rng = np.random.default_rng(100 + seed)
    threshold, keep = 0.45, 4
    depth = keep * 4
    src_concepts, src_vec = _concepts(rng, "s", 30)
    tgt_concepts, tgt_vec = _concepts(rng, "t", 25)
    src_items = [(c, src_vec[c.concept_id]) for c in src_concepts]
    tgt_items = [(c, tgt_vec[c.concept_id]) for c in tgt_concepts]
    src, tgt = _state_sides(src_items, tgt_items)
    prev = udm._score_correspondence(src, tgt, threshold, depth, count_all)
    updated = 0
    for step in range(25):
        changed_src, changed_tgt = set(), set()
        side_choice = rng.integers(3)
        if side_choice in (0, 2):
            changed_src.add(_mutate(rng, src_items, "s", 1000 + step))
        if side_choice in (1, 2):
            changed_tgt.add(_mutate(rng, tgt_items, "t", 1000 + step))
        src, tgt = _state_sides(src_items, tgt_items)
        full = udm._score_correspondence(src, tgt, threshold, depth, count_all)
        result = udm._update_correspondence(
            prev, src, tgt, changed_src, changed_tgt, threshold, depth, count_all)
        if result is not None and (result["complete"] or len(result["strongest"]) >= keep):
            updated += 1
            assert result["strongest"][:keep] == full["strongest"][:keep]
            if result["complete"]:
                assert result["strongest"] == full["strongest"]
            if count_all:
                assert result["pairs"] == full["pairs"]
                assert result["total"] == pytest.approx(full["total"], abs=1e-9)
            prev = result
        else:
            prev = full
    assert updated, "no change was ever applied incrementally"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
