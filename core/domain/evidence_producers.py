#!/usr/bin/env python3
"""Evidence producers — adapters from tool output to EvidenceEnvelope.

These live here rather than inside the tools deliberately. `conduct_research`
should know how to research and nothing about concepts: it produces findings,
this module wraps them as evidence, and ConceptIngestionService retains all
semantic authority. A tool that decided what a concept is would become a second
authority over the semantic layer.

The lineage these build is what makes root-evidence independence meaningful:

    source A (independent observation)  ─┐
    source B (independent observation)  ─┼─→ synthesis (derived from A, B, C)
    source C (independent observation)  ─┘

Three genuinely independent sources contribute three roots. One source producing
three findings, two summaries and a memory still resolves to one root, because
every derivative declares the source it came from.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .concept_ingestion import (
    _ROOT_SOURCES,
    EvidenceEnvelope,
    EvidenceSourceType,
    IngestionResult,
    get_concept_ingestion_service,
)

logger = logging.getLogger(__name__)


#: What a PRODUCED fact is worth as evidence when the producer has no
#: measurement of its own to offer. Named, not defaulted: it is the value this
#: path has always used, and writing it down is the point -- a number nobody
#: states is indistinguishable from a number nobody chose, and this one set the
#: prior of most of what the substrate believes.
#:
#: It is NOT a fallback for a producer that HAS a confidence. A producer that
#: knows how good its evidence is states it ON THE EDGE it belongs to, and a
#: producer that genuinely has none -- a tool's declared capability, a file
#: property read off disk -- says so by naming this.
PRODUCED_EVIDENCE_QUALITY = 0.9

#: What a claim is worth when its reading resolved NOTHING -- when the
#: measurement sits exactly on the cut that decides between two names. It is a
#: coin flip between those names, so it is worth a coin flip, and no less: the
#: observation did happen and one of the two names is right.
COIN_FLIP = 0.5


def quality_from_resolution(resolution: float,
                            base: float = PRODUCED_EVIDENCE_QUALITY) -> float:
    """Turn a perceptual RESOLUTION into an evidence QUALITY.

    These are two different quantities and feeding one into the other's slot was
    a real defect, measured: the faculty reports how far a reading sits from the
    cut that would rename it, on a scale where 0 means "on the cut". Handed to
    the belief layer raw, that number put 60% of CORRECT colour readings and 65%
    of correct size readings below the 0.5 floor, where a claim is not held
    weakly but REFUSED outright. Doubting almost everything is no more honest
    than doubting nothing; it just fails quietly instead of loudly.

    The mapping is fixed by its two ends, not fitted to anything. A fully
    resolved reading is worth exactly what this producer's observations are
    normally worth -- it is a clean look at a thing, and there is nothing to
    discount. A reading ON the cut is a coin flip between the two names it sits
    between, which is `COIN_FLIP` and not zero. Everything else interpolates.
    """
    r = max(0.0, min(1.0, float(resolution)))
    return COIN_FLIP + (float(base) - COIN_FLIP) * r


async def _ingest_and_learn(service: Any, envelope: "EvidenceEnvelope", *,
                            domain: str, quality: float,
                            memory_id: Optional[str] = None) -> "IngestionResult":
    """Ingest through the ONE write path, then fan the admitted relations out to
    the lexicon and beliefs via the learning authority.

    A produced fact (research, tool capability, perception) landed the concept
    graph but nothing else -- so its words were never learned and it never moved
    a belief. This closes that gap without a second write path: it ingests as
    before, then hands `IngestionResult.admitted_relations` to
    UnifiedLearningSystem.fan_out_ingested, which runs the SAME fan-out a taught
    fact does. Every observation moves a posterior; what it believes today it can
    revise tomorrow. Isolated -- a fan-out failure never fails the production.

    `quality` is how good the producer says its own evidence is, and every
    producer states it. It was omitted here, so the fan-out's default stood and
    a detector's confidence -- the one number on this path that was actually
    measured -- was discarded on the way to the belief.

    `memory_id` is the memory of HAVING MET what this evidence is about, for the
    producers that met something: a belief names the memory it is about or it is
    not stored. A producer with nothing met (a tool signature read off a
    registry) passes None and its beliefs are honestly refused."""
    result = await service.ingest(envelope)
    # A PERCEPTION IS SOMETHING THE SUBSTRATE MET, so if the caller did not
    # already remember it, it is remembered here — in the producer's OWN
    # rendering of the observation, which is the only faithful account of it
    # available and is already computed for the envelope.
    #
    # Scoped to PERCEPTION provenance deliberately. A tool signature read off a
    # registry is not something met, and letting it mint a memory would reopen
    # exactly what the grounding rule closed: ~1,800 of them per boot written as
    # things the substrate believed. `coord.see` supplies its own richer memory
    # (with the picture retained), so an image never reaches this.
    if memory_id is None and _is_perception(envelope):
        from core.memory import Origin
        memory_id = await _remember_percept(envelope, Origin.own("perception"))
    try:
        from core.learning.unified_learning_system import \
            get_unified_learning_system
        await get_unified_learning_system().fan_out_ingested(
            result, domain=domain, surface=getattr(envelope, "content", "") or "",
            quality=quality, memory_id=memory_id)
    except Exception as error:
        logger.debug("evidence fan-out skipped (%s): %s", domain, error)
    return result



def _is_perception(envelope: "EvidenceEnvelope") -> bool:
    """Is this envelope an observation of something the substrate MET?"""
    from .concept_ingestion import EvidenceSourceType
    return getattr(envelope, "source_type", None) is EvidenceSourceType.PERCEPTION


async def _remember_percept(envelope: "EvidenceEnvelope", origin: "Origin") -> Optional[str]:
    """Remember having perceived this, as whose it was, and return the memory's id.

    The text is the envelope's own `content` — the producer's rendering of what
    it observed ("boiler_temp_sensor reads 94.5 celsius of temperature"), so
    nothing is invented here to get a memory written. Isolated: a perception is
    never failed by its memory, but the failure is reported, because a percept
    with no memory is a percept nothing can be believed about."""
    account = str(getattr(envelope, "content", "") or "").strip()
    if not account:
        return None
    try:
        from core.memory import get_memory_agent
        from core.memory.utils.interfaces import MemoryType
        agent = await get_memory_agent()
        ok, memory_id = await agent.store_memory(
            origin=origin,
            content=account, memory_type=MemoryType.EPISODIC,
            importance_score=0.5,
            tags=["percept", str(getattr(envelope, "producer", "") or "")],
            source_context={"source_system": "perception",
                            "evidence_id": getattr(envelope, "evidence_id", None),
                            "source_id": getattr(envelope, "source_id", None)})
        return memory_id if ok else None
    except Exception as error:
        logger.error("perceived %r but formed no memory of it: %s",
                     account[:80], error)
        return None


async def _admit_perceived(service: Any, envelope: "EvidenceEnvelope", *, origin: "Origin",
                           domain: str, quality: float,
                           memory_id: Optional[str] = None) -> Optional["IngestionResult"]:
    """A perception, admitted where its owner's words go.

    The substrate's own takes the one write path and the learning fan-out, as
    it always has. A PERSON'S -- their image, what was seen in it -- is theirs:
    each edge of the observation goes through the learning authority's router
    to their context, as what they tell does, and nothing of it enters the shared
    graph, its beliefs or the vocabulary. It enters the substrate's own
    knowledge only as an experience, through the lift and the gate. Returns the
    ingestion for the substrate's own, and None for a person's: the shared
    graph took nothing."""
    if origin.person is None:
        return await _ingest_and_learn(service, envelope, domain=domain,
                                       quality=quality, memory_id=memory_id)
    from core.capability import raise_if_structural
    from core.learning.unified_learning_system import get_unified_learning_system
    from core.semantics.cognitive_ingress import Provenance
    if memory_id is None:
        await _remember_percept(envelope, origin)
    learning = get_unified_learning_system()
    provenance = Provenance(producer=str(envelope.producer),
                            source_id=str(envelope.source_id),
                            source_type=EvidenceSourceType.PERCEPTION.name)
    for concept in (envelope.structured_data or {}).get("concepts") or []:
        for edge in concept.get("relationships") or []:
            relation, obj = str(edge[0]), edge[1]
            positive = len(edge) < 3 or str(edge[2]) != "negative"
            support = edge[3] if len(edge) > 3 and edge[3] is not None else quality
            try:
                await learning.learn_fact(
                    str(concept["label"]), relation, str(obj), positive=positive,
                    surface=envelope.content, provenance=provenance, domain=domain,
                    quality=float(support), actor=origin.person)
            except Exception as error:
                raise_if_structural(error, "evidence_producers._admit_perceived")
                logger.warning("a person's perception could not be held in their context "
                               "(%s %s %s): %s", concept.get("label"), relation, obj, error)
    return None


def _stable_id(prefix: str, *parts: str) -> str:
    """Deterministic evidence id.

    Deterministic so re-processing the same research output reinforces the same
    concepts through the same roots rather than minting fresh ids that would
    each look like independent corroboration.
    """
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()
    return f"{prefix}_{digest[:24]}"


#: Query parameters that identify a referrer or campaign rather than a document.
#: Stripped so the same page reached from two places is one source.
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "ref", "referrer", "source", "src",
})


def canonical_source_key(locator: str) -> str:
    """Canonical identity of an underlying source observation.

    THE ROOT INVARIANT:

        same underlying source observation  -> same epistemic root
        different question / summary / extraction -> different derivative
                                                     envelope, SAME root

    Root ids must therefore be a function of the source alone. They previously
    included the research topic, so one DOI encountered under "fuel cells" and
    again under "electrochemistry" produced two envelope ids and counted as two
    independent roots -- corroboration manufactured by asking a second question.

    Normalises: scheme and host case, `www.`, default ports, trailing slash,
    URL fragments, tracking parameters, and the several spellings of a DOI.
    """
    raw = str(locator or "").strip()
    if not raw:
        return ""

    low = raw.lower()

    # DOIs: doi:10.x, https://doi.org/10.x, https://dx.doi.org/10.x -> 10.x
    for prefix in ("https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if low.startswith(prefix):
            return "doi:" + low[len(prefix):].strip("/")
    if low.startswith("10.") and "/" in low:
        return "doi:" + low.strip("/")

    if "://" not in low:
        return low.strip("/")

    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    parts = urlsplit(low)
    host = parts.netloc
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(":80") or host.endswith(":443"):
        host = host.rsplit(":", 1)[0]

    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k not in _TRACKING_PARAMS
    ))
    path = parts.path.rstrip("/") or "/"

    # Fragment dropped: it addresses a location within one document, not a
    # different document.
    return urlunsplit(("https", host, path, query, ""))


def _source_identity(result: Dict[str, Any]) -> Tuple[str, str]:
    """(source_name, canonical_source_key) for one research result."""
    name = str(result.get("source") or result.get("api") or "unknown_source")
    raw = result.get("doi") or result.get("url") or result.get("id") or name
    return name, (canonical_source_key(raw) or name.lower())


#: Sentence boundaries. Deliberately simple: the statement reader declines
#: anything it cannot parse, so an over-split sentence costs a decline, never a
#: wrong assertion.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _statements(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(str(text or "")) if s.strip()]


async def submit_research_result(
    topic: str,
    output: Dict[str, Any],
    *,
    producer: str = "conduct_research",
    request_id: Optional[str] = None,
) -> List[IngestionResult]:
    """Turn one `conduct_research` payload into evidence and ingest it.

    Args:
        topic:   what was researched.
        output:  the tool's `output` dict — expects `raw_results` (per-source)
                 and optionally `synthesis`.
        producer: tool name, recorded as interpretation provenance.
        request_id: caller's id for this research operation, if any.

    Returns one IngestionResult per envelope submitted.

    Raises rather than returning empty when the payload has no usable sources:
    a research call that produced nothing and one whose output could not be read
    are different failures, and only the second is a defect here.
    """
    service = get_concept_ingestion_service()
    await service._ready()

    raw = output.get("raw_results") or output.get("results") or []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise TypeError(
            f"research output raw_results has type {type(raw).__name__}; "
            f"expected a list of per-source results"
        )

    categories = [str(c).strip().lower() for c in (output.get("categories") or [])
                  if str(c).strip()]
    if not categories:
        raise ValueError(
            f"research on {topic!r} carries no categories; TopicClassifier "
            f"assigns them deterministically and a concept must belong "
            f"somewhere, so inventing a domain here is how one topic acquired 21")
    domain = categories[0]

    results: List[IngestionResult] = []
    source_ids: List[str] = []

    # 1. One ROOT envelope per independent source.
    for entry in raw:
        if not isinstance(entry, dict):
            # A source we cannot attribute is not an independent observation.
            logger.warning(
                "Skipping unattributable research result of type %s for topic %r",
                type(entry).__name__, topic,
            )
            continue
        name, locator = _source_identity(entry)
        content = str(
            entry.get("snippet") or entry.get("summary") or entry.get("description")
            or entry.get("title") or entry.get("data") or ""
        ).strip()
        if not content:
            logger.info("Source %s returned no content for %r; not evidence", name, topic)
            continue

        # ROOT ID IS TOPIC-FREE. The same source met under a different
        # research question must resolve to the same epistemic root.
        eid = _stable_id("ev_src", locator)
        envelope = EvidenceEnvelope(
            evidence_id=eid,
            source_type=EvidenceSourceType.RESEARCH_FINDING,
            source_id=locator,
            producer=producer,
            content=content,
            structured_data={
                # `domain` and `statements` are what the deterministic reader
                # needs. The categories come from TopicClassifier, which is
                # keyword matching -- so the domain a research concept lands in
                # is decided without a model, the same as its structure.
                "domain": domain,
                "statements": _statements(content),
                **{k: v for k, v in entry.items()
                   if k in ("concepts", "title", "url", "authors", "published", "quality")},
            },
        )
        source_ids.append(eid)
        results.append(await _ingest_and_learn(service, envelope, domain=domain,
                                               quality=PRODUCED_EVIDENCE_QUALITY))

    if not source_ids:
        logger.warning(
            "Research on %r produced no attributable sources; no evidence recorded",
            topic,
        )
        return results

    # 2. The synthesis is DERIVATIVE. It restates the sources, so it carries
    #    their ids and resolves to their roots rather than adding one of its own.
    synthesis = str(output.get("synthesis") or "").strip()
    if synthesis:
        results.append(await _ingest_and_learn(service, EvidenceEnvelope(
            evidence_id=_stable_id("ev_synthesis", topic, request_id or "", *source_ids),
            source_type=EvidenceSourceType.MEMORY_RETROSPECTIVE,
            source_id=f"synthesis:{topic}",
            producer=producer,
            content=synthesis,
            structured_data={"domain": domain, "statements": _statements(synthesis)},
            derived_from=tuple(source_ids),
        ), domain=domain, quality=PRODUCED_EVIDENCE_QUALITY))

    total = sum(r.accepted for r in results)
    logger.info(
        "Research %r: %d source envelope(s) + synthesis -> %d concept(s) accepted",
        topic, len(source_ids), total,
    )
    return results


__all__ = ["submit_research_result", "submit_learned_rule",
           "submit_demonstration", "submit_tool_capability",
           "submit_tool_invocation", "submit_perception",
           "submit_sensor_reading", "submit_image", "submit_video",
           "canonical_source_key"]


async def submit_learned_rule(
    stored,
    derived_from,
    *,
    producer: str = "rule_induction",
) -> "IngestionResult":
    """Project an induced rule into the semantic layer as structure.

    THE TWO LEARNING SYSTEMS DID NOT MEET. Rule induction writes operators to
    unified.learned_rules keyed on predicate identity; concept ingestion writes
    structures to unified.concept_relations keyed on concept id. Both are real
    learning systems, and nothing carried a result from one to the other -- so
    "what Lyric has learned" had two answers depending on which store you asked.

    The cost was measurable: CrossDomainGrounder searched 44 learned structures
    for a routing problem structurally identical to MOVE and returned NO_MATCH,
    because the MOVE operator had no representation in the graph it searches.
    Transfer was blocked by absence, not by a weak matcher.

    DERIVATIVE, never a root. A rule is a generalization OF demonstrations, so
    it declares the evidence it was induced from. Ingesting it as a root would
    let the rule count as fresh support for the very concepts its training
    examples already supported.

    The projection is structural: the action is the hub, and each precondition
    and effect becomes an edge. That is the shape the analogy matcher reads --
    a rule with fewer than MIN_STRUCTURE_EDGES edges is not searchable, and
    saying so is more useful than filing an unusable structure.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    service = get_concept_ingestion_service()
    await service._ready()

    rule = stored.rule
    if rule.action is None:
        raise ValueError(
            f"{stored.rule_id}: no action recorded. A rule that describes what "
            f"follows rather than what the agent can do has no operator "
            f"structure to project, and filing it would put a non-operator in "
            f"the store the planner's analogies are drawn from")

    domain = getattr(stored, "domain_id", None)
    if not domain:
        raise ValueError(
            f"{stored.rule_id}: no domain_id. A concept must belong somewhere, "
            f"and inventing a domain for it is how one topic acquired 21")

    action = rule.action
    by_role = {
        "requires": [f for f in sorted(rule.body, key=str) if f != action],
        "adds": sorted(rule.effects.add, key=str),
        "removes": sorted(rule.effects.delete, key=str),
    }

    # Supplied by the caller, which holds the store. `evidence_roots` is a
    # query on RuleStore, not a field on the record -- reading it off the record
    # would silently capture a bound method and file a rule with no lineage.
    roots = tuple(dict.fromkeys(derived_from or ()))
    if not roots:
        raise ValueError(
            f"{stored.rule_id}: no induction roots supplied. A derivative "
            f"source with no lineage cannot be distinguished from a root")

    # PREDICATES, not ground atoms. `AT(?X0, ?X2)` carries variable names bound
    # by this rule alone; `at` is the relation another domain can correspond to.
    operator = {
        "action": action.predicate,
        "arity": action.arity,
        "domain": domain,
        **{role: [{"predicate": f.predicate, "arity": f.arity} for f in facts]
           for role, facts in by_role.items()},
    }

    envelope = EvidenceEnvelope(
        evidence_id=_stable_id("indrule", stored.rule_id),
        source_type=EvidenceSourceType.INDUCED_RULE,
        source_id=stored.rule_id,
        content=(f"{action.predicate} is an operation: " + "; ".join(
            f"{role} {fact}" for role, facts in by_role.items() for fact in facts)),
        producer=producer,
        structured_data={
            "operator": operator,
            "rule_id": stored.rule_id,
            "epistemic_status": getattr(stored.status, "value", str(stored.status)),
        },
        derived_from=roots,
    )
    return await _ingest_and_learn(service, envelope, domain=domain or "researched",
                                 quality=PRODUCED_EVIDENCE_QUALITY)


