#!/usr/bin/env python3
"""
Abstract Reasoning Engine
Advanced reasoning system for complex problem solving and inference
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import re

from core.structural_defects import raise_if_structural
from core.reasoning.unification import Atom, apply_substitution, match_body

# Initialize logger first
# ONE VOCABULARY, OWNED ELSEWHERE.
#
# `ReasoningType` and `InferenceMethod` used to be DECLARED here, shadowing the
# copies in `reasoning_interfaces`. Enum equality is identity-based, so a
# strategy registered against this module's ReasoningType.DEDUCTIVE could not be
# found by anything holding the interfaces one, while both printed 'deductive'.
# See the note on ReasoningType there.
#
# `InferenceMethod` is now an alias of `InferenceStrategy`, so the twelve
# members this file used and the five the interfaces module used are one list of
# fifteen.
from core.reasoning.reasoning_interfaces import (  # noqa: E402
    CLASSICAL_REASONING_TYPES, InferenceMethod, InferenceStrategy, ReasoningType)

logger = logging.getLogger(__name__)

# The universal ontology this engine reasons over
from core.domain import UniversalOntology
from core.structural_defects import raise_if_structural


class ConfidenceLevel(Enum):
    """Confidence levels for reasoning results"""
    VERY_LOW = 0.1
    LOW = 0.3
    MEDIUM = 0.5
    HIGH = 0.7
    VERY_HIGH = 0.9
    CERTAIN = 1.0


@dataclass
class ReasoningPremise:
    """A premise or assumption used in reasoning, AND WHERE IT CAME FROM.

    `premise_id` is local to one reasoning context (`p0`, `p1`, ...) and is what
    `ReasoningConclusion.supporting_premises` names. That is enough to say WHICH
    premise a proof used inside this context, and nothing at all about which
    stored thing the premise WAS.

    `provenance` closes that. The substrate builds its premises from concepts it
    resolved, memories it recalled and rules it holds -- every one of which has
    an identity in the store at the moment it is read -- and that identity was
    dropped when the premise became a string. The consequence was not only lost
    telemetry: attributing support had to be done by MATCHING CONTENT WORDS
    between a premise and the proof's `[Premise]` lines, so two premises sharing
    their content words both counted as used when only one was. A heuristic
    standing in for a link that had been thrown away three frames earlier.

    None means the premise genuinely has no stored origin -- a caller's literal
    context sentence -- which is different from "we forgot".
    """
    premise_id: str
    statement: str
    confidence: float = 1.0
    source: str = "user"

    #: The store identity this premise came from (a concept id, memory id, rule
    #: id, ...). None = no stored origin, never "unknown".
    provenance: Optional[str] = None
    #: What KIND of thing `provenance` names: concept | memory | rule | belief.
    provenance_kind: Optional[str] = None
    #: HOW THE PREMISE READS, for saying why. `statement` is what is reasoned
    #: over -- for a held fact, its atom -- and this is the same premise as a
    #: person reads it. None when the statement already reads as itself.
    said: Optional[str] = None

    # Logical structure
    predicates: List[str] = field(default_factory=list)
    variables: List[str] = field(default_factory=list)
    constants: List[str] = field(default_factory=list)
    
    # Metadata
    domain: Optional[str] = None
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    dependencies: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        """The sentence, so a premise can travel anywhere a premise string could.

        Every existing consumer of `ReasoningRequest.context` does `str(item)`;
        this is what lets a provenance-carrying premise pass through all of them
        unchanged instead of forcing a second, parallel list that could drift
        out of step with the first.
        """
        return self.statement


@dataclass
class ReasoningConclusion:
    """A conclusion produced by reasoning, and where it came from.

    ORIGIN IS NOT DECORATION. `derived` means a deterministic strategy
    established this from the premises -- rule application, pattern
    generalisation, structural abduction -- and its confidence was COMPUTED
    from that derivation. `proposed` means a model suggested it, which is a
    suggestion and nothing more.

    The distinction exists because these two used to be indistinguishable in
    this dataclass, and everything downstream averaged them together.
    """
    conclusion_id: str
    statement: str
    confidence: float
    reasoning_type: ReasoningType
    inference_method: InferenceMethod

    #: "derived" (a strategy established it) or "proposed" (a model suggested
    #: it). A proposal carries no confidence and no quality score: the numbers
    #: it would otherwise carry could only come from the model grading itself.
    origin: str = "derived"
    
    # Supporting evidence
    supporting_premises: List[str] = field(default_factory=list)
    reasoning_steps: List[str] = field(default_factory=list)
    alternative_conclusions: List[str] = field(default_factory=list)
    
    # Quality metrics
    logical_validity: float = 0.0
    evidence_strength: float = 0.0
    coherence_score: float = 0.0
    composite_score: float = 0.0
    
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


@dataclass
class ReasoningContext:
    """Context for a reasoning operation"""
    context_id: str
    domain: str
    problem_type: str
    
    # Available knowledge
    premises: List[ReasoningPremise] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    
    # Reasoning configuration
    allowed_reasoning_types: List[ReasoningType] = field(default_factory=list)
    max_inference_depth: int = 5
    confidence_threshold: float = 0.5
    
    # Goals
    target_conclusions: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)

    #: WHOSE COGNITION THIS SERVES -- the actor the request was reasoned for
    #: (None: the substrate's own). A user's premises can include their own
    #: context, so everything this reasoning writes down is that user's.
    actor: Optional[str] = None
    #: THE ORGANIZATION it was reasoned for, when the person asked through
    #: their work for it: what it writes down is then the organization's Work
    #: Context (docs/research/SEPARATION_MAP.md §11.13).
    organization: Optional[str] = None
    #: WHETHER WHAT THIS REASONING WRITES DOWN IS KEPT. A conversation held not to
    #: remember (`Conversation(remembers=False)`) writes nothing, its reasoning
    #: included: neither the memory of it nor the learning from it. Its questions'
    #: reasoning wrote nine memories, with their learning, to main during
    #: UNDERSTANDS-PROSE-02 (2026-10-21/22).
    remembered: bool = True

    def origin(self, through: str):
        """Where what this reasoning writes down belongs: the person's, the
        organization's at work, or the substrate's own (`Origin.owner`)."""
        from core.memory import Origin
        return Origin.of(self.actor, through, context="work" if self.organization else None,
                         organization=self.organization)


@dataclass
class ReasoningResult:
    """Complete result of a reasoning operation"""
    result_id: str
    context: ReasoningContext
    
    # Results
    conclusions: List[ReasoningConclusion] = field(default_factory=list)
    intermediate_results: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    reasoning_time: float = 0.0
    total_inferences: int = 0
    confidence_distribution: Dict[str, float] = field(default_factory=dict)
    
    # Quality assessment
    overall_confidence: float = 0.0
    logical_consistency: float = 0.0
    completeness_score: float = 0.0
    
    success: bool = False
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


#: Words that make a statement deny rather than assert. Closed and small: a
#: premise carrying one of these does not support a generalisation drawn from
#: statements that assert the same terms.
_NEGATION_MARKERS = frozenset({
    "not", "no", "never", "isn't", "aren't", "wasn't", "weren't",
    "doesn't", "don't", "didn't", "cannot", "can't", "without",
})


class ReasoningStrategy(ABC):
    """Abstract base class for reasoning strategies"""
    
    @abstractmethod
    async def reason(self, context: ReasoningContext) -> List[ReasoningConclusion]:
        """Execute the reasoning strategy"""
        pass
    
    @abstractmethod
    def get_strategy_name(self) -> str:
        """Get the name of this strategy"""
        pass
    
    @abstractmethod
    def is_applicable(self, context: ReasoningContext) -> bool:
        """Check if this strategy is applicable to the context"""
        pass


class DeductiveReasoningStrategy(ReasoningStrategy):
    """Strategy for deductive reasoning (general to specific)"""

    def __init__(self, neural_bridge=None):
        self.strategy_name = "deductive_reasoning"
        self.neural_bridge = neural_bridge
    
    async def reason(self, context: ReasoningContext) -> List[ReasoningConclusion]:
        """Execute deductive reasoning. Rule application, and nothing else.

        DEDUCTION IS THE RELATION OF FOLLOWING FROM THE PREMISES, so the rules
        are not a floor beneath something better -- they are the whole of it. If
        no rule applies, nothing follows, and reporting that is the correct
        answer rather than a shortfall to be topped up.

        Two things were removed to get here, in order.

        First this branched on whether an llm_service object EXISTED, which made
        rule application unreachable whenever one was attached: a model that was
        present but failing produced no conclusions at all, even for premises
        the rules alone could settle.

        Then the model was consulted UNCONDITIONALLY after the rules, "to extend
        the result". A statement the rules cannot derive is not a deduction; it
        is a guess wearing the label. That call also cost 33.6 s against roughly
        80 ms for the strategies that never call a model, and it MASKED failure
        -- a run where no rule fired still returned a conclusion, so "the rules
        did not match" looked like a successful answer.
        """
        conclusions = []

        try:
            for rule in context.rules:
                for premise in context.premises:
                    if await self._rule_applies_to_premise(rule, premise):
                        conclusion = await self._apply_rule(rule, premise, context)
                        if conclusion:
                            conclusions.append(conclusion)
        except Exception as e:
            logger.error(f"Error in rule-based deduction: {e}")

        # THE MODEL IS NOT CONSULTED. DEDUCTION IS WHAT THE SUBSTRATE DERIVES.
        #
        # This used to run the rule floor and then call the model
        # UNCONDITIONALLY -- the only thing that skipped it was the absence of a
        # service object -- "to extend the result".
        #
        # That cannot be right for deduction. Deduction is the relation of following from the premises. A statement the
        # rules cannot produce is, by definition, not a deduction; it is a
        # guess wearing the label. There is no coverage gap here for a model to
        # fill, because the gap IS the answer: if nothing follows, nothing
        # follows, and saying so is the correct output.
        #
        # It had also stopped contributing anything. Since model proposals were
        # given `origin="proposed"`, confidence 0.0 and no cited premises, they
        # are excluded from `overall_confidence`, ranked below every derived
        # conclusion and counted in no quality metric -- so what remained was an
        # unscored sentence appended to the result.
        #
        # And it was expensive: measured at 33.6 s against roughly 80 ms for the
        # nine strategies that never call a model. Worse, it MASKED failure --
        # a run where rule matching produced nothing still returned a
        # conclusion, so "the rules did not fire" looked like a successful
        # answer.

        return conclusions


    
    def get_strategy_name(self) -> str:
        return self.strategy_name
    
    def is_applicable(self, context: ReasoningContext) -> bool:
        """Whether the context carries what this strategy needs.

        NO LONGER RE-CHECKS `allowed_reasoning_types`. `_select_strategies`
        already filters on that before calling this, so the test was redundant
        on the normal path -- and actively wrong on the other one: when a caller
        declares no allowed types, `_select_strategies` falls back to "every
        applicable strategy", and this returned False for an EMPTY list. So the
        three original strategies could never fire on the fallback path, while
        the eight added later (which test only for material) could. Same engine,
        same call, two different rules about what "applicable" means.

        What remains is the honest question: is the material here?
        """
        return len(context.rules) > 0 and len(context.premises) > 0
    
    async def _rule_applies_to_premise(self, rule: str, premise: ReasoningPremise) -> bool:
        """Whether this rule can fire against this premise, by UNIFICATION.

        This used to extract bare words from both strings and return True on any
        overlap -- a gate so loose that essentially every rule passed it, paired
        with an application step so strict that essentially none succeeded.
        """
        return bool(self._bind(rule, [premise]))

    def _as_atom(self, text: str) -> Optional[Atom]:
        """Read one literal, or None if it is not a relational atom.

        None means UNREPRESENTABLE, and callers must treat it as such rather
        than as a failed match: "I could not read this" and "this does not
        follow" are different answers.
        """
        text = (text or "").strip().rstrip(".")
        if not text or "(" not in text:
            return None
        try:
            return Atom.parse(text)
        except Exception:
            return None

    def _split_rule(self, rule: str) -> Optional[Tuple[List[Atom], Atom]]:
        """A rule as (body, head), or None if it is not an implication."""
        text = (rule or "").strip()
        for arrow in ("->", "=>", "\u2192"):
            if arrow in text:
                left, _, right = text.partition(arrow)
                break
        else:
            lowered = text.lower()
            if "if" not in lowered or "then" not in lowered:
                return None
            left = text[lowered.index("if") + 2:lowered.index("then")]
            right = text[lowered.index("then") + 4:]

        head = self._as_atom(right)
        if head is None:
            return None
        body = [atom for atom in (self._as_atom(part) for part in left.split(","))
                if atom is not None]
        if not body:
            return None
        return body, head

    def _bind(self, rule: str, premises: List[ReasoningPremise]) -> List[Dict[str, str]]:
        """Every substitution under which the rule's body holds in the premises."""
        parsed = self._split_rule(rule)
        if parsed is None:
            return []
        body, _head = parsed
        state = [atom for atom in (self._as_atom(p.statement) for p in premises)
                 if atom is not None]
        if not state:
            return []
        return match_body(body, state)

    async def _apply_rule(self, rule: str, premise: ReasoningPremise,
                          context: ReasoningContext) -> Optional[ReasoningConclusion]:
        """Instantiate the rule's head under each binding the premises license.

        THE DEFECT THIS REPLACES. The previous implementation compared the
        rule's condition text to the premise as a SUBSTRING, with the variable
        name still in it:

            condition = "x is human"
            "x is human" in "socrates is human"   ->  False

        so no rule containing a variable could ever fire. It returned None
        silently, and because the applicability gate above passed almost
        everything, the engine reported zero conclusions with no error --
        for every reasoning type, on every input. Unification is now delegated
        to `core/reasoning/unification.py`, which is the single authority for
        binding variables to terms and is shared with rule induction.
        """
        try:
            parsed = self._split_rule(rule)
            if parsed is None:
                return None
            _body, head = parsed

            bindings = self._bind(rule, [premise])
            if not bindings:
                return None

            derived = apply_substitution(head, bindings[0])
            if not derived.is_ground:
                # An unbound head variable means the rule is not range
                # restricted for these premises; asserting it would invent a
                # constant that no premise supplied.
                return None

            confidence = min(0.8, premise.confidence * 0.9)
            return ReasoningConclusion(
                conclusion_id=str(uuid.uuid4()),
                statement=derived.to_formula(),
                confidence=confidence,
                reasoning_type=ReasoningType.DEDUCTIVE,
                inference_method=InferenceMethod.UNIFICATION,
                supporting_premises=[premise.premise_id],
                reasoning_steps=[f"Applied rule: {rule}",
                                 f"Unified: {bindings[0]}"],
                logical_validity=0.8,
                evidence_strength=premise.confidence,
                coherence_score=0.7,
            )
        except Exception as e:
            raise_if_structural(e, "DeductiveReasoningStrategy._apply_rule")
            logger.error(f"Error applying rule: {e}")
            return None


