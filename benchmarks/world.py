"""The shared world both agents act in — and the independent referee.

The "world" is the real ToolRegistry filesystem tools (core/tools/filesystem_tools.py),
exactly what the substrate acts through in production. Both the substrate and the
LLM baseline run their steps here, against an isolated temp directory per episode,
so neither has any advantage of environment. This is the ONE thing the LLM is
allowed to share with the substrate: the tools. Nothing else.

The referee is not a tool. It is a fresh, independent measurement of the world
(pure os/pathlib) that NEITHER agent can see, and it is the sole arbiter of
whether a task's goal actually holds. An agent's own claim of "done" is scored
against this ground truth.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from core.tools.tool_registry import get_tool_registry

#: The filesystem world the agents may touch. This is the whole tool surface the
#: LLM baseline is given — and the substrate's tasks declare from the same set.
WORLD_TOOLS: Dict[str, Dict[str, Any]] = {
    "write_file": {
        "args": {"file_path": "str", "content": "str", "create_dirs": "bool (default false)"},
        "desc": "Write content to a file. Fails if the parent directory is missing and create_dirs is false.",
    },
    "read_file": {
        "args": {"file_path": "str"},
        "desc": "Read a file's contents. Fails if the file does not exist.",
    },
    "create_directory": {
        "args": {"directory_path": "str", "parents": "bool (default false)"},
        "desc": "Create a directory.",
    },
    "copy_file": {
        "args": {"source_path": "str", "destination_path": "str", "create_dirs": "bool (default false)"},
        "desc": "Copy a file. Fails if the source does not exist.",
    },
    "move_file": {
        "args": {"source_path": "str", "destination_path": "str", "create_dirs": "bool (default false)"},
        "desc": "Move/rename a file. Fails if the source does not exist.",
    },
    "delete_file": {
        "args": {"path": "str", "confirm": "bool (must be true to delete)"},
        "desc": "Delete a file or directory. Fails if the path does not exist.",
    },
    "list_directory": {
        "args": {"directory_path": "str"},
        "desc": "List entries in a directory.",
    },
    "get_file_info": {
        "args": {"file_path": "str"},
        "desc": "Return metadata about a path (existence, size, type). Use this to VERIFY the world.",
    },
}


class World:
    """One isolated filesystem world for a single benchmark episode, and the
    shared tool executor over it. Both agents get their own World instance for
    the same task, so their effects never collide and the referee measures each
    independently."""

    def __init__(self, root: str):
        self.root = root
        self._reg = get_tool_registry()
        self.calls: List[Dict[str, Any]] = []  # audit trail of every tool call

    def path(self, *parts: str) -> str:
        """A concrete absolute path inside this world for a relative spec."""
        return os.path.join(self.root, *parts)

    async def run(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one tool against the world through the real registry.
        Returns a normalized {success, output, error} — the same information a
        person would get back from the tool, no more. Both agents call this."""
        if tool not in WORLD_TOOLS:
            out = {"success": False, "output": None, "error": f"unknown tool: {tool}"}
            self.calls.append({"tool": tool, "args": args, **out})
            return out
        try:
            r = await self._reg.execute_tool(tool, dict(args or {}))
            out = {
                "success": bool(getattr(r, "success", False)),
                "output": getattr(r, "output", None),
                "error": (getattr(r, "error", None) or None),
            }
        except Exception as e:  # a tool that raises is a failed effect, honestly
            out = {"success": False, "output": None, "error": f"{type(e).__name__}: {e}"}
        # trim the recovery-hint noise the registry appends, keep the real reason
        if out["error"]:
            out["error"] = str(out["error"]).split("\n\n[RECOVERY_HINT")[0].strip()
        self.calls.append({"tool": tool, "args": args, **out})
        return out


# ----------------------------------------------------------------------------
# The referee's toolbox — pure, independent measurements of the world. NEITHER
# agent can call these; they define ground truth for scoring only.
# ----------------------------------------------------------------------------

def exists(root: str, *parts: str) -> bool:
    return os.path.exists(os.path.join(root, *parts))


def is_file(root: str, *parts: str) -> bool:
    return os.path.isfile(os.path.join(root, *parts))


def is_dir(root: str, *parts: str) -> bool:
    return os.path.isdir(os.path.join(root, *parts))


def file_contains(root: str, rel: str, needle: str) -> bool:
    p = os.path.join(root, rel)
    try:
        with open(p, "r") as f:
            return needle in f.read()
    except Exception:
        return False


def absent(root: str, *parts: str) -> bool:
    return not os.path.exists(os.path.join(root, *parts))