async def submit_demonstration(
    example,
    *,
    domain_id: str,
    source_type: "EvidenceSourceType",
    producer: str,
    source_id: Optional[str] = None,
) -> "IngestionResult":
    """Record one observed state transition as a ROOT observation.

    A demonstration is where the substrate's semantic layer touches the world:
    facts held, an action was taken, facts changed. Everything downstream --
    the induced rule, the operator structure, the cross-domain correspondence
    -- is a generalization OF this, and must declare it.

    Without this the chain has no floor. `learned_rule_evidence` recorded the
    demonstration ids that induced a rule, but nothing recorded the
    demonstrations themselves as evidence, so projecting the rule raised
    `dangling lineage: <rule> -> mv_d1, which is not recorded`. That refusal is
    correct: a derivative whose ancestors are missing cannot be told apart from
    a root, and treating it as one would let a rule corroborate itself.

    THE ENVELOPE ID IS THE DEMONSTRATION'S OWN ID, not a minted one. It is
    already the foreign key in `unified.learned_rule_evidence`, and a second
    identity for one observation is a second root for it.

    Only the OBSERVED delta becomes an edge. The before-state is not projected
    as `requires`: a demonstration shows which facts happened to hold, and
    which of them the action needed is precisely what induction decides. An
    observation that asserted requirement would answer the question the learner
    exists to answer.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    if source_type not in _ROOT_SOURCES:
        raise ValueError(
            f"{source_type.value} is derivative; a demonstration is a fresh "
            f"observation and recording it as anything else would make the "
            f"rule induced from it depend on a lineage that does not exist")

    evidence_id = getattr(example, "evidence_id", None)
    if not evidence_id:
        raise ValueError(
            "demonstration carries no evidence_id; the rule store keys its "
            "induction basis on that id, and minting one here would file the "
            "observation under an identity nothing else refers to")
    if not domain_id:
        raise ValueError(f"{evidence_id}: no domain_id; a concept must belong somewhere")

    service = get_concept_ingestion_service()
    await service._ready()

    action = getattr(example, "action", None)
    effects = example.observed_effects
    # The action is the hub, so it is not also listed as a state atom: one
    # predicate proposed twice under two kinds is one concept whose kind
    # depends on which candidate happened to persist first.
    atoms = {f.predicate: f.arity for f in (*example.before, *example.after)}

    observation = {
        "domain": domain_id,
        "action": ({"predicate": action.predicate, "arity": action.arity}
                   if action else None),
        "atoms": [{"predicate": p, "arity": a} for p, a in sorted(atoms.items())],
        "adds": [{"predicate": f.predicate, "arity": f.arity}
                 for f in sorted(effects.add, key=str)],
        "removes": [{"predicate": f.predicate, "arity": f.arity}
                    for f in sorted(effects.delete, key=str)],
    }

    rendered = "; ".join(filter(None, (
        "holds " + ", ".join(str(f) for f in sorted(example.before, key=str)),
        f"action {action}" if action else "no action taken",
        "adds " + ", ".join(str(f) for f in sorted(effects.add, key=str)) if effects.add else "",
        "removes " + ", ".join(str(f) for f in sorted(effects.delete, key=str)) if effects.delete else "",
    )))

    return await _ingest_and_learn(service, EvidenceEnvelope(
        evidence_id=evidence_id,
        source_type=source_type,
        source_id=source_id or f"{domain_id}:{evidence_id}",
        producer=producer,
        content=rendered,
        structured_data={
            "observation": observation,
            "positive": bool(getattr(example, "positive", True)),
        },
    ), domain=domain_id, quality=PRODUCED_EVIDENCE_QUALITY)


async def submit_tool_capability(tool, *, domain: str = "tools") -> "IngestionResult":
    """Project one tool's DECLARED capability into the semantic layer.

    A tool is an operator the substrate can invoke, and its parameter list is a
    precondition list in a different notation. Until this existed, the concept
    graph knew about operators Lyric had LEARNED and nothing about the 371 it
    could already perform -- so cross-domain grounding could recognise an
    unfamiliar situation as a learned rule but never as something it had a tool
    for.

    IMPORTED_KNOWLEDGE, and a root: the declaration is read from the tool
    itself, which is the origin of that claim. It is not a restatement of
    anything earlier, so it has no lineage to declare.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    name = str(getattr(tool, "name", "") or "").strip()
    if not name:
        raise ValueError(f"{type(tool).__name__} has no name; a tool with no "
                         f"identity cannot be an operator in the store")

    parameters = getattr(tool, "parameters", None) or []
    required, optional = [], []
    for parameter in parameters:
        label = str(getattr(parameter, "name", "") or "").strip()
        if not label:
            continue
        (required if getattr(parameter, "required", True) else optional).append(label)

    profile = getattr(tool, "capability_profile", None)
    provides = sorted({
        getattr(c.capability, "value", str(c.capability))
        for c in (getattr(profile, "capabilities", None) or [])
    }) if profile else []

    service = get_concept_ingestion_service()
    await service._ready()
    return await _ingest_and_learn(service, EvidenceEnvelope(
        evidence_id=_stable_id("toolcap", name),
        source_type=EvidenceSourceType.IMPORTED_KNOWLEDGE,
        source_id=f"tool:{name}",
        producer="tool_registry",
        content=(f"{name} requires {required or 'nothing'}, "
                 f"accepts {optional or 'nothing'}, provides {provides or 'nothing'}"),
        structured_data={"capability": {
            "tool": name,
            "domain": str(getattr(getattr(tool, "category", None), "value", domain)),
            "description": str(getattr(tool, "description", "") or ""),
            "safety": str(getattr(getattr(tool, "safety_level", None), "value", "")
                          or "undeclared"),
            "required": required,
            "optional": optional,
            "provides": provides,
        }},
    ), domain=domain, quality=PRODUCED_EVIDENCE_QUALITY)


