#!/usr/bin/env python3
"""REMEMBER-01 — a fact taught from a corpus is remembered like one it was told.

`learn_facts` and `admit_relation` carried a `remember` flag, and four of the
five corpus passes set it False. The result was two grades of knowledge out of
one act: ask about a fact taught in conversation and the substrate answered
"I remember: a kettle boils water."; ask about one of the 314,856 taught from
ConceptNet and it answered correctly while having no recollection of ever
learning it -- and could not reach it by MEANING at all, only by naming the
concept exactly.

The flag's two stated defences, both examined before removing it:

  "a reference taxonomy is knowledge, not a conversation"
      `_remember` does not store an event. It stores a SEMANTIC memory, for the
      express reason that what was learned "has to be findable later by MEANING
      ... the substrate's alternative to baking knowledge into weights".

  "embedding tens of thousands of episodes is slow"
      MEASURED, not argued: 12.5 facts/s with the episode against 18.4 without
      (+47%), so the full taxonomy costs ~7.0h instead of ~4.7h. Real, and not a
      reason to hold two grades of knowledge.

  A  THE FLAG IS GONE          no caller can ask for a fact without an episode.
  B  TEACHING MAKES A MEMORY   a bulk-taught fact carries a real memory id.
  C  AND IT IS RECALLED        asked about it, the substrate says it REMEMBERS,
                               which is the behaviour only conversation-taught
                               facts had before.

Run: PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/REMEMBER-01/experiment.py
"""
import asyncio
import contextlib
import inspect
import io
import os
import sys
import time
from pathlib import Path

for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1",
               "LYRIC_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

STAMP = time.strftime("%H%M%S")
PASS = FAIL = 0
OUT = []


def check(label, got, want):
    global PASS, FAIL
    good = got == want
    PASS, FAIL = PASS + good, FAIL + (not good)
    OUT.append(f"  {'PASS' if good else 'FAIL'}  {label}")
    if not good:
        OUT.append(f"          got={got!r}  want={want!r}")


async def main():
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.learning.unified_learning_system import UnifiedLearningSystem
        from core.main import get_system
        from core.semantics.cognitive_ingress import (CognitiveIngress,
                                                      get_cognitive_ingress,
                                                      Provenance)

        # A -- the flag cannot be passed by anyone.
        learn_params = inspect.signature(UnifiedLearningSystem.learn_facts).parameters
        admit_params = inspect.signature(CognitiveIngress.admit_relation).parameters

        system = get_system()
        await system.initialize()
        learning = system.autonomous_coordinator.learning

        # B -- teach the way a CORPUS pass teaches: through learn_facts, in bulk,
        # with no per-fact conversation anywhere near it.
        subject = f"zelkarn{STAMP}"
        parent = "tree"
        await learning.learn_facts([(subject, "isa", parent)],
                                   domain="remember01", quality=0.9)
        # The admission itself, to read `memories`/`memory_id` rather than trust
        # a count that cannot tell a stored memory from a declined one.
        prov = Provenance(producer="learning", source_id=f"remember01{STAMP}",
                          source_type="USER_SUPPLIED")
        direct = f"korvath{STAMP}"
        admission = await get_cognitive_ingress().admit_relation(
            subject=direct, relation="isa", obj="tool",
            surface=f"{direct} isa tool", provenance=prov,
            domain="remember01", quality=0.9)

        # C -- ask about it the way a person would.
        talk = system.autonomous_coordinator.conversation(session=f"rem{STAMP}")
        understanding = await talk.understand(f"what is a {subject}?")
        reply = understanding.reply or ""

    OUT.append(__doc__.split("Run:")[0].rstrip())
    OUT.append("\n" + "=" * 72)
    OUT.append("A  THE FLAG IS GONE")
    OUT.append("=" * 72)
    check("learn_facts has no `remember` parameter", "remember" in learn_params, False)
    check("admit_relation has no `remember` parameter", "remember" in admit_params, False)

    OUT.append("\n" + "=" * 72)
    OUT.append("B  TEACHING MAKES A MEMORY")
    OUT.append("=" * 72)
    OUT.append(f"  admitted={getattr(admission, 'admitted', False)}  "
               f"memories={getattr(admission, 'memories', None)}  "
               f"memory_id={getattr(admission, 'memory_id', None)}")
    OUT.append(f"  refusals={list(getattr(admission, 'refusals', []))}")
    check("a bulk admission stored an episode",
          bool(getattr(admission, "memories", 0)), True)
    check("and it carries a real memory id",
          str(getattr(admission, "memory_id", "") or "").startswith("mem_"), True)

    OUT.append("\n" + "=" * 72)
    OUT.append("C  AND IT IS RECALLED")
    OUT.append("=" * 72)
    OUT.append(f"  asked: 'what is a {subject}?'")
    for line in reply.split("\n")[:4]:
        if line.strip():
            OUT.append(f"      {line[:96]}")
    check("the reply says it REMEMBERS being taught this",
          "i remember" in reply.lower(), True)

    OUT.append("\n" + "=" * 72)
    OUT.append(f"{PASS}/{PASS + FAIL}")
    OUT.append("=" * 72)
    print("\n".join(OUT))
    return 0 if not FAIL else 1


sys.exit(asyncio.run(main()))
