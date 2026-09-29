#!/usr/bin/env python3
"""A domain the substrate can act in, DERIVED from the tools it already has.

THE CLAIM THIS EXISTS TO KEEP TRUE: the substrate can learn to do anything.
It cannot, if every domain it may act in has to be hand-written first.

A domain becomes learnable when two things hold — it is OBSERVABLE (its state
can be read back from the world) and ACTABLE (a real tool changes it). Neither
is written by hand. The domain authority diagnoses the two gaps honestly
(`BINDING_GAP`,
`OBSERVATION_GAP`) and routes both to ESCALATE — "input the substrate cannot
self-supply". That is true of a tool that does not exist. It is NOT true of one
that does, sitting in the registry, declaring its own name, its typed parameters
and what it does to the world.

So this derives both halves from what a tool already says about itself:

  ACTING       every tool the consequence map classes as changing the world
               becomes an operator. The predicate is the tool's name; the
               operator's arguments ARE the tool's declared parameters, in
               declared order. Nothing is invented — the mapping back is a zip.

  OBSERVING    what the self perceives with its own senses -- the filesystem,
               path by path -- is read by that sense and by no tool: one
               observation, one interpretation. Every other kind is read by the
               tools the same map classes `investigate`, which change nothing
               and report something; their results are lifted to facts by
               shape, not by meaning.

WHAT THIS DELIBERATELY DOES NOT DO is invent a vocabulary. A hand-written domain
can say `FILE_IN(file, dir)` because a person knew that a file is in a directory;
derived facts say what the tool reported, in the tool's own words. That is
coarser, and it is honest: the substrate learns the structure that is actually
there rather than one somebody imagined for it. Whether coarse facts are enough
to induce a usable operator is a question for measurement, not for argument —
see experiments/TOOLDOMAIN-01.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple

from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact

logger = logging.getLogger(__name__)

#: Consequence classes that CHANGE the world. An operator is something that can
#: move the world from one state to another, so a tool that changes nothing is
#: not an operator however useful it is.
ACTING_CLASSES = ("modify", "archive", "delete", "execute")

#: The class that changes nothing and reports something.
OBSERVING_CLASS = "investigate"

#: The observer name for the self's own perception. A resource of a kind the
#: self senses is read by that sense and by no tool: one observation, one
#: interpretation.
SELF_SENSE = "self"

#: What names a derived domain: the kinds of resource its acts touch.
DERIVED_PREFIX = "tools:"


def derived_domain_id(kinds) -> str:
    """The domain an act belongs to, named by the kinds of thing it touches."""
    return DERIVED_PREFIX + "-".join(sorted(set(kinds)))


def _encode(value: Any) -> str:
    """Any reported value as a logic constant, bijectively.

    The same escape scheme the filesystem domain uses, for the same reason: a
    term must be an identifier and the world is full of dots, slashes and
    spaces. Dropping such values would make the substrate blind to exactly the
    things tools report.
    """
    out = ["F"]
    for byte in str(value).encode("utf-8"):
        ch = chr(byte)
        out.append(ch if (ch.isascii() and ch.isalnum()) else "_%02x" % byte)
    return "".join(out)


def _decode(ident: str) -> str:
    """Invert `_encode`. An action carries encoded terms; the tool needs the
    real values back before it runs."""
    body = ident[1:] if ident.startswith("F") else ident
    buffer = bytearray()
    index = 0
    while index < len(body):
        if body[index] == "_":
            try:
                buffer.append(int(body[index + 1:index + 3], 16))
                index += 3
                continue
            except ValueError:
                pass
        buffer.append(ord(body[index]))
        index += 1
    return buffer.decode("utf-8", errors="replace")


def predicate_for(tool_name: str) -> str:
    """The operator name for a tool. Its own name, upper-cased — never a
    invented one, so the rule the substrate learns can always be traced back to
    the thing that does it."""
    return "".join(ch if ch.isalnum() else "_" for ch in str(tool_name)).upper()


def declared_parameters(tool) -> List[Any]:
    """The tool's declared parameters, in declared order -- TYPED ones only.

    Six of the 356 registered tools put a raw JSON schema here instead of
    `ToolParameter` records, so `parameters` reads as the bare strings
    ("type", "properties", "required"). Nothing can be derived from those: a
    string is not a name, a type or a requirement. They are dropped rather than
    guessed at, which makes such a tool honestly underivable instead of binding
    an operator whose arguments are the words of a schema.
    """
    declared = list(getattr(tool, "parameters", None) or [])
    typed = [p for p in declared if hasattr(p, "name") and hasattr(p, "type")]
    if declared and not typed:
        logger.debug("%s declares untyped parameters; nothing to derive from it",
                     getattr(tool, "name", tool))
    return typed


def action_binding(tool_name: str, tool, observe) -> Optional[OperatorBinding]:
    """One operator, derived from what the tool declares about itself.

    ITS ARGUMENTS ARE THE TOOL'S RESOURCE PARAMETERS, in declared order. Those
    are the only ones whose values appear as terms in the observed world, and an
    argument that appears nowhere in the world is one induction can never
    connect to a precondition or an effect. It is also what keeps this operator
    the SAME operator `ActFrame` names when the substrate watches itself act --
    two spellings of MOVE_FILE at different arities would split one capability's
    evidence in half, which is how one file move came to be relearned eight
    times.

    EVERY OTHER DECLARED PARAMETER IS SUPPLIED FROM ITS OWN DECLARED DEFAULT,
    and the trade deserves stating because the alternative is defensible too.
    A hand-written binding could pin `create_dirs=False`, so that a move to a
    directory that is not there FAILS and gives the learner a negative to learn
    from. That is a person's judgement about what makes a good lesson, and it
    cannot be derived. Exposing the option instead makes it
    an argument the learner must vary blindly, with no term in the world to
    reason about.

    So the option takes the value the tool itself would use. The cost is real
    and worth naming: `move_file` defaults `create_dirs=True`, so a move to a
    missing directory SUCCEEDS, and the substrate will not learn a
    destination-directory precondition from it. What it learns instead is true
    of the operator it actually performs -- called this way, `move_file` really
    does not require the destination to exist. Negative evidence still comes
    from the world (a source that is not there, a path it may not write), just
    not from an option set to make the act fail.
    """
    resources = resource_parameters(tool)
    if not resources:
        return None
    declared = declared_parameters(tool)
    names = [str(p.name) for p in resources]

    def parameters(args: Sequence[str]) -> Dict[str, Any]:
        supplied: Dict[str, Any] = {}
        for name, raw, declared_param in zip(names, args, resources):
            supplied[name] = _coerce(_decode(str(raw)), declared_param)
        for parameter in declared:
            if parameter.name not in supplied:
                default = getattr(parameter, "default", None)
                if default is not None:
                    supplied[parameter.name] = default
                elif (getattr(parameter, "required", False)
                      and str(getattr(parameter, "type", "")).lower() == "boolean"):
                    # A REQUIRED YES/NO WITH NO DEFAULT IS A GATE THE CALLER
                    # OPENS TO PROCEED -- `delete_file`'s `confirm`, "must be set
                    # to true to proceed", is the one in the registry. It changes
                    # nothing about what the act does. An act performed through a
                    # binding has already been judged by the constitution, so
                    # performing it is proceeding.
                    supplied[parameter.name] = True
        return supplied

    return OperatorBinding(
        predicate=predicate_for(tool_name), tool_name=tool_name,
        parameters=parameters, observe=observe,
        observe_async=getattr(observe, "__self__", None) and
                      getattr(observe.__self__, "observe_async", None),
        description=str(getattr(tool, "description", "") or ""))


def _coerce(value: str, declared) -> Any:
    """A logic constant back to the type the tool declared.

    Terms are strings because logic constants are; tools take booleans and
    numbers. Reported honestly rather than guessed: a value that does not parse
    as its declared type is passed through as the string it is, so the tool's
    own validation refuses it rather than this silently substituting something.
    """
    kind = str(getattr(declared, "type", "") or "").lower()
    if kind == "boolean":
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
        return value
    if kind in ("number", "integer"):
        try:
            return int(value) if kind == "integer" or value.isdigit() else float(value)
        except ValueError:
            return value
    return value


def facts_from(report: Any, *, source: str) -> FrozenSet[Fact]:
    """What an observation tool reported, as facts — read by SHAPE, not meaning.

    Three shapes cover what tools actually return, and each maps to relations
    the same way regardless of what the tool is about:

      {"files": ["a/b.txt", ...]}   a named list  -> FILES(<source>, <item>)
      {"total_files": 1}            a named scalar -> TOTAL_FILES(<source>, 1)
      [{"id": 1, "state": "open"}]  a list of records -> STATE(<id>, open)

    NOTHING HERE KNOWS WHAT A FILE IS. `FILES(root, inbox/report.txt)` is not as
    good a fact as `FILE_IN(report, inbox)`, and that is the honest trade: the
    substrate reads the structure the tool actually reports instead of one
    somebody wrote down for it in advance. A fact that changes when the world
    changes is all induction needs; whether these are sharp enough to induce a
    usable operator is measured, not asserted.
    """
    facts: set = set()
    subject = _encode(source)

    def add(predicate: str, args: Tuple[str, ...]) -> None:
        name = "".join(ch if ch.isalnum() else "_" for ch in predicate).upper()
        if name and name[0].isdigit():
            name = "P" + name
        if name:
            facts.add(Fact(name, args))

    def walk(value: Any, subject_term: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (str, int, float, bool)) or item is None:
                    if item is not None:
                        add(str(key), (subject_term, _encode(item)))
                elif isinstance(item, list):
                    for entry in item:
                        if isinstance(entry, (str, int, float, bool)):
                            add(str(key), (subject_term, _encode(entry)))
                        elif isinstance(entry, dict):
                            # A LIST OF RECORDS names its own subjects.
                            ident = entry.get("id") or entry.get("name") or \
                                entry.get("path")
                            walk(entry, _encode(ident) if ident else subject_term)
                elif isinstance(item, dict):
                    walk(item, subject_term)
        elif isinstance(value, list):
            for entry in value:
                walk(entry, subject_term)

    walk(report, subject)
    return frozenset(facts)


def _senses() -> Dict[str, Any]:
    from core.agents.autonomous.autonomous_coordinator import SENSES
    return SENSES


def identity(kind: str, value: str) -> str:
    """The one name a resource goes by. A kind the self senses is named the way
    its sense names it, so a file reached by two spellings is one term; any
    other kind is taken as given."""
    sensed = _senses().get(kind)
    return sensed.identify(value) if sensed is not None else value


def term(kind: str, value: str) -> str:
    """A resource as a logic term: its identity, encoded. What a goal must use to
    speak about the same thing the substrate perceives and acts on."""
    return _encode(identity(kind, value))


def sensed_fact(measure: str, kind: str, value: str, measured: Any) -> Fact:
    """The fact the self's perception states when `value` measures `measured`
    -- that a path is a file, say. What a goal says, in perception's words."""
    return Fact(measure.upper(), (term(kind, value), _encode(measured)))


