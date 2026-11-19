"""Regenerate the master experiment registry from the run artifacts.

Reads every experiments/**/results/*.json, keeps the RunRecords (a transcript is not one),
and writes the registry table plus the totals the document quotes.
"""
import json, os, re, glob, sys
from collections import defaultdict

ROOT = "."
DOC = "docs/LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md"

# Domains already in use in the document, reused rather than invented.
doc = open(DOC, encoding="utf-8").read()
KNOWN = {m.group(1): m.group(2).strip()
         for m in re.finditer(r"^\| `([A-Z0-9][A-Z0-9\-]*)` \| ([A-Za-z\- ]*?) \|", doc, re.M)
         if m.group(2).strip()}

# For an experiment the document never listed, the family its name belongs to.
FAMILY = [
 (r"^(GRAMMAR|SENSE|SENSES|ENGLISH|WORD|QUESTION-FORMS|STRUCTURE|SHAPES|COMPOSE|PACKED|PMB|PROPBANK|ROLES|COUNTABILITY|GROUPS|READ|UNDERSTANDS|NLU|SPLIT|SPLITS|KNOWS-WORDNET|MAIN-ENGLISH|FRESH-LESSON|ENGLISH-LESSON|TRAIN-FORMAT|SONGS|TUNES|nlu|PROBE)", "Language"),
 (r"^(SPEECH|HEAR|MEMORY-SOUND|MEMORY-SIGHT|RECOGNISE|SEE-LOOP|PERCEIVE)", "Perception"),
 (r"^(RULE-AUTHORITY|RULE-EVIDENCE|TEACH|LEARNED-WORK|READ-LEARN|CAPABILITY-EMERGE|DOMAIN-DISCOVERY|CONSOLIDATION|FIFTY|EXPECT)", "Learning"),
 (r"^(CANARY|TRUTH|UNASSERTED|RULE-|FALSIFY|SELFSTATE)", "Epistemics"),
 (r"^(TASK-GATE|TASKS-AT-ONCE|REPLAN|PATHS|PURSUIT|DRIVES|RELEASE)", "Intent"),
 (r"^(AGENTS|ORG|INSTANCES|MESSAGE|WORK-TALK|LIVE|SYSTEM-CONVERSATION)", "Coordination"),
 (r"^(THREAT-SENSE|ARBITER-WIRING)", "Governance"),
 (r"^(RECALL|MEMORY)", "Memory"),
 (r"^(SYSTEM-)", "Integrated"),
 (r"^(TOOLDOMAIN|TOOLS-EXTERNAL|OUTSIDE-DB|RESEARCH-WRITE|DOC|SYSML|ENCODER|SEPARATION)", "Capability"),
]
def domain_of(name):
    if name in KNOWN: return KNOWN[name]
    for pat, d in FAMILY:
        if re.match(pat, name): return d
    return "Capability"

# A RUN RECORD is `<UTC stamp>.json`. `<stamp>_<name>.json` is a side record of that run (a
# transcript, the cases it used, what changed) and is not a second run; a fixed-name file
# (`manifest.json`, `result.json`) is an older experiment's one record, which each run replaced.
RUN = re.compile(r"^\d{8}T\d{6}Z\.json$")
SIDE = re.compile(r"^\d{8}T\d{6}Z_.+\.json$")
runs = defaultdict(list); side = defaultdict(list)
for p in glob.glob("experiments/**/results/*.json", recursive=True):
    base = os.path.basename(p)
    exp = p.split("/results/")[0].split("/")[-1]
    if SIDE.match(base): side[exp].append(p)
    else: runs[exp].append(p)

# every experiment directory, so the ones with no artifact are listed too
dirs = set()
for d, subs, files in os.walk("experiments"):
    b = os.path.basename(d)
    if b in ("results", "__pycache__", "experiments"): continue
    if "results" in subs or any(f.endswith(".py") for f in files):
        dirs.add(b)

