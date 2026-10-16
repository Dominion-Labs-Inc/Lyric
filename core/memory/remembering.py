"""Whether what is happening now is remembered.

Everything the substrate does keeps a trace by default: a conversation turn is an experience, a reasoning episode
is remembered, an argument it weighed is held, an intent is recorded, and the time each part took is logged. A
conversation held NOT to remember (`Conversation(remembers=False)`) answers inside `not_remembered()`, and every place
that keeps such a trace asks `remembered()` first and keeps none. So the substrate can be asked about what it holds,
on the store it holds it in, without the asking becoming part of it (UNDERSTANDS-WORDNET-01, run on main).

It is the context's, not the process's: the turn's own awaits and the tasks it starts see it, and a worker that was
already running (the memory agent's pool, its write queue) does not -- so it is asked where a trace is handed over,
not where a queue is drained.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator

_remembering: contextvars.ContextVar[bool] = contextvars.ContextVar("remembering", default=True)


def remembered() -> bool:
    """Whether what is happening now leaves a trace."""
    return _remembering.get()


@contextmanager
def not_remembered() -> Iterator[None]:
    """What happens inside leaves no trace: no experience, no reasoning memory, no argument, no intent, no timing."""
    token = _remembering.set(False)
    try:
        yield
    finally:
        _remembering.reset(token)
