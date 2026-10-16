#!/usr/bin/env python3
"""Capabilities: how Lyric learns what it can do.

A faculty of the substrate, beside reasoning, learning, the constitution and the
senses. It reads, and moves no belief. The one thing it holds is each person's
operating mode, as the world hands it over (`set_operating_mode`).

WHAT A CAPABILITY IS. A method the memory agent lifted from the first task of
its shape that worked, widened by the tasks after it (`core.memory.lift`,
MEMORY_AGENT_MAP §10.2, SEPARATION_MAP §11.4): steps, each a tool with
arguments, the task's particulars made variables, and the fixes it overcame
failures by. It is never declared, never inferred from words, and never there
because a tool exists. Tools are the means: they perform primitives
(`tool_registry.Primitive`), and a capability may use many of them.

WHAT IT OVERCAME IS USED AT ONCE (`known_fix`). A plan about to be done that is
an instance of a capability once one of its fixes is made is given the fix
before it is done: the failure it overcame for one person is not met again, by
them or by anyone. How it is done for someone is still `may_act_for`.

STANDING, read from beliefs the belief system holds:

  the world    the shared belief that the method works, moved by every counted
               outcome from everyone. Reliability, not how many people used it:
               ten people who all saw it fail make it fail.
  a person     their own belief in the same claim, in their context, moved only
               by their own outcomes.

A standing is settled in favour when the belief is (`settled_in_favour`: the
belief system's own bar, `UNSTABLE_ENTROPY`, on the side of "it works"). It is
never permanent: the memory agent records each time it crosses, and a later
failure can take it back.

  world      learning     not settled in favour, and never was
             unlocked     settled in favour now
             withdrawn    was unlocked, and is not now

  person     not encountered   no outcome of theirs yet
             learning          theirs is not settled in favour
             demonstrated      theirs is, and the world's is not
             unlocked          theirs is, and the world's is (world first: a
                               capability unlocks for nobody in particular
                               until it unlocks for the world)
             withdrawn         was unlocked for them, and is not now

  A method that is only one person's (the lift kept something only they
  supplied) is never the world's; it unlocks for them when their own standing
  settles, and is withdrawn when it stops being.

ACTING FOR SOMEONE (`may_act_for`). The substrate's own work: on its own; the
constitution judges every act. For a person: on its own only when unlocked for
them, and only if appraisal's disposition at that moment does not say to back
off or escalate (read live by the caller, never stored); otherwise each act is
confirmed by the person. Before the world unlocks a capability, it is used for a
person only when they ask; it is not raised unasked.

A PERSON'S OPERATING MODE BOUNDS ALL OF IT (`OPERATING_MODES`). Observe: Lyric
notices and tells, and completes the work they ask for, each act confirmed; it
never acts for them unasked and runs nothing on a schedule for them. Assist:
each act waits for their yes, however settled the capability.
Delegate: as above. The constitution holds every act on their work to the classes
their mode permits (`settings_for`, Law 1). No mode handed over is no authority
established: treated as Observe here, and refused there.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: How Lyric operates for a person, and the classes of act each mode lets it do on their work, in the constitution's
#: own classes (`classify_action`, Law 1): Observe and Assist investigate, modify and archive, each act confirmed (Observe
#: only what the person asks for, `may_act_for`); Delegate does what the constitution's other laws allow.
OPERATING_MODES: Dict[str, Tuple[str, ...]] = {
    "observe": ("investigate", "modify", "archive"),
    "assist": ("investigate", "modify", "archive"),
    "delegate": ("investigate", "modify", "archive", "delete", "execute"),
}


def settled_in_favour(posterior: Optional[float]) -> bool:
    """Whether a belief at `posterior` is settled on the side that the claim
    holds: the belief system's own bar for settled (`UNSTABLE_ENTROPY`)."""
    if posterior is None:
        return False
    from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem, belief_entropy
    return posterior > 0.5 and belief_entropy(posterior) <= BayesianUncertaintySystem.UNSTABLE_ENTROPY


def _last(history: List[Dict[str, Any]], settled: bool) -> Optional[str]:
    times = [h["at"] for h in history if bool(h.get("settled")) is settled]
    return times[-1] if times else None


