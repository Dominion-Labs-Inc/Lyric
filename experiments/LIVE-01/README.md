# LIVE-01 — always listening and looking, keeping only what is said to it

**Finding (2026-09-28).** The live senses (`core/perception/live.py`) listen to a microphone and
look at a camera for as long as the substrate runs, and keep only what is said to it. They ran as
real programs, against a stream played in real time exactly as a device feeds them:
- a real room, recorded from this Mac's microphone;
- a speaker, the rule-based macOS voice "Fred";
- the repo's real jellyfish footage, as the camera.

Results (record `20260929T011204Z`, 17/17):
- **Dropped:** before its name was taught, everything, even its name, and it said why. Also the
  room's own clicks and hum, the unaddressed questions, and a question after attention had
  lapsed: **22 utterances, 19.9 s**. None left a percept or a memory.
- **Kept:** the name was taught while it listened, and was listened for within 8 s. From then on
  it kept the three questions said to it by name, and the talk that followed without the name.
  Each became a hearing remembered in words, as a trace, with no recording left on disk, and the
  scene was looked at each time.
- **Answered:** two of the four hearings came through complete, every word a taught word:
  - "are mammals animals" was answered through the front door typed words go to: *"Yes, a
    mammal is an animal. Yes, mammals are animals."*;
  - "are cats animals" was not known, so it asked back.

  Both exchanges are in the same conversation memory as typed ones. The two incomplete hearings
  were remembered and not acted on.

**Re-run 2026-09-29: 18/18** (record `20260929T140643Z`). Since the first runs:
- The take-in is two-phase: sensed first, then remembered within the pursuit a request forms.
- Kept utterances say "heard before". That is true here: the stream replays the recordings its lessons taught.
- **The experiment now teaches what it asks.** A re-run in between (17/17, `20260929T140157Z`) showed the
  spoken "are mammals animals" answered "could not answer". After the sandbox resets nothing held it: a
  lesson's example sentences are how English says things, never world facts. The run had relied on a fact left
  there by chance. It now teaches "a mammal is an animal" as a fact when it is not held (left in place, as
  SENSES-TOGETHER-01 does). A check fixed before the run requires the spoken question to be answered yes.
  Answered: "Yes. A mammal is an animal."
- That run also recited a lesson hearing as knowledge. The session that owns replies fixed it at the root: a
  remembered memory is recited only when it names what was asked and reads as a telling, which a hearing's
  record does not.

**How the ear decides.**
- **Utterances** are hearing's own sounds: held above the room, counted only once they rise above
  it. Sounds that follow each other within 0.8 s are one utterance.
- **Kept** when its taught name is found in it, or when taught words are **firmly** heard in it
  (support ≥ 0.5) within 8 s of a kept one.
- **Dropped otherwise**, inside the ear's own process: only its length leaves.

**Found while building it**, each measured before it was fixed:
- **My streaming utterance rule was not hearing's.** I let any flicker above the hold level keep
  an utterance going. This real room flickers just above that level every fraction of a second,
  so utterances ran to the 15 s cap. The ear now finds sounds exactly as `hearing.segment` does.
- **Attention held open for good by the room.** The room's own 87 Hz hum recurred and re-opened
  attention each time. Neither voicing nor `judge_voice` tells it from a voice: it lies inside
  the reach of two taught synthetic voices. No taught word is ever heard in it, so attention is
  now held by firmly heard words.
- **The attention clock ran on wall time.** A stream fed faster than real time never let
  attention lapse. It now runs on the stream's own clock.
- **The ear aborted at exit.** A thread blocked on stdin met the interpreter's shutdown:
  `_enter_buffered_busy`, SIGABRT, and a macOS "Python quit unexpectedly" report each time. The
  programs now exit directly (`os._exit`) once everything is sent. The run recorded here passed
  before that fix, and the fix only changes how the programs exit.
- **A played recording ending was logged as an error.** The ear now says when its source has
  ended. A file played to it ending is logged as information. A microphone that stops giving
  sound, or an ear program that dies, is logged as an error. Checked by running the ear program
  on a 2 s recording, with no store.

**Limits, stated.**
- Spoken sentences are understood only as far as words were taught. Short words said in flowing
  speech ("a", "an") are absorbed or lost. Taught from words said alone, it reliably takes words
  said one at a time with short pauses. In the real room it missed "mammals" once, and "do"
  twice.
- The room recording loops every 8.3 s, so its hum recurs more often than a real room's would.
- Replies are text. A voice of its own is later work, as decided.

**Checked properties (18):** A unnamed (2); B taught live (1); C addressed (3); D dropped (1);
E remembered (3); F looked (1); G answered (6); H stopped (1). See `experiment.py`.

Run (sandbox store; the system is initialised, not started, so a queued task is never run):
`./venv_lyric/bin/python3 experiments/LIVE-01/experiment.py`
