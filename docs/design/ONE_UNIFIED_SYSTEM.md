# One unified system: whatever arrives, every authority at once — Design Doc

Status: PROPOSED (rev 1, 2026-10-23). Nothing here is built. Worker processes for reading (the "switch" to all
cores) are measured and shelved (lab notebook 2026-10-23 (37), (38); §6).

## 1. What is asked

The owner, 2026-10-23: "a request comes in, a task happens, an error happens, whatever: not only does Lyric start to
process the message or request, all its other systems should be firing at the same time. It all starts in reasoning,
but learning should be processing at the same time, the memory agent should be doing work at the same time, because
you can't really reason about something unless you know about it. Right now its systems are passing each other
things instead of it all working as one."

In cognitive science this is a global workspace: what arrives is broadcast to every specialist at once, each adds
what it has to one shared state, and thinking runs on that state as it fills. Lyric already has the parts; what it
lacks is the broadcast and the one state.

## 2. How it works today (read in the code, 2026-10-23)

**One door.** Apps and outside services reach Lyric through the API gateway's relay to the Tet field (`tet_api`), into
Tet, where Lyric is attached as the inhabitant (`core/integration/world_inhabitant.py`). Each thing is taken for what
it is: a message to the front door (`AutonomousCoordinator.handle_user_request`), a reward allowance to the appraisal
authority, an operating mode to the capability faculty, shared-learning settings to the learning authority, what a
device hears to Lyric's ears. (The gateway's older Lyric routes, `/api/lyric/chat` to 9080 and "lyric-main" on 9001,
point at servers not running since 2026-08-28.)

