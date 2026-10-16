"""Where a long run is, asked from outside: `kill -USR1 <pid>` writes every thread's Python stack to a file.

A teaching pass or a review that spins at full CPU and logs nothing can only be read from its stack, and reading another
process's stack takes root on macOS. A process that registers here writes its own, to `logs/stack_<name>_<pid>.txt`,
each time it is signalled, and goes on running.
"""
import faulthandler
import os
import signal
from pathlib import Path

_open = []


def dump_stacks_on_signal(name: str, logs: Path) -> Path:
    """Register SIGUSR1 to append this process's stacks to `logs/stack_<name>_<pid>.txt`; returns the path."""
    path = Path(logs) / f"stack_{name}_{os.getpid()}.txt"
    handle = open(path, "a")
    _open.append(handle)  # held for the life of the process: faulthandler writes to its descriptor
    faulthandler.register(signal.SIGUSR1, file=handle, all_threads=True, chain=False)
    return path
