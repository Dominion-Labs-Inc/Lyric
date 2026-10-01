# SHAPES-LEARN-09: function words, names and words without "a", taught; new words said as words like them are

**Finding (2026-09-29, run `20260929T215535Z`, 18/18).** Taught english_01 to english_07 through the one teaching
path in the sandbox, the substrate reads sentences it was never taught that use function words, names, words used
without "a" and kinds of people written with a capital. It also says a word it never held the way words used like it
are said, on a uniform sample of WordNet's nouns (the 3,000-record sample of SHAPES-LEARN-08). The two faults
SHAPES-LEARN-08 showed are gone: names said after "a", and words that take no "a" said with one.

**Taught:** the seven lessons, none refused, and every taught sentence still reads to its meaning. english_07 is 101
pairs:
- names, met first in known sentences;
- words used without "a";
- "is a kind of";
- plural-only words;
- kinds of people written with a capital ("An American is a person.") beside names that end as they do ("Japan is
  a country.").

**Read, never taught:**

| Probes | Result |
|---|---|
| Sentences with english_06's function words ("The girl who owns the bike is tall.", "Birds never swim.") | 15/15 |
| Sentences with names, words without "a" and kinds of people ("Mississippi is a river.", "Is Rex a German?", "A Bostonian is a person.") | 9/9 |

**Said, 1,262 of WordNet's 1,404 nouns in the sample.** Each was said through the teaching pass's own saying, in the
use the view finds for it:

| Use | Words | Said, for example |
|---|---|---|
| counted | 1,144 | "A sudoku is a puzzle.", "An amphisbaena is a mythical monster." |
| name | 154 | "Lycoperdaceae is a fungus family.", "Palm Sunday is a Christian holy day." |
| used without "a" | 94 | "Imperialism is a political orientation.", "Sausage meat is a kind of meat." |
| plural only | 4 | "Fire tongs are tongs." |
| held already | 8 | "Meat is a food.", "A pen is a writing implement." |

Checked on every sentence said:
- no name, and no word taken to go without "a", after "a";
- no counted word said bare;
- "a" and "an" as the letter after them asks.

**Faults said rightly, 5/5:**
- "Thiosulfil is a sulfa drug.";
- "Paleoanthropology is a kind of vertebrate paleontology.";
- "Fire tongs are tongs.";
- "An Asian is an inhabitant.";
- "A Slovenian is a person.".

The check takes "Every Asian is an inhabitant." as well as "An …": both are English for the same meaning, and which
ranks first depends on how much each frame has been used.

**Nothing written:** reading and saying wrote nothing, and the main store did not change (192,294 rows before and
after).

**The first run** (`20260929T200222Z`, 16/16) passed its checks, but its sayings showed a fault the checks did not
cover: a capitalized word for a kind of people was taken as a name and lost its "a" ("Asian is an inhabitant.",
"Slav is a person."). The same fault left most of its 44 unsaid names unsaid, as in "Bostonian is an American".
Fixing it (`SHAPES_CHANGE_MAP.md` §11f) exposed three more faults, all fixed before the second run:
- **Articles inside names.** The learner took "An American" as one name in "?slot0 is a ?slot1.", "An eel" and
  "A painting" too, names that reading would never take as new.
- **"every" as a third shape.** Once frames were held as written, "every" was found as a shape of "an", and "An
  peludo is an armadillo." was said.
- **Lost capitals.** A shaped capitalized word lost its capital ("Bostonians are americans.").

The second run (`20260929T202704Z`, 18/18) adds the checks for these faults.

**The third run** (`20260929T215535Z`, 18/18) follows fixes for two faults SYSTEM-CONVERSATION-01 found, and
for a check that now also judges the object after "is":
- **Kinds.** A kind statement names a kind in each place (the owner's choice). Since english_03's phrases, "a
  glintbsrtp bird" there had read as some bird that is glintbsrtp.
- **Plurals.** Saying counts shapes over the concepts whose plural is held. english_07's "kindness" and
  "scissors" had sunk the `s` plural, so saying gave "Vexbsrtpes".

The sample's size changes a little from run to run, because the harvest is not fixed by its seed alone.

**Limits:**
- **Kinds of people whose ending the lessons do not decide** are still said as names: "Montanan is an American."
  ("-an" also ends "Japan"), "Alcaic is a poem.", "Slav".
- **Held words with another sense** are said as the sense taught: "Black is a person.", "A wing is a stage.".
- **A word held only after "an"** is of another kind than the words held after "a" in the same place. "American",
  held only in "Tom is an American.", is not said in "A Bostonian is an American.". That sentence goes unsaid, not
  said wrongly.
- **Kept whole for now.** Six english_04 sentences are now held as holophrases ("A painting is pretty.") and two
  as frames around their nouns ("A cake is ?slot0."). The learner no longer makes names like "A painting". They
  read as taught.
- **Unsaid:** 127 of the 1,401 nouns, most because no frame taught says them in their use, such as a counted word
  under an uncounted one ("A sausage is meat.").

Run: `./venv_lyric/bin/python3 experiments/SHAPES-LEARN-09/experiment.py` (empties the sandbox first; about 70 s
after the boot).
