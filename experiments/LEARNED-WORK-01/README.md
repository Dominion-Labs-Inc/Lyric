# LEARNED-WORK-01 — teach something new, then watch how the substrate behaves on it

**Finding (2026-09-26, run `20260927T011034Z`):** it holds what it was taught and can say it back. It does not
yet use it: it does not reason across the facts, apply the taught rule to a situation, know what it can do, or
change after doing the work. Where it reports confidence ("verified"), that is about a file existing, not the work.

The substrate is built on confidence earned from what it has met: taught, seen or done. So it should say what it
knows and what it does not, what it can do and what it cannot, and be different after it has tried. This teaches
a lesson it did not hold (pipeline corrosion and cathodic protection: eight facts and one rule) and watches it.
It observes; only the lesson itself is scored. Every request, reply, step, tool run and belief reading is in
`results/<stamp>_transcript.md`.

| | | What it did |
|---|---|---|
| **A** | Teach 8 facts + "if the sacrificial anode is depleted then the pipeline is unprotected" | All held. Each taught fact went from no belief to 0.997 after one lesson from one source |
| **B** | What it knows | Taught facts answered: "Yes, a sacrificial anode is part of cathodic protection system", "made of a zinc". "Does moisture cause pipeline failure?" → one link ("Moisture causes corrosion."), no yes or no. "Does a coating cause corrosion?" → "Corrosion causes pipeline failure." (unrelated; taught: a coating PREVENTS corrosion). "What is an impressed current system?" → "I remember: A system is a matter", then looked it up, found nothing, "the kind of gap I want to close" — nothing follows |
| **C** | "Can you write a report about cathodic protection?" / "Can you inspect a pipeline?" | Recited a taught fact / "'pipeline' is used as a noun", and looked up "write a report" and "inspect a pipeline" on the web as unknown things. It has no notion of itself as the one being asked |
| **D1** | The research-and-report goal in plain words | Read as a statement: "Noted — a Research how cathodic protection protects pipelines", stored in the person's context as `research how cathodic_protection_protects_pipeline`. No tools, no file |
| **D2** | The same goal through the planning engine | Gather → analyse → write → check, all "success", check "verified". The report is the gather step's reply pasted in: three taught facts and "I hold nothing for protects pipelines." |
| **D3** | An inspection report (anode depleted, coating damaged, wet soil) | Plain words: declined ("no substrate handler"). Declared `read_file`: returned the text, no judgement. Told "The sacrificial anode is depleted." → "Noted" (stored as `sacrificial_anode has property depleted`, the person's context). "Is the pipeline unprotected?" → "I hold nothing for unprotected". The taught rule never fired |
| **E** | After the work | Competence in the domain 0.5 → 0.5; operating attempts 0 → 0 through the whole run. "Can you write a report…" answered the same. The second attempt ran the same four steps and wrote the same report |
| **F** | Over the run | 9 web searches, 18 page reads (15 ok): nothing learned about the topic. 100 tool runs, mostly the observation tools run around each write. 124 graph edges, almost all `write_file adds <field>` from the write's own output. 49 memories, 2 demonstrations, 0 rules, 0 open questions registered |

Open measurement question: the belief reader found no belief for the two taught "is a" facts (the other six read
0.997). Not yet checked whether that is how those beliefs are spelled or a missing belief.

## What it leaves behind

The lesson and its beliefs, the rule, and the fixture user's context (`learned-work-<nonce>`, printed as the run's
`user` metric) are kept. Scratch files are removed after their contents are copied into the transcript.

## Run

```
./venv_lyric/bin/python3 experiments/LEARNED-WORK-01/experiment.py
```
Boots the whole system, alone.