#: What the self's perception MEASURES about a thing: what kind it is, its size,
#: and which thing it is. Its name, extension and depth are read off the path
#: itself and change only when the path does, so as facts they would only
#: restate the term they are about.
SENSED_MEASURES = ("kind", "size", "identity")

#: The measures that say what a thing is LIKE, as opposed to which thing it is:
#: two copies of one file are alike and are two things.
DESCRIBING_MEASURES = ("kind", "size")

#: What the self's perception states when it looks at a place and nothing is
#: there. A fact of its own rather than a kind called "none": nothing is not a
#: kind of thing, and as a value it would read as something an act carries --
#: a move would be learned to give its source whatever its destination held.
ABSENT = "ABSENT"


def gone_everywhere(kind: str, value: str) -> Optional[str]:
    """The goal that the thing now at `value` exists nowhere: no place holds its
    identity. A removal asked for is this, not "nothing at this path", which a
    move satisfies while keeping the thing. None when nothing is there to
    identify."""
    held = next((fact for fact in (sense(kind, value) or ())
                 if fact.predicate == "IDENTITY"), None)
    return f"¬IDENTITY(?where, {held.args[1]})" if held is not None else None


def sense(kind: str, value: str) -> Optional[FrozenSet[Fact]]:
    """The self's own reading of one resource, as facts about its identity.

    ABSENT(<it>) when nothing is there: the world answered, and "nothing is
    here" is what a move leaves at its source and what it needs at its
    destination. None when the thing could not be looked at, or is not a kind
    the self senses, which is not the same.
    """
    sensed = _senses().get(kind)
    if sensed is None:
        return None
    name = sensed.identify(value)
    try:
        entry = sensed.perceive(name)
    except OSError:
        return None
    subject = _encode(name)
    if entry is None:
        return frozenset({Fact(ABSENT, (subject,))})
    return frozenset(Fact(measure.upper(), (subject, _encode(entry[measure])))
                     for measure in SENSED_MEASURES if entry.get(measure) is not None)


