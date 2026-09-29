#!/usr/bin/env python3
"""The development phase of an experiment that serves a release: teach the sandbox's model, then stop.

Run as its own process, because a process is one environment for its whole life. It starts the substrate in
development on `torinai_dev` (the sandbox), teaches the SHAPES-LEARN-01 lesson through the one teaching path,
stores one memory of the substrate's own carrying `--mark`, shuts down, and prints what it did as JSON on its
last line. The release cut from the sandbox afterwards carries all of it.

Run: ./venv_torin/bin/python3 experiments/_develop.py --mark WORD [--seconds N]
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path

os.environ.pop("TORINAI_RELEASE", None)
os.environ["TORINAI_ENVIRONMENT"] = "development"
os.environ["POSTGRES_DATABASE"] = "torinai_dev"
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LESSON_DOMAIN = "lesson_01"


class Lesson:
    """The SHAPES-LEARN-01 lesson as a teaching source."""

    name = "the SHAPES-LEARN-01 lesson"
    curated = True
    quality = 0.9

    def provenance(self):
        from core.learning.teaching_sources import _provenance
        return _provenance("teaching", "develop-lesson")

    def records(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "shapes_learn_01", ROOT / "experiments" / "SHAPES-LEARN-01" / "experiment.py")
        lesson = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lesson)
        from core.learning.teaching import TaughtRecord
        for sentence, meaning, situation in lesson.LESSON:
            yield TaughtRecord(subject="", relation="", obj="", quality=self.quality,
                               sentence=sentence, meaning=meaning, situation=situation)


async def main(mark: str, seconds: float) -> dict:
    from core.memory import Origin
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()
    await db.assert_database_identity("torinai_dev")
    log = io.StringIO()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        from core.main import get_system
        system = get_system()
        await system.start()
        try:
            await asyncio.sleep(seconds)
            from core.learning import get_learning_authority
            from core.learning.teaching import TeachingPass
            from core.memory import get_memory_agent
            report = await TeachingPass(Lesson(), domain=LESSON_DOMAIN, sample=False).run(
                get_learning_authority())
            agent = await get_memory_agent()
            stored, memory_id = await agent.store_memory(
                content=f"The substrate's own note: {mark} is a word it was taught to remember.",
                tags=["develop_phase"], importance_score=0.9, origin=Origin.own("_develop"))
            # A release is cut with every concept encoded: development finishes its own encoding first.
            from core.integration.universal_domain_master import get_universal_domain_master
            encoded = await get_universal_domain_master().start_concept_embedding()
        finally:
            await system.shutdown()
    return {"environment": db.environment, "database": db.database, "patterns": report.patterns,
            "facts": report.taught, "meanings": report.meanings, "memory_stored": stored,
            "memory_id": memory_id, "lesson_domain": LESSON_DOMAIN, "concepts_encoded": encoded}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark", required=True)
    parser.add_argument("--seconds", type=float, default=20.0)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main(args.mark, args.seconds)), default=str))
