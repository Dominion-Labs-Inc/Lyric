# PERCEIVE-AMBIG-02 — closing an undetermined induction by asking for a case

When the labelled examples admit more than one hypothesis, induction keeps them all and reports the case
that would eliminate one. This measures whether supplying that case closes the ambiguity, and whether it
beats supplying more data.

## Protocol

Eight categories, two repeats, in the accidental arm only (both positives share a size the category does
not require). For each undetermined induction, two arms from the same four labelled images:

- **targeted** — each round supplies the case `deciding_request` names, then re-induces.
- **random** — each round supplies a randomly drawn stimulus instead.

Cap: four rounds. Both arms label a supplied example by the same rule (member iff it has the category's
shape and colour). Every stimulus is drawn and then perceived, and is used only if perception reports the
features the round requires; a case that cannot be built is recorded `unbuildable` and excluded. A size
band is a property of perceived area, so nothing is assumed from a radius.

## Result (17 September 2026)

| | closed | mean rounds |
|---|---|---|
| the case the substrate asked for | 16 / 16 | 2.62 |
| randomly drawn examples | 1 / 16 | 2.0 |

16 of 16 inductions were undetermined at the start; the stimulus space was 448 perceived images and 232
were taught. Every induction is `coordinator.learning.induce_category`.

## Run

    PYTHONPATH="$PWD" TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/PERCEIVE-AMBIG-02/experiment.py

Writes `manifest.json`: per-case round logs (what was supplied, what it was labelled, which hypotheses
stood afterwards, and the request at each round).
