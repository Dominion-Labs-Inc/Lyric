# RESEARCH-WRITE-01 — given a goal in words, does it research, write, and verify?

**What it tests.** The live substrate is given a goal in words and nothing else: research a topic and write
a summary of what it learned to a file it names. No tool is named and no path is wired. Completion is judged
by re-reading the world, not by the tool's own report.

What it touches, all of it live:
- **the goal** is set the way the substrate sets its own (`set_goal`): formed as its intent, with how much it
  matters on the intent's shape, and queued as work;
- **the queue** hands it out, the one dispatcher;
- **its pursuit** (`_pursue_described_goal`) decomposes it into the work it names (`plan_described_goal`,
  in the execution plan adapter), records the steps on the goal's intent, and walks them through
  `execute_task`, handing what the research found to the step that writes it up;
- **the knowledge loop** (`understand`) does the research;
- **the declared file** is written, then read back, and Law 2's CARRY_OUT account for the write is checked
  against the pursuit being walked and the goal's own words;
- **completion** closes the goal's intent with how it ended.

Nothing here writes the file on the substrate's behalf. If it does not write it, that is the result.

| Section | What it establishes |
|---|---|
| A | the goal is taken on, and is its intent |
| B | it is queued as work, and the live loop runs it to an ending |
| C | its pursuit decomposed it into steps recorded on the intent, and every step ran |
| D | it can answer about the topic, and the knowledge stores moved or it already knew |
| E | the file exists, is not empty, and is about the topic |
| F | the substrate read the file back, and the act left experience behind |
| G | the goal's intent is concluded, not left `active` |

**Until 2026-10-22** the goal went to a planning engine (`create_goal`, `generate_plan`), and this experiment
drove the engine's dispatcher (`get_next_tasks`) by hand, since nothing in Lyric called it. The engine was
dissolved into the owners of its parts; the goal now goes through the door for Lyric's own goals, and nothing
is driven by hand.

**Run** (from the Lyric folder; boots the full system on `lyric_dev`):

```
./venv_lyric/bin/python3 experiments/RESEARCH-WRITE-01/experiment.py
```

**Results.** Each run writes `results/<UTC timestamp>.json` with a `.md` beside it.
- 2026-09-26: 13/13, through the planning engine.
- 2026-10-22, through `set_goal`, twice on `lyric_dev`: A and B pass (the goal is taken on as its intent, queued,
  handed out, and its pursuit begins walking the steps it decomposed), then the research step does not end. The
  knowledge loop looked the topic up and the reader stays at full CPU classifying the page it read
  (`Conversation.look_up` → `_research_phrase` → `derived_reader.read_text` → `_analyses` → `_slot_fillings` /
  `_phrase_fillings`, read from a stack dump), which blocks the event loop. That is the reader's search explosion
  (every sense and grouping built, then most discarded), whose fix, a packed chart, is its own work. Both runs were
  stopped and their goals cancelled; no record was written. The rest of a goal in words (the write-up, the
  CARRY_OUT account, the read-back, the closed intent) is measured where its research is answered from what is held:
  TEACH-AND-DO-01.
- 2026-10-23 (`20261023T124829Z`, `lyric_dev`, the reader of SPLITS-01): 8/15. The research step ends. The search's
  top hit arrives with the whole of Wikipedia's Photosynthesis article (90,289 characters, 792 blocks), whose first
  sentence ("Photosynthesis [ note 1 ] is a system of biological processes ...") reads to no kind, so every block is
  read: the event loop was held from 08:59:08 to 09:08:58 (9 min 50 s; the article alone, read the same way outside
  the substrate, 564 s, one paragraph 302 s of it). Nothing was found that says what photosynthesis is, so nothing
  was learned, the file was never written, and the goal's intent was closed as abandoned (G passes). What fails now
  is what the reader understands of the page, and that a page is read whole inside the event loop; no longer that it
  never ends.
