#!/usr/bin/env python3
"""Oracles for the task-outcome -> domain-knowledge chain (Priority 4).

Every component of this chain existed and none of them were joined:

  producer  AutonomousCoordinator._store_task_outcome_meta_memory writes a
            TaskOutcomeRecord as a META memory tagged "task_outcome", with the
            knowledge domain from knowledge_domain_of (the declared domain;
            none otherwise)
  bridge    DomainRegistry.resolve_domain_reference turns that reference (a
            field, or a category) into the populated FIELDS it names
  consumer  UnifiedLearningSystem.learn_with_domain_context, the only method
            that puts a domain onto learn_from_example
  tier      _idle_domain_expansion_work, documented at TORINAI_REFERENCE.md:3114
            and never registered

Four defects found while joining them are locked here. Each returned a
plausible value while doing nothing, which is why none of them surfaced:

  1. `metadata = metadata || $1::jsonb` on a NULL column yields NULL. The row
     updated, so rows_affected was 1 and update_memory returned True while
     storing nothing.
  2. learn_with_domain_context returned learn_from_example's CREDIT flag as its
     own `success`, so an outcome that was learned from -- cross-domain transfer
     included -- came back success=False with no error and no error_class.
  3. The structured record lives in thinking_state["raw_event"]; `content` is a
     rendered narrative. Reading `content` yields prose and every field of the
     TaskOutcomeRecord reads as absent.
  4. 15 of 18 populated fields were absent from _FIELD_TO_DOMAIN_TYPE and fell
     to the ABSTRACT fallback, so the producer's categories resolved past the
     concepts they should have found.

test_chain_end_to_end is the oracle that matters: the five component tests can
all pass while the chain remains broken at a joint none of them crosses.
"""

import asyncio
from pathlib import Path

import pytest

TAG = "task_outcome"
MARK = "domain_expanded_at"


def _load_env():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.production", override=True)


#: The field these oracles act in. A task declares it; nothing infers it.
FIELD = "fluid_mechanics"


async def _field_is_held():
    """THE DOMAIN IS TAUGHT, NOT ASSUMED. The chain runs through a field that
    holds learned concepts, and a store that was never taught one -- the sandbox
    after a reset, a model wiped for teaching -- has none to run through: every
    oracle below then fails as though the chain were broken. Taught here through
    the one learning path, into the sandbox the suite runs in, and only when the
    field holds nothing yet."""
    from core.domain.domain_registry import DomainRegistry, UnresolvedDomainReference
    from core.learning.unified_learning_system import get_learning_authority

    registry = DomainRegistry()
    await registry.initialize()
    try:
        if registry.resolve_domain_reference(FIELD, require_concepts=True):
            return
    except UnresolvedDomainReference:
        pass
    admission = await get_learning_authority().learn_fact(
        "pressure loss", "caused_by", "pipe friction", domain=FIELD,
        description="the drop in pressure as a fluid flows through a pipe or a fitting")
    assert admission.admitted, admission.refusals


#: The analogy the transfer oracles run through. In both fields the concept is
#: caused by pipe friction and reduces flow rate: the same relation to the same
#: concept, which is what the validator accepts -- never a likeness of names.
ANALOGY = (("clogged pipe", "caused_by", "pipe friction", "plumbing"),
           ("clogged pipe", "reduces", "flow rate", "plumbing"),
           ("pressure loss", "caused_by", "pipe friction", FIELD),
           ("pressure loss", "reduces", "flow rate", FIELD))


async def _analogy_is_held():
    """THE ANALOGY IS TAUGHT, NOT ASSUMED. A transfer needs two fields whose
    concepts share structure; a store never taught them has no mapping to
    validate, and the oracles would have nothing to apply. Each fact is taught
    through the one learning path, into the sandbox the suite runs in, only when
    it is not already held."""
    from core.database import get_database_manager
    from core.learning.unified_learning_system import get_learning_authority

    db = get_database_manager()
    for subject, relation, obj, field in ANALOGY:
        held = await db.execute_query(
            "SELECT 1 FROM unified.concept_relations cr "
            "JOIN unified.concepts c ON c.concept_id = cr.source_concept_id "
            "WHERE c.name = $1 AND c.domain = $2 AND cr.relation = $3 "
            "AND cr.target_surface = $4 LIMIT 1",
            (subject.replace(" ", "_"), field, relation.replace("_", " "),
             obj.replace(" ", "_")), fetch_all=True)
        if held:
            continue
        admission = await get_learning_authority().learn_fact(
            subject, relation, obj, domain=field)
        assert admission.admitted, admission.refusals