class ToolObservedWorld:
    """A world read by running the domain's declared observation tools.

    An observer is not derivable from a tool alone: a tool needs ARGUMENTS, and
    which directory (or repository, or case queue) this domain is about is the
    one thing the registry cannot know. So a domain declares its observations as
    (tool, arguments) pairs -- a line, not a class -- and everything after that
    is mechanical.

    UNREADABLE IS NOT EMPTY. If no observation succeeds, this returns None:
    planning against a world that was never read authorises a plan on a state
    that does not exist.
    """

    def __init__(self, domain_id: str,
                 observations: Sequence[Tuple[str, Dict[str, Any]]]) -> None:
        self.domain_id = domain_id
        self.observations = list(observations)
        self._registry = None

    def _tools(self):
        if self._registry is None:
            from core.tools import get_tool_registry
            self._registry = get_tool_registry()
        return self._registry

    def _current_observations(self) -> List[Tuple[str, Dict[str, Any]]]:
        """The observations a reading of this world is made of, now."""
        return list(self.observations)

    def observe(self) -> Optional[FrozenSet[Fact]]:
        """Read the world NOW, by looking.

        Runs synchronously from whatever context asks, because `observe` is a
        plain callable in the binding contract and every existing caller treats
        it as one. What the self senses is read directly; only observations made
        by running tools need a loop.
        """
        current = self._current_observations()
        if all(tool == SELF_SENSE for tool, _ in current):
            return self._read_sensed(current)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            # An async caller should be using `observe_async` (the binding
            # carries it). Reaching here means a synchronous caller inside a
            # running loop, and the thread below is the only way to serve it.
            # Already inside the substrate's loop: the observation tools are
            # investigate-class and cheap, but they are coroutines, so they are
            # run on a private loop in a worker thread rather than blocking this
            # one or being silently skipped.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(self._observe(current))).result()
        return asyncio.run(self._observe(current))

    async def observe_async(self) -> Optional[FrozenSet[Fact]]:
        """Read the world on the CALLER'S loop. The honest path for a world made
        of tools -- see `OperatorBinding.observe_async`."""
        return await self._observe()

    @staticmethod
    def _read_sensed(observations) -> Optional[FrozenSet[Fact]]:
        """What the self senses of these resources; None if it could see none."""
        facts: set = set()
        read_anything = False
        for _sense, arguments in observations:
            for kind, value in arguments.items():
                answered = sense(kind, value)
                if answered is not None:
                    read_anything = True
                    facts |= answered
        return frozenset(facts) if read_anything else None

    async def _observe(self, observations=None) -> Optional[FrozenSet[Fact]]:
        current = (self._current_observations() if observations is None
                   else list(observations))
        facts: set = set()
        read_anything = False
        sensed = self._read_sensed([o for o in current if o[0] == SELF_SENSE])
        if sensed is not None:
            read_anything = True
            facts |= sensed
        tooled = [o for o in current if o[0] != SELF_SENSE]
        registry = self._tools() if tooled else None
        for tool_name, arguments in tooled:
            try:
                result = await registry.execute_tool(tool_name, dict(arguments))
            except Exception as e:
                logger.info("observation %s of %s raised: %s",
                            tool_name, self.domain_id, e)
                continue
            if not getattr(result, "success", False):
                continue
            read_anything = True
            source = next((str(v) for v in arguments.values() if v), tool_name)
            output = getattr(result, "output", None)
            facts |= facts_from(output, source=source)
        if not read_anything:
            return None
        return frozenset(facts)



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
                acts.append(Fact(binding.predicate, (_encode(order[0]),)))
            else:
                for thing in order:
                    places = [p for p in (sensed.relocate(thing, c) for c in containers)
                              if p != thing and free(sensed, p)]
                    if places:
                        there = places[turn % len(places)]
                        claimed.add(there)
                        acts.append(Fact(binding.predicate, (_encode(thing), _encode(there))))
                        acts.append(Fact(binding.predicate, (_encode(there), _encode(thing))))
                        break
            rounds.append(acts)

        # THEN, WHAT EACH DOES WHEN IT CANNOT, from what is still free: the
        # contrasts use only places no working act needed.
        for index, (binding, arity_, sensed, things, containers) in enumerate(practisable):
            spare = free_places(sensed, containers, things)
            if arity_ == 1 and spare:
                absent = spare[turn % len(spare)]
                claimed.add(absent)
                rounds[index].append(Fact(binding.predicate, (_encode(absent),)))
            elif arity_ == 2:
                if len(spare) >= 2:
                    absent, target = spare[turn % len(spare)], spare[(turn + 1) % len(spare)]
                    if absent != target:
                        claimed.update((absent, target))
                        rounds[index].append(Fact(binding.predicate,
                                                  (_encode(absent), _encode(target))))
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
                                              (_encode(thing), _encode(taken[turn % len(taken)]))))
        return [act for acts in rounds for act in acts]

    return propose



# =============================================================================
# WATCHING AN ACT THE SUBSTRATE WAS NEVER TAUGHT
# =============================================================================
#
# The header above names the gap this section closes:
#
#     "An observer is not derivable from a tool alone: a tool needs ARGUMENTS,
#      and which directory (or repository, or case queue) this domain is about
#      is the one thing the registry cannot know."
#
# A CALL KNOWS. `move_file(source_path=A, destination_path=B)` names A and B.
# So the arguments the registry could not supply come from the act itself, and
# nobody has to declare a domain, a directory or a tool list before the
# substrate can watch itself act. Point it at a SOC and the act names a host or
# an address instead; nothing here knows the difference.
#
# WHY THIS EXISTS AT ALL. `_execute_via_substrate` already observes before,
# acts, re-observes and files the triple -- but only after it has found a
# VALIDATED learned rule, in a declared domain, with a registered binding. You
# need an operator to record the demonstration that would teach you an
# operator. Every other act the substrate performs went through `_run_tool`,
# which observed no world state at all: 185 acting tools producing evidence for
# the completion judgment ("did I reach the goal?") and none for learning what
# the act DOES. That is why 898,593 knowledge items sat beside 14 operators.

#: How long one reading of a WARM observation may take. Past it the answer is
#: UNKNOWN, not empty -- see `observe_resources`.
OBSERVATION_BUDGET_SECONDS = 10.0

