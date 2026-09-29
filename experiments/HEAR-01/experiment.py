#!/usr/bin/env python3
"""HEAR-01 — hearing is a sense of the substrate, on sight's own path.

Hearing was built as a reader under the one perception faculty, not as a faculty
beside it: what it hears is stated on the same contract as what sight sees, so
admission, belief, memory, the naming reflex, describing a kind and the
acceptance band serve it with no second mechanism. This boots the real substrate
and hears real recordings through `coordinator.hear()`, and asserts what happened
at every stage and at every seam between them.

  A  EAR         the live substrate hears a real recording through the one door.
  B  ADMITTED    each sound is an individual in the concept graph, carrying what
                 it is (`isa`) apart from what the recording made of it.
  C  BELIEVED    what was heard is held as beliefs.
  D  REMEMBERED  the hearing forms a memory that keeps a trace of the sounds,
                 a few percent of the recording, never the recording itself.
  E  JUDGED      the hearing is judged by the acceptance band, per claim, and the
                 judgement reaches the reaction system as an event.
  F  EXPERIENCE  the whole hearing is handed to the memory agent through `hear`.
  G  DOORS       `see` refuses a recording and `hear` refuses a picture.
  H  INVARIANT   on 19 real recordings: what `isa` claims survives gain, padding
                 and codec; the level (a fact about the recording) does not.
  I  NAMED       the substrate learns to name a kind of sound by its own
                 induction, then names a fresh sound by hearing it; asking gives
                 the same answer.
  J  KIND        a kind heard twice is described, and never by its framing.
  K  KNOWN       a sound taught once is recognised when heard again inside
                 speech, and nowhere else; a featureless reference is refused.
  L  VIDEO       a clip with a sound track is seen and heard on one percept; a
                 silent clip says so.

Recordings: the JFK inaugural sample and a speech sample from the repo's
third_party folder, three LibriSpeech utterances, and the macOS system sounds
(so section H, I, J and K need macOS). Mixtures and the muxed clip are built from
those real recordings into `stimuli/` on first run.

Run (sandbox store): ./venv_torin/bin/python3 experiments/HEAR-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "torinai_dev")

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
JFK = REPO / "third_party" / "whisper.cpp" / "samples" / "jfk.wav"
SPEECH_2 = REPO / "third_party" / "llama.cpp" / "tools" / "mtmd" / "test-2.mp3"
LIBRI = Path("/Users/stefan/Dominion Labs/r1-rom/asr/"
             "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17-mobile/test_wavs")
SYSTEM_SOUNDS = Path("/System/Library/Sounds")
JELLYFISH = REPO / "test_data" / "jellyfish_real_10s.mp4"
PICTURE = REPO / "test_data" / "vision_test.png"

EV = RunRecord(
    "HEAR-01",
    claim=("Hearing is a sense of the substrate on the same path as sight: a real "
           "recording is sensed into sounds with what each is and how they stand "
           "to one another, admitted once, believed, remembered with the sound "
           "kept, judged, handed over as an experience, and learned to be named "
           "by the substrate's own induction — with no model anywhere."),
    hypothesis=("H1 pitch behaves like hue: the register survives gain, padding and "
                "codec, so it may be claimed with `isa`. H2 loudness behaves like "
                "the size band: it follows the gain, so it is a fact about the "
                "recording and the invariant form is `louder_than`. H4 a known "
                "sound can be recognised heard again, by landmark agreement, only "
                "when it carries enough landmarks. And because hearing states its "
                "sounds on sight's contract, the naming reflex, induction and "
                "describing a kind need no code of their own."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── stimuli, built from real recordings ─────────────────────────────────────

def _ffmpeg(args):
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + args, check=True)


def build_stimuli() -> dict:
    """A known sound mixed into real speech at equal level, and a real clip
    given a real sound track. Built once; the sources are real recordings."""
    import numpy as np
    import soundfile as sf
    from core.perception import hearing as H
    STIM.mkdir(parents=True, exist_ok=True)
    mix = STIM / "glass_in_jfk.wav"
    if not mix.exists():
        speech = H.decode(str(JFK))
        glass = H.decode(str(SYSTEM_SOUNDS / "Glass.aiff"))

        def level(y):
            db = H._levels(y)
            top = db[db > db.max() - 30]
            return 10 * np.log10(np.mean(10 ** (top / 10)))
        gain = 10 ** ((level(speech) - level(glass)) / 20)
        out = speech.copy()
        at = int(5.0 * H.SR)
        seg = glass * gain
        out[at:at + len(seg)] += seg[:len(out) - at]
        sf.write(str(mix), (out / max(1.0, np.abs(out).max())).astype(np.float32), H.SR)
    clip = STIM / "jellyfish_with_speech.mp4"
    if not clip.exists():
        _ffmpeg(["-i", str(JELLYFISH), "-i", str(JFK), "-c:v", "copy", "-c:a", "aac",
                 "-shortest", str(clip)])
    # A SOUND AS IT IS MET: with a moment of quiet before it. The macOS sound
    # files begin at their very first sample, where no hearing could tell a
    # sound's start from a recording that cut into it -- so their onset is not
    # claimed. Met in a room, a sound has quiet before it and its start is heard.
    met = {}
    for name, gain_db in (("Ping", 0), ("Tink", 0), ("Glass", 0), ("Basso", 0), ("Purr", 0),
                          ("Funk", 0), ("Ping", -10)):
        key = name if gain_db == 0 else f"{name}{gain_db}dB"
        out = STIM / f"{key.lower()}_in_quiet.wav"
        if not out.exists():
            y = H.decode(str(SYSTEM_SOUNDS / f"{name}.aiff")) * 10 ** (gain_db / 20)
            sf.write(str(out), np.concatenate([np.zeros(H.SR // 4), y]).astype(np.float32), H.SR)
        met[key] = out
    return {"mix": mix, "clip": clip, "met": met}


# ── section H, measured on the describer alone ──────────────────────────────

def invariance() -> dict:
    """Which claims survive identity-preserving change, over 19 real recordings."""
    import numpy as np
    import soundfile as sf
    from collections import defaultdict
    from core.perception import hearing as H
    recordings = [JFK, SPEECH_2] + [LIBRI / f"{n}.wav" for n in ("0", "1", "8k")] \
        + sorted(SYSTEM_SOUNDS.glob("*.aiff"))
    tally = defaultdict(lambda: [0, 0])

    def write(y):
        t = tempfile.mktemp(suffix=".wav")
        sf.write(t, np.clip(y, -1, 1).astype(np.float32), H.SR)
        return t

    for rec in recordings:
        y = H.decode(str(rec))
        base = write(y)
        mp3 = tempfile.mktemp(suffix=".mp3")
        _ffmpeg(["-i", base, "-b:a", "64k", mp3])
        variants = {"gain-12dB": (write(y * 10 ** (-12 / 20)), 0.0),
                    "gain+6dB": (write(y * 10 ** (6 / 20)), 0.0),
                    "pad0.5s": (write(np.concatenate([np.zeros(H.SR // 2), y,
                                                      np.zeros(H.SR // 2)])), 0.5),
                    "mp3_64k": (mp3, None)}
        d0 = H.describe(base)
        for name, (path, shift) in variants.items():
            d1 = H.describe(path)
            if shift is None:      # an mp3 encoder adds delay; align on the first sound
                shift = (d1["sounds"][0]["start"] - d0["sounds"][0]["start"]
                         if d0["sounds"] and d1["sounds"] else 0.0)
            tally[(name, "sound_count")][0] += int(d0["sound_count"] == d1["sound_count"])
            tally[(name, "sound_count")][1] += 1
            for s in d0["sounds"]:
                # The variant sound overlapping this one most in time, or none.
                overlap = [(min(s["end"], u["end"] - shift) - max(s["start"], u["start"] - shift), u)
                           for u in d1["sounds"]]
                best = max(overlap, default=(0.0, None), key=lambda o: o[0])
                t = best[1] if best[0] > 0 else None
                for feat in ("tonality", "register", "onset"):
                    if s.get(feat) is None:
                        continue            # not claimed, so nothing to survive
                    same = int(t is not None and t.get(feat) == s.get(feat))
                    tally[(name, feat)][1] += 1
                    tally[(name, feat)][0] += same
                    # FIRMLY READ: the reading's own support says it is not near
                    # the cut. A reading AT the cut is a coin flip by its own
                    # account, and flipping is what it says it may do.
                    if s["support"].get(s[feat], 0.0) >= 0.5:
                        tally[(name, feat + "_firm")][1] += 1
                        tally[(name, feat + "_firm")][0] += same
                tally[(name, "level_within_1dB")][1] += 1
                tally[(name, "level_within_1dB")][0] += int(
                    t is not None and abs(t["level"] - s["level"]) <= 1.0)
            if d0["sound_count"] == d1["sound_count"]:
                r1 = {(r["a"], r["rel"], r["b"]) for r in d1["relations"]}
                for r in d0["relations"]:
                    same = int((r["a"], r["rel"], r["b"]) in r1)
                    tally[(name, "relations")][1] += 1
                    tally[(name, "relations")][0] += same
                    if (r.get("support") or 0.0) >= 0.5:
                        tally[(name, "relations_firm")][1] += 1
                        tally[(name, "relations_firm")][0] += same
    return {f"{k[1]} under {k[0]}": tuple(v) for k, v in tally.items()}


async def main() -> int:
    from core.memory import Origin
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
        from core.agents.autonomous.autonomous_coordinator import SelfEventType
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.reasoning.concept_graph_reasoning import instance_predicates
    await db.assert_database_identity(os.environ["POSTGRES_DATABASE"])
    stim = build_stimuli()

    tag = uuid.uuid4().hex[:6]
    DOMAIN = "hearing"
    memory_ids = []
    memory_of = {}          # label -> memory id of that hearing
    events = []
    coord.on(SelfEventType.PERCEPT_RECOGNIZED, lambda ev: events.append(ev),
             name=f"hear01_probe_{tag}")

    import logging
    said = io.StringIO()
    _handler = logging.StreamHandler(said)
    _handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    for _name in ("core.agents.memory_agent", "core.agents.autonomous.autonomous_coordinator"):
        logging.getLogger(_name).addHandler(_handler)

    async def hear(path, label, **kw):
        said.truncate(0)
        said.seek(0)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await coord.hear(str(path), source=f"h{tag}{label}", domain=DOMAIN,
                                       actor_identity=None, **kw)
            await get_uncertainty_system().drain_writes()
        meta = (percept.metadata or {}) if percept is not None else {}
        if meta.get("memory_id"):
            memory_ids.append(meta["memory_id"])
            memory_of[label] = meta["memory_id"]
        elif percept is not None:
            # A hearing that formed no memory is recorded with what the memory
            # agent and the coordinator said about it, so the run carries why.
            why = [line for line in said.getvalue().splitlines()
                   if any(k in line for k in ("REJECT", "reject", "formed no memory",
                                              "Filter decision", "ERROR", "WARNING"))]
            EV.note(f"hearing {label} formed no memory: " + " | ".join(why[-6:]))
        return percept

    async def sounds_in(subject):
        rows = await db.execute_query(
            "SELECT cr.target_surface AS s FROM unified.concept_relations cr "
            "JOIN unified.concepts c ON cr.source_concept_id = c.concept_id "
            "WHERE c.name = $1 AND cr.relation = 'contains' ORDER BY cr.target_surface",
            (subject,), fetch_all=True) or []
        return [str(r["s"]) for r in rows]

    async def edges_of(name):
        rows = await db.execute_query(
            "SELECT cr.relation AS rel, COALESCE(c2.name, cr.target_surface) AS obj "
            "FROM unified.concept_relations cr "
            "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
            "WHERE c1.name = $1", (name,), fetch_all=True) or []
        return [(str(r["rel"]), str(r["obj"])) for r in rows]

    try:
        # ── A. THE EAR ──────────────────────────────────────────────────────
        print("\n== A. The live substrate hears a real recording ==")
        percept = await hear(JFK, "jfk")
        subject = percept.source if percept else None
        check("a real recording was heard through the one door",
              percept is not None and percept.data_type == "audio",
              f"{percept.data_type if percept else None}: {subject}")
        content = percept.content if percept else {}
        check("the percept is named from what was heard, not from who listened",
              bool(subject) and subject.startswith(f"h{tag}jfkx"), subject)
        check("its sounds were perceived, with how good the hearing was",
              len(content.get("blobs") or []) >= 4
              and (content.get("properties") or {}).get("hearing_is") in ("clear", "fair"),
              f"{len(content.get('blobs') or [])} sound(s), hearing "
              f"{(content.get('properties') or {}).get('hearing_is')}")
        EV.metric("sounds_in_jfk", len(content.get("blobs") or []), "count")

        # ── B. ADMITTED ─────────────────────────────────────────────────────
        print("\n== B. Each sound is an individual in the concept graph ==")
        sounds = await sounds_in(subject) if subject else []
        check("the recording CONTAINS its sounds, each its own concept",
              len(sounds) == len(content.get("blobs") or []), ", ".join(sounds)[:160])
        first = sorted(content.get("blobs") or [], key=lambda b: b["properties"]["starts_at"])
        edges = await edges_of(first[1]["name"]) if len(first) > 1 else []
        isa = sorted(o for r, o in edges if r == "isa")
        check("a sound IS what belongs to it: pitched-ness, register, onset",
              bool(isa) and set(isa) <= {"pitched", "unpitched", "low_pitched",
                                         "mid_pitched", "high_pitched", "abrupt", "gradual"},
              f"{first[1]['name'] if len(first) > 1 else '?'} isa {isa}")
        rels = {r for r, _o in edges}
        check("and what the RECORDING made of it is stated apart, never as `isa`",
              {"level", "starts_at"} <= rels
              and not any(o.lstrip("-").replace(".", "").isdigit() for r, o in edges if r == "isa"),
              f"relations held: {sorted(rels)}")
        order = [(r, o) for s in first for r, o in await edges_of(s["name"])
                 if r in ("before", "louder_than", "higher_than")]
        check("how the sounds stand to one another is admitted between them",
              any(r == "before" for r, _ in order),
              "; ".join(f"{r} {o.rsplit('_', 1)[-1]}" for r, o in order[:5]))

        # ── C. BELIEVED ─────────────────────────────────────────────────────
        print("\n== C. What was heard is believed ==")
        rows = await db.execute_query(
            "SELECT belief_text FROM unified.beliefs WHERE belief_text LIKE $1",
            (f"{subject}%",), fetch_all=True) or []
        check("what was heard is held as beliefs", len(rows) >= len(sounds) * 2,
              f"{len(rows)} belief(s)")
        EV.metric("beliefs_from_one_hearing", len(rows), "count")

        # ── D. REMEMBERED ───────────────────────────────────────────────────
        print("\n== D. The hearing is remembered, with the recording kept ==")
        memory_id = (percept.metadata or {}).get("memory_id") if percept else None
        check("hearing formed a memory", bool(memory_id), str(memory_id))
        media = await coord.recall_media(memory_id) if memory_id else []
        truth = hashlib.sha256(JFK.read_bytes()).hexdigest()
        kept = media[0] if media else {}
        check("the memory keeps a TRACE of what was heard, never the recording",
              bool(kept) and kept.get("mime") == "application/x-npz"
              and hashlib.sha256(kept["bytes"]).hexdigest() != truth
              and (kept.get("perceived") or {}).get("kind") == "sound_trace",
              f"{kept.get('mime')}, {kept.get('byte_size')} bytes" if kept else "nothing kept")
        ratio = (kept.get("byte_size") or 0) / JFK.stat().st_size if kept else None
        check("a few percent of the recording's size",
              ratio is not None and ratio < 0.1,
              f"{kept.get('byte_size')} of {JFK.stat().st_size} bytes = {ratio:.1%}" if ratio else None)
        EV.metric("trace_share_of_recording", round(ratio, 4) if ratio else None, "fraction")
        row = await db.execute_query(
            "SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1",
            (str(memory_id),), fetch_one=True) if memory_id else None
        check("the memory is found by what was heard in it",
              bool(row) and "pitched sound" in str(row["content"]),
              str(row["content"])[:110] if row else None)

        # ── E. JUDGED ───────────────────────────────────────────────────────
        print("\n== E. The hearing is judged by the acceptance band ==")
        mine = [e for e in events if getattr(e.payload, "subject", None) == subject]
        check("the judgement reached the reaction system as an event", bool(mine),
              f"{len(mine)} event(s)")
        payload = mine[-1].payload if mine else None
        check("per claim, each with its own verdict",
              payload is not None and len(payload.claims) >= len(sounds)
              and all(c.decision in ("ACT", "VERIFY", "ABSTAIN") for c in payload.claims),
              f"percept {payload.decision}: " + ", ".join(
                  f"{sum(1 for c in payload.claims if c.decision == d)} {d}"
                  for d in ("ACT", "VERIFY", "ABSTAIN")) if payload else "none")

        # ── F. EXPERIENCE ───────────────────────────────────────────────────
        print("\n== F. The hearing is handed over whole, as a hearing ==")
        exp = await db.execute_query(
            "SELECT kind, through, parts FROM unified.experience_pool WHERE about = $1",
            (subject,), fetch_all=True) or []
        check("an experience of the hearing waits in the pool",
              any(r["through"] == "hear" and r["kind"] == "perception" for r in exp),
              ", ".join(f"{r['kind']} through {r['through']}" for r in exp))
        parts = str(exp[0]["parts"]) if exp else ""
        check("met as a sound, and sensed by hearing",
              '"sound"' in parts and "hearing" in parts, "role sound, sensed_by hearing"
              if '"sound"' in parts else parts[:120])

        # ── G. DOORS ────────────────────────────────────────────────────────
        print("\n== G. Each door opens what it perceives ==")
        refused = []
        for door, path in (("see", JFK), ("hear", PICTURE)):
            try:
                await getattr(coord, door)(str(path), actor_identity=None, source=f"h{tag}door")
                refused.append((door, None))
            except ValueError as error:
                refused.append((door, str(error)))
        check("`see` refuses a recording, naming the door that opens it",
              refused[0][1] is not None and "use hear" in refused[0][1], refused[0][1])
        check("`hear` refuses a picture", refused[1][1] is not None, refused[1][1])

        # ── H. INVARIANT ────────────────────────────────────────────────────
        print("\n== H. What `isa` claims survives change; the level does not ==")
        tally = invariance()
        for key, (a, b) in sorted(tally.items()):
            EV.metric(key, f"{a}/{b}", "survived")

        def rate(feature, nuisances):
            a = sum(tally.get(f"{feature} under {n}", (0, 0))[0] for n in nuisances)
            b = sum(tally.get(f"{feature} under {n}", (0, 0))[1] for n in nuisances)
            return a, b
        keep = ("gain-12dB", "gain+6dB", "pad0.5s", "mp3_64k")
        a, b = rate("register_firm", keep)
        check("H1: a firmly read register survives gain, padding and codec",
              b and a == b, f"{a}/{b} (all readings: {'/'.join(map(str, rate('register', keep)))})")
        a, b = rate("tonality_firm", keep)
        check("and firmly read pitched or unpitched",
              b and a == b, f"{a}/{b} (all readings: {'/'.join(map(str, rate('tonality', keep)))})")
        a, b = rate("onset_firm", keep)
        check("and a firmly read onset",
              b and a == b, f"{a}/{b} (all readings: {'/'.join(map(str, rate('onset', keep)))})")
        a, b = rate("level_within_1dB", ("gain-12dB", "gain+6dB"))
        check("H2: the level follows the gain, so it is the recording's, not the sound's",
              b and a == 0, f"level unchanged in {a}/{b} under gain")
        a, b = rate("relations_firm", keep)
        check("while how the sounds stand to one another survives, where firmly read",
              b and a == b, f"{a}/{b} (all: {'/'.join(map(str, rate('relations', keep)))})")
        a, b = rate("sound_count", ("pad0.5s",))
        check("silence padded around a recording does not change what is in it",
              b and a == b, f"{a}/{b} recordings")

        # ── I. NAMED ────────────────────────────────────────────────────────
        print("\n== I. The substrate learns to name a kind of sound, then hears one ==")
        CAT = f"ring{tag}"

        async def sound_of(name, label):
            p = await hear(stim["met"][name], label)
            found = await sounds_in(p.source) if p else []
            return found[0] if found else ""

        # What is heard of these, met in quiet: Ping and Tink are mid-pitched and
        # abrupt; Glass is mid-pitched and gradual; Basso is low and abrupt;
        # Purr mid-pitched and abrupt; Funk low and gradual.
        positives = [await sound_of("Ping", "pos1"), await sound_of("Tink", "pos2")]
        negatives = [await sound_of("Glass", "neg1"), await sound_of("Basso", "neg2")]
        check("every example entered by being heard", all(positives) and all(negatives),
              f"{positives} vs {negatives}")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            induced = await coord.learning.induce_category(
                CAT, positives=positives, negatives=negatives, domain=DOMAIN)
        # ONE RULE IS NOT ALWAYS DETERMINABLE, and here it cannot be: every
        # mid-pitched sound is pitched, so `mid_pitched & abrupt` and
        # `pitched & mid_pitched & abrupt` agree on every sound there could be.
        # The version space stands, and naming goes by its agreement.
        hypotheses = [str(c) for c in induced.candidates]
        check("naming hypotheses were induced from what was heard", bool(hypotheses),
              f"{induced.status.name}: " + " | ".join(hypotheses))
        EV.metric("induced_hypotheses", " | ".join(hypotheses), "formulas")
        if induced.deciding_request:
            EV.note(f"Induction's own request for a deciding case: {induced.deciding_request}")
        fresh = await sound_of("Purr", "fresh")
        held = await instance_predicates(db, fresh) if fresh else []
        check("a fresh sound is NAMED by the act of hearing it, with nobody asking",
              CAT in held, f"{fresh} isa {CAT}" if CAT in held else f"held {sorted(held)}")
        wrong = await sound_of("Funk", "wrong")
        wrong_held = await instance_predicates(db, wrong) if wrong else []
        check("and the wrong kind of sound is not", bool(wrong) and CAT not in wrong_held,
              f"{wrong}: {sorted(wrong_held)}")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            asked = await coord.reason_about(f"is {fresh} a {CAT}?",
                                             origin=Origin.own("HEAR-01"))
        answer = (getattr(asked, "answer", "") or "").strip()
        check("asking gives the same answer — one authority, two doors",
              answer.lower().startswith("yes"), answer[:80] or "(no answer)")

        # ── J. KIND ─────────────────────────────────────────────────────────
        print("\n== J. A kind heard twice is described, never by its framing ==")
        second = await sound_of("Ping-10dB", "second")
        second_held = await instance_predicates(db, second) if second else []
        check("a second instance is named too", CAT in second_held,
              f"{second}: {sorted(second_held)}")
        # Seven different recordings have now been heard. Each is its own
        # observation, however alike their accounts read.
        seven = ("pos1", "pos2", "neg1", "neg2", "fresh", "wrong", "second")
        ids = [memory_of.get(k) for k in seven]
        mets = await db.execute_query(
            "SELECT memory_id, metadata->>'met' AS met FROM memory_hot.memory_hot "
            "WHERE memory_id = ANY($1::text[])", ([i for i in ids if i],), fetch_all=True) or []
        check("seven different sounds heard are seven memories, never merged into one",
              all(ids) and len(set(ids)) == 7,
              f"{len(set(i for i in ids if i))} distinct of 7: " + ", ".join(
                  f"{k}={str(memory_of.get(k))[-6:]}" for k in seven))
        check("each memory knows WHAT was met, by the digest of its recording",
              len(mets) == 7 and len({r["met"] for r in mets if r["met"]}) == 7,
              f"{len({r['met'] for r in mets if r['met']})} distinct digests")

        kind = [(r.replace(" ", "_"), o) for r, o in await edges_of(CAT)]
        described = sorted(o for r, o in kind if r == "has_property")
        check("the kind now says what it sounds like, from what was heard of it",
              bool(described), f"{CAT} has_property {described}")
        check("and none of it is how loud, when or how long — the recording's facts",
              not ({r for r, _ in kind} & {"level", "starts_at", "lasts"}),
              f"relations on the kind: {sorted({r for r, _ in kind})}")

        # ── K. KNOWN ────────────────────────────────────────────────────────
        print("\n== K. A sound taught once is known when heard again ==")
        KNOWN = f"glass{tag}"
        marks = await coord.vision.learn_instance(KNOWN, str(SYSTEM_SOUNDS / "Glass.aiff"))
        check("the reference is kept by its landmarks", marks >= 100, f"{marks} landmark(s)")
        tink = await coord.vision.learn_instance(f"tink{tag}", str(SYSTEM_SOUNDS / "Tink.aiff"))
        check("a reference too featureless to recognise is refused, not kept",
              tink == 0 and f"tink{tag}" not in coord.vision.known_instances, f"{tink} landmark(s)")
        mixed = await hear(stim["mix"], "mix")
        detected = [d for d in (mixed.content.get("detections") or [])] if mixed else []
        check("heard again inside speech at equal level, it is recognised",
              any(d["label"] == KNOWN for d in detected),
              ", ".join(f"{d['label']} ({d['confidence']})" for d in detected) or "nothing")
        observed = [o for r, o in (await edges_of(mixed.source) if mixed else []) if r == "observed"]
        check("and the recognition is admitted as what was observed in it",
              KNOWN in observed, f"{mixed.source if mixed else '?'} observed {observed}")
        plain = await hear(JFK, "plain")
        plain_det = [d["label"] for d in (plain.content.get("detections") or [])] if plain else []
        others = []
        for k, rec in enumerate((LIBRI / "0.wav", LIBRI / "1.wav", SYSTEM_SOUNDS / "Ping.aiff")):
            p = await hear(rec, f"other{k}")
            others.extend(d["label"] for d in (p.content.get("detections") or []) if p)
        check("and it is not heard where it is not",
              KNOWN not in plain_det and KNOWN not in others,
              f"speech alone: {plain_det or 'nothing'}; others: {others or 'nothing'}")

        # ── L. VIDEO ────────────────────────────────────────────────────────
        print("\n== L. A clip is seen and heard on one percept ==")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            clip = await coord.see(str(stim["clip"]), source=f"h{tag}clip",
                                   domain=DOMAIN, actor_identity=None)
            await get_uncertainty_system().drain_writes()
        blobs = clip.content.get("blobs") or [] if clip else []
        seen = [b for b in blobs if "pitched" not in " ".join(b.get("isa") or [])]
        heard = [b for b in blobs if "pitched" in " ".join(b.get("isa") or [])]
        check("what was seen in it and what was heard in it are one percept",
              bool(seen) and bool(heard), f"{len(seen)} seen, {len(heard)} heard")
        check("with how good its hearing was stated on the clip",
              (clip.content.get("properties") or {}).get("hearing_is") in ("clear", "fair")
              if clip else False,
              str((clip.content.get("properties") or {}).get("hearing_is")) if clip else None)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            silent = await coord.see(str(JELLYFISH), source=f"h{tag}silent",
                                     domain=DOMAIN, actor_identity=None)
        check("a clip with no sound track says so, rather than looking silent",
              silent is not None
              and (silent.content.get("properties") or {}).get("hearing_is") == "no_soundtrack",
              str((silent.content.get("properties") or {}).get("hearing_is")) if silent else None)
    finally:
        # ── cleanup: everything this run wrote, by its nonce ────────────────
        # Counted BEFORE as well as after, so "nothing left" cannot be the work
        # of someone else emptying the sandbox mid-run: the run must have
        # written rows for their absence afterwards to mean it removed them.
        _tagged = ("SELECT (SELECT count(*) FROM unified.concepts WHERE name LIKE $1) + "
                   "(SELECT count(*) FROM unified.beliefs WHERE belief_text LIKE $1) + "
                   "(SELECT count(*) FROM unified.learned_rules WHERE rendered_formula LIKE $1) + "
                   "(SELECT count(*) FROM unified.perceptions WHERE source LIKE $1) + "
                   "(SELECT count(*) FROM memory_hot.memory_hot WHERE content::text LIKE $1) AS n")
        try:
            written = await db.execute_query(_tagged, (f"%{tag}%",), fetch_one=True)
        except Exception as error:
            written = None
            EV.note(f"Could not count this run's rows before cleanup: {error}")
        try:
            for name in (f"glass{tag}", f"tink{tag}"):
                await coord.vision.forget_instance(name)
            like = f"%{tag}%"
            await db.execute_query(
                "DELETE FROM unified.concept_relations WHERE source_concept_id IN "
                "(SELECT concept_id FROM unified.concepts WHERE name LIKE $1) "
                "OR target_concept_id IN (SELECT concept_id FROM unified.concepts "
                "WHERE name LIKE $1) OR target_surface LIKE $1", (like,), commit=True)
            await db.execute_query("DELETE FROM unified.concepts WHERE name LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.beliefs WHERE belief_text LIKE $1",
                                   (like,), commit=True)
            await db.execute_query(
                "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN (SELECT rule_id "
                "FROM unified.learned_rules WHERE rendered_formula LIKE $1)", (like,), commit=True)
            await db.execute_query("DELETE FROM unified.learned_rules "
                                   "WHERE rendered_formula LIKE $1", (like,), commit=True)
            await db.execute_query("DELETE FROM unified.experience_pool WHERE about LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.evidence_envelopes "
                                   "WHERE producer LIKE $1 OR source_id LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.perceptions WHERE source LIKE $1",
                                   (like,), commit=True)
            tagged = await db.execute_query(
                "SELECT memory_id FROM memory_hot.memory_hot WHERE content::text LIKE $1",
                (like,), fetch_all=True) or []
            for mid in set(memory_ids) | {r["memory_id"] for r in tagged}:
                await db.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1",
                                       (str(mid),), commit=True)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (str(mid),), commit=True)
            left = await db.execute_query(_tagged, (like,), fetch_one=True)
            EV.note(f"Cleanup by nonce {tag}: "
                    f"{written['n'] if written else 'an uncounted number of'} tagged row(s) "
                    f"written, {left['n']} left.")
        except Exception as error:
            print(f"  (cleanup: {error})")
            EV.note(f"Cleanup failed: {error}")

    passed = sum(1 for ok in results if ok)
    print(f"\n==== HEAR-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
