# SYSTEM-MEMORY-01 — the memory faculty, and whose memory it is

**Finding (2026-09-26): behaviour 18/18; ten wiring findings.** One memory authority (`MemoryAgent`). A
memory is stored, found by content and by id, superseded keeping what it used to say, and cannot be deleted
without the token governance requires.

**The memory store did not keep users apart.** All 156,178 hot memories carried no owner. The storage layer
had an owner rule, but only the semantic search applied it — and only ever as the substrate, since no reader
passed an owner — while the keyword and tag searches read every row. So what was concluded from one speaker's
private context (a reasoning record, the learning summary of it, an unread sentence they told) became shared
memory, and another speaker's recall could hand it back as a premise (measured in SYSTEM-CONVERSATION-01).
Now one rule (`PostgresStorage._actor_predicate`) governs every strategy: a user sees their own memories and
the substrate's, never another user's; the substrate sees only its own. Deduplication matches only within
the writer's own memories — merging a user's memory INTO a shared one would write their content into it.

**Merging was broken twice.** The merge wrote `embeddings`, a key `update_memory` silently ignored, so every
merged memory kept the embedding of its first text; when `update_memory` began refusing unknown keys, every
merge failed and each near-duplicate was stored beside its original instead (21 exact duplicates in the 14
hours before the fix). It now writes `embedding`, and the merged reasoning trace has a write path.

**What it checks.**

| | |
|---|---|
| **A** | one authority, one construction site |
| **B** | stored, found by content, read back by id; an unknown id is None |
| **C** | superseded: the content changes and what it said is kept |
| **D** | a delete without a valid token is refused |
| **E** | a user's memory is found by its owner and by no other user and not by the substrate — by meaning, by wording and by tag; the same words from the substrate are a separate memory; the same words from the same user merge into theirs |

**Wiring findings (called by nothing in `core/`):** `bulk_import`, `get_memory_by_content`, `claim_tags`,
`increment_access_count`, `update_importance`, `update_tags`, `add_related_memory`, `retrieve_from_archive`,
`cleanup_cache`, `form_abstractions`.

**The trap in measuring it.** A merge that fails does not raise: `store_memory` logs "merge failed" and stores
a new memory, so the only visible symptom is a second id. And ownership has to be checked per strategy —
the semantic search passing proves nothing about the keyword search.

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-MEMORY-01/experiment.py
```

Every memory it writes is removed by id. Each run writes `results/<UTC timestamp>.json` with a `.md` beside it,
reporting **behaviour** (pass/fail), **wiring** and **completeness** findings apart (`experiments/_isolation.py`).