rows = []
total_runs = 0
for exp in sorted(dirs | set(runs)):
    # "latest" means latest by the UTC stamp the filename carries; a file with no stamp
    # is an older fixed-name record and never outranks a stamped run.
    def _key(path):
        m = re.search(r"(\d{8}T\d{6}Z)", os.path.basename(path))
        return (1, m.group(1)) if m else (0, os.path.basename(path))
    arts = sorted(runs.get(exp, []), key=_key)
    total_runs += len(arts)
    dom = domain_of(exp)
    if not arts:
        rows.append((exp, dom, "", "NO ARTIFACT", "", 0, "`none`")); continue
    latest = arts[-1]
    try:
        d = json.load(open(latest, encoding="utf-8"))
    except Exception:
        rows.append((exp, dom, "see §25", "MEASURED (non-standard record)", "", len(arts), f"`{os.path.basename(latest)}`")); continue
    if not isinstance(d, dict):
        rows.append((exp, dom, "see §25", "MEASURED (non-standard record)", "", len(arts), f"`{os.path.basename(latest)}`")); continue
    checks = passed = None
    s = d.get("summary")
    if isinstance(s, dict) and isinstance(s.get("checks"), int):
        checks, passed = s.get("checks"), s.get("passed")          # RunRecord
    elif isinstance(d.get("checks_total"), int):
        checks, passed = d["checks_total"], d.get("checks_passed")  # exit-code form
    elif isinstance(d.get("total"), int) and isinstance(d.get("passed"), int):
        checks, passed = d["total"], d["passed"]                    # checks + total form
    elif isinstance(d.get("checks"), list) and d["checks"]:
        checks = len(d["checks"])
        passed = sum(1 for c in d["checks"] if isinstance(c, dict) and c.get("passed") is True)
    when = (d.get("started_at") or d.get("run_at") or d.get("at") or d.get("stamp") or "")
    when = when[:10] if re.match(r"^\d{4}-", when or "") else (
           f"{when[:4]}-{when[4:6]}-{when[6:8]}" if re.match(r"^\d{8}T", when or "") else "")
    if isinstance(checks, int) and isinstance(passed, int) and checks > 0:
        result = f"{passed}/{checks}"
        status = "VALIDATED" if passed == checks else "FINDING"
    else:
        result, status = "see §25", "MEASURED"
    rows.append((exp, dom, result, status, when, len(arts), f"`{os.path.basename(latest)}`"))

print(f"experiment directories : {len(dirs | set(runs))}")
print(f"carrying run records   : {sum(1 for r in rows if r[5] > 0)}")
print(f"run records in total   : {total_runs}")
print(f"side records beside them: {sum(len(v) for v in side.values())}")
from collections import Counter
print("statuses:", dict(Counter(r[3] for r in rows)))
print("domains :", dict(Counter(r[1] for r in rows)))

out = ["| Experiment ID | Domain | Result | Status | Latest | Runs | Latest artifact |",
       "|---|---|---|---|---|---|---|"]
for exp, dom, res, st, when, n, art in rows:
    out.append(f"| `{exp}` | {dom} | {res} | {st} | {when} | {n} | {art} |")
open("/private/tmp/claude-501/-Users-stefan-Dominion-Labs/3e939454-a958-48e7-98fc-fe70317b1f46/scratchpad/registry_table.md","w").write("\n".join(out)+"\n")
json.dump({"dirs":len(dirs|set(runs)),"with_records":sum(1 for r in rows if r[5]>0),"runs":total_runs,
           "side":sum(len(v) for v in side.values()),
           "statuses":dict(Counter(r[3] for r in rows))},
          open("/private/tmp/claude-501/-Users-stefan-Dominion-Labs/3e939454-a958-48e7-98fc-fe70317b1f46/scratchpad/registry_totals.json","w"), indent=1)
print(f"\ntable rows written: {len(rows)}")
