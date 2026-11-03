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


def sense_kinds() -> dict:
    """Each word recorded whole -> the kinds each of its senses is directly a kind of (`WordSense.kind_of`), as the
    store holds them. The question set is drawn from these and from nothing else."""
    import psycopg2
    from core.database.postgres_config import PostgresConfig
    held_of = PostgresConfig.resolve()
    out: dict = {}
    with psycopg2.connect(host=held_of.host, port=held_of.port, dbname=held_of.database,
                          user=held_of.user, password=held_of.password) as link:
        with link.cursor() as ask:
            ask.execute("""
                select lower(m.metadata->'word_record'->>'word'), s->>'id', s->>'class', s->'kind_of',
                       coalesce((s->>'used')::int, 0)
                  from memory_hot.memory_hot m, jsonb_array_elements(m.metadata->'word_record'->'senses') s
                 where m.tags @> '["word_record"]'::jsonb
                   and m.metadata->'word_record'->>'word' is not null and s->>'id' is not null""")
            for word, sense, cls, kinds, used in ask.fetchall():
                if cls != "NOUN" or not kinds:
                    continue
                out.setdefault(word, []).append((sense, [k[1] for k in kinds if len(k) > 1], used))
    return out


def draw_questions(how_many: int) -> None:
    """QUESTIONS LYRIC CAN BE FAIRLY ASKED, each with the answer the store itself gives.

    ASKING ABOUT A RELATION THE STORE DOES NOT HOLD MEASURES NOTHING, and scoring the honest reply as a failure is
    worse than measuring nothing. Six questions chosen by hand on 2026-11-02 asked whether an issue is a problem, a
    review a report and people animals; WordNet holds none of the three, Lyric answered with the kinds it does hold
    (`content`, `appraisal`, `group`, each the real direct hypernym), and that was written up as composition being
    broken. It was not: every one of those sentences read whole at sureness 1.000.

    So both sides of every question are drawn from the store: the word is one it holds a record of, and the kind is
    one it holds a record of too. A YES is a kind the record states directly. A NO is a held kind that is nowhere in
    the word's hypernyms, so a `true` there is a real error and not a gap in what was taught."""
    kinds = sense_kinds()
    words = set(kinds)
    print(f"{len(words):,} words recorded whole with a noun sense that states its kinds")
    # ONE QUESTION PER WORD. Drawn per SENSE, `person` was asked three times over (person.n.01 an organism, .n.02 a
    # body, .n.03 a class) and three identical negatives came with it: a 120-question set holding 40 distinct
    # questions, which flatters or damns whatever those 40 happen to be.
    yes, no = [], []
    for word in sorted(words, key=lambda w: -max(u for _, _, u in kinds[w])):
        if len(yes) >= how_many:
            break
        # FROM THE SENSE THE WORD IS MOST USED IN, AND NO OTHER. Drawn from any sense, this asked "Is a year a
        # gathering?" (from `class.n.06`, a graduating class), "Is a hand a laborer?" (a hired hand) and "Is a head
        # an animal?" (a head of cattle). Nothing in those questions says which sense is meant, so they cannot be
        # answered as asked -- and Lyric answered about each word's usual sense, correctly, and was scored wrong for
        # it: 4 of 10 counted as failures that were nothing of the kind (2026-11-02).
        # ONLY THE DOMINANT SENSE, AND NO FALLING THROUGH TO ANOTHER. Trying each sense in turn until one yielded a
        # usable kind was the whole defect: `year`'s most-used sense is a period, whose kinds are all several words
        # ("time period", "fundamental quantity") and so unusable here, and the loop fell through to `class.n.06`,
        # a graduating class, and asked "Is a year a gathering?". A word whose dominant sense offers no single-word
        # held kind is simply not asked about.
        sense, directly, _used = max(kinds[word], key=lambda s: s[2])
        got = next((k for k in directly
                    # BOTH SIDES HELD, or the question is unanswerable by construction.
                    if k in words and k != word and " " not in k), None)
        if got:
            yes.append({"ask": f"Is {_article(word)} {word} {_article(got)} {got}?",
                        "expect": True, "word": word, "kind": got, "from": sense, "sense_used": _used})
    # A NO is checked against WordNet's whole closure, not against the one sense drawn, so a word that IS the kind
    # through any sense is never asked as a negative.
    def above(word: str) -> set:
        out = set()
        for s in wn.synsets(word, "n"):
            for path in s.hypernym_paths():
                out.update(h.lemma_names()[0].lower().replace("_", " ") for h in path)
        return out
    # The negative kind is taken from a different place in the pool for each word, so the set does not ask the same
    # pairing over and over; and no pairing is asked twice.
    pool = sorted({q["kind"] for q in yes})
    asked = set()
    for n, q in enumerate(yes):
        over = above(q["word"])
        for step in range(len(pool)):
            kind = pool[(n + step) % len(pool)]
            if kind in over or kind == q["word"] or " " in kind or (q["word"], kind) in asked:
                continue
            asked.add((q["word"], kind))
            no.append({"ask": f"Is {_article(q['word'])} {q['word']} {_article(kind)} {kind}?",
                       "expect": False, "word": q["word"], "kind": kind, "from": "not above it in WordNet"})
            break
        if len(no) >= how_many:
            break
    out = ROOT / "experiments/GRAMMAR-01/taught_questions.json"
    out.write_text(json.dumps({"yes": yes, "no": no}, indent=1) + "\n")
    print(f"{len(yes)} questions whose answer the store holds as YES, {len(no)} as NO")
    print(f"written: {out}")
    for q in yes[:6]:
        print(f"  YES  {q['ask']:<44} from {q['from']}")
    for q in no[:6]:
        print(f"  NO   {q['ask']:<44} ({q['kind']} is nowhere above {q['word']})")


