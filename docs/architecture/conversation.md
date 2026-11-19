# The conversation — reading a sentence and answering from what is held

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

`Conversation` (`core/agents/autonomous/autonomous_coordinator.py` at 23221, 4,107 lines, 90 methods) reads
a sentence and answers out of what the substrate holds. No model is on any path through it: what a sentence
means is read by the one reader, and what is said back is composed from held facts.

It is reached through the body — `AutonomousCoordinator.conversation(session)` — or directly through
`get_conversation(session)` (27233). The reader itself and the gate that admits what a turn tells are
documented separately in [semantics-ingress.md](semantics-ingress.md); this document is the thread of talk
and the answering.

---

## 1. A thread, not a person

`session` identifies a **thread of talk**. Two windows are two sessions. A caller with no session of its own
must pass a stable string rather than a default, so unrelated callers cannot silently share one another's
context.

| Binding | What it is |
|---|---|
| `session` | The thread. The last-resort scope when no verified identity is bound |
| `actor_identity` | The **verified** person behind the thread, supplied by whatever authenticated them. When set, it — not the ephemeral session — is the actor a told fact is scoped to, so one person is one context across sessions and devices |
| `source` | Whose work the thread is, in the task queue's own vocabulary. Defaults to `MANUAL` — a person talking, which can never resolve to the substrate. Only `AUTONOMOUS`/`SYSTEM` resolves to the shared mind, and only by stating it |
| `_context` | Which of that person's contexts the turns come through: `work` for an organization, else personal |
| `within` | What it is being told **in**, where that is not the talk itself — a document being read. Each happening is named as told in it, so "The dog barked." in two stories is two barkings, and the same story read again names the same one |

A held conversation adopts a later-supplied identity, so authenticating mid-thread binds the rest of the
talk to that person without losing the thread.

**`remembers=False`** holds a thread that remembers no turn and keeps what it is told in working memory
only, as the premises of what it is asked next. It reads, recalls, reasons and answers as any other does and
writes nothing, so the substrate can be asked about what it holds on the store it holds it in without the
asking becoming part of it (`UNDERSTANDS-WORDNET-01`, `UNDERSTANDS-PROSE-01`).

## 2. What a conversation remembers

The record is the authority on the conversation. Not the concept store, and never the web: until the record
existed, "what did I just ask you about?" fell through to the only owner there was — research an
unrecognised phrase — and came back with an article about the rhetorical tactic of asking questions.

| Held | Bound | What it is for |
|---|---|---|
| `_turns` | 560 | Every turn in order: what was said, what was told, what was answered |
| `_not_taken_in` | 560 | What it was told and did not take in whole, as said. Memory then knows what it holds of those is not all it was told, so the reasoner closes no world on it |
| `_talked_of` | 24 | The things talked of, most recent last — what a word naming several things is weighed against ("We went to the river. The bank was steep.") |
| `_spoken_of` | by utterance | What a later "it" or "they" points back to |
| `_particulars` / `_mentioned` | — | Which "the X" is which, and the X talked of most |
| `_named` | — | The word this speaker last called each thing by ("kennel", for the kennel WordNet also writes "doghouse"). A reply says the thing with it |
| `_framed` | — | The constructions this speaker's sentences were read with. Of the ways a reply can be said, one of theirs comes first |
| `_last_read` / `_last_heard` | — | So one turn reads its words once however many of its steps ask what they mean |

Every one of these is bounded. The turn record is the one that mattered: a plain list only ever grew — one
conversation object accumulated a turn per exchange for its whole life and never freed one. Continuity is
recent, so a generous window keeps it intact while capping the growth.

## 3. One turn

`understand(text)` is the entry. `_understand_each` splits a text of several utterances and answers them
**one at a time**, because `_understand` asks what the last utterance meant and only where every utterance
read. One sentence the grammar read no whole of used to throw away the meaning of every sentence that did:
four sentences of prose came back as one part-report because the second read as nothing, so two sentences
Lyric understood perfectly went unanswered for a fault in a third.

