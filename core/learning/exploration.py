#!/usr/bin/env python3
"""Always-online exploration: the substrate acts in a domain to learn its
operators from what happens.

This is how a NEW operator is acquired without a model and without a teacher.
The substrate observes a world, tries actions in it, and records what each one
did -- the effect when it worked, the absence of an effect when it did not, and
the absence of any change when nothing was done at all. Those three are exactly
the evidence induction needs: positives to generalize the effect, action-ful
negatives to sharpen the preconditions, and still-world negatives to establish
that the ACTION, not the co-occurring state, is what produces the effect.

Exploration is not gated and not a fallback. It is a standing capability: the
substrate is meant to be doing this continuously, so that by the time a task
needs an operator the experience that teaches it has already been gathered.
Safety is consulted for a signal, never as a bouncer -- every action still runs
through the tool registry's single evaluation point, which records the outcome
without blocking the substrate's autonomy.

Induction is NOT run here. Exploration records demonstrations (cheap) and asks
the learning authority to re-induce the affected operators afterwards; the
authority carries the cost of the hypothesis search off the acting path.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.execution.operator_binding import get_binding_registry
from core.learning.rule_induction import Fact, TrainingExample

logger = logging.getLogger(__name__)

#: A candidate proposer maps the observed world to ground actions worth trying.
ProposeActions = Callable[[], List[Fact]]

#: What the tool registry stamps on a result the constitution refused. Read as
#: the TYPED marker it is rather than by matching the error text, so a reworded
#: refusal cannot quietly start counting as evidence about the world again.
CONSTITUTION_REFUSED = "CONSTITUTION_REFUSED"


def _refusal(outcome: Any) -> Optional[str]:
    """The reason this act was refused, or None if the world actually answered.

    An act the constitution stopped never reached the world. Everything the
    explorer does afterwards — observe, compare, label — is about a world that
    was never asked, so the only honest thing to do with it is nothing.
    """
    if outcome is None or getattr(outcome, "success", False):
        return None
    metadata = getattr(outcome, "metadata", None) or {}
    if metadata.get("error_type") != CONSTITUTION_REFUSED:
        # An ordinary tool failure IS the world answering: the move did not
        # happen because the source was not there, and that is exactly the
        # negative the learner needs.
        return None
    return str(getattr(outcome, "error", "") or "refused")


# ── EXPLORABLE-DOMAIN REGISTRY ────────────────────────────────────────────
# A domain becomes explorable when something declares HOW to propose actions in
# it (the binding says how to observe and act; this says what to try). The idle
# exploration tier iterates these so it can explore any installed domain without
# knowing the domain's specifics -- the domain supplies its own proposer.
_proposers: Dict[str, ProposeActions] = {}


def register_explorable_domain(domain_id: str, propose_actions: ProposeActions) -> None:
    _proposers[domain_id] = propose_actions
    logger.info("registered explorable domain %s", domain_id)


def explorable_domains() -> List[str]:
    return list(_proposers)


def get_proposer(domain_id: str) -> Optional[ProposeActions]:
    return _proposers.get(domain_id)


def unregister_explorable_domain(domain_id: str) -> None:
    _proposers.pop(domain_id, None)


def fresh_evidence_id() -> str:
    """An id for one exploratory act's demonstration."""
    return f"explore_{uuid.uuid4().hex[:12]}"


def _still_world_id(facts) -> str:
    """A stable id for a still-world observation, so the same unchanged state is
    not recorded as many independent contrastives."""
    digest = hashlib.sha256(
        "|".join(sorted(str(f) for f in facts)).encode()).hexdigest()
    return f"still_{digest[:16]}"


