"""Whether what is happening now is remembered.

Everything the substrate does keeps a trace by default: a conversation turn is an experience, a reasoning episode
is remembered, an argument it weighed is held, an intent is recorded, and the time each part took is logged. Code that holds work inside
`not_remembered()` keeps no such trace, and every place that would keep one asks `remembered()` first.

`Conversation(remembers=False)` WAS the main user of this and HAS BEEN REMOVED (2026-11-21). It wrapped a whole
turn, so a thread could not use what it had just been told: told "Socrates is a human." and then asked "Is
Socrates mortal?", the premises were never delivered and nine of the eleven kinds of thinking reported
`unsupported_input`. A conversation remembers what it is told. This remains for callers that genuinely want one
piece of work to leave no trace, which is a narrower thing than a conversation.

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
