# Teaching session — wordnet-validate
*2026-09-08T01:45:05.242546+00:00 · fan-out ON (beliefs + domain + lexicon) · model-free (no LLM)*

## Taught
- ISA facts (WordNet noun taxonomy): **1,200**  → `{'admitted': 1198, 'already': 0, 'refused': 2, 'total': 1200}`
- Parts of speech (WordNet lemmas): **1,200**  → `{'proposed': 0, 'already': 1200, 'refused': 0, 'total': 1200}`
- Elapsed: 27.2s

## Substrate: prior → after

| Store | Prior | After | Δ |
|---|--:|--:|--:|
| Beliefs | 2,815 | 2,815 | +0 |
| Concepts | 175,150 | 175,151 | +1 |
| Lexicon words | 72,901 | 72,936 | +35 |
| Domains | 21 | 21 | +0 |

**Domains added:** (none — existing `lexical` domain reinforced)

## Beliefs: prior → resulting (sample, domain `lexical`)

_Before this session:_

- `abrader isa tool` → 0.9926
- `abrachia isa abnormality` → 0.9926
- `abrading stone isa abrader` → 0.9926
- `abracadabra isa gibberish` → 0.9926
- `above isa section` → 0.9926
- `about-face isa reversion` → 0.9926
- `abortus isa fetus` → 0.9926
- `abortionist isa doctor` → 0.9926
- `about-face isa change` → 0.9926
- `abortion pill isa abortifacient` → 0.9926
- `abortion isa termination` → 0.9926
- `abortifacient isa drug` → 0.9926

_After this session:_

- `1198 taught facts` → 0.9926
- `abrader isa tool` → 0.9926
- `abrachia isa abnormality` → 0.9926
- `abrading stone isa abrader` → 0.9926
- `abracadabra isa gibberish` → 0.9926
- `above isa section` → 0.9926
- `about-face isa reversion` → 0.9926
- `abortus isa fetus` → 0.9926
- `abortionist isa doctor` → 0.9926
- `about-face isa change` → 0.9926
- `abortion pill isa abortifacient` → 0.9926
- `abortion isa termination` → 0.9926

---
*Report: docs/teaching_sessions/20260908T014505Z.md*
