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

**Results:** `results/<UTC timestamp>.json` and `.md`, the transcript beside them, and `results/run.log`.

**Runs on main:**

| Run | Code | Sentences understood | Right | Wrong | Written |
|---|---|---|---|---|---|
| `20261014T190758Z` | composition (adjuncts) | 4/33 | 8/37 | 4/37 | nothing |
| `20261016T002042Z` | + no closed world on what was not taken in | 4/33 | 8/37 | 0/37 | nothing |

Of the four wrong answers in the first run, three were the strong disjointness assumption about a subject the
conversation had been told of and could not read; the fourth was a recital `scored` counted as wrong, and counted
unanswered in the second run only because its words came in another order.