#: The budget for an observation that has never run in this process.
#:
#: A tool's FIRST execution loads the tool; every execution after it answers
#: about the world. Measured on the live registry: first call 11.6s, then
#: 0.1-0.4ms. Charging the load to the observation budget is what made the first
#: watched act read nothing at all -- 38 readings started cold at once, all but
#: the few that failed fast exceeded 10s, and the frame kept only the failures.
#: The budget exists to bound how long the substrate waits for an ANSWER, not
#: how long a tool takes to load itself once, so the two are separated. The
#: readings run concurrently, so this is paid once per process as roughly the
#: slowest single load, not once per observation.
COLD_OBSERVATION_BUDGET_SECONDS = 60.0

#: Observations that have completed at least once in this process, whatever
#: they answered. A tool that ran and reported "not a directory" is warm; it
#: answered. Only an observation that has never returned is charged the cold
#: budget.
_OBSERVER_WARM: set = set()

#: Parameter names carrying a PAYLOAD rather than naming a thing in the world.
#: Their value is bytes the act writes, not a resource that can be looked at,
#: so they are neither observable nor usable as a logic term.
PAYLOAD_PARAMS = frozenset({
    "content", "code", "command", "data", "body", "text", "payload", "sql",
})

#: tool -> the predicates its reports were OBSERVED to produce. Grown from real
#: readings, never declared. Empty after a restart, which costs one wide
#: reading per tool to refill -- the durable half (which predicates actually
#: discriminate) lives in `unified.operator_demonstrations` and survives.
_OBSERVER_PREDICATES: Dict[str, set] = {}

_OBSERVER_INDEX: Optional[Dict[str, List[Tuple[str, str]]]] = None


def resource_kind(parameter_name: str) -> str:
    """The KIND of thing a parameter names, from its head noun.

    `source_path`, `destination_path`, `directory_path` and `path` all name a
    path; `host` names a host. English compounds put the head last, so the final
    underscore-delimited token is the kind and what precedes it is the ROLE that
    parameter plays in this particular act.

    THIS IS A CANDIDATE GENERATOR, NOT AN AUTHORITY, and the distinction is the
    whole reason the rest of this section exists. Measured against the live
    registry, the rule also claims `metric_name`, `table_name` and
    `service_name` are the same kind of thing. They are not. A name cannot
    settle what a thing is, so nothing here relies on it being right: an
    observer it proposes is kept only if the world answers when it is pointed at
    the value, and kept in the frame only if it was observed to DISCRIMINATE.
    Naming proposes; the world disposes.
    """
    return str(parameter_name).strip().lower().rsplit("_", 1)[-1]


def observer_index(*, rebuild: bool = False) -> Dict[str, List[Tuple[str, str]]]:
    """kind -> [(tool_name, parameter_name)] for every POINTABLE observation.

    Two conditions, both read off the tool's own declaration:

      it changes nothing    `classify_action` puts it in `investigate`. An
                            observation taken twice around an act must not be
                            able to alter the world it is reading, or the
                            before/after difference is partly the reader's own
                            doing.

      it can be pointed     exactly ONE required parameter, and that parameter
                            is a string. A tool with two required arguments
                            needs a second value nobody has, and inventing one
                            is how an observation starts reporting on something
                            other than what the act touched.

    A function of the registry rather than of any call, so it is built once.
    """
    global _OBSERVER_INDEX
    if _OBSERVER_INDEX is not None and not rebuild:
        return _OBSERVER_INDEX

    from core.agents.autonomous.autonomous_coordinator import classify_action
    from core.tools import get_tool_registry

    registry = get_tool_registry()
    index: Dict[str, List[Tuple[str, str]]] = {}
    for name in sorted(set(list(registry.tools) + list(registry.tool_factories))):
        try:
            tool = registry.get_tool(name)
        except Exception:
            continue
        if tool is None:
            continue
        declared = declared_parameters(tool)
        if not declared:
            continue
        try:
            action_class, _ = classify_action(name, {})
        except Exception:
            continue
        if getattr(action_class, "value", str(action_class)) != OBSERVING_CLASS:
            continue
        required = [p for p in declared if getattr(p, "required", False)]
        if len(required) != 1:
            continue
        only = required[0]
        if str(getattr(only, "type", "")).lower() != "string":
            continue
        index.setdefault(resource_kind(only.name), []).append((name, str(only.name)))

    _OBSERVER_INDEX = index
    logger.info("observation index: %d kind(s) the substrate can be pointed at",
                len(index))
    return index


def resource_parameters(tool) -> List[Any]:
    """The declared parameters that NAME SOMETHING IN THE WORLD.

    A parameter names a resource exactly when the substrate has some way of
    LOOKING at that kind of thing -- when `observer_index` holds an entry for
    its kind. That is not a list of resource-ish words; it is the observability
    requirement itself, applied per argument. `grep_search(pattern=...)` names
    no resource because nothing in the registry can be pointed at a `pattern`,
    while `path` is one because `read_file`, `list_directory` and `get_file_info`
    can each be pointed at one.

    An unobservable argument is therefore not a defect to route around. It is
    the honest report that the substrate can change something it cannot see, and
    it must not become a term in an operator: a rule whose precondition can
    never be read is a rule that can never be checked.
    """
    index = observer_index()
    senses = _senses()
    return [p for p in declared_parameters(tool)
            if str(getattr(p, "type", "")).lower() == "string"
            and str(p.name).lower() not in PAYLOAD_PARAMS
            and (resource_kind(p.name) in senses or resource_kind(p.name) in index)]