**Read once, not once per sentence.** The whole text is read and listened to together, which is what lets
the listener weigh each utterance against the rest of what was said. Each utterance is then handed to
`_understand` under its own words with what was already read put where `_read` and `_listen` look for it.
Reading the second sentence of a paragraph by itself costs 665 s at the width a person's words are read at,
and it had just been read as part of the whole.

`classify(sentence)` returns `question`, `telling`, `job` or `not_understood`, **decided here by the one
reader with no model**. This was decided twice once — the coordinator asked a model, this asked a rule, and
they disagreed: *a quorum sensor detects bacterial population density* is plainly a statement, the model
called it a question, and it was filed in memory as `Asked: a quorum sensor detects…`. What the speaker
wants is part of what a sentence means, learned with it.

**What does not read is not understood.** It used to be called a job, so anything the reader could not read
became work: a misheard fragment, a greeting, a sentence in a shape never taught. It has told the substrate
nothing and asked for nothing it can name, and it is said so.

## 4. Answering

`Understanding` (21996) is what the substrate made of one sentence: what was resolved, what was answered,
what was acquired, what is unknown, and `why_not` — one entry per path that found nothing, kept where the
person asking can be told rather than only logged.

The answer is assembled from several paths, each of which can return nothing:

| Path | What it answers from |
|---|---|
| `_from_the_record` | This conversation, when the question is about this exchange |
| `about_my_work` | The queue authority, when the sentence is about the substrate's own work |
| `asked` | The held relations that answer what the question **means** |
| `_held_ways` | Every way what is held makes all of a question's facts hold |
| `_reasoned_answers` | What the substrate **derives** from what it holds |
| `_worked` | A sentence about numbers, worked by the reasoning owner |
| `_what_a_kind_is` | Asked of a kind itself rather than of any one thing of it |
| `look_up` | A genuine gap, researched on the web |

**`_Held` (22212, 1,009 lines)** is what is held about one thing, read as its relations say: what points out
of it and into it (`out`, `into`), what it equals (`same`), what it is called (`called`), every kind it is
one of (`kinds`, `is_kind`), and what follows from a chain of links through the relation algebra
(`_edges`, `_step`, `_leads_to`, `subjects`, `objects`, `holds`). A question is answered by finding every
assignment of its unknowns that makes all its facts hold.

A question is asked both ways it can be: as the relation its verb names (`_as_the_relation_a_verb_names`),
and as English's grammar reads it (`_asked_of_events_composed`). Where a link does not hold in the sense
first read, each side is re-read in the sense that **does** hold it
(`_in_the_sense_that_holds`, `_placed_in_the_senses_that_hold`).

**`say(understanding)` is the one path from what is held to what is said.** Every branch returns sentences,
and a held fact becomes words in exactly one place (`_triple_sentence`), so a reply cannot drift into
printing the store's own vocabulary at a person. `support=True` appends the derivation a claim was proved
from — the same answer with its working shown, which is why it is a parameter and not a second renderer.

A reply already established is not re-derived. There used to be a second renderer beside `say` with an `or`
between them, which fell through to an introspection dump for every question that was not a yes/no; and
recomputing an already-answered conversation question produced a second, different answer, so a caller
reading `.reply` and a caller calling `say()` on the same object were told different things.

Nothing is said twice: one claim can arrive recalled from memory **and** held in the store, and both render
to the same sentence.

What is said is said plainly (`said_plainly`): one dash, the hyphen.

## 5. Being told something

`teach(sentence)` reads what was said with the one reader and hands it to memory. `_told` makes
`(facts, rules, theirs, names, given)` of one utterance; `_telling` is what memory takes in; `stated(text)`
is the same for a written document, between named things.