def _held_facts(premises: List[ReasoningPremise]) -> List[Tuple[str, str, str, bool, str]]:
    """The premises that carry their structure, as `(subject, relation, object, held, premise_id)`: one relation
    (`predicates`) between two named things (`constants`), held, or denied where its statement is negated ("~").
    A premise given only as a string has no structure here, and two kinds that need it (induction, analogy) have
    nothing to work from in it: they never reach for the words of the string."""
    out = []
    for premise in premises:
        if len(premise.predicates) == 1 and len(premise.constants) == 2:
            subject, obj = (str(c) for c in premise.constants)
            out.append((subject, str(premise.predicates[0]), obj,
                        not str(premise.statement).startswith("~"), premise.premise_id))
    return out


def _atom(subject: str, relation: str, obj: str) -> Optional[str]:
    from core.reasoning.neural_bridge import clause_atom
    return clause_atom(subject, relation, obj)


class InductiveReasoningStrategy(ReasoningStrategy):
    """Induction: from the instances of a kind held, what holds of the kind (specific to general).

    Where every instance of a kind memory holds -- at least two -- holds the same fact, the fact is proposed of the
    kind: "robin isa bird", "sparrow isa bird", both "capable_of fly", so perhaps "bird capable_of fly". Over the
    premises' STRUCTURE (`_held_facts`), never their words. A generalisation is supported by its examples, not
    proved by them: induction is not a kind that yields facts (`neural_bridge._FACT_YIELDING_KINDS`), and what it
    proposes is not verified. Nothing is proposed that the kind already holds or is held not to."""

    #: The fewest instances a generalisation is drawn from.
    FEWEST = 2

    def __init__(self, neural_bridge=None):
        self.strategy_name = "inductive_reasoning"
        self.neural_bridge = neural_bridge

    async def reason(self, context: ReasoningContext) -> List[ReasoningConclusion]:
        facts = _held_facts(context.premises)
        held = {(s, r, o) for s, r, o, positive, _ in facts if positive}
        denied = {(s, r, o) for s, r, o, positive, _ in facts if not positive}
        kinds: Dict[str, Dict[str, str]] = {}
        for s, r, o, positive, pid in facts:
            if positive and r in ("isa", "instance_of"):
                kinds.setdefault(o, {})[s] = pid
        by_thing: Dict[str, Dict[Tuple[str, str], str]] = {}
        for s, r, o, positive, pid in facts:
            if positive and r not in ("isa", "instance_of"):
                by_thing.setdefault(s, {})[(r, o)] = pid
        conclusions = []
        for kind, instances in kinds.items():
            if len(instances) < self.FEWEST:
                continue
            shared = set.intersection(*(set(by_thing.get(x, {})) for x in instances))
            for relation, obj in sorted(shared):
                if (kind, relation, obj) in held or (kind, relation, obj) in denied or obj == kind:
                    continue
                statement = _atom(kind, relation, obj)
                if not statement:
                    continue
                support = [pid for pid in instances.values()] + [by_thing[x][(relation, obj)] for x in instances]
                confidence = min(0.7, len(instances) / (len(instances) + 1))
                conclusions.append(ReasoningConclusion(
                    conclusion_id=str(uuid.uuid4()), statement=statement, confidence=confidence,
                    reasoning_type=ReasoningType.INDUCTIVE, inference_method=InferenceMethod.PATTERN_MATCHING,
                    supporting_premises=support,
                    reasoning_steps=[f"{', '.join(sorted(instances))}: each is a {kind} and each {relation} {obj}",
                                     f"so perhaps every {kind} {relation} {obj}"],
                    logical_validity=0.0, evidence_strength=confidence, coherence_score=confidence))
        return conclusions

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def is_applicable(self, context: ReasoningContext) -> bool:
        """Whether the context carries what this strategy needs: structured premises, two at least."""
        return len(_held_facts(context.premises)) >= 2


class AbductiveReasoningStrategy(ReasoningStrategy):
    """Inference to the best explanation.

    ReasoningType.ABDUCTIVE was declared but no strategy implemented it, so a
    context allowing abduction selected no strategy and silently produced
    nothing.

    The floor is a backward search over the rule base: a rule C → O whose
    consequent matches an observation makes C a candidate explanation.
    Candidates are scored on coverage, simplicity and consistency, and the
    best is registered with the hypothesis system so its confidence is earned
    by falsification rather than asserted at generation time.
    """

    # Structural plausibility is not evidence. A candidate that merely explains
    # the observations cannot reach certainty from structure alone -- only the
    # epistemic layer, holding real evidence, may exceed this.
    STRUCTURAL_CONFIDENCE_CEILING = 0.7

    def __init__(self, neural_bridge=None):
        self.strategy_name = "abductive_reasoning"
        self.neural_bridge = neural_bridge
        self._parser = None

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def is_applicable(self, context: ReasoningContext) -> bool:
        return bool(self._observations(context)) and bool(context.rules)

    @property
    def parser(self):
        if self._parser is None:
            from core.reasoning.logical_integration import LogicalFormulaParser
            self._parser = LogicalFormulaParser()
        return self._parser

    async def reason(self, context: ReasoningContext) -> List[ReasoningConclusion]:
        """Explain the observations: rule search first, model second."""
        try:
            conclusions = self._explain_from_rules(context)
        except Exception as e:
            logger.error(f"Error in rule-based abduction: {e}")
            return []

        if conclusions:
            try:
                await self._register_best_as_hypothesis(conclusions[0], context)
            except Exception as e:
                logger.debug(f"Hypothesis registration unavailable: {e}")

        return conclusions

    # ── the substrate floor ──────────────────────────────────────────────

    def _observations(self, context: ReasoningContext) -> List[str]:
        seen, observations = set(), []
        for text in [p.statement for p in context.premises] + list(context.facts):
            statement = (text or "").strip()
            if statement and statement.lower() not in seen:
                seen.add(statement.lower())
                observations.append(statement)
        return observations

    def _key(self, text: str) -> str:
        """Canonical form, so 'A→B' and 'A → B' compare equal."""
        try:
            text = self.parser.render(self.parser.parse_ast(text))
        except Exception:
            pass
        return "".join(text.split()).lower()

    def _parsed_rules(self, context: ReasoningContext):
        """Rules of the form C → O. Anything else cannot support abduction."""
        rules, unusable = [], 0
        for text in context.rules:
            try:
                node = self.parser.parse_ast(text)
            except Exception:
                unusable += 1
                continue
            if node[0] != "implies":
                unusable += 1
                continue
            rules.append((node[1], node[2], text))
        if unusable:
            logger.debug(f"Abduction ignored {unusable} rule(s) that are not implications")
        return rules

    def _polarity(self, observations: List[str]):
        """Which atoms the observations assert, and which they deny."""
        asserted, denied = set(), set()
        for text in observations:
            try:
                node = self.parser.parse_ast(text)
            except Exception:
                continue
            if node[0] == "not":
                denied |= self.parser.formula_atoms(node[1])
            elif node[0] == "atom":
                asserted.add(node[1])
        return asserted, denied

    def _explain_from_rules(self, context: ReasoningContext) -> List[ReasoningConclusion]:
        observations = self._observations(context)
        if not observations:
            return []

        by_key = {self._key(o): o for o in observations}
        _, denied = self._polarity(observations)

        candidates: Dict[str, Dict[str, Any]] = {}
        for antecedent, consequent, rule_text in self._parsed_rules(context):
            observation = by_key.get(self._key(self.parser.render(consequent)))
            if observation is None:
                continue
            explanation = self.parser.render(antecedent)
            entry = candidates.setdefault(explanation, {
                "atoms": self.parser.formula_atoms(antecedent),
                "explains": set(),
                "rules": [],
            })
            entry["explains"].add(observation)
            entry["rules"].append(rule_text)

        if not candidates:
            return []

        scored = []
        for explanation, entry in candidates.items():
            coverage = len(entry["explains"]) / len(observations)
            # Occam: an explanation resting on more conjuncts assumes more.
            simplicity = 1.0 / len(entry["atoms"]) if entry["atoms"] else 0.0
            consistent = not (entry["atoms"] & denied)
            confidence = (
                self.STRUCTURAL_CONFIDENCE_CEILING * coverage * simplicity
                if consistent else 0.0
            )
            scored.append((confidence, coverage, simplicity, consistent, explanation, entry))

        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        alternatives = [s[4] for s in scored]

        conclusions = []
        for rank, (confidence, coverage, simplicity, consistent, explanation, entry) in enumerate(scored):
            explained = sorted(entry["explains"])
            conclusions.append(ReasoningConclusion(
                conclusion_id=f"abduct_{uuid.uuid4().hex[:12]}",
                statement=explanation,
                confidence=round(confidence, 4),
                reasoning_type=ReasoningType.ABDUCTIVE,
                inference_method=InferenceMethod.BACKWARD_CHAINING,
                supporting_premises=[
                    p.premise_id for p in context.premises if p.statement in entry["explains"]
                ],
                reasoning_steps=[
                    f"observed: {', '.join(explained)}",
                    *[f"rule: {r}" for r in entry["rules"]],
                    f"therefore {explanation} would explain "
                    f"{len(explained)} of {len(observations)} observation(s)",
                    "abduction is defeasible: a competing explanation may account "
                    "for the same observations",
                ],
                alternative_conclusions=[a for a in alternatives if a != explanation],
                # For a defeasible inference this records consistency with the
                # observations -- the rule link is what makes the explanation
                # admissible at all -- not deductive entailment.
                logical_validity=1.0 if consistent else 0.0,
                evidence_strength=round(coverage, 4),
                coherence_score=round(simplicity, 4),
                composite_score=round(confidence, 4),
            ))
            _ = rank

        return conclusions

    async def _register_best_as_hypothesis(self, conclusion: ReasoningConclusion, context: ReasoningContext):
        """Make the leading explanation falsifiable.

        This is what keeps abduction honest: the candidate leaves here as a
        hypothesis with falsification criteria, so evidence -- not the search
        that produced it -- decides what it is worth.
        """
        from core.reasoning.hypothesis_testing import get_hypothesis_system

        system = get_hypothesis_system()
        # self.db is set only inside initialize(); the singleton factory does not
        # call it. Without this the hypothesis is built in memory and
        # _save_hypothesis silently returns -- a write that never happens and
        # never complains.
        if not system.db:
            await system.initialize()

        # An explanation of a person's observations is theirs (the organization's at work).
        hypothesis = await system.generate_hypothesis(
            claim=conclusion.statement,
            domain=context.domain,
            predictions=conclusion.reasoning_steps[:1],
            alternatives=conclusion.alternative_conclusions,
            owner=context.origin("hypothesis testing").owner,
        )
        conclusion.reasoning_steps.append(f"registered as hypothesis {hypothesis.hypothesis_id}")
        return hypothesis


