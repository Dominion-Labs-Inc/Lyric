#!/usr/bin/env python3
"""SysML: a system's model, written from what its documents say.

Legacy technical data (equipment inventories, cable run sheets, interface tables, manuals) says what a system is
made of and how its parts are joined, spread over many files. `generate_sysml_model` reads them by the substrate's
own reading (`core.perception.reading`) and reader (`core.semantics.document_reader`), and writes the system they
describe as a SysML v2 textual model:

    a thing a row is about         part, typed by its kind (`part def`) where a source says what kind it is
    "Part of"                      the part is declared inside its whole
    a port column                  port of its part
    a connection's two ends        connection ... connect <end> to <end>, inside the nearest whole holding both
    "Connected to"                 connection connect <part> to <part>
    "Requires"                     dependency from <part> to <part>
    "Location"                     attribute 'Location'
    any other heading              attribute named by the heading; a number under a heading with a unit, "(m)",
                                   is a number, anything else a string

EVERY ELEMENT SAYS WHERE IT WAS READ, in a `doc` comment naming each document and the row or line it came from, so
an engineer reviewing the model can find the evidence for any part of it.

WHAT THE SOURCES DISAGREE ON IS KEPT, NOT SETTLED. An attribute two sources give different values is declared with
no value, and its doc names each value and where it was read. A part two sources put in different wholes, or in a
whole that is part of it, is declared at the top level and says why. A connection read with other than two ends is
not drawn; a comment says what was read of it.

WHAT NO SOURCE STATES IS NOT INVENTED. A part named only as a connection's end or as a whole is declared, because the
model needs it there, and its doc says it was only named. A part no source gives a kind is left untyped.

THE MODEL IS CHECKED BY THE LANGUAGE'S OWN IMPLEMENTATION before it is handed over (`validate_sysml`): the OMG SysML
v2 pilot implementation parses it, resolves every name against the standard library and checks every rule of the
language. Where that implementation or Java is not installed, the report says the model was not checked.

NO MODEL IS INVOLVED. The mapping from the substrate's link kinds to SysML is the table above.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.tools.tool_registry import (Primitive, PrimitiveProfile, PrimitiveUse, Tool, ToolCategory,
                                      ToolParameter, ToolResult)

logger = logging.getLogger(__name__)

#: Where something was read: the document, and the row or line in it.
Source = Tuple[str, str]

_INDENT = "    "
_UNIT = re.compile(r"\(([^()]+)\)\s*$")
_INTEGER = re.compile(r"^[+-]?\d+$")
_REAL = re.compile(r"^[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?$")


def _key(name: str) -> str:
    """What two spellings of one name share: case, underscores and spacing aside."""
    return " ".join(str(name).replace("_", " ").casefold().split())


def _note(entries: Dict[str, Dict[str, Any]], name: str, source: Source) -> None:
    """That `name` was read at `source`, under its own key in `entries`."""
    entry = entries.setdefault(_key(name), {"name": name, "read_in": []})
    if entry["name"].islower() and not str(name).islower():
        entry["name"] = name
    if source not in entry["read_in"]:
        entry["read_in"].append(source)


def _where(sources: Sequence[Source]) -> str:
    return "; ".join(f"{document}, {at}" for document, at in sources)


def _name(name: str) -> str:
    """A SysML unrestricted name: any words, in single quotes."""
    return "'" + str(name).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _string(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _doc(text: str) -> str:
    return "doc /* " + " ".join(str(text).replace("*/", "* /").split()) + " */"


@dataclass
class _Thing:
    """Everything the documents said of one thing a row or a fact is about."""

    name: str
    rows: List[Source] = field(default_factory=list)       # where it was what a row or fact was about
    named_in: List[Source] = field(default_factory=list)   # where it was only named
    first: Optional[int] = None                            # its place among things first read about
    kinds: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    wholes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    ports: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    ends: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    values: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # heading key -> {"name", "values": {...}}


@dataclass
class SystemReading:
    """What a set of documents says of a system, gathered by thing, each piece with where it was read."""

    things: Dict[str, _Thing] = field(default_factory=dict)
    #: port key -> (owner key, the port's own name)
    ports: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    links: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)
    needs: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)
    kinds: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    supers: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    not_modelled: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)

    def thing(self, name: str, source: Source, *, about: bool = True) -> _Thing:
        """The thing `name` names, noting that it was read at `source`: as what was read about, or only named."""
        key = _key(name)
        thing = self.things.get(key)
        if thing is None:
            thing = self.things[key] = _Thing(name=name)
        elif thing.name.islower() and not str(name).islower():
            thing.name = name
        where = thing.rows if about else thing.named_in
        if source not in where:
            where.append(source)
        if about and thing.first is None:
            thing.first = sum(1 for t in self.things.values() if t.first is not None)
        return thing

    def value(self, subject: str, heading: str, value: str, source: Source) -> None:
        held = self.thing(subject, source).values.setdefault(_key(heading), {"name": heading, "values": {}})
        _note(held["values"], value, source)

    def fact(self, fact: Dict[str, Any], document: str) -> None:
        """One fact a document states, filed under what it is about."""
        s, r, o = str(fact["subject"]), str(fact["relation"]), str(fact["object"])
        source: Source = (document, str(fact.get("at") or ""))
        # WHAT THE ROW OR LINE IS ABOUT is described there; anything else it names is only named there. A line is
        # about its fact's subject; a row about the thing it is the row of (`row`).
        about_key = _key(fact.get("row") or s)

        def thing(name: str) -> _Thing:
            return self.thing(name, source, about=_key(name) == about_key)

        if not fact.get("positive", True):
            self.not_modelled.append({**fact, "document": document, "why": "a denial is not a model element"})
            return
        if r == "instance_of":
            _note(thing(s).kinds, o, source)
            _note(self.kinds, o, source)
        elif r == "isa":
            _note(self.kinds, s, source)
            _note(self.kinds, o, source)
            _note(self.supers.setdefault(_key(s), {}), o, source)
        elif r in ("part_of", "has_part"):
            part, whole = (s, o) if r == "part_of" else (o, s)
            _note(thing(part).wholes, whole, source)
            thing(whole)
        elif r in ("has_port", "port_of"):
            owner, port = (s, o) if r == "has_port" else (o, s)
            own = str(fact.get("name") or port)
            self.ports[_key(port)] = (_key(owner), own)
            _note(thing(owner).ports, own, source)
        elif r == "has_end":
            _note(thing(s).ends, o, source)
        elif r == "connected_to":
            thing(s)
            thing(o)
            entry = self.links.setdefault(tuple(sorted((_key(s), _key(o)))), {"read_in": []})
            if source not in entry["read_in"]:
                entry["read_in"].append(source)
        elif r == "requires":
            thing(s)
            thing(o)
            entry = self.needs.setdefault((_key(s), _key(o)), {"read_in": []})
            if source not in entry["read_in"]:
                entry["read_in"].append(source)
        elif r == "located_in":
            self.value(s, "Location", o, source)
        else:
            self.not_modelled.append({**fact, "document": document,
                                      "why": f"{r} has no SysML element in this mapping"})


async def read_system(paths: Sequence[str]) -> SystemReading:
    """Read every document and gather what they say: its passages in order as one text by the one reader, each
    table row by row. A workbook's and a CSV's pages are their rows run together, so their rows are read as rows and
    never again as sentences (`document_reader.passages_of`)."""
    from core.perception.reading import read_document
    from core.semantics.derived_reader import live_view
    from core.semantics.document_reader import passages_of, passages_stated, tables_stated
    view = live_view()
    out = SystemReading()
    for path in paths:
        name = Path(path).name
        try:
            read = read_document(str(path))
        except Exception as error:
            out.documents.append({"document": name, "path": str(path), "error": str(error)})
            continue
        form = read["kind"] if read["kind"] != "text" else (Path(path).suffix.lower().lstrip(".") or "text")
        passages = passages_of(read["pages"], form, view)
        from_passages = await passages_stated(passages, document=read["sha256"])
        tables = tables_stated(read.get("tables") or [])
        for fact in from_passages + tables.facts:
            out.fact(fact, name)
        for value in tables.values:
            out.value(value["subject"], value["heading"], value["value"], (name, value["at"]))
        out.documents.append({
            "document": name, "path": str(path), "kind": form, "sha256": read["sha256"],
            "passages": len(passages), "facts_from_passages": len(from_passages),
            "tables": len(read.get("tables") or []), "rows": tables.rows,
            "facts_from_rows": len(tables.facts), "values": len(tables.values), "unread": tables.unread})
    return out


class _Writer:
    """The model text, element by element, with where each element was read."""

    def __init__(self, reading: SystemReading, system: str) -> None:
        self.r = reading
        self.system = system
        self.lines: List[str] = []
        self.sources: Dict[str, List[str]] = {}
        self.counts: Dict[str, int] = {}
        self.connection_kinds: set = set()
        self.disagreements: List[Dict[str, Any]] = []
        self.named_only: List[Dict[str, Any]] = []
        self.untyped: List[str] = []
        self.unresolved: List[Dict[str, Any]] = []
        self.declared: Dict[str, str] = {}   # element path -> "part" / "port"
        self.connections: List[Dict[str, Any]] = []

    def put(self, depth: int, text: str) -> None:
        self.lines.append(_INDENT * depth + text)

    def element(self, kind: str, path: str, sources: Sequence[Source]) -> None:
        self.sources[f"{kind}: {path}"] = [f"{d}, {a}" for d, a in sources]
        self.counts[kind] = self.counts.get(kind, 0) + 1

    # ── structure ────────────────────────────────────────────────────────────

    def _parts(self) -> Dict[str, _Thing]:
        """Every thing that is a part: whatever is not a connection (a thing with ends) or a port. A thing named only
        as a connection's end is a part the model needs, declared as only named there."""
        for connection in [t for t in self.r.things.values() if t.ends]:
            for key, end in connection.ends.items():
                if key not in self.r.ports and key not in self.r.things:
                    for source in end["read_in"]:
                        self.r.thing(end["name"], source, about=False)
        return {k: t for k, t in self.r.things.items() if not t.ends and k not in self.r.ports}

    def _whole_of(self, parts: Dict[str, _Thing]) -> Dict[str, Optional[str]]:
        """Each part's whole, where the sources agree on one and it does not hold the part inside itself."""
        whole: Dict[str, Optional[str]] = {}
        for key, part in parts.items():
            if len(part.wholes) == 1:
                (w,) = part.wholes
                whole[key] = w if w in parts and w != key else None
            else:
                whole[key] = None
                if len(part.wholes) > 1:
                    self.disagreements.append({
                        "element": part.name, "about": "Part of",
                        "values": [{"value": e["name"], "read_in": _where(e["read_in"])}
                                   for e in part.wholes.values()]})
        for key in parts:
            seen, at = [key], whole.get(key)
            while at is not None and at not in seen:
                seen.append(at)
                at = whole.get(at)
            if at is not None:
                cycle = seen[seen.index(at):]
                for k in cycle:
                    whole[k] = None
                self.disagreements.append({
                    "element": parts[key].name, "about": "Part of",
                    "values": [{"value": " is part of ".join(parts[k].name for k in cycle + [cycle[0]]),
                                "read_in": _where([s for k in cycle for e in parts[k].wholes.values()
                                                   for s in e["read_in"]])}]})
        return whole

    def _path(self, key: str, whole: Dict[str, Optional[str]]) -> List[str]:
        out = [key]
        while whole.get(out[0]) is not None:
            out.insert(0, whole[out[0]])
        return out

    def write(self) -> str:
        parts = self._parts()
        whole = self._whole_of(parts)
        connections = {k: t for k, t in self.r.things.items() if t.ends}
        children: Dict[Optional[str], List[str]] = {}
        # In the order the documents describe them; what is only named, after.
        for key in sorted(parts, key=lambda k: (parts[k].first is None, parts[k].first or 0)):
            children.setdefault(whole[key], []).append(key)

        # Where each connection is drawn: inside the nearest whole holding both its ends.
        owned: Dict[Optional[str], List[Tuple[str, str, Tuple[str, Optional[str]], Tuple[str, Optional[str]]]]] = {}
        for key, c in connections.items():
            ends = [self._end(e) for e in c.ends.values()]
            if len(ends) != 2 or any(e is None for e in ends):
                self.unresolved.append({"connection": c.name, "ends": [
                    {"end": e["name"], "read_in": _where(e["read_in"])} for e in c.ends.values()],
                    "why": (f"read with {len(c.ends)} end(s), not two" if len(c.ends) != 2
                            else "an end names nothing the documents describe")})
                continue
            owner = self._owner(ends[0][0], ends[1][0], whole)
            owned.setdefault(owner, []).append(("connection", key, ends[0], ends[1]))
        for (a, b), entry in self.r.links.items():
            if a in parts and b in parts:
                owner = self._owner(a, b, whole)
                owned.setdefault(owner, []).append(("link", f"{a}|{b}", (a, None), (b, None)))

        sources = [d["document"] for d in self.r.documents if "error" not in d]
        self.put(0, f"package {_name(self.system)} {{")
        self.put(1, _doc(f"Model written from {len(sources)} document(s): {', '.join(sources)}. "
                         f"Every element names the document and the row or line it was read from."))
        self._kinds(parts, connections)
        for key in children.get(None, []):
            self._part(key, parts, children, owned, whole, depth=1)
        for item in owned.get(None, []):
            self._connection(item, None, whole, depth=1)
        self._dependencies(parts, whole)
        for item in self.unresolved:
            text = (f"{item['connection']} is not drawn: {item['why']}. Ends read: "
                    + "; ".join(f"{e['end']} ({e['read_in']})" for e in item["ends"]) + ".")
            self.put(1, "comment /* " + " ".join(text.replace("*/", "* /").split()) + " */")
        self.put(0, "}")
        return "\n".join(self.lines) + "\n"

    def _end(self, end: Dict[str, Any]) -> Optional[Tuple[str, Optional[str]]]:
        """A connection's end as (part key, port's own name or None)."""
        key = _key(end["name"])
        if key in self.r.ports:
            owner, own = self.r.ports[key]
            return owner, own
        return (key, None) if key in self.r.things else None

    def _owner(self, a: str, b: str, whole: Dict[str, Optional[str]]) -> Optional[str]:
        """The nearest whole holding both parts and being neither, or None for the package."""
        pa, pb = self._path(a, whole)[:-1], self._path(b, whole)[:-1]
        owner = None
        for x, y in zip(pa, pb):
            if x != y:
                break
            owner = x
        return owner

    def _reference(self, end: Tuple[str, Optional[str]], owner: Optional[str],
                   whole: Dict[str, Optional[str]]) -> str:
        path = self._path(end[0], whole)
        if owner is not None:
            path = path[path.index(owner) + 1:]
        names = [_name(self.r.things[k].name) for k in path] + ([_name(end[1])] if end[1] else [])
        return ".".join(names)

    def _qualified(self, key: str, whole: Dict[str, Optional[str]]) -> str:
        return "::".join(_name(self.r.things[k].name) for k in self._path(key, whole))

    # ── elements ─────────────────────────────────────────────────────────────

    def _kinds(self, parts: Dict[str, _Thing], connections: Dict[str, _Thing]) -> None:
        of_connections = {k for c in connections.values() for k in c.kinds}
        of_parts = {k for p in parts.values() for k in p.kinds} | set(self.r.supers)
        self.connection_kinds = of_connections - of_parts
        for key, kind in self.r.kinds.items():
            word = "connection def" if key in self.connection_kinds else "part def"
            supers = self.r.supers.get(key) or {}
            special = (" :> " + ", ".join(_name(s["name"]) for s in supers.values())) if supers else ""
            self.put(1, f"{word} {_name(kind['name'])}{special} {{")
            self.put(2, _doc(f"Kind named in: {_where(kind['read_in'])}"))
            if word == "connection def":
                # A connection's kind joins two things, ports or parts, so its ends are untyped.
                self.put(2, "end 'end 1';")
                self.put(2, "end 'end 2';")
            self.put(1, "}")
            self.element(word, kind["name"], kind["read_in"])

    def _typed(self, thing: _Thing, *, connection: bool = False) -> str:
        if len(thing.kinds) == 1:
            (key, kind), = thing.kinds.items()
            if connection and key not in self.connection_kinds:
                # A kind parts are of too is a part def, which no connection can be typed by.
                self.untyped.append(thing.name)
                return ""
            return f" : {_name(kind['name'])}"
        if len(thing.kinds) > 1:
            self.disagreements.append({"element": thing.name, "about": "Type", "values": [
                {"value": k["name"], "read_in": _where(k["read_in"])} for k in thing.kinds.values()]})
        else:
            self.untyped.append(thing.name)
        return ""

    def _part(self, key: str, parts: Dict[str, _Thing], children: Dict[Optional[str], List[str]],
              owned: Dict[Optional[str], List[Any]], whole: Dict[str, Optional[str]], depth: int) -> None:
        part = parts[key]
        path = "/".join(parts[k].name for k in self._path(key, whole))
        self.declared[path] = "part"
        typed = self._typed(part)
        self.put(depth, f"part {_name(part.name)}{typed} {{")
        if part.rows:
            said = f"Read from: {_where(part.rows)}"
            self.element("part", path, part.rows)
        else:
            said = f"Named only in: {_where(part.named_in)}. No source describes it in a row of its own"
            self.element("part", path, part.named_in)
            self.named_only.append({"part": part.name, "read_in": _where(part.named_in)})
        if len(part.wholes) > 1 or (len(part.wholes) == 1 and whole.get(key) is None
                                    and next(iter(part.wholes)) in parts):
            said += ". Declared at the top level: the sources do not agree on what it is part of"
        if len(part.kinds) > 1:
            said += ". Left untyped: the sources name " + "; ".join(
                f"{k['name']} ({_where(k['read_in'])})" for k in part.kinds.values())
        self.put(depth + 1, _doc(said))
        self._attributes(part, path, depth + 1)
        for port in part.ports.values():
            self.declared[f"{path}/{port['name']}"] = "port"
            self.put(depth + 1, f"port {_name(port['name'])} {{")
            self.put(depth + 2, _doc(f"Read from: {_where(port['read_in'])}"))
            self.put(depth + 1, "}")
            self.element("port", f"{path}/{port['name']}", port["read_in"])
        for child in children.get(key, []):
            self._part(child, parts, children, owned, whole, depth + 1)
        for item in owned.get(key, []):
            self._connection(item, key, whole, depth + 1)
        self.put(depth, "}")

    def _attributes(self, thing: _Thing, path: str, depth: int) -> None:
        for held in thing.values.values():
            heading, values = held["name"], list(held["values"].values())
            unit = _UNIT.search(heading)
            if len(values) == 1:
                value = values[0]["name"]
                if unit and _INTEGER.match(value):
                    typed = f"ScalarValues::Integer = {int(value)}"
                elif unit and _REAL.match(value):
                    typed = f"ScalarValues::Real = {value}"
                else:
                    typed = f"ScalarValues::String = {_string(value)}"
                said = f"Read from: {_where(values[0]['read_in'])}"
                sources = values[0]["read_in"]
            else:
                typed = "ScalarValues::String"
                said = ("The sources disagree, so no value is chosen: " + "; ".join(
                    f"{_string(v['name'])} in {_where(v['read_in'])}" for v in values))
                sources = [s for v in values for s in v["read_in"]]
                self.disagreements.append({"element": thing.name, "about": heading, "values": [
                    {"value": v["name"], "read_in": _where(v["read_in"])} for v in values]})
            self.put(depth, f"attribute {_name(heading)} : {typed} {{")
            self.put(depth + 1, _doc(said))
            self.put(depth, "}")
            self.element("attribute", f"{path}/{heading}", sources)

    def _connection(self, item, owner: Optional[str], whole: Dict[str, Optional[str]], depth: int) -> None:
        what, key, a, b = item
        ra, rb = self._reference(a, owner, whole), self._reference(b, owner, whole)
        if what == "connection":
            c = self.r.things[key]
            typed = self._typed(c, connection=True)
            self.put(depth, f"connection {_name(c.name)}{typed} connect {ra} to {rb} {{")
            self.put(depth + 1, _doc(f"Read from: {_where(c.rows)}"))
            self._attributes(c, c.name, depth + 1)
            self.put(depth, "}")
            self.element("connection", c.name, c.rows)
            label, sources = c.name, c.rows
        else:
            entry = self.r.links[tuple(key.split("|"))]
            self.put(depth, f"connection connect {ra} to {rb} {{")
            self.put(depth + 1, _doc(f"Read from: {_where(entry['read_in'])}"))
            self.put(depth, "}")
            label = f"{self.r.things[a[0]].name} to {self.r.things[b[0]].name}"
            self.element("connection", label, entry["read_in"])
            sources = entry["read_in"]
        self.connections.append({"connection": label, "ends": [
            "/".join(self.r.things[k].name for k in self._path(e[0], whole)) + (f"/{e[1]}" if e[1] else "")
            for e in (a, b)], "read_in": _where(sources)})

    def _dependencies(self, parts: Dict[str, _Thing], whole: Dict[str, Optional[str]]) -> None:
        for (a, b), entry in self.r.needs.items():
            if a not in parts or b not in parts:
                continue
            self.put(1, f"dependency from {self._qualified(a, whole)} to {self._qualified(b, whole)} {{")
            self.put(2, _doc(f"Read from: {_where(entry['read_in'])}"))
            self.put(1, "}")
            self.element("dependency", f"{parts[a].name} to {parts[b].name}", entry["read_in"])


