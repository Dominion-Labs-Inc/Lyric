#!/usr/bin/env python3
"""Harness for the NLU suite. ONE LIVE SUBSTRATE, shared by every experiment.

Not `initialize()`. `start()` -- the coordination cycle and the reactive drain
worker are alive, so what the substrate is asked it answers as the running
system rather than as a module lifted out of it. A run refuses to proceed if
the drain worker is not up, exactly as the teaching entry point refuses.

Booting costs real time, so the suite boots ONCE and every experiment runs
against that same substrate, in order. Which experiments WRITE to the store is
declared per experiment and reported, because a reading experiment that quietly
taught the substrate its own probe sentences would flatter every experiment
after it.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1",
               "TQDM_DISABLE": "1"}.items():
    os.environ.setdefault(_k, _v)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------- reporting
@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    #: The short term the substrate holds this result under. Empty means this
    #: check teaches nothing -- see `Experiment.check`.
    finding: str = ""


@dataclass
class Experiment:
    code: str
    question: str
    #: True when running it changes the store. Declared, not inferred.
    writes: bool = False
    checks: List[Check] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    seconds: float = 0.0

    def check(self, name: str, passed: bool, detail: str = "",
              finding: str = "") -> None:
        """Record one check. `finding` is the SHORT term under which the
        substrate holds this result about itself.

        A CHECK NAME IS A SENTENCE; A FINDING IS A NAME. The first attempt used
        the check name as the finding, and the door refused most of them: the
        concept store admits a term of at most `MAX_TERM_WORDS` (4), on the
        stated ground that past this it is a clause and not a name. "no document
        made the reader raise" is six words, so three findings in five were
        thrown away by a gate that was working correctly.

        Truncating the name to fit would produce `no_document_made_the`, which
        names nothing. So a check that has not declared a finding term records
        NOTHING -- an honest gap, and visible as one, rather than a nonsense
        term the substrate would hold forever.
        """
        self.checks.append(Check(name, bool(passed), detail, finding.strip()))

    def note(self, text: str) -> None:
        self.notes.append(text)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    #: Numbers the experiment measured that are not pass/fail -- yields, rates,
    #: distributions. Persisted beside the checks so a run can be compared with
    #: the one before it instead of being read once in a terminal and lost.
    data: Dict[str, Any] = field(default_factory=dict)

    def measure(self, key: str, value: Any) -> None:
        self.data[key] = value

    def as_dict(self) -> Dict[str, Any]:
        return {
            "experiment": f"{self.code} — {self.question}",
            "writes_to_store": self.writes,
            "notes": list(self.notes),
            "data": dict(self.data),
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                       for c in self.checks],
            "passed": self.passed,
            "total": len(self.checks),
            "seconds": round(self.seconds, 2),
        }

    def save(self, root: Path, stamp: str) -> Path:
        """Write this run to `experiments/nlu/<CODE>/results/<stamp>.json`.

        EVERY OTHER EXPERIMENT IN THIS REPOSITORY DOES THIS. A suite whose
        output lives only in a terminal has measured nothing anybody can check
        later, compare against, or disagree with.
        """
        out = root / self.code / "results"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{stamp}.json"
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
        return path

    #: The faculty this experiment is ABOUT, so a finding can name its subject.
    #: Declared, never guessed from the question text.
    faculty: str = ""

    async def learned(self, coordinator, *, run: str,
                      artifact: Optional[str] = None) -> int:
        """Hand what this run found back to the substrate it was run on.

        AN EXPERIMENT ON ITSELF THAT TEACHES IT NOTHING IS A LOSS. The run
        engaged the live faculties -- reading, memory, perception, learning --
        and then its result went to a file. What the substrate discovered about
        itself is knowledge, and it should hold it like any other.

        EVERY CHECK, PASSED OR FAILED. A failure is a finding: "it does not read
        subordination" is a true thing about this substrate, and an experiment
        that reported only its successes would be teaching it a flattering
        fiction. `holds=False` carries that as a negative claim.

        The PROBE is never taught here -- only the finding, whose subject is the
        faculty. That is the line `writes_to_store` exists to protect, kept.
        """
        if not self.faculty:
            return 0
        held = 0
        undeclared = 0
        for check in self.checks:
            if not check.finding:
                undeclared += 1
                continue
            outcome = await coordinator.record_finding(
                faculty=self.faculty, finding=check.finding,
                holds=check.passed, experiment=self.code, run=run,
                artifact=artifact)
            if outcome is not None and (getattr(outcome, "admitted", False)
                                        or getattr(outcome, "already_present", False)):
                held += 1
        if undeclared:
            # SAID OUT LOUD, never swallowed: a check with no finding term is a
            # measurement the substrate did not get to keep.
            print(f"         -> {undeclared} check(s) declared no finding term "
                  f"and taught nothing", flush=True)
        return held

    def render(self) -> str:
        head = (f"\n{self.code} — {self.question}"
                f"{'   [WRITES TO THE STORE]' if self.writes else ''}")
        lines = [head, "-" * min(len(head.strip()) + 2, 78)]
        for note in self.notes:
            lines.append(f"  · {note}")
        for c in self.checks:
            lines.append(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}"
                         + (f"\n         {c.detail}" if c.detail else ""))
        lines.append(f"  {self.passed}/{len(self.checks)} checks  ({self.seconds:.1f}s)")
        return "\n".join(lines)


# ------------------------------------------------------------ live substrate
@contextlib.asynccontextmanager
async def live_substrate():
    """The whole substrate, running. Yields the coordinator."""
    quiet = io.StringIO()
    print("starting the substrate…", flush=True)
    started = time.time()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    # WORD CLASSES MUST BE WARM BEFORE ANYTHING IS MEASURED. Reading consults
    # them (genericity asks whether a subject is a known noun before it will
    # call a reading representable), and they are DERIVED from taught memories
    # at warm time. A cold substrate therefore reads strictly less than the same
    # substrate a moment later.
    #
    # Measured, and it is why this is here: in the first full run "A robin is a
    # bird." was declined by four experiments and then read by two, because an
    # experiment in between wrote to the store and warmed the classes. Every
    # number taken before that point was of a substrate that had not finished
    # waking up.
    warmed = await coordinator.memory.warm_word_classes()
    print(f"  word classes warm: {warmed}", flush=True)

    alive = bool(getattr(coordinator, "_reactive_worker", None))
    cycling = bool(getattr(coordinator, "coordination_task", None))
    print(f"  running: coordination={cycling} reactive_drain={alive} "
          f"({time.time() - started:.0f}s)", flush=True)
    if not alive:
        raise SystemExit("the reactive drain worker is not running; refusing to "
                         "measure a substrate that cannot react.")
    try:
        coordinator._nlu_warm = warmed
        yield coordinator
    finally:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            with contextlib.suppress(Exception):
                await system.shutdown()


def conversation_of(coordinator, session: str = "nlu-suite"):
    """The substrate HOLDING A CONVERSATION -- where reading and replying live.

    `read`, `understand` and `say` are on the `Conversation` faculty, not on the
    coordinator: the coordinator owns the faculties and this is one of them,
    reached through `coordinator.conversation(...)` so the substrate's own emit,
    learning authority and disposition are injected into it. Calling it any
    other way would measure a faculty lifted out of the substrate.
    """
    return coordinator.conversation(session=session)


async def reading_of(conversation, sentence: str) -> Tuple[Optional[Tuple[str, ...]], str]:
    """What the substrate makes of one sentence. Pure: reads, stores nothing."""
    try:
        return await conversation.read(sentence)
    except Exception as error:
        # THE REASON TRAVELS WITH THE FAILURE. Recording only the exception TYPE
        # turned a broken harness into a plausible-looking result: 300/300
        # "raised:AttributeError" read as a substrate that understands nothing,
        # and the refusal checks all PASSED because a crash refuses too.
        return None, f"raised:{type(error).__name__}: {error}"


# ------------------------------------------------------------------ corpora
_CODE = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MDSYNTAX = re.compile(r"^[\s>#*\-|+\d.]+", re.M)
_EMPHASIS = re.compile(r"\*{1,3}|_{2,}")
_SPACES = re.compile(r"\s{2,}")
_SENT = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def real_prose(limit: int = 400, min_words: int = 4,
               max_words: int = 40) -> List[str]:
    """Sentences of genuine human-written English from the repository's docs.

    NOT sentences written for this suite. Every other corpus here was authored
    to probe something, which flatters a reader; this one was written by a
    person for people, with no reader in mind. Technical prose skews long and
    subordinate-heavy, and that skew is the point: it is what the substrate
    would actually be asked to read.
    """
    out: List[str] = []
    for path in sorted((ROOT / "docs").glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        text = _CODE.sub(" ", text)
        text = _INLINE.sub(" ", text)
        text = _LINK.sub(r"\1", text)
        for block in text.split("\n\n"):
            block = _MDSYNTAX.sub("", block).replace("\n", " ")
            block = _SPACES.sub(" ", _EMPHASIS.sub("", block)).strip()
            if not block:
                continue
            for sentence in _SENT.split(block):
                sentence = sentence.strip()
                if not sentence.endswith((".", "?", "!")):
                    continue
                words = _WORD_RE.findall(sentence)
                if not (min_words <= len(words) <= max_words):
                    continue
                if not sentence[:1].isupper():
                    continue
                # Drop anything still carrying markup or path-like debris: it is
                # not prose and counting it as unread would be a false failure.
                if any(ch in sentence for ch in "|_/<>{}=@*"):
                    continue
                # A stripped link leaves "( )" behind; that is debris, not prose.
                if "( )" in sentence or "()" in sentence:
                    continue
                # A removed link leaves a gap: " ;" / " ." / doubled function
                # words. Those are not sentences the substrate failed to read,
                # they are sentences nobody wrote, and counting them as misses
                # would understate the reader.
                if re.search(r"\s[;.,]|\b(and|is|the|of|to)\s+[;.]", sentence):
                    continue
                out.append(sentence)
                if len(out) >= limit:
                    return out
    return out


def words_of(sentence: str) -> List[str]:
    return _WORD_RE.findall(sentence.lower())


def stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def save_suite(experiments, root: Path, stamp: str, warm: Any) -> Path:
    """The whole run in one file, beside the per-experiment ones."""
    total = sum(len(x.checks) for x in experiments)
    passed = sum(x.passed for x in experiments)
    blob = {
        "suite": "NLU — natural-language understanding and expression",
        "stamp": stamp,
        "substrate": {"live": True, "word_classes_warm": warm},
        "passed": passed,
        "total": total,
        "experiments": [x.as_dict() for x in experiments],
    }
    root.mkdir(parents=True, exist_ok=True)
    path = root / "results" / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    return path


__all__ = ["Check", "Experiment", "live_substrate", "conversation_of",
           "reading_of", "real_prose", "words_of", "save_suite", "stamp_now",
           "ROOT"]