async def _storage():
    from core.agents.memory_agent import get_memory_agent
    agent = await get_memory_agent()
    # get_memory_agent() returns an UNINITIALIZED agent by its own docstring;
    # postgres_storage is None until initialize() runs.
    await agent.initialize()
    assert agent.postgres_storage is not None, "memory agent exposes no storage"
    return agent.postgres_storage


async def _coordinator():
    """A coordinator carrying only what this chain needs, wired to the real systems."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.memory_agent import get_memory_agent
    from core.learning.unified_learning_system import get_learning_authority

    coord = AutonomousCoordinator.__new__(AutonomousCoordinator)
    coord.config = {}
    coord.memory = await get_memory_agent()
    await coord.memory.initialize()
    # ONE learning attribute now: `coord.learning` (the coordinator's methods
    # read self.learning; `unified_learning` was a second name for the same
    # singleton and is gone). get_learning_authority() == get_unified_learning_system().
    coord.learning = get_learning_authority()
    await coord.learning.start()
    # Domain expansion is woken by the outcome it reads: a stored outcome sets
    # this flag and starts the single-flight drain.
    coord._domain_expansion_dirty = False
    coord._domain_expansion_drain_task = None
    return coord


async def _reader_woken_by(coord):
    """Run to its end the reader a stored outcome woke. Expansion is event-driven:
    storing an outcome starts the drain, and a pass run beside it would race it
    for the same outcomes and the same status."""
    drain = coord._domain_expansion_drain_task
    assert drain is not None, "the stored outcome woke no reader"
    await asyncio.wait_for(drain, timeout=120)


def _task(description, task_type="analysis", task_id="oracle_task", domain_id=None):
    from types import SimpleNamespace
    return SimpleNamespace(
        id=task_id,
        description=description,
        type=SimpleNamespace(value=task_type),
        source=SimpleNamespace(value="autonomous"),
        metadata={"domain_id": domain_id} if domain_id else {},
        provenance=None,
    )


# ---------------------------------------------------------------- component 1

@pytest.mark.asyncio
async def test_metadata_merge_is_a_merge_and_survives_a_null_column():
    """Both halves of `COALESCE(metadata,'{}') || $1`: NULL-safe AND merging."""
    _load_env()
    from core.database import get_database_manager
    from core.memory.utils.interfaces import MemoryItem, MemoryType

    storage = await _storage()
    db = get_database_manager()
    mid = "test_merge_semantics"

    await storage.store_memory(MemoryItem(
        memory_id=mid, memory_type=MemoryType.META,
        content={"event": "test", "purpose": "metadata merge oracle"},
        tags={"test_merge_oracle"}))

    async def metadata():
        rows = await db.execute_query(
            "SELECT metadata FROM memory_hot.memory_hot WHERE memory_id = $1",
            (mid,), fetch_all=True)
        import json
        raw = rows[0]["metadata"]
        return json.loads(raw) if isinstance(raw, str) else raw

    try:
        # (a) NULL column. `NULL || jsonb` is NULL, and UPDATE still reports one
        # row affected -- so the write returns True and stores nothing.
        await db.execute_query(
            "UPDATE memory_hot.memory_hot SET metadata = NULL WHERE memory_id = $1",
            (mid,), commit=True)
        assert await storage.update_memory(
            mid, {"metadata": {"first": "a"}, "metadata.merge": True}) is True
        stored = await metadata()
        assert isinstance(stored, dict), f"metadata is {type(stored).__name__}, not an object"
        assert stored.get("first") == "a", (
            f"merge into a NULL metadata column stored {stored!r} while "
            f"update_memory returned True; anything using this to mark an item "
            f"processed will reprocess it forever")

        # (b) MERGE, not replace. A marker written over existing metadata must
        # not discard what was already there.
        assert await storage.update_memory(
            mid, {"metadata": {"second": "b"}, "metadata.merge": True}) is True
        stored = await metadata()
        assert stored == {"first": "a", "second": "b"}, (
            f"expected a merge, got {stored!r}; the pre-existing key was "
            f"discarded, so marking an item processed would erase its other "
            f"metadata")
    finally:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE memory_id = $1", (mid,), commit=True)


# ---------------------------------------------------------------- component 2

@pytest.mark.asyncio
async def test_learning_recorded_and_credit_earned_are_separately_representable():
    """The interface must express (recorded=True, credit=False)."""
    _load_env()
    from core.learning.unified_learning_system import get_unified_learning_system
    from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
    from core.learning.learning_interfaces import LearningExample

    learning = get_unified_learning_system()
    await learning.start()
    await _field_is_held()

    # A domain known to hold learned concepts, and an example that states no
    # accuracy -- so the strategy cannot earn credit while the example is still
    # learned from. This is precisely the state the old interface collapsed.
    result = await learning.learn_with_domain_context(
        LearningExample(
            example_id="test_recorded_vs_credit",
            actor=SUBSTRATE_ACTOR,
            inputs={"task_description": "verify pressure loss across a fitting"},
            domain=FIELD,
        ),
        FIELD,
    )
    meta = result.metadata or {}

    assert "learning_recorded" in meta, (
        "learn_with_domain_context does not report whether the example was "
        "learned from; without it a caller can only read `success`, which used "
        "to carry the credit flag")
    assert "strategy_earned_credit" in meta, (
        "credit must be reported separately from whether the example was "
        "learned from")
    assert result.success is meta["learning_recorded"], (
        f"success={result.success!r} but learning_recorded={meta['learning_recorded']!r}; "
        f"`success` must mean 'learned from' and nothing else")

    assert meta["learning_recorded"] is True, (
        f"an example in a populated domain was not recorded as learned "
        f"(error={result.error!r}, class={meta.get('error_class')!r})")

    # The regression case, stated as a state rather than a hope: recorded
    # without credit must be expressible and must read as success.
    if meta["strategy_earned_credit"] is False:
        assert result.success is True, (
            "an example that was learned from but earned no strategy credit "
            "reported success=False -- the exact conflation that made the idle "
            "tier discard working expansions and reprocess them forever")

    # A negative must always be explained, on every path.
    if not result.success:
        assert result.error or meta.get("error_class"), (
            "unexplained negative: indistinguishable from a strategy that "
            "simply earned no credit")


# ---------------------------------------------------------------- component 3

@pytest.mark.asyncio
async def test_producer_vocabulary_is_a_subset_of_what_the_resolver_accepts():
    """The producer's domain references and the registry's must be ONE vocabulary."""
    _load_env()
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.domain.domain_registry import DomainRegistry, UnresolvedDomainReference
    from core.domain.domain_types import DomainType

    # (a) ONE enum, not two vocabularies that happen to agree. universal_domain_master
    # re-exports the registry's DomainType; a shadow copy would compare unequal
    # by identity and every category would silently miss.
    from core.integration.universal_domain_master import DomainType as ProducerDomainType
    assert ProducerDomainType is DomainType, (
        "the producer and the registry use different DomainType objects; "
        "identity-based Enum equality means their values can never match")

    # (b) The producer names a domain only from what a task declares. Nothing is
    # read into the description: a task's contract text ("You MAY: investigate")
    # once filed every one of them under `scientific` -> biology.
    of = AutonomousCoordinator.knowledge_domain_of
    assert of("analysis", "domain_fluid_mechanics") == "domain_fluid_mechanics"
    for task_type in ("research", "analysis", "execution", "learning"):
        assert of(task_type, None) is None, (
            f"a {task_type} task that declares no domain was given one")

    # (c) Every category is ACCEPTED by the resolver -- either resolving to
    # fields or raising the explicit unresolved error. What must never happen is
    # a crash or a silent empty. A category with no populated field is not a
    # lost outcome: (b) is why -- the producer names only what a task declares,
    # never a category it guessed.
    await _field_is_held()
    registry = DomainRegistry()
    await registry.initialize()
    for dt in DomainType:
        try:
            fields = registry.resolve_domain_reference(dt.value, require_concepts=True)
        except UnresolvedDomainReference:
            continue
        assert fields, (
            f"category {dt.value!r} resolved to nothing without saying so; an "
            f"empty answer reads as 'resolved' to every caller")

    # (d) And every populated field is reachable from its own category, or a
    # task classified there resolves past the concepts it should have found.
    populated = {d.domain_id for d in registry.domains.values() if d.concepts}
    assert populated, "registry loaded no populated domain"
    reachable = set()
    for domain in registry.domains.values():
        if domain.concepts:
            reachable.update(
                r.domain_id for r in registry.resolve_domain_reference(
                    domain.domain_type.value, require_concepts=True))
    assert not sorted(populated - reachable), (
        f"populated field(s) {sorted(populated - reachable)} cannot be reached "
        f"from their own DomainType category")


# ---------------------------------------------------------------- component 4

@pytest.mark.asyncio
async def test_universal_projection_is_derived_not_persisted():
    """domain_abstract carries the ontology's universal level, by projection."""
    _load_env()
    from core.database import get_database_manager
    from core.domain.domain_registry import DomainRegistry

    registry = DomainRegistry()
    await registry.initialize()
    abstract = registry.domains[DomainRegistry.UNIVERSAL_DOMAIN_ID]

    projected = {cid: c for cid, c in abstract.concepts.items()
                 if (c.properties or {}).get("source") == "universal_ontology"}
    assert projected, (
        "domain_abstract holds no projected universal concepts; the ABSTRACT "
        "category resolves to nothing while UniversalOntology holds them one "
        "module away")

    # Authority is encoded by PROVENANCE, not by forbidding the abstract domain
    # to hold anything. Torin may legitimately learn a concept that belongs to
    # the abstract level later; what must never happen is the ONTOLOGY's
    # concepts being copied into unified.concepts, which would give the
    # universal level two owners that can disagree.
    db = get_database_manager()
    rows = await db.execute_query(
        "SELECT concept_id FROM unified.concepts WHERE concept_id = ANY($1::text[])",
        (list(projected),), fetch_all=True) or []
    assert not rows, (
        f"projected universal concept(s) {[r['concept_id'] for r in rows]} were "
        f"persisted to unified.concepts; the projection must stay derived so "
        f"UniversalOntology remains their single authority")

    # Stable identity across reload, or structure compared between restarts
    # looks changed when nothing changed.
    again = DomainRegistry()
    await again.initialize()
    assert set(abstract.relations) == set(
        again.domains[DomainRegistry.UNIVERSAL_DOMAIN_ID].relations), (
        "projected relation ids differ between loads")


