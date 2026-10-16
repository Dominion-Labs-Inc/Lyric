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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("questions", nargs="*")
    parser.add_argument("--file", default=None)
    parser.add_argument("--one", action="store_true", help="ask the command line's questions in one conversation")
    parser.add_argument("--main", action="store_true", help="allow lyric_db")
    args = parser.parse_args()
    database = os.environ.get("POSTGRES_DATABASE", "")
    if database in ("", "lyric_db") and not args.main:
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
