"""THE HELD-OUT SENTENCES LYRIC CAN BE FAIRLY ASKED, drawn from what the store holds NOW.

`taught_words_test.json` lists 228 words and the 100 dev documents drawn against them, of which 77 have a gold
meaning: it was drawn when a store held that many recorded words, and every "77 held-out" number since was measured
on it. The store holds 6,643 forms now -- 3,662 words recorded whole and 241 closed-class words -- and 490 of the
911 dev documents with a gold meaning use nothing else (2026-11-02).

READING A SENTENCE IT WAS NEVER TAUGHT THE WORDS OF MEASURES NOTHING, which is why this is drawn at all: the words
are taught before the sentences on purpose (`WordRecord`), so a measure that asks for words the store does not hold
is asking about teaching that never happened.

    POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/draw_taught_set.py

It reads the store (the words it holds) and the PMB dev split, writes `experiments/GRAMMAR-01/taught_now_test.json`
in the shape `on_store.py` reads (`WORDS_TEST`), and names the words that most often put a sentence out of reach."""
import json, re, sys
from pathlib import Path

ROOT = Path("/Users/stefan/Dominion Labs/Lyric")
sys.path.insert(0, str(ROOT))
S = Path("/private/tmp/claude-501/-Users-stefan-Dominion-Labs/ab7a2550-74ab-46ff-b647-d3356ba73943/scratchpad")
from core.learning.teaching_sources import WordNetSource, file_words
from core.semantics import grammar as gm
from core.semantics import pmb_meanings as pm
from nltk.corpus import wordnet as wn

def vocabulary() -> set:
    """Every form of every word the store holds: the forms of each word recorded whole (`WordRecord.forms`) and the
    closed-class words whose class it was told (`word_class`). Read from the store the config authority names
    (`PostgresConfig.resolve`), never from a dump made by hand."""
    import psycopg2
    from core.database.postgres_config import PostgresConfig
    held_of = PostgresConfig.resolve()
    with psycopg2.connect(host=held_of.host, port=held_of.port, dbname=held_of.database,
                          user=held_of.user, password=held_of.password) as link:
        with link.cursor() as ask:
            ask.execute("""
                select distinct lower(f->>'form')
                  from memory_hot.memory_hot m, jsonb_array_elements(m.metadata->'word_record'->'forms') f
                 where m.tags @> '["word_record"]'::jsonb and f->>'form' is not null
                union
                select distinct lower(metadata->'word_record'->>'word') from memory_hot.memory_hot
                 where tags @> '["word_record"]'::jsonb and metadata->'word_record'->>'word' is not null
                union
                select distinct lower(metadata->>'word') from memory_hot.memory_hot
                 where tags @> '["word_class"]'::jsonb and metadata->>'word' is not null""")
            return {row[0] for row in ask.fetchall() if row[0]}


held = vocabulary()
print(f"{len(held):,} word forms the store holds")

sense_names = WordNetSource()._sense_names()
def sense_name(sense):
    try:
        return sense_names.get(wn.synset(sense)) or None
    except Exception:
        return None

# TOKENIZED AS LYRIC TOKENIZES, never by a pattern of my own: the store holds "n't" as a negator, so it splits a
# contraction and "isn't" is "is" + "n't", both held. Counted as one word, 100 sentences looked out of reach that
# are not.
file_vocab = file_words(ROOT / "test_data/syntax/UD_English-EWT/en_ewt-ud-train.conllu", gm.closed_uses())
WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")

def words_of(text):
    return [t.lower() for t in gm.tokens_of(text, file_vocab) if any(c.isalpha() for c in t)]
pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
drawn, missing_counts, with_gold = [], {}, 0
for doc_id in pm.split_ids(pmb / "split" / "en" / "dev" / "standard.sbn"):
    document = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
    said = pm.meaning_of(document, sense_name) if document is not None else None
    if said is None or said.meaning is None:
        continue
    with_gold += 1
    words = words_of(document.text)
    short = [w for w in words if w not in held and w.rstrip("'’s") not in held]
    if not short:
        drawn.append([doc_id, document.text])
    else:
        for w in short:
            missing_counts[w] = missing_counts.get(w, 0) + 1

print(f"{with_gold:,} dev sentences have a gold meaning")
print(f"{len(drawn):,} of them use ONLY words the store holds  ({len(drawn)/with_gold:.1%})")
used = sorted({w for _, text in drawn for w in words_of(text)})
out = ROOT / "experiments/GRAMMAR-01/taught_now_test.json"
out.write_text(json.dumps({"drawn": drawn, "words": used}, indent=1) + "\n")
print(f"written: {out}  ({len(used):,} distinct words)")
print("\nthe words that most often put a sentence out of reach:")
for w, k in sorted(missing_counts.items(), key=lambda kv: -kv[1])[:20]:
    print(f"  {k:>4}  {w}")
