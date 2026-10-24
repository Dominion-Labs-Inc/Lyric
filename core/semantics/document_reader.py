#!/usr/bin/env python3
"""What a document states: its passages, read in order as one text by the substrate's one reader, and its tables,
row by row.

Reading (`core.perception.reading`) measures a file: its pages, and its tables as rows under their headings. What
they SAY is told here, by one owner, for every caller: the substrate taking in a document it met (the coordinator's
`_understand_words`), and a tool that works from documents it is given (`generate_sysml_model`).

A TEXT IS READ AS A TELLING IS HEARD. Its passages (`passages_of`), what its writer wrote as one run and never a
printed line, are read in order by a conversation of the text's own (`Conversation.stated`), through the one reader
(`derived_reader`), which reads only the English the substrate has been taught. With no memory up in the process
nothing is taught, so nothing is stated: that is the true answer, not an empty document.

A ROW IS ONE THING, AND ITS HEADINGS SAY WHAT EACH CELL IS TO IT (`relation_types.classify_heading`):
- the row is about the thing in its name column: the column headed as a name, else the first;
- a cell under a heading that names a kind the substrate reasons with is a fact: "Part of" says what the row's
  thing is part of, "Type" what it is an instance of, "Location" where it is;
- an end column ("From", "To") says what the row's connection joins, and a port column ("From port") which port
  of that end it joins through, paired with its end by the rest of its heading. A port column with no end column
  names a port of the row's own thing;
- a cell under any other heading is a VALUE the table states (a part number, a length), kept with its heading.
  It is never made a link: nothing tells the substrate what a "Part number" is to a console.

Every fact and value says where it was read (`at`): the passage, or the table and row.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.semantics.relation_types import SemanticRelation, classify_heading

#: Where a passage stands, by what a document's pages are: a PDF's pages hold lines, a Word file's "pages" are its
#: paragraphs (`reading.read_document`), and a text is one page of lines.
_PAGE_WORD = {"pdf": "page", "docx": "paragraph"}

#: What a workbook's or a CSV's pages are: its rows run together. Its rows are read as rows (`tables_stated`),
#: never as sentences too, or each row would be read twice and once as a run-on of every cell.
_ROWS_ONLY = frozenset({"xlsx", "csv"})

#: Formats each of whose lines is an entry of its own, a record or a key and its value: their lines are never joined.
_LINE_BY_LINE = frozenset({"json", "log", "yaml", "yml"})

#: The Latin ligatures a PDF's text is often written in ("ﬁ", "ﬂ"): one character standing for two or three letters.
_LIGATURES = re.compile("[ﬀ-ﬆ]")

_LETTERS_AT_END = re.compile(r"[^\W\d_]+$")
_LETTERS_AT_START = re.compile(r"^[^\W\d_]+")


def passages_of(pages: Sequence[str], kind: Optional[str] = None, view=None) -> List[Tuple[str, str]]:
    """A document's passages, each with where it stands: `(passage, at)`. None for a document whose pages are its rows.

    A PASSAGE IS WHAT ITS WRITER WROTE AS ONE RUN, NOT A PRINTED LINE. A page breaks a sentence wherever its line is
    full; a writer ends a run with a blank line, a heading, an item, a paragraph's last line. Read a printed line at a
    time, every sentence the page broke was two pieces, neither of which read ("Collectives of actively-moving
    particles can spontaneously separate into dilute and dense" and "phases"). So a printed line goes on into the
    next where the page broke it (`_goes_on`), and a passage's sentences are found where the reader finds them, where
    what it was taught ends (`derived_reader.read_text`). A Word file's paragraphs are passages already; a format
    whose every line is an entry of its own keeps each line.

    A word the page split with a hyphen is one word where the substrate holds it ("collec-" and "tive" are
    "collective"), and stays two joined by their hyphen where it does not ("self-" and "propelled"): `view`, what the
    substrate was taught, says which. A ligature is the letters it stands for. Both are the writing, not the
    language."""
    if kind in _ROWS_ONLY:
        return []
    out: List[Tuple[str, str]] = []
    word = _PAGE_WORD.get(kind or "")
    for page_number, page in enumerate(pages, 1):
        lines = [" ".join(_LIGATURES.sub(lambda m: unicodedata.normalize("NFKC", m.group()), line).split())
                 for line in str(page).splitlines()]
        run: List[int] = []
        for at, line in enumerate(lines):
            if not line:
                continue
            run.append(at)
            following = lines[at + 1] if at + 1 < len(lines) else ""
            if following and (kind == "docx" or (kind not in _LINE_BY_LINE
                                                 and _goes_on(line, following, lines[at - 1] if at else ""))):
                continue
            first, last = run[0] + 1, run[-1] + 1
            lines_said = f"line {first}" if first == last else f"lines {first} to {last}"
            if word is None:
                where = lines_said
            elif kind == "docx":
                where = f"paragraph {page_number}"
            else:
                where = f"{word} {page_number}, {lines_said}"
            out.append((_joined([lines[k] for k in run], view), where))
            run = []
    return out


def _split_word(line: str, following: str) -> bool:
    """Whether a printed line ends in a word the page split with a hyphen, the rest of it beginning the next."""
    return line[-1:] == "-" and line[-2:-1].isalpha() and following[:1].isalpha()


def _goes_on(line: str, following: str, before: str) -> bool:
    """Whether the page broke a printed line, not its writer, so the next line goes on with what it says: a word split
    across them, the next going on in lower case, or the next line's first word too long to have fit on this one in
    the width the lines about it run to. A line stopping short of that width was ended there: a heading, an item, a
    paragraph's last line. Measured against its neighbours, since one page holds more than one width: an abstract
    across the page, two columns below it. Measured in letters, which a page's type does not set at one width each,
    so a line as long as the width with the word is taken to be full: "...the comprehension and security of" stopped
    one letter short of the line before it, and "AI models." was cut from its sentence."""
    if _split_word(line, following) or following[:1].islower():
        return True
    return len(line) + 1 + len(following.split(" ", 1)[0]) >= max(len(before), len(following))


def _joined(lines: Sequence[str], view) -> str:
    """Printed lines as the one run they were written as: a word the page split is put back together (`passages_of`),
    and the rest joined by a space."""
    text = lines[0]
    for line in lines[1:]:
        if not _split_word(text, line):
            text = f"{text} {line}"
            continue
        head, tail = _LETTERS_AT_END.search(text[:-1]), _LETTERS_AT_START.match(line)
        whole = (head.group() if head else "") + (tail.group() if tail else "")
        one_word = view is not None and (view.knows(whole) or bool(view.names_of_shape(whole)))
        text = (text[:-1] if one_word else text) + line
    return text


async def passages_stated(passages: Sequence[Tuple[str, str]], *, document: str) -> List[Dict[str, Any]]:
    """Each fact the passages state between named things, read in order as ONE text, kept with the sentence it was
    read from (`said`) and where its passage stands (`at`).

    A TEXT IS READ AS A LISTENER FOLLOWS ONE, by a conversation of its own (`Conversation.stated`): "the dog" is the
    dog it told of before, "it" and "they" what it last spoke of, and each happening it tells of is named, as this
    text's and no other's (`document`, what the text is known by). Read a line at a time with nothing before each,
    every happening was an unknown, a fact about an unknown has nothing to name it, and a story stated almost nothing.

    THE SUBSTRATE READS WHILE IT THINKS. The reader runs in its loop, about 2 ms a word measured, so a long document
    yields between passages: a question asked while it reads is not held behind the last page."""
    from core.agents.autonomous.shared_types import TaskSource
    from core.semantics.conversation import Conversation
    reading = Conversation(session=f"reading:{document}", source=TaskSource.SYSTEM, remembers=False,
                           within=document)
    found: List[Dict[str, Any]] = []
    for passage, at in passages:
        if not passage.strip():
            continue
        await asyncio.sleep(0)
        for fact, said in await reading.stated(passage):
            found.append({"subject": str(fact.subject), "relation": str(fact.relation),
                          "object": str(fact.obj), "positive": bool(fact.positive),
                          "said": said[:300], "at": at})
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


__all__ = ["passages_of", "passages_stated", "tables_stated", "TablesRead", "port_term"]
