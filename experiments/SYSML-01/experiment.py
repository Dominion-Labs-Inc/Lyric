#!/usr/bin/env python3
"""SYSML-01: a system's SysML v2 model, written from its legacy documents, checked by the language's own
implementation.

`generate_sysml_model` (core/tools/sysml_tools.py) on a synthetic document set for a fictional patrol vessel mission
system: an equipment inventory (xlsx), a software inventory (csv), a cable run sheet (csv) and an interface control
document (docx: three paragraphs and a table). Built into the set on purpose: the Mission Computer's part number
differs between the two inventories; one cable end (Navigation Radar) is in no inventory; one cable (W108) has a
single end.

  A  every table is read row by row under its headings, with nothing left unread;
  B  every inventoried part is declared, typed by its kind and nested in the whole its "Part of" names;
  C  every cable and interface with two ends is drawn between the ports the rows name, inside the nearest whole
     holding both, and every end is a declared part or port;
  D  every element of the model names the document and row it was read from;
  E  the disagreement is kept, not settled: the part number is declared with no value, and its doc names both values
     and where each was read;
  F  nothing is invented: the part only a cable names is declared as only named, and untyped; the one-ended cable is
     not drawn, and a comment says so;
  G  the OMG SysML v2 pilot implementation finds no syntax error and no semantic error in the model;
  H  the same documents give the same model, byte for byte;
  I  the substrate's own reading of a document (`_understand_words`) states its table rows too, each with where it
     was read, and lets the rows go once read;
  J  no store is touched.

The prose paragraphs are read by the substrate's one reader, which reads only English the substrate has been taught;
this run has no memory up, so it measures how many lines were read and states nothing of them (a metric, not a check).

    ./venv_lyric/bin/python3 experiments/SYSML-01/experiment.py
"""
from __future__ import annotations

import asyncio
import csv
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
             "TQDM_DISABLE": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

SYSTEM = "Patrol Vessel Mission System"
EV = RunRecord(
    "SYSML-01",
    claim=("From a system's legacy documents (inventories, a cable run sheet, an interface control document), the "
           "substrate writes a SysML v2 model that the OMG's own implementation accepts, in which every element "
           "names the row it was read from, a disagreement between sources is kept with both values rather than "
           "settled, and nothing no source states is invented."),
    hypothesis=("A table read as run-on text, a part in the wrong whole or untyped, a cable drawn to a port no row "
                "names, an element with no source, a value chosen where the sources disagree, a part or cable "
                "invented to fill a gap, a model the pilot implementation rejects, a model that changes between "
                "two runs on the same documents, or a write to any store would each show here."))


def say(line=""):
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, ok, detail)
    say(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))


def make_set(folder: Path) -> list:
    """The synthetic document set (see the docstring)."""
    import docx
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Equipment"
    for row in [
        ["Name", "Type", "Part of", "Location", "Part number", "Requires"],
        ["Mission System", "System", "", "", "MS-100", ""],
        ["Sensor Suite", "Subsystem", "Mission System", "", "SS-200", ""],
        ["Surface Search Radar", "Radar", "Sensor Suite", "Mast", "SR-310", "Power Panel 2"],
        ["Radar Processor", "Processor", "Sensor Suite", "Equipment Room 2", "RP-220", "Power Panel 2"],
        ["Combat Management", "Subsystem", "Mission System", "", "CM-400", ""],
        ["Mission Computer", "Computer", "Combat Management", "Equipment Room 2", "MC-410", "Power Panel 2"],
        ["Operator Console A", "Operator Console", "Combat Management", "Operations Center", "OC-4471", ""],
        ["Operator Console B", "Operator Console", "Combat Management", "Operations Center", "OC-4471", ""],
        ["Network Switch 2", "Network Switch", "Mission System", "Equipment Room 2", "NS-2240", "Power Panel 2"],
        ["Power Panel 2", "Power Panel", "Mission System", "Equipment Room 2", "PP-0902", ""],
    ]:
        sheet.append(row)
    book.save(folder / "equipment_inventory.xlsx")
    with open(folder / "software_inventory.csv", "w", newline="") as f:
        csv.writer(f).writerows([
            ["Name", "Software", "Version", "Part number"],
            ["Mission Computer", "Combat Management Software", "7.4.2", "MC-411"],
            ["Radar Processor", "Track Processing", "3.1.0", "RP-220"],
            ["Operator Console A", "Console Display", "5.0.1", "OC-4471"],
        ])
    with open(folder / "cable_run_sheet.csv", "w", newline="") as f:
        csv.writer(f).writerows([
            ["Cable", "From", "From port", "To", "To port", "Type", "Length (m)"],
            ["W101", "Surface Search Radar", "J1", "Radar Processor", "J4", "Fiber", "32"],
            ["W102", "Radar Processor", "J7", "Network Switch 2", "P1", "Cat6", "4"],
            ["W103", "Mission Computer", "J2", "Network Switch 2", "P2", "Cat6", "3"],
            ["W104", "Operator Console A", "J3", "Network Switch 2", "P5", "Cat6", "18"],
            ["W105", "Operator Console B", "J3", "Network Switch 2", "P6", "Cat6", "18"],
            ["W106", "Power Panel 2", "CB4", "Radar Processor", "PWR", "Power", "6"],
            ["W107", "Navigation Radar", "J1", "Network Switch 2", "P7", "Cat6", "21"],
            ["W108", "Operator Console B", "J4", "", "", "Cat6", ""],
        ])
    document = docx.Document()
    document.add_paragraph("This document describes the interfaces of the patrol vessel mission system.")
    document.add_paragraph("The radar processor is connected to the mission computer.")
    document.add_paragraph("The mission computer is part of the combat management subsystem.")
    table = document.add_table(rows=1, cols=4)
    for cell, text in zip(table.rows[0].cells, ["Interface", "From", "To", "Protocol"]):
        cell.text = text
    for values in [["Track data", "Radar Processor", "Mission Computer", "Ethernet"],
                   ["Display data", "Mission Computer", "Operator Console A", "Ethernet"]]:
        for cell, text in zip(table.add_row().cells, values):
            cell.text = text
    document.save(folder / "interface_control.docx")
    return [str(folder / n) for n in ("equipment_inventory.xlsx", "software_inventory.csv",
                                      "cable_run_sheet.csv", "interface_control.docx")]


