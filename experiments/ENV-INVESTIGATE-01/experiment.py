"""ENV-INVESTIGATE-01 — environment investigation is ROBUST: recursive scan, each file's structure
held, what it HOLDS taken in by every sense that can (a picture seen, a recording heard, a text read by the
substrate's own reading), binaries and over-long texts recorded by metadata only.

Uses the REAL `_scan_environment` / `_ingest_environment_entry` and the real senses' judgement of what
each file can give (`PerceptionFaculty.senses_of`), bound to a stand-in that records the structural facts
learned and what is handed to the one act of perceiving (`take_in`), so no DB writes. What the one act
does with a text it reads is READ-01's to show.

Run: ./venv_lyric/bin/python3 scratchpad/bench_envscan.py
"""
from __future__ import annotations
import asyncio, os, sys, tempfile, shutil
from types import SimpleNamespace
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "ENV-INVESTIGATE-01",
    claim=("Environment investigation is ROBUST and BOUNDED: the substrate scans "
           "its world recursively, records what each thing IS structurally, and "
           "takes what each file holds in through its one act of perceiving, by "
           "every sense that can — while never handing a binary to reading, and "
           "never exceeding its scan/depth/size bounds."),
    hypothesis=("A naive scanner either stays shallow (missing nested content), or "
                "decodes everything (turning binary bytes into fabricated 'facts'). "
                "Both failures are visible here: nested content must be found, and "
                "a NUL-containing file must yield structural metadata and never be "
                "taken in."))

results = []
def check(n, ok, d=""):
    results.append(bool(ok))
    EV.check(n, bool(ok), d)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


