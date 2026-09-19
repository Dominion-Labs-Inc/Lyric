#!/usr/bin/env python3
"""The Habitat — a fully-contained world the substrate can live in, and that we
can manipulate any way we like to test it.

Design goals (set with the user):
  * 100% SAFE. Everything lives under ONE sandbox root. No path escapes it, no
    network, no arbitrary exec — only contained, fully-reversible file actions.
    The substrate's own safety_framework still evaluates each action (defense in
    depth); the guarantee here is structural: the world cannot touch anything real.
    Resettable, so any test starts clean.
  * NOT a file-mover that neglects capability. It exercises every faculty:
      - PERCEPTION : each entity has a real generated image (offline, PIL) to SEE
                     and a recognizer can categorize, plus sensor-style properties.
      - REASONING  : multi-step structure — to get what's in a sealed chest you must
                     be there, OPEN it, then TAKE the revealed item.
      - LEARNING   : affordances are real contained tools; act → observe() → induce.
      - MEMORY/DOMAINS/BELIEFS/AFFECT : entity KINDS crystallize into subjects;
                     novelty/contradiction we inject moves beliefs and feeling.
  * TWO sides:
      - AGENT side       : `observe()` + the five affordance bindings (MOVE, TAKE,
                           DROP, OPEN, INSPECT) — how the substrate reads and acts.
      - EXPERIMENTER side: spawn/remove/move/mutate/set_appearance/seal/open_loc/
                           cut_path/add_path/place_agent/tick/inject_percept/
                           snapshot/reset — how WE perturb the world to probe any
                           faculty.

`observe()` reads only what is really on disk, so runtime evidence stays
admissible: the world is never reported by the code that acted on it.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.execution.operator_binding import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact

# ── containment ────────────────────────────────────────────────────────────
HABITAT_ROOT = Path(__file__).resolve().parent / "sandbox"
ASSETS_DIRNAME = "_assets"
INVENTORY = "INVENTORY"                      # where TAKE puts things (the agent carries)
AGENT = "agent"                              # the substrate's own body, an entity

SHAPES = ("circle", "square", "triangle")
COLORS = {
    "red": (200, 40, 40), "green": (40, 170, 70),
    "blue": (50, 90, 200), "yellow": (220, 200, 40),
    "violet": (150, 60, 200), "orange": (230, 130, 30),
}
SIZES = {"small": 16, "medium": 28, "large": 40}   # drawn margin → apparent size


@dataclass
class EntitySpec:
    """What we ask the world to instantiate. `properties` are sensed immediately;
    `hidden_props` only after INSPECT. `contains` is the entity revealed by OPEN
    (makes it a container). `dynamic` names a per-tick behaviour (plant grows,
    sensor drifts)."""
    name: str
    kind: str
    shape: str = "circle"
    color: str = "red"
    size: str = "medium"
    properties: Dict[str, Any] = field(default_factory=dict)
    hidden_props: Dict[str, Any] = field(default_factory=dict)
    contains: Optional["EntitySpec"] = None
    movable: bool = True
    dynamic: Optional[str] = None            # "grow" | "drift" | None


class Habitat:
    """A contained world of locations holding entities. Pure environment — it does
    not import the substrate; the runner wires the two together."""

    def __init__(self, root: Path = HABITAT_ROOT,
                 locations: Tuple[str, ...] = ("ATRIUM", "LAB", "VAULT", "GARDEN", "WORKSHOP"),
                 paths: Tuple[Tuple[str, str], ...] = (
                     ("ATRIUM", "LAB"), ("ATRIUM", "GARDEN"),
                     ("LAB", "WORKSHOP"), ("LAB", "VAULT"))):
        self.root = Path(root)
        self.locations: List[str] = list(locations) + [INVENTORY]
        self.paths: List[Tuple[str, str]] = [tuple(p) for p in paths]
        self._time = 0
        self.reset()

    # ── safety: nothing escapes the root ────────────────────────────────────
    def _safe(self, p: Path) -> Path:
        p = Path(p).resolve()
        root = self.root.resolve()
        if root != p and root not in p.parents:
            raise ValueError(f"path escapes the habitat sandbox: {p}")
        return p

    def _loc_dir(self, loc: str) -> Path:
        if loc not in self.locations:
            raise ValueError(f"unknown location {loc!r}")
        return self._safe(self.root / loc)

    def _assets(self) -> Path:
        return self._safe(self.root / ASSETS_DIRNAME)

    def _entity_file(self, loc: str, name: str) -> Path:
        return self._safe(self._loc_dir(loc) / f"{name}.json")

    # ── lifecycle ───────────────────────────────────────────────────────────
    def reset(self) -> "Habitat":
        """Wipe and rebuild an empty habitat — a clean start for any test."""
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self._assets().mkdir(parents=True, exist_ok=True)
        (self.root / "_hidden").mkdir(parents=True, exist_ok=True)   # unrevealed container contents
        for loc in self.locations:
            (self.root / loc).mkdir(parents=True, exist_ok=True)
        self._time = 0
        return self

    def _hidden_dir(self) -> Path:
        return self._safe(self.root / "_hidden")

    # ── perceptual form (offline, deterministic) ────────────────────────────
    def _render_appearance(self, name: str, shape: str, color: str, size: str) -> Path:
        """Draw the entity as a colored shape of a given size on a plain ground — a
        REAL image the classical CV front-end reads and a recognizer can categorize.
        No external asset, no model."""
        from PIL import Image, ImageDraw
        if shape not in SHAPES:
            raise ValueError(f"unknown shape {shape!r}")
        if color not in COLORS:
            raise ValueError(f"unknown color {color!r}")
        W = H = 128
        img = Image.new("RGB", (W, H), (245, 245, 245))
        d = ImageDraw.Draw(img)
        fill = COLORS[color]
        m = SIZES.get(size, 28)
        if shape == "circle":
            d.ellipse([m, m, W - m, H - m], fill=fill)
        elif shape == "square":
            d.rectangle([m, m, W - m, H - m], fill=fill)
        else:  # triangle
            d.polygon([(W // 2, m), (m, H - m), (W - m, H - m)], fill=fill)
        out = self._assets() / f"{name}.png"
        img.save(self._safe(out))
        return out

    def _record(self, spec: EntitySpec) -> Dict[str, Any]:
        appearance = self._render_appearance(spec.name, spec.shape, spec.color, spec.size)
        rec: Dict[str, Any] = {
            "name": spec.name, "kind": spec.kind,
            "shape": spec.shape, "color": spec.color, "size": spec.size,
            "properties": dict(spec.properties),
            "hidden_props": dict(spec.hidden_props),
            "movable": bool(spec.movable),
            "inspected": False,
            "dynamic": spec.dynamic,
            "appearance": str(appearance.relative_to(self.root)),
        }
        if spec.contains is not None:
            # The content is a REAL entity file kept HIDDEN until OPEN moves it into
            # view. OPEN then uses the same move_file tool as MOVE, opened-state is
            # read back from the content's presence, and it cannot be re-revealed
            # (the hidden source is gone) — so opening never duplicates.
            content_rec = self._record(spec.contains)
            (self._hidden_dir() / f"{spec.contains.name}.json").write_text(
                json.dumps(content_rec, indent=2))
            rec["container"] = True
            rec["contains"] = spec.contains.name
        return rec

    # ── EXPERIMENTER side — manipulate the world ────────────────────────────
    def spawn(self, spec: EntitySpec, location: str) -> Path:
        """Introduce an entity into a location (novelty to perceive and make sense of)."""
        f = self._entity_file(location, spec.name)
        f.write_text(json.dumps(self._record(spec), indent=2))
        return f

    def place_agent(self, location: str) -> None:
        """Put the substrate's BODY in the world. AGENT_AT(location) follows; the
        agent can MOVE between connected locations like any movable entity."""
        for loc in self.locations:                      # the body is singular
            ef = self._loc_dir(loc) / f"{AGENT}.json"
            if ef.exists():
                ef.unlink()
        self.spawn(EntitySpec(AGENT, kind="agent", shape="triangle", color="violet",
                              movable=True), location)

    def _find(self, name: str) -> Optional[Tuple[str, Path, Dict[str, Any]]]:
        for loc in self.locations:
            f = self._loc_dir(loc) / f"{name}.json"
            if f.exists():
                return loc, f, json.loads(f.read_text())
        return None

    def remove(self, name: str) -> bool:
        found = self._find(name)
        if not found:
            return False
        self._safe(found[1]).unlink()
        return True

    def move(self, name: str, to: str) -> bool:
        found = self._find(name)
        if not found:
            return False
        found[1].rename(self._entity_file(to, name))
        return True

    def mutate(self, name: str, prop: str, value: Any, *, hidden: bool = False) -> bool:
        found = self._find(name)
        if not found:
            return False
        _loc, f, rec = found
        rec.setdefault("hidden_props" if hidden else "properties", {})[prop] = value
        f.write_text(json.dumps(rec, indent=2))
        return True

    def set_appearance(self, name: str, *, shape: Optional[str] = None,
                       color: Optional[str] = None, size: Optional[str] = None) -> bool:
        found = self._find(name)
        if not found:
            return False
        _loc, f, rec = found
        rec["shape"] = shape or rec["shape"]
        rec["color"] = color or rec["color"]
        rec["size"] = size or rec["size"]
        self._render_appearance(name, rec["shape"], rec["color"], rec["size"])
        f.write_text(json.dumps(rec, indent=2))
        return True

    def seal(self, location: str) -> None:
        (self._loc_dir(location) / ".sealed").write_text("")

    def open_loc(self, location: str) -> None:
        marker = self._loc_dir(location) / ".sealed"
        if marker.exists():
            marker.unlink()

    def cut_path(self, a: str, b: str) -> None:
        self.paths = [p for p in self.paths if set(p) != {a, b}]

    def add_path(self, a: str, b: str) -> None:
        if (a, b) not in self.paths and (b, a) not in self.paths:
            self.paths.append((a, b))

    def tick(self) -> int:
        """Advance world time — dynamic entities change on their own (a plant grows,
        a sensor drifts), so the substrate has moving state to track and predict."""
        self._time += 1
        order = ["small", "medium", "large"]
        for loc in self.locations:
            for entry in list(self._loc_dir(loc).glob("*.json")):
                rec = json.loads(entry.read_text())
                dyn = rec.get("dynamic")
                changed = False
                if dyn == "grow":
                    i = order.index(rec.get("size", "medium"))
                    if i < len(order) - 1:
                        rec["size"] = order[i + 1]; changed = True
                        self._render_appearance(rec["name"], rec["shape"], rec["color"], rec["size"])
                elif dyn == "drift":
                    base = float(rec.get("properties", {}).get("reading", 0.5))
                    rec.setdefault("properties", {})["reading"] = round(
                        base + 0.1 * math.sin(self._time), 4); changed = True
                if changed:
                    entry.write_text(json.dumps(rec, indent=2))
        return self._time

    def inject_percept(self, name: str) -> Dict[str, Any]:
        """A raw stimulus descriptor the ENVIRONMENT presents to the substrate's
        perception intake (the runner pushes it; the substrate's own loop perceives).
        Not a cognitive call."""
        found = self._find(name)
        if not found:
            raise ValueError(f"no entity {name!r} to present")
        loc, _f, rec = found
        return {
            "source": name, "location": loc, "kind": rec["kind"],
            "appearance_path": str(self._safe(self.root / rec["appearance"])),
            "properties": rec.get("properties", {}), "t": self._time,
        }

    # ── AGENT side — how the substrate reads & acts ─────────────────────────
    def observe(self) -> Optional[frozenset]:
        """Symbolic facts really on disk — None if the world is unreadable (distinct
        from empty). Containers reveal CONTAINS only when OPEN; hidden props surface
        only after INSPECT. Feeds planning / verification / operator induction."""
        if not self.root.exists():
            return None
        facts = set()
        for loc in self.locations:
            d = self.root / loc
            if not d.is_dir():
                continue
            if loc != INVENTORY:
                sealed = (d / ".sealed").exists()
                facts.add(Fact("SEALED", (loc,)) if sealed else Fact("OPEN", (loc,)))
            for entry in d.iterdir():
                if entry.suffix != ".json" or not entry.is_file():
                    continue
                rec = json.loads(entry.read_text())
                name = rec["name"]
                if name == AGENT:
                    facts.add(Fact("AGENT_AT", (loc,)))
                    continue
                if loc == INVENTORY:
                    facts.add(Fact("HOLDING", (name,)))
                else:
                    facts.add(Fact("AT", (name, loc)))
                facts.add(Fact("KIND", (name, rec["kind"])))
                if rec.get("movable"):
                    facts.add(Fact("MOVABLE", (name,)))
                if rec.get("container"):
                    facts.add(Fact("CONTAINER", (name,)))
                    content = rec.get("contains")
                    # opened iff the content has been moved into view at this location
                    revealed = bool(content) and self._entity_file(loc, content).exists()
                    facts.add(Fact("OPENED", (name,)) if revealed else Fact("CLOSED", (name,)))
                    if revealed:
                        facts.add(Fact("CONTAINS", (name, content)))
                if rec.get("inspected"):
                    facts.add(Fact("INSPECTED", (name,)))
                    for k in (rec.get("hidden_props") or {}):
                        facts.add(Fact("REVEALED", (name, k)))
        for a, b in self.paths:
            facts.add(Fact("PATH", (a, b)))
        return frozenset(facts)

    def appearance_path(self, name: str) -> Optional[str]:
        found = self._find(name)
        return str(self._safe(self.root / found[2]["appearance"])) if found else None

    def properties_of(self, name: str, *, include_hidden: bool = False) -> Optional[Dict[str, Any]]:
        found = self._find(name)
        if not found:
            return None
        rec = found[2]
        props = dict(rec.get("properties", {}))
        if include_hidden and rec.get("inspected"):
            props.update(rec.get("hidden_props", {}))
        return props

    # ── affordances (contained tools; act → observe → induce) ───────────────
    def _bindings(self) -> List[OperatorBinding]:
        obs = self.observe
        return [
            OperatorBinding(
                predicate="MOVE", tool_name="move_file",
                parameters=lambda a: {"source_path": str(self._entity_file(a[1], a[0])),
                                      "destination_path": str(self._entity_file(a[2], a[0])),
                                      "create_dirs": False},
                observe=obs, description="move an entity between connected locations"),
            OperatorBinding(
                predicate="TAKE", tool_name="move_file",
                parameters=lambda a: {"source_path": str(self._entity_file(a[1], a[0])),
                                      "destination_path": str(self._entity_file(INVENTORY, a[0])),
                                      "create_dirs": False},
                observe=obs, description="pick up an entity into the agent's inventory"),
            OperatorBinding(
                predicate="DROP", tool_name="move_file",
                parameters=lambda a: {"source_path": str(self._entity_file(INVENTORY, a[0])),
                                      "destination_path": str(self._entity_file(a[1], a[0])),
                                      "create_dirs": False},
                observe=obs, description="put a held entity down at a location"),
            OperatorBinding(
                predicate="OPEN", tool_name="move_file",
                parameters=lambda a: self._open_params(a),
                observe=obs, description="open a container, revealing the entity inside it"),
            OperatorBinding(
                predicate="INSPECT", tool_name="patch_file",
                parameters=lambda a: {"file_path": str(self._entity_file(a[1], a[0])),
                                      "old_string": '"inspected": false',
                                      "new_string": '"inspected": true'},
                observe=obs, description="inspect an entity, revealing its hidden properties"),
        ]

    def _open_params(self, args: Tuple[str, ...]) -> Dict[str, Any]:
        """OPEN(container, loc): move the hidden content entity into the location, so
        it becomes perceivable and takeable. Reads the container's own record for the
        content name — the world is never invented by the actor. One-shot: once moved,
        the hidden source is gone, so opening cannot duplicate."""
        container, loc = args[0], args[1]
        rec = json.loads(self._entity_file(loc, container).read_text())
        content = rec.get("contains")
        if not content:
            raise ValueError(f"{container!r} has nothing to reveal")
        return {"source_path": str(self._hidden_dir() / f"{content}.json"),
                "destination_path": str(self._entity_file(loc, content)),
                "create_dirs": False}

    def register(self, domain_id: str) -> "Habitat":
        reg = get_binding_registry()
        for b in self._bindings():
            reg.register(domain_id, b)
        return self

    # ── observability — the full world side of a test snapshot ──────────────
    def snapshot(self) -> Dict[str, Any]:
        """Everything true about the world right now, for assertions."""
        entities, agent_at = {}, None
        for loc in self.locations:
            for entry in self._loc_dir(loc).glob("*.json"):
                rec = json.loads(entry.read_text())
                if rec["name"] == AGENT:
                    agent_at = loc; continue
                entities[rec["name"]] = {
                    "location": loc, "kind": rec["kind"],
                    "shape": rec["shape"], "color": rec["color"], "size": rec["size"],
                    "properties": rec.get("properties", {}),
                    "open": rec.get("open"), "inspected": rec.get("inspected"),
                }
        return {"t": self._time, "agent_at": agent_at, "locations": list(self.locations),
                "paths": [list(p) for p in self.paths], "entities": entities}


__all__ = ["Habitat", "EntitySpec", "HABITAT_ROOT", "INVENTORY", "AGENT", "SHAPES", "COLORS", "SIZES"]
