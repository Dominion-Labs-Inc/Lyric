# TEACH-AND-DO-01 — a small lesson, then real work on what was taught

**Finding (2026-09-26): 17/18.** The one failure is a declared `run_python`, which Law 2 refuses.
Before the store is wiped and the main model is taught on corrected data, this checks that the system works
as one. A six-fact lesson and one conditional go in through the one teaching path. The substrate is then
asked to use them:
- answer from the lesson;
- look up what it lacks on the web;
- read a document;
- write down what it knows;
- run code.

Every store learning should touch is measured before and after.

| | |
|---|---|
| **A** | Teach: 6 pump facts + "if the valve is closed then the pump is overheating", through `TeachingPass`. A first teach must write memories, edges, beliefs and ledger rows. A re-teach of the kept lesson must write nothing new and be ledgered `unchanged`. |
| **B** | Ask back through the front door: "Is a centrifugal pump a machine?", which chains centrifugal pump → pump → machine. |
| **C** | Web: "What is a peristaltic pump?" is not taught, so it is looked up and read. What was read is world knowledge, with the page as its source; none of it is filed as the asker's context. The finding is removed before and after each run, so every run meets the gap. |
| **D** | Documents: a maintenance note on disk. Asked in plain words (observed only), and with `read_file` declared (scored). Then a planned goal: "Create a written summary of what you know about centrifugal pumps at `<path>`". |
| **E** | Code: asked in plain words (observed only), and with `run_python` declared (scored). |
| **F** | Which stores moved, the ledger by cause, tool runs, the asker's scoped context, the taught domain, consolidation. |

Plain-words requests are observed, not scored: how the model-free substrate handles free text is what this
experiment is for finding out. The lesson is kept for the wipe and re-teach; scratch files, and what the
run's fixture user learned, are removed.

## What the first runs found, and what was fixed

The first run scored **11/17**. Each failure was traced to its cause before anything was changed:

| failure | cause | fix |
|---|---|---|
| the run stopped before teaching anything | teaching read one `quality` off the source for all its word classes. ConceptNet declares none, so any ConceptNet pass that states classes would also crash | each class carries the quality of the record that stated it (`teaching.py`) |
| "Read the maintenance note." with `read_file` declared was answered from memory ("A maintenance is a wrongdoing") | the reader read the command as a statement: subject *Read*, verb *the*. A word known only as a determiner (or preposition, pronoun…) fell through to the "never seen" case | a word observed in any class other than verb is never the verb (`sentence_reader._reads_as_verb`) |
| "What is a peristaltic pump?" looked up `peristaltic` alone and found nothing | a word left unresolved before a held noun was looked up on its own | a modifier directly before a held noun forms the unknown name `peristaltic pump`; the head is not asked about ("which pump do you mean?") |
| "Which pump do you mean — the one in general, or in general?" | a narrower concept (`centrifugal pump`, a specialization of `pump`) was counted as another meaning of the word | only same-name concepts are alternatives |
| the exchange was remembered as "answered from held knowledge", then recited back as "I remember: Asked: …" | any held word made the turn "answered"; recall offered the front door's own exchange record as knowledge | answered only when nothing asked about is unaccounted for; exchange records are not recalled as knowledge |
| the web search left no tool-run record | tool runs were recorded by the coordinator's `_run_tool` only. The registry wrote a second table (`tool_execution_events`) that nothing reads, so any other caller's runs (the conversation, reading steps, observations) never reached tool learning | the registry records every run once into `tool_usage_history`, attributed to the acting task (`set_acting_task`); the unread duplicate write is removed |
| the planned summary: validation ran before creation, a "Plan creation process" step always failed, nothing was written | steps inside a planner stage were not chained; that step had no handler; "what you know about X" named no subject, so nothing gathered what to write | stage steps run in order; the unhandled step is removed; "about X" / "a summary of X" name the subject, and a creation with a subject gathers it first |
| "Use Python to…" reported only "completion belief 0.01 < acceptance 0.96" | validation replaced the executor's own reason | the executor's reason comes first |

The second and third runs uncovered what the first failures had hidden:

| failure | cause | fix |
|---|---|---|
| re-teaching the kept lesson reported 6 `admitted` and ledgered 6 `new`, while no edge or belief changed | the ingress's "already held from this source" lived only in the process (`_seen`), so after a restart, or on another instance, a held fact reinforced its concepts again and moved its belief a second time. The bulk path also ledgered any admission as `new` | the ingress checks whether an edge from this exact evidence is in the graph (new index `ix_cr_evidence`); one ledger rule for both paths (`_ledger_disposition`) |
| the planned goal's gathering step learned "centrifugal pumps is a boiler feed application" from the web | resolution looked up the raw words, but every name is written through `normalize_term`, so the plural never met the taught `centrifugal_pump` and was researched instead | `resolve_query` reads a name the way it was written. The wrong fact was removed by id (snapshot `data/snapshots/wrong_web_fact_centrifugal_pump_20260926.json`) |
| the Wikipedia lead "A peristaltic pump, also commonly known as a roller pump, is a type of positive displacement pump used for …" read nothing | "a type of Y" used two of the complement's four words; "used for …" made it unbounded; fetched text puts a space before commas | a classifier ("type/kind/sort/variety/class/species of") names a Y; a participle + preposition after the noun only narrows it; space before punctuation is closed up |
| a declared `read_file` that succeeded failed completion (0.72 < 0.95) | completion needs a second, independent observation, and only changes of the world were re-observed | a whole-file reading is confirmed by the coordinator reading the file again |