class AnalogicalReasoningStrategy(ReasoningStrategy):
    """Analogy: what one thing holds, proposed of another thing that is like it in what is held of both.

    Two things alike in at least one fact held of each ("robin isa bird", "wug isa bird") are compared, and a fact
    held of one and not of the other is proposed of the other, with how alike they are as its confidence: "robin
    capable_of fly", so perhaps "wug capable_of fly". Structure-mapping over the premises' STRUCTURE (`_held_facts`;
    Gentner 1983), never their words. An analogy proposes; it does not prove: analogy is not a kind that yields
    facts (`neural_bridge._FACT_YIELDING_KINDS`), and what it proposes is not verified. Nothing is proposed that the
    other thing is held not to hold."""

    def __init__(self, neural_bridge=None):
        self.strategy_name = "analogical_reasoning"
        self.neural_bridge = neural_bridge

    async def reason(self, context: ReasoningContext) -> List[ReasoningConclusion]:
        facts = _held_facts(context.premises)
        denied = {(s, r, o) for s, r, o, positive, _ in facts if not positive}
        by_thing: Dict[str, Dict[Tuple[str, str], str]] = {}
        for s, r, o, positive, pid in facts:
            if positive:
                by_thing.setdefault(s, {})[(r, o)] = pid
        conclusions = []
        things = sorted(by_thing)
        for source in things:
            for target in things:
                if source == target:
                    continue
                shared = set(by_thing[source]) & set(by_thing[target])
                if not shared:
                    continue
                alike = len(shared) / len(set(by_thing[source]) | set(by_thing[target]))
                for (relation, obj), pid in sorted(by_thing[source].items()):
                    if (relation, obj) in by_thing[target] or (target, relation, obj) in denied or obj == target:
                        continue
                    statement = _atom(target, relation, obj)
                    if not statement:
                        continue
                    confidence = min(0.7, 0.8 * alike)
                    conclusions.append(ReasoningConclusion(
                        conclusion_id=str(uuid.uuid4()), statement=statement, confidence=confidence,
                        reasoning_type=ReasoningType.ANALOGICAL, inference_method=InferenceMethod.PATTERN_MATCHING,
                        supporting_premises=[by_thing[source][f] for f in sorted(shared)]
                        + [by_thing[target][f] for f in sorted(shared)] + [pid],
                        reasoning_steps=[f"{source} and {target} are alike: "
                                         + "; ".join(f"each {r} {o}" for r, o in sorted(shared)),
                                         f"{source} {relation} {obj}, so perhaps {target} {relation} {obj}"],
                        logical_validity=0.0, evidence_strength=confidence, coherence_score=alike))
        return conclusions

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def is_applicable(self, context: ReasoningContext) -> bool:
        return len(_held_facts(context.premises)) >= 2


class CausalReasoningStrategy(ReasoningStrategy):
    """What brings about what, over the engine that already knows how.

    ReasoningType.CAUSAL was declared and selected by nothing, anywhere -- the
    same defect AbductiveReasoningStrategy records for ABDUCTIVE. Meanwhile
    `temporal_reasoning` carried a complete causal apparatus --
    `establish_causal_link`, `trace_causal_chain`, `predict_effect` -- with ZERO
    callers in the entire repository.

    So this implements nothing itself. It reads causal claims out of the
    premises, hands them to the engine that owns causality, and reports what the
    engine derives. Building a second causal implementation here is what would
    have made this file a competing authority.

    CONFIDENCE COMES FROM THE LINK, NOT FROM HERE. A traced chain is only as
    strong as its weakest link, so the chain's confidence is the minimum along
    it -- a conclusion resting on a 0.4 step is not a 0.9 conclusion because the
    other steps were strong.
    """

    #: Phrases that assert one thing brings about another, longest first so
    #: "leads to" is matched before "to". Deliberately closed and small: this is
    #: not an attempt at English, it is the handful of forms whose meaning IS a
    #: causal relation.
    CAUSAL_FORMS = (
        " results in ", " leads to ", " brings about ", " gives rise to ",
        " causes ", " triggers ", " produces ",
    )
    #: Same relation stated backwards -- "B because of A" means A causes B.
    REVERSED_FORMS = (" because of ", " due to ", " caused by ")

    def __init__(self, neural_bridge=None):
        self.strategy_name = "causal_reasoning"
        self.neural_bridge = neural_bridge
        self._engine = None

    @property
    def engine(self):
        """The causal authority, loaded lazily so importing this file is cheap."""
        if self._engine is None:
            from core.reasoning.temporal_reasoning import TemporalReasoningSystem
            self._engine = TemporalReasoningSystem()
        return self._engine

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def _causal_pairs(self, context) -> List[Tuple[str, str, float]]:
        """(cause, effect, confidence) for every premise stating a causal claim."""
        pairs = []
        for premise in context.premises:
            text = f" {str(getattr(premise, 'statement', '') or '').lower()} "
            confidence = float(getattr(premise, "confidence", 1.0) or 1.0)
            for form in self.CAUSAL_FORMS:
                index = text.find(form)
                if index != -1:
                    cause = text[:index].strip()
                    effect = text[index + len(form):].strip()
                    if cause and effect:
                        pairs.append((cause, effect, confidence))
                    break
            else:
                for form in self.REVERSED_FORMS:
                    index = text.find(form)
                    if index != -1:
                        effect = text[:index].strip()
                        cause = text[index + len(form):].strip()
                        if cause and effect:
                            pairs.append((cause, effect, confidence))
                        break
        return pairs

    def is_applicable(self, context) -> bool:
        """True only when a premise actually states a causal relation.

        Answering honestly matters: a context with no causal claim selects no
        strategy, which is a different outcome from a strategy running and
        finding nothing, and the engine reports the two differently.
        """
        return bool(self._causal_pairs(context))

    async def reason(self, context) -> List[ReasoningConclusion]:
        pairs = self._causal_pairs(context)
        if not pairs:
            return []

        engine = self.engine
        # Prior causal links (Postgres-backed) accumulate observations across
        # sessions instead of starting fresh each call. Non-fatal.
        await engine.load()
        conclusions: List[ReasoningConclusion] = []
        effect_ids: Dict[str, str] = {}
        strengths: Dict[str, float] = {}

        from core.reasoning.temporal_reasoning import TimePoint

        # ONE PROPOSITION PER DISTINCT STATEMENT.
        #
        # `create_proposition` mints a fresh id every call, so minting per
        # premise gave "write failure" one id as the EFFECT of premise 1 and a
        # different id as the CAUSE of premise 2. The two links then shared no
        # node, `trace_causal_chain` could not walk from one to the other, and a
        # genuine two-step chain -- disk exhaustion -> write failure ->
        # checkout timeout -- reported the intermediate step as the root cause.
        #
        # Wrong in the most dangerous direction: it produced a confident,
        # plausible answer rather than an error. Composing chains the premises
        # never state individually is the entire reason to consult a causal
        # engine, and that was exactly what silently did not happen.
        known: Dict[str, Any] = {}

        # WHOSE: a person's premises can be their own context, so what this
        # reasoning writes down is theirs.
        owner = context.origin("temporal reasoning").owner

        def proposition(text: str, when, confidence: float):
            existing = known.get(text)
            if existing is not None:
                return existing
            made = engine.create_proposition(
                statement=text, time_point=when, confidence=confidence, owner=owner)
            known[text] = made
            return made

        for cause_text, effect_text, confidence in pairs:
            cause = proposition(cause_text, TimePoint.PAST, confidence)
            effect = proposition(effect_text, TimePoint.PRESENT, confidence)
            link = engine.establish_causal_link(
                cause=cause, effect=effect, strength=confidence,
                evidence=[f"premise: {cause_text} -> {effect_text}"])
            effect_ids[effect.prop_id] = effect_text
            # KEYED BY EDGE, NOT BY NODE.
            #
            # Keying strength per node made a node inherit the weakest link
            # touching it ANYWHERE, so "write failure" -- the effect of a 0.90
            # link and the cause of a 0.60 one -- dragged the 0.90 chain down to
            # 0.60. A conclusion resting entirely on the strong link was scored
            # by a link it does not use. Understating, so not dangerous, but not
            # the number it claims to be.
            strengths[(link.cause_id, link.effect_id)] = confidence

            # A stated link is a conclusion in its own right: this premise
            # asserts a relation, and the engine now holds it as one.
            conclusions.append(ReasoningConclusion(
                conclusion_id=str(uuid.uuid4()),
                statement=f"{cause_text} causes {effect_text}",
                confidence=confidence,
                origin="derived",
                reasoning_type=ReasoningType.CAUSAL,
                inference_method=InferenceMethod.FORWARD_CHAINING,
                supporting_premises=[p.premise_id for p in context.premises
                                     if cause_text in str(p.statement).lower()],
                reasoning_steps=[f"stated: {cause_text} -> {effect_text}",
                                 f"link strength {confidence:.2f}"],
                logical_validity=confidence,
                evidence_strength=confidence,
                coherence_score=confidence))

        # ROOT CAUSES. The chains are what the premises could not state
        # individually -- A->B and B->C only become "A explains C" once
        # something composes them, and that composition is the engine's.
        for effect_id, effect_text in effect_ids.items():
            for chain in engine.trace_causal_chain(effect_id) or []:
                if len(chain) < 2:
                    continue
                # Weakest link governs: a chain is not stronger than its
                # least-supported step -- and the steps are the EDGES actually
                # walked. `trace_causal_chain` returns nodes effect-first, so
                # consecutive pairs (chain[i+1] -> chain[i]) are the links.
                walked = [strengths[(chain[i + 1], chain[i])]
                          for i in range(len(chain) - 1)
                          if (chain[i + 1], chain[i]) in strengths]
                if not walked:
                    continue
                chain_confidence = min(walked)
                root = chain[-1]
                root_text = getattr(engine.propositions.get(root, None),
                                    "statement", root)
                conclusions.append(ReasoningConclusion(
                    conclusion_id=str(uuid.uuid4()),
                    statement=f"root cause of {effect_text}: {root_text}",
                    confidence=chain_confidence,
                    origin="derived",
                    reasoning_type=ReasoningType.CAUSAL,
                    inference_method=InferenceMethod.BACKWARD_CHAINING,
                    reasoning_steps=[f"traced {len(chain)} step(s) back",
                                     f"weakest link {chain_confidence:.2f}"],
                    logical_validity=chain_confidence,
                    evidence_strength=chain_confidence,
                    coherence_score=chain_confidence))

        # Persist causal links to Postgres, off the critical path and non-fatal.
        await engine.persist()
        return conclusions


class CounterfactualReasoningStrategy(ReasoningStrategy):
    """What would have followed instead, over the engine that projects states.

    ReasoningType.COUNTERFACTUAL was declared and selected by nothing, while
    `temporal_reasoning` -- whose own class docstring lists "Counterfactual
    temporal reasoning" as a purpose -- carried `project_future_state`,
    `compare_future_states` and `evaluate_state_reachability` with ZERO callers
    anywhere in the repository.

    A counterfactual is two states and a comparison: the world as its conditions
    actually stand, and the world under the alternative the premise names. The
    engine projects both and compares them; this reads the alternative out of
    the premise and reports what the comparison found.

    REACHABILITY IS PART OF THE ANSWER. "Things would have gone better" is worth
    little if the alternative could never have obtained, so every conclusion
    carries what the engine says about whether the alternative was reachable
    from the conditions that actually held, and an unreachable alternative is
    reported as unreachable rather than quietly scored as an improvement.
    """

    #: Phrases that pose an alternative to what actually happened. Closed and
    #: small, for the same reason as the causal forms above.
    COUNTERFACTUAL_FORMS = (
        "would have", "what if", "if instead", "instead of", "had it",
        "were it not", "otherwise", "without ",
    )

    #: A projection is a projection. Structural plausibility is not evidence,
    #: so a counterfactual conclusion cannot exceed this from comparison alone
    #: -- the same ceiling AbductiveReasoningStrategy applies for the same
    #: reason.
    STRUCTURAL_CONFIDENCE_CEILING = 0.7

    def __init__(self, neural_bridge=None):
        self.strategy_name = "counterfactual_reasoning"
        self.neural_bridge = neural_bridge
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            from core.reasoning.temporal_reasoning import TemporalReasoningSystem
            self._engine = TemporalReasoningSystem()
        return self._engine

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def _alternatives(self, context) -> List[Tuple[str, float]]:
        """(alternative, confidence) for each premise posing a counterfactual."""
        found = []
        for premise in context.premises:
            text = str(getattr(premise, "statement", "") or "").lower()
            confidence = float(getattr(premise, "confidence", 1.0) or 1.0)
            for form in self.COUNTERFACTUAL_FORMS:
                index = text.find(form)
                if index != -1:
                    alternative = text[index + len(form):].strip(" ,.?")
                    # "what if the retry HAD fired" -> the marker already
                    # carries the counterfactual mood, so a leading auxiliary
                    # left in place reads back as "had the retry had fired".
                    for auxiliary in ("had ", "have ", "were ", "was "):
                        if alternative.startswith(auxiliary):
                            alternative = alternative[len(auxiliary):]
                            break
                    alternative = " ".join(
                        w for w in alternative.split() if w not in ("had", "have"))
                    if alternative:
                        found.append((alternative, confidence))
                    break
        return found

    def is_applicable(self, context) -> bool:
        """Needs BOTH an alternative to consider and conditions to compare against.

        An alternative with no actual state to compare it to is not a
        counterfactual, it is a wish, and there is nothing for the engine to
        evaluate. Refusing here means the engine selects no strategy rather than
        running one that can only return nothing.
        """
        return bool(self._alternatives(context)) and bool(context.facts)

    async def reason(self, context) -> List[ReasoningConclusion]:
        alternatives = self._alternatives(context)
        if not alternatives or not context.facts:
            return []

        engine = self.engine
        horizon = timedelta(hours=1)
        actual = engine.project_future_state(
            description="conditions as they actually stand",
            time_horizon=horizon,
            conditions=list(context.facts),
            probability=1.0)

        conclusions: List[ReasoningConclusion] = []
        for alternative, confidence in alternatives:
            # REACHABILITY MUST BE ABLE TO COME OUT FALSE.
            #
            # This passed `required_actions=[alternative]`, and
            # `evaluate_state_reachability` decides a missing condition is
            # achievable when it appears in some required action -- so listing
            # the alternative as its own action made it achievable BY
            # CONSTRUCTION. Every alternative came back reachable, reachable and
            # unreachable cases produced identical output, and the reachability
            # check could not fail. A gate that cannot fail measures nothing.
            #
            # The actions available are the ones the context actually declares:
            # its rules. If nothing known can bring the alternative about, then
            # it could not have obtained, and that is the honest answer rather
            # than a preference score computed over a world that was never
            # available.
            counterfactual = engine.project_future_state(
                description=f"had {alternative}",
                time_horizon=horizon,
                conditions=list(context.facts) + [alternative],
                required_actions=list(context.rules or ()),
                probability=confidence)

            comparison = engine.compare_future_states(actual, counterfactual)
            reachability = engine.evaluate_state_reachability(
                counterfactual, current_conditions=list(context.facts))

            preferred_alternative = comparison.get("preferred") == counterfactual.state_id
            reachable = bool(reachability.get("reachable"))
            difficulty = float(reachability.get("estimated_difficulty") or 0.0)

            # COMPUTED, not chosen. The premise's own confidence is the ceiling
            # on how seriously the alternative is taken; an alternative that
            # could not have obtained is discounted by how far out of reach it
            # was, and nothing here can exceed the structural ceiling.
            score = confidence * (1.0 if reachable else max(0.0, 1.0 - difficulty))
            score = min(score, self.STRUCTURAL_CONFIDENCE_CEILING)

            if reachable:
                verdict = ("would have been preferable" if preferred_alternative
                           else "would not have been preferable")
            else:
                missing = reachability.get("unachievable_conditions") or []
                verdict = (f"could not have obtained; unachievable: "
                           f"{sorted(str(m) for m in missing)[:3]}")

            conclusions.append(ReasoningConclusion(
                conclusion_id=str(uuid.uuid4()),
                statement=f"had {alternative}: {verdict}",
                confidence=score,
                origin="derived",
                reasoning_type=ReasoningType.COUNTERFACTUAL,
                inference_method=InferenceMethod.BIDIRECTIONAL,
                supporting_premises=[p.premise_id for p in context.premises],
                reasoning_steps=[
                    f"projected the actual state from {len(context.facts)} condition(s)",
                    f"projected the alternative: {alternative}",
                    f"reachable={reachable} difficulty={difficulty:.2f}",
                    f"preference difference "
                    f"{float(comparison.get('preference_score_difference') or 0.0):.3f}",
                ],
                logical_validity=score,
                evidence_strength=confidence,
                coherence_score=score))

        return conclusions



