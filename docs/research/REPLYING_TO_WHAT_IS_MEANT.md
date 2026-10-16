# Replying to what was meant

Research note, 2026-10-02. It follows COMPREHENSION-01, which asked again the questions `COMPREHENSION_SCOPE.md`
§3 and §4 found failing on 2026-09-19. §5 is built (§7).

## 1. The problem, as measured

COMPREHENSION-01 (`experiments/COMPREHENSION-01/results/20261002T124158Z.json`), on the sandbox after the lessons,
with WordNet's records about the words asked of taught first:

| Asked | Said | An LLM |
|---|---|---|
| "hello" | "Part of that is about something I have no name for yet, so I did not hold it." | "Hello." |
| "is a grandfather clock a beer?" | "I remember: A grandfather clock is a pendulum clock. I hold things about grandfather clock that I have not been taught to say yet." | "No. A grandfather clock is a clock." |
| "is a grandfather clock a clock?" | "Yes. A grandfather clock is a clock." | the same |
| "where is a dog?" | "I remember: A dog is a canine. Dog can mean a carnivore canine or a domestic animal. Which dog do you mean?" | that it does not know where, or a place |
| "what is a dog?" | the same as for "where is a dog?" | "A dog is a canine, a domestic animal." |
| "what is a bass?" | "A bass is a musical instrument." (recall: bass memories only) | a fish, a low voice or an instrument |

Since 2026-09-19 two things are fixed:
- "hello" is no longer looked up as a thing.
- Recall about "bass" no longer hands up an embassy.

Two are half fixed: the greeting is not answered, and the yes/no recites nothing about beer but does not answer. Two
fail word for word as they did: the place asked for, and the question of which dog.

## 2. The cause, traced

Every sentence here reads, to the meaning the lessons teach:
- "hello" means a greeting done by the speaker to the listener (english_16).
- "where is a dog?" means asking `located_in(dog, ?x)` (english_01).
- "is a grandfather clock a beer?" means asking whether `isa(grandfather clock, beer)` holds.

What goes wrong is after reading. **The reply is chosen by whether the sentence asks or tells, not by what it
means:**
- **A telling is handled as something to hold.** The greeting's facts are about an act with no name (`?v0`), so the
  telling path reports that it held nothing (`Conversation` near `autonomous_coordinator.py:22597`). The meaning says
  an act was done *to the listener*, and nothing answers the act.
- **A question with no held answer forgets what it asked.** `Conversation.asked` (`:21942`) builds answers from the
  question's meaning. When none is held, `say` (`:23498`) falls through to everything held about the subject, the
  reply written for "what is X?". So "where is a dog?" is answered about what a dog is.
- **The question of which sense comes from a word's parents, not from the listener.** `_sense_groups` (`:21553`)
  counts the kinds a concept is that are not kinds of each other as its senses. It was written when one concept held
  every sense of a word. Since one concept is one sense (`WordNetSource._sense_names`), a concept's several kinds are
  all true of it: a dog is a canine and a domestic animal. Which sense a word was meant in is the listener's to
  decide (`derived_reader.meant`), and this path never asks it.

## 3. What is known

- **Adjacency pairs** (Schegloff and Sacks 1973). A first part makes a second part relevant: a greeting makes a
  greeting relevant, a question an answer, thanks an acknowledgement. Answering a greeting by reporting what was held
  of it is no second part.
- **The question under discussion** (Roberts 1996/2012; Ginzburg 2012). A question sets what counts as a relevant
  reply. An answer resolves it. "I do not know where" addresses it without resolving it, and is relevant. Saying
  what a dog is does not address where it is.
- **Clarification requests** (Purver 2004; Ginzburg 2012). A hearer asks which was meant when it cannot ground what
  was said, not whenever a word could be taken another way.
- **Saying no** (Schlobach 2005; Markman 1989). Under the strong disjointness assumption, kinds that are siblings
  exclude each other unless something is known to be both. Children assume the same of names for things (mutual
  exclusivity). Measured here, offline on WordNet:
  - of 1,479 questions "is an X a Y?" with Y near X (a common ancestor 2 to 4 levels up) and X not held under Y,
    something is both in 19 (1.3%): "is a canine a domestic animal?";
  - for Y at random, in 6 of 1,484 (0.4%).
  So "No, unless something held is both" is wrong rarely on what WordNet holds. Where something is both, "Some
  are." is the answer.

