# Permission Surface — what will need authorization when auth is added

*Purpose: a living inventory of every operation the substrate performs autonomously that a future
auth/permission layer must gate. NOT gated yet (by decision) — this is the map so the permission model
knows its surface. Organized by ACCESS CLASS; most tools already carry `core.tools` `Capability`
metadata (`READ_DATA`, filesystem/network flags) an auth layer can key on, so per-tool enumeration is
unnecessary — gate the class.*

Legend — sensitivity: 🟢 low (self/metadata) · 🟡 medium (local data) · 🔴 high (external / mutating / PII).

## 1. Environment / filesystem READ  🟡 (🔴 when the corpus contains PII)
The robust environment investigation reads the world it is placed in. This is the biggest newly-widened
surface.
- **Directory enumeration (recursive)** — `_scan_environment` (autonomous_coordinator). Lists every
  file/dir under the environment root, bounded (`_ENV_SCAN_MAX_ENTRIES=400`, depth `4`). *Needs:* a LIST
  grant scoped to authorized roots (which directories the substrate may enumerate).
- **File content read** — `_read_text_bounded` + `_ingest_environment_entry` (text ≤ `_ENV_READ_MAX_BYTES`
  64 KiB) and the `read_file` tool (`core/tools/filesystem_tools.py`). Reads file CONTENTS into knowledge
  as PERCEPTION observations. *Needs:* a READ grant scoped to paths/types; a per-file-type policy (which
  extensions may be read); a size ceiling per grant.
- **Image perception** — `see(path)` on image files found during investigation. *Needs:* READ grant on
  image paths.
- **Host metadata** — `_observe_environment` (hostname, user, uid, platform, cwd). 🟢 low, but still an
  environment read; *Needs:* a (usually default-allow) self-inspection grant.
- **PII note:** entities/people in read files become ENTITY concepts + beliefs (PERCEPTION provenance).
  A most-wanted-style corpus makes this 🔴. *Needs (future):* a PERSON/PII classification gate — entities
  tagged PERSON get a mandatory high stakes floor + a governance check before any operating action, and
  investigation confined to an explicitly-authorized corpus. (Flagged as a gap; not built.)

## 2. Network / external egress  🔴
- **Web research** — `look_up` → `_research_phrase` → the `web_search` tool (currently hardcoded; slated
  to become source-agnostic). Any outbound lookup leaves the box. *Needs:* a NETWORK/EGRESS grant
  (allow-list of destinations, or off entirely on an air-gapped deployment).
- **API / browser / communication tools** — `api_call`, `browser_navigate`, communication tools, etc.
  *Needs:* per-destination egress grants.

## 3. Execution / world-mutation  🔴
Gated today by governance + action contracts + the operability stakes gate; an auth layer adds identity.
- **Run a learned operator / tool** — `_execute_grounded_operator`, `_run_tool`, `execute_tool`.
  *Needs:* an EXECUTE grant per tool (or per `ActionClass`).
- **Filesystem WRITE / mutate** — `atomic_write_file`, `apply_patch`, copy/move/delete, `run_python`,
  subprocess. *Needs:* a WRITE grant scoped to paths; EXECUTE grant for code/subprocess.
- **Action classes** — `_declared_consequence` orders INVESTIGATE < MODIFY < ARCHIVE < DELETE < EXECUTE
  (the stakes scale). *Needs:* permission keyed to action class (e.g. DELETE/EXECUTE require explicit
  grant; INVESTIGATE may default-allow).
- **Deploy an agent of self** — `deploy_agent` (spawns a scoped substrate copy). *Needs:* a SPAWN grant +
  the child inherits only the parent's granted tool subset.

## 4. Knowledge ingestion / memory WRITE  🟡
- **Ingest external content into the store** — `learn_fact` / `_ingest` / `teach` with non-self provenance
  (file content, web findings, perception). Writing external data into durable belief/concept stores.
  *Needs:* a data-ingestion grant (what sources may be admitted) — provenance is already stamped, so an
  auth layer can gate by source class.
- **No self-modification** — the substrate never rewrites its own code, configuration or weights; it
  improves only by learning, which is covered by the ingestion grant above.

## 5. Security / infrastructure actions  🔴
- Block IP/country, rate-limit, threat response (`block_ip_address`, `apply_rate_limit`, `auto_respond_threat`),
  health/DB checks. *Needs:* an OPERATE-SECURITY grant (these change the environment's posture).

## How an auth layer should attach (design note, not built)
- **Key on capability class + action class + provenance + path/destination scope**, not per-tool — the
  `Capability` metadata and `_declared_consequence` already provide the axes.
- **The operability stakes gate is the natural place for the per-domain bar**; identity/permission is an
   orthogonal gate in front of execution and external egress.
- **Default posture for a DoD/air-gapped deployment:** network egress OFF (web research disabled →
  investigation is local-corpus only); filesystem READ scoped to an authorized corpus; WRITE/EXECUTE/
  DELETE explicit-grant; PERSON/PII classification gate on entities.
