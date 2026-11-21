#!/usr/bin/env python3
"""Talk to Lyric directly, as a person does, and print what it says.

Starts the substrate on the store named by POSTGRES_DATABASE (about three and a half minutes: the substrate, then
the reader's view of everything taught), then:
  - with questions on the command line, asks each in a conversation of its own (all in one with --one);
  - with --file, holds each conversation the file has, in order: a conversation is a run of lines, and a blank
    line starts the next;
  - with neither, stays open and answers what is typed: a blank line starts a new conversation, Ctrl-D ends.
Nothing is looked up outside the store. Conversation remembers every turn, so this refuses lyric_db unless --main.

    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 scripts/ask.py "Is a hawk a bird?"
    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 scripts/ask.py --file data/probes/reasoning_conversations.txt
    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 scripts/ask.py

With --measure it asks instead of talks: a BROAD sample of the sentences the store itself holds, each in a
conversation that remembers nothing, bucketed by what came back. Not the 28 cases `check_reading.py` guards and
not the 3,237 lessons the listener's worths are counted on -- the holophrases hold every sentence ever taught
from every source, which is the language the store actually has.

    POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 scripts/ask.py --main --measure --sample 300
"""
import argparse
import asyncio
import contextlib
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(_k, _v)


def conversations_in(text: str):
    """The conversations a file holds: runs of non-blank lines."""
    out, current = [], []
    for line in text.splitlines():
        if line.strip():
            current.append(line.strip())
        elif current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


async def _sentences(whence: str, how_many: int, seed: int, quiet) -> list:
    """A broad sample of sentences to ask, each with where it came from: the store's own holophrases (every
    sentence ever taught, from every source) and the lessons the listener's worths are counted on."""
    import json as _json
    import random as _random
    found: list = []
    if whence in ("store", "both"):
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            from core.agents.memory_agent import get_memory_agent
            view = await (await get_memory_agent()).language_view()
            held = view.holophrases()
        for item in held:
            said = getattr(item, "surface", None)
            if not said or item.slots:
                continue          # a frame is not a sentence; only what is held whole
            words = said.split()
            if len(words) < 3 or len(words) > 40:
                continue
            found.append({"said": said, "whence": "store"})
    if whence in ("lessons", "both"):
        for path in sorted(Path("data/lessons").glob("english_[0-9][0-9].json")):
            for record in _json.loads(path.read_text(encoding="utf-8")).get("records", ()):
                found.append({"said": record["sentence"], "whence": f"lesson:{path.stem}"})
    seen, unique = set(), []
    for row in found:
        if row["said"] not in seen:
            seen.add(row["said"])
            unique.append(row)
    _random.Random(seed).shuffle(unique)
    return unique[:how_many]