class SubstrateExplorer:
    """Drives one domain's exploration cycle and feeds what it observes to the
    learning authority."""

    def __init__(self, learning_authority=None, tool_registry=None):
        self._authority = learning_authority
        self._tools = tool_registry

    def _authority_(self):
        if self._authority is None:
            from core.learning.unified_learning_system import get_learning_authority
            self._authority = get_learning_authority()
        return self._authority

    async def _tools_(self):
        if self._tools is None:
            from core.tools import get_tool_registry
            self._tools = get_tool_registry()
        return self._tools

    async def _state_experiment(self, domain_id: str, action: Fact) -> Optional[str]:
        """Record WHY this act is happening: it is an experiment.

        The account is written to the intent authority and only its id travels,
        exactly as a proved plan's does. The constitution reads what was
        recorded and checks it against the exploration and binding registries,
        so this states a claim rather than granting itself permission.

        A failure here is not swallowed into acting anyway: with no recorded
        account the act is judged as one nothing can explain, which is the
        correct answer to an experiment the substrate cannot show it is running.
        """
        try:
            from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
            from core.reasoning.intent_authority import get_intent_authority

            intent = await get_intent_authority().form(
                "self_goal", SUBSTRATE_ACTOR,
                f"experiment:{domain_id}:{action.predicate}",
                shape={
                    # The account this act gives. `proved` is deliberately
                    # ABSENT: nothing was proved, and claiming it would be the
                    # fabricated-intent hole the constitution closed by
                    # fetching intents instead of accepting them.
                    "purpose": "find_out",
                    "operator": str(action),
                    "domain": domain_id,
                    "predicate": action.predicate,
                },
                content={"aim": f"find out what {action.predicate} does in "
                                f"{domain_id}"})
            return intent.intent_id
        except Exception as e:
            logger.error("exploration could not record what it is doing, so "
                         "its acts will be judged as unexplained: %s", e)
            return None

    async def _read_targets(self, tools, params: Dict[str, Any]) -> None:
        """Read the existing files this act would write over, before it runs.

        Law 2 refuses an act on a file with no current reading of it, and it is
        right to: a negative control aimed at a file that is already there is
        still aimed at content nobody has looked at. The learner's answer is to
        LOOK, not to be excused — the reading is cheap, it is an investigate-
        class act the laws permit, and it is recorded by the constitution at the
        single point every act passes, which is what makes the act that follows
        legal.
        """
        import os

        for key in ("destination_path", "path", "file_path", "target_path"):
            target = params.get(key)
            if not target:
                continue
            target = str(target)
            # A READING APPROPRIATE TO WHAT IS THERE. `read_file` cannot read a
            # directory, so a target that was one went unread, Law 2 refused the
            # act for want of a reading, and the cycle produced no evidence
            # EITHER WAY -- not a positive, not even an honest negative. A
            # refusal is not a result, so the act has to be able to run and then
            # succeed or fail on its own merits.
            if os.path.isfile(target):
                observation, argument = "read_file", "file_path"
            elif os.path.isdir(target):
                observation, argument = "list_directory", "directory_path"
            else:
                continue          # nothing there yet: nothing to have read
            try:
                await tools.execute_tool(observation, {argument: target})
            except Exception as e:
                # Not fatal: the act will be refused for want of a reading, and
                # that refusal is itself honest evidence about the world.
                logger.info("exploration could not read %s before acting: %s",
                            target, e)

    async def explore(
        self, domain_id: str, propose_actions: ProposeActions, *,
        max_actions: int = 8, reinduce: bool = False,
    ) -> Dict[str, Any]:
        """One exploration cycle in a bound, observable domain.

        Observes the world, records that it does not change on its own (the
        still-world contrastive), tries up to `max_actions` candidate actions
        and records what each did. Recording ENQUEUES each affected operator for
        induction; it does not induce here.

        `reinduce` is False by default so exploration stays a cheap acting loop:
        the hypothesis search runs off the acting path, drained by the
        always-online learner (`LearningAuthority.drain_pending_induction`) in
        its own idle tier. Pass `reinduce=True` only where induction is wanted
        synchronously -- a test, or a caller that must see the operator this
        cycle. Left on the acting path, induction's cost (which grows with the
        richness of the observed state) would make every exploration cycle pay
        for it.
        """
        registry = get_binding_registry()
        authority = self._authority_()

        before = await registry.observe_world_async(domain_id)
        if before is None:
            return {"status": "unobservable",
                    "detail": f"the world of domain {domain_id!r} could not be read"}

        summary: Dict[str, Any] = {
            "domain_id": domain_id, "acted": 0, "positive": 0, "negative": 0,
            "contrastive": 0, "signatures_reinduced": [], "operators_executable": [],
            # Controllability evidence: does acting change the world MORE than
            # not acting? `acted`/`positive` are the action side; these are the
            # no-action side.
            "still_observations": 0, "ambient_changes": 0,
        }

        # STILL-WORLD OBSERVATION. Observe again with nothing done. If the world
        # is unchanged, that is a contrastive negative -- no effect occurs
        # without an action (its id is derived from the state so a repeated
        # still world does not pile up duplicate negatives). If it CHANGED with
        # no action taken, that is AMBIENT change: the world is moving on its
        # own, which is evidence the domain is not controllable -- an outcome
        # the substrate cannot attribute to, or produce with, its own actions.
        again = await registry.observe_world_async(domain_id)
        if again is not None:
            summary["still_observations"] += 1
            if again == before:
                contrastive = TrainingExample(
                    before=tuple(sorted(before)), action=None,
                    after=tuple(sorted(before)), positive=False,
                    evidence_id=_still_world_id(before))
                if await authority.record_demonstration(contrastive, domain_id=domain_id):
                    summary["contrastive"] += 1
            else:
                summary["ambient_changes"] += 1

        # ACTION-FUL DEMONSTRATIONS. Try candidates; record what each did.
        tools = await self._tools_()
        from core.execution.effect_verification import concurrent_execution_guard
        signatures = set()
        for action in propose_actions()[:max_actions]:
            binding = registry.get(domain_id, action.predicate)
            if binding is None:
                continue
            # What the act names is looked at before the world is read, so the
            # before and the after speak about the same things: a place this
            # world never looked at says nothing before and something after.
            registry.look_at(domain_id, action.args)
            s_before = await registry.observe_world_async(domain_id)
            if s_before is None:
                continue
            # Under the concurrency guard: if another execution in this domain
            # overlapped the act, the before/after cannot be attributed to THIS
            # action -- the positive/negative label would be wrong -- so the
            # observation is dropped rather than recorded as a mislabeled
            # demonstration. Nothing is serialized; the act still runs.
            params = binding.parameters(action.args)
            # SAY WHAT THIS ACT IS FOR, so the constitution can judge it as the
            # experiment it is.
            #
            # EVERY EXPLORATORY ACT USED TO BE REFUSED. Law 2 accepted exactly
            # one account -- a proved route to a goal state -- and an experiment
            # cannot have one: proving a route needs the knowledge the
            # experiment exists to acquire. Measured on the live substrate: 3
            # actions tried per cycle, 0 positives, `insufficient_evidence`
            # forever. The substrate's one model-free way to learn an operator
            # had never worked in production, which is why the binding registry
            # was "populated only by experiments and tests".
            #
            # The intent is RECORDED and the constitution FETCHES it -- naming
            # an experiment is not having one, and `_experiment_is_earned`
            # checks the domain is really explorable and the operator really
            # bound before the account counts.
            intent_id = await self._state_experiment(domain_id, action)
            # READ WHAT THE ACT WOULD OVERWRITE, because the law asks for it and
            # asking to be excused instead would be trading the protection of
            # file CONTENT for the convenience of the learner. A negative
            # control aimed at an existing file is exactly the case: the act is
            # meant to fail, but it is still aimed at something nobody has read.
            await self._read_targets(tools, params)
            s_after, interfered = None, False
            from core.reasoning.intent_authority import (
                reset_acting_intent, set_acting_intent)
            token = set_acting_intent(intent_id)
            refused = None
            with concurrent_execution_guard(domain_id) as _overlapped:
                try:
                    outcome = await tools.execute_tool(binding.tool_name, params)
                    refused = _refusal(outcome)
                except Exception as e:
                    from core.capability import raise_if_structural
                    raise_if_structural(e, "exploration.execute_tool")
                    logger.info("exploration action %s raised: %s", action, e)
                s_after = await registry.observe_world_async(domain_id)
                interfered = _overlapped()
            reset_acting_intent(token)
            if refused is not None:
                # A REFUSAL IS NOT EVIDENCE ABOUT THE WORLD. The act never ran,
                # so the world did not move — and recording an unmoved world as
                # a negative demonstration teaches the substrate that its own
                # operator does nothing.
                #
                # MEASURED, and it had already happened: in one domain
                # `MOVE_FILE(report, inbox, archive)` stood 8× negative against
                # 10× positive, the same action with the same before-state and
                # opposite outcomes. Every negative was a law refusing the act,
                # never the world answering. Induction correctly found that no
                # generalization survives its own counter-evidence and returned
                # `no_rule` — the substrate had learned from its own constitution
                # that moving a file does not move a file.
                #
                # `_drive_substrate_goal` already says this for the planned path
                # ("a false negative about knowledge, produced by the substrate's
                # own law"); exploration is the other path that acts, and it was
                # writing exactly that false negative down.
                summary["refused"] = summary.get("refused", 0) + 1
                logger.info("exploration action %s was refused, not answered by "
                            "the world; recording nothing: %s", action, refused)
                continue
            if s_after is None:
                continue
            if interfered:
                summary["interfered"] = summary.get("interfered", 0) + 1
                continue

            positive = s_after != s_before
            example = TrainingExample(
                before=tuple(sorted(s_before)), action=action,
                after=tuple(sorted(s_after)), positive=positive,
                evidence_id=fresh_evidence_id())
            await authority.record_demonstration(example, domain_id=domain_id)
            summary["acted"] += 1
            summary["positive" if positive else "negative"] += 1
            signatures.add(action.signature)

        # RE-INDUCE off the acting path. Each operator that gained a
        # demonstration is re-induced over its whole accumulated experience.
        if reinduce:
            for predicate, arity in sorted(signatures):
                outcome = await authority.reinduce_operator(
                    domain_id=domain_id, predicate=predicate, arity=arity)
                summary["signatures_reinduced"].append(
                    {"signature": f"{predicate}/{arity}",
                     "status": outcome.get("status"),
                     "executable": outcome.get("executable")})
                if outcome.get("executable"):
                    summary["operators_executable"].append(f"{predicate}/{arity}")

        logger.info("exploration of %s: %d acted (%d+/%d-), %d contrastive, "
                    "executable=%s", domain_id, summary["acted"],
                    summary["positive"], summary["negative"],
                    summary["contrastive"], summary["operators_executable"])
        return summary