#: Invocation SHAPES already submitted in this process. A tool called ten
#: thousand times with the same arguments is one observation about that tool
#: repeated, not ten thousand independent ones -- and the envelope id already
#: collapses them in the store. This only stops the redundant round trip.
_SEEN_INVOCATIONS: set = set()


async def submit_tool_invocation(
    tool_name: str,
    parameters: Dict[str, Any],
    succeeded: bool,
    *,
    category: str = "tools",
) -> Optional["IngestionResult"]:
    """Record that a tool was actually invoked, and how it went.

    Separate from the tool's declaration on purpose. A tool that is registered
    and has never run, and one that has done work, are different epistemic
    states, and a store that cannot tell them apart reports coverage it does not
    have. The declaration proposes the operator; this is what OBSERVES it.

    Keyed on the invocation SHAPE -- tool, argument names, outcome -- not on the
    argument values. Values are the instance; the shape is what recurs, and
    minting a root per value would let one tool called in a loop out-corroborate
    every other source in the store.

    Returns None when this shape has already been recorded in this process.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    name = str(tool_name or "").strip()
    if not name:
        raise ValueError("a tool invocation with no tool name has nothing to observe")

    supplied = sorted(str(k) for k in (parameters or {}))
    key = (name, tuple(supplied), bool(succeeded))
    if key in _SEEN_INVOCATIONS:
        return None
    _SEEN_INVOCATIONS.add(key)

    service = get_concept_ingestion_service()
    await service._ready()
    return await _ingest_and_learn(service, EvidenceEnvelope(
        evidence_id=_stable_id("toolobs", name, ",".join(supplied), str(bool(succeeded))),
        source_type=EvidenceSourceType.TOOL_OBSERVATION,
        source_id=f"tool:{name}",
        producer="tool_registry",
        content=(f"{name} was invoked with {supplied or 'no arguments'} and "
                 f"{'succeeded' if succeeded else 'failed'}"),
        structured_data={"capability": {
            "tool": name,
            "domain": category,
            "required": supplied,
            "provides": [f"{name}_{'succeeded' if succeeded else 'failed'}"],
        }},
    ), domain=category, quality=PRODUCED_EVIDENCE_QUALITY)


async def submit_perception(
    source: str,
    data_type: str,
    content: Dict[str, Any],
    *,
    domain: str = "substrate",
    memory_id: Optional[str] = None,
    origin: "Origin",
) -> Optional["IngestionResult"]:
    """Record a perceived state of something the substrate can name, where its
    owner's words go (`_admit_perceived`).

    PERCEPTION's live producer is health monitoring: a named component observed
    in a named condition. That is already a subject and a state -- the typed
    fields carry it, so nothing has to interpret the message text.

    Returns None when the input names no subject. A perception with nothing to
    be about is not evidence of anything, and filing it under the source name
    would make `health_monitoring` a concept.
    """
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    payload = content or {}
    subject = str(payload.get("component") or payload.get("subject") or "").strip()
    if not subject:
        return None
    state = str(payload.get("severity") or payload.get("status")
                or payload.get("state") or "").strip()

    concepts = [{"label": subject, "kind": "entity", "domains": [domain],
                 "description": str(payload.get("message") or "")[:400],
                 "relationships": [["has_status", state]] if state else []}]
    if state:
        concepts.append({"label": state, "kind": "state", "domains": [domain]})

    service = get_concept_ingestion_service()
    await service._ready()
    return await _admit_perceived(service, EvidenceEnvelope(
        evidence_id=_stable_id("percept", source, data_type, subject, state),
        source_type=EvidenceSourceType.PERCEPTION,
        source_id=f"{source}:{data_type}",
        producer=str(source),
        content=f"{subject} observed as {state or 'unspecified'} via {source}",
        structured_data={"concepts": concepts},
    ), origin=origin, domain=domain, quality=PRODUCED_EVIDENCE_QUALITY, memory_id=memory_id)


# --- richer perception modalities: sensor, image, video, audio -----------
#
# THESE ADMIT SUPPLIED DESCRIPTORS, THEY DO NOT PERCEIVE. The substrate is
# model-free, so nothing here runs a detector over pixels or a waveform: a
# camera's object detector, an EXIF header, an IoT sensor bus, or a human
# annotator produces the STRUCTURE (a value with a unit, a list of recognised
# labels, a capture time), and these turn that structure into first-class typed
# observations with PERCEPTION provenance -- the same door and the same
# fan-out-to-beliefs a taught fact takes. What is honestly claimed is that the
# substrate can HOLD and REASON OVER perceptual data it is given, not that it
# extracts meaning from raw media itself.


def _literal_concept(term: Any, domain: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """A typed-literal concept for a numeric/date term, plus its canonical surface.

    The producer door (`_read_concepts`) does not classify relation TARGETS as
    literals -- only the teaching door does -- so a sensor value declared only as
    an edge target would land as an ordinary word `94.5` rather than a quantity.
    Declaring the value as its own concept, typed exactly as the teaching door
    types it (`literal_type`/`literal_value` attributes, coarse kind quantity or
    temporal), is what keeps a measurement a measurement. Returns (None, surface)
    when the term is not a readable literal, so the caller decides whether that is
    a defect (a sensor value) or simply an untyped target (a free-text label)."""
    from core.semantics.literals import classify_literal

    lit = classify_literal(str(term))
    if lit is None:
        return None, str(term).strip()
    return ({"label": lit.canonical, "kind": lit.concept_type, "domains": [domain],
             "attributes": {"literal_type": lit.kind, "literal_value": str(lit.value)}},
            lit.canonical)


def _property_concept(value: Any, domain: str) -> Tuple[Dict[str, Any], str]:
    """A concept for one measured property value: typed literal if numeric/date,
    otherwise an ordinary entity for the value's canonical form. Unlike
    `_literal_concept` this always returns a concept, because a measured property
    (a format `png`, a codec `h264`) is a real fact whether or not it is a
    number."""
    lit, surface = _literal_concept(value, domain)
    if lit is not None:
        return lit, surface
    return {"label": surface, "kind": "entity", "domains": [domain]}, surface


def _term_like(value: Any) -> str:
    """One concept label: lowercase, with runs of punctuation as underscores.

    A perceived feature and a taught one must land on the SAME label or the
    substrate holds two concepts for one thing, so this matches the spelling the
    vision faculty uses when it names what it measured."""
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _named(items: Any) -> List[Tuple[str, Optional[float]]]:
    """Normalise a detections/events list to (label, confidence) pairs.

    Accepts bare strings (`"person"`) or dicts (`{"label": "person",
    "confidence": 0.94}`). A detector's confidence is kept as provenance on the
    concept; it is deliberately NOT folded into the belief posterior here, which
    would be claiming a calibration this producer has not earned."""
    out: List[Tuple[str, Optional[float]]] = []
    for item in items or []:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("name") or "").strip()
            conf = item.get("confidence")
        else:
            label, conf = str(item).strip(), None
        if label:
            try:
                conf = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf = None
            out.append((label, conf))
    return out


async def submit_sensor_reading(
    source: str,
    content: Dict[str, Any],
    *,
    domain: str = "sensor",
    memory_id: Optional[str] = None,
    origin: "Origin",
) -> Optional["IngestionResult"]:
    """Record one sensor reading as a typed observation, where its owner's words
    go (`_admit_perceived`).

    A reading is: a named sensor, a numeric value (a QUANTITY literal), and
    optionally the quantity it measures, a unit, and a time. The value is
    declared as a typed literal so a temperature of `94.5` is held as a quantity
    the substrate can reason over, not as the word "94.5".

    Returns None when there is no sensor to attribute the reading to or no value
    to record -- a reading about nothing is not evidence. Raises when a value IS
    given but is not a readable number: a sensor reads a magnitude, and filing a
    word under `reads` would record a measurement as a name."""
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    payload = content or {}
    sensor = str(payload.get("sensor") or payload.get("subject") or source or "").strip()
    raw_value = payload.get("value")
    if payload.get("value") is None and "reading" in payload:
        raw_value = payload.get("reading")
    if not sensor or raw_value is None:
        return None

    value_concept, value_surface = _literal_concept(raw_value, domain)
    if value_concept is None:
        raise ValueError(
            f"sensor reading value {raw_value!r} is not a readable quantity; a "
            f"sensor reads a magnitude, and admitting a word here would file a "
            f"measurement as a name")

    quantity = str(payload.get("quantity") or payload.get("measure") or "").strip()
    unit = str(payload.get("unit") or payload.get("units") or "").strip()

    rels: List[List[str]] = [["reads", value_surface]]
    concepts: List[Dict[str, Any]] = [
        {"label": sensor, "kind": "entity", "domains": [domain],
         "description": str(payload.get("message") or payload.get("location") or "")[:400]},
        value_concept,
    ]
    if quantity:
        rels.append(["measures", quantity])
        concepts.append({"label": quantity, "kind": "property", "domains": [domain]})
    if unit:
        rels.append(["reads_in", unit])
        concepts.append({"label": unit, "kind": "entity", "domains": [domain]})

    when = payload.get("at") or payload.get("observed_at")
    if when is not None:
        time_concept, time_surface = _literal_concept(when, domain)
        # Only an actual date becomes a temporal fact. An epoch float would
        # classify as a quantity, which would file the time of the reading as a
        # second magnitude -- so a non-temporal `when` is left off the graph.
        if time_concept is not None and time_concept["kind"] == "temporal":
            rels.append(["observed_at", time_surface])
            concepts.append(time_concept)

    concepts[0]["relationships"] = rels
    rendered = (f"{sensor} reads {value_surface}"
                f"{' ' + unit if unit else ''}"
                f"{' of ' + quantity if quantity else ''}")

    service = get_concept_ingestion_service()
    await service._ready()
    return await _admit_perceived(service, EvidenceEnvelope(
        evidence_id=_stable_id("sensor", source, sensor, quantity, value_surface,
                               str(when or "")),
        source_type=EvidenceSourceType.PERCEPTION,
        source_id=f"{source}:sensor",
        producer=str(source),
        content=rendered,
        structured_data={"concepts": concepts},
    ), origin=origin, domain=domain, quality=PRODUCED_EVIDENCE_QUALITY, memory_id=memory_id)


async def _submit_perceived(
    source: str,
    content: Dict[str, Any],
    *,
    data_type: str,
    domain: str,
    extra_edges: Optional[List[Tuple[str, str, List[Dict[str, Any]]]]] = None,
    memory_id: Optional[str] = None,
    origin: "Origin",
) -> Optional["IngestionResult"]:
    """Shared body for image, video and audio: an observer that perceived some
    individuals and recognised some things, admitted where its owner's words go
    (`_admit_perceived`). One body, because a sound heard and a thing seen are
    stated on one contract and must reach belief the same way.

    `extra_edges` is a list of (relation, surface, concept_dicts) the caller adds
    on top of the recognised-label edges (e.g. a video's duration). Returns None
    when nothing was recognised -- an image or clip with no labels is not, by
    itself, evidence of anything nameable."""
    from .concept_ingestion import (
        EvidenceEnvelope, EvidenceSourceType, get_concept_ingestion_service)

    payload = content or {}
    observer = str(payload.get("subject") or source or "").strip()
    detections = _named(payload.get("detections") or payload.get("objects")
                        or payload.get("labels"))
    # `properties` are facts MEASURED off the real file (dimensions, format,
    # EXIF, duration) -- distinct from `detections`, which are objects a model
    # RECOGNISED. Deterministic extraction yields the former with no model; a
    # detector yields the latter. A clip with only measured properties is still
    # a real observation of a real file, so either alone is enough to record.
    properties = payload.get("properties") or {}
    # `blobs` are perceived INDIVIDUALS: an object-like region measured off the
    # file, carrying its own features. Unlike a detection, which records that
    # the observer saw something of a description, a blob is the something: it
    # is admitted as its own concept with `isa` edges, so a rule about round red
    # things has an individual to bind to and a name can be learned for it.
    blobs = [b for b in (payload.get("blobs") or [])
             if isinstance(b, dict) and str(b.get("name") or "").strip()]
    extra = list(extra_edges or [])
    # What was heard said, sung or played is something recognised too, and a
    # hearing named only by that -- a song taught now, said of a recording
    # heard before -- is a real observation of it.
    heard = any(payload.get(k) for k in ("said", "spoken_by", "in_key", "tempo", "plays",
                                         "heard_before", "seen_before"))
    if not observer or (not detections and not properties and not extra and not blobs
                        and not heard):
        return None

    rels: List[List[str]] = []
    concepts: List[Dict[str, Any]] = [{
        "label": observer, "kind": "entity", "domains": [domain],
        "description": str(payload.get("caption") or payload.get("message") or "")[:400],
        "attributes": {k: str(v) for k, v in (
            ("uri", payload.get("uri")),
            ("sha256", payload.get("sha256")),
        ) if v},
    }]
    for label, conf in detections:
        # A RECOGNITION'S CONFIDENCE BELONGS TO THE RECOGNITION. It used to set
        # the quality of the WHOLE envelope, so `has_width 800` -- read exactly
        # off the file header -- inherited the confidence of an ORB descriptor
        # match. Measured once the instance library became durable and a
        # reference actually matched: a 0.997 match raised `has_width`'s prior
        # from 0.900 to 1.000. It could lower it just as easily. Nothing about a
        # detector's opinion bears on a number read from the file.
        rels.append(["observed", label] if conf is None
                    else ["observed", label, "positive", conf])
        concept: Dict[str, Any] = {"label": label, "kind": "entity", "domains": [domain]}
        if conf is not None:
            concept["attributes"] = {"detection_confidence": str(conf)}
        concepts.append(concept)

    for relation, value in properties.items():
        prop_concept, surface = _property_concept(value, domain)
        if not surface:
            continue
        rels.append([str(relation), surface])
        concepts.append(prop_concept)

    # HOW THE BLOBS STAND TO ONE ANOTHER, collected before the loop so each
    # blob's concept can be built once with its outgoing relations already on it.
    # This is the frame-INVARIANT structure: `larger_than` survived 48 of 48
    # geometric transforms where the size band it replaces survived 73% and the
    # position word 52%. It was computed by the describer from the beginning and
    # read by nobody.
    blob_links: Dict[str, List[List[Any]]] = {}
    for link in (payload.get("blob_relations") or []):
        subj = _term_like(str(link.get("subject") or ""))
        obj = _term_like(str(link.get("object") or ""))
        relation = str(link.get("relation") or "").strip()
        if not subj or not obj or not relation:
            continue
        sup = link.get("support")
        blob_links.setdefault(subj, []).append(
            [relation, obj, "positive",
             None if sup is None else quality_from_resolution(float(sup))])

    for blob in blobs:
        name = _term_like(blob["name"])
        rels.append(["contains", name])
        features = [_term_like(f) for f in (blob.get("isa") or []) if str(f).strip()]
        # EACH `isa` CARRIES ITS OWN SUPPORT, where the producer measured one.
        # Both of them do now. They used not to: a blob's colour was treated as
        # exact because it follows from a measurement and a stated threshold, and
        # only the SHAPE was allowed to be uncertain. That reasoning held for the
        # PHOTOGRAPH and not for the OBJECT, which is what these claims are about
        # -- measured across 1512 live sightings, the colour name survived 0% of
        # a 0.55x illuminant while the substrate acted on it every time.
        #
        # THE SIZE BAND IS NO LONGER AMONG THEM AT ALL. It is not a weak claim
        # about the object, it is a claim about the framing, and a support number
        # cannot convert one into the other. Its exact measurement stays below as
        # `occupies`, and what it was reaching for is now `larger_than`.
        #
        # The faculty reports a RESOLUTION and this maps it onto the quality
        # scale, because the floor of that scale is a coin flip and not zero.
        _support = blob.get("isa_support") or {}
        blob_rels: List[List[Any]] = [
            ["isa", f, "positive",
             None if _support.get(f) is None
             else quality_from_resolution(_support[f])]
            for f in features]
        blob_rels.extend(blob_links.get(name, ()))
        # A PROPERTY CAN CARRY ITS OWN SUPPORT TOO, and `sits` was the last
        # reading the faculty made that went out with none: it travels as a
        # property rather than as an `isa`, so it never passed through the
        # channel the rest use. Measured, the position word survived 0% of a 28%
        # translation while the substrate judged the percept ACT in 62% of those
        # sightings -- the worst remaining gap in the band once colour was
        # compensated. Properties with nothing to say still say nothing, and the
        # envelope's own quality stands for them.
        _prop_support = blob.get("property_support") or {}
        for relation, value in (blob.get("properties") or {}).items():
            prop_concept, surface = _property_concept(value, domain)
            if not surface:
                continue
            support = _prop_support.get(str(relation))
            blob_rels.append(
                [str(relation), surface] if support is None
                else [str(relation), surface, "positive",
                      quality_from_resolution(float(support))])
            concepts.append(prop_concept)
        concepts.append({
            "label": name, "kind": "entity", "domains": [domain],
            "description": " ".join(features),
            "relationships": blob_rels,
        })

    # WHAT WAS SAID, heard as the words taught, and WHOSE VOICE said it. Each
    # carries the support its naming earned, as a recognition's confidence
    # belongs to the recognition. A word said twice is one claim, at its best.
    said: Dict[str, Optional[float]] = {}
    for spoken in (payload.get("said") or []):
        word = _term_like(spoken.get("word") or "") if isinstance(spoken, dict) else ""
        if not word:
            continue
        sup = spoken.get("support")
        if word not in said or (sup is not None and (said[word] or 0.0) < float(sup)):
            said[word] = None if sup is None else float(sup)
    for word, sup in said.items():
        rels.append(["said", word] if sup is None
                    else ["said", word, "positive", quality_from_resolution(sup)])
        concepts.append({"label": word, "kind": "entity", "domains": [domain]})
    voice = payload.get("spoken_by") or {}
    person = _term_like(voice.get("person") or "") if isinstance(voice, dict) else ""
    if person:
        sup = voice.get("support")
        rels.append(["spoken_by", person] if sup is None
                    else ["spoken_by", person, "positive", quality_from_resolution(float(sup))])
        concepts.append({"label": person, "kind": "entity", "domains": [domain], "is_name": True})

    # WHAT THE MUSIC IS: the key it is in, its tempo (beats a minute, a typed
    # quantity), and the songs taught that it plays. Each carries the support
    # its measurement earned; a melody's notes stay in the percept and its
    # memory, not in edges. A key, a song and a person are NAMES, and keep
    # their words ("A major" is not the word `major`).
    keyed = payload.get("in_key") or {}
    key_label = _term_like(keyed.get("key") or "") if isinstance(keyed, dict) else ""
    if key_label:
        sup = keyed.get("support")
        rels.append(["in_key", key_label] if sup is None
                    else ["in_key", key_label, "positive", quality_from_resolution(float(sup))])
        concepts.append({"label": key_label, "kind": "entity", "domains": [domain], "is_name": True})
    paced = payload.get("tempo") or {}
    if isinstance(paced, dict) and paced.get("bpm") is not None:
        bpm_concept, bpm_surface = _literal_concept(paced["bpm"], domain)
        if bpm_concept is not None and bpm_concept["kind"] == "quantity":
            sup = paced.get("support")
            rels.append(["has_tempo", bpm_surface] if sup is None
                        else ["has_tempo", bpm_surface, "positive",
                              quality_from_resolution(float(sup))])
            concepts.append(bpm_concept)
    for played in (payload.get("plays") or []):
        title = _term_like(played.get("song") or "") if isinstance(played, dict) else ""
        if not title:
            continue
        sup = played.get("support")
        rels.append(["plays", title] if sup is None
                    else ["plays", title, "positive", quality_from_resolution(float(sup))])
        concepts.append({"label": title, "kind": "entity", "domains": [domain], "is_name": True})
    # HEARD OR SEEN BEFORE: the same sound, the same thing, as a memory already
    # holds, found by the sound or the picture itself, with the support its
    # agreement earned.
    for key, relation in (("heard_before", "same_sound_as"), ("seen_before", "same_thing_as")):
        for earlier in (payload.get(key) or []):
            other = _term_like(earlier.get("subject") or "") if isinstance(earlier, dict) else ""
            if not other or other == _term_like(observer):
                continue
            sup = earlier.get("support")
            rels.append([relation, other] if sup is None
                        else [relation, other, "positive", quality_from_resolution(float(sup))])

    for relation, surface, concept_dicts in extra:
        rels.append([relation, surface])
        concepts.extend(concept_dicts)

    when = payload.get("captured") or payload.get("at") or payload.get("captured_at")
    if when is not None:
        time_concept, time_surface = _literal_concept(when, domain)
        if time_concept is not None and time_concept["kind"] == "temporal":
            rels.append(["observed_at", time_surface])
            concepts.append(time_concept)

    concepts[0]["relationships"] = rels
    seen = ", ".join([label for label, _ in detections]
                     + [" ".join(b.get("isa") or []) for b in blobs])
    rendered = f"{observer} observed {seen} via {source}"

    service = get_concept_ingestion_service()
    await service._ready()
    return await _admit_perceived(service, EvidenceEnvelope(
        evidence_id=_stable_id(data_type, source, observer,
                               ",".join(sorted([l for l, _ in detections]
                                               + [str(b["name"]) for b in blobs])),
                               str(when or "")),
        source_type=EvidenceSourceType.PERCEPTION,
        source_id=f"{source}:{data_type}",
        producer=str(source),
        content=rendered,
        structured_data={"concepts": concepts},
    # THE ENVELOPE'S QUALITY IS THE MEASUREMENT'S, and the recognitions carry
    # their own above. This took the lowest detection confidence, on the
    # reasoning that relations "are fanned out together under one quality and a
    # batch cannot be more trustworthy than its weakest member" -- true when it
    # was written, and no longer: per-edge quality landed, the blob `isa` edges
    # already use it, and a detection stating its own confidence is strictly
    # more precise than dragging every measured property to meet it.
    ), origin=origin, domain=domain, quality=PRODUCED_EVIDENCE_QUALITY, memory_id=memory_id)


async def submit_image(
    source: str,
    content: Dict[str, Any],
    *,
    domain: str = "vision",
    memory_id: Optional[str] = None,
    origin: "Origin",
) -> Optional["IngestionResult"]:
    """Record what is known about one image, where its owner's words go.

    `content` carries STRUCTURE produced upstream, of two honest kinds:
      - `properties`: facts MEASURED off the real file with no model -- format,
        width/height, EXIF camera and capture date, sha256. Each becomes an edge
        `observer <relation> <value>` (the relation is the property's key), with
        numeric values held as typed quantities.
      - `detections`: objects a DETECTOR recognised (labels, optional confidence),
        each becoming `observer observed <label>`.
    Plus an optional `subject` (defaulting to the source), `uri`, and `captured`
    date. Either kind alone is enough; returns None when neither is present. This
    producer reads no pixels itself -- the deterministic extractor or the detector
    upstream does, and this admits their output with perception provenance."""
    return await _submit_perceived(source, content, data_type="image", domain=domain,
                                   memory_id=memory_id, origin=origin)


async def submit_video(
    source: str,
    content: Dict[str, Any],
    *,
    domain: str = "vision",
    memory_id: Optional[str] = None,
    origin: "Origin",
) -> Optional["IngestionResult"]:
    """Record what a detector/annotator recognised in one video clip, where its
    owner's words go.

    Like `submit_image`, plus temporal structure: `events` (recognised happenings,
    each a label optionally with a `confidence`) become `observer observed
    <event>` edges alongside the `detections`, and a numeric `duration` (seconds)
    is held as a typed quantity. Returns None when nothing was recognised. No
    frames are decoded here."""
    payload = content or {}
    events = _named(payload.get("events"))
    extra: List[Tuple[str, str, List[Dict[str, Any]]]] = []
    for label, conf in events:
        concept: Dict[str, Any] = {"label": label, "kind": "event", "domains": [domain]}
        if conf is not None:
            concept["attributes"] = {"detection_confidence": str(conf)}
        extra.append(("observed", label, [concept]))

    duration = payload.get("duration") or payload.get("duration_seconds")
    if duration is not None:
        dur_concept, dur_surface = _literal_concept(duration, domain)
        if dur_concept is not None and dur_concept["kind"] == "quantity":
            extra.append(("lasts", dur_surface, [dur_concept]))

    return await _submit_perceived(source, content, data_type="video", domain=domain,
                                   extra_edges=extra, memory_id=memory_id, origin=origin)


async def submit_audio(
    source: str,
    content: Dict[str, Any],
    *,
    domain: str = "hearing",
    memory_id: Optional[str] = None,
    origin: "Origin",
) -> Optional["IngestionResult"]:
    """Record what was heard in one recording, where its owner's words go.

    The same contract as an image: `properties` measured off the file (format,
    codec, rate, channels, how good the hearing was, what it rests on), each
    sound as a perceived individual under `blobs` with its own `isa` features
    and supports (a sound heard as a voice carries `isa voice`), how the sounds
    stand to one another under `blob_relations`, known sounds recognised under
    `detections`, the taught words heard under `said` and whose voice said
    them under `spoken_by`, and the music: the key it is in (`in_key`), its
    tempo (`has_tempo`, beats a minute) and the taught songs it plays
    (`plays`). A numeric `duration` is held as a typed quantity, as a video's
    is. Returns None when nothing was heard and nothing measured. No samples
    are decoded here."""
    payload = content or {}
    extra: List[Tuple[str, str, List[Dict[str, Any]]]] = []
    duration = payload.get("duration")
    if duration is not None and "lasts" not in (payload.get("properties") or {}):
        dur_concept, dur_surface = _literal_concept(duration, domain)
        if dur_concept is not None and dur_concept["kind"] == "quantity":
            extra.append(("lasts", dur_surface, [dur_concept]))
    return await _submit_perceived(source, content, data_type="audio", domain=domain,
                                   extra_edges=extra, memory_id=memory_id, origin=origin)
