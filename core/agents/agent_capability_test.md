## Test ##


**Capability verification: the substrate deploys multiple agents, defines a
tool set for each, and each agent successfully executes each of its tools —
against the REAL booted system and the REAL filesystem world. The substrate
(coordinator) deploys the agents, awaits their findings, and reports back.**



Constraints proven: <=3 agents, <=3 tools each, every tool must actually run and
succeed (real tool registry, real files on disk — nothing faked)."""
import asyncio
import os
import shutil
import sys

WORLD = "/private/tmp/claude-501/-Users-stefan-Dominion-Labs/742ecdc2-23e5-4155-8eef-f9a56262a11a/scratchpad/world"


async def main():
    from core.main import get_system
    from core.agents.autonomous.shared_types import TaskType

    print("booting substrate ...", flush=True)
    system = get_system()
    await system.initialize()
    coord = system.autonomous_coordinator
    assert coord is not None, "no coordinator after init"
    assert coord.agent_coordinator is not None, "agent authority not bound to coordinator"
    print("substrate up; agent authority bound:", coord.agent_coordinator is not None, flush=True)

    # ── the filesystem world: a scratch dir with one seed file as initial state ─
    if os.path.exists(WORLD):
        shutil.rmtree(WORLD)
    os.makedirs(WORLD)
    seed = os.path.join(WORLD, "seed.txt")
    with open(seed, "w") as f:
        f.write("seed-line-1\nseed-line-2\nseed-line-3\n")

    # ── three agents, each a defined set of <=3 tools + the plan to run them ────
    A = os.path.join(WORLD, "a.txt")
    fleet = [
        {
            "desc": "file-scribe: author, read back, and checksum a file",
            "reasoning": "deductive",
            "tools": ["write_file", "read_file", "calculate_checksum"],
            "plan": [
                {"tool": "write_file", "args": {"file_path": A, "content": "alpha\nbeta\ngamma\n"}},
                {"tool": "read_file", "args": {"file_path": A}},
                {"tool": "calculate_checksum", "args": {"file_path": A}},
            ],
            "artifacts": [A],
        },
        {
            "desc": "dir-warden: make a dir, copy the seed into it, list it",
            "reasoning": "inductive",
            "tools": ["create_directory", "copy_file", "list_directory"],
            "plan": [
                {"tool": "create_directory", "args": {"directory_path": os.path.join(WORLD, "b")}},
                {"tool": "copy_file", "args": {"source_path": seed, "destination_path": os.path.join(WORLD, "b", "seed_b.txt")}},
                {"tool": "list_directory", "args": {"directory_path": os.path.join(WORLD, "b")}},
            ],
            "artifacts": [os.path.join(WORLD, "b", "seed_b.txt")],
        },
        {
            "desc": "copy-clerk: make a dir, copy the seed, checksum the copy",
            "reasoning": "abductive",
            "tools": ["create_directory", "copy_file", "calculate_checksum"],
            "plan": [
                {"tool": "create_directory", "args": {"directory_path": os.path.join(WORLD, "c")}},
                {"tool": "copy_file", "args": {"source_path": seed, "destination_path": os.path.join(WORLD, "c", "seed_c.txt")}},
                {"tool": "calculate_checksum", "args": {"file_path": os.path.join(WORLD, "c", "seed_c.txt")}},
            ],
            "artifacts": [os.path.join(WORLD, "c", "seed_c.txt")],
        },
    ]

    # ── the SUBSTRATE deploys each agent (scoped to its tools) ──────────────────
    deployed = []
    for spec in fleet:
        handle = coord.deploy_agent(
            spec["desc"],
            reasoning_type=spec["reasoning"],
            allowed_tools=spec["tools"],
            task_type=TaskType.EXECUTION,
            parameters={"tool_plan": spec["plan"]},
        )
        assert handle is not None, f"deploy refused for {spec['desc']}"
        deployed.append((handle, spec))
        print(f"  deployed  {handle:16}  ({spec['reasoning']:9}) tools={spec['tools']}", flush=True)

    print(f"\nsubstrate deployed {len(deployed)} agents concurrently; pending={coord.pending_agents()}\n", flush=True)

    # ── the SUBSTRATE awaits each agent's findings and reports back ─────────────
    all_pass = True
    for handle, spec in deployed:
        finding = await asyncio.wait_for(coord.await_agent(handle), timeout=120)
        if finding is None or finding.get("error"):
            all_pass = False
            print(f"✗ {handle}: {finding.get('error') if finding else 'no finding'}")
            continue
        res = finding["findings"] or {}
        runs = res.get("tools_run", [])
        ok = res.get("success") is True and len(runs) == len(spec["plan"]) and all(r["success"] for r in runs)
        # real-world effects: the artifacts must actually exist on disk
        artifacts_ok = all(os.path.exists(p) for p in spec["artifacts"])
        ok = ok and artifacts_ok
        all_pass = all_pass and ok
        mark = "✓" if ok else "✗"
        print(f"{mark} {handle:16} ({spec['reasoning']}) — {res.get('method')} — artifacts_on_disk={artifacts_ok}")
        for r in runs:
            print(f"      {'✓' if r['success'] else '✗'} {r['tool']}")

    print("\n" + ("ALL AGENTS EXECUTED ALL TOOLS SUCCESSFULLY" if all_pass else "VERIFICATION FAILED"))

    # cleanup the world
    shutil.rmtree(WORLD, ignore_errors=True)
    return 0 if all_pass else 1


sys.exit(asyncio.run(main()))


## Results ##


=== report lines from stdout ===
booting substrate ...
substrate up; agent authority bound: True
  deployed  sly-otter         (deductive) tools=['write_file', 'read_file', 'calculate_checksum']
  deployed  clever-wren       (inductive) tools=['create_directory', 'copy_file', 'list_directory']
  deployed  opal-silo         (abductive) tools=['create_directory', 'copy_file', 'calculate_checksum']
substrate deployed 3 agents concurrently; pending=['sly-otter', 'clever-wren', 'opal-silo']
✓ sly-otter        (deductive) — declared_tools — artifacts_on_disk=True
      ✓ write_file
      ✓ read_file
      ✓ calculate_checksum
✓ clever-wren      (inductive) — declared_tools — artifacts_on_disk=True
      ✓ create_directory
      ✓ copy_file
      ✓ list_directory
✓ opal-silo        (abductive) — declared_tools — artifacts_on_disk=True
      ✓ create_directory
      ✓ copy_file
      ✓ calculate_checksum
ALL AGENTS EXECUTED ALL TOOLS SUCCESSFULLY

=== any Traceback/deploy refused in stdout? ===
