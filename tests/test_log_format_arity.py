"""No logger call may promise more values than it is given, anywhere in the tree.

WHAT THIS COSTS WHEN IT IS WRONG: `memory_agent`'s word-class warm passed the LIST of derived claims where its
format said `%d`. Python's logging cannot format that, so it fell back to printing the record's whole argument
tuple -- which held all 7,462 `Derived` sentences -- and wrote the same 3.8 MB line three times. 11 MB of log from
one mistaken character, and the traceback it leaves looks like a crash in logging rather than a wrong argument
(2026-11-02).

It reads the source and runs nothing, so it holds for every call in the tree and not only the ones a run happens
to reach. A call whose format string is not a literal, or that is given `*args`, is not checked: nothing can be
known about it without running it.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: A %-placeholder, by the conversions Python's logging actually formats with. `*` is a width taken from the
#: arguments, which is why it is inside the flags and not a conversion of its own.
HOLE = re.compile(r"%[-+ #0-9.*]*[diouxXeEfFgGcrsa]")

#: Not the tree's own code: a staged copy of a protected module, a vendored interpreter, what was archived.
APART = ("venv_lyric", "Python-3.11.4", "/archive", "/backups/", "/node_modules/", "/_disabled/")

LOGGING_CALLS = ("info", "warning", "error", "debug", "critical", "exception")
LOGGERS = ("logger", "log", "LOGGER")


def _calls():
    """Every logger call in the tree whose format string is a literal and whose arguments can be counted:
    (file, line, placeholders, arguments given, the format string)."""
    for path in sorted(ROOT.rglob("*.py")):
        if any(skip in str(path) for skip in APART):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue        # a file that does not parse is another test's business
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if getattr(func, "attr", None) not in LOGGING_CALLS:
                continue
            base = getattr(func, "value", None)
            if not (isinstance(base, ast.Name) and base.id in LOGGERS):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if not isinstance(node.args[0].value, str):
                continue
            if any(isinstance(a, ast.Starred) for a in node.args) or node.keywords:
                continue
            written = node.args[0].value
            # A LITERAL PERCENT SIGN IS NOT A PLACEHOLDER and has to go before anything is counted: left in,
            # "moved %.0f%% of the way" counts one too many, because `% o` is a space-flagged octal by the same
            # rule. That false positive named two innocent files, one of them a protected module whose edit halts
            # a running substrate.
            yield (str(path.relative_to(ROOT)), node.lineno,
                   len(HOLE.findall(written.replace("%%", ""))), len(node.args) - 1, written)


ALL = list(_calls())


def test_there_are_calls_to_check():
    """A test that checks nothing passes, so the floor is stated: 1,456 logger calls carried a literal format
    string when this was written (2026-11-02), over 1,037 files.

    THE PATHS ARE ABSOLUTE AND THE SKIPS EXPECT IT. Walked as `Path(".")` instead, `/archive` and `/backups/` match
    nothing, archived and staged code is counted too, and the same walk reported 3,624 calls and six defects that
    were all in copies of a protected module nobody runs."""
    assert len(ALL) > 1200, f"only {len(ALL)} logger calls found; the walk is no longer reaching the tree"


@pytest.mark.parametrize("path,line,holes,given,written",
                         [c for c in ALL if c[2] != c[3]] or [("", 0, 0, 0, "")])
def test_no_logger_call_promises_more_than_it_is_given(path, line, holes, given, written):
    assert holes == given, (
        f"{path}:{line} has {holes} placeholder(s) and is given {given} argument(s): {written!r}")
