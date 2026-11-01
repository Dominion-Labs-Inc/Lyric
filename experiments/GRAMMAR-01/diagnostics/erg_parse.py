"""THE ENGLISH RESOURCE GRAMMAR READING A SENTENCE, for comparison with Lyric's own grammar.

The ERG (`delph-in/erg`, MIT) is a hand-written broad-coverage HPSG grammar of English, built over more than twenty
years, with 225 syntactic and 70 lexical rules; it gives Minimal Recursion Semantics (Copestake et al. 2005). ACE
(`sweaglesw.org/linguistics/ace`, MIT) parses with it. NEITHER IS A MODEL: both are rules written by hand, which is
why this is comparable with Lyric's grammar at all.

RUN IN A CONTAINER, and why: ACE mmaps its grammar image at a hardcoded address (`FREEZER_MMAP_BASE`), and the macOS
build on offer is from February 2020, before the fix that moved it for Apple Silicon (r1096). On this machine it dies
with "mmap didn't put the freezer where i wanted it". The Linux build 0.9.34 and the grammar image compiled for it
run under Docker. A UTF-8 locale must be set or ACE fails decoding a curly apostrophe in the grammar's OWN data
("multibyte decoding failed ... on string `isn't`"), which looks like a problem with the sentence and is not.

    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/erg_parse.py "The dog chased a cat."

Nothing here is pushed: `tools/delphin/` is 302 MB of downloaded binary and grammar image (`.gitignore`).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "tools" / "delphin"
GRAMMAR = "erg-2018-x86-64-0.9.34.dat"
ACE = "ace-0.9.34/ace"
IMAGE = "debian:stable-slim"


def read(sentences, readings=1, timeout=600):
    """Each sentence's Minimal Recursion Semantics as the ERG gives it, in the order asked, None where it gives none.

    One ACE for all of them: starting it costs loading a 270 MB grammar image, so a sentence at a time made the whole
    dev split unaffordable."""
    said = "\n".join(s.replace("\n", " ") for s in sentences) + "\n"
    out = subprocess.run(
        ["docker", "run", "--rm", "-i", "--platform", "linux/amd64",
         "-e", "LC_ALL=C.UTF-8", "-e", "LANG=C.UTF-8",
         "-v", f"{TOOLS}:/d:ro", IMAGE,
         f"/d/{ACE}", "-g", f"/d/{GRAMMAR}", "-n", str(readings), "-T", "-q"],
        input=said, capture_output=True, text=True, timeout=timeout)
    # ACE writes one block per sentence, blocks apart by a blank line, nothing where it read none; what it could not
    # read at all it says on stderr.
    blocks, held = [], []
    for line in out.stdout.splitlines():
        if line.startswith("[ LTOP:"):
            held.append(line)
        elif not line.strip() and held:
            blocks.append(held[-1])
            held = []
    if held:
        blocks.append(held[-1])
    return blocks, out.stderr


def main():
    sentences = sys.argv[1:] or ["The dog chased a cat."]
    blocks, trouble = read(sentences)
    from delphin.codecs import simplemrs
    from delphin import dmrs
    for text, block in zip(sentences, blocks + [None] * len(sentences)):
        print(f"{text!r}")
        if block is None:
            print("    the ERG reads no whole")
            continue
        m = simplemrs.decode(block)
        d = dmrs.from_mrs(m)
        print(f"    {len(d.nodes)} predicates, {len(d.links)} links; "
              f"{m.index and dict(m.variables.get(m.index, {})) or ''}")
        for node in d.nodes:
            print(f"      {node.id:>4} {node.predicate:20} {dict(node.properties) if node.properties else ''}"
                  + (f'  CARG={node.carg!r}' if node.carg else ""))
        for link in d.links:
            print(f"      {link.start} -{link.role}/{link.post}-> {link.end}")
        print(flush=True)
    if trouble.strip():
        print("ACE said:", trouble.strip()[:400])


if __name__ == "__main__":
    main()