## 4. What the substrate already has

| Needed | In Lyric |
|---|---|
| What a sentence does and asks | the meaning: `act`, the facts, the variable asked (`Meaning.asked`) |
| What is held that answers it | `Conversation.asked`; reasoning for what is derived |
| Which sense was meant, or that it is open | the listener: `meant`, with what memory holds (`Heard`) |
| Saying a meaning in English | `say`, through the frames the lessons taught |
| Greetings and thanks as acts done to the listener | english_16 |
| "knows where", and denial | english_18; the lessons' negation |
| What things are kinds of | memory's taxonomy |

## 5. Proposed: the reply answers the meaning

1. **Ask which sense only when the listener leaves it open.** When a word in the question names several concepts and
   `meant` decides none, ask which, naming each by its sense ("Which bass do you mean: the fish, the voice or the
   instrument?"). `_sense_groups` goes: the question of which sense stays, owned by the listener.
2. **A question with no held answer is answered about what it asked.**
   - What is said is the gap in the question's own terms ("I do not know where the dog is."), said through taught
     frames.
   - That needs a lesson record saying it, with its meaning ("I do not know where the book is."), taught first.
   - Everything held about the subject is said only for "what is X?", the question it answers.
3. **"No" where the kinds exclude each other.** A yes/no whose kinds are held and are not one under the other:
   - "No" when nothing held is both, with what the thing is ("No. A grandfather clock is a clock.");
   - "Some are." when something held is both;
   - declined when the thing's kinds are not held.

   This is an inference, so it belongs to the reasoning authority, not to the reply.
4. **A first part is answered with its second part.**
   - A telling whose meaning is an act done to the listener (a greeting, thanks) is answered with the act the
     lessons pair with it, done by the substrate to the speaker and said through `say` ("Hello.", "You are
     welcome.").
   - The pairs are taught in a lesson of exchanges, not written into the code.

**Order:** 1 and 2 first. They change only how the reply uses what is already read and held, plus one lesson record.
Then 3, in reasoning. Then 4, which needs the exchanges lesson and a way to hold a pair.

**Measured by:**
- COMPREHENSION-01, whose kennel check now tells the place in the lessons' form ("The dog is in the kennel.");
- NLU-08 (does it answer the question or recite what it holds);
- K and SENSE-COVERAGE-01, which must not move.

## 6. Limits

- "No" rests on what memory holds. WordNet files the tomato under vegetables only, so "is a tomato a fruit?" would be
  answered "No", where an LLM says botanically yes.
- The 1.3% was measured on WordNet's taxonomy, not memory's. Memory holds what was taught, a part of it.
- An exchanges lesson teaches the pairs it states. A greeting it never paired is not answered.

## 7. Built (2026-10-02)

In the order of §5, with what changed from the proposal.

1. **Which sense is the listener's to ask** (`_which_meant`). An utterance that reads whole and that the listener
   cannot decide is asked about, naming the word and what it can mean. `_sense_groups` and `Resolved.senses` are
   gone.
2. **A question nothing held answers is answered about what it asked** (`_not_known`), through english_30:
   - "I do not know where the dog is." for a place asked for;
   - "I do not know whether the dog is big." for a yes or no about one fact (a kind, a property, an ability).
     "Whether" is the fact as it holds and as it does not, marked as alternatives, so reading the sentence holds
     neither.

   A question kind english_30 does not cover keeps the reply it had.
3. **"No" where the kinds exclude each other** (`concept_graph_reasoning._kinds_exclude`, basis `disjoint`).
   - **Narrower than proposed.** It applies only where memory places both under something in common. A thing only
     told to be of a kind memory places nowhere is not known to be apart from anything.
   - **A telling is not refused on this basis:** being told something is both is how memory learns it is.
   - **"Some are."** is said as the thing that is both: "A dog is a canine. A dog is a domestic animal."
     (`held_as_both`). The lessons cannot yet say "Some canines are domestic animals." of a name of two words.
   - **A derived "No" now says the denial.** It used to name the claim it denied ("No. A grandfather clock is a
     beer.").
4. **A first part is answered with its second part** (`Conversation._answered_in_kind`). No relation was added:
   english_30 teaches "A greeting follows a greeting.", "A farewell follows a farewell." and "A welcome follows
   thanks." as held facts, and the reply does the act that follows the one done to it.

**Found on the way, and fixed:**
- **Every noun was taken as a plural** (`PatternInventory._written_otherwise`). Traced in
  `experiments/COMPREHENSION-01/README.md`.
- **A thing is said as the speaker said it** (`say(named=…, framed=…)`; Brennan and Clark 1996; Pickering and
  Garrod 2004): with the word the speaker called it by, else the word most used for it; and of sentences supposing
  the same, in a frame the speaker used.
- **A name of several words is used as its head is** when said: its last word ("domestic dog", a dog), or the word
  before a frame word inside it ("body of water", a body).
- **A counted word does not stand bare** (`slot_admits`): not where a sentence begins, and not in a slot beside
  which a held frame says the same with a counting word before it ("?slot0 is ?slot1." beside "?slot0 is a
  ?slot1.", `counted_beside`). The teaching pass also refuses to say, and so to learn, a sentence that begins with
  a word its source states is counted.
- **The reply sees every relation a concept holds,** not the first four by name.
- **A fact's sentence is learned before the fact is admitted** (`TeachingPass._teach`), so a word the lessons hold
  only inside frames ("power", "name", "front") is named by the time its fact reaches the door.

**Tried and taken back the same day:**
- **Ranking sentences by use before score.** It put a much-used bare frame before the right one for a word new to
  the view: "Kennel is outbuilding.".
- **Using a name of several words as its last word is.** "body of water" was used as "water" is, and said bare:
  "Stream is body of water.".
- **Preferring the sentence with the fewest words the speaker had not used.** It counted "the" as one: "I do not
  know where domestic dog is.".

Both wrong sentences were taught to the sandbox by COMPREHENSION-01's fifth run before its new check stopped at
them. Both experiments now say every record first, with nothing written, and teach nothing if a counted word
would stand bare (`said_wrongly`).

**Not built:**
- "Some canines are domestic animals." as a sentence.
- A not-knowing sentence for question kinds other than where and whether.
- Looking the answer up when it is not held. The look-up exists for a word not held (`Conversation.look_up`);
  COMPREHENSION-01 runs with it off.
- **Fixed the same day: a list blocked "No" for physical things.** The concept resolver refused the names in a list
  written into it (`ConceptResolver._NON_CONCEPTS`: "object", "thing", "data", "value", "item" and others).
  WordNet's `object` was one of them, so nothing above "object whole" was reached, a clock and a beer shared no
  kind, and "is a grandfather clock a beer?" was not known. The list is deleted; what names nothing is asked at
  the door (`cognitive_ingress.admissible`). Measured again by COMPREHENSION-01 on a rebuilt sandbox.

## References

- Brennan, S. E., Clark, H. H. (1996). Conceptual pacts and lexical choice in conversation. *Journal of
  Experimental Psychology: Learning, Memory, and Cognition* 22(6): 1482–1493.

- Schegloff, E. A., Sacks, H. (1973). Opening up closings. *Semiotica* 8(4): 289–327.
- Roberts, C. (2012). Information structure in discourse: towards an integrated formal theory of pragmatics.
  *Semantics and Pragmatics* 5(6): 1–69. (First circulated 1996.)
- Ginzburg, J. (2012). *The Interactive Stance: Meaning for Conversation*. Oxford University Press.
- Purver, M. (2004). *The Theory and Use of Clarification Requests in Dialogue*. PhD thesis, King's College London.
- Schlobach, S. (2005). Debugging and semantic clarification by pinpointing. *ESWC 2005*, LNCS 3532: 226–240.
- Markman, E. M. (1989). *Categorization and Naming in Children: Problems of Induction*. MIT Press.
