"""UNDERSTANDS-PROSE-02: reading prose nobody fitted the reader to, and reasoning over what was read.

UNDERSTANDS-PROSE-01's claim, on texts held out from all the work done on it: 50 texts taken as they are published
(Wikipedia, GOV.UK, the Python documentation, arXiv, Loghub's logs, Wikinews, the United States Constitution), drawn by
a fixed seed and cut to their opening sentences (`draw.py`), and 456 questions written from them before any of it was
read by the substrate (`questions.py`, joined by `assemble.py` into `texts.json`). Sized so each measure is known to
about five points either way, and reported with its 95% interval.

Told, asked and scored by UNDERSTANDS-PROSE-01's harness, unchanged: each text told sentence by sentence in a
conversation of its own held not to remember, then asked; wrong answers counted apart; nothing written to the store.

Run (from the Lyric folder; starts no substrate):
    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/UNDERSTANDS-PROSE-02/experiment.py
"""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
# A question that spins at full CPU and logs nothing can only be read from its stack, and reading another process's
# stack takes root on macOS. Registered here, the run writes its own on `kill -USR1 <pid>` and goes on running.
sys.path.insert(0, str(ROOT))
from core.utils.stack_dump import dump_stacks_on_signal  # noqa: E402
dump_stacks_on_signal("prose02", ROOT / "logs")

_spec = importlib.util.spec_from_file_location("understands_prose_01", ROOT / "experiments" / "UNDERSTANDS-PROSE-01" / "experiment.py")
prose = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prose)

CLAIM = ("the substrate reads prose nobody fitted it to as its sources write it, and reasons over what it read: it "
         "understands the sentences, answers what they say and what follows, and does not answer wrongly what it did "
         "not understand")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", type=int, default=1, help="the text to begin at (1 is the first)")
    parser.add_argument("--to", dest="end", type=int, default=None, help="the last text to run (the last of all if not given)")
    parser.add_argument("--half", choices=("fit", "held"), default=None,
                        help="only the texts of one half of split.json: those fixed against, or those kept unseen")
    parser.add_argument("--texts", default=None,
                        help="only these texts of the half fixed against, by number: 8,13,14 (never a text kept unseen)")
    asked = parser.parse_args()
    split = json.loads((HERE / "split.json").read_text())
    only = set(split[asked.half]) if asked.half else None
    part = f"the half {'fixed against' if asked.half == 'fit' else 'kept unseen'}" if asked.half else None
    if asked.texts:
        only = {int(n) for n in asked.texts.split(",")}
        if only - set(split["fit"]):
            parser.error(f"texts kept unseen are run only as their half, once: {sorted(only - set(split['fit']))}")
        part = "texts of the half fixed against"
    sys.exit(asyncio.run(prose.main("UNDERSTANDS-PROSE-02", HERE, CLAIM, start=asked.start, end=asked.end, only=only,
                                    part=part)))
