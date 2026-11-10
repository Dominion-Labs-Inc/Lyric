"""One stream in, four streams out.

Everything the system emitted went to one logger, so watching Lyric reason meant
reading it interleaved with connection-pool churn and 371 tool registrations.
The signal was there; it was 2% of the volume.

No subsystem was changed to make this work. All 222 modules already log through
`getLogger(__name__)`, so every record arrives carrying `core.<subsystem>.<...>`
-- the channel is derivable from what is already there. Routing is decided in
this one file, which is what keeps a new subsystem from silently landing in the
wrong place: an unmatched prefix goes to SYSTEM by name, not by accident.

Channels are about WHOSE ACTIVITY a line describes, not how severe it is.
Severity is orthogonal and already carried by levelname; a pool timeout is
SYSTEM whether it is INFO or CRITICAL.
"""
import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SUBSTRATE = "substrate"
SYSTEM = "system"
SECURITY = "security"
HEALTH = "health"

# FOUR PANELS, ONE PER CONCERN. TASKS was folded into SUBSTRATE and HEALTH was
# split out of SYSTEM on 2026-08-25.
#
# The substrate IS Lyric thinking AND acting -- learning, reasoning, memory,
# then the agents, execution and tools that carry a decision out. Those are not
# two things to a substrate-first system; a task is the substrate doing
# something, so it belongs in the same panel, not a separate "tasks" lane that
# implied a request-processing pipeline.
#
# HEALTH and SECURITY are the two watching faculties, now peers -- health and
# monitoring had been buried in the SYSTEM catch-all while security had its own
# panel, which is the asymmetry that made this wrong. SYSTEM keeps only the
# machinery neither faculty owns: the database, services, the API, integration.
ALL_CHANNELS = (SUBSTRATE, SYSTEM, SECURITY, HEALTH)

#: Logger-name prefix -> channel. Longest prefix wins, so a more specific rule
#: can carve a module out of its parent without reordering anything.
ROUTES: Tuple[Tuple[str, str], ...] = (
    # THE SUBSTRATE: thinking and acting are one concern.
    ("core.learning",       SUBSTRATE),
    ("core.reasoning",      SUBSTRATE),
    ("core.domain",         SUBSTRATE),
    ("core.memory",         SUBSTRATE),
    ("core.semantics",      SUBSTRATE),
    ("core.agents",         SUBSTRATE),
    ("core.intelligence",   SUBSTRATE),
    ("core.tools.execution_tools", SUBSTRATE),
    # The domain MASTER decides what a subject is, whether two subjects
    # correspond and what may transfer between them. That is substrate work, and
    # it was reaching SYSTEM only because it happens to live under
    # core.integration beside the Slack handlers -- so the concern was split
    # across two channels, with the half that decides landing in the file where
    # asyncpg's connection churn was 806 of the first 808 lines. Longest prefix
    # wins, so the rest of core.integration stays on SYSTEM.
    ("core.integration.universal_domain_master", SUBSTRATE),

    # SECURITY: what was permitted, refused, or recorded.
    ("core.security",       SECURITY),
    ("core.agents.autonomous.threat_sense", SECURITY),

    # HEALTH: the monitoring faculty, its own panel now, not folded into SYSTEM.
    ("core.health",         HEALTH),
    ("core.monitoring",     HEALTH),

    # SYSTEM: the machinery neither faculty owns. Listed explicitly rather than
    # left to the default so the intent is visible when reading this table.
    ("core.database",       SYSTEM),
    ("core.services",       SYSTEM),
    ("core.tools",          SYSTEM),
    ("core.api",            SYSTEM),
    ("core.integration",    SYSTEM),
    ("core.system",         SYSTEM),
    ("core.utils",          SYSTEM),
    ("core.chaos",          SYSTEM),
)


def channel_for(logger_name: str) -> str:
    """Which channel a record belongs to. Unknown prefixes are SYSTEM."""
    best, best_len = SYSTEM, -1
    for prefix, channel in ROUTES:
        if (logger_name == prefix or logger_name.startswith(prefix + ".")) \
                and len(prefix) > best_len:
            best, best_len = channel, len(prefix)
    return best


