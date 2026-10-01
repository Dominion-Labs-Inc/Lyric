# MESSAGE-01: the substrate speaks first

Before this, the substrate could only reply. Everything it said was the answer to a turn, so work it finished in
the background waited, unsaid, until the person spoke again. Now it can say something with no turn before it.
This is the base for reminders, scheduled work, and telling people what they should know.

**How it works (2026-09-30):**
- **`coord.speak_to(person, text, why=…, about=…, at=…)`** owes the person a message, due now or at a set moment.
  The message is kept in the **outbox** (`core/agents/autonomous/outbox.py`, table `unified.outbox`). The outbox
  is durable: it is not memory, only what is owed to be said and when. The saying is also recorded in the
  person's conversation as a turn of the substrate's own (`Conversation.note_said`).
- **Pushed when due** to every front end listening for that person (`coord.on_message(person, listener)`). A
  listener that starts listening is handed anything already waiting.
- **With no one listening, it waits.** It comes with the person's next reply, or when a front end asks
  (`metadata={"notices": True}`).
- **Once.** Marking a message delivered is one statement, and the row records how it went out: `push`, `reply` or
  `asked`. If every listener fails, it is owed again.
- **At its time.** A message due later is delivered by the queue authority's own timed job. At boot the substrate
  arms whatever is still owed (`_rearm_messages`, beside restoring the queue's backlog), so a message due after
  a restart is still said at its time.
- **Work that ends is said by the substrate itself.** The queue authority announces a work job ending
  (`on_work_ended`, as it already pushes an await-job's result), and the substrate tells the person how it ended
  and what it found (`_speak_of_ended_work`).
- **The live senses listen** for the person talking to them, so what the substrate says unasked reaches them in
  the room. It is written to the log for now; spoken once the substrate has a voice.

**What it checks**, on the running substrate in the sandbox:

| | |
|---|---|
| A | A person's work ends while they say nothing. A front end listening for them is told how it ended and what it found ("It says: A robin is a bird."), with no turn of theirs in between. Their next turn does not repeat it. |
| B | With no one listening, the message waits. Their next turn brings it, once. |
| C | A message set for 4 s later is not said at 2 s, and is said at 4.0 s. |
| D | A message whose timed job is gone, as when the process ends, is still owed in the outbox. Armed again the way boot arms it, it is said at its time. |
| E | Every front end of that person is told. Another person is told nothing. It is delivered once, by being pushed. |
| F | What the substrate said unasked is a turn of its own in the person's conversation. |
| G | The main model's store is untouched. |

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/MESSAGE-01/experiment.py
```

It removes the messages it owed, by person, and the pursuit memories its turns form, by id. What it leaves in the
sandbox, named by the run's nonce: the people's job records in the queue's history, and their turns' experiences in
the memory agent's pool.

**Run `20260930T162241Z`: 17/17.** WORK-TALK-01, rerun on the same path (work that ends goes through the
outbox), 21/21 (`20260930T162340Z`).

**Not yet built on it:**
- Channels beyond a listening front end, such as email or SMS through the tools.
- Scheduled work the person asks for ("remind me at 3", "check the backup every morning"): the sentences and a
  durable schedule. The queue authority's recurring jobs are still registered in code.
