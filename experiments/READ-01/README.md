# READ-01: reading is the substrate's own sense, and one moment is one experience

Perception was rebuilt on 2026-09-30. Sight, hearing and reading are the substrate's own senses. Before, a
document was "sight's": it was read in sight's process, came in through the `see` door, and was stored as a
percept whose words nothing ever read. Each sense now takes in what it can, at the same time, in one act
(`coord.perceive_moment`). `see`, `hear`, `read` and `take_in` are its doors. This experiment shows the reading
half of that on the real substrate.

**What it checks**, in the sandbox (`lyric_dev`), which it does not empty:

| | |
|---|---|
| A | A text file is taken in by reading alone. Its lines go to the substrate's one reader (`derived_reader.stated`), and each fact is kept with the line it was read from. |
| B | The reading is remembered, keeping only the runs of words it is known again by (never the file), and the reading ledger records the file as read now. |
| C | What the substrate's own document says is in the shared graph as what it said, held at the learning door's floor, and the document `mentions` what it is about. |
| D | A person's document is theirs: its memory is in their store, what it says goes to their context, and nothing of it reaches the shared graph. |
| E | The same text read again is known as the same text. A new version is known as that text, changed. A different text is not known. |
| F | A Word file and a file with no extension are read by what their bytes are. |
| G | `see` refuses a text and names `read`; `read` refuses a picture and names `see`. |
| H | A text and a picture met at one moment are one memory, keeping a text trace and a sight trace. |
| J | A file a person's task opens through its tool (`read_file`) is read by the substrate's own reading: the reading is their memory, what it says is in their context, and the reading ledger holds it. |
| I | The main model's store is untouched. |

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/READ-01/experiment.py
```

It deletes every memory it forms, by id. It leaves two things in the sandbox, both named by the run's nonce:
- the nonce word its own document taught, a weak observation;
- the test person's context (`read01_<nonce>`). The memory agent has no way to forget a person's context.

**First run (`20260930T145815Z`, 21/22).** D failed. What the person's document said never reached their context.
Reading held what a document states at quality 0.3, and the learning door refuses anything below its floor of
0.5 (`MIN_ADMIT_QUALITY`). The substrate's own documents went through a path that took 0.3 anyway, which is the
opposite fault: it went around the floor. Both paths now hold what a document says at the door's own floor.

This also explains why the substrate never held what its own files say. The environment scan read them at 0.3,
the door refused every statement, and ENV-INVESTIGATE-01 passed only because its stand-in learning accepted
everything.

**Second run (`20260930T150041Z`, 22/22).** Every check passed.

**Third run (`20260930T151829Z`, 27/27), with J.** A task used to open a file through the `read_file` tool, which
handed the bytes to its plan. Nothing read the words, and nothing remembered the reading. Now the substrate reads
every file a task's tool opens by its own reading, as part of the task's pursuit, as whoever the task is for
(`_read_what_was_opened`).

**What it does not show.** How much of real prose the reader understands. Timed on the sandbox's view, read-only,
the repository README (286 lines, 2,497 words) gave 1 fact in 4.9 s. `docs/AUTONOMOUS_CAPABILITIES.md` (85 lines)
gave 0. Reading is now the substrate's own, and what it can read is what the English lessons have taught.
"A salmon is a fish." states nothing once WordNet's senses of "fish" are held, because the reader will not pick a
sense. That is the open work on word senses.
