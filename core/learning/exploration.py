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

from core.tools.tool_registry import get_binding_registry
from core.perception.perception_faculty import look_at, observe_world_async
from core.learning.rule_induction import Fact, TrainingExample
from core.learning.rule_induction import as_constant
from typing import TYPE_CHECKING, Sequence, Tuple

if TYPE_CHECKING:
    from core.perception.perception_faculty import ToolObservedWorld

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

        before = await observe_world_async(domain_id)
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
        again = await observe_world_async(domain_id)
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
        from core.intelligence.effect_verification import concurrent_execution_guard
        signatures = set()
        for action in propose_actions()[:max_actions]:
            binding = registry.get(domain_id, action.predicate)
            if binding is None:
                continue
            # What the act names is looked at before the world is read, so the
            # before and the after speak about the same things: a place this
            # world never looked at says nothing before and something after.
            look_at(domain_id, action.args)
            s_before = await observe_world_async(domain_id)
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
                    from core.structural_defects import raise_if_structural
                    raise_if_structural(e, "exploration.execute_tool")
                    logger.info("exploration action %s raised: %s", action, e)
                s_after = await observe_world_async(domain_id)
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


# =============================================================================
# PRACTICE: WHERE THE SUBSTRATE MAY TRY ACTS UNASKED, AND WHAT IT TRIES THERE
# =============================================================================




def derive_domain(domain_id: str, *,
                  observations: Sequence[Tuple[str, Dict[str, Any]]],
                  actions: Sequence[str]) -> Dict[str, Any]:
    """Make a domain ACTABLE and OBSERVABLE out of tools the substrate has.

    This is the answer to `BINDING_GAP -> ESCALATE` for every action a tool
    already performs. A domain is declared by saying what to look at and which
    tools may act on it; the operators, their arguments, and the mapping back to
    each tool's parameters are all derived from what the tools declare.

    Registers the domain as EXPLORABLE too, so the always-online learner can
    practise in it -- which is what turns a bound domain into a domain with
    learned operators.

    Returns what was actually bound, including what could not be and why, so a
    caller is never told a domain is actable when half its tools were missing.
    """
    from core.perception.perception_faculty import _senses, resource_kind, world_of
    from core.tools.tool_registry import ACTING_CLASSES, action_binding
    from core.learning.exploration import register_explorable_domain
    from core.agents.autonomous.autonomous_coordinator import classify_action
    from core.tools import get_tool_registry

    registry = get_tool_registry()
    # ONE WORLD CLASS. A domain declared this way and a domain met by acting
    # must be the same kind of thing, or the proposer works for one and not the
    # other. The declared observations seed the resources; acting adds to them.
    world = world_of(domain_id)
    senses = _senses()
    for observation_tool, arguments in observations:
        for parameter_name, value in (arguments or {}).items():
            if isinstance(value, str) and value.strip():
                kind = resource_kind(parameter_name)
                world.encountered(kind, value)
                # A declared place is a place given to practise in, and the self
                # LOOKS at it: what is in it is what can be practised on.
                if kind in senses:
                    world.allow_practice(kind, value)
                    world.perceive(value)
    bound: List[str] = []
    refused: List[Dict[str, str]] = []

    for tool_name in actions:
        tool = registry.get_tool(tool_name)
        if tool is None:
            refused.append({"tool": tool_name, "why": "no such tool"})
            continue
        try:
            action_class, _ = classify_action(tool_name, {})
        except Exception as e:
            refused.append({"tool": tool_name, "why": f"unclassifiable: {e}"})
            continue
        kind = getattr(action_class, "value", str(action_class))
        if kind not in ACTING_CLASSES:
            # AN OPERATOR MOVES THE WORLD. A tool that changes nothing is an
            # observation, and calling it an operator would give the planner a
            # step that can never make progress.
            refused.append({"tool": tool_name,
                            "why": f"{kind} — changes nothing, so it is not an operator"})
            continue
        binding = action_binding(tool_name, tool, world.observe)
        if binding is None:
            refused.append({"tool": tool_name, "why": "declares no parameters"})
            continue
        get_binding_registry().register(domain_id, binding)
        bound.append(binding.predicate)

    proposer = _proposer_for(domain_id, world)
    register_explorable_domain(domain_id, proposer)
    logger.info("derived domain %s: %d operator(s) from tools, %d observation(s)",
                domain_id, len(bound), len(observations))
    return {"domain_id": domain_id, "operators": bound, "refused": refused,
            "observations": [t for t, _ in observations],
            "actable": bool(bound), "observable": world.observe() is not None}


