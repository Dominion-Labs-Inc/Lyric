# Teaching session — wordnet-validate2
*2026-09-08T01:50:16.472450+00:00 · fan-out ON (beliefs + domain + lexicon) · model-free (no LLM)*

## Taught
- ISA facts (WordNet noun taxonomy): **3,000**  → `{'admitted': 2997, 'already': 0, 'refused': 3, 'total': 3000}`
- Parts of speech (WordNet lemmas): **3,000**  → `{'proposed': 0, 'already': 3000, 'refused': 0, 'total': 3000}`
- Elapsed: 64.7s

## Substrate: prior → after

| Store | Prior | After | Δ |
|---|--:|--:|--:|
| Beliefs (all) | 2,816 | 2,817 | +1 |
| Beliefs (`lexical`) | 184 | 185 | +1 |
| Concepts | 175,151 | 175,151 | +0 |
| Lexicon words | 72,936 | 73,010 | +74 |
| Domains | 21 | 21 | +0 |

**Domains added:** (none — existing `lexical` domain reinforced)

## Beliefs: prior → resulting (sample, domain `lexical`)

_Before this session:_

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

_After this session:_

- `2997 taught facts` → 0.9926
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

---
*Report: docs/teaching_sessions/20260908T015016Z.md*