class SpatialReasoningStrategy(ReasoningStrategy):
    """Where things are in relation to each other, by composing stated relations.

    ReasoningType.SPATIAL was declared, selected by nothing, and -- unlike
    CAUSAL and COUNTERFACTUAL -- had no engine anywhere to delegate to. So this
    one is implemented rather than adapted.

    It is deliberately small. Spatial reasoning in general is a large field;
    what is implemented here is the part that is decidable from stated relations
    alone, with no geometry, no coordinates and no assumptions about the world:

        CONTAINMENT is transitive.   a in b, b in c  =>  a in c
        VERTICAL ORDER is transitive. a above b, b above c  =>  a above c
        ADJACENCY is symmetric but NOT transitive. a near b, b near c does not
            make a near c, and asserting it would be inventing a fact.

    That last line is the whole reason to write this rather than pattern-match:
    the useful thing a spatial reasoner does is know which relations compose and
    which do not. Deriving `a near c` would be exactly the plausible-but-wrong
    output the substrate exists to avoid.

    CONFIDENCE IS THE WEAKEST STEP, as in the causal chain: a containment
    derived through a 0.5 premise is not a 0.9 conclusion because the other
    premise was strong.
    """

    #: relation -> (surface forms, transitive?, symmetric?)
    #: Closed and visible. Each entry is a claim about how that relation
    #: composes, which is the part that has to be right.
    RELATIONS = {
        "inside": ((" is inside ", " is within ", " is in ", " inside ", " within "),
                   True, False),
        "contains": ((" contains ", " encloses ", " holds "), True, False),
        "above": ((" is above ", " is over ", " above ", " on top of "), True, False),
        "below": ((" is below ", " is under ", " below ", " beneath "), True, False),
        "near": ((" is near ", " is adjacent to ", " borders ", " next to "),
                 False, True),
    }

    #: Relations that are each other's converse. Recorded so "a contains b" and
    #: "b is inside a" are the same fact rather than two unrelated ones.
    CONVERSE = {"inside": "contains", "contains": "inside",
                "above": "below", "below": "above"}

    def __init__(self, neural_bridge=None):
        self.strategy_name = "spatial_reasoning"
        self.neural_bridge = neural_bridge

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def _stated(self, context) -> List[Tuple[str, str, str, float]]:
        """(relation, subject, object, confidence) for each spatial premise."""
        found = []
        for premise in context.premises:
            text = f" {str(getattr(premise, 'statement', '') or '').lower().strip()} "
            confidence = float(getattr(premise, "confidence", 1.0) or 1.0)
            for relation, (forms, _t, _s) in self.RELATIONS.items():
                hit = next((f for f in forms if f in text), None)
                if hit is None:
                    continue
                left, right = text.split(hit, 1)
                subject = left.strip(" .,")
                obj = right.strip(" .,")
                # "the cup is in the top cabinet" -- determiners are not part of
                # the thing's identity.
                for article in ("the ", "a ", "an "):
                    if subject.startswith(article):
                        subject = subject[len(article):]
                    if obj.startswith(article):
                        obj = obj[len(article):]
                if subject and obj:
                    found.append((relation, subject, obj, confidence))
                break
        return found

    def is_applicable(self, context) -> bool:
        return bool(self._stated(context))

    async def reason(self, context) -> List[ReasoningConclusion]:
        stated = self._stated(context)
        if not stated:
            return []

        # edges[relation][subject] -> {object: confidence}, with converses
        # folded in so both phrasings populate one graph.
        edges: Dict[str, Dict[str, Dict[str, float]]] = {}

        def add(relation: str, subject: str, obj: str, confidence: float):
            bucket = edges.setdefault(relation, {}).setdefault(subject, {})
            bucket[obj] = max(bucket.get(obj, 0.0), confidence)

        for relation, subject, obj, confidence in stated:
            add(relation, subject, obj, confidence)
            converse = self.CONVERSE.get(relation)
            if converse:
                add(converse, obj, subject, confidence)
            if self.RELATIONS[relation][2]:          # symmetric
                add(relation, obj, subject, confidence)

        conclusions: List[ReasoningConclusion] = []

        # A CONVERSE OF A STATED FACT IS NOT A DERIVATION.
        #
        # "the socket contains the chip" from "the chip is inside the socket" is
        # the same fact said the other way round. Reporting it as derived
        # inflated what the strategy found -- two premises produced four
        # "conclusions", half of them restatements -- and a caller counting
        # conclusions would read that as twice the inference actually done.
        # Symmetric relations are the same case in the same way.
        known = set()
        for relation, subject, obj, _confidence in stated:
            known.add((relation, subject, obj))
            converse = self.CONVERSE.get(relation)
            if converse:
                known.add((converse, obj, subject))
            if self.RELATIONS[relation][2]:          # symmetric
                known.add((relation, obj, subject))

        for relation, (_forms, transitive, _symmetric) in self.RELATIONS.items():
            if not transitive or relation not in edges:
                continue
            graph = edges[relation]
            # Closure by repeated composition. Bounded by the node count, so a
            # cycle in the premises terminates instead of looping.
            for _ in range(len(graph) + 1):
                grew = False
                for subject in list(graph):
                    for middle, first in list(graph[subject].items()):
                        for end, second in list(graph.get(middle, {}).items()):
                            if end == subject:
                                continue          # a inside a says nothing
                            step = min(first, second)
                            if step > graph[subject].get(end, 0.0):
                                graph[subject][end] = step
                                grew = True
                if not grew:
                    break

            for subject, reach in graph.items():
                for obj, confidence in reach.items():
                    if (relation, subject, obj) in known:
                        continue              # stated, not derived
                    conclusions.append(ReasoningConclusion(
                        conclusion_id=str(uuid.uuid4()),
                        statement=f"{subject} {relation} {obj}",
                        confidence=confidence,
                        origin="derived",
                        reasoning_type=ReasoningType.SPATIAL,
                        inference_method=InferenceMethod.FORWARD_CHAINING,
                        supporting_premises=[p.premise_id for p in context.premises],
                        reasoning_steps=[
                            f"{relation} composes transitively",
                            f"weakest step {confidence:.2f}"],
                        logical_validity=confidence,
                        evidence_strength=confidence,
                        coherence_score=confidence))

        return conclusions


class FuzzyReasoningStrategy(ReasoningStrategy):
    """Claims that hold BY DEGREE rather than sharply.

    ReasoningType.FUZZY was declared, selected by nothing, and had no engine to
    delegate to. Implemented here.

    THE POINT IS THAT DEGREE IS NOT CONFIDENCE, and conflating them is the
    mistake this exists to avoid. "the disk is mostly full" is not an uncertain
    claim about a sharp fact -- it is a certain claim about a graded one. A
    system with only confidence has to record it as "probably full", which is a
    different and false statement: it says the disk might be entirely full, and
    it might not be full at all.

    So a conclusion here carries BOTH. `truth_degree` in the metadata is how
    much the property holds; `confidence` is how sure we are of that degree, and
    comes from the premises. A premise stated with certainty about a graded
    property yields a certain conclusion about a partial truth.

    Standard Zadeh operators, because they are the ones that compose without
    needing a probability model nobody supplied:

        AND  min(a, b)        the weakest conjunct governs
        OR   max(a, b)
        NOT  1 - a

    HEDGES MODIFY THE DEGREE, not the confidence. `very` concentrates (d^2),
    `somewhat` dilates (d^0.5) -- Zadeh's own concentration and dilation. So
    "very full" is a stronger claim than "full", and "somewhat full" a weaker
    one, while both are equally certain if the speaker was equally certain.
    """

    #: Hedge -> what it does to the degree. Closed and small.
    #: (base_degree, exponent) -- a bare hedge sets a degree, a modifying hedge
    #: reshapes whatever degree the term already had.
    HEDGES = {
        "completely": (1.00, 1.0), "entirely": (1.00, 1.0), "fully": (1.00, 1.0),
        "mostly": (0.80, 1.0), "largely": (0.80, 1.0),
        "roughly": (0.70, 1.0), "approximately": (0.70, 1.0), "about": (0.70, 1.0),
        "partially": (0.50, 1.0), "somewhat": (0.50, 1.0), "partly": (0.50, 1.0),
        "slightly": (0.25, 1.0), "barely": (0.15, 1.0),
        "hardly": (0.10, 1.0), "scarcely": (0.10, 1.0),
        # modifiers: reshape rather than set
        "very": (None, 2.0), "extremely": (None, 3.0), "highly": (None, 2.0),
    }

    #: A claim with no hedge at all is sharp, and sharp claims are not this
    #: strategy's business -- deduction handles them.
    DEFAULT_DEGREE = 1.0

    def __init__(self, neural_bridge=None):
        self.strategy_name = "fuzzy_reasoning"
        self.neural_bridge = neural_bridge

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def _graded(self, context) -> List[Tuple[str, float, float]]:
        """(claim, truth_degree, confidence) for each hedged premise."""
        graded = []
        for premise in context.premises:
            words = str(getattr(premise, "statement", "") or "").lower().split()
            confidence = float(getattr(premise, "confidence", 1.0) or 1.0)
            degree = None
            exponent = 1.0
            for word in words:
                token = word.strip(" .,;:!?")
                if token not in self.HEDGES:
                    continue
                base, power = self.HEDGES[token]
                if base is None:
                    exponent *= power              # "very" reshapes
                else:
                    degree = base if degree is None else min(degree, base)
            if degree is None and exponent == 1.0:
                continue                            # no hedge: not a fuzzy claim
            if degree is None:
                degree = self.DEFAULT_DEGREE
            graded.append((" ".join(words), degree ** exponent, confidence))
        return graded

    def is_applicable(self, context) -> bool:
        """Needs at least one HEDGED premise. A sharp claim is deduction's job."""
        return bool(self._graded(context))

    async def reason(self, context) -> List[ReasoningConclusion]:
        graded = self._graded(context)
        if not graded:
            return []

        conclusions: List[ReasoningConclusion] = []
        for claim, degree, confidence in graded:
            conclusions.append(self._conclusion(
                statement=f"holds to degree {degree:.2f}: {claim}",
                degree=degree, confidence=confidence, context=context,
                method=InferenceMethod.FUZZY_LOGIC,
                steps=[f"hedged claim read at degree {degree:.2f}"]))

        # THE CONJUNCTION IS THE DERIVED PART. Each premise states its own
        # degree; what none of them states is how much they hold TOGETHER, and
        # under Zadeh that is the minimum -- the weakest conjunct governs, the
        # same shape as the weakest link in a causal chain.
        if len(graded) > 1:
            degrees = [d for _c, d, _f in graded]
            joint = min(degrees)
            weakest = graded[degrees.index(joint)][0]
            conclusions.append(self._conclusion(
                statement=f"all of them together hold to degree {joint:.2f}",
                degree=joint,
                confidence=min(f for _c, _d, f in graded),
                context=context, method=InferenceMethod.FUZZY_LOGIC,
                steps=[f"conjunction over {len(graded)} graded claims",
                       f"min-rule: governed by {weakest!r} at {joint:.2f}"]))

        return conclusions

    def _conclusion(self, *, statement, degree, confidence, context, method, steps):
        return ReasoningConclusion(
            conclusion_id=str(uuid.uuid4()),
            statement=statement,
            # CONFIDENCE, not degree. How sure we are that this degree is right
            # -- which comes from the premise, not from how true the claim is.
            confidence=confidence,
            origin="derived",
            reasoning_type=ReasoningType.FUZZY,
            inference_method=method,
            supporting_premises=[p.premise_id for p in context.premises],
            reasoning_steps=steps,
            logical_validity=confidence,
            evidence_strength=confidence,
            coherence_score=confidence)


