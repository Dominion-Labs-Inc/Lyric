# FEELING-OBJECT-01 — can the substrate say WHAT it feels about?

**Why it exists.** A feeling can be relieved four ways. Three already worked; the fourth
was unreachable.

1. **Constituent relief** — emotions here are derived properties, never stored, so
   `doubt = (1−confidence) + epistemic_opportunity + risk` cannot be stale while
   confidence is genuinely high. Correct by construction.
2. **Fade** — an unsupported emotion decays on a half-life (15 min), between the arousal's
   10 and the mood's 30.
3. **Nothing else may.** There is no setter for `_affect_emotion` or `_mood_valence`
   outside an appraisal-derived measurement and rehydration from the store. If the
   substrate could relieve its own doubt by deciding to, the doubt would be a dial, not a
   signal — it would carry no information about the world.
4. **Resolution of the cause** — needs an OBJECT, and nothing named one.

**What was missing.** `attribution` says WHY an outcome ended as it did and is fed only by
`outcome_class`, a task-outcome label, so outside a task it is `None`. `ThreatSense` has
always carried a `subject` and a `detail` per event and only the scalar magnitude ever
left it — the same defect shape this codebase already names for bearing: *a famine and a
file with a `.txt` extension arrived differing only in magnitude*. So the substrate could
feel doubt and be unable to say what it doubted, and a feeling with no object can only be
waited out.

## The eight properties

| | |
|---|---|
| **A** | the threat names WHAT it is about, not only how much — the heaviest DECAYED contributor |
| **B** | that object reaches appraisal as `about` / `about_domain` |
| **C** | the feeling carries it |
| **D** | it survives a restart, like the feeling it belongs to |
| **E** | the substrate can SAY it, in its own words |
| **F** | a faded doubt leaves its question behind, idempotently |
| **G** | no object ⇒ no question — counted as lost, never invented |
| **H** | a partial update does not erase the object |

**F is the asymmetry worth the whole experiment.** Fading is alleviation by TIME, and for
satisfaction that is harmless — it was about something finished. Doubt is not symmetric
with it. Doubt is an open question wearing a feeling, and letting the feeling lapse with
nothing recorded means the substrate stopped wondering about something it never settled:
strictly worse than staying uncertain, because the uncertainty stops being visible to the
machinery that exists to resolve it. So the feeling goes and the QUESTION is handed to its
owner, the belief authority's known-unknowns, in the domain the object was met in.

**G is why F is not fabrication.** A doubt that faded without appraisal ever naming what
it was about cannot be written down without inventing a subject. It is counted as lost and
logged, not turned into a question the substrate never had.

## About is not attribution

They answer different questions and are kept apart deliberately:

- `attribution` — WHY an outcome ended that way (`strategy_failure`). Fed by `outcome_class`.
- `about` — WHAT the state concerns (`integrity:<module>`). Named by whoever met it.

Both are carried forward in `_blend` for the same reason: an update silent about the
object has not made the feeling object-less.

## Measuring this is a trap

The fade is wall-clock. The run moves the affect anchor back two hours and sets appraisal
to a genuinely UNMEASURED state — which is what the substrate is in outside a task, and
exactly when the fade branch runs. It does not stub the clock or reach into the emotion.

## Run

```
./venv_torin/bin/python3 experiments/FEELING-OBJECT-01/experiment.py
```

Runs a LIVE substrate. Every belief and known-unknown it creates is removed before it
exits. Each run writes a structured record to `results/<timestamp>.json` with a `.md`
summary beside it.