The regression batch after those fixes found three more:

| failure | cause | fix |
|---|---|---|
| the web question made no look-up on a later run | two earlier runs' fixture users had each looked up the same page; the second counted the first as an INDEPENDENT holder, and the finding was promoted into the shared mind. Promotion counts actors, not independent sources | the finding removed (snapshot `teach_and_do_web_residue_20260926.json`); each run removes its user's context and memories at the end. Whether one source read by two people is corroboration is still to be decided |
| (seen while tracing it) the front door stored every user's exchange record with no owner, and `close_open` searched with none | one speaker's answer could close, and rewrite, another speaker's open question | the record is the asker's; only the asker's own open episode is closed (`PostgresStorage.owned_by`) |
| (DOM-KG-01, from this run's fix) an edge left behind by a deleted concept read as "already held" | experiment scrubs delete concepts and keep their edges (371 in the store) | "already held" requires the edge's concept to exist |

A fact read from the web is not the asker's to keep: it is a learned fact.
That round found:

| failure | cause | fix |
|---|---|---|
| the web finding was filed in the asker's context | the look-up admitted what it read through the same call as a telling, under the speaker's actor. So a page the substrate found and read itself was treated as something the person said, and reached the shared mind only when a second person asked the same question | what the look-up reads is learned under the substrate's own account, with the page as its source (`_research_phrase` → `_ingest(actor=SUBSTRATE_ACTOR)`); only what a person tells stays theirs |
| on the next run the look-up found nothing | every result title arrived glued ("Peristalticpump- Wikipedia"), so no page matched the phrase. `ddgs` 9.12 stripped each HTML text node before joining them, dropping the space between highlighted words; which of its backends answered decided whether a run passed | `ddgs` upgraded to 9.16, which joins the nodes and then normalises spaces; pinned in `requirements.txt` |
| `validate_path` failed every observation run | it, `validate_sql_input` and `check_rate_limit` imported the archived `core.security.system_security`; and `security_tools` registered a second `validate_path` over the filesystem one | one `validate_path` (traversal, encoded or not, and containment after symlinks resolve); the SQL check reads the value as SQL; the rate limit is counted in the store |

**Now:** A 7/7; B 1/1; C 4/4 (looked up; read "peristaltic pump is a positive displacement pump"; in the
shared graph with the Wikipedia page as its evidence; nothing in the asker's context); D 3/3 (declared read
completes; the plan runs gather → analyse → write → validate and writes the file); E 0/1; F 2/2.
`validate_path` ran 2/2 during observation (0/2 before).

## Open

- **Declared `run_python` is refused by Law 2**: "no account of why". The executor's declared-tool path
  (a user's, or a deployed agent's, named tool plan) can never run a tool that changes anything, because
  "someone asked" is an account (`CARRY_OUT`) only for writing a planned artefact. This is a decision about
  the constitution, still to be made.
- **Plain words that ask for action** ("Read the note at … and tell me what is wrong", "Use Python to
  compute …") have no model-free route to a tool, and the substrate says so. That is the honest gap, and the
  failure report says it too. It is still validated once more and retried once, which cannot change it.
- **The written summary is thin.** It holds what "what is X?" answers ("A centrifugal pump is a pump"), not
  the facts that point at X ("an impeller is part of a centrifugal pump"), and it is the reply's own voice
  ("I remember: …").
- **Watching an act runs every read-only tool that takes a path, twice.** On one markdown file that was
  about 20 tools, security scanners included. Those runs are recorded now, attributed as observations.
  `validate_path` is among them and now runs; given a path that climbs out of the boundary, the
  constitution blocks the call as a traversal attack (Law 5) before the tool can give its verdict.
- **Competence in the taught domain stays at 0.5**; teaching facts does not move it.
- **Promotion to the shared mind counts people, not sources.** A web finding no longer goes through it.
  A TOLD fact still promotes when one other actor told the same, and every anonymous session counts as a
  person.

## Run

```
./venv_torin/bin/python3 experiments/TEACH-AND-DO-01/experiment.py
```

Boots the whole system, alone (its store deltas assume nothing else is writing). Each run writes
`results/<UTC timestamp>.json` with a `.md` beside it.