class LogicalReasoningStrategy(ReasoningStrategy):
    """Is this PROVABLE from the premises as stated? Z3 decides.

    ReasoningType.LOGICAL was declared and registered by nothing, while
    `advanced_proof_engine` sat with a working Z3 theorem prover. The engine was
    reachable through `neural_bridge._symbolic_reasoning`, but nothing could ask
    for logical reasoning BY NAME through the strategy registry.

    DISTINCT FROM DEDUCTIVE, and the difference is not cosmetic.
    `DeductiveReasoningStrategy` applies rules forward from premises to see what
    follows. This asks a different question: is a specific target CONSISTENT
    with, and provable from, the premises as written? Forward chaining finds
    what it can reach; a prover settles a stated claim, including claims no
    forward chain would stumble onto.

    CONFIDENCE COMES FROM THE PROVER. `Proof.proved` is the verdict and
    `Proof.confidence` the engine's own score. Nothing here adds to it, and a
    failed proof produces NO conclusion rather than a low-confidence one --
    "not proved" is not evidence for the negation, and emitting it as a weak
    positive would be the single most misleading thing this strategy could do.
    """

    def __init__(self, neural_bridge=None):
        self.strategy_name = "logical_reasoning"
        self.neural_bridge = neural_bridge
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            from core.reasoning.advanced_proof_engine import get_proof_engine
            self._engine = get_proof_engine()
        return self._engine

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def is_applicable(self, context) -> bool:
        """Needs something to prove AND something to prove it from.

        A target with no premises is not a proof obligation, and premises with
        no target give the prover no question to answer.
        """
        return bool(context.target_conclusions) and bool(
            context.premises or context.facts or context.rules)

    async def reason(self, context) -> List[ReasoningConclusion]:
        if not self.is_applicable(context):
            return []

        from core.reasoning.advanced_proof_engine import LogicType, Theorem

        premises = ([str(p.statement) for p in context.premises]
                    + list(context.facts or ()) + list(context.rules or ()))

        conclusions: List[ReasoningConclusion] = []
        for target in context.target_conclusions:
            theorem = Theorem(
                theorem_id=f"thm_{uuid.uuid4().hex[:12]}",
                statement=str(target),
                premises=premises,
                logic_type=LogicType.PROPOSITIONAL)
            try:
                proof = await self.engine.prove_theorem(theorem)
            except Exception as error:
                logger.warning("proof attempt failed for %r: %s: %s",
                               target, type(error).__name__, error)
                continue

            if not getattr(proof, "proved", False):
                # NOT PROVED IS NOT DISPROVED, and it is not a weak yes either.
                # Emitting a low-confidence conclusion here would turn "the
                # prover could not settle this" into evidence, which is exactly
                # the fabrication this strategy exists to avoid.
                logger.info("not proved: %r (%s)", target,
                            getattr(proof, "error", None) or "no derivation found")
                continue

            confidence = float(getattr(proof, "confidence", 0.0) or 0.0)
            steps = [f"{s.step_number}. {s.statement}  [{s.justification}]"
                     for s in (getattr(proof, "steps", None) or [])]
            conclusions.append(ReasoningConclusion(
                conclusion_id=str(uuid.uuid4()),
                statement=f"Proved: {target}",
                confidence=confidence,
                origin="derived",
                reasoning_type=ReasoningType.LOGICAL,
                inference_method=InferenceMethod.RESOLUTION,
                supporting_premises=[p.premise_id for p in context.premises],
                reasoning_steps=steps or ["proved by the solver"],
                logical_validity=confidence,
                evidence_strength=confidence,
                coherence_score=confidence))

        return conclusions


class ProbabilisticReasoningStrategy(ReasoningStrategy):
    """How the evidence moves a belief, over the Bayesian engine.

    ReasoningType.PROBABILISTIC was declared and registered by nothing, while
    `bayesian_uncertainty` held a full belief system -- priors, likelihoods,
    posteriors, temporal decay and regime-shift detection -- reachable only as a
    constraint check inside `_hybrid_reasoning`, never as a kind of thinking
    somebody could ask for.

    THE PREMISES ARE THE EVIDENCE AND THEIR CONFIDENCES ARE REAL NUMBERS. A
    premise stated at 0.9 and one stated at 0.4 are different evidence, and this
    is the one strategy for which that difference IS the input rather than
    metadata about it.

    A premise is read as supporting or opposing the target by its polarity, and
    the engine does the updating. The posterior is the conclusion's confidence
    because that is what a posterior IS -- there is nothing to add to it.
    """

    #: Words that flip a premise from supporting the claim to opposing it.
    NEGATORS = ("not ", "no ", "never ", "fails", "failed", "absent", "without ")

    #: An actual PROBABILISTIC signal -- a stated probability/frequency, or a
    #: stated evidential RELATION between things. Its presence is what separates
    #: probabilistic evidence ("the smoke alarm reliably INDICATES fire") from a
    #: bare fact ("Socrates is human"), which is not evidence for a different
    #: claim ("Socrates is mortal") without a relation and must not move a belief.
    EVIDENTIAL_SIGNALS = frozenset({
        "probability", "probable", "probably", "likely", "unlikely", "chance",
        "odds", "posterior", "prior", "expected", "statistical", "hypothesis",
        "frequently", "usually", "often", "typically", "tends", "tend", "rate",
        "percent", "percentage", "distribution", "variance",
        "indicates", "indicate", "indicated", "suggests", "suggest", "implies",
        "imply", "predicts", "predict", "predictive", "signals", "signal",
        "means", "shows", "show", "evidence", "reliably", "reliable",
        "correlates", "correlate", "correlated", "associated", "estimate",
    })

    def __init__(self, neural_bridge=None):
        self.strategy_name = "probabilistic_reasoning"
        self.neural_bridge = neural_bridge
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            from core.reasoning.bayesian_uncertainty import get_uncertainty_system
            self._engine = get_uncertainty_system()
        return self._engine

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def _has_evidential_signal(self, context) -> bool:
        """Whether the premises or the query carry a probabilistic signal at all.

        Reads the raw text of every premise and target: a stated probability or
        frequency, or an evidential relation word. Without one there is nothing
        to update a belief WITH -- the premises are facts, not evidence bearing
        on the target."""
        words = set()
        for text in ([str(getattr(p, "statement", "") or "") for p in context.premises]
                     + [str(t) for t in (context.target_conclusions or [])]):
            words |= set(re.findall(r"[a-z]+", text.lower()))
        return bool(words & self.EVIDENTIAL_SIGNALS)

    def is_applicable(self, context) -> bool:
        """Needs a claim to hold a belief about, evidence to move it, and an
        ACTUAL evidential signal. A target with premises but no stated
        probability, frequency or indication is not a probabilistic problem;
        treating every non-negated premise as support fabricated a confident
        posterior (P=0.998 for 'Socrates is mortal' from premises that never
        mentioned mortality)."""
        return (bool(context.target_conclusions) and bool(context.premises)
                and self._has_evidential_signal(context))

    async def reason(self, context) -> List[ReasoningConclusion]:
        if not self.is_applicable(context):
            return []

        engine = self.engine
        # A PROBABILITY WORKED OUT TO ANSWER IS NOT A BELIEF HELD. This created a
        # shared belief for every target, every time, and moved it with whatever
        # premises it was given -- a person's context among them -- so reasoning
        # for one person wrote the world's beliefs past the one door
        # (docs/research/SEPARATION_MAP.md §11.6). The posterior is computed by
        # the belief system's own update, and nothing is written.
        from core.reasoning.bayesian_uncertainty import evidence_step, probability_of
        conclusions: List[ReasoningConclusion] = []

        for target in context.target_conclusions:
            held = 0.0   # even odds: nothing is assumed
            steps = ["prior 0.50 (no assumption made)"]

            for premise in context.premises:
                text = str(getattr(premise, "statement", "") or "").lower()
                weight = float(getattr(premise, "confidence", 1.0) or 1.0)
                supports = not any(n in f" {text} " for n in self.NEGATORS)
                held += evidence_step(weight, supports)
                steps.append(
                    f"{'for' if supports else 'against'} (q={weight:.2f}): "
                    f"{text[:48]} -> {probability_of(held):.3f}")

            posterior = probability_of(held)
            conclusions.append(ReasoningConclusion(
                conclusion_id=str(uuid.uuid4()),
                statement=f"P({target}) = {posterior:.3f}",
                # The posterior IS the confidence. Scaling it would be inventing
                # a second opinion about a number that already means exactly
                # this.
                confidence=posterior,
                origin="derived",
                reasoning_type=ReasoningType.PROBABILISTIC,
                inference_method=InferenceMethod.BAYESIAN_INFERENCE,
                supporting_premises=[p.premise_id for p in context.premises],
                reasoning_steps=steps,
                logical_validity=posterior,
                evidence_strength=posterior,
                coherence_score=posterior))

        return conclusions


class TemporalReasoningStrategy(ReasoningStrategy):
    """What holds always, eventually, before or after -- over temporal logic.

    ReasoningType.TEMPORAL was declared and registered by nothing.
    `temporal_reasoning.evaluate_temporal_formula` implements the operators and
    had ZERO callers in the repository; the only temporal selection anywhere was
    a private `is_temporal` keyword flag inside `_hybrid_reasoning`, which chose
    which ENGINE to load rather than answering a temporal question.

    An operator is read from the premise's own wording and evaluated against the
    timeline the other premises establish. ALWAYS over a timeline is a real
    check -- it fails the moment one proposition in the timeline is false --
    which is why the timeline is built from every premise rather than from the
    one being evaluated.
    """

    #: Surface form -> temporal operator. Closed, and each entry is a claim
    #: about which operator that word names.
    OPERATOR_WORDS = {
        "always": "ALWAYS", "constantly": "ALWAYS", "invariably": "ALWAYS",
        "never": "ALWAYS",
        "eventually": "EVENTUALLY", "sometime": "EVENTUALLY",
        "next": "NEXT", "until": "UNTIL", "since": "SINCE",
        "before": "BEFORE", "after": "AFTER", "during": "DURING",
    }

    def __init__(self, neural_bridge=None):
        self.strategy_name = "temporal_reasoning"
        self.neural_bridge = neural_bridge
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            from core.reasoning.temporal_reasoning import TemporalReasoningSystem
            self._engine = TemporalReasoningSystem()
        return self._engine

    def get_strategy_name(self) -> str:
        return self.strategy_name

    def _operator_of(self, text: str) -> Optional[str]:
        lowered = f" {text.lower()} "
        for word, operator in self.OPERATOR_WORDS.items():
            if f" {word} " in lowered:
                return operator
        return None

    def is_applicable(self, context) -> bool:
        return any(self._operator_of(str(getattr(p, "statement", "") or ""))
                   for p in context.premises)

    async def reason(self, context) -> List[ReasoningConclusion]:
        from core.reasoning.temporal_reasoning import TemporalOperator, TimePoint

        engine = self.engine
        # Bring prior temporal knowledge into memory (Postgres-backed) so
        # reasoning consults what earlier sessions established. Non-fatal.
        await engine.load()
        # WHOSE: a person's premises can be their own context, so what this
        # reasoning writes down is theirs.
        owner = context.origin("temporal reasoning").owner
        timeline = []
        for premise in context.premises:
            text = str(getattr(premise, "statement", "") or "")
            # "never X" asserts X is FALSE at every point; the operator is still
            # ALWAYS, the polarity is what differs.
            is_true = " never " not in f" {text.lower()} "
            timeline.append(engine.create_proposition(
                statement=text, time_point=TimePoint.PRESENT, is_true=is_true,
                confidence=float(getattr(premise, "confidence", 1.0) or 1.0),
                owner=owner))

        conclusions: List[ReasoningConclusion] = []
        for premise, proposition in zip(context.premises, timeline):
            text = str(getattr(premise, "statement", "") or "")
            name = self._operator_of(text)
            if name is None:
                continue
            operator = getattr(TemporalOperator, name, None)
            if operator is None:
                continue

            holds = engine.evaluate_temporal_formula(
                operator=operator, proposition=proposition,
                timeline_context=timeline)
            confidence = float(getattr(premise, "confidence", 1.0) or 1.0)
            conclusions.append(ReasoningConclusion(
                conclusion_id=str(uuid.uuid4()),
                statement=f"{name.lower()} holds: {text}" if holds
                          else f"{name.lower()} does NOT hold: {text}",
                confidence=confidence,
                origin="derived",
                reasoning_type=ReasoningType.TEMPORAL,
                inference_method=InferenceMethod.FORWARD_CHAINING,
                supporting_premises=[p.premise_id for p in context.premises],
                reasoning_steps=[
                    f"operator {name} read from the premise's wording",
                    f"evaluated against a timeline of {len(timeline)} proposition(s)",
                    f"result: {holds}"],
                logical_validity=confidence,
                evidence_strength=confidence,
                coherence_score=confidence))

        # Persist the timeline to the unified Postgres DB, off the critical
        # path and non-fatal -- the derivation above is complete regardless.
        await engine.persist()
        return conclusions

