# SYSML-01: a system's SysML v2 model, written from its legacy documents

`generate_sysml_model` (`core/tools/sysml_tools.py`) reads a system's technical documents and writes the system they
describe as a SysML v2 textual model. Every element names the document and row or line it was read from. Where
sources disagree, both are kept and no value is chosen. The OMG's own SysML v2 implementation checks every model
before it is handed over.

**First run (`20261014T130401Z`, 13/13).** The set is four documents for a fictional patrol vessel mission system:
- an equipment inventory (xlsx);
- a software inventory (csv);
- a cable run sheet (csv);
- an interface control document (docx: three paragraphs and a table).

The model has 82 elements: 8 part defs, 3 connection defs, 11 parts, 15 ports, 32 attributes, 9 connections and 4
dependencies. The OMG SysML v2 pilot implementation (release 2026-08, kernel jar 0.62.0) finds no syntax error, no
semantic error and no warning in it. Every name resolves against the standard library, including nested port
references such as `'Sensor Suite'.'Radar Processor'.'J7'`. The model is saved beside the record as
`results/20261014T130401Z.sysml`.

What the set tests on purpose:
- **A disagreement.** The Mission Computer's part number is MC-410 in the equipment inventory and MC-411 in the
  software inventory. The model declares that attribute with no value, and its doc names both values and the row
  each was read from.
- **A part no inventory lists.** Navigation Radar is named only as the end of cable W107. It is declared as only
  named there, and left untyped.
- **A cable with one end.** W108 is not drawn; a comment in the model says what was read of it.

**What it does not show.**
- **Prose.** The document's three paragraphs go to the substrate's one reader. This run has no memory up, so the
  reader has none of the English the substrate was taught, and it states nothing of them
  (`facts_from_prose_lines` 0). That is the run's setup, not the reader's limit. A read-only probe on main, with
  the taught English loaded (76,884 words, 3 minutes to load), read 4 of 7 manual sentences. "A radar is a
  device." was stated as `radar isa device`. "The radar processor is connected to the mission computer.", "The
  console is connected to the switch." and "The mission computer requires power." read, but stated nothing: what
  drops them between reading and stating is not yet found.
- **The hand-over to the substrate's own reading.** A task's tool names the files it opened in `opened`, for the
  substrate's own reading (`_read_what_was_opened`). That needs a running substrate and is not exercised.
- **PDF tables.** A PDF's text is read; its tables are not read as tables.

**Before this run, in the scratchpad,** the pilot implementation found three errors in the first model: a
`connection def` must declare its two ends. Each cable kind is now written with two untyped ends, since a cable may
join ports or whole parts.

| | |
|---|---|
| A | Every table (one sheet, two CSV files, one Word table) is read row by row under its headings, with nothing left unread. |
| B | All ten inventoried parts are declared, typed by their kind, and nested in the whole their "Part of" names. |
| C | All seven two-ended cables and both interfaces are drawn between the parts and ports their rows name, inside the nearest whole holding both ends. Every end is a declared part or port. |
| D | Every element names the document and row it was read from. |
| E | The part number disagreement is kept with both sources, and no value is chosen. |
| F | Navigation Radar is declared as only named and is untyped. W108 is not drawn, and the model says so. |
| G | The OMG SysML v2 pilot implementation accepts the model: 0 syntax errors, 0 semantic errors, 0 warnings. |
| H | The same documents give the same model, byte for byte. |
| I | The substrate's own reading of a spreadsheet (`_understand_words`) states its rows, each with where it was read ("Equipment, row 5"), and lets the rows go once read. |
| J | No store is touched. |

**The trap in measuring G.** The implementation's `loadLibrary` needs an absolute library path. Given a relative
one, it reads the library through file URIs that keep the spaces in its folder names escaped
(`Kernel%20Libraries`), and loads nothing. A validator with no library rejects every model, valid or not: each
reference to `ScalarValues` fails to resolve and every part "must specialize Parts::Part". `SysMLValidate.java`
takes the absolute path, and the tool passes one.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/SYSML-01/experiment.py
```

It needs:
- **Java 21** at `/opt/homebrew/opt/openjdk@21/bin/java` (`brew install openjdk@21`);
- **The pilot implementation** in `third_party/sysml-v2-pilot`. `SOURCE.txt` there says where it came from.

`LYRIC_JAVA` and `SYSML_PILOT_DIR` override both. Without them the tool still writes the model, and reports it as
not validated, saying why; G then fails.