# ---------------------------------------------------------------- component 5

@pytest.mark.asyncio
async def test_a_stored_outcome_wakes_its_reader():
    """The task-outcome producer HAS A READER, and storing an outcome wakes it.

    Domain expansion was an idle tier on a fixed poll; it is event-driven now: a
    stored outcome starts a single-flight drain over `_idle_domain_expansion_work`.
    Proven by storing an outcome through the real producer and seeing the drain
    run to completion, not by reading the source.
    """
    _load_env()
    await _field_is_held()
    from core.database import get_database_manager

    coord = await _coordinator()
    db = get_database_manager()
    assert asyncio.iscoroutinefunction(coord._idle_domain_expansion_work), (
        "the reader is not awaitable; the drain awaits it")

    task = _task("check the pressure loss across the pipe fitting",
                 task_id="oracle_wake", domain_id=FIELD)
    memory_id = await coord._store_task_outcome_meta_memory(
        task=task, outcome="success", confidence=0.8)
    try:
        assert isinstance(memory_id, str) and memory_id, (
            f"the producer returned {memory_id!r}, not the stored outcome's id")
        drain = coord._domain_expansion_drain_task
        assert drain is not None, (
            "a stored task outcome woke no reader; nothing expands what the "
            "producer writes into the domain layer")
        await asyncio.wait_for(drain, timeout=120)
        assert coord._domain_expansion_status == "COMPLETED"
    finally:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
            (memory_id,), commit=True)