class AbstractReasoningEngine:
    """
    Advanced abstract reasoning engine for complex problem solving
    Integrates multiple reasoning strategies and inference methods
    """
    
    def __init__(self,
                 ontology: Optional[Any] = None,
                 domain_adapter: Optional[Any] = None,
                 learning_engine: Optional[Any] = None,
                 memory: Optional[Any] = None,
                 neural_bridge: Optional[Any] = None):

        self.engine_id = str(uuid.uuid4())

        # Core components
        self.ontology = ontology if ontology else UniversalOntology()
        self.domain_adapter = domain_adapter
        self.learning_engine = learning_engine
        self.memory = memory
        self.neural_bridge = neural_bridge

        # Reasoning strategies
        self.strategies: Dict[ReasoningType, ReasoningStrategy] = {}
        self._initialize_strategies()

        # Knowledge base
        self.knowledge_base = {
            "facts": [],
            "rules": [],
            "concepts": {},
            "relationships": {}
        }

        # Reasoning history
        self.reasoning_history: List[ReasoningResult] = []
        self.active_contexts: Dict[str, ReasoningContext] = {}

        # Performance metrics
        self.statistics = {
            "total_reasoning_operations": 0,
            "successful_operations": 0,
            "average_confidence": 0.0,
            "reasoning_types_used": {},
            "inference_methods_used": {},
            "total_reasoning_time": 0.0,
        }

        logger.info(f"Abstract Reasoning Engine initialized with domain knowledge: {self.engine_id}")
    
    async def initialize(self) -> bool:
        """
        Async initialization method for compatibility with autonomous coordinator.
        The engine is already initialized in __init__, so this just returns True.
        
        Returns:
            bool: Always returns True indicating successful initialization
        """
        return True
    
    def _initialize_strategies(self):
        """Initialize available reasoning strategies"""

        self.strategies[ReasoningType.DEDUCTIVE] = DeductiveReasoningStrategy(neural_bridge=self.neural_bridge)
        self.strategies[ReasoningType.INDUCTIVE] = InductiveReasoningStrategy(neural_bridge=self.neural_bridge)
        self.strategies[ReasoningType.ABDUCTIVE] = AbductiveReasoningStrategy(neural_bridge=self.neural_bridge)
        self.strategies[ReasoningType.ANALOGICAL] = AnalogicalReasoningStrategy(neural_bridge=self.neural_bridge)

        # CAUSAL and COUNTERFACTUAL were declared in ReasoningType and
        # registered by nothing, so a context allowing either selected no
        # strategy and silently produced no conclusions -- the defect
        # AbductiveReasoningStrategy records for ABDUCTIVE, twice more.
        #
        # Neither needed an algorithm written. `temporal_reasoning` already held
        # `establish_causal_link`, `trace_causal_chain`, `predict_effect`,
        # `project_future_state` and `compare_future_states`, every one of them
        # with ZERO callers in the repository. These two strategies are adapters
        # onto that engine; the reasoning stays where it already lived.
        self.strategies[ReasoningType.CAUSAL] = CausalReasoningStrategy(neural_bridge=self.neural_bridge)
        self.strategies[ReasoningType.COUNTERFACTUAL] = CounterfactualReasoningStrategy(neural_bridge=self.neural_bridge)

        # SPATIAL and FUZZY had no engine anywhere to delegate to, so unlike the
        # two above these are implemented rather than adapted. Both are
        # deliberately small and both refuse rather than guess: spatial composes
        # only the relations that actually compose (containment and vertical
        # order are transitive; adjacency is not), and fuzzy requires a hedged
        # premise, because a sharp claim is deduction's business.
        self.strategies[ReasoningType.SPATIAL] = SpatialReasoningStrategy(neural_bridge=self.neural_bridge)
        self.strategies[ReasoningType.FUZZY] = FuzzyReasoningStrategy(neural_bridge=self.neural_bridge)

        # The last three. Each had a complete engine that the registry could not
        # reach: Z3 in advanced_proof_engine, the belief system in
        # bayesian_uncertainty, and the temporal operators in
        # temporal_reasoning -- the last with zero callers anywhere. All three
        # were reachable only as constraint checks inside the bridge's hybrid
        # path, never as a kind of thinking anybody could ask for by name.
        self.strategies[ReasoningType.LOGICAL] = LogicalReasoningStrategy(neural_bridge=self.neural_bridge)
        self.strategies[ReasoningType.PROBABILISTIC] = ProbabilisticReasoningStrategy(neural_bridge=self.neural_bridge)
        self.strategies[ReasoningType.TEMPORAL] = TemporalReasoningStrategy(neural_bridge=self.neural_bridge)

        logger.info("Reasoning strategies registered: %d of %d classical kinds",
                    len(self.strategies), len(CLASSICAL_REASONING_TYPES))
        
        # Quantum reasoning DISABLED — requires IBM Quantum connection which is not configured
        # See autonomous_coordinator.py line 294: enable_quantum defaults to False
        self.quantum_reasoning_system = None
        logger.info("Quantum reasoning disabled (IBM Quantum connection not configured)")
        
        # Additional strategies would be added here
        logger.info(f"Initialized {len(self.strategies)} reasoning strategies")
    
    async def reason(self, context: ReasoningContext) -> ReasoningResult:
        """Execute reasoning operation with given context"""
        
        start_time = datetime.now().timestamp()
        result_id = str(uuid.uuid4())
        
        try:
            # WHAT IT IS REASONING ABOUT, not merely that it is reasoning. `Starting reasoning operation: <type>`
            # named the KIND of problem and never the problem: a reader could not tell what was asked, what was
            # given to work from, or -- when nothing came back -- whether there had been anything to work from at
            # all. An answer that took 5.6s of reasoning said nothing about what it reasoned over (2026-11-02).
            logger.info("reasoning: asked %s in %s -- %d premise(s), %d fact(s), %d rule(s), depth<=%d, conf>=%.2f",
                        context.problem_type, context.domain or "no domain", len(context.premises or ()),
                        len(context.facts or ()), len(context.rules or ()),
                        context.max_inference_depth, context.confidence_threshold)
            for _n, _premise in enumerate(context.premises or (), 1):
                logger.info("reasoning:   given %d. %s", _n, str(_premise)[:200])
            if not context.premises:
                logger.info("reasoning:   NOTHING WAS GIVEN TO REASON FROM")
            # THE WORKING TRAVELS WITH THE ANSWER, not only in the log. What was asked, what was given, what every
            # kind concluded, what was refused and at which step belong to the answer that came of them
            # (`ReasoningResult.intermediate_results`, which the bridge already carries out): a log is read by
            # whoever is watching the process, and in production nobody is, so an answer whose working exists only
            # at INFO has no working at all. Showing your work is the same answer with its working shown.
            working: List[Dict[str, Any]] = [{
                # Named as it is written, never as the enum object: the working is carried out of here into what the
                # bridge hands on, and an enum there is a value nothing downstream can write out.
                "asked": getattr(context.problem_type, "value", context.problem_type),
                "domain": context.domain,
                "given": [str(_p) for _p in (context.premises or ())],
                "facts": len(context.facts or ()),
                "rules": len(context.rules or ()),
                "depth_at_most": context.max_inference_depth,
                "confidence_at_least": context.confidence_threshold,
            }]

            self.active_contexts[context.context_id] = context
            
            # Initialize result
            result = ReasoningResult(
                result_id=result_id,
                context=context
            )
            
            # Select applicable strategies
            applicable_strategies = await self._select_strategies(context)
            
            if not applicable_strategies:
                result.error_message = "No applicable reasoning strategies found"
                return result
            
            # Execute reasoning with each strategy
            all_conclusions = []
            
            for reasoning_type, strategy in applicable_strategies:
                try:
                    strategy_conclusions = await strategy.reason(context)

                    # WHAT THE KIND CONCLUDED, AND WHAT WAS THROWN AWAY. A conclusion rejected by
                    # `_validate_conclusion` vanished without trace, so a kind that derived the right thing and had
                    # it refused looked identical to a kind that derived nothing -- and both came out as
                    # `no kind of thinking settled this`.
                    if not strategy_conclusions:
                        logger.info("reasoning:   %s concluded nothing", reasoning_type.value)
                        working.append({"kind": reasoning_type.value, "concluded": None})
                    for conclusion in strategy_conclusions:
                        # Validate conclusion
                        _ok = await self._validate_conclusion(conclusion, context)
                        # THAT IT CONCLUDED AND WHETHER IT WAS REFUSED is the line a reader needs, and stays here.
                        # The numbers it was judged by and the steps it took are the working, which goes on the
                        # answer (above) and is said here only to whoever asked for every detail.
                        logger.info("reasoning:   %s %s %r (conf=%.2f, via %s)", reasoning_type.value,
                                    "concluded" if _ok else "concluded BUT WAS REFUSED",
                                    str(conclusion.statement)[:160], conclusion.confidence,
                                    getattr(conclusion.inference_method, "value", conclusion.inference_method))
                        logger.debug("reasoning:     valid=%.2f evidence=%.2f coherence=%.2f from %d premise(s), "
                                     "%d step(s)", conclusion.logical_validity, conclusion.evidence_strength,
                                     conclusion.coherence_score, len(conclusion.supporting_premises or ()),
                                     len(conclusion.reasoning_steps or ()))
                        for _n, _step in enumerate(conclusion.reasoning_steps or (), 1):
                            logger.debug("reasoning:       step %d. %s", _n, str(_step)[:200])
                        working.append({
                            "kind": reasoning_type.value,
                            "concluded": str(conclusion.statement),
                            "kept": bool(_ok),
                            "refused_by": None if _ok else "validation",
                            "confidence": conclusion.confidence,
                            "logical_validity": conclusion.logical_validity,
                            "evidence_strength": conclusion.evidence_strength,
                            "coherence": conclusion.coherence_score,
                            "method": getattr(conclusion.inference_method, "value", conclusion.inference_method),
                            "from_premises": [str(_p) for _p in (conclusion.supporting_premises or ())],
                            "steps": [str(_s) for _s in (conclusion.reasoning_steps or ())],
                        })
                        if _ok:
                            all_conclusions.append(conclusion)

                            # Update statistics
                            strategy_name = reasoning_type.value
                            self.statistics["reasoning_types_used"][strategy_name] = \
                                self.statistics["reasoning_types_used"].get(strategy_name, 0) + 1
                            
                            method_name = conclusion.inference_method.value
                            self.statistics["inference_methods_used"][method_name] = \
                                self.statistics["inference_methods_used"].get(method_name, 0) + 1
                    
                except Exception as e:
                    logger.error(f"Error with strategy {reasoning_type.value}: {e}")
                    continue
            
            # Filter and rank conclusions
            filtered_conclusions = await self._filter_conclusions(all_conclusions, context)
            ranked_conclusions = await self._rank_conclusions(filtered_conclusions, context)

            # WHAT SURVIVED AND WHAT WON. Filtering and ranking both dropped and reordered conclusions in silence,
            # so the one conclusion that became the answer could not be told apart from the ones that did not, and a
            # conclusion lost at the filter looked exactly like one never derived.
            if len(filtered_conclusions) != len(all_conclusions):
                _gone = {id(c) for c in filtered_conclusions}
                _kept_statements = {str(c.statement) for c in filtered_conclusions}
                for _c in all_conclusions:
                    if id(_c) not in _gone:
                        logger.info("reasoning:   filtered out %r (%s, conf=%.2f)", str(_c.statement)[:140],
                                    getattr(_c.reasoning_type, "value", _c.reasoning_type), _c.confidence)
                        for _entry in working:
                            if _entry.get("concluded") == str(_c.statement) and _entry.get("kept") \
                                    and str(_c.statement) not in _kept_statements:
                                _entry["kept"], _entry["refused_by"] = False, "the filter"
            if ranked_conclusions:
                logger.info("reasoning: %d conclusion(s) kept of %d derived; answering with %r (%s, conf=%.2f)",
                            len(ranked_conclusions), len(all_conclusions), str(ranked_conclusions[0].statement)[:160],
                            getattr(ranked_conclusions[0].reasoning_type, "value",
                                    ranked_conclusions[0].reasoning_type), ranked_conclusions[0].confidence)
            else:
                logger.info("reasoning: NOTHING survived -- %d derived, %d past the filter",
                            len(all_conclusions), len(filtered_conclusions))

            result.conclusions = ranked_conclusions
            result.intermediate_results = working
            result.total_inferences = len(all_conclusions)
            
            # Calculate quality metrics
            await self._calculate_result_quality(result)
            
            # Determine success
            result.success = (len(result.conclusions) > 0 and 
                            result.overall_confidence >= context.confidence_threshold)
            
            # STAMP THE DURATION BEFORE ANY CONSUMER READS IT.
            #
            # This was assigned below, after _update_learning and
            # _store_in_memory had both already run, so each read the dataclass
            # default of 0.0: the learning lane scored the strategy on a zero
            # duration and the stored memory recorded a 21s derivation as
            # instantaneous. Measuring here also excludes the bookkeeping that
            # follows, which is not part of the reasoning being timed.
            reasoning_time = datetime.now().timestamp() - start_time
            result.reasoning_time = reasoning_time

            # Update learning
            if self.learning_engine and context.remembered:
                await self._update_learning(result)

            # Store in memory
            if self.memory and context.remembered:
                await self._store_in_memory(result)
            
            # Clean up
            if context.context_id in self.active_contexts:
                del self.active_contexts[context.context_id]
            
            # Update statistics
            self.statistics["total_reasoning_operations"] += 1
            if result.success:
                self.statistics["successful_operations"] += 1
            
            self.statistics["total_reasoning_time"] += reasoning_time
            
            # Calculate running average confidence
            if result.overall_confidence > 0:
                current_avg = self.statistics["average_confidence"]
                total_ops = self.statistics["total_reasoning_operations"]
                self.statistics["average_confidence"] = \
                    (current_avg * (total_ops - 1) + result.overall_confidence) / total_ops
            
            # Store result
            self.reasoning_history.append(result)
            
            logger.info(f"Reasoning completed: {len(result.conclusions)} conclusions, "
                       f"confidence: {result.overall_confidence:.2f}, time: {reasoning_time:.2f}s")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in reasoning operation: {e}")
            
            result = ReasoningResult(
                result_id=result_id,
                context=context,
                success=False,
                error_message=str(e),
                reasoning_time=datetime.now().timestamp() - start_time
            )
            
            return result
    
    async def explain_reasoning(self, result: Any) -> List[str]:
        """Render why each conclusion was reached, from the recorded derivation.

        IReasoningEngine declared this and nothing implemented it.

        The explanation is read out of what the strategies actually recorded --
        premises used, rules fired, competitors considered, how confidence was
        composed. It is never generated prose: an explanation that does not come
        from the derivation cannot be checked against it, and an unfaithful
        explanation is worse than none. Where a strategy recorded no steps, that
        is reported rather than filled in.
        """
        conclusions = getattr(result, "conclusions", None)
        if conclusions is None:
            conclusions = [result] if hasattr(result, "statement") else []
        if not conclusions:
            return ["No conclusions were reached, so there is no derivation to explain."]

        context = getattr(result, "context", None)
        premise_statements = {
            p.premise_id: p.statement for p in (getattr(context, "premises", None) or [])
        }

        lines: List[str] = []
        for index, conclusion in enumerate(conclusions, start=1):
            lines.append(f"{index}. {conclusion.statement}")
            lines.append(
                f"   via {conclusion.reasoning_type.value} reasoning "
                f"({conclusion.inference_method.value}), confidence {conclusion.confidence:.2f}"
            )

            used = [premise_statements.get(pid, pid) for pid in conclusion.supporting_premises]
            if used:
                lines.append(f"   from: {'; '.join(used)}")

            if conclusion.reasoning_steps:
                lines.extend(f"   step: {step}" for step in conclusion.reasoning_steps)
            else:
                lines.append("   step: none recorded — this strategy did not report its derivation")

            if conclusion.alternative_conclusions:
                lines.append(f"   competing: {', '.join(conclusion.alternative_conclusions)}")

            lines.append(
                f"   confidence composed of validity {conclusion.logical_validity:.2f}, "
                f"evidence {conclusion.evidence_strength:.2f}, "
                f"coherence {conclusion.coherence_score:.2f}"
            )

        return lines

    async def _select_strategies(self, context: ReasoningContext) -> List[Tuple[ReasoningType, ReasoningStrategy]]:
        """Select applicable reasoning strategies for the context"""
        
        applicable = []
        # WHICH KINDS, AND WHY NOT THE REST. This said `Selected 0 reasoning strategies` and nothing else, which is
        # the one case where the count answers nothing: 0 can mean the context allowed no kind, or that it allowed
        # kinds none of which said it could help, and those are different faults with different fixes. A substrate
        # that answered nothing logged `Selected 0 reasoning strategies` right after `tried deductive` and there was
        # no way to tell whether deductive had been excluded or had declined (2026-11-02).
        not_allowed, declined = [], []

        for reasoning_type, strategy in self.strategies.items():
            if reasoning_type not in context.allowed_reasoning_types:
                not_allowed.append(reasoning_type.value)
            elif not strategy.is_applicable(context):
                declined.append(reasoning_type.value)
            else:
                applicable.append((reasoning_type, strategy))

        # If no specific types are allowed, use all applicable
        if not context.allowed_reasoning_types:
            not_allowed, declined = [], []
            for reasoning_type, strategy in self.strategies.items():
                if strategy.is_applicable(context):
                    applicable.append((reasoning_type, strategy))
                else:
                    declined.append(reasoning_type.value)

        if applicable:
            logger.info("reasoning: %d kind(s) will be tried: %s",
                        len(applicable), ", ".join(t.value for t, _ in applicable))
        else:
            logger.info("reasoning: NO kind will be tried -- %d held; %s; %s",
                        len(self.strategies),
                        f"not allowed here: {', '.join(not_allowed)}" if not_allowed else "every kind was allowed",
                        f"said it could not help: {', '.join(declined)}" if declined else "none declined")
        return applicable
    
    async def _validate_conclusion(self, conclusion: ReasoningConclusion, context: ReasoningContext) -> bool:
        """Validate a reasoning conclusion"""
        
        try:
            if not conclusion.statement.strip():
                return False

            # Contradiction is checked for BOTH origins: a proposal that
            # contradicts what is known is worse than useless, and this is the
            # one check that reads something other than the conclusion's own
            # numbers.
            if await self._contradicts_knowledge(conclusion):
                return False

            # A PROPOSAL IS NOT GATED ON A CONFIDENCE IT DOES NOT HAVE.
            #
            # Model proposals carry confidence 0.0 and logical_validity 0.0 --
            # not because they are judged worthless, but because nothing has
            # judged them at all. Applying the derived-conclusion thresholds to
            # them would drop every one, which would silently delete the model
            # path rather than demote it, and would look identical to the model
            # having produced nothing.
            #
            # So a proposal survives validation and travels marked. It cannot
            # be mistaken for an established conclusion: it is ranked below
            # every derived one, contributes nothing to overall_confidence, and
            # carries origin="proposed" for any caller that asks.
            if getattr(conclusion, "origin", "derived") == "proposed":
                return True

            if conclusion.confidence < context.confidence_threshold:
                return False

            if conclusion.logical_validity < 0.3:
                return False

            return True
            
        except Exception as e:
            logger.error(f"Error validating conclusion: {e}")
            return False
    
    async def _contradicts_knowledge(self, conclusion: ReasoningConclusion) -> bool:
        """Check if conclusion contradicts existing knowledge"""
        
        # Simple contradiction check (would be more sophisticated)
        conclusion_words = set(conclusion.statement.lower().split())
        
        for fact in self.knowledge_base["facts"]:
            fact_words = set(fact.lower().split())
            
            # Look for explicit negations
            if ("not" in conclusion_words and 
                len(conclusion_words & fact_words) > len(conclusion_words) * 0.5):
                return True
        
        return False
    
    async def _filter_conclusions(self, conclusions: List[ReasoningConclusion], context: ReasoningContext) -> List[ReasoningConclusion]:
        """Filter conclusions based on quality and relevance"""
        
        filtered = []
        
        for conclusion in conclusions:
            # Proposals are kept and marked; see _validate_conclusion for why
            # the derived thresholds must not be applied to them.
            if getattr(conclusion, "origin", "derived") == "proposed":
                filtered.append(conclusion)
                continue

            if (conclusion.confidence >= context.confidence_threshold and
                conclusion.logical_validity >= 0.3 and
                conclusion.coherence_score >= 0.3):
                filtered.append(conclusion)
        
        # Remove duplicates
        unique_conclusions = []
        seen_statements = set()
        
        for conclusion in filtered:
            if conclusion.statement not in seen_statements:
                unique_conclusions.append(conclusion)
                seen_statements.add(conclusion.statement)
        
        logger.info(f"Filtered {len(conclusions)} conclusions to {len(unique_conclusions)}")
        return unique_conclusions
    
    async def _rank_conclusions(self, conclusions: List[ReasoningConclusion], context: ReasoningContext) -> List[ReasoningConclusion]:
        """Rank conclusions by quality and relevance"""
        
        # Calculate composite scores
        for conclusion in conclusions:
            quality_score = (conclusion.confidence * 0.4 +
                           conclusion.logical_validity * 0.3 +
                           conclusion.evidence_strength * 0.2 +
                           conclusion.coherence_score * 0.1)
            
            # `hasattr` is always True here -- composite_score is a declared
            # dataclass field -- so the guard never did anything. Assigned
            # directly.
            conclusion.composite_score = quality_score

        # DERIVED OUTRANKS PROPOSED, ALWAYS. Not by score: a proposal has no
        # score to compete with, and sorting on composite alone would put
        # every proposal (0.0) below every derived conclusion only by
        # accident of arithmetic. Stating it as the primary sort key makes it
        # a property of the ordering rather than a coincidence.
        #
        # A CERTAIN CONCLUSION OUTRANKS A DEGREE OR A BELIEF. Probabilistic and
        # fuzzy answer "how likely" / "to what degree"; every other kind answers
        # "what follows" / "what is the case". When more than one kind derived
        # something for the same question -- probabilistic's is_applicable is
        # `target and premises`, so it fires on any premise, including a purely
        # deductive one -- the certain answer must win. Otherwise a deductively
        # PROVABLE fact ("mortal(socrates)") is displaced by a probability
        # estimate of it ("P = 0.953"), which is the weaker statement of the two.
        # This changes nothing when a single kind fires (the caller forced a
        # kind, or only one was applicable): it only breaks the tie when a degree
        # kind competes with a certain one.
        _DEGREE_KINDS = {ReasoningType.PROBABILISTIC, ReasoningType.FUZZY}
        ranked = sorted(
            conclusions,
            key=lambda c: (getattr(c, "origin", "derived") == "derived",
                           getattr(c, "reasoning_type", None) not in _DEGREE_KINDS,
                           getattr(c, "composite_score", 0.0)),
            reverse=True)

        return ranked
    
    async def _calculate_result_quality(self, result: ReasoningResult):
        """Calculate quality metrics for the reasoning result"""
        
        if not result.conclusions:
            result.overall_confidence = 0.0
            result.logical_consistency = 0.0
            result.completeness_score = 0.0
            return
        
        # QUALITY IS MEASURED OVER DERIVED CONCLUSIONS ONLY.
        #
        # Averaging model proposals in here is what carried a model's opinion
        # of itself all the way into the memory store: `overall_confidence` is
        # the stored memory's confidence and its importance_score. A proposal
        # has no confidence to contribute, and
        # counting it as 0.0 would be just as wrong in the other direction --
        # it would drag down conclusions that WERE derived. So proposals are
        # excluded from the average rather than scored into it.
        derived = [c for c in result.conclusions
                   if getattr(c, "origin", "derived") == "derived"]

        if not derived:
            # Proposals only. Nothing has been established, and that is the
            # honest reading -- not "confidence 0.7 because the model said so".
            result.overall_confidence = 0.0
            result.logical_consistency = 0.0
        else:
            result.overall_confidence = sum(c.confidence for c in derived) / len(derived)
            result.logical_consistency = (
                sum(c.logical_validity for c in derived) / len(derived))
        
        # Calculate completeness (how well it addresses the context goals)
        if result.context.target_conclusions:
            addressed_goals = 0
            for target in result.context.target_conclusions:
                for conclusion in result.conclusions:
                    if target.lower() in conclusion.statement.lower():
                        addressed_goals += 1
                        break
            result.completeness_score = addressed_goals / len(result.context.target_conclusions)
        else:
            result.completeness_score = 0.5  # Neutral score when no specific goals
    
    async def _update_learning(self, result: ReasoningResult):
        """Update learning engine with reasoning results"""
        
        try:
            if not self.learning_engine:
                return
            
            # Create learning data
            #
            # THE OUTCOME BELONGS AT THE TOP LEVEL. UnifiedLearningSystem.
            # learn_from_example reads 'success', 'accuracy', 'confidence',
            # 'domain' and 'content' there. Nested under "output" they were
            # invisible to it, so a valid derivation at confidence 1.0 arrived
            # stating no outcome at all, was classified INSUFFICIENT_EVIDENCE,
            # and the strategy's posterior was left unchanged -- every reasoning
            # result this engine has ever produced. The nested blocks are kept:
            # they are the detail, and these are the fields the consumer reads.
            learning_data = {
                "reasoning_type": "abstract_reasoning",
                # This engine knows what kind of work it did. Left unstated it
                # arrived as CONTINUAL -> SEQUENCE and every derivation was
                # scored against the sequence arms; the reasoning arms
                # (reasoning_few_shot, reasoning_meta, ...) are the ones whose
                # posteriors this outcome is actually evidence about.
                "task_family": "reasoning",
                "success": result.success,
                # How good the conclusions were, not how sure we are of them --
                # this becomes performance_score for the selected strategy.
                "accuracy": result.logical_consistency,
                "confidence": result.overall_confidence,
                # Opens the cross-domain transfer path, which is gated on the
                # domain and so never fired from here.
                "domain": result.context.domain,
                # Without this the stored memory is str(dict)[:200] -- the
                # observed row was cut mid-key at 212 chars.
                "content": (
                    f"Abstract reasoning ({result.context.problem_type}) in "
                    f"{result.context.domain}: {len(result.conclusions)} "
                    f"conclusion(s) from {len(result.context.premises)} "
                    f"premise(s), {len(result.context.rules)} rule(s)"
                    + (" — " + "; ".join(c.statement for c in result.conclusions[:3])
                       if result.conclusions else "")
                ),
                "source": "abstract_reasoning",
                # Whose reasoning it was: the content names that actor's
                # premises, so the record learning keeps of it is theirs.
                "actor": result.context.actor,
                # The duration of the REASONING, so the strategy is scored on
                # the time its work took rather than on the learning system's
                # own bookkeeping.
                "duration_s": result.reasoning_time,
                "input": {
                    "context": result.context.problem_type,
                    "premises_count": len(result.context.premises),
                    "rules_count": len(result.context.rules)
                },
                "output": {
                    "conclusions_count": len(result.conclusions),
                    "success": result.success,
                    "confidence": result.overall_confidence
                },
                "performance": {
                    "reasoning_time": result.reasoning_time,
                    "logical_consistency": result.logical_consistency,
                    "completeness": result.completeness_score
                }
            }
            
            # Submit to learning engine
            await self.learning_engine.learn_from_experience(learning_data)
            
        except Exception as e:
            logger.error(f"Error updating learning: {e}")
    
    async def _store_in_memory(self, result: ReasoningResult):
        """
        Hand a reasoning result to the memory agent: what was concluded, how, and
        what it rested on. Whether it is worth keeping, and why, is the memory
        agent's (`MemoryAgent.store_memory`); this engine wrote its own account of
        why it should be stored, with its own complexity, novelty and impact, until
        2026-10-23.
        """

        try:
            if not self.memory:
                return

            from core.memory.utils.interfaces import MemoryType

            # Aggregate reasoning_steps from all conclusions (chain of thought)
            all_reasoning_steps = []
            for c in result.conclusions:
                if c.reasoning_steps:
                    all_reasoning_steps.extend(c.reasoning_steps)

            # Build content summary
            content_summary = f"Reasoning result for {result.context.problem_type} in {result.context.domain}"
            if result.conclusions:
                content_summary += f": {result.conclusions[0].statement}"

            # What happened, as it happened: the memory agent judges it.
            thinking_state = {
                "result_id": result.result_id,
                "reasoning_time": result.reasoning_time,
                "total_inferences": result.total_inferences,
                "confidence_distribution": result.confidence_distribution,
                # RICH METADATA: Outcome of this reasoning operation
                "outcome": {
                    "action_type": "reasoning_conclusion",
                    "action_summary": f"Reached {len(result.conclusions)} conclusions via {', '.join([rt.value for rt in result.context.reasoning_types])} reasoning",
                    "affected_components": ["reasoning_engine", result.context.domain, "knowledge_base"],
                    "confidence": result.overall_confidence,
                    "verification_status": "unverified",
                    "success_criteria": {
                        "min_confidence": result.context.confidence_threshold,
                        "logical_consistency": result.logical_consistency,
                        "completeness": result.completeness_score,
                        "conclusions_reached": len(result.conclusions) > 0
                    }
                }
            }

            decision_factors = {
                "context_domain": result.context.domain,
                "problem_type": result.context.problem_type,
                "premises_count": len(result.context.premises),
                "reasoning_types": [rt.value for rt in result.context.reasoning_types],
                # RICH METADATA: Why these specific reasoning types were used
                "reasoning_selection": {
                    "chosen_types": [rt.value for rt in result.context.reasoning_types],
                    "selection_rationale": f"Selected based on problem type '{result.context.problem_type}' and available premises",
                    "inference_methods_used": list(set([c.inference_method.value for c in result.conclusions])) if result.conclusions else [],
                    "alternative_approaches": ["pure_logical", "pure_probabilistic", "pure_analogical"]
                }
            }

            emotional_context = {
                "overall_confidence": result.overall_confidence,
                "logical_consistency": result.logical_consistency,
                "completeness_score": result.completeness_score
            }

            # Store to memory agent with full chain of thought
            success, memory_id = await self.memory.store_memory(
                memory_type=MemoryType.SEMANTIC,
                content=content_summary,
                # Reasoned for a user, over premises that may be their own
                # context: their memory, not the shared mind's.
                origin=result.context.origin("reasoning"),
                confidence_score=result.overall_confidence,
                tags=["reasoning", result.context.problem_type, result.context.domain],
                source_context={
                    # ORIGIN TRAVELS INTO MEMORY WITH THE CONCLUSION.
                    # A stored record that does not say whether a statement was
                    # derived or merely proposed cannot be re-read correctly
                    # later, and recall would hand a model's suggestion back as
                    # something Lyric concluded.
                    "conclusions": [
                        {
                            "statement": c.statement,
                            "confidence": c.confidence,
                            "origin": getattr(c, "origin", "derived"),
                            "reasoning_type": c.reasoning_type.value,
                            "supporting_premises": c.supporting_premises
                        }
                        for c in result.conclusions
                    ],
                    "intermediate_results": result.intermediate_results
                },
                reasoning_trace=all_reasoning_steps,
                thinking_state=thinking_state,
                decision_factors=decision_factors,
                emotional_context=emotional_context
            )

            if success:
                logger.debug(f"Reasoning result stored to memory: {memory_id}")

        except Exception as e:
            logger.error(f"Error storing in memory: {e}")

    
    # Public API methods
    
    def create_context(self,
                      domain: str,
                      problem_type: str,
                      premises: List[str],
                      rules: Optional[List[str]] = None,
                      facts: Optional[List[str]] = None,
                      reasoning_types: Optional[List[ReasoningType]] = None,
                      confidence_threshold: float = 0.5) -> ReasoningContext:
        """Create a reasoning context"""
        
        context_id = str(uuid.uuid4())
        
        # Convert premise strings to ReasoningPremise objects
        premise_objects = []
        for i, premise_text in enumerate(premises):
            premise = ReasoningPremise(
                premise_id=f"{context_id}_premise_{i}",
                statement=premise_text
            )
            premise_objects.append(premise)
        
        context = ReasoningContext(
            context_id=context_id,
            domain=domain,
            problem_type=problem_type,
            premises=premise_objects,
            rules=rules or [],
            facts=facts or [],
            allowed_reasoning_types=reasoning_types or list(ReasoningType),
            confidence_threshold=confidence_threshold
        )
        
        return context
    
    def add_knowledge(self, facts: List[str], rules: List[str]):
        """Add knowledge to the reasoning engine"""
        
        self.knowledge_base["facts"].extend(facts)
        self.knowledge_base["rules"].extend(rules)
        
        logger.info(f"Added {len(facts)} facts and {len(rules)} rules to knowledge base")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get reasoning engine statistics"""
        
        return {
            "engine_id": self.engine_id,
            "total_operations": self.statistics["total_reasoning_operations"],
            "successful_operations": self.statistics["successful_operations"],
            "success_rate": (self.statistics["successful_operations"] / 
                           max(1, self.statistics["total_reasoning_operations"])),
            "average_confidence": self.statistics["average_confidence"],
            "total_reasoning_time": self.statistics["total_reasoning_time"],
            "average_reasoning_time": (self.statistics["total_reasoning_time"] / 
                                     max(1, self.statistics["total_reasoning_operations"])),
            "reasoning_types_used": self.statistics["reasoning_types_used"].copy(),
            "inference_methods_used": self.statistics["inference_methods_used"].copy(),
            "knowledge_base_size": {
                "facts": len(self.knowledge_base["facts"]),
                "rules": len(self.knowledge_base["rules"])
            },
            "active_contexts": len(self.active_contexts)
        }
    
    def get_reasoning_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get reasoning operation history"""

        history = self.reasoning_history[-limit:] if limit else self.reasoning_history

        return [
            {
                "result_id": result.result_id,
                "domain": result.context.domain,
                "problem_type": result.context.problem_type,
                "conclusions_count": len(result.conclusions),
                "overall_confidence": result.overall_confidence,
                "success": result.success,
                "reasoning_time": result.reasoning_time,
                "timestamp": result.timestamp
            }
            for result in history
        ]


