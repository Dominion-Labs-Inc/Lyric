"""What main reads and says, and HOW IT CUT THE SENTENCE UP BEFORE IT READ IT.

Read only. For each sentence: the pieces the sentence machine made of it, the words those pieces are written as, the
tokens the grammar is actually handed, then the meaning read (or why none) and how surely that reading is the one
among all the whole readings; then that very meaning said back, with how sure it is of each sentence it says
(`how_surely`).

THE TOKENS ARE PRINTED BECAUSE A FUSED ONE IS INVISIBLE IN THE REPLY. "Is iron a metal?", answered honestly as "I
hold nothing for metal." before 8,566 word records were taught, afterwards came back "I don't hold iron a yet" --
a word that does not exist. Nothing in the reply, the meaning or the sureness says where "iron a" came from; only
the tokens do. Where a token holds a space this prints each of its parts with whether `Words.uses` holds it, because
that is the one test `tokens_of` splits a fused piece back on (grammar.py:2176) and a closed-class word like "a" is
held by the lexicon rather than by `Words`.

Given sentences on the command line it reads those; given none, the four taught, the three composed of their words
and the two controls holding a word never taught.

For each thing the meaning names it prints HOW OFTEN EACH WORD IS USED FOR THAT THING (`Words.used_for`), which is
what saying weighs the words for a thing by, because the word it ends up saying is otherwise the only evidence of
what it had to choose between. `WORDS` asks the same of the grammar's own words: how each is used and what each of
its entries scores, which is what decides between two ways of saying one piece ("is" against "does ... be").

  POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" WORDS="is,does,be" \
      ./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-03/check.py "Is iron a metal?" "Is a dog an animal?"
"""
import asyncio, contextlib, io, math, os, sys, time
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
    groups = (("GIVEN", sys.argv[1:]),) if len(sys.argv) > 1 else (
        ("TAUGHT", TAUGHT), ("COMPOSED", COMPOSED), ("CONTROL", CONTROL))
    for name, group in groups:
        print(f"── {name} ──", flush=True)
        for text in group:
            at = time.time()
            tokens = gm.tokens_of(text, view.words)
            print(f"{text}", flush=True)
            # HOW THE SENTENCE WAS CUT UP, before anything is said about what it means.
            from core.semantics.sentence_machine import form_of
            from core.semantics.structure import words_of
            written = words_of(form_of(text))
            print(f"    PIECES  {list(written)}", flush=True)
            print(f"    TOKENS  {[str(t) for t in tokens]}", flush=True)
            for token in tokens:
                if " " in str(token):
                    parts = str(token).split()
                    held = ", ".join(f"{p}={'held' if view.words.uses(p) else 'NOT in Words'}" for p in parts)
                    print(f"    FUSED   {str(token)!r} stayed one token: {held}", flush=True)
            reading = view.grammar.read(tokens)
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
            # HOW OFTEN EACH WORD IS USED FOR EACH THING THE MEANING NAMES (`Words.used_for`), which is what saying
            # weighs the words for a thing by: printed because the word it says is otherwise the only evidence of
            # which words it had to choose between, and that is the thing under test.
            for concept, cls in sorted(gm._things_said(reading.meaning)):
                if cls in ("PRONOUN", "NAME"):
                    continue
                used = view.words.used_for(str(concept), cls)
                if used:
                    worded = ", ".join(f"{w} {n:.0f}" for w, n in list(used.items())[:6])
                    print(f"    USED FOR {concept} ({cls}): {worded}"
                          f"{' ...' if len(used) > 6 else ''}", flush=True)
                    # WHAT EACH WORD IS WEIGHED BY, both halves: the entry's own score, which is how surely the
                    # WORD is read as a word of that kind and says nothing of the thing (`Lexicon.entries`:
                    # `evidence`), and the weight saying adds for how often the word is used FOR THE THING
                    # (`Grammar._say`). Printed together because which of the two decides the word said is the
                    # whole question, and the word said alone does not say which it was.
                    total = sum(used.values())
                    for form, n in list(used.items())[:6]:
                        scores = [e.score for _, e in view.grammar.lexicon.entries((form,), 0) if e.cls == cls]
                        if scores:
                            share = math.log((n + 0.5) / (total + 0.5 * len(used)))
                            print(f"      {form:16s} entry {max(scores):7.3f}   used for it {share:7.3f}"
                                  f"   = {max(scores) + share:7.3f}", flush=True)
            at = time.time()
            how_surely: dict = {}
            why: dict = {}
            said = view.say(reading.meaning, why=why, how_surely=how_surely)
            if not said:
                print(f"    SAID: nothing -- {why.get('why') or '?'}  [{time.time() - at:.1f}s]", flush=True)
                continue
            for i, sentence in enumerate(said[:8]):
                mark = "<-- says first" if i == 0 else ""
                print(f"    SAID {i + 1:2d} sure {how_surely.get(sentence, 0.0):.3f}  {sentence!r} {mark}",
                      flush=True)
            back = [s.rstrip(".?!") for s in said]
            where = back.index(text.rstrip(".?!")) + 1 if text.rstrip(".?!") in back else 0
            print(f"    {len(said)} sentence(s) said in {time.time() - at:.1f}s"
                  + (f"; THE SENTENCE IT WAS GIVEN IS THE {where} OF THEM" if where else
                     "; the sentence it was given is NOT among them"), flush=True)
        print(flush=True)
    # HOW EACH OF THE WORDS GIVEN IS USED, AND WHAT EACH OF ITS ENTRIES SCORES, as saying asks it: a grammar word's
    # entry is scored by how surely the word is READ in that use (`Lexicon.entries`: `evidence`), which is the only
    # thing that decides between two ways of saying the same piece with different words. Asked of the copula and the
    # auxiliaries, this is why a question is said one way and not another: "Does a dog be a creature?" was said for
    # `ask isa(dog, animal)` where "Is a dog an animal?" says it in one word.
    #
    #   WORDS="is,'s,does,be" POSTGRES_DATABASE=lyric_db ... check.py "Is a dog an animal?"
    for word in [w for w in os.environ.get("WORDS", "").split(",") if w]:
        used = view.words.uses(word)
        print(f"── {word!r} ──", flush=True)
        print("    USED  " + ", ".join(f"{u} {n:.0f}" for u, n in
                                       sorted(used.items(), key=lambda it: -it[1])[:10])
              + f"   ({sum(used.values()):.0f} in all)", flush=True)
        for _, entry in sorted(view.grammar.lexicon.entries((word,), 0), key=lambda e: -e[1].score):
            print(f"    {entry.score:8.3f}  {entry.cls:9s} {entry.label or entry.name:14s} {entry.cat}", flush=True)
        print(flush=True)
    # EVERY THING A WORD MAY NAME, AND WHAT EACH OF THEM IS A KIND OF: the senses memory holds of the word
    # (`word_senses_alike`), each with how often it is used and the first kinds of its chain (`word_kinds`, which is
    # what reasoning is handed of what a question names). A question about a word's minor sense can only be answered
    # where that sense is held AND the listener takes the word in it, and these are the two halves: this says what
    # is held, and what the sentence reads to says which was taken.
    #
    #   SENSES="mouse,bank,head" POSTGRES_DATABASE=lyric_db ... check.py "Is a mouse an animal?"
    for word in [w for w in os.environ.get("SENSES", "").split(",") if w]:
        alike = agent.word_senses_alike(word)
        used = {m["concept"]: m for m in agent.word_meanings(word)}
        print(f"── {word!r}: {len(alike)} thing(s) it may name ──", flush=True)
        for concept in alike:
            held = used.get(concept, {})
            kinds = [k for k, _ in agent.word_kinds(concept)]
            print(f"    {concept!r} ({held.get('class', '?')}, used {held.get('used', '?')}"
                  f"{', named by the word' if held.get('named') else ''}): {kinds[:5]}"
                  f"{' ...' if len(kinds) > 5 else ''}", flush=True)
            if held.get("means"):
                print(f"        means: {held['means'][:120]}", flush=True)
        print(flush=True)


asyncio.run(main())