# ---------------------------------------------------------------- component 6

@pytest.mark.asyncio
async def test_tier_reads_the_structured_record_not_the_narrative():
    """store_memory keeps the record and the rendering apart; the tier must
    read the record.

    `content` is the substrate's own account -- "I was asked to ... I did
    it." The TaskOutcomeRecord fields are not
    recoverable from it without parsing English, and store_memory preserves the
    original dict verbatim at thinking_state["raw_event"] for exactly that
    reason. A tier reading `content` finds no `domain` on any outcome and
    classifies every one of them as unusable -- which is indistinguishable from
    having nothing to learn from, and is why this is asserted on the tier's own
    skip reasons rather than only through the full chain.
    """
    _load_env()
    from core.database import get_database_manager
    from core.memory.utils.interfaces import MemoryType

    await _field_is_held()
    coord = await _coordinator()
    storage = await _storage()
    db = get_database_manager()

    # The task DECLARES its field: the producer names no domain it was not told.
    task = _task("test and verify pressure loss across the pipe fitting installation",
                 task_id="oracle_record_vs_narrative", domain_id=FIELD)
    memory_id = await coord._store_task_outcome_meta_memory(
        task=task, outcome="success", confidence=0.8,
        result_summary="verified against the minor-loss coefficient")
    try:
        found = await storage.search_memories(
            memory_type=MemoryType.META, tags={TAG}, limit=500)
        item = next(m for m in found if m.memory_id == memory_id)

        # The two are DIFFERENT representations, and only one is the record.
        raw = (item.thinking_state or {}).get("raw_event")
        assert isinstance(raw, dict) and raw.get("domain"), (
            "the structured record did not survive storage")
        assert not (isinstance(item.content, dict) and item.content.get("domain")), (
            "content now carries the structured fields too; if that is "
            "intentional the record has two representations and they can "
            "disagree")

        await _reader_woken_by(coord)
        # THIS outcome, not the pass's totals: a shared store holds other
        # outcomes the drain also passes over, and its last pass may see only
        # those. The outcome carries the expansion mark only if the tier found
        # its field, which the narrative never names.
        rows = await db.execute_query(
            f"SELECT metadata->>'{MARK}' AS m FROM memory_hot.memory_hot "
            f"WHERE memory_id = $1", (memory_id,), fetch_all=True)
        assert rows and rows[0]["m"], (
            f"the tier did not expand an outcome whose record names its field "
            f"({coord._domain_expansion_counts}); it is reading the narrative "
            f"instead of thinking_state['raw_event']")
    finally:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
            (memory_id,), commit=True)


