#!/usr/bin/env python3
"""DOC-01 — What share of REAL documents can the substrate perceive and read?

The substrate could WRITE a PDF and not open one. `PerceptionFaculty` now reads
documents as a modality beside image and video, so this is the baseline: point it
at every real document on this machine and measure what it can actually take in.

TWO DIFFERENT QUESTIONS, MEASURED SEPARATELY, because conflating them is how a
capability gets overstated:

  PERCEIVE   can it open the file and get the text that is really in it?
  READ       does that text become CLAIMS it holds -- subject, relation, object?

A document that perceives and yields no claim is not understood, and saying so is
the point. Perception is the easy half.

Run: PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/DOC-01/experiment.py
"""
from __future__ import annotations

import asyncio
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "nlu"))

from _nlu_lib import Experiment, live_substrate, stamp_now      # noqa: E402

#: Where real documents live. Two roots: the working tree, and the business
#: documents the substrate has never been shown.
CORPUS_ROOTS = [
    Path("/Users/stefan/Dominion Labs"),
    Path("/Users/stefan/Library/Mobile Documents/com~apple~CloudDocs/"
         "Dominion Labs Inc. "),
]
#: Directories that hold LIBRARY files, not this project's documents. Their
#: JSON and Markdown would swamp the sample and measure pip, not the substrate.
SKIP = ("/venv", "/node_modules/", "/.git/", "/.cache/", "/Python-3.11.4/",
        "/site-packages/", "/__pycache__/")
#: WRITTEN BY A PERSON, FOR A PERSON. This is what "can it read a document"
#: means, and it is the number that answers the question.
DOCUMENT_EXT = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".csv"}
#: EMITTED BY A MACHINE. Real files the substrate must cope with, and not prose:
#: measured separately because mixing them answers neither question.
#:
#: The first run of this experiment reported "620,139,068 words extracted" from
#: 4,400 documents -- 141,000 words each. The cause was in the corpus, not the
#: reader: `api-gateway.log` alone is 143MB and `operation_logs.log` 31MB, so
#: the word count measured how much machine output is on this disk. Worse, log
#: lines and JSON were being split on "." and handed to the sentence reader as
#: though they were prose, which makes the claims-per-sentence figure meaningless
#: in the same breath.
MACHINE_EXT = {".json", ".yaml", ".yml", ".log"}
WANTED = DOCUMENT_EXT | MACHINE_EXT

#: The bound on the sample, DECLARED. A silent cap reads as "this is everything".
SAMPLE = 5000
#: Sentences read per document. Reading every sentence of 4,000 documents is a
#: different experiment; this measures whether a document's prose YIELDS claims,
#: for which the opening of each is representative and the bound is stated.
SENTENCES_PER_DOC = 12

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def corpus() -> list:
    found = []
    for root in CORPUS_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            p = str(path)
            if any(s in p for s in SKIP):
                continue
            if path.suffix.lower() in WANTED and path.is_file():
                found.append(path)
    found.sort()
    if len(found) > SAMPLE:
        # A uniform sample across the WHOLE corpus, seeded so the run repeats.
        found = random.Random(20260923).sample(found, SAMPLE)
    return found


