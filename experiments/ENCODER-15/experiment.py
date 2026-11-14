#!/usr/bin/env python3
"""ENCODER-15 — A RETRIEVAL MEASURE THAT CANNOT SATURATE: FIND THE WORD FROM ITS DEFINITION.

The ENCODER series settled on "MiniLM stays" on 2026-09-22, and its own README says why that
verdict cannot be trusted on the question that matters:

    "The retrieval task saturates: MRR is 0.750 for both encoders at every corpus size, because
     each subject has two facts and both contain the subject, so rank 1 or 2 is forced.
     ENCODER-02's H1 and H3 are therefore NOT TESTABLE with this task and should not be read as
     evidence either way. A retrieval measure with one correct answer per question is needed
     before the scale question can be answered."

WHY THE SATURATION IS INTRINSIC, and what gets rid of it. Every question in that task names its
subject and every answer contains it, so finding the subject is most of the job and six facts per
subject would not fix it -- a subject-only matcher still lands in the top k. The fix is a question
that does not hand over the answer's name. Asked the other way round it is the task a dictionary
performs: here is a definition, which word is it? Nothing in the question names the word, there is
exactly one right answer, and it competes against every other word in the sample, so the floor is
1/N rather than 1/2.

TWO TASKS, because lexical overlap is a confound and the honest way to handle it is to measure
with and without:

  * TOGETHER   the definition's terms and the fact hold the same words. An encoder can win on
               weighting alone -- which is a real skill (`idf` is taught, not pretrained) but is
               not relating.
  * HELD OUT   the fact keeps half of a word's defining terms and the question asks with the OTHER
               half. Word overlap is zero by construction, so anything above the floor is the
               encoder relating terms it was taught stand together.

A WORD-OVERLAP BASELINE runs beside the encoders in both: on TOGETHER it is strong and says how
much of the task is lexical; on HELD OUT it is at the floor and says what relating is worth.

TAUGHT FROM THE LIVE STORE. `_encoder_lib.REAL_FACTS` is 30 hand-written facts, and the verdict was
set when the substrate held a fraction of what it holds now -- 584,753 admitted propositions and
146,732 words recorded whole as of 2026-11-14. The native encoders are taught from propositions
drawn from `lyric_db` at rising volume, which is the only way ENCODER-02's question -- does a taught
encoder improve as the substrate is taught? -- can be asked at all.

  H1  On HELD OUT, every encoder beats the word-overlap floor. An encoder that does not is doing
      nothing a string comparison does not already do.
  H2  The measure DISCRIMINATES: best − worst p@1 > 0.05 on HELD OUT.
  H3  SCALE, asked of EACH native encoder separately and read against the share of the corpus the
      task itself is. The task's own propositions must be taught -- an encoder cannot encode words
      it was never told -- so at the smallest volume the task is nearly half of everything the
      encoder knows, and a score there flatters it. Only the largest volume, where the task is
      under one per cent, is a fair reading. This is what ENCODER-02 could not test at all.
  H4  At the largest volume, a native encoder is within 0.05 p@1 of MiniLM on HELD OUT. Closing to
      a tie is what would justify retiring a pretrained model whose weights nothing taught.

Reads only: draws propositions from the store and teaches encoders in this process. Writes nothing
to any store. Its own record goes under results/.
"""
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments"))

from _encoder_lib import MiniLM, Run, SubstrateEncoder, StructuralEncoder, cos_for  # noqa: E402

PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
STORE = os.environ.get("POSTGRES_DATABASE", "lyric_db")
#: Defining terms a word needs to be usable: half go in the fact, half in the question.
TERMS_EACH = 6
#: How many words are in the sample. The floor is 1/WORDS, so this sets how far from chance the
#: measure can read.
WORDS = 300
#: How many propositions the native encoders are taught, in order, to read the scale question.
VOLUMES = (2_000, 20_000, 200_000)
SEED = 15


def asked(sql):
    out = subprocess.run([PSQL, "-p", "5433", "-U", "stefan", "-d", STORE, "-At", "-F", "\t", "-c", sql],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr[:400])
    return [line.split("\t") for line in out.stdout.splitlines() if line.strip()]


def taught_propositions(limit):
    """`(subject, relation, object)` as the store holds them, from the propositions it admitted."""
    rows = asked("SELECT metadata->>'reading' FROM memory_hot.memory_hot "
                 "WHERE tags @> '[\"admitted_proposition\"]'::jsonb "
                 f"AND metadata->>'reading' LIKE '%|%|%' LIMIT {int(limit)}")
    props = []
    for row in rows:
        parts = [p.strip() for p in row[0].split("|")]
        if len(parts) == 3 and all(parts):
            props.append((parts[0], parts[1], parts[2]))
    return props