# ------------------------------------------------------- the return direction

@pytest.mark.asyncio
async def test_applying_a_mapping_counts_as_using_it():
    """usage_count separates a relied-upon correspondence from a one-off."""
    _load_env()
    from core.database import get_database_manager
    from core.learning.unified_learning_system import get_unified_learning_system

    learning = get_unified_learning_system()
    await learning.start()
    db = get_database_manager()

    async def events_for(task_ids):
        rows = await db.execute_query(
            "SELECT count(*) AS n FROM unified.mapping_usage_events "
            "WHERE task_id = ANY($1::text[])", (list(task_ids),), fetch_all=True)
        return rows[0]["n"]

    # DISTINCT identities per run. Usage events are idempotent on
    # (mapping, task, stage), so reusing fixed task ids makes the second run of
    # this test record nothing -- correct behaviour that would read here as the
    # accumulation defect it is meant to catch.
    import uuid as _uuid
    run = _uuid.uuid4().hex[:8]
    task_a, task_b = f"oracle_usage_{run}_a", f"oracle_usage_{run}_b"

    await _analogy_is_held()
    before = await events_for([task_a, task_b])
    result = await learning.transfer_learning_across_domains(
        "domain_plumbing", "domain_fluid_mechanics",
        {"trigger": "usage oracle 1", "task_id": task_a})
    assert result.get("success"), (
        f"a transfer between two fields that share structure did not apply: "
        f"{result.get('error') or result}")
    once = await events_for([task_a, task_b])

    assert once > before, (
        "a transfer was created from validated mappings and no mapping's "
        "usage_count moved; usage_count is serialised, persisted and read back "
        "but nothing increments it, so every mapping reads as equally untried "
        "forever")

    # ACCUMULATION across DISTINCT applications. UniversalDomainMaster.suggest_mappings
    # mints a fresh CrossDomainMapping per call with usage_count=0, so storing
    # the candidate wholesale reset the running total and every application
    # landed on 1 again. A single-application assertion passes against that bug.
    await learning.transfer_learning_across_domains(
        "domain_plumbing", "domain_fluid_mechanics",
        {"trigger": "usage oracle 2", "task_id": task_b})
    twice = await events_for([task_a, task_b])
    assert twice > once, (
        f"usage went {before} -> {once} -> {twice}: a second application on a "
        f"different task did not accumulate. A re-derived mapping is "
        f"overwriting the stored count, so a correspondence relied on fifty "
        f"times is indistinguishable from one used once")

    # And the count is state, not a session artefact.
    # usage_count is a PROJECTION: after a restart it must equal the number of
    # events, not a separately-maintained number that happens to look right.
    from core.domain.domain_registry import DomainRegistry
    fresh = DomainRegistry()
    await fresh.initialize()
    truth = {r["mapping_id"]: r["n"] for r in (await db.execute_query(
        "SELECT mapping_id, count(*) AS n FROM unified.mapping_usage_events "
        "GROUP BY mapping_id", fetch_all=True) or [])}
    drifted = [(mid, m.usage_count, truth.get(mid, 0))
               for mid, m in fresh.cross_domain_mappings.items()
               if m.usage_count != truth.get(mid, 0)]
    assert not drifted, (
        f"usage_count disagrees with the usage events after reload: {drifted[:3]}; "
        f"the count is maintained independently of the record it summarises and "
        f"can survive with no events to justify it")
    assert max(truth.values(), default=0) >= 1, "no usage event survived reload"

    await db.execute_query(
        "DELETE FROM unified.mapping_usage_events WHERE task_id = ANY($1::text[])",
        ([task_a, task_b],), commit=True)


