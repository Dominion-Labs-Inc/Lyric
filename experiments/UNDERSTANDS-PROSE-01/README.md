# UNDERSTANDS-PROSE-01: reading prose as its sources write it, and reasoning over what was read

**Claim.** The substrate reads prose as its sources write it and reasons over what it read. It understands the
sentences, answers what they say and what follows from them, and does not answer wrongly what it did not understand.

**Why.** Everything measured before this was English the substrate was taught, or close to it: the lessons, sentences
built from their frames, questions in their shapes. A first look on 2026-10-14 (read only, on main) told five short
texts to a conversation. They were an encyclopedia paragraph, a premise with a rule, the opening of a webpage, a
maths definition and a paper abstract. Of 18 sentences, 2 were understood. Two questions got a wrong "No".

- "Is Python a programming language?" was answered about the snake.
- "Is seven a natural number?" was No: WordNet files 7 under digit and natural numbers under integer.

A conversation held not to remember also took in nothing it was told. So nothing could be read to it and then asked
about without writing to the store.

**What it does** (`experiment.py`, on main, starting no substrate):

- **The texts** (`texts.json`), written as their sources write them:

  | Kind | About |
  |---|---|
  | Encyclopedia | whales |
  | Science | photosynthesis |
  | Webpage | Python |
  | Code documentation | `sorted` |
  | Mathematics | primes |
  | Premises and a rule | a valve and a tank |
  | History | the Eiffel Tower |
  | Paper abstract | anomaly detection |
  | Security log | an account lockout |
  | News | hiring |

- **Told, then asked:** each text is told sentence by sentence in a conversation of its own. The conversation is
  held not to remember, so it keeps what it is told in working memory and writes none of it. It is then asked what
  the text says outright, what follows from it (the Eiffel Tower is in France because it is in Paris), and what it
  denies.
- **Scored as a reader is:**
  - how many sentences were understood whole;
  - of the questions, how many were answered right, how many not answered ("I don't know", or not read), and how
    many were answered **wrong**. A wrong answer is worse than none, and is counted apart.
- **Checks** that the store was not written to, by the server's own counters.

| Bar (fixed before the run) | |
|---|---|
| Sentences understood | ≥ 90% |
| Questions answered right | ≥ 80% |
| Questions answered wrong | ≤ 2% |

**Run** (from the Lyric folder):

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/UNDERSTANDS-PROSE-01/experiment.py
```

With `LYRIC_COMPOSE=1` an utterance no taught frame reads is read by composing its meaning from how its words go
together (`core/semantics/composition.py`; learned from the lessons' sentences and PropBank's arguments memory holds,
taught by `--source composition` and `--source propbank`); the record notes whether it was on.

**Results:** `results/<UTC timestamp>.json` and `.md`, the transcript beside them, and `results/run.log`. The transcript
keeps what each sentence and question was read as (a composed reading marked) and, for each question, the answers
given and what the reasoner was asked and said, by which route. A sentence or question that stops the conversation is
kept with what stopped it and counted apart; the run goes on, and its check fails.

**Runs on main:**

| Run | Code | Sentences understood | Right | Wrong | Written |
|---|---|---|---|---|---|
| `20261014T190758Z` | composition (adjuncts) | 4/33 | 8/37 | 4/37 | nothing |
| `20261016T002042Z` | + no closed world on what was not taken in | 4/33 | 8/37 | 0/37 | nothing |
| `20261016T125637Z` | + a person's rule reaches the reasoner; a question about a known thing asks one fact | 4/33 | 9/37 | 1/37 | nothing |
| `20261016T140446Z` | + a happening told in a conversation is held, and asked about | 7/33 | 9/37 | 0/37 | nothing |
| `20261017T224849Z` | 29caa75, composing on (`LYRIC_COMPOSE=1`) | 16/33 | 10/37 | 3/37 | nothing |

Of the four wrong answers in the first run, three were the strong disjointness assumption about a subject the
conversation had been told of and could not read; the fourth was a recital `scored` counted as wrong, and counted
unanswered in the second run only because its words came in another order.

The third run answered "Is the tank full?" from the rule and the fact told beside it. Its one wrong answer is that
same recital, "What is the largest animal on Earth?", without the "I remember:" line recall put first in the second
run: it is counted wrong or unanswered by the order recall gives, not by what was answered.

The fourth run read three sentences more, each held as main misreads it: the engineers taken for the hiring ("The
company hired three engineers in May."), "animal" for a happening ("The blue whale is the largest animal on Earth."),
the working done by the listener ("Guido van Rossum began working on Python in the late 1980s."). A telling of a
happening was refused before, whatever its reading, so `understood_whole` counts a sentence held, not one read right.
Its wrong count is 0 because the largest-animal recital began "I remember:" again.

The fifth run composed what no taught frame read. Nine sentences more were held (16 of 33), and one question more was
answered right: "Is Paris the capital of France?", told and asked through the same composed reading. Two runs before
it stopped: a composed question that named only a thing already found asked nothing, and the code that answers it
and the code that says what is not known of it each took it for a question (fixed, with a composed meaning of known
things alone no reading at all). Of its three wrong answers, one is a false No: "Is chlorophyll green?" read by the
frames only as whether chlorophyll is the colour green (no reading has green as a quality), which the closed world
denies; the told sentence was held whole this time, where it had been left in part, so the world was closed on it.
The other two are composed questions answered with what memory holds of their subject ("Each company is an
institution." for "How many engineers did the company hire?"): the composer lost what was asked, and a recital that
does not begin "I remember:" is counted wrong. Composing stays off by default.