def the_words():
    """Words with at least TERMS_EACH things their definition is written with, from the store."""
    rows = asked(
        "SELECT subject, string_agg(object, '|' ORDER BY object) FROM ("
        "  SELECT DISTINCT split_part(metadata->>'reading','|',1) AS subject,"
        "                  split_part(metadata->>'reading','|',3) AS object"
        "    FROM memory_hot.memory_hot"
        "   WHERE tags @> '[\"admitted_proposition\"]'::jsonb"
        "     AND split_part(metadata->>'reading','|',2) = 'defined_with'"
        ") s GROUP BY subject HAVING count(*) >= " + str(TERMS_EACH) + " ORDER BY subject")
    out = []
    for row in rows:
        if len(row) != 2:
            continue
        subject, terms = row[0], [t.strip() for t in row[1].split("|") if t.strip()]
        if " " in subject or len(terms) < TERMS_EACH:
            continue
        out.append((subject, terms[:TERMS_EACH]))
    random.Random(SEED).shuffle(out)
    return out[:WORDS]


def the_two_tasks(words):
    """(facts, questions) for TOGETHER and for HELD OUT, over the same words."""
    together_facts, together_questions = [], []
    heldout_facts, heldout_questions = [], []
    half = TERMS_EACH // 2
    for subject, terms in words:
        said = " ".join(t.replace("_", " ") for t in terms)
        fact = f"A {subject} is defined with {said}."
        together_facts.append(fact)
        together_questions.append((said, fact))

        kept = " ".join(t.replace("_", " ") for t in terms[:half])
        asked_with = " ".join(t.replace("_", " ") for t in terms[half:])
        held = f"A {subject} is defined with {kept}."
        heldout_facts.append(held)
        heldout_questions.append((asked_with, held))
    return (together_facts, together_questions), (heldout_facts, heldout_questions)


class WordOverlap:
    """THE FLOOR, NOT AN ENCODER: how much of the task a string comparison already does."""

    def learn(self, props):
        return self

    def encode(self, text):
        drop = {"a", "an", "the", "is", "defined", "with"}
        return {w for w in text.lower().strip(".").split() if w not in drop}


def overlap_cos(a, b):
    return len(a & b) / (len(a | b) or 1)


def retrieval(name, enc, questions, facts):
    """p@1, MRR and the mean margin over the best wrong answer. One answer per question."""
    cos = overlap_cos if isinstance(enc, WordOverlap) else cos_for(enc)
    vectors = [(f, enc.encode(f)) for f in facts]
    at1, rr, margins = 0, 0.0, []
    for question, target in questions:
        qv = enc.encode(question)
        scored = sorted(((cos(qv, v), f) for f, v in vectors), key=lambda t: -t[0])
        ranked = [f for _, f in scored]
        position = ranked.index(target) + 1 if target in ranked else len(ranked) + 1
        at1 += (position == 1)
        rr += 1.0 / position
        mine = next((s for s, f in scored if f == target), 0.0)
        best_other = next((s for s, f in scored if f != target), 0.0)
        margins.append(mine - best_other)
    n = max(1, len(questions))
    return {"encoder": name, "p_at_1": at1 / n, "mrr": rr / n,
            "margin": sum(margins) / n, "n": n}