@pytest.mark.asyncio
async def test_a_retried_application_is_not_a_second_use():
    """usage is EVENTS keyed by (mapping, task, stage) -- retries count once."""
    _load_env()
    from core.database import get_database_manager
    from core.learning.unified_learning_system import get_unified_learning_system

    learning = get_unified_learning_system()
    await learning.start()
    db = get_database_manager()

    import uuid as _uuid
    run = _uuid.uuid4().hex[:8]
    task, other = f"oracle_retry_{run}", f"oracle_retry_{run}_other"

    async def events():
        rows = await db.execute_query(
            "SELECT count(*) AS n FROM unified.mapping_usage_events WHERE task_id = ANY($1::text[])",
            ([task, other],), fetch_all=True)
        return rows[0]["n"]

    await _analogy_is_held()
    try:
        r = await learning.transfer_learning_across_domains(
            "domain_plumbing", "domain_fluid_mechanics",
            {"trigger": "retry oracle", "task_id": task})
        assert r.get("success"), (
            f"a transfer between two fields that share structure did not apply: "
            f"{r.get('error') or r}")
        first = await events()
        assert first > 0, "the application recorded no usage event"

        # Autonomous execution retries. The SAME logical application must not
        # become additional evidence -- a count inflated by retries would make a
        # mapping applied once look like one relied on repeatedly.
        await learning.transfer_learning_across_domains(
            "domain_plumbing", "domain_fluid_mechanics",
            {"trigger": "retry oracle", "task_id": task})
        assert await events() == first, (
            f"a retried application added usage events ({first} -> {await events()}); "
            f"usage_id must be derived from (mapping_id, task_id, stage) so the "
            f"same application is idempotent")

        # A genuinely different task IS a second use.
        await learning.transfer_learning_across_domains(
            "domain_plumbing", "domain_fluid_mechanics",
            {"trigger": "retry oracle", "task_id": other})
        assert await events() > first, (
            "a different task did not register as a distinct use; idempotency "
            "is keyed too coarsely and real applications are being discarded")
    finally:
        await db.execute_query(
            "DELETE FROM unified.mapping_usage_events WHERE task_id = ANY($1::text[])",
            ([task, other],), commit=True)


@pytest.mark.asyncio
async def test_transfer_verdict_states_how_it_was_inferred():
    """An attributed verdict and a correlational one must not read the same.

    "The domain improved after the transfer" is not "the transfer improved the
    domain". When usage events identify which tasks a mapping actually
    participated in, the comparison is applied-vs-unapplied within the same
    window; when they do not, it falls back to before-vs-after, which is
    confounded with everything else that changed. Both can be legitimate, but a
    reader must be able to tell which one produced a TRUE.
    """
    _load_env()
    import inspect
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    source = inspect.getsource(AutonomousCoordinator._resolve_transfer_outcomes)
    assert '"attributed"' in source and '"observational"' in source, (
        "the evaluator does not distinguish an attributed verdict from a "
        "correlational one; a before/after TRUE would be reported as though it "
        "established that the transfer helped")
    assert "tasks_using_mappings" in source, (
        "the evaluator never asks which tasks the mapping participated in, so "
        "every post-transfer outcome is credited to it regardless of whether "
        "it was involved")

    # And the verdict carries its inference, not just its answer.
    coord = await _coordinator()
    await coord._resolve_transfer_outcomes()
    assert coord._transfer_resolution_status in {"COMPLETED", "NOTHING_PENDING"}