def ask_questions(batch: int = 10) -> None:
    """Ask the running Lyric the drawn questions THROUGH ITS OWN DOOR, and score each against what the store holds.

    IN BATCHES, AND EACH BATCH KEPT AS IT ARRIVES. All 80 asked in one request took longer than the twenty minutes
    allowed it and the reply was discarded whole: 80 questions answered, nothing kept, nothing learned (2026-11-02).
    A batch that overruns now costs that batch and no more, and a run can be continued.

    The score is reported for the YES half and the NO half apart, because one number over both hides the only thing
    worth knowing: whether a wrong answer is a kind it failed to find or a kind it invented."""
    import urllib.request
    questions = json.loads((ROOT / "experiments/GRAMMAR-01/taught_questions.json").read_text())
    drawn = questions["yes"] + questions["no"]
    # The newest instance door whose store is the one these questions were drawn from.
    from core.database.postgres_config import PostgresConfig
    want = PostgresConfig.resolve().database
    doors = sorted((json.loads(p.read_text()) for p in (ROOT / "runtime/instances").glob("*.json")),
                   key=lambda d: d.get("started_at") or "", reverse=True)
    door = next((d for d in doors if d.get("database") == want), None)
    if door is None:
        raise SystemExit(f"no running Lyric on {want}: start one, or ask against the store it is on")
    print(f"asking {door['instance']} on {want} at {door['door']}")
    kept = ROOT / "experiments/GRAMMAR-01/results/taught_questions_answered.json"
    kept.parent.mkdir(parents=True, exist_ok=True)
    answered = json.loads(kept.read_text()) if kept.exists() else {}
    for at in range(0, len(drawn), batch):
        chunk = [q for q in drawn[at:at + batch] if q["ask"] not in answered]
        if not chunk:
            continue
        body = json.dumps({"questions": [q["ask"] for q in chunk]}).encode()
        call = urllib.request.Request(door["door"] + "/check", data=body, method="POST",
                                      headers={"Authorization": f"Bearer {door['key']}",
                                               "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(call, timeout=600) as reply:
                for got in json.loads(reply.read())["answers"]:
                    answered[got["asked"]] = {"reply": got["reply"], "verdict": got["verdict"]}
        except Exception as trouble:
            print(f"  batch at {at}: {type(trouble).__name__} {trouble} -- kept what came before it")
            break
        kept.write_text(json.dumps(answered, indent=1) + "\n")
        print(f"  {len(answered)}/{len(drawn)} answered", flush=True)
    right = {True: 0, False: 0}
    wrong = {True: 0, False: 0}
    silent = {True: 0, False: 0}
    misses = []
    for q in drawn:
        got = answered.get(q["ask"])
        if got is None:
            continue
        if got["verdict"] is None:
            silent[q["expect"]] += 1
            misses.append(("no verdict", q, got))
        elif bool(got["verdict"]) == q["expect"]:
            right[q["expect"]] += 1
        else:
            wrong[q["expect"]] += 1
            misses.append(("WRONG", q, got))
    for expect, name in ((True, "YES (a kind the store states)"), (False, "NO (a kind nowhere above it)")):
        n = right[expect] + wrong[expect] + silent[expect]
        if n:
            print(f"\n{name}: {n} asked -- {right[expect]} right, {wrong[expect]} wrong, "
                  f"{silent[expect]} gave no verdict  ({right[expect]/n:.1%} right)")
    print(f"\nkept: {kept}")
    for why, q, got in misses[:20]:
        print(f"  {why:<10} {q['ask']:<40} expected {q['expect']}, verdict {got['verdict']}: {got['reply'][:70]!r}")


held = vocabulary()
print(f"{len(held):,} word forms the store holds")

if "--ask" in sys.argv:
    ask_questions()
    sys.exit(0)

if "--questions" in sys.argv:
    from core.learning.teaching_sources import _article
    draw_questions(int(sys.argv[sys.argv.index("--questions") + 1])
                   if len(sys.argv) > sys.argv.index("--questions") + 1 else 100)
    sys.exit(0)

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
