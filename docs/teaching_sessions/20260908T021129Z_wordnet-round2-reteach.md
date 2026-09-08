# Teaching session — wordnet-round2-reteach
*2026-09-08T02:11:29.111393+00:00 · fan-out ON (beliefs + domain + lexicon) · model-free (no LLM)*

## Taught
- ISA facts (WordNet noun taxonomy): **2,000**  → `{'admitted': 1997, 'already': 0, 'refused': 3, 'total': 2000}`
- Parts of speech (WordNet lemmas): **2,000**  → `{'proposed': 0, 'already': 2000, 'refused': 0, 'total': 2000}`
- Elapsed: 41.7s

## Substrate: prior → after

| Store | Prior | After | Δ |
|---|--:|--:|--:|
| Beliefs (all) | 4,714 | 4,714 | +0 |
| Beliefs (`lexical`) | 2,082 | 2,082 | +0 |
| Concepts | 175,166 | 175,166 | +0 |
| Lexicon words | 73,010 | 73,010 | +0 |
| Domains | 21 | 21 | +0 |

**Domains added:** (none — existing `lexical` domain reinforced)

## Beliefs: prior → resulting (sample, domain `lexical`)

_Before this session:_

- `ascolichen isa lichen` → 0.9926
- `asclepiad isa herb` → 0.9926
- `ascites isa pathology` → 0.9926
- `ascidian isa tunicate` → 0.9926
- `ascidiaceae isa class` → 0.9926
- `asceticism isa self-denial` → 0.9926
- `asceticism isa doctrine` → 0.9926
- `ascent isa slope` → 0.9926
- `ascender isa mover` → 0.9926
- `ascender isa line` → 0.9926
- `ascender isa letter` → 0.9926
- `ascendant isa dominance` → 0.9926

_After this session:_

- `ascolichen isa lichen` → 0.9995
- `asclepiad isa herb` → 0.9995
- `ascites isa pathology` → 0.9995
- `ascidian isa tunicate` → 0.9995
- `ascidiaceae isa class` → 0.9995
- `asceticism isa self-denial` → 0.9995
- `asceticism isa doctrine` → 0.9995
- `ascent isa slope` → 0.9995
- `ascender isa mover` → 0.9995
- `ascender isa line` → 0.9995
- `ascender isa letter` → 0.9995
- `ascendant isa dominance` → 0.9995

---
*Report: docs/teaching_sessions/20260908T021129Z.md*
