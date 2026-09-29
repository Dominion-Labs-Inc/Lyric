#!/usr/bin/env python3
"""How a learned operator becomes an actual tool invocation, and how the world
is read back afterwards.

A learned rule says `MOVE(?X,?A,?B)` changes the world. It does not say what
`MOVE` *is* — the KITE experiments proved acquisition precisely because the
predicates carried no meaning. Something has to connect the symbol to an act,
and that connection is declared here rather than inferred: guessing which tool
a predicate denotes would let the substrate take a real action on a resemblance
between strings.

A binding supplies both halves, and both are required:

    execute   the tool and parameters that perform the action
    observe   how the world is read back, independently of what the tool said

The second is what makes verification possible. Without an independent
observation the only available evidence is the tool's own success flag, and a
rule would be confirmed by the fact that its invocation returned cleanly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Optional, Sequence, Tuple

from core.learning.rule_induction import Fact

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OperatorBinding:
    """Binds one action predicate to a tool, and a world to its observer."""

    predicate: str
    tool_name: str
    #: ground action args -> tool parameters
    parameters: Callable[[Tuple[str, ...]], Dict[str, Any]]
    #: reads the world; returns None when it cannot be read, which is different
    #: from returning an empty world
    observe: Callable[[], Optional[FrozenSet[Fact]]]
    description: str = ""
    #: An observer that must be AWAITED, when reading this world means running
    #: tools rather than reading a directory. Optional, and `observe` remains
    #: the contract every existing caller uses.
    #:
    #: A world observed by running investigate-class tools cannot honestly be
    #: read from a synchronous callable inside a running loop: the only way to
    #: do it is a private loop on a worker thread, and those tools touch the
    #: database, which rebinds the connection pool away from the loop that owns
    #: it ("Database not initialized" mid-exploration, reproducibly). Async
    #: callers use `observe_world_async` and get the real thing.
    observe_async: Optional[Callable[[], Any]] = None


class BindingRegistry:
    """The declared bindings for a domain. Unbound predicates are refused."""

    def __init__(self):
        self._bindings: Dict[Tuple[str, str], OperatorBinding] = {}
        #: domain -> (observe, observe_async) of a world registered on its own.
        #: A domain can be SEEN before anything can be done in it: until an
        #: operator is bound, this is how its world is read.
        self._worlds: Dict[str, Tuple[Callable[[], Optional[FrozenSet[Fact]]],
                                      Optional[Callable[[], Any]]]] = {}
        #: domain -> how its world looks at the things given terms name.
        self._lookers: Dict[str, Callable[[Sequence[str]], FrozenSet[Fact]]] = {}

    def register(self, domain_id: str, binding: OperatorBinding) -> None:
        self._bindings[(domain_id, binding.predicate)] = binding
        logger.info("bound %s.%s -> %s", domain_id, binding.predicate, binding.tool_name)

    def get(self, domain_id: str, predicate: str) -> Optional[OperatorBinding]:
        return self._bindings.get((domain_id, predicate))

    def register_world(self, domain_id: str,
                       observe: Callable[[], Optional[FrozenSet[Fact]]],
                       observe_async: Optional[Callable[[], Any]] = None,
                       look_at: Optional[Callable[[Sequence[str]], FrozenSet[Fact]]] = None
                       ) -> None:
        """Register how a domain's world is read, apart from any operator, and
        how it looks at particular things when asked."""
        self._worlds[domain_id] = (observe, observe_async)
        if look_at is not None:
            self._lookers[domain_id] = look_at

    def look_at(self, domain_id: Optional[str],
                terms: Sequence[str]) -> Optional[FrozenSet[Fact]]:
        """What the domain's world sees, now, of the things these terms name.
        None for a domain whose world cannot look at particular things."""
        looker = self._lookers.get(domain_id) if domain_id else None
        return looker(terms) if looker is not None else None

    def bindings_for(self, domain_id: str) -> Sequence[OperatorBinding]:
        """Every binding declared in a domain.

        The world a state goal is planned against is not one predicate's slice
        of it but the union of what every binding in the domain observes. A
        caller reading the whole world reads it through here rather than
        guessing which predicates exist.
        """
        return [b for (d, _), b in self._bindings.items() if d == domain_id]

    def observe_world(self, domain_id: str) -> Optional[FrozenSet[Fact]]:
        """Read the whole observable world of a domain, or None if any part of
        it cannot be read.

        Returning None on an unreadable slice is deliberate: a world assembled
        from the bindings that happened to answer is a different world from the
        real one, and planning against it would authorise a plan on a state
        that was never observed. An empty world (a domain with no facts) is not
        the same as an unreadable one and returns an empty set.
        """
        bindings = self.bindings_for(domain_id)
        if not bindings:
            world = self._worlds.get(domain_id)
            return world[0]() if world is not None else None
        facts: set = set()
        for binding in bindings:
            observed = binding.observe()
            if observed is None:
                return None
            facts |= set(observed)
        return frozenset(facts)

    async def observe_world_async(self, domain_id: str) -> Optional[FrozenSet[Fact]]:
        """`observe_world` for callers that can await — the same contract.

        A binding whose world is read by RUNNING TOOLS supplies `observe_async`
        and is awaited here, on the caller's own loop. One that reads a
        directory has no need of it and is called as before, so both kinds of
        domain live in one registry and neither is a special case.
        """
        bindings = self.bindings_for(domain_id)
        if not bindings:
            world = self._worlds.get(domain_id)
            if world is None:
                return None
            observe, observe_async = world
            return (await observe_async()) if observe_async is not None else observe()
        facts: set = set()
        for binding in bindings:
            observer = getattr(binding, "observe_async", None)
            observed = (await observer()) if observer is not None else binding.observe()
            if observed is None:
                return None
            facts |= set(observed)
        return frozenset(facts)

    def clear(self, domain_id: Optional[str] = None) -> None:
        if domain_id is None:
            self._bindings.clear()
            self._worlds.clear()
            self._lookers.clear()
            return
        for key in [k for k in self._bindings if k[0] == domain_id]:
            del self._bindings[key]
        self._worlds.pop(domain_id, None)
        self._lookers.pop(domain_id, None)


_registry: Optional[BindingRegistry] = None


def get_binding_registry() -> BindingRegistry:
    global _registry
    if _registry is None:
        _registry = BindingRegistry()
    return _registry
