# CANARY-01: what a person gives the substrate stays in that person's context

Part 1 of M2 (`docs/research/MEMORY_AGENT_MAP.md` §8.2, M2a), extended for M2b-1 and M2b-2 (§9). Unique markers are
planted in what one person gives the substrate through its real doors, and in a note of the substrate's own. After the
work, every table of the substrate's memory is searched for the markers. The harness never says whose work anything
is: each door gets only what a real caller would give it.

## What it checks

| Part | Check |
|---|---|
| A. Lesson | The substrate's own lesson, through the learning authority: a robin is a bird, a bird is an animal. |
| B. Tell | Through the front door, the person tells it that a *marker* is a robin. |
| C. Ask | Through the front door, the person asks whether a *marker* is an animal. This is answered by reasoning over their fact and the lesson, through the neural bridge. They also ask what a second *marker* is, which nothing held can place, so it is looked up. |
| D. Task | Through the front door, the person gives it a job: read their note, which holds a marker. The job runs to its end on the task loop. |
| E. Image | The person's image, carrying a marker in a QR code, is seen through `see`, given their identity. While it is in view they give a second job, so a memory of theirs forms in the window a memory is stamped in. |
| F. Own | A note of the substrate's own. |
| G. Memories | Every memory row holding the person's markers is theirs, the memory `see` made of their image is theirs (read by the id the percept carries back), and the substrate's note is its own. A stored image (`unified.memory_media`) belongs to its memory, so its owner is the memory's. Every memory is stamped only with what its own owner was perceiving, and theirs, formed while their image was in view, carries it. Which paths kept anything is reported, so a path that kept nothing is not mistaken for one that kept it safely. |
| H. The rest | Every other table of memory. Where a table records an owner, the person's marker is under them. Tables with no owner column that hold a marker are reported (M2b-3 gives them owners). Nothing of the person's image is in a table of the substrate's own, and what it showed is held in their context. |
| J. Pool | Each experience waits in the pool in its owner's store, decided by the memory agent. See below. |
| I. Main | The main store is untouched. |

What J checks:

| Experience | Check |
|---|---|
| The person's job (M2b-1) | theirs, holding their marker; decided a candidate; holds the substrate's steps and tool runs apart from their parts |
| A job of the substrate's own (M2b-1) | its own |
| The person's telling and question (M2b-2) | theirs, their words in their parts; how the substrate took each is its own part |
| The reasoning over their fact (M2b-2) | theirs; their fact is their premise; the lesson's premises are the substrate's and hold nothing of theirs |
| The look-up of their word (M2b-2) | theirs; the word is their part, the query it sent out is its own, what came back is the world's |
| The seeing of their image (M2b-2) | theirs, holding what was seen in it (the QR marker) as their part |
| Every one of the person's items (M2b-2) | decided, with a reason |
| A question of the substrate's own (M2b-2) | put on the task queue as its own loops do; its look-up and its turn are its own |
| Recall | the substrate's own recall finds nothing of the person's job, fact, question, word or image |

## Harness changes, and why

- **M2b-1:** J added (the pool).
- **M2b-2:**
  - C asks about a word nothing holds, so the look-up path runs; before this, no part of the canary reached research.
  - E's image carries its marker in a QR code, which the vision faculty decodes into what it saw. An image named with
    a marker never put the marker anywhere, so the image checks could not find anything to judge.
  - G reads a stored image's owner through its memory (`unified.memory_media` has no owner column; its rows are parts
    of a memory). Only that table: a row that merely points at a memory, such as a belief about it, is read where it
    sits, so a leak there is not hidden.
  - G and H search for the two new markers too.
  - J gains the checks above.
- **M2b-3, the image fix:**
  - while the image is in view the person gives a second job: their follow-up question had merged into an earlier
    memory of theirs, and a merged memory is not re-stamped, so no new memory of theirs formed in the window;
  - G checks every perceptual stamp against its memory's owner, and that theirs carries their image;
  - H checks that nothing of the image is in a table of the substrate's own, and that it is in their context;
  - "the memory `see` made of their image" is read by the id the percept carries back. It was found by time and
    tag, and the environment scan, which sees images again, forms the substrate's own vision memory at the same
    time.

## Before part 1 (`20260927T230245Z`, 10/12)

- **Leaked:** the memory `see` made of the person's image was filed as the substrate's. `see` took no identity.
- **Owner-less tables holding the person's claim:** `reasoning_arg_claims` and `reasoning_arguments`.
- **Already the person's:**
  - their fact and question (the exchange memories, the reasoning bridge's memory, their scoped facts);
  - their job's outcome record.
- **Wrote nothing:** the task-end record of what the job found and the tools it used (`capture_task_outcome`). It
  reads fields no task result carries.

What the first runs taught the harness:
- A question about an unknown word takes a web look-up path that never reasons.
- An image named with a marker never puts the marker in memory.
- A job whose result has no summary never reaches the task-end record.

Each was replaced by a path that does run, so no check passes for want of anything written.

## Runs

| Run | Result | For |
|---|---|---|
| `20260927T225730Z` | 7/9 | first run, before the harness was rebuilt around paths that run |
| `20260927T230245Z` | 10/12 | before part 1 |
| `20260927T233433Z`, `20260927T234542Z` | 12/12 | M2a |
| `20260928T001000Z` | 18/18 | M2b-1 |
| `20260928T005213Z`, `20260928T010444Z` | 31/32 | M2b-2. Every pool check passes. The failure is the first image the canary could trace: the QR marker from the person's image was in 131 of the substrate's own memories and in its own knowledge (see below) |
| `20260928T014624Z`, `20260928T021238Z` | 39/39 | M2b-3, the image fix |

## What the image marker found (M2b-2)

The code in the person's image reached the substrate's own memory and knowledge by two routes, both older than M2b-2:
- **The memory agent stamps recent perceptions on every memory it writes, whoever's the memory is.** Each
  perception from the last 120 seconds is attached whole to `thinking_state.perceptual_state`. The person's image
  was stamped on 131 of the substrate's own memories.
- **`see` admits a person's image as the substrate's own knowledge.** It went into `unified.concepts`,
  `concept_relations`, `concept_aliases`, `concept_domains`, `concept_evidence`, `evidence_envelopes`, `beliefs` and
  `perceptions`, with no owner.

Both are M2b-3 (perceptions by owner), in `docs/research/MEMORY_AGENT_MAP.md` §9.5. Fixed in §9.6: nothing of the
person's image is in the substrate's own memory or knowledge, and it is held in their context.

## Run

```
./venv_torin/bin/python3 experiments/CANARY-01/experiment.py
```

It empties the sandbox first (`scripts/reset_dev_store.py`) and starts the substrate.