async def observe_resources(
    readings: Sequence[Tuple[str, str, str]],
) -> Dict[Tuple[str, str], Optional[FrozenSet[Fact]]]:
    """Point each observation at each value and keep the three answers apart.

    UNREADABLE IS NOT EMPTY, and "the world says no" is not "we could not ask":

      facts          the observation ran and reported. What it reported becomes
                     facts by shape, in the tool's own words.
      frozenset()    the observation ran and the world answered NOTHING -- a
                     `read_file` of a path that is gone, a `list_directory` of
                     something that is not a directory. That is a reading, and
                     it is exactly the reading a deletion is supposed to produce.
      None           the observation did not complete: it raised, or the budget
                     expired. Nothing about the world follows from that, so a
                     None on EITHER side removes that reading from BOTH -- see
                     `ActFrame.close`. Letting it stand as empty would make
                     every fact it had reported before the act look deleted by
                     the act, which is a fabricated effect.

    READINGS RUN IN SERIES, and that is a measurement rather than a preference.
    Asking them concurrently looks right -- they are independent questions about
    a world that is moving, and a serial pass spreads the "before" over a span
    in which it could change. But most of these tools do blocking work inside an
    `async def`, so `gather` yields no concurrency at all: 38 readings that take
    45ms in series did not finish in 60s under `gather`, and the first watched
    act read nothing. A budget cannot preempt a blocking body either, so
    `wait_for` bounds only the tools that actually await. The serial pass is
    what the registry supports; the alternative was a frame that timed out.
    """
    from core.tools import get_tool_registry

    registry = get_tool_registry()

    async def one(observer: str, parameter: str, value: str):
        # A READING IS RECORDED AS ONE. The registry records every tool run for
        # learning, attributed to the task the run serves; these serve none --
        # they are the substrate looking at the world around an act -- so they
        # say so, rather than reading as anonymous tool use.
        from core.reasoning.intent_authority import set_acting_task, reset_acting_task
        token = set_acting_task("observation", f"observing {parameter}={value} with {observer}")
        try:
            result = await registry.execute_tool(observer, {parameter: value})
        finally:
            reset_acting_task(token)
        if not getattr(result, "success", False):
            # A REFUSAL IS NOT A READING. The constitution is wired to
            # `execute_tool`, so it judges these observations too. An act it
            # refused never ran, and reporting "the world answered nothing"
            # would turn the substrate's own law into evidence about the world
            # -- the same false negative that once refuted a validated operator
            # because Law 2 had replanned the move behind it.
            if (getattr(result, "metadata", None) or {}).get(
                    "error_type") == "CONSTITUTION_REFUSED":
                return None
            return frozenset()
        return facts_from(getattr(result, "output", None), source=value)

    unique: List[Tuple[str, str, str]] = []
    seen: set = set()
    for observer, parameter, value in readings:
        if (observer, value) not in seen:
            seen.add((observer, value))
            unique.append((observer, parameter, value))

    out: Dict[Tuple[str, str], Optional[FrozenSet[Fact]]] = {}
    for observer, parameter, value in unique:
        if observer == SELF_SENSE:
            # The self's own perception: `parameter` carries the kind it senses.
            out[(observer, value)] = sense(parameter, value)
            continue
        budget = (OBSERVATION_BUDGET_SECONDS if observer in _OBSERVER_WARM
                  else COLD_OBSERVATION_BUDGET_SECONDS)
        try:
            answer = await asyncio.wait_for(one(observer, parameter, value),
                                            timeout=budget)
        except Exception as e:
            logger.debug("observation %s of %r did not complete: %s",
                         observer, value, type(e).__name__)
            out[(observer, value)] = None
            continue
        out[(observer, value)] = answer
        # It ANSWERED -- including "not a directory", which is an answer about
        # the world. Only a reading that never returned stays cold.
        _OBSERVER_WARM.add(observer)
        if answer:  # None (refused/incomplete) and frozenset() both teach nothing here
            _OBSERVER_PREDICATES.setdefault(observer, set()).update(
                fact.predicate for fact in answer)
    return out


#: (domain_id, predicate, arity) -> the predicates that were observed to change.
#: Memoised because it is read before every act; refreshed when that signature
#: gains a demonstration (`note_demonstration`).
_DISCRIMINATING: Dict[Tuple[str, str, int], FrozenSet[str]] = {}


def note_demonstration(domain_id: str, predicate: str, arity: int) -> None:
    """Forget the memo for a signature that just gained evidence, so the next
    act re-reads what discriminates instead of trusting a stale answer."""
    _DISCRIMINATING.pop((domain_id, predicate, arity), None)


async def discriminating_predicates(domain_id: str, predicate: str,
                                    arity: int) -> FrozenSet[str]:
    """Which predicates this operator was OBSERVED to move.

    THE FRAME IS LEARNED, NOT CHOSEN. Pointed at a file, 14 of 19 observations
    answer -- `find_dead_code`, `find_todos`, `trace_dependencies` and
    `security_scan` all report happily on a file that was moved, and none of it
    is what the move did. Keeping all of them would put the induction back where
    an unscoped generalisation retained 4098 literals and the suite stopped
    finishing.

    So an observation earns its place in the frame by having reported something
    that CHANGED when this operator ran. That is read from the demonstrations
    already stored for the signature, which is why it survives a restart with no
    table of its own: the evidence is the calibration.

    Empty while a signature has no demonstrations yet -- the bootstrap, where
    the substrate watches everything it can once in order to find out what is
    worth watching.
    """
    key = (domain_id, predicate, arity)
    memo = _DISCRIMINATING.get(key)
    if memo is not None:
        return memo

    from core.learning.demonstration_store import get_demonstration_store
    try:
        examples = await get_demonstration_store().load(
            domain_id=domain_id, predicate=predicate, arity=arity)
    except Exception as e:
        # An unreadable store is not an empty one. Returning "nothing
        # discriminates" would silently narrow every future frame to nothing.
        logger.warning("could not read demonstrations for %s/%d in %s: %s",
                       predicate, arity, domain_id, e)
        return frozenset()

    moved: set = set()
    for example in examples:
        before = {f.predicate for f in example.before}
        after = {f.predicate for f in example.after}
        moved |= before ^ after
        # A predicate present on both sides may still have MOVED -- the same
        # relation about different arguments. Compared as whole facts, not as
        # bare names, or a rename inside one predicate reads as no change.
        moved |= {f.predicate for f in set(example.before) ^ set(example.after)}

    result = frozenset(moved)
    _DISCRIMINATING[key] = result
    return result