def _both_settled_spans(world: List[Dict[str, Any]], person: List[Dict[str, Any]]
                        ) -> List[Tuple[str, Optional[str]]]:
    """When the world's and a person's standings were both settled in favour:
    (from, until) spans, `until` None while it holds."""
    events = sorted([(h["at"], "w", bool(h.get("settled"))) for h in world]
                    + [(h["at"], "p", bool(h.get("settled"))) for h in person])
    state = {"w": False, "p": False}
    spans: List[Tuple[str, Optional[str]]] = []
    for at, who, settled in events:
        was = state["w"] and state["p"]
        state[who] = settled
        now = state["w"] and state["p"]
        if now and not was:
            spans.append((at, None))
        elif was and not now:
            spans[-1] = (spans[-1][0], at)
    return spans


@dataclass
class Standing:
    """Where a capability stands, for the world and for one person."""
    world: str
    world_belief: Optional[float]
    world_last_move: Optional[float]
    world_unlocked_on: Optional[str]
    world_withdrawn_on: Optional[str]
    person: Optional[str] = None
    person_belief: Optional[float] = None
    person_last_move: Optional[float] = None
    person_outcomes: int = 0
    person_unlocked_on: Optional[str] = None
    person_withdrawn_on: Optional[str] = None
    #: The mean reward their counted outcomes carried (`_evaluate_outcome`).
    person_reward: Optional[float] = None


@dataclass
class Capability:
    """A lifted method, as the faculty reports it."""
    id: str
    whose: str                      # "world", or "person" for one person's own
    steps: List[str]
    shape: str
    means: Dict[str, List[str]]     # tool -> the primitives it performs
    outcomes: Dict[str, int]        # counted and worked, over everyone's instances
    #: The mean reward everyone's counted outcomes carried, or None.
    reward: Optional[float]
    standing: Standing
    unread: List[str] = field(default_factory=list)   # steps no registered tool performs