def write_sysml(reading: SystemReading, system: str) -> Tuple[str, Dict[str, Any]]:
    """The SysML v2 text of the system the reading describes, and a report: every element with where it was read,
    what the sources disagree on, what was only named, what is untyped or not drawn, and the checks the model
    passed before it was written."""
    writer = _Writer(reading, system)
    text = writer.write()
    ends_resolve = all(end in writer.declared for c in writer.connections for end in c["ends"])
    report = {
        "elements": dict(writer.counts),
        "sources": writer.sources,
        "connections": writer.connections,
        "disagreements": writer.disagreements,
        "named_only": writer.named_only,
        "untyped": writer.untyped,
        "not_drawn": writer.unresolved,
        "not_modelled": reading.not_modelled,
        "checks": {
            "every_element_read_in": all(writer.sources.values()),
            "connection_ends_declared": ends_resolve,
        },
    }
    return text, report


#: The OMG SysML v2 pilot implementation, unpacked from its Jupyter kernel release: its jar and standard library
#: (`third_party/sysml-v2-pilot/SOURCE.txt`), run on Java 21.
PILOT_DIR = Path(os.environ.get("SYSML_PILOT_DIR")
                 or Path(__file__).resolve().parents[2] / "third_party" / "sysml-v2-pilot")
JAVA = os.environ.get("LYRIC_JAVA") or "/opt/homebrew/opt/openjdk@21/bin/java"
_VALIDATOR = Path(__file__).with_name("SysMLValidate.java")