# EVERY KIND OF THINKING SAYS IT IS THINKING, AND WHAT IT COST.
#
# Eight of the twelve strategies held NOT ONE logger call: causal reasoning is 113 lines and said nothing, spatial
# 80 and said nothing, counterfactual 80 and said nothing. So a question could be reasoned about at length and the
# only trace was the engine's own count of how many kinds it picked -- never which kind ran, what it looked at, how
# long it took, or whether it concluded anything. `no kind of thinking settled this (tried deductive)` was the whole
# of what a failed reasoning said about itself.
#
# Wrapped here, once, over the kinds the engine registers, so the log shows the order they were tried in and where
# the time went. `is_applicable` is wrapped too, because the interesting answer is often that a kind declined before
# it did any work at all. Entry and cost are at DEBUG; a kind that takes longer than `SLOW_STEP_MS` says so at INFO,
# and one still running says so from a thread while it runs (`trace_step`) -- which is the only way a kind that does
# not finish can be named, since reasoning is CPU-bound and holds the event loop while it thinks.
#
# NOTHING IS CAPPED, BOUNDED OR TIMED OUT HERE. A kind that thinks for an hour still thinks for an hour.
from core.learning.performance_profiler import trace_step as _trace_step

for _strategy_class in (DeductiveReasoningStrategy, InductiveReasoningStrategy, AbductiveReasoningStrategy,
                        AnalogicalReasoningStrategy, CausalReasoningStrategy, CounterfactualReasoningStrategy,
                        SpatialReasoningStrategy, FuzzyReasoningStrategy, LogicalReasoningStrategy,
                        ProbabilisticReasoningStrategy, TemporalReasoningStrategy):
    #: `DeductiveReasoningStrategy` -> `deductive`, which is what the engine and the log already call the kind.
    _kind = _strategy_class.__name__.replace("ReasoningStrategy", "").lower()
    for _part in ("reason", "is_applicable"):
        _was = _strategy_class.__dict__.get(_part)
        if callable(_was):
            setattr(_strategy_class, _part, _trace_step("thinking", f"{_kind}.{_part}")(_was))
