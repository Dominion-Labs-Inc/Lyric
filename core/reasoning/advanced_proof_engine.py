#!/usr/bin/env python3
"""
Advanced Proof Engine
=====================
Formal theorem proving and logical verification system

Features:
- Automated theorem proving
- Proof verification
- Logical inference
- Constraint solving
"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
from enum import Enum

try:
    # Optional SMT backend for industrial-strength proving/constraints
    from z3 import Solver, Bool, And, Or, Not, Implies, sat  # type: ignore
    _Z3_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Solver = None  # type: ignore
    Bool = And = Or = Not = Implies = sat = None  # type: ignore
    _Z3_AVAILABLE = False

logger = logging.getLogger(__name__)


#: The proof was requested from a backend that is not present. NOT a refutation.
CAPABILITY_UNAVAILABLE = "capability_unavailable"
#: A negative from natural deduction, which is sound but incomplete (it has no
#: case split). "I could not derive it" is not "it does not follow".
NEGATIVE_NOT_AUTHORITATIVE = "negative_not_authoritative"
#: Natural deduction DERIVED the goal with sound rules and the solver found a
#: countermodel. One of them is wrong; neither is allowed to win silently.
PROVERS_DISAGREE = "provers_disagree"
#: The closing statement of a proof by contradiction.
BOTTOM = ("bottom",)


@dataclass
class ProofVerification:
    """The outcome of checking a proof, with what could not be checked."""

    verified: bool
    reason: str
    method: Optional["ProofMethod"] = None
    failed_step: Optional[int] = None
    unchecked_steps: List[int] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.verified


class ProofMethod(Enum):
    """Proof methods"""
    DIRECT = "direct"
    CONTRADICTION = "contradiction"
    INDUCTION = "induction"
    RESOLUTION = "resolution"
    NATURAL_DEDUCTION = "natural_deduction"
    SMT = "smt"  # Z3-backed SMT solving


class LogicType(Enum):
    """Logic types"""
    PROPOSITIONAL = "propositional"
    FIRST_ORDER = "first_order"
    MODAL = "modal"
    TEMPORAL = "temporal"


@dataclass
class Axiom:
    """Logical axiom"""
    axiom_id: str
    statement: str
    logic_type: LogicType
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Theorem:
    """Theorem to prove"""
    theorem_id: str
    statement: str
    premises: List[str] = field(default_factory=list)
    logic_type: LogicType = LogicType.PROPOSITIONAL
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProofStep:
    """Single step in proof"""
    step_number: int
    statement: str
    justification: str
    rule_applied: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Proof:
    """Complete proof"""
    theorem_id: str
    proved: bool

    steps: List[ProofStep] = field(default_factory=list)
    method: ProofMethod = ProofMethod.DIRECT
    confidence: float = 0.0

    execution_time: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    #: A natural-deduction derivation of the same theorem, when one exists: every
    #: step names its rule and cites the steps it came from, so it can be
    #: re-checked without trusting the prover. On an SMT proof this is the
    #: independent, human-readable account of WHY the solver's verdict holds.
    derivation: List[ProofStep] = field(default_factory=list)
    derivation_method: Optional[ProofMethod] = None
    #: How the two provers stood: "both", "solver_only" (beyond the natural-
    #: deduction rules), "derivation_only" (the solver was undecided), or
    #: "disagree". None where only one prover ran.
    agreement: Optional[str] = None

    #: WHICH PREMISES THE PROOF ACTUALLY NEEDED -- indices into
    #: `Theorem.premises`, from the solver's minimised unsat core.
    #:
    #: Every given premise used to be emitted as a `Premise` step, so "what did
    #: this proof rest on" could only ever be answered with "everything it was
    #: handed". Downstream that became a false claim: the reply cited every
    #: recalled sentence as support. None where it was not computed (a non-SMT
    #: strategy, or a goal that was not proved) -- never an empty list standing
    #: in for "unknown", because empty means the goal needed no premise at all.
    premises_used: Optional[List[int]] = None


class AdvancedProofEngine:
    """
    Advanced Theorem Proving Engine

    Capabilities:
    - Automated theorem proving
    - Multiple proof strategies
    - Logical inference
    - Proof verification
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Knowledge base
        self.axioms: Dict[str, Axiom] = {}
        self.theorems: Dict[str, Theorem] = {}
        self.proofs: Dict[str, Proof] = {}

        # Inference rules
        self.inference_rules = self._initialize_inference_rules()

        # Statistics
        self.stats = {
            'total_proofs': 0,
            'successful_proofs': 0,
            'failed_proofs': 0
        }

        logger.info("AdvancedProofEngine initialized")

    def _initialize_inference_rules(self) -> Dict[str, Any]:
        """The rules natural deduction FIRES and the checker RE-CHECKS -- exactly
        these, so the table is a statement of fact rather than an aspiration.
        (It used to list hypothetical syllogism and resolution, which nothing
        implemented.) Every rule is sound; the set has no case split, so it is
        incomplete, and a failure to derive is never a refutation."""
        return {
            'modus_ponens': {'pattern': '(A -> B), A |- B'},
            'modus_tollens': {'pattern': '(A -> B), ~B |- ~A'},
            'and_elim': {'pattern': '(A & B) |- A ; (A & B) |- B'},
            'disjunctive_syllogism': {'pattern': '(A | B), ~A |- B'},
            'iff_elim': {'pattern': '(A <-> B) |- (A -> B) ; |- (B -> A)'},
            'double_negation': {'pattern': '~~A |- A'},
            'not_implies': {'pattern': '~(A -> B) |- A ; |- ~B'},
            'not_or': {'pattern': '~(A | B) |- ~A ; |- ~B'},
            'not_and': {'pattern': '~(A & B), A |- ~B'},
            'and_intro': {'pattern': 'A, B |- (A & B)'},
            'or_intro': {'pattern': 'A |- (A | B)'},
            'contradiction': {'pattern': 'A, ~A |- bottom'},
        }

    @property
    def z3_available(self) -> bool:
        """Return True if Z3 backend is available."""
        return _Z3_AVAILABLE

    async def prove_theorem(
        self,
        theorem: Theorem,
        max_steps: int = 100,
        timeout: float = 30.0
    ) -> Proof:
        """
        Attempt to prove theorem

        Args:
            theorem: Theorem to prove
            max_steps: Maximum proof steps
            timeout: Timeout in seconds

        Returns:
            Proof result
        """
        start_time = datetime.now()
        self.stats['total_proofs'] += 1

        logger.info(f"Proving theorem: {theorem.theorem_id}")

        try:
            # Store theorem
            self.theorems[theorem.theorem_id] = theorem

            # TWO PROVERS, NEITHER A STAND-IN FOR THE OTHER. The solver decides
            # entailment completely; natural deduction produces a derivation
            # whose every step can be re-checked without trusting either prover.
            # Where the solver applies, both run and are reconciled. Where it
            # does not (absent, or a logic it does not decide), natural deduction
            # runs on its own: its proofs are sound, and its failures are marked
            # as the non-refutations they are.
            if self._select_proof_method(theorem) is ProofMethod.SMT:
                derived = await self._natural_deduction(theorem, max_steps)
                solved = await self._smt_proof(theorem, max_steps, timeout)
                proof = self._reconcile(solved, derived)
            else:
                proof = await self._natural_deduction(theorem, max_steps)

            # Calculate execution time
            proof.execution_time = (datetime.now() - start_time).total_seconds()

            # Store proof
            self.proofs[theorem.theorem_id] = proof

            # Update statistics
            if proof.proved:
                self.stats['successful_proofs'] += 1
                logger.info(f"✓ Theorem proved: {theorem.theorem_id} ({len(proof.steps)} steps)")
            else:
                self.stats['failed_proofs'] += 1
                logger.warning(f"✗ Theorem not proved: {theorem.theorem_id}")

            return proof

        except Exception as e:
            logger.error(f"Proof attempt failed: {e}")
            self.stats['failed_proofs'] += 1

            return Proof(
                theorem_id=theorem.theorem_id,
                proved=False,
                error=str(e),
                execution_time=(datetime.now() - start_time).total_seconds()
            )

    def _select_proof_method(self, theorem: Theorem) -> ProofMethod:
        """Select appropriate proof method"""
        # Prefer SMT when available for propositional / simple first-order
        if self.z3_available and theorem.logic_type in (LogicType.PROPOSITIONAL, LogicType.FIRST_ORDER):
            return ProofMethod.SMT

        # Otherwise natural deduction decides alone: sound, re-checkable, and
        # incomplete, so its `proved=False` is NON-AUTHORITATIVE.
        return ProofMethod.DIRECT

    async def _smt_proof(
        self,
        theorem: Theorem,
        max_steps: int,
        timeout: float = 30.0
    ) -> Proof:
        """SMT-based proof strategy using Z3.

        Premises and the goal are parsed by LogicalFormulaParser into syntax
        trees, then translated to Z3. Anything that does not parse is reported
        as a parse failure rather than being reduced to an opaque atom, because
        an atomised premise silently makes a valid theorem unprovable.
        """
        if not self.z3_available:
            # NO FALLBACK. Quietly answering with a weaker method makes the
            # solver decorative: severing it would change nothing observable,
            # and a `proved=False` produced by its absence is indistinguishable
            # from one produced by a refutation.
            logger.error("SMT proof requested but the Z3 backend is unavailable")
            return Proof(
                theorem_id=theorem.theorem_id,
                proved=False,
                method=ProofMethod.SMT,
                confidence=0.0,
                error=CAPABILITY_UNAVAILABLE,
            )

        # Imported lazily: logical_integration imports this module inside its
        # own functions, so a module-level import here risks a cycle.
        from core.reasoning.logical_integration import (
            FormulaSyntaxError,
            LogicalFormulaParser,
        )

        parser = LogicalFormulaParser()

        # Parse every premise and the goal up front so a syntax error is
        # reported as such instead of surfacing as "not proved".
        parsed_premises: List[Any] = []
        try:
            for premise in theorem.premises:
                parsed_premises.append(parser.parse_ast(premise))
            parsed_statement = parser.parse_ast(theorem.statement)
        except FormulaSyntaxError as e:
            logger.info(f"Theorem {theorem.theorem_id} could not be formalised: {e}")
            return Proof(
                theorem_id=theorem.theorem_id,
                proved=False,
                steps=[],
                method=ProofMethod.SMT,
                confidence=0.0,
                error=f"formula could not be parsed: {e}"
            )

        # Declare one Z3 boolean per distinct atom across premises and goal.
        atoms: Set[str] = set()
        for node in parsed_premises:
            parser.formula_atoms(node, atoms)
        parser.formula_atoms(parsed_statement, atoms)
        z3_vars: Dict[str, Any] = {name: Bool(name) for name in sorted(atoms)}

        solver = Solver()

        # Bound the search. Without this Z3 can run unbounded on a hard
        # instance and block the event loop, since prove_theorem is reachable
        # from an LLM-callable tool.
        if timeout and timeout > 0:
            solver.set("timeout", int(timeout * 1000))
        # A MINIMISED core: without this Z3 returns *a* core, which can carry
        # premises the refutation did not need.
        solver.set("core.minimize", True)

        # Refutation encoding: premises together with the negated goal are
        # unsatisfiable exactly when the premises entail the goal.
        #
        # EACH PREMISE IS TRACKED, so that when the refutation succeeds the
        # solver can say WHICH premises it needed. Added untracked, the only
        # available answer was "all of them", and every premise was reported as
        # support. The negated goal is not tracked: it is part of every
        # refutation by construction and is not something the proof rested on.
        trackers = []
        for index, node in enumerate(parsed_premises):
            tracker = Bool(f"__premise_{index}")
            trackers.append(tracker)
            solver.assert_and_track(parser.to_z3(node, z3_vars), tracker)
        solver.add(Not(parser.to_z3(parsed_statement, z3_vars)))

        logger.debug("Running Z3 SMT solver for theorem %s", theorem.theorem_id)

        result = await asyncio.to_thread(solver.check)
        status = str(result).lower()

        used: Optional[List[int]] = None
        if status == "unsat":
            core = {str(literal) for literal in solver.unsat_core()}
            used = sorted(int(name[len("__premise_"):]) for name in core
                          if name.startswith("__premise_"))

        # EVERY GIVEN PREMISE IS STILL LISTED -- the proof says what it was
        # handed -- but only the ones in the core carry `Premise`, which is the
        # mark downstream readers take to mean "the proof rested on this".
        steps: List[ProofStep] = []
        for step_number, premise in enumerate(theorem.premises, start=1):
            needed = used is None or (step_number - 1) in used
            steps.append(ProofStep(
                step_number=step_number,
                statement=premise,
                justification="Premise" if needed else "Given, not needed",
                rule_applied="given"
            ))
        steps.append(ProofStep(
            step_number=len(theorem.premises) + 1,
            statement=f"~({theorem.statement})",
            justification="Negation of conclusion (for refutation)",
            rule_applied="assumption"
        ))

        if status == "unsat":
            steps.append(ProofStep(
                step_number=len(steps) + 1,
                statement=theorem.statement,
                justification="Premises with the negated goal are unsatisfiable",
                rule_applied="refutation"
            ))
            return Proof(
                theorem_id=theorem.theorem_id,
                proved=True,
                steps=steps,
                method=ProofMethod.SMT,
                confidence=0.98,
                premises_used=used,
            )

        if status == "sat":
            # A model satisfies the premises while falsifying the goal, so the
            # premises genuinely do not entail it.
            return Proof(
                theorem_id=theorem.theorem_id,
                proved=False,
                steps=steps,
                method=ProofMethod.SMT,
                confidence=0.0,
            )

        # "unknown" means the solver gave up (usually the timeout). That is not
        # evidence either way and must not be reported as a decided result.
        return Proof(
            theorem_id=theorem.theorem_id,
            proved=False,
            steps=steps,
            method=ProofMethod.SMT,
            confidence=0.0,
            error=f"solver returned {status!r} (timeout {timeout}s); entailment undecided"
        )

    # ── NATURAL DEDUCTION ─────────────────────────────────────────────────────
    #
    # THIS REPLACES A PROVER THAT DID NOT WORK. The forward chainer split facts
    # on the substring "->", so `(a & b) -> c`, conjunctions, negations and
    # nested implications were invisible to it while the solver parsed the same
    # premises with a real grammar. It returned the first derivable consequent
    # WITHOUT checking whether it was already known, so after one step it could
    # re-derive the same fact until the step budget ran out -- and which pair it
    # hit first depended on set iteration order, i.e. the hash seed. A goal that
    # was already a premise was never proved. `_proof_by_contradiction` was a
    # stub returning proved=False at a made-up 0.5.
    #
    # Now: the solver's own AST; a closure that only adds what is new, in a
    # fixed order; each step citing the steps it came from; and a real proof by
    # contradiction, which reaches what plain forward derivation cannot (a proof
    # by cases goes through modus tollens and disjunctive syllogism).

    _RULE_TEXT = {
        "modus_ponens": "Modus ponens", "modus_tollens": "Modus tollens",
        "and_elim": "Conjunction elimination",
        "disjunctive_syllogism": "Disjunctive syllogism",
        "iff_elim": "Biconditional elimination", "double_negation": "Double negation",
        "not_implies": "Negated implication", "not_or": "Negated disjunction",
        "not_and": "Negated conjunction", "and_intro": "Conjunction introduction",
        "or_intro": "Disjunction introduction", "contradiction": "Contradiction",
    }

    @staticmethod
    def _neg(node: Any) -> Any:
        """The negation of a formula, with a double negation cancelled."""
        return node[1] if node[0] == "not" else ("not", node)

    @staticmethod
    def _parser():
        from core.reasoning.logical_integration import LogicalFormulaParser
        return LogicalFormulaParser()

    def _text(self, node: Any) -> str:
        return "⊥" if node == BOTTOM else self._parser().render(node)

    def _given(self, theorem: Theorem) -> Tuple[List[ProofStep], Dict[Any, int], Any]:
        """Parse the theorem and lay down its premises as the first steps."""
        parser = self._parser()
        goal = parser.parse_ast(theorem.statement)
        steps: List[ProofStep] = []
        facts: Dict[Any, int] = {}
        for premise in theorem.premises:
            node = parser.parse_ast(premise)
            if node in facts:
                continue
            number = len(steps) + 1
            steps.append(ProofStep(number, self._text(node), "Premise", "given",
                                   metadata={"from": [], "premise_index":
                                             theorem.premises.index(premise)}))
            facts[node] = number
        return steps, facts, goal

    def _consequences(self, facts: Dict[Any, int]) -> List[Tuple[Any, str, List[int]]]:
        """Everything one rule application yields from the current facts.

        In a FIXED ORDER -- facts by their canonical text, rules in the order
        written -- so the same premises give the same derivation on every run.
        """
        neg = self._neg
        out: List[Tuple[Any, str, List[int]]] = []
        for fact, n in sorted(facts.items(), key=lambda kv: (self._text(kv[0]), kv[1])):
            kind = fact[0]
            if kind == "and":
                out += [(fact[1], "and_elim", [n]), (fact[2], "and_elim", [n])]
            elif kind == "iff":
                out += [(("implies", fact[1], fact[2]), "iff_elim", [n]),
                        (("implies", fact[2], fact[1]), "iff_elim", [n])]
            elif kind == "implies":
                if fact[1] in facts:
                    out.append((fact[2], "modus_ponens", [n, facts[fact[1]]]))
                if neg(fact[2]) in facts:
                    out.append((neg(fact[1]), "modus_tollens", [n, facts[neg(fact[2])]]))
            elif kind == "or":
                if neg(fact[1]) in facts:
                    out.append((fact[2], "disjunctive_syllogism", [n, facts[neg(fact[1])]]))
                if neg(fact[2]) in facts:
                    out.append((fact[1], "disjunctive_syllogism", [n, facts[neg(fact[2])]]))
            elif kind == "not":
                inner = fact[1]
                if inner[0] == "not":
                    out.append((inner[1], "double_negation", [n]))
                elif inner[0] == "implies":
                    out += [(inner[1], "not_implies", [n]), (neg(inner[2]), "not_implies", [n])]
                elif inner[0] == "or":
                    out += [(neg(inner[1]), "not_or", [n]), (neg(inner[2]), "not_or", [n])]
                elif inner[0] == "and":
                    if inner[1] in facts:
                        out.append((neg(inner[2]), "not_and", [n, facts[inner[1]]]))
                    if inner[2] in facts:
                        out.append((neg(inner[1]), "not_and", [n, facts[inner[2]]]))
        return out

    def _close(self, facts: Dict[Any, int], steps: List[ProofStep], max_steps: int,
               done) -> None:
        """Add consequences until `done`, nothing new, or the step budget.

        ONLY WHAT IS NEW is added -- the defect this replaces re-derived a known
        fact on every pass. The closure is finite for these rules: each derives
        a subformula of a premise, or the negation of one."""
        while len(steps) < max_steps and not done(facts):
            fresh = False
            for node, rule, cited in self._consequences(facts):
                if node in facts:
                    continue
                number = len(steps) + 1
                steps.append(ProofStep(number, self._text(node), self._RULE_TEXT[rule],
                                       rule, metadata={"from": sorted(cited)}))
                facts[node] = number
                fresh = True
                if done(facts) or len(steps) >= max_steps:
                    return
            if not fresh:
                return

    def _goal_closing(self, goal: Any, facts: Dict[Any, int]) -> Optional[Tuple[str, List[int]]]:
        """How the goal follows from the facts, if it does: already present, or
        by one conjunction/disjunction introduction."""
        if goal in facts:
            return ("present", [facts[goal]])
        if goal[0] == "and" and goal[1] in facts and goal[2] in facts:
            return ("and_intro", [facts[goal[1]], facts[goal[2]]])
        if goal[0] == "or":
            for side in (goal[1], goal[2]):
                if side in facts:
                    return ("or_intro", [facts[side]])
        return None

    def _clash(self, facts: Dict[Any, int]) -> Optional[List[int]]:
        for node, n in sorted(facts.items(), key=lambda kv: kv[1]):
            if self._neg(node) in facts:
                return sorted([n, facts[self._neg(node)]])
        return None

    def _mark_used(self, theorem: Theorem, proof: Proof) -> Proof:
        """Walk the citations back from the conclusion: the premises reached are
        the ones this derivation RESTS on, the same question the solver's unsat
        core answers. Only those keep `Premise`; the rest become `Given, not
        needed` -- the convention the solver's steps already follow."""
        by_number = {s.step_number: s for s in proof.steps}
        seen, stack = set(), [proof.steps[-1].step_number] if proof.steps else []
        while stack:
            n = stack.pop()
            if n in seen or n not in by_number:
                continue
            seen.add(n)
            stack.extend((by_number[n].metadata or {}).get("from") or [])
        used = []
        for step in proof.steps:
            if step.rule_applied != "given":
                continue
            if step.step_number in seen:
                used.append(step.metadata["premise_index"])
            else:
                step.justification = "Given, not needed"
        proof.premises_used = sorted(set(used))
        return proof

    async def _direct_proof(self, theorem: Theorem, max_steps: int) -> Proof:
        """Derive the goal forward from the premises."""
        steps, facts, goal = self._given(theorem)
        self._close(facts, steps, max_steps,
                    lambda fs: self._goal_closing(goal, fs) is not None)
        closing = self._goal_closing(goal, facts)
        if closing is None:
            return Proof(theorem_id=theorem.theorem_id, proved=False, steps=steps,
                         method=ProofMethod.DIRECT, confidence=0.0)
        rule, cited = closing
        if rule != "present":
            steps.append(ProofStep(len(steps) + 1, self._text(goal), self._RULE_TEXT[rule],
                                   rule, metadata={"from": sorted(cited)}))
        elif steps[-1].step_number != cited[0]:
            # The goal is an earlier step; the derivation ends where it was reached.
            steps = [s for s in steps if s.step_number <= cited[0]]
        return self._mark_used(theorem, Proof(
            theorem_id=theorem.theorem_id, proved=True, steps=steps,
            method=ProofMethod.DIRECT, confidence=0.95))

    async def _proof_by_contradiction(self, theorem: Theorem, max_steps: int) -> Proof:
        """Assume the goal is false and derive a contradiction."""
        steps, facts, goal = self._given(theorem)
        assumed = self._neg(goal)
        number = len(steps) + 1
        steps.append(ProofStep(number, self._text(assumed),
                               "Assume the negation of the goal", "assumption",
                               metadata={"from": []}))
        facts.setdefault(assumed, number)
        self._close(facts, steps, max_steps, lambda fs: self._clash(fs) is not None)
        clash = self._clash(facts)
        if clash is None:
            return Proof(theorem_id=theorem.theorem_id, proved=False, steps=steps,
                         method=ProofMethod.CONTRADICTION, confidence=0.0)
        steps.append(ProofStep(len(steps) + 1, "⊥", self._RULE_TEXT["contradiction"],
                               "contradiction", metadata={"from": clash}))
        return self._mark_used(theorem, Proof(
            theorem_id=theorem.theorem_id, proved=True, steps=steps,
            method=ProofMethod.CONTRADICTION, confidence=0.95))

    async def _natural_deduction(self, theorem: Theorem, max_steps: int) -> Proof:
        """Directly if the goal can be reached forward; otherwise by
        contradiction. A failure of both is NOT a refutation: these rules have
        no case split, so a true consequence can lie beyond them."""
        from core.reasoning.logical_integration import FormulaSyntaxError
        try:
            direct = await self._direct_proof(theorem, max_steps)
            if direct.proved:
                return direct
            reductio = await self._proof_by_contradiction(theorem, max_steps)
        except FormulaSyntaxError as error:
            return Proof(theorem_id=theorem.theorem_id, proved=False,
                         method=ProofMethod.DIRECT, confidence=0.0,
                         error=f"formula could not be parsed: {error}")
        if not reductio.proved:
            reductio.error = NEGATIVE_NOT_AUTHORITATIVE
        return reductio

    def _reconcile(self, solved: Proof, derived: Proof) -> Proof:
        """The solver's verdict, with the derivation that explains it -- or a
        loud failure if a sound derivation and the solver contradict each other."""
        if solved.proved:
            if derived.proved:
                solved.derivation = derived.steps
                solved.derivation_method = derived.method
                solved.agreement = "both"
            else:
                solved.agreement = "solver_only"
            return solved
        if derived.proved:
            if solved.error:
                # The solver did not decide (timeout, parse limit); a sound
                # derivation is a proof on its own.
                derived.agreement = "derivation_only"
                return derived
            logger.error(
                "PROVERS DISAGREE on %s: natural deduction derived it with sound "
                "rules and the solver found a countermodel", solved.theorem_id)
            return Proof(theorem_id=solved.theorem_id, proved=False, steps=solved.steps,
                         method=ProofMethod.SMT, confidence=0.0, error=PROVERS_DISAGREE,
                         derivation=derived.steps, derivation_method=derived.method,
                         agreement="disagree")
        return solved

    async def add_axiom(self, axiom: Axiom):
        """Add axiom to knowledge base"""
        self.axioms[axiom.axiom_id] = axiom
        logger.info(f"Added axiom: {axiom.axiom_id}")

    async def verify_proof(self, proof: Proof, theorem: Optional[Theorem] = None
                           ) -> "ProofVerification":
        """Check a proof without trusting the prover that made it.

        A proof's own `proved=True` is the claim under test, never the evidence.
        The first implementation looped with `pass` and returned exactly that.
        Now two independent checks exist:

          * a DERIVATION is re-checked step by step -- every step must be a
            premise, the one assumption of a proof by contradiction, or follow
            by its named rule from the steps it cites. The checker is written
            apart from the prover's rule-firing, so a bug in one is not
            automatically a bug in the other.
          * an SMT verdict is re-run against its theorem. That is the SAME
            method again, not an independent one, and the reason says so when
            it is the only check available.
        """
        if not proof.proved:
            return ProofVerification(False, "proof does not claim to prove anything")
        if proof.error == CAPABILITY_UNAVAILABLE:
            return ProofVerification(False, "proof was produced without its solver")

        is_smt = proof.method is ProofMethod.SMT
        derivation = proof.derivation if is_smt else proof.steps
        method = proof.derivation_method if is_smt else proof.method
        checks: List[str] = []
        if derivation:
            checked = self._check_derivation(derivation, method, theorem)
            if not checked.verified:
                return checked
            checks.append("every derivation step re-checked by its rule")
        elif not is_smt:
            return ProofVerification(False, "proof claims success with no steps")

        if is_smt:
            if theorem is None:
                if not checks:
                    return ProofVerification(
                        False, "an SMT proof can only be verified against its theorem")
            else:
                replay = await self._smt_proof(theorem, max_steps=len(proof.steps) or 10)
                if not replay.proved:
                    return ProofVerification(False, "solver did not reproduce the proof",
                                             method=ProofMethod.SMT)
                checks.append("solver re-run")

        reason = "; ".join(checks)
        if checks == ["solver re-run"]:
            reason += (" -- the same method that produced it; no independent "
                       "derivation exists for this proof")
        return ProofVerification(True, reason, method=proof.method)

    def _check_derivation(self, steps: List[ProofStep], method: Optional[ProofMethod],
                          theorem: Optional[Theorem]) -> "ProofVerification":
        from core.reasoning.logical_integration import FormulaSyntaxError
        parser = self._parser()
        premises = goal = None
        try:
            if theorem is not None:
                premises = {parser.parse_ast(p) for p in theorem.premises}
                goal = parser.parse_ast(theorem.statement)
        except FormulaSyntaxError as error:
            return ProofVerification(False, f"the theorem could not be parsed: {error}")

        established: Dict[int, Any] = {}
        unchecked: List[int] = []
        assumptions = 0
        for step in steps:
            n = step.step_number
            rule = (step.rule_applied or "").lower()
            try:
                node = BOTTOM if step.statement.strip() == "⊥" else parser.parse_ast(step.statement)
            except FormulaSyntaxError:
                return ProofVerification(False, f"step {n} is not a formula", failed_step=n)
            cited = list((step.metadata or {}).get("from") or [])
            if any(c not in established for c in cited):
                return ProofVerification(False, f"step {n} cites a step that does not precede it",
                                         failed_step=n)
            sources = [established[c] for c in cited]
            if rule in ("given", "premise", "axiom"):
                if premises is not None and node not in premises:
                    return ProofVerification(False, f"step {n} is given but is not a premise",
                                             failed_step=n)
            elif rule == "assumption":
                assumptions += 1
                if method is not ProofMethod.CONTRADICTION or assumptions > 1:
                    return ProofVerification(
                        False, f"step {n} assumes outside a single proof by contradiction",
                        failed_step=n)
                if goal is not None and node != self._neg(goal):
                    return ProofVerification(
                        False, f"step {n} assumes something other than the negated goal",
                        failed_step=n)
            elif rule in self._RULE_TEXT:
                if not self._licensed(rule, sources, node):
                    return ProofVerification(False, f"step {n} does not follow by {rule}",
                                             failed_step=n)
            else:
                unchecked.append(n)
                continue
            established[n] = node

        if unchecked:
            return ProofVerification(
                False, f"steps {unchecked} use rules this checker cannot re-derive",
                unchecked_steps=unchecked)
        final = established.get(steps[-1].step_number)
        if method is ProofMethod.CONTRADICTION:
            if final != BOTTOM or assumptions != 1:
                return ProofVerification(
                    False, "a proof by contradiction must end in ⊥ from its one assumption")
        elif goal is not None and final != goal:
            return ProofVerification(
                False, f"the last step proves {steps[-1].statement!r}, not the theorem")
        return ProofVerification(True, "every step re-derived", method=method)

    def _licensed(self, rule: str, sources: List[Any], node: Any) -> bool:
        """Does `rule`, applied to exactly the cited formulas, yield `node`?

        Deliberately a separate implementation from `_consequences`: this checks
        a claimed step by the shape of its inputs; that enumerates what the facts
        allow. Sharing the code would make the check agree with the prover by
        construction."""
        neg = self._neg
        pairs = [(sources[0], sources[1]), (sources[1], sources[0])] if len(sources) == 2 else []
        one = sources[0] if len(sources) == 1 else None
        if rule == "modus_ponens":
            return any(a[0] == "implies" and a[1] == b and a[2] == node for a, b in pairs)
        if rule == "modus_tollens":
            return any(a[0] == "implies" and b == neg(a[2]) and node == neg(a[1]) for a, b in pairs)
        if rule == "disjunctive_syllogism":
            return any(a[0] == "or" and ((b == neg(a[1]) and node == a[2]) or
                                         (b == neg(a[2]) and node == a[1])) for a, b in pairs)
        if rule == "not_and":
            return any(a[0] == "not" and a[1][0] == "and" and
                       ((b == a[1][1] and node == neg(a[1][2])) or
                        (b == a[1][2] and node == neg(a[1][1]))) for a, b in pairs)
        if rule == "and_intro":
            return any(node == ("and", a, b) for a, b in pairs)
        if rule == "contradiction":
            return node == BOTTOM and any(b == neg(a) for a, b in pairs)
        if one is None:
            return False
        if rule == "and_elim":
            return one[0] == "and" and node in (one[1], one[2])
        if rule == "iff_elim":
            return one[0] == "iff" and node in (("implies", one[1], one[2]),
                                                ("implies", one[2], one[1]))
        if rule == "double_negation":
            return one[0] == "not" and one[1][0] == "not" and node == one[1][1]
        if rule == "not_implies":
            return one[0] == "not" and one[1][0] == "implies" and node in (one[1][1], neg(one[1][2]))
        if rule == "not_or":
            return one[0] == "not" and one[1][0] == "or" and node in (neg(one[1][1]), neg(one[1][2]))
        if rule == "or_intro":
            return node[0] == "or" and one in (node[1], node[2])
        return False

    async def get_statistics(self) -> Dict[str, Any]:
        """Get proof engine statistics"""
        total = self.stats['total_proofs']

        return {
            **self.stats,
            'success_rate': (
                self.stats['successful_proofs'] / total * 100
                if total > 0 else 0
            ),
            'axioms_count': len(self.axioms),
            'theorems_count': len(self.theorems)
        }


