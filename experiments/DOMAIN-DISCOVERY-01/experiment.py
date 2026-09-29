#!/usr/bin/env python3
"""DOMAIN-DISCOVERY-01 — does the substrate create domains, or only file names?

THE COMPLAINT THAT PROMPTED THIS. Four days of work kept landing back on the
same hand-written domains (kite17, warehouse, fs_g2_real1) after two flushes.
The reason is not that discovery was slow or unlucky. BOTH HALVES OF IT WERE
UNREACHABLE BY CONSTRUCTION, and every row in `unified.domains` is a string some
caller typed into `domain=`.

  OPERATIONAL HALF.  `provisional_domains()` returned rule-domains MINUS
  registered domains -- "not yet registered". But the learning fan-out calls
  `ensure_domain(domain)` on the FIRST FACT TAUGHT, long before any operator is
  induced there. So the candidate set was empty on every wake, forever, and
  `crystallize()` -- the function that decides new-vs-merge and records
  cross-domain analogies -- had never run on a real domain in the substrate's
  life. Measured: provisional_domains() == [], and 6 of 8 rule-holding domains
  were registered BEFORE their first rule existed.

  DECLARATIVE HALF.  The idle sweep asked for `from_field="conversation"`, a
  channel holding 0 concepts, while 82,676 taught concepts sat in `general`.
  The splitter written for exactly that blob, `crystallize_taxonomic_domains`,
  had ZERO CALLERS anywhere in the tree.

  AND THE SPLITTER PLACED BY ALPHABET.  Its home-subject choice was
  `max(Counter(roots), key=lambda r: (tally[r], r))`, described as "the subject
  the most of this concept's hypernym chains arrive at". THE COUNTS WERE ALL 1
  -- the walk shares one `seen` set, so each root is recorded once however many
  chains reach it -- which collapses the choice to `max` over the NAME. 65,056
  of 82,676 concepts filed under `x_linked_recessive` because `x` sorts last.

  A  A REGISTERED-BUT-UNDECIDED DOMAIN IS A CANDIDATE   registration is not the decision
  B  A DOMAIN NEVER MERGES INTO ITSELF                  exposed the moment A made it reachable
  C  A DECISION IS DURABLE AND NOT RE-TAKEN             or every sweep re-decides forever
  D  THE SWEEP READS CHANNELS THAT HOLD CONCEPTS        not one hardcoded name
  E  THE TAXONOMIC SPLITTER HAS A CALLER                it had none
  F  A CONCEPT LANDS UNDER ITS NEAREST SUBJECT          not the alphabetically last root
  G  A FUNNEL ROOT IS NOT A SUBJECT                     one inverted edge must not take the bucket
  H  A REAL MULTI-KIND ROOT IS STILL A SUBJECT          the negative control for G

H is the control: a guard that rejects funnels by rejecting everything would
"fix" the mega-bucket by making discovery produce nothing at all.

Run: ./venv_torin/bin/python3 experiments/DOMAIN-DISCOVERY-01/experiment.py
"""
import asyncio
import contextlib
import io
import logging
import os
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))
logging.disable(logging.CRITICAL)

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "DOMAIN-DISCOVERY-01",
    claim=("The substrate DECIDES which domains exist, from what it has learned "
           "and been taught, rather than filing whatever string a caller passed."),
    hypothesis=("If `provisional` means not-yet-DECIDED rather than "
                "not-yet-REGISTERED, if the declarative sweep reads the channels "
                "that actually hold concepts, and if a concept is placed under "
                "its nearest subject rather than its alphabetically last root, "
                "then discovery produces a subject map instead of nothing and "
                "instead of one mega-bucket."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)