**Behind the door, a line.** A turn (`_take_turn`) is scoped to who asked, sorted into a kind by the conversation
(`_request_kind` → `Conversation.classify`: not understood, about Lyric's own work, a question or telling, a job),
becomes a pursuit (`intend`: its intent, and its one memory), then goes down one branch. A question or telling is
understood in steps, each waiting for the one before (`Conversation._understand`): listen and read, take what it tells
(`teach`), resolve its words, look up the longest one not placed (`look_up`), answer (`asked`), hand the turn over to
memory. A job waits in the queue for the cognition loop (`execute_task`).

**Memory alongside, in one place.** `core/memory/live_recall.py` ("remembering while thinking, instead of before it")
sends recall in waves, each a task the moment its query is known: the raw words, then what they turned out to be,
then what is asked. It runs only inside a conversation's understanding, and starts after reading.

**Learning after the fact.** The event spine (`emit`/`on`) carries nine events, every one after work: task completed,
outcome observed, competence changed, evidence admitted, job completed, deficit diagnosed, percept recognized,
environment encountered, expectation unmet. Nothing is emitted when a turn reaches the front door, a task reaches the
queue, or a step fails. Learning hears of an arrival only once something about it has ended.

**Text between them.** The reader's meaning goes to the learning authority as facts (`take_in_telling`), and the
question's reading reaches reasoning (`ReasoningRequest.reading`); everything else crosses as text. Premises reach
reasoning as sentences each kind of thinking reads again (`request.context`); memory is recalled by likeness of text
and handed back as a string; what is kept is written text. Complexity is a word count (`complexity_of`).

**One core, taking turns.** Everything runs in one event loop. The reader is CPU-bound and holds it: a page looked up
held the whole substrate for 9 min 50 s (RESEARCH-WRITE-01, 2026-10-23). Recall's waves are tasks of that loop, so
while the reader reads they do not run.

## 3. The design

### 3.1 One arrival event

A new self-event, ARRIVED, emitted the moment anything comes in, before anything is done with it: a turn at the front
door, a task at the queue (`QueueAuthority.add_task`), a step that failed. Each carries what arrived, from whom,
through which context, and the pursuit it opens or belongs to. The nine events after work stay as they are.

### 3.2 The pursuit is the shared state

Every arrival opens a pursuit (a turn already does: `intend`) or joins the one it belongs to (a failed step joins the
pursuit it happened in). The pursuit's intent and its one memory are where every authority writes what it finds, as
it finds it: the reading, what is recalled, what was learned, how complex it is, how hard to try, what reasoning has
reached. No authority hands its output to the next one; each reads the pursuit and adds to it.

### 3.3 What each authority does when something arrives

All at once, each its own reaction to ARRIVED (`on(ARRIVED, ...)`), each writing into the pursuit:

| Authority | Reacts by | Writes into the pursuit |
|---|---|---|
| The reader | reading what arrived | its reading: one meaning, the one every authority uses |
| The reasoning authority | scoring how complex it is, then reasoning as soon as a reading lands | the score; what it has reached so far |
| The memory agent | recalling in waves (LiveRecall, moved from the conversation into the memory agent's reaction) | each recalled memory, as a meaning |
| The learning authority | taking in what it teaches as it is read: new words, evidence, what it contradicts | what it learned, at once |
| The behaviour arbiter | deciding how hard to try from the complexity and the appraisal | effort: answer from what is held, research, persist, ask |
| Research, when the arbiter says so | looking up what is missing | what the pages say, as meanings |

Reasoning starts on the reading and takes in each memory and each thing learned as it lands. The answer is assembled
when the arbiter's effort is met, never at a fixed deadline.

### 3.4 One representation

The reader's meaning is the one interpretation: memory keeps what happened as meanings tied to the things and relations
they involve and recalls by them (likeness of text alongside, no longer how memory knows what a memory is about);
reasoning takes its premises as facts, never sentences to read again; the reasoning authority scores complexity from
the reading (how much was understood, what is asked, how many unknowns, how far it is from what is held); the memory
agent decides what to keep from the meaning (what is new, what contradicts, what it connects to). What the reader
cannot read stays text, marked as not understood, and is kept as that.

### 3.5 Owners, unchanged in kind

No new intelligence system and no new authority. The spine gets one event; the pursuit becomes the shared state; each
authority keeps its job and reacts instead of waiting to be handed something. Affect: the arbiter becomes the one
authority for emotions and for how they turn into action (today the appraisal derives them and the arbiter reads them).

## 4. What changes where

- **Coordinator** (protected; edited only while nothing runs): the front door and the queue emit ARRIVED; the
  conversation's line becomes the reactions of §3.3; `_understand` reads the pursuit instead of calling each step.
- **Memory agent:** recall as its reaction (LiveRecall's waves); keeping and recalling meanings.
- **Learning authority:** a reaction on arrival, not only after outcomes.
- **Reasoning authority:** complexity from the reading; premises as facts; reasoning that takes in what lands.
- **Behaviour arbiter:** effort from complexity and appraisal; the owner of affect.
- **Queue authority:** a task's arrival emits ARRIVED.

## 5. Order of building, each step measured before the next

1. ARRIVED, and the pursuit as the shared state, for a turn: the conversation's steps become reactions writing into
   the pursuit, answering the same. Checked: UNDERSTANDS-PROSE-01 and the experience-pool tests give the same answers.
2. Memory's recall as its reaction to ARRIVED, from the moment of arrival.
3. Learning on arrival.
4. Complexity from the reading; the arbiter deciding effort; the arbiter owning affect.
5. Meanings as the one representation: memory keeps and recalls meanings; reasoning's premises are facts.
6. Tasks and failed steps as arrivals.
7. Heavy work off the event loop (§6), so "at once" is at once.

## 6. Dependency: at once needs more than one core

Reactions are tasks of one event loop: they interleave, and a CPU-bound reaction (the reader, the grammar's chart)
stops the others until it ends. Steps 1 to 6 make Lyric one system; step 7 makes its parts run together. The switch to
worker processes was measured (the reader's view copies to a worker: 86 MB on lyric_dev, 4.8 s to load) and shelved
on the owner's word: reading in a worker also needs the word classes, the grammar's word knowledge and the beliefs the
reader ranks constructions by, each kept current with the main process (lab notebook 2026-10-23).

## 7. For the owner to decide

1. Which arrivals are in from the start: turns, tasks and failed steps (this doc), or also percepts and alerts.
2. Whether the arbiter takes over deriving affect from the appraisal in step 4, or later.
3. Whether step 7 (worker processes) comes back before step 5, since meanings as the one representation add reading.
