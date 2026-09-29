# SHAPES-LEARN-01 — sentences taught with their meaning become patterns

**Finding (2026-09-27, run `20260927T053015Z`, 27/27): step 1 of the change map works end to end.** Nine sentences
were taught, each with what it means, through the one teaching path, in the sandbox store. Each one became a
pattern held by the three named owners:
- **memory:** one pattern memory per sentence, never merged and never read as a claim
- **beliefs:** one belief per pattern, grounded in its memory
- **domain system:** in the English domain, with the facts the meanings state held in the graph

Every taught sentence then read back to its meaning, and every meaning was said back as its sentence. Nothing
untaught read. The main store was not touched (207 rows before and after).

This is the substrate's first English that is learned rather than written into the code. It reads only what it
was taught, exactly: `this is my shoe.` (lowercase) and `My shoe is red.` do not read. Turning differences between
patterns into slots and word entries is step 2.

## The lesson

| Sentence | What it means (as taught) | Situation |
|---|---|---|
| This is my shoe. | tell: `instance_of(?shown, shoe)`, `owned_by(?shown, ?speaker)` | speaker = teacher, shown = teachers_shoe |
| My shoe is black. | tell: `has_property(?shown, black)` | same |
| It is black. | tell: `has_property(?previous, black)` | previous = teachers_shoe |
| Is the shoe red? | ask: `has_property(?shown, red)` | same |
| What color is the shoe? | ask for `?c`: `has_property(?shown, ?c)`, `instance_of(?c, color)` | same |
| Tie your shoe. | request: `instance_of(?e, tying)`, `done_by(?e, ?listener)`, `done_to(?e, ?shown)` | shown = teachers_shoe |
| A robin is a bird. | tell: `isa(robin, bird)` | — |
| Is a robin a bird? | ask: `isa(robin, bird)` | — |
| A robin is not a mammal. | tell: not `isa(robin, mammal)` | — |

## What held

| Check | Result |
|---|---|
| Patterns learned | 9/9, none refused |
| Meaning facts | 6 bound by the situation and taught as facts; 7 asked or requested, so none held |
| A fact said twice in the lesson ("My shoe is black." / "It is black.") | held once: 5 admitted, 1 already |
| Memory | 9 pattern memories, 9 distinct keys, none merged, none read as a claim |
| Beliefs | 9, each grounded in its pattern's memory, each in the English domain, persisted |
| Domain | `english` exists |
| Facts in the graph | `teachers_shoe` instance of shoe, owned by teacher, has property black; `robin isa bird`; `robin isa mammal` held as a **denial** |
| Held from a question or request | nothing |
| Ledger | 9 patterns recorded `new` |
| Read and say | 9/9 read to their meaning; 9/9 said back; 4/4 untaught sentences read to nothing |
| A fresh warm from memory alone | reads all 9 |
| Same lesson, same source | 0 learned, 9 already; no belief moved; still 9 memories |
| Same lesson, another source | each belief observed once more (1 → 2); 9 ledger `updated` |
| Reasoner | "Is a robin a bird?" with the premise "A robin is a bird." formalizes to `robin_bird`, no model; an untaught question is declined |
| Main store | 207 rows before, 207 after |

## The domain rework (2026-09-27, run `20260927T060256Z`, 33/33)

The domain system keeps no knowledge of its own; it is judgments over memory. The run now starts the
substrate itself (so every admission is announced to a live coordinator) and adds these checks:

| Check | Result |
|---|---|
| The substrate is running; every admission reached it | 0 unannounced |
| English is judged by its patterns | maturity 0.4383 = `coverage_from_counts(9 patterns, 13 facts in their meanings, 6 kinds)` |
| The lesson's domain is judged by what it now holds | 0.2936 (registered at 0.1) |
| No domain record stores a copy of what it holds | `shapes_learn_01`, `english`: no concepts, relations, knowledge or vocabulary in the record |
| The thinnest knowledge is what proactive research would go after | the lesson's 7 concepts are among the 15 topics |

The first run with these checks failed the last one: the lesson's concepts sat in a twin domain
(`domain_shapes_learn_01`, 7 concepts) beside the learned `shapes_learn_01` (0), so the sparsity map found nothing.
Fixed in `domain_registry.py` (`domain_for_field`, `_absorb_field_twin`); the environment domain had the same twin.

**Two checks pass but must change with the separation** (`docs/research/SEPARATION_MAP.md`):
- The research topics this check accepts include the host's own details (`0 arm64`, file names from the boot scan)
  and an image's width and height. Research sends its topics out.
- "The told facts are held" accepts facts about the speaker (`teachers_shoe owned_by teacher`) as the substrate's own
  knowledge. They belong to the speaker's context.

## Facts about the situation go to the speaker's context (2026-09-27, run `20260927T172201Z`, 35/35)

The second of those is changed. Whose a fact is, the meaning says:
- **The speaker's context.** A fact that names the speaker, the listener, what was shown or what was mentioned
  before is about the situation it was said in. The three facts about the teacher's shoe are the teacher's.
- **The model.** A fact naming none of these is general. "A robin is a bird." and "a robin is not a mammal" go
  there.
- **Nobody's.** "It is black." binds only `?previous`, in a situation that names no speaker, so its fact is not
  held.

| Check | Result |
|---|---|
| Meaning facts | `bound` 2 (the model's), `speaker_context` 3, `no_speaker` 1, `open` 0, `not_told` 7 |
| Taught | 5 admitted, each once, where it belongs |
| The model's graph | holds the two robin facts, and nothing about the teacher's shoe |
| The teacher's context | holds the three facts about the teacher's shoe, and nothing else is in any person's context |

The first item (the host's details as research topics) is still open in development. A frozen release does no
research.

## The trap in measuring it

The run happens in the sandbox (`lyric_dev`), emptied first by `scripts/reset_dev_store.py`, so every run
starts from nothing. The same lesson taught into a store that already held it would count "already", not
"learned". The check that the main store is untouched counts its rows over a separate connection. A teaching
record's own knowledge (the lesson facts) and its language knowledge (the patterns) are checked separately,
because they go to different owners: the facts to the lesson's domain, the patterns to English.

## Run

```
./venv_lyric/bin/python3 experiments/SHAPES-LEARN-01/experiment.py
```
It empties `lyric_dev` first, starts the substrate there, teaches, waits for the domain judgments (up to 120 s),
checks, and shuts the substrate down. It never writes to `lyric_db`.

**Step 3 (2026-09-29, run `20260929T013752Z`, 36/36).** "this is my shoe." (lowercase) now reads loosely, by
design: heard speech and chat arrive without capitals. The reading says it was loose. The teaching report counts two
more buckets: conditionals held as rules, and examples.