async def _measure(system, coord, args, quiet) -> int:
    """Ask each sentence in a conversation that remembers NOTHING and is forgotten after -- the door's own
    read-only probe (`instance_door._check`) -- and bucket what came back. Nothing is written."""
    import json as _json
    from collections import Counter
    from core.agents.autonomous.autonomous_coordinator import end_conversation, get_conversation

    asked = await _sentences(args.whence, args.sample, args.seed, quiet)
    print(f"asking {len(asked)} sentence(s), each forgotten after; nothing is written\n", flush=True)
    buckets: Counter = Counter()
    whys: Counter = Counter()
    by_whence: Counter = Counter()
    rows = []
    began = time.perf_counter()
    for at, row in enumerate(asked, 1):
        session = f"measure:{time.time_ns()}"
        started = time.perf_counter()
        reply = None
        verdicts: list = []
        why_not: list = []
        trouble = None
        try:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                try:
                    understood = await get_conversation(session).understand(
                        row["said"], look_up=False)
                finally:
                    end_conversation(session)
            reply = (understood.reply or "").strip() or None
            verdicts = [a.verdict for a in (understood.answers or [])]
            why_not = [dict(reason) for reason in (understood.why_not or ())]
        except Exception as trouble_here:            # a sentence that breaks is a result, not the end of the pass
            trouble = f"{type(trouble_here).__name__}: {trouble_here}"
        took = time.perf_counter() - started
        settled = {v for v in verdicts if v is not None} if verdicts and None not in verdicts else set()
        if trouble is not None:
            bucket = "broke"
        elif reply is None:
            bucket = "said nothing"
        elif len(settled) == 1:
            bucket = "answered yes" if settled.pop() else "answered no"
        elif verdicts:
            bucket = "replied, unsettled"
        else:
            bucket = "replied, nothing to settle"
        buckets[bucket] += 1
        by_whence[(row["whence"].split(":")[0], bucket)] += 1
        for reason in why_not:
            whys[str(reason.get("why") or sorted(reason)[:1])] += 1
        rows.append({**row, "reply": reply, "verdicts": verdicts, "why_not": why_not,
                     "bucket": bucket, "broke": trouble, "seconds": round(took, 2)})
        if at % 10 == 0 or at == len(asked):
            print(f"  {at}/{len(asked)}  {dict(buckets)}  ({time.perf_counter()-began:.0f}s)", flush=True)

    print(f"\n  {len(asked)} sentence(s) in {time.perf_counter()-began:.0f}s")
    for bucket, n in buckets.most_common():
        print(f"     {bucket:30s} {n:5d}  {100.0*n/max(1,len(asked)):5.1f}%")
    print("\n  by where the sentence came from:")
    for (whence, bucket), n in sorted(by_whence.items()):
        print(f"     {whence:10s} {bucket:30s} {n:5d}")
    if whys:
        print("\n  why nothing answered, most often first:")
        for why, n in whys.most_common(12):
            print(f"     {n:5d}  {why[:120]}")
    if args.out:
        Path(args.out).write_text(_json.dumps(rows, indent=1), encoding="utf-8")
        print(f"\n  rows written to {args.out}")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("questions", nargs="*")
    parser.add_argument("--file", default=None)
    parser.add_argument("--one", action="store_true", help="ask the command line's questions in one conversation")
    parser.add_argument("--main", action="store_true", help="allow lyric_db")
    parser.add_argument("--measure", action="store_true",
                        help="ask a broad sample of the sentences the store holds and bucket what came back")
    parser.add_argument("--sample", type=int, default=200, help="--measure: how many sentences")
    parser.add_argument("--from", dest="whence", default="both", choices=("store", "lessons", "both"),
                        help="--measure: where the sentences come from")
    parser.add_argument("--out", default=None, help="--measure: write the rows here as JSON")
    parser.add_argument("--seed", type=int, default=7, help="--measure: which sample")
    args = parser.parse_args()
    database = os.environ.get("POSTGRES_DATABASE", "")
    if database in ("", "lyric_db") and not args.main and not args.measure:
        print("refused: conversation remembers every turn; set POSTGRES_DATABASE to a copy, or pass --main")
        return 2
    if args.file:
        conversations = conversations_in(Path(args.file).read_text())
    elif args.questions:
        conversations = [args.questions] if args.one else [[q] for q in args.questions]
    else:
        conversations = None

    print(f"starting Lyric on {database}…", flush=True)
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        from core.agents.memory_agent import get_memory_agent
        await (await get_memory_agent()).warm_word_classes()
    coord = system.autonomous_coordinator
    print("ready.\n", flush=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    count = [0]

    def conversation():
        count[0] += 1
        return coord.conversation(f"ask_{stamp}_{count[0]}")

    async def say(talk, line: str) -> None:
        started = time.perf_counter()
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            understanding = await talk.understand(line, look_up=False)
        took = time.perf_counter() - started
        print(f"Q: {line}")
        print(f"A: {(understanding.reply or '(said nothing)').strip()}")
        print(f"   ({took:.1f}s)\n", flush=True)

    if args.measure:
        return await _measure(system, coord, args, quiet)

    try:
        if conversations is not None:
            for at, lines in enumerate(conversations, 1):
                print(f"=== conversation {at} ===\n", flush=True)
                talk = conversation()
                for line in lines:
                    await say(talk, line)
        else:
            print("type to Lyric; a blank line starts a new conversation, Ctrl-D ends.\n", flush=True)
            talk = conversation()
            while True:
                try:
                    line = await asyncio.to_thread(input, "> ")
                except EOFError:
                    break
                if not line.strip():
                    talk = conversation()
                    print("(new conversation)\n", flush=True)
                    continue
                await say(talk, line.strip())
    finally:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await system.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
