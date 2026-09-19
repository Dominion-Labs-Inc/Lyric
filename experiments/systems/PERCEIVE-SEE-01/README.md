# PERCEIVE-SEE-01 — the whole loop through the faculty, from pixels only

Earlier perception studies taught the substrate the features a blob had been measured to have. That
measures learning and naming honestly, but the features were handed over rather than arriving by sight.
This study hands over nothing: every fact the substrate holds about a thing arrives through
`coordinator.see`, the one entry point for sight.

The faculty perceives an image and admits each object-like region as **its own individual** carrying its
own measured features, so what reaches the substrate is a thing that *is* round and *is* red, rather than
one flattened label hung on the image. A rule can bind to such a thing; a label it cannot.

## What is measured

- **Admission.** For each image, does a thing exist in what was admitted, holding the colour, shape and
  size the faculty measured off the pixels?
- **Naming.** A category induced from blobs admitted by sight alone, then held-out blobs named through
  the reasoner.
- **Abstention.** Blobs of a category never taught must be declined.

Three categories, four labelled images each, six held-out images each. Every name is
`coordinator.reason_about`; every induction is `coordinator.learning.induce_category`.

## Run

    PYTHONPATH="$PWD" TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/PERCEIVE-SEE-01/experiment.py

Writes `manifest.json`: per image what was drawn, what the faculty measured, which individual was
admitted and what it holds; then per category the induced rule, recall, abstention and false namings.
