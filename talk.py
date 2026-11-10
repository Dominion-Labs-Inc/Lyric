#!/usr/bin/env python3
"""Talk to the substrate. Everything it says comes out of what it holds.

    ./venv_lyric/bin/python3 talk.py                 (interactive)
    ./venv_lyric/bin/python3 talk.py "what causes pressure loss"
"""
import asyncio
import logging
import os
import sys

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
logging.disable(logging.INFO)

from core.semantics.conversation import get_conversation  # noqa: E402


async def main() -> int:
    # THROUGH THE SUBSTRATE'S OWN FRONT DOOR, not a bare `Conversation()`. The front door keys the thread by
    # session so two speakers are two threads, shares one in-flight lookup across them, and arms the observability
    # apparatus -- which a bare construction skips, so this CLI ran with the logging spine switched off.
    conversation = get_conversation("talk")
    if len(sys.argv) > 1:
        print((await conversation.understand(" ".join(sys.argv[1:]))).reply)
        return 0

    print("Talking to the substrate. Nothing it says is generated; it is held.")
    print("Ctrl-D to stop.\n")
    while True:
        try:
            said = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not said:
            continue
        understanding = await conversation.understand(said)
        print("lyric>", understanding.reply.replace("\n", "\n       "), "\n")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