INVENTORIED = {
    "Mission System": ("System", "Mission System"),
    "Sensor Suite": ("Subsystem", "Mission System/Sensor Suite"),
    "Surface Search Radar": ("Radar", "Mission System/Sensor Suite/Surface Search Radar"),
    "Radar Processor": ("Processor", "Mission System/Sensor Suite/Radar Processor"),
    "Combat Management": ("Subsystem", "Mission System/Combat Management"),
    "Mission Computer": ("Computer", "Mission System/Combat Management/Mission Computer"),
    "Operator Console A": ("Operator Console", "Mission System/Combat Management/Operator Console A"),
    "Operator Console B": ("Operator Console", "Mission System/Combat Management/Operator Console B"),
    "Network Switch 2": ("Network Switch", "Mission System/Network Switch 2"),
    "Power Panel 2": ("Power Panel", "Mission System/Power Panel 2"),
}
CABLES = {
    "W101": ["Mission System/Sensor Suite/Surface Search Radar/J1", "Mission System/Sensor Suite/Radar Processor/J4"],
    "W102": ["Mission System/Sensor Suite/Radar Processor/J7", "Mission System/Network Switch 2/P1"],
    "W103": ["Mission System/Combat Management/Mission Computer/J2", "Mission System/Network Switch 2/P2"],
    "W104": ["Mission System/Combat Management/Operator Console A/J3", "Mission System/Network Switch 2/P5"],
    "W105": ["Mission System/Combat Management/Operator Console B/J3", "Mission System/Network Switch 2/P6"],
    "W106": ["Mission System/Power Panel 2/CB4", "Mission System/Sensor Suite/Radar Processor/PWR"],
    "W107": ["Navigation Radar/J1", "Mission System/Network Switch 2/P7"],
    "Track data": ["Mission System/Sensor Suite/Radar Processor", "Mission System/Combat Management/Mission Computer"],
    "Display data": ["Mission System/Combat Management/Mission Computer",
                     "Mission System/Combat Management/Operator Console A"],
}


