# WORK-TALK-01: the conversation knows the substrate's own work

The queue authority holds every job the substrate has: what people asked for, its own work, and its scheduled work.
The conversation never read it. So the substrate could not say what it was working on, could not report when
something finished, and "stop that" became a new job. `cancel` stopped only background and scheduled jobs, never
the work a request becomes.

**What changed (2026-09-30):**
- **Stopping.** `QueueAuthority.cancel` now also stops work jobs. A waiting job is never drawn. A running job is
  stopped where it is, and the authority holds each running job's handle for that. The job's record says
  `cancelled`, and a late "completed" cannot overwrite it.
- **Knowing the work.** `work_of(actor)` returns one person's jobs from the queue's own record, and `mark_told`
  records on the job that they were told how it ended.
- **The conversation.** `Conversation.about_my_work` reads, from the meaning, an event done by `?listener`:
  what it is doing now, whether it finished, a request to stop it, or not to stop it.
- **The front door.** It answers those turns from the queue before anything else. `stop_work` cancels the job and
  ends its pursuit, saying who stopped it. A request not to act ("Don't open the box.") is answered and never made
  a job. Every reply carries whatever of the person's work ended and they have not been told, said once: how it
  ended, and what it found, including what a file it read says.
- **The lesson.** english_27 teaches these sentences (see below).

**What it checks**, on the real substrate in the sandbox:

| | |
|---|---|
| A | Work asked for is taken on and said so. "What are you working on?" names it. "Stop that." stops that job before it runs and is not a new job, and its record says `cancelled`. Asked again, nothing is running. Another person sees none of it. |
| B | A job the queue authority is running (its work a long wait, the one stand-in) is named by "Are you still working?". "Cancel it." stops it where it is. |
| D | "Don't stop." means keep going. "Don't open the box." is answered, not taken on, and neither becomes a job. |
| C | The task loop runs a job to its end (a note read through the job's tool). The person's next turn, about anything, is answered and then says how the job ended and what the note says. The turn after does not say it again. "Did you finish?" answers yes, with what it found. Asking only for what finished brings nothing new. |
| E | The main model's store is untouched. |

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/WORK-TALK-01/experiment.py
```

It deletes the pursuit memories its turns form, by id. What it leaves in the sandbox, named by the run's nonce: the
test person's job records in the queue's history, and their turns' experiences in the memory agent's pool.

**Runs:**
- `20260930T154448Z`, 19/19. It showed a fault its checks did not catch: "Don't stop." was taken on as work and
  then reported as failed. A request not to act is now never made a job, and "Don't stop." reads as keep going.
- `20260930T154639Z`, 21/21, with that fix.
- `20260930T154800Z`, 21/21. The report now says what the note says ("I read note.txt. It says: A robin is a
  bird."), from the substrate's own reading of it.

- `20260930T162340Z`, 21/21. Work that ends is now said by the substrate itself, through the outbox (MESSAGE-01).
  With no front end listening, it waits for the person's next turn, which is what this experiment shows.

**The lesson, english_27** (71 records, taught to the sandbox, none refused). It teaches "What are you doing /
working on?", "Are you (still) working?", "Did you / Have you finished?", "Are you done?", "Is it done / finished?",
"Stop (it / that / the search)", "Cancel that", "Stop working", "Don't stop", with other doers beside "you" so the
frames are learned rather than memorized. It reads in the sandbox's own view, with WordNet's sample on top.
Checked in memory on all twenty-seven lessons: 27/27 sentences it never taught read and are placed right, and every
earlier lesson still reads. The only misses were already there before english_27: four reflexives in english_13
("Tom helped himself.") read two ways in the memory-taught view. The store's view reads them.

**Also changed, in the reader.** A meaning in which one happening is both going on and already over, at the same
moment, is refused. "Is the book finished?" had read as the book finishing now and before now.
`tests/test_derived_reading.py`: 93/93.

**Known limits:**
- A new noun phrase does not always fill a slot learned from phrases. "Did you finish the report?" read only once
  "report" was taught in that frame.
