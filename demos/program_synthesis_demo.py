#!/usr/bin/env python3
"""
TorinAI — learning an algorithm from examples, model-free.

Run:   PYTHONPATH="$PWD" ./venv_torin/bin/python3 demos/program_synthesis_demo.py

This is the REAL substrate. No database, no language model — the derivation is
pure. Given only input->output examples, TorinAI derives a procedure that
reproduces them, runs it on inputs it has never seen, and — when asked for
something it cannot build — reports an honest gap instead of guessing.

Nothing is staged: the programs below are derived live by the same engine, and
the answers are produced by running the derived procedure.
"""
import io
import logging
import os
import sys
import contextlib

# Keep the terminal clean for the recording: silence framework logging and the
# one-time environment-load banner that fires on import. (This hides log noise
# only — every result printed below is real, computed live.)
logging.disable(logging.CRITICAL)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import core.execution.list_synthesis as ls
    from core.execution.list_synthesis import synthesize_fold

# Fresh derivation on every run — no cached operators, no persisted state.
ls._state = {"operators": None, "why": ""}

BOLD = "\033[1m"; DIM = "\033[2m"; GRN = "\033[32m"; CYN = "\033[36m"; RST = "\033[0m"
if not sys.stdout.isatty():
    BOLD = DIM = GRN = CYN = RST = ""


def rule(ch="─", n=64):
    print(ch * n)


def header():
    rule("═")
    print(f"{BOLD} TorinAI — deriving procedures from examples (model-free){RST}")
    rule("═")
    print("We give it input→output examples. We never provide the algorithm.")
    print(f"{DIM} Language model: not loaded   ·   Database: not used   ·   "
          f"pure derivation{RST}")
    print(f"{DIM} The three tasks below are shown the SAME input lists — only the"
          f" outputs differ,{RST}")
    print(f"{DIM} so each must derive a DIFFERENT procedure to explain them.{RST}")
    print()


def show(title, examples, unseen):
    print(f"{BOLD}{CYN}[{title}]{RST}")
    print("  Examples it is shown:")
    for ex in examples:
        print(f"     {str(ex['input']):<14} → {ex['output']}")
    print(f"  {DIM}It has no procedure for this — it must derive one from the "
          f"examples…{RST}")

    result, why = synthesize_fold(examples)
    if result is None:
        print(f"  {BOLD}REPORTED GAP{RST}: {why}")
        print()
        return

    print(f"  {GRN}✓ Derived a procedure consistent with the examples{RST}  "
          f"{DIM}(model-free · kind: {result['kind']}){RST}")
    print("    program:")
    for step in result["steps"]:
        print(f"       {step}")
    print("  Now run the derived program on inputs it has NEVER seen:")
    for items in unseen:
        got = result["run"](items)
        print(f"     {str(items):<18} → {GRN}{got}{RST}")
    print()


def gap(title, examples, note):
    print(f"{BOLD}{CYN}[{title}]{RST}")
    print("  Examples it is shown "
          f"{DIM}(same shape as above: a list of integers → an integer){RST}:")
    for ex in examples:
        print(f"     {str(ex['input']):<14} → {ex['output']}")
    print(f"  {DIM}It attempts to derive a procedure that explains these…{RST}")
    result, why = synthesize_fold(examples)
    if result is None:
        print(f"  {BOLD}REPORTED GAP{RST}: {why}")
    else:
        print(f"  Derived: {result['kind']}  (unexpected — it found one)")
    print(f"  {DIM}{note}{RST}")
    print()


def main():
    header()

    show("SUM",
         [{"input": [1, 2, 3], "output": 6},
          {"input": [4, 5], "output": 9},
          {"input": [10, 20], "output": 30}],
         unseen=[[10, 20, 30, 40], [7, 7, 7, 7]])

    show("COUNT  (same inputs — only the outputs differ)",
         [{"input": [1, 2, 3], "output": 3},
          {"input": [4, 5], "output": 2},
          {"input": [10, 20], "output": 2}],
         unseen=[[10, 20, 30, 40], [9]])

    show("MAXIMUM  (same inputs — only the outputs differ)",
         [{"input": [1, 2, 3], "output": 3},
          {"input": [4, 5], "output": 5},
          {"input": [10, 20], "output": 20}],
         unseen=[[10, 20, 30, 40], [4, 9, 2, 9, 1]])

    gap("OUT OF REACH — an honest boundary, not a hallucination",
        [{"input": [2, 3], "output": 6},
         {"input": [2, 4], "output": 8},
         {"input": [1, 5], "output": 5}],
        note="Product is well-formed input, but not something it can build from "
             "its current operators. It attempts a derivation, finds none "
             "consistent with the examples, and reports that — it does not "
             "fabricate an answer.")

    rule("═")
    print(f"{BOLD} One derivation engine. Given only examples, it derived executable{RST}")
    print(f"{BOLD} procedures, validated them by execution, generalized them to new{RST}")
    print(f"{BOLD} inputs — and reported a gap where it lacked the knowledge.{RST}")
    print(f"{DIM} The language model was never called.{RST}")
    rule("═")


if __name__ == "__main__":
    main()
