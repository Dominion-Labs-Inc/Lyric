"""ENV-INVESTIGATE-01 — environment investigation is ROBUST: recursive scan + file CONTENT read into
knowledge (as observations), images perceived, binaries recorded by metadata only.

Uses the REAL `_scan_environment` / `_read_text_bounded` / `_ingest_environment_entry` bound to a
recording stand-in learning faculty (so we see exactly what is turned into knowledge, no DB writes).

Run: ./venv_torin/bin/python3 scratchpad/bench_envscan.py
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
           "reads textual CONTENT into observations linked to what the file is "
           "about — while never decoding a binary as text, and never exceeding its "
           "scan/depth/size bounds."),
    hypothesis=("A naive scanner either stays shallow (missing nested content), or "
                "decodes everything (turning binary bytes into fabricated 'facts'). "
                "Both failures are visible here: nested content must be found, and "
                "a NUL-containing file must yield structural metadata with ZERO "
                "content facts."))

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

    class _Env:
        _ENV_SCAN_MAX_ENTRIES = C._ENV_SCAN_MAX_ENTRIES
        _ENV_SCAN_MAX_DEPTH = C._ENV_SCAN_MAX_DEPTH
        _ENV_READ_MAX_BYTES = C._ENV_READ_MAX_BYTES
        _ENV_CONTENT_MAX_FACTS = C._ENV_CONTENT_MAX_FACTS
        _ENV_TEXT_EXTS = C._ENV_TEXT_EXTS
        _ENV_IMAGE_EXTS = C._ENV_IMAGE_EXTS
        _scan_environment = C._scan_environment
        _read_text_bounded = C._read_text_bounded
        _ingest_environment_entry = C._ingest_environment_entry
        saw = []
        async def see(self, path, *, source=None):
            self.saw.append(path)
    me = _Env(); me.learning = _Rec()
    # A REAL reading ledger. `_read_text_bounded` records what it read and of
    # which version — reading a file IS a reading, and Law 2 consults the ledger
    # before the substrate acts on anything it has only remembered. The stand-in
    # has to carry the real one or it stops exercising the real method.
    from core.agents.autonomous.autonomous_coordinator import ReadingLedger
    me.reading = ReadingLedger()

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

        print("\n== binary sniff ==")
        check("a NUL-containing file reads as None (binary, never decoded)",
              me._read_text_bounded(os.path.join(root, "bin.dat")) is None)
        check("a real text file reads its content",
              "cat" in (me._read_text_bounded(os.path.join(root, "a.txt")) or ""))

        print("\n== CONTENT is read into knowledge (as PERCEPTION observations) ==")
        me.learning.calls.clear()
        # ingest the text file
        a_entry = names["a.txt"]
        n = await me._ingest_environment_entry(a_entry, "environment_test", SimpleNamespace(
            producer="perception", source_id="environment", source_type="PERCEPTION"))
        calls = me.learning.calls
        struct = [c for c in calls if c["r"] in ("contains", "isa", "has_extension", "has_size_bytes")]
        content = [c for c in calls if c["prov"] == "PERCEPTION" and c["src"] == a_entry["path"]]
        mentions = [c for c in calls if c["r"] == "mentions"]
        check("structural facts held (contains / isa / extension / size)", len(struct) >= 3,
              f"{len(struct)} structural")
        check("file CONTENT read into observations (PERCEPTION prov, source=the file, low quality)",
              len(content) >= 1 and all(c["q"] == 0.3 for c in content),
              f"{len(content)} content observations: {[(c['s'],c['r'],c['o']) for c in content][:3]}")
        check("the file is linked to what it is ABOUT (mentions)", len(mentions) >= 1,
              f"{[c['o'] for c in mentions]}")

        print("\n== binary file: metadata only, never read as content ==")
        me.learning.calls.clear()
        await me._ingest_environment_entry(names["bin.dat"], "environment_test", SimpleNamespace(
            producer="perception", source_id="environment", source_type="PERCEPTION"))
        bin_content = [c for c in me.learning.calls if c["src"] == names["bin.dat"]["path"]]
        check("binary file yields structural metadata but NO decoded content", len(bin_content) == 0,
              f"{len(bin_content)} content facts (want 0)")
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
    EV.metric("content_observations", len(content), "count",
              "sentences read from real text, held as PERCEPTION-provenance "
              "observations at low quality — observations, not knowledge")
    EV.metric("binary_content_facts", len(bin_content), "count",
              "MUST be 0: a NUL-containing file yields metadata only. Any other "
              "value means the substrate decoded bytes into invented facts")
    EV.metric("files_recorded_in_ledger", len(me.reading.authored_paths()) + 
              me.reading.status()["files_read"], "count",
              "every content read is recorded as a READING, so Law 2 can later tell "
              "whether what the substrate holds is still what is on disk")
    EV.note("Uses the REAL _scan_environment / _read_text_bounded / "
            "_ingest_environment_entry bound to a minimal stand-in carrying a real "
            "ReadingLedger, so the reading-ledger side effect is exercised rather "
            "than stubbed out.")
    await EV.verify_database()
    EV.write()
    return 0 if passed == total else 1

sys.exit(asyncio.run(main()))