# Global instance
_proof_engine: Optional[AdvancedProofEngine] = None


def get_proof_engine() -> AdvancedProofEngine:
    """Get global proof engine instance"""
    global _proof_engine
    if _proof_engine is None:
        _proof_engine = AdvancedProofEngine()
    return _proof_engine


# Alias for backwards compatibility
def create_advanced_proof_engine() -> AdvancedProofEngine:
    """Create/get advanced proof engine instance (alias for get_proof_engine)"""
    return get_proof_engine()


# Test usage
async def main():
    """Test proof engine"""
    logging.basicConfig(level=logging.INFO)

    engine = get_proof_engine()

    # Test theorem
    theorem = Theorem(
        theorem_id="test_1",
        statement="Q",
        premises=["P -> Q", "P"],
        logic_type=LogicType.PROPOSITIONAL
    )

    proof = await engine.prove_theorem(theorem)

    print(f"\n{'='*50}")
    print("Proof Engine Test")
    print(f"{'='*50}")
    print(f"Theorem: {theorem.statement}")
    print(f"Proved: {proof.proved}")
    print(f"Steps: {len(proof.steps)}")
    print(f"Method: {proof.method.value}")
    print(f"\nProof steps:")
    for step in proof.steps:
        print(f"  {step.step_number}. {step.statement} ({step.justification})")

    stats = await engine.get_statistics()
    print(f"\nStatistics: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