def main():
    run = Run("ENCODER-15 — find the word from its definition: a measure that cannot saturate", [
        "H1  on HELD OUT, every encoder beats the word-overlap floor",
        "H2  the measure discriminates: best − worst > 0.05 p@1 on HELD OUT",
        "H3  a native encoder's p@1 rises as it is taught more",
        "H4  at the largest volume, a native encoder is within 0.05 p@1 of MiniLM on HELD OUT",
    ])

    words = the_words()
    if len(words) < 50:
        run.check("the store holds enough words with definitions", False, f"only {len(words)}")
        run.finish("not measurable")
        return 1
    (tf, tq), (hf, hq) = the_two_tasks(words)
    run.observe("the task", f"{len(words)} words, {TERMS_EACH} defining terms each, "
                            f"one answer among {len(words)} — floor {1/len(words):.4f}")
    run.data["task"] = {"words": len(words), "terms_each": TERMS_EACH, "floor": 1 / len(words)}

    floor_t = retrieval("word-overlap", WordOverlap(), tq, tf)
    floor_h = retrieval("word-overlap", WordOverlap(), hq, hf)
    run.observe("word-overlap floor", f"TOGETHER p@1 {floor_t['p_at_1']:.3f}  "
                                      f"HELD OUT p@1 {floor_h['p_at_1']:.3f}")
    run.data["floor"] = {"together": floor_t, "held_out": floor_h}

    at = time.time()
    model = MiniLM()
    minilm_t = retrieval("MiniLM", model, tq, tf)
    minilm_h = retrieval("MiniLM", model, hq, hf)
    run.observe("MiniLM", f"TOGETHER p@1 {minilm_t['p_at_1']:.3f}  HELD OUT p@1 {minilm_h['p_at_1']:.3f}  "
                          f"({time.time()-at:.0f}s)")
    run.data["minilm"] = {"together": minilm_t, "held_out": minilm_h}

    task_props = [(s, "defined_with", t) for s, terms in words for t in terms]
    by_volume, rows = {}, []
    for volume in VOLUMES:
        at = time.time()
        taught = taught_propositions(volume)
        if not taught:
            continue
        learned = taught + task_props
        got = {}
        for label, enc in (("native", SubstrateEncoder()), ("structural", StructuralEncoder())):
            enc.learn(learned)
            got[label] = {"together": retrieval(label, enc, tq, tf),
                          "held_out": retrieval(label, enc, hq, hf)}
        by_volume[volume] = {"taught": len(learned), **got}
        rows.append(f"{len(learned):>9,} taught   "
                    f"native {got['native']['held_out']['p_at_1']:.3f}   "
                    f"structural {got['structural']['held_out']['p_at_1']:.3f}   "
                    f"({time.time()-at:.0f}s)")
        run.observe(f"{len(learned):,} propositions taught",
                    f"HELD OUT native {got['native']['held_out']['p_at_1']:.3f} / "
                    f"structural {got['structural']['held_out']['p_at_1']:.3f}"
                    f"  (the task is {100*len(task_props)/len(learned):.1f}% of what it knows)")
    run.data["by_volume"] = by_volume
    if rows:
        run.table("HELD OUT, as the substrate is taught more:", rows)

    if not by_volume:
        run.check("propositions could be drawn", False, "none")
        run.finish("not measurable")
        return 1

    biggest, smallest = max(by_volume), min(by_volume)
    held = [minilm_h["p_at_1"],
            by_volume[biggest]["native"]["held_out"]["p_at_1"],
            by_volume[biggest]["structural"]["held_out"]["p_at_1"]]
    best_native = max(held[1], held[2])

    run.check("H1 every encoder beats the word-overlap floor on HELD OUT",
              min(held) > floor_h["p_at_1"],
              f"floor {floor_h['p_at_1']:.3f}; lowest encoder {min(held):.3f}")
    run.check("H2 the measure discriminates", max(held) - min(held) > 0.05,
              f"best {max(held):.3f} − worst {min(held):.3f} = {max(held)-min(held):.3f}")
    # EACH ENCODER ON ITS OWN. Asked as `any`, this passed because one rose while the other fell,
    # which is not the hypothesis: it reported "a native encoder improves with teaching" over a
    # native encoder that declined from 0.797 to 0.540 (2026-11-14).
    for label in ("native", "structural"):
        first = by_volume[smallest][label]["held_out"]["p_at_1"]
        last = by_volume[biggest][label]["held_out"]["p_at_1"]
        run.check(f"H3 {label} improves as it is taught more", last > first and len(by_volume) > 1,
                  f"{smallest:,} -> {biggest:,}: {first:.3f} -> {last:.3f}"
                  + ("  (the task is "
                     f"{100*len(task_props)/by_volume[smallest]['taught']:.0f}% of the corpus at "
                     f"{smallest:,} and {100*len(task_props)/by_volume[biggest]['taught']:.1f}% at "
                     f"{biggest:,}, so the smaller figure flatters it)" if last < first else ""))
    run.check("H4 a native encoder is within 0.05 of MiniLM on HELD OUT",
              best_native >= minilm_h["p_at_1"] - 0.05,
              f"best native {best_native:.3f} against MiniLM {minilm_h['p_at_1']:.3f}")

    run.finish(f"HELD OUT: floor {floor_h['p_at_1']:.3f}, MiniLM {minilm_h['p_at_1']:.3f}, "
               f"best native {best_native:.3f} at {biggest:,} taught; "
               f"TOGETHER: floor {floor_t['p_at_1']:.3f}, MiniLM {minilm_t['p_at_1']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
