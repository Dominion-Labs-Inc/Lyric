# SENSES-TOGETHER-01 — the substrate hears, sees and reasons at the same time

**Finding (2026-09-28).** Hearing and sight stay first-class parts of the substrate, with one
faculty, one perception pipeline and one memory. Each now does its measuring in a process of its
own (`core/perception/senses.py`), so the running substrate hears a real recording, sees a real
video frame and answers a question by reasoning, in every combination, at the same time.
Every result was right, and each memory held its own sound or picture.

**Before**, measured on the same stimuli: sight held the substrate's loop for **1.4 s** at a
stretch. A question answered in 0.3 s waited 1.4 s behind a picture.

**After** (record `20260928T183109Z`):

| run | hear | see | reason | loop held at most |
|---|---|---|---|---|
| alone | 1.32 s | 2.52 s | 0.34 s | — |
| hear + reason | overlapped | — | **0.28 s** | 116 ms |
| see + reason | — | overlapped | **0.27 s** | 33 ms |
| hear + see | overlapped | overlapped | — | 23 ms |
| all three | overlapped | overlapped | **0.27 s** | 21 ms |

Reasoning is no longer queued behind perceiving.

**Third run, after the other session's reader switch landed: 16/16** (record `20260929T112247Z`).
- The chained question was answered: "Yes, vexkrvexy is an animal."
- Reasoning took 0.12–0.14 s beside a perception and 0.15 s alone.
- In the runs together, the loop was held at most **30 ms**. Hearing alone held it 93 ms,
  under the limit but near it: the database-layer stalls described below still vary from run
  to run.

**Second run (after the pid-named death reports, the failure-record cleanup and the import-cycle
fixes): 12/16.**
- Every senses check passed. The loop was held at most **31 ms**: the database-layer stalls vary
  from run to run.
- A killed sense was reported by its pid, and its failure record was cleaned up.
- The four failures are one reasoning answer, from the other session's reader switch, which was
  part-way on disk in `neural_bridge.py`. "Is a vex‹nonce› an animal" now replies "I remember: a
  mammal is an animal … A vex… is a mammal." instead of chaining them into a yes. Reported to
  that session; to re-run once the switch lands, with `english_01` taught.

**First run: 15/16. The one failure is reported, not adjusted.** The threshold was fixed before the first
run: the loop is never held more than 100 ms. It was held up to 116 ms. What held it is not the
senses. A watchdog sampled the main thread during every stall, and found the database layer:
- new connections doing their SCRAM password handshake in Python (`hmac`, inside `_acquire` /
  `_register_connection_codecs`);
- JSON-decoding memory rows in `search_memories`.

Those stalls happen whether or not anything is perceived. Removing them is separate work.

**Properties checked:**

| # | property |
|---|---|
| A | alone: a recording is heard, a video frame is seen, a question needing a chain of reasoning is answered |
| B | hear + reason, see + reason, hear + see, all three: every result right, each memory its own (its own caption, its own kind of thing kept); reasoning within 3x its time alone and finished before the perceiving beside it; loop never held over 100 ms (**failed: 116 ms, database layer**) |
| C | sight and hearing each measure in a process of their own |
| D | a sense process killed while perceiving is started again and the perception completes; its death is reported, naming the process; one that died while idle does not cost the next perception |
| E | the senses' processes stop with the substrate |

**Found and fixed while building it.** Each fix is at the root, and each has a check here or in
the tests.
- **A multiprocessing worker re-ran the caller's script.** Both `spawn` and `forkserver` send the
  parent's main path to the child. Every experiment without a `__main__` guard started itself
  again inside the sense and killed it. The senses are now **programs of their own**
  (`python -m core.perception.senses <sense>`), talking over pipes.
- **`core/__init__.py` imported the substrate on any import.** It pulled in 127 modules and took
  5.6 s, through try/except-ImportError fallbacks of package-level names that nothing used. It is
  now a docstring; a sense's process loads the six perception modules in 0.28 s.
- **Removing it exposed two hidden circular imports**, each closed by dead code:
  - unused aliases `AGILearningEngine` / `AGIMemory` in `abstract_reasoning_engine.py`;
  - an unused `Connectivity` import in `sentence_reader.py`.
- **A sense that died while idle failed the next perception.** Its death is only noticed some
  time later. A process found dead is now started again, and the perception given to it once.
  A perception that kills it twice fails, naming the sense.
- **`speech.hear` collided with the `hear` door** in `test_memory_writers`' scan. It is renamed
  `speech.recognise`: it recognises speech, and hands nothing to memory.

Stimuli: the JFK inaugural sample and frames of the repo's real jellyfish footage. The question
chains a told fact ("a vex‹nonce› is a mammal") through a held one ("a mammal is an animal").

Run (sandbox store): `./venv_torin/bin/python3 experiments/SENSES-TOGETHER-01/experiment.py`
