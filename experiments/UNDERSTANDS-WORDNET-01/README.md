# UNDERSTANDS-WORDNET-01 — is what WordNet taught understood, shown in what the substrate answers?

**Finding (2026-10-13, `results/20261013T220542Z.md`, FAIL at 9/13 checks): where the question can be READ, it is
answered; where it cannot, nothing else gets a turn.** Inference 95% (95/100), "What is a X?" 99% right, senses
84%, and nothing invented -- 0/200 yes to unrelated pairs, 0/50 to nonce words, all fifty of which came back
unknown. The three failures are reading, not answering: opposites 14% with **66 of 100 UNREAD**, the plural form
("Are flagons vessels?") 35 of 57 unread, and parts 77% with 14 "recalled, gave no verdict". The reply that marks
them is "I know these words, but not this way of putting them together" -- a construction never held, not a fact
never learned. P7 asks about adjectives, which hold words for 2.4% of themselves.

This also settles what the end-of-pass review cannot say. That review calls `answer_over_graph` directly and never
builds a conversation, so it measures graph traversal: it reported the eleven kinds of thinking used zero times
across 200 questions, while this run, through `Conversation.understand`, reasons its way to 95 of 100. The number
to improve is this one.

**Stale as of 2026-11-10** -- it predates the grammar reader rebuilt (10-21), the composer rebuilt (10-20), the
word classes taught (11-06/07), PropBank's arguments and the word groups reaching the reader, and the multi-word
reading fixes (11-10). Every one of those bears on the unread rates. Re-run before acting on these figures.

KNOWS-WORDNET-01 asks whether a fact is held. Holding is not understanding. This asks the substrate questions, in
English, the way a person asks them, in forms the teaching never used, and reads its own verdict on each.

## What is asked

| Probe | Question | Right answer | Shows |
|---|---|---|---|
| P1 taught | "Is a flagon a vessel?", "…a kind of vessel?", "Is it true that…?", "Are flagons vessels?" | yes | recall beyond the sentence taught |
| P2 inferred | "Is a flagon a kind of container?" (two or three steps up) | yes | reasoning, not lookup |
| P3 unrelated | "Is a towner a kind of canary?" (WordNet relates them in no sense) | not yes | it does not invent |
| P4 nonce | "Is a sugumev a kind of textile?" | not yes; unknown | it knows what it does not know |
| P5 senses | "Is a dresser a kind of furniture?" and "…a kind of person?" | yes, both | it holds a word's senses apart |
| P6 parts | "Is a flower part of an angiosperm?", and unrelated pairs | yes / not yes | relations beyond "is a" |
| P7 opposites | "Is weak the opposite of strong?", and unrelated pairs | yes / not yes | relations beyond "is a" |
| P8 what is | "What is a flagon?" | a class WordNet puts above it | it can say what a thing is |

Bars are fixed in the code before the run (`BARS`): 90% on taught facts, 80% on inference, senses, parts, opposites
and "what is"; at most 2% "yes" to unrelated pairs and none to nonce words.

## How it is scored, and the traps

- **The truth is WordNet itself** (`nltk`), never the store, so the store cannot grade itself. "Yes" is right when
  some sense of the word has the class among its ancestors; a pair is a negative only when no sense of either word
  reaches the other.
- **The verdict is the turn's own** (`Answer.verdict`: True holds, False the denial is held, None not known), never
  a word found in the reply. A reply that mentions the right word while answering something else scores nothing.
- **Unread is not unknown.** A question the reader could not read is counted apart from one it read and could not
  answer: they are different failures.
- **Each question is its own conversation** with nothing looked up (`look_up=False`): no earlier turn can carry an
  answer in, and nothing outside the store can supply one.
- **Things only.** Nouns under WordNet's `object` (artifacts, organisms, people, body parts, natural objects), which
  English asks about with "a". Abstract and mass nouns ("Is a sternness a severeness?") are out of scope, not asked
  badly. Common words (met in SemCor) and rare ones are reported apart.
- **On main, remembering nothing.** Each conversation is held with `remembers=False`: it reads, recalls and answers
  as any other, and stores no turn and takes in nothing it is told. No substrate is started, since its own loops
  write -- only memory, the beliefs and the language view are loaded. The store's write counters
  (`pg_stat_user_tables`) are read before and after, any table written to while the questions were asked is
  reported, and the run fails its first check. **It did fail it on 2026-10-13: `unified.knowledge_consumption` took
  426 rows**, so something on the asking path still writes, and that is a defect of its own.

## Run

    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/UNDERSTANDS-WORDNET-01/experiment.py [N]

`N` (default 100) sets the sample per probe; P1 asks 4N. Seed `20261010`. Each run writes `results/<UTC>.json` and
`.md` through `_evidence.RunRecord`, and its log to `results/run.log`.
