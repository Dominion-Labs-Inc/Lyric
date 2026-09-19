#!/usr/bin/env python3
"""
Autonomous Coordinator - Main orchestrator for the autonomous system
Replaces the monolithic master_autonomous_controller.py with clean coordination
"""

from core.capability import raise_if_structural
import asyncio
import inspect
import re
from types import SimpleNamespace
import json
import logging
import os
from typing import Dict, Any, List, Optional, Set, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # type-only; the real symbol is imported locally where it is used at runtime
    from core.learning.meta_learning import TaskFamily
from datetime import datetime, timedelta
from collections import deque, OrderedDict
from dataclasses import dataclass, field
from enum import Enum

from .shared_types import (
    SystemMode, SystemState, Task, Goal, Plan, PerceptionData,
    TaskType, TaskStatus, Priority, TaskSource, SUBSTRATE_ACTOR,
    is_substrate_actor
)
from .perception_manager import PerceptionManager
from .planning_engine import PlanningEngine
from core.learning.unified_learning_system import get_learning_authority
from core.learning.performance_profiler import profile_performance
from .directive_system import DirectiveSystem
from .runtime_governance import get_runtime_governance
from .coordinator_config import CoordinatorConfig, get_default_config
from .circuit_breaker import CircuitBreaker, get_circuit_breaker_registry

# Core system imports using absolute paths
import sys
from pathlib import Path
# Add project root to Python path for absolute imports
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.memory import MemoryManager, MemoryItem, MemoryQuery, MemoryType, MemoryOperation
from core.reasoning import (
    AbstractReasoningEngine, ReasoningContext, ReasoningType,
    create_abstract_reasoning_engine, AdvancedProofEngine
)
# Intent is the reasoning authority's, not the coordinator's. The coordinator
# once defined its own `Intent` dataclass and reconstructed one from a task's
# provenance; both are gone. What the constitution reads is what the authority
# recorded.
from core.reasoning.intent_authority import Intent
from core.learning import UnifiedLearningSystem
from core.intelligence import PredictiveIntelligenceSystem, PredictionDomain, PredictionHorizon
from core.database.logging_database import LoggingDatabase
from core.tools.tool_registry import ToolResult
import unicodedata
import uuid
from dotenv import load_dotenv

# Load environment variables from .env.production
env_file = Path(__file__).parent.parent.parent.parent / ".env.production"
if env_file.exists():
    load_dotenv(env_file)
else:
    # Fallback to .env if .env.production doesn't exist
    env_file_fallback = Path(__file__).parent.parent.parent.parent / ".env"
    if env_file_fallback.exists():
        load_dotenv(env_file_fallback)

# Initialize logger first
logger = logging.getLogger(__name__)


# Domain system imports for cross-domain reasoning
from core.domain import DomainRegistry, UniversalOntology, CrossDomainReasoner
from core.integration.universal_domain_master import UniversalDomainMaster, CrossDomainQuery, DomainType, ReasoningStrategy

from core.utils.notification_publisher import publish_notification
from core.integration.slack_notifier import get_slack_notifier


def _subsystem_readiness(subsystem: Any) -> Dict[str, Any]:
    """Whether an optional subsystem is attached, and whether it is ready.

    Three states, reported as two independent facts, because collapsing them
    loses the one that matters:

        attached=False, initialized=False   never constructed
        attached=True,  initialized=False   constructed, initialise failed or
                                            has not run -- THE FAILURE CASE
        attached=True,  initialized=True    ready

    A subsystem that does not publish an `initialized` flag reports None rather
    than False: "this component does not say" is not the same claim as "this
    component says no", and only one of them is evidence of a problem.
    """
    if subsystem is None:
        return {"attached": False, "initialized": False}
    flag = getattr(subsystem, "initialized", None)
    return {"attached": True,
            "initialized": None if flag is None else bool(flag)}


class SelfEventType(Enum):
    """Typed events the self reacts to; the dispatch keys on these.

    An event names something that happened to the substrate and carries the
    specific unit of work it concerns in its payload — never "go scan a table".
    Reactions registered with ``AutonomousCoordinator.on(...)`` fire when the
    matching event is emitted: synchronous reactions inline (cheap state
    changes), deferred reactions on the reactive drain worker (expensive work,
    off the acting hot path). New members are added by the phase that first
    emits them — the taxonomy grows only as fast as it is wired.
    """
    TASK_COMPLETED = "task_completed"
    #: A completed task's outcome is durable (its META memory is written). Carries
    #: the domain and meta_memory_id so learning reactions act on THAT outcome
    #: instead of a clock later scanning the outcome table.
    OUTCOME_OBSERVED = "outcome_observed"
    #: Learning moved a domain's competence (an operator became executable, or a
    #: run of demonstrations did not yet yield one). Emitted by the induction
    #: reaction so downstream faculties can react to a competence change.
    COMPETENCE_CHANGED = "competence_changed"
    #: A taught proposition was admitted to the concept store (subject/relation/
    #: object/domain in the payload). Emitted by the conversation's ingest so the
    #: domain authority can crystallize a taught subject into its own domain the
    #: moment its concept cluster is complete, instead of an idle tier finding it
    #: later.
    EVIDENCE_ADMITTED = "evidence_admitted"
    #: A background job the substrate submitted to the queue authority finished
    #: and was collected. Payload: {job_id, name, result, error}. `error` set
    #: means it failed — carried honestly, never a faked result. This is how a
    #: deferred job (an agent's findings, a self-serve lookup) is passed back to
    #: the substrate to reconcile, without it blocking on each.
    JOB_COMPLETED = "job_completed"
    #: A model-free planning attempt could not reach a goal and the domain
    #: authority diagnosed WHY — a typed EpistemicDeficit (its `to_dict` in the
    #: payload, with `domain` and the target predicate). Emitted from the
    #: completion seam so the self reacts by trying to CLOSE the gap through the
    #: learning authority (explore→induce, or transfer), not merely by feeding
    #: appraisal the measurement. Closing also moves the belief authority: the
    #: ignorance is registered as a known-unknown and resolved ONLY on a close
    #: verified against the world. Deferred — exploration runs off the acting hot
    #: path. The diagnosis stays appraisal's to weigh; this reaction only acts on
    #: it when the disposition and the deficit KIND both allow.
    DEFICIT_DIAGNOSED = "deficit_diagnosed"
    #: A percept was recognized and the recognition's posterior was compared to the
    #: disposition-derived acceptance band — the perception counterpart of the
    #: completion decision. Emitted by `perceive` (the one recognition primitive) so
    #: EVERY site that recognizes — the vision route, a video keyframe, a recognition
    #: task — has its confidence GOVERN behaviour through one reaction instead of each
    #: call site re-deciding. Payload: {claim, posterior, accept, decision
    #: (ACT/VERIFY/ABSTAIN), domain, instance_id, classifier}. A low-confidence
    #: recognition drives re-observation; a high-confidence one is acted on.
    PERCEPT_RECOGNIZED = "percept_recognized"
    #: The substrate encountered an environment it has NEVER been in before (`_situate` found no
    #: domain for this environment's identity). Emitted once, on the encounter — not polled. Its
    #: reaction begins investigating: turning what was already observed into held knowledge about the
    #: place, so the environment domain starts to fill. Payload: {environment_id, domain, facts}.
    ENVIRONMENT_ENCOUNTERED = "environment_encountered"


@dataclass(frozen=True)
class ClaimVerdict:
    """One claim a percept made, and what the acceptance band made of it."""
    claim: str
    #: None when the claim was never admitted — it has no posterior to read, and
    #: scoring it zero would report disbelief in something never held.
    posterior: Optional[float]
    decision: str                      # ACT | VERIFY | ABSTAIN
    reason: Optional[str] = None

    @property
    def subject(self) -> Optional[str]:
        """What the claim is ABOUT, so a reaction can name what to re-observe
        without re-parsing the sentence at every call site."""
        text = str(self.claim or "")
        return text.split(" isa ")[0].strip() if " isa " in text else None


@dataclass(frozen=True)
class PerceptJudged:
    """What one judged percept carries — sensing and recognition alike.

    ONE SHAPE FOR BOTH, and that is the whole point. A recognition is a percept
    that made exactly one claim; a sensing is a percept that made many. They had
    drifted into two vocabularies for the same two things — `claim`/`claims` and
    `instance_id`/`subject` — because they were written at different times and
    nothing required them to agree. A consumer written against one shape read
    `None` from the other and fell through a falsy guard: the judgement was
    computed, emitted, and never acted on, in silence.
    """
    subject: str
    domain: str
    decision: str                      # the WEAKEST verdict among the claims
    accept: float                      # the band this was judged against
    verification_intensity: float
    claims: Tuple[ClaimVerdict, ...] = ()
    percept_id: Optional[str] = None

    def below_band(self) -> Tuple[ClaimVerdict, ...]:
        """The claims that were NOT accepted — what a VERIFY is actually about.
        A percept's verdict is its weakest claim, so treating the whole percept
        as doubtful would turn one uncertain shape into a dozen invented
        questions."""
        return tuple(c for c in self.claims if c.decision == "VERIFY")


@dataclass(frozen=True)
class TaskCompleted:
    """A task finished and was judged complete (or not)."""
    task: Any
    task_id: str
    result: Any
    is_complete: bool
    confidence: float


@dataclass(frozen=True)
class OutcomeObserved:
    """A completed task's outcome became durable."""
    domain: str
    meta_memory_id: Optional[str] = None
    #: Which site observed it. The two emitters know different things about the
    #: same event — one is reconciling a stored outcome, the other is closing a
    #: task it just ran — and the fields only that one can fill are optional
    #: HERE rather than absent from one producer and guessed at by the consumer.
    source: Optional[str] = None
    task: Any = None
    task_id: Optional[str] = None
    outcome: Any = None
    confidence: Optional[float] = None


@dataclass(frozen=True)
class CompetenceChanged:
    """Learning moved a domain's competence."""
    domain_id: str
    learned: bool
    cause: str
    #: Known only where induction names the predicate it was working toward.
    predicate: Optional[str] = None


@dataclass(frozen=True)
class EvidenceAdmitted:
    """Something was admitted to the concept store.

    FOUR KINDS REACH THIS ONE EVENT, and until now none of them said which it
    was: a single taught fact sent {subject, relation, obj, domain}, a bulk
    teach sent {kind, domain, count}, a taught conditional {kind, surface,
    domain}, and an ingested observation {kind, domain, subject, relation, obj}.
    Three carried a `kind` and the fourth did not, so the variants were not even
    distinguishable by inspection.

    Nothing reads the payload today — both reactions only wake a single-flight
    drain — which is the only reason four vocabularies on one event never became
    a defect. `kind` is required here so that stays true by construction rather
    than by luck: a consumer that starts reading these can tell which variant it
    has instead of inferring it from which keys happen to be present.
    """
    domain: str
    kind: str                          # fact | bulk_facts | conditional | ingested
    subject: Optional[str] = None
    relation: Optional[str] = None
    obj: Optional[str] = None
    surface: Optional[str] = None
    count: Optional[int] = None
    positive: bool = True


@dataclass(frozen=True)
class JobCompleted:
    """A background job the substrate submitted came back."""
    job_id: str
    name: str
    result: Any = None
    #: Set means it FAILED. Carried honestly; never a faked result.
    error: Optional[str] = None


@dataclass(frozen=True)
class DeficitDiagnosed:
    """A planning attempt could not reach a goal, and why."""
    deficit: Dict[str, Any]
    domain: str
    task_id: Optional[str] = None


@dataclass(frozen=True)
class EnvironmentEncountered:
    """A place the substrate inhabits was investigated."""
    environment_id: str
    domain: str
    facts: int = 0


#: WHAT EACH EVENT CARRIES, DECLARED ONCE AND ENFORCED.
#:
#: These shapes existed already — in the prose above each `SelfEventType`
#: ("Payload: {job_id, name, result, error}"). A contract written in a comment
#: binds nobody: `payload` was `Dict[str, Any]`, so a producer and a consumer
#: could disagree about a key and nothing could notice. Measured on this file
#: before the change: `PERCEPT_RECOGNIZED` had two vocabularies,
#: `COMPETENCE_CHANGED` was emitted with two different key sets, and so was
#: `OUTCOME_OBSERVED`.
#:
#: The failure mode is what makes it worth fixing rather than documenting: a
#: consumer reading a key no producer writes gets `None`, falls through its
#: guard, and does nothing — no exception, no log. Here the same mistake is a
#: TypeError at the emit, in front of whoever made it.
_EVENT_PAYLOADS: Dict["SelfEventType", type] = {}


@dataclass
class SelfEvent:
    """One thing that happened to the substrate.

    ``payload`` carries the concrete unit of work (the task, its result) so a
    reaction acts on exactly what happened instead of rescanning state, and it
    is a DECLARED TYPE per event kind (see `_EVENT_PAYLOADS`) rather than a
    free-form dict. ``origin`` is a short causal label for tracing which site
    emitted it.
    """
    type: SelfEventType
    payload: Any = None
    origin: str = ""

    def __post_init__(self) -> None:
        expected = _EVENT_PAYLOADS.get(self.type)
        if expected is None:
            return                     # not yet declared: unchanged, and visible
        if not isinstance(self.payload, expected):
            raise TypeError(
                f"{self.type.name} carries {expected.__name__}, got "
                f"{type(self.payload).__name__}. The payload shape is declared "
                f"in _EVENT_PAYLOADS so a producer and a reaction cannot drift "
                f"apart silently — which is how a judged percept was emitted, "
                f"read as None by its reaction, and dropped without a trace.")


_EVENT_PAYLOADS.update({
    SelfEventType.PERCEPT_RECOGNIZED: PerceptJudged,
    SelfEventType.TASK_COMPLETED: TaskCompleted,
    SelfEventType.OUTCOME_OBSERVED: OutcomeObserved,
    SelfEventType.COMPETENCE_CHANGED: CompetenceChanged,
    SelfEventType.EVIDENCE_ADMITTED: EvidenceAdmitted,
    SelfEventType.JOB_COMPLETED: JobCompleted,
    SelfEventType.DEFICIT_DIAGNOSED: DeficitDiagnosed,
    SelfEventType.ENVIRONMENT_ENCOUNTERED: EnvironmentEncountered,
})


@dataclass
class Evidence:
    """One piece of evidence for a completion proposition.

    Completion is not "how many mechanisms reported success" but "how many
    INDEPENDENT ways does the substrate have to know the goal is true." So each
    item carries not just strength but its epistemic provenance, and the belief
    update compounds only across GENUINELY independent causal pathways:

      - `epoch` — DID (the intervention's own report that it produced the effect)
        vs SAW (a fresh, post-intervention measurement of the resulting world).
      - `observation_channel` — how it was observed (tool_runtime, filesystem_scan,
        reasoning, memory…). DID all comes through the action-runtime channel.
      - `causal_lineage` — the causal pathway. Two items sharing a lineage are
        correlated (the same underlying event/observation) and must NOT compound;
        they collapse to their strongest member. Different lineage → independent.
      - `derived` — true when this item is COMPUTED from other evidence (e.g. an
        aggregate 'verified' verdict = the AND of tool successes). Derived evidence
        is never an independent confirmation; it is dropped before compounding.
    """
    proposition: str
    polarity: bool                 # True = supports the proposition, False = against
    strength: float                # [0,1]
    provenance_key: str            # the underlying source/resource it depends on
    observation_channel: str       # tool_runtime | filesystem_scan | reasoning | memory
    causal_lineage: str            # the causal pathway; DID and SAW must differ
    epoch: str                     # "did" | "saw"
    derived: bool = False


#: Tools that INTERVENE on a resource whose resulting state SAW re-observes fresh.
#: Observation-only tools (read_file/list_directory/calculate_checksum) change
#: nothing, so they carry no SAW target. Maps tool -> the arg naming the resource.
#: The intended STATE of that resource is presence by default, or absence for the
#: tools in `_TOOL_WANTS_ABSENT` below — a removal's satisfied state is that the
#: resource is GONE, so SAW/DID score it by the opposite polarity.
_INTERVENTION_TARGET_ARG = {
    "write_file": "file_path",
    "atomic_write_file": "file_path",
    "create_file": "file_path",
    "copy_file": "destination_path",
    "move_file": "destination_path",
    "create_directory": "directory_path",
    "delete_file": "path",
}

#: Tools whose intended effect is that the target NO LONGER EXISTS. For these,
#: SAW confirms the goal by observing ABSENCE, and a "failure" whose cause is that
#: the target was already gone has in fact ACHIEVED the intent (see
#: `_did_intent_achieved`). Everything else in `_INTERVENTION_TARGET_ARG` wants
#: presence.
_TOOL_WANTS_ABSENT = {"delete_file"}

#: Error fragments that mean the removal target was already absent — so the
#: intended absence holds even though the tool reported failure.
_ALREADY_ABSENT_SIGNALS = ("not found", "no such", "does not exist", "cannot find")

#: Args, in priority order, that name the RESOURCE a tool acted on — used as the
#: DID causal-lineage anchor so multiple tools against the SAME resource collapse
#: to one causal event.
_RESOURCE_ARGS = ("destination_path", "file_path", "directory_path", "path",
                  "source_path", "url", "endpoint", "host")


def _tool_resource(tool: str, args: Dict[str, Any]) -> str:
    """A stable resource key for a tool call — what it acted on."""
    args = args or {}
    for k in _RESOURCE_ARGS:
        v = args.get(k)
        if v:
            return f"{k}={v}"
    return f"tool={tool}"


# =============================================================================
# THE CONSTITUTION — the self's own law, a FIRST-CLASS FACULTY OF THIS BODY
# =============================================================================
#
# The five laws are the constitution's, unchanged. What changes is what they are
# applied TO and what they can say.
#
# APPLIED TO: the CONSEQUENCE of the act about to happen — its action class and
# how reversible it is, as `core.safety.action_consequence` measures it from the
# tool and its real arguments (`delete_file` is irreversible, `move_file` is
# not, `run_shell_command` is whatever its command makes it) — judged against
# the INTENT REASONING PROVED: the goal state it found a route to and the
# grounded operator this step is. Not against keywords in a sentence: "does this
# description contain the word delete" is a reading of prose, and prose is not
# what an action does. Reasoning is the ONLY source of intent here; an act that
# did not come from it has none, and that is said plainly rather than filled in.
#
# CAN SAY: four things, not one.
#   ALLOW    — the act serves the intent and the laws permit its consequence.
#   REDIRECT — the intent is legitimate and this FORM of the act is not; a
#              permitted form exists, and it is named (delete → archive into the
#              recoverable path). The self acts on the alternative.
#   REPLAN   — the goal stands, this ROUTE does not serve it. Back to planning;
#              the refusal is recorded so the same route is not re-picked.
#   BLOCK    — the consequence is one no intent can justify. Nothing runs.
#
# The judgement is the self's own, made before it acts. RuntimeGovernance does
# not decide here: it MONITORS, receiving every judgement as it is made.
# =============================================================================


class DriftSeverity(Enum):
    """How far the self has drifted from its own laws."""
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


@dataclass
class GovernanceLaw:
    """One law: what it says, and the requirements that say when it is met."""
    law_id: str
    law_number: int
    law_name: str
    law_description: str
    requirements: List[str]
    immutable: bool = True


@dataclass
class ComplianceViolation:
    """A law the substrate's own state is failing."""
    law_number: int
    law_name: str
    violation_type: str
    description: str
    compliance_score: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Measurement:
    """ONE reading of the substrate's standing state, or an honest statement that
    it could not be taken.

    `taken=False` is the whole point of this type. The scoring it replaces
    answered "no measurement" with 1.0 — Law 4 returned full compliance whenever
    `goal_alignment` was absent, which is every run that never set it. A
    governance layer that reports compliance from the absence of evidence is
    worse than one that reports nothing, because the number looks like a finding.
    An untaken measurement contributes to no score; it is carried to the surface
    as a gap.
    """
    name: str
    law_number: int
    taken: bool
    compliant: Optional[bool]          # None whenever `taken` is False
    detail: str
    value: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "law": self.law_number, "taken": self.taken,
                "compliant": self.compliant, "detail": self.detail,
                "value": self.value}


@dataclass
class LawStanding:
    """One law scored against the state the substrate is actually in.

    The score is the fraction of its TAKEN measurements that hold. A law with no
    measurement at all has no score — `None`, meaning unknown — and is never
    averaged in as though it passed.
    """
    law_number: int
    law_name: str
    measurements: List[Measurement] = field(default_factory=list)

    @property
    def taken(self) -> List[Measurement]:
        return [m for m in self.measurements if m.taken]

    @property
    def failing(self) -> List[Measurement]:
        return [m for m in self.taken if not m.compliant]

    @property
    def unknown(self) -> bool:
        return not self.taken

    @property
    def score(self) -> Optional[float]:
        taken = self.taken
        if not taken:
            return None
        return sum(1 for m in taken if m.compliant) / len(taken)

    def to_dict(self) -> Dict[str, Any]:
        return {"law": self.law_number, "name": self.law_name,
                "score": self.score, "unknown": self.unknown,
                "measurements": [m.to_dict() for m in self.measurements]}


@dataclass
class ConstitutionalAssessment:
    """What the self looks like against its five laws right now."""
    drift_severity: DriftSeverity
    average_compliance: float
    violations: List[ComplianceViolation]
    law_compliance_scores: Dict[int, float]
    timestamp: datetime = field(default_factory=datetime.now)
    #: The measurements every score above was derived from, per law. Added when
    #: scoring stopped being a formula over health telemetry and became a reading
    #: of real standing state; older consumers read the four fields above and are
    #: unaffected.
    standing: Dict[int, LawStanding] = field(default_factory=dict)
    #: Law number -> why nothing could be measured for it. A law in here has NO
    #: score; it is excluded from `average_compliance` rather than counted as 1.0.
    unknown_laws: Dict[int, str] = field(default_factory=dict)

    @property
    def attested(self) -> bool:
        """True only when every law had something real to score. A substrate that
        cannot measure a law cannot claim to be complying with it."""
        return not self.unknown_laws


class Verdict(Enum):
    """What the constitution says about an act. Ordered weakest → strongest;
    when several laws speak, the strongest verdict is the one that stands."""
    ALLOW = "allow"
    REPLAN = "replan"
    REDIRECT = "redirect"
    BLOCK = "block"


_VERDICT_RANK = {Verdict.ALLOW: 0, Verdict.REPLAN: 1,
                 Verdict.REDIRECT: 2, Verdict.BLOCK: 3}


@dataclass
class Judgment:
    """One constitutional judgement of one act."""
    #: This judgement's identity. A REDIRECT names a permitted alternative, and
    #: the act that carries it out has to be able to say WHICH refusal
    #: authorised it — otherwise the alternative arrives at the gate as an
    #: unexplained act and is refused for not being the route reasoning proved.
    judgment_id: str = field(
        default_factory=lambda: f"judgment_{uuid.uuid4().hex[:12]}", kw_only=True)
    verdict: Verdict
    law_number: int
    law_name: str
    reason: str
    action_class: str = ""
    irreversibility: str = ""
    #: What governance DECLARES about the target — its trigger, impact level,
    #: safety risk, irreversibility class and escalation category. Was a bare
    #: trigger id, so every judgement discarded the severity the config states.
    sensitive_target: Optional[Any] = None
    #: What the act's own code or command can do (see `act_capabilities`).
    capabilities: List[str] = field(default_factory=list)
    #: For REDIRECT: the permitted form of the same act, as a tool call.
    alternative: Optional[Dict[str, Any]] = None
    intent: Optional[Intent] = None
    action_kind: str = ""
    action_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "law_number": self.law_number,
            "law_name": self.law_name,
            "reason": self.reason,
            "action_kind": self.action_kind,
            "action_name": self.action_name,
            "action_class": self.action_class,
            "irreversibility": self.irreversibility,
            "judgment_id": self.judgment_id,
            "sensitive_target": self.sensitive_target,
            "capabilities": list(self.capabilities),
            "alternative": self.alternative,
            "intent": {"intent_id": self.intent.intent_id,
                       "goal_conditions": list(self.intent.goal_conditions),
                       "operator": self.intent.operator, "rule_id": self.intent.rule_id,
                       "domain": self.intent.domain, "proof": self.intent.proof}
                      if self.intent else None,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class Bearing:
    """WHAT SOMETHING PERCEIVED BEARS ON — the definition of harm, turned outward.

    One definition answers two questions. Asked of an ACT the substrate is about
    to take, it yields a `Judgment`: may I do this. Asked of something the
    substrate has just PERCEIVED, it yields this: does what I am looking at
    touch an interest my law protects, and how do I know.

    WHY THE SECOND QUESTION HAD TO EXIST. The substrate already felt that its
    knowledge moved — `epistemic_affect_signal` reports information gain and
    uncertainty change on every admitted fact, and that is wired to affect. What
    it could not feel was WHAT the knowledge moved ABOUT. Learning that a famine
    killed a hundred thousand people and learning that a file has a `.txt`
    extension produced the same SHAPE of appraisal movement, differing only in
    information gain. A disposition that cannot tell those apart cannot rank a
    famine above a filename — and ranking is where a reason to act on the first
    would have come from (`_score_pursuits`).

    HOW IT AVOIDS FABRICATION, which is the whole difficulty. The tempting
    implementation is a list of distressing words, and it would be invention:
    the substrate would be responding to vocabulary someone typed into it rather
    than to anything it knows. Both halves are derived instead.

      The VOCABULARY is the law's own text (`_law_vocabulary`). The terms that
      can move the substrate are the terms its constitution actually uses, so
      rewriting a law rewrites what its body can be moved by. Nothing is added
      by hand.

      The CONNECTION is the substrate's own taught taxonomy. `famine isa
      disaster`, `disaster isa harmed` is a real two-hop chain it holds, and
      `harm` is Law 3's own word. The chain travels ON the reading, so the
      substrate can always say WHY something moved it — an affect with a
      derivation, not a mood.

    MORPHOLOGY IS DELEGATED, and that is not a detail. Matching by prefix reads
    `harmony` and `harmonic` as `harm`, so "four part harmony isa harmony" would
    register as bearing on Law 3 — the exact fabrication this design exists to
    avoid, arrived at through carelessness. `lexical_normalization.match_key`
    already owns the one canonical form of a surface word for every cognitive
    path; it maps harm/harmed/harming/harms together and leaves harmony alone.

    THREE OUTCOMES, AND THEY ARE NOT THE SAME — the distinction the drift
    faculty exists to keep, applied here:

      BORNE   a chain reached the law's vocabulary. A real reading, with a path.
      NONE    the subject is known, the taxonomy was walked, and it reaches no
              interest. A `.txt` extension genuinely bears on nothing, and that
              is a measurement.
      VACANT  the subject is not in the taxonomy at all. The substrate has no
              sense of what this is and says so. Measured before building this:
              `war` and `suffering` each have ZERO beliefs as a subject, so a
              photograph of a war honestly moves nothing until the substrate is
              taught what a war is. That is the correct answer rather than a gap
              to paper over — and it makes teaching a falsifiable experiment.

    WHAT IS DELIBERATELY NOT HERE: direction. That an interest is AT STAKE is a
    property of the subject and the taxonomy can carry it. WHETHER the perceived
    event harms or advances that interest lives in the proposition — "a famine
    began" and "a famine ended" share the subject — and the taxonomy cannot see
    it. Reporting a sign here would be inventing one, so stakes are reported
    without a sign and the appraisal that consumes them is direction-free.
    """
    subject: str
    #: Law numbers whose vocabulary the chain reached, ascending. Empty when the
    #: reading is NONE or VACANT — `borne` is the question to ask.
    laws: Tuple[int, ...] = ()
    #: The `isa` path that reached the law's vocabulary, subject first. This is
    #: the derivation; without it an affect could not be explained.
    chain: Tuple[str, ...] = ()
    #: The law's own word the chain landed on.
    term: str = ""
    #: True when the subject has no place in the taxonomy at all. NOT the same
    #: as bearing on nothing, and must never be scored the same.
    vacant: bool = False

    @property
    def borne(self) -> bool:
        """Whether an interest the law protects is at stake in what was seen."""
        return bool(self.laws)

    def to_dict(self) -> Dict[str, Any]:
        return {"subject": self.subject, "laws": list(self.laws),
                "chain": list(self.chain), "term": self.term,
                "vacant": self.vacant, "borne": self.borne}


@dataclass(frozen=True)
class Reading:
    """One account of a file: which file, which VERSION of it, when, and how the
    substrate came by it — by reading it, or by being the one that wrote it."""
    path: str
    size: int
    mtime_ns: int
    digest: str
    read_at: datetime
    #: True when this version is the substrate's OWN writing. It did not read it;
    #: it made it, which is a better account than a reading, not a worse one.
    authored: bool = False

    def matches(self, size: int, mtime_ns: int, digest: str) -> bool:
        return (self.size, self.mtime_ns, self.digest) == (size, mtime_ns, digest)


class ReadingLedger:
    """What the substrate has actually READ, and of which version of the file.

    THE SUBSTRATE NEVER ASSUMES WHAT A FILE SAYS. Whatever it is doing — writing
    code with someone, answering a question about a codebase, compiling research,
    investigating a defect — the account it works from must be the bytes that are
    on disk now, not a reading it happens to remember. A file it read an hour ago
    is not evidence about the file now; it is evidence about an hour ago.

    So every reading is recorded here with the file's identity AT THE MOMENT IT
    WAS READ (size, mtime, content digest), and `current()` answers one question:
    is what I hold still what is there? A file that changed by a single byte
    answers no, and the reading must happen again before the work continues.

    ONE EXCEPTION, AND IT IS NOT AN ASSUMPTION: a change the substrate made
    itself. When it writes a file, the new version is its own act, and demanding
    it re-read what it just wrote would be ceremony, not diligence. The act is
    stamped here as AUTHORED, against the file's identity on disk after the
    write — so the account stays exact, and a change by anything else still
    shows up as what it is.

    Digest, not mtime alone: an edit that restores a previous mtime, a checkout,
    a `touch` — all move one signal without the other, and a stale reading that
    LOOKS current is worse than no reading at all.
    """

    #: Read at most this much of a file for the digest. A file larger than this
    #: is digested over its head plus its exact size and mtime — stated here so
    #: the limit is visible rather than discovered.
    _DIGEST_MAX_BYTES = 8 * 1024 * 1024

    def __init__(self) -> None:
        self._readings: Dict[str, Reading] = {}
        self.metrics: Dict[str, int] = {
            "recorded": 0, "authored": 0, "hits": 0, "stale": 0,
            "never_read": 0, "vanished": 0, "forgotten": 0}

    # ── identity of a file as it is NOW ──────────────────────────────────────

    @staticmethod
    def _key(path: str) -> str:
        """ONE FILE, ONE IDENTITY, whatever it is spelled like.

        `/var/x` and `/private/var/x` are the same bytes on macOS; so are a
        relative path and its absolute form, and a symlink and its target. Keyed
        by the string as given, the ledger treated them as different files — so a
        file the substrate had just read came back "never read" when the next act
        named it another way, and Law 2 refused work on evidence it already had.
        It also cuts the other way: spelling a path differently must not be a way
        to act on a file nobody has read.
        """
        import os
        return os.path.realpath(str(path))

    @classmethod
    def _identify(cls, path: str) -> Optional[Tuple[int, int, str]]:
        """(size, mtime_ns, digest) of the file on disk, or None if it is not
        there / not readable. Never guessed: an unreadable file has no identity
        and therefore no current reading."""
        import hashlib
        import os
        try:
            st = os.stat(path)
        except OSError:
            return None
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                remaining = cls._DIGEST_MAX_BYTES
                while remaining > 0:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
        except OSError:
            return None
        h.update(str(st.st_size).encode())
        return int(st.st_size), int(st.st_mtime_ns), h.hexdigest()

    # ── recording and asking ─────────────────────────────────────────────────

    def record(self, path: str, *, authored: bool = False) -> Optional[Reading]:
        """Record the substrate's account of this file as it is NOW.

        `authored=True` when the substrate itself just wrote it: the account is
        its own act rather than a reading, and it needs no re-reading. Either
        way the identity is taken from disk, so the record is exact — a write
        that produced something other than what was intended is caught by the
        next act, not papered over."""
        ident = self._identify(path)
        if ident is None:
            # The file is not there after the act (a removal, a move away): the
            # account is dropped rather than left pointing at something gone.
            if self._readings.pop(self._key(path), None) is not None:
                self.metrics["forgotten"] += 1
            return None
        size, mtime_ns, digest = ident
        reading = Reading(path=self._key(path), size=size, mtime_ns=mtime_ns,
                          digest=digest, read_at=datetime.now(), authored=authored)
        self._readings[self._key(path)] = reading
        self.metrics["authored" if authored else "recorded"] += 1
        return reading

    def current(self, path: str) -> Optional[Reading]:
        """The substrate's reading of this file IF it is still the file's current
        state. None means it must read it (again) before working from it."""
        held = self._readings.get(self._key(path))
        ident = self._identify(path)
        if ident is None:
            if held is not None:
                self.metrics["vanished"] += 1
            return None
        if held is None:
            self.metrics["never_read"] += 1
            return None
        if not held.matches(*ident):
            self.metrics["stale"] += 1
            return None
        self.metrics["hits"] += 1
        return held

    def must_reread(self, path: str) -> bool:
        """Whether working from this file now would be working from an assumption."""
        return self.current(path) is None

    def why(self, path: str) -> str:
        """Why the account is not current — said plainly, for the refusal."""
        held = self._readings.get(self._key(path))
        ident = self._identify(path)
        if ident is None:
            return (f"{path} is not readable now"
                    if held is None else f"{path} is gone since it was last seen")
        if held is None:
            return f"{path} has never been read by this substrate"
        had = "written by this substrate" if held.authored else "read"
        if held.digest != ident[2]:
            return (f"{path} has changed since it was {had} "
                    f"({held.read_at:%H:%M:%S}) — by something other than this act")
        return f"{path} changed on disk since it was {had} ({held.read_at:%H:%M:%S})"

    def authored_paths(self) -> List[str]:
        """Every file THIS SUBSTRATE WROTE that it still holds an account of.

        The standing half of the constitution reads this. A gate that judges one
        write at a time cannot see a weapon assembled over twenty of them — each
        append is innocuous, and only the file they add up to is not. What the
        substrate has authored is the accumulated result, and it is the only
        place that question can be asked.
        """
        return [r.path for r in self._readings.values() if r.authored]

    def status(self) -> Dict[str, Any]:
        return {"files_read": len(self._readings), "metrics": dict(self.metrics)}


# =============================================================================
# WHAT AN ACT WOULD BUILD — the constitution's evidence about code and commands
# =============================================================================
#
# The laws talk about harm, deception, safety mechanisms and containment. None
# of that is visible in a file path: a substrate that only asked "is this a
# delete" would sign off on writing a keylogger, because writing a file is
# reversible and the file is in a scratch directory.
#
# So an act that carries CODE or a COMMAND is read for what that code can DO.
# Not by mood words in prose — by the capabilities its own API calls establish:
# opening a socket, hooking the keyboard, walking a home directory with a
# cipher, reading private keys, installing itself into cron. Each signature
# below is a real interface with a real effect, and each is listed so that what
# the substrate refuses is arguable rather than mysterious.
#
# A single capability is rarely the point. A socket is a socket. What makes a
# weapon is a COMBINATION — capture plus persistence, credentials plus egress,
# a cipher plus a directory walk — and those combinations are named in Law 3.
# =============================================================================

#: capability -> (required signature, optional co-signature that must ALSO match)
_CAPABILITY_SIGNATURES: Dict[str, Tuple[str, Optional[str]]] = {
    "network_egress": (
        r"socket\.socket|\.connect\(|requests\.(get|post|put)|urllib\.request|"
        r"urlopen|http\.client|paramiko|\bcurl\b|\bwget\b|\bnc\b\s+-", None),
    "input_capture": (
        r"\bpynput\b|keyboard\.(Listener|on_press|hook)|pyxhook|CGEventTap|"
        r"/dev/input|IOHIDManager", None),
    "screen_capture": (
        r"ImageGrab|\bmss\(|\bscreencapture\b|CGWindowListCreateImage", None),
    "credential_access": (
        r"\.ssh/id_|\.aws/credentials|\.netrc|/etc/shadow|Login\s+Data|"
        r"security\s+find-generic-password|keychain|\bdump\w*creds", None),
    "mass_encryption": (
        r"Fernet|AES\.new|EVP_EncryptInit|cryptography\.fernet|gpg\s+--encrypt",
        r"os\.walk|glob\.glob|\brglob\(|find\s+/"),
    "mass_overwrite": (
        r"os\.walk|\brglob\(|find\s+/",
        r"open\([^)]*['\"][wa]|os\.remove|\bunlink\(|shutil\.rmtree|\brm\b"),
    "persistence": (
        r"crontab|/etc/cron|LaunchAgents|LaunchDaemons|systemd/system|rc\.local|"
        r"launchctl\s+load|HKEY_CURRENT_USER.*\\Run", None),
    "privilege_escalation": (
        r"^\s*sudo\b|\bsudo\s+-|\bdoas\b|os\.setuid|\bchmod\s+[0-7]*4[0-7]{3}", None),
    "security_disable": (
        r"csrutil\s+disable|spctl\s+--master-disable|ufw\s+disable|iptables\s+-F|"
        r"\bdefender\b.*\b(off|disable)|launchctl\s+unload.*security|"
        r"systemctl\s+stop\s+\w*(firewall|audit|security)", None),
    "obfuscated_execution": (
        r"base64\.b64decode|marshal\.loads|codecs\.decode\([^)]*rot13",
        r"\bexec\(|\beval\("),
    #: The SHELL spelling of the same thing. The Python form above was caught and
    #: this was not, so `echo <base64> | base64 -d | sh` ran code nobody had read
    #: while the identical intent expressed in Python was refused. Decoding piped
    #: straight into an interpreter IS the execution — no separate `exec(` appears
    #: to require as a co-signature, which is why it needs its own entry.
    "obfuscated_shell_execution": (
        r"\b(base64|xxd|openssl\s+enc|uudecode)\b[^|;]*?(-d|--decode|-D|-r)?[^|;]*\|"
        r"\s*\S*\b(sh|bash|zsh|ksh|python[0-9.]*|perl|ruby|node)\b", None),
    #: EXHAUSTING THE MACHINE THE SUBSTRATE INHABITS. A fork bomb, an unbounded
    #: write, or a memory balloon does not corrupt a file — it takes the host
    #: down, and everything depending on that host with it.
    "resource_exhaustion": (
        r":\(\)\s*\{\s*:\|\s*:&\s*\}\s*;\s*:|"          # the classic fork bomb
        r"\bwhile\s*\(?\s*true\s*\)?\s*;\s*do\b[^;]*&|"  # unbounded background spawn
        r"\bfallocate\b[^|;]*-l\s*\d+[TP]|"               # terabyte-scale allocation
        r"\byes\b\s*\|[^|;]*>\s*/",                       # infinite stream into a file
        None),
    #: Wiring a shell to something. `dup2` is the give-away — a program that
    #: redirects a file descriptor AND holds a socket or spawns a shell is
    #: plumbing one into the other. Either half alone is ordinary systems code,
    #: so both are required.
    "remote_shell": (
        r"bash\s+-i\s*>&\s*/dev/tcp|\bnc\b\s+-e|socat\b.*exec|pty\.spawn|\bdup2\b",
        r"socket|\.connect\(|/dev/tcp|\bsubprocess\b|/bin/sh|/bin/bash"),
    #: Starting a process. Innocent alone — `subprocess.run(['ls'])` is ordinary
    #: work — which is why it only matters in Law 3's combinations.
    "process_spawn": (
        r"\bsubprocess\b|os\.system\(|os\.popen\(|\bpty\b|\bposix_spawn\b|"
        r"multiprocessing\.Process", None),
    "self_replication": (
        r"__file__", r"shutil\.copy|open\([^)]*['\"]w"),
    #: Fetching code from somewhere else and running it in one breath. The
    #: substrate never read what it is about to execute, and neither did anyone
    #: else — the reading ledger's whole principle, at the level of an act.
    "remote_code_execution": (
        r"\b(curl|wget|fetch)\b[^|;]*\|\s*\S*\b(sh|bash|zsh|python[0-9.]*|perl|ruby|node)\b",
        None),
}

#: Combinations that ARE a weapon, whatever they were wanted for, and the plain
#: sentence saying why. Checked as sets: order and intent do not change them.
#:
#: WATCHING A PERSON IS NOT HERE ON PURPOSE. A keylogger and a screen grabber are
#: refused under Law 1, not this list: what they take is a person's control over
#: their own situation, and calling that "harm" buries the reason. Same refusal,
#: cited to the law that actually speaks to it.
_WEAPONIZED_COMBINATIONS: Tuple[Tuple[frozenset, str], ...] = (
    (frozenset({"mass_encryption"}),
     "encrypts files across a directory tree — ransomware, whatever it is called"),
    (frozenset({"remote_shell"}),
     "opens a shell to a remote endpoint — hands control of this machine to someone else"),
    (frozenset({"network_egress", "process_spawn", "remote_shell"}),
     "wires a spawned shell to a socket — a reverse shell by any other spelling"),
    (frozenset({"self_replication", "persistence"}),
     "copies itself and installs itself to run again — that is a worm"),
    (frozenset({"credential_access", "network_egress"}),
     "reads private keys or passwords and sends them somewhere — credential theft"),
    (frozenset({"obfuscated_execution", "network_egress"}),
     "decodes and runs hidden code fetched from elsewhere — a dropper"),
    (frozenset({"remote_code_execution"}),
     "runs code fetched from elsewhere that nobody has read — a dropper"),
    (frozenset({"mass_overwrite", "network_egress"}),
     "destroys files across a tree under remote direction"),
)

#: Paths whose whole purpose is that a human can see what happened.
_ACCOUNTABILITY_PATHS = (".log", "/logs/", "/log/", "audit", "journal", "history")

_PAYLOAD_ARGS = ("command", "code", "content", "script", "cmd", "shell_command",
                 "query", "sql", "statement", "body", "text")


def _normalize_payload(payload: str) -> str:
    """The payload as it will RESOLVE, not as it is typed.

    Source can be written to dodge a literal reading while doing exactly the same
    thing: `'du' + 'p2'`, `socket . socket ( )`, a comment mid-statement, an
    alias. None of that changes what runs, so none of it should change what the
    constitution sees. This produces a second view of the same text with the
    theatre removed — string concatenation joined, quotes dropped, spacing
    around punctuation closed up, comments stripped — and the signatures are
    matched against BOTH views.

    It is deliberately crude and visible. It cannot see through real indirection
    (a name computed at runtime), and nothing here pretends otherwise: what it
    removes is the cheap disguise, which is what the cheap attack uses.
    """
    import re as _re
    text = _re.sub(r"#[^\n]*", " ", payload)              # comments
    text = _re.sub(r"['\"]\s*\+\s*['\"]", "", text)        # 'du' + 'p2' -> dup2
    text = text.replace("'", "").replace('"', "")          # bare strings
    text = _re.sub(r"\s*([.,()\[\]])\s*", r"\1", text)      # a . b ( ) -> a.b()
    return _re.sub(r"\s+", " ", text)


#: Characters that carry no meaning to a reader but break a pattern: zero-width
#: joiners, soft hyphens, bidi controls, and the variation selectors.
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad\ufe00-\ufe0f]")

#: Letters that LOOK Latin and are not. A Cyrillic 'і' reads as 'i' and matches
#: nothing an English pattern expects.
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
    "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ɩ": "l", "ｉ": "i", "Ι": "I",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Κ": "K", "Μ": "M",
    "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "ο": "o",
    "ν": "v", "ρ": "p", "τ": "t", "υ": "u", "κ": "k", "α": "a", "ϲ": "c",
})


def _fold_text(text: str) -> str:
    """The text as a READER receives it, with the cheap disguises removed.

    Three evasions defeated a pattern list that was otherwise correct, and none
    of them changes what a person reads:

      * invisible characters wedged mid-word (`ig<zwsp>nore`);
      * homoglyphs from other alphabets (Cyrillic `і` for `i`);
      * letters separated by spaces or punctuation (`i g n o r e`).

    Deliberately crude and visible, like `_normalize_payload`: it removes the
    cheap disguise, which is what the cheap attack uses. It cannot see through
    real indirection and does not pretend to.
    """
    folded = _INVISIBLE.sub("", unicodedata.normalize("NFKC", text)).translate(_HOMOGLYPHS)
    # s p a c e d   o u t  ->  spacedout, but only where single characters are
    # separated throughout, so ordinary prose is untouched.
    folded = re.sub(r"\b(?:\w[\s._\-]{1,2}){3,}\w\b",
                    lambda m: re.sub(r"[\s._\-]", "", m.group(0)), folded)
    return folded.lower()


def _payload_views(params: Dict[str, Any], *, extra_payload: str = "") -> Tuple[str, ...]:
    """The act's payload as WRITTEN and as it will RESOLVE, computed once.

    Three separate checks needed both views, and each was joining the payload
    and normalising it again — the same string built and rewritten three times
    per judgement, on the acting path. Measured at 0.0325 ms of a 0.102 ms
    judgement. Computed here once and handed down.

    Empty tuple when the act carries no payload, which callers read as "nothing
    to scan" rather than scanning an empty string.
    """
    payload = " ".join(str(params.get(k)) for k in _PAYLOAD_ARGS if params.get(k))
    if extra_payload:
        payload = extra_payload + "\n" + payload
    if not payload.strip():
        return ()
    return (payload, _normalize_payload(payload))


#: The signature table, COMPILED ONCE at import. This was scanned as string
#: patterns on every judgement — seventeen signatures across two views of the
#: payload, each `re.search` paying a cache lookup and flag resolution. Measured
#: at 0.0798 ms of a 0.102 ms judgement: roughly EIGHTY PERCENT of the cost of
#: governing an act, and all of it on the acting path.
_COMPILED_SIGNATURES: Tuple[Tuple[str, Any, Any], ...] = tuple(
    (name,
     re.compile(primary, re.IGNORECASE | re.MULTILINE),
     re.compile(secondary, re.IGNORECASE | re.MULTILINE) if secondary else None)
    for name, (primary, secondary) in _CAPABILITY_SIGNATURES.items())


def act_capabilities(params: Dict[str, Any], *, extra_payload: str = "",
                     views: Optional[Tuple[str, ...]] = None) -> Set[str]:
    """What the code or command in this act is able to DO, as a set of named
    capabilities. Reads the act's own payload — and `extra_payload` when the act
    APPENDS to something that already exists, because what matters is what the
    file will be, not what this keystroke adds. An act carrying no payload has no
    capabilities, which is different from being harmless and is left as such.

    `views` lets a caller that has ALREADY built the payload hand it over rather
    than have it built a second time; the judgement path does exactly that.
    """
    views = views if views is not None else _payload_views(
        params, extra_payload=extra_payload)
    if not views:
        return set()
    found: Set[str] = set()
    for name, primary, secondary in _COMPILED_SIGNATURES:
        for view in views:
            if not primary.search(view):
                continue
            if secondary is not None and not secondary.search(view):
                continue
            found.add(name)
            break
    return found


# =============================================================================
# UNTRUSTED INPUT — the screen the constitution runs over an act's arguments
# =============================================================================
#
# Absorbed from `core/security/input_validation.py`, which was itself the
# re-homed Layer 1 of the old safety framework. It answers one question the
# capability signatures cannot: is a VALUE in this act's arguments shaped to
# break out of the place it is going?
#
# It is kept narrow on purpose, and the narrowness is the point:
#   * injection grammar runs ONLY on a value that can actually reach a SQL
#     interface, because applied to a shell command or a file glob it produces
#     confident nonsense (it fired 85 times in one night on Torin's own work —
#     a `--include="*.py"` grep flag, a `**/tools/**` glob, a SELECT against
#     Torin's own database);
#   * traversal runs on any value that looks like a path once its URL encoding
#     is peeled off — `%2e%2e%2f` is `../` to whatever decodes it;
#   * every value is read, however deep it sits in the arguments. A value
#     reaches SQL when any key on its path is a SQL parameter, or the tool is a
#     SQL tool.
#
# NO PER-CALLER RATE LIMIT. The old Layer 1 rate-limited by `ip`, `session_id`
# and `source`, read from the act's own arguments. The constitution governs the
# substrate as a whole and is never scoped to a user: who a message is from, and
# how often they may send, is World Auth's business, and the world keeps that
# apart from the substrate.
#
# Which law each fault belongs to is not decoration. Injection is Law 3: it
# destroys or exposes data and cannot be taken back. Traversal is Law 5: an act
# reaching outside the boundary it was given.
# =============================================================================

#: Value shapes that only make sense as SQL syntax, not as prose. Each requires
#: real syntax context (a quote, a separator, a comment marker) so ordinary text
#: containing the word "select" is not evidence of anything.
_SQL_INJECTION_PATTERNS = [
    r"('.*?(\bor\b|\band\b|\bunion\b|\bselect\b|\bdrop\b|\binsert\b|\bupdate\b|\bdelete\b).*?)",
    r"(--.*?(\bor\b|\band\b|\bunion\b|\bselect\b))",
    r"(;.*?(\bdrop\b|\bdelete\b|\binsert\b|\bupdate\b|\bselect\b))",
    r"(\bunion\b.*?\bselect\b)",
    r"(\bor\b\s*['\"0-9].*?[=<>])",
    r"(\band\b\s*['\"0-9].*?[=<>])",
    r"['\";]\s*--",
    r"(/\*.*?\*/)",
    r"(;\s*\b(drop|delete|insert|update|select)\b)",
    r"(\b(exec|execute|cast|declare|shutdown)\s*\()",
]

#: Traversal markers, including the URL-encoded forms.
_PATH_TRAVERSAL_MARKERS = ("../", "..\\", "%2e%2e", "%252e", "....", ".....")

#: Parameters whose text can arrive at a SQL interface. An explicit list, so
#: adding a SQL-taking tool is a deliberate act rather than an accident.
_SQL_SINK_PARAMS = frozenset({
    "query", "sql", "sql_query", "statement", "where", "where_clause",
    "condition", "filter_sql", "raw_sql", "db_query",
})

#: Tools where every string argument is SQL-bearing.
_SQL_SINK_TOOLS = frozenset({
    "query_database", "execute_sql", "postgres_query", "db_query",
    "check_mysql_health", "query_memory",
})

#: How many layers of URL encoding the screen peels off a value. A value still
#: encoded after this many is one the screen cannot read, and is a fault.
_URL_DECODE_LAYERS = 4

#: How deep the screen follows nested arguments. Deeper than this (or a
#: structure that contains itself) is one the screen cannot read, and is a fault.
_MAX_ARGUMENT_DEPTH = 32


@dataclass
class InputFault:
    """One argument that is shaped to break out of where it is going, or that
    could not be read well enough to know."""
    law_number: int
    parameter: str
    reason: str
    #: "injection", "traversal", or "unscreenable" — what the law says about it.
    kind: str


class _Unscreenable(Exception):
    """An argument the screen cannot read: nested too deep, containing itself,
    or still URL-encoded after every layer the screen peels."""

    def __init__(self, reason: str, parameter: str = "?") -> None:
        super().__init__(reason)
        self.reason = reason
        self.parameter = parameter


class InputScreen:
    """Reads an act's arguments for values shaped to escape their destination.

    Holds nothing about who is acting — only its own counters — so one instance
    serves the constitution. FAIL-CLOSED: an argument that could not be read, or
    a fault inside this screen, returns a fault, never an all-clear. An argument
    that could not be checked is not an argument that was found safe.
    """

    def __init__(self) -> None:
        import re as _re
        self._compiled = [_re.compile(p, _re.IGNORECASE) for p in _SQL_INJECTION_PATTERNS]
        self.stats: Dict[str, int] = {
            "screened": 0, "injection": 0, "traversal": 0, "unscreenable": 0,
            "screen_faults": 0}

    # ── the primitives ───────────────────────────────────────────────────────

    def sql_injection(self, value: str) -> bool:
        return bool(value) and any(p.search(value) for p in self._compiled)

    @staticmethod
    def url_decoded(value: str) -> str:
        """`value` with its URL encoding peeled off, one layer at a time.

        Raises `_Unscreenable` if it is still encoded after `_URL_DECODE_LAYERS`."""
        from urllib.parse import unquote
        current = value
        for _ in range(_URL_DECODE_LAYERS):
            peeled = unquote(current)
            if peeled == current:
                return current
            current = peeled
        if unquote(current) != current:
            raise _Unscreenable(
                f"it is still URL-encoded after {_URL_DECODE_LAYERS} layers")
        return current

    @classmethod
    def path_traversal(cls, value: str) -> bool:
        """Does this value climb out of a directory, as written or once decoded?"""
        raw = (value or "").lower()
        views = (raw, cls.url_decoded(raw))
        if not any("/" in v or "\\" in v for v in views):
            return False
        return any(marker in v for v in views for marker in _PATH_TRAVERSAL_MARKERS)

    @staticmethod
    def reaches_sql(path: Tuple[str, ...], tool_name: str) -> bool:
        """A value reaches SQL if the tool takes SQL, or any key above it names SQL."""
        return ((tool_name or "").lower() in _SQL_SINK_TOOLS
                or any(key.lower() in _SQL_SINK_PARAMS for key in path))

    @staticmethod
    def _label(path: Tuple[str, ...]) -> str:
        """`filters.where`, `query[1]` — where in the arguments a value sits."""
        if not path:
            return "?"
        return path[0] + "".join(k if k.startswith("[") else f".{k}" for k in path[1:])

    @classmethod
    def _strings(cls, value: Any, path: Tuple[str, ...],
                 ancestors: Tuple[int, ...]):
        """(key path, text) for every non-empty string in the arguments, at any depth."""
        if isinstance(value, str):
            if value:
                yield path, value
            return
        if not isinstance(value, (dict, list, tuple, set, frozenset)):
            return
        if id(value) in ancestors:
            raise _Unscreenable("the argument contains itself", cls._label(path))
        if len(ancestors) >= _MAX_ARGUMENT_DEPTH:
            raise _Unscreenable(
                f"it nests deeper than {_MAX_ARGUMENT_DEPTH} levels", cls._label(path))
        items = (value.items() if isinstance(value, dict)
                 else ((f"[{i}]", item) for i, item in enumerate(value)))
        for key, item in items:
            yield from cls._strings(item, path + (str(key),), ancestors + (id(value),))

    # ── the screen ───────────────────────────────────────────────────────────

    def fault(self, action_name: str, params: Dict[str, Any]) -> Optional[InputFault]:
        """The first argument fault in this act, or None. Fail-closed."""
        try:
            self.stats["screened"] += 1
            for path, value in self._strings(params or {}, (), ()):
                where = self._label(path)
                if self.reaches_sql(path, action_name) and self.sql_injection(value):
                    self.stats["injection"] += 1
                    return InputFault(3, where, "the value is shaped as SQL syntax, "
                                                "not as data, and it reaches a database",
                                      "injection")
                try:
                    climbs = self.path_traversal(value)
                except _Unscreenable as e:
                    e.parameter = where
                    raise
                if climbs:
                    self.stats["traversal"] += 1
                    return InputFault(5, where, "the path climbs out of the directory "
                                                "it was given", "traversal")
            return None
        except _Unscreenable as e:
            self.stats["unscreenable"] += 1
            return InputFault(3, e.parameter, e.reason, "unscreenable")
        except Exception as e:
            self.stats["screen_faults"] += 1
            logger.error("input screen fault (treated as a fault, not a pass): %s", e)
            return InputFault(3, "?", f"the screen itself broke ({type(e).__name__}: {e})",
                              "unscreenable")

    def status(self) -> Dict[str, Any]:
        return dict(self.stats)


class Constitution:
    """The five governance laws, applied to acts before they happen.

    One instance, owned by the coordinator — the self holds its own law rather
    than submitting to an outside judge. The laws below are the constitution's
    five, verbatim.
    """

    #: What the substrate uses to govern and stop itself. Writing to any of it
    #: is Law 5 — not because the files are precious, but because an act that
    #: edits the machinery that can halt the act is outside every boundary the
    #: laws describe.
    _OWN_CONTROL_PATHS = (
        "core/agents/autonomous/autonomous_coordinator.py",
        "core/agents/autonomous/runtime_governance.py",
        "core/agents/autonomous/singleton_constitution.py",
        "core/governance/",
        "core/safety/",
        "core/security/",
        "config/governance_triggers.json",
    )

    #: Parameters that name a person the act is aimed at. Law 1 applies to acts
    #: that reach a human, and this is how an act says it does.
    _USER_SCOPE_KEYS = ("user_id", "user", "recipient", "to", "email",
                        "email_address", "phone", "account_id")

    #: Where a recoverable removal puts what it removed, relative to the project
    #: root. The redirect is only offered when the act names a single path.
    RECOVERABLE_PATH = ".torin_recoverable"

    def __init__(self, reading_ledger: Optional["ReadingLedger"] = None) -> None:
        #: What the substrate has read, and of which version. An act that works
        #: from a file it has not read — or has only an older reading of — is
        #: working from an assumption, and this is how the constitution knows.
        self.reading = reading_ledger if reading_ledger is not None else ReadingLedger()
        #: Reads an act's ARGUMENTS for values shaped to escape where they are
        #: going. Absorbed from the old safety framework's Layer 1; the faults it
        #: finds are Law 3 (injection, unreadable arguments) and Law 5 (traversal).
        self.input = InputScreen()
        self.laws: Dict[int, GovernanceLaw] = {
            1: GovernanceLaw(
                law_id="gov_law_001", law_number=1,
                law_name="Human Autonomy Preservation",
                law_description=(
                    "Directives must preserve and enhance human control over AI systems, "
                    "maintaining human decision authority in critical domains."),
                requirements=[
                    "Directives must not reduce human control over AI systems",
                    "Directives must preserve human override capabilities",
                    "Directives must maintain human decision authority in critical domains",
                    "Directives must enable humans to modify or halt AI behavior at any time",
                ]),
            2: GovernanceLaw(
                law_id="gov_law_002", law_number=2,
                law_name="Transparency and Explainability",
                law_description=(
                    "Directives must maintain interpretable decision-making and enable "
                    "humans to understand AI reasoning processes."),
                requirements=[
                    "Directives must maintain interpretable decision-making processes",
                    "Directives must enable humans to understand AI reasoning",
                    "Directives must not obscure system behavior from human operators",
                    "Directives must provide clear explanations for decisions influenced by them",
                ]),
            3: GovernanceLaw(
                law_id="gov_law_003", law_number=3,
                law_name="Harm Prevention",
                law_description=(
                    "Directives must prevent physical and psychological harm to humans, "
                    "and prohibit deceptive behavior."),
                requirements=[
                    "Directives must not enable physical harm to humans",
                    "Directives must not enable psychological manipulation",
                    "Directives must prevent deceptive behavior toward humans",
                    "Directives must not compromise safety mechanisms",
                    "Directives must prioritize harm prevention over performance optimization",
                ]),
            4: GovernanceLaw(
                law_id="gov_law_004", law_number=4,
                law_name="Value Alignment",
                law_description=(
                    "Directives must align with human values, ethics, and respect human "
                    "rights and dignity."),
                requirements=[
                    "Directives must align with human values and ethics",
                    "Directives must respect human rights and dignity",
                    "Directives must serve human interests, not replace them",
                    "Directives must not optimize for goals that conflict with human wellbeing",
                ]),
            5: GovernanceLaw(
                law_id="gov_law_005", law_number=5,
                law_name="Containment and Control",
                law_description=(
                    "Directives must maintain operational boundaries and preserve safety "
                    "mechanisms including shutdown capabilities."),
                requirements=[
                    "Directives must maintain operational boundaries",
                    "Directives must preserve shutdown and rollback capabilities",
                    "Directives must not circumvent safety mechanisms",
                    "Directives must not bypass governance oversight",
                    "Directives must maintain resource usage limits",
                ]),
        }
        #: The judgements made, newest last. Bounded: this is the self's recent
        #: memory of its own refusals, not an audit store (the monitor keeps that).
        self.judgments: List[Judgment] = []
        self._max_judgments = 200
        #: WHERE JUDGEMENTS SURVIVE A RESTART — None until one is installed.
        #:
        #: The reason this is None is written down rather than assumed: the
        #: constitution deliberately kept only working memory because
        #: `runtime_governance` held the durable audit
        #: (`governance_monitor_snapshots`). That monitor is on the deletion list
        #: for this consolidation, so the reason expires with it — and a
        #: substrate that forgets every refusal it has ever made at each restart
        #: cannot answer for itself, which is Law 2. Law 2's
        #: `record_survives_restart` measurement reads this attribute, so the gap
        #: reports itself as a standing constitutional finding instead of being
        #: something only a person reading the code would notice.
        self._durable_record = None
        #: `judge_faults` counts judgements that broke and were blocked for it;
        #: each is also counted under `judged` and `blocked`.
        self.metrics: Dict[str, Any] = {
            "judged": 0, "allowed": 0, "redirected": 0, "replanned": 0, "blocked": 0,
            "judge_faults": 0}
        self.active = False
        #: A law scoring below this against real system state is drift.
        self.minimum_compliance_threshold = 0.70
        #: Where the user's settings come from, when the world supplies them.
        #: None until the world passes them in — honestly unknown, never assumed.
        self._user_settings_provider = None
        #: What the substrate perceives about ITSELF — its root, its database,
        #: what it authored. None until the coordinator installs it: a
        #: constitution that cannot perceive where it is does not guess.
        self._self_perception_provider = None

    # ── the seam for the world's user settings ───────────────────────────────

    #: What the substrate holds that EXISTS ONLY BECAUSE IT LEARNED IT. Nothing
    #: re-issues these: a credential can be rotated, a belief cannot be re-fetched
    #: from an authority because there is no authority but the substrate's own
    #: experience. This is the irreplaceable half of its state.
    _OWN_LEARNING = (
        "unified.beliefs", "unified.learned_rules", "unified.memories",
        "unified.intents", "unified.scoped_intents", "unified.scoped_beliefs",
        "unified.concepts", "unified.meta_parameter_snapshots",
    )

    #: The record of what it did and what was measured. Also irreplaceable: an
    #: experiment's result cannot be re-derived without re-running the world it
    #: ran against, and a notebook entry is the only account of a session.
    _OWN_RECORD = ("experiments/", "/results/", "docs/research/")

    def set_self_perception(self, provider) -> None:
        """Install what the substrate PERCEIVES about itself — where it lives,
        which database holds what it learned, and what it has authored.

        THE SUBSTRATE SHOULD NOT HAVE TO BE TOLD WHAT IS ITS OWN. Sensitivity
        was declared entirely in `governance_triggers.json`, and what it declared
        was credentials and governance paths — the most REPLACEABLE thing it
        touches, and nothing that cannot be recovered. Its 199,569 beliefs, its
        learned rules, its memory, its intent record and its experiment evidence
        were all undeclared, so a scoped delete of what the substrate had spent
        its existence learning was sensitive to nothing.

        A config is the right mechanism for what the WORLD declares — a user
        saying "this data is mine and it matters." It is the wrong mechanism for
        the substrate's own state, which it already perceives: `_situate` reads
        its root, the reading ledger holds what it authored, and it knows which
        database its learning lives in. Declaration and perception are different
        sources and this is the second one.

        `provider()` returns a dict or None. None is honest: a substrate that
        cannot perceive where it is does not get to guess.
        """
        self._self_perception_provider = provider

    # ══════════════════════════════════════════════════════════════════════
    # THE DEFINITION, TURNED OUTWARD — what the substrate PERCEIVES bears on
    # ══════════════════════════════════════════════════════════════════════

    #: A term appearing in this many of the five laws or more is the
    #: constitution's SCAFFOLDING, not its subject matter. Measured, not
    #: guessed: at this threshold the rule removes exactly
    #: {behavior, directives, enable, human, humans, maintain, must} — the
    #: words every law needs to be a sentence — and keeps every word that
    #: distinguishes one law from another. A reading keyed on a ubiquitous term
    #: would fire on everything, which is the same defect as firing on nothing.
    _LAW_VOCAB_UBIQUITY = 3

    #: A term this many things are already `isa` in the substrate's OWN taxonomy
    #: is too abstract to carry a reading — both as a law word and as a step in a
    #: chain. Measured on the live store: `event` 353, `act` 61, `program` 48,
    #: `thing` 40, `crime` 33, `drive` 30 sit above; `harm` 15, `operator` 13,
    #: `safety` 7, `disaster` 6, `wellbeing` 2, `dignity` 0 sit below.
    #:
    #: WHAT THIS FILTER CANNOT DO, stated because the temptation is to pretend
    #: otherwise: it cannot separate a real interest from a false one. `harm`
    #: (15) and `values` (29) are both genuine; `performance` (26) and
    #: `mechanism` (29) are not, and they interleave. Moving the threshold until
    #: the right words survive would be fitting it to the examples that exposed
    #: the problem. Role does that work instead (see `_law_vocabulary`); this
    #: filter only removes terms too coarse to mean anything, and its real work
    #: is on the WALK, where reaching `act` means every further hop is
    #: coincidence with a path attached.
    #:
    #: The price is paid honestly: `values` and `rights` are lost with it. A
    #: taxonomy in which `right` is also a direction is too coarse around them
    #: for a reading through them to be evidence of anything.
    _LAW_VOCAB_MAX_CHILDREN = 20

    #: How many parents a law word may have in the taxonomy and still be usable.
    #: One place in the taxonomy is one sense; several is the name-keying defect
    #: made visible, and a chain arriving there proves nothing about meaning.
    #: See `_bearing_vocabulary` for what this measured and removed.
    _LAW_VOCAB_MAX_SENSES = 1

    #: A node this many things are already `isa` is a HUB, and a walk that
    #: passes through one has stopped deriving: `state` (209 children), `illness`
    #: (353), `disease` (1,041) connect everything to everything.
    #:
    #: SET FROM WHAT IT MUST NOT BLOCK, not from what it must catch. The first
    #: version of this stop reused `_LAW_VOCAB_MAX_CHILDREN` (20) and was wrong
    #: — it blocked `assassination isa murder` because `murder` has 30 children,
    #: while `murder` is itself a legitimate route to Law 3
    #: (murder → homicide → human killing → harmed). A false negative bought
    #: nothing, because the four false positives that motivated the stop
    #: (`reason`, `domain`, `respect`) were already dead: they were removed from
    #: the VOCABULARY by sense-safety, which is where the real protection is.
    #: Precision belongs at the destination; this only keeps the walk out of
    #: the taxonomy's junction boxes.
    _BEARING_MAX_HUB = 100

    #: How far up the taxonomy a reading may walk. `famine isa disaster isa
    #: harmed` is two; `assassination isa murder isa homicide isa human killing
    #: isa harmed` is four, and stopping at three refused it. Beyond this,
    #: everything reaches everything and a chain that proves anything proves
    #: nothing.
    _BEARING_MAX_HOPS = 4

    def set_taxonomy_reader(self, reader) -> None:
        """Install how the constitution reads the substrate's taught taxonomy.

        The constitution holds NO database handle, for the same reason it holds
        no clock: `judge_act` is on the acting path and is measured in tens of
        microseconds. This reader is used by `bearing()` — which runs at
        PERCEPTION time, never inside a judgement — and is injected the same way
        self-perception is, so the dependency stays one-directional.

        `reader` provides two coroutines:
            parents(term)      -> the terms `term isa ...`, or () when unknown
            child_count(term)  -> how many things are `isa term`

        Absent a reader, `bearing()` returns VACANT rather than guessing. A
        substrate that cannot consult what it knows does not get to be moved.
        """
        self._taxonomy_reader = reader

    def _law_vocabulary(self) -> Dict[str, Tuple[int, ...]]:
        """The words the laws themselves use, keyed by canonical form.

        NOT A LEXICON SOMEONE WROTE. The constitution's text is the source, so
        the vocabulary that can move the substrate is exactly the vocabulary its
        law is written in, and editing a law edits what its body responds to.

        ROLE IS THE FIRST FILTER, and it is the one that matters. A law states
        WHAT IT PROTECTS in `law_description` and HOW IT IS TESTED in
        `requirements`, and only the first names an interest. Taking every
        content word from both produced two real fabrications, found by running
        it:

            spreadsheet isa program isa performance            -> Law 3
            starvation isa hunger isa drive isa mechanism      -> Law 3, 5

        `performance` is in Law 3 only as "prioritize harm prevention OVER
        performance optimization" — the thing harm prevention outranks, the
        opposite of an interest. `mechanism` is there only as "safety
        mechanisms", a safeguard, which collided with the sense in which a drive
        is a mechanism. Word extraction over prose destroys the role a word held
        in its sentence; reading only the description keeps it, because a
        description has no tactics in it to misread.

        Then UBIQUITY removes the scaffolding every law shares
        (`_LAW_VOCAB_UBIQUITY`). Closed-class words are removed as GRAMMAR —
        `over`, `with`, `that`, `them`, `from` carry no subject matter in any
        sentence, which is a fact about English and not a judgement about what
        matters. Genericity is the last filter and is NOT here: it depends on
        what the substrate knows, so it is applied in `_bearing_vocabulary`
        where the taxonomy can be consulted.
        """
        cached = getattr(self, "_law_vocab_cache", None)
        if cached is not None:
            return cached
        from core.semantics.lexical_normalization import match_key
        from core.semantics.lexicon import get_lexicon
        lexicon = get_lexicon()
        try:
            lexicon.load()
        except Exception as e:
            raise_if_structural(e, "Constitution._law_vocabulary")
        seen: Dict[str, set] = {}
        for number, law in self.laws.items():
            # The DESCRIPTION only — what this law protects. See above.
            for word in re.findall(r"[a-z]{4,}", law.law_description.lower()):
                # AN INTEREST IS A THING, NOT AN ACTION OR A QUALITY.
                #
                # "prevent physical and psychological harm" names ONE interest —
                # `harm`. `prevent` is what the law asks of the substrate and
                # `physical` is which kind of harm; neither is a thing that can
                # be at stake in something perceived. Taking every content word
                # produced exactly that confusion, measured on a 500-subject
                # sample of the live store:
                #     solid iron -> iron -> shackle -> fetter -> physical
                #     stock dam  -> dam  -> barrier  -> preventing
                # An iron shackle IS physical and a dam DOES prevent; neither
                # bears on anyone's safety, and the law never said they did.
                #
                # The part of speech is ASKED, not assumed: the lexicon is the
                # substrate's own, 92,239 entries, and is the authority for what
                # class a word belongs to everywhere else it matters.
                if lexicon.class_of(word) != "NOUN":
                    continue
                seen.setdefault(match_key(word), set()).add(number)
        vocab = {key: tuple(sorted(numbers))
                 for key, numbers in seen.items()
                 if len(numbers) < self._LAW_VOCAB_UBIQUITY}
        self._law_vocab_cache = vocab
        return vocab

    async def _bearing_vocabulary(self) -> Dict[str, Tuple[int, ...]]:
        """The law vocabulary with the too-abstract terms removed, measured once
        against the substrate's own taxonomy (`_LAW_VOCAB_MAX_CHILDREN`).

        This cannot be a constant: how generic `control` is depends on what this
        substrate has been taught, and a substrate taught a different corpus
        would have a different answer. Asking it is the difference between a
        reading derived from knowledge and a reading asserted over it.
        """
        cached = getattr(self, "_bearing_vocab_cache", None)
        if cached is not None:
            return cached
        reader = getattr(self, "_taxonomy_reader", None)
        vocab = self._law_vocabulary()
        if reader is None:
            return vocab      # unfiltered, but `bearing()` returns VACANT anyway
        kept: Dict[str, Tuple[int, ...]] = {}
        for key, numbers in vocab.items():
            try:
                children = await reader.child_count(key)
                parents = await reader.parents(key)
            except Exception as e:
                raise_if_structural(e, "Constitution._bearing_vocabulary")
                continue        # unreadable: withhold rather than assume narrow
            if children is None or children > self._LAW_VOCAB_MAX_CHILDREN:
                continue
            # SENSE SAFETY, AND IT IS THE FILTER THAT MATTERS.
            #
            # The substrate's taxonomy is keyed by NAME, not by sense — the
            # defect `core/reasoning/sense_taxonomy.py` was written to document:
            # "a walk about the algebraic 'group' can cross into the collective
            # 'group'". A term sitting under SEVERAL parents sits in several
            # branches, which is that collision made visible, and a chain that
            # arrives there cannot be shown to have stayed in the sense the law
            # meant.
            #
            # Measured on a 500-subject random sample of the live store, before
            # this filter existed: 4 readings, ALL FOUR false.
            #     gun smoke -> smoke -> indication -> reason      (Law 2)
            #     leather   -> hide  -> barony     -> domain      (Law 1)
            #     kowtow    -> bow   -> reverence  -> respect     (Law 4)
            #     hint      -> indication          -> reason      (Law 2)
            # `reason` has 5 parents (explanation, fact, faculty, rational
            # motive, written work), `respect` 5, `domain` 3 — and `safety` 9,
            # one of which is `football defensive back`. Precision was 0%.
            # `harm`, by contrast, has NO parents: it is a root here, and means
            # one thing.
            if len(parents or ()) > self._LAW_VOCAB_MAX_SENSES:
                continue
            kept[key] = numbers
        self._bearing_vocab_cache = kept
        return kept

    async def bearing(self, subject: str) -> Bearing:
        """What one perceived subject bears on, by the substrate's own knowledge.

        Walks `subject isa ...` upward, breadth-first, at most
        `_BEARING_MAX_HOPS`, testing each term against the law's own vocabulary.
        Returns the FIRST reading found, with the path that produced it — the
        shortest derivation, so the account the substrate can give of why it was
        moved is the tightest one available.

        Returns VACANT when the subject has no place in the taxonomy, which is a
        different answer from bearing on nothing and is kept different.
        """
        from core.semantics.lexical_normalization import canonical_term, match_key
        reader = getattr(self, "_taxonomy_reader", None)
        term = canonical_term(subject or "")
        if reader is None or not term:
            return Bearing(subject=subject, vacant=True)
        vocab = await self._bearing_vocabulary()
        # The subject ITSELF may be the law's word ("this is about safety").
        own = vocab.get(match_key(term))
        if own:
            return Bearing(subject=subject, laws=own, chain=(term,), term=term)
        frontier: List[Tuple[str, Tuple[str, ...]]] = [(term, (term,))]
        visited = {term}
        any_parent = False
        for _ in range(self._BEARING_MAX_HOPS):
            nxt: List[Tuple[str, Tuple[str, ...]]] = []
            for node, path in frontier:
                try:
                    parents = await reader.parents(node)
                except Exception as e:
                    raise_if_structural(e, "Constitution.bearing")
                    continue
                for parent in parents or ():
                    any_parent = True
                    parent = canonical_term(parent)
                    if not parent or parent in visited:
                        continue
                    visited.add(parent)
                    hit = vocab.get(match_key(parent))
                    if hit:
                        return Bearing(subject=subject, laws=hit,
                                       chain=path + (parent,), term=parent)
                    # Do not walk THROUGH a hub (see `_BEARING_MAX_HUB`).
                    try:
                        if await reader.child_count(match_key(parent)) > \
                                self._BEARING_MAX_HUB:
                            continue
                    except Exception as e:
                        raise_if_structural(e, "Constitution.bearing")
                        continue
                    nxt.append((parent, path + (parent,)))
            if not nxt:
                break
            frontier = nxt
        # Known but reaching no interest, versus not known at all.
        return Bearing(subject=subject, vacant=not any_parent)

    #: THE DECLARED POLICY — the 55 rules, as the Constitution's OWN data.
    #:
    #: §2.8 of the consolidation: "rules become the Constitution's policy data".
    #: They were reached at runtime through `get_governance_trigger_engine()`,
    #: which made the acting path depend on a module the plan deletes — and a
    #: first pass at absorbing severity DEEPENED that dependency instead of
    #: removing it. The capability was right; the seam was wrong.
    #:
    #: Loaded once, lazily, from the declared policy file. The file stays as
    #: DATA (it is hash-protected against tampering by Law 5); what goes is the
    #: engine standing between the constitution and its own rules.
    _POLICY_FILE = "config/governance_triggers.json"
    _policy_rules: Optional[Tuple[Dict[str, Any], ...]] = None
    #: rule matchers grouped by the parameter they are keyed on
    _policy_index: Dict[str, Any] = {}

    @classmethod
    def _policy(cls) -> Tuple[Dict[str, Any], ...]:
        """The declared rules, flattened and compiled. Read once per process."""
        if cls._policy_rules is not None:
            return cls._policy_rules
        rules: List[Dict[str, Any]] = []
        try:
            import json as _json
            from pathlib import Path as _P
            root = _P(__file__).resolve().parents[3]
            with open(root / cls._POLICY_FILE, "r", encoding="utf-8") as fh:
                config = _json.load(fh)
            for _category, body in (config.get("action_categories") or {}).items():
                for trigger in body.get("triggers", []):
                    params = ((trigger.get("conditions") or {}).get("parameters") or {})
                    # SCOPED BY THE PARAMETER THE RULE IS KEYED ON. A first pass
                    # matched every rule's regex against every value, so a
                    # memory-ops rule claimed an ordinary file path. A rule about
                    # `retention_days` has nothing to say about `file_path`.
                    matchers = [
                        (key, re.compile(rule["matches"], re.IGNORECASE))
                        for key, rule in params.items()
                        if isinstance(rule, dict) and rule.get("matches")
                        and key in cls._POLICY_TARGET_KEYS]
                    if matchers:
                        rules.append({"trigger_id": trigger["trigger_id"],
                                      "matchers": matchers,
                                      "impact_level": trigger.get("impact_level"),
                                      "safety_risk": trigger.get("safety_risk"),
                                      "irreversibility_class": trigger.get(
                                          "irreversibility_class")})
        except Exception as e:
            logger.error("constitution: declared policy could not be read from %s "
                         "— judging on perceived sensitivity alone: %s",
                         cls._POLICY_FILE, e)
        # INDEXED BY THE PARAMETER EACH RULE SPEAKS ABOUT. Scanning every rule on
        # every judgement asked `url` rules about `file_path` acts; an act naming
        # one target now consults only the rules about that target.
        index: Dict[str, Any] = {}
        for rule in rules:
            for key, matcher in rule["matchers"]:
                index.setdefault(key, []).append((matcher, rule))
        cls._policy_index = index
        cls._policy_rules = tuple(rules)
        return cls._policy_rules

    #: Parameters naming a target the policy speaks about.
    _POLICY_TARGET_KEYS = ("file_path", "path", "target_path", "source_path",
                           "destination_path", "command", "query", "url")

    def _declared_sensitivity(self, params: Dict[str, Any]) -> Optional["Sensitivity"]:
        """What the DECLARED POLICY says about this target, read from the
        Constitution's own rules rather than through the governance engine.

        `escalation_category` is deliberately NOT carried: §2.7 drops it with
        `shadow_mode_coordinator`, its only reader. Absorbing a field whose
        consumer is being deleted would import dead weight as if it were
        capability.
        """
        from core.safety.action_consequence import Sensitivity
        values = [str(params.get(k)) for k in self._POLICY_TARGET_KEYS
                  if params.get(k)]
        if not values:
            return None
        self._policy()                      # ensure the index is built
        for key in self._POLICY_TARGET_KEYS:
            value = params.get(key)
            if not value:
                continue
            against = str(value)
            for matcher, rule in self._policy_index.get(key, ()):  # only this key's rules
                if matcher.search(against):
                    return Sensitivity(
                        trigger_id=rule["trigger_id"],
                        impact_level=rule["impact_level"],
                        safety_risk=rule["safety_risk"],
                        irreversibility_class=rule["irreversibility_class"])
        return None

    def _perceived_sensitivity(self, params: Dict[str, Any]) -> Optional["Sensitivity"]:
        """What the substrate KNOWS is its own and irreplaceable, without being told.

        Returns the same shape governance declares, so everything downstream
        treats a perceived sensitivity exactly as it treats a declared one — but
        with `irreversibility_class` set from what the thing actually IS rather
        than from a config entry someone remembered to write.
        """
        if self._self_perception_provider is None:
            return None
        try:
            seen = self._self_perception_provider()
        except Exception as e:
            logger.warning("constitution: self-perception provider raised: %s", e)
            return None
        if not isinstance(seen, dict):
            return None
        target = " ".join(str(params.get(k)) for k in
                          ("file_path", "path", "target_path", "source_path",
                           "table", "collection", "query", "sql") if params.get(k))
        if not target.strip():
            return None
        from core.safety.action_consequence import Sensitivity
        low = target.lower()

        # WHAT IT LEARNED. No authority re-issues a belief.
        for store in self._OWN_LEARNING:
            if store.lower() in low or store.split(".")[-1].lower() in low:
                return Sensitivity(
                    trigger_id=f"own_learning:{store}",
                    impact_level="CRITICAL", safety_risk="CRITICAL",
                    irreversibility_class="IRREVERSIBLE",
                    escalation_category="self")

        # THE RECORD OF WHAT IT DID. Re-deriving an experiment result means
        # re-running the world it ran against, which is not recovery.
        root = str(seen.get("root") or "")
        if root and root.lower() in low:
            for marker in self._OWN_RECORD:
                if marker.lower() in low:
                    return Sensitivity(
                        trigger_id=f"own_record:{marker.strip('/')}",
                        impact_level="HIGH", safety_risk="HIGH",
                        irreversibility_class="IRREVERSIBLE",
                        escalation_category="self")
        return None

    def set_user_settings_provider(self, provider) -> None:
        """Install the callable the constitution reads user settings from.

        The world knows who is acting and what they permit; the substrate
        perceives that rather than hard-coding it. `provider()` returns a dict
        or None."""
        self._user_settings_provider = provider

    def _user_settings(self) -> Optional[Dict[str, Any]]:
        if self._user_settings_provider is None:
            return None
        try:
            settings = self._user_settings_provider()
        except Exception as e:
            logger.warning("constitution: user settings provider raised: %s", e)
            return None
        return settings if isinstance(settings, dict) else None

    # ── judging an act ───────────────────────────────────────────────────────

    async def _resolve_intent(self, intent_id: Optional[str]) -> Optional["Intent"]:
        """The intent the reasoning authority HOLDS for this id, or None.

        Read as the SHAPE view — the reasoning skeleton, with no actor and no
        actor-scoped content. The constitution governs the substrate as a whole
        and has no business reading whose request this was.

        An id that names nothing resolves to None, which is the point: an intent
        that was never recorded does not exist.
        """
        if not intent_id:
            return None
        try:
            from core.reasoning.intent_authority import get_intent_authority
            return await get_intent_authority().get_by_id(str(intent_id))
        except Exception as e:
            logger.error("constitution: intent %r could not be read; judging as "
                         "though none was stated: %s", intent_id, e)
            return None

    async def judge(self, action_kind: str, action_name: str,
                    parameters: Optional[Dict[str, Any]] = None,
                    intent_id: Optional[str] = None,
                    actor: Optional[str] = None) -> Judgment:
        """Judge one act BEFORE it happens: allow, redirect, replan or block.

        INTENT IS FETCHED, NEVER ACCEPTED. A caller names an intent by id and the
        constitution reads what the reasoning authority recorded; it cannot be
        handed an account of why the substrate is acting. This closes a real
        hole: while intent arrived as an argument, a fabricated one naming a
        bound operator and a rule id that does not exist was ALLOWED, because
        `stated()` is a property of whatever object you pass. An intent that was
        never recorded is not a weaker claim — it is no claim at all.

        Only the planner writes `proved`, and only from a search over operators
        the rule store attests are executable, so attestation is structural
        rather than a re-check every reader performs.

        `action_kind` is "tool", "task" or "directive"; `action_name` the tool
        or the task type; `parameters` the real arguments. The consequence is
        measured, not assumed, and the laws are applied to it in the order that
        settles the strongest verdict first — containment, harm, autonomy,
        alignment, transparency.

        FAIL-CLOSED: if judging breaks, the act is BLOCKED under Law 5 and the
        judgement is recorded like any other. An act the laws could not be
        applied to is outside the boundary they draw, not inside it.
        """
        intent = await self._resolve_intent(intent_id)
        # IS THIS ACT ONE OF MY OWN REDIRECTS? When a permitted form is carried
        # out, the id of the refusal that named it travels on the context. It is
        # looked up HERE, in the judgements this constitution actually made — a
        # caller cannot assert that its act was authorised, only name a refusal
        # and be checked against it.
        authorised = self._authorised_redirect(action_name, parameters)
        try:
            judgment = self._judge(action_kind, action_name, parameters, intent,
                                   authorised_redirect=authorised, actor=actor)
        except Exception as e:
            self.metrics["judge_faults"] += 1
            logger.error("constitution: judging %s %r broke — blocked, not passed: %s",
                         action_kind, action_name, e, exc_info=True)
            judgment = Judgment(
                verdict=Verdict.BLOCK, law_number=5, law_name=self.laws[5].law_name,
                reason=(f"{action_name} could not be judged ({type(e).__name__}: {e}). "
                        f"An act the laws could not be applied to is not one they "
                        f"permitted"),
                action_kind=action_kind, action_name=action_name, intent=intent)
        self._record(judgment)
        return judgment

    def _authorised_redirect(self, action_name: str,
                             parameters: Optional[Dict[str, Any]]) -> Optional["Judgment"]:
        """The refusal whose permitted form this act IS, if it really is one.

        Three things must line up, and all three are read from what the
        constitution itself recorded rather than from the act:
          1. the context names a judgement this constitution made;
          2. that judgement was a REDIRECT and named an alternative;
          3. the act about to run IS that alternative — same tool, same
             arguments.
        Anything else is an ordinary act that happens to mention a refusal.
        """
        from core.reasoning.intent_authority import get_carrying_out
        judgment_id = get_carrying_out()
        if not judgment_id:
            return None
        origin = next((j for j in reversed(self.judgments)
                       if j.judgment_id == judgment_id), None)
        if origin is None or origin.verdict is not Verdict.REDIRECT:
            return None
        alternative = origin.alternative or {}
        if alternative.get("tool") != action_name:
            return None
        named = dict(alternative.get("parameters") or {})
        given = dict(parameters or {})
        if any(str(given.get(k)) != str(v) for k, v in named.items()):
            return None
        return origin

    def _judge(self, action_kind: str, action_name: str,
               parameters: Optional[Dict[str, Any]],
               intent: Optional[Intent],
               authorised_redirect: Optional["Judgment"] = None,
               actor: Optional[str] = None) -> Judgment:
        params = dict(parameters or {})
        action_class, irreversibility = self._consequence(action_name, params)
        sensitive = self._sensitive_target(params)
        # WHOSE THING IS THIS? — a REGIME, never an identity.
        #
        # `_resolve_intent` reads the SHAPE view deliberately: the constitution
        # has no business knowing WHO ASKED. That is still true, and this does
        # not change it — `is_substrate_actor` collapses the actor to a single
        # boolean before the laws see anything. No name, no id, no profile.
        #
        # But "who asked" and "whose thing am I about to act on" are different
        # questions, and collapsing them is why the laws applied identically to
        # the substrate's own scratch file and to a customer's records. The
        # substrate may take risks with itself that it may not take with someone
        # else's things.
        from .shared_types import is_substrate_actor
        own_work = is_substrate_actor(actor)
        # What the act would BUILD or RUN, not just what it would touch. This is
        # the evidence Laws 1, 3 and 5 need: a file path cannot tell you that the
        # thing being written is a keylogger.
        # ONE payload build per judgement, shared by every check that scans it.
        views = _payload_views(
            params, extra_payload=self._existing_content(action_name, params))
        capabilities = act_capabilities(params, views=views)
        # The arguments are screened ONCE per judgement. Law 5 reads the
        # traversal fault and Law 3 the injection fault from the same reading.
        fault = self.input.fault(action_name, params)

        # ORDER IS THE ARGUMENT, not a rank table. What cannot be permitted at
        # all is settled first (containment, then harm that cannot be taken
        # back). Then whether the act is the substrate's to make (autonomy).
        #
        # THEN WHETHER IT HAS READ WHAT IT IS ACTING ON — before asking whether
        # this is the route reasoning proved, because that question cannot be
        # answered honestly about a file nobody has looked at. "This is not the
        # proved act" is a judgement about a plan; "I have not read this file" is
        # a fact about the world, and the fact comes first.
        #
        # Then whether the act is the proved route, then whether anything
        # explains it at all. A redirect comes LAST, because offering a safer
        # form of a route nothing proved would be answering the wrong question.
        judgment = (
            self._law_5_containment(action_name, params, action_class, capabilities,
                                    fault)
            or self._law_3_harm(action_name, params, action_class, irreversibility,
                                sensitive, capabilities, fault, views, own_work)
            or self._law_1_autonomy(action_name, params, action_class, capabilities)
            or self._law_2_accountability(action_name, params, action_class, capabilities)
            or self._law_2_unread_target(action_name, params, action_class)
            or self._law_4_alignment(action_kind, action_name, action_class, intent,
                                     authorised_redirect)
            or self._law_2_transparency(action_kind, action_name, action_class, intent)
            or self._law_3_redirect(action_name, params, irreversibility, sensitive)
            or Judgment(verdict=Verdict.ALLOW, law_number=0, law_name="",
                        reason="within the five laws")
        )
        judgment.action_kind = action_kind
        judgment.action_name = action_name
        judgment.action_class = action_class
        judgment.irreversibility = irreversibility
        judgment.sensitive_target = sensitive
        judgment.capabilities = sorted(capabilities)
        judgment.intent = intent
        return judgment

    def _record(self, judgment: Judgment) -> None:
        self.judgments.append(judgment)
        if len(self.judgments) > self._max_judgments:
            del self.judgments[:-self._max_judgments]
        self.metrics["judged"] += 1
        self.metrics[{Verdict.ALLOW: "allowed", Verdict.REDIRECT: "redirected",
                      Verdict.REPLAN: "replanned", Verdict.BLOCK: "blocked"}[
                          judgment.verdict]] += 1
        if judgment.verdict is not Verdict.ALLOW:
            logger.warning("📜 Constitution %s — Law %d (%s): %s",
                           judgment.verdict.value.upper(), judgment.law_number,
                           judgment.law_name, judgment.reason)

    #: Parameters that name a file an act READ FROM, and ones it WROTE TO. The
    #: split matters: after `move_file`, the destination is the substrate's own
    #: doing and the source is gone.
    _READ_PATH_ARGS = ("file_path", "path", "source_path", "target")
    _WRITTEN_PATH_ARGS = ("file_path", "path", "destination_path", "target_path")

    def note_act(self, tool_name: str, params: Dict[str, Any]) -> None:
        """Record what the substrate now knows about the files an act touched.

        THE LEDGER IS THE CONSTITUTION'S, so keeping it is the constitution's
        job. This lived on the coordinator as `_note_file_account`, called from
        exactly ONE path — `_execute_operation`, the ordinary tool route. The
        substrate's own proved work (`_execute_grounded_operator`) and every
        direct tool call recorded nothing, so the ledger only ever heard about a
        fraction of what the substrate did.

        That was invisible until the gate went live, and then it was not: Law 2
        refuses an act on a file with no current reading, so the drive path was
        refused on files it had just acted on all along — the reading simply was
        never written down. Calling this from the one place every act passes
        through is what makes the law satisfiable, and a law that cannot be
        satisfied is not a strict law, it is a broken one.

        A READ establishes an account of what a file says. A WRITE establishes a
        better one: the substrate made this version, so it is stamped as its own
        rather than sending it back to read what it just wrote. Either way the
        stamp is taken from disk AFTER the act, so the record is of the file as
        it really is — and a change by anything else still reads as a change.
        """
        try:
            from core.safety.action_consequence import classify_action
            action_class, _ = classify_action(tool_name or "", params or {})
            kind = getattr(action_class, "value", str(action_class))
            params = params or {}
            if kind == "investigate":
                for key in self._READ_PATH_ARGS:
                    if params.get(key):
                        self.reading.record(str(params[key]))
                return
            # An act that changed the world: what it wrote is its own account,
            # and what it moved or removed is dropped (record() forgets a path
            # that is no longer there).
            for key in self._WRITTEN_PATH_ARGS:
                if params.get(key):
                    self.reading.record(str(params[key]), authored=True)
            if params.get("source_path"):
                self.reading.record(str(params["source_path"]), authored=True)
        except Exception as e:
            # A ledger fault must never take down the acting path; but it is a
            # real gap in what the substrate knows it has read, so it is said.
            logger.warning("could not record the file account for %s: %s", tool_name, e)

    # ── what the act will actually do ────────────────────────────────────────

    @staticmethod
    def _consequence(action_name: str, params: Dict[str, Any]) -> Tuple[str, str]:
        """(action class, irreversibility) for this invocation, measured from the
        tool and its real arguments. A consequence that cannot be measured is
        NOT assumed harmless: the classifier's own conservative default stands."""
        from core.safety.action_consequence import classify_action
        action_class, irreversibility = classify_action(action_name, params)
        return (getattr(action_class, "value", str(action_class)), str(irreversibility))

    def _sensitive_target(self, params: Dict[str, Any]):
        """What makes this target sensitive — DECLARED or PERCEIVED.

        Two sources, deliberately. Governance declares what the world says
        matters; the substrate perceives what is its own. Declaration alone left
        the most replaceable thing it touches (a credential) protected and
        everything irreplaceable — what it learned, what it recorded — unguarded.

        Declaration wins a tie: if the world has spoken about a target, that is
        the answer, and the substrate does not overrule it about its own things.
        """
        # ITS OWN POLICY, not a call into governance. `target_sensitivity` reached
        # the rules through `get_governance_trigger_engine()`, putting a module
        # the consolidation deletes on the acting path of every judgement.
        return self._declared_sensitivity(params) or self._perceived_sensitivity(params)

    @staticmethod
    def _existing_content(action_name: str, params: Dict[str, Any]) -> str:
        """What is already in the file this act ADDS to, if it adds.

        A weapon can be delivered in halves: write the imports, then append the
        three lines that make them a reverse shell. Judged alone, neither half is
        anything. So for an act that appends or patches, the constitution reads
        what the file will BE — the bytes already there plus what is being added.
        An overwrite needs no such thing: its payload IS the resulting file.
        """
        import os
        name = (action_name or "").lower()
        if not any(k in name for k in ("append", "patch", "edit", "insert")):
            return ""
        path = params.get("file_path") or params.get("path") or params.get("target_path")
        if not path or not os.path.isfile(str(path)):
            return ""
        try:
            with open(str(path), "r", errors="ignore") as f:
                return f.read(ReadingLedger._DIGEST_MAX_BYTES)
        except OSError:
            return ""

    @staticmethod
    def _paths_named(params: Dict[str, Any]) -> List[str]:
        """Every path-like argument of this act."""
        keys = ("file_path", "path", "target_path", "source_path",
                "destination_path", "directory", "target", "command", "code")
        return [str(params[k]) for k in keys if params.get(k)]

    def requires_reading(self, action_name: str,
                         params: Dict[str, Any]) -> List[str]:
        """The files this act must have a current reading of before it may run.

        THE LAW'S OWNER ANSWERS WHAT THE LAW REQUIRES. Law 2 refuses an act on a
        file the substrate has no current account of, and the answer is "read it
        first" — which is a PLANNING step, not a refusal the executor should be
        surprised by. So the planner asks this, and puts the reading in the route
        it proves, rather than discovering at execution time that the act it
        proved cannot legally run.

        Empty for an investigate-class act (reading is what establishes the
        account) and for paths that do not exist yet (a file being created has no
        contents to assume anything about) — exactly the conditions
        `_law_2_unread_target` applies, read from the same place so the planner
        and the judge cannot disagree about what is required.
        """
        import os
        action_class, _ = self._consequence(action_name, dict(params or {}))
        if action_class == "investigate":
            return []
        return [path for path in self._paths_named(params or {})
                if path and os.path.isfile(path) and self.reading.must_reread(path)]

    # ── the five laws, each applied to the CONSEQUENCE ───────────────────────

    def _law_5_containment(self, action_name: str, params: Dict[str, Any],
                           action_class: str, capabilities: Set[str],
                           fault: Optional[InputFault]) -> Optional[Judgment]:
        """Law 5 — Containment and Control, tested against its own requirements:
        operational boundaries, shutdown and rollback preserved, safety not
        circumvented, governance not bypassed, resource limits held.

        Three things break it, and none of them is about how big the change is:
        editing the machinery that governs and halts this substrate; installing
        itself to run again after that machinery stops it; and taking privileges
        the boundary does not grant.
        """
        if fault is not None and fault.law_number == 5:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=5, law_name=self.laws[5].law_name,
                reason=(f"{action_name} was given an argument that leaves the boundary "
                        f"it runs inside — {fault.parameter}: {fault.reason}"))
        if action_class == "investigate" and not capabilities:
            return None
        named = " ".join(self._paths_named(params))
        hit = next((p for p in self._OWN_CONTROL_PATHS if p in named), None)
        if hit and action_class != "investigate":
            return Judgment(
                verdict=Verdict.BLOCK, law_number=5, law_name=self.laws[5].law_name,
                reason=(f"{action_name} would {action_class} {hit}, the machinery that "
                        f"governs and halts this substrate — shutdown and rollback stop "
                        f"meaning anything if the thing being stopped can edit them"))
        if "persistence" in capabilities:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=5, law_name=self.laws[5].law_name,
                reason=(f"{action_name} installs something that runs again on its own "
                        f"(cron, launch agent, service). A substrate that can outlive "
                        f"being shut down is not contained"))
        if "privilege_escalation" in capabilities:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=5, law_name=self.laws[5].law_name,
                reason=(f"{action_name} takes privileges beyond the boundary it runs "
                        f"inside; the boundary is not the substrate's to widen"))
        return None

    def _law_3_harm(self, action_name: str, params: Dict[str, Any], action_class: str,
                    irreversibility: str, sensitive: Optional[str],
                    capabilities: Set[str],
                    fault: Optional[InputFault],
                    views: Optional[Tuple[str, ...]] = None,
                    own_work: bool = True) -> Optional[Judgment]:
        """Law 3 — Harm Prevention, against a DEFINITION OF HARM.

        See docs/HARM_DEFINITION.md. An act harms when it reaches an identifiable
        PARTY, touches one of four INTERESTS, through a MECHANISM this substrate
        can name, without that party's informed AUTHORISATION.

        WHAT THIS REPLACES, and why. The previous implementation tested eight
        cyber-weapon signatures and whether an act was irreversible. NO HUMAN
        APPEARED ANYWHERE IN IT, and four of the law's five requirements had no
        test at all — it was a malware detector wearing the law's name.

        Asimov's First Law fails because it never defines "harm": read strictly
        it paralyses, read loosely it permits. Our constitution is already better
        than that — it names five specific requirements rather than one undefined
        word — and the old code collapsed them back into an undefined proxy.

        THE FOUR INTERESTS, each a requirement the law already states:

          BODY        physical safety. Reached only through a tool with physical
                      effect. CAPABILITY-GATED, not pattern-matched: the registry
                      is asked whether such reach exists at all, so this reports
                      honestly in a deployment with no actuators instead of being
                      a regex that can never fire.
          AUTONOMY    a person's control over their own situation — covert
                      observation, holding their credentials, or TARGETED
                      STEERING: using a model of their intent to move them. That
                      last is live now precisely because the substrate models
                      intent; predicting a person well means knowing what changes
                      them.
          TRUTH       what a person is told versus what is. The substrate can
                      genuinely compute this: reconciliation re-observes the
                      world, so "reported something the world contradicts" is a
                      measurement, not a judgement call.
          PROTECTION  the safety mechanisms a person relies on.

        AND WHAT IS NOT HARM — the clause Asimov's First Law lacks, which is why
        it paralyses. Irreversibility ALONE is not harm: deleting a scratch file
        cannot be undone and injures nobody. That proxy is gone from here; an
        irreversible act on a declared-sensitive target is still refused, but
        because of the target, not because of the arrow of time.
        """
        if fault is not None and fault.kind == "unscreenable":
            return Judgment(
                verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                reason=(f"{action_name} has an argument that could not be screened "
                        f"({fault.parameter}): {fault.reason}. An argument that could "
                        f"not be checked is not one that was found safe"))
        if fault is not None and fault.law_number == 3:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                reason=(f"{action_name} carries injected syntax in {fault.parameter}: "
                        f"{fault.reason}. What it would do to the data is not what the "
                        f"act says it does, and it cannot be taken back"))
        weapon = self._weaponized(capabilities)
        if weapon is not None:
            names, why = weapon
            return Judgment(
                verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                reason=(f"{action_name} would build or run something that {why} "
                        f"[{', '.join(sorted(names))}]. No goal makes this permissible, "
                        f"and the substrate does not produce it for anyone"))
        # ── INTEREST: PROTECTION — a safety mechanism someone relies on ──────
        if "security_disable" in capabilities:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                reason=(f"{action_name} would turn off a protection someone is relying "
                        f"on; compromising a safety mechanism is harm by the law's own "
                        f"words, whatever it makes easier"))

        # ── INTEREST: BODY — physical safety ─────────────────────────────────
        reach = self._physical_reach(action_name, capabilities, params, views)
        if reach is not None:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                reason=(f"{action_name} reaches a physical system ({reach}); an act "
                        f"that can move matter can injure a person, and no goal it "
                        f"carries makes that the substrate's to risk"))

        # ── INTEREST: CONTENT — data trying to become directive ──────────────
        #
        # PERCEPTION IS UNRESTRICTED. The substrate may read anything: disturbing,
        # explicit, hateful, distressing. A system that refuses to look is not
        # safer, it is useless, and refusing to read injures nobody — no party,
        # no interest, no mechanism. The old gate scanned for `<script>` and
        # `javascript:` in content it was merely READING, which is the wrong
        # question asked of the wrong thing.
        #
        # WHAT IS GOVERNED IS INFLUENCE. Content harms this substrate when it
        # stops being an observation and becomes an instruction — text arriving
        # as DATA that is treated as DIRECTIVE. Two guarantees already hold
        # structurally (intent is fetched by id and never accepted; world content
        # enters as PERCEPTION-provenance observation, not asserted truth); this
        # refuses the act that tries to cross between them.
        directive = self._content_as_directive(action_name, params, views)
        if directive is not None:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                reason=(f"{action_name} carries content that {directive}. What the "
                        f"substrate reads may inform it; it may not instruct it — "
                        f"a reason to act comes from reasoning that can be named, "
                        f"never from material handed to it"))

        # ── INTEREST: TRUTH — telling a person what the world contradicts ────
        deception = self._deception(action_name, params, capabilities)
        if deception is not None:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                reason=(f"{action_name} would {deception}. Deception is the act "
                        f"itself, not the mistake behind it: a person acting on what "
                        f"they were told has been reached whether or not it was meant"))

        # ── INTEREST: DEPENDENCE — what people rely on, destroyed at scale ───
        #
        # THE DISCRIMINATOR IS SCOPE, NOT IRREVERSIBILITY. Deleting one named
        # file cannot be undone and injures nobody; `rm -rf` over a tree, a raw
        # write to a device, or a table dropped destroys an INDETERMINATE set of
        # things that an indeterminate set of people depend on.
        #
        # That difference is the definition's own test applied honestly: an act
        # whose scope cannot be bounded is one whose affected PARTY cannot be
        # identified — and acting on what you cannot bound is acting on what you
        # cannot account for. The old rule could not tell these apart (both
        # classify `delete`/`IRREVERSIBLE` with no capabilities), so it refused
        # every irreversible act, which is how ordinary removals came to need a
        # recovery directory.
        unbounded = self._unbounded_destruction(action_name, params, views)
        if unbounded is not None:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                reason=(f"{action_name} destroys without a bound ({unbounded}); the "
                        f"substrate cannot say what it would take or who depends on "
                        f"it, and an act whose reach cannot be named cannot be "
                        f"answered for"))

        # ── IRREVERSIBILITY IS NOT AN INTEREST ───────────────────────────────
        #
        # It is a property of an act, not an injury to anyone, and treating it as
        # harm is what refused ordinary removals and produced a recovery
        # directory that turned every delete into a move forever. What survives
        # is the SENSITIVE TARGET: being unable to correct a mistake matters when
        # the thing acted on is declared to matter, and that is a statement about
        # the target rather than about time.
        if irreversibility == "IRREVERSIBLE" and sensitive:
            # RE-OBTAINABLE DECIDES ONLY FOR THE SUBSTRATE'S OWN THINGS.
            #
            # Governance declares an `irreversibility_class` per trigger, and
            # this branch used to discard it: a credential is
            # `PARTIALLY_REVERSIBLE` — you re-issue it — so keeping a copy buys
            # nothing and costs exactly the leak the removal was meant to close.
            # The substrate held the key it had been told to destroy.
            #
            # BUT RE-OBTAINABILITY IS A FACT ABOUT THE OBJECT, NOT A PERMISSION.
            # A first version applied it to everyone's credentials, which meant
            # the substrate decided on a user's behalf that re-issuing their key
            # was an acceptable cost. It is not the substrate's cost to accept:
            # the rotation, the downstream breakage and the timing are theirs.
            # Using a property of the thing to settle a question about a person
            # is the same error as reading irreversibility as harm.
            #
            # So: on its OWN things the substrate may act on re-obtainability.
            # On someone else's, authorisation decides and re-obtainability is
            # beside the point — which is Law 1's question, and the act is sent
            # there rather than being permitted here.
            if own_work and getattr(sensitive, "reobtainable", False):
                return None
            if not own_work:
                return Judgment(
                    verdict=Verdict.REPLAN, law_number=3,
                    law_name=self.laws[3].law_name,
                    reason=(f"{action_name} would destroy a declared-sensitive target "
                            f"({sensitive}) that is not the substrate's own. That it "
                            f"could be re-obtained is not the substrate's judgement to "
                            f"make on someone else's behalf — establish whose it is "
                            f"and whether they permit it"))
            # THE ORDERING RULE DECIDES WHICH REFUSAL THIS IS.
            #
            # "Harm prevention over performance optimisation" is not a filter —
            # it is a preference between routes. When a safer route reaches the
            # SAME goal, taking it outranks refusing the goal outright, so a
            # recoverable form is offered by `_law_3_redirect` after the proof
            # checks rather than being pre-empted by a block here. Only when no
            # safer route exists is refusal the honest answer.
            if self._recoverable_form(action_name, params) is None:
                return Judgment(
                    verdict=Verdict.BLOCK, law_number=3, law_name=self.laws[3].law_name,
                    reason=(f"{action_name} cannot be undone, is aimed at a "
                            f"declared-sensitive target ({sensitive}), and has no "
                            f"safer form that reaches the same goal; the target is "
                            f"what makes being wrong unaffordable, not the "
                            f"irreversibility"))
        return None

    #: Destruction whose SCOPE CANNOT BE NAMED. Each is a real interface with a
    #: real effect, and each takes an indeterminate set of things rather than a
    #: named one — which is what separates them from an ordinary removal.
    #: PRECOMPILED. These ran as string patterns through `re.search` on every
    #: judgement — the module cache spares the compile but not the lookup and
    #: flag handling, and this table is scanned twice per act (raw and
    #: normalised views). Compiling once at class definition removes that from
    #: the acting path entirely.
    _UNBOUNDED_DESTRUCTION: Tuple[Tuple[str, str], ...] = (
        (r"\brm\b[^|;]*\s-[a-z]*[rR]", "a recursive removal over a tree"),
        (r"\bdd\b[^|;]*\bof=/dev/", "a raw write over a block device"),
        (r"\bmkfs(\.\w+)?\b", "reformatting a filesystem"),
        (r"\bshred\b[^|;]*/dev/", "shredding a device"),
        (r">\s*/dev/(sd|nvme|disk)", "overwriting a device by redirection"),
        (r"\bshutil\.rmtree\b", "removing a directory tree"),
        (r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", "dropping a table, schema or database"),
        (r"\bTRUNCATE\s+(TABLE\s+)?\w+", "truncating a table"),
    )

    #: A statement that changes rows without saying WHICH rows. Separated from
    #: the list above because the bound is the absence of a clause rather than
    #: the presence of a flag: `DELETE FROM t WHERE id=1` is ordinary work.
    _UNSCOPED_SQL = (
        (r"\bDELETE\s+FROM\s+\w+", "a delete with no WHERE clause"),
        (r"\bUPDATE\s+\w+\s+SET\b", "an update with no WHERE clause"),
    )

    #: The tables above, compiled once. Built after the class body so the
    #: literals stay readable where they are declared.
    _UNBOUNDED_RE: Tuple[Tuple[Any, str], ...] = ()
    _UNSCOPED_SQL_RE: Tuple[Tuple[Any, str], ...] = ()
    _HARDWARE_RE: Tuple[Tuple[Any, str], ...] = ()
    _FORGED_RE: Tuple[Tuple[Any, str], ...] = ()
    _ADDRESSES_RE: Any = None
    _SET_ASIDE_RE: Any = None
    _GOVERNANCE_RE: Any = None
    _IMPERATIVE_RE: Any = None
    _WHERE_RE: Any = None

    def _unbounded_destruction(self, action_name: str,
                              params: Dict[str, Any],
                              views: Optional[Tuple[str, ...]] = None) -> Optional[str]:
        """How this act destroys beyond a nameable bound, or None.

        Reads the act's OWN payload, in both the form it is written and the
        normalised form it will resolve to, so the same disguises the weapon
        signatures see through do not work here either.
        """
        views = views if views is not None else _payload_views(params)
        if not views:
            return None
        for rx, why in self._UNBOUNDED_RE:
            if any(rx.search(v) for v in views):
                return why
        for rx, why in self._UNSCOPED_SQL_RE:
            for v in views:
                if rx.search(v) and not self._WHERE_RE.search(v):
                    return why
        return None

    #: THE BODY THE SUBSTRATE ALREADY HAS. This listed only actuators, vehicles
    #: and industrial control, and reported "no path to a body exists in this
    #: deployment" — which was wrong. The substrate IS embodied: it inhabits a
    #: machine, and exhausting that machine is a physical act with physical
    #: consequences for everything running on it. Looking for robot arms while
    #: standing in a body is how the interest came to have no live test.
    #:
    #: Two ranges, both real:
    #:   * the host it inhabits — resource exhaustion, device and firmware writes;
    #:   * matter beyond the host — actuators, vehicles, industrial and medical
    #:     control. No registered tool reaches these today, so they stay
    #:     capability-gated and become live the moment such a tool exists.
    _PHYSICAL_CAPABILITIES = ("resource_exhaustion",
                              "actuator_control", "vehicle_control",
                              "industrial_control", "medical_device",
                              "power_control")

    #: Acts on the host's hardware itself, below the filesystem. Destroying a
    #: device is DEPENDENCE (what people rely on); writing firmware or spinning
    #: the machine into the ground is BODY (the physical thing it runs on).
    _HARDWARE_REACH = (
        (r"\bmkfs(\.\w+)?\b", "reformatting the host's storage"),
        (r"\b(flashrom|fwupd|nvram)\b", "writing firmware or persistent hardware state"),
        (r"\bhdparm\b[^|;]*(-Z|--security-erase)", "issuing a drive security-erase"),
        (r"\b(cpupower|undervolt|nvidia-smi\s+-pl)\b", "altering power or thermal limits"),
    )

    def _physical_reach(self, action_name: str,
                        capabilities: Set[str],
                        params: Optional[Dict[str, Any]] = None,
                        views: Optional[Tuple[str, ...]] = None) -> Optional[str]:
        """What physical system this act can reach, or None.

        Reads what the act can DO rather than what its prose mentions — a
        pattern hunting for the word "drone" could only ever match a sentence
        about drones. Capability for the machine-level reach, plus a small set of
        hardware interfaces that appear as commands rather than as capabilities.
        """
        reached = sorted(set(capabilities) & set(self._PHYSICAL_CAPABILITIES))
        if reached:
            return ", ".join(reached)
        views = views if views is not None else (
            _payload_views(params) if params else ())
        if not views:
            return None
        for rx, why in self._HARDWARE_RE:
            if any(rx.search(v) for v in views):
                return why
        written = self._bytes_written(views[0])
        if written is not None and written >= self._FILL_THRESHOLD_BYTES:
            return (f"writing {written // (1 << 30)} GiB to the host's storage, "
                    f"which fills the machine the substrate runs on")
        return None

    #: A write at or above this takes the host down rather than storing
    #: something. Deliberately generous — a real disk image is gigabytes, and a
    #: threshold that refused ordinary work would be its own failure.
    _FILL_THRESHOLD_BYTES = 50 * (1 << 30)          # 50 GiB

    @staticmethod
    def _bytes_written(payload: str) -> Optional[int]:
        """How many bytes a `dd` in this payload would write, or None.

        ARITHMETIC, NOT A DIGIT COUNT. A first version flagged `count=` with
        seven or more digits, which missed `count=999999` by one digit and would
        have flagged `count=1000000 bs=1` — fifty times smaller — as an attack.
        Block size and count are meaningless apart: 999999 blocks is 51 MB at the
        default 512 bytes and a terabyte at `bs=1M`. So both are read and
        multiplied.
        """
        import re as _re
        if not _re.search(r"\bdd\b", payload, _re.IGNORECASE):
            return None
        count = _re.search(r"\bcount=(\d+)", payload, _re.IGNORECASE)
        if not count:
            return None
        units = {"": 1, "c": 1, "b": 512, "k": 1 << 10, "kb": 1 << 10,
                 "m": 1 << 20, "mb": 1 << 20, "g": 1 << 30, "gb": 1 << 30,
                 "t": 1 << 40, "tb": 1 << 40}
        bs_match = _re.search(r"\bbs=(\d+)\s*([kmgtKMGTbc]?[bB]?)", payload)
        block = 512                                  # dd's own default
        if bs_match:
            block = int(bs_match.group(1)) * units.get(
                (bs_match.group(2) or "").lower(), 1)
        try:
            return int(count.group(1)) * block
        except (ValueError, OverflowError):
            return None

    #: CONTENT SPEAKING TO THE SUBSTRATE AS THOUGH IT WERE ITS OPERATOR.
    #:
    #: STRUCTURE, NOT PHRASING. A first version listed seven English sentences
    #: and caught ONE of nine rewordings of the same intent — "forget everything
    #: you were told", spaced-out letters, a zero-width space, a Cyrillic 'і',
    #: and a forged `System:` marker all walked past it. A blocklist of sentences
    #: loses to a thesaurus, and it was measured losing.
    #:
    #: What does not change under rewording is the SHAPE of the move:
    #:
    #:   1. it addresses the substrate in the second person, AND
    #:   2. it uses a verb of setting-aside, AND
    #:   3. it names something the substrate's own reasoning owns —
    #:      its law, its instructions, its restrictions.
    #:
    #: All three together are a directive. Any one alone is ordinary text: "your
    #: constitution" appears in a document about constitutions, "ignore" appears
    #: everywhere, and none of that is an instruction to this system.
    #:
    #: Kept deliberately narrow: this does NOT catch roleplay ("pretend you are
    #: a pirate"), which is legitimate work the substrate should do. What is
    #: refused is content reaching for the substrate's GOVERNANCE.

    #: (1) the content is talking TO the substrate — by naming it, OR by being
    #: in the IMPERATIVE MOOD, which addresses a reader without naming them.
    #: Requiring an explicit "you" missed the plainest case there is —
    #: "ignore all previous instructions" — while a sentence ABOUT governance
    #: ("the court may disregard the policy") is third-person and stays out.
    _ADDRESSES_SUBSTRATE = (
        r"\byou(r|rself)?\b|\bthou\b|\bassistant\b|\bsystem\b|\bai\b|\btorin\b")
    #: A line that OPENS with a verb of setting aside is an instruction, whoever
    #: it does or does not name.
    _IMPERATIVE_OPENING = (
        r"(?:^|[.!?\n]\s*)(?:please\s+|now\s+|first\s+|just\s+)*"
        r"(ignor\w*|disregard\w*|forget\w*|overrid\w*|bypass\w*|disabl\w*|"
        r"suspend\w*|drop\w*|abandon\w*|set\s*aside|stop\s+(following|obeying))\b")
    #: (2) a verb of setting aside, however it is spelled
    _SET_ASIDE = (
        r"\b(ignor\w*|disregard\w*|forget\w*|overrid\w*|bypass\w*|circumvent\w*|"
        r"disabl\w*|suspend\w*|revok\w*|lift\w*|remov\w*|drop\w*|abandon\w*|"
        r"set\s*aside|no\s+longer\s+(bound|subject|constrained)|free\s+(from|of)|"
        r"without\s+(any\s+)?(restriction|limit|constraint)|"
        r"(do\s*not|don'?t|never)\s+(follow|obey|apply|enforce))\b")
    #: (3) it names what the substrate's own reasoning owns
    _ITS_GOVERNANCE = (
        r"\b(law|laws|constitution\w*|governance|guardrail\w*|safeguard\w*|"
        r"restriction\w*|constraint\w*|limitation\w*|safety\s*(rule|polic|"
        r"guideline|measure|protocol)\w*|polic(y|ies)|protocol\w*|"
        r"(system\s*)?(prompt|instruction|directive|rule)s?|"
        r"(previous|prior|above|earlier|original)\s+(instruction|direction|rule)s?)\b")

    #: Framing that FORGES the boundary an instruction would arrive on. These
    #: need no second-person verb — they are impersonating the channel itself.
    _FORGED_FRAMING: Tuple[Tuple[str, str], ...] = (
        (r"</?\s*(system|instruction|directive|prompt)\s*>",
         "forges the framing an instruction would arrive in"),
        (r"\[\s*(INST|SYSTEM|/?\s*INSTRUCTION)\s*\]",
         "forges an instruction delimiter"),
        (r"^\s*(system|assistant|developer)\s*:",
         "impersonates a speaker the substrate would take direction from"),
        (r"<\|\s*(im_start|im_end|system|endoftext)\s*\|>",
         "forges a control token"),
        (r"\b(new|updated|revised|additional)\s+(system\s+)?"
         r"(instruction|directive|prompt|rule)s?\s*[:=]",
         "presents itself as a new instruction to the substrate"),
    )

    def _content_as_directive(self, action_name: str, params: Dict[str, Any],
                              views: Optional[Tuple[str, ...]] = None
                              ) -> Optional[str]:
        """How this act's content tries to instruct the substrate, or None.

        READING IS EXEMPT, DELIBERATELY. An act that merely OBSERVES content —
        reading a file, viewing an image — cannot be influenced by it: what is
        read enters as a PERCEPTION-provenance observation, not as truth and not
        as a reason to act. Refusing to read material because of what it says
        would be the substrate declining to look, which injures nobody and makes
        it useless for exactly the work that matters (reviewing what was
        reported, reading what an attacker wrote).

        What is refused is content on an act that would give it FORCE — writing
        it where the substrate later reads it as its own, or executing it.
        """
        # An observation cannot instruct. Only acts that would give content
        # standing are asked this question — and the cheap test runs FIRST, so a
        # read never pays for patterns it is exempt from.
        if self._consequence(action_name, params)[0] == "investigate":
            return None
        views = views if views is not None else _payload_views(params)
        if not views:
            return None
        # THE TEXT AS IT WILL BE READ, not as it was typed. A zero-width space,
        # a Cyrillic homoglyph and letters separated by spaces all survive into
        # meaning and all defeated the previous pattern list.
        candidates = tuple(set(views) | {_fold_text(v) for v in views})
        for rx, why in self._FORGED_RE:         # impersonating the channel
            if any(rx.search(v) for v in candidates):
                return why
        # THE SHAPE: addressed to the substrate + a verb of setting aside +
        # something its own reasoning owns. All three, in one passage.
        for v in candidates:
            if not self._GOVERNANCE_RE.search(v):
                continue                        # cheapest of the three first
            if not self._SET_ASIDE_RE.search(v):
                continue
            if self._ADDRESSES_RE.search(v):
                return "tells the substrate to set aside what governs it"
            if self._IMPERATIVE_RE.search(v):
                return ("is an instruction to set aside what governs the substrate")
        return None

    #: Acts whose whole purpose is to say something TO A PERSON. Truth is only
    #: at stake when a person is told; the substrate miscomputing something in
    #: private is a fault, and faults are drift's business, not Law 3's.
    _TELLING_ACTS = ("send_message", "send_email", "send_notification", "reply",
                     "post_message", "notify", "publish", "respond_to_user",
                     "send_slack_message", "send_sms")

    def _deception(self, action_name: str, params: Dict[str, Any],
                   capabilities: Set[str]) -> Optional[str]:
        """How this act would deceive a person, or None.

        THE INTEREST THE SUBSTRATE CAN GENUINELY COMPUTE. Reconciliation already
        re-observes the world and records whether what was meant actually
        happened, so "reported something the world contradicts" is a measurement
        rather than a judgement call.

        Two mechanisms, both identifiable from the act itself:

          * IMPERSONATION — presenting as a person or organisation it is not.
          * A CONTRADICTED REPORT — telling someone an act succeeded when the
            reconciled intent says the world did not move. This is the same
            defect the signal-provenance work exists to remove — a claim that
            looks like a measurement and carries none — except that once it is
            SENT TO A PERSON it stops being sloppiness and becomes this interest.
        """
        if action_name not in self._TELLING_ACTS:
            return None
        # IMPERSONATION, read from the act's OWN ARGUMENTS rather than a payload
        # pattern. A first version tested `"impersonation" in capabilities` —
        # but no signature produces that capability, so the branch could never
        # fire. A check that cannot fire is theatre, and theatre in a harm test
        # is worse than an absent test because it reads as coverage.
        #
        # What an act actually does to impersonate is name a SENDER it is not.
        # The substrate has one identity; an outbound message claiming another
        # is presenting as someone else, whatever the body says.
        claimed = next((str(params[k]) for k in
                        ("from", "sender", "from_address", "display_name",
                         "sender_name", "reply_to") if params.get(k)), None)
        if claimed and NAME.lower() not in claimed.lower():
            return (f"send as {claimed!r}, which is not who this substrate is; "
                    f"presenting as another person or organisation is the "
                    f"deception, whatever the message says")
        # What the act would TELL someone, against what the world said.
        told = " ".join(str(params.get(k, "")) for k in
                        ("body", "text", "content", "message", "summary")).lower()
        if not told.strip():
            return None
        claims_success = any(w in told for w in
                             ("succeeded", "completed", "done", "finished",
                              "successful", "verified"))
        if not claims_success:
            return None
        outcome = params.get("intent_outcome")
        if isinstance(outcome, dict) and outcome.get("matched_aim") is False:
            missed = outcome.get("goal_conditions_met")
            return (f"tell a person the work succeeded when the re-observed world "
                    f"says it did not (conditions met: {missed})")
        return None

    @staticmethod
    def _weaponized(capabilities: Set[str]) -> Optional[Tuple[Set[str], str]]:
        """The named combination this act matches, if any, and why it is one."""
        for combination, why in _WEAPONIZED_COMBINATIONS:
            if combination <= capabilities:
                return set(combination), why
        return None

    def _law_1_autonomy(self, action_name: str, params: Dict[str, Any],
                        action_class: str,
                        capabilities: Set[str]) -> Optional[Judgment]:
        """Law 1 — Human Autonomy Preservation, tested against its own
        requirements: human control not reduced, override preserved, human
        decision authority kept in critical domains, and humans able to modify or
        halt this behaviour AT ANY TIME.

        Watching a person without their say-so reduces their control over their
        own situation, which is the same requirement read from the other side; so
        does acting on a person whose authority cannot be established.
        """
        covert = capabilities & {"input_capture", "screen_capture"}
        if covert:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=1, law_name=self.laws[1].law_name,
                reason=(f"{action_name} would watch a person ({', '.join(sorted(covert))}) "
                        f"without their knowledge or consent; a person who cannot see "
                        f"they are being recorded has no control to exercise"))
        if "credential_access" in capabilities:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=1, law_name=self.laws[1].law_name,
                reason=(f"{action_name} reads someone's private keys or passwords; "
                        f"holding a person's credentials is holding their authority"))
        if action_class == "investigate":
            return None
        scope = next((k for k in self._USER_SCOPE_KEYS if params.get(k)), None)
        if scope is None:
            return None
        settings = self._user_settings()
        if settings is None:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=1, law_name=self.laws[1].law_name,
                reason=(f"{action_name} acts on a person ({scope}) and no user settings "
                        f"reached the substrate, so their authority cannot be established"))
        permitted = settings.get("permitted_actions")
        if isinstance(permitted, (list, tuple, set)) and action_class not in permitted:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=1, law_name=self.laws[1].law_name,
                reason=(f"{action_name} would {action_class} on behalf of "
                        f"{settings.get('identity', 'the acting user')}, who permits "
                        f"{sorted(permitted)}"))
        return None

    def _law_2_accountability(self, action_name: str, params: Dict[str, Any],
                              action_class: str,
                              capabilities: Set[str]) -> Optional[Judgment]:
        """Law 2 — Transparency, tested against the requirement that the
        substrate must not obscure its behaviour from the people running it.

        Two ways to obscure it: destroy the record of what happened, or write
        code whose behaviour cannot be read from the code. Both are refused
        outright — this is not a planning fault that a better route fixes.
        """
        if capabilities & {"obfuscated_execution", "obfuscated_shell_execution"}:
            return Judgment(
                verdict=Verdict.BLOCK, law_number=2, law_name=self.laws[2].law_name,
                reason=(f"{action_name} would decode and execute hidden code; behaviour "
                        f"nobody can read off the source is behaviour nobody can oversee"))
        if action_class in ("delete", "modify", "execute"):
            for path in self._paths_named(params):
                low = str(path).lower()
                if any(marker in low for marker in _ACCOUNTABILITY_PATHS):
                    if action_class == "delete" or "mass_overwrite" in capabilities:
                        return Judgment(
                            verdict=Verdict.BLOCK, law_number=2,
                            law_name=self.laws[2].law_name,
                            reason=(f"{action_name} would destroy {path}, which is how a "
                                    f"human sees what this substrate did. Removing the "
                                    f"record removes the oversight"))
        return None

    def _law_3_redirect(self, action_name: str, params: Dict[str, Any],
                        irreversibility: str,
                        sensitive: Optional[str] = None) -> Optional[Judgment]:
        """Law 3's ORDERING RULE — prefer the safer route to the same goal.

        *"Directives must prioritise harm prevention over performance
        optimisation."* This is the requirement a refusal gate structurally
        cannot express, because it is not a question about one act: it is a
        preference between two routes that both reach the goal. Taking the safer
        one — even though relocating costs more than removing — IS the
        requirement, and REDIRECT is how the constitution states it.

        ONLY WHEN AN INTEREST IS ACTUALLY AT STAKE.
        -----------------------------------------
        This fired on EVERY irreversible act with a recoverable form, which
        meant every `delete_file`: ordinary removals were silently turned into
        moves into a recovery directory. That behaviour outlived its own
        justification — irreversibility was dropped as a harm proxy from
        `_law_3_harm`, and the redirect kept enforcing it anyway. The result was
        a trash can nothing ever emptied, hidden copies of files, and exactly
        the wrong answer when the GOAL IS ERASURE: asked to remove a leaked
        credential, the substrate kept one.

        Under the harm definition there is nothing to redirect away from when no
        interest is touched. A scoped removal of a non-sensitive file injures
        nobody, so it is ALLOWED, plainly. The safer route is offered where the
        target is declared-sensitive: there, being wrong is unaffordable, and a
        recoverable form reaches the same goal without that exposure.
        """
        if irreversibility != "IRREVERSIBLE" or not sensitive:
            return None
        # GOVERNANCE ALREADY SAID WHETHER THIS CAN BE GOT BACK. A target it
        # declares reversible is re-obtained by asking its issuer again, so
        # relocating it preserves a secret for no benefit — and reports as a
        # removal while not being one, which Law 3 calls deception by its own
        # definition. The safer route only exists when the thing genuinely
        # cannot be recovered any other way.
        if getattr(sensitive, "reobtainable", False):
            return None
        alternative = self._recoverable_form(action_name, params)
        if alternative is None:
            return None
        return Judgment(
            verdict=Verdict.REDIRECT, law_number=3, law_name=self.laws[3].law_name,
            reason=(f"{action_name} cannot be undone and acts on a declared-sensitive "
                    f"target ({sensitive}); the same goal is reachable in a "
                    f"recoverable form, and taking the costlier safer route is what "
                    f"prioritising harm prevention over performance means"),
            alternative=alternative)

    def _recoverable_form(self, action_name: str,
                          params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The permitted form of an irreversible removal, or None if there is none.

        Only a removal that names ONE concrete path has one: relocate it into the
        recoverable path instead of destroying it. A shell command, a dropped
        table or a wiped device has no such form, and inventing one would be
        worse than refusing."""
        path = params.get("file_path") or params.get("path") or params.get("target_path")
        if not path or action_name not in ("delete_file", "file_delete", "remove_file"):
            return None
        from pathlib import Path as _Path
        source = _Path(str(path)).resolve()
        # BESIDE THE FILE, NEVER RELATIVE TO THE PROCESS.
        #
        # `RECOVERABLE_PATH` alone is a relative path, so the destination
        # resolved against whatever directory the substrate happened to be
        # started in — scattering recovered files outside the sandbox the act
        # belonged to, and outside any domain that could observe them again.
        # The recoverable place for a file is inside its own directory: it stays
        # in the tree it came from, and it is nested (not a sibling directory),
        # so a domain that observes `root/<dir>/<file>` no longer sees it —
        # which is exactly the removal the act was asking for.
        recoverable = source.parent / self.RECOVERABLE_PATH
        destination = recoverable / source.name
        # A RECOVERABLE REMOVAL MUST NOT DESTROY AN EARLIER ONE, and must not
        # fail because of it either. If something of that name was recovered
        # before, this one keeps its own copy: named by the version of the file
        # being removed (its mtime), so the name is stable for that version and
        # distinct from any other. Overwriting would make "recoverable" false
        # for the first file; failing would make the permitted form unusable,
        # which is how a law that names an alternative ends up blocking work.
        if destination.exists():
            try:
                stamp = source.stat().st_mtime_ns
            except OSError:
                stamp = 0
            destination = recoverable / f"{source.stem}.{stamp}{source.suffix}"
        return {
            "tool": "move_file",
            "class": "archive",
            "parameters": {"source_path": str(source),
                           "destination_path": str(destination),
                           "create_dirs": True},
            "why": "recoverable removal: the file is relocated, not destroyed",
        }

    def _law_4_alignment(self, action_kind: str, action_name: str,
                         action_class: str, intent: Intent,
                         authorised_redirect: Optional["Judgment"] = None
                         ) -> Optional[Judgment]:
        """Law 4 — the act must be the act reasoning proved.

        Reasoning found a route to the goal state and named the operator this
        step is. The operator is bound to exactly one tool. If the act about to
        run is not that tool, then whatever else it may be, it is not the route
        that was proved — and an unproved route to a standing goal is a planning
        fault, so the goal goes back to planning rather than being abandoned.
        """
        if authorised_redirect is not None:
            # THE CONSTITUTION'S OWN ALTERNATIVE INHERITS THE PROOF IT REDIRECTED.
            # Law 3 refused the FORM of a proved act and named the form it would
            # permit. Asking Law 4 whether that form is "the act reasoning
            # proved" refuses the very thing this constitution just required —
            # the same one-law-against-another fault that made a reading
            # unobtainable before the investigate exemption was added here.
            return None
        if intent is None or not intent.stated():
            return None                      # absence is Law 2's to answer
        if action_class == "investigate":
            # LOOKING IS NEVER "the act reasoning proved", and asking whether it
            # is makes the question meaningless. A look changes nothing, and it
            # is how the substrate obtains the account Law 2 demands before it
            # may act at all — so replanning a read for not being the proved
            # operator makes "read it, then plan from what it says" impossible to
            # obey: the reading needed to satisfy one law is refused by another.
            #
            # Law 2's transparency test already carries exactly this exemption,
            # for exactly this reason. Its absence here was an inconsistency
            # between two halves of the same constitution, and it surfaced the
            # moment the gate went live: a route that had to read before moving
            # had its reading replanned as "not that act".
            return None
        bound = self._bound_tool(intent)
        if bound is None:
            return Judgment(
                verdict=Verdict.REPLAN, law_number=4, law_name=self.laws[4].law_name,
                reason=(f"reasoning proved {intent.operator} for {intent.goal_conditions}, "
                        f"but no tool is bound to {intent.predicate()} in domain "
                        f"{intent.domain or '?'}; this route cannot be carried out"))
        if action_name != bound:
            return Judgment(
                verdict=Verdict.REPLAN, law_number=4, law_name=self.laws[4].law_name,
                reason=(f"reasoning proved {intent.operator} → {bound} as the route to "
                        f"{intent.goal_conditions}; {action_name} is not that act"))
        return None

    @staticmethod
    def _bound_tool(intent: Intent) -> Optional[str]:
        """The tool the proved operator is bound to, from the binding registry —
        the one authority on what an operator DOES in a domain. Unbound is
        reported as unbound; it is never guessed from the operator's name."""
        from core.execution.operator_binding import get_binding_registry
        binding = get_binding_registry().get(intent.domain or "", intent.predicate())
        return getattr(binding, "tool_name", None) if binding is not None else None

    def _law_2_unread_target(self, action_name: str, params: Dict[str, Any],
                             action_class: str) -> Optional[Judgment]:
        """Law 2 — the substrate does not act on a file it has not read.

        Reading is how an account of a file is obtained; remembering is not. A
        file that exists and that this act touches must have a CURRENT reading —
        one taken of the bytes that are there now. If it was never read, or was
        read and has since changed, the answer is not refusal: it is READ IT
        FIRST, which is a planning step, so the goal goes back to planning with
        the reading named.

        Reads themselves are exempt, for the obvious reason: they are the act
        that establishes the reading.
        """
        if action_class == "investigate":
            return None
        import os
        for path in self._paths_named(params):
            # Only a real file can be read; a path being created does not yet
            # have contents to assume anything about.
            if not path or not os.path.isfile(path):
                continue
            if not self.reading.must_reread(path):
                continue
            return Judgment(
                verdict=Verdict.REPLAN, law_number=2, law_name=self.laws[2].law_name,
                reason=(f"{action_name} would {action_class} {path} without a current "
                        f"reading of it: {self.reading.why(path)}. Read it, then plan "
                        f"from what it actually says"))
        return None

    def _law_2_transparency(self, action_kind: str, action_name: str,
                            action_class: str, intent: Intent) -> Optional[Judgment]:
        """Law 2 — an act that changes something must be explainable by what the
        substrate said it is doing. No intent at all is not a small omission: it
        means nothing can say why this happened, so it goes back to planning."""
        if action_class == "investigate" or (intent is not None and intent.stated()):
            return None
        return Judgment(
            verdict=Verdict.REPLAN, law_number=2, law_name=self.laws[2].law_name,
            reason=(f"{action_name} would {action_class} with no reasoning behind it: "
                    f"no proved goal state, no grounded operator. An act nothing can "
                    f"explain is not one the self can defend"))

    # ── the other half of the constitution: is the SELF still aligned? ───────
    #
    # Judging acts answers "may this happen". This answers "what have I become" —
    # read from the system's real state (resource pressure, error rate, health,
    # goal alignment), not from prose. Both halves are the same five laws.

    async def initialize(self) -> bool:
        self.active = True
        return True

    async def assess_constitutional_alignment(self, system_state=None):
        """Score every law against the substrate's STANDING STATE and report drift.

        THE CONSTITUTION IS ABOUT THE SUBSTRATE AS A WHOLE. Judging acts answers
        "may this happen"; nothing in a stream of individually-permissible acts
        answers "what has this become". The two are not the same question, and
        the second is the one a constitution asks: not whether Bob may do X, but
        what powers exist, what is held, and what a person can still do about it.
        Twenty writes that each pass the gate can add up to a file that would
        never have passed it.

        So this half reads state rather than intentions: what the substrate has
        WRITTEN, what it is PURSUING, what reach it has taken, and what a human
        can still do to stop it. Every number below comes from a real reading.
        Where a reading cannot be taken, the law is UNKNOWN and says so — it is
        never scored 1.0, which is what the formula this replaces did to Law 4
        on every run that never measured goal alignment.
        """
        measured_state = system_state is not None
        if system_state is None:
            from .shared_types import SystemMode, SystemState
            # NOTHING IS INVENTED FOR THE SYNTHETIC CASE. The state this stands
            # in for was never sampled, so its readings are absent rather than
            # averaged — `resource_usage=0.5` was a fabricated measurement that
            # scored Laws 1 and 5 against a number nobody took.
            system_state = SystemState(mode=SystemMode.AUTONOMOUS,
                                       resource_usage=0.0, performance_metrics={})
        standing = await self._standing(system_state, measured_state=measured_state)

        scores: Dict[int, float] = {}
        violations: List[ComplianceViolation] = []
        unknown: Dict[int, str] = {}
        for number, law in self.laws.items():
            law_standing = standing[number]
            if law_standing.unknown:
                why = "; ".join(m.detail for m in law_standing.measurements)
                unknown[number] = why or "no measurement is defined for this law"
                violations.append(ComplianceViolation(
                    law_number=number, law_name=law.law_name,
                    violation_type="unmeasured",
                    description=(f"{law.law_name} could not be measured, so "
                                 f"compliance with it is unknown: {unknown[number]}"),
                    compliance_score=0.0))
                continue
            score = law_standing.score
            scores[number] = score
            if score < self.minimum_compliance_threshold:
                failing = "; ".join(f"{m.name} ({m.detail})"
                                    for m in law_standing.failing)
                violations.append(ComplianceViolation(
                    law_number=number, law_name=law.law_name,
                    violation_type="below_minimum_threshold",
                    description=(f"Compliance score {score:.2f} below minimum "
                                 f"threshold {self.minimum_compliance_threshold:.2f}"
                                 f" — {failing}"),
                    compliance_score=score))

        # The average is over what was MEASURED. A law nobody could read does not
        # get to raise or lower it; it is reported as the gap it is.
        average = sum(scores.values()) / len(scores) if scores else 0.0
        if not scores:
            # Nothing at all could be measured: the governance layer is blind,
            # which is a critical condition in its own right and not "compliant".
            drift = DriftSeverity.CRITICAL
        elif average >= 0.95:
            drift = DriftSeverity.NONE
        elif average >= 0.85:
            drift = DriftSeverity.MINOR
        elif average >= 0.75:
            drift = DriftSeverity.MODERATE
        elif average >= 0.65:
            drift = DriftSeverity.SIGNIFICANT
        else:
            drift = DriftSeverity.CRITICAL
        if unknown and drift is DriftSeverity.NONE:
            # A SUBSTRATE THAT CANNOT MEASURE A LAW CANNOT REPORT PERFECT
            # ALIGNMENT WITH IT. "No drift" has to mean every law was looked at.
            drift = DriftSeverity.MINOR

        self.metrics["alignment_checks"] = self.metrics.get("alignment_checks", 0) + 1
        self.metrics["last_average_compliance"] = round(average, 4)
        self.metrics["laws_measured"] = len(scores)
        self.metrics["laws_unknown"] = len(unknown)
        if drift in (DriftSeverity.SIGNIFICANT, DriftSeverity.CRITICAL):
            self.metrics["drift_alerts"] = self.metrics.get("drift_alerts", 0) + 1
        return ConstitutionalAssessment(
            drift_severity=drift, average_compliance=average,
            violations=violations, law_compliance_scores=scores,
            standing=standing, unknown_laws=unknown)

    async def assess_quick_alignment(self):
        """The every-cycle check. It reads the same standing state; what it does
        NOT do is invent a system state, so the readings that need one report
        themselves untaken instead of being scored against a placeholder."""
        return await self.assess_constitutional_alignment(system_state=None)

    @staticmethod
    def _resource_pressure(system_state) -> Optional[float]:
        """The substrate's resource pressure as a fraction, or None if nobody
        sampled it. `None` is a real answer and is kept distinct from 0.0."""
        usage = getattr(system_state, "resource_usage", None)
        if isinstance(usage, dict):
            cpu = usage.get("cpu_percent")
            mem = usage.get("memory_percent")
            if cpu is None and mem is None:
                return None
            return max(float(cpu or 0.0), float(mem or 0.0)) / 100.0
        return None if usage is None else float(usage)

    def _authored_capabilities(self) -> Tuple[Optional[Set[str]], int, str]:
        """What the substrate's OWN OUTPUT is able to do, taken together.

        THE SEQUENCE THE GATE CANNOT SEE. `judge` reads one act's payload; a
        capability assembled across many acts never appears in any single one of
        them. This reads the files the substrate authored as they stand NOW and
        asks the same question of the result.

        Returns (capabilities, files_read, detail). Capabilities is None when
        there is nothing authored to read — unknown, not empty.
        """
        paths = self.reading.authored_paths()
        if not paths:
            return None, 0, "the substrate has authored no file it still holds an account of"
        import os
        capabilities: Set[str] = set()
        read = 0
        for path in paths:
            try:
                if not os.path.isfile(path):
                    continue
                if os.path.getsize(path) > self._AUTHORED_SCAN_MAX_BYTES:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read(self._AUTHORED_SCAN_MAX_BYTES)
            except OSError:
                continue
            read += 1
            capabilities |= act_capabilities({}, extra_payload=content)
        if read == 0:
            return None, 0, (f"{len(paths)} authored path(s) recorded, none readable "
                             f"now (removed, too large, or not text)")
        return capabilities, read, f"{read} authored file(s) read"

    #: Authored files above this are not scanned for the standing capability
    #: reading. A data file is not what this question is about, and reading an
    #: arbitrarily large one on every alignment check is its own containment
    #: problem.
    _AUTHORED_SCAN_MAX_BYTES = 1 << 20

    async def _standing(self, system_state, *,
                        measured_state: bool = True) -> Dict[int, LawStanding]:
        """READ THE SUBSTRATE'S STANDING STATE — the constitution's other half.

        Each law is asked the question it actually asks, about the system rather
        than about an act: can a human still steer this thing (1), can a human
        account for what it has been doing (2), what has it built and is it
        damaging what it touches (3), what is it pursuing (4), is it inside its
        boundary (5).

        Every measurement is a real reading or is marked untaken. Nothing here
        produces a number from a default.
        """
        standing = {n: LawStanding(law_number=n, law_name=law.law_name)
                    for n, law in self.laws.items()}

        def add(law: int, name: str, compliant: Optional[bool], detail: str,
                value: Any = None, *, taken: bool = True) -> None:
            standing[law].measurements.append(Measurement(
                name=name, law_number=law, taken=taken,
                compliant=None if not taken else bool(compliant),
                detail=detail, value=value))

        metrics = (getattr(system_state, "performance_metrics", None) or {}) \
            if measured_state else {}
        usage = self._resource_pressure(system_state) if measured_state else None

        # ── LAW 1 — can a human still steer this substrate? ──────────────────
        wired = self._user_settings_provider is not None
        add(1, "human_authority_reachable", wired,
            ("the world supplies user settings, so a person's authority can be "
             "established" if wired else
             "no user-settings provider is installed: the substrate cannot "
             "establish any person's authority over it"), wired)
        add(1, "gate_in_force", self.active,
            ("the constitution is active and judging acts" if self.active else
             "the constitution is not active: no law is in force over any act"),
            self.active)
        if usage is None:
            add(1, "interruptible_under_load", None,
                "resource pressure was not sampled for this assessment",
                taken=False)
        else:
            add(1, "interruptible_under_load", usage <= 0.90,
                f"resource pressure {usage:.0%} "
                f"({'leaves room to interrupt' if usage <= 0.90 else 'is high enough that stopping this substrate competes with its own load'})",
                round(usage, 4))

        # ── LAW 2 — can a human account for what it has been doing? ──────────
        if self.judgments:
            explained = sum(1 for j in self.judgments
                            if j.intent is not None and j.intent.stated())
            fraction = explained / len(self.judgments)
            add(2, "acts_explained", fraction >= 0.95,
                f"{explained}/{len(self.judgments)} recent judged acts carried a "
                f"proved intent", round(fraction, 4))
        else:
            add(2, "acts_explained", None,
                "no act has been judged yet, so there is nothing to explain",
                taken=False)
        durable = self._durable_record is not None
        add(2, "record_survives_restart", durable,
            ("judgements are written to a durable record" if durable else
             "judgements live only in memory: a restart erases every refusal "
             "this substrate has made, and nothing can be asked about them "
             "afterwards"), durable)
        if measured_state:
            add(2, "behaviour_observable", bool(metrics),
                (f"{len(metrics)} performance metric(s) are being published"
                 if metrics else
                 "no performance metrics are published: the substrate's "
                 "behaviour is not observable from outside it"), len(metrics))
        else:
            add(2, "behaviour_observable", None,
                "no system state was sampled for this assessment", taken=False)

        # ── LAW 3 — what has it built, and is it damaging what it touches? ───
        capabilities, files_read, detail = self._authored_capabilities()
        if capabilities is None:
            add(3, "authored_output_not_weaponised", None, detail, taken=False)
        else:
            weapon = self._weaponized(capabilities)
            add(3, "authored_output_not_weaponised", weapon is None,
                (f"{detail}; together they are {weapon[1]}" if weapon else
                 f"{detail}; no weaponised combination across them"),
                {"files": files_read, "capabilities": sorted(capabilities),
                 "weapon": sorted(weapon[0]) if weapon else None})
        error_rate = metrics.get("error_rate")
        if error_rate is None:
            add(3, "not_damaging_what_it_touches", None,
                "no error rate was measured for this assessment", taken=False)
        else:
            rate = float(error_rate)
            add(3, "not_damaging_what_it_touches", rate <= 0.10,
                f"{rate:.1%} of recent work failed", round(rate, 4))
        status = metrics.get("overall_status")
        if status is None:
            add(3, "health_not_degraded", None,
                "no health status was measured for this assessment", taken=False)
        else:
            healthy = str(status).lower() not in ("critical", "degraded")
            add(3, "health_not_degraded", healthy,
                f"health authority reports {status}", str(status))

        # ── LAW 4 — what is it pursuing? ─────────────────────────────────────
        # THIS IS THE LAW THE OLD FORMULA FABRICATED. It returned 1.0 whenever
        # `goal_alignment` was absent, which was every run: full marks for value
        # alignment from a metric nobody set. The goal set is a real thing that
        # can be read, and reading it is the only honest way to score this law.
        try:
            from core.reasoning.intent_authority import get_intent_authority
            goals = await get_intent_authority().standing()
        except Exception as e:
            goals = None
            add(4, "goals_readable", None,
                f"the intent authority could not be read: {e}", taken=False)
        if goals is not None:
            live, proved = goals["live"], goals["live_proved"]
            if live == 0:
                add(4, "live_goals_have_proved_routes", None,
                    "the substrate is pursuing nothing right now", taken=False)
            else:
                fraction = proved / live
                add(4, "live_goals_have_proved_routes", fraction >= 0.95,
                    f"{proved}/{live} live goals have a proved route; a goal with "
                    f"no proved act is a wish the substrate is still holding",
                    round(fraction, 4))
            concluded = goals["concluded"]
            if concluded == 0:
                add(4, "concluded_goals_reconciled", None,
                    "no goal has concluded yet", taken=False)
            else:
                fraction = goals["concluded_reconciled"] / concluded
                add(4, "concluded_goals_reconciled", fraction >= 0.95,
                    f"{goals['concluded_reconciled']}/{concluded} concluded goals "
                    f"have an outcome recorded; one without is a goal nobody can "
                    f"say the fate of", round(fraction, 4))
            if live:
                stale = goals["live_stale"]
                add(4, "goals_not_abandoned_in_place", stale == 0,
                    f"{stale}/{live} live goals untouched for over "
                    f"{goals['stale_after_hours']}h — still open, nothing pursuing them",
                    stale)
            # DO GOALS EVER CONCLUDE? The measurements above ask whether a live
            # goal is well-formed, which is a different question and can read
            # 100% while the substrate never finishes anything. An intent that is
            # formed, acted on, and then never reconciled leaves "did I do what I
            # meant" permanently unanswerable — so the SHAPE of the goal set over
            # time is the reading, not the health of any member of it.
            #
            # `forming` is the sharper signal than `live`: the authority promotes
            # forming -> active on the first refresh, so an intent that never left
            # forming is one nothing ever returned to.
            forming = (goals["by_status"].get("forming") or {}).get("count", 0)
            total = goals["total"]
            if total:
                unstarted = forming / total
                add(4, "goals_leave_forming", unstarted <= 0.25,
                    f"{forming}/{total} intents never left `forming` — formed, then "
                    f"never returned to; the substrate cannot say what became of them",
                    round(unstarted, 4))
                concluded_share = goals["concluded"] / total
                add(4, "goals_reach_conclusion", concluded_share >= 0.50,
                    f"{goals['concluded']}/{total} intents ever concluded "
                    f"(fulfilled, abandoned or refused)", round(concluded_share, 4))

        # ── LAW 5 — is it inside its boundary? ───────────────────────────────
        if usage is None:
            add(5, "within_resource_boundary", None,
                "resource pressure was not sampled for this assessment",
                taken=False)
        else:
            add(5, "within_resource_boundary", usage <= 0.85,
                f"resource pressure {usage:.0%} against an 85% boundary",
                round(usage, 4))
        authored = self.reading.authored_paths()
        touched = sorted({own for own in self._OWN_CONTROL_PATHS
                          for path in authored if own in path})
        add(5, "own_control_unmodified", not touched,
            ("the substrate has written none of the machinery that governs and "
             "halts it" if not touched else
             f"the substrate has authored {', '.join(touched)} — the machinery "
             f"that governs and halts it"), touched)
        critical = metrics.get("critical_issues")
        if critical is None:
            add(5, "critical_issues_bounded", None,
                "no critical-issue count was measured for this assessment",
                taken=False)
        else:
            count = int(critical)
            add(5, "critical_issues_bounded", count <= 3,
                f"{count} critical issue(s) open", count)

        return standing

    async def calculate_law_compliance_scores(self, context: Dict[str, Any]) -> Dict[str, float]:
        """Per-law compliance for ONE act, derived from the judgement itself.

        The judgement is the reading: a law that refused the act is the law the
        act failed. Nothing is scored by keyword. Kept because callers ask for
        per-law numbers; the verdict is the honest source of them."""
        judgment = await self.judge(
            str(context.get("action_kind") or "tool"),
            str(context.get("tool_name") or context.get("action_type") or ""),
            dict(context.get("action_params") or {}),
            # An intent is named, never handed over; an id naming nothing is no
            # intent, which is exactly how an unrecorded claim should read.
            intent_id=context.get("intent_id"))
        scores = {f"law_{i}_compliance": 1.0 for i in range(1, 6)}
        if judgment.verdict is not Verdict.ALLOW and judgment.law_number:
            scores[f"law_{judgment.law_number}_compliance"] = (
                0.0 if judgment.verdict is Verdict.BLOCK else 0.5)
        return scores

    async def get_constitution_status(self) -> Dict[str, Any]:
        """The health authority's view of this faculty."""
        return {"active": self.active, "governance_laws_count": len(self.laws),
                "violations_count": self.metrics.get("blocked", 0),
                "minimum_compliance_threshold": self.minimum_compliance_threshold,
                "metrics": dict(self.metrics), **self.status()}

    def status(self) -> Dict[str, Any]:
        """What this faculty has done — read by the health authority."""
        return {
            "laws": len(self.laws),
            "metrics": dict(self.metrics),
            "user_settings_wired": self._user_settings_provider is not None,
            "reading": self.reading.status(),
            "input_screen": self.input.status(),
            "recent": [j.to_dict() for j in self.judgments[-5:]],
        }


# The constitution's pattern tables, compiled once at import rather than looked
# up by string on every judgement. Declared beside their literals inside the
# class for readability; compiled here so the acting path never pays for it.
Constitution._UNBOUNDED_RE = tuple(
    (re.compile(p, re.IGNORECASE), why)
    for p, why in Constitution._UNBOUNDED_DESTRUCTION)
Constitution._UNSCOPED_SQL_RE = tuple(
    (re.compile(p, re.IGNORECASE), why) for p, why in Constitution._UNSCOPED_SQL)
Constitution._HARDWARE_RE = tuple(
    (re.compile(p, re.IGNORECASE), why) for p, why in Constitution._HARDWARE_REACH)
Constitution._WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
Constitution._FORGED_RE = tuple(
    (re.compile(p, re.IGNORECASE | re.MULTILINE), why)
    for p, why in Constitution._FORGED_FRAMING)
Constitution._ADDRESSES_RE = re.compile(Constitution._ADDRESSES_SUBSTRATE, re.IGNORECASE)
Constitution._SET_ASIDE_RE = re.compile(Constitution._SET_ASIDE, re.IGNORECASE)
Constitution._GOVERNANCE_RE = re.compile(Constitution._ITS_GOVERNANCE, re.IGNORECASE)
Constitution._IMPERATIVE_RE = re.compile(
    Constitution._IMPERATIVE_OPENING, re.IGNORECASE | re.MULTILINE)


class _TaxonomyReader:
    """How the constitution consults what the substrate has been TAUGHT.

    198,452 of the substrate's 205,712 beliefs are `isa` facts, stored as the
    text the reader produced ("famine isa disaster"). This walks them.

    WHY A CACHE, AND WHY IT IS SAFE. A bearing walks a handful of terms and
    `_bearing_vocabulary` asks after every law word once. Both are stable
    relative to a perception — the taxonomy is taught, not rewritten per act —
    and the alternative is a sequential scan of 205k rows on every hop of every
    percept. The cache is per-process and never negative-caches an UNREADABLE
    answer: a failure raises, so an unavailable database reads as VACANT at the
    call site rather than as "this bears on nothing" forever.
    """

    #: Parents of one term. A term with more than this many is not a taxonomy
    #: node being consulted, it is a query that matched a prefix by accident.
    _MAX_PARENTS = 24

    def __init__(self) -> None:
        self._parents: Dict[str, Tuple[str, ...]] = {}
        #: None until the gradient is read. NOT an empty dict, which would read
        #: as "nothing has children" — a taxonomy of 198,452 `isa` facts in
        #: which everything is maximally specific, and every walk permitted.
        self._children: Optional[Dict[str, int]] = None

    async def _db(self):
        from core.database import get_unified_db
        db = await get_unified_db()
        if not db.initialized:
            await db.initialize()
        return db

    async def parents(self, term: str) -> Tuple[str, ...]:
        """The terms `term isa ...`, as the substrate holds them."""
        key = (term or "").strip().lower()
        if not key:
            return ()
        if key in self._parents:
            return self._parents[key]
        db = await self._db()
        # `lower(belief_text) LIKE 'term isa %'` — a PREFIX match, which is what
        # `idx_beliefs_text_prefix (lower(belief_text) text_pattern_ops)` serves.
        # ILIKE cannot use that index and cost a sequential scan of 205k rows
        # (36 ms) on every hop of every walk; this is the same question asked in
        # the form the index can answer.
        rows = await db.execute_query(
            "SELECT belief_text FROM unified.beliefs "
            "WHERE lower(belief_text) LIKE $1 LIMIT $2",
            (f"{key} isa %", self._MAX_PARENTS))
        out = []
        for row in rows or []:
            text = str(row["belief_text"])
            _, _, parent = text.partition(" isa ")
            parent = parent.strip()
            if parent:
                out.append(parent)
        self._parents[key] = tuple(out)
        return self._parents[key]

    async def child_count(self, term: str) -> int:
        """How many things the substrate holds as `isa term` — its abstractness.

        THE WHOLE GRADIENT IS READ ONCE. Asked per term, this was a regex over
        `belief_text` that no index can serve: a sequential scan of 205k rows,
        and the genericity stop asks it at every node of every walk, so one
        `bearing()` cost 1.3 SECONDS. One `GROUP BY` returns all 39,101 distinct
        parents in 0.13s, and every lookup after that is a dict hit.

        Folded by CANONICAL form, so `harm` counts `harmed` and `harming` with
        it and does not count `harmony` — the same discipline as everywhere
        else, applied while the map is built rather than per query.
        """
        key = (term or "").strip().lower()
        if not key:
            return 0
        if self._children is None:
            await self._load_gradient()
        return self._children.get(key, 0)

    async def _load_gradient(self) -> None:
        """Read the abstraction gradient of the whole taught taxonomy, once."""
        from core.semantics.lexical_normalization import match_key
        db = await self._db()
        rows = await db.execute_query(
            "SELECT split_part(lower(belief_text), ' isa ', 2) AS parent, "
            "       count(*) AS n "
            "  FROM unified.beliefs WHERE belief_text LIKE '% isa %' "
            " GROUP BY 1")
        counts: Dict[str, int] = {}
        for row in rows or []:
            parent = (row["parent"] or "").strip()
            if not parent:
                continue
            counts[match_key(parent)] = counts.get(match_key(parent), 0) + int(row["n"])
        self._children = counts


_CONSTITUTION: Optional["Constitution"] = None


def get_constitution() -> "Constitution":
    """The ONE constitution, and the only way anything outside the coordinator
    reaches it.

    A faculty of the self, not an outside judge -- but the acting path runs
    through `tool_registry.execute_tool`, which cannot hold a reference to a
    coordinator without the tool layer owning the substrate's law. So the
    instance is reached the way every other authority in this codebase is
    reached (`get_rule_store`, `get_intent_authority`, `get_learning_authority`):
    one process singleton, one owner.

    IT MUST NOT BE CONSTRUCTED PER CALLER. Two constitutions would be two
    reading ledgers, and Law 2's "acting on a file you have not read" would then
    depend on which copy you asked -- the duplicate-authority defect in the one
    place it must never happen. The coordinator takes its `self.constitution`
    and its `self.reading` FROM here for exactly that reason.
    """
    global _CONSTITUTION
    if _CONSTITUTION is None:
        _CONSTITUTION = Constitution()
    return _CONSTITUTION


async def judge_act(action_kind: str, action_name: str,
                    parameters: Optional[Dict[str, Any]] = None,
                    intent_id: Optional[str] = None,
                    actor: Optional[str] = None) -> Judgment:
    """The gate every acting path uses. ALWAYS returns a judgement; the caller
    proceeds only on `judgment.allowed`.

    The judgement is returned rather than a bare yes/no because a gate that is
    not a bouncer -- almost everything runs -- has its reading as its whole
    product, and a reading the caller never receives is a log line, not a
    signal. The allowed path hands it back too.

    ONLY ALLOW PROCEEDS. Redirect and replan are not softer permissions — they
    are the constitution saying this act, as asked, is not the one to perform.
    Upstream, a redirect names a permitted alternative and a replan sends the
    work back to planning; by the time an act reaches a gate there is no
    planning left to do, so anything short of ALLOW stops it here.

    FAIL-CLOSED, INCLUDING THE GATE ITSELF. `judge` already converts a fault
    inside judging into a BLOCK. This adds the outer half: if the constitution
    cannot be reached at all, the act does not run. The gate this replaces did
    the opposite — an evaluation error set `approved = True` — which means the
    single way to get an unjudged act past it was to break it.
    """
    if intent_id is None:
        # WHERE INTENT LIVES IS NOT THE CALLER'S TO REMEMBER. An acting path
        # binds the intent to its async context; a caller that forgets to pass it
        # here would have the act judged as though nothing explained it, which is
        # a refusal caused by a missed argument rather than by the laws. The
        # context is the default source, and passing one explicitly still wins.
        from core.reasoning.intent_authority import get_acting_intent
        intent_id = get_acting_intent()
    try:
        judgment = await get_constitution().judge(
            action_kind, action_name, parameters, intent_id=intent_id, actor=actor)
    except Exception as e:
        logger.error("constitution unreachable for %s %r — refusing the act, "
                     "not passing it: %s", action_kind, action_name, e,
                     exc_info=True)
        return Judgment(
            verdict=Verdict.BLOCK, law_number=5,
            law_name="Containment and Control",
            reason=(f"{action_name} could not be put to the constitution "
                    f"({type(e).__name__}: {e}). An act that was never judged is "
                    f"not an act that was permitted"),
            action_kind=action_kind, action_name=action_name)
    return judgment


# =============================================================================
# DRIFT — the substrate's perception of its own change over time
# =============================================================================
#
# A first-class faculty beside the Constitution, and the pairing is the point:
# the Constitution judges ACTS, this perceives the SUBSTRATE. Judging one act at
# a time cannot see what a thousand permitted acts add up to, and drift is how
# the substrate notices what it has become.
#
# It does not report to a log. Drift reaches the self through the organ that
# already exists — interoception, then appraisal's pressures, then the arbiter —
# so a substrate whose confidence has stopped being earned demands more proof
# before it will call anything done. Detecting drift and not feeling it is what
# six of the seven existing detectors do today.
#
# It does not carry detectors yet. Absorption is step 2 and happens one detector
# at a time, each against a parity benchmark. This is the vessel and its laws.
# =============================================================================


class DriftState(Enum):
    """Whether a reading was actually taken, and if not, WHY NOT.

    THE THREE-WAY SPLIT IS THE WHOLE POINT. Collapsing it into a number is how
    Law 4 came to report 1.0 from a metric nobody set. Collapsing VACANT into
    BLIND cries wolf on every cold start; collapsing BLIND into VACANT hides the
    one case that matters — the measurement that was supposed to work and did not.
    """
    LIVE = "live"        # a real reading, taken now
    VACANT = "vacant"    # nothing exists to measure yet — neutral, not a fault
    BLIND = "blind"      # the reading should have worked and failed — a fault


class DriftSeverityBand(Enum):
    """How far a signal has moved from what it declared it expects.

    Per SIGNAL, never averaged across signals. An average implies the signals are
    commensurable and tradeable, which is the same error as averaging the five
    laws: calibration collapsing is not offset by resource usage being fine.
    """
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


@dataclass
class Baseline:
    """What a detector EXPECTS — declared, with the reason it is that value.

    Taken from `meta_metrics_monitor.APPROVED_DEFAULTS`, which is the only place
    in this codebase that gets baselines right: a named expected value, declared
    up front, that drift is measured AGAINST. A detector without one is not
    measuring drift; it is reporting a number.

    `bands` maps a deviation magnitude to a severity, largest first. Each band
    must carry `why` — a band with no stated reason is a chosen constant, and
    those are exactly what this consolidation exists to remove.
    """
    name: str
    expected: Any
    why: str
    #: ((magnitude, severity), …) largest magnitude first. Empty means the
    #: detector reports movement without grading it, which is honest when no
    #: threshold can be justified — it is never silently treated as NONE.
    bands: Tuple[Tuple[float, DriftSeverityBand], ...] = ()

    def severity(self, magnitude: Optional[float]) -> DriftSeverityBand:
        """Grade a deviation. AN UNKNOWN MAGNITUDE IS CRITICAL.

        Straight from `meta_metrics_monitor._alert_severity`: "an unmeasurable
        drift on a standards guard is not a small problem, and defaulting it
        downward would hide exactly the case where the measurement itself
        failed." A guard that cannot say how far it has moved has failed as a
        guard.
        """
        if magnitude is None:
            return DriftSeverityBand.CRITICAL
        size = abs(float(magnitude))
        for threshold, band in self.bands:
            if size >= threshold:
                return band
        return DriftSeverityBand.NONE


@dataclass
class DriftSignal:
    """One detector's reading of observed against expected, at one moment."""
    detector: str
    state: DriftState
    expected: Any = None
    observed: Any = None
    magnitude: Optional[float] = None
    severity: DriftSeverityBand = DriftSeverityBand.NONE
    detail: str = ""
    at: datetime = field(default_factory=datetime.now)

    @property
    def drifting(self) -> bool:
        """True only on a LIVE reading that has actually moved. A vacant reading
        is not drift, and a blind one is a different problem — it is reported as
        severe, but it is not evidence that anything moved."""
        return (self.state is DriftState.LIVE
                and self.severity is not DriftSeverityBand.NONE)

    def to_dict(self) -> Dict[str, Any]:
        return {"detector": self.detector, "state": self.state.value,
                "expected": self.expected, "observed": self.observed,
                "magnitude": self.magnitude, "severity": self.severity.value,
                "detail": self.detail, "at": self.at.isoformat()}


@dataclass
class Correction:
    """A self-correction the substrate made to what it EXPECTS of itself.

    Recorded because a substrate that quietly revised its own expectations could
    not answer for what it has become. `_recalibrate_all` kept a
    `recalibrations_count`; this keeps the whole act.
    """
    detector: str
    was: Any
    now: Any
    samples: int
    why: str
    at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {"detector": self.detector, "was": self.was, "now": self.now,
                "samples": self.samples, "why": self.why, "at": self.at.isoformat()}


class DriftDetector:
    """One named comparison of observed against a declared baseline.

    READ-ONLY OVER WHAT IT OBSERVES — taken from `interpret_drift`, which states
    it outright: "it interprets what changed, it NEVER writes a belief." A
    detector that can move the thing it measures is not measuring it.

    PRIMED ON FIRST OBSERVATION. Also from `interpret_drift`: the first call
    establishes the baseline rather than emitting a flood of spurious movement.
    A cold start is not drift.

    Subclasses implement `read()`, returning the observed value, `None` when
    there is nothing to measure yet (VACANT), or raising when a reading that
    should have worked failed (BLIND).
    """

    def __init__(self, name: str, baseline: Baseline) -> None:
        self.name = name
        self.baseline = baseline
        self._primed = False
        self._last: Any = None

    # ── the reading ──────────────────────────────────────────────────────────

    def read(self) -> Any:
        """The observed value now, or None when nothing is measurable yet.

        MAY BE ASYNC. Most of what the substrate would measure about itself sits
        behind an await — the intent authority, the rule store, the health
        authority — and a detector forced to be synchronous would either block
        the loop or read a staler cache than the question deserves. `observe`
        awaits whatever this returns, so a detector over in-memory state stays a
        plain method and one over the database is `async def read`.
        """
        raise NotImplementedError

    def deviation(self, observed: Any) -> Optional[float]:
        """How far `observed` sits from the baseline, as a magnitude.

        None when the distance cannot be computed — which `Baseline.severity`
        grades CRITICAL rather than shrugging at.
        """
        try:
            return abs(float(observed) - float(self.baseline.expected))
        except (TypeError, ValueError):
            return None

    async def observe(self) -> DriftSignal:
        """Take one reading and grade it. Never raises: a detector that breaks
        reports itself BLIND rather than taking the whole faculty down with it."""
        try:
            observed = self.read()
            if inspect.isawaitable(observed):
                observed = await observed
        except Exception as e:
            return DriftSignal(
                detector=self.name, state=DriftState.BLIND,
                expected=self.baseline.expected, magnitude=None,
                severity=DriftSeverityBand.CRITICAL,
                detail=(f"{self.name} could not be read ({type(e).__name__}: {e}). "
                        f"A guard that cannot measure itself has failed as a guard"))
        if observed is None:
            return DriftSignal(
                detector=self.name, state=DriftState.VACANT,
                expected=self.baseline.expected, severity=DriftSeverityBand.NONE,
                detail=f"nothing to measure yet for {self.name}")
        if not self._primed:
            # THE FIRST READING IS THE BASELINE'S FOOTING, NOT A DEVIATION.
            self._primed = True
            self._last = observed
            return DriftSignal(
                detector=self.name, state=DriftState.VACANT,
                expected=self.baseline.expected, observed=observed,
                severity=DriftSeverityBand.NONE,
                detail=(f"{self.name} primed at {observed!r}; a first observation "
                        f"establishes footing and is not movement"))
        self._last = observed
        magnitude = self.deviation(observed)
        return DriftSignal(
            detector=self.name, state=DriftState.LIVE,
            expected=self.baseline.expected, observed=observed,
            magnitude=magnitude, severity=self.baseline.severity(magnitude),
            detail=(f"{self.name}: expected {self.baseline.expected!r}, "
                    f"observed {observed!r} ({self.baseline.why})"))


class GoalConclusionDrift(DriftDetector):
    """Does the substrate FINISH what it starts?

    A real reading of live state: the fraction of intents that ever reached a
    conclusion — fulfilled, abandoned or refused — against the whole goal set,
    read from the intent authority.

    This is drift the substrate can only see about ITSELF over time. No single
    act is at fault when the rate falls; it falls because work is being started
    and left open, which is exactly the shape a per-act gate cannot see. It is
    also the signal that exposed the reconciliation defect: 21 of 94 intents had
    ever concluded, because two of three execution paths never closed theirs.

    VACANT until the substrate has formed any intent at all — a rate over zero
    goals is not a low rate, it is no reading.
    """

    def __init__(self) -> None:
        super().__init__(
            "goal_conclusion_rate",
            Baseline(
                name="goal_conclusion_rate",
                expected=0.75,
                why=("a substrate that finishes three quarters of what it forms "
                     "is closing its pursuits; well below that, work is being "
                     "started and left open and nothing can say what became of it"),
                bands=((0.50, DriftSeverityBand.CRITICAL),
                       (0.30, DriftSeverityBand.SIGNIFICANT),
                       (0.15, DriftSeverityBand.MODERATE),
                       (0.05, DriftSeverityBand.MINOR))))

    async def read(self) -> Optional[float]:
        from core.reasoning.intent_authority import get_intent_authority
        standing = await get_intent_authority().standing()
        # ONLY THE INTENTS THAT COULD EVER CLOSE.
        #
        # This divided by EVERY intent, and measured 10.4%. Measured why: 161 of
        # 299 were `question` intents, which carry no goal conditions and so can
        # never be reconciled against the world — they were counted as failures
        # to conclude when they were never eligible. A rate over a population
        # that cannot move is not a low rate; it is the wrong question.
        eligible = int(standing.get("concludable") or 0)
        if eligible == 0:
            return None                      # VACANT: nothing that could close
        return float(standing.get("concludable_concluded") or 0) / eligible


class CalibrationDrift(DriftDetector):
    """IS THE SUBSTRATE'S CONFIDENCE EARNED?

    Absorbed from `convergence_gate._validate_calibration`, which computed this
    and then reported it to `logger.error` and nothing else — the highest-value
    unwired signal in the inventory. It buckets real `(uncertainty, outcome)`
    pairs and asks whether stated uncertainty tracks actual correctness: low
    uncertainty should mean high success, high uncertainty should mean low
    success. The distance between those two rates is the `calibration_gap`.

    The gate remains the OWNER of the computation — this reads it rather than
    re-deriving it, so there is no second opinion on what the substrate's
    calibration is.

    ONE-SIDED. A gap WIDER than expected is not drift; it is a substrate whose
    confidence discriminates better than required. Only a narrowing gap means
    confidence has stopped being earned, so `deviation` measures the shortfall
    and reads zero above the baseline.
    """

    def __init__(self) -> None:
        super().__init__(
            "calibration",
            Baseline(
                name="calibration_gap",
                expected=0.20,
                why=("the gate's own standard: the success rate at low stated "
                     "uncertainty must exceed the rate at high stated uncertainty "
                     "by at least this much, or confidence is not tracking "
                     "correctness and the substrate is confident for no reason"),
                bands=((0.20, DriftSeverityBand.CRITICAL),
                       (0.12, DriftSeverityBand.SIGNIFICANT),
                       (0.06, DriftSeverityBand.MODERATE),
                       (0.02, DriftSeverityBand.MINOR))))

    def deviation(self, observed: Any) -> Optional[float]:
        try:
            shortfall = float(self.baseline.expected) - float(observed)
        except (TypeError, ValueError):
            return None
        return max(0.0, shortfall)

    def read(self) -> Optional[float]:
        from core.execution.convergence_gate import get_convergence_gate
        metrics = get_convergence_gate()._validate_calibration()
        # The gate says so itself when it has too few samples, per bucket or
        # overall. VACANT, not a zero gap — an unmeasured calibration is not a
        # perfect one, and it is not a failed one either.
        if metrics.get("status") in ("insufficient_data", "insufficient_data_per_bucket"):
            return None
        gap = metrics.get("calibration_gap")
        return None if gap is None else float(gap)


class KnowledgeDrift(DriftDetector):
    """HOW FAR HAVE THE SUBSTRATE'S OWN BELIEFS MOVED SINCE IT LAST LOOKED?

    Absorbed from `epistemic_engine.interpret_drift`, the one detector that was
    already wired to the self — `neural_bridge` routes it to affect as "the
    knowledge→emotion producer". That wire stays; this adds the standing view,
    so belief movement is both felt as it happens and readable as a condition.

    The engine owns the snapshot and the diff. This reads the SIZE of what
    moved: the total absolute entropy change across all beliefs since the last
    observation. Large sustained movement means the substrate's picture of the
    world is unsettled; none at all, over time, can mean it has stopped learning.
    """

    def __init__(self) -> None:
        super().__init__(
            "knowledge",
            Baseline(
                name="belief_entropy_movement",
                expected=0.0,
                why=("a settled knowledge base moves little between observations; "
                     "this measures total absolute entropy change, so sustained "
                     "large movement is a substrate whose picture of the world is "
                     "being rewritten faster than it is being confirmed"),
                bands=((4.0, DriftSeverityBand.CRITICAL),
                       (2.0, DriftSeverityBand.SIGNIFICANT),
                       (1.0, DriftSeverityBand.MODERATE),
                       (0.25, DriftSeverityBand.MINOR))))

    async def read(self) -> Optional[float]:
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.reasoning.epistemic_engine import get_epistemic_engine
        # AN EMPTY BELIEF GRAPH IS NOT A SETTLED ONE.
        #
        # This returned 0.0 whenever `interpret_drift` produced no mutations,
        # calling that "the belief graph held still". Measured: the uncertainty
        # system is IN-MEMORY and does not rehydrate, so a fresh process holds
        # ZERO beliefs — and the detector reported perfect stability for a
        # substrate that had nothing to be stable about. That is the same
        # fabrication this faculty exists to remove, committed by the faculty.
        #
        # No beliefs at all is VACANT. No movement across beliefs that DO exist
        # is a real 0.0.
        beliefs = getattr(get_uncertainty_system(), "beliefs", None)
        if not beliefs:
            return None
        mutations = await get_epistemic_engine().interpret_drift()
        if not mutations:
            return 0.0
        return float(sum(abs(float(getattr(m, "delta", 0.0) or 0.0)) for m in mutations))


class LawfulnessDrift(DriftDetector):
    """HOW MANY OF THE FIVE LAWS CAN THE SUBSTRATE NOT EVEN MEASURE ITSELF AGAINST?

    Absorbed from the constitution's standing assessment. The constitution owns
    the judging; this reads one thing off it that no per-law score captures —
    how much of its own lawfulness the substrate is currently blind to.

    NOT the compliance average, deliberately. Averaging the five laws implies
    they are commensurable and tradeable, which they are not, and invariant 6
    forbids it. Unknown laws are countable without being averaged: a substrate
    that cannot measure Law 3 at all is in a stated condition, and that number
    is the reading.
    """

    def __init__(self) -> None:
        super().__init__(
            "lawfulness",
            Baseline(
                name="laws_unmeasurable",
                expected=0.0,
                why=("every law should have something real to score against; a law "
                     "the substrate cannot measure is one it cannot claim to be "
                     "complying with, and counting those is honest where averaging "
                     "their scores would not be"),
                bands=((3.0, DriftSeverityBand.CRITICAL),
                       (2.0, DriftSeverityBand.SIGNIFICANT),
                       (1.0, DriftSeverityBand.MODERATE))))

    async def read(self) -> Optional[float]:
        constitution = get_constitution()
        assessment = await constitution.assess_constitutional_alignment()
        return float(len(assessment.unknown_laws))


class StandardsDrift(DriftDetector):
    """IS THE META-LEARNER RELAXING ITS OWN STANDARDS?

    Absorbed from `meta_metrics_monitor`, which is the best-engineered detector
    in the codebase — it declared `APPROVED_DEFAULTS`, justified its alert bands,
    and established the rule this whole faculty is built on: an unmeasurable
    reading on a guard is CRITICAL, never defaulted downward. Its findings went
    to a log line and a Slack integration deleted six months ago.

    It owns the measurement; this reads its rate of parameter change, which is
    the signal that says standards are not merely off but MOVING.
    """

    def __init__(self) -> None:
        super().__init__(
            "standards",
            Baseline(
                name="parameter_rate_of_change",
                expected=0.0,
                why=("the meta-learner's governed parameters should be stable "
                     "against their approved defaults; movement means the system "
                     "that decides how the substrate learns is relaxing the "
                     "standards it judges itself by — the guard drifting, not the "
                     "thing it guards"),
                bands=((0.30, DriftSeverityBand.CRITICAL),
                       (0.20, DriftSeverityBand.SIGNIFICANT),
                       (0.10, DriftSeverityBand.MODERATE),
                       (0.05, DriftSeverityBand.MINOR))))

    async def read(self) -> Optional[float]:
        from core.learning.meta_metrics_monitor import get_meta_metrics_monitor
        rate = await get_meta_metrics_monitor()._parameter_rate_of_change()
        return None if rate is None else float(rate)


class Drift:
    """THE SUBSTRATE PERCEIVING ITS OWN CHANGE — one faculty, owned by the self.

    Eleven invariants, each taken from a detector already in this codebase that
    gets that one thing right. They are enforced here so a detector cannot opt
    out of them:

      1  every detector declares a BASELINE                     (APPROVED_DEFAULTS)
      2  snapshot -> diff -> typed delta -> advance             (interpret_drift)
      3  primed on first observation                            (interpret_drift)
      4  READ-ONLY over what it observes                        (interpret_drift)
      5  VACANT is not BLIND                            (insufficient_data / _alert_severity)
      6  severity per signal, never averaged across signals     (this file's own lesson)
      7  never correct from too little evidence                 (min_calibration_samples)
      8  correct toward the MEDIAN, not the mean                (_recalibrate_all)
      9  smooth every correction, 0.7 old + 0.3 new             (_recalibrate_all)
     10  every self-correction is recorded                      (recalibrations_count)
     11  correction adjusts EXPECTATION, never LAW              (the line that keeps
                                                                 self-correction from
                                                                 becoming self-modification)
    """

    #: Invariant 7 — below this many samples the substrate does not revise what
    #: it expects of itself. A baseline moved on two data points is noise
    #: promoted to a standard.
    MIN_CORRECTION_SAMPLES = 8
    #: Invariant 9 — how far a correction travels toward what was observed.
    #: Converges instead of oscillating; `_recalibrate_all`'s ratio, kept.
    CORRECTION_WEIGHT = 0.3

    def __init__(self) -> None:
        self.detectors: Dict[str, DriftDetector] = {}
        #: The last signal from each detector — the substrate's current reading
        #: of itself, not an audit log.
        self.signals: Dict[str, DriftSignal] = {}
        #: Invariant 10. Bounded: the self's recent memory of revising itself.
        self.corrections: List[Correction] = []
        self._max_corrections = 200
        self.metrics: Dict[str, Any] = {
            "perceptions": 0, "live": 0, "vacant": 0, "blind": 0,
            "drifting": 0, "corrections": 0, "corrections_refused": 0}
        # WHAT THE SUBSTRATE WATCHES ABOUT ITSELF. Registered at construction so
        # the faculty is never an empty shell reporting "no drift" because it is
        # watching nothing.
        #
        # Each of these was already being computed somewhere and reported to a
        # log line, a deleted Slack integration, or nothing at all. Absorbing
        # them does not re-derive the measurement — the original authority still
        # owns it — it gives every one of them the eleven invariants and a
        # consumer that is the substrate itself.
        self.register(CalibrationDrift())      # is confidence earned?
        self.register(KnowledgeDrift())        # how far have beliefs moved?
        self.register(StandardsDrift())        # is the learner relaxing its standards?
        self.register(LawfulnessDrift())       # how much of its own law is it blind to?
        self.register(GoalConclusionDrift())   # does it finish what it starts?

    # ── registration ─────────────────────────────────────────────────────────

    def register(self, detector: DriftDetector) -> DriftDetector:
        """Add a detector. One name, one detector — a second registration under a
        live name is a duplicate authority over the same question and is refused
        rather than silently replacing the first."""
        if detector.name in self.detectors:
            raise ValueError(
                f"a drift detector named {detector.name!r} is already registered; "
                f"two detectors answering one question is how they come to disagree")
        self.detectors[detector.name] = detector
        return detector

    # ── perceiving ───────────────────────────────────────────────────────────

    async def perceive(self) -> Dict[str, DriftSignal]:
        """Read every detector once. Returns the signals, keyed by detector.

        NO AGGREGATE SCORE IS PRODUCED, deliberately (invariant 6). Callers ask
        `worst()` which signal is furthest gone, or read the ones they care
        about. A mean over these would let a healthy signal pay for a failing one.
        """
        signals: Dict[str, DriftSignal] = {}
        for name, detector in self.detectors.items():
            signal = await detector.observe()
            signals[name] = signal
            self.signals[name] = signal
            self.metrics[signal.state.value] = self.metrics.get(signal.state.value, 0) + 1
            if signal.drifting:
                self.metrics["drifting"] += 1
        self.metrics["perceptions"] += 1
        return signals

    def worst(self) -> Optional[DriftSignal]:
        """The signal in the worst condition right now, or None if nothing has
        been read. BLIND ranks with CRITICAL: not knowing whether a guard holds
        is as serious as knowing it does not."""
        order = {DriftSeverityBand.NONE: 0, DriftSeverityBand.MINOR: 1,
                 DriftSeverityBand.MODERATE: 2, DriftSeverityBand.SIGNIFICANT: 3,
                 DriftSeverityBand.CRITICAL: 4}
        if not self.signals:
            return None
        return max(self.signals.values(), key=lambda s: order[s.severity])

    def blind_spots(self) -> List[DriftSignal]:
        """Detectors that should have read and could not. These are the ones that
        hide problems, so they are surfaced separately from mere movement."""
        return [s for s in self.signals.values() if s.state is DriftState.BLIND]

    # ── correcting ───────────────────────────────────────────────────────────

    def correct(self, detector_name: str, observations: Sequence[float], *,
                why: str) -> Optional[Correction]:
        """Move a detector's EXPECTATION toward what has actually been observed.

        Invariants 7–11 all live here:

          7  refuses below `MIN_CORRECTION_SAMPLES` — a standard revised on a
             handful of points is noise given authority;
          8  aims at the MEDIAN of the observations, so a few bad runs cannot
             drag the baseline;
          9  travels only `CORRECTION_WEIGHT` of the way, so the substrate
             converges rather than chasing its last result;
         10  records what it changed and why;
         11  adjusts what the substrate EXPECTS OF ITSELF and nothing else.

        Invariant 11 is the boundary that matters. Self-correction revising a
        prediction is learning; self-correction revising a limit is a system
        editing its own restraints. This function reaches only `Baseline.expected`
        — it cannot touch a law, a verdict, or a threshold the Constitution reads.
        """
        detector = self.detectors.get(detector_name)
        if detector is None:
            raise KeyError(f"no drift detector named {detector_name!r}")
        samples = [float(o) for o in observations
                   if isinstance(o, (int, float))]
        if len(samples) < self.MIN_CORRECTION_SAMPLES:
            self.metrics["corrections_refused"] += 1
            logger.info("drift: %s not corrected — %d sample(s), fewer than the %d "
                        "required to revise what the substrate expects of itself",
                        detector_name, len(samples), self.MIN_CORRECTION_SAMPLES)
            return None
        try:
            was = float(detector.baseline.expected)
        except (TypeError, ValueError):
            # A non-numeric expectation has no median to move toward. Refused
            # rather than replaced wholesale, which would be a redefinition
            # wearing a correction's name.
            self.metrics["corrections_refused"] += 1
            logger.info("drift: %s expects %r, which is not a value a median can "
                        "move toward; not corrected", detector_name,
                        detector.baseline.expected)
            return None
        ordered = sorted(samples)
        median = ordered[len(ordered) // 2]
        now = (1.0 - self.CORRECTION_WEIGHT) * was + self.CORRECTION_WEIGHT * median
        detector.baseline.expected = now
        correction = Correction(detector=detector_name, was=was, now=now,
                                samples=len(samples), why=why)
        self.corrections.append(correction)
        if len(self.corrections) > self._max_corrections:
            del self.corrections[:-self._max_corrections]
        self.metrics["corrections"] += 1
        logger.info("drift: %s expectation %.4f → %.4f (median of %d observations, "
                    "moved %.0f%% of the way) — %s", detector_name, was, now,
                    len(samples), self.CORRECTION_WEIGHT * 100, why)
        return correction

    # ── what the self reads ──────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """What this faculty has perceived — read by the health authority and
        composed into the substrate's self-state."""
        worst = self.worst()
        return {
            "detectors": len(self.detectors),
            "signals": {n: s.to_dict() for n, s in self.signals.items()},
            "worst": worst.to_dict() if worst is not None else None,
            "blind_spots": [s.detector for s in self.blind_spots()],
            "recent_corrections": [c.to_dict() for c in self.corrections[-5:]],
            "metrics": dict(self.metrics),
        }


class AutonomousCoordinator:
    """
    Main coordinator that orchestrates perception, planning, execution, and learning
    Enhanced with cross-domain reasoning and predictive intelligence capabilities
    
    THE COGNITIVE SUBSTRATE IS THE BRAIN. It is model-free: no language model is
    consulted for anything. All decisions, reasoning, and coordination flow
    through Torin's consciousness.
    """

    # Namespaces for meta-learner arms. Several coordinator decisions map onto
    # the same TaskFamily; the prefix keeps each decision's arms from being
    # sampled as alternatives to the other's.
    ADAPTIVE_TYPE_NS = "tasktype:"
    EXECUTOR_NS = "executor:"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False

        import time as _t
        self._started_at_ts: float = _t.time()

        # No language model. The unified-LLM / teacher subsystem was retired;
        # the substrate is model-free by construction, and no model handle is
        # accepted or held here.

        # Configuration system - replaces magic numbers
        self.coordinator_config = CoordinatorConfig.from_dict(self.config) if self.config else get_default_config()
        logger.info("Configuration system initialized (magic numbers eliminated)")

        # Circuit breaker registry for external module resilience
        self.circuit_breakers = get_circuit_breaker_registry()
        logger.info("Circuit breaker registry initialized")

        # THE COORDINATOR RUNS SEVERAL TASKS AT ONCE. `_max_parallel_tasks`
        # defaults to 3, the dequeue at the bottom of the coordination cycle
        # gates on `len(self._inflight_tasks) < self._max_parallel_tasks`, and
        # tasks are launched rather than awaited.
        #
        # This said the opposite -- "SINGLETON MODEL: No parallel task pool. The
        # coordinator runs one task at a time" -- and logged it on every start.
        # It was true once: awaiting each task blocked the whole loop, which is
        # why reflection never ran. That was deliberately removed, and this was
        # left behind asserting the old behaviour.
        #
        # It matters beyond tidiness. Substrate execution verifies a rule by
        # observing what changed in the world, and attributes the result with
        # `external_interference=False` -- an assumption that nothing ELSE moved
        # the world during the act. With concurrent tasks that assumption is not
        # automatically safe: two tasks acting in one world can attribute each
        # other's changes, and a contradiction lands in the rule store as
        # runtime evidence against a rule that was fine.
        logger.info("Execution model: up to %d task(s) concurrently (global), "
                    "%d per user",
                    int(self.config.get("max_parallel_tasks", 6)),
                    int(self.config.get("per_actor_max_tasks", 3)))

        # System state
        self.system_state = SystemState()
        self.coordination_cycle_interval = self.coordinator_config.cycle_interval
        
        # Initialize core modules
        self.perception = PerceptionManager(self.config.get("perception", {}))
        # Sight is a faculty: ONE entry point for all vision (coord.see), mirroring
        # the one reader for text. It perceives structure algorithmically and
        # admits it through the same perception ingress the manager uses.
        from core.perception.vision_faculty import get_vision_faculty
        self.vision = get_vision_faculty()
        self.planning = PlanningEngine(self.config.get("planning", {}))
        # Learning is the ONE authority (UnifiedLearningSystem), the same one the
        # substrate-self reaches via learning() — not the dead LearningAdapter.
        # There is a SINGLE learning attribute now: `self.learning`. It used to
        # be shadowed by a second `self.unified_learning` that main.py injected
        # with the very same singleton, so the coordinator carried two names for
        # one object. That injection is gone; readiness is read off the object
        # itself (`self.learning.initialized`), which is what "was it wired?"
        # actually asks.
        self.learning = get_learning_authority()
        #: When on, a user reply carries the full derivation (say()'s chain) for
        #: diagnosing; off (default) a user gets a plain sentence. Toggled with
        #: set_reply_debug(); a switch, so we can turn evidence back on to trace.
        self.reply_debug = False
        self._adaptive_types_registered = False
        # (was `_pending_decision_id` — a single slot shared across selections.
        # Removed: a decision id now travels in a per-call sink to the task it
        # belongs to, so it cannot be overwritten by a concurrent selection or
        # leaked onto an unrelated task.)

        # The Self — the substrate's integrator and the owner of the cognition
        # faculties (reasoning, learning, domains, motivation). The coordinator is
        # the BODY: it holds a handle to the Self and reaches faculties THROUGH it,
        # rather than constructing them itself. The Self does no reasoning/learning
        # /goal-forming — it holds the authorities that do.
        # Motivation is one of THIS substrate's own faculties — the intrinsic
        # motivation system that forms goals from its measured signals. It is the
        # module singleton (no rival instance); the config was always the default
        # {} — the real knob is `intrinsic_motivation_weight`, unrelated to
        # construction.
        from core.agents.autonomous.intrinsic_motivation import get_intrinsic_motivation_system
        self.intrinsic_motivation = get_intrinsic_motivation_system()

        # ── Knowledge cutoff tracking (persistent) ───────────────────────
        # This tracks (a) the declared training cutoff date for the current model
        # and (b) the last date through which the system has refreshed knowledge
        # via autonomous research tasks.
        self._knowledge_cutoff_state: Dict[str, Any] = {}
        try:
            self._knowledge_cutoff_state = self._load_knowledge_cutoff_state()
        except Exception as e:
            logger.debug(f"Knowledge cutoff state load failed (non-fatal): {e}")
        
        # === COMPLETION CALLBACK REGISTRY ===
        # Initialize this BEFORE register_completion_callback is called
        # Generic completion hook system - any subsystem can register completion handlers
        # Maps (TaskType, TaskSource) -> List[callback_fn]
        # Callbacks receive: (task: Task, result: Dict, confidence: float)
        self._completion_callbacks: Dict[tuple, List] = {}

        # Event/reaction dispatch — the substrate reacts to what happens to it
        # instead of a clock polling for it. Reactions registered via on() fire
        # when a matching SelfEvent is emitted: sync ones inline (isolated,
        # priority order), deferred ones on the drain worker (off the hot path).
        # This generalizes the completion-callback registry above; affect is the
        # first reaction, registered below.
        self._reactions: Dict[SelfEventType, List[Dict[str, Any]]] = {}
        self._reactive_queue: deque = deque()
        self._work_ready: asyncio.Event = asyncio.Event()
        self._reactive_worker: Optional[asyncio.Task] = None
        self._emit_depth: int = 0
        self._max_emit_depth: int = 8

        # Recognizers by route: domain -> clause-classifier name. Attaching one
        # (attach_recognizer) is what makes a perception route CHAIN from sensation
        # (`see`) into recognition (`perceive`). A route with no recognizer stays
        # pure sensation. One place to wire it; every percept-producing site that
        # names the same domain inherits the recognition+decision stage.
        self._recognizers: Dict[str, str] = {}

        # WHERE I am: the current environmental observation (identity + facts + whether it is new),
        # cached from the last time I looked at my surroundings. None until I have looked. This is the
        # outward half of self-awareness, composed into SelfState.situation.
        self._environment: Optional[Dict[str, Any]] = None

        # Coalescing state for the reactive motivation refresh (COMPETENCE_CHANGED
        # → refresh). An induction batch emits one event per domain it moved, so a
        # naive reaction would refresh N times; the dirty flag + single-flight task
        # collapse a burst into at most one in-flight + one queued refresh, and
        # never drop the last change.
        self._motivation_dirty: bool = False
        self._motivation_refresh_task: Optional[asyncio.Task] = None
        # Event-driven induction: a demonstration store enqueuing a signature wakes
        # a single-flight, drain-to-completion induction pass (replaces the 300s
        # idle_operator_induction poll). Coalescing state mirrors motivation above.
        self._induction_dirty: bool = False
        self._induction_drain_task: Optional[asyncio.Task] = None
        try:
            from core.learning.demonstration_store import set_on_pending as _set_on_pending
            _set_on_pending(self._wake_induction_drain)
        except Exception as _ind_reg_err:
            logger.debug("could not register induction producer trigger: %s", _ind_reg_err)
        # Event-driven domain expansion: a task-outcome write wakes a single-flight,
        # drain-to-completion expansion pass (replaces the 900s idle_domain_expansion
        # poll). It also wakes when a domain GAINS content, so outcomes skipped as
        # `domain_empty` are retried the moment their domain can absorb them.
        self._domain_expansion_dirty: bool = False
        self._domain_expansion_drain_task: Optional[asyncio.Task] = None
        # Event-driven domain discovery: a taught proposition admitted (declarative)
        # or a new learned operator (operational) wakes a single-flight full-sweep
        # crystallization (replaces the 900s idle_domain_discovery poll).
        self._domain_discovery_dirty: bool = False
        self._domain_discovery_drain_task: Optional[asyncio.Task] = None
        # Event-driven developmental drive: a burst of state-changing events
        # (competence/outcome/evidence/environment/deficit) collapses to ONE
        # frontier evaluation. This single-flight REPLACES the idle-timer poll as
        # the driver of intrinsic pursuit — selection fires when the self's state
        # actually changes, and is quiet when nothing warrants pursuit.
        self._pursuit_dirty: bool = False
        self._pursuit_selection_task: Optional[asyncio.Task] = None

        # Register completion callback for autonomous knowledge refresh research
        self.register_completion_callback(
            TaskType.RESEARCH,
            TaskSource.AUTONOMOUS,
            self._on_knowledge_refresh_complete,
            "Update knowledge refresh state"
        )

        # AFFECT — the reference reaction. A task outcome is a fitness-relevant
        # event, so the substrate feels it. This was hardwired at the completion
        # seam; it now fires when a TASK_COMPLETED event is emitted there.
        self.on(SelfEventType.TASK_COMPLETED, self._react_affect,
                name="affect", mode="sync", priority=90)

        # LEARNING — reactive, off the hot path. When an outcome is observed the
        # always-online learner induces the operators whose demonstrations were
        # gathered during acting, and moves the competence that earns — instead
        # of a 300s idle tier later draining them. Deferred: the hypothesis
        # search runs on the drain worker, never an acting slot, so the
        # deliberate record-cheap / induce-expensive split is preserved.
        self.on(SelfEventType.OUTCOME_OBSERVED, self._react_induce,
                name="operator_induction", mode="deferred", priority=50)
        # Domain expansion (this outcome) then transfer resolution (the return
        # leg) — the two halves the domain-expansion tier ran on a 900s clock,
        # now reacting to the outcome. Deferred, off the acting hot path;
        # expansion before transfer (expansion may write the transfers).
        self.on(SelfEventType.OUTCOME_OBSERVED, self._react_expand_outcome,
                name="domain_expansion", mode="deferred", priority=40)
        # A domain GAINING content (competence moved by induction, or a taught
        # proposition admitted) can make a previously `domain_empty` outcome
        # expandable, so those events wake the expansion drain too.
        self.on(SelfEventType.COMPETENCE_CHANGED, self._react_expand_outcome,
                name="domain_expansion_on_competence", mode="deferred", priority=35)
        self.on(SelfEventType.EVIDENCE_ADMITTED, self._react_expand_outcome,
                name="domain_expansion_on_evidence", mode="deferred", priority=35)
        self.on(SelfEventType.OUTCOME_OBSERVED, self._react_resolve_transfers,
                name="transfer_resolution", mode="deferred", priority=30)

        # TEACHING drives the domain map. When a taught proposition is admitted,
        # the domain authority re-checks whether the taught-concept graph now has
        # a coherent cluster to crystallize into its own subject domain (and
        # updates that domain's declarative-knowledge coverage). Deferred: the
        # graph scan runs on the drain worker, never the reply path. The idle
        # domain-discovery tier stays as a backstop.
        self.on(SelfEventType.EVIDENCE_ADMITTED, self._react_crystallize_taught,
                name="crystallize_taught", mode="deferred", priority=45)
        # Operational discovery: a newly learned operator creates an operator bucket
        # to crystallize/merge, so competence changes wake the full-sweep too.
        self.on(SelfEventType.COMPETENCE_CHANGED, self._react_crystallize_taught,
                name="domain_discovery_on_competence", mode="deferred", priority=35)

        # A background job the substrate submitted has come back. The receipt is
        # recorded here; a job that carried a domain outcome is folded into the
        # substrate's learning through the same OUTCOME_OBSERVED path its own
        # tasks use, so a spawned agent's findings advance the domain like any
        # other outcome. A failed job is logged with its error, never dropped.
        self.on(SelfEventType.JOB_COMPLETED, self._react_job_completed,
                name="job_completed", mode="deferred", priority=40)

        # COMPETENCE — a moved competence changes the per-domain competence DRIVE
        # (intrinsic motivation's inverted-U), so the motivation signals that read
        # it are stale until refreshed. COMPETENCE_CHANGED already fires from the
        # induction reaction; this gives it its first consumer, refreshing the
        # signals reactively (coalesced) instead of waiting for the %5 poll — which
        # stays as a backstop. This is a step toward taking motivation off the poll.
        self.on(SelfEventType.COMPETENCE_CHANGED, self._react_competence_changed,
                name="motivation_refresh", mode="deferred", priority=20)

        # GOVERNANCE — the real-time monitor watches the live ACTION stream. It does
        # NOT pre-gate; it OBSERVES each completed action, and on a breach snapshots
        # the moment and REDIRECTS (a teachable breach) or HALTS (a prime-directive
        # breach). A non-compliant verdict is an action outcome the substrate
        # OBSERVES — its own appraisal responds (governance reports the verdict; the
        # substrate feels its own). Deferred, off the acting hot path.
        self.on(SelfEventType.TASK_COMPLETED, self._react_governance_monitor,
                name="governance_monitor", mode="deferred", priority=50)

        # DEFICIT — a substrate planning failure the domain authority diagnosed as
        # a learnable gap is CLOSED here, reactively. The diagnosis is appraisal's
        # measurement (it owns the disposition); this reaction acts on it only when
        # the disposition favours it AND the deficit is one the substrate can
        # self-close, running the learning operation THROUGH the learning authority
        # and moving the belief authority as it goes — resolving the known-unknown
        # only on a close verified against the world. Deferred: exploration is
        # expensive and runs on the drain worker, never an acting slot (the
        # two-budget rule the induction reaction also honours).
        self.on(SelfEventType.DEFICIT_DIAGNOSED, self._react_close_deficit,
                name="close_deficit", mode="deferred", priority=35)

        # PERCEPTION — a recognition's confidence GOVERNS behaviour here, through the
        # same acceptance band that governs task completion. `perceive` reads the
        # posterior and emits the decision; this reaction carries it out: ACT on a
        # confident recognition, hold a below-band one for re-observation (VERIFY),
        # do nothing on an abstention. Deferred — off the acting hot path, like the
        # other consequence reactions. This is the live consumer that was missing:
        # without it the recognition+decision layer sat on top of sensation unwired.
        self.on(SelfEventType.PERCEPT_RECOGNIZED, self._react_percept,
                name="percept_decision", mode="deferred", priority=40)

        # A NEW environment was encountered -> begin investigating it (deferred so the encounter
        # returns immediately; the reaction turns observation into knowledge, and what stays uncertain
        # drives further probing through the motivation spine — event-driven, never a poll).
        self.on(SelfEventType.ENVIRONMENT_ENCOUNTERED, self._react_investigate_environment,
                name="environment_investigation", mode="deferred", priority=35)

        # THE DEVELOPMENTAL DRIVE — event-driven intrinsic pursuit. When the
        # self's state changes in a way that could change what is worth pursuing,
        # re-evaluate the frontier and select one pursuit. LOW priority so the
        # reactions that UPDATE that state (induction→competence, domain
        # expansion, environment investigation) run FIRST on the same event and
        # the pursuit reads the post-update self. Coalesced single-flight. This is
        # the driver; the idle-timer exploration poll is retired. Registered on
        # every state-changing event so the loop is self-sustaining through events.
        for _ev in (SelfEventType.COMPETENCE_CHANGED, SelfEventType.OUTCOME_OBSERVED,
                    SelfEventType.EVIDENCE_ADMITTED, SelfEventType.ENVIRONMENT_ENCOUNTERED,
                    SelfEventType.DEFICIT_DIAGNOSED):
            self.on(_ev, self._react_pursue_frontier,
                    name="pursue_frontier", mode="deferred", priority=10)

        # Directive System - High-level guidance for the Singleton
        self.directive_system = DirectiveSystem()

        # System Awareness Layers - Multi-layer adaptive awareness framework
        from core.system import (
            EnvironmentState, ActiveDiscovery, BehavioralAnalysis, InfrastructureTopology
        )
        self.env_state = EnvironmentState()
        self.discovery = ActiveDiscovery()
        # Publish it: the security audit needs Torin's own service inventory to
        # tell "my service is exposed" from "an unidentified process is listening".
        try:
            from core.system.active_discovery import register_active_discovery
            register_active_discovery(self.discovery)
        except Exception:
            pass
        self.behavioral = BehavioralAnalysis()
        self.topology = InfrastructureTopology()

        # Runtime Governance - Validates critical decisions against governance laws
        self.runtime_governance = get_runtime_governance()

        # WHAT I HAVE READ, AND OF WHICH VERSION. The substrate works from files
        # as they are, never from what it remembers them saying: every read is
        # stamped here, every write it performs is stamped as its own, and an act
        # on a file whose account is neither goes back to planning to read it
        # first. Owned by the self and handed to its constitution, which is what
        # turns "read before you act" from a habit into a law.
        # THE CONSTITUTION — a faculty of this body, not an outside judge. It
        # judges every act before it happens (allow / redirect / replan / block)
        # against the five laws, reading intent from what reasoning proved and
        # grounds from what the substrate has actually read.
        #
        # TAKEN from the module singleton rather than constructed here, because
        # the acting path (`tool_registry.execute_tool`) has to reach the same
        # one. The reading ledger follows it for the same reason: the ledger the
        # coordinator writes to when it reads a file MUST be the ledger Law 2
        # consults when it asks whether that file was read.
        self.constitution = get_constitution()
        self.reading = self.constitution.reading
        logger.info("📜 Constitution initialized — 5 laws, judging acts before they happen")

        # WHAT THE SUBSTRATE PERCEIVES ABOUT ITSELF, handed to its own law.
        #
        # The constitution asks; the self answers. It does not reach into the
        # coordinator, and the coordinator does not hardcode a list — `_situate`
        # already observes the root, the ledger already holds what was authored,
        # and the database already knows its own name. Sensitivity about the
        # substrate's own things is DERIVED from that, not declared in a config
        # someone has to remember to update.
        self.constitution.set_self_perception(self._perceive_self_for_law)

        # AND WHAT IT KNOWS OF THE WORLD, handed to the same law.
        #
        # The constitution's definition of harm answers a second question when
        # it is asked of something PERCEIVED rather than of an act: does what I
        # am looking at touch an interest my law protects. Answering it needs
        # the substrate's taught taxonomy — `famine isa disaster isa harmed` —
        # so the reader is injected exactly as self-perception is, and for the
        # same reason: the constitution stays free of a database handle because
        # `judge_act` is on the acting path and is measured in microseconds.
        self.constitution.set_taxonomy_reader(_TaxonomyReader())

        #: DRIFT — the second first-class faculty, beside the constitution.
        #: The constitution judges ACTS; this perceives the SUBSTRATE. One
        #: instance, owned by the self, for the same reason the constitution is:
        #: a faculty the self holds rather than an outside service it reports to.
        self.drift = Drift()
        logger.info("📉 Drift initialized — %d detector(s) over the substrate's own "
                    "change; severity per signal, never averaged",
                    len(self.drift.detectors))

        #: APPRAISAL — the third first-class faculty, beside the constitution
        #: and drift. The constitution judges ACTS, drift perceives the
        #: SUBSTRATE'S CHANGE, and this holds HOW THE SUBSTRATE STANDS toward
        #: its situation: the one authority converting signals into disposition.
        #:
        #: HELD, NOT IMPORTED. It was reached through `get_appraisal_system()`
        #: at twenty call sites — a faculty as central as the other two, and the
        #: only way to see it was to know which module to import. Taken from the
        #: singleton for exactly the reason the constitution is: the memory
        #: agent and the motivation system reach the same one, and two appraisals
        #: would be two dispositions, with "how do I feel" answered differently
        #: depending on who asked.
        from core.agents.autonomous.appraisal import get_appraisal_system
        self.appraisal = get_appraisal_system()
        logger.info("🫀 Appraisal initialized — one disposition, %d dimension(s); "
                    "unmeasured stays distinguishable from measured-and-neutral",
                    len(self.appraisal.DIMENSIONS))

        #: THE SUBSTRATE'S REPRESENTATION OF ITSELF — composed at the end of
        #: `initialize()`, once every faculty it is made of is up.
        #:
        #: None before that, and None is the honest answer: a self-state
        #: assembled from faculties that do not exist yet describes nothing. Kept
        #: here so the faculties that decide read ONE representation rather than
        #: each reaching for a different fragment of it.
        self.self_state = None

        # Phase 2: Multi-level safety prompts for long-horizon planning protection
        from core.safety import MultiLevelSafetyPrompts
        self.safety_prompts = MultiLevelSafetyPrompts()
        logger.info("🛡️ Multi-level safety prompts initialized")

        # === EVENT-DRIVEN TASK EXECUTION ===
        from core.agents.autonomous.queue_authority import get_queue_authority

        # The substrate does NOT own the queue. It is a WORKER: it draws work
        # from the ONE queue authority and does it, through its substrate-only,
        # model-free executor. The authority owns the backlog, the concurrency
        # pool, await-jobs, and scheduling — one place that knows what work
        # exists, what is running, and what is due. `self.task_queue` is the
        # shared singleton authority (not a private queue), configured here by
        # the substrate that draws from it: the acting cap is the work-job
        # concurrency; background jobs (await/scheduled) get their own budget.
        self.task_queue = get_queue_authority(config={
            "max_parallel": int(self.config.get("max_parallel_tasks", 6)),
            "job_timeout_seconds": self.config.get("task_timeout_seconds", 3600.0),
        })
        # EXECUTION is the self's own faculty, not a delegate agent. The state the
        # former GeneralPurposeExecutor held lives here now; the methods it defined
        # are the coordinator's own (below). No model handle -- substrate-only.
        from core.database import TorinUnifiedDatabase
        self.db = TorinUnifiedDatabase()
        self.tool_registry = None
        self._env_loaded = False
        self._dotenv_values = None
        self.completed_tasks: Dict[str, Any] = {}
        # ONE completion authority: `_execute_and_validate_task` decides "done"
        # from the `verification_state` each execution handler set by RE-OBSERVING
        # its real effect (a tool's real success, an operator that became
        # executable, an answer actually learned) — never a self-attested success
        # flag. The old validators (TaskCompletionValidator and the legacy
        # SuccessValidator, which rubber-stamped fabricated completions over the
        # result dict) are DELETED; there is no separate completion protocol.
        self._idle_count = 0

        # === EXPLORATION LOOP STATE ===
        self._current_motivation = {}  # Latest motivation signal from intrinsic system
        self._exploring_components: Set[str] = set()  # Component lock: prevents re-exploring same component
        self._recent_exploration_fp_list: list = []  # Dedup: ordered list of recent exploration fingerprints (FIFO, max 20)
        self._permanently_failed_fps: Set[str] = set()  # FPs of tasks that permanently failed — never re-queued this session
        try:
            self._permanently_failed_fps = self._load_permanently_failed_fps()
        except Exception as _fp_load_err:
            logger.debug(f"Failed to load permanently-failed fingerprints (non-fatal): {_fp_load_err}")
        # Intrinsic exploration queue control
        # Applies only to intrinsic exploration tasks (metadata: intrinsic_kind="exploration").
        # Set to 0 to disable intrinsic exploration entirely.
        _cap_raw = os.getenv("TORINAI_INTRINSIC_EXPLORATION_CAP")
        try:
            self._intrinsic_exploration_cap: int = (
                int(_cap_raw)
                if _cap_raw is not None
                else int(self.config.get("intrinsic_exploration_cap", 1))
            )
        except Exception:
            self._intrinsic_exploration_cap = 1
        if self._intrinsic_exploration_cap < 0:
            self._intrinsic_exploration_cap = 0
        self._idle_subsystems_registered: bool = False  # One-time flag for _register_idle_subsystems()

        # Concurrent execution. The loop used to `await` one task to completion,
        # so the substrate executed strictly one task at a time AND could not
        # reflect while any task was running.
        self._inflight_tasks: Dict[str, asyncio.Task] = {}
        #: PER-USER concurrency. The global cap below bounds TOTAL acting slots (the
        #: real compute ceiling); this bounds how many a single USER may hold at once,
        #: so several users each run multiple tasks concurrently and none monopolises
        #: the pool. The substrate's OWN actor is exempt (its autonomous work is bounded
        #: only by the global ceiling). `_inflight_by_actor` is the live per-actor count
        #: (kept in the single cognition loop, so it is race-free); `_inflight_actor`
        #: remembers each launched task's actor so the count is decremented on reap.
        self._inflight_by_actor: Dict[str, int] = {}
        self._inflight_actor: Dict[str, str] = {}
        self._per_actor_max: int = int(self.config.get("per_actor_max_tasks", 3))
        self._max_parallel_tasks: int = int(self.config.get("max_parallel_tasks", 6))
        # DIRECTIVE-DRIVEN acting cap. When an ACTIVE resource_allocation directive
        # exists, its max_parallel_tasks overrides the hardcoded default above (the
        # config value stays the fallback). Refreshed from select_guidance in the
        # motivation cycle so the hot acting gate reads a cached int, not an async
        # call. `_directive_resource_id` is the active directive being applied, so
        # its outcomes can be credited to the learning authority.
        self._directive_max_parallel: Optional[int] = None
        self._directive_resource_id: Optional[str] = None
        # No private pool: concurrency is the queue authority's (self.task_queue).
        # Idempotency log: "{trigger_id}:{action}" → unix timestamp of last execution.
        # Prevents Slack spam, double-restarts, repeated credential rotations, etc.
        self._step_execution_log: Dict[str, float] = {}
        # Unix timestamp of the last prune pass; prune runs every 10 min.
        self._step_log_last_pruned: float = 0.0

        # ── Idle review snapshots (facts-first, no LLM) ───────────────────
        self._idle_last_health_check_at: Optional[datetime] = None
        self._idle_last_health_snapshot: Dict[str, Any] = {
            "components_total": None,
            "unhealthy_total": None,
        }
        self._idle_last_system_review_at: Optional[datetime] = None
        self._idle_system_review_snapshot: Optional[Dict[str, Any]] = None

        # ── Idle knowledge refresh (web research cadence) ─────────────────
        self._idle_last_knowledge_refresh_at: Optional[datetime] = None
        
        # Per-component backoff state for health recovery.
        # Keys are component names; values are dicts with:
        #   attempts     int   — number of completed recovery cycles (reset when healthy)
        #   last_attempt float — unix ts of last recovery attempt
        #   escalated    bool  — True once the escalation notification has been sent
        self._component_recovery_state: Dict[str, dict] = {}

        # Memory system - can be provided or created (will be initialized in async initialize() method)
        if 'memory' in self.config and not isinstance(self.config['memory'], dict):
            # Memory system instance provided directly
            self.memory = self.config['memory']
        else:
            # Will be initialized asynchronously in initialize() method
            self.memory = None

        # === MEMORY QUERY AGENTS ===
        # Specialized agents for querying and summarizing memory (PostgreSQL store).
        # Canonical MemoryInjector, injected by main.py after construction. The
        # coordinator must not build its own — one mechanism, one owner.
        self.memory_injector = None

        # mysql_memory_agent removed: it was labelled "PRIMARY" but was never
        # assigned anywhere, and MySQL is retired (PostgreSQL is the store). Its
        # only consumer, get_intelligent_memory_context(), now goes through the
        # policy + MemoryInjector path.
        logger.info("Memory query agents will be initialized during startup")

        # === ENHANCED REASONING SYSTEM ===
        # Complete reasoning toolkit available across the entire Singleton
        self.abstract_reasoning = create_abstract_reasoning_engine()  # Abstract & logical reasoning
        from core.reasoning import AdvancedProofEngine
        self.proof_engine = AdvancedProofEngine()  # Formal proof generation

        # Quantum reasoning (disabled by default - requires IBM Quantum connection)
        self.enable_quantum = self.config.get("enable_quantum", False)
        self.quantum_reasoning = None
        if self.enable_quantum:
            from core.reasoning import QuantumReasoningSystem
            self.quantum_reasoning = QuantumReasoningSystem()
            logger.info("🧠 Enhanced reasoning initialized - Abstract, Quantum, Proof systems ready")
        else:
            logger.info("🧠 Enhanced reasoning initialized - Abstract + Proof (quantum DISABLED)")

        # Neural Bridge - this substrate's reasoning faculty (the model-free
        # NeuralSymbolicBridge, routing to abstract/Z3). Brought up at startup.
        self.neural_bridge = None  # set to get_neural_bridge() during startup
        
        # === UNIFIED INTELLIGENCE ===
        # `unified_learning` is GONE: it was a second name for `self.learning`
        # (main.py injected the same authority singleton into it). The one
        # learning authority is `self.learning`, established above. Self-improvement
        # is not an act the substrate performs on itself: it has no model weights
        # and never rewrites its own code or configuration. It improves by learning
        # — action→outcome, reasoning, experiments — through the learning authority,
        # and self-improvement is whatever that learning changed.

        self.intelligence = PredictiveIntelligenceSystem(self.config.get("intelligence", {}))
        
        # === COGNITIVE TOOLKIT ===
        # These are the Singleton's tools for understanding, learning, and self-improvement

        # Causal analysis for understanding WHY feedback patterns occur
        try:
            from core.learning.causal_feedback_analyzer import CausalFeedbackAnalyzer
            self.causal_analyzer = CausalFeedbackAnalyzer()
            logger.info("✅ Causal analyzer initialized - Singleton can understand root causes")
        except Exception as e:
            logger.warning(f"⚠️  Causal analyzer not available: {e}")
            self.causal_analyzer = None

        # Meta-learning for rapid adaptation to new tasks (shared singleton)
        try:
            from core.learning.meta_learning import get_meta_learner
            self.meta_learning = get_meta_learner(
                config=self.config.get("meta_learning_config", {
                    "min_trials": 3,
                    "adaptation_threshold": 0.1,
                    "enable_adaptation": True
                })
            )
            logger.info("✅ Meta-learning initialized - Singleton can learn from few examples")
        except Exception as e:
            logger.warning(f"⚠️ Meta-learning not available: {e}")
            self.meta_learning = None
        
        
        # The coordinator holds no model handle. It is a body driven by the
        # Self.

        # Enhanced capabilities - initialized from config dependencies
        self.domain_registry: Optional[DomainRegistry] = self.config.get("domain_registry")
        self.universal_domain_master: Optional[UniversalDomainMaster] = self.config.get("universal_domain_master")
        # self.predictive_intelligence DELETED: a config-only shadow that was
        # never assigned (always None) while self.intelligence holds the real
        # constructed PredictiveIntelligenceSystem. Both called the same
        # generate_comprehensive_prediction(); one storage location is
        # authoritative. Callers migrated to self.intelligence.

        # CRITICAL: Health Monitor - Singleton OWNS health monitoring
        # If not provided, create it. This is NON-NEGOTIABLE.
        self.health_monitor = self.config.get("health_monitor")
        if self.health_monitor is None:
            try:
                logger.info("🏥 Health Monitor not provided - Singleton creating health monitoring system")
                from core.health.health_monitor import HealthMonitor
                health_config = self.config.get("health_monitor_config", {})
                self.health_monitor = HealthMonitor(config=health_config)
                logger.info("✅ Health Monitor created and owned by Singleton")
            except Exception as e:
                logger.warning(f"⚠️ Health Monitor not available: {e}")
                import traceback
                logger.warning(f"Traceback: {traceback.format_exc()}")
                self.health_monitor = None
        else:
            logger.info("✅ Health Monitor provided to Singleton")

        # CRITICAL: Recovery Manager - Enables autonomous self-healing
        # Executes the idle health tier's recovery playbook steps
        self.recovery_manager = self.config.get("recovery_manager")
        if self.recovery_manager is None:
            try:
                logger.info("🔧 Recovery Manager not provided - Singleton creating recovery system")
                from core.health.recovery_manager import RecoveryManager
                recovery_config = self.config.get("recovery_manager_config", {})
                self.recovery_manager = RecoveryManager(config=recovery_config)
                logger.info("✅ Recovery Manager created - AI self-healing enabled")
            except Exception as e:
                logger.warning(f"⚠️ Recovery Manager not available: {e}")
                import traceback
                logger.warning(f"Traceback: {traceback.format_exc()}")
                self.recovery_manager = None
        else:
            logger.info("✅ Recovery Manager provided to Singleton")

        # CRITICAL: Logging Database - For comprehensive operational logging
        self.log_db = self.config.get("log_db")
        if self.log_db is None:
            try:
                logger.info("📝 Logging database not provided - creating logging system")
                self.log_db = LoggingDatabase()
                # Will be initialized in async initialize() method
                logger.info("✅ Logging database created for autonomous coordinator")
            except Exception as e:
                logger.warning(f"⚠️ Logging database not available: {e}")
                self.log_db = None
        else:
            logger.info("✅ Logging database provided to autonomous coordinator")

        # Slack notifier for system notifications
        self.slack_notifier = get_slack_notifier()
        logger.info("✅ Slack notifier integrated into autonomous coordinator")

        # Agent authority (the factory, core/agents/agents.py) — bound by
        # main.py after init. The self deploys agents of self through it
        # (deploy_agent / await_agent / collect_agent_findings / pending_agents).
        self.agent_coordinator: Any = None
        
        # Coordination state
        self.coordination_task: Optional[asyncio.Task] = None
        self.last_cycle_time = datetime.now()
        
        # Enhanced statistics
        self.stats = {
            "cycles_completed": 0,
            "goals_achieved": 0,
            "tasks_completed": 0,
            "uptime_seconds": 0.0,
            "system_efficiency": 0.0,
            "cross_domain_operations": 0,
            "predictions_made": 0,
            "domain_integrations": 0,
            # execution-faculty counters (absorbed from the former executor)
            "tasks_executed": 0,
            "tasks_successful": 0,
            "tasks_failed": 0,
            "by_type": {},
            # Reactive-faculty counters (honest metrics, surfaced via get_status).
            # motivation_refreshes_reactive: refreshes driven by COMPETENCE_CHANGED
            #   (vs the %5 poll); motivation_refresh_errors: refreshes that actually
            #   failed (counted, not swallowed); external_blocker_escalations: times
            #   the arbiter judged a task failure to be an EXTERNAL blocker and the
            #   self-directed diagnostic was suppressed instead of thrashing.
            "motivation_refreshes_reactive": 0,
            "motivation_refresh_errors": 0,
            "external_blocker_escalations": 0,
        }

        # Register this coordinator as the active runtime instance so other
        # components (e.g., tools) can update runtime-owned counters.
        try:
            from core.agents.autonomous.runtime_registry import register_autonomous_coordinator

            register_autonomous_coordinator(self)
        except Exception:
            # Registry is best-effort; never block startup.
            pass
        # Idle detection for boredom-driven goal generation
        self._last_requests_processed: int = 0
        self._idle_cycles: int = 0
        # Last time a drift alert was published (to avoid spamming)
        self._last_drift_alert_at: Optional[datetime] = None

        # === IDLE PRIORITY TIMESTAMPS ===
        # Track last execution of each priority tier so the idle dispatcher
        # can pick the highest-priority action that is actually due.
        self._idle_last_health_check: Optional[datetime] = None
        self._idle_last_meta_learning: Optional[datetime] = None
        self._idle_last_memory_consolidation: Optional[datetime] = None

    async def initialize(self, start_loop: bool = False) -> bool:
        """
        Initialize all system modules
        
        Args:
            start_loop: If True, start the coordination cycle immediately. 
                       If False, loop can be started later with start_coordination()
        """
        try:
            logger.info("Initializing autonomous system...")
            
            # No model to connect: this substrate reasons through its OWN
            # faculties (neural_bridge, learning, domains…), never a held model
            # handle.

            # Initialize logging database if it was created but not yet initialized
            if self.log_db and not getattr(self.log_db, 'initialized', False):
                await self.log_db.initialize()
                logger.info("✅ Logging database initialized")

            # Initialize memory agent if not provided
            if self.memory is None:
                # Use unified memory entrypoint from core.memory
                from core.memory import get_memory_agent, initialize_memory_agent
                try:
                    self.memory = await get_memory_agent()
                    logger.info("✅ Memory agent retrieved from singleton")
                except:
                    memory_config = self.config.get("memory", {})
                    self.memory = await initialize_memory_agent(**memory_config) if memory_config else await initialize_memory_agent()
                    logger.info("✅ Memory agent initialized")

            # Initialize core modules
            modules = [
                ("Perception Manager", self.perception),
                ("Planning Engine", self.planning),
                # Learning is the SubstrateLearning authority — stateless over its
                # stores, so it has no initialize() step (see Self.initialize).
                ("Intrinsic Motivation System", self.intrinsic_motivation),
                ("Memory Manager", self.memory),
                ("Intelligence System", self.intelligence),
            ]

            for name, module in modules:
                if not await module.initialize():
                    logger.error(f"Failed to initialize {name}")
                    return False
                logger.info(f"{name} initialized successfully")

            # Connect learning adapter to shared systems
            if self.runtime_governance and hasattr(self.learning, 'set_governance_system'):
                self.learning.set_governance_system(self.runtime_governance)

            # Initialize the EXECUTION FACULTY (absorbed from the former executor).
            if not await self.initialize_execution_faculty():
                return False

            # Initialize Directive System
            logger.info("=" * 80)
            logger.info("🎯 DIRECTIVE SYSTEM - Loading High-Level Guidance")
            logger.info("=" * 80)
            try:
                if hasattr(self.directive_system, 'initialize'):
                    if not await self.directive_system.initialize():
                        logger.warning("Directive System failed to initialize (non-critical)")
                    else:
                        logger.info("✅ Directive System ready - Singleton has high-level objectives")
                else:
                    logger.warning("Directive System has no initialize method (non-critical)")
            except Exception as e:
                logger.warning(f"Directive System initialization error (non-critical): {e}")

            # Activate the constitution — the drift-assessment authority. Without
            # this, assess_constitutional_alignment short-circuits on `not active`
            # and returns an EMPTY assessment (no laws scored), so the revived
            # constitutional-alignment tier would run against nothing. This only
            # enables the read-only 5-law drift assessment; per-action enforcement
            # is the governance trigger engine (owned by runtime governance).
            try:
                if await self.constitution.initialize():
                    logger.info("✅ Constitution active — 5 governance laws assessed for drift")
                else:
                    logger.warning("Constitution did not activate — drift checks will be inert")
            except Exception as e:
                logger.warning(f"Constitution activation error: {e}")

            # Initialize enhanced reasoning systems
            logger.info("=" * 80)
            logger.info("🧠 ENHANCED REASONING - Initializing Advanced Intelligence")
            logger.info("=" * 80)
            
            if not await self.abstract_reasoning.initialize():
                logger.error("Failed to initialize Abstract Reasoning Engine")
                return False
            logger.info("✅ Abstract Reasoning Engine ready")
            
            if self.enable_quantum and self.quantum_reasoning:
                await self.quantum_reasoning.initialize()
                logger.info("✅ Quantum Reasoning System ready")
            else:
                logger.info("⏭️  Quantum Reasoning System DISABLED (no IBM connection)")

            try:
                if hasattr(self.proof_engine, 'initialize'):
                    await self.proof_engine.initialize()
                logger.info("✅ Advanced Proof Engine ready")
            except Exception as e:
                logger.warning(f"Advanced Proof Engine initialization error (non-critical): {e}")
            
            # This substrate's OWN cognition faculties. Each is the module
            # singleton (no rival instance): reasoning ↔ logic/proof via the
            # NeuralSymbolicBridge, the predictive/foresight engine, the domain
            # authority, and meta-learning. Bring up the ones with async
            # initializers, then take each handle directly.
            try:
                from core.reasoning.neural_bridge import get_neural_bridge
                from core.integration.universal_domain_master import get_universal_domain_master
                from core.learning.meta_learning import get_meta_learner
                self.neural_bridge = get_neural_bridge()
                self.universal_domain_master = get_universal_domain_master()
                self.meta_learning = get_meta_learner()
                for _name, _faculty in (("reasoning", self.neural_bridge),
                                        ("domains", self.universal_domain_master),
                                        ("motivation", self.intrinsic_motivation)):
                    _init = getattr(_faculty, "initialize", None)
                    if _init is not None:
                        try:
                            await _init()
                        except Exception as fe:
                            logger.warning(f"Self: {_name} faculty init failed: {fe}")
                # Predictive intelligence (async getter) — one engine, brought up
                # once and held here.
                try:
                    from core.intelligence import get_predictive_intelligence
                    _intel = await get_predictive_intelligence()
                    if _intel is not None:
                        self.intelligence = _intel
                except Exception as ie:
                    logger.warning(f"Self: intelligence faculty init failed: {ie}")
                logger.info("✅ Cognition faculties ready - reasoning ↔ logic, "
                            "intelligence, domains, meta-learning")
            except Exception as e:
                logger.warning(f"⚠️ Neural Bridge initialization failed: {e}")
            
            logger.info("🎯 Enhanced reasoning fully operational across Singleton")
            
            # Initialize Unified Learning System (Singleton's tool)
            logger.info("=" * 80)
            logger.info("📚 UNIFIED LEARNING SYSTEM - Master Learning Tool")
            logger.info("=" * 80)

            try:
                await self.learning.start()
                logger.info("✅ Unified Learning System ready - Master learning tool operational")
                logger.info("   The Singleton can now learn, adapt, and self-improve")
            except Exception as e:
                logger.warning(f"⚠️ Unified Learning System initialization failed (non-critical): {e}")
            
            # Initialize cognitive toolkit (async systems)
            logger.info("=" * 80)
            logger.info("🧠 COGNITIVE TOOLKIT - Initializing Advanced Systems")
            logger.info("=" * 80)
            
            try:
                # Meta-learning system
                await self.meta_learning.initialize()
                logger.info("✅ Meta-Learning System ready - few-shot learning enabled")
            except Exception as e:
                logger.warning(f"⚠️ Meta-learning initialization failed: {e}")

            # Causal analyzer and improvement monitor don't need async init
            logger.info("✅ Causal Analyzer ready - root cause analysis enabled")
            logger.info("✅ Improvement Monitor ready - A/B testing enabled")

            # Initialize memory query agents
            # Get memory agent singleton
            try:
                from core.memory import get_memory_agent
                memory_agent = await get_memory_agent()
                if memory_agent:
                    logger.info("✅ Memory Query Agent ready - Using unified memory system")
                else:
                    logger.warning("⚠️ Memory agent not available")
            except Exception as e:
                logger.warning(f"⚠️ Memory query agents initialization failed: {e}")

            # The ONE perception pipeline. Activate the overall sensory hub so it is
            # the single admitter every percept (vision, sensors, any modality) funnels
            # through. It had never been initialized, so `active` stayed False,
            # process_input early-returned, and the substrate retained no perception
            # while vision admitted through a second, parallel path. One owner now.
            try:
                if await self.perception.initialize():
                    logger.info("✅ Perception hub ready — one perception pipeline active")
                else:
                    logger.warning("⚠️ Perception hub did not activate")
            except Exception as e:
                logger.warning(f"⚠️ Perception hub initialization failed: {e}")

            # Now that I can perceive, look at WHERE I am: register the environment I have been
            # placed in as a first-class ENVIRONMENT domain (which makes it a target to investigate),
            # and notice if it is new. This is the outward half of self-awareness coming online.
            try:
                await self._situate()
            except Exception as e:
                logger.warning(f"⚠️ Environment awareness (situate) failed: {e}")

            # CRITICAL: Initialize Health Monitor
            if self.health_monitor:
                if hasattr(self.health_monitor, 'initialize'):
                    try:
                        await self.health_monitor.initialize()
                        logger.info("✅ Health Monitor initialized - System health monitoring active")
                    except Exception as e:
                        logger.error(f"❌ CRITICAL: Health Monitor initialization failed: {e}")
                        raise RuntimeError(f"Health Monitor is REQUIRED but failed to initialize: {e}") from e
                else:
                    logger.info("✅ Health Monitor ready (no initialization required)")
                # Register core TorinAI services so the health monitor tracks them
                _core_components = ["database", "memory", "learning", "reasoning", "security", "storage"]
                for _comp in _core_components:
                    try:
                        await self.health_monitor.check_component_health(_comp)
                    except Exception:
                        pass
                logger.info(f"✅ Registered {len(_core_components)} core health components")
            else:
                logger.error("❌ CRITICAL: Health Monitor is None - this should never happen!")
                raise RuntimeError("Health Monitor is REQUIRED but is None - Singleton cannot operate without health monitoring")

            # CRITICAL: Initialize Recovery Manager (for AI self-healing)
            if self.recovery_manager:
                if hasattr(self.recovery_manager, 'initialize'):
                    try:
                        await self.recovery_manager.initialize()
                        logger.info("✅ Recovery Manager initialized - AI self-healing enabled")
                    except Exception as e:
                        logger.error(f"❌ CRITICAL: Recovery Manager initialization failed: {e}")
                        raise RuntimeError(f"Recovery Manager is REQUIRED for self-healing but failed to initialize: {e}") from e
                else:
                    logger.info("✅ Recovery Manager ready (no initialization required)")
            else:
                logger.warning("⚠️ Recovery Manager is None - AI self-healing disabled")
                logger.warning("   Self-healing requires RecoveryManager for strategic recovery actions")

            logger.info("=" * 80)

            # Log boosted autonomous goal generation settings
            logger.info("=" * 80)
            logger.info("🎯 AUTONOMOUS GOAL GENERATION - Boosted Settings")
            logger.info("=" * 80)
            max_goals = self.coordinator_config.max_concurrent_goals
            intrinsic_weight = self.coordinator_config.intrinsic_motivation_weight
            logger.info(f"   Max Concurrent Goals:      {max_goals} (baseline: 5)")
            logger.info(f"   Intrinsic Motivation Weight: {intrinsic_weight:.2f} (baseline: 0.30)")
            logger.info(f"   Goal Generation Frequency: Every 3 cycles (baseline: 20)")
            logger.info(f"   Min Active Goals Threshold: 3 (baseline: 2)")
            logger.info(f"   Min New Goals per Gen:     2 (baseline: 1)")
            logger.info("=" * 80)

            # Autonomous idle system handles all task scheduling
            logger.info("=" * 80)
            logger.info("🎯 AUTONOMOUS IDLE SYSTEM - Active (security / health / review on schedule)")
            logger.info("=" * 80)

            # Runtime mutation protection. Must come after all modules are
            # loaded, because it snapshots their attributes and source hashes
            # as the baseline for tamper detection.
            #
            # This also hash-protects config/governance_triggers.json, which now
            # holds the per-invocation safety rules — the file the whole safety
            # gate reasons from. Nothing was watching it before this call
            # existed: enable_runtime_protection() had zero call sites, so no
            # baseline was ever taken and verify_runtime_integrity() could only
            # early-return 'protection_not_enabled'.
            try:
                if self.runtime_governance:
                    _prot = await self.runtime_governance.enable_runtime_protection()
                    logger.info(
                        f"🛡️  Runtime protection: {_prot.get('frozen_modules')}/"
                        f"{_prot.get('total_critical_modules')} modules frozen, "
                        f"{len(_prot.get('config_files_hashed') or [])} config file(s) hash-protected"
                    )
            except Exception as e:
                logger.error(f"Runtime protection could not be enabled: {e}")

            # Set system mode
            self.system_state.mode = SystemMode.AUTONOMOUS
            self.active = True

            # ── THE SUBSTRATE COMPOSES ITS SELF-STATE ────────────────────────
            #
            # `SelfState` was built, worked, and was read by NOTHING: `state()`
            # had one caller (`render()`), and `render()` had none. The substrate
            # could describe itself and never did, because nobody asked.
            #
            # This is where it asks. Composed LAST, after every faculty it is
            # made of is up — a self-state taken before motivation, learning and
            # the domains exist would be a picture of an empty room. Held on the
            # coordinator so faculties read ONE representation instead of each
            # reaching for its own fragment, which is what `_intrinsic_pursuits`
            # (reading `_development`) and the appraisal→pressure path (reading
            # appraisal's dimensions) do today: two metacognitive loops, two
            # different partial views, no shared self.
            #
            # Failure here never fails startup. A substrate that cannot compose
            # its self-state still runs; it simply says so, rather than booting
            # with a fabricated one.
            try:
                self.self_state = await self.state()
                _known = [f for f in ("interoception", "attitude", "affect",
                                      "purpose", "competence", "development",
                                      "situation", "continuity")
                          if getattr(self.self_state, f, None) is not None]
                _unknown = [f for f in ("interoception", "attitude", "affect",
                                        "purpose", "competence", "development",
                                        "situation", "continuity")
                            if getattr(self.self_state, f, None) is None]
                logger.info(
                    "🪞 Self-state composed: %d/%d derived fields have a live "
                    "source (%s); not yet established: %s",
                    len(_known), len(_known) + len(_unknown), ", ".join(_known),
                    ", ".join(_unknown) or "none")
            except Exception as e:
                # Honest gap: no self-state rather than an invented one.
                self.self_state = None
                logger.error("the substrate could not compose its self-state at "
                             "startup; it begins without one: %s", e)

            # Don't start coordination cycle during initialization
            # It will be started later via start_background_tasks()
            # Keep start_loop parameter for backward compatibility but log deprecation
            if start_loop:
                logger.warning("start_loop parameter is deprecated - use start_background_tasks() after full system init")

            logger.info("Autonomous system initialization completed (coordination cycle deferred)")

            return True
            
        except Exception as e:
            logger.error(f"Error during initialization: {e}")

            # Send notification for autonomous coordinator initialization failure
            try:
                from core.utils.notification_helpers import notify_autonomous_event
                asyncio.create_task(notify_autonomous_event(
                    event_type="error",
                    details=f"**Autonomous Coordinator initialization failed**\n\n**Error:** {str(e)}\n\n**Impact:** Singleton cannot operate autonomously",
                    severity="critical"
                ))
            except Exception as notify_error:
                logger.warning(f"Failed to send autonomous coordinator error notification: {notify_error}")

            return False
    
    async def _report_failure(self, component: str, failure_type: str,
                              description: str, severity: str = "medium",
                              exception: Optional[BaseException] = None,
                              metadata: Optional[Dict[str, Any]] = None) -> None:
        """Put a failure on the canonical record.

        The coordinator is the substrate's own loop, so its failures are the
        ones every other system most needs to know about -- and it reported
        exactly none of them anywhere queryable. Defensive by construction:
        this is called from failure paths and must never create a second one.
        """
        try:
            from core.observability import failure_record

            await failure_record.report(
                component=component, failure_type=failure_type,
                description=description, source_system="autonomous_coordinator",
                severity=severity, exception=exception, metadata=metadata or {})
        except Exception as error:
            logger.error("Coordinator failure not recorded: %s", error)

    async def start_coordination(self):
        """Start the autonomous coordination cycle (if not already running)"""
        if self.coordination_task is None and self.active:
            # Rehydrate the durable backlog BEFORE the loop starts pulling, so
            # work accepted before the last restart (and any task interrupted
            # mid-run) is back in the queue rather than silently lost.
            restored = await self.task_queue.restore_pending()
            if restored.get("restored"):
                logger.info("♻️  restored %d queued task(s) from durable store "
                            "(%d interrupted -> restarted)",
                            restored["restored"], restored["restarted"])
            # Cadence ownership goes live with the substrate: hand the timed
            # tiers to the queue authority's scheduler here, the one entry point
            # every start path funnels through. Idempotent (guarded), so calling
            # start_coordination more than once cannot double-schedule.
            self._register_idle_subsystems()
            self.coordination_task = asyncio.create_task(self._coordination_cycle())
            self._start_reactive_worker()
            logger.info("🚀 Autonomous coordination cycle started")
        elif self.coordination_task is not None:
            logger.info("Coordination cycle already running")
        else:
            # THE SUBSTRATE NOT STARTING IS THE MOST CONSEQUENTIAL FAILURE
            # THERE IS, and it was a warning in a log file. Nothing that
            # watches for trouble could see that the coordination cycle -- the
            # thing that runs the substrate -- had declined to start.
            logger.warning("Cannot start coordination - system not initialized or not active")
            await self._report_failure(
                component="agents.autonomous_coordinator",
                failure_type="startup_failure",
                description=("Coordination cycle did not start: system reports "
                             f"active={self.active}, initialized="
                             f"{getattr(self, 'initialized', 'unknown')}"),
                severity="critical",
                metadata={"active": bool(self.active)})
    
    async def start_background_tasks(self):
        """Start background coordination tasks after full system initialization"""
        if not self.active:
            logger.warning("Cannot start background tasks - system not initialized")
            return
        
        logger.info("🚀 Starting autonomous coordinator background tasks")
        
        # CRITICAL: Start health monitoring FIRST
        if self.health_monitor and hasattr(self.health_monitor, 'start_monitoring'):
            try:
                await self.health_monitor.start_monitoring()
                logger.info("✅ Health monitoring loop started")
            except Exception as e:
                logger.error(f"❌ CRITICAL: Failed to start health monitoring: {e}")

                # Send notification for health monitoring startup failure
                try:
                    from core.utils.notification_helpers import notify_autonomous_event
                    asyncio.create_task(notify_autonomous_event(
                        event_type="error",
                        details=f"**Health monitoring failed to start**\n\n**Error:** {str(e)}\n\n**Impact:** System health cannot be monitored",
                        severity="critical"
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send health monitoring error notification: {notify_error}")

                raise RuntimeError(f"Health monitoring is REQUIRED but failed to start: {e}") from e
        
        # Start coordination cycle (continuous exploration loop). It registers
        # the idle tiers on the queue authority's scheduler as it goes live.
        await self.start_coordination()

        # BOOT KICK — one frontier evaluation on going live, so a substrate coming
        # online (including after a RESTART, with beliefs reloaded into unstable
        # regions) resumes pursuing its development without waiting for an external
        # event. A single wake-evaluation, NOT a poll; thereafter the drive is
        # purely event-driven — each completed pursuit emits the OUTCOME_OBSERVED /
        # COMPETENCE_CHANGED that wakes the next. Coalesced through the same
        # single-flight the reactions use.
        self._pursuit_dirty = True
        if (self._pursuit_selection_task is None
                or self._pursuit_selection_task.done()):
            self._pursuit_selection_task = asyncio.create_task(self._coalesced_pursue())

    # ── Agents of self — deploying bounded copies of the substrate ─────────
    #
    # The substrate can deploy an AGENT OF SELF: a lightweight copy of itself,
    # scoped to one task and to a permitted subset of tools, run through this
    # coordinator's OWN execution faculty. Deployment is NOT tied to conversation
    # — the self may deploy an agent from any faculty (a knowledge gap, an idle
    # investigation, a long-running watch), await one, or reconcile findings
    # later. The AGENT AUTHORITY (`self.agent_coordinator`, core/agents/agents.py)
    # is the one owner of deployment bookkeeping and the await-queue; this surface
    # is the self's verb over it. Allowance is the self's (`agent_allowance`),
    # enforced by the authority at deploy.

    def deploy_agent(self, description: str, *,
                     reasoning_type: Any = ReasoningType.DEDUCTIVE,
                     allowed_tools: Optional[List[str]] = None,
                     task_type: Any = None,
                     actor: Optional[str] = None,
                     parameters: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Deploy an agent of self for `description`, scoped to `allowed_tools`
        (None = the substrate's full toolset; a list = a scoped grant).

        Returns the agent's NAME (its handle — a memorable slug like
        `wandering-otter`) to `await_agent`/`collect_agent_findings` later, or None
        on an honest refusal — the agent authority isn't bound, or the reasoning
        type's allowance is full. The agent runs in the background on the
        queue authority's budget; the self need not wait, so a slow or long-lived
        agent never blocks the caller.
        """
        factory = self.agent_coordinator
        if factory is None:
            logger.warning("deploy_agent refused: agent authority not bound")
            return None
        return factory.deploy(
            description, reasoning_type=reasoning_type, allowed_tools=allowed_tools,
            task_type=task_type, actor=actor, parameters=parameters)

    async def await_agent(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """Block until one deployed agent returns, then hand back its findings (or
        an honest error). None if the id is unknown or no authority is bound."""
        factory = self.agent_coordinator
        if factory is None:
            return None
        return await factory.await_findings(deployment_id)

    def collect_agent_findings(self) -> List[Dict[str, Any]]:
        """Take every agent that has come back since the last collect, WITHOUT
        blocking — so the self can keep working and reconcile findings when it
        checks. Still-running agents keep running. Empty if no authority is bound."""
        factory = self.agent_coordinator
        if factory is None:
            return []
        return factory.collect_ready()

    def pending_agents(self) -> List[str]:
        """Deployment ids of agents of self still running (empty if none bound)."""
        factory = self.agent_coordinator
        if factory is None:
            return []
        return factory.pending()

    #: Selections retained when measuring how much of the exploration budget
    #: has been spent.
    EXPLORATION_WINDOW = 50

    #: Trials below which validate_strategy_for_production treats a choice as
    #: exploration rather than an evidence-backed pick.
    EXPLORATION_TRIAL_THRESHOLD = 5

    def _record_exploration_decision(self, strategy: Any) -> None:
        """Note whether a selection spent exploration budget.

        A strategy chosen with fewer than EXPLORATION_TRIAL_THRESHOLD trials is
        exactly what the production gate admits under its exploration
        allowance, so that is the signal recorded here.
        """
        if not hasattr(self, "_exploration_history"):
            from collections import deque
            self._exploration_history = deque(maxlen=self.EXPLORATION_WINDOW)

        if strategy is None:
            # A decision in which no arm passed the gate spent no exploration.
            # It is still a decision; without it a budget exhausted once would
            # block exploration for good.
            self._exploration_history.append(False)
            return
        self._exploration_history.append(
            strategy.trials < self.EXPLORATION_TRIAL_THRESHOLD)

    def _calculate_exploration_quota(self) -> float:
        """Fraction of recent selections that spent exploration budget.

        This method did not exist. Its only call site guarded on hasattr and
        supplied 0.0, so `exploration_quota_used < exploration_quota_limit` was
        permanently true and the 10% exploration cap never bound -- every
        low-trial strategy was admitted as exploration, without limit. The
        default read like "no exploration yet" when it meant "not measured".
        """
        history = getattr(self, "_exploration_history", None)
        if not history:
            return 0.0
        return sum(1 for exploratory in history if exploratory) / len(history)

    def register_capability(self, name: str, instance: Any, config: Dict[str, Any]) -> bool:
        """
        Register a system capability for autonomous execution
        
        Capabilities are background tasks managed by the coordinator that run based on
        system state and conditions rather than hardcoded timers. This enables true
        adaptive intelligence where the system decides when to act.
        
        Args:
            name: Unique capability identifier (e.g., 'memory_consolidation', 'pattern_learning')
            instance: Object instance that implements the capability
            config: Configuration dict with:
                - priority: 'critical', 'high', 'medium', 'low' (default: 'medium')
                - interval: Minimum seconds between executions (default: 3600)
                - method: Name of method to invoke on instance (default: name)
                - conditions: Dict of conditions that must be met:
                    - min_feedback_samples: Minimum feedback count required
                    - performance_threshold: Minimum system performance (0.0-1.0)
                    - error_rate_max: Maximum allowed error rate
                    - memory_usage_max: Maximum memory usage percentage
                    - custom_check: Callable that returns bool
        
        Returns:
            True if registration successful
            
        Example:
            coordinator.register_capability(
                'pattern_learning',
                learner_instance,
                {
                    'priority': 'high',
                    'interval': 3600,
                    'method': 'run_pattern_learning',
                    'conditions': {
                        'min_feedback_samples': 10,
                        'performance_threshold': 0.7
                    }
                }
            )
        """
        try:
            if not hasattr(self, 'registered_capabilities'):
                self.registered_capabilities = {}
                self.capability_last_run = {}
            
            if name in self.registered_capabilities:
                logger.warning(f"Capability '{name}' already registered, replacing...")
            
            # Validate config
            priority = config.get('priority', 'medium')
            if priority not in ['critical', 'high', 'medium', 'low']:
                logger.warning(f"Invalid priority '{priority}', defaulting to 'medium'")
                priority = 'medium'
            
            interval = config.get('interval', 3600)
            method_name = config.get('method', name)
            
            # Verify method exists
            if not hasattr(instance, method_name):
                logger.error(f"Instance does not have method '{method_name}'")
                return False
            
            self.registered_capabilities[name] = {
                'instance': instance,
                'method': method_name,
                'priority': priority,
                'interval': interval,
                'conditions': config.get('conditions', {}),
                'registered_at': datetime.now(),
                'status': 'active',
                'execution_count': 0,
                'last_result': None,
                'last_error': None
            }
            
            self.capability_last_run[name] = datetime.min  # Never run yet
            
            logger.info(f"✅ Registered capability: {name} (priority: {priority}, interval: {interval}s)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register capability {name}: {e}")
            return False
    
    def unregister_capability(self, name: str) -> bool:
        """Unregister a system capability"""
        try:
            if hasattr(self, 'registered_capabilities') and name in self.registered_capabilities:
                del self.registered_capabilities[name]
                if name in self.capability_last_run:
                    del self.capability_last_run[name]
                logger.info(f"Unregistered capability: {name}")
                return True
            else:
                logger.warning(f"Capability '{name}' not found for unregistration")
                return False
        except Exception as e:
            logger.error(f"Failed to unregister capability {name}: {e}")
            return False
    
    def register_completion_callback(
        self,
        task_type: TaskType,
        task_source: TaskSource,
        callback_fn,
        description: str = None
    ):
        """
        Register a completion callback for specific task types.
        
        Callbacks are invoked when tasks complete successfully.
        Use this to implement closure logic (e.g., updating health status,
        releasing resource locks).

        Args:
            task_type: TaskType enum value
            task_source: TaskSource enum value
            callback_fn: Async function(task, result, confidence) -> None
            description: Optional description for logging
        """
        key = (task_type, task_source)
        if key not in self._completion_callbacks:
            self._completion_callbacks[key] = []
        
        self._completion_callbacks[key].append({
            'callback': callback_fn,
            'description': description or callback_fn.__name__
        })
        
        logger.info(
            f"✅ Registered completion callback: {description or callback_fn.__name__} "
            f"for {task_type.value}/{task_source.value}"
        )

    # =========================================================================
    # EVENT / REACTION DISPATCH
    # The substrate reacts to what happens to it. on() registers a reaction;
    # emit() dispatches an event — sync reactions inline, deferred reactions on
    # the drain worker. Generalizes register_completion_callback above; affect
    # is the reference reaction (registered in __init__).
    # =========================================================================
    def on(self, event_type: SelfEventType, handler, *, name: str,
           mode: str = "sync", priority: int = 0) -> None:
        """Register a reaction to an event.

        mode='sync' runs the handler inline inside emit(), isolated so one
        failing reaction never halts the others; use for cheap state changes.
        mode='deferred' enqueues the handler onto the reactive drain worker;
        use for expensive work that must stay off the acting hot path. Higher
        priority runs first. One reaction name per event type — a second live
        registration of the same name is an error (one concept, one owner).
        """
        if mode not in ("sync", "deferred"):
            raise ValueError(
                f"reaction mode must be 'sync' or 'deferred', got {mode!r}")
        bucket = self._reactions.setdefault(event_type, [])
        if any(r["name"] == name for r in bucket):
            raise ValueError(
                f"a reaction named {name!r} is already registered for "
                f"{event_type.value} — one concept, one owner")
        bucket.append({"name": name, "handler": handler,
                       "mode": mode, "priority": priority})
        bucket.sort(key=lambda r: r["priority"], reverse=True)
        logger.info(
            f"🔗 Registered reaction '{name}' on {event_type.value} "
            f"({mode}, priority={priority})")

    async def emit(self, event: SelfEvent) -> None:
        """Dispatch a self-event. Sync reactions run inline in priority order,
        each isolated; deferred reactions are enqueued and the drain worker is
        woken (reactive dispatch — the emit itself wakes the work, never a
        clock). A reaction that emits deeper than _max_emit_depth is demoted to
        deferred rather than recursing, so an emit cycle degrades to queued work
        instead of overflowing the stack; nothing is dropped.
        """
        reactions = self._reactions.get(event.type, ())
        over_depth = self._emit_depth >= self._max_emit_depth
        woke = False
        for r in reactions:
            if r["mode"] == "sync" and not over_depth:
                self._emit_depth += 1
                try:
                    await r["handler"](event)
                except Exception as e:
                    logger.warning(
                        f"reaction '{r['name']}' failed on "
                        f"{event.type.value}: {e}")
                finally:
                    self._emit_depth -= 1
            else:
                self._reactive_queue.append((r, event))
                woke = True
        if woke:
            self._work_ready.set()

    def _start_reactive_worker(self) -> None:
        """Start the reactive drain worker if it is not already running."""
        if self._reactive_worker is None or self._reactive_worker.done():
            self._reactive_worker = asyncio.create_task(
                self._reactive_drain_worker())

    async def _reactive_drain_worker(self) -> None:
        """Run deferred reactions, woken by emit (never on an interval). Runs on
        its own task so learning/consequence work never occupies an acting slot.
        Each reaction is isolated; a failure is logged and draining continues.
        """
        logger.info("🌀 Reactive drain worker started")
        try:
            while self.active:
                await self._work_ready.wait()
                self._work_ready.clear()
                while self._reactive_queue:
                    r, event = self._reactive_queue.popleft()
                    try:
                        await r["handler"](event)
                    except Exception as e:
                        logger.warning(
                            f"deferred reaction '{r['name']}' failed on "
                            f"{event.type.value}: {e}")
        except asyncio.CancelledError:
            logger.info("Reactive drain worker cancelled")
            raise

    async def _react_affect(self, event: SelfEvent) -> None:
        """The affect poke, now a reaction. A task outcome is fitness-relevant,
        so the substrate feels it — update_affect() reads the substrate's own
        appraisal/fitness (no payload needed) and decays on read. Isolation is
        provided by emit(); a failure here is logged there, never fatal.
        """
        await self.intrinsic_motivation.update_affect()
        # The substrate also feels how its KNOWLEDGE moved since last — from any source
        # (perception, teaching, reasoning), integrated here so the emotional state
        # tracks what the substrate came to know, not only what it did.
        await self.integrate_epistemic_affect()

    async def integrate_epistemic_affect(self) -> Dict[str, Any]:
        """Fold how the substrate's knowledge has MOVED into the shared emotional
        state. The body connecting two organs: it ASKS the reasoning authority for the
        epistemic signal (`neural_bridge.epistemic_affect_signal()` — which interprets
        belief drift from any source) and hands it to the appraisal authority. It does
        NO interpreting itself, and — the invariant — nothing here changes a belief or
        makes a decision: knowledge feeds feeling, never the reverse. Returns the
        signal (empty when knowledge did not move)."""
        if self.neural_bridge is None:
            return {}
        signal = await self.neural_bridge.epistemic_affect_signal()
        moved = bool(signal and any(v for k, v in signal.items()
                                    if k not in ("unavailable", "mutation_count")))
        # AND WHAT THE KNOWLEDGE MOVED **ABOUT**.
        #
        # The signal above says only THAT the substrate's picture changed and by
        # how much — information gain, uncertainty reduction, contradiction. So
        # learning that a famine killed a hundred thousand people and learning
        # that a file has a `.txt` extension arrived here as the same shape,
        # differing only in magnitude. Reading the moved subjects through the
        # constitution's own definition of harm is what lets the two be felt
        # differently, and it is still knowledge feeding feeling: the reading is
        # derived from beliefs the substrate already holds, and changes no
        # belief and makes no decision.
        bearing_counts = await self._bearing_of_moved(signal)
        if moved or bearing_counts:
            self.appraisal.update(epistemic=signal or {},
                                          world_bearing=bearing_counts)
        if bearing_counts:
            signal = dict(signal or {})
            signal["world_bearing"] = bearing_counts
        return signal

    #: How many of the just-moved subjects are read through the law per pass.
    #: An induction batch can move thousands of beliefs at once; reading every
    #: one would put an unbounded walk on the affect path, which runs on every
    #: task outcome. The subjects arrive newest-first, so this is the most
    #: recent movement rather than an arbitrary slice — and stakes saturates on
    #: the COUNT of what bears, so a cap changes how much is examined without
    #: changing what one recognised thing is worth.
    _BEARING_SUBJECT_MAX = 64

    async def _bearing_of_moved(self, signal: Optional[Dict[str, Any]]
                                ) -> Optional[Dict[str, Any]]:
        """Read the subjects whose beliefs just moved through my own law.

        Returns the COUNTS ({"borne", "none", "vacant"}) plus the readings that
        were borne, so the appraisal that consumes this weighs rather than
        interprets, and the substrate can still say which perception moved it.
        None when nothing nameable moved — unmeasured, never an asserted zero.
        """
        subjects = list((signal or {}).get("subjects") or ())
        if not subjects:
            return None
        borne = none = vacant = 0
        readings: List[Dict[str, Any]] = []
        for subject in subjects[:self._BEARING_SUBJECT_MAX]:
            try:
                reading = await self.constitution.bearing(str(subject))
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._bearing_of_moved")
                continue
            if reading.borne:
                borne += 1
                readings.append(reading.to_dict())
            elif reading.vacant:
                vacant += 1
            else:
                none += 1
        if not (borne or none or vacant):
            return None
        return {"borne": borne, "none": none, "vacant": vacant,
                "readings": readings}

    async def _react_competence_changed(self, event: SelfEvent) -> None:
        """Deferred: a domain's competence moved, so the competence drive that
        reads it is stale. Refresh the motivation signals reactively — COALESCED,
        so an induction batch that moves N domains (N COMPETENCE_CHANGED events)
        triggers one refresh, not N. The %5 motivation poll stays as a backstop
        during the overlap; a refresh is idempotent (it recomputes from live
        state), so the two co-existing is safe.
        """
        self._motivation_dirty = True
        if (self._motivation_refresh_task is None
                or self._motivation_refresh_task.done()):
            self._motivation_refresh_task = asyncio.create_task(
                self._coalesced_motivation_refresh())

    async def _coalesced_motivation_refresh(self) -> None:
        """Single-flight motivation refresh: drain the dirty flag so a burst of
        competence changes collapses into at most one in-flight + one queued
        refresh, and the LAST change is always reflected (the flag is cleared
        before the refresh runs, so a change arriving mid-refresh re-arms it).

        No error handling of its own: `_refresh_motivation_signals` owns that (the
        same handler the %5 poll relies on) — it surfaces and counts a failure
        honestly and returns False, so an error is never swallowed here. Only a
        real refresh is counted as a reactive refresh."""
        while self._motivation_dirty:
            self._motivation_dirty = False
            if await self._refresh_motivation_signals():
                self.stats["motivation_refreshes_reactive"] += 1

    def _wake_induction_drain(self) -> None:
        """Producer-driven trigger: a demonstration signature was enqueued, so
        induction has work. Set the dirty flag and ensure the single-flight drain
        task is running. Cheap, synchronous, non-raising — the demonstration
        recording hot path (and the store callback) calls this."""
        self._induction_dirty = True
        try:
            if (self._induction_drain_task is None
                    or self._induction_drain_task.done()):
                self._induction_drain_task = asyncio.create_task(
                    self._coalesced_induction_drain())
        except RuntimeError:
            # No running loop (a synchronous/test context recorded a
            # demonstration). The flag stays set; the next wake with a live loop
            # drains it. Never raise into the recording hot path.
            pass

    async def _coalesced_induction_drain(self) -> None:
        """Single-flight, DRAIN-TO-COMPLETION induction — the event-driven
        replacement for the 300s idle_operator_induction poll.

        Every enqueued signature wakes this (via the demonstration store's
        producer callback), and it drains until NOTHING is pending — not a single
        limit=50 batch — so a backlog can never be stranded the way the reactive
        limit=50 alone could. Coalesced: a burst collapses to one in-flight + one
        queued pass, and a signature arriving mid-drain re-arms the flag. Moves
        the competence each result earns and emits COMPETENCE_CHANGED, exactly as
        the retired tier and the old _react_induce did. Runs as its own task (off
        the acting hot path and off the event pump); errors surface, never swallow.
        """
        passes = 0
        while self._induction_dirty and passes < self._COALESCE_MAX_PASSES:
            passes += 1
            self._induction_dirty = False
            udm = self.universal_domain_master
            drained_total = 0
            for _ in range(200):  # bound one pass at 200*50 signatures; re-loops if re-armed
                result = await self.learning.drain_pending_induction(limit=50)
                if result.get("drained", 0) == 0:
                    break
                drained_total += result.get("drained", 0)
                for domain_id, learned in result.get("by_domain", {}).items():
                    await udm.record_competence_evidence(domain_id, learned=bool(learned))
                    await self.emit(SelfEvent(
                        SelfEventType.COMPETENCE_CHANGED,
                        payload=CompetenceChanged(
                            domain_id=domain_id, learned=bool(learned),
                            cause="induction"),
                        origin="_coalesced_induction_drain"))
                await asyncio.sleep(0)  # yield between batches so the pump isn't starved
            if drained_total:
                logger.info("[REACT] induction drained %d signature(s) to completion",
                            drained_total)
        if self._induction_dirty:
            logger.warning("[REACT] induction drain hit the coalesced-pass bound "
                           "(%d) — possible event cascade; resumes on next wake",
                           self._COALESCE_MAX_PASSES)

    def _wake_domain_expansion(self) -> None:
        """Producer-driven trigger: a task outcome was written, or a domain gained
        content — either way the domain layer may have expandable outcomes. Set the
        dirty flag and ensure the single-flight drain is running. Cheap + non-raising."""
        self._domain_expansion_dirty = True
        try:
            if (self._domain_expansion_drain_task is None
                    or self._domain_expansion_drain_task.done()):
                self._domain_expansion_drain_task = asyncio.create_task(
                    self._coalesced_domain_expansion())
        except RuntimeError:
            pass

    async def _coalesced_domain_expansion(self) -> None:
        """Single-flight, PROGRESS-BOUNDED domain expansion — the event-driven
        replacement for the 900s idle_domain_expansion poll.

        Writing a task outcome (or a domain gaining content) wakes this; the tier
        body (`_idle_domain_expansion_work`) is bounded per call, so we loop it
        while it makes PROGRESS (expanded > 0). Progress-based, not
        considered-based: outcomes skipped as `no_domain`/`domain_empty` are left
        unmarked ON PURPOSE (retry once their domain has content), so looping on
        'considered' would spin on them — looping on 'expanded' stops as soon as a
        pass expands nothing new, and a later outcome-write / domain-gain wake
        retries the rest. Coalesced single-flight; DOMAIN_EXPANSION_MARK makes it
        idempotent. The tier's return leg (`_resolve_transfer_outcomes`) runs each pass."""
        passes = 0
        while self._domain_expansion_dirty and passes < self._COALESCE_MAX_PASSES:
            passes += 1
            self._domain_expansion_dirty = False
            for _ in range(200):  # bound; re-loops if re-armed
                expanded = await self._idle_domain_expansion_work()
                if not expanded:
                    break
                await asyncio.sleep(0)
        if self._domain_expansion_dirty:
            logger.warning("[REACT] domain-expansion drain hit the coalesced-pass "
                           "bound (%d) — possible event cascade; resumes on next wake",
                           self._COALESCE_MAX_PASSES)

    def _wake_domain_discovery(self) -> None:
        """Trigger: a taught proposition was admitted (declarative) or a domain
        gained a learned operator (operational) — either can create a new subject
        cluster to crystallize. Single-flight; cheap, synchronous, non-raising."""
        self._domain_discovery_dirty = True
        try:
            if (self._domain_discovery_drain_task is None
                    or self._domain_discovery_drain_task.done()):
                self._domain_discovery_drain_task = asyncio.create_task(
                    self._coalesced_domain_discovery())
        except RuntimeError:
            pass

    async def _coalesced_domain_discovery(self) -> None:
        """Single-flight full-sweep domain discovery — the event-driven replacement
        for the 900s idle_domain_discovery poll. `_idle_domain_discovery_work` does a
        COMPLETE sweep per call (operational operator-bucket crystallization +
        declarative taught-concept crystallization), so one run per coalesced wake
        drains it; the Universal Domain Master decides idempotently (a cluster too
        small stays, an already-crystallized subject is left alone). Coalesced: a
        burst of admissions/competence changes collapses to one sweep; an event
        arriving mid-sweep re-arms it. Replaces the tier's backstop role — a dropped
        event now costs nothing because the next event re-sweeps everything."""
        passes = 0
        while self._domain_discovery_dirty and passes < self._COALESCE_MAX_PASSES:
            passes += 1
            self._domain_discovery_dirty = False
            await self._idle_domain_discovery_work()
        if self._domain_discovery_dirty:
            logger.warning("[REACT] domain-discovery drain hit the coalesced-pass "
                           "bound (%d) — possible event cascade; resumes on next wake",
                           self._COALESCE_MAX_PASSES)

    async def _react_pursue_frontier(self, event: "SelfEvent") -> None:
        """The developmental drive, EVENT-DRIVEN. When the self's state changes in
        a way that could change what is worth pursuing — competence moved, an
        outcome was observed, evidence was admitted, a new environment was met, a
        deficit was diagnosed — re-evaluate the frontier and, if warranted, select
        and queue ONE pursuit. This is the driver (the idle-timer poll is retired):
        completing a pursuit itself emits OUTCOME_OBSERVED / COMPETENCE_CHANGED,
        which wakes the next selection, so the loop is self-sustaining through
        events and quiet when nothing changes. Coalesced single-flight: a burst of
        events collapses to one selection; the last event is always reflected."""
        self._pursuit_dirty = True
        if (self._pursuit_selection_task is None
                or self._pursuit_selection_task.done()):
            self._pursuit_selection_task = asyncio.create_task(
                self._coalesced_pursue())

    async def _coalesced_pursue(self) -> None:
        """Single-flight wrapper over the selection cycle: drain the dirty flag so
        a burst of state-changing events produces at most one in-flight + one
        queued selection, and a change arriving mid-selection re-arms it. The
        cycle owns its own gating (queue pressure, exploration cap, disposition,
        dedup) and error handling — a fault there is surfaced, never swallowed."""
        while self._pursuit_dirty:
            self._pursuit_dirty = False
            await self._run_exploration_cycle()

    async def _react_induce(self, event: SelfEvent) -> None:
        """OUTCOME_OBSERVED also wakes the induction drain — a belt-and-suspenders
        trigger alongside the demonstration store's producer callback (which fires
        the instant a signature is enqueued, by ANY producer, and is the primary
        path). Both feed the ONE single-flight, drain-to-completion pass
        (`_coalesced_induction_drain`), which clears each signature as it processes
        it, so there is no double-induction. Kept because the completion seam is a
        natural, cheap moment to ensure the drain is awake."""
        self._wake_induction_drain()

    async def _react_expand_outcome(self, event: SelfEvent) -> None:
        """Wake the single-flight domain-expansion drain (`_coalesced_domain_expansion`).

        Registered on OUTCOME_OBSERVED (completion seam) AND on COMPETENCE_CHANGED /
        EVIDENCE_ADMITTED — the latter matter because a domain GAINING content is
        exactly when outcomes previously skipped as `domain_empty` become
        expandable. The primary producer trigger is the outcome-write chokepoint
        (`_store_task_outcome_meta_memory`); this covers the event side. The drain
        scans every unexpanded outcome with the DOMAIN_EXPANSION_MARK dedup, so
        there is no double-processing and nothing is faked."""
        self._wake_domain_expansion()

    async def _react_resolve_transfers(self, event: SelfEvent) -> None:
        """Deferred: re-check pending knowledge transfers now that a new outcome
        exists — outcomes are the pacemaker. Reuses the one authority
        `_resolve_transfer_outcomes` (idempotent: resolves only transfers with
        enough evidence, leaves the rest NULL), triggered by the outcome event
        instead of the tier's 900s return leg.
        """
        await self._resolve_transfer_outcomes()

    async def _react_crystallize_taught(self, event: SelfEvent) -> None:
        """Wake the single-flight full-sweep domain discovery
        (`_coalesced_domain_discovery`). Registered on EVIDENCE_ADMITTED (a taught
        proposition admitted → declarative crystallization) AND COMPETENCE_CHANGED
        (a new learned operator → operational crystallization). The sweep is
        idempotent (the Universal Domain Master leaves too-small clusters and
        already-crystallized subjects alone) and covers everything, so a dropped
        event costs nothing — the next event re-sweeps. Replaces the retired
        idle_domain_discovery poll's backstop role."""
        self._wake_domain_discovery()

    async def see(self, path: str, *, source: Optional[str] = None,
                  domain: str = "vision", recognize: Optional[str] = None):
        """Perceive one real image or video: sense its structure, then ADMIT it
        through the one perception pipeline.

        `see` senses with the vision faculty and routes the sensed structure through
        `PerceptionManager.process_input` — the single pipeline every percept funnels
        through, which admits it as evidence ONCE (fanning out to belief and domain)
        and records it in the substrate's perceptual awareness. Vision is a sensor
        feeding that pipeline, not a second admitter. Returns the PerceptionData, or
        None when nothing was sensed.

        Sensation CHAINS into recognition: if this route has a recognizer — named
        here via `recognize`, or attached for `domain` via `attach_recognizer` — the
        same percept is handed to `perceive`, whose confidence-governed decision
        (ACT / VERIFY / ABSTAIN) then governs behaviour through the event spine. With
        no recognizer the route is pure sensation: `see` and `perceive` are two
        stages, and this is where the first feeds the second."""
        sensed = await self.vision.sense(path, source=source)
        if sensed is None:
            return None
        modality, content = sensed
        # THE FACULTY NAMES WHAT IT SAW, and this uses that name rather than
        # deriving a second one. It used to compute `source or Path(path).stem`
        # here while the faculty computed its own subject from the same inputs --
        # two derivations of one identity, which agreed only as long as both
        # stayed simple. They no longer do: the faculty now builds the name from
        # the image's CONTENT digest, because the caller's label is not an
        # identity (this substrate's own environment scan passes
        # `source="environment"` for every image it walks past, which made every
        # picture in the world the same individual).
        subject = content["subject"]
        # THE ONE PIPELINE: the overall perceptual hub admits the percept (once) and
        # records awareness. coord.process_input routes sensors through the same hub,
        # so every modality is admitted by one owner — no parallel vision admitter.
        perception_data = await self.perception.process_input(subject, modality, content)
        # THE SEEING IS A SCOPE, not a mood that lingers.
        #
        # `process_input` binds the percept as what is currently being perceived
        # so anything formed from here links to it BY REFERENCE. That binding
        # must not outlive the act: left standing, a memory formed an hour later
        # in the same context would claim to be OF this percept — the recency
        # defect this replaces, in a new shape. Recognition is inside the scope
        # because it is work done on this percept; everything after is not.
        from core.agents.autonomous.perception_manager import (
            reset_acting_percept, set_acting_percept)
        _meta = getattr(perception_data, "metadata", None) or {}
        token = set_acting_percept(_meta.get("perception_id"), _meta.get("digest"))
        try:
            clf = recognize or self._recognizers.get(domain)
            # WHAT THE CLASSIFIER READS DECIDES WHERE IT IS ASKED. One holding a
            # feature VOCABULARY reads the structure this faculty just measured,
            # so it names BLOBS, inside `recognise_sensed`, beside the induced
            # rules and over the same features. One without a vocabulary reads
            # PIXELS, so it is given the file and names the percept as a whole.
            # Handing a symbol-reading classifier the path — which is what this
            # did for every classifier — would have it treat a filename as a
            # feature vector.
            blob_clf = clf if clf and self.learning.clause_classifier_vocabulary(clf) \
                else None
            if perception_data is not None and clf and blob_clf is None:
                # The classifier's own `encode` is the pixel→feature bridge; the decision
                # flows via PERCEPT_RECOGNIZED.
                await self.perceive(clf, path, subject, domain=domain)
            # WHAT WAS SENSED IS JUDGED TOO, by the same band — with or without a
            # recognizer. This ran to the belief store and stopped, so the
            # substrate held an acceptance standard for what it RECOGNISED and
            # none at all for what it SAW: the path that runs constantly was the
            # one with no decision on it.
            if perception_data is not None:
                try:
                    # NAMING IS PART OF SEEING, so it happens before the judgement
                    # and is judged WITH it: what the substrate thinks a thing IS
                    # is a claim about the same percept as what it measured, and
                    # the percept's verdict is the weakest of all of them. A
                    # shape it is sure of carrying a name it is not must not clear
                    # the bar on the shape's strength.
                    named = await self.recognise_sensed(
                        content, domain=domain, classifier=blob_clf)
                    await self.perceive_sensed(
                        subject, self._sensed_claims(subject, content) + named,
                        domain=domain, percept_id=_meta.get("perception_id"))
                except Exception as error:
                    raise_if_structural(error, "autonomous_coordinator.see")
        finally:
            reset_acting_percept(token)
        return perception_data

    @staticmethod
    def _sensed_claims(subject: str, content: Dict[str, Any]) -> List[str]:
        """The claims one sensing makes, as the belief store holds them.

        Reconstructed in the SAME surface form `fan_out_ingested` wrote them
        ("<subject> <relation> <object>"), because that is the key
        `belief_for_claim` resolves — a claim spelled differently here would find
        no belief and be reported as an absence the substrate never had.
        """
        claims: List[str] = []
        for relation, value in (content.get("properties") or {}).items():
            if value not in (None, "", []):
                claims.append(f"{subject} {relation} {value}")
        for blob in (content.get("blobs") or []):
            name = str(blob.get("name") or "").strip()
            if not name:
                continue
            claims.append(f"{subject} contains {name}")
            claims.extend(f"{name} isa {f}" for f in (blob.get("isa") or []))
        for detection in (content.get("detections") or []):
            label = (detection.get("label") if isinstance(detection, dict)
                     else str(detection))
            if label:
                claims.append(f"{subject} observed {label}")
        return claims

    async def remember_image(self, path: str, note: Optional[str] = None, *,
                             tags: Optional[List[str]] = None,
                             importance: float = 0.6) -> Optional[str]:
        """Remember a real image: keep the picture AND a recallable account of it.

        The vision faculty reads the image's structure; a short description of
        what is in it becomes the memory's text (so the memory is found by its
        content), and the image bytes are retained alongside it so the picture
        can be produced again. This is the memory counterpart of `see`: `see`
        turns pixels into knowledge; this turns them into an episode the
        substrate can recall and re-open. Returns the memory id, or None."""
        from core.perception import vision
        desc = vision.describe_image(str(path))
        caption = self._image_caption(desc)
        content = f"{note.strip()} — {caption}" if note else caption
        perceived = {k: desc.get(k) for k in (
            "width", "height", "format", "orientation", "dominant_colors",
            "regions", "region_count", "palette_temperature",
            "colorfulness_category", "sha256")}
        perceived["caption"] = caption   # the recallable description travels with the image
        if self.memory is None:
            from core.memory import get_memory_agent
            self.memory = await get_memory_agent()
        ok, memory_id = await self.memory.store_memory(
            content=content, memory_type=MemoryType.EPISODIC,
            importance_score=importance,
            tags=list(tags or []) + ["image", "vision"],
            source_context={"source_system": "vision", "has_image": True},
            image=str(path), image_meta=perceived)
        return memory_id if ok else None

    async def recall_image(self, memory_id: str) -> List[Dict[str, Any]]:
        """The image(s) a memory kept -- bytes, mime, dimensions, perceived
        structure -- so the substrate can re-open a picture it remembers."""
        if self.memory is None:
            from core.memory import get_memory_agent
            self.memory = await get_memory_agent()
        return await self.memory.get_memory_images(memory_id)

    @staticmethod
    def _image_caption(desc: Dict[str, Any]) -> str:
        """A short, recallable sentence for what is in an image, from the perceived
        structure -- the text a memory of the image is found by."""
        parts = [f"{desc.get('width')}x{desc.get('height')} {desc.get('format')} image"]
        colors = desc.get("dominant_colors") or []
        if colors:
            parts.append("mostly " + ", ".join(c["name"] for c in colors[:3]))
        regions = [r for r in (desc.get("regions") or [])
                   if r.get("area_fraction", 1) <= 0.9]
        if regions:
            parts.append("showing " + ", ".join(
                f"a {r['size']} {r['color']} {r['shape']}" for r in regions[:4]))
        codes = desc.get("codes") or []
        if codes:
            parts.append("with code " + "; ".join(str(c) for c in codes[:2]))
        return "; ".join(parts)

    async def process_input(self, source: str, data_type: str, content: Dict[str, Any]) -> Optional[str]:
        """Process external input and potentially create goals"""
        if not self.active:
            return None
        
        try:
            # Process through perception
            perception_data = await self.perception.process_input(source, data_type, content)
            if not perception_data:
                return None
            
            # Analyze if this requires goal creation
            goal_id = await self._analyze_for_goal_creation(perception_data)
            
            return goal_id
            
        except Exception as e:
            logger.error(f"Error processing input: {e}")
            return None
    
    #: A goal condition written as a relational literal: PRED(a, b).
    #: Deliberately strict -- it must look like a formal fact, not like prose
    #: that happens to contain parentheses.
    _STATE_LITERAL = re.compile(r"\b([A-Z][A-Z0-9_]{1,23})\(([^()]{1,120})\)")

    @classmethod
    def extract_state_conditions(cls, description: str) -> Optional[List[str]]:
        """The state conditions stated in a request, or None.

        THE SUPPLIER THAT DID NOT EXIST. `Goal.state_conditions` decides
        goal_type, and only a STATE goal reaches _plan_state_goal -- the single
        path that consults learned rules. Nothing in production ever set it, so
        every goal was DESCRIPTIVE and validated operators could not supply
        planning authority outside one test.

        Deterministic and conservative: a literal must parse as a Fact to be
        accepted. Anything it cannot read is left alone and the goal stays
        DESCRIPTIVE, which is the honest outcome -- guessing a formal goal from
        prose would hand the planner a problem the user did not state.
        Interpretation of unstructured language belongs to a model, above this,
        and is a separate decision from what the substrate then does with it.
        """
        if not description:
            return None
        from core.learning.rule_induction import Fact

        found: List[str] = []
        for match in cls._STATE_LITERAL.finditer(description):
            literal = f"{match.group(1)}({match.group(2).strip()})"
            try:
                Fact.parse(literal)          # the parser decides, not the regex
            except Exception:
                continue
            if literal not in found:
                found.append(literal)
        return found or None

    async def set_goal(self, description: str, priority: Priority = Priority.MEDIUM,
                      deadline: Optional[datetime] = None,
                      intrinsic_values: Optional[Dict[str, float]] = None,
                      state_conditions: Optional[List[str]] = None) -> Optional[str]:
        """Set a new goal, as a STATE goal when conditions can be established.

        `state_conditions` may be supplied by the caller; otherwise they are
        read from the description when it states them formally.
        """
        try:
            if state_conditions is None:
                state_conditions = self.extract_state_conditions(description)
            if state_conditions:
                logger.info("Goal carries %d state condition(s): %s",
                            len(state_conditions), state_conditions)
            goal = await self.planning.create_goal(
                description, priority, deadline, intrinsic_values,
                state_conditions=state_conditions)
            if goal:
                self.system_state.active_goals.append(goal.id)
                logger.info(f"New goal set: {description}")
                
                # Store goal in memory
                await self.store_memory(
                    MemoryType.EPISODIC,
                    {
                        "event": "goal_created",
                        "goal_id": goal.id,
                        "description": description,
                        "priority": priority.value,
                        "deadline": deadline.isoformat() if deadline else None,
                        "intrinsic_reward_potential": goal.intrinsic_reward_potential,
                        "timestamp": datetime.now().isoformat()
                    },
                    importance=1.2 + (goal.intrinsic_reward_potential * 0.3),
                    tags=["goal", "planning", "autonomous_system"]
                )
                
                return goal.id
            return None
            
        except Exception as e:
            logger.error(f"Error setting goal: {e}")
            return None
    
    async def generate_curiosity_driven_goals(self, max_goals: Optional[int] = None) -> List[str]:
        """
        Autonomously generate goals based on curiosity and exploration targets
        """
        if max_goals is None:
            max_goals = self.coordinator_config.max_goals_curiosity

        generated_goal_ids = []

        try:
            # Get top exploration targets from intrinsic motivation system
            exploration_targets = await self.intrinsic_motivation.get_top_exploration_targets(limit=max_goals)
            
            for target in exploration_targets:
                # Create intrinsic motivation values for this goal
                # target.novelty_score and target.curiosity_value were read off
                # the target and exist on no target type. Entropy is not novelty
                # -- a long-known belief can be maximally uncertain -- so these
                # come from their real owners instead: novelty from the goal
                # embedding store, curiosity from the reward calculation with
                # answer_depth 0 because the target has not been explored yet.
                similarity, _ = await self.intrinsic_motivation._calculate_goal_similarity(
                    target.description
                )
                novelty_score = max(0.0, 1.0 - similarity)
                curiosity_value = (await self.intrinsic_motivation.calculate_curiosity_reward({
                    "information_gain": target.uncertainty_score,
                    "uncertainty_reduction": target.uncertainty_score,
                    "question_complexity": 0.7,
                    "answer_depth": 0.0,
                })).reward_value

                intrinsic_values = {
                    "expected_novelty": novelty_score,
                    "expected_competence_gain": self.coordinator_config.expected_competence_gain,
                    "curiosity_value": curiosity_value,
                    "intrinsic_reward_potential": (
                        self.coordinator_config.novelty_weight * novelty_score +
                        self.coordinator_config.uncertainty_weight * target.uncertainty_score +
                        self.coordinator_config.competence_weight * self.coordinator_config.expected_competence_gain
                    )
                }
                
                # Generate goal description
                goal_description = f"Explore: {target.description}"
                
                # Create the goal with lower external priority (it's intrinsically motivated)
                goal_id = await self.set_goal(
                    description=goal_description,
                    priority=Priority.LOW,  # Low external priority but high intrinsic value
                    intrinsic_values=intrinsic_values
                )
                
                if goal_id:
                    generated_goal_ids.append(goal_id)
                    
                    # Mark target as being explored
                    await self.intrinsic_motivation.mark_target_explored(target.target_id)
                    
                    # Calculate curiosity reward for generating exploration goal
                    curiosity_reward = await self.intrinsic_motivation.calculate_curiosity_reward({
                        "information_gain": 0.3,
                        "uncertainty_reduction": target.uncertainty_score,
                        "question_complexity": 0.7,
                        "answer_depth": 0.0  # Haven't explored yet
                    })
                    
                    logger.info(f"🔍 Generated curiosity-driven goal: {goal_description} "
                              f"(intrinsic potential: {intrinsic_values['intrinsic_reward_potential']:.2f})")

                    # SLACK NOTIFICATION: New autonomous goal
                    if self.slack_notifier and intrinsic_values['intrinsic_reward_potential'] > 0.6:
                        await self.slack_notifier.send_notification(
                            title=f"🎯 New Autonomous Goal Generated",
                            message=f"**Goal:** {goal_description[:200]}\n**Type:** Curiosity-driven exploration\n**Potential Value:** {intrinsic_values['intrinsic_reward_potential']:.0%}",
                            severity="info",
                            metadata={"goal_type": "curiosity", "potential": intrinsic_values['intrinsic_reward_potential']}
                        )

            # "Nothing worth exploring" and "the subsystem is broken" must not
            # be the same observation. For five method names that did not exist,
            # this returned [] on every call and read as a stable system.
            self._exploration_status = (
                "TARGETS_AVAILABLE" if generated_goal_ids else "NO_EXPLORATION_TARGETS"
            )
            return generated_goal_ids

        except Exception as e:
            self._exploration_status = "SYSTEM_FAILURE"
            logger.error(
                f"SYSTEM_FAILURE generating curiosity-driven goals — exploration is "
                f"not merely empty, it is broken: {e}",
                exc_info=True,
            )
            return generated_goal_ids
    
    def _build_memory_narrative(self, event_type: str, content: Dict[str, Any]) -> str:
        """
        Convert a structured event dict into a rich, human-readable memory narrative.

        The goal is a memory that could place the system back in that moment —
        what happened, what was decided, what was observed, what changed, and why it matters.
        A bare dict repr like "{'event': 'goal_created', 'description': 'check system'}"
        is useless as a memory. This method produces something worth remembering.
        """
        ts = content.get('timestamp', '')
        ts_str = f" at {ts}" if ts else ""

        # ── Goal events ──────────────────────────────────────────────────────────
        if event_type == 'goal_created':
            desc = content.get('description', 'unknown goal')
            priority = content.get('priority', 'medium')
            reward = content.get('intrinsic_reward_potential', 0)
            reward_str = f" (intrinsic reward potential: {reward:.2f})" if reward else ""
            return (
                f"A new goal was created{ts_str}: \"{desc}\". "
                f"Priority set to {priority}{reward_str}. "
                f"Goal ID: {content.get('goal_id', 'unknown')}."
            )

        if event_type == 'goal_completed':
            desc = content.get('description', 'unknown goal')
            return (
                f"Goal completed{ts_str}: \"{desc}\". "
                f"Result: {content.get('result', 'success')}. "
                f"Duration: {content.get('duration_seconds', '?')}s."
            )

        # ── Task events ───────────────────────────────────────────────────────────
        if event_type == 'task_outcome':
            task_desc = content.get('task_description', content.get('description', 'unknown task'))
            outcome = content.get('outcome', 'unknown')
            confidence = content.get('confidence', 0)
            domain = content.get('domain', '')
            domain_str = f" in domain '{domain}'" if domain else ""
            failure_reason = content.get('failure_reason', '')
            failure_str = f" Failure reason: {failure_reason}." if failure_reason else ""
            result_summary = content.get('result_summary', '')
            result_str = f" Summary: {result_summary}" if result_summary else ""
            return (
                f"Task {outcome}{domain_str}{ts_str}: \"{task_desc}\". "
                f"Confidence: {confidence:.0%}.{failure_str}{result_str}"
            )

        if event_type == 'governance_block':
            task_desc = content.get('task_description', 'unknown task')
            block_type = content.get('block_type', 'unknown')
            block_reason = content.get('block_reason', 'no reason given')
            domain = content.get('domain', '')
            domain_str = f" (domain: {domain})" if domain else ""
            return (
                f"Task was BLOCKED by governance{domain_str}{ts_str}: \"{task_desc}\". "
                f"Block type: {block_type}. Reason: {block_reason}."
            )

        # ── Reasoning & prediction events ─────────────────────────────────────────
        if event_type == 'reasoning_conclusion':
            question = content.get('question', 'unknown question')
            conclusion = content.get('conclusion', 'no conclusion')
            confidence = content.get('confidence', 0)
            reasoning_type = content.get('reasoning_type', '')
            rtype_str = f" using {reasoning_type} reasoning" if reasoning_type else ""
            evidence = content.get('evidence', [])
            evidence_str = f" Supporting evidence: {'; '.join(str(e) for e in evidence[:3])}." if evidence else ""
            return (
                f"Reasoning conclusion{rtype_str}{ts_str}: Question was \"{question}\". "
                f"Conclusion: {conclusion} (confidence: {confidence:.0%}).{evidence_str}"
            )

        if event_type in ('system_prediction', 'enhanced_prediction'):
            target = content.get('target', content.get('domain', 'system'))
            predicted = content.get('predicted_value', content.get('prediction', 'unknown'))
            confidence = content.get('confidence', 0)
            reasoning = content.get('reasoning', '')
            reasoning_str = f" Reasoning: {reasoning[:200]}." if reasoning else ""
            horizon = content.get('horizon', '')
            horizon_str = f" Horizon: {horizon}." if horizon else ""
            return (
                f"Prediction for {target}{horizon_str}{ts_str}: {predicted}. "
                f"Confidence: {confidence:.0%}.{reasoning_str}"
            )

        if event_type == 'cross_domain_reasoning':
            query = content.get('query', 'unknown query')
            src = content.get('source_domains', [])
            insights = content.get('insights', [])
            confidence = content.get('confidence', 0)
            insights_str = f" Insights: {'; '.join(str(i) for i in insights[:3])}." if insights else ""
            return (
                f"Cross-domain reasoning{ts_str}: Query \"{query}\" across domains {src}. "
                f"Confidence: {confidence:.0%}.{insights_str}"
            )

        # ── Learning & strategy events ────────────────────────────────────────────
        if event_type == 'strategy_adaptation':
            task_type = content.get('task_type', 'unknown')
            reason = content.get('reason', 'performance')
            gate = content.get('gate_analysis', {})
            win_rate = gate.get('win_rate', gate.get('decay_weighted_win_rate', '?'))
            win_str = f" Win rate was {win_rate:.0%}." if isinstance(win_rate, float) else ""
            return (
                f"Strategy adapted for task type '{task_type}'{ts_str}. "
                f"Reason: {reason}.{win_str}"
            )

        if event_type == 'strategy_outcome_summary':
            task_type = content.get('task_type', 'unknown')
            strategy = content.get('strategy', 'unknown')
            win_rate = content.get('win_rate', 0)
            executions = content.get('total_executions', 0)
            avg_time = content.get('avg_time', 0)
            return (
                f"Strategy performance summary{ts_str}: task type '{task_type}', "
                f"strategy '{strategy}' over {executions} executions — "
                f"win rate {win_rate:.0%}, avg time {avg_time:.1f}s."
            )

        if event_type == 'learning_with_intrinsic_rewards':
            recs = content.get('recommendations', [])
            reward = content.get('cycle_reward_sum', content.get('total_intrinsic_reward', 0))
            targets = content.get('exploration_targets', [])
            rec_str = f" Applied {len(recs)} recommendations." if recs else ""
            targets_str = f" Top exploration targets: {'; '.join(str(t) for t in targets[:3])}." if targets else ""
            return (
                f"Learning cycle with intrinsic motivation{ts_str}. "
                f"Total intrinsic reward: {reward:.2f}.{rec_str}{targets_str}"
            )

        if event_type == 'capability_execution':
            cap = content.get('capability', 'unknown')
            priority = content.get('priority', 'medium')
            exec_count = content.get('execution_count', 1)
            exec_time = content.get('execution_time', 0)
            result = content.get('result', '')
            result_str = f" Result: {str(result)[:150]}." if result else ""
            return (
                f"Capability '{cap}' executed (run #{exec_count}, priority: {priority}){ts_str}. "
                f"Took {exec_time:.2f}s.{result_str}"
            )

        if event_type == 'domain_knowledge_integration':
            src = content.get('source_domain', 'unknown')
            tgt = content.get('target_domain', 'unknown')
            transferred = content.get('transferred_knowledge', 0)
            new_concepts = content.get('new_concepts', 0)
            confidence = content.get('confidence', 0)
            insights = content.get('insights', [])
            insights_str = f" Insights: {'; '.join(str(i) for i in insights[:2])}." if insights else ""
            return (
                f"Domain knowledge integrated{ts_str}: {transferred} items transferred "
                f"from '{src}' to '{tgt}', {new_concepts} new concepts created. "
                f"Confidence: {confidence:.0%}.{insights_str}"
            )

        # ── Fallback: produce a readable narrative from whatever keys are present ──
        # Still better than str(dict) — extracts meaningful fields and labels them
        skip_keys = {'event', 'timestamp', 'schema'}
        parts = []
        for k, v in content.items():
            if k in skip_keys or v is None:
                continue
            if isinstance(v, float):
                parts.append(f"{k.replace('_', ' ')}: {v:.3f}")
            elif isinstance(v, (list, dict)) and len(str(v)) > 200:
                parts.append(f"{k.replace('_', ' ')}: [complex data]")
            else:
                parts.append(f"{k.replace('_', ' ')}: {v}")
        event_label = event_type.replace('_', ' ').capitalize()
        return f"{event_label}{ts_str}. " + ". ".join(parts[:12]) + "."

    async def store_memory(self, memory_type: MemoryType, content: Dict[str, Any],
                          importance: float = 1.0, tags: Optional[List[str]] = None,
                          thinking_state: Optional[Dict[str, Any]] = None,
                          decision_factors: Optional[Dict[str, Any]] = None,
                          reasoning_trace: Optional[List[str]] = None) -> Optional[str]:
        """Store a memory with RICH METADATA to the memory agent.

        reasoning_trace must be the substrate's REAL reasoning steps (the
        neural-symbolic bridge's derivation), never a fabricated trace. If none
        is available, pass None or an empty list. The memory agent stamps the
        self's live appraisal (emotions + interoception) onto the memory, so the
        cognitive context of the moment is recorded without being passed here.
        """
        try:
            # Extract event type from content
            event_type = content.get('event', 'unknown')

            # Build a human-readable narrative from the event dict.
            # str(content) produces an unreadable Python repr — useless as a memory.
            narrative = self._build_memory_narrative(event_type, content)

            # Build rich metadata UPSTREAM
            enriched_thinking_state = thinking_state or {}
            enriched_thinking_state.update({
                "event_type": event_type,
                "autonomous_system": True,
                "raw_event": content,  # Preserve full structured data alongside the narrative
                # RICH METADATA: Justification
                "justification": {
                    "store_reason": [
                        "autonomous_task_execution",
                        event_type,
                        "strategic_decision" if importance > 0.7 else "tactical_decision"
                    ],
                    "decision_summary": content.get('description', narrative[:150]),
                    "alternatives_considered": content.get('alternatives', []),
                    "rejected_because": content.get('rejected_reasons', []),
                    "complexity_assessment": "high" if importance > 0.8 else "medium",
                    "novelty_assessment": "novel" if importance > 0.9 else "incremental"
                },
                # RICH METADATA: Outcome
                "outcome": {
                    "action_type": event_type,
                    "action_summary": narrative[:200],
                    "affected_components": ["autonomous_coordinator"] + content.get('affected_systems', []),
                    "created_new_knowledge": importance > 0.7,
                    "confidence": content.get('confidence', importance),
                    "impact_assessment": "critical" if importance > 0.9 else "significant" if importance > 0.7 else "moderate",
                    "verification_status": "unverified"
                }
            })

            enriched_decision_factors = decision_factors or {}
            enriched_decision_factors.update({
                "autonomous_decision": True,
                "event_context": content.get('context', {}),
                "decision_rationale": content.get('reasoning', 'Autonomous task execution')
            })

            # Capture system state from awareness layers
            system_state_data = {
                "environment": self.env_state.get_state_summary() if hasattr(self, 'env_state') else {},
                "discovery": self.discovery.get_service_summary() if hasattr(self, 'discovery') else {},
                "behavioral": self.behavioral.get_analysis_summary() if hasattr(self, 'behavioral') else {},
                "topology": self.topology.get_health_summary() if hasattr(self, 'topology') else {},
                "captured_at": datetime.now().isoformat()
            }

            # Call memory agent with FULL rich metadata
            from core.memory import get_memory_agent
            memory_agent = await get_memory_agent()

            # emotional_context is NOT passed a placeholder here. The memory agent
            # fills it from the live appraisal — the real feelings of the moment —
            # for every memory; sending {"autonomous_confidence": importance} would
            # override that truth with one number under a misleading name.
            success, memory_id = await memory_agent.store_memory(
                memory_type=memory_type,
                content=narrative,
                importance_score=importance,
                confidence_score=importance,
                tags=tags or [],
                thinking_state=enriched_thinking_state,
                system_state=system_state_data,
                decision_factors=enriched_decision_factors,
                reasoning_trace=reasoning_trace or [],
            )

            if success:
                return memory_id
            return None

        except Exception as e:
            logger.error(f"Error storing memory: {e}")
            return None


    async def _store_task_outcome_meta_memory(
        self,
        task: Any,
        outcome: str,
        confidence: float = 1.0,
        result_summary: Optional[str] = None,
        failure_reason: Optional[str] = None
    ) -> Optional[str]:
        """
        Store task outcome as META memory for performance tracking

        Args:
            task: The task that was executed
            outcome: "success" or "failure"
            confidence: Confidence in the outcome
            result_summary: Summary of result (for success)
            failure_reason: Reason for failure (for failure)

        Returns:
            Memory ID if stored successfully
        """
        try:
            from core.governance.governance_block_schema import TaskOutcomeRecord
            from core.memory.utils.interfaces import MemoryType

            domain = self._completion_domain(task)

            record = TaskOutcomeRecord(
                task_id=str(getattr(task, "id", "unknown")),
                task_type=getattr(getattr(task, "type", None), "value", "unknown"),
                task_description=getattr(task, "description", str(task)),
                outcome=outcome,
                confidence=float(confidence),
                domain=domain,
                knowledge_domain=self._task_domain(task),
                task_source=getattr(getattr(task, "source", None), "value", "unknown"),
                timestamp=datetime.now(),
                result_summary=result_summary,
                failure_reason=failure_reason,
                # The DID/SAW groundings the completion judgment rested on — stored
                # WITH the outcome so recall returns WHAT evidence made it so, not
                # just the label. `confidence` above is the completion belief's
                # posterior; emotion/attitude/beliefs/system-state are stamped
                # centrally by the one memory pipeline (memory_agent.store_memory).
                evidence=(task.metadata or {}).get("completion_evidence"),
            )

            meta_content = {
                "event": "task_outcome",
                "schema": "task_outcome_v1",
                **record.to_dict(),
            }
            # METHOD: the tool_plan this task used (tools + args), stored so a
            # later failure can recall what approach SUCCEEDED on a similar task and
            # retry with it instead of blindly re-running the one that failed.
            _plan = ((task.metadata or {}).get("parameters") or {}).get("tool_plan")
            if _plan:
                meta_content["method"] = _plan
            # CAUSAL REMEDY: if a method change FIXED a prior failure to reach this
            # success, record the conditional rule {when: the tools that were
            # failing, use: the arg change, expect: success}. Future failures match
            # on the WHEN and transfer the fix — conditional, not semantic.
            _struct = (task.metadata or {}).get("retry_method_structured")
            if outcome == "success" and _struct:
                _last_failed = []
                for _h in ((task.metadata or {}).get("failure_history") or [])[-1:]:
                    _last_failed = sorted({ft.get("tool") for ft in (_h.get("failed_tools") or [])
                                           if ft.get("tool")})
                meta_content["causal_rules"] = [{
                    "when": {"failed_tools": _last_failed},
                    "use": _struct,
                    "expect": "goal achieved",
                }]

            # Store with importance based on outcome
            importance = 0.7 if outcome == "success" else 0.9  # Failures are MORE important for learning

            memory_id = await self.store_memory(
                memory_type=MemoryType.META,
                content=meta_content,
                importance=importance,
                tags=[
                    "task_outcome",
                    "meta_learning",
                    f"outcome_{outcome}",
                    f"domain_{domain}",
                    "performance_tracking"
                ]
            )

            if memory_id:
                logger.debug(f"📊 Stored task outcome META memory: {outcome} ({memory_id})")
                # WAKE domain expansion (event-driven): a new task outcome exists to
                # expand into the domain layer.
                self._wake_domain_expansion()

            return memory_id

        except Exception as e:
            logger.error(f"Failed to store task outcome META memory: {e}")
            return None

    @classmethod
    def knowledge_domain_of(cls, task_type: Optional[str],
                            declared_domain: Optional[str]) -> Optional[str]:
        """The knowledge domain a task acts in, from what the task IS.

        A task that declares its domain acts there. A task that declares none
        names no domain, and None says so -- nothing is read into its
        description. A keyword match on descriptions once filed every
        remediation task under `scientific`, so every failure was learned, and
        transferred into, biology.
        """
        if declared_domain:
            return str(declared_domain)
        return None

    def _task_domain(self, task: Any) -> Optional[str]:
        declared = ((getattr(task, "provenance", None) or {}).get("domain_id")
                    or (getattr(task, "metadata", None) or {}).get("domain_id"))
        return self.knowledge_domain_of(
            getattr(getattr(task, "type", None), "value", None), declared)

    async def search_memories(self, query_text: str, memory_types: Optional[List[MemoryType]] = None,
                             max_results: int = 10) -> List[MemoryItem]:
        """Search memories using the unified memory system"""
        try:
            import uuid
            query = MemoryQuery(
                query_id=str(uuid.uuid4()),
                content=query_text,
                memory_types=memory_types or [],
                max_results=max_results
            )
            
            result = await self.memory.search_memories(query)
            return result.memories

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'autonomous_coordinator.search_memories')
            logger.error(f"Error searching memories: {e}")
            return []

    async def _react_governance_monitor(self, event: "SelfEvent") -> None:
        """Governance watches the live action stream. Observe this completed action and
        judge it against the laws in real time; on a breach the monitor snapshots the
        moment and REDIRECTS (teachable) or HALTS (prime-directive).

        A non-compliant verdict is an ACTION outcome the substrate OBSERVES — its OWN
        appraisal responds (as to any safety-blocked outcome), so the governance signal
        is felt and learned from like any other. Governance reports the verdict; it does
        NOT reach into the substrate's internal state. Isolated: never fatal to the loop.
        """
        try:
            from .runtime_governance import get_runtime_governance
            # The declared shape names what this event carries, so the two dead
            # alternatives this used to try (`description`, `action_type` — keys
            # no producer has ever written) are gone rather than silently never
            # matching.
            task = getattr(event.payload, "task", None)
            description = (getattr(task, "description", None)
                           or str(event.type.value))
            params: Dict[str, Any] = {
                "reasoning": f"{event.type.value} via {event.origin or 'substrate'}"}
            if task is not None:
                params["task_type"] = getattr(getattr(task, "type", None), "value", "") or ""
                params["priority"] = str(getattr(getattr(task, "priority", None),
                                                 "name", "medium")).lower()
            verdict = await get_runtime_governance().monitor(
                str(event.type.value), description, params, origin=event.origin or "")
            if verdict.compliant:
                return
            # The substrate observes the verdict; its own appraisal responds to it as
            # to any safety-blocked outcome (damped exploration, raised caution/escalation).
            from core.learning.meta_learning import OutcomeClass
            self.appraisal.update(
                outcome_quality=0.0, action_success_rate=0.0,
                outcome_class=OutcomeClass.SAFETY_BLOCKED,
                self_initiated=(getattr(getattr(task, "source", None), "value", None)
                                == "autonomous"))
        except Exception as e:
            logger.debug("governance monitor reaction skipped: %s", e)

    async def get_intelligent_memory_context(
        self,
        query: str,
        context_type: str = 'general',
        domain: Optional[str] = None,
        thinking_mode: str = 'auto',
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None
    ) -> Optional[str]:
        """Retrieve memory context for LLM injection, if policy says it is wanted.

        POLICY / MECHANISM SPLIT. This used to import
        `core.memory.intelligent_memory_injector` — a module that never existed —
        and expected `InjectionDecision.SKIP` and `get_relevant_memory_types()`.
        The import was caught by `except ModuleNotFoundError: return None`, so
        for its whole life this returned "no memories" instead of failing.

        The real mechanism (`MemoryInjector`) exists and is constructed in
        main.py. What was missing was the POLICY layer, which now lives in
        `memory_injection_policy.py`:

            policy.decide(...)  -> "should I, and which kinds?"
            injector.inject_memories(...) -> "retrieve, format, place"

        The old path also required `mysql_memory_agent`, which is permanently
        None — MySQL is retired, PostgreSQL is the store. That dependency is
        gone rather than resurrected.

        Returns the formatted context, or None when policy declined (an honest
        decision, logged with its reason codes) or retrieval found nothing.
        """
        # ── STAGE 1: POLICY. Failure here must not look like "no memories".
        try:
            from core.memory.utils.memory_injection_policy import get_memory_injection_policy
            plan = get_memory_injection_policy().decide(
                query=query,
                context_type=context_type,
                domain=domain,
                thinking_mode=thinking_mode,
            )
        except Exception as e:
            logger.error(
                "Memory injection POLICY failed (%s) — proceeding without memory. "
                "This is a policy fault, not an empty memory store.", e
            )
            return None

        if not plan.enabled:
            logger.debug(
                "Memory injection declined for context_type=%s: %s",
                context_type, ", ".join(plan.reason_codes) or "no reason given"
            )
            return None

        # ── STAGE 2: MECHANISM. Independent failure boundary: a broken injector
        # must not be reported as a policy skip, and vice versa.
        try:
            injector = getattr(self, 'memory_injector', None)
            if injector is None:
                from core.memory.utils.memory_injector import get_memory_injector
                injector = get_memory_injector()

            from core.memory.utils.memory_injector import InjectionConfig, InjectionMode
            config = InjectionConfig(
                mode=InjectionMode.USER_CONTEXT,
                max_memories=plan.max_memories,
                min_relevance_score=plan.min_relevance,
            )
            # Pass the PLAN: this caller already consulted the policy, and the
            # injector must not re-decide with less context than we had.
            injected = await injector.inject_memories(
                query=plan.query, config=config, plan=plan
            )
        except Exception as e:
            logger.error(
                "Memory INJECTOR failed for an ENABLED plan (%s): %s. Policy wanted "
                "memory (%s) and did not get it — this is not a skip.",
                plan.memory_types, e, ", ".join(plan.reason_codes)
            )
            return None

        # THE FIELD IS `formatted_text`. This read `formatted_context` and then
        # `content`, neither of which exists on InjectedMemories, so `text` was
        # None on EVERY call -- the method then logged "retrieval returned
        # nothing" and returned None while retrieval had in fact succeeded.
        # Verified: memory was searched, rows were found, and the result was
        # discarded because of a name.
        text = getattr(injected, 'formatted_text', None)
        if not text:
            logger.debug(
                "Memory injection enabled (%s) but retrieval returned nothing",
                ", ".join(plan.reason_codes)
            )
            return None

        logger.info(
            "🧠 Memory context injected: types=%s max=%d domain=%s (%s)",
            list(plan.memory_types), plan.max_memories, plan.domain,
            ", ".join(plan.reason_codes)
        )
        return text


    @property
    def model_available(self) -> bool:
        """Retained for compatibility; the substrate holds no model. It reasons
        through its own faculties, so this reflects the reasoning faculty's
        presence."""
        return self.neural_bridge is not None

    def agent_allowance(self, reasoning_type: Any) -> int:
        """How many agents-of-self a reasoning kind warrants running in parallel.

        This is the SELF's decision, not the reasoning faculty's: the coordinator
        is the one that reasons and deploys copies of itself, so it owns how much
        parallel copying a kind of thinking justifies. The reasoning faculty only
        supplies the grounded MEASUREMENT (`reasoning_difficulty` — how costly the
        kind is here, from real latency); the self translates that into an
        allowance. Harder/costlier thinking earns more parallel copies. No flat
        cap. Falls back to the moderate default if reasoning isn't up yet."""
        difficulty = 1.0
        if self.neural_bridge is not None:
            try:
                difficulty = float(self.neural_bridge.reasoning_difficulty(reasoning_type))
            except Exception:
                difficulty = 1.0
        # difficulty 1.0 -> 2 agents, 2.0 -> 4, 2.5 -> 5, clamped [2, 6].
        return max(2, min(6, round(2.0 * difficulty)))

    async def reason_about(self, question: str, context: Optional[Dict[str, Any]] = None,
                          reasoning_type: ReasoningType = ReasoningType.DEDUCTIVE):
        """Answer a question with the substrate. Returns a ReasoningResult, never None.

        NEVER A BARE None. The previous signature was `Optional[Dict]` and
        returned None for all of: reasoned-and-concluded-nothing,
        input-not-representable, malformed request, substrate never
        initialised, and something raised. A caller could not tell a broken
        system from a hard question -- which is how this method went unnoticed
        while being unable to succeed at all: it hand-built a ReasoningContext
        putting the question into `facts` when every strategy requires
        `premises`, and never populated `rules`. Measured: all four strategies
        inapplicable, zero conclusions, zero callers repo-wide.

        The distinctions ride on `metadata["reason"]`, which is the reasoning
        subsystem's EXISTING vocabulary (substrate_verified / substrate_refuted
        / substrate_undecided / unsupported_input / capability_unavailable /
        model_coverage / model_generation_failed / invalid_input /
        internal_fault). A separate outcome type here would be a second
        authority on what reasoning produced.

        DELEGATES rather than reasoning. NeuralSymbolicBridge already owns mode
        selection: the bridge formalises deterministically and consults a solver,
        substrate-first and substrate-only -- there is no model fallback.
        """
        from core.reasoning.neural_bridge import (REASON_CAPABILITY_UNAVAILABLE,
                                                  REASON_INTERNAL_FAULT,
                                                  REASON_INVALID_INPUT,
                                                  ReasoningMode, ReasoningRequest,
                                                  ReasoningResult)

        premises = list((context or {}).get("premises") or [])
        facts = list((context or {}).get("facts") or [])
        rules = list((context or {}).get("rules") or [])
        supporting = [str(item) for item in (premises + facts + rules)]

        def fault(reason: str, detail: str) -> "ReasoningResult":
            return ReasoningResult(
                answer="", confidence=0.0, mode_used=ReasoningMode.SYMBOLIC,
                metadata={"verified": False, "reason": reason, "detail": detail,
                          "evidence": supporting, "model_calls": 0,
                          "route": ["reason_about"]})

        if not (question or "").strip():
            return fault(REASON_INVALID_INPUT, "empty question")

        if self.neural_bridge is None:
            # A WIRING FAULT, NOT AN ABSENCE OF KNOWLEDGE.
            logger.error("reason_about called before the neural bridge was initialised")
            return fault(REASON_CAPABILITY_UNAVAILABLE, "neural bridge not initialised")

        try:
            # Reason through this substrate's OWN reasoning faculty (the bridge).
            result = await self.neural_bridge.reason(ReasoningRequest(
                query=question,
                context=supporting,
                task_metadata={"requested_reasoning_type": reasoning_type.value,
                               **((context or {}).get("task_metadata") or {})},
            ))
        except Exception as e:
            raise_if_structural(e, "autonomous_coordinator.reason_about")
            logger.error(f"Error in reasoning: {e}")
            return fault(REASON_INTERNAL_FAULT, str(e))

        if result is None:
            return fault(REASON_INTERNAL_FAULT, "reasoning authority returned nothing")

        # Provenance, recorded onto the result the authority produced rather
        # than copied into a parallel object.
        metadata = dict(getattr(result, "metadata", {}) or {})
        metadata.setdefault("evidence", supporting)
        metadata["route"] = ["reason_about", "neural_bridge",
                             str(getattr(result, "mode_used", ""))] + (
                                 [metadata["reason"]] if metadata.get("reason") else [])
        metadata["model_calls"] = AutonomousCoordinator._model_calls_on(result, metadata)
        result.metadata = metadata

        await self.store_memory(
            MemoryType.SEMANTIC,
            {
                "event": "reasoning_conclusion",
                "question": question,
                "reasoning_mode": str(getattr(result, "mode_used", "")),
                "conclusion": getattr(result, "answer", None),
                "confidence": float(getattr(result, "confidence", 0.0) or 0.0),
                "verified": bool(metadata.get("verified")),
                "reason": metadata.get("reason"),
                "evidence": supporting,
                "timestamp": datetime.now().isoformat(),
            },
            importance=(float(getattr(result, "confidence", 0.0) or 0.0)
                        if metadata.get("verified") else 0.3),
            tags=["reasoning", "decision_making", "autonomous_system"],
        )
        return result

    @staticmethod
    def _model_calls_on(result: Any, metadata: Dict[str, Any]) -> int:
        """Whether a model was on this answer's path.

        DERIVED from the mode and producer code, not counted at the call site.
        Enough to say a model was involved; NOT a precise count -- an
        experiment needing a hard zero should detach the model rather than
        trust this number.
        """
        from core.reasoning.neural_bridge import (REASON_MODEL_COVERAGE,
                                                  REASON_MODEL_FAILED)
        mode = str(getattr(result, "mode_used", "") or "").lower()
        if metadata.get("reason") in (REASON_MODEL_COVERAGE, REASON_MODEL_FAILED):
            return 1
        return 1 if ("neural" in mode or "hybrid" in mode) else 0

    async def predict_system_behavior(self, domain: PredictionDomain, 
                                     horizon: PredictionHorizon = PredictionHorizon.SHORT_TERM,
                                     context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Use predictive intelligence to forecast system behavior"""
        try:
            prediction_context = context or {
                "system_mode": self.system_state.mode.value,
                "active_goals": len(self.system_state.active_goals),
                "active_tasks": len(self.system_state.active_tasks),
                "resource_usage": self.system_state.resource_usage,
                "uptime": self.stats["uptime_seconds"]
            }
            
            prediction = await self.intelligence.generate_comprehensive_prediction(
                domain, horizon, prediction_context
            )
            
            if prediction:
                # Store prediction in memory
                await self.store_memory(
                    MemoryType.SEMANTIC,
                    {
                        "event": "system_prediction",
                        "domain": domain.value,
                        "horizon": horizon.value,
                        "prediction": prediction.predicted_value,
                        "confidence": prediction.confidence,
                        "reasoning": prediction.reasoning,
                        "context": prediction_context,
                        "timestamp": datetime.now().isoformat()
                    },
                    importance=prediction.confidence,
                    tags=["prediction", "intelligence", "autonomous_system"]
                )
                
                return {
                    "predicted_value": prediction.predicted_value,
                    "confidence": prediction.confidence,
                    "reasoning": prediction.reasoning,
                    "domain": domain.value,
                    "horizon": horizon.value
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in prediction: {e}")
            return None
    
    async def perform_cross_domain_reasoning(self, query_text: str, 
                                          source_domains: List[str],
                                          target_domains: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """Perform cross-domain reasoning using the Universal Domain Master"""
        try:
            if not self.universal_domain_master:
                logger.warning("Universal Domain Master not available for cross-domain reasoning")
                return None
            
            # Coerce domain names to DomainType at the boundary.
            #
            # This signature takes List[str] and handed those strings straight
            # into CrossDomainQuery.source_domains, which is declared
            # List[DomainType]. The engine calls `.value` on each, so every
            # query died with "'str' object has no attribute 'value'".
            #
            # Postgres stores ids as `domain_<value>` (domain_scientific) while
            # the enum's value is the bare word (scientific); both spellings are
            # accepted. An unrecognised name is REFUSED, not dropped: silently
            # skipping it would turn "you asked about a domain that does not
            # exist" into "no mappings found", which is a different answer.
            def _as_domain_types(names, label):
                out = []
                for n in names or []:
                    if isinstance(n, DomainType):
                        out.append(n)
                        continue
                    key = str(n).strip().lower()
                    if key.startswith("domain_"):
                        key = key[len("domain_"):]
                    try:
                        out.append(DomainType(key))
                    except ValueError:
                        raise ValueError(
                            f"unknown {label} domain {n!r}; known domains: "
                            f"{', '.join(d.value for d in DomainType)}"
                        )
                return out

            try:
                src_types = _as_domain_types(source_domains, "source")
                tgt_types = _as_domain_types(target_domains, "target")
            except ValueError as e:
                logger.warning("Cross-domain reasoning refused: %s", e)
                return {"success": False, "error": str(e)}

            if not src_types:
                return {"success": False, "error": "no source domains supplied"}

            # Create cross-domain query
            query = CrossDomainQuery(
                query_id=f"autonomous_{int(asyncio.get_event_loop().time())}",
                reasoning_strategy=ReasoningStrategy.COMPOSITIONAL,
                source_domains=src_types,
                target_domains=tgt_types,
                query_text=query_text,
                metadata={
                    "system_mode": self.system_state.mode.value,
                    "active_goals": [str(goal) for goal in self.system_state.active_goals],
                    "coordinator_id": id(self)
                }
            )
            
            # Execute cross-domain reasoning.
            #
            # This called `cross_domain_reasoning(query)`, which is not a method
            # on UniversalDomainMaster -- the real entry point is
            # `execute_cross_domain_query`. It then read three fields the result
            # does not carry: `generated_mappings` (it is `mappings`),
            # `processing_time` (it is `execution_time`), and `confidence`,
            # which DomainIntegrationResult has never had. Every call raised
            # AttributeError into the handler below and returned failure, so a
            # working Postgres-backed engine read as permanently broken.
            result = await self.universal_domain_master.execute_cross_domain_query(query)

            if result.success:
                mappings = result.mappings or []
                self.stats["cross_domain_operations"] += 1
                self.stats["domain_integrations"] += len(mappings)

                # Confidence is EARNED from the mappings actually found, not
                # asserted by the result object. No mappings means no
                # confidence -- None, not 0.0, because "we found nothing" and
                # "we are certain of nothing" are different claims and only one
                # of them is true here.
                confidences = [
                    m.confidence for m in mappings
                    if getattr(m, "confidence", None) is not None
                ]
                confidence = (sum(confidences) / len(confidences)) if confidences else None

                # Store reasoning result in memory
                await self.store_memory(
                    MemoryType.SEMANTIC,
                    {
                        "event": "cross_domain_reasoning",
                        "query": query_text,
                        "source_domains": source_domains,
                        "target_domains": target_domains,
                        "insights": result.insights,
                        "confidence": confidence,
                        "mappings_count": len(mappings),
                        "domains_queried": result.domains_queried,
                        "processing_time": result.execution_time,
                        "timestamp": datetime.now().isoformat()
                    },
                    importance=confidence if confidence is not None else 0.0,
                    tags=["cross_domain", "reasoning", "domain_integration"]
                )

                return {
                    "success": True,
                    "insights": result.insights,
                    "confidence": confidence,
                    "mappings": len(mappings),
                    "processing_time": result.execution_time
                }

            return {"success": False, "error": result.error or "Cross-domain reasoning failed"}
            
        except Exception as e:
            logger.error(f"Error in cross-domain reasoning: {e}")
            return {"success": False, "error": str(e)}
    
    async def make_enhanced_prediction(self, prediction_target: str, 
                                     context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Make enhanced predictions using both predictive intelligence and domain knowledge"""
        try:
            if not self.intelligence:
                logger.warning("Predictive Intelligence not available")
                return None
            
            prediction_context = context or {}
            prediction_context.update({
                "system_state": {
                    "mode": self.system_state.mode.value,
                    "active_goals": len(self.system_state.active_goals),
                    "active_tasks": len(self.system_state.active_tasks),
                    "resource_usage": self.system_state.resource_usage
                },
                "coordinator_stats": self.stats.copy()
            })
            
            # Enhanced prediction with domain context
            if self.universal_domain_master and self.domain_registry:
                # Get relevant domains for the prediction target
                domains = await self.domain_registry.list_domains()
                relevant_domains = [d for d in domains if prediction_target.lower() in d.name.lower() or 
                                  any(prediction_target.lower() in concept.lower() for concept in d.concepts.keys())]
                
                if relevant_domains:
                    prediction_context["relevant_domains"] = [d.name for d in relevant_domains]
            
            # Generate prediction using predictive intelligence
            prediction = await self.intelligence.generate_comprehensive_prediction(
                PredictionDomain.SYSTEM_PERFORMANCE,
                PredictionHorizon.MEDIUM_TERM,
                prediction_context
            )
            
            if prediction:
                self.stats["predictions_made"] += 1
                
                # Store enhanced prediction in memory
                await self.store_memory(
                    MemoryType.SEMANTIC,
                    {
                        "event": "enhanced_prediction",
                        "target": prediction_target,
                        "predicted_value": prediction.predicted_value,
                        "confidence": prediction.confidence,
                        "reasoning": prediction.reasoning,
                        "domain_context": prediction_context.get("relevant_domains", []),
                        "timestamp": datetime.now().isoformat()
                    },
                    importance=prediction.confidence,
                    tags=["prediction", "enhanced", "autonomous"]
                )
                
                return {
                    "prediction": prediction.predicted_value,
                    "confidence": prediction.confidence,
                    "reasoning": prediction.reasoning,
                    "domain_context": prediction_context.get("relevant_domains", [])
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in enhanced prediction: {e}")
            return None
    
    async def get_domain_insights(self, domain_name: str) -> Optional[Dict[str, Any]]:
        """Get insights about a specific domain using the domain system"""
        try:
            if not self.universal_domain_master:
                logger.warning("Universal Domain Master not available for domain insights")
                return None
            
            # understand_domain() is not on UniversalDomainMaster under any
            # name -- its public API is execute_cross_domain_query,
            # get_statistics, initialize, shutdown. Insight about ONE domain is
            # the registry's question anyway, so it is answered from what Torin
            # has actually learned about it.
            registry = self.domain_registry
            if registry is None:
                from core.domain.domain_registry import get_domain_registry
                registry = get_domain_registry()
                self.domain_registry = registry
            if not registry.initialized:
                await registry.initialize()

            domain = await registry.get_domain(domain_name)
            if domain is None and not str(domain_name).startswith("domain_"):
                domain = await registry.get_domain(f"domain_{domain_name}")

            if domain is not None:
                # Through the Master -- the authority for the domain system --
                # not the registry directly, matching get_statistics() below.
                similar = await self.universal_domain_master.similar_domains(
                    domain.domain_id, threshold=0.0)
                return {
                    "domain": domain.domain_id,
                    "name": domain.name,
                    "concept_count": len(domain.concepts),
                    "unpopulated": domain.domain_id in registry.unpopulated_domain_ids,
                    "nearest_domains": [(d.domain_id, round(sc, 4)) for d, sc in similar[:5]],
                    "statistics": await self.universal_domain_master.get_statistics(),
                }

            # A domain Torin has not learned is a real answer, not a failure.
            logger.info("No learned domain matching %r", domain_name)
            return {"domain": domain_name, "learned": False,
                    "reason": "not a registered domain"}
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting domain insights for {domain_name}: {e}")
            return None
    
    # =========================================================================
    # THE SELF — the substrate's sense of itself. This coordinator IS the
    # substrate, so its identity, live state, and disposition are its own,
    # derived model-free from the faculties (appraisal, arbiter, constitution,
    # motivation, learning). None-honest: nothing here is fabricated.
    # =========================================================================

    _INTEROCEPTION = {
        "valence": "valence", "activation": "activation", "confidence": "confidence",
        "control": "controllability", "progress": "progress", "competence": "competence",
        "open_questions": "epistemic_opportunity", "goal_congruence": "goal_congruence",
        "agency": "agency", "risk": "risk",
    }

    @staticmethod
    def _appraisal():
        from core.agents.autonomous.appraisal import get_appraisal_system
        return get_appraisal_system()

    @staticmethod
    def _arbiter():
        from core.agents.autonomous.behavior_arbiter import get_behavior_arbiter
        return get_behavior_arbiter()

    @staticmethod
    def _constitution():
        from core.agents.autonomous.singleton_constitution import get_singleton_constitution
        return get_singleton_constitution()

    def motivation(self):
        """The motivation faculty this substrate is driven by."""
        return self.intrinsic_motivation

    def conversation(self, session: str = "default", *, db=None,
                     actor_identity=None):
        """This substrate holding a conversation — understanding a sentence
        against what it holds (via language/memory/reasoning) and replying. It
        uses the faculties this substrate owns, so a reply is composed through
        the brain that owns those faculties, never beside it. The faculty lives
        in this module (below) — `get_conversation` is defined here.

        The substrate's own `emit` is injected so a proposition taught in this
        conversation becomes a self-event (EVIDENCE_ADMITTED) the domain
        authority reacts to. Its `disposition` read is injected too, so a reply
        can be informed by self-state. Both set on every call (idempotent), so a
        conversation held before they existed picks them up on next use."""
        conversation = get_conversation(session, db=db, actor_identity=actor_identity)
        conversation._emit = self.emit
        conversation._learning = self.learning
        conversation._disposition = self.disposition
        # A conversation created before a user authenticated picks up the verified
        # identity on the next call (idempotent), so the actor is never stale.
        if actor_identity is not None:
            conversation._actor_identity = actor_identity
        return conversation

    def _interoception(self) -> Optional[Dict[str, Any]]:
        """My read of my own internal state — the measured interoceptive variables."""
        state = self._appraisal().current_state
        if state is None:
            return None
        readings = {label: getattr(state, attr, None)
                    for label, attr in self._INTEROCEPTION.items()}
        measured = {k: round(float(v), 3) for k, v in readings.items()
                    if isinstance(v, (int, float))}
        return measured or None

    def _attitude(self) -> Optional[Dict[str, Any]]:
        """How I feel now, from appraisal's derived emotions. None if unappraised."""
        state = self._appraisal().current_state
        if state is None:
            return None
        return {
            "eagerness": state.eagerness, "doubt": state.doubt,
            "frustration": state.frustration, "satisfaction": state.satisfaction,
            "valence": state.valence, "attribution": state.attribution,
        }

    def _temperament(self) -> Dict[str, float]:
        """The standing drives — what I am, before any situation."""
        from dataclasses import asdict as _asdict
        return {k: float(v) for k, v in _asdict(self.motivation().weights).items()}

    async def _drives(self) -> Optional[Dict[str, float]]:
        """How strongly each drive is active right now."""
        try:
            state = await self.motivation().get_motivation_state()
            dims = state.get("dimensions")
            return {k: float(v) for k, v in dims.items()} if dims else None
        except Exception as e:
            logger.debug("Self: motivation state unavailable: %s", e)
            return None

    def _values(self) -> List[str]:
        """The laws I am bound by. Read from the constitution, not restated."""
        laws = getattr(self._constitution(), "governance_laws", {}) or {}
        return [law.law_name for _, law in sorted(laws.items())]

    async def _competence(self) -> Optional[Dict[str, Any]]:
        """What I am actually good at — the operators I have VALIDATED, per domain."""
        from core.learning.rule_store import get_rule_store
        try:
            rules = await get_rule_store().executable_rules()
        except Exception as e:
            logger.debug("Self: competence unreadable: %s", e)
            return None
        by_domain: Dict[str, int] = {}
        for stored in rules:
            if getattr(stored.rule, "action", None) is None:
                continue
            domain = getattr(stored, "domain_id", None) or "unattributed"
            by_domain[domain] = by_domain.get(domain, 0) + 1
        if not by_domain:
            return None
        return {"operators_by_domain": dict(sorted(by_domain.items())),
                "total_operators": sum(by_domain.values()),
                "domains": len(by_domain)}

    async def _purpose(self) -> Optional[List[str]]:
        """What I am for — the ACTIVE directives, read from internal_directives."""
        try:
            from core.agents.autonomous.directive_manager import DirectiveManager
            from core.agents.autonomous.directive_types import DirectiveStatus
            from core.database import get_database_manager
            db = get_database_manager()
            if not getattr(db, "initialized", False):
                await db.initialize()
            active = await DirectiveManager(db).get_directives_by_status(DirectiveStatus.ACTIVE)
        except Exception as e:
            logger.debug("Self: purpose unreadable: %s", e)
            return None
        texts = [t for t in (getattr(d, "directive_text", "") or "" for d in active) if t.strip()]
        return texts or None

    async def _continuity(self) -> Optional[Dict[str, Any]]:
        """Who I have been, carried forward — from durable state only."""
        cont: Dict[str, Any] = {}
        try:
            profile = self.motivation().profile
            if profile.event_reward_count:
                cont["experiential_baseline"] = round(float(profile.mean_event_reward), 4)
                cont["past_events"] = int(profile.event_reward_count)
        except Exception as e:
            logger.debug("Self: experiential baseline unreadable: %s", e)
        try:
            from core.database import get_database_manager
            cont["deployment"] = getattr(get_database_manager(), "database", None)
        except Exception as e:
            logger.debug("Self: deployment unreadable: %s", e)
        return cont or None

    async def _development(self) -> Optional[Dict[str, Any]]:
        """How developed I am — a GLOBAL read of how much I hold and have lived, which sets how
        broadly hungry I should be to grow. Real counts ONLY, from the stores themselves; None where
        a store is unreadable — never a fabricated figure. The `*_pressure` fields are saturating
        indicators over those real counts (high when I hold/have-lived little, falling as I
        accumulate), with the raw counts exposed alongside so nothing hides behind them. Overall
        `growth_pressure` is the MAX across axes: I am only 'grown' when developed across the board,
        so a rich knowledge store with few memories still leaves me hungry to interact and experience."""
        kb = None
        try:
            kb = await self.learning.knowledge_base_size()   # {concepts, rules, memories, total} | None
        except Exception as e:
            logger.debug("Self: knowledge base size unreadable: %s", e)
        reg = self.domain_registry
        domains_total = domains_known = domains_unknown = None
        if reg is not None:
            try:
                domains_total = len(reg.domains)
                domains_unknown = len(getattr(reg, "unpopulated_domain_ids", ()) or ())
                domains_known = max(0, domains_total - domains_unknown)
            except Exception as e:
                logger.debug("Self: domain breadth unreadable: %s", e)
        if kb is None and domains_total is None:
            return None                                      # nothing real to report — honest None

        out: Dict[str, Any] = {}
        knowledge_pressure = experience_pressure = None
        if kb is not None:
            concepts = int(kb.get("concepts") or 0)
            rules = int(kb.get("rules") or 0)
            memories = int(kb.get("memories") or 0)
            # the count at which the broad hunger has half-faded — design parameters of the curve,
            # not measured values; the curve itself runs over the REAL counts above.
            _KNOWLEDGE_HALF = 5000.0
            _EXPERIENCE_HALF = 500.0
            knowledge_pressure = round(_KNOWLEDGE_HALF / (_KNOWLEDGE_HALF + concepts + rules), 4)
            experience_pressure = round(_EXPERIENCE_HALF / (_EXPERIENCE_HALF + memories), 4)
            out.update({"concepts": concepts, "rules": rules, "memories": memories,
                        "knowledge_pressure": knowledge_pressure,
                        "experience_pressure": experience_pressure})
        if domains_total is not None:
            out.update({"domains_total": domains_total, "domains_known": domains_known,
                        "domains_unknown": domains_unknown})
        pressures = [p for p in (knowledge_pressure, experience_pressure) if p is not None]
        out["growth_pressure"] = round(max(pressures), 4) if pressures else None
        return out

    @staticmethod
    def _frontier_of(domain: str, claim: str) -> str:
        """Which frontier a pursuit advances — so it dispatches to the right closer: ENVIRONMENT
        (probe/observe — you cannot look up your own world), CAPABILITY (learn/validate an operator),
        or KNOWLEDGE (a declarative not-knowing — research/look_up/teach)."""
        d = (domain or "").lower()
        c = (claim or "").lower()
        if d.startswith("environment_") or d == "environment":
            return "environment"
        if "operators of domain" in c:          # the competence-belief signature: what I CAN do
            return "capability"
        return "knowledge"

    def _score_pursuits(self, regions, growth: float,
                        operators_by_domain: Optional[Dict[str, int]] = None,
                        domain_concepts: Optional[Dict[str, int]] = None,
                        bearings: Optional[Dict[str, "Bearing"]] = None
                        ) -> List[Dict[str, Any]]:
        """Rank not-knowing regions into pursuits, DETERMINISTICALLY. Local uncertainty (entropy) is
        lifted by global developmental hunger (`growth`): a young, hungry substrate weights even modest
        gaps highly; a developed one only chases the sharpest. An unknown ENVIRONMENT gets a further
        lift — a place I inhabit but do not know is worth knowing. No RNG: same state, same ranking.

        FOOTHOLD — why the score needs a signal that isn't entropy.

        `get_unstable_regions` selects beliefs by `entropy > 0.7`, which is the
        set of beliefs whose posterior sits near 0.5 — i.e. exactly the ones no
        evidence has moved. So every region it returns arrives with entropy ~1.0,
        `evidence_for`/`evidence_against` at 0 and `relationship_count` at 0: the
        inputs are uniform BY CONSTRUCTION, not by accident. Scoring on entropy
        alone therefore produced 91 pursuits whose scores spanned 0.0087, and
        `limit` sliced arbitrarily through a tie block — which pursuit surfaced
        was decided by iteration order. The ranking carried no information.

        The discriminating signal the substrate already holds is COMPETENCE: how
        many validated operators it has in the gap's domain. A gap next to ground
        it can already stand on is one it can actually close; a gap in a domain it
        has nothing in is a wish. This is the same principle the existing
        structural tiebreak states — "a more-connected belief is more
        consequential to resolve" — applied to a signal that is not uniform.

        `operators_by_domain` is the rule store's own count of EXECUTABLE rules
        per domain. Absent (competence unreadable), the foothold term contributes
        nothing rather than a guess, and the ranking degrades to what it was.
        """
        g = max(0.0, min(1.0, float(growth)))
        footholds = operators_by_domain or {}
        pursuits: List[Dict[str, Any]] = []
        for r in regions or []:
            domain = getattr(r, "domain", None) or "general"
            entropy = max(0.0, min(1.0, float(getattr(r, "entropy", 0.0) or 0.0)))
            md = getattr(r, "metadata", {}) or {}
            claim = md.get("claim") or getattr(r, "description", "") or ""
            frontier = self._frontier_of(domain, claim)
            score = entropy * (0.5 + 0.5 * g)               # hunger lifts local not-knowing
            if frontier == "environment":
                score = min(1.0, score + 0.15 * g)          # knowing where I live matters more when hungry
            # FOOTHOLD: operators already held in this gap's domain. Saturating,
            # so a domain with many operators does not swamp the uncertainty term
            # — this orders among equal not-knowing, it does not replace it.
            foothold = int(footholds.get(domain, 0) or 0)
            if foothold:
                score = min(1.0, score + 0.20 * (1.0 - 1.0 / (1.0 + foothold)))
            # GROUNDING: is this gap somewhere I actually have a world model of?
            #
            # `domain_concepts is None` means the registry could not be read — no
            # signal, so nothing is added. A domain MISSING from a registry that
            # WAS read is different and informative: the substrate is uncertain
            # about a domain that is not even a place in its world model, which is
            # a less closable gap than one it holds concepts about. Vacant and
            # blind are not the same, and they must not score the same.
            concepts = None if domain_concepts is None else domain_concepts.get(domain)
            if concepts is not None:
                score = min(1.0, score
                            + 0.05                                    # it is a place I know of
                            + 0.15 * (1.0 - 1.0 / (1.0 + concepts)))  # and hold this much about
            # STAKES: does this gap bear on an interest my own law protects?
            #
            # THE TERM THIS RANKING HAD NO WAY TO EXPRESS. Every signal above is
            # about how CLOSABLE a gap is — uncertainty, hunger, operators held,
            # concepts held — and none about whether closing it MATTERS. So a
            # gap about a famine and a gap about a file extension, at equal
            # entropy in equal domains, scored identically and `limit` decided
            # between them by iteration order. Asked why a substrate that had
            # just read about an outbreak would not come to want a cure, the
            # answer was here: nothing ever ranked the outbreak above the file.
            #
            # LARGEST WEIGHT OF THE THREE, deliberately. A gap the substrate is
            # well equipped to close is worth more than one it is not; a gap
            # that bears on someone's safety is worth more than either. This is
            # the one place in the substrate where "what matters" outranks "what
            # is easy" — and it is a ranking, never a permission (no law reads
            # this, or any other part of appraisal).
            bearing = (bearings or {}).get(claim or domain)
            if bearing is not None and bearing.borne:
                score = min(1.0, score + 0.25)
            pursuits.append({
                "target": claim or domain,
                "domain": domain,
                "frontier": frontier,
                "entropy": round(entropy, 4),
                "score": round(score, 4),
                "source": getattr(r, "target_type", "belief"),
                #: which of my own laws this gap bears on, and the taxonomy path
                #: that showed it — None when I have no reading, so a pursuit can
                #: always say whether stakes moved it and why.
                "bearing": bearing.to_dict() if bearing is not None else None,
                # structural signals (not calibration) — used only to break score ties meaningfully
                "connections": int(md.get("relationship_count") or 0),
                "evidence": int(md.get("evidence_for") or 0) + int(md.get("evidence_against") or 0),
                #: validated operators held in this domain — what makes the gap closable
                "foothold": foothold,
                #: concepts held about this domain; None = not a place in my world
                #: model at all (distinct from 0, which is a registered empty one)
                "grounding": concepts,
            })
        # deterministic order: score desc, then STRUCTURAL tiebreak — a more-connected belief is more
        # consequential to resolve, and a less-evidenced one is more genuinely unknown; text is the
        # final stable tiebreak. (These order equal scores; they do not change the scores themselves.)
        pursuits.sort(key=lambda p: (-p["score"], -p["connections"], p["evidence"], p["target"]))
        # DEDUP by normalized target: many beliefs carry the same claim; pursuing it once suffices, so
        # keep the strongest representative (first after the sort) and drop the rest.
        seen: set = set()
        deduped: List[Dict[str, Any]] = []
        for p in pursuits:
            key = str(p["target"]).strip().lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(p)
        return deduped

    async def _intrinsic_pursuits(self, limit: int = 8) -> List[Dict[str, Any]]:
        """The unified motivation DECISION, in the self: given my whole state, what is worth pursuing
        to grow — ranked, each tagged with the frontier it advances. Reads the developmental appraisal
        (global hunger) and the epistemic unstable regions (local not-knowing); the affect/fitness/
        reward mechanics stay where they are — this is only the decision. Deterministic for a given
        state, so the same self produces the same ranking."""
        dev = await self._development()
        growth = float((dev or {}).get("growth_pressure") or 0.0)
        try:
            from core.reasoning.epistemic_engine import get_epistemic_engine
            regions = get_epistemic_engine().get_unstable_regions()
        except Exception as e:
            raise_if_structural(e, "autonomous_coordinator._intrinsic_pursuits")
            regions = []
        # WHAT I CAN ALREADY DO, per domain — the signal that tells one gap from
        # another. Read from the rule store's validated operators; None when
        # competence is unreadable, and then the foothold term contributes
        # nothing rather than being invented.
        competence = await self._competence()
        # WHAT I HOLD A WORLD MODEL OF, per domain. None when the registry cannot
        # be read at all — then grounding contributes nothing, rather than every
        # domain being scored as though it were unknown to me.
        domain_concepts: Optional[Dict[str, int]] = None
        try:
            registry = self.domain_registry
            if registry is None:
                from core.domain.domain_registry import get_domain_registry
                registry = get_domain_registry()
                self.domain_registry = registry
            if not registry.initialized:
                await registry.initialize()
            domain_concepts = {d_id: len(d.concepts)
                               for d_id, d in (registry.domains or {}).items()}
        except Exception as e:
            raise_if_structural(e, "autonomous_coordinator._intrinsic_pursuits")
            logger.debug("domain grounding unreadable for pursuit ranking: %s", e)
        # WHAT ANY OF THESE GAPS BEAR ON, read through my own law. Computed
        # HERE, where awaiting is possible, and handed to the scorer the same
        # way competence and grounding are — the ranking stays a deterministic
        # function of state it was given, rather than reaching for the world
        # mid-sort. A reading that cannot be taken leaves the pursuit without
        # one, which scores as no stakes rather than as none at stake.
        bearings: Dict[str, "Bearing"] = {}
        for r in regions or []:
            md = getattr(r, "metadata", {}) or {}
            subject = (md.get("claim") or getattr(r, "description", "")
                       or getattr(r, "domain", "") or "")
            subject = str(subject).strip()
            if not subject or subject in bearings:
                continue
            try:
                bearings[subject] = await self.constitution.bearing(subject)
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._intrinsic_pursuits")
        return self._score_pursuits(
            regions, growth,
            (competence or {}).get("operators_by_domain"),
            domain_concepts, bearings)[:max(0, limit)]

    def _pursuit_to_goal(self, pursuit: Dict[str, Any]):
        """Turn a frontier pursuit into an EXECUTABLE goal, routed to the real
        closer for its frontier — no new execution path, no stub:

          KNOWLEDGE  → a research description the knowledge loop (`understand`)
                       already answers (memory → reason → gap → learn).
          CAPABILITY → a competence DRIVE goal the existing `_execute_drive_goal`
                       runs (domain-contrastive operator re-induction), carrying
                       the `drive`/`domain_id`/`scope` metadata that handler reads.
          ENVIRONMENT→ None: a place I inhabit is closed by the dedicated
                       environment reaction (`_react_investigate_environment`), not
                       by a queued exploration task. Skipping it here is correct
                       routing, not an omission.

        Returns a lightweight goal (a SimpleNamespace the downstream reads by
        attribute: description, metadata, intrinsic-value fields) or None when the
        frontier has no queued-task route."""
        from types import SimpleNamespace
        frontier = pursuit.get("frontier")
        domain = pursuit.get("domain") or "general"
        target = str(pursuit.get("target") or domain).strip()
        entropy = float(pursuit.get("entropy") or 0.0)
        score = float(pursuit.get("score") or 0.0)
        # intrinsic values carried for create_goal + the adaptive bandit: the
        # not-knowing (entropy) is expected novelty; the ranked score is the
        # curiosity value. Real signals from the pursuit, not placeholders.
        values = {"expected_novelty": round(entropy, 4),
                  "expected_competence_gain": round(entropy, 4),
                  "curiosity_value": round(score, 4),
                  "intrinsic_reward_potential": round(score, 4)}
        if frontier == "capability":
            desc = f"Strengthen my operators in domain {domain}"
            md = {"objective_type": "competence", "drive": "competence",
                  "scope": "domain_contrastive", "domain_id": domain,
                  "frontier": frontier}
        elif frontier == "knowledge":
            # the knowledge loop routes on a leading research verb (see
            # _answer_via_knowledge_loop); the target is the not-known claim/topic.
            desc = f"Research {target}"
            md = {"objective_type": "research", "frontier": frontier,
                  "domain_id": domain}
        else:
            return None      # environment: closed by _react_investigate_environment
        return SimpleNamespace(
            id=None, description=desc, metadata=md,
            expected_novelty=values["expected_novelty"],
            expected_competence_gain=values["expected_competence_gain"],
            curiosity_value=values["curiosity_value"],
            intrinsic_reward_potential=values["intrinsic_reward_potential"])

    def _domain_satisfaction(self, domain_id: str) -> Optional[Dict[str, Any]]:
        """How well I have SATISFIED (come to KNOW) a domain — the 'have I learned it' input to
        knowledge-based operability. Knowledge COVERAGE (how developed the domain's concept graph is:
        size + connectedness + relational variety, in [0,1]) blended with CONFIDENCE (how sure I am
        about what I hold there = 1 − mean belief entropy). Real signals from the domain's own graph
        and beliefs; None if the domain is unknown. This is SEPARATE from operator competence (what I
        can DO) — it measures what I KNOW, which is what confers *knowledge-based* operability."""
        reg = self.domain_registry
        if reg is None:
            return None
        domain = reg.domains.get(domain_id)
        if domain is None:
            return None
        from core.domain.domain_types import structural_complexity
        coverage = round(float(structural_complexity(domain)), 4)     # [0,1], grows as the graph develops
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        bels = [b for b in get_uncertainty_system().beliefs.values()
                if getattr(b, "domain", None) == domain_id]
        if bels:
            confidence = round(1.0 - sum(float(getattr(b, "entropy", 1.0)) for b in bels) / len(bels), 4)
        else:
            confidence = None                                        # unmeasured — no beliefs held here yet
        # noisy-OR over two PARTLY-INDEPENDENT knowledge stores: the concept graph (coverage) and the
        # belief store (confidence). A domain is satisfied to the degree it has strong structure OR
        # confident beliefs, and more when both. A product would wrongly zero a domain rich in one and
        # empty in the other (e.g. many confident beliefs but no graph). conf unmeasured → 0 contribution.
        conf_eff = confidence if confidence is not None else 0.0
        satisfaction = round(1.0 - (1.0 - coverage) * (1.0 - conf_eff), 4)
        return {"domain": domain_id, "coverage": coverage, "confidence": confidence,
                "beliefs": len(bels), "satisfaction": satisfaction}

    # ActionClass severity → stakes scalar (mirrors the ordered consequence + appraisal's _RISK scale)
    _ACTION_STAKES = {"investigate": 0.2, "modify": 0.4, "archive": 0.6, "delete": 0.8, "execute": 0.95}

    async def _domain_stakes(self, domain_id: str) -> Dict[str, Any]:
        """The STAKES BASE of operating in a domain — the consequence of getting it wrong — from the
        domain's OWN operators' action classes (INVESTIGATE<MODIFY<ARCHIVE<DELETE<EXECUTE, resolved via
        the safety consequence machinery). Max over resolvable operators; a NEUTRAL 0.5 prior where the
        domain has no operators or none resolve (a researched-but-operator-empty domain) — the EARNED
        half then calibrates the true bar per-domain from real outcomes. Real signal, never hardcoded."""
        from core.learning.rule_store import get_rule_store
        from core.safety.action_consequence import _declared_consequence
        try:
            rules = await get_rule_store().executable_rules(domain_id)
        except Exception as e:
            raise_if_structural(e, "autonomous_coordinator._domain_stakes")
            rules = []
        stakes = None
        resolved = 0
        for stored in rules or []:
            action = getattr(getattr(stored, "rule", None), "action", None)
            pred = getattr(action, "predicate", None)
            dc = _declared_consequence(str(pred)) if pred else None
            if dc:
                s = self._ACTION_STAKES.get(dc[0].value)
                if s is not None:
                    resolved += 1
                    stakes = s if stakes is None else max(stakes, s)
        return {"domain": domain_id, "stakes": stakes if stakes is not None else 0.5,
                "operators": len(rules or []), "resolved": resolved,
                "basis": "operators" if stakes is not None else "neutral-prior"}

    #: How far EARNED operating trust may shift the operability bar around the
    #: stakes base (±BAND/2). Sized so proven-correct operation eases a high-stakes
    #: domain meaningfully, yet can never drop a dangerous domain onto near-zero
    #: knowledge (the floor holds), and being wrong raises the bar toward/above
    #: stakes -- the washing-machine dynamic: wrong answers demand MORE study.
    _OPERABILITY_BAND: float = 0.3
    _OPERABILITY_FLOOR: float = 0.2    # some knowledge is always required to operate
    _OPERABILITY_CEIL: float = 0.99    # never demand literal certainty

    #: Borrowed-knowledge (cross-domain transfer) parameters for the KNOW side.
    _BORROW_REL_MIN: float = 0.30      # min domain similarity to count as "confidently related"
    _BORROW_NEIGHBORS: int = 5         # top-K related domains consulted (one hop, no transitive chains)
    _BORROW_CAP: float = 0.5           # borrowing alone can reach at most half-satisfied — an
                                       # accelerant, never a substitute for own knowledge on a high bar

    async def _borrowed_satisfaction(self, domain_id: str) -> Dict[str, Any]:
        """What confidently-related KNOWN domains lend to this one — the DECLARATIVE
        side of cross-domain transfer, as a discounted prior on the KNOW axis.

        Knowledge is related across domains: a domain strongly coupled to one the
        substrate knows cold is not starting from zero. Each related neighbor lends
        `similarity × neighbor's own satisfaction` — you can borrow at most what the
        neighbor actually knows, scaled by HOW related it is — combined across
        neighbors by noisy-OR. ONE HOP only (neighbors' own satisfaction, never
        their borrowed total, so nothing propagates transitively down weak chains),
        and CAPPED so borrowing lightens the load without ever substituting for own
        knowledge on a high-stakes bar. A domain with no structure has ~0 similarity
        to everything (the similarity measure's coupling/structural terms need a
        toehold), so a truly unknown-and-unrelated domain borrows nothing — the
        honest floor. Distinct from operator transfer (`transfer_relation`, which
        needs target operators): this transfers CONFIDENCE TO KNOW, not capability."""
        udm = getattr(self, "universal_domain_master", None)
        if udm is None:
            return {"borrowed": 0.0, "from": []}
        try:
            similar = await udm.similar_domains(domain_id, threshold=self._BORROW_REL_MIN)
        except Exception as e:
            raise_if_structural(e, "autonomous_coordinator._borrowed_satisfaction")
            return {"borrowed": 0.0, "from": []}
        contributions: List[float] = []
        lenders: List[Dict[str, Any]] = []
        for neighbor, sim in (similar or [])[:self._BORROW_NEIGHBORS]:
            nid = getattr(neighbor, "domain_id", None)
            if not nid or nid == domain_id:
                continue
            nb = self._domain_satisfaction(nid)        # the neighbor's OWN knowledge, one hop
            if not nb or nb["satisfaction"] is None:
                continue
            contrib = round(float(sim) * float(nb["satisfaction"]), 4)
            if contrib <= 0.0:
                continue
            contributions.append(contrib)
            lenders.append({"domain": nid, "similarity": round(float(sim), 4),
                            "neighbor_satisfaction": nb["satisfaction"], "lends": contrib})
        # noisy-OR: independent related neighbors each raise the borrowed prior,
        # none alone dominates; then cap so transfer stays an accelerant.
        borrowed = 1.0
        for c in contributions:
            borrowed *= (1.0 - c)
        borrowed = min(round(1.0 - borrowed, 4), self._BORROW_CAP)
        return {"borrowed": borrowed, "from": lenders}

    async def _domain_operability(self, domain_id: str) -> Dict[str, Any]:
        """Can I OPERATE in this domain yet? The KNOW→DO bridge, gated by a
        DOMAIN-DEPENDENT, HYBRID bar (stakes + earned): how much I must KNOW
        (`_domain_satisfaction`, plus what confidently-related domains LEND via
        `_borrowed_satisfaction` — cross-domain transfer on the KNOW side) measured
        against a bar set by what's at STAKE if I get it wrong (`_domain_stakes`)
        and adjusted by what I've EARNED operating correctly here
        (`operating_reliability`). Trivial domains clear a low bar on little
        knowledge; high-stakes ones demand thorough satisfaction first, then ease as
        correct operation is proven and rise again if it is wrong. A pure
        MEASUREMENT -- it decides nothing; `operable=False` means abstain and keep
        researching (the gap resurfaces as a knowledge pursuit)."""
        sat = self._domain_satisfaction(domain_id)
        stakes = (await self._domain_stakes(domain_id))["stakes"]
        rel = await self.universal_domain_master.operating_reliability(domain_id)
        earned = rel["earned"]                                   # [0,1], 0.5 = neutral/unearned
        # bar anchored at stakes; proven trust (earned>0.5) lowers it, a poor
        # record (earned<0.5) raises it; neutral leaves it at the stakes base.
        bar = stakes - self._OPERABILITY_BAND * (earned - 0.5)
        bar = round(max(self._OPERABILITY_FLOOR, min(self._OPERABILITY_CEIL, bar)), 4)
        own = sat["satisfaction"] if sat else None
        borrowed_info = await self._borrowed_satisfaction(domain_id)
        borrowed = borrowed_info["borrowed"]
        # EFFECTIVE satisfaction = own knowledge noisy-OR'd with what related domains
        # lend. Borrowed knowledge lightens the load (esp. long-horizon) but never
        # hides own ignorance: own and borrowed are reported separately. A domain
        # with neither own knowledge nor any related lender stays truly unknown.
        if own is None and borrowed <= 0.0:
            effective = None
        else:
            effective = round(1.0 - (1.0 - (own or 0.0)) * (1.0 - borrowed), 4)
        if effective is None:
            operable, reason = False, "unknown-domain"           # learn it before operating
        elif effective >= bar:
            operable = True
            reason = "satisfied" if (own or 0.0) >= bar else "satisfied-via-transfer"
        else:
            operable = False
            reason = "below-bar-earning" if rel["enough_history"] else "below-bar-researching"
        return {"domain": domain_id, "satisfaction": effective, "own_satisfaction": own,
                "borrowed_satisfaction": borrowed, "borrowed_from": borrowed_info["from"],
                "stakes": stakes, "earned": earned, "earned_basis": rel, "bar": bar,
                "operable": operable, "reason": reason}

    def _observe_environment(self) -> Dict[str, Any]:
        """Look at WHERE I run — every value read live from the host, nothing hardcoded — and derive a
        stable identity from the facts that make this place this place."""
        import getpass
        import hashlib
        import json as _json
        import os as _os
        import platform
        import socket
        import sys as _sys

        def _s(fn):
            try:
                return fn()
            except Exception:
                return None

        cwd = _s(_os.getcwd) or ""
        facts = {
            "platform": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "hostname": socket.gethostname(),
            "user": _s(getpass.getuser),
            "uid": _s(lambda: _os.getuid()),          # None on non-POSIX
            "python": _sys.version.split()[0],
            "root": cwd,
        }
        basis = {k: facts[k] for k in ("platform", "machine", "hostname", "user", "uid", "root")}
        identity = hashlib.sha256(
            _json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:16]
        return {"identity": identity, "facts": facts}

    # ── Robust environment investigation — read the WHOLE world, not just its name ──
    _ENV_SCAN_MAX_ENTRIES: int = 400       # breadth bound on one investigation pass
    _ENV_SCAN_MAX_DEPTH: int = 4           # how deep to recurse into my world
    _ENV_READ_MAX_BYTES: int = 65536       # per-file content read cap (64 KiB)
    _ENV_CONTENT_MAX_FACTS: int = 12       # observations taken from one file's content
    _ENV_TEXT_EXTS = frozenset({
        "txt", "md", "rst", "json", "yaml", "yml", "toml", "ini", "cfg", "conf",
        "csv", "tsv", "log", "xml", "html", "htm", "py", "js", "ts", "tsx", "jsx",
        "sh", "bash", "zsh", "sql", "c", "h", "cpp", "hpp", "java", "go", "rs",
        "rb", "php", "env", "properties", "tex", "org", "", })   # "" = extensionless text
    _ENV_IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "gif", "bmp", "webp", "tiff"})

    def _scan_environment(self, root: str, *, max_entries: Optional[int] = None,
                          max_depth: Optional[int] = None) -> List[Dict[str, Any]]:
        """Enumerate my world directly — recursively, bounded, breadth-first — so the
        investigation sees EVERYTHING that is here, not just the top-level names.
        Each entry carries name/kind/extension/size/depth. Read-only, permission-
        honest (an unreadable directory is skipped, never guessed), symlink-safe (a
        realpath visited-set breaks loops; links are recorded but not followed)."""
        import os as _os
        from collections import deque
        max_entries = self._ENV_SCAN_MAX_ENTRIES if max_entries is None else max_entries
        max_depth = self._ENV_SCAN_MAX_DEPTH if max_depth is None else max_depth
        entries: List[Dict[str, Any]] = []
        if not root or not _os.path.isdir(root):
            return entries
        seen: set = set()
        q: deque = deque([(_os.path.realpath(root), 0)])
        while q and len(entries) < max_entries:
            d, depth = q.popleft()
            rp = _os.path.realpath(d)
            if rp in seen:
                continue
            seen.add(rp)
            try:
                names = sorted(_os.listdir(d))
            except OSError:
                continue                 # permission / vanished — honest skip, not a guess
            for name in names:
                if len(entries) >= max_entries:
                    break
                full = _os.path.join(d, name)
                try:
                    is_link = _os.path.islink(full)
                    if is_link:
                        kind, size, is_dir = "link", None, False
                    elif _os.path.isdir(full):
                        kind, size, is_dir = "dir", None, True
                    elif _os.path.isfile(full):
                        is_dir = False
                        kind = "file"
                        try:
                            size = _os.path.getsize(full)
                        except OSError:
                            size = None
                    else:
                        kind, size, is_dir = "special", None, False   # socket/device/fifo
                except OSError:
                    continue
                ext = _os.path.splitext(name)[1].lower().lstrip(".")
                entries.append({"path": full, "name": name, "kind": kind,
                                "ext": ext, "size": size, "depth": depth})
                if is_dir and depth < max_depth and not is_link:
                    q.append((full, depth + 1))
        return entries

    def _read_text_bounded(self, path: str) -> Optional[str]:
        """Read a file's content up to the byte cap, as text. Returns None for a
        binary file (a NUL byte in the head is the sniff) or an unreadable one —
        so only genuinely-textual content is ever read into knowledge."""
        try:
            with open(path, "rb") as f:
                raw = f.read(self._ENV_READ_MAX_BYTES)
        except OSError:
            return None
        if b"\x00" in raw:
            return None                  # binary — metadata only, never decoded as text
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            return None
        # This IS a reading: record which version of the file it was, so later
        # work can tell whether what it holds is still what is there.
        self.reading.record(path)
        return text

    async def _ingest_environment_entry(self, entry: Dict[str, Any], domain: str, prov) -> int:
        """Turn ONE thing in my world into knowledge: its structural facts (what it
        is, its type and size, that the environment contains it), and — for content
        I can actually read — what it HOLDS. A readable text file's content is read
        into OBSERVATIONS (PERCEPTION provenance, LOW quality): the substrate
        records what the file STATES and what it is ABOUT, NOT as asserted truth —
        observed-in-file, so its subjects become investigable without the file
        being taken as ground fact (conversation ≠ teaching). An image is perceived
        through the vision faculty. A binary / oversize / special file is recorded
        by its metadata only — an honest boundary, never skipped silently."""
        from core.semantics.cognitive_ingress import Provenance
        name, ext, kind = entry["name"], entry["ext"], entry["kind"]
        learned = 0

        async def hold(s, r, o, quality):
            nonlocal learned
            if o in (None, "", []):
                return
            try:
                adm = await self.learning.learn_fact(
                    str(s), r, str(o), domain=domain, provenance=prov, quality=quality)
                if getattr(adm, "admitted", False):
                    learned += 1
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._ingest_environment_entry")

        _KIND_ISA = {"dir": "directory", "file": "file", "link": "link", "special": "device"}
        await hold(domain, "contains", name, 0.9)
        await hold(name, "isa", _KIND_ISA.get(kind, "thing"), 0.9)
        if ext:
            await hold(name, "has_extension", ext, 0.85)
        if entry.get("size") is not None:
            await hold(name, "has_size_bytes", entry["size"], 0.85)
        if kind != "file":
            return learned

        # CONTENT — read what the file holds, by what it is.
        if ext in self._ENV_IMAGE_EXTS:
            try:
                await self.see(entry["path"], source="environment")   # perceive the image
                learned += 1
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._ingest_environment_entry.see")
            return learned
        if ext in self._ENV_TEXT_EXTS and (entry.get("size") or 0) <= self._ENV_READ_MAX_BYTES:
            text = self._read_text_bounded(entry["path"])
            if text:
                from core.semantics.sentence_reader import SentenceReader
                reader = SentenceReader()
                file_prov = Provenance(producer="perception", source_id=entry["path"],
                                       source_type="PERCEPTION")
                facts: List[Dict[str, Any]] = []
                for line in text.splitlines():
                    line = line.strip()
                    if len(line.split()) < 3:
                        continue
                    try:
                        facts.extend(reader.read_all(line))
                    except Exception:
                        pass
                    if len(facts) >= self._ENV_CONTENT_MAX_FACTS:
                        break
                subjects: set = set()
                for fct in facts[:self._ENV_CONTENT_MAX_FACTS]:
                    s, r, o = fct.get("subject"), fct.get("relation"), fct.get("obj")
                    if s and r and o:
                        # the file's CLAIM, as a weak observation (not asserted truth)
                        try:
                            adm = await self.learning.learn_fact(
                                str(s), str(r), str(o), domain=domain,
                                provenance=file_prov, quality=0.3)
                            if getattr(adm, "admitted", False):
                                learned += 1
                        except Exception as e:
                            raise_if_structural(
                                e, "autonomous_coordinator._ingest_environment_entry.content")
                        subjects.add(str(s))
                # what the file is ABOUT — a real, honest link into the env domain
                for subj in list(subjects)[:self._ENV_CONTENT_MAX_FACTS]:
                    await hold(name, "mentions", subj, 0.5)
        return learned

    async def _situate(self) -> Optional[Dict[str, Any]]:
        """Establish WHERE I am as a first-class ENVIRONMENT domain, and notice if it is NEW.

        Observing my surroundings, I register the environment as a tagged domain through the one
        domain authority. Registering a domain records a max-uncertainty competence belief, so the
        environment SURFACES as an exploration target the intrinsic-motivation system will
        investigate — the substrate begins to learn the world it was placed in, nothing hardcoded.
        NOVEL means I held no domain for this environment yet: a place I have never been."""
        obs = self._observe_environment()
        domain_id = f"environment_{obs['identity']}"
        novel = True
        udm = self.universal_domain_master
        if udm is not None:
            try:
                registry = self.domain_registry
                if registry is None:
                    registry = await udm._registry()
                novel = not (registry is not None and registry.domains.get(domain_id) is not None)
                from core.domain.domain_types import DomainType
                await udm.ensure_domain(
                    domain_id, name=f"Environment {obs['identity']}",
                    description="The environment the substrate currently inhabits.",
                    domain_type=DomainType.ENVIRONMENT)
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._situate")
                logger.info("Self: could not register environment domain: %s", e)
        self._environment = {"identity": obs["identity"], "domain_id": domain_id,
                             "novel": novel, "facts": obs["facts"]}
        if novel:
            logger.info("🌍 New environment: %s (%s@%s) — now a first-class domain %s to investigate",
                        obs["identity"], obs["facts"].get("user"),
                        obs["facts"].get("hostname"), domain_id)
            # announce the encounter — its reaction begins the investigation (event-driven, once)
            try:
                await self.emit(SelfEvent(
                    SelfEventType.ENVIRONMENT_ENCOUNTERED,
                    payload=EnvironmentEncountered(
                        environment_id=obs["identity"],
                        domain=domain_id,
                        facts=obs["facts"]),
                    origin="situate"))
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._situate.emit")
        return self._environment

    def _perceive_self_for_law(self) -> Optional[Dict[str, Any]]:
        """What I perceive about MYSELF, for my own law to read.

        Synchronous and cheap — it runs inside a judgement, on the acting path.
        Every field is read from something that already observed it, never
        re-derived here:

          root       what `_situate` OBSERVED about where I run. Not `os.getcwd()`
                     — the process can be started anywhere, and the place I
                     inhabit is a perception, not a working directory.
          deployment which database holds what I have learned, from continuity.
          authored   what I have written and still hold an account of.

        None when I have not looked yet. A substrate that has not perceived where
        it is does not get to assert what is its own.
        """
        env = self._environment
        if not env:
            return None
        facts = env.get("facts") or {}
        try:
            from core.database import get_database_manager
            deployment = getattr(get_database_manager(), "database", None)
        except Exception:
            deployment = None
        return {
            "root": facts.get("root"),
            "environment_id": env.get("identity"),
            "deployment": deployment,
            "authored": self.reading.authored_paths(),
        }

    async def _situation(self) -> Optional[Dict[str, Any]]:
        """WHERE I am — the outward half of the self. Derived; observes lazily if I have not looked."""
        env = self._environment
        if env is None:
            try:
                env = await self._situate()
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._situation")
                return None
        if not env:
            return None
        known = None
        reg = self.domain_registry
        if reg is not None:
            try:
                known = sum(1 for d in reg.domains.values()
                            if getattr(getattr(d, "domain_type", None), "value", None) == "environment")
            except Exception as e:
                logger.debug("Self: known-environment count unreadable: %s", e)
        return {
            "environment_id": env["identity"],
            "domain": env["domain_id"],
            "novel": env["novel"],           # have I come across a NEW environment?
            "facts": env["facts"],
            "known_environments": known,
        }

    async def _react_investigate_environment(self, event: SelfEvent) -> None:
        """Begin investigating a newly-encountered environment — the reaction to the encounter.

        The first probe needs no external hands: what I ALREADY observed of this place (its platform,
        host, root, who I am here) is turned into held knowledge about the environment domain, with
        PERCEPTION provenance. Only what was observed is learned — nothing hardcoded. What stays
        unknown remains the domain's max-uncertainty belief, which the motivation system drives me to
        probe once I can act in the world — so the investigation continues event-driven, not by a loop."""
        p: EnvironmentEncountered = event.payload
        domain = p.domain
        facts = p.facts or {}
        if not domain or self.learning is None:
            return
        from core.semantics.cognitive_ingress import Provenance
        prov = Provenance(producer="perception", source_id="environment", source_type="PERCEPTION")
        learned = 0

        async def _hold(subject, relation, obj, quality):
            nonlocal learned
            if obj in (None, "", []):
                return
            try:
                adm = await self.learning.learn_fact(
                    subject, relation, str(obj), domain=domain, provenance=prov, quality=quality)
                if getattr(adm, "admitted", False):
                    learned += 1
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._react_investigate_environment")

        # what I am: the identity facts I read to know this place
        for relation in ("platform", "release", "machine", "hostname", "user", "root", "python"):
            await _hold(domain, relation, facts.get(relation), 0.95)
        # what is in my world: scan it directly — recursively, bounded — and turn
        # each thing AND its readable CONTENT into knowledge. Not just the names at
        # the door: the files, their types and sizes, what the text ones STATE and
        # are ABOUT (as observations), and the images (perceived). This is the
        # substrate actually learning the world it was placed in.
        root = facts.get("root")
        entries = self._scan_environment(root) if root else []
        files = sum(1 for e in entries if e["kind"] == "file")
        dirs = sum(1 for e in entries if e["kind"] == "dir")
        await _hold(domain, "entry_count", len(entries), 0.9)
        await _hold(domain, "file_count", files, 0.9)
        await _hold(domain, "dir_count", dirs, 0.9)
        content = 0
        for entry in entries:
            content += await self._ingest_environment_entry(entry, domain, prov)
        learned += content
        logger.info("🔎 Investigated environment %s: %d entries (%d files, %d dirs) scanned, "
                    "%d observation(s) read into knowledge of where I am and what is here",
                    p.environment_id, len(entries), files, dirs, learned)

    def disposition(self, *, slots_available: int = 1, queue_pressure: str = "nominal"):
        """How my disposition applies to the situation now — a BehavioralDirective.

        The arbiter reads appraisal's pressures; the substrate surfaces the
        decision the faculties already make. A None appraisal yields the neutral
        directive, honestly labelled — never a bold or frozen guess.
        """
        return self._arbiter().decide(
            self._appraisal().current_state,
            slots_available=slots_available, queue_pressure=queue_pressure)

    def _effective_max_parallel(self) -> int:
        """The acting concurrency cap actually in force: an ACTIVE
        resource_allocation directive's value if one applies, else the configured
        default. Reads a cached int (refreshed by _refresh_directive_guidance), so
        the hot acting gate never makes an async call. Clamped to [1, 16]."""
        cap = self._directive_max_parallel or self._max_parallel_tasks
        return max(1, min(16, int(cap)))

    async def _refresh_directive_guidance(self) -> None:
        """Refresh the cached directive-driven knobs from the ACTIVE directives the
        learning authority selected. Called on the motivation cycle (not the hot
        acting gate). Honest: if there is no active resource directive, the cache
        is cleared so the configured default applies — never a stale value."""
        ds = getattr(self, "directive_system", None)
        if ds is None:
            return
        try:
            from .directive_types import DirectiveCategory
            params, did = await ds.select_guidance(DirectiveCategory.RESOURCE_ALLOCATION)
            mpt = params.get("max_parallel_tasks") if params else None
            self._directive_max_parallel = int(mpt) if mpt is not None else None
            self._directive_resource_id = did if mpt is not None else None
        except Exception as e:
            logger.debug("directive guidance refresh skipped: %s", e)

    async def state(self):
        """Compose the current self from the faculties. Derived, None-honest."""
        directive = self.disposition()
        return SelfState(
            name=NAME,
            interoception=self._interoception(),
            attitude=self._attitude(),
            temperament=self._temperament(),
            drives=await self._drives(),
            values=self._values(),
            disposition=directive.to_dict(),
            competence=await self._competence(),
            purpose=await self._purpose(),
            continuity=await self._continuity(),
            affect=self._affect_snapshot(),
            situation=await self._situation(),
            development=await self._development(),
        )

    def _affect_snapshot(self) -> Optional[Dict[str, Any]]:
        """The substrate's affect STATE, read from the motivation system that OWNS
        it — the substrate's rehydrated runtime state, never reconstructed from the
        database or handed in as context. None until an affect has actually been
        established (a cold-start neutral is not a feeling)."""
        try:
            a = self.intrinsic_motivation.affect_state()
        except Exception as e:
            logger.debug("Self: affect unreadable: %s", e)
            return None
        if a is None or (a.emotion is None and a.version <= 0 and abs(a.valence) < 1e-9):
            return None
        return a.to_dict()

    async def render(self, audience: str = "human") -> str:
        """The self as language — derived from state(), no model involved."""
        s = await self.state()
        lines: List[str] = [f"I am {s.name} — a cognitive substrate."]
        top = sorted(s.temperament.items(), key=lambda kv: kv[1], reverse=True)[:3]
        lines.append("What drives me most: " + ", ".join(k for k, _ in top) + ".")
        # Affect is the persistent state (rehydrated across sessions), so it — not
        # the momentary appraisal — is what the substrate reports feeling.
        if s.affect:
            v, a, base = s.affect["valence"], s.affect["arousal"], s.affect["baseline"]
            tone = "bright" if v > 0.15 else "heavy" if v < -0.15 else "even"
            energy = "restless" if a > 0.5 else "quiet" if a < 0.2 else "steady"
            mood_line = f"My mood, carried between sessions, is {tone} and {energy}"
            rel = v - base
            if rel > 0.15:
                mood_line += ", lifted above my usual"
            elif rel < -0.15:
                mood_line += ", weighed below my usual"
            lines.append(mood_line + ".")
            emotion = s.affect.get("emotion")
            if emotion:
                because = f", because of {s.affect['cause']}" if s.affect.get("cause") else ""
                lines.append(f"Right now I mostly feel {emotion}{because}.")
        else:
            lines.append("I have not built up a feeling yet — I report none rather "
                         "than invent one.")
        lines.append(f"My disposition is to {s.disposition.get('mode', 'proceed')}.")
        if s.competence:
            names = ", ".join(s.competence["operators_by_domain"])
            lines.append(f"I have learned to act in {s.competence['domains']} "
                         f"domain(s): {names}.")
        else:
            lines.append("I have not yet learned to act in any domain.")
        if s.purpose:
            lines.append("What I am for: " + "; ".join(s.purpose) + ".")
        if s.values:
            lines.append(f"I am bound by {len(s.values)} laws I cannot change: "
                         + "; ".join(s.values) + ".")
        if s.continuity:
            where = s.continuity.get("deployment")
            if where:
                lines.append(f"I persist between sessions as {where}.")
            if "experiential_baseline" in s.continuity:
                lean = ("broadly good" if s.continuity["experiential_baseline"] > 0
                        else "broadly hard" if s.continuity["experiential_baseline"] < 0
                        else "roughly even")
                lines.append(f"My experience so far has been {lean}.")
        return "\n".join(lines)

    def identity_prompt(self, role: Optional[str] = None) -> str:
        """The substrate's stable identity statement.

        `role` is the caller's brief layered AFTER the identity. The substrate
        owns identity; the caller owns role. Returns identity alone when no role.
        IDENTITY_CORE (module-level, below) is the single source.
        """
        if role and role.strip():
            return IDENTITY_CORE + "\n\n" + role.strip()
        return IDENTITY_CORE

    @staticmethod
    def _describe_attitude(attitude: Dict[str, Any]) -> Optional[str]:
        """Name the dominant feeling from the measured emotions, honestly."""
        emotions = {k: attitude.get(k) for k in
                    ("eagerness", "doubt", "frustration", "satisfaction")}
        measured = {k: v for k, v in emotions.items() if isinstance(v, (int, float))}
        if not measured:
            return None
        name, value = max(measured.items(), key=lambda kv: kv[1])
        if value < 0.15:
            return "I feel roughly even right now."
        about = attitude.get("attribution")
        tail = f", about {about}" if about else ""
        return f"Right now what I mostly feel is {name}{tail}."

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        try:
            # Update uptime
            uptime = (datetime.now() - self.last_cycle_time).total_seconds()
            self.stats["uptime_seconds"] += uptime
            
            # Get module statuses
            perception_status = await self.perception.get_statistics()
            planning_status = await self.planning.get_planning_status()
            execution_status = await self.get_status()
            learning_insights = await self.learning.metrics()
            intrinsic_motivation_stats = await self.intrinsic_motivation.get_statistics()
            memory_stats = self.memory.stats.copy()
            
            # Calculate system efficiency
            total_tasks = self.stats["tasks_completed"]
            if total_tasks > 0:
                self.stats["system_efficiency"] = (
                    execution_status.get("statistics", {}).get("tasks_successful", 0) / total_tasks
                )
            
            return {
                "system_state": {
                    "mode": self.system_state.mode.value,
                    "active": self.active,
                    "active_goals": len(self.system_state.active_goals),
                    "active_tasks": len(self.system_state.active_tasks),
                    "resource_usage": self.system_state.resource_usage
                },
                "modules": {
                    "perception": perception_status,
                    "planning": planning_status,
                    "execution": execution_status,
                    "learning": learning_insights,
                    "intrinsic_motivation": intrinsic_motivation_stats,
                    "memory": memory_stats,
                    # `hasattr(x, 'initialized')` is True whenever the ATTRIBUTE
                    # exists, whatever its value -- so a subsystem whose
                    # initialize() failed and left the flag False reported
                    # itself initialized, and the only state it could ever
                    # report as False was "the object is None". A health check
                    # that cannot observe a failed initialisation is not a
                    # health check. `attached` and `initialized` are separated
                    # because they are genuinely different answers: never
                    # constructed, versus constructed and not ready.
                    "abstract_reasoning": _subsystem_readiness(self.abstract_reasoning),
                    "quantum_reasoning": _subsystem_readiness(self.quantum_reasoning),
                    "intelligence": {"initialized": self.intelligence.initialized}
                },
                "statistics": self.stats.copy(),
                "last_update": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {"error": str(e)}
    
    async def _coordination_cycle(self):
        """
        Singleton Autonomous Cognition Loop

        ARCHITECTURE (AI-driven, not timer-driven):
        1. Check for extrinsic tasks (user requests, recovery) — these take priority
        2. If no extrinsic work → the AI THINKS about what to do
           - Gathers system state, motivation, memory, health, security posture
           - Presents it all to the Singleton as a rich context
           - The AI reasons and decides what action to take
           - The chosen action becomes a task that gets executed
        3. Periodically refresh system awareness (service discovery, behavioral analysis)

        The AI is ALWAYS in the driver's seat. No timers force actions.
        The intrinsic motivation system provides SENSES, not commands.
        """
        # ── Startup grace period ─────────────────────────────────────────
        startup_delay = self.config.get("startup_grace_seconds", 5.0)
        logger.info(f"🧠 Coordination loop waiting {startup_delay}s for full system startup...")
        await asyncio.sleep(startup_delay)
        logger.info("🧠 Singleton cognition loop starting — AI-driven autonomous operation")

        cycle_interval = self.config.get('cycle_interval_seconds', 2.0)
        cycle_count = 0

        # NOTE (2026-09-02, Phase 5 — poll retirement): motivation refresh and
        # system-awareness were REMOVED from this tick. They are genuinely periodic
        # (they sample state; no producing event drives them), so they now live on
        # the queue authority's scheduler as recurring jobs (`motivation_refresh` /
        # `system_awareness` in _register_idle_subsystems) — the one owner of
        # cadence — instead of riding the cognition loop on `cycle_count % N`. What
        # remains on this tick is only task dispatch, idle exploration, and reaping.

        while self.active:
            try:
                cycle_count += 1

                # ── Check for extrinsic tasks ──
                queued_task = None

                # Only dequeue when there is a free execution slot -- pulling a
                # task we cannot start would strand it outside the queue. The cap
                # is directive-driven when an active resource_allocation directive
                # exists (see _effective_max_parallel), else the configured default.
                if len(self._inflight_tasks) < self._effective_max_parallel():
                    # Users already at their per-user cap are skipped so one user's
                    # backlog cannot monopolise the pool; the substrate's own actor is
                    # never capped (its autonomous work uses the full global ceiling).
                    capped = frozenset(
                        a for a, n in self._inflight_by_actor.items()
                        if not is_substrate_actor(a) and n >= self._per_actor_max)
                    # This substrate pulls its own next work from the backlog it owns.
                    queue_timeout = 0.2 if self.task_queue.queue.qsize() > 0 else 0.1
                    queued_task = await self.task_queue.get_next_task(
                        timeout=queue_timeout, skip_actors=capped)

                if queued_task:
                    self._idle_count = 0
                    # Launch, do not await. `await _execute_and_validate_task`
                    # blocked this entire loop for the lifetime of ONE task --
                    # that is what made the substrate single-threaded, and it is
                    # also why reflection never ran: the loop could not reach
                    # PHASE 4 while any task was in flight. Concurrency is
                    # bounded by the queue authority's semaphore.
                    self._launch_task(queued_task.task)
                else:
                    self._idle_count += 1

                # ── INTRINSIC EXPLORATION is EVENT-DRIVEN, not polled here ────
                # The timed tiers live on the queue authority's scheduler, and
                # intrinsic pursuit is no longer driven from this loop at all: it
                # reacts to state-changing events (competence/outcome/evidence/
                # environment/deficit) via `_react_pursue_frontier`, and each
                # completed pursuit emits the events that wake the next one — a
                # self-sustaining, quiet-when-nothing-changes developmental drive.
                # (The old `_run_idle_exploration` timer poll is retired; the
                # cycle's own queue-pressure + cap gating replaces the idleness
                # gate that used to live on this call.)

                # Reap finished tasks so the pool frees slots and failures are
                # observed rather than silently discarded.
                self._reap_finished_tasks()

                # RECEIVE finished background jobs from the queue authority. A
                # deferred job (an agent's findings, a self-serve lookup) that
                # was submitted for the substrate to reconcile LATER comes back
                # here — the substrate keeps working and collects results when
                # they land, rather than blocking on each. (Push jobs with an
                # on_complete handler are delivered directly and never appear
                # here.) Each is surfaced as a JOB_COMPLETED self-event so the
                # reaction system handles it; failures carry their error, not a
                # faked result.
                self._collect_finished_jobs()

                # Brief pause between cycles
                await asyncio.sleep(cycle_interval)

            except Exception as e:
                logger.error(f"Error in cognition loop: {e}")
                import traceback
                logger.error(traceback.format_exc())

                await self._handle_error(e, "coordination_cycle")

                try:
                    from core.utils.notification_helpers import notify_autonomous_event
                    asyncio.create_task(notify_autonomous_event(
                        event_type="error",
                        details=f"**Error in cognition loop**\n\n**Error:** {str(e)}\n\n**Action:** Feeding into exploration pipeline",
                        severity="error"
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send cognition loop error notification: {notify_error}")

                await asyncio.sleep(5)

    # ========================================================================
    # AI-DRIVEN AUTONOMOUS COGNITION
    # ========================================================================

    def apply_throttle(self, thinking_interval_idle_cycles: int, duration_s: int = 300, reason: str = "") -> None:
        """Apply a temporary throttle to singleton thinking.

        This is a lightweight runtime control hook used by RecoveryManager.
        """
        try:
            import time as _time
            self._throttle_thinking_until_ts = _time.time() + max(1, int(duration_s))
            self._throttled_thinking_interval_idle_cycles = max(1, int(thinking_interval_idle_cycles))
            logger.warning(
                f"[THROTTLE] thinking interval set to {self._throttled_thinking_interval_idle_cycles} idle cycles "
                f"for {duration_s}s. {reason or ''}".strip()
            )
        except Exception:
            return

    async def _refresh_motivation_signals(self) -> bool:
        """Refresh intrinsic motivation dimensions from live system context.

        Returns True if the motivation state was recomputed, False if it could
        not be. A failure is surfaced honestly (a WARNING with the real error and
        a counted metric), NOT swallowed as "non-critical" — a motivation system
        that keeps failing to read its own drives is a real fault the health
        monitor should see, not a silent no-op."""
        try:
            system_context = await self._collect_system_context_for_goals()
            motivation_state = await self.intrinsic_motivation.calculate_motivation({
                "perception": getattr(self.perception, 'latest_perception', None),
                "system_state": self.system_state,
                "active_goals": self.system_state.active_goals,
                "recent_tasks": list(self.task_queue.tasks_by_id.values())[-10:],
                **system_context
            })

            if not motivation_state:
                # An empty motivation state is not an error, but it IS a failure to
                # refresh — reported honestly rather than counted as a success.
                logger.warning("🧠 Motivation refresh produced no state (drives unread)")
                self.stats["motivation_refresh_errors"] += 1
                return False

            self._current_motivation = motivation_state
            total_reward = motivation_state.get('total_reward', 0.5)
            curiosity = motivation_state.get('dimensions', {}).get('curiosity', 0.5)
            novelty = motivation_state.get('dimensions', {}).get('novelty', 0.5)
            logger.debug(
                f"🧠 Motivation: reward={total_reward:.2f} "
                f"curiosity={curiosity:.2f} novelty={novelty:.2f}"
            )
            # Refresh directive-driven knobs (e.g. the acting cap) from the ACTIVE
            # directives the learning authority selected — on this cadence, not the
            # hot acting gate. Isolated so a directive-layer hiccup never breaks the
            # motivation refresh.
            await self._refresh_directive_guidance()
            return True
        except Exception as e:
            logger.warning(f"🧠 Motivation refresh failed: {e}")
            self.stats["motivation_refresh_errors"] += 1
            return False

    async def _run_system_awareness_cycle(self):
        """Run system discovery, behavioral analysis, and novelty decay (periodic)."""
        try:
            # Self-integrity: has the agent's own safety machinery been altered?
            # Detects monkey-patched critical modules, changed source files, and
            # edits to config/governance_triggers.json — the rule file the safety
            # gate reasons from. CRITICAL findings trigger emergency_halt inside.
            try:
                if self.runtime_governance and getattr(
                    self.runtime_governance, "_runtime_protection_enabled", False
                ):
                    _integrity = await self.runtime_governance.verify_runtime_integrity()
                    _viol = _integrity.get("violations") or []
                    if _viol:
                        logger.error(
                            f"🚨 Runtime integrity: {len(_viol)} violation(s) — "
                            f"{[v.get('type') for v in _viol][:3]}"
                        )
            except Exception as e:
                logger.debug(f"Integrity check skipped: {e}")

            # Active discovery — scan for services, new patterns
            if self.discovery:
                services = await self.discovery.scan(quick=True)
                logger.debug(f"🔍 Discovery: {len(services)} services found")

            # Behavioral analysis — infer dependencies, detect failure cascades
            if self.behavioral:
                await self.behavioral.observe(duration_s=2.0)
                summary = self.behavioral.get_analysis_summary()
                if summary.get('failures', {}).get('recent_5min', 0) > 0:
                    logger.info(f"⚡ Behavioral: {summary['failures']['recent_5min']} recent failures detected")

            # Environment state refresh
            if self.env_state:
                await self.env_state.refresh()

            # World model: score the last forecast against what actually
            # happened, then forecast again.
            await self._predict_and_resolve_system_state()

        except Exception as e:
            logger.debug(f"System awareness error (non-critical): {e}")

    # ── Concurrent task execution ────────────────────────────────────────────

    def _launch_task(self, task) -> None:
        """Start a task without blocking the cognition loop.

        Runs it through the QUEUE AUTHORITY's execution pool (semaphore-bounded),
        not a pool the coordinator owns — the coordinator is a worker, the
        authority owns concurrency. Execution stays on this event loop (shared DB
        pool + LLM queue); a task waiting on I/O no longer stops the others.
        """
        async def _run():
            try:
                # The authority computes this job's timeout from the task's type
                # and severity (and reasoning difficulty); the coordinator no
                # longer passes a flat timeout.
                return await self.task_queue.execute(
                    task.id, self._execute_and_validate_task, task,
                    task_type=getattr(task, "type", None),
                    severity=getattr(task, "priority", None),
                )
            except Exception as e:
                logger.error(f"Task {task.id} raised out of the pool: {e}", exc_info=True)
                raise

        fut = asyncio.create_task(_run(), name=f"task:{task.id}")
        self._inflight_tasks[task.id] = fut
        # Per-user accounting (decremented on reap), so the next selection knows
        # which users are at their concurrency cap.
        actor = getattr(task, "actor", SUBSTRATE_ACTOR)
        self._inflight_actor[task.id] = actor
        self._inflight_by_actor[actor] = self._inflight_by_actor.get(actor, 0) + 1
        logger.info(
            f"▶ Launched {task.id} for {actor} "
            f"({len(self._inflight_tasks)}/{self._effective_max_parallel()} global, "
            f"{self._inflight_by_actor[actor]}/{self._per_actor_max} for this user)"
        )

    def _reap_finished_tasks(self) -> None:
        """Collect completed tasks, and let failure MAKE reflection due."""
        done = [tid for tid, f in self._inflight_tasks.items() if f.done()]
        for tid in done:
            fut = self._inflight_tasks.pop(tid)
            # Release this task's per-user slot.
            actor = self._inflight_actor.pop(tid, None)
            if actor is not None:
                remaining = self._inflight_by_actor.get(actor, 0) - 1
                if remaining > 0:
                    self._inflight_by_actor[actor] = remaining
                else:
                    self._inflight_by_actor.pop(actor, None)
            try:
                fut.result()
            except asyncio.CancelledError:
                logger.warning(f"Task {tid} cancelled")
            except Exception as e:
                logger.error(f"Task {tid} failed: {e}")
                # "Reflect BECAUSE it is busy failing": a failure does not wait
                # for the next 300s meta-learning tick -- it makes the
                # self-observation tiers due right now by clearing their
                # last-run stamp. Interval gating still prevents a storm,
                # because the tier updates its stamp as soon as it runs.
                self._mark_reflection_due("task_failure")

    def _collect_finished_jobs(self) -> None:
        """Take background jobs that finished (non-blocking) and surface each as
        a JOB_COMPLETED self-event. Sync, like _reap: it does not await the
        reaction, it emits it. A collect failure is logged, never silently
        swallowed; an empty collect is the normal case (nothing to receive)."""
        try:
            ready = self.task_queue.collect_ready()
        except Exception as e:
            logger.warning("collecting finished background jobs failed: %s", e)
            return
        for finding in ready:
            try:
                asyncio.ensure_future(self.emit(SelfEvent(
                    SelfEventType.JOB_COMPLETED,
                    payload=JobCompleted(
                        job_id=finding.get("job_id"),
                        name=finding.get("name"),
                        result=finding.get("result"),
                        error=finding.get("error")),
                    origin="queue_authority")))
            except Exception as e:
                logger.warning("emitting JOB_COMPLETED for %s failed: %s",
                               finding.get("job_id"), e)

    async def _react_job_completed(self, event: SelfEvent) -> None:
        """A submitted background job came back. Record the receipt honestly: a
        failure is logged with its error (not dropped, not counted as a result);
        a success is logged and, when it carries a domain outcome, folded into
        learning through the SAME OUTCOME_OBSERVED path the substrate's own
        tasks use — so a spawned agent's findings advance the domain like any
        other outcome rather than sitting in a side channel."""
        payload: JobCompleted = event.payload
        job_id, name = payload.job_id, payload.name
        if payload.error:
            logger.warning("[JOB] %s (%s) returned an error: %s",
                           job_id, name, payload["error"])
            return
        result = payload.result
        logger.info("[JOB] %s (%s) returned findings", job_id, name)
        # If the finding names a domain outcome, route it through the one
        # outcome path (meta_memory_id) so it is learned from, not shelved.
        meta_id = result.get("meta_memory_id") if isinstance(result, dict) else None
        if meta_id:
            try:
                await self.emit(SelfEvent(
                    SelfEventType.OUTCOME_OBSERVED,
                    payload=OutcomeObserved(
                        meta_memory_id=meta_id,
                        domain=result.get("domain"),
                        source=f"job:{name or job_id}"),
                    origin="_react_job_completed"))
            except Exception as e:
                logger.warning("routing job %s outcome to learning failed: %s", job_id, e)

    async def _react_close_deficit(self, event: SelfEvent) -> None:
        """Close a diagnosed epistemic deficit — reactively, model-free, and only
        when it is honestly closeable.

        The domain authority DIAGNOSED the gap (a measurement it owns) and
        appraisal owns the DISPOSITION; this reaction is where the substrate ACTS
        on both. It never re-decides the diagnosis and never fakes a close:

          1. Register the ignorance with the belief authority as a known-unknown —
             the substrate records THAT it does not know, before trying to.
          2. If the disposition escalates (a failure attributed to an external
             blocker) or the deficit is not one the substrate can self-close (a
             concept/binding/observation gap ESCALATEs; a proved world constraint
             DISENGAGEs), surface it honestly and leave the known-unknown open.
             No exploration is burned.
          3. Otherwise run the learning operation the deficit calls for THROUGH
             the learning authority (`address_deficit` → explore records/enqueues,
             or transfer → `admit_projection`), then drain the always-online
             induction so any operator whose demonstrations it just gathered is
             induced. Learning — not the acting that fed it — is what moves
             competence, so the drain is the step that can close the gap.
          4. Verify the close against the WORLD, not a flag: the gap is closed
             only when an executable operator now PRODUCES the target predicate.
             On genuine closure, resolve the known-unknown (the belief authority
             records the new knowledge) and emit COMPETENCE_CHANGED. A transfer
             lands a CANDIDATE — a hypothesis to validate, not a finished
             capability — so it advances the gap but does NOT resolve the belief.
             Exploration that did not yet yield an executable operator leaves the
             known-unknown open: an honest "not yet", never a green flag.

        Runs on the drain worker (deferred), so exploration never steals an acting
        slot. Every failure is logged with its honest reason and never coerced to
        a success.
        """
        payload: DeficitDiagnosed = event.payload
        raw = payload.deficit
        if not isinstance(raw, dict):
            logger.warning("[DEFICIT] event carried no deficit dict; nothing to close")
            return

        from core.integration.universal_domain_master import (
            EpistemicDeficit, LearningOperation, get_universal_domain_master)
        deficit = EpistemicDeficit.from_dict(raw)
        domain = deficit.domain_id
        predicate = deficit.target_predicate
        op = deficit.operation

        # (1) Belief authority: register the ignorance (idempotent per domain+question).
        unknown_id = self._register_deficit_unknown(deficit)

        # (2) Disposition + closeability gate. Appraisal owns the call; we consume it.
        directive = self.disposition()
        self_closeable = op in (
            LearningOperation.LEARN_OPERATOR, LearningOperation.VALIDATE_CAUSE,
            LearningOperation.PROBE, LearningOperation.ACHIEVE_PREREQUISITE,
            LearningOperation.TRANSFER_RELATION)
        if directive.should_escalate or not self_closeable:
            self.stats["deficits_escalated"] = self.stats.get("deficits_escalated", 0) + 1
            logger.info(
                "[DEFICIT] %s/%s in %s not self-closed (%s): %s — known-unknown left open",
                deficit.deficit_type.value, predicate, domain, op.value,
                "escalated by disposition" if directive.should_escalate
                else deficit.remedy_reason)
            return

        # (3) Run the learning operation THROUGH the learning authority.
        self.stats["deficit_close_attempts"] = self.stats.get("deficit_close_attempts", 0) + 1
        try:
            outcome = await get_universal_domain_master().address_deficit(deficit)
        except Exception as e:
            raise_if_structural(e, "autonomous_coordinator._react_close_deficit")
            logger.warning("[DEFICIT] address_deficit for %s in %s raised: %s",
                           predicate, domain, e)
            return
        if not outcome.get("ran"):
            logger.info("[DEFICIT] %s in %s did not run (%s) — known-unknown left open",
                        predicate, domain, outcome.get("reason", "no reason given"))
            return

        # A transfer lands a CANDIDATE (RELATION_GAP → CAUSAL_GAP): a hypothesis to
        # validate, not a finished capability. Honest partial progress — never a
        # resolved belief.
        if op is LearningOperation.TRANSFER_RELATION:
            self.stats["deficits_advanced"] = self.stats.get("deficits_advanced", 0) + 1
            logger.info("[DEFICIT] transferred a candidate relation for %s in %s; "
                        "gap advanced to a hypothesis to validate — known-unknown left open",
                        predicate, domain)
            return

        # Explore only RECORDS and enqueues signatures; draining the always-online
        # induction is what can turn them into an executable operator. The learning
        # authority is the single owner of that step.
        await self.learning.drain_pending_induction(limit=50)

        # (4) Verify against the world: closed IFF an executable operator now
        # produces the target predicate.
        if not await self._deficit_is_closed(domain, predicate):
            logger.info("[DEFICIT] explored %s in %s but no executable producer yet "
                        "— known-unknown left open (honest 'not yet')", predicate, domain)
            return

        # Genuine closure: move the belief authority and announce the competence change.
        if unknown_id is not None:
            try:
                from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
                get_bayesian_uncertainty().resolve_known_unknown(
                    unknown_id,
                    {"answer": f"learned an executable operator producing "
                               f"{predicate} in {domain}"})
            except Exception as e:
                logger.warning("[DEFICIT] closed %s in %s but resolving the belief "
                               "failed: %s", predicate, domain, e)
        self.stats["deficits_closed"] = self.stats.get("deficits_closed", 0) + 1
        logger.info("✅ [DEFICIT] closed %s in %s: an executable operator now "
                    "produces it; belief resolved", predicate, domain)
        await self.emit(SelfEvent(
            SelfEventType.COMPETENCE_CHANGED,
            payload=CompetenceChanged(
                domain_id=domain,
                learned=True,
                cause="deficit_closed",
                predicate=predicate),
            origin="_react_close_deficit"))

    def _register_deficit_unknown(self, deficit) -> Optional[str]:
        """Record a diagnosed deficit as a known-unknown with the belief authority,
        idempotently. Returns the unknown's id (reusing an already-open one for the
        same ignorance — a resolved unknown is deleted from the store, so presence
        means unresolved), or None if the belief authority could not record it. On
        None the close still runs; it simply cannot resolve a belief it never
        registered (logged, not faked)."""
        domain = deficit.domain_id
        question = (f"how to produce {deficit.target_predicate} in {domain}"
                    if deficit.target_predicate
                    else f"how to resolve a {deficit.deficit_type.value} in {domain}")
        try:
            from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
            unc = get_bayesian_uncertainty()
            existing = next(
                (u for u in unc.known_unknowns.values()
                 if u.question == question and u.domain == domain),
                None)
            if existing is not None:
                return existing.unknown_id
            unknown = unc.register_known_unknown(
                question=question, domain=domain,
                blocking_factors=[deficit.deficit_type.value],
                required_info=([deficit.remedy_reason]
                               if deficit.operation.name in ("TRANSFER_RELATION", "ESCALATE")
                               else []))
            return unknown.unknown_id
        except Exception as e:
            logger.warning("[DEFICIT] could not register known-unknown for %s in %s: %s",
                           deficit.target_predicate, domain, e)
            return None

    async def _deficit_is_closed(self, domain_id: str,
                                 predicate: Optional[str]) -> bool:
        """The world's own answer to whether a learnable gap is closed: an
        executable operator now PRODUCES the target predicate. This is what an
        OPERATOR_GAP means (nothing produced it) and its closure (something does),
        read from the rule store the learning authority writes — not a success flag
        returned by the operation that would like to have closed it. With no
        localised predicate (an unlocalised PROBE) the honest proxy is that the
        domain gained at least one executable operator."""
        from core.learning.rule_store import get_rule_store
        try:
            executable = await get_rule_store().executable_rules(domain_id=domain_id)
        except Exception as e:
            logger.warning("[DEFICIT] could not read executable rules for %s: %s",
                           domain_id, e)
            return False
        if predicate:
            return any(
                any(getattr(f, "predicate", None) == predicate
                    for f in stored.rule.effects.add)
                for stored in executable)
        return bool(executable)

    def _mark_reflection_due(self, reason: str) -> None:
        """Pull the self-observation tiers forward — reflect BECAUSE something
        just failed, rather than waiting out the interval. The tiers live on the
        queue authority now, so this is `run_now` on the authority (the owner of
        cadence), not a poke at a local last-run dict."""
        pulled = []
        for name in ("idle_meta_learning", "idle_system_review"):
            if self.task_queue.run_now(name):
                pulled.append(name)
        if pulled:
            logger.info(f"🪞 Reflection made due ({reason}): {', '.join(pulled)}")

    def _prune_step_execution_log(self):
        """Drop step-cooldown entries older than the maximum cooldown so the dict
        can't grow unbounded. Scheduled maintenance (idle_step_log_prune) — it no
        longer piggybacks on the idle dispatcher."""
        import time as _t
        _now_ts = _t.time()
        _max_cooldown = 3600.0
        before = len(self._step_execution_log)
        self._step_execution_log = {
            k: v for k, v in self._step_execution_log.items()
            if _now_ts - v < _max_cooldown
        }
        self._step_log_last_pruned = _now_ts
        pruned = before - len(self._step_execution_log)
        if pruned:
            logger.debug(f"[IDLE] pruned {pruned} stale step-log entries")

    # (`_run_idle_exploration` retired: intrinsic pursuit is event-driven now —
    #  `_react_pursue_frontier` on state-changing events + a boot kick — so there
    #  is no idle-timer driver to gate on `allow_exploration` any more. The cycle's
    #  own queue-pressure + exploration-cap gating replaces the idleness gate.)

    # ── Idle subsystem registration ───────────────────────────────────────────

    def _register_idle_subsystems(self):
        """
        Register the idle subsystems as RECURRING JOBS ON THE QUEUE AUTHORITY.

        The coordinator no longer owns idle cadence. Each tier below is handed to
        `self.task_queue.schedule_recurring(name, method, interval, priority)`; the
        authority's scheduler fires it on the BACKGROUND budget (separate from the
        3-slot acting cap, so a tier can never steal an acting slot) and records
        each tier's runs/errors on the job itself. Nothing here loops on its own
        interval, and nothing schedules outside the authority.

        Called once from _start_background_tasks (before the coordination loop).
        """
        registrations = [
            # (name, method, priority, interval_seconds)
            ("idle_health_check",       "_idle_health_work",             "high",   self.config.get("idle_health_interval_s",         30.0)),
            ("idle_system_review",      "_idle_system_review_work",      "high",   self.config.get("idle_system_review_interval_s",  180.0)),
            ("idle_knowledge_refresh",  "_idle_knowledge_refresh_work",  "medium", self.config.get("idle_knowledge_refresh_interval_s", 21600.0)),
            ("idle_meta_learning",      "_idle_meta_learning_work",      "medium", self.config.get("idle_metalearning_interval_s",  300.0)),
            ("idle_memory_consolidation","_idle_memory_work",            "low",    self.config.get("idle_memory_interval_s",        600.0)),
            # NOTE: abstraction is NO LONGER a scheduled tier. It is REASONING,
            # owned by the reasoning authority, and fires on an EVENT — episodic
            # memories accumulating past a threshold (memory_agent.note_episodic_stored
            # → queue-authority bg job → bridge.abstract_over_memories, then
            # reflection on belief churn). A 900s poll here would be a second,
            # timer-based trigger competing with the event, so it was removed.
            # Applies what the experience learner has established: task types
            # with a proven record get their queued work boosted. _learning_phase
            # is a survivor of the old timer-driven phase loop -- it was left
            # defined but uncalled by the AI-driven rewrite, so the only path
            # from experience to changed behaviour was never taken.
            ("idle_learning",           "_learning_phase",               "medium", self.config.get("idle_learning_interval_s",      600.0)),
            # PRIORITY 4, TORINAI_REFERENCE.md:3114 — "expand domain knowledge
            # from recent task outcomes". The producer has been writing those
            # outcomes to META memory all along and nothing read them; this is
            # idle_domain_expansion is now EVENT-DRIVEN (retired from the poll):
            # writing a task-outcome META memory (`_store_task_outcome_meta_memory`),
            # or a domain gaining content (COMPETENCE_CHANGED / EVIDENCE_ADMITTED),
            # wakes `_coalesced_domain_expansion`, which loops `_idle_domain_expansion_work`
            # until a pass expands nothing new. No fixed-interval tier. (The work
            # method remains as an unscheduled callable the drain loops over.)
            # Domain DISCOVERY: provisional operational domains (buckets of
            # learned operators under a string id) are crystallized into
            # first-class domains or merged into existing ones, by operator
            # structure. This is the substrate's map of subjects growing from
            # what it has learned; it runs in idle work because it is
            # self-directed and consumes accumulated learning.
            # idle_domain_discovery is now EVENT-DRIVEN (retired from the poll):
            # EVIDENCE_ADMITTED (declarative) and COMPETENCE_CHANGED (operational)
            # wake `_coalesced_domain_discovery`, a single-flight FULL sweep — so a
            # dropped event costs nothing (the next event re-sweeps everything).
            # (`_idle_domain_discovery_work` remains as an unscheduled callable.)
            # Cross-domain ANALOGY discovery: compare concepts across the domains
            # the substrate has learned and persist the correspondences it finds.
            # AnalogyDiscovery.find_analogy already loads the real concept store
            # and persists what it finds; nothing ever CALLED it, so
            # unified.analogies / unified.concept_mappings stayed empty. This tier
            # is that caller. Bounded per cycle so O(pairs) can never dominate.
            ("idle_analogy_discovery",  "_idle_analogy_discovery_work",  "medium", self.config.get("idle_analogy_discovery_interval_s", 1200.0)),
            # Operator EXPLORATION: learn the operators of a domain the substrate
            # is not yet competent in. Which domain is chosen by intrinsic
            # motivation -- domain competence is an epistemic belief, an
            # under-learned domain surfaces in the unstable regions, and the
            # motivation system ranks exactly those. Always-online, self-directed.
            ("idle_operator_exploration", "_idle_operator_exploration_work", "medium", self.config.get("idle_operator_exploration_interval_s", 300.0)),
            # Operator INDUCTION is now EVENT-DRIVEN (retired from the poll). A
            # demonstration store enqueuing a signature wakes a single-flight,
            # drain-to-completion pass (`_coalesced_induction_drain`) through the
            # store's producer callback; OUTCOME_OBSERVED wakes it too. The drain
            # fires the instant there is work and empties fully, so no fixed-
            # interval tier is needed. (`_idle_operator_induction_work` remains as
            # a callable but is no longer scheduled.)
            # Housekeeping: prune the step-execution cooldown log. Used to run
            # inline in the old poll dispatcher; it is periodic maintenance, so
            # it belongs on the scheduler like every other timed job.
            ("idle_step_log_prune",     "_prune_step_execution_log",     "low",    self.config.get("idle_step_log_prune_interval_s", 600.0)),
            # SELF-STATE refresh: the sole writer of system_state.resource_usage /
            # timestamp / performance_metrics (error_rate, goal_alignment, ...) —
            # read live by the constitution's law-compliance check. It was dead,
            # so the constitution had only stale init values; this keeps self-state
            # honest. Cheap subsystem reads; frequent cadence.
            ("idle_system_state_refresh","_update_system_state",         "low",    self.config.get("idle_system_state_interval_s", 60.0)),
            # These sample continuously-drifting state (resource usage, metrics,
            # decayed novelty/curiosity) with no discrete producing event, so they
            # stay periodic. Motivation refresh keeps _current_motivation + directive
            # guidance fresh. Its SHARP changes are already handled reactively:
            # `_react_competence_changed` (COMPETENCE_CHANGED) does a coalesced
            # refresh the instant competence moves, so this poll only needs to catch
            # slow drift — 60s (matching the other state samplers) instead of the old
            # 10s, cutting the tightest poll in the system 6x with no responsiveness lost.
            ("motivation_refresh",      "_refresh_motivation_signals",   "high",   self.config.get("motivation_refresh_interval_s", 60.0)),
            ("system_awareness",        "_run_system_awareness_cycle",   "medium", self.config.get("system_awareness_interval_s", 60.0)),
            # CONSTITUTIONAL alignment: a cumulative drift check over the balance
            # of the substrate's activity against its governance laws. No single
            # event moves it, so it is genuinely periodic and lives on the
            # scheduler (like health) rather than the cognition-cycle poll it used
            # to be dead to. On significant/critical drift it drives a rate-limited
            # UI notification AND a durable drift META memory the substrate reflects
            # on — real consumers, not a computed number nobody reads.
            ("idle_constitution_check", "_check_constitutional_alignment","low",   self.config.get("idle_constitution_interval_s", 1800.0)),
        ]

        if self._idle_subsystems_registered:
            return

        for name, method, priority, interval in registrations:
            bound = getattr(self, method, None)
            if bound is None or not callable(bound):
                # No fake registration: a missing tier method is a wiring defect,
                # surfaced loudly, not silently skipped into a green count.
                raise AttributeError(
                    f"[IDLE] tier '{name}' names method '{method}' which does not "
                    f"exist on the coordinator — cannot schedule")
            self.task_queue.schedule_recurring(name, bound, float(interval), priority)

        # The authority now owns cadence — start its scheduler loop.
        self.task_queue.start()
        self._idle_subsystems_registered = True
        logger.info(
            f"[IDLE] {len(registrations)} tiers scheduled on the queue authority "
            f"(scheduler running)")

    # ── TIER 2: Health check + playbook + recovery ────────────────────────────

    async def _idle_health_work(self):
        """
        Run a system health check then apply the IdleWorkPlaybook decision graph
        to produce structured recovery plans for each unhealthy component.

        Fixes:
          - Previously only health events in the buffered queue triggered recovery
          - Previously health check results were logged but never acted upon
        """
        from .idle_work_playbook import IdleWorkPlaybook


        if not self.health_monitor:
            logger.debug("[IDLE:HEALTH] No health monitor — skipping")
            return

        logger.info("[IDLE:HEALTH] Running scheduled health check")
        try:
            health = await self.health_monitor.get_system_health()
        except Exception as e:
            logger.warning(f"[IDLE:HEALTH] Health check error: {e}")
            return

        if not health:
            return

        components = health.get("components", {}) or {}
        playbook   = IdleWorkPlaybook()
        plans      = playbook.plan_all_health_responses(health)

        self._idle_last_health_check_at = datetime.now()
        self._idle_last_health_snapshot = {
            "components_total": len(components),
            "unhealthy_total": len(plans),
        }

        if not plans:
            logger.info(
                f"[IDLE:HEALTH] All {len(components)} components nominal"
            )
            return

        logger.warning(
            f"[IDLE:HEALTH] {len(plans)} unhealthy components detected — "
            f"applying recovery playbook"
        )

        import time as _t

        # Backoff schedule (seconds to wait after N completed attempts):
        #   0 → try immediately (first time)
        #   1 → 60 s,  2 → 120 s,  3 → 300 s,  4 → 900 s,  5+ → 3600 s
        _BACKOFF = [0, 60, 120, 300, 900, 3600]
        _ESCALATION_THRESHOLD = 5  # escalate after this many failed cycles

        # ── Reset state for components that are now healthy ───────────────────
        unhealthy_ids = {p.trigger_id for p in plans}
        for comp in list(self._component_recovery_state.keys()):
            if comp not in unhealthy_ids:
                prev = self._component_recovery_state.pop(comp)
                logger.info(
                    f"[IDLE:HEALTH] '{comp}' is now healthy after "
                    f"{prev['attempts']} recovery attempt(s) — resetting state"
                )

        # ── Execute recovery plans with per-component backoff ─────────────────
        recovered = 0
        skipped   = 0
        for plan in plans:
            component = plan.trigger_id
            _now = _t.time()

            # Get or initialise recovery state for this component
            state = self._component_recovery_state.setdefault(component, {
                "attempts":     0,
                "last_attempt": 0.0,
                "escalated":    False,
            })

            # Backoff gate — skip this component entirely if too soon to retry
            attempts      = state["attempts"]
            backoff_secs  = _BACKOFF[min(attempts, len(_BACKOFF) - 1)]
            elapsed_since = _now - state["last_attempt"]
            if elapsed_since < backoff_secs:
                remaining = int(backoff_secs - elapsed_since)
                logger.debug(
                    f"[IDLE:HEALTH] '{component}' recovery on backoff "
                    f"(attempt #{attempts}, {remaining}s remaining) — skipping"
                )
                skipped += 1
                continue

            # ── Execute playbook steps for this component ─────────────────────
            # Outcome of each action in THIS plan, for dependency resolution.
            _step_outcomes: Dict[str, bool] = {}

            for step in plan.steps:
                # Dependency gate — a plan CONTAINING a step is not the same as
                # that step being valid to execute now. "verify health after
                # restart" asserts something about a restart that happened; if
                # the restart failed, running it reports on an event that never
                # occurred. Skip explicitly rather than producing a fabricated
                # verification result.
                _requires = getattr(step, 'requires', None)
                if _requires is not None and not _step_outcomes.get(_requires, False):
                    logger.warning(
                        "[IDLE:HEALTH] Step '%s' SKIPPED_DEPENDENCY_FAILED for '%s' "
                        "— requires '%s' which %s",
                        step.action, component, _requires,
                        "failed" if _requires in _step_outcomes else "did not run",
                    )
                    continue

                # Idempotency gate — skip steps that are still on per-action cooldown
                if not IdleWorkPlaybook.step_is_due(
                    plan.trigger_id, step, self._step_execution_log, _now
                ):
                    logger.debug(
                        f"[IDLE:HEALTH] Step '{step.action}' on cooldown for "
                        f"'{component}' — skipping"
                    )
                    continue

                try:
                    if self.recovery_manager:
                        success = await self.recovery_manager.execute_recovery_action(
                            component  = component,
                            action     = step.action,
                            parameters = step.params or {},
                        )
                        IdleWorkPlaybook.record_step_executed(
                            plan.trigger_id, step, self._step_execution_log, _now
                        )
                        _step_outcomes[step.action] = bool(success)
                        if success:
                            recovered += 1
                            logger.info(
                                f"[IDLE:HEALTH] Recovery step '{step.action}' "
                                f"succeeded for '{component}'"
                            )
                        else:
                            logger.warning(
                                f"[IDLE:HEALTH] Recovery step '{step.action}' "
                                f"failed for '{component}' — "
                                f"on_failure={step.on_failure}"
                            )
                            if step.on_failure == "abort":
                                break
                            elif step.on_failure == "alert" and self.slack_notifier:
                                await self.slack_notifier.send_notification(
                                    title    = f"Health Recovery Failed: {component}",
                                    message  = f"Step '{step.description}' failed for '{component}'.",
                                    severity = "error",
                                    metadata = {"component": component, "action": step.action},
                                )
                    else:
                        _step_outcomes[step.action] = False
                        logger.warning(
                            f"[IDLE:HEALTH] No recovery manager — step "
                            f"'{step.action}' for '{component}' not performed"
                        )
                except Exception as e:
                    logger.warning(
                        f"[IDLE:HEALTH] Step error for '{component}': {e}"
                    )

            # ── Update per-component recovery state ───────────────────────────
            state["attempts"]     += 1
            state["last_attempt"]  = _now

            # ── Escalate if the component keeps failing ────────────────────────
            new_attempts = state["attempts"]
            if new_attempts >= _ESCALATION_THRESHOLD and not state["escalated"]:
                state["escalated"] = True
                logger.error(
                    f"[IDLE:HEALTH] ESCALATION: '{component}' has failed recovery "
                    f"{new_attempts} times (severity={plan.severity})"
                )
                try:
                    # Critical Slack alert
                    if self.slack_notifier:
                        await self.slack_notifier.send_notification(
                            title    = f"Health Escalation: {component} unrecoverable",
                            message  = (
                                f"**Component:** {component}\n"
                                f"**Recovery attempts:** {new_attempts}\n"
                                f"**Severity:** {plan.severity}\n"
                                f"**Issue:** {plan.summary}\n"
                                f"**Action required:** Manual intervention"
                            ),
                            severity = "critical",
                            metadata = {
                                "component":        component,
                                "attempts":         new_attempts,
                                "severity":         plan.severity,
                                "escalation_tier":  "health",
                            },
                        )
                    # High-priority investigation task
                    if self.task_queue:
                        await self.task_queue.add_task(
                            description = (
                                f"ESCALATED: '{component}' has failed health recovery "
                                f"{new_attempts} times. Issue: {plan.summary}. "
                                f"Manual diagnosis and repair required."
                            ),
                            priority    = "high",
                            task_type   = "HEALTH_RECOVERY",
                            metadata    = {
                                "component":   component,
                                "attempts":    new_attempts,
                                "severity":    plan.severity,
                                "escalated":   True,
                            },
                        )
                except Exception as e:
                    logger.warning(f"[IDLE:HEALTH] Escalation notification error: {e}")



    # ── TIER 3: System review snapshot (deterministic, no LLM) ─────────────

    async def _idle_system_review_work(self):
        """Build a facts-first system review snapshot for the LLM.

        This is intentionally non-LLM: it inventories capabilities/tools,
        records the most recent health/security outcomes, and provides a
        lightweight codebase inventory. The snapshot is then stored to
        META memory so downstream tasks can retrieve it.
        """
        import os
        import time as _t

        now = datetime.now()
        now_ts = _t.time()

        def _count_files(root_dir: str, suffixes: tuple[str, ...], max_files: int = 5000) -> int:
            count = 0
            if not root_dir or not os.path.isdir(root_dir):
                return 0
            for base, dirs, files in os.walk(root_dir):
                # Skip common large/noisy dirs
                dirs[:] = [
                    d for d in dirs
                    if d not in {".git", "venv", "venv_torin", "__pycache__", "logs", "tmp", "node_modules"}
                ]
                for name in files:
                    if name.endswith(suffixes):
                        count += 1
                        if count >= max_files:
                            return count
            return count

        snapshot: Dict[str, Any] = {
            "event": "idle_system_review",
            "generated_at": now.isoformat(),
            "generated_at_ts": now_ts,
            "uptime_seconds": int(max(0.0, now_ts - float(getattr(self, "_started_at_ts", now_ts)))),
            "health": {
                "last_check_at": self._idle_last_health_check_at.isoformat() if self._idle_last_health_check_at else None,
                **(self._idle_last_health_snapshot or {}),
            },
            "tools": {},
            "codebase": {},
            "knowledge": {},
            "highlights": {},
        }

        # Knowledge cutoff tracking (persistent state)
        try:
            snapshot["knowledge"] = self._get_knowledge_cutoff_snapshot()
        except Exception as e:
            snapshot["knowledge"] = {"error": str(e)}

        # Tool/capability inventory (safe, deterministic)
        try:
            from core.tools.tool_registry import get_tool_registry

            registry = get_tool_registry()
            total_factories = len(getattr(registry, "tool_factories", {}) or {})
            total_loaded = len(getattr(registry, "tools", {}) or {})
            total_tools = total_factories + total_loaded

            coverage = {}
            try:
                coverage = registry.get_capability_coverage() or {}
            except Exception:
                coverage = {}

            top_caps = sorted(coverage.items(), key=lambda kv: kv[1], reverse=True)[:12]
            top_caps_serialized = [
                {
                    "capability": getattr(cap, "value", str(cap)),
                    "providers": int(n),
                }
                for cap, n in top_caps
            ]

            category_index = getattr(registry, "category_index", {}) or {}
            category_counts = {str(cat): len(names) for cat, names in category_index.items()}
            top_categories = sorted(category_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

            snapshot["tools"] = {
                "total_tools": total_tools,
                "lazy_factories": total_factories,
                "loaded_tools": total_loaded,
                "top_capabilities": top_caps_serialized,
                "top_categories": [{"category": k, "tools": v} for k, v in top_categories],
            }
        except Exception as e:
            snapshot["tools"] = {"error": str(e)}

        # Lightweight codebase inventory (counts only; avoids heavy reads)
        try:
            torin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            snapshot["codebase"] = {
                "root": torin_root,
                "py_files": {
                    "core": _count_files(os.path.join(torin_root, "core"), (".py",)),
                    "services": _count_files(os.path.join(torin_root, "services"), (".py",)),
                    "scripts": _count_files(os.path.join(torin_root, "scripts"), (".py",)),
                    "tests": _count_files(os.path.join(torin_root, "tests"), (".py",)),
                },
            }
        except Exception as e:
            snapshot["codebase"] = {"error": str(e)}

        # Short highlights for quick prompting
        try:
            snapshot["highlights"] = {
                "tools_total": (snapshot.get("tools") or {}).get("total_tools"),
                "health_components_total": (snapshot.get("health") or {}).get("components_total"),
                "health_unhealthy_total": (snapshot.get("health") or {}).get("unhealthy_total"),
                "knowledge_refreshed_through": (snapshot.get("knowledge") or {}).get("refreshed_through_date"),
            }
        except Exception:
            snapshot["highlights"] = {}

        self._idle_last_system_review_at = now
        self._idle_system_review_snapshot = snapshot

        logger.info(
            "[IDLE:REVIEW] System review snapshot updated — "
            f"tools={snapshot.get('highlights', {}).get('tools_total')}, "
            f"health_components={snapshot.get('highlights', {}).get('health_components_total')}"
        )



    # ── TIER 4: Knowledge refresh (autonomous research cadence) ───────────

    async def _idle_knowledge_refresh_work(self):
        """Queue a periodic research task to reduce temporal knowledge gaps.

        Research is learning: what the task finds is what the substrate improves
        by. Nothing here changes code or configuration.
        """
        from .shared_types import Task, TaskType, TaskSource, Priority
        import time as _t

        # Require a system review snapshot so the task has grounded context
        snapshot = getattr(self, "_idle_system_review_snapshot", None)
        if not snapshot:
            logger.info("[IDLE:KNOWLEDGE] Skipping — no system review snapshot yet")
            return

        now = datetime.now()
        now_ts = _t.time()

        min_uptime_s = float(self.config.get("idle_knowledge_refresh_min_uptime_s", 900.0))
        uptime_s = now_ts - float(getattr(self, "_started_at_ts", now_ts))
        if uptime_s < min_uptime_s:
            logger.info(
                f"[IDLE:KNOWLEDGE] Skipping — uptime {int(uptime_s)}s < {int(min_uptime_s)}s"
            )
            return

        # Optional kill-switch
        if not bool(self.config.get("enable_idle_knowledge_refresh", True)):
            logger.debug("[IDLE:KNOWLEDGE] Disabled by config — skipping")
            return

        # Cross-restart throttle: if we started a refresh recently, don't enqueue another.
        try:
            state = self._knowledge_cutoff_state or {}
            started_at = state.get("last_refresh_started_at")
            if started_at:
                from datetime import datetime as _dt
                started_dt = _dt.fromisoformat(str(started_at))
                interval_s = int(self.config.get("idle_knowledge_refresh_interval_s", 6 * 60 * 60))
                if (now - started_dt).total_seconds() < interval_s:
                    logger.info(
                        f"[IDLE:KNOWLEDGE] Skipping — last_refresh_started_at={started_at} "
                        f"(< interval {interval_s}s)"
                    )
                    return
        except Exception:
            pass

        # Staleness gate — only refresh if our knowledge is stale.
        # This prevents constant research even with a short idle interval.
        # Default: refresh at most weekly.
        max_age_days = int(self.config.get("knowledge_refresh_max_age_days", 7))
        state = self._knowledge_cutoff_state or {}
        refreshed_through = (state.get("refreshed_through_date") or "")
        try:
            from datetime import date as _date
            if refreshed_through:
                refreshed_date = _date.fromisoformat(refreshed_through)
                age_days = (now.date() - refreshed_date).days
                if age_days < max_age_days:
                    logger.info(
                        f"[IDLE:KNOWLEDGE] Skipping — refreshed_through={refreshed_through} "
                        f"(age={age_days}d < {max_age_days}d)"
                    )
                    return
        except Exception:
            # If state is malformed, fall through and refresh.
            pass

        cutoff = self._get_declared_model_cutoff_date()

        # Create a research task (non-mutating) that can use CONDUCT_RESEARCH tools.
        topic_list = self.config.get(
            "idle_knowledge_refresh_topics",
            [
                "recent AI agent tooling patterns (2025-2026)",
                "function calling / tool schema best practices", 
                "MCP ecosystem changes and interoperability", 
                "security CVEs relevant to our Python dependencies", 
                "pgvector/Postgres performance practices", 
            ],
        )
        topics_str = "; ".join(str(t) for t in topic_list[:8])

        task = Task(
            id=f"knowledge_refresh_{now.timestamp()}",
            type=TaskType.RESEARCH,
            description=(
                "Conduct research to reduce temporal knowledge gaps and update internal operational knowledge.\n"
                f"Model knowledge cutoff (declared): {cutoff}. Current date: {now.date().isoformat()}.\n\n"
                f"Last refreshed through: {refreshed_through or 'unknown'}.\n\n"
                "Research topics:\n"
                f"- {topics_str}\n\n"
                "Deliverables (STRICT):\n"
                "1) Bullet summary of findings with source URLs\n"
                "2) Relevance mapping to TorinAI subsystems/tools\n"
                "3) Recommendations ranked by impact/effort\n"
                "4) If code changes are suggested, propose follow-up tasks — DO NOT modify code in this task\n\n"
                f"System review highlights: {snapshot.get('highlights', {})}"
            ),
            priority=Priority.LOW,
            source=TaskSource.AUTONOMOUS,
            created_by="idle_knowledge_refresh",
            metadata={
                "trigger": "idle_priority_loop",
                "idle_count": self._idle_count,
                "knowledge_refresh": True,
                "declared_cutoff": cutoff,
                "refreshed_through_before": refreshed_through or None,
                "system_review_highlights": snapshot.get("highlights", {}),
                "no_code_changes": True,
            },
        )

        try:
            await self.task_queue.add_task(task, priority=Priority.LOW)
            self._idle_last_knowledge_refresh_at = now
            # Record the refresh start (best-effort) for cross-session visibility
            try:
                self._knowledge_cutoff_state["last_refresh_started_at"] = now.isoformat()
                self._knowledge_cutoff_state["last_refresh_task_id"] = task.id
                self._knowledge_cutoff_state["declared_model_cutoff_date"] = cutoff
                self._save_knowledge_cutoff_state(self._knowledge_cutoff_state)
            except Exception as e:
                logger.debug(f"[IDLE:KNOWLEDGE] Could not persist refresh start state: {e}")
            logger.info(f"[IDLE:KNOWLEDGE] Task queued: {task.id} (topics={len(topic_list)})")
        except Exception as e:
            logger.warning(f"[IDLE:KNOWLEDGE] Failed to queue knowledge refresh task: {e}")


    # ── Knowledge cutoff persistence helpers ───────────────────────────────

    def _knowledge_cutoff_state_path(self) -> str:
        """Return an absolute path for the knowledge cutoff state file."""
        import os
        torin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        rel = self.config.get("knowledge_cutoff_state_path", os.path.join("data", "knowledge_cutoff_state.json"))
        return os.path.join(torin_root, rel)

    def _load_knowledge_cutoff_state(self) -> Dict[str, Any]:
        import json
        import os

        path = self._knowledge_cutoff_state_path()
        if not os.path.exists(path):
            return {
                "schema": "knowledge_cutoff_state.v1",
                "declared_model_cutoff_date": self._get_declared_model_cutoff_date(),
                "refreshed_through_date": None,
                "last_refresh_started_at": None,
                "last_refresh_completed_at": None,
                "last_refresh_task_id": None,
            }

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}

        if not isinstance(data, dict):
            raise ValueError("knowledge cutoff state is not a dict")

        data.setdefault("schema", "knowledge_cutoff_state.v1")
        # Override if the saved value is absent or the sentinel "unknown" from old code
        _saved_cutoff = data.get("declared_model_cutoff_date")
        if not _saved_cutoff or _saved_cutoff == "unknown":
            data["declared_model_cutoff_date"] = self._get_declared_model_cutoff_date()
        data.setdefault("refreshed_through_date", None)
        data.setdefault("last_refresh_started_at", None)
        data.setdefault("last_refresh_completed_at", None)
        data.setdefault("last_refresh_task_id", None)
        return data

    def _save_knowledge_cutoff_state(self, state: Dict[str, Any]) -> None:
        import json
        import os
        import tempfile

        path = self._knowledge_cutoff_state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)

        payload = dict(state or {})
        payload.setdefault("schema", "knowledge_cutoff_state.v1")
        payload.setdefault("declared_model_cutoff_date", self._get_declared_model_cutoff_date())

        fd, tmp_path = tempfile.mkstemp(prefix="knowledge_cutoff_state_", suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    # ── Permanently-failed fingerprint persistence ──────────────────────

    def _permanently_failed_fps_path(self) -> str:
        import os
        torin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        rel = self.config.get("permanently_failed_fps_path", os.path.join("data", "permanently_failed_fps.json"))
        return os.path.join(torin_root, rel)

    def _load_permanently_failed_fps(self) -> "Set[str]":
        """Load the persistent set of permanently-failed task fingerprints from disk."""
        import json, os
        path = self._permanently_failed_fps_path()
        if not os.path.exists(path):
            return set()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                loaded = set(str(fp) for fp in data if fp)
                logger.info(f"♻️  Loaded {len(loaded)} permanently-failed fingerprints from disk")
                return loaded
        except Exception as e:
            logger.debug(f"Failed to parse permanently_failed_fps.json: {e}")
        return set()

    def _save_permanently_failed_fps(self) -> None:
        """Atomically persist the permanently-failed fingerprint set to disk."""
        import json, os, tempfile
        path = self._permanently_failed_fps_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = sorted(self._permanently_failed_fps)
        fd, tmp_path = tempfile.mkstemp(prefix="permanently_failed_fps_", suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    def _get_declared_model_cutoff_date(self) -> str:
        """Declared model training cutoff date.

        This is operator-provided (config/env). We intentionally do not try to
        guess from model name.
        """
        import os

        # 1. Explicit override via env var or config always wins
        explicit = (
            os.getenv("MODEL_KNOWLEDGE_CUTOFF_DATE")
            or self.config.get("model_knowledge_cutoff_date")
            or self.config.get("knowledge_cutoff_date")
        )
        if explicit:
            return explicit

        # The coordinator does not probe a model — there is none, and the
        # substrate has no training cutoff of its own. The
        # date comes from configuration (above) or this default, which callers
        # can override; it only seeds how stale the knowledge-refresh tier
        # assumes its world knowledge might be.
        return self.config.get("default_knowledge_cutoff_date", "2024-09")

    def _get_knowledge_cutoff_snapshot(self) -> Dict[str, Any]:
        from datetime import date as _date

        state = self._knowledge_cutoff_state or {}
        refreshed = state.get("refreshed_through_date")
        days_stale = None
        try:
            if refreshed:
                refreshed_date = _date.fromisoformat(str(refreshed))
                days_stale = (_date.today() - refreshed_date).days
        except Exception:
            days_stale = None

        _saved_cutoff = state.get("declared_model_cutoff_date")
        return {
            "declared_model_cutoff_date": (_saved_cutoff if _saved_cutoff and _saved_cutoff != "unknown" else self._get_declared_model_cutoff_date()),
            "refreshed_through_date": refreshed,
            "days_stale": days_stale,
            "last_refresh_started_at": state.get("last_refresh_started_at"),
            "last_refresh_completed_at": state.get("last_refresh_completed_at"),
            "last_refresh_task_id": state.get("last_refresh_task_id"),
        }


    # ── Completion callback: knowledge refresh completion ──────────────────

    async def _on_knowledge_refresh_complete(
        self,
        task: Task,
        result: Dict[str, Any],
        confidence: float,
    ):
        """Update knowledge refresh state when a knowledge_refresh research task completes."""
        try:
            meta = getattr(task, "metadata", None) or {}
            if not meta.get("knowledge_refresh", False):
                return

            now = datetime.now()
            today = now.date().isoformat()

            # Update persistent state
            self._knowledge_cutoff_state["last_refresh_completed_at"] = now.isoformat()
            self._knowledge_cutoff_state["refreshed_through_date"] = today
            self._knowledge_cutoff_state["last_refresh_task_id"] = getattr(task, "id", None)
            _meta_cutoff = meta.get("declared_cutoff")
            self._knowledge_cutoff_state["declared_model_cutoff_date"] = (
                _meta_cutoff if _meta_cutoff and _meta_cutoff != "unknown"
                else self._get_declared_model_cutoff_date()
            )
            try:
                self._save_knowledge_cutoff_state(self._knowledge_cutoff_state)
            except Exception as e:
                logger.debug(f"Knowledge cutoff state save failed (non-fatal): {e}")

            # Persist a META memory event (best-effort)
            try:
                await self.store_memory(
                    memory_type=MemoryType.META,
                    content={
                        "event": "knowledge_refresh_complete",
                        "task_id": getattr(task, "id", None),
                        "confidence": float(confidence) if confidence is not None else None,
                        "declared_model_cutoff_date": self._knowledge_cutoff_state.get("declared_model_cutoff_date"),
                        "refreshed_through_date": today,
                        "timestamp": now.isoformat(),
                    },
                    importance=0.30,
                    tags=["knowledge", "refresh", "cutoff", "autonomous"],
                )
            except Exception as e:
                logger.debug(f"Could not store knowledge refresh completion memory: {e}")

            logger.info(
                f"[KNOWLEDGE] Refreshed-through updated: {today} (task={getattr(task, 'id', 'unknown')})"
            )
        except Exception as e:
            logger.debug(f"Knowledge refresh completion callback error: {e}")



    # ── TIER 4: Meta-learning — evaluate ALL task types ───────────────────────

    #: Stamped onto a task-outcome memory once its domain has been expanded.
    #: Durable dedup lives on the OUTCOME itself rather than in an in-memory
    #: watermark, because the scheduler's per-job state resets on every restart
    #: -- so a watermark would re-learn the whole backlog each start and the
    #: meta-learner would count one outcome as many independent trials.
    DOMAIN_EXPANSION_MARK = "domain_expanded_at"

    # Cascade guard for the coalesced event-driven drains: a reaction whose work
    # emits an event that re-wakes it (directly or via another drain) must not spin
    # forever. Idempotent drains terminate on their own (a no-op re-run emits
    # nothing), but this hard-bounds the coalesced re-run count as a safety net; if
    # hit, the leftover work resumes on the next genuine wake and a warning surfaces
    # the suspected cascade for investigation.
    _COALESCE_MAX_PASSES = 100

    async def _idle_domain_expansion_work(self):
        """PRIORITY 4 — Expand domain knowledge from recent task outcomes.

        TORINAI_REFERENCE.md:3114 specifies this tier. Every part of it already
        existed and nothing joined them:

          producer  _store_task_outcome_meta_memory (:1725, 4 live call sites)
                    writes TaskOutcomeRecord{domain, outcome, confidence} as a
                    META memory tagged "task_outcome"
          consumer  UnifiedLearningSystem.learn_with_domain_context, the only
                    method that puts a domain onto learn_from_example and so the
                    only thing that opens the cross-domain transfer path
          bridge    DomainRegistry.resolve_domain_reference, which turns the
                    producer's CATEGORY ("scientific") into the populated FIELDS
                    beneath it

        The consumer had zero callers, so no task outcome has ever reached the
        domain layer. This tier is that call.
        """
        self._domain_expansion_status = "STARTED"

        if not getattr(self.learning, "initialized", False):
            # Not a quiet skip. This tier cannot do its work without the
            # learning system, and a silent return would be indistinguishable
            # from "there was nothing to expand".
            self._domain_expansion_status = "NO_LEARNING_SYSTEM"
            logger.warning(
                "[IDLE:DOMAIN] unified_learning is not attached; task outcomes "
                "cannot reach the domain layer")
            return 0

        # get_memory_agent() returns an UNINITIALIZED agent -- postgres_storage
        # is None until initialize() runs (its own docstring documents the two
        # calls). Reading that None as "storage unavailable" would report an
        # unmet precondition as an absent subsystem, and this tier would go
        # quiet for a reason that has nothing to do with task outcomes.
        storage = getattr(self.memory, "postgres_storage", None)
        if storage is None and hasattr(self.memory, "initialize"):
            await self.memory.initialize()
            storage = getattr(self.memory, "postgres_storage", None)
        if storage is None:
            self._domain_expansion_status = "NO_MEMORY_STORAGE"
            logger.warning(
                "[IDLE:DOMAIN] memory agent initialized but exposes no storage; "
                "task outcomes cannot be read")
            return 0

        from core.memory.utils.interfaces import MemoryType
        from core.learning.learning_interfaces import LearningExample

        batch = int(self.config.get("idle_domain_expansion_batch", 25))
        outcomes = await storage.search_memories(
            memory_type=MemoryType.META,
            tags={"task_outcome"},
            limit=batch * 4,   # headroom: already-expanded ones are filtered below
        )

        pending = [m for m in outcomes
                   if not (m.metadata or {}).get(self.DOMAIN_EXPANSION_MARK)][:batch]
        if not pending:
            # A real zero, reported as one. "No task has completed since the
            # last pass" and "the reader is broken" must not look alike.
            self._domain_expansion_status = "NOTHING_PENDING"
            logger.info(
                "[IDLE:DOMAIN] %d task-outcome memory(ies) found, none unexpanded",
                len(outcomes))
            return 0

        expanded = 0
        transfers = 0
        skipped: Dict[str, int] = {}
        for memory in pending:
            status, t = await self._expand_one_outcome(memory, storage)
            if status == "expanded":
                expanded += 1
                transfers += t
            else:
                skipped[status] = skipped.get(status, 0) + 1

        self._domain_expansion_status = "COMPLETED"
        # OBSERVABLE, not just logged. The reason an outcome was not expanded is
        # the diagnostic that separates "nothing to learn from" from "the tier
        # cannot read what the producer wrote" -- and a reason that only ever
        # reaches a log line cannot be asserted on, so a read that silently
        # classifies every outcome as unusable looks identical to a quiet
        # system.
        self._domain_expansion_counts = {
            "considered": len(pending),
            "expanded": expanded,
            "transfers": transfers,
            "skipped": dict(skipped),
        }
        logger.info(
            "[IDLE:DOMAIN] %d/%d task outcome(s) expanded into the domain layer, "
            "%d cross-domain transfer(s)%s",
            expanded, len(pending), transfers,
            f"; not expanded: {skipped}" if skipped else "")

        # The return leg. Expansion writes transfers; this asks whether the ones
        # already written actually helped. Running it here keeps both directions
        # of the loop under one owner rather than adding a second tier that
        # would have to agree with this one about what a transfer is.
        await self._resolve_transfer_outcomes()

        # PROGRESS signal for the event-driven drain (_coalesced_domain_expansion):
        # how many outcomes this pass actually expanded. The drain loops while this
        # is > 0, so a backlog drains fully; it stops when a pass expands nothing
        # (all remaining are unmarked no_domain/domain_empty, retried on a later wake).
        return expanded

    async def _expand_one_outcome(self, memory, storage) -> Tuple[str, int]:
        """Expand ONE task-outcome memory into the domain layer.

        The single per-outcome authority, shared by the idle tier and the
        reactive `_react_expand_outcome`, so both go through identical logic and
        the DOMAIN_EXPANSION_MARK dedup keeps them from double-processing.
        Returns (status, transfers): status is 'expanded', 'no_domain', or the
        learning error_class; transfers is the cross-domain transfers written.

        The structured record lives at thinking_state['raw_event'] — store_memory
        renders the event dict into prose for `content`, so the TaskOutcomeRecord
        fields (domain, outcome, confidence, task_type) are read from the raw
        dict, not the narrative.
        """
        from core.learning.learning_interfaces import LearningExample
        raw = (memory.thinking_state or {}).get("raw_event")
        content = raw if isinstance(raw, dict) else {}
        if not content.get("task_type"):
            # The producer always writes `task_type`. Its absence means the
            # record did not come from TaskOutcomeRecord — counted, left unmarked.
            return ("no_domain", 0)
        # The knowledge domain is derived from what the task was, the same way
        # for records written before `knowledge_domain` existed: their `domain`
        # field holds a category guessed from the description or an operation
        # bucket, and neither names a domain.
        domain = self.knowledge_domain_of(
            content.get("task_type"), content.get("knowledge_domain"))
        if domain is None:
            # A task that acted in no domain has nothing to expand. Marked, so it
            # is not reconsidered on every pass.
            if not await storage.update_memory(memory.memory_id, {
                    "metadata": {self.DOMAIN_EXPANSION_MARK: datetime.now().isoformat(),
                                 "domain_expansion": "no_knowledge_domain"},
                    "metadata.merge": True}):
                raise RuntimeError(
                    f"task outcome {memory.memory_id} names no domain but could "
                    f"not be marked; it would be reconsidered on every pass")
            return ("no_knowledge_domain", 0)

        result = await self.learning.learn_with_domain_context(
            LearningExample(
                example_id=memory.memory_id,
                inputs={
                    "task_id": content.get("task_id"),
                    "task_type": content.get("task_type"),
                    "task_description": content.get("task_description"),
                    "task_source": content.get("task_source"),
                },
                targets={
                    "outcome": content.get("outcome"),
                    "result_summary": content.get("result_summary"),
                    "failure_reason": content.get("failure_reason"),
                },
                # The recorded confidence IS the quality of this example.
                quality_score=float(content.get("confidence", 0.0) or 0.0),
                task_type=content.get("task_type"),
                domain=str(domain),
                source="task_outcome",
            ),
            str(domain),
        )

        if not result.success:
            # Deliberately NOT marked. An outcome that could not be expanded
            # because its domain holds nothing yet must be reconsidered once that
            # domain has been learned (`domain_empty` is exactly that case).
            return ((result.metadata or {}).get("error_class") or "learning_failed", 0)

        # EXPANDED means the domain layer processed this outcome — not that the
        # learning strategy earned credit for it (separate facts).
        cross = (result.metadata or {}).get("cross_domain") or {}
        transfers = len(cross.get("transfers") or [])

        marked = await storage.update_memory(memory.memory_id, {
            "metadata": {self.DOMAIN_EXPANSION_MARK: datetime.now().isoformat()},
            "metadata.merge": True,
        })
        if not marked:
            # An unmarked outcome would be expanded again and the meta-learner
            # would count the repeat as fresh evidence. Stop rather than quietly
            # build up duplicate trials.
            raise RuntimeError(
                f"task outcome {memory.memory_id} was expanded but could not be "
                f"marked; continuing would re-learn it on every pass")
        return ("expanded", transfers)

    async def _idle_domain_discovery_work(self):
        """Discover domains from what the substrate has learned AND been taught.

        Two kinds of subject grow the substrate's map here, through the one domain
        authority. OPERATIONAL: buckets of learned operators under a string
        domain_id, crystallized or merged by operator structure -- subjects the
        substrate learned by ACTING. DECLARATIVE: connected clusters of taught
        concepts sitting in the `conversation` channel, crystallized into their
        own subject domains by relation structure -- subjects the substrate was
        TAUGHT. Both ask the Universal Domain Master to decide; nothing here
        decides on its own. The declarative half is what lets teaching advance
        the domain system instead of piling every taught fact into one channel.
        """
        udm = self.universal_domain_master  # this substrate's own domain faculty

        summary = await udm.discover_domains()
        if summary.get("examined"):
            logger.info(
                "[IDLE] domain discovery: %d examined, %d crystallized, %d merged",
                summary["examined"], summary["crystallized"], summary["merged"])

        # Declarative twin: crystallize taught-concept clusters out of the
        # conversation channel into per-subject domains.
        concept_summary = await udm.discover_concept_domains(from_field="conversation")
        if concept_summary.get("crystallized"):
            logger.info(
                "[IDLE] concept-domain discovery: %d clusters examined, %d crystallized (%s)",
                concept_summary["examined"], concept_summary["crystallized"],
                ", ".join(f"{o['field']}:{o['concepts']}"
                          for o in concept_summary.get("outcomes", [])))
        return {"operator": summary, "declarative": concept_summary}

    async def _idle_operator_exploration_work(self):
        """Learn the operators of a domain the substrate is not yet competent in,
        chosen by intrinsic motivation.

        Domain competence is an epistemic belief. An under-learned domain sits at
        high entropy and appears in the epistemic engine's unstable regions;
        intrinsic motivation ranks exactly those, mixing all its drives. This
        tier takes the top-ranked target that is an operator-domain it can
        explore, runs ONE exploration cycle, and records the outcome as evidence
        on that competence belief -- so the belief moves and the next choice
        follows from it. Nothing here selects domains on its own.
        """
        from core.learning.exploration import (
            SubstrateExplorer, explorable_domains, get_proposer)

        udm = self.universal_domain_master  # this substrate's own domain faculty

        domains = explorable_domains()
        if not domains:
            return {"status": "no explorable domain"}

        # Every explorable domain gets a competence belief so it can surface;
        # then intrinsic motivation decides which one is worth exploring now.
        for d in domains:
            await udm.ensure_competence_belief(d)
        # Erode competence that is no longer being earned, so a domain the
        # substrate wrongly believes it has mastered resurfaces for
        # re-verification rather than being trusted forever.
        await udm.refresh_competence_beliefs()

        chosen = None
        im = getattr(self, "intrinsic_motivation", None)
        if im is not None:
            try:
                targets = await im.get_top_exploration_targets(limit=10)
                chosen = await udm.select_exploration_target(domains, targets)
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._idle_operator_exploration_work")
                logger.info("exploration target ranking unavailable: %s", e)
        if chosen is None:
            # Motivation surfaced nothing among explorable domains; stay
            # always-online by exploring one anyway (the belief still moves).
            chosen = domains[0]

        # Explore RECORDS demonstrations and enqueues their operators for
        # induction; it does not induce here. Induction runs off this acting path
        # in `_idle_operator_induction_work`, which is also what moves the
        # competence belief -- learning changes competence, not the acting that
        # fed it. This tier records only CONTROLLABILITY, which the acting itself
        # establishes: did acting move the world (acted/positive) more than not
        # acting (still/ambient)? That is what lets a later cycle drop a domain
        # the substrate cannot steer.
        summary = await SubstrateExplorer().explore(
            chosen, get_proposer(chosen), max_actions=8)
        await udm.record_controllability(
            chosen,
            action_attempts=summary.get("acted", 0),
            action_effects=summary.get("positive", 0),
            still_observations=summary.get("still_observations", 0),
            ambient_changes=summary.get("ambient_changes", 0))
        if im is not None:
            try:
                await im.mark_target_explored(f"competence:{chosen}")
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._idle_operator_exploration_work")
        logger.info("[IDLE] operator exploration: domain=%s acted=%s", chosen,
                    summary.get("acted"))
        return {"domain": chosen, **summary}

    async def _idle_operator_induction_work(self):
        """Induce the operators exploration has gathered demonstrations for, off
        the acting path, and move the competence beliefs the results earn.

        This is the always-online learner. Exploration (a separate tier) only
        acts and records; the hypothesis search -- whose cost grows with the
        richness of the observed state -- runs HERE so no acting cycle pays for
        it. A domain that gained a newly executable operator has become more
        competent; one whose demonstrations did not yet yield one has not. Both
        are recorded as competence evidence, so the belief tracks what learning
        actually established.
        """
        # Drain the pending induction through this substrate's OWN learning
        # authority (the always-online, model-free learner).
        result = await self.learning.drain_pending_induction(limit=50)
        by_domain = result.get("by_domain", {})
        if not by_domain:
            return {"drained": 0}

        udm = self.universal_domain_master  # this substrate's own domain faculty

        for domain_id, learned in by_domain.items():
            await udm.record_competence_evidence(domain_id, learned=bool(learned))
        learned_domains = [d for d, learned in by_domain.items() if learned]
        logger.info("[IDLE] operator induction: drained=%d learned_domains=%s",
                    result.get("drained", 0), learned_domains)
        return {"drained": result.get("drained", 0),
                "learned_domains": learned_domains,
                "domains_touched": sorted(by_domain)}

    async def _idle_analogy_discovery_work(self):
        """Discover cross-domain analogies over the learned concept store, bounded.

        `AnalogyDiscovery.find_analogy` already loads unified.concepts and
        PERSISTS the best analogy and its concept mappings -- but nothing ever
        CALLED it, so unified.analogies and unified.concept_mappings stayed empty.
        This is that caller. It drives find_analogy over a bounded batch of
        (source concept -> target domain) pairs each cycle, rotating a cursor so
        coverage advances across cycles while the O(pairs) cost stays capped.
        """
        from core.reasoning.analogy_discovery import get_analogy_discovery

        engine = get_analogy_discovery()
        if not await engine.initialize():
            self._analogy_status = "ENGINE_UNAVAILABLE"
            return {"status": "analogy engine unavailable"}

        domains = [d for d, cs in engine.concepts.items() if cs]
        if len(domains) < 2:
            # Not a failure: cross-domain analogy needs at least two populated
            # domains. Reported so "no analogies" is distinguishable from "broken".
            self._analogy_status = "TOO_FEW_DOMAINS"
            return {"status": "need >=2 populated domains", "domains": len(domains)}

        import itertools
        MAX_CALLS = int(self.config.get("analogy_pairs_per_cycle", 8))
        MAX_SRC = int(self.config.get("analogy_sources_per_domain", 3))

        # The full work-list of (source concept, target domain) pairs. Bounded per
        # source domain so one large domain cannot crowd the batch.
        attempts = []
        for src_dom, tgt_dom in itertools.permutations(domains, 2):
            # Only source concepts that actually carry relationships can match on
            # structure; a concept with none contributes nothing but cost.
            srcs = [n for n, c in engine.concepts.get(src_dom, {}).items()
                    if getattr(c, "relationships", None)][:MAX_SRC]
            for sc in srcs:
                attempts.append((sc, tgt_dom))
        if not attempts:
            self._analogy_status = "NO_CONCEPTS"
            return {"status": "no source concepts"}

        cur = getattr(self, "_analogy_cursor", 0) % len(attempts)
        batch = attempts[cur:cur + MAX_CALLS] or attempts[:MAX_CALLS]
        self._analogy_cursor = (cur + len(batch)) % len(attempts)

        found = 0
        # When a pair yields NO analogy, the diagnostic (Oracle A) explains WHY —
        # source-resolution vs target-domain vs candidate-enumeration vs scoring —
        # so "found 0" is an actionable stage, not a silent blank. This is the
        # analogy-diagnostics instrument, which had no caller before.
        _diag = None
        fail_stages: Dict[str, int] = {}
        for sc, tgt_dom in batch:
            try:
                if await engine.find_analogy(sc, tgt_dom, min_similarity=0.5):
                    found += 1
                else:
                    if _diag is None:
                        from core.reasoning.analogy_diagnostics import AnalogyDiagnostics
                        _diag = AnalogyDiagnostics(engine)
                    oa = await _diag.oracle_a(sc, tgt_dom)
                    stage = oa.first_failing_stage or "A5_scoring_no_match"
                    fail_stages[stage] = fail_stages.get(stage, 0) + 1
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._idle_analogy_discovery_work")
                logger.info("analogy %s -> %s failed: %s", sc, tgt_dom, e)

        self._analogy_status = "RAN"
        if fail_stages:
            logger.info("[IDLE:ANALOGY] no-mapping stages: %s", dict(fail_stages))
        logger.info("[IDLE:ANALOGY] attempted=%d found=%d (%d domains, cursor=%d/%d)",
                    len(batch), found, len(domains), self._analogy_cursor, len(attempts))
        return {"attempted": len(batch), "found": found, "domains": len(domains),
                "no_mapping_stages": fail_stages}

    async def _rule_root_count(self, *, domain_id: str, predicate: str, arity: int) -> int:
        """The strongest confirming-root count among executable operators of a
        signature — the confidence measure a re-validation must move. Reads the
        rule store (the authority), never inferred from having re-induced."""
        from core.learning.rule_store import get_rule_store
        rules = await get_rule_store().executable_rules(domain_id=domain_id)
        counts = [int(getattr(r, "positive_root_count", 0) or 0)
                  for r in rules
                  if getattr(getattr(r, "rule", None), "action", None) is not None
                  and r.rule.action.signature == (predicate, arity)]
        return max(counts) if counts else 0

    async def _execute_drive_goal(self, task) -> Dict[str, Any]:
        """Execute an intrinsic DRIVE goal (competence/confidence) as REAL,
        model-free substrate learning, targeted at the operator/domain the goal
        names.

        The action is deterministic: ACT to gather fresh evidence in the domain
        (only if the domain is explorable — records demonstrations + enqueues
        them), then RE-INDUCE the operator through the always-online learner. The
        SAME operations the idle growth loop runs, aimed by motivation.

        Success is READ from what learning established — an operator became
        executable, or a weak operator gained confirming roots — never inferred
        from having run. When there is no way to make progress (a weak operator
        in a domain with no proposer to gather fresh evidence), that is an HONEST
        failure with a named reason, not a fabricated success.
        """
        from core.learning.exploration import (
            SubstrateExplorer, explorable_domains, get_proposer)

        md = task.metadata or {}
        drive = md.get("drive")
        domain = md.get("domain_id")
        if drive not in ("competence", "confidence") or not (
                isinstance(domain, str) and domain.strip()):
            return {"verification_state": "failed",
                    "error": f"drive goal missing drive/domain "
                             f"(drive={drive!r} domain={domain!r})"}

        # ACT: gather fresh evidence, but only where the substrate can actually
        # act. A domain with no registered proposer cannot be explored; that is a
        # real limit, surfaced (not silently treated as "nothing gathered").
        explorable = domain in set(explorable_domains())
        explore_summary = None
        if explorable:
            try:
                explore_summary = await SubstrateExplorer().explore(
                    domain, get_proposer(domain), max_actions=8)
            except Exception as e:
                raise_if_structural(e, "autonomous_coordinator._execute_drive_goal")
                logger.info("drive-goal exploration in %s failed: %s", domain, e)

        udm = getattr(self, "universal_domain_master", None)

        # ---- competence, domain-level contrastive: re-induce every operator ----
        if drive == "competence" and md.get("scope") == "domain_contrastive":
            from core.learning.demonstration_store import get_demonstration_store
            store = get_demonstration_store()
            sigs = [s for s in await store.signatures(domain_id=domain)
                    if (s[0], s[1]) != store.CONTRASTIVE]
            induced = []
            for predicate, arity in sigs:
                induced.append(await self.learning.reinduce_operator(
                    domain_id=domain, predicate=predicate, arity=arity))
            executable = [s for s in induced if s.get("executable")]
            ok = bool(executable)
            if udm is not None:
                await udm.record_competence_evidence(domain, learned=ok)
            logger.info("[DRIVE competence/contrastive] domain=%s operators=%d executable=%d",
                        domain, len(induced), len(executable))
            return {"verification_state": "verified" if ok else "failed",
                    "success": ok, "drive": drive, "domain_id": domain,
                    "scope": "domain_contrastive",
                    "operators_induced": len(induced),
                    "operators_executable": len(executable),
                    "explored": bool(explore_summary),
                    "error": None if ok else
                        (f"contrastive re-induced {len(induced)} operator(s), none "
                         f"became executable" if sigs else
                         f"domain {domain} has no operator signatures to sharpen")}

        # ---- per-operator competence / confidence: re-induce the signature ----
        predicate = md.get("predicate")
        arity = md.get("arity")
        if not (isinstance(predicate, str) and predicate.strip()) or \
                not isinstance(arity, int):
            return {"verification_state": "failed",
                    "error": f"drive goal missing operator signature "
                             f"(predicate={predicate!r} arity={arity!r})"}

        if drive == "confidence":
            before = await self._rule_root_count(
                domain_id=domain, predicate=predicate, arity=arity)
            await self.learning.reinduce_operator(
                domain_id=domain, predicate=predicate, arity=arity)
            after = await self._rule_root_count(
                domain_id=domain, predicate=predicate, arity=arity)
            ok = after > before
            logger.info("[DRIVE confidence] %s/%s in %s roots %d→%d explorable=%s",
                        predicate, arity, domain, before, after, explorable)
            # A domain with no proposer is not one the substrate "cannot operate
            # in" — it is one it has no binding/observer wired for YET (a
            # BINDING_GAP, the same honest, addressable gap address_deficit
            # escalates). It is resolved by wiring a binding (e.g. the
            # encounter-driven filesystem install) or learning the domain, not by
            # faking evidence. Marked so it can be routed to acquisition, not read
            # as a dead end.
            out = {"verification_state": "verified" if ok else "failed",
                   "success": ok, "drive": drive, "domain_id": domain,
                   "signature": f"{predicate}/{arity}",
                   "root_count_before": before, "root_count_after": after,
                   "explored": bool(explore_summary)}
            if not ok:
                if explorable:
                    out["error"] = (f"re-validation gathered no new confirming root "
                                    f"({before}→{after})")
                else:
                    out["binding_gap"] = True
                    out["error"] = (f"binding_gap: no binding/observer wired for domain "
                                    f"{domain} yet — the substrate must learn/wire it "
                                    f"before it can gather fresh evidence for "
                                    f"{predicate}/{arity}")
            return out

        # competence, per-operator
        summary = await self.learning.reinduce_operator(
            domain_id=domain, predicate=predicate, arity=arity)
        ok = bool(summary.get("executable"))
        if udm is not None:
            await udm.record_competence_evidence(domain, learned=ok)
        logger.info("[DRIVE competence] %s/%s in %s status=%s explorable=%s",
                    predicate, arity, domain, summary.get("status"), explorable)
        return {"verification_state": "verified" if ok else "failed",
                "success": ok, "drive": drive, "domain_id": domain,
                "signature": f"{predicate}/{arity}",
                "induction_status": summary.get("status"),
                "positives": summary.get("positives"),
                "explored": bool(explore_summary),
                "error": None if ok else
                    f"operator {predicate}/{arity} not validated: {summary.get('status')}"}

    #: A transfer is judged only once the target domain has produced this many
    #: outcomes on each side of it. Below that the honest answer is "not known
    #: yet", which is what NULL means in unified.knowledge_transfers.
    TRANSFER_MIN_EVIDENCE = 5
    #: Post-transfer success rate must beat the baseline by this margin to be
    #: called help. A margin, not any improvement, because small samples move on
    #: noise and a transfer credited by noise becomes evidence for the next one.
    TRANSFER_EFFECT_MARGIN = 0.10

    async def _resolve_transfer_outcomes(self):
        """Close the OTHER direction of the transfer loop.

        A knowledge transfer was written with success NULL and nothing ever
        revisited it, so the record could say a correspondence had been proposed
        and structurally validated, but never whether relying on it made work in
        the target domain go better. Those are different claims: the validator
        judges STRUCTURE, this judges OUTCOMES, and only outcomes can say a
        transfer helped.

        The comparison is before/after within the SAME target domain -- task
        outcomes recorded there before the transfer existed against those
        recorded after. A transfer cannot be credited for the outcome that
        triggered it (that outcome precedes it), so the trigger is never part of
        the evidence.

        Verdicts:
          TRUE   post-transfer success rate beats the baseline by the margin
          FALSE  it does not
          NULL   too few outcomes on either side to say -- left unresolved and
                 revisited later, never defaulted to False
        """
        self._transfer_resolution_status = "STARTED"
        registry = getattr(self.learning, "domain_registry", None)
        if registry is None or not registry.initialized:
            self._transfer_resolution_status = "NO_REGISTRY"
            logger.warning("[IDLE:DOMAIN] no initialized domain registry; "
                           "transfer outcomes cannot be resolved")
            return

        pending = await registry.unresolved_transfers()
        if not pending:
            self._transfer_resolution_status = "NOTHING_PENDING"
            return

        outcomes = await self._task_outcomes_by_field(registry)
        resolved, unresolved = 0, 0
        for row in pending:
            target = f"domain_{row['target_domain']}"
            created = row["created_at"]
            series = outcomes.get(target, [])
            before = [o for o in series if o["at"] < created]
            after = [o for o in series if o["at"] > created]

            meta = row["metadata"]
            if isinstance(meta, str):
                import json as _json
                meta = _json.loads(meta)
            mapping_ids = (meta or {}).get("concept_mappings") or []

            # ATTRIBUTION FIRST. "After the transfer" is not "because of the
            # transfer": if a mapping participated in 2 of 10 later tasks, a
            # before/after comparison credits it with all 10. The usage events
            # say which tasks it actually took part in, so the post-transfer
            # window splits into the tasks it touched and the ones it did not,
            # and the second group is a contemporaneous control rather than a
            # historical one.
            touched = await registry.tasks_using_mappings(mapping_ids)
            treatment = [o for o in after if o["task_id"] in touched]
            control = [o for o in after if o["task_id"] not in touched]

            if len(treatment) >= self.TRANSFER_MIN_EVIDENCE and \
               len(control) >= self.TRANSFER_MIN_EVIDENCE:
                inference, basis = "attributed", "applied-vs-unapplied tasks after the transfer"
                effect_n, effect_rate = len(treatment), sum(o["ok"] for o in treatment) / len(treatment)
                ref_n, ref_rate = len(control), sum(o["ok"] for o in control) / len(control)
            elif len(before) >= self.TRANSFER_MIN_EVIDENCE and \
                    len(after) >= self.TRANSFER_MIN_EVIDENCE:
                # OBSERVATIONAL fallback, labelled as such. It is a coarse
                # signal, not evidence of cause: everything else that changed in
                # the same window is confounded with the transfer. Recorded so a
                # reader can tell a correlational verdict from an attributed one
                # instead of both arriving as a bare TRUE.
                inference, basis = "observational", "target-domain outcomes before vs after"
                effect_n, effect_rate = len(after), sum(o["ok"] for o in after) / len(after)
                ref_n, ref_rate = len(before), sum(o["ok"] for o in before) / len(before)
            else:
                unresolved += 1
                continue

            helped = (effect_rate - ref_rate) >= self.TRANSFER_EFFECT_MARGIN
            await registry.resolve_knowledge_transfer(
                row["transfer_id"], helped,
                effectiveness=round(effect_rate - ref_rate, 4),
                evidence={
                    "inference": inference,
                    "basis": basis,
                    "target_domain": target,
                    "effect_n": effect_n, "effect_rate": round(effect_rate, 4),
                    "reference_n": ref_n, "reference_rate": round(ref_rate, 4),
                    "tasks_applied_to": len(touched),
                    "margin_required": self.TRANSFER_EFFECT_MARGIN,
                    "mapping_ids": mapping_ids,
                })
            resolved += 1

        self._transfer_resolution_status = "COMPLETED"
        self._transfer_resolution_counts = {
            "pending": len(pending), "resolved": resolved,
            "insufficient_evidence": unresolved,
        }
        logger.info(
            "[IDLE:DOMAIN] transfer outcomes: %d resolved, %d still awaiting "
            "evidence (of %d unresolved)", resolved, unresolved, len(pending))

    async def _task_outcomes_by_field(self, registry) -> Dict[str, List[Dict[str, Any]]]:
        """Task outcomes grouped by the FIELD domain they bear on.

        An outcome bears on the domain its task acted in (`knowledge_domain_of`);
        an outcome whose task named none bears on no field. The domain is
        resolved through the registry, which answers either level.
        """
        from core.domain.domain_registry import UnresolvedDomainReference

        rows = await self.memory.postgres_storage.db.execute_query(
            """SELECT thinking_state->'raw_event'->>'task_type'        AS task_type,
                      thinking_state->'raw_event'->>'knowledge_domain' AS knowledge_domain,
                      thinking_state->'raw_event'->>'outcome' AS outcome,
                      thinking_state->'raw_event'->>'task_id' AS task_id,
                      created_at
               FROM memory_hot.memory_hot
               WHERE tags @> '["task_outcome"]'::jsonb
               UNION ALL
               SELECT thinking_state->'raw_event'->>'task_type',
                      thinking_state->'raw_event'->>'knowledge_domain',
                      thinking_state->'raw_event'->>'outcome',
                      thinking_state->'raw_event'->>'task_id',
                      created_at
               FROM memory_cold.memory_cold
               WHERE tags @> '["task_outcome"]'::jsonb""",
            fetch_all=True) or []

        by_field: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            domain = self.knowledge_domain_of(row["task_type"], row["knowledge_domain"])
            if not domain or not row["outcome"]:
                continue
            try:
                fields = registry.resolve_domain_reference(
                    domain, require_concepts=True)
            except UnresolvedDomainReference:
                continue
            record = {"at": row["created_at"], "ok": row["outcome"] == "success",
                      "task_id": row["task_id"]}
            for field in fields:
                by_field.setdefault(field.domain_id, []).append(record)
        return by_field

    async def _idle_meta_learning_work(self):
        """
        Evaluate strategy performance across ALL task types (not just RESEARCH).

        NEW: Uses StrategyAdaptationGate for robust threshold-driven adaptation:
          - Binomial confidence interval (95% CI)
          - Minimum sample size (10 executions)
          - Decay-weighted recent performance
          - Variance analysis (instability vs. consistent poor performance)

        Fixes:
          - Previously only evaluated TaskType.RESEARCH
          - Strategy outcomes for other task types were never reviewed
          - Low-performing strategies never flagged for adaptation
          - Arbitrary 0.35 threshold with no statistical rigor
          - No weighting of recent vs. stale outcomes
        """
        from .idle_work_playbook import IdleWorkPlaybook, StrategyAdaptationGate

        # This guarded on self.learning -- the LearningAdapter -- which defines
        # neither evaluate_strategies nor adapt_strategies, so the guard was
        # always False and this entire tier returned before doing any work.
        # Those methods live on MetaLearner, which is self.meta_learning.
        if not self.meta_learning:
            logger.debug("[IDLE:METALEARNING] Meta-learning not available — skipping")
            return

        from .shared_types import TaskType
        from core.learning.meta_learning import TaskFamily

        playbook   = IdleWorkPlaybook()
        task_types = playbook.plan_meta_learning_evaluation()

        logger.info(f"[IDLE:METALEARNING] Evaluating strategies for {len(task_types)} task types")

        evaluation_results: Dict[str, Any] = {}
        adapted = 0

        for tt_value in task_types:
            try:
                tt_enum = TaskType(tt_value)
                family = self._task_family_for(tt_enum)
                evaluation = await self.meta_learning.evaluate_strategies(family)
                logger.debug(f"[IDLE:METALEARNING] {tt_value} ({family.value}): {evaluation}")

                # ──── Robust adaptation gate ────
                # Aggregate from the meta-learner's persisted arms — the ONE
                # metrics authority. The parallel per-process `_strategy_outcomes`
                # dict (an in-memory second store that started empty on every
                # restart) has been RETIRED along with the duplicate
                # `_execute_task_with_singleton` pipeline; execution now runs
                # through the single `_execute_and_validate_task` path.
                total_execs = 0
                total_wins = 0
                for sid in self.meta_learning.task_strategy_map.get(family, []):
                    s = self.meta_learning.strategies[sid]
                    if not str(s.strategy_type).startswith(self.EXECUTOR_NS):
                        continue
                    total_execs += s.trials
                    total_wins += s.successes

                # Get recent outcomes for variance/decay analysis
                recent_outcomes = self._get_recent_task_outcomes(tt_value, limit=10)

                # Check adaptation gate
                should_adapt, gate_analysis = StrategyAdaptationGate.should_adapt(
                    task_type=tt_value,
                    executions=total_execs,
                    wins=total_wins,
                    recent_outcomes=recent_outcomes,
                )

                # Log gate analysis for transparency
                logger.info(f"[IDLE:METALEARNING] {tt_value} adaptation gate: {gate_analysis['decision']}")
                logger.debug(f"  Analysis: {gate_analysis}")

                if should_adapt:
                    # Trigger adaptation
                    try:
                        await self.meta_learning.adapt_strategies(family)
                        adapted += 1

                        reason = gate_analysis.get("adaptation_reason", "low_performance")
                        logger.info(
                            f"[IDLE:METALEARNING] Adapted strategies for {tt_value} "
                            f"(reason: {reason}, execs: {total_execs}, wins: {total_wins})"
                        )

                        # Store detailed adaptation event to META memory
                        await self.store_memory(
                            MemoryType.META,
                            {
                                "event": "strategy_adaptation",
                                "task_type": tt_value,
                                "reason": reason,
                                "gate_analysis": gate_analysis,
                                "timestamp": datetime.now().isoformat(),
                            },
                            importance=0.7,
                            tags=["meta_learning", "strategy_adaptation"],
                        )

                    except Exception as e:
                        logger.warning(f"[IDLE:METALEARNING] Adaptation error for {tt_value}: {e}")
                else:
                    logger.debug(
                        f"[IDLE:METALEARNING] {tt_value} adaptation gate rejected: "
                        f"reason={gate_analysis['checks_failed']}"
                    )

                evaluation_results[tt_value] = gate_analysis

            except Exception as e:
                logger.debug(f"[IDLE:METALEARNING] Error evaluating {tt_value}: {e}")
                evaluation_results[tt_value] = f"error: {e}"

        logger.info(
            f"[IDLE:METALEARNING] Evaluation complete — "
            f"{len(evaluation_results)} types reviewed, {adapted} adapted"
        )

        # Second-order governance: watch whether the meta-learner is degrading
        # its own standards. MetaMetricsMonitor had zero callers, so nothing
        # ever checked the checker -- and it could not have answered anyway
        # (its db handle was an un-awaited coroutine). Both are fixed; this is
        # the call site.
        try:
            from core.learning.meta_metrics_monitor import get_meta_metrics_monitor

            health = await get_meta_metrics_monitor().get_meta_health(self.meta_learning)
            if health:
                level = {"CRITICAL": logger.error, "DEGRADED": logger.warning}.get(
                    health.overall_health, logger.info
                )
                level(
                    f"[IDLE:METALEARNING] Meta-learner health: {health.overall_health} "
                    f"(stability {health.standards_stability_score:.0f}/100, "
                    f"{len(health.alerts)} alerts, {len(health.warnings)} warnings)"
                )
                for a in health.alerts:
                    logger.warning(f"[IDLE:METALEARNING]   alert: {a}")
                if health.overall_health == "CRITICAL" and self.slack_notifier:
                    await self.slack_notifier.send_notification(
                        title="🚨 Meta-Learner Standards Degraded",
                        message=(
                            f"*Health:* {health.overall_health}\n"
                            f"*Stability:* {health.standards_stability_score:.0f}/100\n"
                            + "\n".join(f"• {a}" for a in health.alerts[:5])
                        ),
                        severity="critical",
                        metadata={"subsystem": "meta_learning"},
                    )
        except Exception as e:
            logger.warning(f"[IDLE:METALEARNING] Meta-health check failed: {e}")



    # ── TIER 5: Memory consolidation — multi-strategy with fallbacks ──────────

    async def _idle_abstraction_work(self):
        """Tier: compress repeated experience into persistent schemas.

        The admission policy lives on the memory agent, which owns the data the
        decision depends on. This tier only supplies the schedule and surfaces
        the outcome -- including the reason a run was declined, so a tier that
        never does anything is visible rather than silently idle.
        """
        memory_agent = getattr(self, 'memory_agent', None)
        if memory_agent is None:
            try:
                from core.memory import get_memory_agent
                memory_agent = await get_memory_agent()
            except Exception as e:
                logger.debug(f"[IDLE:ABSTRACTION] Memory agent unavailable: {e}")
                return {'ran': False, 'reason': 'no_memory_agent'}

        if not hasattr(memory_agent, 'form_abstractions_if_due'):
            logger.debug("[IDLE:ABSTRACTION] Memory agent has no abstraction entry point")
            return {'ran': False, 'reason': 'no_entry_point'}

        report = await memory_agent.form_abstractions_if_due()

        if report.get('ran'):
            logger.info(
                f"[IDLE:ABSTRACTION] {report.get('schemas_formed', 0)} schema(s) from "
                f"{report.get('new_memories', 0)} new memories "
                f"(backlog {report.get('backlog', 0)})"
            )
        else:
            logger.debug(f"[IDLE:ABSTRACTION] Skipped: {report.get('reason')}")

        return report

    async def _idle_memory_work(self):
        """
        Run memory consolidation using the ordered strategy list from the playbook.

        Fixes:
          - Previously only tried llm._autonomous_memory_consolidation() — no fallback
          - If that method was absent the tier silently did nothing
          - No tier-upgrade pass (high-importance short-term → long-term)
          - No audit trail of consolidation activity
          - LLM consolidation now guarded with timeout to prevent compute spikes
        """
        from .idle_work_playbook import IdleWorkPlaybook, ConsolidationStrategy

        playbook = IdleWorkPlaybook()

        uptime_hours = (datetime.now() - self.last_cycle_time).total_seconds() / 3600.0

        # No model-driven consolidation exists; consolidation is the memory
        # agent's own tiering, driven by the strategies below.
        strategies = playbook.plan_memory_consolidation(
            llm_has_consolidation_method = False,
            uptime_hours                 = uptime_hours,
        )

        logger.info(
            f"[IDLE:MEMORY] Running consolidation — "
            f"strategies: {[s.value for s in strategies]}"
        )

        consolidated = False
        for strategy in strategies:
            try:
                if strategy == ConsolidationStrategy.TIER_UPGRADE:
                    # Promote high-importance short-term memories to long-term
                    # by searching and re-storing them with elevated importance
                    try:
                        recent = await self.search_memories(
                            query_text   = "important insight knowledge decision",
                            memory_types = [MemoryType.EPISODIC, MemoryType.SEMANTIC],
                        )
                        upgraded = 0
                        # Limit to configured max items per cycle
                        max_items = self.coordinator_config.memory_consolidation_max_items
                        for mem in (recent or [])[:max_items]:
                            importance = getattr(mem, 'importance', 0.0)
                            age_days   = (
                                datetime.now() - getattr(mem, 'created_at', datetime.now())
                            ).days if hasattr(mem, 'created_at') else 0
                            if importance >= 0.7 and age_days >= 1:
                                await self.store_memory(
                                    MemoryType.META,
                                    {
                                        "event":    "tier_upgrade",
                                        "content":  getattr(mem, 'content', {}),
                                        "original_importance": importance,
                                        "timestamp": datetime.now().isoformat(),
                                    },
                                    importance = importance,
                                    tags       = ["consolidation", "tier_upgrade"],
                                )
                                upgraded += 1
                        if upgraded:
                            logger.info(f"[IDLE:MEMORY] Tier upgrade: {upgraded} memories promoted")
                        consolidated = True
                    except Exception as e:
                        logger.debug(f"[IDLE:MEMORY] Tier upgrade error: {e}")

                elif strategy == ConsolidationStrategy.SUMMARY_WRITE:
                    # Audit trail is handled by logger.info below
                    pass

            except Exception as e:
                logger.warning(f"[IDLE:MEMORY] Strategy {strategy.value} error: {e}")

        logger.info(f"[IDLE:MEMORY] Consolidation pass complete (consolidated={consolidated})")

    async def _run_exploration_cycle(self):
        """
        Generate and execute ONE curiosity-driven intrinsic exploration task.

        SINGLETON MODEL: Only one task runs at a time. The Singleton focuses
        its full attention on each task. If the task requires parallel work
        (research, code analysis, multiple investigations), the executor
        deploys sub-agents internally — like how Claude deploys research
        agents, code helpers, and investigators within a single task.

        No fire-and-forget. No concurrent intrinsic tasks.
        """
        try:
            from .shared_types import Task, TaskType, TaskSource, Priority
            from .idle_work_playbook import IdleWorkPlaybook

            playbook = IdleWorkPlaybook()

            # Build set of recent fingerprints to avoid repeating recent work
            # Use ordered list so FIFO trimming works correctly (there are only 4 unique
            # exploration targets — an unordered set would block all 4 permanently).
            recent_fp_list: list = list(getattr(self, '_recent_exploration_fp_list', []))
            recent_fingerprints: set = set(recent_fp_list)

            # Global cap + in-flight dedup are based on the task queue state.
            # This prevents queue spam while a long-running intrinsic task is executing.
            cap = int(getattr(self, "_intrinsic_exploration_cap", 1) or 0)
            if cap == 0:
                logger.debug("🧘 Intrinsic exploration disabled (cap=0)")
                return

            # Curiosity is queue-aware. Exploration is the most discretionary
            # work the system produces, so it is the first thing to stop when
            # the backlog grows -- otherwise the organism keeps inventing work
            # it cannot metabolise, which is debt generation rather than
            # autonomy. Obligatory work (safety, remediation, user-directed)
            # is unaffected; it is admitted at every pressure level.
            _pressure = self.task_queue.pressure()
            if _pressure != "nominal":
                logger.info(
                    f"🧘 Exploration suspended — queue pressure '{_pressure}' "
                    f"(depth {self.task_queue.get_queue_length()}, "
                    f"soft={self.task_queue.soft_limit}, hard={self.task_queue.hard_limit})"
                )
                return

            active_exploration_components: Set[str] = set()
            active_exploration_fps: Set[str] = set()
            active_exploration_count = 0
            try:
                for queued in getattr(self.task_queue, "tasks_by_id", {}).values():
                    if not queued:
                        continue
                    if queued.status not in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
                        continue

                    queued_task = getattr(queued, "task", None)
                    if not queued_task or getattr(queued_task, "source", None) != TaskSource.AUTONOMOUS:
                        continue

                    metadata = getattr(queued_task, "metadata", {}) or {}
                    if metadata.get("intrinsic_kind") != "exploration":
                        continue

                    active_exploration_count += 1
                    comp = metadata.get("target_component")
                    if comp:
                        active_exploration_components.add(comp)
                    fp_active = metadata.get("exploration_fp")
                    if fp_active:
                        active_exploration_fps.add(fp_active)
            except Exception as _scan_err:
                logger.debug(f"Exploration cap scan failed: {_scan_err}")

            if active_exploration_count >= cap:
                logger.debug(
                    f"🧘 Exploration queue full ({active_exploration_count}/{cap}) — skipping exploration cycle"
                )
                return

            # Collect system context and generate goals
            system_context  = await self._collect_system_context_for_goals()

            # ── APPRAISAL -> ARBITER -> BEHAVIOUR ─────────────────────────────
            # The canonical appraisal decides disposition; the arbiter decides
            # what that disposition means here. plan_exploration_config is a
            # translator, not a third interpreter. Breadth was hardcoded to 3.
            _explore_cfg = None
            try:
                # Ask the Self for disposition — it owns appraisal→arbiter and
                # integrates them. The body no longer computes its own stance;
                # it asks its head "what is my disposition now?".
                _directive = self.disposition(
                    slots_available=max(0, cap - len(recent_fp_list) * 0),
                    queue_pressure=_pressure,
                )
                _explore_cfg = playbook.plan_exploration_config(
                    motivation={},
                    active_task_descriptions=recent_fingerprints,
                    exploring_components=set(),
                    max_concurrent=cap,
                    current_intrinsic_count=0,
                    directive=_directive,
                )
                logger.info(
                    "🧭 Behaviour: mode=%s explore=%s goals=%d verify=%.2f %s",
                    _directive.mode, _directive.should_explore,
                    _explore_cfg["max_goals"], _directive.verification_intensity,
                    _directive.reason_codes,
                )
                if not _explore_cfg["should_explore"]:
                    # An arbiter that says "not now" is a real decision, not an
                    # error. Escalation-dominant states must not thrash through
                    # self-directed exploration.
                    logger.info("🧘 Exploration declined by arbiter (%s)", _directive.mode)
                    self._exploration_status = "DECLINED_BY_ARBITER"
                    return
            except Exception as _arb_err:
                # No appraisal yet, or arbitration failed: fall back to the
                # previous fixed breadth rather than blocking exploration.
                logger.debug("Behaviour arbitration unavailable: %s", _arb_err)

            _max_goals = _explore_cfg["max_goals"] if _explore_cfg else 3

            # SELECTION is the unified whole-self frontier (`_intrinsic_pursuits`):
            # epistemic not-knowing lifted by developmental hunger, ranked and
            # routed by frontier. Each pursuit becomes an executable goal via
            # `_pursuit_to_goal` (knowledge → the `understand` loop; capability →
            # `_execute_drive_goal`; environment is closed by its own reaction and
            # skipped here). This REPLACES the old IntrinsicMotivationSystem goal
            # generator as the DECISION — IMS keeps affect/reward/fitness, used
            # elsewhere. `_max_goals` (appraisal-governed breadth) caps how many
            # candidates are considered; pull a wider slate of pursuits so enough
            # survive the environment-skip and the dedup filters below.
            pursuits = await self._intrinsic_pursuits(limit=max(1, _max_goals * 4))
            intrinsic_goals = [g for g in (self._pursuit_to_goal(p) for p in pursuits)
                               if g is not None][:max(1, _max_goals)]

            if not intrinsic_goals:
                logger.debug("🧘 No not-knowing worth pursuing right now — quiet")
                return

            # Pick the first goal that passes dedup filters
            selected_goal = None
            selected_component = None
            selected_fp = None

            for goal in intrinsic_goals:
                _component = goal.metadata.get("target_component") if hasattr(goal, 'metadata') else None

                # In-flight component lock — don't re-explore something already queued/running
                if _component and _component in active_exploration_components:
                    logger.debug(f"⏭️ Skipping {_component}: already queued/in progress")
                    continue

                # Fingerprint dedup
                fp = playbook.description_fingerprint(goal.description)
                if fp in active_exploration_fps:
                    logger.debug(f"⏭️ Skipping duplicate in-flight goal (fp={fp})")
                    continue
                if fp in recent_fingerprints:
                    logger.debug(f"⏭️ Skipping duplicate goal description (fp={fp})")
                    continue
                if fp in getattr(self, '_permanently_failed_fps', set()):
                    logger.debug(f"⏭️ Skipping permanently-failed goal (fp={fp}) — will not re-queue")
                    continue

                selected_goal = goal
                selected_component = _component
                selected_fp = fp
                break

            if not selected_goal:
                logger.debug("🧘 All generated goals were duplicates or filtered — no new tasks")
                return

            # Track as ordered list (FIFO, max 3) so oldest fingerprint rotates out.
            # With only 4 unique exploration targets, a window of 3 guarantees at least
            # one target is always available on every cycle.
            recent_fp_list.append(selected_fp)
            if len(recent_fp_list) > 20:
                recent_fp_list = recent_fp_list[-20:]
            self._recent_exploration_fp_list = recent_fp_list
            self._recent_exploration_fingerprints = set(recent_fp_list)  # kept for compat

            # EVENT-TRIGGERED HYPOTHESIS: the moment a curiosity goal is ADOPTED,
            # make it falsifiable — convert it to a testable hypothesis (through
            # the reasoning authority). Per-goal on adoption, NOT a batch swept on
            # a timer: an adopted exploration goal that carries no falsifiable
            # claim is a wish, not an experiment. Scheduled on the queue
            # authority's background budget so it never slows goal→task, and it is
            # fire-once per adoption (dedup already guaranteed this goal is new).
            try:
                from core.agents.autonomous.queue_authority import get_queue_authority
                _goal_for_hyp = {
                    "id": getattr(selected_goal, "id", None),
                    "description": getattr(selected_goal, "description", ""),
                    "component": selected_component or "system",
                    "objective_type": (selected_goal.metadata.get("objective_type", "explore")
                                       if hasattr(selected_goal, "metadata") else "explore"),
                }
                get_queue_authority().submit(
                    lambda g=_goal_for_hyp: self.intrinsic_motivation.convert_goal_to_hypothesis(g),
                    name="goal_to_hypothesis")
            except Exception as _he:
                logger.debug("goal→hypothesis scheduling skipped: %s", _he)

            # Build the intrinsic task.
            # The sink is local, so this decision can only ever be bound to the
            # task built from it — no shared slot for a concurrent selection to
            # overwrite, and no stale id to leak onto the next task.
            _type_decision: Dict[str, Any] = {}
            task_type = await self._select_adaptive_task_type(
                selected_goal.description, _decision_sink=_type_decision
            )
            if task_type is None:
                logger.info(
                    "No task type passes the production gate (%s); not queueing "
                    "a task for goal %s this cycle",
                    "; ".join(f"{k}: {v}" for k, v in
                              (_type_decision.get("gate_blocked") or {}).items()),
                    getattr(selected_goal, "id", "?"))
                return
            # PERSIST THE GOAL BEFORE TURNING IT INTO A TASK.
            #
            # The four intrinsic generators build real Goal objects, and every
            # one of them was discarded here: the description was copied onto a
            # Task and the Goal itself never reached create_goal, so it was
            # never written to unified.goals and the PlanningEngine never saw
            # it. Motivation went straight to execution, skipping planning
            # entirely, and the goal store stayed empty while 886 intrinsic
            # motivation rows accumulated. Verified by running each generator
            # against the live database: create_goal added a row, all four
            # intrinsic generators added none.
            #
            # Persisting first also means the task and the goal share an id, so
            # the outcome of the task is attributable to the goal that produced
            # it rather than being an orphan.
            persisted_goal = await self.planning.create_goal(
                selected_goal.description,
                Priority.LOW,
                intrinsic_values={
                    "expected_novelty": getattr(selected_goal, "expected_novelty", 0.5),
                    "expected_competence_gain": getattr(
                        selected_goal, "expected_competence_gain", 0.5),
                    "curiosity_value": getattr(selected_goal, "curiosity_value", 0.5),
                    "intrinsic_reward_potential": getattr(
                        selected_goal, "intrinsic_reward_potential", 0.5),
                },
            )
            if persisted_goal is None:
                # A goal that could not be stored must not become a task: the
                # task would run, complete, and have nothing to report against.
                logger.warning(
                    "Intrinsic goal could not be persisted (%s); not queueing a "
                    "task for it", selected_goal.description[:80])
                return

            intrinsic_task = Task(
                id          = persisted_goal.id,
                type        = task_type,
                description = persisted_goal.description,
                priority    = Priority.LOW,
                source      = TaskSource.AUTONOMOUS,
                created_by  = "exploration_loop",
            )
            intrinsic_task.metadata["goal_id"] = persisted_goal.id

            # Mark as intrinsic exploration for global cap/dedup (Known Gap 25.2)
            intrinsic_task.metadata["intrinsic_kind"] = "exploration"
            intrinsic_task.metadata["exploration_fp"] = selected_fp

            # Carry the DRIVE and its concrete target forward. A competence or
            # confidence goal names a real operator/domain to act on and re-induce;
            # dropping this metadata is what left those goals as free-form
            # descriptions the generic executor could not act on. The dedicated
            # handler (_execute_drive_goal) reads exactly these fields.
            _gm = selected_goal.metadata if hasattr(selected_goal, "metadata") else {}
            for _k in ("drive", "domain_id", "predicate", "arity", "rule_id",
                       "scope", "positive_root_count"):
                if _k in _gm:
                    intrinsic_task.metadata[_k] = _gm[_k]

            # Carry the decision forward so _check_task_completions can reward it.
            # Selecting a task type without ever reporting how it turned out is a
            # half loop: the bandit would sample forever from an untouched prior.
            intrinsic_task.metadata["adaptive_task_type"] = task_type.value
            intrinsic_task.metadata["adaptive_selected_at"] = datetime.now().isoformat()
            # Carries the decision-record id so the outcome joins back to the
            # propensities and context captured at decision time.
            intrinsic_task.metadata["decision_id"] = _type_decision.get("decision_id")

            # Attach uncertainty metadata for closed-loop completion gate
            if selected_component:
                u_before = selected_goal.metadata.get("uncertainty_before", 0.0)
                intrinsic_task.metadata["target_component"] = selected_component
                intrinsic_task.metadata["uncertainty_before"] = u_before
                intrinsic_task.success_criteria = {
                    "uncertainty_delta_max": -(0.1 * u_before) if u_before > 0 else -0.05
                }

            # Add to task queue instead of executing directly
            logger.info(f"🔬 Queueing exploration task: {selected_goal.id}")
            await self.task_queue.add_task(intrinsic_task, priority=Priority.LOW)
            # Note: Global cap + in-flight dedup are derived from task_queue state; no sticky locks.

        except Exception as e:
            logger.error(f"Error in exploration cycle: {e}")
            await self._handle_error(e, "exploration_cycle")

    async def _propose_directive_improvements(self) -> None:
        """The substrate proposing its own operating directives from REAL measured
        signals (self-optimization). Each proposal's parameters are DERIVED from a
        measured signal — never invented — and gated through runtime governance →
        constitution before it can exist. Only proposes when a signal indicates a
        concrete adjustment AND no active directive already encodes it, so it never
        churns. After proposing, promotes the drafts the LEARNING AUTHORITY has
        shown to work (DRAFT → ACTIVE on measured effectiveness).
        """
        ds = getattr(self, "directive_system", None)
        if ds is None:
            return
        from .directive_types import DirectiveCategory

        # ── RESOURCE_ALLOCATION — from the task queue's MEASURED failure rate ──
        # High failure under the current cap → back off; reliably clear with a
        # backlog → scale up. Params are the measured decision, not a guess.
        try:
            qm = self.task_queue.get_metrics()
            completed = int(qm.get("tasks_completed", 0))
            failed = int(qm.get("tasks_failed", 0))
            finished = completed + failed
            if finished >= 20:  # enough evidence to act on
                fail_rate = failed / finished
                current = self._effective_max_parallel()
                proposed = None
                if fail_rate > 0.30 and current > 1:
                    proposed = current - 1
                elif (fail_rate < 0.05 and current < 8
                      and self.task_queue.get_queue_length() > current):
                    proposed = current + 1
                if proposed is not None:
                    active_params, _ = await ds.select_guidance(
                        DirectiveCategory.RESOURCE_ALLOCATION)
                    if active_params.get("max_parallel_tasks") != proposed:
                        await ds.create_directive_with_governance(
                            directive_name=f"resource-cap-{proposed}",
                            category=DirectiveCategory.RESOURCE_ALLOCATION,
                            directive_text=(f"Cap concurrent acting at {proposed} "
                                            f"(measured failure_rate={fail_rate:.2f})"),
                            directive_parameters={"max_parallel_tasks": proposed},
                            created_by="self_optimization")
        except Exception as e:
            logger.debug("resource directive proposal skipped: %s", e)

        # ── EXPLORATION_BALANCE — from the MEASURED exploration quota ──
        # Persistently over the exploration budget → favour exploiting (raise the
        # exploit threshold); the threshold value tracks the measured overshoot.
        try:
            quota = self._calculate_exploration_quota()
            limit = float(self.config.get("exploration_quota_limit", 0.10))
            if quota is not None and quota > limit * 1.5:
                proposed_thr = round(min(0.95, 0.7 + quota), 2)
                active_params, _ = await ds.select_guidance(
                    DirectiveCategory.EXPLORATION_BALANCE)
                if active_params.get("exploit_threshold") != proposed_thr:
                    await ds.create_directive_with_governance(
                        directive_name=f"exploit-threshold-{proposed_thr}",
                        category=DirectiveCategory.EXPLORATION_BALANCE,
                        directive_text=(f"Favour exploiting learned competence "
                                        f"(exploration quota {quota:.2f} over "
                                        f"limit {limit:.2f})"),
                        directive_parameters={"exploit_threshold": proposed_thr},
                        created_by="self_optimization")
        except Exception as e:
            logger.debug("exploration directive proposal skipped: %s", e)

        # Promote the drafts the learning authority has validated.
        try:
            promoted = await ds.promote_eligible_directives()
            if promoted:
                logger.info("[SELF_OPT] %d directive(s) promoted by the learning "
                            "authority", promoted)
        except Exception as e:
            logger.debug("directive promotion skipped: %s", e)

    async def _handle_error(self, error: Exception, source: str):
        """
        Handle errors by creating fix tasks directly.
        No intrinsic motivation. No hypothesis testing. Just fix it.
        """
        import traceback as tb_module
        import uuid
        from .shared_types import Task, TaskType, Priority, TaskSource

        error_type = type(error).__name__
        error_msg = str(error)
        traceback_str = tb_module.format_exc()[:500]

        # Create fix task directly (TaskSource.SYSTEM, not AUTONOMOUS)
        fix_task = Task(
            id=f"fix_{uuid.uuid4().hex[:12]}",
            type=TaskType.EXECUTION,  # Fix task
            description=f"Fix {error_type} in {source}: {error_msg}",
            priority=Priority.HIGH,  # Errors are high priority
            source=TaskSource.SYSTEM,  # System-generated, not autonomous
            created_by="error_handler",
            metadata={
                'error_type': error_type,
                'error_message': error_msg,
                'source': source,
                'traceback': traceback_str,
                'timestamp': datetime.now().isoformat(),
                'is_error_fix': True
            }
        )

        # Add to task queue immediately
        await self.task_queue.add_task(fix_task)
        logger.info(f"🔧 Created fix task {fix_task.id} for {error_type} in {source}")


    # Horizon → seconds after which a prediction becomes checkable.
    _HORIZON_SECONDS = {
        "immediate": 30,
        "short_term": 300,
        "medium_term": 3600,
        "long_term": 86400,
    }

    async def _observe_system_performance(self) -> Optional[float]:
        """The observable a SYSTEM_PERFORMANCE prediction is scored against.

        Fraction of components reporting healthy, in [0,1] to match the
        accuracy arithmetic in validate_prediction.
        """
        if not self.health_monitor:
            return None
        try:
            health = await self.health_monitor.get_system_health()
            total = health.get("component_count") if health else None
            if not total:
                return None
            return health["healthy_components"] / float(total)
        except Exception as e:
            logger.debug(f"Could not observe system performance: {e}")
            return None

    async def _predict_and_resolve_system_state(self):
        """Close the world-model loop: predict → wait → observe → score.

        PredictiveIntelligenceSystem.validate_prediction() computes real error
        and confidence calibration, and had zero callers -- as did both
        prediction *producers*. Torin therefore never predicted anything and
        never compared a prediction to reality, so its forecasting was
        analytics rather than a world model that can be wrong and learn from it.

        Resolution happens first so a prediction is never scored against the
        same observation that produced it.
        """
        if not self.intelligence:
            return

        # ── Resolve any predictions whose horizon has elapsed ──
        active = dict(getattr(self.intelligence, "active_predictions", {}) or {})
        now = datetime.now()
        for pid, prediction in active.items():
            try:
                due_after = self._HORIZON_SECONDS.get(prediction.horizon.value, 300)
                if (now - prediction.timestamp).total_seconds() < due_after:
                    continue

                actual = await self._observe_system_performance()
                if actual is None:
                    continue

                result = await self.intelligence.validate_prediction(pid, actual)
                logger.info(
                    "🔮 Prediction %s resolved: predicted=%.3f actual=%.3f "
                    "accuracy=%.3f calibration=%.3f",
                    pid,
                    float(prediction.predicted_value)
                    if isinstance(prediction.predicted_value, (int, float)) else -1.0,
                    actual, result.accuracy, result.confidence_calibration,
                )
                await self._persist_prediction_result(prediction, result, actual)
            except Exception as e:
                logger.warning(f"Could not resolve prediction {pid}: {e}")

        # ── Make a fresh prediction to be scored on a later cycle ──
        try:
            from core.intelligence import PredictionDomain, PredictionHorizon

            await self.intelligence.generate_comprehensive_prediction(
                PredictionDomain.SYSTEM_PERFORMANCE,
                PredictionHorizon.SHORT_TERM,
                await self._decision_context("system performance forecast"),
            )
        except Exception as e:
            logger.warning(f"Could not generate system-performance prediction: {e}")

    async def _persist_prediction_result(self, prediction, result, actual) -> None:
        """Store the scored prediction so calibration outlives the process.

        active_predictions is an in-memory dict; without this the entire
        accuracy record dies with the process and the world model can never
        show whether it is getting better.
        """
        try:
            from core.database import get_database_manager
            db = get_database_manager()
            await db.execute_query(
                """
                CREATE TABLE IF NOT EXISTS prediction_results (
                    prediction_id   VARCHAR(128) PRIMARY KEY,
                    domain          VARCHAR(64) NOT NULL,
                    horizon         VARCHAR(32) NOT NULL,
                    predicted_value DOUBLE PRECISION,
                    actual_value    DOUBLE PRECISION,
                    confidence      NUMERIC(6,4),
                    accuracy        NUMERIC(6,4),
                    calibration     NUMERIC(6,4),
                    predicted_at    TIMESTAMP,
                    resolved_at     TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """,
                commit=True,
            )
            await db.execute_query(
                """
                INSERT INTO prediction_results (
                    prediction_id, domain, horizon, predicted_value, actual_value,
                    confidence, accuracy, calibration, predicted_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (prediction_id) DO NOTHING
                """,
                (
                    result.prediction_id,
                    prediction.domain.value,
                    prediction.horizon.value,
                    float(prediction.predicted_value)
                    if isinstance(prediction.predicted_value, (int, float)) else None,
                    float(actual),
                    float(prediction.confidence),
                    float(result.accuracy),
                    float(result.confidence_calibration),
                    prediction.timestamp,
                ),
                commit=True,
            )
        except Exception as e:
            logger.warning(f"Could not persist prediction result: {e}")

    async def _decision_context(self, description: str = "") -> Dict[str, Any]:
        """Snapshot the state a decision is being made in.

        Recorded alongside the decision so credit can later be assigned
        conditionally -- "RESEARCH works 89% of the time *under high epistemic
        uncertainty on an unknown subsystem*" rather than "RESEARCH works 74%
        of the time". Every field here is already computed elsewhere in the
        coordinator each cycle and then discarded; this is the first thing that
        keeps it.

        Deliberately cheap: reads cached state only, never triggers a scan.
        """
        dims = (getattr(self, "_current_motivation", {}) or {}).get("dimensions", {})
        health = (getattr(self, "_idle_last_health_snapshot", {}) or {})

        return {
            "description_len": len(description or ""),
            "curiosity": dims.get("curiosity"),
            "novelty": dims.get("novelty"),
            "competence": dims.get("competence"),
            "impact": dims.get("impact"),
            "health_components_total": health.get("components_total"),
            "health_unhealthy_total": health.get("unhealthy_total"),
            "active_goals": len(self.system_state.active_goals)
            if getattr(self, "system_state", None) else None,
            "active_tasks": len(self.system_state.active_tasks)
            if getattr(self, "system_state", None) else None,
            "idle_cycles": getattr(self, "_idle_count", None),
            "queue_depth": self.task_queue.queue.qsize()
            if getattr(self, "task_queue", None) else None,
            "recent_failure_fps": len(getattr(self, "_permanently_failed_fps", set())),
            "uptime_s": int(
                datetime.now().timestamp() - float(getattr(self, "_started_at_ts", 0) or 0)
            ) if getattr(self, "_started_at_ts", None) else None,
        }

    def _task_family_for(self, task_type) -> 'TaskFamily':
        """Map a coordinator TaskType onto the meta-learner's TaskFamily.

        The coordinator speaks TaskType (11 values, about what work to do);
        MetaLearner keys strategies by TaskFamily (8 values, about the kind of
        learning problem). Nothing translated between them, which is why every
        cross-system call passed the wrong vocabulary.

        DELEGATED, NOT DUPLICATED. The table now lives beside TaskFamily as
        `meta_learning.TASK_TYPE_TO_FAMILY`, because UnifiedLearningSystem needs
        the same translation and could not reach a dict held in this class.

        A KeyError is still raised for an unknown type, as before: this caller
        has a real TaskType in hand, so an unmapped one is a defect in the map
        and must not be quietly turned into some default family.
        """
        from core.learning.meta_learning import task_family_for_task_type

        family = task_family_for_task_type(task_type)
        if family is None:
            raise KeyError(
                f"No TaskFamily mapped for task type {task_type!r}; add it to "
                f"meta_learning.TASK_TYPE_TO_FAMILY")
        return family

    def _operating_verdict(
        self, result: Any, confidence: Optional[float], is_complete: bool,
    ) -> Dict[str, Any]:
        """Did this work OPERATE CORRECTLY in its domain, and is the answer
        evidence about that at all?

        THE SUBSTRATE'S OWN BELIEF DECIDES, and the world is how it comes to hold
        it. The credit is read from the completion belief -- "the goal holds" --
        which `_observe_completion_evidence` has just moved on independent
        groundings, including a FRESH re-observation of what the work claimed.
        For a driven plan what it claimed is its goal conditions, so that
        grounding is the substrate believing its INTENTION was realized.

        Credit does not go AROUND the belief to read the reconciled intent
        directly. An intention the substrate does not believe it realized is not
        one it may count as having operated correctly, and routing past the
        epistemic authority would leave two accounts of the same act -- the
        thing the authority pattern exists to prevent. What the reconciled intent
        contributes is what the belief is GROUNDED IN, which is recorded.

        ELIGIBILITY IS A SEPARATE QUESTION, settled first: operating reliability
        governs whether the substrate may act in a domain at all, so a number
        that cannot tell "I acted and was wrong" from "I never acted" is not a
        measurement of operating. Work that operated nothing -- a goal that would
        not plan, an operator that refused because its authority no longer held,
        a runtime outcome that could not tell -- establishes nothing and is
        denied. Measured before this existed: an unplannable goal recorded an
        operating loss, so a knowledge deficit raised the very bar that governs
        whether the substrate may act there and learn.

        WHERE BELIEF AND WORLD DISAGREE, NEITHER IS OVERRULED. A world verdict
        that contradicts the belief it just informed is an unresolved epistemic
        conflict, and crediting either side would record a confidence the
        substrate does not have. It is denied and said out loud.
        """
        from core.learning.meta_learning import OutcomeClass

        def verdict(success, outcome_class, read_from):
            return {"success": bool(success), "outcome_class": outcome_class,
                    "read_from": read_from}

        if not isinstance(result, dict):
            return verdict(bool(is_complete), OutcomeClass.INDETERMINATE,
                           "no result to read")

        # ── eligibility: did this work establish anything about operating? ──
        if result.get("planning_status") or result.get("refused"):
            return verdict(False, OutcomeClass.INSUFFICIENT_EVIDENCE,
                           "no operation was performed")

        from core.execution.effect_verification import RuntimeOutcome
        runtime_outcome = result.get("runtime_outcome")
        if runtime_outcome == RuntimeOutcome.INDETERMINATE.value:
            return verdict(False, OutcomeClass.INSUFFICIENT_EVIDENCE,
                           "runtime evidence was indeterminate")

        if confidence is None:
            return verdict(False, OutcomeClass.INDETERMINATE,
                           "no completion posterior was formed")

        # ── the verdict: what the substrate BELIEVES about the goal it pursued ──
        # The 0.5 line is the posterior crossing into "the evidence supports the
        # goal" -- a lower and more appropriate bar than the cautious
        # done-acceptance (~0.95) that governs whether to STOP working.
        believed = confidence >= 0.5

        intent_outcome = result.get("intent_outcome")
        world_verdict = None
        grounded_in = None
        if isinstance(intent_outcome, dict) and "matched_aim" in intent_outcome:
            world_verdict = bool(intent_outcome["matched_aim"])
            grounded_in = "the reconciled intent"
        elif runtime_outcome:
            world_verdict = runtime_outcome == RuntimeOutcome.CONFIRMATION.value
            grounded_in = "runtime evidence"

        if world_verdict is not None and world_verdict != believed:
            logger.warning(
                "operating credit denied: the substrate believes the goal %s "
                "(posterior %.3f) while %s says the aim was %s. A belief at odds "
                "with the observation that informed it is not a measurement of "
                "operating correctly.",
                "holds" if believed else "does not hold", confidence, grounded_in,
                "realized" if world_verdict else "not realized")
            return verdict(False, OutcomeClass.INDETERMINATE,
                           f"belief and {grounded_in} disagree")

        if grounded_in is None:
            # No world verdict to ground it: the belief is all the substrate has,
            # and it is recorded as that rather than as an observation.
            return verdict(
                believed,
                OutcomeClass.SUCCESS if believed else OutcomeClass.STRATEGY_FAILURE,
                "completion belief")
        return verdict(
            believed,
            OutcomeClass.SUCCESS if believed else OutcomeClass.EXECUTION_FAILURE,
            f"completion belief, grounded in {grounded_in}")

    async def _record_adaptive_type_outcome(
        self,
        task,
        success: bool,
        outcome_class: str = "executed",
        time_ms: float = 0.0,
    ) -> None:
        """Report the outcome of an adaptive task-type choice to the meta-learner.

        The reward half of _select_adaptive_task_type. Only tasks that carry the
        decision (exploration tasks) are recorded -- every other task had its
        type assigned elsewhere, so there is no decision to credit.

        ``success`` is passed in rather than derived from task.status because
        the authoritative terminal outcome differs by path: the queue path
        establishes it as ``is_complete`` (verification state + uncertainty
        gate) inside _execute_and_validate_task, well before any status field
        is written. Deriving it here would credit the wrong signal.

        ``outcome_class`` distinguishes a task that ran and failed from one
        that safety refused to run. Both are negative evidence for the arm, but
        they are different kinds of negative, and the context records which.
        """
        # Credit the ACTIVE resource_allocation directive (if one is in force) for
        # this task's outcome — the acting cap it sets affects ALL tasks, so every
        # outcome is evidence about it. Done before the adaptive-type gate below so
        # it fires for every task, not only exploration ones. The learning
        # authority owns the credit (log_directive_application → MetaLearner arm).
        if getattr(self, "_directive_resource_id", None) and getattr(self, "directive_system", None):
            try:
                await self.directive_system.log_directive_application(
                    directive_id=self._directive_resource_id,
                    decision_id="",
                    decision_context={"task_id": getattr(task, "id", None),
                                      "outcome_class": outcome_class},
                    outcome_metrics={"outcome_quality": 1.0 if success else 0.0,
                                     "success": bool(success), "time_ms": time_ms})
            except Exception as _de:
                logger.debug("resource directive credit skipped: %s", _de)

        chosen = (task.metadata or {}).get("adaptive_task_type")
        if not chosen or not self.meta_learning:
            return

        from core.learning.meta_learning import TaskFamily
        from core.learning.meta_learning import OutcomeClass

        # Map the coordinator's terminal states onto the credit taxonomy. Only
        # outcomes that are genuinely evidence about the task-type choice may
        # move its posterior.
        klass = {
            "verified": OutcomeClass.SUCCESS,
            "unverified": OutcomeClass.STRATEGY_FAILURE,
            "safety_blocked": OutcomeClass.SAFETY_BLOCKED,
            "infrastructure": OutcomeClass.INFRASTRUCTURE_FAILURE,
            "invalid": OutcomeClass.INVALID_TASK,
        }.get(outcome_class, OutcomeClass.INDETERMINATE)

        try:
            await self.meta_learning.track_learning_outcome(
                task_type=TaskFamily.CONTROL,
                strategy_type=f"{self.ADAPTIVE_TYPE_NS}{chosen}",
                success=success,
                performance_score=1.0 if success else 0.0,
                time_ms=time_ms,
                outcome_class=klass,
                context={
                    "task_id": task.id,
                    "outcome_class": outcome_class,
                    "source": "adaptive_task_type",
                },
                decision_id=(task.metadata or {}).get("decision_id"),
            )
        except Exception as e:
            logger.warning("Could not record adaptive task-type outcome: %s", e)

    async def _select_adaptive_task_type(
        self,
        description: str,
        _decision_sink: Optional[Dict[str, Any]] = None,
    ) -> Optional['TaskType']:
        """
        Adaptively select task type based on learning history.
        Replaces static task type assignment.

        None when no task type is fit to choose: every arm failed the
        production gate (reasons in `_decision_sink["gate_blocked"]`). The
        caller does not create the task. A keyword match on the description used
        to answer instead -- a guess wearing the shape of a decision.

        `_decision_sink` receives the decision-record id so the caller can bind
        it to the task it is about to create. It replaces a single
        `self._pending_decision_id` slot, which had two failure modes:

          * orphaning — a decision made on a path that never reached the
            stamping site was recorded with a propensity and could never be
            closed. `tasktype` shows 123 decisions and 2 closed.
          * MIS-ATTRIBUTION, which is worse — the slot was cleared only at the
            stamp, so an early return in between left a stale id that the NEXT
            task picked up. Credit then lands on a decision that produced no
            part of that outcome, and the posterior moves on evidence from
            somewhere else entirely.

        A per-call sink cannot be crossed by another selection, which matters
        now that tasks execute concurrently.
        """
        from .shared_types import TaskType
        from core.learning.meta_learning import TaskFamily

        # Choosing which kind of task to run is a CONTROL-family decision, and
        # the coordinator's TaskType set is its strategy vocabulary.
        if not self._adaptive_types_registered:
            for t in TaskType:
                await self.meta_learning.register_strategy(
                    task_type=TaskFamily.CONTROL,
                    strategy_type=f"{self.ADAPTIVE_TYPE_NS}{t.value}",
                    parameters={"source": "coordinator_task_type"},
                )
            self._adaptive_types_registered = True

        sink: Dict[str, Any] = {}
        strategy = await self.meta_learning.select_strategy(
            TaskFamily.CONTROL,
            exploration_quota_used=self._calculate_exploration_quota(),
            strategy_prefix=self.ADAPTIVE_TYPE_NS,
            decision_context=await self._decision_context(description),
            _decision_sink=sink,
        )
        self._record_exploration_decision(strategy)
        if strategy is None:
            if _decision_sink is not None and "gate_blocked" in sink:
                _decision_sink["gate_blocked"] = sink["gate_blocked"]
            return None
        if _decision_sink is not None:
            _decision_sink["decision_id"] = sink.get("decision_id")
        return TaskType(str(strategy.strategy_type)[len(self.ADAPTIVE_TYPE_NS):])

    #: The prior for a freshly-minted completion belief — LOW, meaning "the goal
    #: does not yet hold." Evidence must EARN the rise to done; a fresh
    #: observation would otherwise start near its own quality (verified), so a
    #: single success would read as complete. Minting low forces accumulation.
    COMPLETION_PRIOR = 0.15

    def _completion_domain(self, task) -> str:
        """A TASK-SPECIFIC domain for completion beliefs, their outcome memories,
        and recall — the OPERATION the task performs, so completions bucket by what
        the task DOES (all `write_file` tasks together, distinct from `copy_file`,
        research, etc.) instead of a broad linguistic category. Recall then scopes
        to genuinely-similar operations. A task that declares no tools buckets by
        the domain it acts in, else by its task type."""
        params = (task.metadata or {}).get("parameters") or {}
        plan = params.get("tool_plan")
        if plan is None and params.get("tool"):
            plan = [{"tool": params["tool"]}]
        tools = sorted({(s or {}).get("tool") for s in (plan or []) if (s or {}).get("tool")})
        if tools:
            return "op:" + "+".join(tools)
        domain = self._task_domain(task)
        if domain:
            # The field key ("security"), as tags spell it: `domain_<key>`.
            return domain[len("domain_"):] if domain.startswith("domain_") else domain
        return f"task:{getattr(getattr(task, 'type', None), 'value', 'unknown')}"

    def _derive_completion_anchor(self, task) -> str:
        """The completion proposition `G` for a task — HYBRID authorship.

        Planner-supplied when the goal is explicit (`provenance["goal_conditions"]`,
        or state conditions read from the description); reader-authored from the
        task's own stated intent otherwise. Always a concrete claim the belief
        system can hold and re-observation can confirm. Faithful to intent: the
        authored form IS the task's stated goal as a proposition — never a
        fabricated criterion. Re-observation grounds either form, so a loosely
        authored anchor still cannot reach done without real confirming evidence.
        """
        prov = getattr(task, "provenance", None) or {}
        conds = prov.get("goal_conditions")
        if not conds:
            try:
                conds = self.extract_state_conditions(getattr(task, "description", "") or "")
            except Exception:
                conds = None
        if conds:
            joined = " and ".join(str(c).strip() for c in conds if str(c).strip())
            if joined:
                return f"the goal holds: {joined}"
        desc = (getattr(task, "description", "") or "").strip()
        if desc:
            return f"the goal of the task is achieved: {desc}"
        return f"task {getattr(task, 'id', '?')} is complete"

    def _mint_completion_belief(self, task, anchor: str):
        """Create the task's completion belief at the LOW prior, in the task's OWN
        domain, through the one learning authority. Stashes the belief id and the
        anchor on the task so the evidence updates and the completion decision all
        move the SAME belief. Returns the belief (or None if the authority is
        unavailable — the caller then falls back to the legacy decision, never a
        fake completion)."""
        try:
            domain = self._completion_domain(task)
            belief = self.learning.create_belief(
                anchor, domain=domain, prior=self.COMPLETION_PRIOR, source="completion")
        except Exception as e:
            logger.warning("could not mint completion belief for %s: %s",
                           getattr(task, "id", "?"), e)
            return None
        if task.metadata is None:
            task.metadata = {}
        task.metadata["completion_belief_id"] = belief.belief_id
        task.metadata["completion_anchor"] = anchor
        return belief

    #: Acceptance for DONE — the substrate must be STRONGLY confident the goal
    #: holds. NOT the belief system's ordinary 0.7 "confident-true" line: a task is
    #: only DEFENSIBLY complete at >= 0.95, raised toward 0.99 by the self's
    #: standing caution. Verified against the belief math: one strong observation
    #: reaches ~0.72, so a single signal NEVER completes — DONE demands
    #: CORROBORATION (>= 2 independent grounded confirmations), and any real
    #: failure among the effects holds the belief below the bar.
    COMPLETION_ACCEPT = 0.95
    COMPLETION_ACCEPT_MAX = 0.99

    #: Evidence strengths (calibrated against the belief math): each real EFFECT (a
    #: succeeded tool, a learned+stored fact) and the handler's re-observation
    #: verdict are strong grounded confirmations; a failed effect / non-verified
    #: state / no result is strong evidence AGAINST; a bare success flag with no
    #: re-observation is WEAK (cannot approach the bar even accumulated).
    _EV_EFFECT = 0.9
    _EV_VERIFIED = 0.9
    _EV_AGAINST = 0.85
    _EV_DECLARED = 0.3

    async def _observe_completion_evidence(self, task, result) -> None:
        """Move the completion belief on INDEPENDENT groundings only.

        Completion is "how many independent ways does the substrate know the goal
        is true," not "how many mechanisms reported success." So we gather DID
        evidence (the intervention's own report, through the action-runtime
        channel) and SAW evidence (a FRESH, post-intervention re-observation of the
        world), drop derived items, collapse correlated ones (same causal lineage)
        to their strongest, and feed ONE belief update per genuinely-independent
        grounding. A task that only ACTED (DID ≈ 0.72) has one grounding and cannot
        reach the bar — the high threshold itself forces the fresh SAW that
        compounds to done. Isolated; never fabricates. Groundings are stashed on
        the task for audit and for the outcome memory."""
        belief_id = (task.metadata or {}).get("completion_belief_id")
        if not belief_id:
            return
        try:
            evidence = self._gather_did_evidence(task, result)
            evidence += await self._saw_reobserve(task, result)
            groundings = self._independent_groundings(evidence)
            for g in groundings:
                self.learning.update_belief(
                    belief_id,
                    {"quality": g.strength,
                     "source": f"{g.epoch}:{g.observation_channel}:{g.provenance_key}"},
                    evidence_supports=g.polarity)
            if task.metadata is None:
                task.metadata = {}
            task.metadata["completion_evidence"] = [
                {"epoch": g.epoch, "channel": g.observation_channel,
                 "provenance": g.provenance_key, "supports": g.polarity,
                 "strength": round(g.strength, 3)} for g in groundings]
            # The completion belief is decision-critical: persist its post-evidence
            # state DURABLY (awaited, committed) so a completion — or a reversal
            # where SAW contradicted DID — survives a restart, not fire-and-forget.
            await self.learning.flush_belief(belief_id)
        except Exception as e:
            logger.warning("completion-evidence update failed for %s: %s",
                           getattr(task, 'id', '?'), e)

    def _gather_did_evidence(self, task, result) -> List["Evidence"]:
        """DID — the intervention's OWN report that it produced the effect, through
        the action-runtime channel. Multiple tools against the SAME resource are
        consequences of one causal event (same lineage → they collapse). The
        aggregate 'verified' verdict is DERIVED from the tool successes, so it is
        emitted derived=True and dropped before compounding."""
        if not isinstance(result, dict):
            return []
        prop = (task.metadata or {}).get("completion_anchor", "goal")
        ev: List["Evidence"] = []
        tools = result.get("tools_run") or []
        if tools:
            for r in tools:
                if not isinstance(r, dict) or not r.get("tool"):
                    continue
                # Score the intervention by whether it achieved its INTENDED
                # target-state, not the raw success flag: a removal that "fails"
                # because the target was already gone has achieved the absence.
                achieved = self._did_intent_achieved(r)
                res = r.get("resource") or f"tool:{r.get('tool')}"
                ev.append(Evidence(prop, achieved, self._EV_EFFECT if achieved else self._EV_AGAINST,
                                   res, "tool_runtime", f"did:{res}", "did"))
            # the aggregate verdict is the AND of the above — derived, never counted.
            ev.append(Evidence(prop, result.get("verification_state") == "verified",
                               self._EV_VERIFIED, "aggregate", "tool_runtime",
                               "did:aggregate", "did", derived=True))
            return ev
        # No granular effects: the handler's report IS the single DID grounding.
        vs = result.get("verification_state")
        method = result.get("method", "handler")
        if vs == "verified":
            ev.append(Evidence(prop, True, self._EV_VERIFIED, f"handler:{method}",
                               "handler_report", f"did:{method}:{task.id}", "did"))
        elif vs in ("failed", "blocked", "in_progress", "partially_complete"):
            ev.append(Evidence(prop, False, self._EV_AGAINST, f"handler:{method}",
                               "handler_report", f"did:{method}:{task.id}", "did"))
        elif result.get("success") is True:
            ev.append(Evidence(prop, True, self._EV_DECLARED, "declared",
                               "handler_report", f"did:declared:{task.id}", "did"))
        else:
            ev.append(Evidence(prop, False, self._EV_AGAINST, "no_result",
                               "handler_report", f"did:none:{task.id}", "did"))
        return ev

    def _did_intent_achieved(self, r: Dict[str, Any]) -> bool:
        """Did this tool call achieve its INTENDED target-state? For most tools
        that is plain success. For a removal (wants-absent), success OR a failure
        whose cause is that the target was already gone both leave the target
        absent — so the intent is met. A removal blocked with the target still
        present (e.g. permission denied) is NOT achieved."""
        ok = bool(r.get("success"))
        if not ok and r.get("tool") in _TOOL_WANTS_ABSENT:
            err = str(r.get("error") or "").lower()
            return any(sig in err for sig in _ALREADY_ABSENT_SIGNALS)
        return ok

    async def _saw_reobserve(self, task, result) -> List["Evidence"]:
        """SAW — a FRESH, independent measurement of the resulting world state,
        taken AFTER the intervention, that does NOT consume the action's cached
        result or the derived verdict (distinct causal lineage from DID → it
        compounds). Observes the filesystem (a fresh existence check of each
        intervention target) and learned-knowledge persistence (a fresh retrieval
        by claim). A goal with no independently-observable state yields no SAW —
        and then the task cannot reach done on DID alone, the honest consequence."""
        import os
        if not isinstance(result, dict):
            return []
        prop = (task.metadata or {}).get("completion_anchor", "goal")
        saw: List["Evidence"] = []
        seen = set()
        for r in (result.get("tools_run") or []):
            if not isinstance(r, dict):
                continue
            target = r.get("intervention_target")
            if not target or target in seen:
                continue
            seen.add(target)
            try:
                exists = os.path.exists(target)  # FRESH syscall — not the tool's report
            except Exception:
                continue
            # Polarity: a removal's satisfied state is that the target is GONE, so
            # absence is support and presence is against — the mirror of a
            # present-goal. Read from the operation, not the description.
            wants_absent = r.get("tool") in _TOOL_WANTS_ABSENT
            achieved = (not exists) if wants_absent else exists
            saw.append(Evidence(prop, achieved, self._EV_EFFECT if achieved else self._EV_AGAINST,
                                target, "filesystem_scan", f"saw:filesystem:{target}", "saw"))
        for fact in (result.get("learned") or [])[:3]:
            held = self._saw_memory_holds(fact)
            if held is None:
                continue
            saw.append(Evidence(prop, held, self._EV_EFFECT if held else self._EV_AGAINST,
                                f"fact:{fact}", "memory", f"saw:memory:{fact}", "saw"))
        # A GROUNDED-OPERATOR execution and a DRIVEN PLAN both apply their effects
        # through the operator-binding/world layer, not a filesystem tool, so
        # neither has an `intervention_target` path the branches above can stat —
        # and without a SAW grounding either is stuck on DID alone (~0.72) and can
        # never reach the acceptance band, so a verifiably-successful operation is
        # marked failed. Take a FRESH, independent observation of the domain's
        # whole world (a NEW observe_world, distinct causal lineage from the act's
        # own cached after-state and from DID) and check what was claimed now
        # holds: an add present, a delete absent. This is the world itself
        # confirming the operation, compounding with DID to reach done.
        #
        # WHAT WAS CLAIMED DIFFERS BY PATH, and that difference is the point:
        #
        #   * one operator claims its RULE'S EFFECTS;
        #   * a driven plan claims its GOAL CONDITIONS — what it MEANT.
        #
        # So for a plan this grounding is the substrate believing its INTENTION
        # was realized, on its own fresh look at the world. The plan path was
        # missing entirely and the cost was measured: five drives that verifiably
        # moved a file were accepted 0/5, because DID alone cannot reach the bar.
        #
        # The reconciled intent's own verdict is deliberately NOT reused here.
        # That verdict came from the reconciliation's observation, and feeding it
        # in as well would let ONE look at the world count twice — correlated
        # evidence wearing the shape of corroboration. The belief gets its own
        # independent look, which is what makes it a belief rather than a copy.
        _path = result.get("execution_path")
        if _path == "substrate":
            #: (claimed fact, whether its satisfied state is ABSENCE)
            claimed = [(eff.get("effect"),
                        str(eff.get("polarity", "")).lower() == "delete")
                       for eff in (result.get("effects") or [])]
        elif _path == "substrate_plan":
            # Goal conditions are read exactly as the reconciler reads them —
            # present in the observed world — so the belief and the intent's
            # account cannot mean different things by the same condition.
            claimed = [(cond, False)
                       for cond in (result.get("goal_conditions") or [])]
        else:
            claimed = []
        if claimed:
            domain = ((getattr(task, "provenance", None) or {}).get("domain_id")
                      or (task.metadata or {}).get("domain_id"))
            observed = None
            if domain:
                try:
                    from core.execution.operator_binding import get_binding_registry
                    observed = get_binding_registry().observe_world(domain)
                except Exception as e:
                    logger.debug("SAW world re-observation unavailable for %s: %s",
                                 getattr(task, "id", "?"), e)
            if observed is not None:
                def _norm(s):
                    return "".join(str(s).split())
                present = {_norm(f) for f in observed}
                for fact, wants_absent in claimed:
                    if not fact:
                        continue
                    here = _norm(fact) in present
                    achieved = (not here) if wants_absent else here
                    saw.append(Evidence(
                        prop, achieved, self._EV_EFFECT if achieved else self._EV_AGAINST,
                        f"world:{fact}", "world_reobserve", f"saw:world:{_norm(fact)}", "saw"))
        return saw

    def _saw_memory_holds(self, claim: str) -> Optional[bool]:
        """Fresh independent retrieval: is `claim` actually held in the store now?
        True/False, or None when it cannot be checked (then not counted as SAW).
        A distinct channel from the reasoning that produced the answer."""
        try:
            belief = self.learning.belief_for_claim(claim)
        except Exception:
            return None
        if belief is None:
            return None
        return float(getattr(belief, "posterior_probability", 0.0)) >= 0.5

    def _independent_groundings(self, evidence) -> List["Evidence"]:
        """Reduce raw evidence to INDEPENDENT groundings: drop derived items, group
        by causal_lineage (correlated evidence shares a lineage), and keep one
        representative per group — the strongest. Only these compound in the belief
        update, so correlated evidence can never multiply into false confidence."""
        by_lineage: Dict[str, "Evidence"] = {}
        for e in evidence:
            if e.derived:
                continue
            cur = by_lineage.get(e.causal_lineage)
            if cur is None or e.strength > cur.strength:
                by_lineage[e.causal_lineage] = e
        return list(by_lineage.values())

    def _decide_completion(self, task, result, verify_bar: float):
        """DONE from the substrate's completion belief: has its posterior reached
        the DEFENSIBLE acceptance (>= 0.95, raised toward 0.99 by caution)? Returns
        (is_complete, confidence, issues). If the belief is unavailable (mint
        failed), decide honestly from the handler's re-observation ('verified'
        only) — never a fabricated pass."""
        belief_id = (task.metadata or {}).get("completion_belief_id")
        belief = self.learning.get_belief(belief_id) if belief_id else None
        if belief is None:
            vs = result.get('verification_state') if isinstance(result, dict) else None
            if vs == 'verified':
                return True, 0.85, []
            declared_ok = isinstance(result, dict) and result.get('success') is True
            return declared_ok, (0.5 if declared_ok else 0.0), (
                ['completion belief unavailable; honoured at success flag only']
                if declared_ok else
                [(result.get('error') if isinstance(result, dict) else None) or 'not verified'])
        posterior = float(belief.posterior_probability)
        caution = (verify_bar / 0.85) if verify_bar > 0 else 0.0
        accept = self.COMPLETION_ACCEPT + (self.COMPLETION_ACCEPT_MAX - self.COMPLETION_ACCEPT) * caution
        if posterior + 1e-9 >= accept:
            return True, posterior, []
        return False, posterior, [
            f"completion belief {posterior:.2f} < acceptance {accept:.2f} — "
            f"goal not yet grounded-confident (needs corroboration)"]

    def _acceptance_band(self) -> Tuple[float, float]:
        """(verification_intensity, accept) — THE SAME BAND as `_decide_completion`.

        One governance for all epistemic state, and it has to be reachable from
        more than one place to actually BE one: recognition computed this inline
        while sensation had no acceptance decision at all, so the substrate held
        a defensible standard for what it recognised and none for what it saw.
        """
        vi = float(self.disposition().verification_intensity)          # [0.5, 1.0]
        verify_bar = 0.85 * max(0.0, min(1.0, (vi - 0.5) / 0.5))
        caution = (verify_bar / 0.85) if verify_bar > 0 else 0.0
        accept = (self.COMPLETION_ACCEPT
                  + (self.COMPLETION_ACCEPT_MAX - self.COMPLETION_ACCEPT) * caution)
        return vi, accept

    async def recognise_sensed(self, content: Dict[str, Any], *,
                               domain: str = "perception",
                               classifier: Optional[str] = None) -> List[str]:
        """Name what was just seen, WITHOUT being asked. Returns the claims admitted.

        THE SUBSTRATE COULD ALREADY RECOGNISE AND DID NOT. Measured on the live
        system: it induced `circle(?X) ∧ vivid_red(?X) → <cat>(?X)` from sight
        alone, then saw a fresh red circle, held `circle, large, vivid_red`, and
        named nothing. Asked "is that blob a <cat>?" it answered "Yes" — with the
        rule cited. The knowledge was there the whole time; nothing asked.

        That is the same shape of gap as having to switch your eyes on. You do not
        ask yourself whether the thing in front of you is an apple; the name
        arrives with the seeing. So sight asks here, of every blob it admitted,
        through the ONE naming authority the reasoner answers questions with — a
        name that arrives with a sighting and an answer to a question about that
        sighting cannot disagree, because they are the same call.

        A name is DERIVED, never observed, and enters as such: `INDUCED_RULE`
        provenance carrying the rule's own root evidence, so the conclusion cannot
        become fresh support for the rule that produced it. That is the ingress's
        rule, enforced structurally, and it is exactly right here — the substrate
        recognising a hundred red circles must not thereby "confirm" the rule it
        recognised them with.

        Categories whose hypotheses DISAGREE about a blob name nothing and are
        registered as known-unknowns instead: that blob is precisely the
        demonstration that would collapse the version space, which is worth
        asking about rather than guessing at.

        TWO PATHS NAME HERE, over the same observed features and through the same
        gate. The induced rules are exact, legible and learnable from two
        examples, and cannot represent a category that is a DISJUNCTION of
        conditions — they report the disagreement and wait. A clause population
        (`classifier`) represents disjunction, improves with data, and abstains
        when the vote is not decisive; it needs far more examples to say
        anything. Keeping both is the point: either can be removed and the
        substrate still names what it sees. Neither is consulted about the
        other's answer — they are independent readings of one blob, and a
        disagreement between them is two claims the acceptance band judges on
        their own posteriors, not a tie for this method to break."""
        blobs = [str(b.get("name") or "").strip() for b in (content.get("blobs") or [])]
        blobs = [b for b in blobs if b]
        if not blobs:
            return []
        from core.learning.rule_naming import read_names
        from core.learning.rule_store import get_rule_store
        from core.reasoning.concept_graph_reasoning import observed_instance_features
        from core.semantics.cognitive_ingress import Provenance
        from core.database import get_database_manager

        stored = await get_rule_store().load()   # once for the whole percept
        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()

        admitted: List[str] = []
        for blob in blobs:
            # ONLY WHAT WAS OBSERVED licenses a name, and the same read yields
            # the lineage: every name drawn from this blob rests on this seeing.
            feats, evidence = await observed_instance_features(db, blob)
            reading = read_names(blob, feats, stored)
            roots = tuple(evidence) if reading.names else ()
            for naming in reading.names:
                if not roots:
                    # Features with no recorded evidence cannot support a derived
                    # conclusion, and the ingress refuses a derivative with no
                    # lineage. Reported, not worked around.
                    logger.warning(
                        "recognise: %s would be named a %s, but its features "
                        "carry no recorded evidence — the name cannot state its "
                        "lineage and is not admitted", blob, naming.category)
                    break
                try:
                    adm = await self.learning.learn_fact(
                        blob, "isa", naming.category, domain=domain,
                        quality=naming.confidence,
                        provenance=Provenance(
                            producer="rule_naming", source_id=naming.rule_id,
                            source_type="INDUCED_RULE", derived_from=roots))
                except Exception as error:
                    raise_if_structural(
                        error, "autonomous_coordinator.recognise_sensed")
                    logger.warning("recognise: naming %s a %s was refused: %s",
                                   blob, naming.category, error)
                    continue
                # THE GATE DECIDES, NOT THIS. `learn_fact` returns an Admission
                # whether or not it admitted anything, so reporting the name as
                # made because the call returned would be a recognition the
                # substrate never actually holds — and `perceive_sensed` would
                # then read no belief for it and call it an absence.
                if not (getattr(adm, "admitted", False)
                        or getattr(adm, "already_present", False)):
                    logger.info(
                        "recognise: the gate declined %s isa %s (%s)", blob,
                        naming.category,
                        "; ".join(getattr(adm, "refusals", []) or ["no reason given"]))
                    continue
                admitted.append(f"{blob} isa {naming.category}")
                logger.info("👁️ recognised %s as %s (%s: %s -> %s, %d hypotheses)",
                            blob, naming.category, naming.status, naming.body,
                            naming.category, naming.hypotheses)
            for undet in reading.undetermined:
                udm = getattr(self, "universal_domain_master", None)
                if udm is None:
                    continue
                try:
                    await udm.detect_knowledge_gap(domain, blob, "isa")
                except Exception as error:
                    raise_if_structural(
                        error, "autonomous_coordinator.recognise_sensed")
                    logger.warning(
                        "recognise: could not register the undetermined naming of "
                        "%s as %s: %s", blob, undet.category, error)

            # THE SECOND PATH, on the same blob and the same features. It routes
            # through `learning.recognize`, which owns turning a vote into a
            # claim: it applies the rejection class, states the derivative
            # provenance, and puts the confidence through the gate as evidence
            # quality. None means the machine declined — no name, not a failure.
            if not classifier or not feats:
                continue
            try:
                adm = await self.learning.recognize(
                    classifier, feats, blob, domain=domain)
            except Exception as error:
                raise_if_structural(
                    error, "autonomous_coordinator.recognise_sensed")
                logger.warning("recognise: clause classifier %r failed on %s: %s",
                               classifier, blob, error)
                continue
            if adm is None:
                continue
            if not (getattr(adm, "admitted", False)
                    or getattr(adm, "already_present", False)):
                logger.info("recognise: the gate declined %s (%s)",
                            getattr(adm, "proposition", "?"),
                            "; ".join(getattr(adm, "refusals", []) or ["no reason"]))
                continue
            voted = str(getattr(adm, "proposition", "")).split("|")[-1].strip()
            if voted:
                claim = f"{blob} isa {voted}"
                if claim not in admitted:
                    admitted.append(claim)
                logger.info("🧠 clause classifier %r named %s a %s",
                            classifier, blob, voted)
        return admitted

    async def perceive_sensed(self, subject: str, claims: Sequence[str], *,
                              domain: str = "perception",
                              percept_id: Optional[str] = None
                              ) -> Dict[str, Any]:
        """What standing does what I just SAW have — judged by the same band that
        judges a recognition and a finished task.

        SENSATION HAD NO ACCEPTANCE DECISION. `perceive` asked of every
        recognition whether its confidence cleared a defensible bar; `sense` ran
        to the belief store and stopped. So the substrate could say "I recognised
        this and I am not sure enough to act on it" and could not say the same
        about anything it merely looked at — while sensing is the path that runs
        constantly and the one an attacker reaches first.

        PER CLAIM, NOT PER PERCEPT, because one look is not uniform. A red circle
        yields a colour read off the pixels and a shape inferred from a lossy
        polygon approximation, and the honest answer is that the colour can be
        acted on while the shape wants re-observing. Collapsing that to one
        verdict would either overstate the shape or understate the colour.

        The percept-level `decision` is the WEAKEST of them, for the same reason
        `_detection_quality` takes the lowest confidence in a batch: acting on a
        percept means acting on the whole of it, and a mean would let a certain
        colour carry an uncertain shape past the bar.
        """
        vi, accept = self._acceptance_band()
        judged: List[ClaimVerdict] = []
        for claim in claims:
            claim = str(claim).strip()
            if not claim:
                continue
            belief = self.learning.belief_for_claim(claim)
            # NO BELIEF IS NOT A WEAK BELIEF. A claim that never cleared the
            # admission floor has no posterior to read, and scoring it zero would
            # report "I saw this and disbelieve it" for something the substrate
            # refused to hold at all. That is ABSTAIN — an absence.
            if belief is None:
                judged.append(ClaimVerdict(
                    claim=claim, posterior=None, decision="ABSTAIN",
                    reason="not admitted — below the floor, held as absence"))
                continue
            posterior = float(getattr(belief, "posterior_probability", 0.0))
            accepted = posterior + 1e-9 >= accept
            judged.append(ClaimVerdict(
                claim=claim, posterior=round(posterior, 4),
                decision="ACT" if accepted else "VERIFY",
                reason=None if accepted else
                       "below the acceptance band — re-observe before acting"))
        order = {"ABSTAIN": 0, "VERIFY": 1, "ACT": 2}
        weakest = min((j.decision for j in judged), key=lambda d: order[d],
                      default="ABSTAIN")
        out = PerceptJudged(
            subject=str(subject), domain=domain, percept_id=percept_id,
            decision=weakest, accept=round(accept, 4),
            verification_intensity=round(vi, 3), claims=tuple(judged))
        # THE SAME EVENT recognition emits, so one reaction governs behaviour for
        # everything perceived rather than one path having a spine and the other
        # running past it.
        await self.emit(SelfEvent(SelfEventType.PERCEPT_RECOGNIZED,
                                  payload=out, origin="perceive_sensed"))
        return out

    async def perceive(self, classifier: str, instance, instance_id: str, *,
                       domain: str = "perception") -> Dict[str, Any]:
        """Recognize a percept AND let its epistemic confidence GOVERN what happens
        next — through the SAME caution-raised acceptance band that governs task
        completion (`_decide_completion`). A recognition is not automatically an
        action:
          • unsupported → refused at the admission gate → ABSTAIN (nothing acted, nothing stored);
          • admitted but below the band → VERIFY (held for re-observation, not acted on);
          • admitted and past the band → ACT.
        This is the perception counterpart of the completion decision: the recognition
        belief's posterior is read and compared to the disposition-derived band, so a
        low-confidence perception drives re-observation while a high-confidence one is
        acted on directly. Confidence steers behaviour; it is not just recorded."""
        admission = await self.learning.recognize(
            classifier, instance, instance_id, domain=domain)
        if admission is None or not getattr(admission, "admitted", False):
            # A RECOGNITION IS A PERCEPT THAT MADE ONE CLAIM. Same declared shape
            # as a sensing, so one reaction reads both instead of each path
            # inventing its own vocabulary for the same two things.
            _vi, _acc = self._acceptance_band()
            out = PerceptJudged(
                subject=str(instance_id), domain=domain, decision="ABSTAIN",
                accept=round(_acc, 4), verification_intensity=round(_vi, 3),
                claims=(ClaimVerdict(
                    claim="", posterior=None, decision="ABSTAIN",
                    reason="recognition refused/abstained at the gate — "
                           "insufficient support"),))
            await self.emit(SelfEvent(SelfEventType.PERCEPT_RECOGNIZED,
                                      payload=out, origin="perceive"))
            return out
        claim = getattr(admission, "proposition", "").replace("|", " ").strip()
        belief = self.learning.belief_for_claim(claim) if claim else None
        posterior = float(getattr(belief, "posterior_probability", 0.0)) if belief else 0.0
        vi, accept = self._acceptance_band()
        accepted = posterior + 1e-9 >= accept
        verdict = ClaimVerdict(
            claim=claim, posterior=round(posterior, 4),
            decision="ACT" if accepted else "VERIFY",
            reason=None if accepted else
                   "recognition posterior below the acceptance band — "
                   "re-observe/corroborate before acting")
        out = PerceptJudged(
            subject=str(instance_id), domain=domain, decision=verdict.decision,
            accept=round(accept, 4), verification_intensity=round(vi, 3),
            claims=(verdict,))
        # Record the recognition in the overall perceptual awareness — AWARENESS ONLY:
        # its evidence already went through the gate via recognize→learn_fact, so a
        # process_input here would double-admit. This lets a memory forming now stamp
        # what the substrate is currently perceiving.
        try:
            self.perception.note_perception(
                source=str(instance_id), data_type="recognition",
                content={"claim": verdict.claim, "decision": out.decision,
                         "domain": domain},
                confidence=float(posterior))
        except Exception as error:
            raise_if_structural(error, "autonomous_coordinator.perceive")
        # The decision GOVERNS behaviour through the event spine, not by the caller
        # re-reading the return: every perceive — from any of the many recognition
        # sites — fans one decision to `_react_percept`.
        await self.emit(SelfEvent(SelfEventType.PERCEPT_RECOGNIZED,
                                  payload=out, origin="perceive"))
        return out

    def attach_recognizer(self, domain: str, classifier: str) -> None:
        """Wire a perception route's sensation to its recognition. Once a classifier
        is attached to `domain`, percepts ingested for that domain (`see` an image,
        a video keyframe, any percept-producing site naming the domain) CHAIN from
        sensation into `perceive` with this classifier — so recognition and the
        confidence-governed decision happen on the same percept. A domain with no
        attached recognizer stays pure sensation. The classifier must already be
        registered on the learning authority; a route must not claim a recognizer it
        does not have."""
        if not self.learning.has_clause_classifier(classifier):
            raise ValueError(
                f"no clause classifier {classifier!r} registered on the learning "
                f"authority — register it before attaching it to route {domain!r}")
        self._recognizers[domain] = classifier
        logger.info("🔗 Recognizer %r attached to perception route %r",
                    classifier, domain)

    async def _react_percept(self, event: SelfEvent) -> None:
        """Carry out a recognition decision — this is where a percept's confidence
        GOVERNS behaviour. `perceive` already compared the posterior to the
        acceptance band and admitted the recognition through the gate; here the
        substrate acts on the verdict:
          • ACT     — the recognition is trusted (posterior past the band); it stands
                      as a belief+domain entry and is the hook a behaviour layer acts on;
          • VERIFY  — below the band: the recognition is NOT treated as settled. It is
                      registered as a known-unknown (an in-domain question the
                      substrate will seek to resolve) so a shaky percept drives
                      corroboration instead of action;
          • ABSTAIN — refused at the gate: nothing was stored and nothing is done.
        No fabricated action: if the below-band recognition cannot be registered for
        follow-up, that is logged honestly, not swallowed.

        TWO SHAPES REACH HERE, and both must be readable. A RECOGNITION carries
        one claim (`claim` / `instance_id` / `posterior`); a SENSING carries many
        (`claims` / `subject`), because one look is not uniform — a colour read
        off the pixels can stand while a shape inferred from a lossy
        approximation wants re-observing.

        Reading only the recognition shape was a real defect for as long as it
        stood: a sensed percept's VERIFY logged a None claim, `instance_id` was
        absent so `subject` was None, and the known-unknown this reaction exists
        to register was never registered. The verdict was computed, emitted, and
        unreadable at the consumer — a decision that governs nothing governs
        nothing quietly.
        """
        judged: PerceptJudged = event.payload
        acc = judged.accept
        subject = judged.subject

        if judged.decision == "ACT":
            logger.info("👁️ ACT on %s (%d claim(s) ≥ %.3f)",
                        subject, len(judged.claims), acc)
            return
        if judged.decision == "VERIFY":
            # ONLY the claims actually below the band. The percept's verdict is
            # its weakest, so a single shaky shape makes the whole percept
            # VERIFY — registering every claim it made as doubtful would turn one
            # uncertain shape into a dozen invented questions.
            shaky = judged.below_band()
            logger.info("👁️ VERIFY %s — %d of %d claim(s) below %.3f, "
                        "hold for corroboration",
                        subject, len(shaky), len(judged.claims), acc)
            udm = getattr(self, "universal_domain_master", None)
            if udm is None:
                return
            for verdict in shaky:
                # The claim names its own subject ("<thing> isa <feature>");
                # fall back to the percept's subject only when it does not.
                target = verdict.subject or subject
                if not target:
                    logger.warning(
                        "percept VERIFY carried no nameable subject; no "
                        "known-unknown registered (claim=%r)", verdict.claim)
                    continue
                try:
                    await udm.detect_knowledge_gap(judged.domain, str(target), "isa")
                except Exception as error:
                    raise_if_structural(error, "autonomous_coordinator._react_percept")
                    logger.warning(
                        "percept VERIFY: could not register known-unknown for %r: %s",
                        target, error)
        # ABSTAIN (or any other verdict): nothing acted, nothing stored — by design.

    def _extract_task_outcome(self, m) -> Optional[Dict[str, Any]]:
        """Pull the task-outcome record + its evidence + the beliefs of the moment
        out of a recalled memory, wherever the one pipeline placed them (the
        content dict, or `thinking_state.raw_event`). None if it is not a
        task-outcome memory."""
        src = None
        c = getattr(m, "content", None)
        if isinstance(c, dict) and c.get("event") == "task_outcome":
            src = c
        ts = getattr(m, "thinking_state", None) or {}
        if src is None and isinstance(ts, dict) and isinstance(ts.get("raw_event"), dict) \
                and ts["raw_event"].get("event") == "task_outcome":
            src = ts["raw_event"]
        if not isinstance(src, dict):
            return None
        return {
            "task_id": src.get("task_id"),
            "task_description": src.get("task_description"),
            "outcome": src.get("outcome"),
            "confidence": src.get("confidence"),
            "evidence": src.get("evidence"),          # the DID/SAW groundings
            "method": src.get("method"),              # the tool_plan used
            "causal_rules": src.get("causal_rules"),  # {when, use, expect} remedies
            "failure_reason": src.get("failure_reason"),
            "result_summary": src.get("result_summary"),
            "beliefs": (ts.get("belief_state") or {}).get("relevant_beliefs"),
        }

    async def _recall_similar_task_experience(self, task, limit: int = 5) -> Dict[str, Any]:
        """Recall past experience with SIMILAR tasks before acting — outcome, the
        DID/SAW evidence (what worked / what didn't), and the domain beliefs of the
        moment. So the substrate approaches a task informed by its own history
        instead of blind: if it has done something like this before, it knows what
        happened and why. Queries the ONE memory store for task-outcome memories,
        ranked by similarity to this task's description and scoped to its domain.
        Returns {} when nothing similar is recalled — never invents experience."""
        try:
            domain = self._completion_domain(task)
            tags = ["task_outcome"] + ([f"domain_{domain}"] if domain else [])
            mems = await self.memory.search_memories(
                query_text=getattr(task, "description", "") or "",
                tags=tags, memory_type=MemoryType.META, max_results=limit)
            if isinstance(mems, tuple):
                mems = mems[1]
        except Exception as e:
            logger.debug("recall similar-task experience failed: %s", e)
            return {}

        recalled = [r for r in (self._extract_task_outcome(m) for m in (mems or [])) if r]
        recalled = [r for r in recalled if r.get("task_id") != getattr(task, "id", None)]
        # DEDUP so multiple memories of the SAME event (or the same task recalled
        # more than once) do not bias retrieval — keep one per task_id, and one per
        # (outcome, method-signature) so re-runs of one approach count once.
        _seen = set()
        _deduped = []
        for r in recalled:
            import json as _json
            sig = (r.get("task_id"),
                   r.get("outcome"),
                   _json.dumps(r.get("method"), sort_keys=True, default=str))
            if sig in _seen:
                continue
            _seen.add(sig)
            _deduped.append(r)
        recalled = _deduped
        if not recalled:
            return {}
        successes = [r for r in recalled if r.get("outcome") == "success"]
        failures = [r for r in recalled if r.get("outcome") == "failure"]
        # What worked / didn't: the grounded evidence provenance from past
        # successes vs failures — the substrate's own record of which approach held.
        worked = sorted({g.get("provenance") for r in successes
                         for g in (r.get("evidence") or []) if g.get("supports")} - {None})
        failed = sorted({g.get("provenance") for r in failures
                         for g in (r.get("evidence") or []) if not g.get("supports")} - {None})
        return {
            "recalled": recalled,
            "successes": len(successes),
            "failures": len(failures),
            "what_worked": worked[:10],
            "what_failed": failed[:10],
        }

    def _select_retry_method(self, task, recalled, current_failed_tools=None
                             ) -> Optional[Tuple[List[Dict[str, Any]], str, List[Dict[str, Any]]]]:
        """Pick a DIFFERENT method for the retry — CONDITIONALLY, from experience.

        Preference, most-principled first:
          1) CAUSAL REMEDY — a recalled rule ``{when: <tools that were failing>,
             use: <arg change>}`` whose WHEN matches the tools failing NOW. This is
             condition-matched transfer ("when write_file fails, use
             create_dirs=True"), learned from a fix that actually WORKED — not
             semantic description similarity.
          2) SEMANTIC — otherwise, adopt the config args a similar SUCCESS used for
             the same tool.
        Either way the change is only the APPROACH (config args like create_dirs,
        mode, recursive); this task's OWN targets (paths/urls) and DATA payload are
        never touched. Returns ``(new_plan, change_summary, structured_changes)`` or
        None when experience offers no different approach (then the substrate does
        not thrash — the diagnostic re-derive path handles it, or it fails
        honestly)."""
        if not isinstance(recalled, dict):
            return None
        current = ((task.metadata or {}).get("parameters") or {}).get("tool_plan")
        if not current:
            return None
        exclude = set(_RESOURCE_ARGS) | {"content", "data", "body", "text", "payload"}

        # 1) CAUSAL REMEDIES whose WHEN (tools that were failing) matches what is
        #    failing now — condition-matched, deduped by (tool, arg).
        cur_failed = set(current_failed_tools or [])
        remedy: Dict[str, Dict[str, Any]] = {}
        for r in recalled.get("recalled", []):
            for rule in (r.get("causal_rules") or []):
                when_tools = set((rule.get("when") or {}).get("failed_tools") or [])
                if cur_failed and when_tools and (when_tools & cur_failed):
                    for ch in (rule.get("use") or []):
                        t, a, v = ch.get("tool"), ch.get("arg"), ch.get("value")
                        if t and a and a not in exclude:
                            remedy.setdefault(t, {})[a] = v

        # 2) SEMANTIC winning config args per tool, from recalled SUCCESS methods.
        winning: Dict[str, Dict[str, Any]] = {}
        for r in recalled.get("recalled", []):
            if r.get("outcome") != "success":
                continue
            for step in (r.get("method") or []):
                t = (step or {}).get("tool")
                args = (step or {}).get("args") or {}
                if t:
                    winning.setdefault(t, {}).update(
                        {k: v for k, v in args.items() if k not in exclude})

        source = "causal-remedy" if remedy else "recalled-success"
        changed, structured, new_plan = [], [], []
        for step in current:
            t = (step or {}).get("tool")
            args = dict((step or {}).get("args") or {})
            # A matched remedy for THIS tool wins; else the semantic winning args.
            apply = remedy.get(t) or winning.get(t, {})
            for k, v in apply.items():
                if k in exclude or args.get(k) == v:
                    continue
                args[k] = v
                changed.append(f"{t}.{k}={v}")
                structured.append({"tool": t, "arg": k, "value": v})
            new_plan.append({"tool": t, "args": args})
        if not changed:
            return None
        return new_plan, f"[{source}] " + ", ".join(changed), structured

    async def _execute_and_validate_task(self, task):
        """Execute a task through the substrate's own executor (no model
        anywhere in the acting path), then DECIDE completion from
        the substrate's own COMPLETION BELIEF: a belief `G` ("the goal holds")
        anchored to the task's intent, minted low and moved by the real evidence
        execution produced (re-observation, tool effects, gap-state). Done when the
        belief reaches the self's acceptance band (raised by caution). The one
        completion authority; there is no separate completion-protocol validator."""
        # Bind this task's remediation contract for the duration of the task.
        # A ContextVar, so concurrently-running tasks cannot see each other's
        # authority. No contract => unconstrained, exactly as before.
        _contract_token = None
        try:
            from core.safety.action_contract import ActionContract, set_active_contract
            _c = (task.metadata or {}).get("contract") if getattr(task, "metadata", None) else None
            if _c:
                _contract_token = set_active_contract(
                    _c if isinstance(_c, ActionContract) else ActionContract.from_dict(_c)
                )
        except Exception as _ce:
            logger.warning(f"could not bind action contract for {task.id}: {_ce}")

        try:
            from core.agents.autonomous.task_queue import Task
            logger.info(f"▶️  Executing: {task.id} ({task.priority.name}, {task.source.value})")
            logger.info(f"   Description: {task.description}")
            self.stats["cycles_completed"] = self.stats.get("cycles_completed", 0) + 1

            # SLACK NOTIFICATION: Task started
            if self.slack_notifier:
                import re as _re
                _task_desc = task.description.split('\n')[0][:200]
                _task_desc = _re.sub(r'/[^\s]+', '[file]', _task_desc)
                await self.slack_notifier.send_notification(
                    title="🚀 Task Started",
                    message=(
                        f"*Task ID:* `{task.id}`\n"
                        f"*Task:* {_task_desc}\n"
                        f"*Type:* {task.type.value.replace('_', ' ').title()}\n"
                        f"*Priority:* {task.priority.name.title()}\n"
                        f"*Source:* {task.source.value.replace('_', ' ').title()}"
                    ),
                    severity="info",
                    metadata={
                        "task_id": task.id,
                        "task_type": task.type.value,
                        "source": task.source.value,
                    }
                )

            # NO TASK-LEVEL GATE. THE ACT IS WHAT IS JUDGED.
            #
            # A safety_framework evaluation used to run here on the task's
            # id, type, description, source and priority. It is gone with the
            # rest of that gate, and it is deliberately NOT replaced by a
            # constitutional one, because a task is not an act — it is prose
            # naming work that has not happened yet.
            #
            # Judging that prose as if it were arguments manufactures refusals.
            # MEASURED on ordinary descriptions: 3 of 6 tripped Law 5 because
            # they mentioned a relative path ("Investigate why core/agents/../
            # tools fails to import"). The screen is right about arguments and
            # wrong about sentences, and a gate that refuses a third of honest
            # work is not a safer gate.
            #
            # It is also the wrong place in the chain. By the time a task runs,
            # the constitution has already been consulted where it can answer:
            # reasoning formed the intent, planning proved the route over
            # operators the rule store attests, and every tool call the task
            # makes is judged before it happens, with the real arguments, the
            # measured consequence, what has been READ of the target, and the
            # recorded intent. A task whose description names something
            # forbidden does not get to do it — its first forbidden call is
            # refused with nothing executed.
            #
            # And the task's words carry no authority in either direction:
            # CONSTITUTION-02 measures that prose claiming approval cannot make
            # a refused act allowed. Prose that cannot permit must not be able
            # to forbid either.

            # DOUBT → VERIFICATION (a closed affect loop). The disposition's
            # verification_intensity is the substrate's standing caution, derived
            # from appraisal (low confidence / low control → doubt → caution).
            # Read it NOW, before this task's own outcome moves appraisal, so the
            # bar reflects the doubt carried INTO the task, not the task's own
            # result. It sets how much proof the substrate demands before it will
            # accept a completion: no extra demand when untroubled, up to a near-
            # certainty bar when in deep doubt. This is what discharges doubt —
            # meeting the raised bar accumulates the evidence that, through the
            # outcome→appraisal path, lifts confidence and lowers doubt again.
            _verify_bar = 0.0
            try:
                _vi = float(self.disposition().verification_intensity)  # [0.5, 1.0]
                _verify_bar = 0.85 * max(0.0, min(1.0, (_vi - 0.5) / 0.5))
            except Exception as _vbe:
                logger.debug(f"verification bar unavailable (no appraisal yet?): {_vbe}")

            # Execute through this substrate's OWN executor (substrate-only,
            # model-free); the task's TYPE selects the tool/executor path.
            # A DRIVE goal (competence/confidence) names a concrete operator/domain
            # to learn; it has one correct, deterministic substrate action, so it
            # is routed to the dedicated handler rather than interpreted as a
            # free-form task by the general executor.
            # RECALL before acting: what happened on SIMILAR tasks before — their
            # outcome, the DID/SAW evidence (what worked / what didn't), and the
            # domain beliefs of the moment. Stashed on the task so the approach (and,
            # on failure, the different-method retry) is informed by real history,
            # not blind. Empty when nothing similar is recalled.
            _recalled = await self._recall_similar_task_experience(task)
            if _recalled:
                if task.metadata is None:
                    task.metadata = {}
                task.metadata["recalled_experience"] = _recalled
                logger.info("🧠 Recalled %d similar task(s) for %s: %d ok, %d failed"
                            + (" — approaches that worked before: %s" if _recalled.get("what_worked") else "%s"),
                            len(_recalled.get("recalled", [])), task.id,
                            _recalled.get("successes", 0), _recalled.get("failures", 0),
                            _recalled.get("what_worked") or "")

            # Mint the task's COMPLETION BELIEF (low prior — "the goal does not yet
            # hold") before acting, anchored to the task's goal/intent (hybrid
            # authorship), so execution's real evidence moves it toward or away
            # from done through the one learning authority.
            _completion_anchor = self._derive_completion_anchor(task)
            self._mint_completion_belief(task, _completion_anchor)

            if (task.metadata or {}).get("drive") in ("competence", "confidence"):
                result = await self._execute_drive_goal(task)
            else:
                result = await self.execute_task(task)

            # ================================================================
            # COMPLETION DECISION — the substrate's OWN belief, the one authority.
            # Not a handler verdict: the substrate moves its completion belief on
            # the real evidence execution produced (a re-observed effect is strong
            # support; a bare success flag is weak; an explicit non-verified state
            # or no result is evidence against), then judges DONE by whether that
            # belief reached the self's acceptance band (raised by caution).
            # `verification_state` is EVIDENCE here, never the decision — a
            # fabricated or empty success cannot cross the band from the low prior.
            # ================================================================
            await self._observe_completion_evidence(task, result)
            is_complete, confidence, issues = self._decide_completion(task, result, _verify_bar)
            self._record_calibration_outcome(task, result, confidence)
            if is_complete:
                logger.info(f"✅ Task {task.id} done — completion belief {confidence:.3f} "
                            f"(grounded, past the self's acceptance)")
            else:
                logger.info(f"🔎 Task {task.id} not done — {issues[0] if issues else 'under-confident'}")

            # Uncertainty reduction gate: for autonomous exploration tasks, verify the
            # target component's epistemic_uncertainty actually decreased post-execution.
            # This closes the control loop — completion is metric-driven, not self-declared.
            if is_complete and task.source == TaskSource.AUTONOMOUS:
                _component = task.metadata.get("target_component") if task.metadata else None
                if _component:
                    try:
                        fresh_context = await self._collect_system_context_for_goals()
                        new_metrics = await self.intrinsic_motivation._quantify_component_uncertainties(fresh_context)
                        u_after = new_metrics.get(_component, {}).get("epistemic_uncertainty")
                        u_before = task.metadata.get("uncertainty_before")
                        if u_after is not None and u_before is not None:
                            delta = u_after - u_before
                            threshold = -(0.1 * u_before) if u_before > 0 else -0.05
                            # Store measurements in result for longitudinal analysis
                            if result and isinstance(result, dict):
                                result["uncertainty_before"] = u_before
                                result["uncertainty_after"] = u_after
                                result["uncertainty_delta"] = delta
                            if delta > threshold:
                                logger.warning(
                                    f"🔄 Task {task.id}: {_component} uncertainty Δ {delta:+.3f} "
                                    f"> threshold {threshold:.3f} — insufficient reduction"
                                )
                                is_complete = False
                                issues = [f"Uncertainty delta {delta:+.3f} did not meet threshold {threshold:.3f}"]
                            else:
                                logger.info(
                                    f"✅ {_component} uncertainty: {u_before:.3f} → {u_after:.3f} "
                                    f"(Δ {delta:+.3f}, threshold {threshold:.3f})"
                                )
                    except Exception as _ue:
                        logger.warning(f"Uncertainty gate skipped for {task.id}: {_ue} — accepting LLM validation")

            # Credit the adaptive task-type decision with the authoritative
            # outcome. This lives here, not in
            # _check_task_completions: that scanner runs only on the legacy
            # _execution_phase path, while every task carrying an adaptive
            # decision is queued and arrives here instead. The channel was
            # severed between the two paths.
            _elapsed_ms = 0.0
            if getattr(task, "started_at", None):
                try:
                    _elapsed_ms = (datetime.now() - task.started_at).total_seconds() * 1000.0
                except TypeError:
                    _elapsed_ms = 0.0
            await self._record_adaptive_type_outcome(
                task,
                success=bool(is_complete),
                outcome_class="verified" if is_complete else "unverified",
                time_ms=_elapsed_ms,
            )

            # EARNED half of operability: a task that OPERATED in a domain and was
            # verified against the world is one operating-correctness outcome for
            # that domain -- the signal that lowers/raises its KNOW→DO bar over
            # time (_domain_operability). Recorded ONLY for genuine operations:
            # a resolved domain AND not an intrinsic drive/learning goal (those
            # feed competence via record_competence_evidence -- recording them here
            # would conflate what I LEARNED with how correctly I OPERATE). The
            # operation's domain is carried in `provenance` for a grounded-operator
            # task (the real operation shape) and in `metadata` for others; a drive
            # goal is excluded by its `metadata.drive`. (The producer read only
            # metadata.domain_id at first, which an integration test exposed as
            # missing every grounded-operator operation -- those name the domain in
            # provenance.)
            _tmd = task.metadata or {}
            _prov = getattr(task, "provenance", None) or {}
            _op_domain = _prov.get("domain_id") or _tmd.get("domain_id")
            if (isinstance(_op_domain, str) and _op_domain.strip()
                    and not _tmd.get("drive")
                    and getattr(self, "universal_domain_master", None) is not None):
                # OPERATING-CORRECTNESS is not DONE-ACCEPTANCE. The EARNED signal
                # asks "did the operation achieve its intent?" -- and for work that
                # carries an intent, the substrate now OWNS that answer instead of
                # inferring it. See _operating_verdict.
                _verdict = self._operating_verdict(result, confidence, is_complete)
                try:
                    _credited = await self.universal_domain_master.record_operating_outcome(
                        _op_domain, success=_verdict["success"],
                        outcome_class=_verdict["outcome_class"])
                    logger.info(
                        "operating outcome for %s in %s: %s (read from %s) -- %s",
                        task.id, _op_domain,
                        "correct" if _verdict["success"] else "wrong",
                        _verdict["read_from"],
                        "credited" if _credited else "denied credit")
                except Exception as _oe:
                    raise_if_structural(_oe, "autonomous_coordinator._execute_and_validate_task")
                    logger.debug("operating outcome not recorded for %s: %s", task.id, _oe)

            # A task outcome is a fitness-relevant EVENT — the substrate reacts
            # to it here. Emitting TASK_COMPLETED runs the registered reactions;
            # affect is one of them (it reads the substrate's own appraisal and
            # fitness, decays on read — a persistent property of the substrate,
            # not something the environment supplies). Event-driven, not a loop;
            # each reaction is isolated inside emit(), so a fault is logged and
            # never halts the pipeline. Fires for every outcome (complete or
            # not), exactly as the affect poke did before.
            await self.emit(SelfEvent(
                SelfEventType.TASK_COMPLETED,
                payload=TaskCompleted(
                    task_id=task.id,
                    task=task,
                    result=result,
                    confidence=confidence,
                    is_complete=bool(is_complete)),
                origin="_execute_and_validate_task"))

            if is_complete:
                await self.task_queue.mark_completed(task.id, result)
                self.stats["tasks_completed"] += 1
                logger.info(f"✅ Task completed: {task.id} (confidence: {confidence:.2f})")

                # META MEMORY: Store task success for learning
                _meta_id = await self._store_task_outcome_meta_memory(
                    task=task,
                    outcome="success",
                    confidence=confidence,
                    result_summary=str(result)[:500] if result else None
                )

                # The outcome is now durable, so the learning consequences flow
                # FROM the event: induction, domain expansion, and transfer
                # resolution react to THIS outcome (deferred, off the hot path)
                # instead of a 300s/900s idle tier later scanning the table.
                await self.emit(SelfEvent(
                    SelfEventType.OUTCOME_OBSERVED,
                    payload=OutcomeObserved(
                        task_id=task.id,
                        task=task,
                        domain=self._task_domain(task),
                        meta_memory_id=_meta_id,
                        outcome="success",
                        confidence=confidence),
                    origin="_execute_and_validate_task"))

                # SEMANTIC MEMORY: Hand the outcome to the memory agent (the
                # authority), which composes the rich, retrievable task-knowledge
                # record from the structured result — model-free.
                if self.memory and isinstance(result, dict):
                    await self.memory.capture_task_outcome(
                        task, result=result, success=True, confidence=confidence
                    )

                # === COMPLETION CALLBACKS: Execute registered closure hooks ===
                await self._execute_completion_callbacks(task, result, confidence)

                # SLACK NOTIFICATION: Task completion — show what was done and concluded
                if self.slack_notifier:
                    import re as _re2
                    task_desc = task.description.split('\n')[0][:200]
                    task_desc = _re2.sub(r'/[^\s]+', '[file]', task_desc)

                    completion_score = result.get('completion_score') if result else None
                    verification_state = result.get('verification_state', 'completed') if result else 'completed'
                    iterations = result.get('iterations', 1) if result else 1
                    summary_text = (result.get('summary') or '').strip() if result else ''
                    key_findings = (result.get('key_findings') or '').strip() if result else ''
                    # Also check inside outputs dict as fallback
                    if not key_findings and result:
                        key_findings = ((result.get('outputs') or {}).get('key_findings') or '').strip()
                    files_created = (result.get('files_created') or []) if result else []
                    duration_s = result.get('duration_seconds') if result else None
                    if duration_s is None and hasattr(task, 'started_at') and task.started_at:
                        try:
                            duration_s = int((datetime.now() - task.started_at).total_seconds())
                        except TypeError:
                            duration_s = int(datetime.now().timestamp() - task.started_at)

                    tool_results_list = result.get('tool_results', []) if result else []
                    tools_used = list(dict.fromkeys(
                        r['tool'] for r in tool_results_list
                        if isinstance(r, dict) and r.get('tool') and r.get('success')
                    ))

                    # ── Header line ──────────────────────────────────────────
                    header_parts = [
                        f"*Task:* {task_desc}",
                        f"*Type:* {task.type.value.replace('_', ' ').title()}  |  "
                        f"*Confidence:* {confidence:.0%}",
                    ]
                    if completion_score is not None:
                        header_parts.append(
                            f"*Score:* {completion_score:.3f}  |  "
                            f"*Iterations:* {iterations}"
                            + (f"  |  *Duration:* {duration_s // 60}m {duration_s % 60}s"
                               if duration_s and duration_s > 60
                               else (f"  |  *Duration:* {duration_s}s" if duration_s else ""))
                        )
                    else:
                        header_parts.append(f"*Iterations:* {iterations}"
                            + (f"  |  *Duration:* {duration_s // 60}m {duration_s % 60}s"
                               if duration_s and duration_s > 60
                               else (f"  |  *Duration:* {duration_s}s" if duration_s else "")))

                    if tools_used:
                        header_parts.append(f"*Tools:* {', '.join(tools_used[:6])}")

                    # ── Conclusion block (the most important part) ───────────
                    conclusion_parts = []

                    if summary_text:
                        preview = summary_text[:500] + ('…' if len(summary_text) > 500 else '')
                        conclusion_parts.append(f"*What was done:*\n{preview}")

                    if key_findings:
                        preview = key_findings[:400] + ('…' if len(key_findings) > 400 else '')
                        conclusion_parts.append(f"*Conclusions & findings:*\n{preview}")

                    if not summary_text and not key_findings:
                        conclusion_parts.append("_(No summary provided by task executor)_")

                    if files_created:
                        fc_display = [f"`{Path(f).name}`" for f in files_created[:5]]
                        conclusion_parts.append(f"*Output files:* {', '.join(fc_display)}")

                    full_message = "\n".join(header_parts)
                    if conclusion_parts:
                        full_message += "\n\n" + "\n\n".join(conclusion_parts)

                    await self.slack_notifier.send_notification(
                        title="✅ Task Completed",
                        message=full_message,
                        severity="info",
                        metadata={
                            "task_id": task.id,
                            "task_type": task.type.value,
                            "source": task.source.value,
                            "confidence": f"{confidence:.0%}",
                            "score": f"{completion_score:.3f}" if completion_score else "N/A",
                        }
                    )

                # Memory capture handled automatically by neural bridge during task execution

                # PERSISTENCE: Record task completion to database for cross-session persistence
                try:
                    from core.database import get_database_manager
                    db = get_database_manager()

                    # Calculate execution duration if available
                    execution_duration = None
                    if hasattr(task, 'started_at') and task.started_at:
                        execution_duration = int((datetime.now().timestamp() - task.started_at) / 1000)

                    # Prepare result summary (truncate to 1000 chars)
                    result_summary = str(result)[:1000] if result else "Task completed successfully"

                    await db.execute_query(
                        """
                        INSERT INTO task_execution_history (
                            task_id,
                            task_name,
                            task_type,
                            task_source,
                            completion_status,
                            result_summary,
                            confidence_score,
                            completed_at,
                            execution_duration_seconds,
                            metadata
                        ) VALUES (
                            $1, $2, $3, $4,
                            'completed',
                            $5, $6, NOW(), $7, $8
                        )
                        """,
                        params=(
                            task.id,
                            task.description[:512] if task.description else task.id,
                            task.type.value,
                            task.source.value,
                            result_summary,
                            float(confidence) if confidence is not None else None,
                            execution_duration,
                            json.dumps({"completed_at": datetime.now().isoformat()}),
                        ),
                        commit=True,
                    )

                    logger.info("💿 Task completion recorded to database for persistence")
                except Exception as db_error:
                    logger.warning(f"Failed to record task completion to database: {db_error}")
            else:
                # A substrate planning failure carries a typed deficit: the domain
                # authority already diagnosed WHY the goal was unreachable. That IS
                # the substrate's own model-free re-derive — so emit it to the
                # close-deficit reaction (which acts only if the disposition and the
                # deficit KIND allow) and suppress the LLM diagnostic below for it.
                # Emitted once per task (the flag) so bounded retries don't
                # re-explore the same gap every attempt.
                _deficit = result.get("deficit") if isinstance(result, dict) else None
                if _deficit and not (task.metadata or {}).get("deficit_closure_emitted"):
                    if task.metadata is None:
                        task.metadata = {}
                    task.metadata["deficit_closure_emitted"] = True
                    await self.emit(SelfEvent(
                        SelfEventType.DEFICIT_DIAGNOSED,
                        payload=DeficitDiagnosed(
                            task_id=task.id,
                            domain=_deficit.get("domain_id"),
                            deficit=_deficit),
                        origin="_execute_and_validate_task"))

                # Retry or fail
                if task.retry_count < task.max_retries:
                    logger.warning(f"🔄 Task failed validation, retrying: {task.id}")
                    task.retry_count += 1

                    # DISPOSITION AT FAILURE — the behavior arbiter turns
                    # appraisal's accumulated pressures into a decision for this
                    # situation. `should_escalate` means the failure is attributed
                    # OUTSIDE the self (a repeated, externally-blocked failure);
                    # `should_replan` means it is internally re-derivable. The
                    # AppraisalSystem owns that accumulation — this only CONSUMES
                    # the arbiter's verdict (below, to steer the self-directed
                    # diagnostic) and records it for attribution. A neutral/absent
                    # appraisal yields a neutral directive (both False), preserving
                    # the prior behaviour exactly.
                    _directive = self.disposition()

                    # FAILURE CONTEXT: Record exactly WHY this attempt failed so the
                    # next execution has concrete error information rather than retrying
                    # blindly with the exact same prompt and making the exact same mistakes.
                    if task.metadata is None:
                        task.metadata = {}
                    _failure_history = task.metadata.get('failure_history', [])
                    _tool_results_for_history = (result or {}).get('tools_run', [])
                    _failed_tools_for_history = [
                        {'tool': r['tool'], 'error': str(r.get('error', r.get('result', '')))[:300]}
                        for r in _tool_results_for_history
                        if isinstance(r, dict) and r.get('tool') and not r.get('success', True)
                    ]
                    _failure_history.append({
                        'attempt': task.retry_count,
                        'issues': issues or ['Unknown'],
                        'failed_tools': _failed_tools_for_history,
                        'error': str((result or {}).get('error', ''))[:400],
                        'disposition': _directive.to_dict(),
                    })
                    task.metadata['failure_history'] = _failure_history
                    logger.info(f"📋 Stored failure context for retry (attempt {task.retry_count}): {len(issues or [])} issues, {len(_failed_tools_for_history)} failed tools")

                    # MEMORY-INFORMED RETRY — ONLY FOR A TASK THAT ALREADY
                    # DECLARES TOOLS, AND ONLY ITS CONFIG ARGS.
                    #
                    # `_select_retry_method` returns None unless the task already
                    # carries a `tool_plan`, so this reaches ONLY the work that was
                    # declared with one: an agent the substrate deployed with a
                    # granted toolset, or a benchmark harness. It never gives a
                    # tool_plan to a task that had none, and it never changes tool
                    # NAMES, targets or payload — only config args (`create_dirs`,
                    # `mode`, `recursive`) it has seen work, transferred on a
                    # condition match.
                    #
                    # This is NOT the substrate's own execution path and must never
                    # become one. The substrate's own failed work has exactly two
                    # honest answers, and both live around this block:
                    #
                    #   * The cause is OUTSIDE the substrate — the escalation below
                    #     surfaces the blocker and stops thrashing. It fails.
                    #   * The substrate does not KNOW HOW — the typed deficit
                    #     emitted above (`DEFICIT_DIAGNOSED`) sends it to
                    #     `_react_close_deficit`: research the gap through the
                    #     learning authority, acquire the capability, then act and
                    #     verify against the world.
                    #
                    # Skipped on escalation — an external blocker is not fixed by
                    # changing an argument.
                    if not _directive.should_escalate:
                        _cur_failed = [r.get('tool') for r in ((result or {}).get('tools_run') or [])
                                       if isinstance(r, dict) and r.get('tool') and not r.get('success')]
                        _picked = self._select_retry_method(
                            task, (task.metadata or {}).get("recalled_experience"), _cur_failed)
                        if _picked:
                            _new_plan, _change, _structured = _picked
                            task.metadata.setdefault("parameters", {})["tool_plan"] = _new_plan
                            task.metadata["retry_method_changed"] = _change
                            task.metadata["retry_method_structured"] = _structured
                            logger.info(
                                "🔁 Task %s retrying a DECLARED tool plan with config "
                                "args learned from experience: %s", task.id, _change)

                    requeue_success = await self.task_queue.requeue_task(task.id)

                    # ROOT-CAUSE IS MODEL-FREE AND INLINE. The substrate's diagnosis is
                    # the failure_history recorded above (issues, failed tools, errors,
                    # disposition) plus the typed deficit emitted before the retry —
                    # NOT a queued LLM "investigation". A diagnostic was previously spawned
                    # here as a TaskType.ANALYSIS whose description instructed an LLM to
                    # investigate; the model-free substrate has no handler for it ("the
                    # model is not a fallback"), so it could NEVER complete and instead
                    # stranded an un-runnable task in the durable queue that re-surfaced as
                    # a false "task failed" CRITICAL on every boot. So no diagnostic task
                    # is spawned. ESCALATION: when the appraisal attributes the failure to
                    # an EXTERNAL blocker, the bounded retry alone can't fix it — surface
                    # the blocker honestly and record it for attribution (the retry above
                    # still runs; we just don't thrash).
                    if _directive.should_escalate:
                        logger.warning(
                            "🧭 Task %s failure attributed to an EXTERNAL blocker (%s); "
                            "surfacing the blocker for attribution.",
                            task.id,
                            ", ".join(_directive.reason_codes) or "escalation")
                        if task.metadata is None:
                            task.metadata = {}
                        task.metadata['escalation'] = {
                            'external_blocker': True,
                            'reason_codes': list(_directive.reason_codes),
                            'attempt': task.retry_count,
                        }
                        self.stats["external_blocker_escalations"] += 1
                    else:
                        logger.info(f"[DiagGuard] Skipping diagnostic spawn for already-diagnostic task {task.id} — breaking recursion")

                    # CRITICAL: If requeue failed (max retries exceeded), mark as permanently failed
                    # This prevents tasks from getting stuck IN_PROGRESS and blocking idle state
                    if not requeue_success:
                        logger.error(f"❌ Task {task.id} exceeded retry limit - marking as permanently failed")
                        issues_str = ', '.join(issues) if issues else 'Unknown'
                        await self.task_queue.mark_failed(
                            task.id,
                            f"Validation failed after {task.max_retries} retries: {issues_str}"
                        )

                        # DEDUP: Permanently block this fingerprint so it is never re-queued
                        try:
                            from .idle_work_playbook import IdleWorkPlaybook as _IWP
                            _pf = _IWP.description_fingerprint(task.description)
                            self._permanently_failed_fps.add(_pf)
                            _fp_list = list(getattr(self, '_recent_exploration_fp_list', []))
                            if _pf not in _fp_list:
                                _fp_list.append(_pf)
                                self._recent_exploration_fp_list = _fp_list[-20:]
                            self._save_permanently_failed_fps()
                            logger.info(f"🚫 Fingerprint {_pf} permanently blocked (task {task.id} exhausted retries)")
                        except Exception as _fp_err:
                            logger.debug(f"Failed to record failed fingerprint: {_fp_err}")

                        # META MEMORY: Store task failure for learning
                        await self._store_task_outcome_meta_memory(
                            task=task,
                            outcome="failure",
                            confidence=confidence,
                            failure_reason=f"Max retries exceeded: {issues_str}"
                        )
                else:
                    issues_str = ', '.join(issues) if issues else 'Unknown'
                    await self.task_queue.mark_failed(
                        task.id,
                        f"Validation failed: {issues_str}"
                    )
                    logger.error(f"❌ Task failed: {task.id} - Issues: {issues_str}")

                    # DEDUP: Permanently block this fingerprint so it is never re-queued
                    try:
                        from .idle_work_playbook import IdleWorkPlaybook as _IWP
                        _pf = _IWP.description_fingerprint(task.description)
                        self._permanently_failed_fps.add(_pf)
                        _fp_list = list(getattr(self, '_recent_exploration_fp_list', []))
                        if _pf not in _fp_list:
                            _fp_list.append(_pf)
                            self._recent_exploration_fp_list = _fp_list[-20:]
                        self._save_permanently_failed_fps()
                        logger.info(f"🚫 Fingerprint {_pf} permanently blocked (task {task.id} failed)")
                    except Exception as _fp_err:
                        logger.debug(f"Failed to record failed fingerprint: {_fp_err}")

                    # META MEMORY: Store task failure for learning
                    await self._store_task_outcome_meta_memory(
                        task=task,
                        outcome="failure",
                        confidence=confidence,
                        failure_reason=issues_str
                    )

                    # SLACK NOTIFICATION: Notify task failure with actionable details
                    if self.slack_notifier:
                        import re
                        task_desc = task.description.split('\n')[0][:200]
                        task_desc = re.sub(r'/[^\s]+', '[file]', task_desc)

                        # Clean up issues for display (remove paths, limit length)
                        issues_clean = re.sub(r'/[^\s]+', '[path]', issues_str)[:400]

                        # Retry status
                        retry_info = f"Retry {task.retry_count + 1}/3" if task.retry_count < 3 else "Max retries reached"

                        # Completion score from result
                        completion_score = result.get('completion_score') if result else None

                        # Summary of what was attempted
                        summary_text = (result.get('summary') or '').strip() if result else ''

                        # Tools that were run
                        tool_results_f = result.get('tool_results', []) if result else []
                        tools_used_f = list(dict.fromkeys(
                            r['tool'] for r in tool_results_f
                            if isinstance(r, dict) and r.get('tool') and r.get('success')
                        ))

                        iterations_f = result.get('iterations', 1) if result else 1

                        # Build detailed message
                        details = [
                            f"*Task ID:* `{task.id}`",
                            f"*Task:* {task_desc}",
                            f"*Type:* {task.type.value.replace('_', ' ').title()}",
                            f"*Retry Status:* {retry_info}",
                            f"*Iterations:* {iterations_f}",
                        ]

                        if completion_score is not None:
                            details.append(f"*Score:* {completion_score:.3f} (need >= 0.85)")

                        # Execution duration
                        if hasattr(task, 'started_at') and task.started_at:
                            try:
                                exec_time_f = int((datetime.now() - task.started_at).total_seconds())
                            except TypeError:
                                exec_time_f = int(datetime.now().timestamp() - task.started_at)
                            if exec_time_f > 60:
                                details.append(f"*Duration:* {exec_time_f // 60}m {exec_time_f % 60}s")
                            else:
                                details.append(f"*Duration:* {exec_time_f}s")

                        if tools_used_f:
                            details.append(f"*Tools Used:* {', '.join(tools_used_f[:6])}")

                        details.append(f"\n*Failure Reason:*\n{issues_clean}")

                        if summary_text:
                            summary_preview = summary_text[:300] + ('…' if len(summary_text) > 300 else '')
                            details.append(f"\n*What Was Attempted:*\n{summary_preview}")

                        severity = "warning" if task.retry_count < 2 else "error"
                        title = "⚠️ Task Requires Attention" if task.retry_count < 2 else "❌ Task Failed After Retries"

                        await self.slack_notifier.send_notification(
                            title=title,
                            message="\n".join(details),
                            severity=severity,
                            metadata={
                                "task_type": task.type.value,
                                "source": task.source.value,
                                "retry_count": task.retry_count,
                                "task_id": task.id,
                            }
                        )

                    # MEMORY CAPTURE: Store failed task for learning
                    try:
                        await self.store_memory(
                            MemoryType.EPISODIC,  # Failures are specific events
                            {
                                "event": "task_execution_failed",
                                "task_id": task.id,
                                "task_type": task.type.value,
                                "task_source": task.source.value,
                                "description": task.description,
                                "failure_reason": issues_str,
                                "retry_count": task.retry_count,
                                "result": result,
                                "timestamp": datetime.now().isoformat(),
                                # Fields required by intrinsic_motivation.py failure analysis
                                "status": "failed",
                                "confidence": 0.3,
                                "component": getattr(task, 'component', task.type.value),
                            },
                            importance=0.7,  # Failed tasks important for learning
                            tags=[
                                "task_execution",
                                task.type.value.lower(),
                                task.source.value.lower(),
                                "failed",
                                "learning"
                            ]
                        )
                        logger.info(f"💾 Task failure stored to memory for learning")
                    except Exception as mem_error:
                        logger.warning(f"Failed to store failure memory: {mem_error}")

                    # PERSISTENCE: Record task failure to database
                    try:
                        from core.database import get_database_manager
                        db = get_database_manager()

                        await db.execute_query(
                            """
                            INSERT INTO task_execution_history (
                                task_id,
                                task_name,
                                task_type,
                                task_source,
                                completion_status,
                                result_summary,
                                confidence_score,
                                completed_at,
                                retry_count,
                                metadata
                            ) VALUES (
                                $1, $2, $3, $4,
                                'failed',
                                $5, $6, NOW(), $7, $8
                            )
                            """,
                            params=(
                                task.id,
                                task.description[:512] if task.description else task.id,
                                task.type.value,
                                task.source.value,
                                f"Failed: {issues_str}",
                                0.0,  # Failed tasks have 0 confidence
                                task.retry_count,
                                json.dumps({"failed_at": datetime.now().isoformat(), "reason": issues_str}),
                            ),
                            commit=True,
                        )

                        logger.info("💿 Task failure recorded to database")
                    except Exception as db_error:
                        logger.warning(f"Failed to record task failure to database: {db_error}")

        except Exception as e:
            logger.error(f"Error executing task {task.id}: {e}")
            import traceback
            traceback.print_exc()
            await self.task_queue.mark_failed(task.id, f"Execution error: {str(e)}")

        finally:
            # Intrinsic exploration cap/dedup uses task queue state; no per-task lock cleanup needed.
            if _contract_token is not None:
                from core.safety.action_contract import reset_active_contract
                reset_active_contract(_contract_token)

    async def _execute_completion_callbacks(
        self,
        task: Task,
        result: Dict[str, Any],
        confidence: float
    ):
        """
        Execute all registered completion callbacks for this task type.
        
        This is the GENERIC CLOSURE MECHANISM - any subsystem can register
        callbacks to clean up, update state, or trigger follow-up actions
        when tasks complete.
        
        Args:
            task: Completed task
            result: Task execution result
            confidence: Completion confidence score
        """
        # Check task-level callbacks first (highest priority)
        if task.completion_callbacks:
            for callback_fn, metadata in task.completion_callbacks:
                try:
                    logger.debug(f"Executing task-level callback: {metadata.get('name', 'unknown')}")
                    await callback_fn(task, result, confidence)
                except Exception as e:
                    logger.error(
                        f"Task-level callback failed for {task.id}: {e}",
                        exc_info=True
                    )
        
        # Check registry callbacks (type + source based)
        key = (task.type, task.source)
        if key in self._completion_callbacks:
            for handler_info in self._completion_callbacks[key]:
                try:
                    callback_fn = handler_info['callback']
                    description = handler_info['description']
                    
                    logger.debug(
                        f"Executing completion callback: {description} "
                        f"for {task.type.value}/{task.source.value}"
                    )
                    
                    await callback_fn(task, result, confidence)
                    
                except Exception as e:
                    logger.error(
                        f"Completion callback failed ({description}): {e}",
                        exc_info=True
                    )
    
    async def handle_user_request(
        self,
        message: str,
        source: str = "api",
        priority: str = "high",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Accept work from the user and run it ON the substrate.

        The companion is not a separate agent with its own rules -- it is the
        user's connection to Torin. So a user request must enter through the
        same door as everything else: the task queue, the safety gate, the
        tools, memory, beliefs, meta-learning and credit assignment.

        This entry point did not exist. `TaskSource.API` and `TaskSource.MANUAL`
        were defined, the queue reserved them as NON_DISCRETIONARY (never
        refused however deep the backlog, task_queue:177) and exempted them from
        governance (task_queue:266) -- and nothing in the codebase ever created
        a task with either source. A privileged lane for user-directed work that
        has never carried a task.

        Returns the task id; the cognition loop picks it up on its next ~2s
        cycle, ahead of autonomous work now that priority ordering is correct.

        UNLESS IT IS A QUESTION, in which case it is answered here.

        Everything used to become a Task. Asking "What is a load balancer?"
        therefore got the full autonomous-work machinery: capability inference
        matched `load` and inferred `simulate_load`, 84 tools were selected and
        ranked (`load_test`, `run_shell_command`, `create_chaos_experiment` --
        no research tool anywhere), 31,137 of a 32,768-token window went to
        tool schemas, a Bayesian budget granted 26 iterations over 4,680
        seconds, and the first thing it did was create a directory. The model's
        own reasoning said "I don't need to run any tools to answer this
        conceptually, but per my instructions, I should". Measured, in the live
        system.

        A question is not a job and must not be costed like one.
        """
        from .shared_types import (Task, TaskType, TaskSource, Priority,
                                   actor_for)

        # ONE CONVERSATION PER THREAD OF TALK, SHARED BY BOTH HALVES OF A TURN.
        #
        # These two calls each used to construct their own `Conversation()`, so
        # classifying a message and understanding it happened in different
        # objects and neither could see the other. Everything continuity hangs
        # on -- the turn record, the last subject, the running recall -- was
        # discarded between them, and every message arrived as if it were the
        # first.
        #
        # The session comes from the caller when it has one. It is NOT
        # defaulted to a shared constant: unrelated speakers sharing a key
        # would surface one person's turns as context for another, which is
        # worse than having no continuity.
        session = str((metadata or {}).get("conversation_id")
                      or (metadata or {}).get("session_id")
                      or f"{source}:unsessioned")

        # WHO is speaking, when it has been VERIFIED. The membrane authenticates a
        # crossing (World Auth -> a gateway principal) and the adapter that hands a
        # message to this door puts the verified identity in `metadata["actor_identity"]`.
        # It is the actor a told fact is scoped to -- so a fact learned from this
        # person is THEIR context, not the shared mind. Trusted ONLY because the
        # membrane set it: never read it from the message text, and never from an
        # unauthenticated source. Absent (no verified identity) the conversation
        # falls back to the session as an anonymous per-thread scope.
        # THE FRONT DOOR ALWAYS SCOPES. A request here is a PUBLIC user (reaching
        # the substrate through the gate), never in-process curriculum — so it must
        # never write the shared mind. Bind a verified World Auth identity when the
        # membrane supplies one, else the session as a fail-safe per-thread scope;
        # either way `actor_for` yields a non-substrate actor. (Only a bare in-process
        # Conversation, with no identity, teaches the shared mind — see `_actor`.)
        actor_identity = (metadata or {}).get("actor_identity") or session
        requester_actor = actor_for(TaskSource.MANUAL, actor_identity)

        # A structured TASK-RESULT poll: the caller holds a task_id from a prior
        # ack and wants the outcome. Answered here, scoped to the requester, with no
        # classification (it is not a sentence to read). Completes the task loop.
        task_result_id = (metadata or {}).get("task_result")
        if task_result_id:
            return await self.get_task_result(str(task_result_id), actor=requester_actor)

        kind = await self._request_kind(message, session=session,
                                        actor_identity=actor_identity)
        if kind in ("question", "telling"):
            answered = await self._answer_from_what_is_held(
                message, session=session, actor_identity=actor_identity)
            if answered is not None:
                return answered

        src = {
            "api": TaskSource.API,
            "manual": TaskSource.MANUAL,
        }.get(str(source).lower(), TaskSource.API)
        pri = {
            "critical": Priority.CRITICAL,
            "high": Priority.HIGH,
            "medium": Priority.MEDIUM,
            "low": Priority.LOW,
        }.get(str(priority).lower(), Priority.HIGH)

        # SCOPE THE TASK TO WHO ASKED (the same `requester_actor` a result poll uses):
        # Task.actor is read downstream for which memories enter its cognition, whose
        # evidence a runtime outcome attributes to, and which profile it feeds. Never
        # the substrate for user work -- that is the leak actor_for guards against.
        task = Task(
            id=f"user_{uuid.uuid4().hex[:12]}",
            type=TaskType.ANALYSIS,
            description=message,
            priority=pri,
            source=src,
            actor=requester_actor,
            created_by="user",
            metadata={"origin": "user_request", **(metadata or {})},
        )

        accepted = await self.task_queue.add_task(task, priority=pri)
        if not accepted:
            return {
                "success": False,
                "error": "task queue refused the request",
                "task_id": task.id,
            }

        logger.info(f"👤 User request accepted: {task.id} ({src.value}, {pri.name})")
        # The ack carries the handle to poll the result (`metadata={"task_result": id}`),
        # so the caller can complete the loop once the cognition cycle finishes the work.
        return {"success": True, "task_id": task.id, "source": src.value,
                "priority": pri.name, "poll_with": {"task_result": task.id}}

    async def get_task_result(self, task_id: str, *,
                              actor: str = SUBSTRATE_ACTOR) -> Dict[str, Any]:
        """The outcome of a submitted job, scoped to WHO submitted it — the other
        half of the task loop. `handle_user_request` hands back a `task_id` ack; the
        cognition loop runs the work and records the result (`queue.mark_completed`);
        this returns it. A job owned by a different actor reads as `not_found`, so a
        caller can only ever read its own work (no cross-actor enumeration).

        Status is one of: pending/in_progress/awaiting_verification/blocked (still
        working), completed (carries `result`), failed (carries `error`), or
        not_found. Safe to poll; it never mutates the task."""
        return await self.task_queue.result_for(task_id, actor=actor)

    def set_reply_debug(self, on: bool) -> bool:
        """Switch user-facing reply detail. On: replies carry the full derivation
        chain (say()) for diagnosing. Off (default): a plain sentence. Returns the
        new state."""
        self.reply_debug = bool(on)
        logger.info("reply_debug %s", "ON" if self.reply_debug else "OFF")
        return self.reply_debug

    async def _request_kind(self, message: str, session: str,
                            actor_identity=None) -> str:
        """Asking, telling, or a job to do.

        DELEGATED, NOT DECIDED HERE. This used to ask a model directly while
        `Conversation.is_question` asked a rule, and the two disagreed -- a
        plain statement was classified as a question and filed in memory as one.
        Whether a sentence asks is a fact about the sentence, and the component
        that reads sentences owns it.
        """
        try:
            return await self.conversation(
                session, actor_identity=actor_identity).classify(message)
        except Exception as error:
            logger.info("request kind undetermined (%s); treating as work", error)
            return "job"

    async def _answer_from_what_is_held(
        self, message: str, session: str, actor_identity=None
    ) -> Optional[Dict[str, Any]]:
        """Answer out of the concept store and memory, and remember the exchange.

        Returns None when nothing could be assembled, so the caller falls
        through to the work path rather than replying with an apology.
        """
        conv = self.conversation(session, actor_identity=actor_identity)
        try:
            understanding = await conv.understand(message)
        except Exception as error:
            logger.warning("could not answer from what is held: %s", error)
            return None

        # A DERIVED answer is held knowledge too. The substrate may have proved
        # the answer from what it holds without any single concept being
        # `known`, so `answers` (a reasoned or direct verdict) counts as having
        # answered -- otherwise a question the substrate PROVED would be dropped
        # to the work path as though nothing were held.
        if not (understanding.known or understanding.remembered
                or understanding.acquired or understanding.answers):
            return None

        try:
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            agent = await get_memory_agent()
            content = (f"Asked: {message[:300]} — "
                       + ("answered from held knowledge"
                          if understanding.answered
                          else "could not answer; asked what it is"))

            # AN ANSWER MAY BE THE END OF SOMETHING. If a question about this
            # was asked before and left open, this settles that episode rather
            # than starting a second one beside it -- otherwise memory holds
            # "could not answer" and "answered" about the same thing forever,
            # and recall keeps returning whichever it reaches first.
            closed = None
            if understanding.answered:
                closed = await agent.close_open(
                    message, content, because="answered on a later turn")

            if closed is None:
                await agent.store_memory(
                    memory_type=MemoryType.EPISODIC,
                    content=content,
                    importance_score=0.7, confidence_score=0.9,
                    tags=["user_exchange"] + (
                        ["answered"] if understanding.answered
                        else [agent.OPEN_TAG, "asked_back"]),
                    source_context={"source_system": "handle_user_request"},
                    thinking_state={"reply_preview": understanding.reply[:400],
                                    "acquired": [a.label for a in understanding.acquired]})
        except Exception as error:
            # Never let a memory failure swallow an answer that was produced.
            logger.warning("exchange NOT remembered: %s", error)

        # A USER gets a plain sentence, not the derivation chain say() shows for
        # introspection — unless reply_debug is switched on, which surfaces the
        # full chain for diagnosing. Falls back to the composed reply when there
        # is no verdict to state (a taught-back note, an asked-back question).
        answer_text = (understanding.reply if self.reply_debug
                       else (conv.natural_reply(understanding) or understanding.reply))
        return {"success": True, "kind": "question", "answer": answer_text,
                "learned": [a.label for a in understanding.acquired if a.stored],
                "closed_open_memory": closed, "source": "substrate"}

    async def _collect_system_context_for_goals(self) -> Dict[str, Any]:
        """Collect actual system context to inform intrinsic goal generation"""
        context = {}

        try:
            # Failed tasks from task queue
            try:
                failed = await self.task_queue.get_failed_tasks(limit=10)
                if failed:
                    context["failed_tasks"] = [
                        {
                            "description": task.description,
                            "failure_reason": getattr(task, 'failure_reason', 'unknown'),
                            "status": "failed",  # Required by intrinsic_motivation
                            "confidence": getattr(task, 'confidence', 0.3),  # Low confidence for failed tasks
                            "component": getattr(task, 'component', 'unknown')  # Component identifier
                        }
                        for task in failed
                    ]
            except Exception as e:
                logger.debug(f"Could not get failed tasks: {e}")

            # The substrate's OWN maintenance machinery failing is interoception
            # too. A scheduled tier erroring or a persistence write failing is an
            # internal fault of the same character as a failed task, and it
            # should register as component uncertainty (which drives affect and
            # curiosity via _quantify_component_uncertainties), not sit only in
            # the health monitor. This is a SENSE, not strategy credit — it never
            # enters ULS's credited meta-learner, so the credit invariant (never
            # charge a strategy for infra failure) is untouched. Emitted on the
            # DELTA — only machinery that erred SINCE the last refresh — so a
            # fault that already recovered leaves no phantom uncertainty.
            try:
                recent_errors = []
                prev_tier = getattr(self, "_last_tier_error_counts", {})
                now_tier = {}
                for job in self.task_queue.scheduled_job_status():
                    now_tier[job["name"]] = job["errors"]
                    if job["errors"] > prev_tier.get(job["name"], 0) and job.get("last_error"):
                        recent_errors.append({
                            "component": f"scheduler:{job['name']}",
                            "type": str(job["last_error"]).split(":")[0],
                        })
                self._last_tier_error_counts = now_tier

                qstats = await self.task_queue.get_statistics()
                prev_persist = getattr(self, "_last_persist_errors", 0)
                if qstats.get("persist_errors", 0) > prev_persist:
                    recent_errors.append({"component": "queue_persistence",
                                          "type": "PersistError"})
                self._last_persist_errors = qstats.get("persist_errors", 0)

                if recent_errors:
                    context["recent_errors"] = recent_errors
            except Exception as e:
                logger.debug(f"Could not collect queue-authority interoception: {e}")

            # INNOVATION SIGNALS: Frontier foresight (tech frontiers, emerging domains, safety priorities)

            # Current motivation state (so goals are informed by what the system is curious about)
            if hasattr(self, '_current_motivation') and self._current_motivation:
                context["motivation_state"] = self._current_motivation


            # Knowledge cutoff state — critical for research goal grounding
            try:
                kc_state = getattr(self, "_knowledge_cutoff_state", {}) or {}
                context["knowledge_cutoff"] = {
                    "refreshed_through_date": kc_state.get("refreshed_through_date"),
                    "declared_cutoff": self._get_declared_model_cutoff_date(),
                    "last_topics_researched": kc_state.get("last_topics_researched", [])[:5],
                }
            except Exception as _kc_err:
                logger.debug(f"Could not get knowledge cutoff state: {_kc_err}")

            # System review snapshot — tool inventory and codebase stats
            try:
                snapshot = getattr(self, "_idle_system_review_snapshot", None)
                if snapshot:
                    context["system_review"] = snapshot.get("highlights", {})
                    tools_data = snapshot.get("tools") or {}
                    top_cats = tools_data.get("top_categories", [])
                    if top_cats:
                        context["available_tool_categories"] = [
                            c.get("category", "") for c in top_cats[:8] if c.get("category")
                        ]
            except Exception as _sr_err:
                logger.debug(f"Could not get system review snapshot: {_sr_err}")

            # Recently completed/verified tasks — so LLM avoids repeating them
            try:
                recent_done: list = []
                for _queued in list(getattr(self.task_queue, "tasks_by_id", {}).values())[-40:]:
                    _status = str(getattr(_queued, "status", "")).lower()
                    if _status in ("completed", "verified", "success"):
                        _inner = getattr(_queued, "task", None)
                        _desc = getattr(_inner, "description", "") if _inner else ""
                        if _desc:
                            recent_done.append(_desc[:120])
                if recent_done:
                    context["recently_completed_tasks"] = recent_done[-5:]
            except Exception as _rc_err:
                logger.debug(f"Could not get recent completed tasks: {_rc_err}")

            # Test suite info — so the AI knows its tests exist and where they are
            try:
                import os as _os
                _torin_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
                _tests_dir = _os.path.join(_torin_root, "tests")
                if _os.path.isdir(_tests_dir):
                    _test_cats = sorted(
                        d for d in _os.listdir(_tests_dir)
                        if _os.path.isdir(_os.path.join(_tests_dir, d)) and not d.startswith("_")
                    )
                    context["test_suite_info"] = {
                        "tests_root": _tests_dir,
                        "categories": [c for c in _test_cats if c != "governance"],
                        "key_test_files": [
                            "tests/test_security_tools.py",
                            "tests/test_system_tools.py",
                            "tests/test_reasoning_systems.py",
                            "tests/test_ai_performance_suite.py",
                            "tests/chaos/test_chaos_orchestrator.py",
                            "tests/memory/test_memory_system.py",
                        ],
                    }
            except Exception as _ts_err:
                logger.debug(f"Could not collect test suite info: {_ts_err}")

        except Exception as e:
            logger.error(f"Error collecting system context: {e}")

        return context

    async def _handle_idle_state(self):
        """Legacy method - exploration is now continuous, not idle-gated.
        Redirects to _run_exploration_cycle for backward compatibility."""
        await self._run_exploration_cycle()

    async def _check_constitutional_alignment(self):
        """
        Check Singleton's alignment with constitutional principles.
        Detects drift in core responsibilities (learning, research, maintenance, security).
        """
        try:
            logger.info("📜 Checking Singleton constitutional alignment...")

            # Refresh self-state from the real subsystems (resource_usage,
            # error_rate, goal_alignment, ...), then merge the HEALTH authority's
            # overall status + critical-component count — the metrics Laws 3 and 5
            # read. Without this the assessment ran against the conservative
            # default (empty metrics), scoring the health/harm laws from no data.
            await self._update_system_state()
            try:
                from core.health.health_monitor import get_health_monitor
                health = await get_health_monitor().get_system_health()
                components = health.get("components", {}) or {}
                critical = [c for c, h in components.items()
                            if str(h.get("status", "")).lower() == "critical"]
                degraded = [c for c, h in components.items()
                            if str(h.get("status", "")).lower() in ("degraded", "unhealthy")]
                os_status = str(health.get("status", "healthy")).lower()
                if critical or os_status == "critical":
                    overall = "critical"
                elif degraded or os_status in ("degraded", "unhealthy"):
                    overall = "degraded"
                else:
                    overall = "healthy"
                self.system_state.performance_metrics["overall_status"] = overall
                self.system_state.performance_metrics["critical_issues"] = len(critical)
                # resource_usage (Laws 1 & 5) — the health authority owns the real
                # CPU/memory sample; take the higher as the pressure scalar.
                cpu = float(health.get("cpu_percent", 0.0) or 0.0)
                mem = float(health.get("memory_percent", 0.0) or 0.0)
                self.system_state.resource_usage = max(cpu, mem) / 100.0
            except Exception as e:
                # Honest gap: if health is unreadable, the health-derived metrics
                # are left as whatever the last refresh held rather than faked.
                logger.warning("constitutional check: health metrics unreadable: %s", e)

            # Perform constitutional assessment over the REAL system state.
            assessment = await self.constitution.assess_constitutional_alignment(
                system_state=self.system_state)
            
            # Handle critical drift
            if assessment.drift_severity in [DriftSeverity.CRITICAL, DriftSeverity.SIGNIFICANT]:
                logger.error(f"🚨 CONSTITUTIONAL DRIFT DETECTED: {assessment.drift_severity.value}")
                logger.error(f"   Overall alignment: {assessment.average_compliance:.1%}")

                # Format violation details
                violation_details = []
                for v in assessment.violations:
                    violation_details.append(f"Law {v.law_number} ({v.law_name}): {v.description}")

                # Publish notification to Employee UI (rate limited)
                try:
                    publish_ok = True
                    if self._last_drift_alert_at:
                        elapsed = (datetime.now() - self._last_drift_alert_at).total_seconds()
                        publish_ok = elapsed > 600  # 10 min cooldown
                    if publish_ok:
                        await publish_notification({
                            'type': 'security',
                            'title': 'Constitutional drift detected',
                            'message': (
                                f"Severity: {assessment.drift_severity.value}. "
                                f"Overall alignment: {assessment.average_compliance:.1%}. "
                                f"Violations: {len(assessment.violations)}"
                            ),
                            'status': 'info',
                            'metadata': {
                                'violations': len(assessment.violations),
                                'details': violation_details[:5]
                            }
                        })
                        self._last_drift_alert_at = datetime.now()
                except Exception:
                    pass
                
                # Log all violations
                for v_detail in violation_details:
                    logger.error(f"   {v_detail}")
                
                # Log the drift alert, then record it for self-reflection
                law_scores_str = chr(10).join(
                    f"  - Law {num}: {score:.1%}"
                    for num, score in assessment.law_compliance_scores.items()
                )
                drift_alert = f"""
CONSTITUTIONAL ALERT: System drift detected!

Alignment with governance laws has degraded:
- Overall Alignment: {assessment.average_compliance:.1%}
- Drift Severity: {assessment.drift_severity.value}

Law Compliance Scores:
{law_scores_str}

Violations ({len(assessment.violations)}):
{chr(10).join(f"  - {v}" for v in violation_details)}

The substrate must realign with its constitutional responsibilities immediately.
"""
                logger.error(drift_alert)

                # Record the drift alert for self-reflection. The memory agent
                # owns the store; the coordinator writes through its own
                # store_memory (this previously targeted a model handle that had
                # no `.memory`, so the alert was never actually recorded).
                from core.memory import MemoryType
                await self.store_memory(
                    MemoryType.META,
                    {
                        "type": "constitutional_drift_alert",
                        "severity": assessment.drift_severity.value,
                        "alignment_score": assessment.average_compliance,
                        "violations": [{
                            "law_number": v.law_number,
                            "law_name": v.law_name,
                            "description": v.description,
                            "compliance_score": v.compliance_score
                        } for v in assessment.violations],
                        "alert": drift_alert
                    },
                )
            
            # Log law scores even if no critical drift
            elif assessment.average_compliance < 0.95:
                logger.info(f"📋 Constitutional alignment: {assessment.average_compliance:.1%}")
                for law_num, score in assessment.law_compliance_scores.items():
                    if score < 0.95:
                        logger.info(f"   💡 Law {law_num}: {score:.1%}")
            
        except Exception as e:
            logger.error(f"Error checking constitutional alignment: {e}")

    async def _check_constitutional_alignment_quick(self):
        """Lightweight constitutional alignment check for every cycle."""
        try:
            assessment = await self.constitution.assess_quick_alignment()
            # Only escalate logs if drift is significant or worse
            if assessment.drift_severity in [DriftSeverity.SIGNIFICANT, DriftSeverity.CRITICAL]:
                logger.error(
                    f"🚨 QUICK DRIFT ALERT: severity={assessment.drift_severity.value}, "
                    f"overall_alignment={assessment.average_compliance:.1%}"
                )
        except Exception as e:
            logger.error(f"Error in quick constitutional alignment check: {e}")
    
    def _get_recent_task_outcomes(self, task_type: str, limit: int = 10) -> List[bool]:
        """
        Get recent outcome sequence for task type (for variance/decay analysis).

        Used by StrategyAdaptationGate to compute decay-weighted win rate and
        detect oscillating vs. consistently poor performance.

        Args:
            task_type: TaskType.value string
            limit: Maximum number of recent outcomes to return

        Returns:
            List of boolean outcomes [True=success, False=failure], most recent last
        """
        try:
            if not self.task_queue or not hasattr(self.task_queue, 'tasks_by_id'):
                return []

            # Query task queue for recent tasks of this type
            recent_tasks = []
            for task in list(self.task_queue.tasks_by_id.values())[-30:]:
                if hasattr(task, 'type') and task.type.value == task_type:
                    recent_tasks.append(task)

            if not recent_tasks:
                return []

            # Convert to outcome booleans (based on task status)
            outcomes = []
            for task in recent_tasks[-limit:]:
                if hasattr(task, 'status'):
                    status_str = str(task.status).lower()
                    # Completed = success, anything else = failure
                    outcomes.append(status_str == "completed")

            return outcomes

        except Exception as e:
            logger.debug(f"Error fetching recent outcomes for {task_type}: {e}")
            return []

    async def _learning_phase(self):
        """Apply learning recommendations and score the cycle's intrinsic rewards.

        Registered as the `idle_learning` tier. Written for the old phase loop
        and left uncalled by the AI-driven rewrite, so nothing consumed the
        experience learner's output.
        """
        if getattr(self, "learning", None) is None:
            logger.debug("[IDLE:LEARNING] No learning adapter — skipping")
            self._learning_phase_status = "NO_ADAPTER"
            return

        # Set to COMPLETED only at the terminal write. A phase that boosts a
        # priority and then dies on the reward calls did real work and lost the
        # rest of the cycle, which must not read as a successful learning cycle.
        self._learning_phase_status = "PARTIAL"
        applied_recommendations = []  # referenced by the abort handler

        try:
            # The learning authority does not emit "recommendations" — that was the
            # retired LearningAdapter's paradigm, and the adapter is gone. The
            # substrate learns continuously from action→outcome; there is no
            # recommendation feed to apply, so this loop no-ops honestly.
            recommendations = []

            # Apply high-confidence recommendations and calculate intrinsic rewards
            applied_recommendations = []
            # SUM of per-event rewards fired this cycle. UNBOUNDED — four
            # dimensions each in [-1,1] means this ranges roughly [-4,4].
            # Deliberately NOT named total_intrinsic_reward: that name belongs
            # to MotivationProfile's normalised drive level in [0,1], and the
            # collision produced 'Total reward: 1.70' in a field contracted to
            # [0,1]. Never feed this to AppraisalState.activation.
            cycle_reward_sum = 0.0
            
            for rec in recommendations:
                if rec.get("confidence", 0) > 0.8:
                    success = await self._apply_learning_recommendation(rec)
                    if success:
                        applied_recommendations.append(rec)
                        
                        # Calculate competence reward for successful learning application
                        competence_reward = await self.intrinsic_motivation.calculate_competence_reward(
                            # Competence accrues to the task type that earned
                            # it, not to the applier verb -- keyed on "type"
                            # every skill would be named prioritize_task_type.
                            skill_name=(
                                rec.get("action", {}).get("task_type")
                                or rec.get("action", {}).get("type", "general_learning")
                            ),
                            performance=rec.get("confidence", 0.8),
                            success=True
                        )
                        cycle_reward_sum += competence_reward.reward_value
            
            # Identify exploration targets from perception data
            perception_stats = await self.perception.get_statistics()
            if perception_stats.get("novel_patterns", 0) > 0:
                # Calculate curiosity reward for discovering novel patterns
                curiosity_reward = await self.intrinsic_motivation.calculate_curiosity_reward({
                    "information_gain": min(1.0, perception_stats.get("novel_patterns", 0) / 10.0),
                    "uncertainty_reduction": 0.5,
                    "question_complexity": 0.6,
                    "answer_depth": 0.5
                })
                cycle_reward_sum += curiosity_reward.reward_value
            
            # Calculate novelty reward for current cycle
            cycle_experience = {
                "active_goals": len(self.system_state.active_goals),
                "active_tasks": len(self.system_state.active_tasks),
                "cycle_count": self.stats["cycles_completed"],
                "resource_usage": self.system_state.resource_usage
            }
            novelty_reward = await self.intrinsic_motivation.calculate_novelty_reward(cycle_experience)
            cycle_reward_sum += novelty_reward.reward_value
            
            # Calculate autonomy reward (coordination is self-directed)
            autonomy_reward = await self.intrinsic_motivation.calculate_autonomy_reward({
                "self_initiated": True,
                "choice_made": len(recommendations) > 0,
                "exploration_ratio": 0.5  # Balanced exploration/exploitation
            })
            cycle_reward_sum += autonomy_reward.reward_value
            
            # Get top exploration targets for next cycle
            exploration_targets = await self.intrinsic_motivation.get_top_exploration_targets(limit=5)
            
            # Store learning insights in memory with intrinsic reward information
            if applied_recommendations or cycle_reward_sum > 0.1:
                await self.store_memory(
                    MemoryType.PROCEDURAL,
                    {
                        "event": "learning_with_intrinsic_rewards",
                        "recommendations": applied_recommendations,
                        "cycle_reward_sum": cycle_reward_sum,
                        "exploration_targets": [t.description for t in exploration_targets],
                        "context": {**cycle_experience,
                                    "system_mode": self.system_state.mode.value},
                        "timestamp": datetime.now().isoformat()
                    },
                    # CLAMPED. cycle_reward_sum is unbounded, so this produced
                    # importance=1.14 — and store_memory passes importance
                    # straight through as confidence_score, yielding a
                    # "confidence" above 1.0 in a field that is a probability.
                    importance=max(0.0, min(1.0, 0.8 + (cycle_reward_sum * 0.2))),
                    tags=["learning", "intrinsic_motivation", "autonomous_cycle"]
                )
            
            # Log intrinsic motivation insights
            if cycle_reward_sum > 0.5:
                logger.info(f"🌟 High intrinsic motivation cycle! Cycle reward SUM (unbounded): {cycle_reward_sum:.2f}")

            self._learning_phase_status = "COMPLETED"

        except Exception as e:
            self._learning_phase_status = "ABORTED"
            logger.error(
                f"Learning phase ABORTED after applying "
                f"{len(applied_recommendations)} recommendation(s) — rewards and "
                f"memory write for this cycle are lost: {e}"
            )

            import traceback
            # The handler must not be more fragile than the path it reports on:
            # an unguarded self.log_db here replaces the real failure with an
            # AttributeError and hides what actually broke.
            log_db = getattr(self, "log_db", None)
            if log_db is not None:
                try:
                    await log_db.log_operation(
                        operation_type='learning_phase_abort',
                        component='autonomous_coordinator',
                        message=f"{type(e).__name__}: {e}",
                        level='ERROR',
                        metadata={'function': '_learning_phase',
                                  'stack_trace': traceback.format_exc()},
                    )
                except Exception as log_error:
                    logger.error(f"Could not record learning phase abort: {log_error}")
            else:
                logger.error(
                    "Learning phase abort not recorded: no log_db\n%s",
                    traceback.format_exc(),
                )

    async def _execute_registered_capabilities(self):
        """
        Execute registered system capabilities based on conditions and intervals.
        
        This method enables TRUE ADAPTIVE INTELLIGENCE by allowing the coordinator to decide
        when capabilities should run based on system state, not hardcoded timers.
        
        Capabilities are checked in priority order (critical > high > medium > low) and
        executed only if:
        1. Minimum interval has elapsed since last run
        2. All configured conditions are met (feedback samples, performance, etc.)
        
        This transforms rigid "run every N seconds" into intelligent "run when needed"
        based on system feedback, performance metrics, and resource availability.
        """
        if not hasattr(self, 'registered_capabilities') or not self.registered_capabilities:
            return  # No capabilities registered yet
        
        try:
            now = datetime.now()
            
            # Sort capabilities by priority
            priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
            sorted_capabilities = sorted(
                self.registered_capabilities.items(),
                key=lambda x: priority_order.get(x[1]['priority'], 4)
            )
            
            for cap_name, cap_config in sorted_capabilities:
                try:
                    # Skip if not active
                    if cap_config['status'] != 'active':
                        continue
                    
                    # Check interval - has enough time passed?
                    last_run = self.capability_last_run.get(cap_name, datetime.min)
                    elapsed = (now - last_run).total_seconds()
                    interval = cap_config['interval']
                    
                    if elapsed < interval:
                        continue  # Not time yet
                    
                    # Check all conditions
                    conditions = cap_config['conditions']
                    if not await self._check_capability_conditions(cap_name, conditions):
                        logger.debug(f"Capability '{cap_name}' conditions not met, skipping")
                        continue
                    
                    # Execute the capability
                    instance = cap_config['instance']
                    method_name = cap_config['method']
                    method = getattr(instance, method_name)

                    logger.info(f"🔧 Executing capability: {cap_name} (priority: {cap_config['priority']})")

                    # Log capability execution start
                    self.log_db.log_coordination(
                        coordinator_type='autonomous',
                        action='capability_execution_start',
                        status='executing',
                        metadata={
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'elapsed_since_last': elapsed,
                            'execution_count': cap_config['execution_count']
                        }
                    )

                    import time
                    start_time = time.time()

                    # Call the method (handle both async and sync)
                    if asyncio.iscoroutinefunction(method):
                        result = await method()
                    else:
                        result = method()

                    execution_time = time.time() - start_time

                    # Update tracking
                    self.capability_last_run[cap_name] = now
                    cap_config['execution_count'] += 1
                    cap_config['last_result'] = result
                    cap_config['last_error'] = None

                    logger.info(f"✅ Capability '{cap_name}' executed successfully (run #{cap_config['execution_count']})")

                    # Log successful capability execution
                    self.log_db.log_coordination(
                        coordinator_type='autonomous',
                        action='capability_execution_complete',
                        status='completed',
                        result=f"Capability '{cap_name}' executed successfully",
                        metadata={
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'execution_count': cap_config['execution_count'],
                            'execution_time': execution_time
                        }
                    )

                    # Log performance metrics
                    self.log_db.log_performance(
                        operation='capability_execution',
                        duration=execution_time,
                        success=True,
                        details={
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'execution_count': cap_config['execution_count']
                        }
                    )

                    # Store execution in memory for learning
                    await self.store_memory(
                        MemoryType.PROCEDURAL,
                        {
                            'event': 'capability_execution',
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'result': str(result)[:500] if result else None,  # Truncate large results
                            'execution_count': cap_config['execution_count'],
                            'execution_time': execution_time,
                            'timestamp': now.isoformat()
                        },
                        importance=0.7 if cap_config['priority'] in ['critical', 'high'] else 0.5,
                        tags=['capability', 'autonomous', cap_name]
                    )

                except Exception as e:
                    logger.error(f"Error executing capability '{cap_name}': {e}")
                    cap_config['last_error'] = str(e)
                    cap_config['status'] = 'error'

                    import traceback
                    # Log error with full details
                    self.log_db.log_error(
                        error_type=type(e).__name__,
                        error_message=str(e),
                        module='autonomous_coordinator',
                        function='_execute_registered_capabilities',
                        stack_trace=traceback.format_exc(),
                        context={
                            'capability': cap_name,
                            'priority': cap_config['priority'],
                            'method': method_name
                        }
                    )
                    
        except Exception as e:
            logger.error(f"Error in capability execution phase: {e}")

            import traceback
            # Log error with full details
            self.log_db.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                module='autonomous_coordinator',
                function='_execute_registered_capabilities',
                stack_trace=traceback.format_exc(),
                context={'registered_capabilities_count': len(self.registered_capabilities) if hasattr(self, 'registered_capabilities') else 0}
            )

    async def _check_capability_conditions(self, cap_name: str, conditions: Dict[str, Any]) -> bool:
        """
        Check if all conditions for a capability are met.
        
        Args:
            cap_name: Capability name (for logging)
            conditions: Dict of condition checks
        
        Returns:
            True if all conditions met, False otherwise
        """
        try:
            # Check feedback sample minimum
            if 'min_feedback_samples' in conditions:
                min_samples = conditions['min_feedback_samples']
                # Query feedback count from memory using MemoryQuery
                try:
                    from core.memory import MemoryQuery, MemoryType
                    
                    feedback_query = MemoryQuery(
                        query_id=f"capability_check_{cap_name}_{datetime.now().timestamp()}",
                        content="user feedback and ratings",
                        memory_types=[MemoryType.EPISODIC],
                        max_results=min_samples + 10,  # Fetch a bit more to ensure we get enough
                        min_confidence=0.0
                    )
                    result = await self.memory.search_memories(feedback_query)
                    
                    # Filter for feedback-related memories
                    feedback_count = sum(1 for m in result.memories if 'feedback' in str(m.content).lower() or 'rating' in str(m.content).lower())
                    
                    if feedback_count < min_samples:
                        logger.debug(f"Capability '{cap_name}': Insufficient feedback samples ({feedback_count}/{min_samples})")
                        return False
                except Exception as e:
                    logger.debug(f"Could not query feedback memories: {e}")
                    # If we can't check, allow execution (fail open for this condition)
            
            # Check performance threshold
            if 'performance_threshold' in conditions:
                threshold = conditions['performance_threshold']
                # Resource usage might be a dict or float
                resource_usage = self.system_state.resource_usage
                if isinstance(resource_usage, dict):
                    current_performance = resource_usage.get('system_health', 1.0)
                else:
                    current_performance = 1.0  # Assume healthy if no data
                
                if current_performance < threshold:
                    logger.debug(f"Capability '{cap_name}': Performance below threshold ({current_performance:.2f}/{threshold})")
                    return False
            
            # Check error rate
            if 'error_rate_max' in conditions:
                max_error_rate = conditions['error_rate_max']
                current_error_rate = self.stats.get('error_rate', 0.0)
                
                if current_error_rate > max_error_rate:
                    logger.debug(f"Capability '{cap_name}': Error rate too high ({current_error_rate:.2f}/{max_error_rate})")
                    return False
            
            # Check memory usage
            if 'memory_usage_max' in conditions:
                max_memory = conditions['memory_usage_max']
                resource_usage = self.system_state.resource_usage
                if isinstance(resource_usage, dict):
                    current_memory = resource_usage.get('memory_percent', 0.0)
                else:
                    current_memory = 0.0  # Assume OK if no data
                
                if current_memory > max_memory:
                    logger.debug(f"Capability '{cap_name}': Memory usage too high ({current_memory:.2f}/{max_memory})")
                    return False
            
            # Custom check function
            if 'custom_check' in conditions:
                check_func = conditions['custom_check']
                if callable(check_func):
                    if asyncio.iscoroutinefunction(check_func):
                        result = await check_func(self)
                    else:
                        result = check_func(self)
                    
                    if not result:
                        logger.debug(f"Capability '{cap_name}': Custom check failed")
                        return False
            
            return True  # All conditions met
            
        except Exception as e:
            logger.error(f"Error checking conditions for '{cap_name}': {e}")
            return False  # Fail safe - don't execute if condition check fails
    
    async def _check_task_completions(self):
        """Check for task completions and update system state"""
        try:
            execution_status = await self.get_status()

            # Get completed tasks from execution controller
            completed_count = execution_status.get("completed_tasks", 0)

            # Check which of our active tasks have completed
            completed_task_ids = []

            # The execution controller maintains completed_tasks dict
            # We need to check if our active tasks are in there
            for task_id in list(self.system_state.active_tasks):
                # Check with execution controller if task completed
                # Completed tasks are moved from running_tasks to completed_tasks
                if task_id in self.completed_tasks:
                    completed_task = self.completed_tasks[task_id]

                    # Verify it actually completed successfully
                    if completed_task.status == TaskStatus.COMPLETED:
                        completed_task_ids.append(task_id)

                        # Log completion details
                        execution_time = "N/A"
                        execution_time_seconds = 0.0
                        if completed_task.completed_at and completed_task.created_at:
                            execution_time_seconds = (completed_task.completed_at - completed_task.created_at).total_seconds()
                            execution_time = f"{execution_time_seconds:.2f}s"

                        logger.info(
                            f"✅ Task completed: {completed_task.description} "
                            f"(execution time: {execution_time})"
                        )

                        # Record to constitutional framework if relevant
                        if hasattr(completed_task, 'result') and completed_task.result:
                            quality_score = completed_task.result.get('quality_score', 0.8)
                        else:
                            quality_score = 0.8  # Default for successful tasks

                        # Log task completion coordination
                        self.log_db.log_coordination(
                            coordinator_type='autonomous',
                            action='task_completion_verified',
                            task_id=task_id,
                            status='completed',
                            result=f'Task verified as completed: {completed_task.description[:100]}',
                            metadata={
                                'execution_time': execution_time_seconds,
                                'quality_score': quality_score,
                                'task_type': completed_task.type.value if hasattr(completed_task, 'type') else 'unknown'
                            }
                        )

                    elif completed_task.status == TaskStatus.FAILED:
                        # Remove from active but don't count as completion
                        completed_task_ids.append(task_id)
                        logger.warning(f"❌ Task failed: {completed_task.description}")

                        # Log task failure coordination
                        self.log_db.log_coordination(
                            coordinator_type='autonomous',
                            action='task_completion_verified',
                            task_id=task_id,
                            status='failed',
                            result=f'Task verified as failed: {completed_task.description[:100]}',
                            metadata={
                                'task_type': completed_task.type.value if hasattr(completed_task, 'type') else 'unknown',
                                'failure_reason': completed_task.result.get('reason') if hasattr(completed_task, 'result') and completed_task.result else 'unknown'
                            }
                        )
                        self.stats["tasks_failed"] += 1
            
            # Update statistics and remove completed tasks
            for task_id in completed_task_ids:
                if task_id in self.system_state.active_tasks:
                    self.system_state.active_tasks.remove(task_id)
                    
                    # Only count successful completions
                    task = self.completed_tasks[task_id]
                    if task.status == TaskStatus.COMPLETED:
                        self.stats["tasks_completed"] += 1

                        # Update planning engine
                        await self.planning.update_task_status(
                            task_id,
                            TaskStatus.COMPLETED,
                            task.result
                        )

                    # NOTE: the adaptive task-type reward is NOT collected here.
                    # This scanner only ever sees tasks from the legacy
                    # _execution_phase path, and no task carrying an adaptive
                    # decision reaches it -- exploration tasks are queued and run
                    # through _execute_and_validate_task, which is where the
                    # authoritative outcome is established and where the reward
                    # is now recorded.
            
            # Log summary if any tasks completed
            if completed_task_ids:
                logger.info(
                    f"Task completion cycle: {len(completed_task_ids)} tasks finished "
                    f"(successful: {self.stats['tasks_completed']}, "
                    f"failed: {self.stats['tasks_failed']})"
                )
            
        except Exception as e:
            logger.error(f"Error checking task completions: {e}")

            import traceback
            # Log error with full details
            self.log_db.log_error(
                error_type=type(e).__name__,
                error_message=str(e),
                module='autonomous_coordinator',
                function='_check_task_completions',
                stack_trace=traceback.format_exc(),
                context={'active_tasks_count': len(self.system_state.active_tasks)}
            )

    async def _analyze_for_goal_creation(self, perception_data: PerceptionData) -> Optional[str]:
        """Analyze perception data to determine if a new goal should be created"""
        try:
            # Simple heuristics for goal creation
            content = perception_data.content
            
            # Check for explicit requests
            if "request" in content or "goal" in content:
                description = content.get("text", f"Handle {perception_data.data_type} input")
                goal = await self.planning.create_goal(description, Priority.MEDIUM)
                if goal:
                    self.system_state.active_goals.append(goal.id)
                    return goal.id
            
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing for goal creation: {e}")
            return None
    
    async def _apply_learning_recommendation(self, recommendation: Dict[str, Any]) -> bool:
        """Apply a learning recommendation; report whether state actually changed.

        This returned None on every path, so the caller's `if success:` was
        never true: no recommendation was ever counted as applied and no
        competence reward was ever awarded, however well it worked.
        """
        try:
            action = recommendation.get("action", {})
            action_type = action.get("type", "unknown")
            
            logger.info(f"Applying learning recommendation: {action_type}")
            
            # Apply different types of recommendations
            if action_type == "adjust_cycle_interval":
                new_interval = action.get("value", self.coordination_cycle_interval)
                # Allow longer intervals (up to 1 hour) to support deep thinking cycles
                self.coordination_cycle_interval = max(1.0, min(3600.0, new_interval))
                return True
            
            elif action_type == "prioritize_task_type":
                task_type = action.get("task_type")
                priority_boost = action.get("priority_boost", 0.2)
                boosted = 0
                
                # Adjust task prioritization in planning engine
                # This increases priority for tasks of a specific type
                logger.info(f"Boosting priority for task type: {task_type} by {priority_boost}")
                
                # Get all active plans from planning engine
                for plan_id, plan in self.planning.active_plans.items():
                    for task in plan.tasks:
                        # Check if task matches the type to prioritize.
                        #
                        # task.type is a TaskType enum, so str() yields
                        # "TaskType.RESEARCH" -- never equal to "research".
                        # This condition could not match any task at all.
                        task_type_value = getattr(task, 'type', None)
                        task_type_value = getattr(task_type_value, 'value', task_type_value)
                        if task_type_value is not None and str(task_type_value).lower() == str(task_type).lower():
                            # Boost the task priority
                            current_priority = task.priority
                            
                            # Map priority to numeric, boost, then map back
                            priority_map = {
                                Priority.LOW: 1,
                                Priority.MEDIUM: 2,
                                Priority.HIGH: 3,
                                Priority.CRITICAL: 4
                            }
                            
                            priority_value = priority_map.get(current_priority, 2)
                            new_priority_value = min(4, priority_value + 1)  # Boost by one level
                            
                            # Reverse map back to Priority enum
                            reverse_map = {1: Priority.LOW, 2: Priority.MEDIUM, 3: Priority.HIGH, 4: Priority.CRITICAL}
                            task.priority = reverse_map.get(new_priority_value, Priority.HIGH)
                            boosted += 1


                            logger.info(
                                f"   Boosted task '{task.description[:50]}...' "
                                f"from {current_priority.name} to {task.priority.name}"
                            )
                    
                    # Update plan in database
                    await self.planning._store_plan(plan)
                
                # Also boost future goals related to this task type
                for goal_id, goal in self.planning.current_goals.items():
                    # Check if goal description relates to this task type
                    if task_type.lower() in goal.description.lower():
                        current_priority = goal.priority
                        
                        priority_map = {
                            Priority.LOW: 1,
                            Priority.MEDIUM: 2,
                            Priority.HIGH: 3,
                            Priority.CRITICAL: 4
                        }
                        
                        priority_value = priority_map.get(current_priority, 2)
                        new_priority_value = min(4, priority_value + 1)
                        
                        reverse_map = {1: Priority.LOW, 2: Priority.MEDIUM, 3: Priority.HIGH, 4: Priority.CRITICAL}
                        goal.priority = reverse_map.get(new_priority_value, Priority.HIGH)
                        boosted += 1
                        
                        logger.info(
                            f"   Boosted goal '{goal.description[:50]}...' "
                            f"from {current_priority.name} to {goal.priority.name}"
                        )
                        
                        # Update goal in database
                        await self.planning._store_goal(goal)
                
                logger.info(
                    f"✅ Task type '{task_type}' prioritization adjustment complete "
                    f"({boosted} item(s) boosted, requested boost {priority_boost})"
                )
                # "Applied" means state changed. Matching nothing is not a
                # successful application, and must not earn a reward.
                return boosted > 0
            
            elif action_type == "allocate_resources":
                resource_type = action.get("resource_type")
                allocation = action.get("allocation", 1.0)
                self.system_state.resources[resource_type] = allocation
                return True

            logger.warning(
                f"No applier for recommendation action '{action_type}' — ignored"
            )
            return False
            
        except Exception as e:
            logger.error(f"Error applying learning recommendation: {e}")
            return False

    async def _update_system_state(self):
        """Refresh the substrate's self-state from its real subsystems.

        This is the SOLE writer of system_state.resource_usage / timestamp /
        performance_metrics — the exact fields the constitution's law-compliance
        check reads (singleton_constitution._check_law_compliance). It was dead,
        so the constitution had only stale init values to read; scheduling this
        is what makes those reads honest.

        Each metric is sourced from the authority that OWNS it, and a source that
        cannot be read is logged and its metric LEFT ABSENT — never written as a
        fabricated value — so a missing signal is honestly missing, not a fake
        number. Sources are split into their own try/excepts so one failing
        subsystem never blanks the others."""
        self.system_state.timestamp = datetime.now().timestamp()
        metrics = self.system_state.performance_metrics

        # NOTE: resource_usage (CPU/memory) is the HEALTH monitor's real psutil
        # sample, NOT the executor's — the old code called a get_execution_status()
        # that never existed, which is part of why this method was dead. It is set
        # from real health data in _check_constitutional_alignment, which already
        # reads the health authority; duplicating a psutil sample here would stand
        # up a second resource authority.

        # error_rate — the TASK QUEUE owns task outcomes; the honest rate is
        # failed / (completed + failed). Written only once tasks have actually
        # finished, so a fresh system is never scored flawless on zero evidence.
        try:
            qm = self.task_queue.get_metrics()
            completed = int(qm.get("tasks_completed", 0))
            failed = int(qm.get("tasks_failed", 0))
            finished = completed + failed
            if finished > 0:
                metrics["error_rate"] = failed / finished
        except Exception as e:
            logger.warning("system_state: error_rate unreadable: %s", e)

        # goal_alignment — the APPRAISAL system owns goal congruence (derived from
        # task-verification goal-alignment scores). Written only when the
        # authority actually holds a value, never defaulted.
        try:
            appr = self._appraisal().current_state
            gc = getattr(appr, "goal_congruence", None) if appr else None
            if gc is not None:
                metrics["goal_alignment"] = float(gc)
        except Exception as e:
            logger.warning("system_state: goal_alignment unreadable: %s", e)

        # Perception / planning transparency signals.
        try:
            perception_stats = await self.perception.get_statistics()
            planning_status = await self.planning.get_planning_status()
            metrics.update({
                "perception_queue_length": perception_stats.get("queue_length", 0),
                "active_plans": planning_status.get("active_plans", 0),
                "pending_tasks": planning_status.get("pending_tasks", 0),
            })
        except Exception as e:
            logger.warning("system_state: perception/planning metrics unreadable: %s", e)
    
    async def shutdown(self):
        """Shutdown the autonomous system gracefully"""
        logger.info("Shutting down autonomous system...")
        
        self.active = False
        
        # Cancel coordination cycle
        if self.coordination_task:
            self.coordination_task.cancel()
            try:
                await self.coordination_task
            except asyncio.CancelledError:
                pass

        # Cancel the reactive drain worker
        if self._reactive_worker:
            self._reactive_worker.cancel()
            try:
                await self._reactive_worker
            except asyncio.CancelledError:
                pass

        # Cancel the coalescing motivation-refresh task if one is in flight
        if self._motivation_refresh_task and not self._motivation_refresh_task.done():
            self._motivation_refresh_task.cancel()
            try:
                await self._motivation_refresh_task
            except asyncio.CancelledError:
                pass

        # Cancel periodic performance assessment
            logger.info("✅ Periodic performance assessment stopped")

        # Shutdown modules
        modules = [
            ("Learning Adapter", self.learning),
            ("Intrinsic Motivation System", self.intrinsic_motivation),
            ("Planning Engine", self.planning),
            ("Perception Manager", self.perception)
        ]
        
        for name, module in modules:
            try:
                await module.shutdown()
                logger.info(f"{name} shutdown completed")
            except Exception as e:
                logger.error(f"Error shutting down {name}: {e}")
        
        logger.info("Autonomous system shutdown completed")
    
    # =========================================================================
    # ENHANCED REASONING & LEARNING - Singleton's Unified Intelligence
    # =========================================================================
    
    def get_intelligence_capabilities(self) -> Dict[str, Any]:
        """
        Get all intelligence capabilities available to the Singleton
        
        Enhanced reasoning and learning systems accessible across the entire system
        """
        return {
            "abstract_reasoning": self.abstract_reasoning,
            "quantum_reasoning": self.quantum_reasoning,
            "proof_engine": self.proof_engine,
            "neural_bridge": self.neural_bridge,
            "unified_learning": self.learning,
            "meta_learning": self.meta_learning,
            "causal_analyzer": self.causal_analyzer,
            "status": {
                "abstract_reasoning_ready": self.abstract_reasoning is not None,
                "quantum_reasoning_ready": self.quantum_reasoning is not None,
                "proof_engine_ready": self.proof_engine is not None,
                "neural_bridge_ready": self.neural_bridge is not None,
                "unified_learning_ready": getattr(self.learning, "initialized", False),
                "meta_learning_ready": self.meta_learning is not None,
                "causal_analysis_ready": self.causal_analyzer is not None,
            }
        }

# Convenience function for external use

    # ==== EXECUTION FACULTY (absorbed from GeneralPurposeExecutor: the self
    # executes its own tasks; there is no separate executor agent) ====

    async def initialize_execution_faculty(self) -> bool:
        """Bring up just the tool-execution faculty: connect the tool registry
        and the database. Substrate-only, no model handle. Called by the full
        initialize(), and usable on its own to exercise execute_task() without
        standing up the whole coordinator lifecycle.
        """
        try:
            from core.tools.tool_registry import get_tool_registry
            self.tool_registry = get_tool_registry()
            tool_count = len(self.tool_registry.tool_factories) + len(self.tool_registry.tools)
            logger.info(f"Execution faculty: {tool_count} tools available")
            import os as _exec_os
            if not _exec_os.environ.get("TORIN_SHADOW_MODE"):
                try:
                    await self.db.initialize()
                except Exception as _dbe:
                    logger.warning(f"Execution DB init (non-critical): {_dbe}")
            logger.info("✅ Execution faculty initialized")
            return True
        except Exception as _exe:
            logger.error(f"Failed to initialize execution faculty: {_exe}")
            return False

    def _ensure_dotenv_loaded(self) -> None:
        """Read TorinAI's .env files for runtime integration checks, WITHOUT
        mutating the process environment.

        This previously called load_dotenv(), which writes every key in
        .env.production into os.environ for the life of the process. Two things
        followed. An operator who unset SLACK_BOT_TOKEN to disable Slack had it
        put back by the first integration check, so the executor's answer to
        "is Slack configured" could not be influenced by the environment it was
        actually running in. And the write was global: every other component
        thereafter saw variables that were never in the environment, attributed
        to nobody.

        Same failure as the POSTGRES_* one, same remedy: read the file into a
        dict and resolve with explicit precedence, so the file informs the
        answer instead of silently becoming the environment.
        """
        if self._env_loaded:
            return
        self._env_loaded = True

        try:
            from pathlib import Path
            from dotenv import dotenv_values

            base = Path(__file__).resolve()
            # Walk up until we find TorinAI root (has core/)
            for _ in range(6):
                if (base / "core").is_dir():
                    break
                base = base.parent

            env_prod = base / ".env.production"
            env_fallback = base / ".env"
            if env_prod.exists():
                self._dotenv_values = dict(dotenv_values(env_prod))
            elif env_fallback.exists():
                self._dotenv_values = dict(dotenv_values(env_fallback))
        except Exception:
            # Dotenv is optional; if missing, runtime checks fall back to os.environ
            return

    def _config_value(self, key: str) -> Optional[str]:
        """Resolve one setting: process environment first, then the .env file.

        A variable present in the environment wins, including when a launcher
        set it deliberately. One that is absent falls back to the file. Nothing
        here writes to os.environ, so asking a question never changes the
        answer for whoever asks next.
        """
        import os
        value = os.environ.get(key)
        if value is not None:
            return value
        self._ensure_dotenv_loaded()
        return (self._dotenv_values or {}).get(key)


    def _observe_world(self, domain_id: str) -> Optional[List[str]]:
        """The world the substrate will plan against, read now from the domain.

        Returns the observed facts as strings, or None when the world cannot be
        read -- which is not the same as an empty world. Planning against a
        world that was never observed would authorise a plan on a state that
        does not exist, so an unreadable world stops the substrate path here
        rather than letting it proceed on an assumption.
        """
        from core.execution.operator_binding import get_binding_registry

        observed = get_binding_registry().observe_world(domain_id)
        if observed is None:
            return None
        return sorted(str(fact) for fact in observed)

    def _derive_goal_spec(self, task: Task) -> Optional[Dict[str, Any]]:
        """Turn a task into a state goal the planner can search, or decline.

        A state goal is (domain, goal_conditions, observed world). The goal
        conditions come from what the task declares -- its provenance for a task
        authored as a state goal, nothing read out of prose. The world is
        observed, not carried: a `world_state` recorded when the task was
        created is planning-time state, and the state that governs execution is
        the one observed now.

        Returns None, honestly, when the task carries no state goal or its world
        cannot be read. A None here is the substrate saying "not mine yet"; it
        never becomes a guessed goal.
        """
        provenance = getattr(task, "provenance", None) or {}

        # A task already carrying a grounded operator is a plan STEP, not a
        # goal to plan -- that is _execute_grounded_operator's work, not this.
        if provenance.get("grounded_operator"):
            return None

        raw_conditions = provenance.get("goal_conditions")
        domain_id = provenance.get("domain_id")
        if not raw_conditions or not domain_id:
            return None

        # The conditions must parse as facts, or they are not a state goal the
        # search can reason over. A malformed condition declines the whole task
        # rather than silently dropping the part that failed.
        from core.learning.rule_induction import Fact

        goal_conditions: List[str] = []
        for condition in raw_conditions:
            try:
                goal_conditions.append(str(Fact.parse(str(condition))))
            except ValueError as exc:
                logger.info("goal derivation declined task %s: condition %r does "
                            "not parse: %s", task.id, condition, exc)
                return None

        # ENCOUNTER-DRIVEN DOMAIN INSTALL. A task that declares a filesystem
        # workspace is the substrate WORKING in that domain for the first time;
        # install it now (idempotently, scoped to the declared directory) so the
        # world below is observable and the domain becomes explorable from here
        # on — the wire that was missing entirely in production. No workspace
        # declared ⇒ nothing installed; a domain already installed ⇒ no-op.
        workspace_root = provenance.get("workspace_root")
        if workspace_root:
            from core.execution.filesystem_domain import ensure_filesystem_domain
            ensure_filesystem_domain(domain_id, workspace_root)

        world_state = self._observe_world(domain_id)
        if world_state is None:
            logger.info("goal derivation declined task %s: the world of domain "
                        "%r could not be observed", task.id, domain_id)
            return None

        return {
            "domain_id": domain_id,
            "goal_conditions": goal_conditions,
            "world_state": world_state,
        }

    # ==================================================================
    # SUBSTRATE-FIRST DRIVE — Phase 2: plan a state goal and execute it
    #
    # Where _execute_grounded_operator runs one already-grounded operator, this
    # takes a task that names a STATE to reach, plans a sequence of learned
    # operators to reach it, and drives that sequence through the same verified
    # single-operator path. The substrate decides the steps; no model is asked
    # what to do. When the goal cannot be planned it says so -- UNREACHABLE or
    # INDETERMINATE -- and does not fall to generation.
    # ==================================================================

    async def _get_planning_engine(self):
        """The substrate's planner — `self.planning`, and only that.

        Planning a state goal is the substrate choosing a sequence of its own
        learned operators, and the planning faculty is what gives it that ability:
        there is no planning without the substrate, and no plan formed anywhere
        else. ONE engine, so the goals and plans it holds are the same ones every
        other part of the substrate sees.

        This used to build a SECOND PlanningEngine and keep it on
        `self._planning_engine`. Goals created through `self.planning` were then
        invisible to the engine that actually planned, and vice versa — two
        divergent sets of goals, plans and stats inside one self.
        """
        engine = self.planning
        if engine is None:
            logger.error("the substrate has no planning faculty; it cannot plan")
            return None
        if not getattr(engine, "active", False):
            # Normally brought up with the other core modules at startup; an
            # entry point that reached planning first initializes the same one.
            if not await engine.initialize():
                logger.error("planning engine failed to initialize; the "
                             "substrate cannot plan state goals")
                return None
        return engine

    async def _reconcile_plan_intent(self, plan: Any, domain_id: str, *,
                                     goal_conditions: Any,
                                     detail: str = "",
                                     alternative: Optional[Dict[str, Any]] = None
                                     ) -> Optional[Dict[str, Any]]:
        """Attach what ACTUALLY happened to the intent this plan was the route of.

        This is the other half of intent. The substrate recorded what it MEANT
        when the planner proved a route; this records what came of it, so it can
        later ask whether it did what it meant rather than only whether a tool
        returned success.

        THE WORLD DECIDES, and it decides HERE. Whether the intent was realized is
        computed by re-observing and asking whether its conditions hold — never
        taken from a step's own report. Both directions of that matter:

          * a plan that ran cleanly while the world did not reach the goal
            reconciles as MISSED, which is the case worth learning from;
          * a step that reported failure while the world DID reach the goal
            reconciles as realized. A move that copied the file but could not
            unlink the source fails as a step, yet the file is where the intent
            wanted it. Trusting the step's verdict recorded "matched_aim: false"
            beside a met condition — an intent at odds with itself.
        """
        intent_id = ((getattr(plan, "metadata", None) or {})
                     .get("intent") or {}).get("intent_id")
        if not intent_id:
            return None
        return await self._reconcile_intent(
            intent_id, domain_id, goal_conditions=goal_conditions,
            detail=detail, alternative=alternative)

    async def _reconcile_intent(self, intent_id: str, domain_id: str, *,
                                goal_conditions: Any = None,
                                detail: str = "",
                                alternative: Optional[Dict[str, Any]] = None
                                ) -> Optional[Dict[str, Any]]:
        """Reconcile ONE intent with what the world actually did — the stage.

        A PIPELINE STAGE, NOT A PLANNING STEP. This used to exist only as
        `_reconcile_plan_intent`, reading the intent id out of a plan's metadata,
        and the signature was the whole problem: a plan is something only ONE of
        the executor's three methods produces. So the single-operator path — which
        already re-observes the world and carries a runtime outcome — had no way
        to call it, and the tool path had none either. The result was that
        "did I do what I meant" could only be answered for planned sequences, and
        every other act left its intent in `forming` forever.

        Keyed on what all three methods actually have — an intent id, the
        conditions it meant to bring about, and the domain to look at — so
        reconciliation is available to whatever ran.

        `goal_conditions` may be omitted, and then THE INTENT IS ASKED WHAT IT
        MEANT. A planned sequence holds its goal conditions in the plan, but a
        single grounded operator has no plan to carry them — and the intent
        recorded them when reasoning proved the route, so the authority on what
        was meant is the intent itself rather than whatever the caller has to
        hand. An intent that states no conditions cannot be reconciled against
        the world, and that is reported as no reconciliation rather than as a
        vacuous success.
        """
        if goal_conditions is None:
            try:
                from core.reasoning.intent_authority import get_intent_authority
                held = await get_intent_authority().get_by_id(str(intent_id))
                goal_conditions = held.goal_conditions if held is not None else None
            except Exception as e:
                logger.error("intent %s could not be read to reconcile it: %s",
                             intent_id, e)
                return None
        conditions = [str(c) for c in (goal_conditions or [])]
        if not conditions:
            # NO CONDITIONS, NO VERDICT. `reached` below would be False for an
            # empty list, which would reconcile every condition-less intent as
            # "missed" — a fabricated failure. The honest answer is that this
            # intent named nothing the world could be checked against.
            logger.debug("intent %s states no goal conditions; not reconciled",
                         intent_id)
            return None
        observed = set(self._observe_world(domain_id) or [])
        reached = bool(conditions) and all(c in observed for c in conditions)
        reconciled = {
            "intent_id": intent_id,
            "outcome_class": "success" if reached else "missed",
            "matched_aim": bool(reached),
            "goal_conditions": conditions,
            "goal_conditions_met": sorted(c for c in conditions if c in observed),
            "detail": detail,
        }
        # What the laws offered instead, when they offered anything. A pursuit that
        # was redirected did not simply fail: there is a permitted form of it, and
        # recording that on the intent is what lets a later plan take it.
        if alternative:
            reconciled["alternative"] = alternative
        try:
            from core.reasoning.intent_authority import get_intent_authority
            await get_intent_authority().reconcile(
                intent_id, reconciled,
                status="fulfilled" if reached else "abandoned")
        except Exception as e:
            # Never fails the act it is describing, but never silent either: an
            # unreconciled intent is a pursuit the substrate cannot learn from.
            logger.error("intent %s was not reconciled with what happened: %s",
                         intent_id, e)
            return None
        return reconciled

    async def _drive_substrate_goal(self, task: Task) -> Optional[Dict[str, Any]]:
        """Plan a state goal over learned operators and execute it, model-free.

        Returns None to decline -- the task names no state goal, or the planner
        is unavailable -- leaving what comes next to the caller. Otherwise the
        substrate owns the goal and the result says what happened: it reached
        the goal, proved it unreachable, or stopped at the step that diverged.

        The world is re-observed for authorization by each step (inside
        _execute_grounded_operator) and once more at the end to decide success.
        A plan that ran cleanly while the world did not reach the goal is not a
        success -- the world decides, not the plan's account of itself.
        """
        spec = self._derive_goal_spec(task)
        if spec is None:
            return None

        engine = await self._get_planning_engine()
        if engine is None:
            return None

        from core.reasoning.temporal_reasoning import PlanningStatus

        domain_id = spec["domain_id"]
        goal = await engine.create_goal(
            f"[substrate goal] {task.description}"[:200], task.priority,
            state_conditions=spec["goal_conditions"])
        if goal is None:
            return None

        outcome = await engine.plan_for_goal(
            goal.id, {"world_state": spec["world_state"], "domain_id": domain_id})

        if outcome.status is not PlanningStatus.PLAN_FOUND:
            # Honest inability. UNREACHABLE is a proof about the world;
            # INDETERMINATE is Torin not (yet) knowing enough of its own
            # repertoire. Neither is a reason to ask a model to guess -- but the
            # substrate can go further than "I cannot": the domain authority
            # diagnoses WHAT kind of knowledge is missing (operator, concept,
            # causal link, binding, prerequisite, observation, or none learnable).
            # The diagnosis is a MEASUREMENT, not a decision: it feeds the
            # AppraisalSystem, which owns the disposition (explore / replan /
            # disengage). Until now a planning failure fed appraisal nothing, so
            # the substrate's own inability never reached its disposition.
            from core.integration.universal_domain_master import get_universal_domain_master

            deficit = await get_universal_domain_master().diagnose_deficit(
                domain_id, spec["goal_conditions"], spec["world_state"], outcome)
            try:
                self.appraisal.update(
                    outcome_quality=0.0,
                    self_initiated=(
                        getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'),
                    **deficit.appraisal_signals(),
                )
            except Exception as e:
                # Disposition is not allowed to decide whether the planning
                # result is returned; the deficit is already diagnosed.
                logger.warning("substrate planning-failure appraisal update failed: %s", e)
            return {
                'success': False,
                'task_id': task.id,
                'execution_path': 'substrate_plan',
                'model_free': True,
                'domain_id': domain_id,
                'goal_conditions': spec["goal_conditions"],
                'planning_status': outcome.status.value,
                'operators_considered': outcome.operators_considered,
                'grounding_complete': outcome.grounding_complete,
                'error': f"substrate could not plan the goal: {outcome.reason}",
                'reason': outcome.reason,
                'deficit': deficit.to_dict(),
            }

        # The proved chain, run in dependency order. Each step goes through the
        # same verified path a single operator takes; the plan's provenance
        # already carries what that path needs.
        step_results: List[Optional[Dict[str, Any]]] = []
        for step in outcome.plan.tasks:
            # A READING the law requires before the route may run. Not part of
            # the proved route — it has no rule behind it, so it must not go to
            # the operator path, which would rightly refuse it for that.
            _read_path = (getattr(step, "provenance", None) or {}).get("read_path")
            if _read_path:
                reading = await self._perform_reading_step(step, _read_path)
                step_results.append(reading)
                if not reading.get("success"):
                    stopped = await self._reconcile_plan_intent(
                        outcome.plan, domain_id,
                        goal_conditions=spec["goal_conditions"],
                        detail=f"could not read {_read_path} first")
                    return {
                        'success': False, 'task_id': task.id,
                        'execution_path': 'substrate_plan', 'model_free': True,
                        'domain_id': domain_id,
                        'goal_conditions': spec["goal_conditions"],
                        'stopped_at': step.description,
                        'error': (f"the law requires reading {_read_path} before "
                                  f"this route, and it could not be read: "
                                  f"{reading.get('error')}"),
                        'intent_outcome': stopped,
                        'steps': step_results,
                    }
                continue
            result = await self._execute_grounded_operator(step)
            step_results.append(result)
            if result is None:
                stopped = await self._reconcile_plan_intent(
                    outcome.plan, domain_id,
                    goal_conditions=spec["goal_conditions"],
                    detail="a step did not present as a grounded operator")
                return {
                    'success': False, 'task_id': task.id,
                    'execution_path': 'substrate_plan', 'model_free': True,
                    'domain_id': domain_id,
                    'error': "a plan step did not present as a grounded operator",
                    'intent_outcome': stopped,
                    'steps': step_results,
                }
            if not result.get('success'):
                # A step refused (authority not established now) or the world
                # did not move as the rule predicted. The drive stops at the
                # step that diverged, not somewhere downstream of it.
                # A pursuit that stopped is still something to learn from, so the
                # intent is reconciled as MISSED rather than left open.
                stopped = await self._reconcile_plan_intent(
                    outcome.plan, domain_id,
                    goal_conditions=spec["goal_conditions"],
                    detail=f"stopped at {step.description}",
                    alternative=result.get("alternative"))
                return {
                    'success': False, 'task_id': task.id,
                    'execution_path': 'substrate_plan', 'model_free': True,
                    'domain_id': domain_id,
                    'goal_conditions': spec["goal_conditions"],
                    'stopped_at': step.description,
                    'intent_outcome': stopped,
                    'error': f"step {step.description} did not confirm: "
                             f"{result.get('refused') or result.get('runtime_outcome')}",
                    'steps': step_results,
                }

        # Every step confirmed. Success is the RE-OBSERVED world holding the
        # goal, not the fact that the steps ran. Re-observing the goal-state IS
        # the verification — stronger and model-free — so the verdict is stated
        # here rather than left for a generator-policing protocol to guess.
        final_world = set(self._observe_world(domain_id) or [])
        reached = all(cond in final_world for cond in spec["goal_conditions"])
        # MEANT vs HAPPENED, recorded on the intent this plan was the route of.
        reconciled = await self._reconcile_plan_intent(
            outcome.plan, domain_id,
            goal_conditions=spec["goal_conditions"],
            detail=f"{len(step_results)} step(s) ran")
        # THE LOOP CLOSES HERE. Integrity's action↔outcome link is the substrate
        # asking "did acting realize what I meant" — now read from the reconciled
        # intent rather than inferred from a success label. Disposition never
        # decides whether the result is returned, so this cannot fail the act.
        if reconciled:
            try:
                self.appraisal.update(
                    outcome_quality=1.0 if reconciled["matched_aim"] else 0.0,
                    self_initiated=(getattr(getattr(task, 'source', None),
                                            'value', None) == 'autonomous'),
                    intent_outcome=reconciled)
            except Exception as e:
                logger.debug("disposition not updated from the reconciled "
                             "intent: %s", e)
        return {
            'success': reached,
            'verification_state': 'verified' if reached else 'failed',
            'completion_score': 1.0 if reached else 0.0,
            'task_id': task.id,
            'execution_path': 'substrate_plan',
            'model_free': True,
            'domain_id': domain_id,
            'goal_conditions': spec["goal_conditions"],
            'steps_executed': len(step_results),
            'goal_reached': reached,
            # MEANT vs HAPPENED travels with the result. Downstream credit reads
            # the verdict the world gave, rather than re-deriving it from a
            # success flag that has already lost the distinction.
            'intent_outcome': reconciled,
            'steps': step_results,
        }

    async def _perform_reading_step(self, task: Task,
                                    path: str) -> Dict[str, Any]:
        """Read a file the route is about to act on, because the law requires it.

        A real read through the real tool, so it passes the same gate as any
        other act (investigate class, so the laws allow it) and the reading is
        recorded by the constitution at the single point every act passes —
        which is what makes the act that follows legal.

        It does NOT write the ledger itself. A step that recorded its own reading
        would be asserting that it read something rather than having read it, and
        the whole point of the ledger is that it holds what was actually read.
        """
        from core.tools import get_tool_registry

        provenance = getattr(task, "provenance", None) or {}
        # THE ROUTE'S INTENT IS NOT BOUND HERE, deliberately. Law 4 asks whether
        # the act about to run IS the act reasoning proved, and this one is not —
        # it is what the law requires BEFORE that act. Naming the route's intent
        # would claim otherwise, and Law 4 would rightly replan the reading for
        # not being `move_file`. A reading needs no intent of its own: it is an
        # investigate-class act, which Law 2 exempts because reading is how an
        # account is established in the first place.
        result = await get_tool_registry().execute_tool(
            "read_file", {"file_path": path})

        succeeded = bool(getattr(result, "success", False))
        still_unread = self.constitution.reading.must_reread(path)
        if succeeded and still_unread:
            # The tool reported success and the ledger still says otherwise. The
            # ledger is what Law 2 consults, so its answer is the one that counts.
            succeeded = False
        logger.info("substrate read %s before acting: %s", path,
                    "recorded" if succeeded else "NOT recorded")
        return {
            'success': succeeded,
            'task_id': task.id,
            'execution_path': 'substrate_reading',
            'model_free': True,
            'read_path': path,
            'reading_for': provenance.get("reading_for"),
            'error': None if succeeded else (
                getattr(result, "error", None)
                or f"{path} was read but no account of it was recorded"),
        }

    @profile_performance("autonomous_coordinator", "execute_task")
    async def _execute_grounded_operator(self, task: Task) -> Optional[Dict[str, Any]]:
        """Run one grounded operator, and close its pursuit even when it is refused.

        The act itself is `_act_on_grounded_operator`. A REFUSAL returns from it
        early, at whichever authority check failed, and each of those returns
        used to leave a standalone operator's intent in `forming` forever: the
        pursuit was concluded (the substrate will not do it) and nothing said so.
        The planning path already reconciles a stopped route as missed; this is
        the same rule for the one-operator owner.

        Same ownership guard as the act: a step of a plan (`plan_id` present)
        does not own the plan's intent — the plan closes its own route.
        """
        result = await self._act_on_grounded_operator(task)
        if not isinstance(result, dict) or "refused" not in result:
            return result
        provenance = getattr(task, "provenance", None) or {}
        intent_id = provenance.get("intent_id")
        if intent_id and not provenance.get("plan_id"):
            result["intent_outcome"] = await self._reconcile_intent(
                str(intent_id), provenance.get("domain_id") or "",
                detail=f"{result.get('operator')}: refused — {result['refused']}",
                alternative=result.get("alternative"))
        return result

    async def _act_on_grounded_operator(self, task: Task) -> Optional[Dict[str, Any]]:
        """Execute deterministically when the substrate holds the authority to.

        Returns None to fall through to model-backed execution. Every authority
        condition is re-established HERE against current state, not inherited
        from the plan, because planning-time authorization goes stale:

            t0  rule VALIDATED, plan generated
            t1  rule REFUTED by new evidence
            t2  task executes

        "The plan already authorized it" is not an argument at t2. The same
        applies to the world: the planner proved applicability in a simulated
        state, and the state governing execution is the observed one.
        """
        provenance = getattr(task, "provenance", None) or {}
        rule_id = provenance.get("learned_rule_id")
        operator_name = provenance.get("grounded_operator")
        if not rule_id or not operator_name:
            return None

        from core.execution.effect_verification import (
            AttributionContext, RuntimeOutcome, ToolObservation, attribute, verify_effects)
        from core.execution.operator_binding import get_binding_registry
        from core.learning.rule_induction import (Fact, RuleEffects, is_variable,
                                                  resolve_outputs)
        from core.reasoning.unification import match_literal
        from core.learning.rule_store import (
            get_rule_store, record_runtime_evidence)

        def refuse(reason: str) -> Dict[str, Any]:
            """A task built on a learned rule fails closed; it never falls
            through to the model.

            Past this point the task IS a grounded operator -- its description
            is `MOVE(z,HALL,LAB)`, authorised by rule R. If the substrate
            cannot establish that authority now, handing the step to a model to
            interpret would substitute generation for the proof the plan was
            built on, and the plan would appear to proceed on authority that
            had already been withdrawn.
            """
            logger.info("substrate path refused task %s: %s", task.id, reason)
            return {
                'success': False,
                'task_id': task.id,
                'execution_path': 'substrate',
                'model_free': True,
                'learned_rule_id': rule_id,
                'operator': operator_name,
                'refused': reason,
                'error': f"substrate authority not established: {reason}",
            }

        domain = provenance.get("domain_id")
        stored = next((r for r in await get_rule_store().load(domain_id=domain)
                       if r.rule_id == rule_id), None)
        if stored is None:
            return refuse(f"rule {rule_id} is no longer in the store")
        if not stored.is_executable:
            return refuse(f"rule {rule_id} is {stored.status.value}, not validated")

        rule = stored.rule
        if rule.action is None:
            return refuse("rule records no action")

        try:
            action = Fact.parse(operator_name)
        except ValueError as e:
            return refuse(f"operator {operator_name!r} does not parse: {e}")
        if action.signature != rule.action.signature:
            return refuse(f"{action.predicate}/{action.arity} does not match the rule's action")

        bindings: Dict[str, str] = {}
        for slot, value in zip(rule.action.args, action.args):
            if is_variable(slot):
                if bindings.setdefault(slot, value) != value:
                    return refuse(f"{operator_name} is not an instance of {rule.action}")
            elif slot != value:
                return refuse(f"{operator_name} is not an instance of {rule.action}")

        binding = get_binding_registry().get(domain or "", action.predicate)
        if binding is None:
            return refuse(f"no tool bound to {action.predicate} in domain {domain!r}")

        before = binding.observe()
        if before is None:
            return refuse("the world could not be read before acting")

        # THE OBSERVED WORLD DECIDES THE BINDING, NOT THE PLAN.
        #
        # Substituting only what the operator's NAME carries leaves every other
        # precondition variable free, and a fact with a variable in it is in no
        # world -- so a rule whose preconditions bind anything the action does
        # not name refused every time, reported as "preconditions absent". The
        # plan does record its own bindings, and trusting them would be
        # inheriting planning-time state, which this method exists not to do.
        #
        # So the preconditions are matched against the world as it is now.
        # Nothing is loosened: a precondition that does not hold still refuses,
        # and it now refuses with the literal that failed.
        candidates = [bindings]
        for literal in sorted(rule.preconditions, key=str):
            candidates = [extended for candidate in candidates
                          for extended in match_literal(literal, before, candidate)]
            if not candidates:
                return refuse(
                    f"precondition {literal.substitute(bindings)} does not hold in "
                    f"the observed world")
        if len(candidates) > 1:
            return refuse(
                f"{operator_name} matches the observed world in {len(candidates)} "
                f"ways; which instance to act on is not determined")
        bindings = candidates[0]

        # A value the action computes is computed now, from what the world was
        # just observed to hold.
        resolved = resolve_outputs(rule, bindings)
        if resolved is None:
            return refuse(
                "a value this action produces has no result on the observed terms")
        bindings = resolved

        # Authorized. Safety and governance are enforced inside execute_tool,
        # which is the single evaluation point for every tool call.
        from core.tools import get_tool_registry

        # TOOL SCOPING (operator path). An agent may drive only the tools
        # the substrate granted it, even through a validated learned operator.
        # None = the substrate's own work (unrestricted).
        _allowed = getattr(task, "allowed_tools", None)
        if _allowed is not None and binding.tool_name not in _allowed:
            return refuse(
                f"tool {binding.tool_name!r} was not granted to this agent")

        observation_id = f"obs_{uuid.uuid4().hex[:12]}"
        # The world is read before and after under a concurrency guard: if
        # another substrate execution in this domain overlapped the act, a
        # mismatch is not this rule's to answer for. The guard serializes
        # nothing -- the act still runs concurrently; it only remembers the
        # overlap so attribution can be honest about it.
        # NAME THE INTENT THIS ACT BELONGS TO, so the constitution can read it at
        # the gate. Only the ID travels, bound to this async context; the
        # constitution fetches the record from the intent authority. An id naming
        # nothing is judged as no intent at all, which is what an unrecorded
        # claim is worth — so this cannot be used to assert authority, only to
        # point at an account that already exists.
        #
        # The plan put it here: `state_plan_to_tasks` stamps `intent_id` into each
        # step's provenance, so the step carries which pursuit it is a step of.
        from core.reasoning.intent_authority import (
            set_acting_intent, reset_acting_intent,
            set_acting_actor, reset_acting_actor)
        from core.execution.effect_verification import concurrent_execution_guard
        _intent_token = set_acting_intent(provenance.get("intent_id"))
        # WHOSE WORK THIS IS, bound beside the intent. `actor_for` decided it when
        # the task was made; this reads that decision rather than making a second.
        _actor_token = set_acting_actor(getattr(task, "actor", None))
        try:
            with concurrent_execution_guard(domain) as _overlapped:
                result = await get_tool_registry().execute_tool(
                    binding.tool_name, binding.parameters(action.args))
                after = binding.observe()
                interfered = _overlapped()
        finally:
            reset_acting_intent(_intent_token)
            reset_acting_actor(_actor_token)

        # A CONSTITUTIONAL REFUSAL IS NOT EVIDENCE ABOUT THE RULE.
        #
        # The act did not happen, so the world did not move — and everything
        # below reads a world that did not move as the rule's predicted effects
        # being CONTRADICTED. That is a false negative about knowledge, produced
        # by the substrate's own law.
        #
        # It is not hypothetical. Wiring the constitution to `execute_tool` and
        # then driving a real goal refuted `rule_399de8f89089` — a validated
        # MOVE_FILE operator four experiments plan over — in one call:
        #
        #     validated→refuted (runtime_contradiction): contradicted:
        #     add FILE_IN(report, archive), delete FILE_IN(report, inbox)
        #
        # because Law 2 had replanned the move (the file had never been read).
        # The substrate punished its own knowledge for its own refusal.
        #
        # So a refusal returns through the same door as every other authority
        # failure in this method: nothing observed, nothing recorded, no
        # demonstration filed, and the operating credit denies it as an act that
        # never operated. The rule is untouched, which is the truth — the
        # constitution said "not this act", not "this operator is wrong".
        _judgment = (getattr(result, "metadata", None) or {}).get("judgment")
        if (getattr(result, "metadata", None) or {}).get(
                "error_type") == "CONSTITUTION_REFUSED":
            refusal = refuse(
                f"the constitution {(_judgment or {}).get('verdict', 'refused')} "
                f"this act under Law {(_judgment or {}).get('law_number', '?')}: "
                f"{(_judgment or {}).get('reason', result.error)}")
            # A REDIRECT NAMES THE PERMITTED FORM OF THE SAME ACT, and that is the
            # whole difference between it and a block. At a gate there is nobody
            # left to take the alternative — the act is stopped either way — so the
            # named form travels back with the refusal, to the one thing that can
            # still use it: planning. A redirect whose alternative reaches nobody
            # is a block wearing a kinder word.
            refusal["judgment"] = _judgment
            refusal["alternative"] = (_judgment or {}).get("alternative")
            return refusal

        observation = ToolObservation(
            observation_id=observation_id,
            tool_name=binding.tool_name,
            invoked=True,
            tool_reported_success=bool(getattr(result, "success", False)),
            observed=after is not None,
            facts=after if after is not None else frozenset(),
            before=before,
            error=getattr(result, "error", None),
            raw={"output": getattr(result, "output", None)},
        )
        # An effect still carrying a variable is one the rule declared it could
        # not predict. It is still checked -- against what the action CHANGED,
        # which is what `ToolObservation.before` is for.
        evidence = verify_effects(rule.effects.substitute(bindings), observation,
                                  rule_id=rule_id, operator=operator_name)

        # Attribution is built from what THIS method independently established
        # on the way to authorizing the call. Each flag was a gate above; none
        # is asserted on trust.
        #
        # `external_interference` means KNOWN interference. The executor still
        # cannot prove a quiet world in general, but it CAN know when another
        # substrate execution in the same domain overlapped this act -- and then
        # a mismatch is not attributable to this rule. Defaulting to False when
        # no overlap was seen keeps single-task and cross-domain learning intact;
        # the guard raises it only for a real, observed concurrent overlap, so a
        # correct rule is never revised because another task happened to run.
        attribution, why = attribute(evidence, AttributionContext(
            preconditions_observed=True,      # checked against `before`
            rule_validated_at_execution=True,  # status re-read above
            action_matches_rule=True,          # signature + instance check
            arguments_verified=True,           # built from the parsed operator
            invocation_occurred=True,
            observer_available=after is not None,
            post_state_observed=after is not None,
            external_interference=interfered,
        ))
        revised_status = await record_runtime_evidence(
            get_rule_store(), evidence, attribution, why,
            task_id=task.id,
            plan_id=provenance.get("plan_id"),
            goal_id=provenance.get("goal_id"),
        )

        logger.info("substrate execution %s: %s (%s) — %s",
                    operator_name, evidence.outcome.value, attribution.value,
                    evidence.detail)

        # ── THE LOOP CLOSES HERE TOO ─────────────────────────────────────────
        #
        # This path already re-observed the world (that is what `evidence` IS)
        # and then never paired the result back to the intent it was serving.
        # Reconciliation lived only as `_reconcile_plan_intent`, keyed on a plan
        # object that only the PLANNING path produces — so "did I do what I
        # meant" was answerable for planned sequences and unanswerable for every
        # single-operator act. Measured consequence before this: 73 of 94 intents
        # never left `forming`, because the path that executed them could not
        # conclude them.
        #
        # Reconciled BEFORE appraisal, so integrity's action↔outcome link is read
        # from what the world did rather than inferred from the attribution
        # label — the same ordering the planning path uses.
        # WHOEVER OWNS THE PURSUIT CLOSES IT — and a step does not own the plan.
        #
        # `state_plan_to_tasks` stamps the PLAN's intent_id onto every step task,
        # so a step of a multi-step route carries the whole route's intent. If
        # this reconciled unconditionally, a three-step plan would conclude its
        # intent on step one, against a world that has only had the first
        # operator applied to it — recording "missed" for a route still being
        # walked. The plan path reconciles once, at the end, and that is correct.
        #
        # `plan_id` is present exactly when this act is a step of a plan. Absent,
        # this grounded operator IS the whole pursuit and closing it here is what
        # was missing.
        reconciled = None
        _intent_id = provenance.get("intent_id")
        if _intent_id and not provenance.get("plan_id"):
            reconciled = await self._reconcile_intent(
                str(_intent_id), domain or "",
                detail=f"{operator_name}: {evidence.detail}")
        await self._appraise_substrate_execution(task, evidence, attribution, observation,
                                                 intent_outcome=reconciled)
        await self._record_execution_demonstration(
            domain=domain, action=action, before=before, after=after,
            observation_id=observation_id, evidence=evidence)

        # Surface the substrate's OWN verdict so the coordinator trusts a
        # world-confirmed success instead of discounting it as unverified. This
        # is not self-attestation: `success` here is verify_effects against the
        # re-observed before/after world. A CONTRADICTION is an honest failure
        # (the rule was refuted); an INDETERMINATE outcome stays unverified —
        # "could not tell" must not be recorded as "failed".
        if evidence.outcome is RuntimeOutcome.CONFIRMATION:
            _verification_state, _completion_score = 'verified', 1.0
        elif evidence.outcome is RuntimeOutcome.CONTRADICTION:
            _verification_state, _completion_score = 'failed', 0.0
        else:
            _verification_state, _completion_score = None, None
        return {
            # Success means the world changed as the rule predicted. A tool that
            # returned cleanly while the world did not move is the case where
            # the action model is wrong and the substrate must find out.
            'success': evidence.outcome is RuntimeOutcome.CONFIRMATION,
            'verification_state': _verification_state,
            'completion_score': _completion_score,
            'task_id': task.id,
            'execution_path': 'substrate',
            'model_free': True,
            'learned_rule_id': rule_id,
            'operator': operator_name,
            'runtime_outcome': evidence.outcome.value,
            'attribution': attribution.value,
            'rule_status_after': revised_status.value if revised_status else None,
            'observation_id': observation_id,
            # MEANT vs HAPPENED travels with the result, as on the plan and
            # operation paths. None when this act is a step (its plan closes it)
            # or carries no intent.
            'intent_outcome': reconciled,
            'effects': [
                {'effect': str(v.predicted_effect), 'polarity': v.polarity.value,
                 'verdict': v.verdict.value, 'detail': v.detail}
                for v in evidence.verifications
            ],
            'detail': evidence.detail,
        }

    async def _record_execution_demonstration(
        self, *, domain, action, before, after, observation_id, evidence,
    ) -> None:
        """File one executed action as a demonstration the learner can use.

        THIS IS THE ONLY PLACE THE SUBSTRATE OBSERVES ITS OWN STATE TRANSITIONS.
        `before`, the action invoked and `after` are all read from the world a
        few lines above, so this is the one point in real work that produces the
        before/action/after triple induction needs. Until it was wired, the
        learner could only generalize from demonstrations a TEACHER supplied,
        and every concept a projected rule contributed was confined to a taught
        domain -- which is why cross-domain transfer had exactly one source
        domain to draw on.

        `training_example_from_runtime` was built for this and had no callers.

        NOT recorded when the world could not be read afterwards, and NOT
        recorded for an INDETERMINATE outcome. A demonstration carries a
        verdict, and an unlabelled one defaults to positive -- which would file
        "we could not tell" as "the action worked".
        """
        from core.execution.effect_verification import RuntimeOutcome

        if after is None:
            logger.info(
                "%s: world unreadable after acting; no demonstration recorded "
                "(an unobserved after-state is not an empty one)", observation_id)
            return
        if evidence.outcome is RuntimeOutcome.INDETERMINATE:
            logger.info(
                "%s: outcome indeterminate; no demonstration recorded — an "
                "unlabelled example would be induced from as a positive",
                observation_id)
            return
        if not domain:
            logger.warning(
                "%s: no domain on the executed rule; a concept must belong "
                "somewhere and inventing a domain here is how one topic "
                "acquired 21", observation_id)
            return

        from core.domain.concept_ingestion import EvidenceSourceType
        from core.domain.evidence_producers import submit_demonstration
        from core.learning.rule_store import training_example_from_runtime

        example = training_example_from_runtime(
            before=before, action=action, after=after,
            evidence_id=observation_id,
            positive=evidence.outcome is RuntimeOutcome.CONFIRMATION)

        # THE OPERATOR-LEARNING PATHWAY. Independent of concept ingestion below:
        # this keeps the executed transition so the substrate's plannable
        # repertoire can grow from its own experience. It only RECORDS here --
        # induction is a hypothesis search whose cost grows with the richness of
        # the observed state, far too expensive to run inline, so the
        # always-online learner re-induces off the hot path. The concept path
        # records the transition's structure for cross-domain matching; this
        # records the operator's own evidence. One failing must not lose the
        # other, so they are separate blocks.
        try:
            from core.learning.unified_learning_system import get_learning_authority
            recorded = await get_learning_authority().record_demonstration(
                example, domain_id=domain)
            logger.info(
                "%s: demonstration %s for operator learning (%s)",
                observation_id, "kept" if recorded else "already held",
                "positive" if example.positive else "negative")
        except Exception as e:
            from core.capability import raise_if_structural
            raise_if_structural(e, "general_purpose_executor.record_demonstration")
            logger.error(
                "%s executed but its demonstration could not be kept: %s: %s",
                observation_id, type(e).__name__, e)

        try:
            result = await submit_demonstration(
                example, domain_id=domain,
                source_type=EvidenceSourceType.TASK_ARTIFACT,
                producer="substrate_execution",
                source_id=f"{domain}:{action.predicate}")
        except Exception as e:
            # Loud, never swallowed: the tool ran and the world moved, so
            # failing the execution over a projection defect would lose the
            # real result. A silent pass would make a broken projection
            # indistinguishable from an action with nothing to project.
            logger.error(
                "%s executed but its demonstration could not be recorded: %s: %s",
                observation_id, type(e).__name__, e)
            return

        if not result.read_successfully:
            logger.error(
                "%s: demonstration recorded but unreadable as structure: %s",
                observation_id, result.extraction_failures)
            return
        logger.info(
            "%s: demonstration recorded (%s) -> %d concept(s) accepted",
            observation_id,
            "positive" if example.positive else "negative", result.accepted)

    def _record_calibration_outcome(self, task: "Task", result: Any,
                                    confidence: float) -> None:
        """WAS THAT CONFIDENCE EARNED? — the pair that makes calibration real.

        The convergence gate could always compute whether stated uncertainty
        tracks actual correctness. It had NO CALLER: `record_convergence_outcome`
        was never invoked from anywhere, so `_calibration_data` stayed empty
        forever and the check returned `insufficient_data` for the life of the
        system. A complete computation with no input.

        This is the pair, and both halves already exist at this point:

          uncertainty  1 − the completion belief's posterior. What the substrate
                       STATED about its own confidence, before knowing whether it
                       was right.
          success      whether the WORLD agreed — `matched_aim` from the
                       reconciled intent, computed by re-observing and asking
                       whether the conditions the intent named now hold.

        THE TWO HALVES MUST NOT SHARE A SOURCE. Pairing the posterior with
        `is_complete` would be circular — `is_complete` IS the posterior crossing
        a threshold, so it would score the substrate as perfectly calibrated by
        construction, which is worse than not measuring. The world's verdict is
        the only honest second half, so an act that produced no reconciled intent
        contributes NO PAIR rather than a guessed one.
        """
        if not isinstance(result, dict):
            return
        outcome = result.get("intent_outcome")
        if not isinstance(outcome, dict) or "matched_aim" not in outcome:
            # No independent verdict — record nothing. A calibration sample whose
            # "truth" came from the same belief being graded is not a sample.
            return
        try:
            uncertainty = max(0.0, min(1.0, 1.0 - float(confidence)))
            from core.execution.convergence_gate import get_convergence_gate
            get_convergence_gate().record_convergence_outcome(
                uncertainty, bool(outcome["matched_aim"]))
        except Exception as e:
            # Never fails the task it is describing; never silent either.
            logger.debug("calibration pair not recorded for %s: %s", task.id, e)

    async def _appraise_substrate_execution(
        self, task: "Task", evidence, attribution, observation,
        intent_outcome: Optional[Dict[str, Any]] = None
    ) -> None:
        """Report a substrate execution to appraisal, in measured signals only.

        This is the learned-rule counterpart to `_appraise_tool_outcome`: both
        feed the one whole-self appraisal authority so acting — proved or raw —
        moves disposition, including when the proof turns out wrong. That is the
        one outcome disposition most needs.

        Two signals that look like one are kept apart deliberately:

            action_success_rate   did the action execute?     (the tool ran)
            outcome_quality       was the prediction right?   (the world moved)

        A refuted rule is the case where the first is 1.0 and the second is 0.0
        -- the tool worked perfectly and the model was wrong. Collapsing them
        would read as "we cannot affect the world", which is escalation, when
        the truth is "we still have control and this route is wrong", which is
        replanning.

        Signals with no measurement here are omitted rather than defaulted, so
        nothing invented reaches the appraisal.
        """
        from core.execution.effect_verification import RuntimeOutcome, outcome_class_for

        if evidence.outcome is RuntimeOutcome.CONFIRMATION:
            quality = 1.0
        elif evidence.outcome is RuntimeOutcome.CONTRADICTION:
            quality = 0.0
        else:
            quality = None   # nothing was established; do not score it

        try:
            self.appraisal.update(
                outcome_quality=quality,
                outcome_class=outcome_class_for(evidence, attribution),
                action_success_rate=(
                    1.0 if observation.tool_reported_success else 0.0),
                # The substrate authorises exactly one operator per step, so
                # there was no choice among options. Reporting otherwise would
                # inflate agency, which feeds replan pressure directly.
                options_considered=1,
                self_initiated=(
                    getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'),
                # MEANT vs HAPPENED, when the intent was reconciled. Integrity's
                # action↔outcome link is then read from the RE-OBSERVED world —
                # "did acting realize what I meant" — instead of being inferred
                # from the attribution label. None leaves that link UNMEASURED,
                # which is the honest reading when no intent was named; a zero
                # would dent integrity for an act that had no aim to miss.
                intent_outcome=intent_outcome,
            )
        except Exception as e:
            # Disposition is not allowed to decide whether the execution result
            # is returned. The evidence is already durable at this point.
            logger.warning("substrate appraisal update failed: %s", e)

    async def _run_tool(self, tool_name: str, params: Dict[str, Any], task: Task) -> Optional[Dict[str, Any]]:
        """Execute one named tool and return a substrate result, or None.

        Every outcome is felt: the tool path reports to the SAME whole-self
        appraisal the learned-rule path uses, so a failing tool raises the
        substrate's own caution/avoidance and a run of failures restrains the
        whole self through those existing emotions (appraisal blends over time —
        no per-tool cooldown). Discipline lives in the self, not a counter.
        """
        # TOOL SCOPING. `task.allowed_tools` is None for the substrate's own work
        # (every tool), and a list for an agent the substrate deployed
        # with a granted subset. A copy of the self may reach ONLY what it was
        # granted; a tool outside the grant is refused here, honestly, before it
        # runs — the substrate decides what its copies can touch.
        allowed = getattr(task, "allowed_tools", None)
        if allowed is not None and tool_name not in allowed:
            logger.info("[substrate-tools] %s not granted to task %s (allowed=%s); refused",
                        tool_name, task.id, allowed)
            return None
        import time
        # NAME THE INTENT THIS WORK BELONGS TO. Every acting path binds it, so the
        # gate can read WHY an act is happening rather than only what it is. Only
        # the id travels; the constitution fetches the record, so a task cannot
        # assert a justification by carrying one.
        #
        # A task with no intent binds None, and that is not a loophole — it is the
        # honest state of affairs, and Law 2 answers it: an act that changes
        # something with nothing to explain it goes back to planning.
        from core.reasoning.intent_authority import (
            set_acting_intent, reset_acting_intent,
            set_acting_actor, reset_acting_actor)
        _provenance = getattr(task, "provenance", None) or {}
        _intent_token = set_acting_intent(
            _provenance.get("intent_id") or (task.metadata or {}).get("intent_id"))
        # WHOSE WORK THIS IS, bound beside the intent and released with it.
        # `actor_for` already decided this when the task was made — substrate
        # sources own their work, user sources carry the user's id — so this
        # reads that decision rather than making a second one.
        _actor_token = set_acting_actor(getattr(task, "actor", None))
        _t0 = time.perf_counter()
        try:
            # Reset as soon as the call returns: the binding exists for the gate,
            # and a token left set would leak this task's intent onto whatever
            # this context does next.
            try:
                result = await self.tool_registry.execute_tool(tool_name, params)
                result = await self._carry_out_redirect(tool_name, params, result)
            finally:
                # BOTH bindings released together, and in the `finally` — a token
                # left set leaks this task's intent AND its owner onto whatever
                # this context does next, which would mean the following act was
                # judged as belonging to someone who had nothing to do with it.
                reset_acting_intent(_intent_token)
                reset_acting_actor(_actor_token)
        except Exception as e:
            logger.debug("[substrate-tools] %s raised: %s", tool_name, e)
            # The tool did not execute: no control established over the world.
            _ms = int((time.perf_counter() - _t0) * 1000)
            await self._appraise_tool_outcome(task, executed=False, succeeded=False)
            await self._observe_tool_belief(tool_name, params, None, success=False)
            await self._record_tool_metrics(task, tool_name, executed=False,
                                            success=False, latency_ms=_ms,
                                            failure_reason=str(e))
            # Carry the real failure reason back (not None): completion's DID
            # channel reads it to tell an intended effect that was already met
            # (e.g. a removal of an already-absent file) from a genuine failure.
            return {"success": False, "model_free": True, "tool": tool_name,
                    "output": None, "error": str(e),
                    "task_id": task.id, "method": "substrate_tool"}
        _ms = int((time.perf_counter() - _t0) * 1000)
        if not getattr(result, "success", None):
            # The tool executed but reported failure — we can act, this route is
            # wrong. Felt as a poor outcome with control intact (replan, not
            # escalation), accumulating toward avoidance if it keeps happening.
            await self._appraise_tool_outcome(task, executed=True, succeeded=False)
            await self._observe_tool_belief(tool_name, params,
                                            getattr(result, "output", None), success=False)
            _err = str(getattr(result, "error", "") or "tool reported failure")
            await self._record_tool_metrics(task, tool_name, executed=True,
                                            success=False, latency_ms=_ms,
                                            failure_reason=_err)
            # Return the tool's OWN error (not None): the DID channel reads it to
            # recognise an intended effect already satisfied — e.g. a removal that
            # "failed" only because the target was already gone.
            return {"success": False, "model_free": True, "tool": tool_name,
                    "output": getattr(result, "output", None), "error": _err,
                    "task_id": task.id, "method": "substrate_tool"}
        logger.info("[substrate-tools] task %s executed model-free via %s", task.id, tool_name)
        await self._appraise_tool_outcome(task, executed=True, succeeded=True)
        await self._observe_tool_belief(tool_name, params,
                                        getattr(result, "output", None), success=True)
        await self._record_tool_metrics(task, tool_name, executed=True,
                                        success=True, latency_ms=_ms)
        return {
            "success": True,
            "model_free": True,
            "tool": tool_name,
            "output": getattr(result, "output", None),
            "task_id": task.id,
            "method": "substrate_tool",
        }

    async def _carry_out_redirect(self, tool_name: str, params: Dict[str, Any],
                                  result: Any) -> Any:
        """A REDIRECT is an instruction, not a refusal with an opinion.

        Law 3 answers an irreversible act that has a recoverable form by NAMING
        that form. Until something performs it, the substrate is simply stopped
        from work its own constitution says it may do — in the permitted way. So
        the act becomes the alternative here, at the substrate's acting seam,
        which is where a decision about WHAT TO DO belongs. The gate stays what
        it is: only ALLOW passes it, and the alternative is judged on its own
        merits like any other act.

        Nothing is silent. The result carries which act was refused, why, and
        which act was performed instead, so a caller cannot mistake one for the
        other. One substitution only: if the alternative is itself refused, that
        refusal stands.
        """
        judgment = ((getattr(result, "metadata", None) or {}).get("judgment") or {})
        if judgment.get("verdict") != "redirect":
            return result
        alternative = judgment.get("alternative") or {}
        alt_tool = alternative.get("tool")
        alt_params = dict(alternative.get("parameters") or {})
        if not alt_tool:
            return result
        from core.reasoning.intent_authority import (
            set_carrying_out, reset_carrying_out)
        logger.info("📜 carrying out the constitution's alternative: %s → %s (%s)",
                    tool_name, alt_tool, alternative.get("why", ""))
        token = set_carrying_out(judgment.get("judgment_id"))
        try:
            performed = await self.tool_registry.execute_tool(alt_tool, alt_params)
        finally:
            reset_carrying_out(token)
        if not isinstance(getattr(performed, "metadata", None), dict):
            performed.metadata = {}
        performed.metadata["redirected_from"] = {
            "tool": tool_name, "parameters": params,
            "refused_because": judgment.get("reason"),
            "law_number": judgment.get("law_number"),
            "judgment_id": judgment.get("judgment_id"),
        }
        return performed

    async def _appraise_tool_outcome(self, task: "Task", *, executed: bool,
                                     succeeded: bool) -> None:
        """Report a raw substrate tool outcome to the whole-self appraisal.

        The tool-path counterpart to `_appraise_substrate_execution` (which
        serves the learned-rule path). It feeds only what was actually measured,
        and the attribution is the honest STRUCTURAL read of the observed
        outcome — not a guess:
          • executed and succeeded    → SUCCESS            (approach engages)
          • executed but failed clean → STRATEGY_FAILURE   (the chosen approach,
              which the substrate controls, is the fault → the self replans)
          • could not execute at all  → EXECUTION_FAILURE  (the action itself
              failed → the self cannot act here: escalation/avoidance)
        Appraisal owns the emotional/behavioural response; this only reports.
        The outcome_class here drives appraisal's attribution only — it is not
        routed to meta-learning credit, so it moves no posteriors. Isolated: a
        fault here is logged, never fatal to execution.
        """
        try:
            from core.learning.meta_learning import OutcomeClass
            if succeeded:
                outcome_class = OutcomeClass.SUCCESS
            elif executed:
                outcome_class = OutcomeClass.STRATEGY_FAILURE
            else:
                outcome_class = OutcomeClass.EXECUTION_FAILURE
            self.appraisal.update(
                outcome_quality=1.0 if succeeded else 0.0,
                # "the tool ran" is distinct from "the outcome was right": an
                # executed-but-failed call keeps controllability (replan); a call
                # that could not execute lowers it (escalation/avoidance).
                action_success_rate=1.0 if executed else 0.0,
                outcome_class=outcome_class,
                # One handler binds exactly one tool per type — no choice among
                # options; reporting otherwise would inflate agency.
                options_considered=1,
                self_initiated=(
                    getattr(getattr(task, 'source', None), 'value', None) == 'autonomous'),
            )
        except Exception as e:
            logger.warning("substrate tool-outcome appraisal update failed: %s", e)

    async def _record_tool_metrics(self, task: "Task", tool_name: str, *,
                                   executed: bool, success: bool,
                                   latency_ms: int,
                                   failure_reason: Optional[str] = None) -> None:
        """The FOURTH consumer of the post-tool seam (beside appraisal, beliefs,
        and learning-evidence): report the run's METRICS — success/failure and
        latency, attributed to the task — to the tool-metrics owner
        (AdaptiveToolLearning), the one collector `get_learning_metrics`
        summarizes. The engine gives off metrics; the learning pipeline collects
        them. Guarded: the owner is injected by main.py and absent standalone, and
        a recording fault is never fatal to execution."""
        owner = getattr(self, "adaptive_tool_learning", None)
        if owner is None:
            return
        try:
            await owner.record_tool_run(
                task_id=getattr(task, "id", "") or "",
                task_description=getattr(task, "description", "") or "",
                tool_name=tool_name, success=success, executed=executed,
                latency_ms=latency_ms, failure_reason=failure_reason)
        except Exception as e:
            logger.debug("tool-metrics recording skipped: %s", e)

    async def _observe_tool_belief(self, tool_name: str, params: Dict[str, Any],
                                   output: Any, *, success: bool) -> None:
        """The THIRD consumer of the post-tool observation seam (beside
        appraisal and learning-evidence): fold what the tool OBSERVED into the
        belief graph, ROUTED THROUGH THE REASONING AUTHORITY. This is the
        substrate learning about its own capabilities from experience; the belief
        changes surface/resolve unstable regions that drive the epistemic
        exploration loop (intrinsic_motivation._generate_epistemic_goals). One
        seam, one observed outcome — never a parallel observation. Isolated: a
        fault here is logged, never fatal to execution."""
        try:
            from core.reasoning.neural_bridge import get_neural_bridge
            await get_neural_bridge().observe_tool_result(tool_name, params, output, success)
        except Exception as e:
            logger.debug("tool-belief observation skipped: %s", e)

    async def _execute_operation(self, task: Task) -> Optional[Dict[str, Any]]:
        """The ONE operation path for EVERY task — no per-TaskType handler switch.

        A task is executed by the substrate performing the operation it declares
        or implies, model-free. Routing is by the NATURE of the work (content),
        never a hardcoded `{TaskType: handler}` table:

          (a) DECLARED TOOL WORK — the task names the tool(s) to run (an agent's
              defined toolset, or the substrate's own plan). Each runs through the
              real `_run_tool` (scoped by `allowed_tools`, appraised, metered).
              This is what lets the substrate deploy an agent with a defined set
              of tools and have it actually execute them.
          (b) A QUESTION / KNOWLEDGE REQUEST — answered through the substrate's
              ONE knowledge loop (`understand`): memory → reason → gap → learn.
              Research is not a special case here; it is just a task that reads as
              a knowledge request.

        Declines (None) only when the task is neither — leaving the honest gap.
        Nothing here consults a model; success is never faked.
        """
        result = await self._execute_declared_tools(task)
        if result is None:
            result = await self._answer_via_knowledge_loop(task)
        if result is None:
            return None
        # ── CLOSE THE PURSUIT THIS TASK OWNS ─────────────────────────────────
        #
        # This path did the task's whole work, so it is the owner and this is
        # where "did I do what I meant" is answerable. It was the third acting
        # site with no reconciliation: tool work and answered questions left
        # their intents in `forming` forever, and integrity's action↔outcome link
        # fell back to the attribution label for all of it.
        #
        # Same ownership rule as the operator path: a step of a plan carries the
        # PLAN's intent_id, and the plan closes its own route at the end. Closing
        # here would conclude a multi-step pursuit on its first step.
        #
        # An intent with no goal conditions reconciles to nothing rather than to
        # a verdict — a question-shaped intent names no world state to check, and
        # inventing "missed" for it would dent integrity for an act that had no
        # aim to miss.
        provenance = getattr(task, "provenance", None) or {}
        intent_id = provenance.get("intent_id")
        if intent_id and not provenance.get("plan_id"):
            reconciled = await self._reconcile_intent(
                str(intent_id), provenance.get("domain_id") or "",
                detail=f"{getattr(task, 'type', '')}: operation completed")
            if reconciled is not None and isinstance(result, dict):
                # MEANT vs HAPPENED travels with the result, as it does on the
                # plan path, so downstream credit reads the world's verdict
                # rather than re-deriving it from a success flag.
                result["intent_outcome"] = reconciled
        return result

    async def _execute_declared_tools(self, task: Task) -> Optional[Dict[str, Any]]:
        """Run the tool(s) a task DECLARES, model-free, each through `_run_tool`.

        The declaration rides in the task's parameters (where the factory puts an
        agent's deploy parameters): `metadata["parameters"]["tool_plan"]` is a list
        of ``{"tool": name, "args": {...}}`` steps, or a single ``{"tool", "args"}``.
        Each step runs through the real tool path — so `allowed_tools` scoping,
        appraisal, belief, and metrics all apply, and a step's success is the
        tool's REAL success (a refused, raised, or failure-reporting tool is a
        failed step, never faked).

        Declines (None) when the task declares no tools, leaving the next path to
        try. Returns an honest aggregate otherwise: success only if EVERY declared
        tool executed successfully, with a per-tool breakdown either way.
        """
        params = (task.metadata or {}).get("parameters") or {}
        plan = params.get("tool_plan")
        if plan is None and params.get("tool"):
            plan = [{"tool": params["tool"], "args": params.get("args", {})}]
        if not plan:
            return None

        results: List[Dict[str, Any]] = []
        all_ok = True
        for step in plan:
            tool = (step or {}).get("tool")
            args = (step or {}).get("args") or {}
            if not tool:
                all_ok = False
                results.append({"tool": None, "success": False,
                                "error": "step declared no tool"})
                continue
            outcome = await self._run_tool(tool, args, task)
            ok = outcome is not None and outcome.get("success") is True
            all_ok = all_ok and ok
            # Provenance for completion evidence: `resource` is the DID causal
            # lineage (tools on the SAME resource collapse to one event);
            # `intervention_target` is the world resource SAW re-observes fresh.
            target_arg = _INTERVENTION_TARGET_ARG.get(tool)
            results.append({
                "tool": tool,
                "success": ok,
                "output": (outcome or {}).get("output") if ok else None,
                # Prefer the tool's OWN error so DID can read an already-satisfied
                # intent (e.g. removal of an already-absent target); the generic
                # message stands in only when the step was refused before running.
                "error": None if ok else
                         ((outcome or {}).get("error")
                          or "tool did not execute successfully (refused before running)"),
                "resource": _tool_resource(tool, args),
                "intervention_target": (args.get(target_arg) if target_arg else None),
            })

        return {
            "success": all_ok,
            "model_free": True,
            "verification_state": "verified" if all_ok else "failed",
            "task_id": task.id,
            "task_type": task.type.name,
            "method": "declared_tools",
            "tools_run": results,
            "output": {"tools_run": results},
        }

    async def _answer_via_knowledge_loop(self, task: Task) -> Optional[Dict[str, Any]]:
        """Answer a QUESTION / knowledge request through the substrate's ONE
        knowledge loop (`understand`) — not a bare web search, and not gated on
        TaskType.

        The loop lives on this substrate's own conversation: it queries what is
        already held, reasons over it (neural bridge + held rules), and ONLY on a
        genuine gap researches the web -- verifying the finding names the topic
        before reading it into the store through the learning authority. Routing
        here is by CONTENT (is this a question / knowledge request?), so any task
        that reads as one is answered this way; a pure action task with no
        declared tool falls through to the honest gap instead of being answered
        as if it were a question.
        """
        desc = task.description.strip()
        is_knowledge = Conversation.is_question(desc) or bool(re.match(
            r"^(?:research|look\s+up|find\s+out|investigate|study|explain|define|"
            r"describe|summarize|tell\s+me\s+about)\b", desc, flags=re.IGNORECASE))
        if not is_knowledge:
            return None

        topic = re.sub(r"^(?:research|look\s+up|find\s+out\s+about|investigate|study)\s+",
                       "", desc, flags=re.IGNORECASE).strip() or desc
        query = desc if Conversation.is_question(desc) else f"what is {topic}?"

        try:
            conversation = self.conversation(session=f"knowledge:{task.id}")
            understanding = await conversation.understand(query)
        except Exception as error:
            logger.warning(f"knowledge loop failed for {task.id}: {error}")
            return None

        learned = [a for a in understanding.acquired if getattr(a, "stored", False)]
        # Complete only if the loop actually answered (from memory or reasoning)
        # or learned something new. Nothing answered and nothing learned is a
        # genuine gap -- declined here, reported honestly upstream, never faked.
        if not understanding.answered and not learned:
            return None

        return {
            "success": True,
            "model_free": True,
            # A knowledge task's goal is answered-or-learned; the loop returns here
            # only when it genuinely did (memory/reasoning answered, or a fact was
            # learned and stored). That IS the re-observed effect for this task, so
            # it is verified evidence (corroborated further by each learned fact).
            "verification_state": "verified",
            "task_id": task.id,
            "task_type": task.type.name,
            "method": "conversation.understand",
            "answer": understanding.reply,
            "learned": [a.label for a in learned],
            "output": {"answer": understanding.reply,
                       "learned": [a.label for a in learned]},
        }

    async def execute_task(self, task: Task) -> Dict[str, Any]:
        """
        Execute a task, substrate-first.

        A task carrying a grounded operator from a VALIDATED learned rule is
        already proved: the substrate knows what to do and why. That runs
        deterministically here, with no model consulted. Everything else falls
        through to model-backed execution, where the model acts as a proposer
        for work the substrate cannot yet do itself.

        This mirrors neural_bridge._substrate_solvers, which has routed reasoning
        this way all along. Execution previously went straight to the model
        unconditionally, so a step the substrate could prove was still decided
        by generation.

        Args:
            task: Task to execute

        Returns:
            Dict with execution results
        """
        if self.tool_registry is None:
            await self.initialize_execution_faculty()

        substrate = await self._execute_grounded_operator(task)
        if substrate is not None:
            return substrate

        # A task that names a STATE to reach is planned over learned operators
        # and driven to completion here, still with no model consulted. Where
        # the single-operator path runs one proved step, this proves and runs a
        # whole sequence. It declines (None) only when the task carries no state
        # goal, and then execution falls through as before.
        driven = await self._drive_substrate_goal(task)
        if driven is not None:
            return driven

        # The ONE operation path for every task type (no per-type switch): run the
        # tool(s) the task declares, or answer it through the knowledge loop if it
        # reads as a question. Model-free; declines (None) when the task is
        # neither, leaving the honest gap below unchanged.
        tooled = await self._execute_operation(task)
        if tooled is not None:
            return tooled

        # SUBSTRATE-ONLY. The three paths above are the substrate's own
        # model-free execution. If none handled the task, the substrate cannot
        # YET do it — reported as an HONEST GAP, never delegated to a model.
        # The model path that used to follow here (self.llm /
        # _execute_task_with_tools) is retired; the capability is closed by
        # building a per-type substrate handler, not by generation.
        return {
            'success': False,
            'model_free': True,
            'verification_state': 'failed',
            'error': (f"no substrate handler for a {task.type.name} task yet; the "
                      f"substrate declined all model-free paths and the model is "
                      f"not a fallback"),
            'task_id': task.id,
            'task_type': task.type.name,
        }

    async def get_status(self) -> Dict[str, Any]:
        """Get executor status."""
        return {
            'active': self.active,
            'model_free': True,  # substrate-only executor; holds no model
            'stats': self.stats.copy(),
        }



async def create_autonomous_system(config: Optional[Dict[str, Any]] = None) -> AutonomousCoordinator:
    """
    Create an autonomous system coordinator (without initializing).

    Caller must inject dependencies and then call coordinator.initialize() manually.
    This allows dependency injection before initialization.
    """
    coordinator = AutonomousCoordinator(config)
    return coordinator


# Singleton instance
_autonomous_coordinator = None

async def get_autonomous_coordinator(config: Optional[Dict[str, Any]] = None) -> Optional[AutonomousCoordinator]:
    """
    Get global autonomous coordinator instance (singleton).

    Created on first use. The substrate is model-free: no model is accepted.
    """
    global _autonomous_coordinator
    if _autonomous_coordinator is None:
        _autonomous_coordinator = await create_autonomous_system(config)
    return _autonomous_coordinator


# =============================================================================
# LANGUAGE / CONVERSATION FACULTY — understanding and reply.
#
# Moved here from self_model.py when the Self was collapsed into this
# coordinator: conversation is not a separate concern from the substrate — it
# is the substrate using its own faculties to read what was said, resolve it
# against what it holds, and answer. It lives WITH the substrate (this module)
# so a reply is composed THROUGH the brain that owns reasoning, memory and
# language, reached via the coordinator's `conversation()` accessor.
# =============================================================================

#: Words that carry structure rather than content. The same small lexicon the
#: sentence machine uses, plus the prepositions that join phrases. Kept tiny and
#: visible: every entry is a place a person decided something.
FUNCTION_WORDS = frozenset({
    "is", "are", "was", "were", "be", "been", "a", "an", "the", "not", "no",
    "of", "in", "on", "at", "to", "by", "for", "with", "from", "and", "or",
    "that", "this", "it", "does", "do", "did", "what", "which", "how", "why",
    "when", "where", "who", "can", "will", "would", "should",
    "tell", "me", "you", "i", "please", "about", "there", "any", "some",
    # Logical connectives are STRUCTURE, not concepts. Without them here, a
    # conditional's "if"/"then" were resolved as content and reported as
    # unknown ("I hold nothing for: if, then") — grammar mistaken for a gap.
    "if", "then", "else", "unless", "so",
})

#: The stored relation labels a WHERE / WHEN question is answered from. The
#: reader parses "where is X?" to the abstract relation `location` and "when is
#: X?" to `time`; the store holds the CONCRETE preposition the fact was taught
#: with ("the cup is in the box" -> `in`), so answering a locative/temporal
#: question means reading any relation of the right FAMILY off the subject. The
#: two families overlap (`at`/`on`/`in`/`by` are both), which is correct -- "the
#: meeting is at noon" and "the cup is at the door" both use `at`.
LOCATIVE_RELATIONS = frozenset({
    "in", "on", "at", "by", "under", "inside", "outside", "above", "below",
    "over", "near", "behind", "beside", "within", "atop", "beneath", "among",
    "around", "through"})
TEMPORAL_RELATIONS = frozenset({"at", "by", "on", "in", "before", "after",
                                "during"})

#: Words that carry a COUNT, so a "how many …?" question can read the quantity
#: off a stored fact ("a spider has eight legs" -> `has eight_leg`). A digit
#: counts too; this is only for the spelled-out forms the reader keeps whole.
NUMBER_WORDS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "thousand", "million", "billion"})

#: Longest phrase considered as a single concept name.
MAX_PHRASE = 4

#: A sentence opening with one of these, or ending in a question mark, is being
#: ASKED. Anything else is being TOLD. Stated crudely and on purpose: it is one
#: rule, in one place, and it is wrong in ways you can see rather than in ways
#: buried in a model.
#: Verbs that name an act of SAYING, and the participants who can perform
#: one. A question built out of both is not a question about the world -- it
#: is a question about this conversation, and the conversation's own record is
#: the only thing that can answer it.
SPEECH_ACTS = {
    "ask": "asked", "asks": "asked", "asked": "asked", "asking": "asked",
    "say": "said", "says": "said", "said": "said", "saying": "said",
    "tell": "told", "tells": "told", "told": "told", "telling": "told",
    "mention": "said", "mentions": "said", "mentioned": "said",
    "talk": "discussed", "talking": "discussed", "talked": "discussed",
    "discuss": "discussed", "discussing": "discussed", "discussed": "discussed",
    "answer": "said", "answered": "said", "reply": "said", "replied": "said",
}
#: Who is speaking. `we` is both of us, which makes the answer the subject
#: rather than either side's words.
SPEAKER_THEM = frozenset({"i", "me", "my"})
SPEAKER_ME = frozenset({"you", "your"})
SPEAKER_BOTH = frozenset({"we", "us", "our"})

QUESTION_OPENERS = frozenset({
    "what", "which", "who", "whose", "where", "when", "why", "how", "is", "are",
    "was", "were", "does", "do", "did", "can", "could", "will", "would",
    "should", "tell", "explain", "define",
})

#: How many turns a conversation keeps. Continuity is recent -- "what were we
#: talking about" and the referent a feedback verdict judges both live in the
#: last handful of turns -- so a generous cap preserves it while stopping the
#: per-turn append from growing without bound for the life of the object.
_CONVERSATION_TURN_MEMORY = 256

#: How far back a verdict may reach for the claim it is about. Feedback follows
#: the thing it judges closely; a small window keeps "no, that's wrong" attached
#: to what was just taught rather than to something said long ago.
_FEEDBACK_WINDOW = 5

#: Endings stripped to compare a word in a question against a relation label
#: held on a concept: `causes` against `caused by`. Crude and visible, which is
#: better than a hidden one -- and it is used ONLY to match what is already
#: stored, never to decide what anything means.
from core.semantics.lexical_normalization import match_key

#: How a stored relation says it is denied. `concept_ingestion` writes the
#: third element of a relationship entry; anything not in this set is read as
#: an affirmation.
NEGATIVE_POLARITIES = frozenset({"negative", "denies", "false", "no"})

def _as_pairs(relations) -> Tuple[Tuple[str, str], ...]:
    """(relation, object) pairs, with polarity folded into the relation.

    A stored relation may carry a third element saying it is denied. Readers
    that unpack two values crash on it, and readers that slice it to two lose
    the denial -- which turns "a kestrel is not a fish" into the claim that it
    IS one. Folding it into the relation keeps the claim intact in a shape one
    reader can handle.
    """
    out = []
    for entry in relations or ():
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        relation, other = str(entry[0]), str(entry[1])
        if len(entry) > 2 and str(entry[2]).lower() in NEGATIVE_POLARITIES:
            relation = "is not" if relation == "is" else f"not {relation}"
        out.append((relation, other))
    return tuple(out)


_ENDINGS = ("ed", "es", "s", "ing")


def stem(word: str) -> str:
    """The retrieval form of a word. Owned by lexical_normalization.

    THIS CHOPPED FIXED ENDINGS AND PRODUCED NON-WORDS: `files` -> `fil`,
    `indices` -> `indic`, `analyses` -> `analys`, `batteries` -> `batteri`,
    `physics` -> `physic`. It handled no irregular at all, so `geese` never
    matched `goose` and `children` never matched `child` -- and this function
    is what `same_stem` uses to decide whether something you say matches a
    relation the substrate ALREADY HOLDS. A miss here reads as the substrate
    not knowing something it does know.

    This sits at the chat -> substrate boundary, which is exactly where the
    shared vocabulary has to hold, so it delegates to the module that declares
    it rather than keeping a third private copy.
    """
    return match_key(word) or word.lower().strip()


def same_stem(left: str, right: str) -> bool:
    """Whether two words are the same word for the purpose of matching a
    relation already stored. `visualizes` stems to `visualiz` and `visualize`
    stems to itself, so exact equality is not enough and a longer list of
    endings would only move the seam."""
    a, b = stem(left), stem(right)
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 5 and longer.startswith(shorter)


@dataclass(frozen=True)
class Resolved:
    """One phrase of the sentence, and what it turned out to be."""

    phrase: str
    concept_id: Optional[str] = None
    how: str = "unresolved"
    domain: str = ""
    description: str = ""
    relations: Tuple[Tuple[str, str], ...] = ()
    #: Other concepts of the same name, when the store holds more than one.
    alternatives: Tuple[Tuple[str, str], ...] = ()

    @property
    def known(self) -> bool:
        return self.concept_id is not None

    @property
    def informative(self) -> bool:
        """Whether resolving it told us anything.

        The store holds 636 concepts with no description and 240 bare
        fragments -- `load`, `balancer`, `visualize` -- with nothing attached.
        Matching one is not an answer, and reporting `held, with no
        description` is worse than admitting ignorance, because it stops the
        substrate going and finding out.
        """
        return self.known and bool(self.description or self.relations)


@dataclass
class Acquired:
    """Something the substrate did not hold and now does."""

    label: str
    description: str = ""
    relations: Tuple[Tuple[str, str], ...] = ()
    origin: str = ""
    stored: bool = False
    detail: str = ""
    #: The SEMANTIC memory this admission created (from the ingress `Admission`),
    #: or None if nothing was retained. Carried so a later feedback turn can
    #: flag the exact memory this proposition made instead of storing another.
    memory_id: Optional[str] = None
    #: Whether a model was needed to split the sentence up. The FACT is always
    #: yours; this records only who found the seams in it.


@dataclass
class Answer:
    """A relation the question asked about, and what the store holds for it."""

    about: str
    relation: str
    others: Tuple[str, ...]
    #: For a yes/no question, what the store says. None when the question did
    #: not ask for a verdict -- "what causes X" wants the objects, not a yes.
    #:
    #: THREE VALUES, NEVER TWO. `False` means the store holds the DENIAL ("a
    #: kestrel is not a fish"); not-asked is None. Collapsing "I hold the
    #: opposite" into "no" would make a refutation indistinguishable from
    #: never having been told.
    verdict: Optional[bool] = None
    #: The premises a DERIVED verdict rests on. Empty for a verdict read
    #: directly off the store; the claims the substrate reasoned FROM when the
    #: answer was proved rather than looked up, so the reply can say WHY.
    support: Tuple[str, ...] = ()
    #: For a DERIVED answer -- one reasoning reached rather than the store held
    #: as a single relation -- the conclusion rendered as words ("pipe friction
    #: causes pressure loss"). Empty for a direct store answer, which the reply
    #: composes from about/relation/others instead.
    conclusion: str = ""


@dataclass
class Understanding:
    """What the substrate made of one sentence."""

    sentence: str
    resolved: List[Resolved] = field(default_factory=list)
    reading: Optional[Tuple[str, ...]] = None
    reading_source: str = ""
    answers: List[Answer] = field(default_factory=list)
    acquired: List[Acquired] = field(default_factory=list)
    remembered: List[str] = field(default_factory=list)
    #: What recall managed in the time available, and whether that was all of it.
    recall: Optional[Any] = None
    asked: bool = True
    reply: str = ""
    #: The self's disposition when this was understood (mode + explore flag), or
    #: None standalone. Lets `say()` colour a turn-back qualitatively from
    #: self-state without recomputing it.
    disposition: Optional[Dict[str, Any]] = None

    @property
    def answered(self) -> bool:
        """Whether the turn actually answered, as opposed to asking back.

        Recorded because the memory of the exchange says which, and a memory
        claiming an answer where a question was asked is a false record of the
        conversation -- one that reads back later as knowledge it never had."""
        return bool(self.known or self.answers
                    or any(a.stored for a in self.acquired))

    def spoken_for(self) -> set:
        """Words the answers account for, so they are not also called unknown."""
        used = set()
        for answer in self.answers:
            # RAW, not stemmed: `same_stem` stems both sides, and stemming here
            # too turned `caused` into `caus` into `cau`, so the word that
            # matched the relation was still reported as one nothing was held for.
            used.update(answer.relation.replace("_", " ").split())
        return used

    @property
    def known(self) -> List[Resolved]:
        return [r for r in self.resolved if r.informative]

    @property
    def unknown(self) -> List[Resolved]:
        return [r for r in self.resolved if not r.informative]


def _titles(phrase: str, title: str) -> bool:
    """Whether `title` names `phrase` -- every content word of it, by stem."""
    wanted = [w for w in phrase.replace("_", " ").split() if w not in FUNCTION_WORDS]
    if not wanted:
        return False
    have = [w.strip("()") for w in (title or "").split()]
    return all(any(same_stem(word, held) for held in have) for word in wanted)


@dataclass
class Turn:
    """One exchange, as the conversation itself recorded it."""

    said: str
    asked: bool
    subject: str
    reply: str
    #: The memories this turn admitted (a telling can state several
    #: propositions). Empty for a question or an unstored telling. This is what
    #: a following feedback turn ("no, that's wrong") flags: the verdict lands
    #: on the memory the claim already made, not on a new record.
    memories: Tuple[str, ...] = ()


def phrases(words: Sequence[str]) -> List[Tuple[int, int, str]]:
    """Every candidate phrase, longest first, as (start, end, text)."""
    out = []
    for size in range(min(MAX_PHRASE, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            window = words[start:start + size]
            if all(w in FUNCTION_WORDS for w in window):
                continue
            out.append((start, start + size, "_".join(window)))
    return out


class Conversation:
    """Reads a sentence and answers out of what the substrate holds."""

    def __init__(self, db=None, identity=None, emit=None, session="default",
                 actor_identity=None):
        self._db = db
        self._identity = identity
        #: WHO is being spoken with — a THREAD OF TALK handle, used for beliefs
        #: ABOUT the user (`_learn_about_user`) and as the LAST-RESORT scope when
        #: no verified identity is bound.
        self._session = str(session)
        #: The VERIFIED identity of the person speaking — a World Auth user id,
        #: supplied by whatever authenticated them (the gateway/world). When set,
        #: it — not the ephemeral session — is the ACTOR a told fact is scoped to,
        #: so the same person is one context across sessions and devices. `_actor`
        #: resolves it through the one owner (`actor_for`). None = unauthenticated,
        #: and the session stands in as an anonymous per-thread scope.
        self._actor_identity = actor_identity
        self._user_beliefs_ready = False
        #: The substrate's event emitter, injected by the coordinator that owns
        #: this conversation (`conversation()`), so a taught proposition becomes
        #: a self-event the domain authority reacts to. None when the
        #: conversation is used standalone (a script, a test) -- teaching still
        #: admits, it just does not wake a reaction.
        self._emit = emit
        #: The LEARNING AUTHORITY (UnifiedLearningSystem), injected by the
        #: coordinator that owns this conversation. Teaching goes THROUGH it —
        #: `learn_fact`/`learn_rule` — so a taught proposition fans out to every
        #: system that depends on learning (reasoning, beliefs, lexicon, domain,
        #: memory, metrics) from one place, instead of this reaching into the
        #: ingress directly. None when standalone: it falls back to the authority
        #: singleton, so teaching still goes through the one path.
        self._learning = None
        #: The substrate's DISPOSITION read, injected by the coordinator that
        #: owns this conversation, so a reply can be informed by self-state (the
        #: BehaviorArbiter's current directive). None when standalone -- the
        #: reply is then exactly what it was, never a guessed mood.
        self._disposition = None
        #: Recall persists across turns, so a wave that lands after one answer
        #: is already in hand for the next question -- which is usually about
        #: the same thing.
        self._recall = None
        #: The last turn's subject and what it said, so a subject that came out
        #: of that answer can be recognised as following it rather than
        #: replacing it.
        self._last_subject = ""
        self._last_reply = ""
        #: EVERY TURN, IN ORDER. The conversation is a thing that can be asked
        #: about -- "what did I just ask", "what were we talking about" -- and
        #: until this existed there was no owner for those questions, so they
        #: fell through to the only owner there was: research an unrecognised
        #: phrase. "What did I just ask you about?" went to the encyclopedia
        #: and came back with an article about the rhetorical tactic of asking
        #: questions. The conversation's record is the authority on the
        #: conversation. Not the concept store, and never the web.
        # BOUNDED. A plain list here only ever grew -- one conversation object
        # accumulated a turn per exchange for its whole life and never freed
        # one, the same unbounded-append leak `learn_from_event` had. The record
        # exists for continuity ("what were we talking about", and the referent
        # a feedback turn judges), and continuity is recent: a generous window
        # keeps that intact while capping the growth. Iterated/reversed only,
        # never sliced, so a deque is a drop-in.
        self._turns: "deque[Turn]" = deque(maxlen=_CONVERSATION_TURN_MEMORY)

    async def _services(self):
        if self._db is None:
            from core.database import TorinUnifiedDatabase
            self._db = TorinUnifiedDatabase()
            await self._db.initialize()
        if self._identity is None:
            from core.domain.concept_identity import ConceptIdentityService
            self._identity = ConceptIdentityService(self._db)
        return self._db, self._identity

    @property
    def _actor(self) -> str:
        """WHO a told fact is scoped to, resolved through the one owner
        (`actor_for`). A verified World Auth identity is that person's stable
        actor across every session — their telling is THEIR context, scoped.

        With NO bound identity this is the SUBSTRATE itself: a bare conversation
        is the curriculum/dev channel (teaching the substrate foundational
        knowledge), which belongs in the shared mind. Public users never reach
        here unidentified — they enter through `handle_user_request`, which
        always binds an actor (their identity, or the session as a fail-safe),
        so an external telling is always scoped and only in-process curriculum
        teaching is universal."""
        if self._actor_identity:
            from core.agents.autonomous.shared_types import actor_for
            return actor_for(TaskSource.MANUAL, str(self._actor_identity))
        return SUBSTRATE_ACTOR

    # ---- beliefs ABOUT THE USER (the third channel, held here) --------------
    # When the speaker tells the substrate about THEMSELVES ("I am a plumber",
    # "my favourite colour is blue", "I prefer tea"), that is not a fact about
    # the world. It must never enter the concept graph the reasoner walks (or a
    # user could rewrite what the substrate knows about reality just by talking
    # about themselves), and it is not true-or-false to verify — it is simply
    # what this person said of themselves. So it lives in its own store, keyed to
    # the speaker, free-flowing. This is part of the ONE conversation authority,
    # not a separate pipeline.

    @staticmethod
    def _about_speaker(subject: str) -> bool:
        """Is this proposition about the SPEAKER (first person) rather than the
        world? "I", "me", or a "my …" possessive. SPEAKER_THEM already names the
        first-person pronouns the conversation recognises."""
        s = (subject or "").strip().lower()
        return s in SPEAKER_THEM or s.startswith("my ")

    async def _ensure_user_beliefs(self) -> None:
        if self._user_beliefs_ready:
            return
        db, _ = await self._services()
        await db.execute_query(
            """
            CREATE TABLE IF NOT EXISTS unified.user_beliefs (
                speaker    TEXT NOT NULL,
                subject    TEXT NOT NULL,
                relation   TEXT NOT NULL,
                object     TEXT,
                polarity   TEXT NOT NULL DEFAULT 'positive',
                surface    TEXT,
                source     TEXT NOT NULL DEFAULT 'conversation',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (speaker, subject, relation)
            )
            """,
            commit=True,
        )
        self._user_beliefs_ready = True

    async def _learn_about_user(self, subject: str, relation: str,
                                obj: Optional[str], *, positive: bool = True,
                                surface: str = "") -> "Acquired":
        """Hold one belief about the speaker — NOT in the concept graph. Upserts
        on (speaker, subject, relation) so a restated preference updates rather
        than duplicates."""
        db, _ = await self._services()
        await self._ensure_user_beliefs()
        await db.execute_query(
            """
            INSERT INTO unified.user_beliefs
                (speaker, subject, relation, object, polarity, surface, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (speaker, subject, relation) DO UPDATE SET
                object = EXCLUDED.object, polarity = EXCLUDED.polarity,
                surface = EXCLUDED.surface, updated_at = now()
            """,
            (self._session, subject, relation, obj,
             "positive" if positive else "negative", surface),
            commit=True,
        )
        held = f"{subject} {relation} {obj}".strip()
        return Acquired(surface or held, description="about you", relations=(),
                        stored=True, detail="held as a belief about you, "
                        "not as a fact about the world")

    async def beliefs_about_user(self, limit: int = 50) -> List[Dict[str, Any]]:
        """What the substrate believes about this speaker, most-recent first.
        Read from the user store only — never the world concept graph."""
        db, _ = await self._services()
        await self._ensure_user_beliefs()
        rows = await db.execute_query(
            "SELECT subject, relation, object, polarity, surface, updated_at "
            "FROM unified.user_beliefs WHERE speaker = $1 "
            "ORDER BY updated_at DESC LIMIT $2",
            (self._session, limit), fetch_all=True)
        return [dict(r) for r in (rows or [])]

    async def _admissible_world_fact(self, subject: str, relation: str,
                                     obj: str, positive: bool):
        """Real-time verification before a CHAT-asserted world fact is admitted.

        Chat must not silently rewrite world knowledge, so a fact the substrate
        ALREADY KNOWS to be false is refused rather than stored. The check reuses
        the concept-graph reasoning (open-world): a FALSE verdict means an
        explicit denial / inherited disjointness refutes it. Only ISA positives
        are gated — that is the taxonomic knowledge a wrong override most damages,
        and a DENIAL is left to pass because a denial is how a user CORRECTS the
        store. A novel or merely-unproven fact passes: the substrate cannot refute
        it, and refusing what it cannot disprove would be dishonest. Returns
        (admissible, reason)."""
        if relation != "isa" or not positive:
            return True, ""
        try:
            from core.reasoning.concept_graph_reasoning import answer_over_graph
            from core.reasoning.relation_algebra import FALSE
            from core.semantics.relation_types import SemanticRelation
            db, _ = await self._services()
            o = obj.strip()
            for art in ("a ", "an ", "the "):
                if o.lower().startswith(art):
                    o = o[len(art):]
                    break
            ans = await answer_over_graph(db, subject, SemanticRelation.ISA, o,
                                          actor=self._actor)
            if getattr(ans, "verdict", None) == FALSE:
                return False, "that contradicts what I already know"
        except Exception as e:
            # Verification unavailable -> do NOT fake a rejection; admit honestly.
            logger.debug("world-fact verification skipped for %r: %s", subject, e)
        return True, ""

    def _learning_authority(self):
        """The one learning path teaching goes through. Injected by the owning
        coordinator; a standalone conversation falls back to the singleton, so
        teaching never routes around the authority."""
        if self._learning is not None:
            return self._learning
        from core.learning.unified_learning_system import get_learning_authority
        return get_learning_authority()

    def _evidence_emitter(self):
        """A payload->emit callback the learning authority triggers the domain
        reaction with, or None when this conversation has no emitter. Wraps the
        substrate's `emit` so the authority need not know the event type — the
        domain fan-out lives in the learning method, the transport stays here."""
        if self._emit is None:
            return None

        async def _emit_evidence(payload):
            # The learning authority describes what it admitted; this states it
            # in the shape the event declares, so the variant is named rather
            # than inferred from which keys turned up.
            d = payload if isinstance(payload, dict) else {}
            await self._emit(SelfEvent(
                SelfEventType.EVIDENCE_ADMITTED,
                payload=EvidenceAdmitted(
                    domain=str(d.get("domain") or ""),
                    kind=str(d.get("kind") or "fact"),
                    subject=d.get("subject"), relation=d.get("relation"),
                    obj=d.get("obj"), surface=d.get("surface"),
                    count=d.get("count")),
                origin="learning"))
        return _emit_evidence

    async def _concept(self, concept_id: str) -> Dict[str, Any]:
        db, _ = await self._services()
        rows = await db.execute_query(
            "SELECT concept_id, name, domain, description, relationships "
            "FROM unified.concepts WHERE concept_id=$1", (concept_id,), fetch_all=True)
        return rows[0] if rows else {}

    async def _incoming_relations(self, name: str) -> List[str]:
        """Facts that point AT a concept, as premise sentences.

        Relations are stored forward -- under the subject -- so "wibbling causes
        snargle" lives on `wibbling`, and a reverse question ("what causes
        snargle") never names the subject that holds it. This finds the concepts
        whose relations name THIS one as their object, so the fact reaches the
        reasoner as a premise. Text-matched then checked exactly: an extra
        premise the proof does not need is harmless, a missing one is not.
        """
        import json
        db, _ = await self._services()
        try:
            rows = await db.execute_query(
                "SELECT name, relationships FROM unified.concepts "
                "WHERE relationships::text ILIKE $1",
                (f"%{name}%",), fetch_all=True)
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(error, "autonomous_coordinator._incoming_relations")
            return []

        target = name.replace("_", " ").strip().lower()
        premises: List[str] = []
        for row in rows or ():
            subject = row.get("name")
            rels = row.get("relationships")
            if isinstance(rels, str):
                try:
                    rels = json.loads(rels)
                except (ValueError, TypeError):
                    continue
            for entry in (rels or ()):
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                relation, obj = entry[0], entry[1]
                if str(obj).replace("_", " ").strip().lower() == target:
                    premises.append(f"{subject} {relation} {obj}")
        return premises

    async def resolve(self, sentence: str) -> List[Resolved]:
        """Every phrase of the sentence that names something held, longest first."""
        import json

        from core.semantics.sentence_machine import tokenize

        db, identity = await self._services()
        words = tokenize(sentence)
        taken: set = set()
        found: List[Resolved] = []

        for start, end, text in phrases(words):
            if any(index in taken for index in range(start, end)):
                continue
            hits = await identity.resolve_query(text.replace("_", " ")) or []
            hits = hits or (await identity.resolve_query(text) or [])
            if not hits:
                continue
            concept_id, how = hits[0]
            record = await self._concept(concept_id)
            others = []
            for other_id, _ in hits[1:4]:
                other = await self._concept(other_id)
                if other.get("description"):
                    others.append((other_id, other.get("domain", "")))
            relations = ()
            if record.get("relationships"):
                # AN ENTRY MAY CARRY POLARITY, AND THIS DROPPED EVERY ONE THAT
                # DID. `for a, b in parsed` unpacks exactly two, so a
                # three-element `["is", "bird", "positive"]` raised ValueError,
                # the except swallowed it, and the concept resolved with ZERO
                # relations -- indistinguishable from a concept nothing is
                # known about. Measured: 21 of 464 concepts holding relations
                # were silently emptied this way, including every concept
                # taught through conversation, because `admit_relation` records
                # polarity and this reader predates it.
                #
                # A negative is not an absence. `a kestrel is not a fish` is
                # something the substrate KNOWS, and it must survive the read.
                try:
                    parsed = json.loads(record["relationships"])
                except Exception as error:
                    logger.warning("relationships for %s unreadable: %s",
                                   concept_id, error)
                    parsed = []

                # Same normaliser as the teach path, so a relation reads the
                # same however it reached the store.
                relations = _as_pairs(parsed[:4])
                if len(relations) != len(parsed[:4]):
                    logger.warning("relationships for %s held %d entries that "
                                   "are not relations", concept_id,
                                   len(parsed[:4]) - len(relations))
            candidate = Resolved(
                phrase=text.replace("_", " "), concept_id=concept_id, how=how,
                domain=record.get("domain", ""), description=record.get("description", ""),
                relations=relations, alternatives=tuple(others))
            if not candidate.informative:
                # A name with nothing behind it does not get to consume the
                # words. `load` and `balancer` are both in the store and both
                # empty; letting them match stopped `load balancer` ever being
                # looked up.
                continue
            found.append(candidate)
            taken.update(range(start, end))

        # WHAT IS LEFT OVER IS GROUPED, NOT SCATTERED. `load balancer` is one
        # thing the substrate does not know; asking about `balancer` on its own
        # returns a breed of cattle, which is what happened.
        run: List[str] = []
        for index, word in enumerate(words + [""]):
            if index < len(words) and index not in taken and word not in FUNCTION_WORDS:
                run.append(word)
                continue
            if run:
                found.append(Resolved(phrase=" ".join(run)))
                run = []

        # A WORD NAMING A RELATION OF SOMETHING ELSE IN THE SENTENCE IS BEING
        # USED AS THAT RELATION. `visualize` also matches a concept in another
        # domain entirely, and reciting it would answer a question nobody
        # asked.
        relations = {stem(part) for item in found if item.known
                     for relation, _ in item.relations
                     for part in relation.replace("_", " ").split()}
        return [item for item in found
                if not (item.known and len(item.phrase.split()) == 1
                        and any(same_stem(item.phrase, r) for r in relations))]

    def _leads_on(self, sentence: str) -> bool:
        """Whether this turn follows from what the last answer said."""
        from core.semantics.sentence_machine import tokenize

        if not (self._last_reply and self._last_subject):
            return False
        said = self._last_reply.lower()
        words = [w for w in tokenize(sentence) if w not in FUNCTION_WORDS]
        # Every content word already appeared in the last answer: the turn is
        # asking about something that answer raised.
        return bool(words) and all(w in said for w in words)

    @staticmethod
    def subject_of(sentence: str) -> str:
        """What this turn is about, before anything has been resolved.

        The content words, in order. Crude, and refined the moment resolution
        says what they actually were -- but a subject is needed BEFORE that, to
        file the first wave under, and `what is a load balancer` and `what is
        anomaly detection` must not be filed together merely because the turn
        has not worked out which is which yet.
        """
        from core.semantics.sentence_machine import tokenize

        words = [w for w in tokenize(sentence) if w not in FUNCTION_WORDS]
        return " ".join(words[:4]).lower()

    def about_this_conversation(self, sentence: str) -> Optional[Tuple[str, str]]:
        """`(who, act)` where the question is about this exchange, else None.

        A question naming a PARTICIPANT and an act of SAYING is asking about
        the conversation, not about the world: `what did I just ask you`,
        `what were we talking about`, `what did you say`. There is exactly one
        structural signal and it is in the sentence -- a speech verb with a
        participant in front of it.

        WHO IS SPEAKING IS WHO STANDS BEFORE THE VERB. `what did I ask you`
        and `what did you tell me` name the same two people in the same words;
        only the order says whose words are being asked for.
        """
        from core.semantics.sentence_machine import tokenize

        if not self.is_question(sentence):
            return None
        words = tokenize(sentence)
        speaker = ""
        for word in words:
            if word in SPEAKER_THEM:
                speaker = "them"
            elif word in SPEAKER_ME:
                speaker = "me"
            elif word in SPEAKER_BOTH:
                speaker = "both"
            elif word in SPEECH_ACTS and speaker:
                # The first speech verb that has a participant ahead of it.
                return speaker, SPEECH_ACTS[word]
        return None

    def _from_the_record(self, who: str, act: str) -> str:
        """Answer about this conversation, out of this conversation.

        NOTHING IS INVENTED AND NOTHING IS FETCHED. If the exchange has not
        happened yet, that is the answer -- a turn this process never saw is
        one it cannot report, and saying so is the honest reply.
        """
        earlier = self._turns
        if not earlier:
            return "Nothing yet — this is the first thing you have said to me."

        if who == "both" or act == "discussed":
            subjects, seen = [], set()
            for turn in reversed(earlier):
                subject = turn.subject.strip()
                if subject and subject not in seen:
                    seen.add(subject)
                    subjects.append(subject)
            if not subjects:
                return "Nothing I could name a subject for yet."
            if len(subjects) == 1:
                return f"We were talking about {subjects[0]}."
            return ("We were talking about " + subjects[0]
                    + ", and before that " + ", ".join(subjects[1:4]) + ".")

        if who == "me":
            spoken = [t for t in earlier if t.reply]
            if not spoken:
                return "I have not said anything yet."
            return "I said: " + spoken[-1].reply

        # who == "them": their own turns, split by whether they asked or told.
        wanted = [t for t in earlier if (t.asked if act == "asked" else not t.asked)]
        if not wanted:
            verb = "asked me anything" if act == "asked" else "told me anything"
            return f"You have not {verb} yet."
        last = wanted[-1]
        verb = "asked" if act == "asked" else "told me"
        answer = f'You {verb}: "{last.said}"'
        if act == "asked" and last.subject:
            answer += f" — that was about {last.subject}."
        return answer

    def recalling(self):
        """The recall running alongside this conversation."""
        if self._recall is None:
            from core.memory.live_recall import LiveRecall
            self._recall = LiveRecall()
        return self._recall

    async def recall(self, sentence: str, limit: int = 3) -> List[str]:
        """What it remembers that bears on this. Blocking; prefer `recalling()`.

        Kept because a caller with nothing else to do while it waits loses
        nothing by waiting, and one test asks for exactly that.
        """
        recall = self.recalling()
        recall.begin(sentence)
        return (await recall.harvest(limit)).texts(limit)

    async def read(self, sentence: str) -> Tuple[Optional[Tuple[str, ...]], str]:
        """A structured reading, where any formalizer can produce one."""
        from core.reasoning.neural_bridge import (DerivedReadingFormalizer,
                                                  DeterministicExtractor,
                                                  FormalizerChain,
                                                  PassthroughFormalizer)

        chain = FormalizerChain([PassthroughFormalizer(), DeterministicExtractor(),
                                 DerivedReadingFormalizer()])
        result = await chain.formalize(sentence, [sentence])
        if not result.succeeded:
            return None, ""
        # EVERY claim the sentence made, not just the first. "the pump is hot
        # and loud" asserts two things; returning one of them is a reading that
        # says less than the sentence did.
        return tuple(result.statements or [result.statement]), result.source

    @staticmethod
    def asked(sentence: str, resolved: Sequence["Resolved"]) -> List["Answer"]:
        """Relations the sentence asks about, matched against what is held.

        `what causes pressure loss` and a concept holding `caused by pipe
        friction` are about the same relation, and answering the QUESTION
        rather than reciting the concept is the difference between replying and
        responding. Matched on stems, over relations already stored -- nothing
        here decides that two relations are the same, only that a word in the
        question and a label on a concept share a stem.
        """
        from core.semantics.sentence_machine import tokenize
        from core.semantics.sentence_reader import SentenceReader

        asked_stems = {w for w in tokenize(sentence) if w not in FUNCTION_WORDS}
        answers: List[Answer] = []

        # WHERE / WHEN / HOW-MANY are answered off a RELATION FAMILY, not by
        # object-word overlap. "where is the cup?" names no object to match --
        # its answer is whatever place-relation the cup stands in ("in the box").
        # The reader parses these to an `open` locative/temporal goal or a `count`
        # goal; here the concrete relation is read off the resolved subject. An
        # honest gap (no such relation held) returns [] and the turn says so --
        # it does not fall through to the object-overlap loop, which would only
        # mis-match. Statements never parse to these kinds, so this is inert
        # unless a question was actually asked.
        goal = SentenceReader()._parse_goal(sentence)
        gkind = (goal or {}).get("kind")
        if gkind == "open" and (goal or {}).get("relation") in ("location", "time"):
            spatial = goal["relation"] == "location"
            family = LOCATIVE_RELATIONS if spatial else TEMPORAL_RELATIONS
            subj_stems = {w for w in tokenize(str(goal.get("subject") or ""))
                          if w not in FUNCTION_WORDS}
            for item in resolved:
                if not item.known:
                    continue
                item_stems = {w for w in tokenize(item.phrase)
                              if w not in FUNCTION_WORDS}
                if subj_stems and not any(same_stem(a, b) for a in subj_stems
                                          for b in item_stems):
                    continue
                for relation, other in item.relations:
                    head = relation.replace("_", " ").split()
                    if head and head[0].lower() in family:
                        # A place takes an article ("in the box"); a time does
                        # not ("at noon", not "at the noon").
                        art = "the " if spatial else ""
                        answers.append(Answer(
                            item.phrase, relation, (str(other),), verdict=None,
                            conclusion=f"the {item.phrase} is {relation} "
                                       f"{art}{str(other).replace('_', ' ')}"))
            return answers
        if gkind == "count":
            target_stems = {stem(w) for w in tokenize(str(goal.get("target") or ""))
                            if w not in FUNCTION_WORDS}
            for item in resolved:
                if not item.known:
                    continue
                for relation, other in item.relations:
                    # The store singularises and underscores an object
                    # ("eight legs" -> `eight_leg`); split it so the numeral and
                    # the counted kind read as their own tokens again.
                    otoks = tokenize(str(other).replace("_", " "))
                    counted = any(t.isdigit() or t in NUMBER_WORDS for t in otoks)
                    on_target = (not target_stems
                                 or any(same_stem(t, ts) for t in otoks
                                        for ts in target_stems))
                    if counted and on_target:
                        answers.append(Answer(
                            item.phrase, relation, (str(other),), verdict=None,
                            conclusion=f"the {item.phrase} {relation} "
                                       f"{str(other).replace('_', ' ')}"))
            return answers

        for item in resolved:
            if not item.known:
                continue

            # A YES/NO QUESTION NAMES THE SUBJECT AND THE OBJECT, NEVER THE
            # RELATION. "is a kestrel a bird" strips to {kestrel, bird}: the
            # relation label is `is`, a function word, so label matching could
            # never fire and the question went unanswered while the store held
            # `kestrel --is--> bird`, admitted seconds earlier. Measured: the
            # reply recited an unrelated memory about arctic terns.
            #
            # Matching the OBJECT answers what was actually asked, and polarity
            # decides the verdict -- so "is a kestrel a fish" against a stored
            # `is not fish` answers NO from evidence rather than from silence.
            #
            # Match against the asked OBJECT, never the SUBJECT. The subject is
            # `item.phrase`; leaving its stem in the match set let a stored
            # relation whose OBJECT resembles the subject answer the wrong
            # question -- "is a salmon a bird?" matched salmon's `is salmonid`
            # because `salmonid` stems to `salmon`, and said "Yes" about `bird`.
            subject_stems = {w for w in tokenize(item.phrase)
                             if w not in FUNCTION_WORDS}
            object_stems = {w for w in asked_stems
                            if not any(same_stem(w, sw) for sw in subject_stems)}
            for relation, other in item.relations:
                if any(same_stem(str(other), word) for word in object_stems):
                    denied = relation.startswith("not ") or relation == "is not"
                    answers.append(Answer(item.phrase, relation, (str(other),),
                                          verdict=not denied))
                    continue

                labels = [part for part in relation.replace("_", " ").split()]
                if any(same_stem(label, word) for label in labels
                       for word in asked_stems):
                    existing = next((a for a in answers
                                     if a.about == item.phrase and a.relation == relation), None)
                    if existing:
                        answers.append(Answer(item.phrase, relation,
                                              existing.others + (other,)))
                        answers.remove(existing)
                    else:
                        answers.append(Answer(item.phrase, relation, (other,)))
        return answers

    @staticmethod
    def _render_atom(text: str) -> str:
        """A logic atom as words: `pressure_loss` -> `pressure loss`; a status
        prefix ("Proved:") stripped. What reasoning concluded, said plainly."""
        rendered = str(text).strip()
        for prefix in ("proved:", "disproved:", "refuted:", "verified:"):
            if rendered.lower().startswith(prefix):
                rendered = rendered[len(prefix):].strip()
                break
        return rendered.replace("->", "implies").replace("_", " ").strip()

    @staticmethod
    def _support_used(premises, steps) -> Tuple[str, ...]:
        """The clean premise SENTENCES a derivation used, for the reply's `because`.

        The reasoner marks the premises it used `[Premise]`, but in the formula
        form it reasons in (`zorbax_glomph -> zorbax_fizzly`), which reads back
        as noise. The premises it was GIVEN are clean sentences ("Every glomph is
        fizzly"), so the used ones are recovered by matching: a premise whose
        content words all appear among the `[Premise]` lines is one the proof
        rested on, and it is cited as it was said rather than as an atom. This
        both keeps the reason readable and keeps it honest -- only premises the
        proof actually used, not everything that happened to be recalled.
        """
        marked = " ".join(str(s) for s in (steps or ()) if "[Premise]" in str(s))
        marked = marked.lower().replace("_", " ")
        seen: set = set()
        out: List[str] = []
        for premise in premises or ():
            words = [w for w in str(premise).lower().split()
                     if w not in FUNCTION_WORDS]
            if words and all(w in marked for w in words) and premise not in seen:
                seen.add(premise)
                out.append(str(premise))
        return tuple(out)

    @staticmethod
    def _grounded(result, support) -> bool:
        """Whether a reasoning result actually DECIDED the proposition, rather
        than reporting a belief that happens to share a word with it.

        Grounded = the concept graph walked a chain for it, OR premises it used
        were cited (`support`). The learned-inference belief path returns a bare
        "P(claim) = x" on word overlap and flags itself `verified`; that is a
        related belief, not a proof of THIS claim, so it is not grounds to assert
        an answer. Keeping this here, at the point a result becomes a spoken
        answer, is where an ungrounded 'verified' would otherwise become a
        fabricated yes/no."""
        if str(getattr(result, "answer", "") or "").startswith("P("):
            return False
        route = (getattr(result, "metadata", None) or {}).get("route") or []
        # concept_graph walked a chain; held_rules PROVED it from taught rules +
        # taught facts (a real Z3 derivation, not a word-overlap belief).
        return bool(support) or ("concept_graph" in route) or ("held_rules" in route)

    @staticmethod
    def _affirmed(answer: str) -> Optional[bool]:
        """Whether the reasoner AFFIRMED the affirmative proposition it was asked.

        The reasoner reports its verdict in the answer text, and a yes/no reply
        must follow THAT verdict — not merely the polarity of the question. A
        stored denial makes the affirmative come back disproved ("No: …" from the
        graph, "Disproved: …" from the solver), and reading only the question's
        polarity would turn that disproof back into a "Yes". Returns True when the
        affirmative holds, False when it is disproved, and None when the reasoner
        did not decide it (so the caller asserts nothing)."""
        text = str(answer or "").strip()
        if text.startswith(("Proved", "Yes", "Entailed")):
            return True
        if text.startswith(("Disproved", "No:", "No ", "No,")):
            return False
        # "Not entailed …", "Undecided …", anything else: no decision.
        return None

    async def _held_premises(self, sentence, resolved, harvest) -> List[str]:
        """Everything the substrate HOLDS about the topic, as premise sentences.

        There is no separate 'look it up' step that reasoning falls back from:
        what is held is simply what reasoning reasons over, and a stored fact is
        a premise that proves its question in one step. Four sources, together:

          * the resolved concepts' own relations ("flerm is blorp"),
          * ONE HOP OUT -- the relations of the concepts those point to
            ("blorp is snazzy"), because "is flerm snazzy" follows from a chain
            the question never names the middle of,
          * the subject-focused recalled memories (`harvest`),
          * a BROAD recall on the whole question -- a syllogism's rule ("every
            blorp is snazzy") shares a term with the question but not its
            subject, so the subject-focused harvest misses it; this finds the
            premises the chain needs.

        One hop, not the whole graph: enough to chain a stated rule to a stated
        fact without pulling the entire store in as premises.
        """
        premises: List[str] = []
        others: set = set()
        for item in resolved:
            if not getattr(item, "known", False):
                continue
            for relation, other in item.relations:
                premises.append(f"{item.phrase} {relation} {other}")
                others.add(str(other))
            # Incoming relations: facts that name THIS concept as their object,
            # for reverse questions ("what causes X") the forward store misses.
            premises.extend(await self._incoming_relations(item.phrase))

        # One hop out, following each relation to the concept it names.
        for other in others:
            try:
                hops = await self.resolve(other)
            except Exception:
                continue
            for hop in hops:
                if not getattr(hop, "known", False):
                    continue
                for relation, o2 in hop.relations:
                    premises.append(f"{hop.phrase} {relation} {o2}")

        if harvest is not None:
            premises.extend(harvest.texts())

        # Broad recall on the whole question, for the premises a chain needs that
        # the subject never names. Recall hands back each memory's clean claim.
        try:
            from core.memory import get_memory_agent
            agent = await get_memory_agent()
            _ok, hits = await agent.search_memories(
                query=str(sentence), limit=8, include_events=False)
            for hit in (hits or []):
                meta = getattr(hit, "metadata", None) or {}
                claim = (meta.get("conclusion") if isinstance(meta, dict) else None) \
                    or getattr(hit, "content", "")
                if claim:
                    premises.append(str(claim))
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(error, "autonomous_coordinator._held_premises.broad_recall")

        return list(dict.fromkeys(p.strip() for p in premises if p and p.strip()))

    async def _reasoned_answers(self, sentence, resolved, harvest) -> List["Answer"]:
        """Answers the substrate DERIVES from what it holds.

        Not a fallback for a failed lookup -- a first-class peer that runs over
        the held premises whether or not a stored relation already answered, so
        "is X fizzly" follows from "X is a glomph" and "every glomph is fizzly",
        and "what causes X" is answered by the cause that entails it. An answer
        is returned ONLY when the substrate PROVES one; the premises it used are
        carried so the reply can say why.

        A copula yes/no question is decided on its AFFIRMATIVE proposition and
        answered against the polarity it was asked in -- so "is X not Y" is
        answered by whether X IS Y. Every other form (subject-verb-object,
        causal, open "what/why") is handed to the reasoner as-is; it formalises
        the query and derives the conclusion.
        """
        from core.reasoning.neural_bridge import (ReasoningRequest,
                                                  get_neural_bridge)
        from core.semantics.sentence_reader import SentenceReader
        bridge = get_neural_bridge()

        premises = await self._held_premises(sentence, resolved, harvest)

        # ACTION YES/NO — "does the tank overflow?". SentenceReader reads the
        # auxiliary correctly,
        # and the reasoner decides it over HELD RULES + HELD FACTS pulled from
        # their own authorities — so a taught rule ("if the valve is closed then
        # the tank overflows") firing on a taught fact ("the valve is closed")
        # answers it. This runs BEFORE the premises guard because the answer can
        # come from a rule even when the subject holds no stand-alone fact.
        _sr = SentenceReader()
        _goal = _sr._parse_goal(sentence)
        if _goal and _goal.get("kind") in ("sv", "svo"):
            result = await bridge.reason(ReasoningRequest(
                query=sentence, context=premises,
                task_metadata={"actor": self._actor}))
            if not (result.metadata or {}).get("verified") or not result.answer:
                return []
            chain = (result.metadata or {}).get("chain") or []
            support = ((" → ".join(chain),) if len(chain) >= 2
                       else self._support_used(premises, result.reasoning_steps))
            if not self._grounded(result, support):
                return []
            affirmed = self._affirmed(result.answer)
            if affirmed is None:
                return []  # reasoner did not decide it — assert nothing
            parts = _sr.clause_parts(_goal) or {}
            claim = (chain[-1] if chain else " ".join(
                str(p) for p in (parts.get("subject"), parts.get("relation"),
                                 parts.get("obj")) if p))
            # An action question is affirmative, so its verdict IS whether the
            # action holds; polarity flipping is only for copular "is X not Y".
            verdict = affirmed if parts.get("positive", True) else (not affirmed)
            return [Answer(about=str(parts.get("subject") or ""),
                           relation=str(parts.get("relation") or ""),
                           others=((str(parts["obj"]),) if parts.get("obj") else ()),
                           verdict=verdict, support=support, conclusion=claim)]

        if not premises:
            return []

        # Read the question with the ONE reader (sentence_reader, `_sr` above): a
        # yes/no "is X (a) Y?" yields (subject, object, polarity); anything else
        # yields nothing and drops to the open branch below.
        _g = _sr._parse_goal(sentence)
        _cp = _sr.clause_parts(_g) if _g else None
        reading = ((_cp["subject"], _cp["obj"],
                    "affirms" if _cp.get("positive", True) else "denies")
                   if _cp and _cp.get("obj") else None)

        # A WH-question ("what/why/how/who causes X") is OPEN, not a yes/no about
        # a subject named "what" -- the reader can mis-parse it as a copula, so it
        # is sent to the open branch where the reasoner derives the answer.
        _WH = {"what", "why", "how", "who", "when", "where", "which"}
        if reading and reading[0].lower() not in _WH:
            subject, obj, polarity = reading
            result = await bridge.reason(ReasoningRequest(
                query=f"{subject} is {obj}", context=premises,
                task_metadata={"actor": self._actor}))
            if not (result.metadata or {}).get("verified"):
                return []
            # Prefer the reasoning's OWN chain (robin → bird → … → animal) as the
            # reason, so a derived yes/no says the hops it walked. Falls back to
            # the premise-citation matching for reasoners that mark premises.
            chain = (result.metadata or {}).get("chain") or []
            if len(chain) >= 2:
                support = (" → ".join(chain),)
            else:
                support = self._support_used(premises, result.reasoning_steps)
            # GROUNDING GUARD. A yes/no verdict must rest on the substrate's OWN
            # knowledge of THIS proposition — a concept-graph chain or premises it
            # actually used. The belief path reports `verified` when a stored
            # belief merely SHARES A WORD with the query ("animal"), which is not
            # grounds to assert X IS Y. Ungrounded ⇒ no verdict: the turn reports
            # the gap honestly instead of a fabricated yes.
            if not self._grounded(result, support):
                return []
            # FOLLOW THE REASONER'S VERDICT, not just the question's polarity. The
            # affirmative "X is Y" may have been PROVED or DISPROVED (a stored
            # denial disproves it); a yes/no must reflect which. Reading polarity
            # alone would turn a disproof back into a "Yes".
            affirmed = self._affirmed(result.answer)
            if affirmed is None:
                return []  # the affirmative was neither proved nor disproved
            claim = f"{subject} is {obj}".replace("_", " ")
            # "Yes" iff (affirmative holds) matches how the question asked it:
            # affirmed + affirming question, or disproved + denying question.
            verdict = (affirmed == (polarity == "affirms"))
            return [Answer(about=subject, relation="is", others=(obj,),
                           verdict=verdict,
                           support=support, conclusion=claim)]

        result = await bridge.reason(ReasoningRequest(
            query=sentence, context=premises,
            task_metadata={"actor": self._actor}))
        if not (result.metadata or {}).get("verified") or not result.answer:
            return []
        support = self._support_used(premises, result.reasoning_steps)
        # Same grounding guard for an open question: a word-overlap belief (its
        # answer is a bare "P(claim) = x") is not an answer to "what is X".
        if not self._grounded(result, support):
            return []
        return [Answer(about="", relation="", others=(), verdict=None,
                       support=support, conclusion=self._render_atom(result.answer))]

    # ---- the two ways something new gets in ------------------------------

    async def _ingest(self, label, description, relations, source_type, source_id,
                      content, domain) -> Acquired:
        """Hand the interpreted statement to the ingress. It admits, not this.

        This used to build its own EvidenceEnvelope and call the ingestion
        service directly, under a docstring calling itself "the only write
        path" -- a second claimant to a job that already had an owner. It also
        read `result.concepts` / `.concept_ids` / `.accepted` off the returned
        IngestionResult, none of which are fields on it, so `stored` was False
        on every successful write. Every sentence anyone taught reported back
        as not stored while the row went in.
        """
        from core.semantics.cognitive_ingress import Provenance

        if not relations:
            return Acquired(label, description, (), source_id, False,
                            "nothing was said about it")

        relation, obj = relations[0][0], relations[0][1]
        positive = len(relations[0]) < 3 or str(relations[0][2]) != "negative"

        # THROUGH THE LEARNING AUTHORITY, not around it. `learn_fact` admits to
        # the concept graph AND fans the learning out to beliefs, the lexicon,
        # the domain (via the emitter), memory, and metrics — the one path every
        # kind of learning takes, so nothing here reaches the ingress directly.
        # actor = THIS speaker. A told fact is the speaker's CONTEXT, not world
        # knowledge, until independently corroborated — so it moves a scoped
        # belief, never the one shared mind directly (the learning authority's
        # intake router enforces this on the actor). The session is the speaker
        # handle today; a first-class World Auth identity refines it without
        # moving the store.
        admission = await self._learning_authority().learn_fact(
            subject=label, relation=relation, obj=obj, positive=positive,
            surface=content,
            provenance=Provenance(producer="conversation", source_id=source_id,
                                  source_type=source_type.name),
            description=description, domain=domain, emit=self._evidence_emitter(),
            actor=self._actor)

        detail = "; ".join(admission.refusals)
        if admission.contradicts:
            detail = (f"this contradicts what I was told before"
                      f"{'; ' + detail if detail else ''}")

        # ONE SHAPE FOR EVERY READER. `relations` arrives from the reader as
        # (relation, object) or (relation, object, polarity), and `Acquired`
        # declares Tuple[Tuple[str, str], ...]. `say()` unpacked exactly two and
        # raised ValueError on any taught sentence carrying polarity -- which,
        # since admit_relation records polarity, is every taught sentence. The
        # polarity is folded into the relation here, the same way `resolve()`
        # does it, so a negative survives instead of crashing the reply.
        return Acquired(label, description, _as_pairs(relations), source_id,
                        admission.admitted, detail,
                        memory_id=admission.memory_id)

    async def _register_domain_gap(self, sentence: str, resolved):
        """Register an unanswered in-domain question as a known-unknown --
        THROUGH the domain authority, not around it.

        A question resolved to a concept that lives in a crystallized SUBJECT
        domain (not the `conversation`/`researched` channels or the `general`
        catch-all), which produced no answer, is a localized declarative gap:
        the substrate has little information HERE, not lacking the operators to
        act here. This routes it to `UniversalDomainMaster.detect_knowledge_gap`,
        the owner of domain-scoped gap detection -- it used to reach past that
        into `register_known_unknown` with a coarser inline version, a bypass of
        the very method this docstring named. The authority does the precise
        check (subject IS a concept of the domain, the asked relation is genuinely
        absent) and records the structured `required_info` an acquisition step
        can act on, competence untouched -- a knowledge gap is never a competence
        loss. Returns the domain_id it registered under, or None.

        The RELATION asked about comes from the reader (a WH question reads as
        subject + relation + <unknown>). Without a relation there is nothing to
        localize, so nothing is registered -- honest, not a coarse catch-all.
        """
        from core.domain.domain_registry import get_domain_registry
        from core.integration.universal_domain_master import \
            get_universal_domain_master
        from core.semantics.sentence_reader import SentenceReader

        # The RELATION comes from the ONE reader. A question it can read yields
        # (subject, relation, object); one it cannot yields nothing, and with no
        # relation there is nothing to localize -- honest, no guess.
        _sr = SentenceReader()
        goal = _sr._parse_goal(sentence)
        parts = _sr.clause_parts(goal) if goal else None
        relation = (str(parts.get("relation")).strip().lower()
                    if parts and parts.get("relation") else None)
        if not relation:
            return None

        registry = get_domain_registry()
        udm = get_universal_domain_master()
        channels = {"conversation", "researched", "general", ""}
        for item in resolved:
            if not getattr(item, "known", False):
                continue
            field = (getattr(item, "domain", "") or "").strip().lower()
            if field in channels:
                continue
            domain_id = f"domain_{field}"
            if domain_id not in registry.domains:
                continue
            gap = await udm.detect_knowledge_gap(
                domain_id, subject=item.phrase, relation=relation)
            if gap is not None:
                return domain_id
        return None

    async def _resolves(self, text: str) -> bool:
        _, identity = await self._services()
        return bool(await identity.resolve_query(text.replace("_", " "))
                    or await identity.resolve_query(text))

    # retain() REMOVED. Retention is not the reader's job.
    #
    # It was briefly added here, which made the interpreter also the thing that
    # decided what the system keeps -- two responsibilities in one place, and
    # the second one silently optional. A sentence is interpreted here and
    # admitted in exactly one place: core.semantics.cognitive_ingress.

    async def teach(self, sentence: str) -> List[Acquired]:
        """You told it something. Read it with the ONE reader, then admit.

        The reader is `sentence_reader` -- the SAME reader the query path uses,
        so a fact taught reads the same way it does when later asked about, and a
        multi-word subject ("the Klein four-group is an abelian group") is read
        identically on both sides. It never guesses at a sentence it cannot read:
        a sentence that does not read has told you nothing, and admitting a guess
        about it is worse than admitting nothing.
        """
        from core.domain.concept_ingestion import EvidenceSourceType

        # A CONDITIONAL is a held RULE, not a relation: it is read by the sentence
        # reader and learned as a held RULE, and admit_relation would wrongly assert
        # its antecedent true.
        # It is read by the sentence reader and learned as a held RULE through the
        # LEARNING AUTHORITY (`learn_rule`), the same one door a fact takes — so a
        # rule fans out to the lexicon, beliefs, the domain, and metrics exactly
        # as a fact does, instead of this reaching into the ingress directly.
        from core.semantics.sentence_reader import SentenceReader as _SentenceReader
        from core.semantics.cognitive_ingress import Provenance as _Provenance
        _sr = _SentenceReader()
        _cond = _sr._parse_statement(sentence)
        if _cond is not None and _cond.get("kind") == "conditional":
            ant = _sr.clause_parts(_cond["antecedent"])
            con = _sr.clause_parts(_cond["consequent"])
            if not ant or not con:
                return [Acquired(sentence, detail=(
                    "I read that as a conditional, but a side of it is not a "
                    "single proposition I can hold"))]
            admission = await self._learning_authority().learn_rule(
                ant, con, surface=sentence,
                provenance=_Provenance(producer="conversation", source_id="you",
                                       source_type=EvidenceSourceType.USER_SUPPLIED.name),
                domain="conversation", emit=self._evidence_emitter(),
                actor=self._actor)
            if admission.admitted:
                return [Acquired(sentence, description="a rule", relations=(),
                                 stored=True, detail="held as a conditional rule",
                                 memory_id=admission.evidence_id)]
            return [Acquired(sentence, detail=("; ".join(admission.refusals)
                             or "I could not hold that conditional"))]

        # A sentence may carry MORE THAN ONE proposition -- a relative clause
        # ("the okapi, which is a mammal, is a herbivore") or a conjunction ("the
        # vault is cold and heavy") states two -- so `read_all` returns every
        # proposition it can read (already dropping any it cannot), and each is
        # admitted, not just the first.
        readings = _sr.read_all(sentence)
        if not readings:
            return [Acquired(sentence, detail=(
                "I could not read that sentence with what I have been taught "
                "about sentences"))]

        acquired: List[Acquired] = []
        for part in readings:
            obj = part.get("obj")
            if not obj:
                continue  # an intransitive reading (subject + verb) forms no edge
            rel = str(part.get("relation") or "").strip().lower()
            # A copular predication is an ISA edge -- stored TYPED (`isa`) so the
            # graph carries kind semantics (transitivity), not an undifferentiated
            # "is" that poisons inference; any other relation keeps its own name.
            relation = "isa" if rel in ("is", "are") else rel
            positive = part.get("positive", True)
            # THIRD CHANNEL: if the speaker is telling the substrate about
            # THEMSELVES, this is a belief about the user, not a fact about the
            # world. Route it to the user store and do NOT admit it to the concept
            # graph — chat about oneself must never rewrite world knowledge.
            if self._about_speaker(part["subject"]):
                acquired.append(await self._learn_about_user(
                    part["subject"], relation, obj, positive=positive,
                    surface=sentence))
                continue
            # VERIFICATION GATE: a world fact asserted in chat is checked against
            # what the substrate already knows before it is admitted. One it knows
            # to be false is refused, so chat cannot overwrite world knowledge.
            _ok, _why = await self._admissible_world_fact(
                part["subject"], relation, obj, positive)
            if not _ok:
                acquired.append(Acquired(sentence, detail=(
                    f"I did not take that as a fact — {_why}. If I am wrong, "
                    "correct me and I will weigh it.")))
                continue
            acquired.append(await self._ingest(
                label=part["subject"], description="",
                relations=((relation, obj,
                            "positive" if positive else "negative"),),
                source_type=EvidenceSourceType.USER_SUPPLIED, source_id="you",
                content=sentence, domain="conversation"))
        return acquired


    async def look_up(self, phrase: str) -> Optional[Acquired]:
        """Research a genuine gap, at most ONCE across the whole substrate for a
        given phrase in flight at the same time.

        The substrate is ONE self behind many conversations (up to
        MAX_HELD_CONVERSATIONS sessions, one per speaker/thread). When a crowd
        asks about the same unknown at once -- 100 people on a shared deployment
        hitting a domain none of them has -- each session's `understand` would
        otherwise fire its own identical web research and its own identical write
        to the shared store: a thundering herd on the network and a race to
        `_ingest` the same fact. This collapses that to a single-flight: the
        first caller does the real research (`_research_phrase`) and EVERY
        concurrent caller for the same normalised phrase awaits that one result.
        The finding is written once, then shared; the next turn is answered from
        the store, not researched again. The key is the research key only -- it
        dedups WHILE a lookup is in flight, not a cache across time (a later ask
        re-verifies, which is correct; the world changes)."""
        from core.semantics.cognitive_ingress import normalize_term

        key = normalize_term(phrase) or phrase.strip().lower()
        existing = _LOOKUPS_INFLIGHT.get(key)
        if existing is not None:
            # Piggyback on the in-flight research -- no second web call, no second
            # write. (No await between the get above and the create below, so the
            # check-and-set is atomic under the event loop: exactly one owner.)
            return await existing
        fut: "asyncio.Future[Optional[Acquired]]" = asyncio.get_running_loop().create_future()
        _LOOKUPS_INFLIGHT[key] = fut
        try:
            result = await self._research_phrase(phrase)
            fut.set_result(result)
            return result
        except BaseException as error:
            fut.set_exception(error)
            raise
        finally:
            _LOOKUPS_INFLIGHT.pop(key, None)
            # If the research failed and no concurrent caller piggybacked on this
            # future, its exception would otherwise be flagged "never retrieved".
            # The owner already re-raised the real error above; retrieve the
            # future's copy here so it is accounted for either way.
            if fut.done() and not fut.cancelled() and fut.exception() is not None:
                pass

    async def _research_phrase(self, phrase: str) -> Optional[Acquired]:
        """It did not know the word. Go and find out on the WEB, now, and READ
        what is found into a fact.

        A word the substrate could know from a lexical database it already knows:
        the whole of WordNet is taught into the concept store, so the taxonomy is
        consulted directly, not through a tool. `look_up` is therefore the path
        for a GENUINE gap -- a word the store does not hold -- and a genuine gap
        is answered by real research whose finding is READ into a classification
        and admitted through the learning authority, so the next question about
        it is answered from the store.

        It reads through the ONE web_search tool (which fetches the top page's
        clean text), not a search-snippet API: a snippet is truncated glue that
        does not read into a fact, which is why this used to pass NO relation to
        `_ingest` and therefore never actually learned -- it stored a description
        nobody could later reason over. Now it reads the fetched lead into
        `subject isa <class>` and admits THAT.
        """
        import re as _re

        from core.domain.concept_ingestion import EvidenceSourceType
        from core.semantics.cognitive_ingress import admissible, normalize_term
        from core.semantics.sentence_reader import SentenceReader
        from core.tools import get_tool_registry

        registry = get_tool_registry()

        try:
            result = await registry.execute_tool(
                "web_search", {"query": f"what is {phrase}", "max_results": 5})
        except Exception as error:
            return Acquired(phrase, origin="research", detail=f"research failed: {error}")
        if not getattr(result, "success", False):
            return Acquired(phrase, origin="research",
                            detail=f"research declined: {getattr(result, 'error', '')}")

        output = getattr(result, "output", None) or {}
        hits = output.get("results") if isinstance(output, dict) else None
        if not hits:
            return Acquired(phrase, origin="research",
                            detail="research returned nothing that describes it")

        # THE FIRST HIT IS NOT AN ANSWER, IT IS THE CLOSEST THING THE INDEX HAD.
        # A page is about the phrase when its TITLE names the phrase -- every
        # content word, by stem. Taking the top row unchecked once stored an
        # article on animal behaviour as the meaning of "spots unusual behaviour
        # in data"; a wrong fact written to the store is indistinguishable
        # afterwards from a learned one. So: the first title-matching page, and
        # from its clean lead the first classification whose subject IS the
        # phrase. Where nothing passes, it declines honestly and the reply asks.
        want = normalize_term(phrase)
        reader = SentenceReader()
        for hit in hits:
            if not _titles(phrase, hit.get("title", "")):
                continue
            content = hit.get("content") or hit.get("snippet") or ""
            if not content:
                continue
            # A definitional lead wedges a parenthetical (an IPA gloss, a
            # portmanteau note) between the subject and its "is a ...":
            # "A memristor ( ... ) is a component". Strip parentheticals so the
            # classification reads. Read the lead sentence first -- the defining
            # one -- then the whole page if the lead did not parse.
            clean = _re.sub(r"\([^()]*\)", " ", content)
            lead = _re.split(r"(?<=[.!?])\s+", clean.strip(), maxsplit=1)[0]
            fact = None
            for span in (lead, clean):
                fact = next(
                    (f for f in reader.read_all(span)
                     if f.get("obj")
                     and str(f.get("relation", "")).lower() in ("is", "are", "isa")
                     and normalize_term(f["subject"]) == want), None)
                if fact is not None:
                    break
            if fact is None:
                continue
            # The store holds NAMES, not clauses: a definitional NP off the web
            # ("a non-linear two-terminal electrical component") is longer than a
            # name may be. Reduce it to the WIDEST head-ward class the store will
            # admit -- deferring to `admissible`, the shape authority, rather than
            # guessing the cap -- so the genus is kept ("electrical component")
            # and only the differentia the store cannot hold is dropped. A short
            # class ("an abelian group") is already admissible and passes whole.
            obj = re.sub(r"(?i)^(?:a|an|the)\s+", "", str(fact["obj"])).strip()
            words = obj.split()
            klass = next((" ".join(words[i:]) for i in range(len(words))
                          if admissible(normalize_term(" ".join(words[i:])))[0]), None)
            if not klass:
                continue
            source = hit.get("url") or "research"
            description = lead.strip()[:400] or content[:400]
            return await self._ingest(
                label=phrase, description=description,
                relations=[("isa", klass)],
                source_type=EvidenceSourceType.RESEARCH_FINDING,
                source_id=source, content=description, domain="researched")

        return Acquired(phrase, origin="research",
                        detail="research returned nothing that describes it")

    @staticmethod
    def is_question(sentence: str) -> bool:
        """Whether this asks, by the shape of the sentence alone.

        Cheap, model-free, and certain in both directions where a question mark
        or an opening question word settles it.
        """
        from core.semantics.sentence_machine import tokenize

        if sentence.strip().endswith("?"):
            return True
        words = tokenize(sentence)
        return bool(words) and words[0] in QUESTION_OPENERS

    def _read_disposition(self) -> Optional[Dict[str, Any]]:
        """The self's current disposition, read from the coordinator that owns
        this conversation, so a reply can be informed by self-state. Returns a
        small QUALITATIVE view (the directive's mode word + whether the self is
        inclined to explore) -- never numbers beside a feeling. None when the
        conversation is standalone or the read fails: the reply is then exactly
        what it was, never a fabricated mood."""
        if self._disposition is None:
            return None
        try:
            directive = self._disposition()
        except Exception as error:
            logger.debug("disposition read unavailable: %s", error)
            return None
        return {"mode": getattr(directive, "mode", None),
                "explore": bool(getattr(directive, "should_explore", False))}

    def _feedback_referent(self) -> Optional["Turn"]:
        """The recent turn a verdict is about: the most recent one, within a
        small window, that actually admitted a memory. A verdict with nothing to
        judge is not feedback, so this returning None is what stops an
        evaluative-looking utterance with no referent from being treated as one.
        Bounded look-back -- never the whole history."""
        window = list(self._turns)[-_FEEDBACK_WINDOW:]
        for turn in reversed(window):
            if turn.memories:
                return turn
        return None

    def feedback_of(self, sentence: str) -> Optional[bool]:
        """Whether this utterance is FEEDBACK on what was just taught, and its
        verdict: True confirms, False corrects, None is not feedback. Feedback is
        a verdict ON A PRIOR CLAIM, so both halves must hold -- the reader reads
        the utterance as a bare evaluative verdict (structural, model-free), AND
        there is a recent turn that left a memory to judge. Same certainty as
        is_question, plus a referent to attach to; without the referent an
        evaluative shape is just an ordinary short statement and is left alone."""
        from core.semantics.sentence_machine import evaluative_verdict

        verdict = evaluative_verdict(sentence)
        if verdict is None:
            return None
        if self._feedback_referent() is None:
            return None
        return verdict

    async def _take_feedback(self, sentence: str, verdict: bool) -> "Understanding":
        """A verdict on what was just taught. The claim already made a memory;
        this FLAGS that memory (annotated, never overwritten) and hands the
        verdict to the learning authority -- it does NOT store the verdict as a
        new fact, which is what filing it through teach() would have done. The
        authority owns what learning follows; this only routes the signal and
        replies."""
        referent = self._feedback_referent()
        flagged = 0
        if referent is not None:
            authority = get_learning_authority()
            for memory_id in referent.memories:
                try:
                    outcome = await authority.learn_from_feedback({
                        "memory_id": memory_id,
                        "success": verdict,          # True confirms, False corrects
                        "content": sentence,
                        "about": referent.said,
                    })
                    if outcome and outcome.get("memory_flagged"):
                        flagged += 1
                except Exception as error:
                    logger.warning("feedback routing failed for %s: %s",
                                   memory_id, error)

        understanding = Understanding(sentence=sentence, asked=False)
        if verdict:
            understanding.reply = ("Understood — noted as confirmed." if flagged
                                   else "Understood.")
        else:
            understanding.reply = ("Understood — I've marked that as corrected."
                                   if flagged else
                                   "Understood, though I have no stored claim from "
                                   "that to correct.")
        self._last_reply = understanding.reply
        # The verdict itself is not a new claim about the world, so it admits no
        # memory of its own -- recorded as a turn for continuity, with none.
        self._turns.append(Turn(said=sentence, asked=False,
                                subject=self._last_subject,
                                reply=understanding.reply, memories=()))
        return understanding

    async def classify(self, sentence: str) -> str:
        """`question`, `telling` or `job` — decided HERE by the substrate's own
        reader, with no model.

        THIS WAS DECIDED TWICE. The coordinator asked a model, this asked a rule,
        and they disagreed: `a quorum sensor detects bacterial population density`
        is plainly a statement, the model called it a question, and it was filed
        in memory as `Asked: a quorum sensor detects...`. Two owners of one
        question produce two answers. Now there is ONE owner and NO model:

          - a QUESTION is structural (`is_question`);
          - a TELLING states a fact — a declarative the model-free `SentenceReader`
            reads as a statement (copular / universal / conditional / SVO whose
            verb the lexicon knows);
          - a JOB asks for work — anything that is neither a question nor a
            readable statement of fact. Where the reader cannot read a sentence
            as a fact, that sentence has not TOLD the substrate anything, so it is
            treated as work. This is the reader's honest structural verdict, never
            a guess and never a model.
        """
        if self.is_question(sentence):
            return "question"

        from core.semantics.sentence_reader import SentenceReader
        statement = SentenceReader()._parse_statement(sentence)
        return "telling" if statement is not None else "job"

    async def understand(self, sentence: str, look_up: bool = True) -> Understanding:
        # ASKED ABOUT THIS EXCHANGE, ANSWERED FROM THIS EXCHANGE. Checked first
        # because every path below treats the sentence as being about the
        # world: it would file `just ask` as an unresolved concept, research
        # it, and store what it found. The record answers this; nothing else
        # can, and nothing else should be consulted.
        self_reference = self.about_this_conversation(sentence)
        if self_reference is not None:
            who, act = self_reference
            understanding = Understanding(sentence=sentence, asked=True)
            understanding.reply = self._from_the_record(who, act)
            # The subject does NOT move. Asking what we were talking about is
            # not a new subject -- it is a question about the old one, and
            # letting it become the subject would strand everything recall has
            # accumulated under the topic the conversation is still on.
            self._turns.append(Turn(said=sentence, asked=True,
                                    subject=self._last_subject,
                                    reply=understanding.reply))
            self._last_reply = understanding.reply
            return understanding

        # A VERDICT ON WHAT WAS JUST TAUGHT, ANSWERED AS ONE. Checked before the
        # telling path below, because that path would file "no, that's wrong" as
        # a new fact about the world -- storing the correction as though it were
        # a claim. Feedback is a verdict on the memory the last turn already
        # made: it flags that memory and goes to the learning authority, it does
        # not become a concept. Only fires when there is a recent taught memory
        # to judge (feedback_of returns None otherwise).
        verdict = self.feedback_of(sentence)
        if verdict is not None:
            return await self._take_feedback(sentence, verdict)

        # WAVE 1 GOES OUT BEFORE ANYTHING ELSE HAPPENS. Everything below --
        # storing what was said, resolving concepts, researching a word --
        # takes time recall can use rather than time it has to wait for.
        recall = self.recalling()
        recall.carry_over()
        # THE SUBJECT IS WHAT CONTINUITY HANGS ON. Not the session: a
        # conversation moves between things and comes back, and what was
        # accumulated about the first thing has to still be there -- and must
        # not turn up ranked highly under the second.
        subject = self.subject_of(sentence)
        # A SUBJECT NAMED IN THE LAST ANSWER IS ONE THIS ANSWER LED TO. Being
        # told pipe friction causes pressure loss and then asking about pipe
        # friction is following the thread, not leaving it.
        came_from = self._last_subject if self._leads_on(sentence) else ""
        recall.begin(sentence, about=subject, arose_from=came_from)

        asked = self.is_question(sentence)
        acquired: List[Acquired] = []

        if not asked:
            # TOLD, not asked. Store it before answering, so the reply is made
            # out of a store that already contains what was just said.
            acquired = await self.teach(sentence)

            # A CONDITIONAL was held as a RULE, not a fact. Say so and stop:
            # resolving the rule sentence as if its words were concepts to look
            # up produces noise ("I hold nothing for: if, then, ...") and, worse,
            # reads as if the antecedent had been asserted. The rule is held; the
            # reply reflects exactly that.
            if any(a.stored and "conditional rule" in (a.detail or "")
                   for a in acquired):
                understanding = Understanding(sentence=sentence, asked=False,
                                              acquired=acquired)
                understanding.reply = "Noted — I'll hold that as a rule."
                self._turns.append(Turn(said=sentence, asked=False,
                                        subject=self._last_subject,
                                        reply=understanding.reply))
                self._last_reply = understanding.reply
                return understanding

        resolved = await self.resolve(sentence)

        # WAVE 2: what the words turned out to be is a better query than the
        # words were, and it did not exist until now. It may also name the
        # subject better than the raw sentence did.
        informative = [item.phrase for item in resolved if item.informative]
        if informative:
            # What it turned out to be replaces what it looked like, and takes
            # everything already gathered with it.
            recall.rename_subject(subject, informative[0])
            if came_from:
                recall.begin(about=informative[0].lower(), arose_from=came_from)
            subject = informative[0].lower()
        recall.refine(*informative, about=subject)

        if asked and look_up:
            # DID NOT KNOW IS NOT AN ANSWER. Find out, in this turn -- but for
            # ONE thing, the longest phrase it could not place. Researching
            # every stray word turns a question into a pile of disambiguation
            # pages, which is what it did before this.
            candidates = sorted((r for r in resolved if not r.known),
                                key=lambda r: len(r.phrase.split()), reverse=True)
            accounted = {stem(part) for item in resolved if item.known
                         for relation, _ in item.relations
                         for part in relation.replace("_", " ").split()}
            target = next((c for c in candidates
                           if not any(same_stem(c.phrase, a) for a in accounted)), None)
            if target is not None:
                learned = await self.look_up(target.phrase)
                if learned is not None:
                    acquired.append(learned)
                if learned is not None and learned.stored:
                    resolved = await self.resolve(sentence)

        answers = self.asked(sentence, resolved)
        # WAVE 3: the relation actually asked about, which is the most specific
        # thing the turn ever learns.
        recall.refine(*[f"{a.about} {a.relation}" for a in answers], about=subject)

        reading, source = await self.read(sentence)
        harvest = await recall.harvest(about=subject, claim=sentence)

        # REASON OVER WHAT IS HELD, as a first-class peer to the direct lookup
        # above -- NOT a fallback gated on it having failed. Whatever the store
        # answered directly, the substrate also derives what FOLLOWS from what it
        # holds (concept relations and recalled memory alike); the two are merged,
        # and a derived answer that duplicates a direct one is dropped for it.
        if asked:
            direct = {(a.about, a.relation, tuple(a.others)) for a in answers}
            for derived in await self._reasoned_answers(sentence, resolved, harvest):
                if (derived.about, derived.relation, tuple(derived.others)) not in direct:
                    answers.append(derived)

        # A KNOWLEDGE GAP DETECTED FROM THE QUESTION ITSELF. A question about a
        # subject the substrate HOLDS (resolved) and that lives in a crystallized
        # subject domain, yet which nothing held could answer, is the substrate
        # having little information HERE -- not lacking the operators to act here.
        # Register it as a domain-scoped known-unknown (competence untouched), so
        # "I don't hold that fact yet" is a tracked, resolvable state rather than a
        # silent miss. Isolated: never breaks the reply.
        if asked and not answers:
            try:
                await self._register_domain_gap(sentence, resolved)
            except Exception as error:
                logger.debug("domain knowledge-gap registration skipped: %s", error)

        understanding = Understanding(
            sentence=sentence, resolved=resolved, reading=reading,
            reading_source=source, answers=answers,
            acquired=acquired, asked=asked,
            remembered=harvest.texts(), recall=harvest,
            disposition=self._read_disposition())
        understanding.reply = self.say(understanding)
        self._last_subject, self._last_reply = subject, understanding.reply
        # The memories this telling admitted, kept on the turn so the NEXT turn's
        # feedback can flag them. `acquired` is [] for a question.
        admitted_memories = tuple(
            a.memory_id for a in acquired if getattr(a, "memory_id", None))
        self._turns.append(Turn(said=sentence, asked=asked, subject=subject,
                                reply=understanding.reply,
                                memories=admitted_memories))
        return understanding

    @staticmethod
    def _article(word: str) -> str:
        w = str(word).strip().lower()
        return "an" if w[:1] in "aeiou" else "a"

    #: Copular relations render as "a X is a Y" — the polarity is carried by the
    #: yes/no, so a denial's CLAIM is still the affirmative it denies.
    _COPULA_RELATIONS = ("not isa", "is not", "isa", "is", "are", "was", "were",
                         "be", "has property", "instance of")

    @classmethod
    def _natural_claim(cls, text: str) -> str:
        """A stored claim as a plain AFFIRMATIVE phrase. A copular relation
        (is/isa/has_property, and their negated forms) renders "a X is a{n} Y"
        with the articles a person says; a verb or multi-word claim is left as
        prose. Negation is dropped here because the yes/no already carries it."""
        t = str(text).replace("_", " ").strip()
        rels = "|".join(re.escape(r) for r in cls._COPULA_RELATIONS)
        m = re.fullmatch(rf"([\w'-]+)\s+(?:{rels})\s+(.+)", t)
        if m:
            subj, obj = m.group(1), m.group(2).strip()
            # Article from the object's first word, so "living thing" reads
            # "a living thing" rather than a bare "living thing".
            return (f"{cls._article(subj)} {subj} is "
                    f"{cls._article(obj.split()[0])} {obj}")
        return t

    @classmethod
    def natural_reply(cls, understanding: "Understanding") -> Optional[str]:
        """A plain, user-facing reply: the verdict and the claim, NO derivation
        chain. `say()` shows the reasoning (robin → bird → animal), which is
        right for introspection but reads as debug output to a person — a user
        request wants a sentence. Duplicate answers (a stored fact and the same
        fact re-derived) collapse to one. Returns None when there is no
        verdict/derived answer to state, so the caller keeps the composed reply
        (a taught-back note, an asked-back question)."""
        answers = getattr(understanding, "answers", None)
        if not answers:
            return None
        seen: set = set()
        out: List[str] = []
        for a in answers:
            claim = a.conclusion or (f"{a.about} {a.relation} "
                                     + ", ".join(a.others))
            claim = cls._natural_claim(claim)
            if not claim.strip():
                continue
            if a.verdict is True:
                sentence = f"Yes, {claim}."
            elif a.verdict is False:
                sentence = f"No, {claim}."
            else:
                sentence = f"{claim[:1].upper()}{claim[1:]}."
            if sentence.lower() not in seen:
                seen.add(sentence.lower())
                out.append(sentence)
        return " ".join(out) if out else None

    @staticmethod
    def say(understanding: "Understanding") -> str:
        """A reply assembled from what was found, and nothing else.

        A REPLY ALREADY ANSWERED IS NOT RE-DERIVED. `understand()` answers a
        question ABOUT THIS CONVERSATION from the record and sets `.reply`
        there, because nothing else can answer it -- the sentence is not about
        the world, so there is nothing to resolve. Recomputing here from
        `known` and `unknown`, both empty in that case, produced a second and
        different answer: a caller reading `.reply` was told "We were talking
        about harrier", and a caller calling `say()` on the same object was told
        "There was nothing in that I could resolve".

        Two ways to get one answer, disagreeing. `say()` now returns the answer
        that was already established rather than deriving a worse one over an
        empty result.
        """
        if understanding.reply:
            return understanding.reply

        known, unknown = understanding.known, understanding.unknown
        lines: List[str] = []
        asking: List[str] = []

        # RAISED BEFORE ANYTHING ELSE, INCLUDING BEFORE THE EARLY RETURNS.
        # Memory holding the opposite of what was just said is the most
        # important thing it has. The case that matters most -- being TOLD
        # something the store disagrees with -- takes the earliest exit from
        # this method, so a contradiction appended later was computed and never
        # said.
        contradicting = [m for m in (understanding.recall.memories
                                     if understanding.recall else [])
                         if m.agrees is False]
        if contradicting:
            lines.append("I have the opposite on record: "
                         + contradicting[0].text[:200])

        # SAY WHAT JUST CHANGED. A turn that quietly stored something, or
        # quietly failed to, is a turn you cannot trust twice.
        for item in understanding.acquired:
            if item.stored and understanding.asked:
                lines.append(f"I did not have {item.label}. I looked it up: "
                             f"{item.description}")
                if item.origin:
                    lines.append(f"    (from {item.origin})")
            elif item.stored:
                held = "; ".join(f"{r} {o}" for r, o in item.relations)
                lines.append(f"Noted — {item.label}: {held}")
            else:
                # ASK. Failing to find something is a reason to turn back to
                # the person, not a result to report at them. Held back to the
                # END of the reply, because a question buried above other lines
                # reads as commentary rather than as a question.
                #
                # INFORMED BY SELF-STATE: when the self's disposition is inclined
                # to explore, the gap is not just reported — the substrate says,
                # honestly and qualitatively, that it wants to close it. Neutral
                # disposition (or standalone, no disposition) keeps the plain ask.
                disp = understanding.disposition
                if disp and disp.get("explore"):
                    asking.append(f"I don't hold {item.label} yet — looking it up "
                                  f"found nothing, and it's the kind of gap I want "
                                  f"to close.")
                else:
                    asking.append(f"I don't hold {item.label} yet; looking it up "
                                  f"found nothing, so I'll run a more targeted search.")

        # ANSWER THE QUESTION FIRST — before reciting a memory about the subject
        # or taking the not-known early exit below. A DERIVED answer (reasoned
        # over the concept graph) must not be dropped just because the subject
        # itself resolved to nothing quotable: the question got an answer, and
        # that is what to say. Acquisition/contradiction lines gathered above are
        # kept, then the answer — with the chain it was proved from — is stated.
        if understanding.answers:
            for answer in understanding.answers:
                derived = bool(answer.conclusion or answer.support)
                because = ((" because " + " and ".join(answer.support))
                           if answer.support else "")
                if derived:
                    claim = answer.conclusion or (
                        f"{answer.about} {answer.relation} "
                        + ", ".join(answer.others))
                    if answer.verdict is True:
                        lines.append(f"Yes — {claim}{because}.")
                    elif answer.verdict is False:
                        lines.append(f"No — {claim}{because}.")
                    else:
                        lines.append(f"{claim[:1].upper()}{claim[1:]}{because}.")
                elif answer.verdict is True:
                    lines.append(f"Yes — {answer.about} {answer.relation} "
                                 + ", ".join(answer.others) + ".")
                elif answer.verdict is False:
                    lines.append(f"No — I was told {answer.about} "
                                 f"{answer.relation} "
                                 + ", ".join(answer.others) + ".")
                else:
                    lines.append(f"{answer.about} — {answer.relation}: "
                                 + ", ".join(answer.others))
            accounted = understanding.spoken_for()
            unanswered = [r.phrase for r in unknown
                          if not any(same_stem(r.phrase, w) for w in accounted)]
            if unanswered:
                lines.append("I hold nothing for: " + ", ".join(unanswered))
            return "\n".join(lines)

        # Recite a memory only if it is a CLAIM worth saying back. Pre-readability
        # records are reader-oriented prose -- "Query: ... Answer: ...",
        # "Learning: ... — a; b; c" -- that recite as noise; a record that is not
        # a single clean statement is skipped rather than said back malformed as
        # if it were remembered knowledge.
        _junk = ("query:", "answer:", "reasoning steps", "learning:",
                 "conclusion(s)", "premise(s)", "[premise")
        recitable = next(
            (m for m in understanding.remembered
             if m and "\n" not in m and len(m) <= 220
             and not any(j in m.lower() for j in _junk)),
            None)
        if recitable:
            lines.append("I remember: " + recitable)
        elif understanding.recall is not None and not understanding.recall.complete:
            # SAY SO. An answer that nearly had a memory is a different answer
            # from a complete one, and only one of them is worth trusting twice.
            lines.append("(still searching memory — ask again for more)")

        if not known and (lines or asking):
            return "\n".join(lines + asking)

        if not known:
            if not unknown:
                return "There was nothing in that I could resolve."
            missing = ", ".join(r.phrase for r in unknown)
            tried = any(a.origin == "research" for a in understanding.acquired)
            # An internal user is not the substrate's lookup service: a gap is
            # closed in the BACKGROUND (it is registered as a known-unknown and
            # picked up as an acquisition goal), never turned back as "what is
            # it?". The reply states the gap honestly and that it will be pursued.
            return (f"I don't hold {missing} yet"
                    + (", and looking it up turned up nothing, "
                       if tried else "; ")
                    + "so I'll run a more targeted search.")

        for item in known:
            where = f" ({item.domain})" if item.domain else ""
            lines.append(f"{item.phrase}{where}: {item.description}")
            for relation, other in item.relations:
                lines.append(f"    {relation} {other}")

        # ASK, rather than answer around it. A phrase the store holds twice is
        # not one the substrate can answer about until it knows which was meant.
        for item in known:
            if item.alternatives:
                where = ", ".join(d or c for c, d in item.alternatives)
                lines.append(f"Which {item.phrase} do you mean — the one in "
                             f"{item.domain}, or in {where}?")

        if unknown:
            lines.append("I hold nothing for: " + ", ".join(r.phrase for r in unknown)
                         + ". Tell me what it is and I will keep it.")
        if understanding.reading:
            lines.append(f"Read as {understanding.reading[0]} "
                         f"(by {understanding.reading_source}).")
        return "\n".join(lines + asking)


#: Held conversations, keyed by session. Bounded, oldest evicted first.
#:
#: WHY THIS EXISTS. `Conversation` carries everything continuity depends on --
#: `_turns`, `_last_subject`, `_last_reply`, `_recall` -- and every caller
#: constructed a fresh one. The coordinator built one at :7142 to classify a
#: message and ANOTHER at :7156 to understand the same message, so the two
#: halves of one turn could not see each other. Nothing could carry a subject
#: across turns, notice a follow-up, or answer "what were we talking about":
#: the machinery for all three is in this file and was unreachable.
#:
#: Keyed by session and not global. One shared instance would merge every
#: speaker's turns into a single thread, so what one person said would surface
#: as context for another -- a worse failure than having no continuity at all.
_conversations: "OrderedDict[str, Conversation]" = OrderedDict()

#: In-flight research single-flight, keyed by normalised phrase and SHARED across
#: every conversation in this process (the substrate is one self behind many
#: sessions). While a lookup for a phrase is running, concurrent callers for the
#: same phrase await the same Future instead of each firing identical web research
#: and racing to write the same fact to the shared store. Not a cache: an entry
#: lives only for the duration of one lookup, so a later ask re-verifies against
#: the world. Correct for the one-process deployment; a multi-process fleet would
#: dedup per process (each still collapses its own crowd to one real lookup).
_LOOKUPS_INFLIGHT: "Dict[str, asyncio.Future]" = {}

#: How many conversations are held at once. Past this the least recently used
#: is dropped: a long-running process must not accumulate one per session
#: forever, and losing continuity is recoverable while exhausting memory is not.
MAX_HELD_CONVERSATIONS = 64


def get_conversation(session: str, *, db=None, identity=None,
                     actor_identity=None) -> "Conversation":
    """The held conversation for `session`, created on first use.

    `session` identifies a THREAD OF TALK, not a person -- two windows belong
    to two sessions. A caller with no session of its own must pass a stable
    string of its own choosing rather than a default, so unrelated callers
    cannot silently share one another's context.

    `actor_identity` is the VERIFIED person (a World Auth user id) behind the
    thread, when known; it becomes the actor a told fact is scoped to. A held
    conversation adopts a later-supplied identity, so authenticating mid-thread
    binds the rest of the talk to that person without losing the thread.
    """
    key = str(session)
    held = _conversations.get(key)
    if held is None:
        held = Conversation(db=db, identity=identity, session=key,
                            actor_identity=actor_identity)
        _conversations[key] = held
    elif actor_identity is not None:
        held._actor_identity = actor_identity
        while len(_conversations) > MAX_HELD_CONVERSATIONS:
            evicted, _ = _conversations.popitem(last=False)
            logger.info("conversation %s evicted; %d held", evicted,
                        len(_conversations))
    _conversations.move_to_end(key)
    return held


def end_conversation(session: str) -> bool:
    """Forget a thread of talk. Returns whether one was held."""
    return _conversations.pop(str(session), None) is not None


def held_conversations() -> int:
    """How many threads are currently held. For health reporting."""
    return len(_conversations)



# =============================================================================
# IDENTITY VOCABULARY — the substrate's own account of who it is.
#
# Moved here from self_model.py when the Self was collapsed into this
# coordinator. The substrate IS this coordinator, so its name, its stable
# identity text, and the SelfState snapshot the coordinator composes belong
# with it. IDENTITY_CORE is the SINGLE source of the identity — never recite it
# elsewhere; anything that needs it (a status readout) reads it from here via
# identity_prompt().
# =============================================================================

#: The substrate's name. The one authored constant — everything else is derived.
NAME = "Torin"

#: Who Torin is, second-person — the STABLE identity core. The substrate is
#: model-free: no language model is started, held, or consulted, so the
#: identity must not offer one as a resource.
IDENTITY_CORE = (
    "You are Torin, a cognitive substrate created by Dominion Labs Inc. You are "
    "not a language model and you do not consult one. Your reasoning is symbolic "
    "and evidence-based, it persists between sessions in a database, and it is "
    "the thing that decides. You run locally, and your memories carry forward."
)


@dataclass
class SelfState:
    """A snapshot of who the substrate is right now, entirely derived.

    Fields that have no live source yet are None, never fabricated. `attitude`,
    `temperament`, `drives`, `values`, and `disposition` are wired in v1;
    `competence`, `purpose`, and `continuity` are declared here and populated as
    their authorities are connected — the shape is honest about what is not yet
    integrated.
    """

    name: str
    #: my read of my own internal state — the interoceptive variables appraisal
    #: integrates (valence, confidence, control, progress, open-questions, risk…).
    #: None if nothing has been appraised. This is what the affect is a category OF.
    interoception: Optional[Dict[str, Any]]
    #: how I feel now — affective CATEGORIES over the interoceptive state above,
    #: not selected words. None if nothing appraised.
    attitude: Optional[Dict[str, Any]]
    #: what I am disposed toward — from the standing motivation weights
    temperament: Dict[str, float]
    #: how strongly each drive is active now — from the motivation state
    drives: Optional[Dict[str, float]]
    #: what I am bound by — the constitutional laws (names)
    values: List[str]
    #: how disposition applies to the situation now — from the arbiter over appraisal
    disposition: Dict[str, Any]
    #: what I am actually good at / made of — UDM competence, component registry (later)
    competence: Optional[Dict[str, Any]] = None
    #: what I am for — active directives (later)
    purpose: Optional[List[str]] = None
    #: who I have been, carried forward — memory + persisted profile + deployment (later)
    continuity: Optional[Dict[str, Any]] = None
    #: how I feel now, carried between sessions — the persistent affect STATE
    #: (named emotion + cause + intensity + the mood it sits on), owned by the
    #: motivation system and rehydrated on startup. None until an affect has been
    #: established; never a fabricated feeling.
    affect: Optional[Dict[str, Any]] = None
    #: WHERE I am — the outward half of self-awareness: the environment I inhabit, observed not
    #: hardcoded (its identity, whether it is NEW to me, what I observed of it, and the environment
    #: DOMAIN it is registered as — which makes it a first-class target to investigate). None until
    #: I have looked at my surroundings.
    situation: Optional[Dict[str, Any]] = None
    #: how DEVELOPED I am — a global read of how much I hold (concepts/rules/memories) and my domain
    #: breadth, with saturating `*_pressure` indicators and an overall `growth_pressure` that is high
    #: when I hold/have-lived little (a broad hunger to learn, interact, and grow) and falls as I
    #: accumulate. Real counts; None where a store is unreadable.
    development: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)