async def main() -> int:
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator as C

    class _Rec:
        def __init__(self): self.calls = []
        async def learn_fact(self, s, r, o, *, domain=None, provenance=None, quality=None):
            self.calls.append({"s": s, "r": r, "o": o, "domain": domain, "q": quality,
                               "prov": getattr(provenance, "source_type", None),
                               "src": getattr(provenance, "source_id", None)})
            return SimpleNamespace(admitted=True)

    from core.perception.perception_faculty import PerceptionFaculty

    class _Env:
        _ENV_SCAN_MAX_ENTRIES = C._ENV_SCAN_MAX_ENTRIES
        _ENV_SCAN_MAX_DEPTH = C._ENV_SCAN_MAX_DEPTH
        _ENV_READ_MAX_BYTES = C._ENV_READ_MAX_BYTES
        _scan_environment = C._scan_environment
        _ingest_environment_entry = C._ingest_environment_entry
        # The REAL senses' judgement of what a file can give.
        vision = PerceptionFaculty
        taken = []
        async def take_in(self, path, *, actor_identity, source=None, domain=None, within=None):
            self.taken.append({"path": path, "actor_identity": actor_identity, "source": source})
    me = _Env(); me.learning = _Rec()

    # build a temp world: nested dirs, text with parseable sentences, a binary, an image-by-ext
    root = tempfile.mkdtemp(prefix="envscan_")
    try:
        with open(os.path.join(root, "a.txt"), "w") as f:
            f.write("A cat is an animal.\nThe engine is a component.\nShort.\n")
        os.mkdir(os.path.join(root, "sub"))
        with open(os.path.join(root, "sub", "b.md"), "w") as f:
            f.write("A memristor is a component.\n")
        with open(os.path.join(root, "bin.dat"), "wb") as f:
            f.write(b"\x00\x01\x02\x03binarynottext")
        with open(os.path.join(root, "notes"), "w") as f:
            f.write("A robin is a bird.\n")
        with open(os.path.join(root, "long.txt"), "w") as f:
            f.write("A robin is a bird.\n" * (C._ENV_READ_MAX_BYTES // 19 + 10))
        os.mkdir(os.path.join(root, "empty"))

        print("\n== recursive, bounded scan ==")
        entries = me._scan_environment(root)
        names = {e["name"]: e for e in entries}
        check("scan recurses into subdirectories (finds sub/b.md at depth 1)",
              "b.md" in names and names["b.md"]["depth"] == 1, str(sorted(names)))
        check("scan records kind + extension + size",
              names.get("a.txt", {}).get("kind") == "file" and names["a.txt"]["ext"] == "txt"
              and names["a.txt"]["size"] > 0)
        check("directories are recorded too", names.get("sub", {}).get("kind") == "dir"
              and names.get("empty", {}).get("kind") == "dir")

        print("\n== what each file can give, as its bytes say ==")
        check("a NUL-containing file gives no sense anything (binary, never decoded)",
              PerceptionFaculty.senses_of(os.path.join(root, "bin.dat")) == ())
        check("a text file is taken in by reading",
              PerceptionFaculty.senses_of(os.path.join(root, "a.txt")) == ("reading",))
        check("a text file with no name for its kind is read by what its bytes are",
              PerceptionFaculty.senses_of(os.path.join(root, "notes")) == ("reading",))

        print("\n== what a text HOLDS is taken in by the one act, as its own perceiving ==")
        prov = SimpleNamespace(producer="perception", source_id="environment", source_type="PERCEPTION")
        me.learning.calls.clear(); me.taken.clear()
        a_entry = names["a.txt"]
        await me._ingest_environment_entry(a_entry, "environment_test", prov)
        calls = me.learning.calls
        struct = [c for c in calls if c["r"] in ("contains", "isa", "has_extension", "has_size_bytes")]
        check("structural facts held (contains / isa / extension / size)", len(struct) >= 3,
              f"{len(struct)} structural")
        check("the text is handed to the one act of perceiving, as the substrate's own",
              [t["path"] for t in me.taken] == [a_entry["path"]]
              and all(t["actor_identity"] is None for t in me.taken), f"{me.taken}")

        print("\n== binary file and over-long text: metadata only, never taken in ==")
        me.learning.calls.clear(); me.taken.clear()
        await me._ingest_environment_entry(names["bin.dat"], "environment_test", prov)
        bin_struct = [c for c in me.learning.calls if c["r"] in ("contains", "isa")]
        check("binary file yields structural metadata and is never taken in",
              len(bin_struct) >= 2 and not me.taken, f"taken: {me.taken}")
        bin_content = list(me.taken)
        me.taken.clear()
        await me._ingest_environment_entry(names["long.txt"], "environment_test", prov)
        check("a text past the read bound is recorded by its metadata, not read",
              not me.taken, f"{names['long.txt']['size']} bytes; taken: {me.taken}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    passed = sum(results); total = len(results)
    print(f"\n==== ENV-INVESTIGATE-01: {passed}/{total} checks passed ====")
    EV.metric("entries_scanned", len(entries), "count",
              "everything the bounded recursive scan found, files and directories")
    EV.metric("scan_max_entries", me._ENV_SCAN_MAX_ENTRIES, "count", "the containment bound")
    EV.metric("scan_max_depth", me._ENV_SCAN_MAX_DEPTH, "levels", "the containment bound")
    EV.metric("read_max_bytes", me._ENV_READ_MAX_BYTES, "bytes",
              "no file is read past this — investigation cannot become ingestion")
    EV.metric("structural_facts", len(struct), "count",
              "what the thing IS: contains / isa / extension / size")
    EV.metric("binary_taken_in", len(bin_content), "count",
              "MUST be 0: a NUL-containing file yields metadata only. Any other "
              "value means the substrate decoded bytes into invented facts")
    EV.note("Uses the REAL _scan_environment / _ingest_environment_entry and the "
            "real senses' judgement (PerceptionFaculty.senses_of), bound to a "
            "stand-in that records what is handed to the one act of perceiving. "
            "What that act does with a text it reads -- its words through the "
            "substrate's reader, held as what the file said, the reading recorded "
            "in the reading ledger -- is READ-01's to show.")
    await EV.verify_database()
    EV.write()
    return 0 if passed == total else 1

sys.exit(asyncio.run(main()))
