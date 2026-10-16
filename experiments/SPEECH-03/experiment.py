#!/usr/bin/env python3
"""SPEECH-03 — a word heard as the sounds it is made of, said by speakers never taught by.

SPEECH-02 measured that a whole word carries from one voice to another about four times in ten at best, with sixty
speakers teaching each word. A word is made of a few dozen sounds, and every speaker says each thousands of times.
Here the SOUNDS are taught: frames of each phone, cut by LibriSpeech's aligned phoneme times, measured in the ear's
own speech bands with the frames around them. Nothing is trained. A heard frame is compared with the taught frames,
and its nearest ones say which phone it sounds like; a heard stretch is fitted to each candidate word's phones in
order, as the CMU Pronouncing Dictionary gives them, and the word that fits best is the word heard (`phones.py`).

Offline: no store and no substrate. Research before anything is built (`docs/research/HEARING_BY_PHONES.md`).

  A  FRAMES   a frame said by an untaught speaker (test-clean) is given its phone more often measured with the
              frames around it than as the ear measures a word (12 cepstra and their change).
  B  WORDS    of the lessons' 100 most-used words, the one that fits best is the word said, for words cut from
              untaught speakers' sentences, more often than whole-word matching reached with sixty speakers a word
              (SPEECH-02: 38.3%); and the word said is among the best five three times in four.
  C  ALONE    the same for MSWC's words said alone, by other speakers through other microphones: measured.

Recordings: LibriSpeech dev-clean (40 speakers, to teach) and test-clean (40 others, to hear), with the Montreal
Forced Aligner's times (`gilkeyio/librispeech-alignments`, CC BY 4.0), under `data/speech/` (never pushed); MSWC
clips as SPEECH-02 fetched them.

Run (from the Lyric folder):
    ./venv_lyric/bin/python3 experiments/SPEECH-03/experiment.py [--words 100]
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "experiments" / "SPEECH-02"))

from experiments._evidence import RunRecord  # noqa: E402

#: What whole-word matching reached on the lessons' 100 words with sixty teaching speakers a word and a word's five
#: nearest examples (SPEECH-02, `offline_speakers.py`).
WHOLE_WORD = 38.3

EV = RunRecord(
    "SPEECH-03",
    claim=("Taught the sounds words are made of, from forty speakers, and nothing of the words themselves, the "
           "ear's measurements name a word said in a sentence by a speaker it never heard more often than "
           "whole-word matching does with sixty speakers teaching each word."),
    hypothesis=("A frame measured with its neighbours is given its phone no more often than a frame measured as "
                "the ear measures words; or the word that fits a stretch best by its phones is the word said no "
                "more often than whole-word matching reached; or the word said is among the best five less than "
                "three times in four."))

TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    import numpy as np
    import scipy.fft
    from nltk.corpus import cmudict
    from core.perception import hearing as H
    from core.perception import speech as SP
    import phones as P
    from clips import clips, present
    from fetch_mswc import lesson_words
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", type=int, default=100)
    args = parser.parse_args()
    started = time.monotonic()

    taught = P.Taught()
    say_line(f"== Taught: {len(taught.frames)} frames of {len(taught.phones)} phones from {taught.speakers} "
             f"speakers ({P.TEACH}), {taught.frames.shape[1]} measures a frame, {time.monotonic() - started:.0f} s ==")
    EV.metric("taught frames", len(taught.frames))
    EV.metric("teaching speakers", taught.speakers)
    heard = P.utterances("test_clean", 9)

    # ── A. FRAMES ───────────────────────────────────────────────────────────────────────────────────────────────
    say_line("\n== A. Frames said by untaught speakers, given their phone ==")

    def as_words_are(bands):
        cep = scipy.fft.dct(bands, type=2, norm="ortho", axis=1)[:, 1:SP._CEPSTRA + 1]
        cep = cep - SP._running_mean(cep)
        return np.concatenate([cep, np.gradient(cep, axis=0)], axis=1).astype(np.float32)

    rng = np.random.default_rng(20261003)
    kept, names, seen = [], [], Counter()
    for speaker, bands, phones, _ in P.utterances(P.TEACH.split(",")[0]):
        frames = as_words_are(bands)
        for phone in sorted(set(phones) - {""}):
            at = np.flatnonzero(phones == phone)
            for i in rng.choice(at, size=min(len(at), P.PER_UTTERANCE), replace=False):
                if seen[(speaker, phone)] < P.PER_SPEAKER:
                    seen[(speaker, phone)] += 1
                    kept.append(frames[i])
                    names.append(phone)
    plain_frames = np.array(kept, dtype=np.float32)
    plain_phone = np.array([taught.index[p] for p in names])
    plain_squares = (plain_frames ** 2).sum(axis=1)

    right = Counter()
    total = 0
    for _, bands, phones, _ in heard:
        known = np.flatnonzero(phones != "")[::7]
        truth = np.array([taught.index.get(p, -1) for p in phones[known]])
        right["with the frames around it"] += int((taught.sounds_like(P.measured(bands)[known]).argmax(axis=1) == truth).sum())
        q = as_words_are(bands)[known]
        for lo in range(0, len(q), 256):
            part = q[lo:lo + 256]
            d = (part ** 2).sum(axis=1)[:, None] + plain_squares[None, :] - 2.0 * part @ plain_frames.T
            near = plain_phone[np.argpartition(d, P.NEAREST, axis=1)[:, :P.NEAREST]]
            votes = np.zeros((len(part), len(taught.phones)), dtype=np.int32)
            np.add.at(votes, (np.arange(len(part))[:, None], near), 1)
            right["as the ear measures a word"] += int((votes.argmax(axis=1) == truth[lo:lo + 256]).sum())
        total += len(known)
    for how, n in right.items():
        EV.metric(f"frames given their phone, {how}", f"{n}/{total}")
        say_line(f"    {how}: {100 * n / total:.1f}% of {total}")
    check("a frame measured with the frames around it is given its phone more often than as the ear measures a word",
          right["with the frames around it"] > right["as the ear measures a word"],
          f"{100 * right['with the frames around it'] / total:.1f}% against "
          f"{100 * right['as the ear measures a word'] / total:.1f}% of {total} frames, {len(taught.phones)} phones")

    # ── B. WORDS, in sentences ──────────────────────────────────────────────────────────────────────────────────
    say_line("\n== B. Words cut from untaught speakers' sentences ==")
    said = cmudict.dict()
    used = lesson_words()
    available = clips(set(used), 10, 3)
    words = [w for w in sorted(used, key=lambda w: (-used[w], w))
             if w in available and len(available[w]["teach"]) >= 10 and len(available[w]["heard"]) == 3
             and w in said][:args.words]
    ways = {w: [[P.plain(p) for p in way] for way in said[w]] for w in words}
    EV.metric("candidate words", len(words))

    def order(logp):
        score = {w: max(taught.fit(logp, way) for way in ways[w]) for w in words}
        return sorted(score, key=score.get, reverse=True)

    # WORDS SAID ALIKE ARE ONE TO THE EAR. "two" and "to" have the same phones, fit every stretch equally, and are
    # told apart by which makes sense, which is the listener's to choose (`derived_reader.heard_which`). A word
    # said the same as the one that fits best is heard.
    said_as = {w: {tuple(way) for way in ws} for w, ws in ways.items()}
    alike = lambda a, b: bool(said_as[a] & said_as[b])
    near = exact = top5 = n = 0
    per, confused = Counter(), Counter()
    for speaker, bands, _, spoken in heard:
        frames = None
        for word, lo, hi in spoken:
            if word in ways and per[word] < 5 and hi - lo >= 5:
                per[word] += 1
                frames = P.measured(bands) if frames is None else frames
                found = order(taught.sounds_like(frames[lo:hi + 1]))
                exact += found[0] == word
                near += alike(found[0], word)
                top5 += any(alike(f, word) for f in found[:5])
                n += 1
                if not alike(found[0], word):
                    confused[(word, found[0])] += 1
    EV.metric("words in sentences: the word said, or one said the same, fits best", f"{near}/{n}")
    EV.metric("words in sentences: the very word fits best", f"{exact}/{n}")
    EV.metric("words in sentences: among the best five", f"{top5}/{n}")
    EV.metric("words in sentences: taken most often for another", [f"{a} as {b} ({c})" for (a, b), c in confused.most_common(12)])
    say_line(f"    {n} stretches of {len(per)} words: fits best {100 * near / n:.1f}% (the very word {100 * exact / n:.1f}%), "
             f"among the best five {100 * top5 / n:.1f}%; most often taken for another: {confused.most_common(6)}")
    check("the word that fits best by its phones is the word said more often than whole-word matching reached",
          100 * near / n > WHOLE_WORD, f"{100 * near / n:.1f}% of {n} against {WHOLE_WORD}% (SPEECH-02, sixty "
                                       f"speakers a word); no word was taught as a word")
    check("the word said is among the best five three times in four", top5 * 4 >= n * 3,
          f"{100 * top5 / n:.1f}% of {n}")

    # ── C. WORDS, said alone through other microphones ──────────────────────────────────────────────────────────
    say_line("\n== C. MSWC's words said alone ==")
    near = top5 = n = 0
    for w in words:
        for k, c in enumerate(available[w]["heard"]):
            path = present(c["path"], ROOT / "experiments" / "SPEECH-02" / "work" / "offline" / "heard" / w / f"{k}.wav", rng)
            y = np.asarray(H.decode(str(path)), dtype=np.float64)
            lo, hi, _ = SP._extent(y)
            # A word said alone is measured over its own frames, as the ear measures a word (`speech._measure`).
            found = order(taught.sounds_like(P.measured(P.energies(y)[lo:hi])))
            near += alike(found[0], w)
            top5 += any(alike(f, w) for f in found[:5])
            n += 1
    EV.metric("MSWC words alone: the right word fits best", f"{near}/{n}")
    EV.metric("MSWC words alone: among the best five", f"{top5}/{n}")
    say_line(f"    {n} clips: fits best {100 * near / n:.1f}%, among the best five {100 * top5 / n:.1f}% "
             f"(whole-word matching, taught these very words from sixty speakers each: {WHOLE_WORD}%)")
    EV.note("C is measured, not checked: one word said alone through another microphone is too little to tell the "
            "microphone from the word, and the phones were taught from read speech through other microphones.")

    EV.metric("seconds", round(time.monotonic() - started))
    record = EV.write()
    record.with_name(record.stem + "_transcript.md").write_text(
        "# SPEECH-03 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