@pytest.mark.asyncio
async def test_transfer_outcome_resolves_only_on_sufficient_evidence():
    """NULL until the target domain has history on both sides; then TRUE/FALSE."""
    _load_env()
    from core.database import get_database_manager
    from core.memory.utils.interfaces import MemoryItem, MemoryType

    coord = await _coordinator()
    storage = await _storage()
    db = get_database_manager()

    # The field the fixture's outcomes bear on. An outcome bears on the field its
    # task DECLARED (`knowledge_domain`), which is how the evaluator groups them,
    # and no other oracle leaves outcomes there, so the fixture is the only
    # evidence and the verdict is attributable to it.
    await _field_is_held()
    target_field = FIELD
    rich, thin = "test_xfer_rich", "test_xfer_thin"
    made = []

    async def outcome(tag_id, ok, offset_minutes):
        mid = f"test_outcome_{tag_id}"
        await storage.store_memory(MemoryItem(
            memory_id=mid, memory_type=MemoryType.META,
            content={"event": "task_outcome"},
            thinking_state={"raw_event": {"knowledge_domain": target_field,
                                          "task_type": "analysis", "task_id": mid,
                                          "outcome": "success" if ok else "failure"}},
            tags={TAG, "test_transfer_fixture"}))
        await db.execute_query(
            "UPDATE memory_hot.memory_hot SET created_at = NOW() + ($2 || ' minutes')::interval "
            "WHERE memory_id = $1", (mid, str(offset_minutes)), commit=True)
        made.append(mid)

    async def transfer(tid):
        await db.execute_query(
            """INSERT INTO unified.knowledge_transfers
                 (transfer_id, source_domain, target_domain, concept, concept_type,
                  transfer_method, success, metadata, created_at)
               VALUES ($1,'plumbing',$2,'fixture','entity','structural_analogy',
                       NULL,'{}'::jsonb, NOW())""",
            (tid, target_field), commit=True)

    try:
        # Baseline: 6 failures BEFORE. Post: 6 successes AFTER. A real effect.
        for i in range(6):
            await outcome(f"{rich}_pre_{i}", ok=False, offset_minutes=-120 + i)
        await transfer(rich)
        await transfer(thin)
        for i in range(6):
            await outcome(f"{rich}_post_{i}", ok=True, offset_minutes=60 + i)

        await coord._resolve_transfer_outcomes()

        rows = await db.execute_query(
            "SELECT transfer_id, success, metadata FROM unified.knowledge_transfers "
            "WHERE transfer_id = ANY($1::text[])", ([rich, thin],), fetch_all=True)
        verdicts = {r["transfer_id"]: r["success"] for r in rows}

        assert verdicts[rich] is True, (
            f"a transfer followed by a 0%->100% swing in its target domain "
            f"resolved to {verdicts[rich]!r}; the return leg of the loop is not "
            f"reading the evidence")

        import json
        meta = rows[0]["metadata"] if rows[0]["transfer_id"] == rich else rows[1]["metadata"]
        meta = json.loads(meta) if isinstance(meta, str) else meta
        evidence = meta.get("outcome_evidence") or {}
        assert evidence.get("reference_n", 0) >= 5 and evidence.get("effect_n", 0) >= 5, (
            f"the verdict was stored without the evidence it rests on ({evidence}); "
            f"an opaque boolean cannot be revised when more outcomes arrive")
        # No usage events exist for this fixture transfer, so the only available
        # comparison is before/after. It must SAY so rather than presenting a
        # correlational result as an attributed one.
        assert evidence.get("inference") == "observational", (
            f"a before/after comparison was labelled {evidence.get('inference')!r}; "
            f"with no record of which tasks the mapping participated in, this "
            f"verdict cannot claim the transfer caused the change")

        # The thin transfer shares the same evidence window, so it resolves too.
        # What must never happen is a verdict with too little history -- prove
        # that by asking for more evidence than exists.
        await db.execute_query(
            "UPDATE unified.knowledge_transfers SET success = NULL, metadata = '{}'::jsonb "
            "WHERE transfer_id = ANY($1::text[])", ([rich, thin],), commit=True)
        original = coord.TRANSFER_MIN_EVIDENCE
        try:
            coord.TRANSFER_MIN_EVIDENCE = 500
            await coord._resolve_transfer_outcomes()
        finally:
            coord.TRANSFER_MIN_EVIDENCE = original

        still = await db.execute_query(
            "SELECT transfer_id, success FROM unified.knowledge_transfers "
            "WHERE transfer_id = ANY($1::text[])", ([rich, thin],), fetch_all=True)
        assert all(r["success"] is None for r in still), (
            "a transfer was given a verdict on less evidence than required; "
            "'not enough history to say' must stay NULL and never default to "
            "False, or an unjudged transfer becomes a refuted one")
    finally:
        if made:
            await db.execute_query(
                "DELETE FROM memory_hot.memory_hot WHERE memory_id = ANY($1::text[])",
                (made,), commit=True)
        await db.execute_query(
            "DELETE FROM unified.knowledge_transfers WHERE transfer_id = ANY($1::text[])",
            ([rich, thin],), commit=True)