class ActFrame:
    """The world one act touches, read before it and again after it.

    This is the before/action/after triple for an act nobody planned, in a
    domain nobody declared. It is opened from the call's own arguments, so the
    substrate can watch itself do something it has never done, in an environment
    it was never told about.

    THE SAME QUESTIONS BOTH TIMES. The readings are fixed when the frame opens
    and re-run unchanged when it closes. A frame that asked different questions
    either side of the act would report the difference between two questions as
    an effect of the act.
    """

    def __init__(self, *, tool_name: str, action: Fact, domain_id: str,
                 readings: List[Tuple[str, str, str]],
                 before: Dict[Tuple[str, str], Optional[FrozenSet[Fact]]]) -> None:
        self.tool_name = tool_name
        self.action = action
        self.domain_id = domain_id
        self._readings = readings
        self._before = before

    @classmethod
    async def open(cls, tool_name: str,
                   parameters: Dict[str, Any]) -> Optional["ActFrame"]:
        """Read the world this call is about to touch, or decline to watch.

        Declines (None), never guesses, when:
          - the tool is not registered, or declares no typed parameters;
          - no argument names anything the substrate can look at, so there is
            no world here to have a before and an after;
          - nothing could be read at all, which is not the same as an empty
            world and must not be planned or learned from as if it were.
        """
        from core.agents.autonomous.autonomous_coordinator import classify_action
        from core.tools import get_tool_registry

        tool = get_tool_registry().get_tool(tool_name)
        if tool is None:
            return None

        # ONLY AN ACT HAS AN EFFECT TO LEARN. An investigation changes nothing,
        # so watching one would spend two readings to observe that the world
        # stayed as it was -- and would file that as a demonstration that the
        # investigation does nothing, which is true and useless.
        try:
            action_class, _ = classify_action(tool_name, parameters or {})
        except Exception as e:
            logger.debug("%s could not be classified; not watching it: %s",
                         tool_name, e)
            return None
        if getattr(action_class, "value", str(action_class)) not in ACTING_CLASSES:
            return None

        resources: List[Tuple[str, str]] = []
        for parameter in resource_parameters(tool):
            value = parameters.get(parameter.name)
            if isinstance(value, str) and value.strip():
                kind = resource_kind(parameter.name)
                resources.append((kind, identity(kind, value)))
        if not resources:
            return None

        action = Fact(predicate_for(tool_name),
                      tuple(_encode(value) for _kind, value in resources))
        domain_id = derived_domain_id(kind for kind, _ in resources)

        # A kind the self senses is read by that sense alone; any other kind by
        # the tools that can be pointed at it.
        senses = _senses()
        index = observer_index()
        candidates: List[Tuple[str, str, str]] = []
        for kind, value in resources:
            if kind in senses:
                candidates.append((SELF_SENSE, kind, value))
            else:
                candidates.extend((observer, parameter, value)
                                  for observer, parameter in index.get(kind, ()))
        readings = await cls._earned(domain_id, action, candidates)
        if not readings:
            return None

        before = await observe_resources(readings)
        if all(facts is None for facts in before.values()):
            logger.info("%s: the world could not be read before acting; "
                        "not watching this act", tool_name)
            return None
        return cls(tool_name=tool_name, action=action, domain_id=domain_id,
                   readings=readings, before=before)

    @staticmethod
    async def _earned(domain_id: str, action: Fact,
                      candidates: List[Tuple[str, str, str]]
                      ) -> List[Tuple[str, str, str]]:
        """Narrow the candidates to the observations that have EARNED a place.

        An observation earns it by having reported something this operator was
        seen to move. Until that is known -- a signature with no demonstrations,
        or a process that has not yet learned which observation produces which
        predicate -- everything pointable is read, which is the bootstrap that
        produces the evidence the narrowing is made of.

        NARROWED BY OBSERVATION, NOT BY FACT. A discriminating observation is
        one watching the right ASPECT of the world; its UNCHANGED facts are
        exactly the preconditions. Keeping only facts that moved would throw the
        preconditions away and leave an operator that names its effects and
        nothing it needs.
        """
        discriminating = await discriminating_predicates(
            domain_id, action.predicate, action.arity)
        if not discriminating:
            return candidates
        earned = [observer for observer, produced in _OBSERVER_PREDICATES.items()
                  if produced & discriminating]
        if not earned:
            return candidates
        narrowed = [c for c in candidates if c[0] == SELF_SENSE or c[0] in earned]
        return narrowed or candidates

    async def close(self) -> Optional[Tuple[FrozenSet[Fact], FrozenSet[Fact]]]:
        """Re-read the world and return (before, after) over the readings that
        answered BOTH times.

        A reading that did not complete on either side is dropped from both,
        because an unknown is not a state and the difference between a known and
        an unknown is not an effect. Returns None when nothing survives -- the
        world was not legible around this act, and `_record_execution_
        demonstration` already refuses to file a demonstration in that case.
        """
        after = await observe_resources(self._readings)
        agreed = [key for key, facts in after.items()
                  if facts is not None and self._before.get(key) is not None]
        if not agreed:
            logger.info("%s: no reading answered both before and after; "
                        "nothing observed about this act", self.tool_name)
            return None

        before_facts: set = set()
        after_facts: set = set()
        for key in agreed:
            before_facts |= self._before[key]
            after_facts |= after[key]
        return frozenset(before_facts), frozenset(after_facts)


async def domain_discriminating(domain_id: str) -> FrozenSet[str]:
    """Every predicate any operator of this domain was observed to move."""
    from core.learning.demonstration_store import get_demonstration_store

    demos = get_demonstration_store()
    try:
        signatures = await demos.signatures(domain_id=domain_id)
    except Exception as e:
        logger.warning("could not read the signatures of %s: %s", domain_id, e)
        return frozenset()
    moved: set = set()
    for predicate, arity in signatures:
        if (predicate, arity) == demos.CONTRASTIVE:
            continue
        moved |= await discriminating_predicates(domain_id, predicate, arity)
    return frozenset(moved)