async def main() -> int:
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coord = system.autonomous_coordinator
    from core.database import get_database_manager
    from core.semantics.cognitive_ingress import Provenance
    from core.integration.universal_domain_master import get_universal_domain_master

    db = get_database_manager()
    udm = get_universal_domain_master()
    await EV.verify_database()
    tag = uuid.uuid4().hex[:6]
    CH = f"ddchan{tag}"          # a throwaway CHANNEL, cleaned up at the end
    prov = Provenance(producer="domain_discovery_01", source_id=f"dd_{tag}",
                      source_type="USER_SUPPLIED")

    async def teach(subject, relation, obj):
        await coord.learning.learn_fact(
            subject, relation, obj, surface=f"a {subject} is a {obj}",
            domain=CH, provenance=prov, quality=0.95)

    # ── A. registration is not the decision ──────────────────────────────
    prov_domains = await udm.provisional_domains()
    registry = await udm._registry()
    registered_candidates = [d for d in prov_domains if d in registry.domains]
    check("a registered-but-undecided domain is still a candidate",
          bool(prov_domains) and bool(registered_candidates),
          f"provisional={prov_domains} of which already registered="
          f"{registered_candidates}")
    already = [d for d in prov_domains if d in registry.domains
               and udm.is_crystallized(registry.domains[d])]
    check("a candidate set is not merely 'every domain with a rule'",
          not already, f"decided domains still offered as candidates={already}")

    # ── B/C. decide, and do not re-decide ────────────────────────────────
    first = await udm.discover_domains()
    self_merges = [o for o in first["outcomes"]
                   if o.get("status") == "merged" and o.get("into") == o.get("domain_id")]
    # RE-RUNNABLE BY CONSTRUCTION. A decision is permanent, so a second run of
    # this experiment finds the same domains already decided -- which is the
    # property under test, not a reason the test cannot run. Both checks below
    # read the STORE rather than requiring a fresh decision.
    decided_rows = await db.execute_query(
        "SELECT domain_id, metadata->'boundaries'->>'crystallized' c, "
        "       metadata->'boundaries'->>'merged_into' m "
        "FROM unified.domains "
        "WHERE metadata->'boundaries'->>'crystallized' IS NOT NULL",
        (), fetch_all=True) or []
    self_merged = [r["domain_id"] for r in decided_rows if r["m"] == r["domain_id"]]
    check("no domain in the store is merged into itself",
          not self_merges and not self_merged,
          f"this run={[o['domain_id'] for o in self_merges]} stored={self_merged}")

    second = await udm.discover_domains()
    re_decided = [o["domain_id"] for o in second["outcomes"]
                  if o.get("status") in ("crystallized", "merged")
                  and o.get("domain_id") in {r["domain_id"] for r in decided_rows}]
    check("a decided domain is not decided again", not re_decided,
          f"already decided={len(decided_rows)} re-decided={re_decided}")

    # Durability: rebuild the Domain from its STORED ROW through the loader's own
    # deserializer -- the exact path a restart takes. (A full
    # `DomainRegistry.initialize()` would also reload every concept in the store,
    # which is the loader's cost, not this property.)
    if decided_rows:
        target = decided_rows[0]["domain_id"]
        stored = await db.execute_query(
            "SELECT domain_id, domain_name, description, metadata "
            "FROM unified.domains WHERE domain_id=$1", (target,))
        rebuilt = registry._domain_from_row(stored[0]) if stored else None
        check("the decision survives the round trip through the store",
              rebuilt is not None and udm.is_crystallized(rebuilt),
              f"{target} -> boundaries="
              f"{getattr(rebuilt, 'boundaries', None)}")
    else:
        check("the decision survives the round trip through the store", False,
              "no domain in the store carries a decision")

    # ── D. the sweep reads channels that hold concepts ───────────────────
    counts = {ch: await udm._channel_concept_count(ch)
              for ch in udm.UNDIFFERENTIATED_CHANNELS}
    check("the declarative sweep names more than one channel",
          len(udm.UNDIFFERENTIATED_CHANNELS) > 1 and any(v > 0 for v in counts.values()),
          f"{counts}")

    # ── F. nearest subject, not alphabetically last root ─────────────────
    # x -> m1 -> {near_root(depth 2), m2 -> zzz_root(depth 3)}
    # `zzz_root` sorts after `near_root`, so the old max-by-name choice took the
    # FARTHER one. Two extra kinds keep both roots above the funnel guard.
    near, far = f"aanear{tag}", f"zzzfar{tag}"
    await teach(f"x{tag}", "isa", f"m1{tag}")
    await teach(f"m1{tag}", "isa", near)
    await teach(f"m1{tag}", "isa", f"m2{tag}")
    await teach(f"m2{tag}", "isa", far)
    for i in range(2):                       # give both roots >1 direct child
        await teach(f"nk{i}{tag}", "isa", near)
        await teach(f"fk{i}{tag}", "isa", far)

    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        split = await udm.crystallize_taxonomic_domains(
            from_field=CH, min_size=2, apply=False)
    homes = {o["domain"]: o["concepts"] for o in split["outcomes"]}
    check("a concept lands under its NEAREST subject, not the last by name",
          near in homes and far not in {k for k, v in homes.items()
                                        if v > homes.get(near, 0)},
          f"subjects={homes} (near={near}, far={far})")

    # ── G/H. a funnel is not a subject; a real root still is ─────────────
    funnel, hub = f"funnel{tag}", f"hub{tag}"
    await teach(hub, "isa", funnel)          # funnel gets exactly ONE direct child
    for i in range(4):
        await teach(f"under{i}{tag}", "isa", hub)
    good = f"good{tag}"
    for i in range(3):                       # good gets THREE direct children
        await teach(f"kind{i}{tag}", "isa", good)
        await teach(f"leaf{i}{tag}", "isa", f"kind{i}{tag}")

    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        split2 = await udm.crystallize_taxonomic_domains(
            from_field=CH, min_size=3, apply=False)
    subjects2 = {o["domain"] for o in split2["outcomes"]}
    funnels2 = {f["root"] for f in split2["funnels"]}
    check("a root reached through ONE child is rejected as a funnel",
          funnel in funnels2 and funnel not in subjects2,
          f"funnels={sorted(funnels2)}")
    check("a root with several kinds under it is still a subject",
          good in subjects2, f"subjects={sorted(subjects2)}")

    # ── E. the taxonomic splitter is reachable FROM THE SWEEP ────────────
    # Scoped to this run's own channel, for two reasons. The real channels hold
    # 82,676 concepts and the walk over them takes minutes; and the sweep only
    # re-splits a channel that has GROWN by a subject-floor since its last
    # split, so pointing this at `general` would pass once and then be skipped
    # on every later run. Scoping the INPUT keeps the code path real -- this is
    # the production `discover_taught_domains`, with its own splitter and its
    # own watermark, over a channel small enough to be deterministic.
    for i in range(udm.TAXONOMIC_DOMAIN_MIN_SIZE):
        await teach(f"fill{i}{tag}", "isa", f"kind{i % 3}{tag}")
    reached = {"n": 0, "fields": []}
    original_split = udm.crystallize_taxonomic_domains
    original_channels = udm.UNDIFFERENTIATED_CHANNELS

    async def watched(**kw):
        reached["n"] += 1
        reached["fields"].append(kw.get("from_field"))
        return await original_split(**kw)

    udm.crystallize_taxonomic_domains = watched
    udm.UNDIFFERENTIATED_CHANNELS = (CH,)
    try:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            swept = await udm.discover_taught_domains()
    finally:
        udm.crystallize_taxonomic_domains = original_split
        udm.UNDIFFERENTIATED_CHANNELS = original_channels
    check("the taxonomic splitter has a caller", reached["n"] > 0,
          f"reached {reached['n']} time(s) from discover_taught_domains() "
          f"for {reached['fields']}")
    check("the sweep surveys without applying while the taxonomy is unsound",
          (swept["channels"][CH].get("taxonomic") or {}).get("applied") is False
          and swept.get("surveyed_subjects", 0) > 0,
          f"DECLARATIVE_APPLY={udm.DECLARATIVE_APPLY} "
          f"surveyed={swept.get('surveyed_subjects')}")

    # ── clean up everything this run taught ──────────────────────────────
    # MEMORIES AND LEDGER ROWS TOO. Teaching through the learning authority
    # writes a memory per fact, and this cleanup used to remove only concepts,
    # beliefs and the domain -- so every run left its fixture sentences in
    # memory_hot, where recall then served "a m20… is a zzzfar…" as a premise
    # to an unrelated question and the solver formalized it into a proof.
    # Beliefs grounded in those memories go first: with the memory gone they
    # would be stances on nothing.
    await db.execute_query(
        "DELETE FROM unified.beliefs WHERE memory_id IN (SELECT memory_id FROM "
        "memory_hot.memory_hot WHERE content ILIKE $1)", (f"%{tag}%",), commit=True)
    await db.execute_query(
        "DELETE FROM memory_hot.memory_hot WHERE content ILIKE $1",
        (f"%{tag}%",), commit=True)
    for sql in ("DELETE FROM unified.knowledge_updates WHERE domain=$1",
                "DELETE FROM unified.beliefs WHERE domain=$1",
                "DELETE FROM unified.concepts WHERE domain=$1",
                "DELETE FROM unified.domains WHERE domain_id=$1"):
        await db.execute_query(sql, (CH,), commit=True)
    await db.execute_query(
        "DELETE FROM unified.concept_relations WHERE source_concept_id LIKE $1",
        (f"%{tag}%",), commit=True)

    passed, total = sum(results), len(results)
    EV.metric("provisional_domains", len(prov_domains), "domains",
              "was 0 on every wake before the predicate was corrected")
    EV.metric("channel_concepts", counts, "concepts",
              "the sweep used to read only `conversation`")
    EV.note("B exists because making dead code live exposed a defect the dead "
            "code hid: a candidate is registered, so it appeared in its own "
            "comparison set and merged into itself.")
    EV.note("F is the defect that produced the mega-bucket; the funnel guard in "
            "G only limits the damage when the taxonomy itself is wrong.")
    EV.write()
    print(f"\n==== DOMAIN-DISCOVERY-01: {passed}/{total} checks passed ====\n")
    sys.stdout.flush()
    os._exit(0 if passed == total else 1)


asyncio.run(main())
