# LOOKUP-SINGLEFLIGHT-01 — one lookup for many callers

**What it tests.** When many callers ask about the same unknown phrase at once, `Conversation.look_up`
researches it once. The web research call (`_research_phrase`) is replaced by a slow stand-in that counts
how often it is called.
- N callers at once lead to exactly one research call, and all get the same result.
- Different phrases are not merged.
- After the lookup finishes, a later call researches again; there is no cache across time.
- Differences in case and whitespace still count as one phrase.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/LOOKUP-SINGLEFLIGHT-01/experiment.py
```

The docstring's `scratchpad/bench_lookup_singleflight.py` is an old path.

**Results.** Printed to the terminal only; no run is saved.
