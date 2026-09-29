#!/usr/bin/env python3
"""KNOW-50 — put the real substrate in a world and ask it 50 knowledge questions
drawn from what it was taught (the English IsA taxonomy). NO answers are given to
the substrate: it receives only the question. For each question we display BOTH
what it REASONS (coord.reason_about — the real pipeline) AND what it actually
BELIEVES (the posterior it holds on that proposition, from its own belief store),
plus the derivation. Expected answers are used ONLY to score afterward — never
sent to the substrate.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/KNOW-50/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, json, sys, re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

# (subject, object, expected)  — expected is for SCORING ONLY, never sent.
QUESTIONS = [
    ("robin", "bird", True), ("sparrow", "bird", True), ("eagle", "bird", True),
    ("salmon", "fish", True), ("trout", "fish", True), ("shark", "fish", True),
    ("oak", "tree", True), ("pine", "tree", True), ("maple", "tree", True),
    ("rose", "flower", True), ("tulip", "flower", True), ("daisy", "flower", True),
    ("hammer", "tool", True), ("wrench", "tool", True), ("screwdriver", "tool", True),
    ("violin", "musical instrument", True), ("piano", "musical instrument", True),
    ("guitar", "musical instrument", True),
    ("copper", "metal", True), ("iron", "metal", True), ("gold", "metal", True),
    ("car", "vehicle", True), ("truck", "vehicle", True), ("bicycle", "vehicle", True),
    ("apple", "fruit", True), ("banana", "fruit", True), ("orange", "fruit", True),
    ("dog", "mammal", True), ("cat", "mammal", True), ("whale", "mammal", True),
    ("dolphin", "mammal", True), ("poodle", "dog", True),
    ("bee", "insect", True), ("ant", "insect", True), ("spider", "animal", True),
    ("carrot", "vegetable", True), ("lettuce", "vegetable", True),
    ("oak", "plant", True), ("wine", "beverage", True), ("beer", "beverage", True),
    # negatives — should be refuted, not fabricated
    ("hammer", "bird", False), ("salmon", "tree", False), ("copper", "animal", False),
    ("violin", "vehicle", False), ("rose", "fish", False), ("car", "fruit", False),
    ("dog", "plant", False), ("apple", "tool", False), ("piano", "animal", False),
    ("oak", "metal", False),
]

ART = {"a", "e", "i", "o", "u"}
def art(w):
    return "an" if w and w[0].lower() in ART else "a"
def question_text(s, o):
    return f"is {art(s)} {s} {art(o)} {o}?"
def yes_no(answer):
    a = (answer or "").strip().lower()
    if re.match(r"^(yes|true|correct|affirmative)\b", a) or a.startswith("yes"):
        return True
    if re.match(r"^(no|false|incorrect|negative)\b", a) or "not " in a[:12] or a.startswith("no"):
        return False
    return None  # refused / unsupported / unknown


async def main() -> int:
    from core.memory import Origin
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()

    async def belief_for(s, o):
        """What the substrate actually believes about `s isa o` — the posterior it
        holds, from its own store. (Read-only inspection AFTER reasoning.)"""
        key = f"{s} isa {o}".lower()
        rows = await db.execute_query(
            "SELECT claim, posterior_probability, domain FROM unified.beliefs "
            "WHERE lower(claim) = $1 LIMIT 1", (key,), fetch_all=True) or []
        if rows:
            r = rows[0]
            return {"held": True, "claim": r["claim"],
                    "posterior": round(float(r["posterior_probability"] or 0), 4),
                    "domain": r["domain"]}
        return {"held": False}

    print("=== substrate up; asking 50 knowledge questions (no answers given) ===\n", flush=True)
    results = []
    for i, (s, o, expected) in enumerate(QUESTIONS, 1):
        q = question_text(s, o)
        try:
            r = await coord.reason_about(q, origin=Origin.own("KNOW-50"))
            answer = str(getattr(r, "answer", "") or "")
            conf = round(float(getattr(r, "confidence", 0.0) or 0.0), 3)
            mode = str(getattr(r, "mode_used", "") or "")
            md = dict(getattr(r, "metadata", {}) or {})
        except Exception as e:
            answer, conf, mode, md = f"<error: {type(e).__name__}: {e}>", 0.0, "error", {}
        verdict = yes_no(answer)
        belief = await belief_for(s, o)
        correct = (verdict is not None and verdict == expected)
        results.append({"n": i, "q": q, "subject": s, "object": o,
                        "expected": expected, "verdict": verdict, "correct": correct,
                        "answer": answer[:160], "confidence": conf, "mode": mode,
                        "reason": md.get("reason"), "route": md.get("route"),
                        "derived_by": md.get("derived_by") or md.get("derived"),
                        "model_calls": md.get("model_calls"), "belief": belief})
        mark = "✓" if correct else ("·" if verdict is None else "✗")
        held = (f"believes «{belief['claim']}» → {belief['posterior']} [{belief['domain']}]"
                if belief["held"] else "no direct belief (derived via concept graph)")
        print(f"[{mark}] Q{i:02d} {q}", flush=True)
        print(f"       reasons: {answer[:90]!r}  (conf {conf}, mode {mode}, model_calls {md.get('model_calls')})", flush=True)
        print(f"       {held}\n", flush=True)

    answered = [r for r in results if r["verdict"] is not None]
    correct = [r for r in results if r["correct"]]
    refused = [r for r in results if r["verdict"] is None]
    held = [r for r in results if r["belief"]["held"]]
    pos = [r for r in results if r["expected"]]
    neg = [r for r in results if not r["expected"]]
    summary = {
        "total": len(results), "answered": len(answered), "refused_or_unknown": len(refused),
        "correct": len(correct), "accuracy_over_answered": round(len(correct)/max(1,len(answered)), 3),
        "accuracy_over_all": round(len(correct)/len(results), 3),
        "true_qs_correct": sum(1 for r in pos if r["correct"]), "true_qs": len(pos),
        "false_qs_correct": sum(1 for r in neg if r["correct"]), "false_qs": len(neg),
        "direct_beliefs_held": len(held),
        "model_calls_total": sum(int(r["model_calls"] or 0) for r in results),
    }
    manifest = {"experiment": "KNOW-50",
                "purpose": "50 taught-knowledge questions on the real substrate; display reasoned answer AND held belief",
                "run_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary, "results": results}
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("=== summary ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
