#!/usr/bin/env python3
"""SPEECH-01 — spoken words and voices, taught by example, heard by the substrate.

No model anywhere. Words and voices are TAUGHT by hearing them: a recording of a
word being said, of a person speaking, heard and told what it is. The lesson is
a hearing like any other, remembered as one, and heard speech is matched
against what those hearings kept. This boots the real substrate, teaches it, and
hears real recordings through `coordinator.hear()`, asserting what happened at
every stage and at every seam.

  A  TAUGHT      each example is HEARD through the one door, told what it is,
                 and remembered as a hearing like any other: the same memory,
                 saying what it taught, its trace keeping the example measured
                 for matching, and heard again in the mind as any hearing is;
                 a recording with nothing said in it is refused, nothing kept.
  B  RESTART     a fresh faculty reads the taught words and voices back from
                 memory, exactly as they were taught.
  C  HEARD       a taught speaker saying taught words is heard as those words,
                 in order, in that speaker's voice, and each sound as a voice.
  D  ADMITTED    what was said and whose voice said it are in the concept graph
                 and held as beliefs.
  E  REMEMBERED  the hearing's memory says what was said, in words, and keeps a
                 trace of the sound, never the recording.
  F  JUDGED      what was said and whose voice are judged by the acceptance band
                 with everything else heard.
  G  EXPERIENCE  the hearing is handed to the memory agent whole.
  H  NOT A VOICE a system sound is no voice, and nothing is said in it.
  I  VIDEO       words said in a clip's sound track are heard on the clip.
  J  UNTAUGHT    with nothing taught, no speech is heard as words.
  K  ACCURACY    over real phrases, strangers and untaught words: firm readings
                 are right; weak ones are counted.

Recordings: the Free Spoken Digit Dataset (test_data/fsdd, six speakers, CC
BY-SA 4.0), presented as a live buffer presents speech -- with room quiet
around it -- and the macOS system sounds (so sections H and K need macOS).
Stimuli are built from those real recordings into `stimuli/` on first run.

Run (sandbox store): ./venv_lyric/bin/python3 experiments/SPEECH-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
FSDD = REPO / "test_data" / "fsdd"
SYSTEM_SOUNDS = Path("/System/Library/Sounds")
JELLYFISH = REPO / "test_data" / "jellyfish_real_10s.mp4"

NAMES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
TAUGHT_DIGITS = range(8)           # eight and nine are never taught
TEACHER = "george"                 # whose words are taught
VOICES = ("george", "jackson", "lucas")
STRANGERS = ("nicolas", "theo", "yweweler")
EXAMPLES = 5                       # taught examples of each word
QUIET_DB = -60.0                   # the room's floor

EV = RunRecord(
    "SPEECH-01",
    claim=("Spoken words and voices are taught to the substrate by example and kept "
           "as memories; heard speech is then heard as the words said, in whose "
           "voice, admitted, believed, remembered in words, judged and handed over "
           "-- with no model anywhere, and nothing heard as a word that was not "
           "taught."),
    hypothesis=("H1 a taught word said in running speech is found and named by the "
                "same test a word said alone passes. H2 whether a sound is a voice "
                "is settled by how near the taught voices it lies, measured against "
                "how near they lie to one another. H3 whose voice is named only when "
                "one taught voice clearly wins, on enough speech to know a person "
                "by. H4 firm readings are right: a name given to an untaught word "
                "or to a stranger is never a firm one."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── stimuli, built from real recordings ─────────────────────────────────────

def build_stimuli() -> dict:
    """Real recordings presented as a live buffer presents speech: with room
    quiet around them (seeded, so every run hears the same)."""
    import numpy as np
    import soundfile as sf
    from core.perception import hearing as H
    rng = np.random.default_rng(20260928)
    quiet = lambda s: rng.normal(0, 10 ** (QUIET_DB / 20), int(s * H.SR))
    said = lambda spk, d, take: H.decode(str(FSDD / f"{d}_{spk}_{take}.wav"))

    def room(*parts, gap=0.12):
        out = [quiet(0.3)]
        for k, y in enumerate(parts):
            out += [y, quiet(gap if k < len(parts) - 1 else 0.3)]
        return np.concatenate(out)

    def write(rel, y):
        path = STIM / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(path), np.clip(y, -1, 1).astype(np.float32), H.SR)
        return path

    stim = {"teach": {}, "voice": {}, "phrases": [], "untaught": [], "strangers": []}
    for d in TAUGHT_DIGITS:
        stim["teach"][d] = [write(f"teach/{d}_{TEACHER}_{i}.wav", room(said(TEACHER, d, i)))
                            for i in range(EXAMPLES)]
    for p in VOICES:
        stim["voice"][p] = [write(f"voice/{p}_{i}.wav",
                                  room(*[said(p, d, i) for d in range(10)]))
                            for i in (5, 6)]
    stim["silence"] = write("silence.wav", quiet(1.5))
    stim["heard"] = write("heard/george_three_one_four.wav",
                          room(said(TEACHER, 3, 20), said(TEACHER, 1, 21), said(TEACHER, 4, 22)))
    pick = np.random.default_rng(7)
    for k in range(8):
        digits = [int(pick.integers(0, 8)) for _ in range(3)]
        takes = [int(pick.integers(10, 50)) for _ in digits]
        stim["phrases"].append((digits, write(
            f"phrases/{k}_{''.join(map(str, digits))}.wav",
            room(*[said(TEACHER, d, t) for d, t in zip(digits, takes)]))))
    for k in range(4):
        digits = [int(pick.integers(8, 10)) for _ in range(2)]
        takes = [int(pick.integers(10, 50)) for _ in digits]
        stim["untaught"].append((digits, write(
            f"untaught/{k}_{''.join(map(str, digits))}.wav",
            room(*[said(TEACHER, d, t) for d, t in zip(digits, takes)]))))
    for k, p in enumerate(STRANGERS + STRANGERS[:1]):
        digits = [int(pick.integers(0, 10)) for _ in range(5)]
        stim["strangers"].append((p, write(
            f"strangers/{k}_{p}.wav",
            room(*[said(p, d, int(pick.integers(10, 50))) for d in digits]))))
    clip = STIM / "jellyfish_with_george.mp4"
    if not clip.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(JELLYFISH), "-i",
                        str(stim["heard"]), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", str(clip)], check=True)
    stim["clip"] = clip
    return stim


async def main() -> int:
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
    await db.assert_database_identity(os.environ["POSTGRES_DATABASE"])
    import numpy as np
    from core.perception import hearing as H
    from core.perception import speech as SP
    from core.perception.perception_faculty import PerceptionFaculty
    from core.memory.media_store import get_media_store
    stim = build_stimuli()

    tag = uuid.uuid4().hex[:6]
    DOMAIN = "hearing"
    word_of = {d: f"{NAMES[d]}_{tag}" for d in range(10)}
    person_of = {p: f"{p}_{tag}" for p in VOICES}
    memory_ids = []
    events = []
    coord.on(SelfEventType.PERCEPT_RECOGNIZED, lambda ev: events.append(ev),
             name=f"speech01_probe_{tag}")
    faculty = coord.vision

    async def hear(path, label):
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await coord.hear(str(path), source=f"s{tag}{label}", domain=DOMAIN,
                                       actor_identity=None)
            await get_uncertainty_system().drain_writes()
        meta = (percept.metadata or {}) if percept is not None else {}
        if meta.get("memory_id"):
            memory_ids.append(meta["memory_id"])
        return percept

    async def edges_of(name):
        rows = await db.execute_query(
            "SELECT cr.relation AS rel, COALESCE(c2.name, cr.target_surface) AS obj "
            "FROM unified.concept_relations cr "
            "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
            "WHERE c1.name = $1", (name,), fetch_all=True) or []
        return [(str(r["rel"]), str(r["obj"])) for r in rows]

    try:
        # ── A. TAUGHT ───────────────────────────────────────────────────────
        print("\n== A. Words and voices are taught by example, as memories ==")
        await faculty._read_library()
        before = (dict(faculty.taught_words), dict(faculty.taught_voices))
        EV.note(f"Taught before this run: {len(before[0])} word(s), {len(before[1])} voice(s).")
        taught_ids = {}
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            for d in TAUGHT_DIGITS:
                taught_ids[d] = [await coord.learn_word(word_of[d], str(p), actor_identity=None,
                                                        source=f"s{tag}w{d}x{i}", domain=DOMAIN)
                                 for i, p in enumerate(stim["teach"][d])]
            voice_ids = {p: [await coord.learn_voice(person_of[p], str(path), actor_identity=None,
                                                     source=f"s{tag}v{p}x{i}", domain=DOMAIN)
                             for i, path in enumerate(stim["voice"][p])] for p in VOICES}
            await get_uncertainty_system().drain_writes()
        every = [m for ids in taught_ids.values() for m in ids] + \
                [m for ids in voice_ids.values() for m in ids]
        memory_ids.extend(every)
        check("every example taught was heard, and remembered as a hearing of its own",
              len(set(every)) == len(TAUGHT_DIGITS) * EXAMPLES + 2 * len(VOICES),
              f"{len(set(every))} memories for {len(TAUGHT_DIGITS)} words x {EXAMPLES} "
              f"and {len(VOICES)} voices x 2")
        import json
        as_json = lambda v: json.loads(v) if isinstance(v, str) else (v or {})
        row = await db.execute_query(
            "SELECT memory_type, tags, metadata, content FROM memory_hot.memory_hot "
            "WHERE memory_id = $1", (str(taught_ids[3][0]),), fetch_one=True)
        ctx = as_json(row["metadata"]) if row else {}
        origin = (ctx or {}).get("origin") or {}
        tags = as_json(row["tags"]) if row else []

        def text_of(content):
            # The store keeps a memory's content as JSON text.
            try:
                return str(json.loads(content))
            except (TypeError, ValueError):
                return str(content)
        said_in_it = bool(row) and f'taught: how the word "{word_of[3]}" sounds' in text_of(row["content"])
        check("a lesson is the same memory as any hearing, and says what it taught",
              bool(row) and {"sound", "hearing", "spoken_word"} <= set(tags)
              and ctx.get("word") == word_of[3] and origin.get("through") == "hear" and said_in_it,
              f"{row['memory_type'] if row else None}, tags {tags}, through {origin.get('through')}, "
              f"word {ctx.get('word')}, says so: {said_in_it}")
        kept = await get_media_store().media_for_memory(str(taught_ids[3][0]))
        taught_now = SP.word_features(H.decode(str(stim["teach"][3][0])))
        check("its trace keeps the example measured for matching, never the recording",
              len(kept) == 1 and kept[0]["mime"] == "application/x-npz"
              and kept[0]["perceived"].get("kind") == "sound_trace"
              and kept[0]["perceived"].get("lesson") == {"word": word_of[3]}
              and np.array_equal(SP.unpack(kept[0]["bytes"]), taught_now),
              f"{kept[0]['mime']}, {kept[0]['byte_size']} bytes, {len(taught_now)} frames"
              if kept else "nothing kept")
        rebuilt = await coord.recollect(str(taught_ids[3][0]))
        check("and the lesson can be heard again in the mind, as any hearing can",
              bool(rebuilt) and rebuilt[0].get("kind") == "sound"
              and len(rebuilt[0].get("samples", [])) > 0,
              f"{len(rebuilt[0].get('samples', [])) / H.SR:.2f}s rebuilt" if rebuilt else "nothing")
        vrow = await db.execute_query(
            "SELECT tags, metadata, content FROM memory_hot.memory_hot WHERE memory_id = $1",
            (str(voice_ids["lucas"][0]),), fetch_one=True)
        check("a voice is taught the same way, and kept in the same kind of memory",
              bool(vrow) and {"hearing", "voice"} <= set(as_json(vrow["tags"]))
              and as_json(vrow["metadata"]).get("person") == person_of["lucas"],
              str(vrow["content"])[-80:] if vrow else None)
        count = await db.execute_query(
            "SELECT count(*) AS n FROM memory_hot.memory_hot WHERE content LIKE $1",
            (f"%{tag}%",), fetch_one=True)
        refused = None
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                await coord.learn_word(f"quiet_{tag}", str(stim["silence"]), actor_identity=None,
                                       source=f"s{tag}quiet", domain=DOMAIN)
        except ValueError as error:
            refused = str(error)
        after = await db.execute_query(
            "SELECT count(*) AS n FROM memory_hot.memory_hot WHERE content LIKE $1",
            (f"%{tag}%",), fetch_one=True)
        check("a recording with nothing said in it is refused, and nothing is kept",
              refused is not None and after["n"] == count["n"], refused)

        # ── B. RESTART ──────────────────────────────────────────────────────
        print("\n== B. A fresh faculty reads what was taught back from memory ==")
        fresh = PerceptionFaculty()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await fresh.load_instances()
        words = {w: n for w, n in fresh.taught_words.items() if tag in w}
        voices = {p: n for p, n in fresh.taught_voices.items() if tag in p}
        check("every taught word, with every example",
              words == {word_of[d]: EXAMPLES for d in TAUGHT_DIGITS}, str(words)[:160])
        check("every taught voice, with every example",
              voices == {person_of[p]: 2 for p in VOICES}, str(voices))
        back = fresh._words.get(word_of[3]) or []
        check("exactly as they were taught",
              any(np.array_equal(b, taught_now) for b in back), f"{len(back)} example(s) of three")

        # ── C. HEARD ────────────────────────────────────────────────────────
        print("\n== C. A taught speaker saying taught words is heard as those words ==")
        percept = await hear(stim["heard"], "heard")
        content = percept.content if percept else {}
        subject = percept.source if percept else None
        said = [s["word"] for s in content.get("said") or []]
        expected = [word_of[3], word_of[1], word_of[4]]
        check("what was said was heard as the words taught, in order, none wrongly",
              len(said) >= 2 and said == [w for w in expected if w in said],
              f'said "{content.get("heard_text")}"')
        check("in the voice of the one who said it",
              (content.get("spoken_by") or {}).get("person") == person_of[TEACHER],
              str(content.get("spoken_by")))
        blobs = content.get("blobs") or []
        voiced = [b for b in blobs if "voice" in (b.get("isa") or [])]
        check("each voiced sound is heard as a voice, with the support it earned",
              bool(voiced) and all(0.0 < b["isa_support"].get("voice", 0) <= 1.0 for b in voiced),
              f"{len(voiced)} of {len(blobs)} sound(s) isa voice")

        # ── D. ADMITTED ─────────────────────────────────────────────────────
        print("\n== D. What was said, and by whom, is admitted and believed ==")
        edges = await edges_of(subject) if subject else []
        check("the recording SAID each word heard, in the concept graph",
              bool(said) and {("said", w) for w in said} <= set(edges),
              ", ".join(f"{r} {o}" for r, o in edges if r in ("said", "spoken_by")))
        check("and was SPOKEN BY the one whose voice it was",
              ("spoken_by", person_of[TEACHER]) in edges)
        sound_edges = await edges_of(voiced[0]["name"]) if voiced else []
        check("a sound heard as a voice IS one",
              ("isa", "voice") in sound_edges, voiced[0]["name"] if voiced else None)
        rows = await db.execute_query(
            "SELECT belief_text FROM unified.beliefs WHERE belief_text LIKE $1 "
            "AND (belief_text LIKE '% said %' OR belief_text LIKE '% spoken_by %')",
            (f"{subject}%",), fetch_all=True) or []
        check("what was said and by whom are held as beliefs",
              len(rows) >= len(set(said)) + 1, "; ".join(str(r["belief_text"]) for r in rows)[:200])

        # ── E. REMEMBERED ───────────────────────────────────────────────────
        print("\n== E. The hearing is remembered in words ==")
        memory_id = (percept.metadata or {}).get("memory_id") if percept else None
        mrow = await db.execute_query(
            "SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1",
            (str(memory_id),), fetch_one=True) if memory_id else None
        check("the memory says what was said, in words",
              bool(mrow) and all(w in str(mrow["content"]) for w in said)
              and person_of[TEACHER] in str(mrow["content"]),
              str(mrow["content"])[:160] if mrow else None)
        media = await coord.recall_media(memory_id) if memory_id else []
        kept = media[0] if media else {}
        truth = hashlib.sha256(Path(stim["heard"]).read_bytes()).hexdigest()
        check("and keeps a trace of the sound, never the recording",
              bool(kept) and (kept.get("perceived") or {}).get("kind") == "sound_trace"
              and hashlib.sha256(kept["bytes"]).hexdigest() != truth
              and (kept.get("perceived") or {}).get("heard_text") == content.get("heard_text"),
              f"{kept.get('mime')}, {kept.get('byte_size')} bytes" if kept else "nothing kept")

        # ── F. JUDGED ───────────────────────────────────────────────────────
        print("\n== F. What was said is judged with everything else heard ==")
        mine = [e for e in events if getattr(e.payload, "subject", None) == subject]
        claims = [c for c in (mine[-1].payload.claims if mine else [])
                  if " said " in c.claim or " spoken_by " in c.claim]
        check("each word said and whose voice is a claim with its own verdict",
              len(claims) >= len(set(said)) + 1
              and all(c.decision in ("ACT", "VERIFY", "ABSTAIN") for c in claims),
              "; ".join(f"{c.claim.split(' ', 1)[1]}: {c.decision}" for c in claims)[:200])
        check("and each was believed, not merely stated",
              bool(claims) and all(c.posterior is not None for c in claims),
              ", ".join(f"{c.posterior:.2f}" for c in claims if c.posterior is not None))

        # ── G. EXPERIENCE ───────────────────────────────────────────────────
        print("\n== G. The hearing is handed over whole ==")
        exp = await db.execute_query(
            "SELECT kind, through, parts FROM unified.experience_pool WHERE about = $1",
            (subject,), fetch_all=True) or []
        parts = str(exp[0]["parts"]) if exp else ""
        check("an experience of the hearing, with what was said in it, waits in the pool",
              any(r["through"] == "hear" for r in exp) and "heard_text" in parts,
              ", ".join(f"{r['kind']} through {r['through']}" for r in exp))

        # ── H. NOT A VOICE ──────────────────────────────────────────────────
        print("\n== H. A sound that is not a voice ==")
        sub = await hear(SYSTEM_SOUNDS / "Submarine.aiff", "submarine")
        sc = sub.content if sub else {}
        check("a system sound is heard, and no sound in it is a voice",
              bool(sc.get("blobs")) and not any("voice" in (b.get("isa") or [])
                                                for b in sc.get("blobs") or []),
              sc.get("caption"))
        check("nothing is said in it, and no one's voice is named",
              not sc.get("said") and not sc.get("spoken_by"))

        # ── I. VIDEO ────────────────────────────────────────────────────────
        print("\n== I. Words said in a clip are heard on the clip ==")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            clip = await coord.see(str(stim["clip"]), source=f"s{tag}clip", domain=DOMAIN,
                                   actor_identity=None)
            await get_uncertainty_system().drain_writes()
        cc = clip.content if clip else {}
        clip_said = [s["word"] for s in cc.get("said") or []]
        check("what was said in the sound track is on the clip's percept, none wrongly",
              bool(clip_said) and set(clip_said) <= set(expected), f'said "{cc.get("heard_text")}"')

        # ── J. UNTAUGHT ─────────────────────────────────────────────────────
        print("\n== J. With nothing taught, no speech is heard as words ==")
        blank = PerceptionFaculty()
        blank._instances_loaded = True          # a faculty that was taught nothing
        _modality, bc = await blank.sense(str(stim["heard"]))
        check("the same speech, heard by a faculty taught nothing, has no words and no one's voice",
              not bc.get("said") and not bc.get("spoken_by")
              and not any("voice" in (b.get("isa") or []) for b in bc.get("blobs") or []),
              bc.get("caption"))

        # ── K. ACCURACY ─────────────────────────────────────────────────────
        print("\n== K. Over real phrases: firm readings are right ==")
        named = right = wrong_firm = wrong = slots = 0
        for digits, path in stim["phrases"]:
            _m, c = await faculty.sense(str(path))
            got = c.get("said") or []
            slots += len(digits)
            said_words = [s["word"] for s in got]
            for s in got:
                named += 1
                if s["word"] in {word_of[d] for d in digits}:
                    right += 1
                else:
                    wrong += 1
                    wrong_firm += int(s["support"] >= 0.5)
        EV.metric("taught_words_named_right", f"{right}/{slots}", "words",
                  "3-word phrases of taught words, taught speaker")
        EV.metric("words_named_not_in_phrase", wrong, "words")
        check("taught words in running speech are heard (measured offline: 64-75%)",
              right >= 0.5 * slots, f"{right} of {slots} named right, {wrong} named not said")
        check("no word is FIRMLY named that was not said", wrong_firm == 0,
              f"{wrong_firm} firm, {wrong} weak")
        untaught_named = untaught_firm = 0
        for digits, path in stim["untaught"]:
            _m, c = await faculty.sense(str(path))
            for s in c.get("said") or []:
                untaught_named += 1
                untaught_firm += int(s["support"] >= 0.5)
        EV.metric("untaught_words_named", untaught_named, "words", "of 8 untaught words said")
        check("no word never taught is FIRMLY heard as a taught one", untaught_firm == 0,
              f"{untaught_named} named, {untaught_firm} firmly")
        stranger_voice = stranger_named = stranger_firm = 0
        for p, path in stim["strangers"]:
            _m, c = await faculty.sense(str(path))
            stranger_voice += int(any("voice" in (b.get("isa") or []) for b in c.get("blobs") or []))
            who = c.get("spoken_by") or {}
            stranger_named += int(bool(who))
            stranger_firm += int(bool(who) and who.get("support", 0) >= 0.5)
        EV.metric("strangers_named_as_taught", f"{stranger_named}/{len(stim['strangers'])}", "stretches")
        check("a stranger speaking is heard as a voice",
              stranger_voice == len(stim["strangers"]),
              f"{stranger_voice} of {len(stim['strangers'])}")
        check("and is never FIRMLY named as someone taught", stranger_firm == 0,
              f"{stranger_named} named, {stranger_firm} firmly")
    finally:
        # ── cleanup: everything this run wrote, by exact id and by its nonce ─
        _tagged = ("SELECT (SELECT count(*) FROM unified.concepts WHERE name LIKE $1) + "
                   "(SELECT count(*) FROM unified.beliefs WHERE belief_text LIKE $1) + "
                   "(SELECT count(*) FROM unified.perceptions WHERE source LIKE $1) + "
                   "(SELECT count(*) FROM memory_hot.memory_hot WHERE content::text LIKE $1) AS n")
        try:
            written = await db.execute_query(_tagged, (f"%{tag}%",), fetch_one=True)
        except Exception as error:
            written = None
            EV.note(f"Could not count this run's rows before cleanup: {error}")
        try:
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
            for mid in set(map(str, memory_ids)) | {str(r["memory_id"]) for r in tagged}:
                await db.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1",
                                       (mid,), commit=True)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (mid,), commit=True)
            left = await db.execute_query(_tagged, (like,), fetch_one=True)
            EV.note(f"Cleanup by nonce {tag} and exact memory id: "
                    f"{written['n'] if written else 'an uncounted number of'} tagged row(s) "
                    f"written, {left['n']} left.")
        except Exception as error:
            print(f"  (cleanup: {error})")
            EV.note(f"Cleanup failed: {error}")

    passed = sum(1 for ok in results if ok)
    print(f"\n==== SPEECH-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