del _strategy_class, _kind, _part, _was

# The engine's own pipeline, in the order `reason()` runs it: choose the kinds, run each, keep what validates, then
# filter, rank, score, learn and store. A name not on the class is skipped rather than guessed at.
for _part in ("reason", "_select_strategies", "_validate_conclusion", "_filter_conclusions", "_rank_conclusions",
              "_calculate_result_quality", "_update_learning", "_store_in_memory"):
    _was = AbstractReasoningEngine.__dict__.get(_part)
    if callable(_was):
        setattr(AbstractReasoningEngine, _part, _trace_step("reasoning", _part)(_was))
del _part, _was


# Export main classes and functions
__all__ = [
    "AbstractReasoningEngine",
    "ReasoningType",
    "InferenceMethod", 
    "ConfidenceLevel",
    "ReasoningPremise",
    "ReasoningConclusion",
    "ReasoningContext",
    "ReasoningResult",
    "ReasoningStrategy",
    "DeductiveReasoningStrategy",
    "InductiveReasoningStrategy", 
    "AnalogicalReasoningStrategy",
    "create_abstract_reasoning_engine"
]


def create_abstract_reasoning_engine(config: Optional[Dict[str, Any]] = None) -> AbstractReasoningEngine:
    """
    Factory function to create an AbstractReasoningEngine instance with VLM support

    Args:
        config: Optional configuration dictionary

    Returns:
        AbstractReasoningEngine: Configured reasoning engine instance with VLM
    """
    if config is None:
        config = {}

    # Get neural bridge for automatic memory capture
    neural_bridge = None
    try:
        from core.reasoning.neural_bridge import get_neural_bridge
        neural_bridge = get_neural_bridge()
        logger.info("AbstractReasoningEngine will route through neural bridge")
    except Exception as e:
        logger.warning(f"Could not get neural bridge: {e}")

    # Learning engine — the consumer of _update_learning.
    #
    # This parameter was never supplied by the only construction site, so
    # `_update_learning` returned at its `if not self.learning_engine` guard on
    # every reasoning result the coordinator has ever produced. The engine and
    # the method it calls both exist; nothing connected them.
    from core.learning import get_unified_learning_system
    learning_engine = get_unified_learning_system()

    # Create engine with VLM support
    engine = AbstractReasoningEngine(
        neural_bridge=neural_bridge,
        learning_engine=learning_engine
    )

    logger.info(f"Created AbstractReasoningEngine with config: {config}")
    return engine


_abstract_reasoning_engine: Optional[AbstractReasoningEngine] = None


def get_abstract_reasoning_engine() -> AbstractReasoningEngine:
    """The shared AbstractReasoningEngine. ONE instance so its per-kind stats
    ACCUMULATE (a fresh engine per reason() call reset them every time, which is
    why they read as empty and were never health-probed). The reasoning authority
    and the health monitor both reach this."""
    global _abstract_reasoning_engine
    if _abstract_reasoning_engine is None:
        _abstract_reasoning_engine = create_abstract_reasoning_engine()
    return _abstract_reasoning_engine
