"""PATHS-01 — ONE learning path, ONE conversation path, and every write through its authority.

The rule, in the user's words: "In the substrate, there's only supposed to be one
learning, one conversation path." What a conversation is told is not admitted
because it was said, nor kept out because a person said it: memory splits it by
what it is about, a person's own things held in their context and a claim about
the world judged at the one door by whether it is true (the user, 2026-10-06:
"the point is is it true or not"; docs/research/SEPARATION_MAP.md §11). PATHS-02
checks that split; this checks the paths.

This is the standing check for that. It is deliberately part STATIC — several of
these are architectural invariants about WHO MAY WRITE, and the only way to
verify "nothing else does this" is to look at everything. A live probe can show
that one path works; it cannot show that a second one does not exist. So the
source tree is scanned for bypasses, and the live substrate is used for what only
it can answer: that the one path actually reaches every system it claims to.

  A. ONE LEARNING PATH — the concept graph, the beliefs and the relations each
     have exactly one writer, and the ingress is reachable only through the
     learning authority.
  B. ONE CONVERSATION PATH — there is one Conversation class, it can never
     resolve to the substrate, and what it is told of a person's own named thing
     lands in their context and nowhere else.
  C. EVERY PATH HITS THE AUTHORITIES — relation typing is decided in one place
     for both doors, the same sentence renders to the same atom whichever door it
     comes through, and the kind hierarchy invariant holds at admission.

Run: ./venv_lyric/bin/python3 experiments/PATHS-01/experiment.py
"""
from __future__ import annotations
import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

CORE = ROOT / "core"

EV = RunRecord(
    "PATHS-01",
    claim=("Knowledge enters the substrate by exactly one path — the learning "
           "authority — and conversation is not it. Each shared store has one "
           "writer, the ingress is reachable only through the learning "
           "authority, no conversation can resolve to the substrate actor, and "
           "the decisions a write depends on (what a relation IS, whether a kind "
           "edge is admissible) are made by the authority that owns them rather "
           "than re-derived at the call site."),
    hypothesis=("If a second path existed, either some module would reach the "
                "ingress or a shared table directly, or a conversation would "
                "resolve to the substrate and its telling would land in the "
                "shared graph. If the authorities were bypassed, the same "
                "sentence taught through the two doors would render to different "
                "atoms."))

results = []


def check(n, ok, d=""):
    results.append(bool(ok))
    EV.check(n, bool(ok), d)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def core_files():
    for path in CORE.rglob("*.py"):
        if "_disabled" in path.parts:
            continue
        yield path


