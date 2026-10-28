"""A run with chosen worlds rerun: the first run's answers and world log, each rerun world's taken from the rerun, scored
by the same evaluator. Writes <NAME>_run/ and <NAME>.json beside the first run (NAME: <BASE>_merged unless given), and
NOTES, when given, as what the rerun was."""
import json, os, shutil, subprocess, sys
BASE, RERUN, ONLY = sys.argv[1], sys.argv[2], {int(w) for w in open(sys.argv[3]).read().split(",")}
NAME = sys.argv[4] if len(sys.argv) > 4 else f"{BASE}_merged"
NOTES = sys.argv[5] if len(sys.argv) > 5 else (
    "The worlds of the first run that reached fewer goals the world allows than run 20261028T113002Z, rerun after "
    "the planner's fix (rule_grounding._OneTerm); every world scored by the same evaluator.")
OUT = f"{NAME}_run"
os.makedirs(OUT)
for name in ("worlds_public.jsonl", "worlds_truth.jsonl", "manifest.json"):
    shutil.copy(f"{BASE}_run/{name}", f"{OUT}/{name}")
rerun = {json.loads(l)["world"]: l for l in open(f"{RERUN}_run/answers.jsonl")}
assert ONLY <= set(rerun) and all(json.loads(rerun[w])["goals"] for w in ONLY), "a rerun world has no answer"
with open(f"{OUT}/answers.jsonl", "w") as out:
    for l in open(f"{BASE}_run/answers.jsonl"):
        w = json.loads(l)["world"]
        out.write(rerun[w] if w in ONLY else l)
with open(f"{OUT}/world_log.jsonl", "w") as out:
    for l in open(f"{BASE}_run/world_log.jsonl"):
        if json.loads(l)["world"] not in ONLY:
            out.write(l)
    for l in open(f"{RERUN}_run/world_log.jsonl"):
        if json.loads(l)["world"] in ONLY:
            out.write(l)
subprocess.run([sys.executable, "-I", "../evaluator.py", "--inputs", OUT, "--answers", f"{OUT}/answers.jsonl",
                "--out", f"{OUT}/evaluation.json"], check=True)
base, again = json.load(open(f"{BASE}.json")), json.load(open(f"{RERUN}.json"))
json.dump({"experiment": base["experiment"], "base_run": BASE, "rerun": RERUN, "rerun_worlds": sorted(ONLY),
           "duration_seconds": base["duration_seconds"], "rerun_duration_seconds": again["duration_seconds"],
           "notes": NOTES,
           "checks": json.load(open(f"{OUT}/evaluation.json"))["checks"]},
          open(f"{NAME}.json", "w"), indent=1)
