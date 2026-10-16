# DEVICE-01 — Lyric learns a device it operates through, as it learns where it runs

**Finding.** A person's device answers for itself (what it is, what exists on it at all, what the person
set), and Lyric situates itself in it the way it situates itself in its host. The kind of device
(platform, major release, model, form) is a first-class ENVIRONMENT domain, met once and investigated:
what exists there becomes Lyric's own knowledge of that kind of place, a capability it lacks held as a fact
with negative polarity, so "this kind of device has no way to read messages" is known, not taught. The
device itself and what the person set on it are theirs, held in their scoped context; a location fix is
their perception, at a grain of about 110 m. **20/20** (2026-10-03).

The first run (13/20, kept) found two real defects, both fixed before the second:
- a device was said to be its kind with `is_a`, which the learning door refuses ("carries a determiner"),
  and the kind's label was five words ("a clause, not a name"). Now the device is `instance_of` its model
  (Lyric's relation for an individual and its kind), and the kind's platform and release live on the kind;
- a position named `25.762,-80.192` reached the stores as `25762_80192`: points and signs are not part of
  a name, so west and east collapsed into one. Now it is named as coordinates are written, `25.762N 80.192W`
  (stored `25762n_80192w`), always three places; the latitude and longitude stay signed numbers on it.
Its other failures were the checks spelling relations and names as written rather than as the door
stores them (`located at`, `location_<nonce>`); the checks now ask the door for its own forms.

| Property | Checked by |
|---|---|
| A new kind of device is a new environment domain, announced once with what the device answered | `situate_device`, the encounter caught as it is emitted |
| What exists there is Lyric's own knowledge, with polarity; no file counts for a place with no folder | `_react_investigate_environment`, run on the caught encounter; `unified.concept_relations` |
| Another person's device of the same kind is not new | the second `situate_device` |
| The device and what the person set are theirs, never shared | `unified.scoped_concept_relations` for the person; no shared concept of the device |
| A fix is the person's position at ~110 m; 30 m away is the same position; 900 m accuracy is not evidence | three fixes through `process_input(..., "location")` |
| The world inhabitant's `device` route takes a report and a location, and refuses anything else | `WorldInhabitant._device` |
| Everything written is removed | every text column in the store, searched for the run's nonce and the kind's domain |

**The trap in measuring it.** lyric_dev is shared and holds what was taught. Every name this run writes to
shared knowledge carries its nonce (a made-up platform, model, form and capabilities), so its cleanup can be
exact and nothing it leaves could pass for a real device. Count what it wrote before cleanup as well as
after: "nothing left" is also what someone else's reset produces. The life loop is not started, so the
encounter's reaction (deferred in a running Lyric) is run directly on the event caught when it was emitted.

**Run** (from the Lyric folder, once):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/systems/DEVICE-01/experiment.py
```

**Results.** `results/`: a JSON record and a summary per run.
