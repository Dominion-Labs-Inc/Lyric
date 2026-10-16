# MAIN-ENGLISH-01: the main model after the English lessons, read only

**Why.** `docs/research/ENGLISH_CURRICULUM.md` teaches each phase whole on main, then measures main read only before
the next phase. The main store was emptied on 2026-10-04 (22:10Z, no backup, at the owner's word). On 2026-10-05
english_01–31 were taught into it through the one teaching path (`scripts/teach.py --source lesson`, one lesson per
run, in order; log `data/teaching_runs/main_english_01_31.log`). Each lesson had passed in the sandbox first:
english_01–30 in FRESH-LESSON-01 and -03, english_31 in QUESTION-FORMS-02.

**What it checks,** from main's own store (since the second run, for english_01–39):
- **A.** Every sentence the lessons teach is read with the meaning it was taught.
- **B.** Phase 1's never-taught sentences (ENGLISH-01's `PHASE_1`), each mark in the uses its lesson teaches with
  words the lessons have, each read as written, as on the sandbox.
- **C.** Measured: the 24 sentences FRESH-LESSON-01 to -03 wrote in shapes the lessons teach, with words no lesson
  has. Main holds none of those lessons, so their words are new names here.
- **D.** Main's rows counted before and after: the reading writes nothing to what main knows. The profiler's
  timings of the substrate's own work (`unified.performance_logs`) are kept whenever it runs, and are noted.

A sentence is taken as ENGLISH-01 takes it: one meaning, or what its utterances say together.

**Run** (reads lyric_db): `./venv_lyric/bin/python3 experiments/MAIN-ENGLISH-01/experiment.py`

**Runs:**

- **2026-10-05, first run** (`results/20261005T181301Z`): **1/3**, after english_01–31 were taught into main 17:34–18:12Z,
  none refused (31 lessons, `data/teaching_runs/main_english_01_31.log`).
  - **A, failed: 2,659 of 2,664 taught sentences read as taught.** The five read whole in two ways that tie, as on
    the sandbox (ENGLISH-01's first run), so the faults were in english_01–31's learning, not the comma lesson:
    - "Tom helped himself.", "Rex helped himself.", "The cat hurt itself.", "The dog hurt itself.": the reflexives
      were learned as names ("himself" naming Tom, and again Rex);
    - "The dog chased a cat.": english_29 wrote three "a" objects as the kind ("Rex saw a cat."), where english_22
      writes them as some one thing.
  - **B, measured: 20 of 24.** "Nella has a blicket." was read with the name as written, "Nella", where the fresh
    lessons, which taught it, hold "nella" (and the same for "Yuli" and "Talo"); main never met those names.
    "Fosks are heavy." read two ways ("fosk" or "fosks" as the name).
  - **C, failed as worded: the reading added 5 rows to `unified.performance_logs`**: the profiler's timings of
    `memory_agent.search_memories`, kept whenever the substrate runs and read back by the profiler and the health
    monitor. Nothing else moved. The check now asks that nothing main knows was written, and notes the timings.
- **After the first run:** both faults fixed (ENGLISH-01, second run). Main holds what english_01–31 taught before the
  fixes: the reflexives as names, and english_29's three objects as kinds.
- **2026-10-06: main emptied again and taught english_01–39.** Phase 1 complete on the sandbox (ENGLISH-01, eleventh
  run, 28/28), and the owner's word to teach main after it. `lyric_db` emptied at 01:36Z (68,187 rows to 0; the
  three production databases already empty; no backup), then english_01–39 taught 01:36–02:06Z, one
  `scripts/teach.py --source lesson` run each, in order: 39 lessons, every record learned, none refused
  (`data/teaching_runs/main_english_01_39.log`). Main now holds english_15, 18 and 20 marking what is not told as so.
- **2026-10-06, second run** (`results/20261006T020657Z`): **11/11.**
  - **A: 2,879 of 2,879** taught sentences read as taught.
  - **B:** every never-taught set read as written: the comma 18 of 18, the apostrophe 16 of 16, the colon and the
    semicolon 8 of 8, titles 8 of 8, parentheses and dashes 9 of 9, money and dates 12 of 12, times 7 of 7,
    quotation marks 8 of 8.
  - **C, measured: 20 of 24**, the same four as the first run: three new names held as written ("Nella"), where
    the fresh lessons hold "nella"; "Fosks are heavy." read two ways ("fosk" or "fosks" the name).
  - **D:** the reading wrote nothing main knows (52,501 rows before and after).
- **After the second run:** "Fosks are heavy." read two ways that suppose the same: as written ("?slot0 are
  ?slot1.", fosks), and with "are" read as the "is" of "?slot0 is ?slot1." and "Fosks" one thing's name. Of
  readings the listener cannot otherwise tell apart, the one that reads each word as itself is now taken
  (`meant`, last). The three names stay measured: the reading is right ("Nella" owns a blicket), and a name no
  lesson taught is held as written, where the fresh lessons named theirs "nella"; what is told of Nella is all
  read, and held, as "Nella".
- **2026-10-06, third run** (`results/20261006T022331Z`): **11/11**; A 2,879 of 2,879; B every set as written;
  **C 21 of 24** ("Fosks are heavy." read as fosks that are heavy); D nothing written (52,501 rows).
- **Counting main's rows:** `SENSE-01.main_store_rows` counted a partitioned table's rows twice, in the table and
  in its partition: the profiler's 10,211 timings were 20,422, and main's total read 72,923 where it holds 62,710
  (52,499 that main knows, 10,211 timings). Each row is now counted once (`only`). The second and third runs'
  52,501 included two rows of another partitioned table counted twice.
- **2026-10-06, fourth run** (`results/20261006T162045Z`, log `work/run.log`): **11/11**, after main was emptied
  again at 15:39Z (the teammate's word: "Empty and re-teach") and taught english_01–39 15:39–16:20Z, none refused
  (`data/teaching_runs/main_english_01_39_heard.log`), so that it holds what was heard after each word and each two
  (`docs/TEACHING.md` §12c; 835 hearing memories). A 2,879 of 2,879; B every set as written; C 21 of 24 (the three
  new names held as written, as in the second run); D nothing written (53,318 rows).
