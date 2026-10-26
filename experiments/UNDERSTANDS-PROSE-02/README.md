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

**Runs on main:**

- **2026-10-21, stopped (`terminal.txt`).** Texts 1 to 43 read and asked; then 14 hours on text 44's third sentence
  ("To handle changes in electric current caused by weather variations, ..."), stopped by hand. The transcript was
  written only at the end, so what it did is what it printed, saved to `results/terminal.txt` (scored below). The
  stall: `derived_reader._least_claimed` tried every choice of every sense (lab notebook 2026-10-22 (34)), fixed.
  The harness now writes each sentence and question as it is done.
- **2026-10-22, texts 45 to 50** (`--from 45`, on the code before the fix; transcript
  `20261022T113957Z_transcript.jsonl`, log `run_from45.log`): stopped at 47 of 70, in text 48, when the session
  running it ended. Texts 45 to 47 are taken from it.
- **2026-10-22, text 44 on the fix** (`--from 44 --to 44`, record `20261022T120503Z`, log `run_44.log`): the sentence
  that ran 14 hours read in 410.7 s (not taken in). 2/5 sentences, 0/8 right, 1 wrong; nothing written.
- **2026-10-22, texts 48 to 50 on the fix** (`--from 48`, record `20261022T122438Z`, log `run_from48.log`): 6/8
  sentences, 0/16 right, 1 wrong; nothing written. One sentence stopped the conversation (text 50, "No person shall be
  elected to the office of the President more than twice, ..."): `ValueError: a meaning states the same fact twice`.
  It names one office three times; each description, bound to the known office it picks out
  (`Conversation._telling`, `Meaning.bound`), makes the same fact, and the meaning built of them refuses it.
- **2026-10-22, text 50 again, on the fix for that** (`_telling` holds each fact once; `--from 50 --to 50`, record
  `20261022T131110Z`, log `run_50.log`): 2/2 sentences (the one that stopped read in 487.0 s, its "No" held as the
  electing `false`), 0/5 right, **2 wrong**, nothing stopped, nothing written. Both wrong are "Yes. A The office is
  part of a president.", to "How many times can a person be elected to the office of the President?" and "Can a person
  be elected to the office of the President three times?": `Conversation.asked` answered the question's description
  of the office (`part_of(office_1, president)`, held) as if it were what was asked; only the description's
  `instance_of` is passed over as what picks the office out. The log has one fault: the live recall of the second
  sentence (297.6 s to read) was sent at 09:22:15 and timed out at 09:27:13 (`TimeoutError`, two queries), the
  reader having held the event loop past the store's 60 s command timeout. Not counted in the result below, which
  keeps each text from its first finished run.

**Result, all 50 texts** (each text from the one run that finished it: 1 to 43 from `terminal.txt`, as the run
scored them then; 44 to 50 from their transcripts; every reply with a word answer scored again by `said`, which
changed none, and none of the printed replies cut at 200 characters left one undecided; `results/all_50_scored.json`):

| Measure | Result | 95% interval | Bar |
|---|---|---|---|
| Sentences understood | 210/431 = 48.7% | 44.0% to 53.4% | ≥ 90% |
| Questions answered right | 43/456 = 9.4% | 7.1% to 12.5% | ≥ 80% |
| Questions answered wrong | 43/456 = 9.4% | 7.1% to 12.5% | ≤ 2% |

Stopped: 1 told (text 50), 0 asked. **All three bars fail.** The store was not written to by the runs of 44 and of 48
to 50 (their checks); the two stopped runs never reached that check.

| Kind | Sentences | Right | Wrong |
|---|---|---|---|
| Encyclopedia | 26/48 | 6/48 | 7 |
| Science | 29/50 | 18/49 | 6 |
| History | 23/48 | 4/50 | 6 |
| Mathematics | 21/43 | 3/48 | 6 |
| Webpage | 31/50 | 1/45 | 0 |
| Code documentation | 33/48 | 6/48 | 5 |
| Paper abstract | 17/36 | 2/46 | 1 |
| Security log | 0/50 | 0/39 | 2 |
| News | 20/43 | 1/48 | 9 |
| Premises and a rule | 10/15 | 2/35 | 1 |

**The 43 wrong answers.** Every one answers a question asking what, who, which or when; no yes or no was answered
wrongly.
- **21 say the kind asked for back** ("Which mountains bound South Asia in the north?" "Mountain."; "In which journal
  did the engineers publish?" "Journal."). Traced on text 44's record: the reasoner settled nothing, and
  `Conversation.asked` answered the question's fact `instance_of(?v2, journal)` alone, by the journal held from the
  telling (`Answer("journal_1", "instance_of", ("journal",))`), never asking whether the engineers published in it;
  said by its kind, it is the question's own word. A question is all it asks at once (`_held_ways`); `asked` still
  answers one fact at a time.
- **14 answer a question asking what or when "Yes."** ("When was the Siege of Baghdad?" "Yes."; "In whom is the
  executive Power vested?" "Yes. The power is vested.").
- **8 others**: "also called" answered by what the thing is ("A test case is a kind of legal action."), and things
  found by their kind alone ("Movement.", "Supply.").

**The split (2026-10-22, the owner's decision; `split.py`, `split.json`).** From here the 50 texts are two halves:
25 fixed against (`--half fit`: 222 sentences, 231 questions) and 25 kept unseen (`--half held`: 209 sentences, 225
questions), each kind's texts drawn by seed 20261022, three and two by turns, so every kind has two or three in each.
Texts 44 and 50, whose answers were traced before the split, are in the half fixed against by rule. Every text's run
had been seen as printed before the split: the half kept unseen is unseen in that none of its answers is traced, and
it is run once, after the fixes. On the runs above, the half fixed against was 109/222 read (49.1%), 20/231 right
(8.7%), 25/231 wrong (10.8%); the half kept unseen 101/209 (48.3%), 23/225 (10.2%), 18/225 (8.0%).

**Fixed against the half fixed against** (`Conversation.asked`, tests in `tests/test_conversation.py`, each failing on
the code before): what a question asks for, described by more than one fact, is not answered by one of them (the
"Journal." answers); a question asking for something is not answered yes or no by a fact naming nothing it asks
(text 50's "Yes. A The office is part of a president."); a yes or no is of all a question says (yes every part held,
no one part denied). UNDERSTANDS-PROSE-01 on main after it (`20261022T150121Z`): 33/33, 36/37, 0 wrong, as before.
The half fixed against on main after it (`20261022T152323Z`, log `run_fit.log`): 110/222 read (49.5%), 21/231 right
(9.1%), **8/231 wrong (3.5%, 95% 1.8% to 6.7%)**, from 25; nothing stopped. Its store check **failed**: a question's
reasoning, reaching the abstract reasoning engine, was stored and learned from although the conversation remembers
nothing (`memory_hot` +3, with their learning). Main holds nine such memories from PROSE-02's runs (four of
2026-10-21, two of the `--from 45` run, three of this one: `user_id` `understands_prose_02_*`, "Learning: Abstract
reasoning ..."); whether to delete them is the owner's.

**Fixed after it:** a conversation's reasoning carries `remembers` (`ReasoningContext.remembered`): one that
remembers nothing has its reasoning neither stored nor learned from; a thing held under a name of its own is said by
its name, not its kind (`_kind_of`: West Africa was "Geographical area."); an answer only saying the kind the
question already names is none (`_asked_of_events`: "Base class.", "Objective."); "whom" is never a subject (the
grammar). Tests: `tests/test_conversation.py`, `tests/test_grammar.py`, `tests/test_abductive_reasoning.py`, each
failing before. UNDERSTANDS-PROSE-01 on main after (`20261022T190909Z`): 33/33, 36/37, 0 wrong, nothing written.
Texts 8, 13, 14, 28 and 31 again (`--texts`, `20261022T191951Z`): right 10 to 11 ("Where did the Tichitt Tradition
flourish?" "West africa."), wrong 7 to 4, nothing written. Still wrong there: "whom" did not change "Whom did Cyrus
defeat?" (still `done_by` twice: the link learned for "defeat"'s second place), "also called" read as `isa`, "test
case" taken in WordNet's legal sense, "Movement." for what brings the rainy seasons.

**The half fixed against on main after the reading fix's steps 1 to 3 (2026-10-26, `20261026T145920Z`, log
`results/run.log`; lab notebook (54)):** 103/222 read (46.4%, 95% 40.0% to 53.0%), 18/231 right (7.8%), **5/231 wrong
(2.2%, 95% 0.9% to 5.0%)**, nothing stopped, nothing written to the store; against `20261022T152323Z` (110, 21, 8) the
same within the intervals: what raised the PMB's dev split (each word's category chosen beside the words around it,
links from the sentences derived by hand) does not show on prose. Its first try that day was stopped by hand
(`20261026T134149Z_transcript.jsonl`, log `run_fit_stalled_20261026.log`): two sentences stopped the conversation ("a
meaning states the same fact twice", `Conversation._told`), and "In mountainous areas, heavy precipitation is possible
where ..." , read as asking, sat over half an hour saying its "I do not know" (`derived_reader._compositions` counting
through every part of the meaning's kinds); both fixed (`bd00af85`) before this run. The longest sentence read took 818 s
(65 words; its chart alone 346 s, the same without the derivations).

**Why so few are right** (the half fixed against, its transcript): of 231 questions, 78 had the sentence holding
the answer read and the question read, and the two never met, the question read otherwise than its telling ("the
hashlib module" as a quality, "What time did Delaere post?" with Delaere done to, "When was calculus formulated?" as
a state, frame markers such as `⟨2⟨bound` left in a question's meaning); 55 yes or no found nothing either way; 42
had the answer's sentence unread; 26 questions were not read. Of 112 sentences unread, 65 had every word read but not
how they fit, 40 were about a name nothing names, and the security logs' 20 lines are not read as logs.

Texts 45 to 47 were read on the code before the stall fix, 44 and 48 to 50 on it; the fix keeps the same choices
(lyric_dev, 147 of 147), not yet compared call for call on main. The runs of 44 and 48 to 50 read the coordinator with
another session's uncommitted changes to expectations and goals in it, none on the reading or answering path.
