#!/usr/bin/env python3
"""What a document states: its lines, read by the substrate's one reader, and its tables, row by row.

Reading (`core.perception.reading`) measures a file: its pages, and its tables as rows under their headings. What
they SAY is told here, by one owner, for every caller: the substrate taking in a document it met (the coordinator's
`_understand_words`), and a tool that works from documents it is given (`generate_sysml_model`).

A LINE IS READ AS A SENTENCE IS. Each goes to the one reader (`derived_reader.heard_stated`), which reads only the
English the substrate has been taught. With no memory up in the process nothing is taught, so nothing is stated:
that is the true answer, not an empty document.

A ROW IS ONE THING, AND ITS HEADINGS SAY WHAT EACH CELL IS TO IT (`relation_types.classify_heading`):
- the row is about the thing in its name column: the column headed as a name, else the first;
- a cell under a heading that names a kind the substrate reasons with is a fact: "Part of" says what the row's
  thing is part of, "Type" what it is an instance of, "Location" where it is;
- an end column ("From", "To") says what the row's connection joins, and a port column ("From port") which port
  of that end it joins through, paired with its end by the rest of its heading. A port column with no end column
  names a port of the row's own thing;
- a cell under any other heading is a VALUE the table states (a part number, a length), kept with its heading.
  It is never made a link: nothing tells the substrate what a "Part number" is to a console.

Every fact and value says where it was read (`at`): the line, or the table and row.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.semantics.relation_types import SemanticRelation, classify_heading

#: Where a line stands, by what a document's pages are: a PDF's pages hold lines, a Word file's "pages" are its
#: paragraphs (`reading.read_document`), and a text is one page of lines.
_PAGE_WORD = {"pdf": "page", "docx": "paragraph"}

#: What a workbook's or a CSV's pages are: its rows run together. Its rows are read as rows (`tables_stated`),
#: never as sentences too, or each row would be read twice and once as a run-on of every cell.
_ROWS_ONLY = frozenset({"xlsx", "csv"})


def lines_of(pages: Sequence[str], kind: Optional[str] = None) -> List[Tuple[str, str]]:
    """A document's lines, each with where it stands: `(line, at)`. None for a document whose pages are its rows."""
    if kind in _ROWS_ONLY:
        return []
    out: List[Tuple[str, str]] = []
    word = _PAGE_WORD.get(kind or "")
    for page_number, page in enumerate(pages, 1):
        for line_number, line in enumerate(str(page).splitlines(), 1):
            if word is None:
                at = f"line {line_number}"
            elif kind == "docx":
                at = f"paragraph {page_number}"
            else:
                at = f"{word} {page_number}, line {line_number}"
            out.append((line, at))
    return out


async def lines_stated(lines: Sequence[Tuple[str, str]], view) -> List[Dict[str, Any]]:
    """Each fact the lines state between named things, as the one reader reads them, kept with the line it was read
    from (`said`) and where that line stands (`at`).

    THE SUBSTRATE READS WHILE IT THINKS. The reader runs in its loop, about 2 ms a word measured, so a long document
    yields between lines: a question asked while it reads is not held behind the last page."""
    from core.semantics.derived_reader import heard_stated
    found: List[Dict[str, Any]] = []
    for line, at in lines:
        line = " ".join(str(line).split())
        if not line:
            continue
        await asyncio.sleep(0)
        for fact in await heard_stated(line, view):
            found.append({"subject": str(fact.subject), "relation": str(fact.relation),
                          "object": str(fact.obj), "positive": bool(fact.positive),
                          "said": line[:300], "at": at})
    return found


@dataclass
class TablesRead:
    """What tables state: `facts` in the link kinds the substrate reasons with, `values` a table states of a thing
    under a heading, and `unread`, each row or cell nothing could be read from, with why."""

    facts: List[Dict[str, Any]] = field(default_factory=list)
    values: List[Dict[str, Any]] = field(default_factory=list)
    unread: List[Dict[str, str]] = field(default_factory=list)
    rows: int = 0


