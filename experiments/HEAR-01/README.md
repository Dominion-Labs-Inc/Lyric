# HEAR-01 — hearing is a sense of the substrate, on sight's own path

**Finding (2026-09-28).** Hearing was built as a reader under the one perception faculty,
not as a faculty beside it. Each sound is stated as a perceived individual on the contract
sight already uses. So admission, belief, memory, the naming reflex, induction, describing a
kind and the acceptance band all serve hearing with no code of their own.

Through `coordinator.hear()`, the live substrate:
- heard JFK's inaugural sample as 6 sounds on a room-hiss ground;
- held 60 beliefs about them and remembered them as a trace of the sounds, 6% of the recording's
  size, never the recording itself (see RECALL-01 for hearing it again from memory);
- judged each claim (24 ACT, 6 VERIFY);
- learned by its own induction to name a kind of sound from four heard examples, then named
  fresh sounds as they were heard, and answered the same when asked;
- described the kind it had only heard ("has property abrupt, mid-pitched, pitched");
- recognised a known sound mixed into speech at equal level, and nowhere else.

A clip is seen and heard on one percept.

The run found **two defects in shared code**. Neither was in hearing, and both would have
affected sight the same way. Both are fixed at the root and have their own checks here:

| defect | what it did | fix |
|---|---|---|
| a kind's parts were recognised by **sharing a domain** | `describe_kind` states `<kind> has_property <feature>` in the perception domain, which creates never-taught feature words (`abrupt`) there. From then on every such feature read as a "co-perceived part" with nothing observed of it, and was dropped. After one description, no later kind in that domain could be described. | a part is what the **same percept `contains`** (`concept_graph_reasoning.observed_instance_description`) |
| memories were merged on **similarity alone** | percept accounts are short and alike ("1.5s aiff recording, 1 sound(s): an abrupt mid-pitched sound"). Ping, Submarine and Glass became ONE memory, so every belief about three different sounds named it. | the memory agent stamps `met` (the sha256 of the media) and `_could_be_the_same_claim` refuses to merge different things met |

**Properties checked** (42):

| # | property |
|---|---|
| A | a real recording is heard through the one door; the percept is named from its content, not from who listened |
| B | each sound is its own concept. `isa` holds only pitched/unpitched, register and onset; level, start and length are stated apart, never as `isa`; `before`/`louder_than`/`higher_than` are admitted between neighbours |
| C | what was heard is held as beliefs |
| D | the hearing forms a memory that keeps a TRACE of the sounds (`application/x-npz`, a few percent of the recording) and never the recording, and is found by what was heard |
| E | the acceptance band judges it per claim, and the judgement reaches the reaction system as an event |
| F | the whole hearing waits in the experience pool, through `hear`, met as a sound |
| G | `see` refuses a recording (naming `hear`); `hear` refuses a picture |
| H | over 19 real recordings, every FIRMLY read register, pitchedness, onset and relation survives gain, padding and mp3 (near-cut readings are reported, and flip only as their support says they may). The level follows the gain every time, so it belongs to the recording |
| I | the substrate induces naming hypotheses from four heard examples, names a fresh sound by hearing it, does not name the wrong kind, and gives the same answer when asked. Seven different sounds are seven memories with seven digests |
| J | a kind named twice is described by what was heard of it, and never by level, start or length |
| K | a known sound (320 landmarks) is recognised inside speech at equal level, admitted as `observed`, and not heard in speech or other sounds. A featureless reference (Tink, 6 landmarks) is refused |
| L | a clip with a sound track is one percept of what was seen and what was heard; a clip with none says `no_soundtrack` |

**The trap in measuring it.**
- **Sounds must be met as a hearing meets them.** The macOS sound files begin at their very
  first sample, where no hearing can tell a sound's start from a recording that cut into it, so
  no onset is claimed for them. Section I hears each sound after a quarter second of quiet, as it
  would be met in a room.
  The naming fixture was rebuilt on what the corrected describer hears: Submarine swells over
  90 ms and is gradual. An analysis-grid artifact had read it as abrupt, and the old fixture was
  built on that reading.
- **One rule is not always determinable.** When the version space keeps two hypotheses that
  agree on every sound, naming goes by their agreement. So the check reads the hypotheses, not
  `InductionResult.rule`.
- **A check's position matters.** The seven-memories check first ran before the seventh sound
  was heard, and blamed the memory agent for a hearing that had not happened yet.
- **Nuisance numbers were measured before the checks were written.** A scratch battery ran
  first, and its thresholds are the hypotheses H1/H2 stated in the notebook, not values fitted
  afterwards.
- **What is only reported, not checked.** Reverb, telephone band and 20 dB noise are metrics:
  - register survives 21/24, 23/24 and 20/24 of them;
  - a low note loses its fundamental on a telephone line and is read an octave or two up.

**Recordings.** From the repo:
- the JFK inaugural sample (`third_party/whisper.cpp/samples/jfk.wav`);
- a speech sample (`third_party/llama.cpp/tools/mtmd/test-2.mp3`);
- a silent real clip (`test_data/jellyfish_real_10s.mp4`).

From this machine:
- three LibriSpeech utterances (`r1-rom/asr/.../test_wavs`);
- the macOS system sounds (`/System/Library/Sounds`), so sections H–K need macOS.

`stimuli/` is built on first run from those real recordings: Glass mixed into JFK at equal
level, and the jellyfish clip given JFK's audio.

**Run** (sandbox store, boots the full system; everything the run writes is removed by its
nonce afterwards):

```
POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/HEAR-01/experiment.py
```

**Results.** Each run writes `results/<UTC timestamp>.json` and a `.md` beside it.
- `20260928T135523Z`: 42/42, the first run with both shared-code fixes and their checks.
- `20260928T140458Z`: 42/42 on the final code (an unreadable file now raises instead of
  reading as "no sound track"). 0 tagged rows left.
- `20260928T140856Z`: 42/42, re-run after learning that another session had emptied the whole
  sandbox three times earlier in the day. The cleanup now counts before as well as after:
  686 tagged rows written, 0 left. So the empty sandbox is this run's own cleanup, not
  someone else's reset.
- `20260928T151333Z`: 42/42 after the describer was hardened, alongside RECALL-01:
  - a path-tracked pitch;
  - a 1024-sample pitch frame;
  - supports scaled by effective frame count;
  - attack read on a fine envelope.
  D now requires a trace, not a recording. H counts firm readings: register 88/88,
  pitchedness 96/96, onset 32/32, relations 69/69. Naming finds one rule,
  `abrupt ∧ mid_pitched`. 687 tagged rows written, 0 left.