# ------------------------------------------------------------------ the chain

@pytest.mark.asyncio
async def test_chain_end_to_end():
    """Producer -> memory -> bridge -> consumer -> marker, proven as one path.

    The component tests above each cross a single joint. This crosses all of
    them at once, which is the only way to catch a chain that is broken between
    two individually-correct parts.
    """
    _load_env()
    from core.database import get_database_manager
    from core.domain.domain_registry import DomainRegistry
    from core.memory.utils.interfaces import MemoryType

    await _field_is_held()
    coord = await _coordinator()
    storage = await _storage()
    db = get_database_manager()

    # 1. A task that acts in a domain HOLDING learned concepts -- declared under
    #    the prefixed spelling, which must reach the field as it is registered.
    task = _task("test and verify pressure loss across the pipe fitting installation",
                 task_id="oracle_chain_e2e", domain_id="domain_fluid_mechanics")
    domain = coord._task_domain(task)
    resolved = DomainRegistry()
    await resolved.initialize()
    fields = [r.domain_id for r in resolved.resolve_domain_reference(
        domain, require_concepts=True)]
    assert fields, (
        f"the task acts in {domain!r}, which resolves to no populated field; "
        f"the chain cannot be exercised through it")

    # 2. Store it through the REAL producer.
    memory_id = await coord._store_task_outcome_meta_memory(
        task=task, outcome="success", confidence=0.8,
        result_summary="verified against the minor-loss coefficient")
    assert memory_id, "the producer stored no memory"

    try:
        # 3. Read it back INDEPENDENTLY: the structured record must survive,
        #    not just the narrative rendering.
        found = await storage.search_memories(
            memory_type=MemoryType.META, tags={TAG}, limit=500)
        item = next((m for m in found if m.memory_id == memory_id), None)
        assert item is not None, (
            "the stored outcome is not returned by the structured search the "
            "tier uses to find its work")
        raw = (item.thinking_state or {}).get("raw_event")
        assert isinstance(raw, dict), (
            f"raw_event is {type(raw).__name__}; the structured TaskOutcomeRecord "
            f"did not survive storage and only the prose narrative remains")
        assert raw.get("knowledge_domain") == domain
        assert raw.get("outcome") == "success"

        # 4. The reader the producer woke runs.
        await _reader_woken_by(coord)
        assert coord._domain_expansion_status == "COMPLETED"

        # 5-8. The outcome is consumed, and the marker is durably written.
        async def mark():
            rows = await db.execute_query(
                f"SELECT metadata->>'{MARK}' AS m FROM memory_hot.memory_hot "
                f"WHERE memory_id = $1", (memory_id,), fetch_all=True)
            return rows[0]["m"] if rows else None

        first_mark = await mark()
        assert first_mark, (
            "the outcome was processed but carries no durable marker; the next "
            "pass would re-learn it and the meta-learner would count one "
            "outcome as several independent trials")

        # 9. EXACTLY ONCE. A second pass must not touch it again.
        await coord._idle_domain_expansion_work()
        assert await mark() == first_mark, (
            "the marker changed on a second pass; the outcome was reprocessed")

        # 10. RESTART PERSISTENCE. Fresh instances, nothing carried in memory:
        #     the processed state must still be processed.
        from core.agents.memory_agent import MemoryAgent
        fresh_storage = MemoryAgent()
        await fresh_storage.initialize()
        reread = await fresh_storage.postgres_storage.search_memories(
            memory_type=MemoryType.META, tags={TAG}, limit=500)
        after_restart = next((m for m in reread if m.memory_id == memory_id), None)
        assert after_restart is not None
        assert (after_restart.metadata or {}).get(MARK) == first_mark, (
            "the processed marker did not survive a fresh read; every restart "
            "would re-expand the entire backlog")

        # And the learned structure itself survives a fresh registry.
        fresh_registry = DomainRegistry()
        await fresh_registry.initialize()
        assert fresh_registry.cross_domain_mappings, (
            "no cross-domain mapping survived a registry restart")
    finally:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
            (memory_id,), commit=True)