What a turn admits goes through the **cognitive ingress**, not through a method of this class — see
[semantics-ingress.md](semantics-ingress.md). Admission emits `EVIDENCE_ADMITTED` on the body's event spine,
which is what lets the domain authority crystallize a taught subject into its own domain the moment its
concept cluster is complete.

`_tell_again` handles a sentence this person said before, told again as their verdict on it. `feedback_of`
decides whether an utterance is feedback on what was just taught and what it bears on; `_take_feedback`
hands the verdict to memory. `forbids` reads a sentence that asks the substrate **not** to do something —
answered, and never made a job.

Who a told fact is scoped to is resolved through the one owner (`_actor`, `actor_for`), never a second time
here.

## 6. Resolving what a sentence names

| | |
|---|---|
| `resolve` / `resolve_name` | Every concept the sentence names, and what is held for it |
| `_known_of` | Which thing each "the X" of a meaning is |
| `_known_here` | A known thing talked of here is the one meant |
| `_previous_for` / `_spoke_of` / `_named_before_its_pronoun` | What a later "it" or "they" points back to |
| `_one_in_world` | The particular of a kind the world holds, where it holds exactly one |
| `_plural_map` | Which words are plural, decided against the store |
| `_context_relations` / `_incoming_relations` | What this speaker told the substrate about each phrase, and what points at a concept |
| `_leads_on` / `subject_of` | Whether this turn follows from what the last answer said |

`_listen` is the second reading: where a text's words can be taken more than one way, memory is asked what
each could mean, and the listener weighs them against what has been talked of.

## 7. Looking something up

`look_up(phrase)` researches a genuine gap through the `web_search` tool, at most **once across the whole
substrate** for a phrase: a module-level single-flight (`_LOOKUPS_INFLIGHT`, keyed by the normalized term)
means one self behind many sessions, so a crowd asking the same unknown at once collapses to one real
research and one shared-store write, the rest waiting on the same future. It is not a cross-time cache —
the entry lives only while in flight, so a later ask re-verifies. (`LOOKUP-SINGLEFLIGHT-01`.)

When the body supplies `_looking_up` (`AutonomousCoordinator._look_up_as_work`), a question needing a
look-up is instead **queued as work**: the person is told the substrate does not hold it yet and is looking
it up, whichever instance takes the task answers it through the knowledge loop, and the ended work is said
back to them. A conversation without that seam looks up in the turn.

## 8. What it is handed from the body

The coordinator injects what a reply may be informed by, and each is None when the conversation stands
alone — the reply is then exactly what it was, never a guessed mood.

| Seam | What it supplies |
|---|---|
| `_disposition` | The substrate's current disposition, the behaviour arbiter's directive |
| `_looking_up` | How a look-up is made as work |
| `_recall` | The recall running alongside this conversation, persisting across turns so a wave landing after one answer is already in hand for the next |

## 9. Lifecycle

`get_conversation(session)` creates on first use; `end_conversation(session)` forgets a thread;
`held_conversations()` is how many are held, for health reporting. `get_conversation` also arms the
observability apparatus (channels, failure capture) idempotently, because it is the substrate's front door
for conversing: an experiment, script or test that brought the substrate up without `core.main` ran with no
channel routing and no account of its background work — a 462-second read said nothing about what it was
doing for 461 of them.

## 10. Evidence

| | |
|---|---|
| `experiments/UNDERSTANDS-WORDNET-01` · `UNDERSTANDS-PROSE-01` | Answering from the store without the asking becoming part of it |
| `experiments/LOOKUP-SINGLEFLIGHT-01` | One research behind many sessions |
| `experiments/WORK-TALK-01` | A turn about the substrate's own work |
| [../TEACHING.md](../TEACHING.md) | How the substrate is taught, and from which sources |
| [semantics-ingress.md](semantics-ingress.md) | The reader, and the gate language passes to become knowledge |
| [coordinator.md](coordinator.md) | The body: the front door, speaking first, and work queued from a turn |