def block_of(text: str, opening: str) -> str:
    """The lines of the element that `opening` starts, through its closing brace."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(opening))
    depth, out = 0, []
    for line in lines[start:]:
        out.append(line)
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
    return "\n".join(out)


async def main() -> int:
    from core.tools.sysml_tools import GenerateSysMLModelTool, PILOT_DIR
    tool = GenerateSysMLModelTool()
    with tempfile.TemporaryDirectory() as folder:
        documents = make_set(Path(folder))
        say("generate_sysml_model on the four documents")
        result = await tool.execute(documents=documents, system=SYSTEM,
                                    output_path=str(Path(folder) / "model.sysml"))
        again = await tool.execute(documents=documents, system=SYSTEM)
        out, text = result.output, result.output["sysml"]

        say("\nA  tables read row by row")
        read = {d["document"]: d for d in out["documents"]}
        rows = {name: (d.get("tables"), d.get("rows")) for name, d in read.items()}
        check("A tables read row by row", result.success and rows == {
            "equipment_inventory.xlsx": (1, 10), "software_inventory.csv": (1, 3),
            "cable_run_sheet.csv": (1, 8), "interface_control.docx": (1, 2)}
            and not any(d.get("unread") for d in read.values()), str(rows))
        EV.metric("facts_from_rows", sum(d["facts_from_rows"] for d in read.values()))
        EV.metric("values_from_rows", sum(d["values"] for d in read.values()))
        EV.metric("prose_passages_read", sum(d["passages"] for d in read.values()))
        EV.metric("facts_from_prose_passages", sum(d["facts_from_passages"] for d in read.values()),
                  note="no memory is up in this run, so the reader has no taught English to read them with")

        say("\nB  parts typed and nested")
        wrong = []
        for name, (kind, path) in INVENTORIED.items():
            if f"part: {path}" not in out["sources"]:
                wrong.append(f"{name} not at {path}")
            elif f"part {_q(name)} : {_q(kind)} {{" not in text:
                wrong.append(f"{name} not typed {kind}")
        check("B every inventoried part declared, typed, in its whole", not wrong, "; ".join(wrong) or
              f"{len(INVENTORIED)} parts")

        say("\nC  connections between the stated ports")
        drawn = {c["connection"]: c["ends"] for c in out["connections"]}
        check("C cables and interfaces drawn end to end", drawn == CABLES
              and out["checks"]["connection_ends_declared"],
              "; ".join(f"{k}: {drawn.get(k)}" for k in CABLES if drawn.get(k) != CABLES[k]) or
              f"{len(drawn)} drawn, every end declared")
        w102 = block_of(text, "connection 'W102'")
        check("C W102 sits in Mission System, the nearest whole holding both ends",
              "connect 'Sensor Suite'.'Radar Processor'.'J7' to 'Network Switch 2'.'P1'" in w102
              and block_of(text, "part 'Mission System'").count("connection 'W102'") == 1, w102.splitlines()[0])

        say("\nD  every element names where it was read")
        unsourced = [p for p, s in out["sources"].items() if not s]
        docs = text.count("doc /* Read from:") + text.count("doc /* Kind named in:") + \
            text.count("doc /* Named only in:") + text.count("doc /* The sources disagree")
        check("D every element names its document and row", not unsourced and out["checks"]["every_element_read_in"]
              and docs >= len(out["sources"]), f"{len(out['sources'])} elements, {docs} source docs")
        EV.metric("elements", out["elements"])

        say("\nE  the disagreement is kept")
        disagreements = out["disagreements"]
        computer = block_of(text, "part 'Mission Computer'")
        number = block_of(computer, "attribute 'Part number'")
        check("E one disagreement, the Mission Computer's part number, with both sources",
              len(disagreements) == 1 and disagreements[0]["element"] == "Mission Computer"
              and disagreements[0]["about"] == "Part number"
              and {v["value"] for v in disagreements[0]["values"]} == {"MC-410", "MC-411"}, str(disagreements))
        check("E the model chooses no value and names both",
              number.splitlines()[0].strip() == "attribute 'Part number' : ScalarValues::String {"
              and '"MC-410" in equipment_inventory.xlsx, Equipment, row 7' in number
              and '"MC-411" in software_inventory.csv, row 2' in number, number)

        say("\nF  nothing invented")
        check("F Navigation Radar declared as only named, untyped",
              out["named_only"] == [{"part": "Navigation Radar", "read_in": "cable_run_sheet.csv, row 8"}]
              and "Navigation Radar" in out["untyped"] and "part 'Navigation Radar' {" in text,
              str(out["named_only"]))
        check("F W108 not drawn, and the model says so",
              [n["connection"] for n in out["not_drawn"]] == ["W108"] and "connection 'W108'" not in text
              and "comment /* W108 is not drawn" in text, str(out["not_drawn"]))

        say("\nG  the language's own implementation")
        v = out["validation"]
        check("G the OMG SysML v2 pilot implementation accepts the model",
              v.get("validated") is True and v.get("valid") is True and v.get("warnings") == 0,
              str({k: v.get(k) for k in ("validated", "implementation", "syntax_errors", "semantic_errors",
                                         "warnings", "why")}))
        EV.note(f"Validator: {v.get('implementation')} from {PILOT_DIR}")

        say("\nH  deterministic")
        check("H the same documents give the same model", again.output["sysml"] == text,
              f"{len(text)} characters")

        say("\nI  the substrate's own reading states table rows")
        from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
        from core.perception import senses
        from core.perception.perception_faculty import PerceptionFaculty
        path = Path(documents[0])
        content = PerceptionFaculty._document_content(senses.read(str(path)), path, path.stem)
        had_tables = len(content.get("tables") or [])
        await AutonomousCoordinator._understand_words(None, content)
        stated = content.get("stated") or []
        located = [f for f in stated if f["relation"] == "part_of" and f["subject"] == "Radar Processor"]
        check("I a spreadsheet read by the substrate states its rows, with where each was read",
              had_tables == 1 and "tables" not in content and located
              and located[0]["object"] == "Sensor Suite" and located[0]["at"] == "Equipment, row 5",
              f"{len(stated)} facts; {located[:1]}")

    say("\nJ  no store touched")
    db = await EV.verify_database()
    check("J no store touched", db is None, EV.verified_database_reason)
    path = EV.write()
    # The model this run wrote, beside its record and named by it.
    path.with_suffix(".sysml").write_text(text, encoding="utf-8")
    say(f"\n{EV.passed}/{EV.passed + EV.failed} checks · {path}")
    return 0 if EV.failed == 0 else 1


def _q(name: str) -> str:
    return "'" + name.replace("\\", "\\\\").replace("'", "\\'") + "'"


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