class EncounteredWorld(ToolObservedWorld):
    """A domain's world, made of the resources the substrate has ACTUALLY MET.

    THIS IS THE OTHER HALF OF THE GAP IN THIS MODULE'S HEADER. `ToolObservedWorld`
    needs (tool, arguments) pairs, and the arguments -- which directory,
    repository or case queue this domain is about -- are what the registry
    cannot know. A task that names a workspace supplies them
    (`take_up_workspace`), and so does every act: it names what it touches.

    ACTING NAMES THE PLACE. Every act names the resources it touches, so a
    domain's world can be assembled from what the substrate has had its hands
    on. Nothing is declared and nothing is invented: this world contains exactly
    what it has met.
    """

    def __init__(self, domain_id: str) -> None:
        super().__init__(domain_id, [])
        self.resources: Dict[str, set] = {}
        #: kind -> the places the substrate was given to work in, where it may
        #: also PRACTISE: act unasked to find out what its acts do. Nowhere
        #: else -- a world assembled from everything it has touched is not a
        #: sandbox, and practice there would move a file it once read for a user.
        self.practice_places: Dict[str, set] = {}
        #: Directories this world is LOOKED AT again whenever it is observed. A
        #: place the substrate works in is watched, not remembered: a file that
        #: arrives after the first look is part of the world at the next one.
        self.watched: set = set()

    def allow_practice(self, kind: str, place: str) -> None:
        """Let the substrate practise inside `place`."""
        self.practice_places.setdefault(kind, set()).add(identity(kind, place))

    def practisable(self, kind: str, value: str) -> bool:
        """Whether `value` is inside a place given for practice -- never the
        place itself, which is where the work is, not something to act on."""
        sensed = _senses().get(kind)
        if sensed is None or sensed.within is None:
            return False
        value = sensed.identify(value)
        return any(value != place and sensed.within(place, value)
                   for place in self.practice_places.get(kind, ()))

    def practice_view(self, kind: str) -> Tuple[List[str], List[str]]:
        """(things, containers) of this kind inside the practice places, as the
        self perceives them now. The places themselves can hold things too."""
        sensed = _senses().get(kind)
        containers = set(self.practice_places.get(kind, ()))
        things: List[str] = []
        if sensed is None:
            return things, sorted(containers)
        for value in sorted(self.resources.get(kind, ())):
            if not self.practisable(kind, value):
                continue
            try:
                entry = sensed.perceive(value)
            except OSError:
                continue
            if entry is None:
                continue
            if sensed.holds is not None and sensed.holds(entry):
                containers.add(value)
            else:
                things.append(value)
        return things, sorted(containers)

    def perceive(self, root: str) -> int:
        """Populate this world by LOOKING AT IT — the substrate's own perception.

        WHAT IS HERE IS A QUESTION PERCEPTION ANSWERS, NOT ONE TO INFER FROM A
        TOOL'S REPORT. Reading contents out of the shape of an observation's
        output cannot tell CONTENTS from MENTIONS, and measured, it does not:
        `list_directory` returns an IGNORE list beside its entries, so the world
        absorbed `.git`, `node_modules` and `build`. Bounded to the sandbox those
        became invented paths that `copy_file` then CREATED, and the substrate
        spent every cycle copying into `.git/.git/.git`, filing each as a
        success. Unbounded, `SmartPathResolver` resolved the bare names against
        the real project root and exploration proposed `MOVE_FILE(.git, .venv)`.

        `_react_investigate_environment` already had the right answer -- "what is
        in my world: scan it directly, recursively, bounded" -- and
        `_scan_environment` reports each entry's KIND, which is exactly the
        distinction the report-shape reading could not make and the reason every
        act moved a directory onto a directory. It is permission-honest (an
        unreadable directory is skipped, never guessed), symlink-safe, and
        bounded, so none of the failures above are reachable through it.

        The directory looked at is itself a thing in this world, as is
        everything the scan finds in it, and it stays WATCHED: every observation
        of this world looks at it again. Returns how many resources this added.
        """
        import os

        if not (root and os.path.isdir(root)):
            logger.info("%s is not a directory to perceive; world unchanged", root)
            return 0
        self.watched.add(identity("path", root))
        added = self._look(root)
        logger.info("perceived %s: %d resource(s) entered the world of %s",
                    root, added, self.domain_id)
        return added

    def _look(self, root: str) -> int:
        """Bring what is in `root` now into this world; how many were new."""
        from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
        added = int(self.encountered("path", root))
        for entry in AutonomousCoordinator._scan_environment(root):
            # A LINK OR A SOCKET IS NOT A THING TO ACT ON. `_scan_environment`
            # records them and refuses to follow them; an operator grounded on
            # one would be learning about the link, not about what it names.
            if entry.get("kind") not in ("file", "dir"):
                continue
            path = entry.get("path")
            if isinstance(path, str) and path and self.encountered("path", path):
                added += 1
        return added

    def encountered(self, kind: str, value: str) -> bool:
        """Note a resource this domain is about. True if it had not been met.

        A kind the self senses is read by that sense alone; any other kind by
        the tools that can be pointed at it.
        """
        value = identity(kind, value)
        known = self.resources.setdefault(kind, set())
        if value in known:
            return False
        known.add(value)
        senses = _senses()
        index = observer_index()
        observations: List[Tuple[str, Dict[str, Any]]] = []
        for a_kind, values in sorted(self.resources.items()):
            for met in sorted(values):
                if a_kind in senses:
                    observations.append((SELF_SENSE, {a_kind: met}))
                else:
                    observations.extend((observer, {parameter: met})
                                        for observer, parameter in index.get(a_kind, ()))
        self.observations = observations
        return True

    def look_at(self, terms: Sequence[str]) -> FrozenSet[Fact]:
        """Look now at the things these terms name, and keep them in view.

        AN ACT OR A GOAL CAN NAME A PLACE THIS WORLD HAS NEVER LOOKED AT. Where
        a move is to put something is a place nothing is at yet, and no look at
        a workspace finds it. A plan that needs it free then has nothing to go
        on, and an act recorded against a world that never looked there says
        nothing about it before and something after -- one move reads as
        deleting what the next does not. So what is named is looked at first,
        with the senses this world perceives with, and from then on it is part
        of the world.
        """
        senses = _senses()
        kinds = [kind for kind in self.resources if kind in senses]
        seen: set = set()
        for named in terms:
            value = _decode(named)
            for kind in kinds:
                self.encountered(kind, value)
                answered = sense(kind, value)
                if answered:
                    seen |= answered
        return frozenset(seen)

    def _current_observations(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Read the encountered world through the observations that have EARNED
        a place in it.

        Unnarrowed this grows as the product of resources met and observations
        pointable at them, and most of it is noise: pointed at a file, 14 of 19
        observations answer, and `find_dead_code`, `find_todos` and
        `security_scan` are among them. So the same rule `ActFrame` uses applies
        to the whole domain -- an observation earns its place by having reported
        something one of this domain's operators actually moved. Until any
        operator has demonstrations, everything pointable is read, which is the
        bootstrap that produces the evidence the narrowing is made of. What the
        self senses is always kept: it is how this world is perceived at all.

        A narrowed COPY is returned, never swapped onto the instance: the
        observation list is rebuilt whenever the world gains a resource.
        """
        import os
        for root in sorted(self.watched):
            if os.path.isdir(root):
                self._look(root)
        earned = self._earned_here()
        if earned:
            kept = [(tool, args) for tool, args in self.observations
                    if tool == SELF_SENSE or tool in earned]
            if kept:
                return kept
        return list(self.observations)

    def _earned_here(self) -> Optional[FrozenSet[str]]:
        """The observations that have earned a place in THIS domain's world.

        Read from a cache and never from the database, because `observe()` is a
        plain synchronous callable in the binding contract and may be called
        from a throwaway event loop in a worker thread. Reaching the demonstration
        store from there took the connection pool out from under the loop that
        owned it ("Database not initialized"), which is what a sync/async seam
        does when you pretend it is not there. `refresh_earned` fills this from a
        proper async context instead.
        """
        return _EARNED_OBSERVERS.get(self.domain_id)


#: domain_id -> the observations that have earned a place in its world. Filled
#: only by `refresh_earned`, from an async context that owns the database.
_EARNED_OBSERVERS: Dict[str, FrozenSet[str]] = {}


async def refresh_earned(domain_id: str) -> FrozenSet[str]:
    """Recompute which observations this domain's world is worth reading through.

    Called after a demonstration is filed -- new evidence can only be turned
    into a narrower world from a context that can reach the store.
    """
    moved = await domain_discriminating(domain_id)
    earned = frozenset(observer for observer, produced
                       in _OBSERVER_PREDICATES.items() if produced & moved)
    if earned:
        _EARNED_OBSERVERS[domain_id] = earned
    else:
        _EARNED_OBSERVERS.pop(domain_id, None)
    return earned


#: domain_id -> the world it has met. One world per domain, because a domain is
#: one world and two readings of it that disagree is the duplicate-authority
#: fault this codebase has paid for elsewhere.
_WORLDS: Dict[str, EncounteredWorld] = {}


def world_of(domain_id: str) -> EncounteredWorld:
    """The one world of this derived domain."""
    world = _WORLDS.get(domain_id)
    if world is None:
        world = EncounteredWorld(domain_id)
        _WORLDS[domain_id] = world
    # Registered on every call, not only at creation: a registry cleared for this
    # domain must still be able to see its world.
    get_binding_registry().register_world(domain_id, world.observe, world.observe_async,
                                          look_at=world.look_at)
    return world


def take_up_workspace(domain_id: str, root: str) -> int:
    """A directory the substrate was given to work in: look at it, and let it
    practise there.

    What is in it enters the domain's world through the self's own perception,
    and the domain becomes explorable with practice bounded to the directory.
    Which acts may be practised there is the domain's own: the operators it has
    met or learned, and of those only what can be undone. Returns how many
    resources entered the world.
    """
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


def encounter(tool_name: str, parameters: Dict[str, Any]) -> Optional[str]:
    """Make the domain this act belongs to ACTABLE and OBSERVABLE, on meeting it.

    THE ENCOUNTER IS THE DECLARATION. A task that declares `workspace_root`
    already installs the filesystem domain on encounter -- this is the same
    idea with nothing left for a person to name: the act itself says which
    resources are in play, what kind of thing they are, and which tool changes
    them, so the binding, the world and the explorable registration can all be
    derived from it.

    What this does NOT do is authorise anything. It registers a real binding for
    a real tool and a world that can really be read; the constitution then
    judges the act exactly as it would any other, and the accounts it demands
    (`_experiment_is_earned` checks this registry and the explorable registry)
    are satisfied by something true rather than something claimed. An act with
    no account is still refused.

    Returns the domain id, or None when nothing here is derivable.
    """
    from core.learning.exploration import get_proposer  # noqa: F401
    from core.agents.autonomous.autonomous_coordinator import classify_action
    from core.tools import get_tool_registry

    registry = get_tool_registry()
    tool = registry.get_tool(tool_name)
    if tool is None:
        return None
    try:
        action_class, _ = classify_action(tool_name, parameters or {})
    except Exception:
        return None
    if getattr(action_class, "value", str(action_class)) not in ACTING_CLASSES:
        return None

    resources = [(resource_kind(p.name), str(parameters.get(p.name)))
                 for p in resource_parameters(tool)
                 if isinstance(parameters.get(p.name), str)
                 and str(parameters.get(p.name)).strip()]
    if not resources:
        return None

    domain_id = derived_domain_id(kind for kind, _ in resources)
    world = world_of(domain_id)
    for kind, value in resources:
        world.encountered(kind, value)

    predicate = predicate_for(tool_name)
    if get_binding_registry().get(domain_id, predicate) is None:
        binding = action_binding(tool_name, tool, world.observe)
        if binding is None:
            return None
        get_binding_registry().register(domain_id, binding)
        logger.info("encountered %s: %s is now a bound operator of %s",
                    tool_name, predicate, domain_id)
    # DELIBERATELY NOT REGISTERED EXPLORABLE HERE, and this is the honest edge
    # of what encounter can settle by itself.
    #
    # Binding an operator says "this tool changes this kind of thing, and the
    # substrate can read the result". Registering the domain explorable says
    # something else entirely: that the substrate may PRACTISE here, choosing
    # its own acts to find out what they do. A domain assembled from every
    # resource the substrate has touched is not a sandbox -- it would let
    # exploration move a file it once read for a user, which is why practice is
    # bounded to a place someone gave it (`take_up_workspace`, `derive_domain`).
    #
    # Acting when ASKED and practising UNASKED are different permissions, and
    # nothing derivable from a tool's declaration tells them apart. So the
    # binding is registered (which is true, and what the constitution's account
    # checks need) and the licence to practise is not.
    return domain_id


async def bind_learned() -> List[str]:
    """Bind the tool behind every operator already learned in a derived domain,
    so what was learned before a restart can be planned with and done again.

    A derived domain's operators are bound when an act is met, and nothing is
    met again just because the process restarted: the operator would sit in the
    store, validated, with nothing to perform it. The tool is found by the
    operator's own name, which is the tool's name (`predicate_for`).

    Returns "<domain>/<operator>" for each binding made.
    """
    from core.learning.rule_store import get_rule_store
    from core.tools import get_tool_registry

    registry = get_tool_registry()
    by_predicate = {predicate_for(name): name
                    for name in set(list(registry.tools) + list(registry.tool_factories))}
    bound: List[str] = []
    for stored in await get_rule_store().executable_rules():
        domain_id = str(stored.domain_id or "")
        action = getattr(stored.rule, "action", None)
        if not domain_id.startswith(DERIVED_PREFIX) or action is None:
            continue
        if get_binding_registry().get(domain_id, action.predicate) is not None:
            continue
        tool_name = by_predicate.get(action.predicate)
        tool = registry.get_tool(tool_name) if tool_name else None
        if tool is None:
            logger.warning("learned operator %s in %s names no tool; it cannot be "
                           "performed", action.predicate, domain_id)
            continue
        binding = action_binding(tool_name, tool, world_of(domain_id).observe)
        if binding is None:
            continue
        get_binding_registry().register(domain_id, binding)
        bound.append(f"{domain_id}/{action.predicate}")
    if bound:
        logger.info("bound %d learned operator(s) of derived domains: %s",
                    len(bound), ", ".join(bound))
    return bound
