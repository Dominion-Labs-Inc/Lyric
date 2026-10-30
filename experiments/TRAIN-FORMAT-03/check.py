"""What main reads and says after its first word session and its first sentence session.

Read only. For each sentence: the meaning read (or why none) and how surely that reading is the one among all the
whole readings the grammar made; then that very meaning said back, with how sure it is of each sentence it says
(`how_surely`). The last group holds words that were never taught, as the control that must not read whole.
"""
import asyncio, contextlib, io, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TAUGHT = [
    "This stinks.",
    "I am intelligent.",
    "The whistle blew.",
    "They misled me.",
]
COMPOSED = [          # every word taught, this arrangement of them never taught
    "The person stinks.",
    "I misled the whistle.",
    "The whistle is intelligent.",
]
CONTROL = [           # holds a word that was never taught
    "This sparkles.",
    "The whistle juggled Tom.",
]


async def main():
    quiet = io.StringIO()
    at = time.time()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        agent = await get_memory_agent()
        await agent.initialize()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
    view = agent.grammar_view()
    view.learn_waiting()
    from core.semantics import grammar as gm
    print(f"store {os.environ.get('POSTGRES_DATABASE') or 'lyric_db'}: warm {time.time() - at:.0f}s, "
          f"word records {len(agent._grammar_words)}, sentence records {len(agent._grammar_records)}, "
          f"analysed sentences {len(agent.structure_view())}\n", flush=True)
    for name, group in (("TAUGHT", TAUGHT), ("COMPOSED", COMPOSED), ("CONTROL", CONTROL)):
        print(f"── {name} ──", flush=True)
        for text in group:
            at = time.time()
            tokens = gm.tokens_of(text, view.words)
            reading = view.grammar.read(tokens)
            print(f"{text}", flush=True)
            if reading.meaning is None:
                whole = "no whole reading" if reading.sign is None else "read whole, no meaning"
                print(f"    READ: nothing -- {whole}; why {reading.why or '?'}"
                      f"{'; read as far as ' + str(reading.missing[:2]) if reading.missing else ''}"
                      f"  [{time.time() - at:.1f}s]", flush=True)
                if reading.unheld:
                    print(f"    HOLDS NO WORD FOR {', '.join(reading.unheld)}", flush=True)
                continue
            print(f"    READ  sure {reading.sure:.3f}  {reading.meaning.canonical()}  [{time.time() - at:.1f}s]",
                  flush=True)
            if reading.unheld:
                # What memory does not hold of the sentence it just read confidently (`Reading.unheld`): sureness is
                # about structure, so this is the only thing that says the words were never seen.
                print(f"    HOLDS NO WORD FOR {', '.join(reading.unheld)}", flush=True)
            at = time.time()
            how_surely: dict = {}
            why: dict = {}
            said = view.say(reading.meaning, why=why, how_surely=how_surely)
            if not said:
                print(f"    SAID: nothing -- {why.get('why') or '?'}  [{time.time() - at:.1f}s]", flush=True)
                continue
            for sentence in said[:3]:
                mark = "<-- says first" if sentence == said[0] else ""
                print(f"    SAID  sure {how_surely.get(sentence, 0.0):.3f}  {sentence!r} {mark}", flush=True)
            print(f"    {len(said)} sentence(s) said in {time.time() - at:.1f}s"
                  + ("; THE SENTENCE IT WAS GIVEN IS AMONG THEM"
                     if text.rstrip(".") in {s.rstrip(".") for s in said} else ""), flush=True)
        print(flush=True)


asyncio.run(main())
