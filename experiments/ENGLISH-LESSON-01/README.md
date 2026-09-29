# ENGLISH-LESSON-01 — the substrate's first lesson in American English, on an empty store

**Finding (2026-09-26, run `20260927T023716Z`): it learned almost nothing from the lesson.** Its reader read 2 of
the 11 sentences, and both readings are wrong. What looks like answering afterwards is recall of the stored
sentence that sounds most like the question.

**The lesson:** Illinois Early Learning Project (University of Illinois at Urbana-Champaign), "Language Arts Lesson
Addressing Benchmark 1.C.ECa: Describe familiar people, places, things, and events"
(https://illinoisearlylearning.org/ields/ields-plans/adapting-1ceca/). The teacher describes her shoe to the class;
afterwards she asks the children questions. The substrate was taught the teacher's 11 sentences word for word,
through the one teaching path (`TeachingPass`, sentence-only records read by the substrate's own reader). Nothing
was pre-cut into facts for it.

**How it was run:** on the store as wiped on 2026-09-26, without booting the whole system, so nothing but the
lesson went in (a full boot writes its own startup knowledge). The domain authority was therefore not running. Web
look-ups were off during the questions, so an answer could only come from the lesson.

## What happened

- **Read 2 of 11.** "My shoe is black and has laces." became `my shoe is black` and `my shoe is has laces`.
  "You will have a chance to paint…" became `You / will have / chance to paint pictures…` and was refused at
  admission. "This is my shoe.", "It is black.", "Here are the laces.", "They are red." and six more did not read.
- **Held:** two links, both wrong: `my_shoe isa black` and `my_shoe isa has_lace`. It classed `black` as a noun.
  It has no class for any other word in the lesson, including `is`, `the`, `my`, `it` and `they`. The nine unread
  sentences are kept word for word as memories tagged `told_but_unread`.
- **Asked:**

| Question | Reply |
|---|---|
| What color is the shoe? | "I remember: This is my shoe. / The shoe is a black. It is has lace. / I hold nothing for color." |
| Does the shoe have laces? | "I remember: This is my shoe. / The shoe is a black. It is has lace. / I hold nothing for have laces." |
| What color are the laces? | "I remember: Here are the laces." (the answer, "They are red.", is in memory) |
| What color is the sole? | "I remember: Look, I painted the sole of my shoe here; it is brown." |
| Where do the shoes come from? | "I remember: Here are the laces." |
| Is the shoe red? | "I hold nothing for red." |
| What is a shoe? | "I remember: This is my shoe. / A shoe is a black. It is has lace." |
| What color are your shoes? *(lesson)* | "I remember: I'm going to choose the black, brown, and red paints to create my shoe." |
| Where do you keep your shoes at your house? *(lesson)* | "I remember: I get my shoes from my closet each morning. …" |
| Did someone help you put on your shoes this morning? *(lesson)* | the same sentence |
| Where did you get those shoes? *(lesson)* | "I remember: Here are the laces." |

## What it shows

It cannot read English it does not already know, so it cannot learn English by reading English. Its reader is
hand-written patterns that depend on knowing words' classes, and on an empty store it knows none: not even "This
is my shoe." reads. A preschool lesson also assumes the children already speak: a three-year-old arrives with words
and working grammar, and the substrate arrives with neither.

## Run

```
./venv_torin/bin/python3 experiments/ENGLISH-LESSON-01/experiment.py
```
Run on an empty store to repeat the first lesson; on a store that has been taught, it measures that store.