class ChannelFilter(logging.Filter):
    """Admit only this channel's records, and stamp every record with its own.

    The stamp is set on ALL records the filter sees, including rejected ones, so
    any other handler -- the combined log, a future sink -- can read
    `record.channel` without repeating the routing decision.
    """

    def __init__(self, channel: str):
        super().__init__()
        self.channel = channel

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "channel"):
            record.channel = channel_for(record.name)
        return record.channel == self.channel


def log_dir() -> Path:
    return Path(os.getenv("LYRIC_HOME", ".")) / "logs" / "channels"


def install(level: int = logging.INFO) -> Dict[str, Path]:
    """Attach one file handler per channel to the root logger.

    ADDITIVE. The combined `logs/lyric_main.log` and the stdout stream stay
    exactly as they were: this is a second way to read the same records, not a
    replacement, so nothing that currently greps the main log breaks.
    """
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S")

    root = logging.getLogger()
    paths: Dict[str, Path] = {}

    for channel in ALL_CHANNELS:
        path = directory / f"{channel}.log"
        # Re-running install() must not stack duplicate handlers onto root.
        tag = f"lyric-channel:{channel}"
        if any(getattr(h, "_lyric_tag", None) == tag for h in root.handlers):
            paths[channel] = path
            continue
        handler = logging.FileHandler(path)
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handler.addFilter(ChannelFilter(channel))
        handler._lyric_tag = tag
        root.addHandler(handler)
        paths[channel] = path

    # The stream is only complete if nothing runs beside it. Armed here so
    # every caller of install() gets it with no change of its own.
    watch_background_work(level=level)

    return paths


# ===========================================================================
# NOTHING RUNS OFF THE STREAM
# ===========================================================================
# Routing above decides WHERE a record goes. It cannot help with work that
# emits no record at all, and that was the larger hole: 81 sites across core/
# start a task or a thread, and a task that logs nothing is indistinguishable
# from a task that never ran. A substrate spending 462 seconds on one sentence
# said nothing about what it was doing for 461 of them.
#
# The seam is the LOOP, not the call sites. `loop.set_task_factory` sees every
# task created on that loop whichever module created it, so a site nobody
# remembered to edit is covered anyway -- the same argument `core.main` already
# makes for installing failure capture centrally rather than per except-block.
#
# A task is logged under ITS CREATOR'S module name, so the routing table above
# places it with no new rules: a task started in core.semantics reads on the
# substrate panel, one started in core.database on system.
#: Live background work: id(task) -> (what, where, logger_name, started_at).
#: Written from the loop thread, read from the heartbeat thread under _LIVE_LOCK.
_LIVE: "dict[int, tuple]" = {}
_LIVE_LOCK = threading.Lock()

#: Frames belonging to the plumbing itself, never the answer to "who started
#: this". Walking past them is what makes the attribution useful.
_PLUMBING = ("asyncio", "concurrent.futures", __name__)


def _creator(limit: int = 24) -> "tuple[str, str]":
    """The module and source line that started this work.

    Returns (logger_name, where). The walk is bounded because this runs on
    every task creation and an unbounded stack walk in a hot path is a cost
    nobody asked for.
    """
    frame: Optional[Any] = sys._getframe(1)
    seen = 0
    while frame is not None and seen < limit:
        module = frame.f_globals.get("__name__", "")
        if not any(module == p or module.startswith(p + ".") for p in _PLUMBING):
            code = frame.f_code
            name = code.co_filename.rsplit("/", 1)[-1]
            return module, f"{name}:{frame.f_lineno} {code.co_qualname}"
        frame = frame.f_back
        seen += 1
    return "core", "unattributed"


def _level_for(name: str, level: int) -> int:
    """Lyric's own work on the signal; a library's plumbing beneath it.

    asyncpg's pool creates a task per connection release -- 806 of the first
    808 lines this apparatus wrote were `PoolConnectionHolder.release`, which
    is precisely the 2%-signal problem this file was written to end. Those
    tasks are REAL and still said, at DEBUG, so turning the level down shows
    them; they just do not get to drown the substrate.
    """
    if name == "__main__" or name == "core" or name.startswith("core."):
        return level
    return logging.DEBUG


