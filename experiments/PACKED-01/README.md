# PACKED-01: each word's senses kept together, the listener choosing over the structure

**Claim.** The reader that keeps each word's senses together, with the listener choosing among them over the
structure, hands the listener exactly the readings the reader that builds every reading did, chooses as it chose, and
finishes where that one does not.

**Why.** The reader built every reading whole: each word's every sense crossed with every other's, each slot's every
bracketing with every other's, in every stretch of an utterance read in parts. It then kept the few it hands the
listener and threw the rest away: on a copy of main "The function sorted returns a new list." built 18,101 readings of
which 168 could reach the listener, and the primes sentence of UNDERSTANDS-PROSE-01 never finished (lab notebook
2026-10-19 (23), (24)). Teaching more makes it worse: every word taught adds senses. Everything the reader and the
listener rank by adds up over the structure, so the best reading can be found from the best of its parts.

**What changed** (`core/semantics/derived_reader.py`):
- A word held for several things in a slot is one packed word (`Sense`): its senses with what each supposes there
  (link held or proposed, written against the slot's own, never beside them, numbers of a size never there), never
  crossed. Products run over structures only. One stand-in for a run of words, so readings saying the same are alike.
- The cuts that kept one reading of each meaning work per choice of senses, as they did one by one: a phrase's
  (`_claimed`: fewer constructions, else first), an adjunct's (`_least_claimed`: supposing least, else first),
  `_read_pieces` (`_one_thing_twice`: where two words name one thing, the wording is their own).
- `listening` asks memory about the facts each pairing of senses makes; `meant` finds the best senses over each
  structure by eliminating words one by one over the facts that join them (`_choices`), with what it counts in levels
  (known, defined, fit) as a small state, and keeps the best few of each state so ties are found and asked about. Each
  meaning is weighed by the reading of it the reader puts first, as before (`_best_packed`).
- `read` (every meaning) and the listener's counts on taught sentences make each choice (`unpacked`). Learning reads
  strictly and repairs read with their own charts: never packed.

**What it measures** (read only, from the store's own views, warmed from memory). Every lesson sentence
(`ListeningSource`) and every sentence and question of UNDERSTANDS-PROSE-01 (read in parts, as a conversation reads
them), each read once, each utterance's choice made both ways in one load:
- packed: the readings as read and the listener over them (`listening`, `meant`), timed (the whole read, parts and
  all);
- one by one: the utterance read again as before, every sense of every word apart (charts that do not pack), and the
  listener weighing each reading, timed (the utterance's own read only); and whether those readings are exactly what
  the packed ones stand for (`unpacked`): each meaning, and the reading of it kept, supposed, score, uses,
  constructions and links alike. One by one is what does not finish: past the run's own limit (`--limit`, seconds;
  the probe's, never the reader's) a sentence is compared on nothing, and its packed read is still timed.

Then: readings and choices the same, lessons read as taught each way, seconds, every changed choice
(`_changed.json`), and that nothing was written. **No bar:** it measures.

**Run** (from the Lyric folder; starts no substrate; about 5 minutes to load on main):

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/PACKED-01/experiment.py
```

`--prose-only` reads the prose alone; `--limit N` the run's own limit on one sentence one by one (600 s by default);
`--resume experiments/PACKED-01/work/<stamp>_sentences.jsonl` goes on after a stop.

**Results:** `results/<UTC timestamp>.json` and `.md`, `_changed.json`, `results/run.log`; each sentence as read, in
`work/<stamp>_sentences.jsonl` (the run's working file, kept out of git).

**Runs:**

| Run | Store | Prose: same readings, same choice | Lessons: same readings, same choice | Lessons read as taught (packed, one by one) | Nothing written |
|---|---|---|---|---|---|
| `20261020T114435Z` | sandbox | 70, 70 of 70 | 3,054, 3,054 of 3,054 | 2,913, 2,913 | yes |
| `20261020T115357Z` | main, prose only (one by one limited to 60 s) | 70, 70 of 70; all 70 finish packed | | | yes |
| `work/20261020T120432Z_sentences.jsonl` (stopped at 2,006 lessons, no record) | main (one by one limited to 120 s) | 70, 70 of 70 | 1,985, 1,985 of the 1,985 one by one finished; 21 one by one did not, each about 1 s packed | 2,000 of 2,006 packed | counters unchanged |

On main the prose reads packed in 201 s, the structure reader's first training (81 s) and the primes sentence (65 s)
in it; the primes sentence never finished before (2026-10-19). "If the valve is closed, the tank is full." is 0.3 s
packed against 27 s one by one (2,352 readings handed the listener); the 35 choices yesterday's run on main recorded
are each the same.
