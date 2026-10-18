"""Trace how a question about a happening is answered: tell a conversation some sentences, ask it questions, and show
each step of matching the question to what it was told (`Conversation._asked_of_events`): the question's meaning
with its known things found, the events pointing at what it names, each candidate's links, and what was said.

The conversation is held not to remember, as UNDERSTANDS-PROSE-01's are: it writes nothing to the store.

Run (from the Lyric folder; starts no substrate, reads only):
    LYRIC_COMPOSE=1 POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 scripts/trace_question.py \
        [--text NAME]
with `--text` one of UNDERSTANDS-PROSE-01's texts (default `whales`), its sentences told and its questions asked.
"""
import asyncio
import contextlib
import io
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.basicConfig(level=logging.WARNING)


def say(*a):
    print(*a, flush=True)


async def main() -> int:
    name = sys.argv[sys.argv.index("--text") + 1] if "--text" in sys.argv else "whales"
    texts = json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-01" / "texts.json").read_text())
    text = next(t for t in texts if t["name"] == name)
    quiet = io.StringIO()
    say("loading memory (no substrate is started)…")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.autonomous.autonomous_coordinator import get_conversation
        from core.agents.memory_agent import get_memory_agent
        from core.database import get_unified_db
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        agent = await get_memory_agent()
        await agent.initialize()
        await get_uncertainty_system().load_from_db()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
        db = await get_unified_db()
        if not getattr(db, "initialized", False):
            await db.initialize()
    from core.semantics import derived_reader
    if "--word" in sys.argv:
        # HOW ONE WORD IS READ ON ITS OWN: what memory holds of it, whether each holding says more than its concept,
        # whether it may be read as new, and what a shape that says more would make of it, with the words showing it.
        view, word = derived_reader.live_view(), sys.argv[sys.argv.index("--word") + 1]
        held = view.lexicals_with_words((word.lower(),), loose=True)
        say(f"{word!r} held as: {[(lx.value, view.counts(lx), view.says_more(lx.words[0], lx.value)) for lx in held]}")
        say(f"   (value, counts, says more); may be new: "
            f"{derived_reader._may_be_new((derived_reader.Piece(word, False),), view, 1)}")
        say(f"   a shape of: {view.names_of_shape(word)}")
        for made, says, members in view.shaped_phrases(word):
            shown = sorted({c for w, n in [view._shape_groups[says][m] for m in members]
                            for c in view.changes_between(w, n)})[:12] if says in view._shape_groups else []
            say(f"   shaped: {made!r} says {sorted(says)}; {len(members)} words show it, e.g. "
                f"{[view._shape_groups[says][m] for m in members][:8]}; changes {shown}")
        return 0
    conversation = get_conversation(f"trace_question_{name}", remembers=False)

    # ── each step, watched, not changed ──────────────────────────────────────────────────────────────────────────
    incoming_of, resolve_name, said_by = conversation._incoming_relations, conversation.resolve_name, derived_reader.say

    async def incoming(phrase):
        rows = await incoming_of(phrase)
        told = [r for r in rows if "_" in str(r[0]) and not str(r[0]).replace("_", "").isalpha()]
        say(f"      pointing at {phrase!r}: {len(rows)} links; from what was told here: {told[:6]}")
        return rows

    async def resolved(phrase, *a, **k):
        held = await resolve_name(phrase, *a, **k)
        say(f"      candidate {phrase!r}: known={held.known} links={list(held.relations)[:12]}")
        return held

    def said(meaning, *a, **k):
        out = said_by(meaning, *a, **k)
        say(f"      said {meaning.canonical()[:160]} -> {list(out)[:2]}")
        return out
    conversation._incoming_relations, conversation.resolve_name, derived_reader.say = incoming, resolved, said

    view = derived_reader.live_view()
    for sentence in text["text"]:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            u = await conversation.understand(sentence, look_up=False)
        say(f"\ntold {sentence!r}\n   -> {(u.reply or '').strip()[:300]!r}")
        # HOW EACH WORD WAS NAMED: the reading taken, its words and what each names; for a word named otherwise
        # than as held, what memory holds of it and the held words it is written as a shape of.
        for utterance in conversation._read(sentence):
            chosen = derived_reader.meant(utterance.readings, heard=conversation._heard(sentence))
            if chosen is None:
                say(f"   no one reading taken of {utterance.text!r} ({len(utterance.readings)} readings); the likeliest, "
                    f"as the listener weighs them (`meant`):")
                worths = view.listening_worths()
                best = {}
                for reading in utterance.readings:
                    best.setdefault(reading.meaning.canonical(), reading)
                weighed = derived_reader.weighed(list(best.values()), view, heard=conversation._heard(sentence))

                def score(w):
                    return round(w.activation + w.derivation + sum(
                        worths.get((evidence, level), 0.0)
                        for evidence, level in derived_reader.listening_levels(w).items()), 6)
                for w in sorted(weighed, key=score, reverse=True)[:6]:
                    named = [c.value for c in w.reading.constructions if isinstance(c, derived_reader.Lexical)]
                    say(f"      {score(w):9.3f} (activation {w.activation:.3f}, derivation {w.derivation:.3f}) "
                        f"{w.reading.meaning.canonical()[:200]}\n                names {named[:8]}")
                continue
            say(f"   reading taken{' (composed)' if getattr(chosen, 'composed', False) else ''}: "
                f"{chosen.meaning.canonical()[:240]}")
            for construction in chosen.constructions:
                if isinstance(construction, derived_reader.Lexical):
                    words = " ".join(construction.words)
                    held = sorted({lx.value for lx in view.lexicals_with_words(tuple(construction.words), loose=True)})
                    if construction.value not in held:
                        say(f"      {words!r} named {construction.value!r}; held as {held[:6]}; a shape of "
                            f"{view.names_of_shape(construction.words[0])[:6]}")
    from core.agents.memory_agent import memory_agent
    say("\nheld in working memory for this conversation:")
    for row in memory_agent().working_relations([conversation._actor]):
        say(f"   {row['subj']} {row['rel']} {row['obj']} ({row['pol']})")
    for question in text["questions"]:
        say(f"\nasked {question['q']!r}")
        meaning = conversation._meaning(question["q"])
        say(f"   reading: {meaning.canonical() if meaning else None}")
        if meaning is not None:
            known = await conversation._known_of(meaning)
            say(f"   known things found: {known}")
            say(f"   bound: {[f.render() for f in meaning.bound(conversation._situation(), known)]}")
        resolved = await conversation.resolve(question["q"])
        say(f"   phrases found: {[(r.phrase, r.known) for r in resolved]}")
        say("   matching it to what was told (_asked_of_events), as `understand` does:")
        with contextlib.redirect_stderr(quiet):
            pointing = {r.phrase: await conversation._incoming_relations(r.phrase) for r in resolved if r.known}
            answers = await conversation._asked_of_events(question["q"], pointing)
        say(f"   answered from events: {[(a.about, a.told, a.verdict) for a in answers]}")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            u = await conversation.understand(question["q"], look_up=False)
        say(f"   reply: {(u.reply or '').strip()[:300]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