async def validate_sysml(text: str) -> Dict[str, Any]:
    """The model checked by the OMG's own SysML v2 implementation: parsed, every name resolved against the standard
    library, every rule of the language checked. `valid` only when it found no syntax and no semantic error. Where
    Java or the implementation is not installed, `validated` is False and `why` says which: a model not checked is
    said to be not checked."""
    library = PILOT_DIR / "sysml.library"
    jars = sorted(PILOT_DIR.glob("*.jar"))
    if not Path(JAVA).exists():
        return {"validated": False, "why": f"no Java runtime at {JAVA}"}
    if not jars or not library.is_dir():
        return {"validated": False, "why": f"the SysML v2 pilot implementation is not installed at {PILOT_DIR}"}
    with tempfile.TemporaryDirectory() as folder:
        model = Path(folder) / "model.sysml"
        model.write_text(text, encoding="utf-8")
        process = await asyncio.create_subprocess_exec(
            JAVA, "-cp", f"{PILOT_DIR}/*", str(_VALIDATOR), f"{library.resolve()}/", str(model),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await process.communicate()
    issues: List[Dict[str, Any]] = []
    counts: Optional[List[int]] = None
    exception = None
    for line in out.decode("utf-8", errors="replace").splitlines():
        fields = line.split("\t")
        if fields[0] == "ISSUE" and len(fields) >= 4:
            issues.append({"kind": fields[1], "line": int(fields[2]) if fields[2].isdigit() else None,
                           "message": fields[3]})
        elif fields[0] == "COUNTS" and len(fields) == 4:
            counts = [int(n) for n in fields[1:]]
        elif fields[0] == "EXCEPTION":
            exception = "\t".join(fields[1:])
    if counts is None:
        tail = err.decode("utf-8", errors="replace").strip().splitlines()[-5:]
        return {"validated": False, "why": "the implementation did not finish: " + " ".join(tail)}
    syntax, semantic, warnings = counts
    return {"validated": True, "implementation": jars[0].name, "valid": syntax == 0 and semantic == 0,
            "syntax_errors": syntax, "semantic_errors": semantic, "warnings": warnings,
            "issues": issues, **({"exception": exception} if exception else {})}


class GenerateSysMLModelTool(Tool):
    """A system's SysML v2 model, written from what its documents say, with where each element was read."""

    def __init__(self):
        super().__init__()
        self.name = "generate_sysml_model"
        self.description = ("Read a system's technical documents (equipment and software inventories, cable run "
                            "sheets, interface tables, manuals: PDF, Word, Excel, CSV, text) and write the system "
                            "they describe as a SysML v2 textual model. Every element names the document and row "
                            "or line it was read from; where sources disagree, both are kept and no value is chosen.")
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(name="documents", type="array",
                          description="Paths of the documents that describe the system", required=True),
            ToolParameter(name="system", type="string",
                          description="The system's name, used as the model's package name", required=False),
            ToolParameter(name="output_path", type="string",
                          description="Where to write the .sysml file; the model is returned either way",
                          required=False),
        ]
        self.primitive_profile = PrimitiveProfile(
            tool_name="generate_sysml_model",
            primitives=[
                PrimitiveUse(primitive=Primitive.READ_DATA,
                             description="Read the documents that describe a system",
                             input_types=["document"], output_types=["text", "table"]),
                PrimitiveUse(primitive=Primitive.GENERATE_SYSTEM_MODEL,
                             description="Write the system the documents describe as a SysML v2 model",
                             input_types=["document"], output_types=["sysml"]),
            ])

    async def execute(self, **kwargs) -> ToolResult:
        documents = kwargs.get("documents") or []
        if isinstance(documents, str):
            documents = [documents]
        documents = [str(d) for d in documents if str(d).strip()]
        if not documents:
            return ToolResult(success=False, output=None,
                              error="no documents: name the files that describe the system")
        system = str(kwargs.get("system") or "").strip() or "System"
        reading = await read_system(documents)
        if not any("error" not in d for d in reading.documents):
            return ToolResult(success=False, output={"documents": reading.documents},
                              error="none of the documents could be read")
        text, report = write_sysml(reading, system)
        report["validation"] = await validate_sysml(text)
        written = None
        if kwargs.get("output_path"):
            target = Path(str(kwargs["output_path"])).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            written = str(target)
        return ToolResult(success=True, output={
            "sysml": text, "path": written, "system": system, "documents": reading.documents,
            # WHAT A TASK OPENS, THE SUBSTRATE READS (`_read_what_was_opened`).
            "opened": [d["path"] for d in reading.documents if "error" not in d],
            **report})


__all__ = ["GenerateSysMLModelTool", "SystemReading", "read_system", "write_sysml", "validate_sysml"]