def _what(coro: Any) -> str:
    """What a coroutine is, in the words its own code carries."""
    for attribute in ("__qualname__", "__name__"):
        named = getattr(coro, attribute, None)
        if named:
            return str(named)
    code = getattr(coro, "cr_code", None) or getattr(coro, "gi_code", None)
    if code is not None:
        return str(getattr(code, "co_qualname", code.co_name))
    return type(coro).__name__


def running_now() -> List[dict]:
    """Every piece of background work alive right now, oldest first.

    This is the answer to "what is it doing" asked from outside the loop --
    callable from a signal handler, a health check or a prompt, without
    waiting for anything to finish.
    """
    now = time.monotonic()
    with _LIVE_LOCK:
        live = list(_LIVE.values())
    out = [{"what": what, "where": where, "channel": channel_for(name),
            "logger": name, "running_for_s": round(now - started, 3)}
           for what, where, name, started in live]
    out.sort(key=lambda row: row["running_for_s"], reverse=True)
    return out


def threads_now() -> List[dict]:
    """Every live thread and the line it is actually on.

    There is no supported hook for a thread STARTING -- `threading.excepthook`
    only fires when one dies -- so a thread that is merely busy would say
    nothing at all. `sys._current_frames()` answers it without patching the
    standard library: it gives the real top frame of every live thread, which
    is the question "what is it doing right now" answered exactly.
    """
    frames = sys._current_frames()
    here = threading.get_ident()
    out = []
    for thread in threading.enumerate():
        if thread.ident is None or thread.ident == here:
            continue
        frame = frames.get(thread.ident)
        if frame is None:
            where = "no frame"
        else:
            code = frame.f_code
            where = (f"{code.co_filename.rsplit('/', 1)[-1]}:{frame.f_lineno} "
                     f"{code.co_qualname}")
        out.append({"thread": thread.name, "daemon": thread.daemon, "on": where})
    return out


def _finished(task: "asyncio.Task", key: int, level: int) -> None:
    """Say how a task ended. Registered on every task the factory builds."""
    with _LIVE_LOCK:
        entry = _LIVE.pop(key, None)
    if entry is None:
        return
    what, where, name, started = entry
    took = time.monotonic() - started
    logger = logging.getLogger(name)
    level = _level_for(name, level)
    if task.cancelled():
        # A cancellation is a decision somebody made, not a failure, and it is
        # still the end of a piece of work -- so it is said, at its own level.
        logger.log(level, "background task cancelled after %.3fs: %s (%s)",
                   took, what, where)
        return
    # THE EXCEPTION IS DELIBERATELY NOT TOUCHED HERE. `task.exception()` marks
    # it RETRIEVED, which silences asyncio's own "Task exception was never
    # retrieved" -- the one signal that a failure actually went nowhere. Asking
    # for it turned the only real detector off and replaced it with a worse one:
    # every task that raises looked like a failure, including the ones whose
    # awaiter handles the raise as its ANSWER. `ActiveDiscovery._check_port`
    # opens a connection to see whether a port is listening, so a closed port
    # raises OSError BY DESIGN; reporting those wrote 20 false rows onto the
    # canonical failure record in one teaching run (2026-11-06).
    #
    # A refusal, a probe that found nothing, a cancelled wait -- none of these
    # are failures. What IS one is an exception nobody ever collects, and
    # `_loop_failure` below hears exactly those, from asyncio itself, and logs
    # them at ERROR where the failure record picks them up.
    logger.log(level, "background task done in %.3fs: %s (%s)", took, what, where)


def _watched_task_factory(level: int) -> Callable:
    """A task factory that enters every task on the stream, both ends."""

    def factory(loop, coro, **kwargs):
        task = asyncio.Task(coro, loop=loop, **kwargs)
        what = _what(coro)
        name, where = _creator()
        key = id(task)
        with _LIVE_LOCK:
            _LIVE[key] = (what, where, name, time.monotonic())
        logging.getLogger(name).log(_level_for(name, level),
                                    "background task started: %s (%s)",
                                    what, where)
        task.add_done_callback(lambda done: _finished(done, key, level))
        return task

    return factory


