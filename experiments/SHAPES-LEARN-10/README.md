# SHAPES-LEARN-10: WordNet's nouns, taught after the seven lessons, with the engine as it now is

The gate before all of WordNet goes into the main model: SHAPES-LEARN-08 again, on the same uniform 3,000-record
sample, after english_01–07 and the engine's changes since. The check that English's "a" and "an" are said right
(from SHAPES-LEARN-09) is run on every sentence said.

**First run (2026-09-29, run `20260929T222602Z`, 17/18).** It ran on the engine as it stood when it started: the
seven lessons, the word-use model kept as items arrive, and saying's shapes counted where they are written. The
grammar lessons 08 and later, and the engine changes they brought, came after.

**Taught:** the seven lessons, none refused. Then the sample:
- 1,605 facts, one refused;
- all 75,833 word-class notes of WordNet's vocabulary;
- 1,294 of the 1,421 nouns said and learned, none refused.

**Checked:**

| Check | Result |
|---|---|
| Said as English says it: no name or uncounted word after "a", no counted word bare, "a"/"an" by the next letter | yes |
| Every noun taught reads in "What is a/an <word>?", never taught with it, to the sense taught | 1,293/1,294 |
| The reasoning authority answers yes to facts taught (sampled) | 200/200 |
| Pairs WordNet does not relate answered yes | 0/200 |
| Facts taught, said, read back to themselves | 200/200 |
| Every sentence of the seven lessons still reads | yes |
| The main store is untouched | yes |

**The one that failed** is "What is a stove?". It reads to the lessons' `stove` ("The stove is hot."), not to
WordNet's other sense of the word, a heater. A word already held is read in the sense it was taught. This is the known
limit of held words with another sense ("Bark is a sailing vessel."), shown here by a question.

**The cost:** 4,101 s. As in SHAPES-LEARN-08, most of it is the word-class notes, written one at a time. The run
record's figure of 61 h for all of WordNet divides that one-time stage by the sample and is wrong, as SHAPES-LEARN-08's
README explains.

**Second run (2026-09-29, stopped, no record).** Started with sixteen lessons, each learned with none refused, and
stopped by hand in the WordNet sample after 86 minutes: lessons 17 and 18 and the engine changes they needed were built
while it ran, so its result could no longer gate anything. The experiment now takes every lesson file it finds.

**Third run (2026-09-29, stopped, no record).** Started 22:20 with english_01–18 on the engine as it then stood; all
eighteen lessons were learned, none refused. Stopped by hand after 2 h 47 min, still teaching the WordNet sample: the
engine it had loaded was changed while it ran, by the mathematics lessons (english_24–26) and what they needed. Those
changes include how the reader keeps readings of a span, and they reach every sentence, so its result could no longer
gate anything. It was also running far slower than the first run, which is what the chart change addresses: numeral
phrases that join words without a word of their own made the reading of a long span grow with every way of bracketing
it.

**Fourth run (2026-09-30, 06:27–10:00 UTC, failed: the gate did its job).** All twenty-six lessons (english_01–26,
with the mathematics lessons), none refused; the seeded sample (1,333 nouns' facts, 162 named things', 1,505
definitions), 1,208 nouns said and learned, none refused.

| Check | Result |
|---|---|
| Said as English says it | one counted word bare ("Wing is an airfoil."); "Hepatitis A" flagged against the letter, a name |
| Every noun taught reads in "What is a/an <word>?", never taught with it | **723/1,208** |
| The reasoning authority answers yes to facts taught (sampled) | 199/200 |
| Pairs WordNet does not relate answered yes | 0/200 |
| Facts taught, said, read back to themselves | 200/200 |
| Every sentence of the lessons still reads | yes |
| The main store is untouched | yes |

**Why 723.** english_24 held "Two and three quarters is a number." beside "Three and a half is a number."; learning
the one against the other set "three" where "a" stood, and so taught that the word "a" is the number 1. A word that
names something is no longer a word that only builds sentences, so the WordNet pass took "A quoin" (article and all)
as the name in "?slot0 is a ?slot1." for 1,251 nouns, where "quoin" alone was needed: "What is a quoin?" then read
"quoin" as a word never met. "What is a pump house?" read "a" as 1 as well. The sentence is gone from english_24,
"a" and "an" build sentences only at every lesson, and the lesson test asserts it. Reproduced in memory on the gate's
samples, three more causes came to light and were fixed (`docs/research/SHAPES_CHANGE_MAP.md` §11f): a formula's
letters counted as named words ("a + b" named "a", so "A is a blood group." made "a" a filler mid-pass); a frame
learned as written in another shape ("Every ?slot0 is a ?slot1." beside "… an ?slot1.") put its nouns in a kind of
their own; and English words were read as formulas ("pip" as π·p, "cost" as cos t). After them, in memory, 1,218 of
1,240 nouns read on one sample, and every miss is a word the lessons hold in another sense.

**Next:** the lessons taught again into the sandbox and the main model, then this gate again.

**Fifth run (2026-09-30, `20260930T111909Z`, 11:19–14:12 UTC, 34/37).** All twenty-six lessons, none refused; the
sample (1,375 nouns' facts, 157 named things', 1,468 definitions), 1,254 nouns said and learned, none refused.

| Check | Result |
|---|---|
| Said as English says it | one counted word bare: "Wing is a stage." |
| Every noun taught reads in "What is a/an <word>?", never taught with it | **1,238/1,254** |
| The reasoning authority answers yes to facts taught (sampled) | 198/200 |
| Pairs WordNet does not relate answered yes | 0/200 |
| Facts taught, said, read back to themselves | 200/200 |
| Every sentence of the lessons still reads | yes |
| The main store is untouched | yes |

**The sixteen misses** are words the lessons hold in another sense. "What is a flower?" reads to the lessons'
flower, not WordNet's "time period" sense taught here, and likewise night, bone, drive, kingdom, tank, fire,
barrier, top. "What is an omnivore?" reads to one of WordNet's two senses of it, both taught. **"Wing is a stage."**:
the lessons hold "wing" only as "wings" ("A bird has wings."), and the singular is said with no article. The fourth
run's "Wing is an airfoil." is the same fault. **198/200**: which two were not held is unknown. The sample harvested
again in another process comes out differently (1,397/145/1,458 against the run's 1,375/157/1,468), so the probe
cannot be repeated. The harvest has to be made the same in every process.

**What the gate did not score.** Read-only on the sandbox the run left, the store's view shows WordNet's senses
displacing the lessons' words: "All fish can swim." reads as food fish or aquatic vertebrate fish, "A trillion is a
number." two ways, and "A Slovenian is a person." two ways, so saying avoids "person" and says "A Slovenian is an
one.". The reader reports every meaning of a sentence; the listener needs one, and choosing it "by the situation
and the scores" was never built. All of WordNet would do this to the everyday words, the ones with the most senses.
WordNet waits for the sense choice, and this gate should check sentences the lessons never taught after WordNet is
on top of them.

Run: `./venv_lyric/bin/python3 experiments/SHAPES-LEARN-10/experiment.py` (empties the sandbox first; about 70
minutes).
