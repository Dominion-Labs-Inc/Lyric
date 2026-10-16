# PATHS-02 — Lyric hands over; one door into the world; one conversation path

**Finding (2026-10-07): 15/15.** Lyric (the coordinator and its Conversation) puts no claim into knowledge.
What it meets it hands to memory's intake (`MemoryAgent.take_in_*`); memory splits it; the learning authority
is the one door into the world. The Conversation names no learning at all.

The rule, from the user (2026-10-06): "It's supposed to be a learning authority, which is the one learning path;
then the coordinator, who is Lyric, has that one conversation path." The design is
`docs/research/SEPARATION_MAP.md` §11.2 and §11.7.

**What the first run found, and what was changed to pass it:**
- **Lyric still wrote knowledge itself.** Conversation feedback went to `learn_from_feedback`; recognition called
  `learning.recognize`, which wrote the claim; an act's demonstration and its projection went straight to the
  learning authority and the evidence producers; the senses, threat sensing and the tool registry called the
  producers directly; an unread sentence went to the ingress; the lesson split (`_lesson_for_the_world`) sat in
  the coordinator; a task outcome was handed to learning by the coordinator. Each now goes to memory's intake
  (`take_in_verdict`, `take_in_recognised`, `take_in_demonstration`, `take_in_transition`, `take_in_percept`,
  `take_in_tool`, `take_in_tool_use`, `take_in_unread`, `take_in_lesson`, `take_outcome_to_learning`), and the
  learning authority's `name_instance` only says what its classifier names a thing, writing nothing.
- **A task's completion belief was world knowledge.** It was a belief in the world's store whose claim was the
  task's goal in the words of whoever set it (their names, places, codes). It is now computed on the task itself
  with the same belief kernel, and never written to the world.
- **The learning authority wrote a person's context.** `observe_method_outcome` moved a person's belief in a
  method, and hypothesis testing a person's belief in a hypothesis. Memory holds both now
  (`hold_belief_for_person`); the learning authority keeps only the world's part.

**What it checks.**

| | |
|---|---|
| **A** | no call in `autonomous_coordinator.py` reaches a claim door (the learning authority's, the ingress's, the person's context store's, the belief store's, an evidence producer, memory's own person writers); what Lyric meets goes to memory's intake |
| **B** | nothing inside `class Conversation` names the learning authority |
| **C** | outside the learning path, a claim door is called only by memory, its producers and Lyric's own reasoning conclusions (analogy discovery, the domain master's projections); beliefs for Lyric's own state (competence, patterns over its own memories, its reasoning record) only by those three; the ingress, the producers and a person's context only by memory; a person's context tables have one writer |
| **D** | one Conversation class; a person's turn reaches `Conversation.understand` only through `_take_turn`; the answer from what is held only from the turn |
| **E** | memory's intake reaches the world only through the gate, a person's context only through its own writers, percepts through their producers |
| **F** | live: a telling through the front door is a part of its pursuit's memory, and the pursuit waits in the pool |

**The trap in measuring it.** A live probe shows one path works, never that a second does not exist, so A to E
read the source with Python's parser and classify every call by what it calls and on what. `core/quantum` is
not read: the quantum subsystem is disabled and its learning bridge never started (`core/main.py`). The same
method names on other receivers (`task_queue.hold_for_person`, `world.observe`) are not doors.

## Run

```
./venv_lyric/bin/python3 experiments/PATHS-02/experiment.py
```

On the sandbox. Each run writes `results/<UTC timestamp>.json` with a `.md` beside it.