def _loop_failure(loop, context: dict) -> None:
    """The loop's own complaints, in the log rather than on stderr.

    asyncio's default handler writes to stderr, which is nowhere when the
    substrate runs detached. "Task exception was never retrieved" arrives here.
    """
    message = context.get("message") or "event loop reported a problem"
    failure = context.get("exception")
    source = context.get("future") or context.get("task") or context.get("handle")
    logging.getLogger("core.system.loop").error(
        "event loop: %s%s%s", message,
        f" [{source!r}]" if source is not None else "",
        f": {type(failure).__name__}: {failure}" if failure is not None else "",
        exc_info=failure if failure is not None else False)


def _thread_failure(args) -> None:
    """A thread that dies takes its exception with it unless someone says so."""
    if args.exc_type is SystemExit:
        return
    name = getattr(args.thread, "name", "?")
    logging.getLogger("core.system.thread").error(
        "thread %s DIED: %s: %s", name, args.exc_type.__name__, args.exc_value,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _heartbeat(every: float, after: float, level: int) -> None:
    """Say what is still running, while it is still running.

    Both ends of a task are logged above, which is no help at all while the
    substrate is 400 seconds into something and has not reached either end.
    This is the only part of the apparatus that reports work in progress, so
    it is the part that answers "what is it doing right now".
    """
    while True:
        time.sleep(every)
        # THE ROSTER GOES OUT EVERY TICK, not only when a task is standing.
        # The work that takes 400 seconds is not a task at all -- it is
        # synchronous reading inside a task that already existed, so `_LIVE`
        # is empty and gating the roster on standing tasks reported NOTHING
        # through the exact event this apparatus is for.
        for thread in threads_now():
            logging.getLogger("core.system.thread").log(
                level, "thread %s%s is on %s", thread["thread"],
                " (daemon)" if thread["daemon"] else "", thread["on"])
        standing = [row for row in running_now() if row["running_for_s"] >= after]
        for row in standing:
            logging.getLogger(row["logger"]).log(
                level, "STILL RUNNING after %.1fs: %s (%s)",
                row["running_for_s"], row["what"], row["where"])


def watch_background_work(level: int = logging.INFO, *,
                           heartbeat_every: float = 30.0,
                           report_after: float = 30.0) -> bool:
    """Arm the three seams through which work would otherwise run unseen.

    Idempotent, and armed for loops that DO NOT EXIST YET: `install()` runs at
    import time, while the loop a substrate works on is built later by
    `asyncio.run`. Wrapping the policy is what reaches that loop; waiting for a
    running one would arm nothing.
    """
    if getattr(watch_background_work, "_armed", False):
        return True

    factory = _watched_task_factory(level)

    def arm(loop) -> None:
        loop.set_task_factory(factory)
        loop.set_exception_handler(_loop_failure)

    try:
        arm(asyncio.get_running_loop())
    except RuntimeError:
        pass                      # no loop yet; the policy below catches it

    # Bound onto the LIVE policy rather than swapping in a new instance: the
    # policy holds the current loop association, and a fresh one would drop it.
    # `asyncio.run` resolves new_event_loop through this instance, so this is
    # what reaches the loop a substrate has not built yet.
    policy = asyncio.get_event_loop_policy()
    stock_new_event_loop = policy.new_event_loop

    def new_event_loop():
        loop = stock_new_event_loop()
        arm(loop)
        return loop

    policy.new_event_loop = new_event_loop

    threading.excepthook = _thread_failure

    watcher = threading.Thread(target=_heartbeat, name="lyric-heartbeat",
                               args=(heartbeat_every, report_after, level),
                               daemon=True)
    watcher.start()

    watch_background_work._armed = True
    logging.getLogger("core.system.loop").log(
        level, "background work is on the stream: every task says both ends, "
        "dead threads are logged, and anything past %.0fs is named every %.0fs",
        report_after, heartbeat_every)
    return True
