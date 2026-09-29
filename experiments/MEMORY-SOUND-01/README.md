# MEMORY-SOUND-01: memory recalls a sound by the sound itself

**Finding (2026-09-29): 23/23** (record `20260929T140051Z`; cleanup by nonce and exact memory and intent id, 574 rows written, 0 left).

The memory agent can be asked by the sound itself whether it was heard before:
- The same recording heard twice is two memories, each keeping its own sound.
- The second hearing recalls the first by the sound, fully resolved. It says so in words ("heard before, 1 time(s),
  last on 2026-09-29 09:29"), in the graph (`same_sound_as`) and as a belief.
- Six seconds of it played into a real room, through a 64 kbit/s codec, recall both hearings, with 74% of what was
  heard agreeing.
- A different recording recalls nothing.
- A song heard untaught, then taught, names the earlier hearing: the earlier recording is now said to `play` it.
- The injector brings the same sound's memories into what is being thought, each saying it is this sound heard before.
- A person's hearing is recalled for that person, never for another person, nor for the substrate's own.
- **What is heard and seen within a pursuit is part of its one memory.** A recording heard and a picture seen
  under a pursuit's intent are that pursuit's memory, not memories of their own. The memory keeps the trace
  and the picture, its account says "I heard …" and "I saw …", and all 20 beliefs about what was heard name
  it. Heard again later, the recording is recalled as that pursuit.

**How, all in the existing systems:**
- **Hearing** keeps every hearing's landmarks in its trace (`hearing.trace_bytes(..., landmarks)`), not only a lesson's.
- **The media store** keeps each sound's distinct landmark hashes in a new column of the same table
  (`memory_media.landmarks`, with a GIN index). `by_sound()` returns candidates by what they share.
- It no longer moves a row to a second memory of the same bytes: the media id is now the memory's and the content's
  together. That was a real defect. The same recording heard twice took the first memory's sound away, so the first
  could no longer be heard again or recalled by what it held.
- **`MemoryAgent.retrieve`** has a fourth strategy, `sound`, beside semantic, keyword and tags. It is given `heard`
  (landmark rows), decides each candidate by agreement on one offset, and applies the same visibility rule as every
  other strategy.
- **The coordinator** asks memory by the sound before a hearing is remembered (`_heard_before`). A song lesson names
  the earlier hearings it recalled (`_name_what_was_heard_before`).
- **`MemoryInjector.inject_memories(heard=...)`** injects the same sound's memories first, whatever the policy decides
  about the words.

**The cut** is the one measured for songs (SONGS-01): at least 10 agreeing landmarks, and at least 0.1 of those heard
while the remembered sound would have been sounding. Over 100 taught GTZAN clips and 300 others, true matches were at
least 0.30 and chance at most 0.029.

**Properties checked:** A kept (2), B recalled (6), C a room (1), D another (1), E retrieve (2), F named later (2),
G injected (1), H whose (3), I a pursuit (5).

**How a perception finds its pursuit** is the existing pursuit logic:
- The act's acting intent (`get_acting_intent`) is walked up to the pursuit at its root (`_root_intent_id`),
  whose memory it joins (`MemoryAgent.add_perception_to_pursuit`).
- A live utterance that becomes a task is the TRIGGER of the pursuit it starts
  (`handle_user_request(heard=...)`). The live senses sense it first (`sense_first`) and remember it within
  that pursuit after.
- What forms no pursuit (a question answered from what is held, a sentence not understood, the
  environment scan) is remembered as its own, as the exchange itself is.

**Before section I, 18/18** twice (`20260929T132833Z`, `20260929T132927Z`). The first showed the caption's
time as epoch seconds, which was fixed.

Run (sandbox store): `./venv_lyric/bin/python3 experiments/MEMORY-SOUND-01/experiment.py`
