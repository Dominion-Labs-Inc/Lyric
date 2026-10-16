"""FRESH-LESSON-01, part D: a process started after the lesson, holding nothing of the run that taught it, rebuilds
the language view from memory and reads each sentence given on stdin (one JSON list). Prints one JSON object:
sentence -> the meaning it is taken to have (`Meaning.canonical`), "unread", or null where it reads but the listener
cannot tell. Sandbox only, read only."""
import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["POSTGRES_DATABASE"] = "lyric_dev"


async def main() -> None:
    sentences = json.loads(sys.stdin.read())
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.database import get_database_manager
        from core.memory import get_memory_agent
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.semantics import derived_reader as dr
        await get_database_manager().initialize()
        await get_database_manager().assert_database_identity("lyric_dev")
        await get_uncertainty_system().load_from_db()
        await (await get_memory_agent()).language_view()
        out = {}
        for sentence in sentences:
            utterances = dr.read_text(sentence)
            if not utterances or not all(u.understood for u in utterances):
                out[sentence] = "unread"
                continue
            chosen = dr.meant(utterances[-1].readings)
            out[sentence] = chosen.meaning.canonical() if chosen is not None else None
    print(json.dumps(out))


asyncio.run(main())
