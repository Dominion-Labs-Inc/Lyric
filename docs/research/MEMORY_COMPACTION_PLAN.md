# Compacting what the substrate keeps

**Status (2026-09-30):** planned, to be tried in the sandbox (`lyric_dev`) first. The main model (`lyric_db`) is
changed only after the sandbox experiments pass, and only with the owner's approval.

## What takes the space (measured 2026-09-30)

| | Sandbox | Main |
|---|---:|---:|
| Whole database | 1.0 GB | 0.5 GB |
| Memories (`memory_hot`) | 90,759 rows, 863 MB | 8,382 rows, 197 MB |
| The record kept in each memory (`thinking_state`) | 226 MB | 130 MB |
| Embeddings (column + search index) | 140 + 185 MB | 13 + 16 MB |
| How each memory was admitted (`memory_admission`) | 115 MB | 5 MB |
| The mood when it formed (`appraisal_snapshot`) | 63 MB | 0.2 MB |
| Evidence text (`evidence_envelopes`) | 2.2 MB | 4.1 MB |
| Change log (`knowledge_updates`) | 9 MB | 19 MB |
| Beliefs | 18 MB | 60 MB |
| Facts (`concept_relations`) | 3 MB | 31 MB |

**Where the bulk is:**
- **Copies of the substrate's state inside every memory.** Each memory keeps a copy of what was being perceived,
  a summary of beliefs, the mood, and how it was admitted, all as they stood when it formed. Memories formed in the
  same moment hold identical copies. In main, one admitted fact's memory is 201 KB, and 190 KB of that is eight
  perceptions.
- **The admission decision is kept twice** in each memory: in `memory_admission`, and again inside `thinking_state`.
- **Embeddings:** 384 numbers at full precision, plus a search index about as large again, on every memory,
  including 75,833 word-class memories in the sandbox.

The evidence text and the change log are small today.

## What is kept, and what is not changed

- **Recall stays whole.** A memory still recalls what was perceived, believed and felt when it formed (the memory
  agent attaches that on purpose). The state is **stored once and pointed to**, not dropped.
- **No memory is folded into another.** The memory agent keeps two alike memories as two ("merging them wiped
  one"), so folding similar memories is not part of this plan.
- **Beliefs stay as they are.** They already keep only a probability and counts for and against. Their `evidence`
  column is empty in every row of both stores, and is removed.
- **Every learned item stays its own item**, traceable to its sources.

## The steps, in order

| Step | Change | Information lost | Experiment |
|---|---|---|---|
| 1 | State at storage kept **once per moment**, pointed to by each memory. The admission decision kept once. | None | COMPACT-01 |
| 2 | Empty `beliefs.evidence` column removed | None (always empty) | within COMPACT-01 |
| 3 | Embeddings stored at half precision (`halfvec`, 768 B instead of 1,536 B). Column and index both halve. | Rounding only; recall compared before and after | COMPACT-02 |
| 4 | Embeddings only on memories that are found by resemblance. Word-class and pattern memories are found by their words, if the audit confirms it. | None, if nothing finds them by resemblance | COMPACT-02 |
| 5 | Evidence text, once learned from, moved to a compressed archive. Its tag stays: id, source, kind, what it was derived from, when. | None live; text read back from the archive | COMPACT-03 |
| 6 | Change log: recent entries kept whole, older ones summarized | Old entries' detail, summarized | COMPACT-04 |
| 7 | Facts as number ids and a score (about 150 B each) | None | later, after 1 to 6 |

## How each is tried

1. **Built so that a store is compacted by one explicit pass** that the memory agent performs, the only writer of
   memory. New memories are written compact from then on.
2. **The pass is run on the sandbox only.**
3. **Each step's experiment:**
   - measures the bytes before and after;
   - checks that what the substrate recalls, reads, believes and answers is the same after as before.
4. **Then the compacted sandbox goes through the standing checks:**
   - the taught-sentence and probe checks;
   - a teaching pass after compaction;
   - READ-01, MEMORY-SOUND-01, MEMORY-SIGHT-01, WORK-TALK-01, MESSAGE-01, TASKS-AT-ONCE-01.
5. **Main follows** only with the owner's approval.

**While the sandbox is compacted and main is not:** the code is shared by both stores. A store records which layout
it holds. The substrate refuses to start on a store still in the old layout, and names the pass to run. It never
writes the two layouts into one store.
