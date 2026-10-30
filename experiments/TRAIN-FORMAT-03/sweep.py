"""EVERYTHING ACCOUNTED FOR BEFORE A TEACH: what main reads and says over a broad set of real sentences, with every
failure named by its cause instead of one being found at a time.

READ ONLY on the store. The PMB's gold training sentences, each with the meaning it was annotated with: read the
sentence and compare what is read with that meaning, then say that very meaning back and compare the words. Each
failure is counted under its cause, and the causes are what the grammar itself gives (`Reading.why`, `Grammar.say`'s
`why`), never a guess made after the fact.
"""
import asyncio, contextlib, io, sys, time
from collections import Counter
sys.path.insert(0, "/Users/stefan/Dominion Labs/Lyric")

READ = 400          # sentences read and compared with the meaning they are annotated with
SAID = 120          # of those read right, how many to say back
LONGEST = 90.0      # a sentence still being said after this is counted as one, never dropped silently


async def main():
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        agent = await get_memory_agent()
        await agent.initialize()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
    view = agent.grammar_view()
    view.learn_waiting()
    from core.semantics import grammar as gm
    from core.learning.teaching_sources import PMBSource, ClosedClassSource
    for item in ClosedClassSource().word_forms():
        view.words.held_forms.hold(item)

    words = view.words
    print(f"main, read only. forms for {len(words.held_forms)} base words, "
          f"{sum(words.subjects().values()):,.0f} subjects over {len(words.took_subjects())} verbs, "
          f"{sum(words.objects().values()):,.0f} things after a verb.")
    print(f"the PMB's gold training sentences: {READ} read, {SAID} of what reads right said back.")
    print()

    taught = []
    for sentence in PMBSource(part="gold").taught_sentences():
        taught.append(sentence)
        if len(taught) >= READ:
            break

    read_why: Counter = Counter()
    right = []
    for item in taught:
        text, want = item.sentence, item.meaning
        at = time.time()
        reading = view.grammar.read(gm.tokens_of(text, words))
        took = time.time() - at
        if reading.meaning is None:
            why = (reading.why or "no whole reading")
            read_why[f"read nothing: {str(why)[:60]}"] += 1
        elif reading.meaning.canonical() != want.canonical():
            read_why["read, but not the meaning it is annotated with"] += 1
        else:
            read_why["read exactly the meaning"] += 1
            right.append((text, reading.meaning))
        if took > LONGEST:
            read_why[f"and took over {LONGEST:.0f}s to read"] += 1

    print("== READING, over %d sentences ==" % len(taught))
    for cause, n in read_why.most_common():
        print(f"  {n:>5}  {cause}")

    say_why: Counter = Counter()
    wrong = []
    for text, meaning in right[:SAID]:
        why: dict = {}
        at = time.time()
        said = view.grammar.say(meaning, why=why)
        took = time.time() - at
        if not said:
            say_why[f"said nothing: {str(why.get('why'))[:62]}"] += 1
        elif said[0] == text:
            say_why["said back word for word"] += 1
        else:
            say_why["said back otherwise"] += 1
            wrong.append((text, said[0]))
        if took > LONGEST:
            say_why[f"and took over {LONGEST:.0f}s to say"] += 1

    print()
    print("== SAYING, over %d of them ==" % min(len(right), SAID))
    for cause, n in say_why.most_common():
        print(f"  {n:>5}  {cause}")
    print()
    print("== SAID BACK OTHERWISE, the first 40 ==")
    for text, said in wrong[:40]:
        print(f"  {text}")
        print(f"      -> {said}")

asyncio.run(main())