def port_term(owner: str, port: str) -> str:
    """The name a port is held by: its owner's, since two consoles' "J3" are two ports."""
    return f"{owner} port {port}"


def _words(heading: str) -> str:
    return " ".join(str(heading).replace("_", " ").lower().split())


def tables_stated(tables: Sequence[Dict[str, Any]]) -> TablesRead:
    """Every fact and value the tables state, each with the row it was read from (`said`) and where (`at`)."""
    out = TablesRead()
    for table in tables:
        _table_stated(table, out)
    return out


def _table_stated(table: Dict[str, Any], out: TablesRead) -> None:
    headings = [str(h) for h in table.get("headings") or []]
    kinds = [classify_heading(h).relation for h in headings]
    name_column = kinds.index(SemanticRelation.NAMED) if SemanticRelation.NAMED in kinds else 0
    ends = [i for i, kind in enumerate(kinds) if kind is SemanticRelation.HAS_END]
    # A PORT COLUMN BELONGS TO THE END ITS OTHER WORDS NAME: "From port" to "From".
    port_of_end: Dict[int, int] = {}
    own_ports: List[int] = []
    for i, kind in enumerate(kinds):
        if kind is not SemanticRelation.HAS_PORT or i == name_column:
            continue
        lead = " ".join(_words(headings[i]).split()[:-1])
        end = next((e for e in ends if _words(headings[e]) == lead), None)
        if end is not None:
            port_of_end[end] = i
        elif not ends:
            own_ports.append(i)
        else:
            out.unread.append({"at": str(table.get("name")), "why":
                               f"the port column {headings[i]!r} names no end column of its own"})
    paired = set(port_of_end.values())

    for row in table.get("rows") or []:
        cells = [str(c) for c in row.get("cells") or []]
        at = f"{table['name']}, row {row.get('row')}" if table.get("name") else f"row {row.get('row')}"
        said = " | ".join(c for c in cells if c)[:300]
        out.rows += 1
        subject = cells[name_column] if name_column < len(cells) else ""
        if not subject:
            out.unread.append({"at": at, "why": f"no {headings[name_column]!r} names what the row is about"})
            continue

        def fact(s: str, relation: SemanticRelation, o: str, **more: str) -> None:
            # `row`: what the row is about. A cable's row says its end has a port, and is still the cable's row,
            # not a row describing the end.
            out.facts.append({"subject": s, "relation": relation.value, "object": o, "positive": True,
                              "said": said, "at": at, "row": subject, **more})

        for i, cell in enumerate(cells):
            if i == name_column or not cell or i in paired:
                continue
            if i >= len(headings):
                out.unread.append({"at": at, "why": f"the cell {cell!r} is under no heading"})
                continue
            kind = kinds[i]
            if kind is SemanticRelation.HAS_END:
                port_column = port_of_end.get(i)
                port = cells[port_column] if port_column is not None and port_column < len(cells) else ""
                if port:
                    fact(cell, SemanticRelation.HAS_PORT, port_term(cell, port), name=port)
                    fact(subject, SemanticRelation.HAS_END, port_term(cell, port))
                else:
                    fact(subject, SemanticRelation.HAS_END, cell)
            elif kind is SemanticRelation.HAS_PORT:
                for port in (p.strip() for p in cell.split(";")):
                    if port:
                        fact(subject, SemanticRelation.HAS_PORT, port_term(subject, port), name=port)
            elif kind in (SemanticRelation.RELATED_TO, SemanticRelation.NAMED):
                out.values.append({"subject": subject, "heading": headings[i], "value": cell,
                                   "said": said, "at": at})
            else:
                for each in (v.strip() for v in cell.split(";")):
                    if each:
                        fact(subject, kind, each)


__all__ = ["lines_of", "lines_stated", "tables_stated", "TablesRead", "port_term"]
