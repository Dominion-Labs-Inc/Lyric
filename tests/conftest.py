"""Tests run against the sandbox store, never the model's.

`lyric_db` is the main model: it holds only what the substrate was taught on
purpose. A test that talks to a real store writes whatever it exercises -- on
2026-09-27 `test_conversation.py` wrote 104 rows into the lesson-only store,
among them the wrong fact `load balancer isa replaced`. So every test process
uses `lyric_dev`, an empty copy of the same structure, unless the run names a
database itself (`POSTGRES_DATABASE=... pytest ...`).

This holds because the one authority for connection settings
(`core/database/postgres_config.py`) puts the process environment ahead of the
`.env` files, and the `.env.production` that several tests load with
`override=True` sets no `POSTGRES_*` value.

AND A TEST OF WHAT THE DOOR NAMES NEEDS THE WORDS LYRIC WAS TAUGHT. Naming a term asks what Lyric holds --
whether a word is used as a plural at all, and what it holds the plural written from
(`lexical_normalization._held_singular`, 2026-11-13) -- and `lyric_dev` holds no constructions at all against
main's 429,012, so a process started on it names by the spelling rules and writes "acrobatics" `acrobatic` and
"Mars" `mar`. `lyrics_words` below warms a view for the tests that need one. It is asked for on purpose, because
it costs about four minutes and reads a store that was taught:

    POSTGRES_DATABASE=lyric_db LYRIC_TEST_WORDS=1 ./venv_lyric/bin/python3 -m pytest tests/test_lexical_normalization.py

Two deliberate acts, not one: naming the store is not enough on its own, so no ordinary run pays for a warm or
touches main by accident. Without both, the fixture holds nothing and the tests that need words say so and skip.
Nothing is written where it warms: the agent is put in shadow mode, so no background cognitive loop and no write
queue runs, and the tests that use it only ask what a word is called.
"""
import os

import pytest

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")


@pytest.fixture(scope="session")
def lyrics_words():
    """The words Lyric was taught, warmed into this process, or None where this run holds none.

    Once per session, because the warm reads every construction memory the store holds and takes about four
    minutes of it. A test asks for this and then asks the door; it does not reach into the view itself."""
    from core.semantics.derived_reader import live_view
    view = live_view()
    if len(view):
        return view
    if not os.environ.get("LYRIC_TEST_WORDS"):
        return None

    import asyncio

    async def warm():
        for key, value in {"LYRIC_NO_WATCHDOG": "1", "LYRIC_SHADOW_MODE": "1"}.items():
            os.environ.setdefault(key, value)
        from core.agents.memory_agent import get_memory_agent
        agent = await get_memory_agent()
        await agent.initialize()
        held = await agent.warm_word_classes()
        await agent.stop_memory_loops()
        return held

    held = asyncio.run(warm())
    view = live_view()
    if not len(view):
        raise RuntimeError(
            f"LYRIC_TEST_WORDS is set and {os.environ.get('POSTGRES_DATABASE')!r} was warmed to {held:,} word(s), "
            "but it holds no constructions: name a store that was taught English in POSTGRES_DATABASE")
    return view