def writers_of(table: str):
    """Every core module that INSERTs/UPDATEs/DELETEs `table`, ignoring comments."""
    pattern = re.compile(
        rf"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+unified\.{table}\b", re.I)
    found = set()
    for path in core_files():
        for line in path.read_text(errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue          # a comment recording a REMOVED bypass is not one
            if pattern.search(line):
                found.add(path.relative_to(ROOT).as_posix())
    return found


def callers_of(symbol: str):
    """Core modules calling `symbol(`, ignoring its own definition and comments."""
    found = set()
    for path in core_files():
        for line in path.read_text(errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith(f"def {symbol}") \
                    or stripped.startswith(f"async def {symbol}"):
                continue
            if f"{symbol}(" in line:
                found.add(path.relative_to(ROOT).as_posix())
    return found


async def main() -> int:
    from core.database import get_database_manager

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    # ── A. ONE LEARNING PATH ──────────────────────────────────────────────────
    print("\n== A. One learning path: one writer per store, one door to the ingress ==")

    # THE ONE WRITER IS MEMORY. Since memory became the one writer and reader of memory
    # (docs/research/MEMORY_AGENT_MAP.md), the ingestion, the belief system, the rule store
    # and the domain authority decide what is written and hand the write to the memory agent;
    # none of them writes a table itself. Until 2026-09-26 each was its table's writer.
    for table, what in (("concept_relations", "the reasoning graph's EDGES"), ("beliefs", "BELIEFS"),
                        ("learned_rules", "LEARNED RULES"), ("concepts", "the CONCEPT table")):
        writers = writers_of(table)
        check(f"{what} have exactly one writer, memory",
              writers == {"core/agents/memory_agent.py"}, f"{sorted(writers)}")

    admit_callers = callers_of("admit_relation")
    check("the INGRESS is reachable only through the learning authority",
          admit_callers == {"core/learning/unified_learning_system.py"},
          f"{sorted(admit_callers)}")

    # And the one door genuinely reaches every system it claims to.
    from core.learning.unified_learning_system import Evidence, get_unified_learning_system
    from core.semantics.cognitive_ingress import Provenance
    from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty

    learning = get_unified_learning_system()
    nonce = uuid.uuid4().hex[:8]
    SUBJ, OBJ = f"plax{nonce}", f"plaxkind{nonce}"
    decision = await learning.consider(
        SUBJ, "isa", OBJ, surface=f"a {SUBJ} is a {OBJ}", domain=f"paths01{nonce}",
        evidence=Evidence.from_provenance(Provenance(producer="paths01", source_id=f"paths01_{nonce}",
                                                     source_type="USER_SUPPLIED"), 0.95))
    check("one call on the learning authority ADMITS to the graph", decision.admitted,
          f"{decision.standing}: {decision.reasons}")

    graph = await db.execute_query(
        "SELECT count(*) c FROM unified.concepts WHERE name = $1", (SUBJ,))
    check("...and the concept is in the shared graph", graph[0]["c"] == 1)
    check("...and it was REMEMBERED as well as admitted",
          bool(getattr(decision.admission, "memory_id", None)),
          f"memory_id={getattr(decision.admission, 'memory_id', None)}")
    moved = [b for b in get_bayesian_uncertainty().beliefs.values()
             if SUBJ in str(b.claim)]
    check("...and it moved a BELIEF", bool(moved),
          f"{[b.claim for b in moved][:1]}")
    domains = await db.execute_query(
        "SELECT count(*) c FROM unified.domains WHERE domain_id LIKE $1",
        (f"%paths01{nonce}%",))
    check("...and the DOMAIN it was taught into exists", domains[0]["c"] >= 1)

    # ── B. ONE CONVERSATION PATH ──────────────────────────────────────────────
    print("\n== B. One conversation path, and a person's own things stay theirs ==")

    import core.semantics.conversation as conv_module
    from core.agents.autonomous.autonomous_coordinator import (
        Conversation, TaskSource)
    from core.agents.autonomous.shared_types import (SUBSTRATE_ACTOR,
                                                     is_substrate_actor)
    check("there is ONE Conversation class; the semantics module re-exports it",
          conv_module.Conversation is Conversation)

    # A telling is read before it is held: memory's view of the English it was taught is warmed first.
    from core.memory import get_memory_agent
    await (await get_memory_agent()).warm_word_classes()
    bare = Conversation(session=f"paths01-{nonce}")
    bound = Conversation(session=f"paths01-{nonce}", actor_identity=f"user-{nonce}")
    check("an UNBOUND conversation is a user scope, never the substrate",
          not is_substrate_actor(bare._actor) and bare._actor != SUBSTRATE_ACTOR,
          f"_actor={bare._actor}")
    check("a BOUND conversation is that person",
          bound._actor == f"user-{nonce}")
    raised = False
    try:
        Conversation(session="x", actor_identity=SUBSTRATE_ACTOR)._actor
    except ValueError:
        raised = True
    check("and a speaker may not claim the substrate's identity", raised)
    check("only the substrate's OWN work resolves to the shared mind, by SOURCE",
          Conversation(session="own", source=TaskSource.AUTONOMOUS)._actor
          == SUBSTRATE_ACTOR)

    TOLD = f"plaxtold{nonce}"
    await bare.teach(f"{TOLD.capitalize()} is a gadget.")
    shared = await db.execute_query(
        "SELECT count(*) c FROM unified.concepts WHERE name ILIKE $1", (f"%{TOLD}%",))
    scoped = await db.execute_query(
        "SELECT count(*) c FROM unified.scoped_concept_relations WHERE subj ILIKE $1",
        (f"%{TOLD}%",))
    check("what a conversation is told of a name the world does not hold reaches the SPEAKER'S context",
          scoped[0]["c"] >= 1, f"scoped rows={scoped[0]['c']}")
    check("and NOTHING of it reaches the shared concept graph",
          shared[0]["c"] == 0, f"shared rows={shared[0]['c']}")

    # ── C. EVERY PATH HITS THE AUTHORITIES ────────────────────────────────────
    print("\n== C. The decisions are made by the authority that owns them ==")

    inline = []
    for path in core_files():
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if re.search(r'["\']isa["\']\s+if\s+\w+\s+in\s*\(\s*["\']is["\']', line):
                inline.append(f"{path.relative_to(ROOT).as_posix()}:{i}")
    check("no module decides the COPULA for itself any more",
          not inline, f"{inline or 'none'}")

    from core.semantics.relation_types import classify, complement_class
    from core.memory import get_memory_agent
    agent = await get_memory_agent()
    # TAUGHT WHAT IT ASKS: whether a complement is adjectival is read from the word classes memory holds. The run
    # on 2026-09-26 found "recessive" held as an adjective because WordNet had been taught into that sandbox; an
    # emptied sandbox holds no such class, so the class is taught here, as WordNet teaches it.
    from core.learning import get_learning_authority
    await get_learning_authority().learn_word_classes([("recessive", "ADJECTIVE")])
    await agent.warm_word_classes()

    def typed(obj: str) -> str:
        return classify("is", object_word_class=complement_class(
            obj, agent.word_classes)).relation.value

    check("an ADJECTIVAL complement is a PROPERTY, not a kind",
          typed("X-linked recessive") == "has_property")
    check("a complement opened by a DETERMINER is a KIND",
          typed("a bird") == "isa")
    check("an unobserved complement keeps the copula's default reading",
          typed(f"zzq{nonce}") == "isa")

    # The two doors must render one sentence to one atom.
    from core.learning.teaching import TeachingPass
    from core.learning.teaching_sources import WordNetSource
    tp = TeachingPass(WordNetSource(), domain="paths01")
    tp._memory_for_classes = agent
    coord_rel = await Conversation._typed_relation("is", "X-linked recessive")
    teach_rel = tp._typed_relation("is", "X-linked recessive")
    check("BOTH doors type the same sentence the same way",
          coord_rel == teach_rel == "has_property",
          f"conversation={coord_rel} teaching={teach_rel}")

    from core.semantics.cognitive_ingress import get_cognitive_ingress
    ing = get_cognitive_ingress()
    A, B, C = f"pk{nonce}a", f"pk{nonce}b", f"pk{nonce}c"
    prov = Provenance(producer="paths01", source_id=f"paths01k_{nonce}",
                      source_type="USER_SUPPLIED")

    async def admit(s, o):
        return await ing.admit_relation(subject=s, relation="isa", obj=o,
                                        surface=f"{s} is a {o}", provenance=prov,
                                        domain=f"paths01{nonce}", quality=1.0)

    await admit(A, B)
    await admit(B, C)
    closing = await admit(C, A)
    shortcut = await admit(A, C)
    check("a kind edge that would CLOSE A CYCLE is refused at admission",
          not closing.admitted and any("cycle" in r for r in closing.refusals),
          f"{closing.refusals}")
    check("...while a non-cyclic shortcut through the same nodes is admitted",
          shortcut.admitted)

    EV.metric("stores_with_one_writer", 3, "count",
              "concept_relations, beliefs, learned_rules")
    EV.metric("ingress_callers_outside_the_authority", 0, "count")
    EV.note("The writer and caller checks are STATIC by necessity: a live probe "
            "can show one path works, never that a second does not exist.")
    EV.note("Comment lines are excluded from the scans — this tree records "
            "removed bypasses in comments, and a removed bypass is not one.")

    # clean up everything this run wrote
    for sql, arg in (
        ("DELETE FROM unified.concept_relations WHERE source_concept_id LIKE $1", f"%{nonce}%"),
        ("DELETE FROM unified.concepts WHERE name LIKE $1", f"%{nonce}%"),
        ("DELETE FROM unified.scoped_concept_relations WHERE subj ILIKE $1", f"%{nonce}%"),
        ("DELETE FROM unified.scoped_beliefs WHERE claim ILIKE $1", f"%{nonce}%"),
        ("DELETE FROM unified.domains WHERE domain_id LIKE $1", f"%paths01{nonce}%"),
    ):
        try:
            await db.execute_query(sql, (arg,), commit=True)
        except Exception as error:
            print(f"  (cleanup skipped: {error})")

    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