async def main() -> int:
    x = Experiment("DOC-01",
                   "What share of REAL documents can it perceive, and read?",
                   faculty="document_perception")
    files = corpus()
    x.note(f"corpus: {len(files):,} real document(s) across "
           f"{len({f.suffix.lower() for f in files})} format(s)"
           + (f" (a uniform sample of {SAMPLE:,}; the corpus is larger)"
              if len(files) >= SAMPLE else " (every one found)"))
    x.note(f"bound: the first {SENTENCES_PER_DOC} sentence(s) of each document "
           f"are read, and that bound is stated rather than silent")

    async with live_substrate() as coordinator:
        from core.perception.perception_faculty import PerceptionFaculty
        from core.semantics.sentence_reader import SentenceReader
        faculty, reader = PerceptionFaculty(), SentenceReader()

        kinds = {"document": DOCUMENT_EXT, "machine": MACHINE_EXT}
        per_kind = {k: {"perceived": 0, "words": 0, "sentences": 0,
                        "claims": 0, "with_claims": 0} for k in kinds}

        def kind_of(suffix: str) -> str:
            return "document" if suffix in DOCUMENT_EXT else "machine"

        perceived = refused = raised = 0
        by_format = Counter()
        failed_format = Counter()
        words_total = 0
        empty_text = 0
        docs_with_claims = 0
        sentences_read = claims = 0
        reasons = Counter()
        started = time.time()

        for path in files:
            try:
                modality, content = await faculty.sense(str(path))
            except ValueError as error:
                refused += 1
                failed_format[path.suffix.lower()] += 1
                reasons[str(error).split(":")[0][:60]] += 1
                continue
            except Exception as error:
                raised += 1
                failed_format[path.suffix.lower()] += 1
                reasons[f"{type(error).__name__}: {str(error)[:40]}"] += 1
                continue
            perceived += 1
            kind = kind_of(path.suffix.lower())
            per_kind[kind]["perceived"] += 1
            per_kind[kind]["words"] += int(content.get("words") or 0)
            by_format[path.suffix.lower()] += 1
            words_total += int(content.get("words") or 0)
            if not content.get("words"):
                empty_text += 1
                continue
            got = 0
            for block in content.get("text") or []:
                for sentence in _SENTENCE.split(str(block)):
                    sentence = sentence.strip()
                    if len(sentence.split()) < 3:
                        continue
                    if sentences_read and got >= SENTENCES_PER_DOC:
                        break
                    sentences_read += 1
                    per_kind[kind]["sentences"] += 1
                    got += 1
                    try:
                        parts = reader.read_all(sentence)
                    except Exception:
                        parts = []
                    claims += len(parts)
                    per_kind[kind]["claims"] += len(parts)
                if got >= SENTENCES_PER_DOC:
                    break
            if got and claims:
                docs_with_claims += 1
                per_kind[kind]["with_claims"] += 1
        elapsed = time.time() - started

        total = len(files)
        x.measure("corpus", {"documents": total, "seconds": round(elapsed, 1)})
        x.measure("perceive", {"perceived": perceived, "refused": refused,
                               "raised": raised,
                               "pct": round(100 * perceived / max(total, 1), 1)})
        x.measure("by_format", dict(by_format.most_common()))
        x.measure("could_not_open", dict(failed_format.most_common()))
        x.measure("reasons", dict(reasons.most_common(6)))
        x.measure("text", {"words": words_total,
                           "documents_with_no_text": empty_text})
        x.measure("read", {"sentences": sentences_read, "claims": claims,
                           "claims_per_sentence": round(claims / max(sentences_read, 1), 3)})

        x.measure("by_kind", per_kind)
        x.note(f"PERCEIVED {perceived:,}/{total:,} "
               f"({100 * perceived / max(total, 1):.1f}%) · refused {refused:,} · "
               f"raised {raised:,} · in {elapsed:.0f}s")
        for kind in ("document", "machine"):
            k = per_kind[kind]
            what = ("written by a person" if kind == "document"
                    else "emitted by a machine")
            x.note(f"{kind.upper():9} ({what}): {k['perceived']:,} file(s) · "
                   f"{k['words']:,} word(s) · {k['claims']:,} claim(s) from "
                   f"{k['sentences']:,} sentence(s) "
                   f"({k['claims'] / max(k['sentences'], 1):.3f} per sentence) · "
                   f"{k['with_claims']:,} yielded a claim")
        if empty_text:
            x.note(f"{empty_text:,} document(s) opened but carried NO text — a "
                   f"scanned page has no text layer, and that is this number")

        # A RAISE IS NOT A REFUSAL. Refusing a format by name is correct
        # behaviour; an unexpected exception is a defect.
        x.check("no document made the reader raise", raised == 0,
                f"{raised} raised: {dict(reasons.most_common(3))}",
                finding="opens_without_raising")
        x.check("every perceived document reported its format",
                sum(by_format.values()) == perceived,
                f"{sum(by_format.values())} of {perceived} carried a format",
                finding="reports_format")
        x.check("PDFs are perceived", by_format.get(".pdf", 0) > 0,
                f"{by_format.get('.pdf', 0)} PDF(s) opened", finding="reads_pdf")
        x.check("text is actually extracted, not just opened",
                per_kind["document"]["words"] > 0,
                f"{per_kind['document']['words']:,} word(s) from documents",
                finding="extracts_text")
        # THE HONEST BAR. Perceiving is not understanding; this states the gap
        # rather than letting the perception number stand for both.
        x.check("a document written by a person yields a claim",
                per_kind["document"]["with_claims"] > 0,
                f"{per_kind['document']['with_claims']:,} of "
                f"{per_kind['document']['perceived']:,} document(s)",
                finding="yields_claims")

        stamp = stamp_now()
        here = Path(__file__).resolve().parent
        out = here / "results"
        out.mkdir(parents=True, exist_ok=True)
        import json
        artifact = out / f"{stamp}.json"
        artifact.write_text(json.dumps(x.as_dict(), indent=2), encoding="utf-8")
        print(x.render())
        print(f"\n  artifact: {artifact.relative_to(ROOT)}")
        held = await x.learned(coordinator, run=stamp,
                               artifact=str(artifact.relative_to(ROOT)))
        print(f"  the substrate now holds {held} finding(s) about its own "
              f"{x.faculty}")
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(asyncio.run(main()))
