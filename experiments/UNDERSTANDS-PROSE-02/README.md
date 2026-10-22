# UNDERSTANDS-PROSE-02: reading prose nobody fitted the reader to

**Claim.** UNDERSTANDS-PROSE-01's, on texts held out from all the work done on it. The substrate reads prose as its
sources write it and reasons over what it read. It understands the sentences, answers what they say and what follows
from them, and does not answer wrongly what it did not understand.

**Why.** UNDERSTANDS-PROSE-01 passed on 2026-10-21 (`20261021T184936Z`): 33/33 sentences, 36/37 questions right, none
wrong. Two things keep that from showing that the substrate reads prose:

- **The texts were fitted.** Each of its misses was traced and fixed against those same texts and questions over the
  days before. The fixes are rules of English, not its sentences remembered, but a set the fixes were made against no
  longer measures what they do on text never seen.
- **It is too small to say.** 0 wrong of 37 has a 95% interval of 0% to 9.4%, so the bar of 2% wrong cannot be shown
  by it. Its texts are also written plainly: about 8 words a sentence, where what is published runs to 25 or more.

**What it does** (`experiment.py`, on main, starting no substrate):

- **The texts** (`texts.json`): 50 texts taken as they are published, drawn by a fixed seed (20261021) and cut to
  their opening ten sentences (`draw.py`). The ten kinds are 01's; the topics 01 is about are left out.

  | Kind | Texts | Sentences | Questions | Drawn from | Licence |
  |---|---|---|---|---|---|
  | Encyclopedia | 5 | 48 | 48 | Wikipedia's Vital articles (level 3): geography, everyday life, arts, society, people, technology, health, philosophy | CC BY-SA 4.0 |
  | Science | 5 | 50 | 49 | the same, science | CC BY-SA 4.0 |
  | History | 5 | 48 | 50 | the same, history | CC BY-SA 4.0 |
  | Mathematics | 5 | 43 | 48 | the same, mathematics | CC BY-SA 4.0 |
  | Webpage | 5 | 50 | 45 | GOV.UK's guides | Open Government Licence v3.0 |
  | Code documentation | 5 | 48 | 48 | the Python standard library's modules (deprecated, removed and private ones left out) | PSF Documentation Licence |
  | Paper abstract | 5 | 36 | 46 | arXiv's 200 newest in machine learning, populations and evolution, planetary astrophysics and economics | CC0 |
  | Security log | 5 | 50 | 39 | ten lines from a drawn line of Loghub's OpenSSH (three) and Linux (two) logs | Loghub, research use |
  | News | 5 | 43 | 48 | Wikinews' 500 newest published articles | CC BY 2.5 |
  | Premises and a rule | 5 | 15 | 35 | the United States Constitution as the National Archives transcribes it: chosen, not drawn, as rules a question can apply (who may hold an office, who may vote, how long a term runs) | public domain |

  Each text keeps its source (a Wikipedia or Wikinews page by its revision) and its licence. What was cut is cut by
  rule, never by hand: lists, tables, "See also" boxes, image lines and datelines are left out, and only word joiners,
  non-breaking spaces and empty parentheses (where a pronunciation was) are cleaned. A module documented in fewer than
  three sentences (urllib, a list) is replaced by one drawn by a second seed. What it was drawn from, as it stood on
  2026-10-21, is kept in `sources/` (not pushed); drawing again draws the same texts.
- **The questions** (`questions.py`): 456, written from each text before any of it was read by the substrate. 313 ask
  what, who, when or how many; 114 are answered yes and 29 no. A "no" is asked only where the text says otherwise.
  Some ask what follows: Sri Lanka is in Asia, since it is a state of South Asia and South Asia is a sub-region of
  Asia; a person of twenty may not be a Representative, by the age the Constitution sets. `assemble.py` checks that each
  answer asked for is said in its text (a log's counts are counted from its lines) and that no question says its own
  answer.
- **Told, asked and scored** by UNDERSTANDS-PROSE-01's harness (`main` in its `experiment.py`), unchanged: each text
  told sentence by sentence in a conversation of its own held not to remember, then asked. An answer's word is found
  in the reply only where a word of the reply begins, and a number only whole: the "5" in 10.0.0.5 or in 47068 does
  not say five (since 2026-10-21; 01's last run scores the same under it).
- **Sized before the run:** 431 sentences and 456 questions put each fraction within about five points either way
  (95%). Each is reported with its interval. Were none answered wrong, wrong would be known to be under 0.9%.
- **Checks** that the store was not written to, by the server's own counters.

| Bar (fixed before the run, as 01's) | |
|---|---|
| Sentences understood | ≥ 90% |
| Questions answered right | ≥ 80% |
| Questions answered wrong | ≤ 2% |

**Before the run:** eight sentences of a Wikipedia lead not in the set (Volcano), 10 to 42 words long, read on
lyric_dev in 1 to 26 seconds each; two of them were taken in, one of those misread ("Resultings are A volcano"). The
run should take one to three hours. The harness was checked on lyric_dev with one of 01's texts; nothing in this set
was read before the run.

**Run** (from the Lyric folder):

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/UNDERSTANDS-PROSE-02/experiment.py
```

**Results:** `results/<UTC timestamp>.json` and `.md`, the transcript beside them, and `results/run.log`, as 01's.

**Runs on main:** none yet.