#: domain_id -> how many times its proposer has been asked. Rotates which
#: encountered resources are tried, so successive cycles vary the grounding
#: instead of repeating one act -- variation is where contrast comes from, and
#: contrast is what separates a precondition from a coincidence.
_PROPOSED: Dict[str, int] = {}

#: How reversible an act must be for the substrate to try it unasked.
PRACTISABLE = ("FULLY_REVERSIBLE", "MOSTLY_REVERSIBLE")


def _proposer_for(domain_id: str, world: "ToolObservedWorld") -> Callable[[], List[Fact]]:
    """Candidate acts to TRY, and only inside the places given for practice.

    AN ACT IS TRIED ON WHAT IS THERE AND ON WHERE THINGS COULD GO. Drawing
    arguments from every constant an observation happened to report proposed
    `MOVE_FILE(1, 2, <a path>)`; drawing them from every resource met proposed
    moving a directory onto a directory. The self's sense names both halves
    instead: the things it perceives inside the practice place, and the name a
    thing would have inside another container there -- a free place, which is
    where an act that relocates something can succeed. Nothing else is named.

    PER THING, A ROUND TRIP AND TWO CONTRASTS, run in order against the live
    world:

      1. the thing to a free place       what the act does when it can
      2. back again                      so practice leaves things where they
                                         were, and the demonstrations do not
                                         freeze on one direction
      3. something not there, to another free place
                                         what the act does when there is nothing
                                         to act on; without it nothing
                                         contradicts a rule that needs no
                                         precondition
      4. a thing onto a place that is taken
                                         what the act does when where it goes is
                                         not free. The self sees a free place
                                         (ABSENT), but a rule that ignores it
                                         explains every success just as well;
                                         only this failure keeps it

    A one-place act is tried on a thing and on a free place.

    ONLY WHAT CAN BE UNDONE IS PRACTISED. Practice is acting unasked, and an act
    the constitution rates less than mostly reversible cannot be taken back if
    what it touched mattered. Such an act is learned when the substrate is asked
    to perform it, never tried to see what happens. That rating is also what
    makes contrast 4 safe to try: an act that would destroy what is already at a
    place is not rated reversible.

    Successive cycles rotate through the things, so the demonstrations differ:
    variation is where contrast comes from, and contrast is what separates a
    precondition from a coincidence.
    """
    from core.perception.perception_faculty import DESCRIBING_MEASURES, _senses, resource_kind
    from core.tools.tool_registry import payload_parameters, payload_term, resource_parameters
    def propose() -> List[Fact]:
        from core.agents.autonomous.autonomous_coordinator import classify_action
        from core.tools import get_tool_registry

        registry = get_tool_registry()
        turn = _PROPOSED.get(domain_id, 0)
        _PROPOSED[domain_id] = turn + 1
        senses = _senses()
        #: free places already given to an act this cycle, so no act lands
        #: where an earlier one in the same cycle put something
        claimed: set = set()

        def free(sensed, place: str) -> bool:
            if place in claimed:
                return False
            try:
                return sensed.perceive(place) is None
            except OSError:
                return False

        # What may be practised here, and on what.
        practisable = []
        for binding in get_binding_registry().bindings_for(domain_id):
            tool = registry.get_tool(binding.tool_name)
            if tool is None:
                continue
            try:
                _class, irreversibility = classify_action(binding.tool_name, {})
            except Exception:
                continue
            if getattr(irreversibility, "value", str(irreversibility)) not in PRACTISABLE:
                continue
            kinds = [resource_kind(p.name) for p in resource_parameters(tool)]
            if not kinds or len(kinds) > 2 or len(set(kinds)) != 1:
                continue
            sensed = senses.get(kinds[0])
            if sensed is None or sensed.relocate is None:
                continue
            things, containers = world.practice_view(kinds[0])
            if things:
                practisable.append((binding, len(kinds), sensed, things, containers))

        def free_places(sensed, containers, things) -> List[str]:
            return [p for p in (sensed.relocate(t, c) for t in things for c in containers)
                    if p not in things and free(sensed, p)]

        # FIRST, WHAT EACH ACT DOES WHEN IT CAN. Each starts from a different
        # thing and takes the first that still has somewhere free to go, so no
        # act is left with nowhere because another took the only free place.
        rounds: List[List[Fact]] = []
        for index, (binding, arity_, sensed, things, containers) in enumerate(practisable):
            order = [things[(turn + index + i) % len(things)] for i in range(len(things))]
            acts: List[Fact] = []
            if arity_ == 1:
                acts.append(Fact(binding.predicate, (as_constant(order[0]),)))
            else:
                for thing in order:
                    places = [p for p in (sensed.relocate(thing, c) for c in containers)
                              if p != thing and free(sensed, p)]
                    if places:
                        there = places[turn % len(places)]
                        claimed.add(there)
                        acts.append(Fact(binding.predicate, (as_constant(thing), as_constant(there))))
                        acts.append(Fact(binding.predicate, (as_constant(there), as_constant(thing))))
                        break
            rounds.append(acts)

        # THEN, WHAT EACH DOES WHEN IT CANNOT, from what is still free: the
        # contrasts use only places no working act needed.
        for index, (binding, arity_, sensed, things, containers) in enumerate(practisable):
            spare = free_places(sensed, containers, things)
            if arity_ == 1 and spare:
                absent = spare[turn % len(spare)]
                claimed.add(absent)
                rounds[index].append(Fact(binding.predicate, (as_constant(absent),)))
            elif arity_ == 2:
                if len(spare) >= 2:
                    absent, target = spare[turn % len(spare)], spare[(turn + 1) % len(spare)]
                    if absent != target:
                        claimed.update((absent, target))
                        rounds[index].append(Fact(binding.predicate,
                                                  (as_constant(absent), as_constant(target))))
                # Onto a place something already holds, and something that is
                # not what the act would put there: onto an identical copy, the
                # act succeeding and the act refused leave the same world, and
                # the contrast teaches nothing. A container holding the thing is
                # never the target.
                thing = things[turn % len(things)]
                try:
                    measured = sensed.perceive(thing) or {}
                except OSError:
                    measured = {}

                def differs(place: str) -> bool:
                    try:
                        entry = sensed.perceive(place)
                    except OSError:
                        return False
                    return entry is not None and any(
                        entry.get(m) != measured.get(m) for m in DESCRIBING_MEASURES)

                taken = [p for p in things + containers
                         if p != thing
                         and not (sensed.within is not None and sensed.within(p, thing))
                         and differs(p)]
                if taken:
                    rounds[index].append(Fact(binding.predicate,
                                              (as_constant(thing), as_constant(taken[turn % len(taken)]))))

        # An act that puts something into the world is practised with a text of
        # its own, different each time, so what it carries can be seen to land.
        payload_count = {binding.predicate: len(payload_parameters(registry.get_tool(binding.tool_name)))
                         for binding, *_ in practisable}
        proposed: List[Fact] = []
        for k, act in enumerate(a for acts in rounds for a in acts):
            extra = tuple(as_constant(payload_term(f"practice {turn}.{k}.{i}\n"))
                          for i in range(payload_count.get(act.predicate, 0)))
            proposed.append(Fact(act.predicate, act.args + extra) if extra else act)
        return proposed

    return propose


def take_up_workspace(domain_id: str, root: str) -> int:
    """A directory the substrate was given to work in: look at it, and let it
    practise there.

    What is in it enters the domain's world through the self's own perception,
    and the domain becomes explorable with practice bounded to the directory.
    Which acts may be practised there is the domain's own: the operators it has
    met or learned, and of those only what can be undone. Returns how many
    resources entered the world.
    """
    from core.perception.perception_faculty import world_of
    import os
    from core.learning.exploration import get_proposer, register_explorable_domain

    if not (root and os.path.isdir(root)):
        # A place the substrate would practise in must be a real place.
        logger.info("%s is not a directory; there is no workspace to take up", root)
        return 0
    world = world_of(domain_id)
    added = world.perceive(root)
    world.allow_practice("path", root)
    if get_proposer(domain_id) is None:
        register_explorable_domain(domain_id, _proposer_for(domain_id, world))
    return added