class Capabilities:
    """The faculty. Reads the methods the memory agent keeps and the beliefs the
    belief system holds."""

    #: Each person's operating mode. Runtime, beside the work it governs: a setting of theirs on how Lyric acts for
    #: them, handed over by the world, not something they told Lyric, so it is not their context.
    _MODE_DDL = [
        """CREATE TABLE IF NOT EXISTS unified.operating_modes (
               person   TEXT PRIMARY KEY,
               mode     TEXT NOT NULL,
               set_at   TIMESTAMPTZ NOT NULL DEFAULT now())""",
    ]

    async def operating_mode(self, person: Optional[str]) -> Optional[str]:
        """The mode the world says this person chose; None for the substrate, and until the world hands one over."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        from core.database import get_database_manager
        if is_substrate_actor(person):
            return None
        db = get_database_manager()
        await db.ensure_schema("operating_modes", self._MODE_DDL, store="runtime")
        row = await db.execute_query(
            "SELECT mode FROM unified.operating_modes WHERE person = $1",
            (str(person),), fetch_one=True, store="runtime")
        return row["mode"] if row else None

    async def set_operating_mode(self, person: str, mode: str) -> Dict[str, Any]:
        """Hold the mode the world handed over for a person. Refused for the substrate and for a mode that is none of
        the three, never moved to the nearest one: the world is told, not corrected behind its back."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        from core.database import get_database_manager
        if is_substrate_actor(person):
            raise ValueError("an operating mode is a person's; Lyric's own work is judged by the constitution alone")
        chosen = str(mode or "").strip().lower()
        if chosen not in OPERATING_MODES:
            raise ValueError(f"an operating mode is observe, assist or delegate; {mode!r} is not")
        db = get_database_manager()
        await db.ensure_schema("operating_modes", self._MODE_DDL, store="runtime")
        await db.execute_query(
            "INSERT INTO unified.operating_modes (person, mode) VALUES ($1, $2) "
            "ON CONFLICT (person) DO UPDATE SET mode = EXCLUDED.mode, set_at = now()",
            (str(person), chosen), commit=True, store="runtime")
        return await self.settings_for(person)

    async def settings_for(self, actor: Optional[str]) -> Optional[Dict[str, Any]]:
        """What the constitution reads of the person whose work an act is (`Constitution.set_user_settings_provider`):
        who they are, their mode, and the classes of act it permits. None for the substrate's own work, and for a
        person whose mode has not reached Lyric: no authority established."""
        mode = await self.operating_mode(actor)
        if mode is None:
            return None
        return {"identity": str(actor), "mode": mode, "permitted_actions": list(OPERATING_MODES[mode])}

    async def _world_standing(self, method_id: str, whose: str) -> Tuple[str, Optional[float], Optional[float],
                                                                         Optional[str], Optional[str],
                                                                         List[Dict[str, Any]]]:
        from core.agents.memory_agent import memory_agent
        from core.learning.unified_learning_system import get_learning_authority
        if whose != "world":
            return "not the world's", None, None, None, None, []
        authority = get_learning_authority()
        belief = authority.belief_for_claim(authority.method_claim(method_id))
        posterior = float(belief.posterior_probability) if belief is not None else None
        history = list(getattr(belief, "confidence_history", None) or [])
        last_move = (history[-1] - (history[-2] if len(history) > 1 else 0.5)) if history else None
        record = await memory_agent().standing_history(method_id, None)
        settled = settled_in_favour(posterior) and belief is not None and _grounded(belief)
        if settled:
            state = "unlocked"
        elif _last(record, True) is not None:
            state = "withdrawn"
        else:
            state = "learning"
        return (state, posterior, last_move, _last(record, True) if settled else None,
                _last(record, False) if state == "withdrawn" else None, record)

    async def standing(self, method_id: str, whose: str, actor: Optional[str] = None) -> Standing:
        """Where this capability stands for the world and, when an actor is
        named, for them."""
        from core.agents.memory_agent import memory_agent
        from core.agents.autonomous.shared_types import is_substrate_actor
        from core.learning.scoped_context_store import get_scoped_context_store
        from core.learning.unified_learning_system import get_learning_authority
        state, posterior, last_move, unlocked_on, withdrawn_on, world_history = \
            await self._world_standing(method_id, whose)
        standing = Standing(world=state, world_belief=posterior, world_last_move=last_move,
                            world_unlocked_on=unlocked_on, world_withdrawn_on=withdrawn_on)
        if actor is None or is_substrate_actor(actor):
            return standing
        claim = get_learning_authority().method_claim(method_id)
        mine = await get_scoped_context_store().belief(str(actor), claim)
        if mine is None:
            standing.person = "not encountered"
            return standing
        standing.person_belief = float(mine["posterior"])
        standing.person_outcomes = int(mine["update_count"])
        standing.person_last_move = float(mine["posterior"]) - float(mine.get("prior") or 0.5)
        standing.person_reward = await memory_agent().person_reward(method_id, str(actor))
        person_history = await memory_agent().standing_history(method_id, str(actor))
        theirs = settled_in_favour(standing.person_belief)
        if whose == "person":
            # A METHOD THAT IS ONLY THEIRS unlocks on their own standing: the world
            # never holds it, so world-first does not apply to it.
            if theirs:
                standing.person = "unlocked"
                standing.person_unlocked_on = _last(person_history, True)
            elif _last(person_history, True) is not None:
                standing.person = "withdrawn"
                standing.person_withdrawn_on = _last(person_history, False)
            else:
                standing.person = "learning"
            return standing
        spans = _both_settled_spans(world_history, person_history)
        if theirs and state == "unlocked":
            standing.person = "unlocked"
            standing.person_unlocked_on = spans[-1][0] if spans and spans[-1][1] is None else None
        elif spans:
            standing.person = "withdrawn"
            standing.person_withdrawn_on = spans[-1][1]
        elif theirs:
            standing.person = "demonstrated"
        else:
            standing.person = "learning"
        return standing

    @staticmethod
    def _means(steps: List[str]) -> Tuple[Dict[str, List[str]], List[str]]:
        """The tools a method's steps run, each with the primitives it performs,
        read from the registry; and any step no registered tool performs."""
        from core.execution.tool_domain import predicate_for
        from core.memory.lift import from_formulas
        from core.tools.tool_registry import get_tool_registry
        registry = get_tool_registry()
        by_predicate = {predicate_for(name): name
                        for name in set(registry.tools) | set(registry.tool_factories)}
        performs: Dict[str, List[str]] = {}
        for primitive, names in registry.primitive_index.items():
            for name in names:
                performs.setdefault(name, []).append(primitive.value)
        means: Dict[str, List[str]] = {}
        unread: List[str] = []
        for fact in from_formulas(steps):
            tool = by_predicate.get(fact.predicate)
            if tool is None:
                unread.append(fact.predicate)
                continue
            means[tool] = sorted(performs.get(tool, []))
        return means, unread

    async def held(self, actor: Optional[str] = None) -> List[Capability]:
        """The world's capabilities, and the actor's own when one is named."""
        from core.agents.memory_agent import memory_agent
        from core.agents.autonomous.shared_types import is_substrate_actor
        agent = memory_agent()
        methods = [(m, r, "world") for m, r in await agent.methods_held(None)]
        if actor is not None and not is_substrate_actor(actor):
            methods += [(m, r, "person") for m, r in await agent.methods_held(str(actor))]
        out: List[Capability] = []
        for method_id, record, whose in methods:
            method = record.get("method") or {}
            steps = list(method.get("steps") or [])
            means, unread = self._means(steps)
            instances = list((record.get("instances") or {}).values())
            rewards = [float(i["reward"]) for i in instances if i.get("counted") and i.get("reward") is not None]
            out.append(Capability(
                id=method_id, whose=whose, steps=steps, shape=str(method.get("shape") or ""),
                means=means, unread=unread,
                outcomes={"counted": sum(1 for i in instances if i.get("counted")),
                          "worked": sum(1 for i in instances if i.get("counted") and i.get("worked"))},
                reward=(sum(rewards) / len(rewards)) if rewards else None,
                standing=await self.standing(method_id, whose, actor)))
        return out

    @staticmethod
    async def _methods_for(actor: Optional[str]) -> List[Tuple[str, Dict[str, Any], str]]:
        """The methods a plan for `actor` may be an instance of: their own
        first (it keeps what is theirs, so it is the nearer), then the world's."""
        from core.agents.memory_agent import memory_agent
        from core.agents.autonomous.shared_types import is_substrate_actor
        agent = memory_agent()
        held: List[Tuple[str, Dict[str, Any], str]] = []
        if actor is not None and not is_substrate_actor(actor):
            held += [(m, r, "person") for m, r in await agent.methods_held(str(actor))]
        return held + [(m, r, "world") for m, r in await agent.methods_held(None)]

    async def recognise(self, tool_plan: Any, actor: Optional[str]) -> Optional[Tuple[str, str]]:
        """The capability a declared plan is an instance of, as (method id,
        whose): one of the actor's own, or a world method; None when it is none
        (its acts are primitives, done as they are)."""
        from core.memory.lift import from_formulas, is_instance, method_facts, shape_of
        shape, facts = shape_of(tool_plan), method_facts(tool_plan)
        if shape is None or facts is None:
            return None
        for method_id, record, whose in await self._methods_for(actor):
            method = record.get("method") or {}
            if method.get("shape") == shape and is_instance(from_formulas(method.get("steps") or []), facts):
                return method_id, whose
        return None

    async def known_fix(self, tool_plan: Any, actor: Optional[str]
                        ) -> Optional[Tuple[List[Dict[str, Any]], str, str, List[Dict[str, Any]]]]:
        """What a capability overcame, for a plan about to be done: the plan
        with the fix made, the method, whose, and the changes, as
        (plan, method id, whose, [{tool, arg, value}]); None when no
        capability the actor may use has a fix that makes this plan an instance
        of it.

        A fix is where these tools failed, this argument set to this value
        (`MemoryAgent._fixes_of`): on the world's method only a value that is
        no one's particular (a tool's own word, or what the world holds), so it
        changes the approach and never the plan's own targets or content."""
        from core.memory.lift import from_formulas, is_instance, method_facts, shape_of
        if shape_of(tool_plan) is None:
            return None
        for method_id, record, whose in await self._methods_for(actor):
            method = record.get("method") or {}
            general = from_formulas(method.get("steps") or [])
            for fix in record.get("fixes") or []:
                plan = [{"tool": (step or {}).get("tool"), "args": dict((step or {}).get("args") or {})}
                        for step in tool_plan]
                changes: List[Dict[str, Any]] = []
                for use in fix.get("use") or []:
                    for step in plan:
                        if step["tool"] == use["tool"] and step["args"].get(use["arg"]) != use["value"]:
                            step["args"][use["arg"]] = use["value"]
                            changes.append(dict(use))
                facts = method_facts(plan)
                if (changes and facts is not None and shape_of(plan) == method.get("shape")
                        and is_instance(general, facts)):
                    return plan, method_id, whose, changes
        return None

    async def may_act_for(self, actor: Optional[str], method_id: str, *, whose: str,
                          asked: bool, disposition: Any = None) -> Tuple[str, str]:
        """How the substrate may use a capability for `actor` now:

          on its own     go ahead (the constitution still judges every act)
          supervised     each act waits for the person to confirm it
          not offered    not raised for them unasked

        `disposition` is appraisal's directive at this moment
        (`AutonomousCoordinator.disposition()`), read by the caller as it acts."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        from core.agents.memory_agent import memory_agent
        if whose == "person" and (actor is None or is_substrate_actor(actor) or method_id not in
                                  {m for m, _ in await memory_agent().methods_held(str(actor))}):
            # A METHOD THAT IS ONE PERSON'S is used for that person only: it keeps
            # something only they supplied, and is never the world's or anyone
            # else's.
            return "not offered", "this way of working is another person's"
        if actor is None or is_substrate_actor(actor):
            return "on its own", "the substrate's own work; the constitution judges each act"
        mode = await self.operating_mode(actor)
        if mode in (None, "observe"):
            # OBSERVE: Lyric notices and tells, and completes the work they ask for, each act confirmed; nothing is
            # done for them unasked. No mode handed over is no authority established, and is read the same way.
            why = ("their operating mode is Observe" if mode else
                   "no operating mode has reached Lyric for them")
            return ("supervised", f"{why}; done because they asked") if asked else ("not offered", why)
        standing = await self.standing(method_id, whose, actor)
        if mode == "assist":
            if standing.world != "unlocked" and not asked:
                return "not offered", ("their operating mode is Assist, and it is not unlocked for the world; "
                                       "used for a person only when they ask")
            return "supervised", "their operating mode is Assist: each act waits for their yes"
        if standing.person == "unlocked":
            if disposition is not None and (getattr(disposition, "should_avoid", False)
                                            or getattr(disposition, "should_escalate", False)):
                return "supervised", (f"unlocked for them, but the disposition now is "
                                      f"{getattr(disposition, 'mode', 'to hold back')}")
            return "on its own", f"unlocked for them since {standing.person_unlocked_on}"
        if standing.world != "unlocked" and not asked:
            return "not offered", ("not unlocked for the world; used for a person only when "
                                   "they ask")
        return "supervised", (f"their standing is {standing.person}; the world's is "
                              f"{standing.world}")

    async def discover(self, actor: Optional[str] = None) -> Dict[str, Any]:
        """What the substrate can do: the world's capabilities and, for an actor,
        theirs by standing."""
        held = await self.held(actor)

        def view(c: Capability) -> Dict[str, Any]:
            s = c.standing
            return {"id": c.id, "whose": c.whose, "steps": c.steps, "means": c.means,
                    "unread": c.unread, "outcomes": c.outcomes,
                    # The score, in its two parts, side by side until it is
                    # decided how they combine: the standing belief, and the
                    # reward the experiences carried.
                    "world": {"standing": s.world, "belief": s.world_belief, "reward": c.reward,
                              "last_move": s.world_last_move,
                              "unlocked_on": s.world_unlocked_on, "withdrawn_on": s.world_withdrawn_on},
                    "person": None if s.person is None else {
                        "standing": s.person, "belief": s.person_belief, "reward": s.person_reward,
                        "last_move": s.person_last_move,
                        "outcomes": s.person_outcomes, "unlocked_on": s.person_unlocked_on,
                        "withdrawn_on": s.person_withdrawn_on}}
        report: Dict[str, Any] = {"world": [view(c) for c in held if c.whose == "world"]}
        if actor is not None:
            mine: Dict[str, List[Dict[str, Any]]] = {}
            for c in held:
                state = c.standing.person
                if state and state != "not encountered":
                    mine.setdefault(state, []).append(view(c))
            report["person"] = {"actor": actor, **mine}
        return report


def _grounded(belief: Any) -> bool:
    from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem
    return BayesianUncertaintySystem.is_grounded(belief)


_capabilities: Optional[Capabilities] = None


def get_capabilities() -> Capabilities:
    """The one capabilities faculty."""
    global _capabilities
    if _capabilities is None:
        _capabilities = Capabilities()
    return _capabilities
