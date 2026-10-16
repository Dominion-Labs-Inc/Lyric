"""A person's connectors: connecting one, signing in to it, and calling its tools for them.

A connection belongs to whoever made it (a person, or the substrate itself): the connector's address and name, the
person's token for it, and the tools it had when Lyric last read them. Those tools are registered as tools like any
other (`register_connected`), named `<connector>__<tool>`, each with the connector's own description of it, which
Lyric reads. A connector tool acts for whoever's work the act is (`get_acting_actor`), with that person's own
connection, never anyone else's.

Lyric registers itself with a connector's sign-in server once, for everyone (`connector_clients`); each person
signs in for themselves (`connector_connections`). Both are kept in runtime beside the reward allowances: a
connection is a setting of the person's, not something they told Lyric, so it is not their context. A token is a
key: it is never said back, logged, or put in a result.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from core.connectors import sign_in
from core.connectors.protocol import TIMEOUT, ConnectorError, SignInNeeded, session
from core.tools.tool_registry import (Primitive, PrimitiveProfile, PrimitiveUse, Tool, ToolCategory,
                                      ToolResult, ToolSafety)

logger = logging.getLogger(__name__)

#: Where a connector's sign-in sends the person back to: the platform's page that hands Lyric what came back.
REDIRECT = os.environ.get("LYRIC_CONNECTOR_REDIRECT", "https://lyricai.dmnlabs.org/connectors/callback")

#: A token this close to running out is refreshed before it is used, in seconds.
EARLY = 60

DDL = [
    """CREATE TABLE IF NOT EXISTS unified.connector_clients (
           url            TEXT PRIMARY KEY,
           sign_in        JSONB NOT NULL,
           client         JSONB NOT NULL,
           registered_at  TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS unified.connector_connections (
           owner         TEXT NOT NULL,
           url           TEXT NOT NULL,
           name          TEXT NOT NULL,
           status        TEXT NOT NULL,
           pending       JSONB,
           tokens        JSONB,
           tools         JSONB NOT NULL DEFAULT '[]'::jsonb,
           server        JSONB,
           connected_at  TIMESTAMPTZ,
           updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
           PRIMARY KEY (owner, url))""",
]

#: The words in a connector's address that name no service.
_NOT_NAMES = {"mcp", "api", "www", "app", "server", "remote", "connect"}


def name_of(url: str) -> str:
    """A connector's name from its address, when nothing better is known: mcp.linear.app is Linear."""
    labels = [label for label in urlsplit(url).hostname.split(".")[:-1] if label not in _NOT_NAMES]
    return (labels[-1] if labels else urlsplit(url).hostname).capitalize()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "connector"


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _address(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise ConnectorError(f"a connector's address is an https address: {url!r} is not")
    return url.strip()


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)


class Connectors:
    """Every person's connections, and calls made through them."""

    def __init__(self, db=None):
        self._db = db

    async def _store(self):
        if self._db is None:
            from core.database import get_database_manager
            self._db = get_database_manager()
        await self._db.ensure_schema("connectors", DDL, store="runtime")
        return self._db

    # ── connecting ───────────────────────────────────────────────────────────

    async def connect(self, owner: str, url: str, name: Optional[str] = None,
                      token: Optional[str] = None) -> Dict[str, Any]:
        """Connect `owner` to the connector at `url`. A connector that needs no sign-in is connected at once,
        with its tools. One that does answers with the link the person signs in at (`sign_in`); `finish`
        completes it with what the sign-in sends back.

        `token` is an access token the person made with the service for Lyric (Home Assistant's long-lived
        access tokens are these): Lyric connects with it and keeps it as theirs. It cannot be refreshed; when
        the service stops taking it, the person makes a new one."""
        url = _address(url)
        db = await self._store()
        if token:
            try:
                tools, server = await self._read(url, token)
            except SignInNeeded:
                raise ConnectorError(f"{name or name_of(url)} did not take that token")
            name = name or server.get("title") or server.get("name") or name_of(url)
            await self._keep(owner, url, name, {"access_token": token, "refresh_token": None, "expires_at": None},
                             tools, server)
            return {"name": name, "url": url, "connected": True, "tools": [tool["name"] for tool in tools]}
        try:
            tools, server = await self._read(url, None)
        except SignInNeeded as needed:
            given, client = await self._client(url, needed)
            link, verifier, state = sign_in.begin(given, client)
            name = name or name_of(url)
            await db.execute_query(
                "INSERT INTO unified.connector_connections (owner, url, name, status, pending) "
                "VALUES ($1, $2, $3, 'signing_in', $4::jsonb) "
                "ON CONFLICT (owner, url) DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status, "
                "pending = EXCLUDED.pending, updated_at = now()",
                (owner, url, name, json.dumps({"state": state, "verifier": verifier})), store="runtime")
            return {"name": name, "url": url, "sign_in": link}
        name = name or server.get("title") or server.get("name") or name_of(url)
        await self._keep(owner, url, name, None, tools, server)
        return {"name": name, "url": url, "connected": True, "tools": [tool["name"] for tool in tools]}

    async def finish(self, owner: str, state: str, code: str) -> Dict[str, Any]:
        """Complete a sign-in `owner` started, with the code and state the sign-in sent back."""
        db = await self._store()
        row = await db.execute_query(
            "SELECT url, name, pending FROM unified.connector_connections "
            "WHERE owner = $1 AND status = 'signing_in' AND pending->>'state' = $2",
            (owner, state), fetch_one=True, store="runtime")
        if not row:
            raise ConnectorError("no sign-in of this person's is waiting for that")
        url, pending = row["url"], _json(row["pending"])
        given, client = await self._registered(url)
        async with _http() as http:
            tokens = await sign_in.exchange(http, given, client, code, pending["verifier"])
        tools, server = await self._read(url, tokens["access_token"])
        await self._keep(owner, url, row["name"], tokens, tools, server)
        return {"name": row["name"], "url": url, "connected": True, "tools": [tool["name"] for tool in tools]}

    async def connections(self, owner: str) -> List[Dict[str, Any]]:
        """`owner`'s connections: each connector's name, address, where it stands, and its tools."""
        db = await self._store()
        rows = await db.execute_query(
            "SELECT name, url, status, tools, connected_at FROM unified.connector_connections "
            "WHERE owner = $1 ORDER BY name", (owner,), fetch_all=True, store="runtime") or []
        return [{"name": row["name"], "url": row["url"], "status": row["status"],
                 "tools": [tool["name"] for tool in _json(row["tools"]) or []],
                 "connected_at": row["connected_at"].isoformat() if row["connected_at"] else None}
                for row in rows]

    async def disconnect(self, owner: str, url: str) -> bool:
        """Remove `owner`'s connection to the connector at `url`, and their token with it."""
        db = await self._store()
        removed = await db.execute_query(
            "DELETE FROM unified.connector_connections WHERE owner = $1 AND url = $2 RETURNING url",
            (owner, url), fetch_one=True, store="runtime")
        return bool(removed)

    # ── calling ──────────────────────────────────────────────────────────────

    async def call(self, owner: str, url: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call one of a connector's tools for `owner`, with their own connection."""
        db = await self._store()
        row = await db.execute_query(
            "SELECT name, tokens FROM unified.connector_connections "
            "WHERE owner = $1 AND url = $2 AND status = 'connected'",
            (owner, url), fetch_one=True, store="runtime")
        if not row:
            raise ConnectorError(f"{name_of(url)} is not connected for this person")
        tokens = _json(row["tokens"])
        if tokens and tokens.get("expires_at") and tokens["expires_at"] - EARLY < time.time():
            tokens = await self._refresh(owner, url, tokens)
        try:
            return await self._call(url, tokens, tool, arguments)
        except SignInNeeded:
            if not tokens or not tokens.get("refresh_token"):
                await self._signed_out(owner, url)
                raise ConnectorError(f"{row['name']} needs the person to sign in again")
            tokens = await self._refresh(owner, url, tokens)
            return await self._call(url, tokens, tool, arguments)

    # ── underneath ───────────────────────────────────────────────────────────

    async def _read(self, url: str, token: Optional[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """The connector's tools, and what it says about itself."""
        async with session(url, token) as opened:
            return await opened.tools(), opened.server

    async def _call(self, url: str, tokens: Optional[Dict[str, Any]], tool: str,
                    arguments: Dict[str, Any]) -> Dict[str, Any]:
        async with session(url, tokens and tokens["access_token"]) as opened:
            return await opened.call(tool, arguments)

    async def _keep(self, owner: str, url: str, name: str, tokens: Optional[Dict[str, Any]],
                    tools: List[Dict[str, Any]], server: Dict[str, Any]) -> None:
        db = await self._store()
        await db.execute_query(
            "INSERT INTO unified.connector_connections "
            "(owner, url, name, status, pending, tokens, tools, server, connected_at) "
            "VALUES ($1, $2, $3, 'connected', NULL, $4::jsonb, $5::jsonb, $6::jsonb, now()) "
            "ON CONFLICT (owner, url) DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status, "
            "pending = NULL, tokens = EXCLUDED.tokens, tools = EXCLUDED.tools, server = EXCLUDED.server, "
            "connected_at = now(), updated_at = now()",
            (owner, url, name, json.dumps(tokens) if tokens else None, json.dumps(tools), json.dumps(server)),
            store="runtime")
        from core.tools.tool_registry import get_tool_registry
        registered = register_tools(get_tool_registry(), url, name, tools)
        logger.info("Connector %s connected: %d tools registered", url, registered)

    async def _client(self, url: str, needed: SignInNeeded) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """How the connector signs people in, and Lyric's registration with it: kept from the first time, made
        the first time."""
        db = await self._store()
        row = await db.execute_query(
            "SELECT sign_in, client FROM unified.connector_clients WHERE url = $1",
            (url,), fetch_one=True, store="runtime")
        if row and _json(row["client"]).get("redirect") == REDIRECT:
            return _json(row["sign_in"]), _json(row["client"])
        async with _http() as http:
            given = await sign_in.discover(http, url, needed.resource_metadata, needed.scope)
            client = await sign_in.register(http, given, REDIRECT)
        await db.execute_query(
            "INSERT INTO unified.connector_clients (url, sign_in, client) VALUES ($1, $2::jsonb, $3::jsonb) "
            "ON CONFLICT (url) DO UPDATE SET sign_in = EXCLUDED.sign_in, client = EXCLUDED.client, "
            "registered_at = now()",
            (url, json.dumps(given), json.dumps(client)), store="runtime")
        return given, client

    async def _registered(self, url: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        db = await self._store()
        row = await db.execute_query(
            "SELECT sign_in, client FROM unified.connector_clients WHERE url = $1",
            (url,), fetch_one=True, store="runtime")
        if not row:
            raise ConnectorError(f"Lyric is not registered with {name_of(url)}'s sign-in")
        return _json(row["sign_in"]), _json(row["client"])

    async def _refresh(self, owner: str, url: str, tokens: Dict[str, Any]) -> Dict[str, Any]:
        if not tokens.get("refresh_token"):
            await self._signed_out(owner, url)
            raise ConnectorError(f"{name_of(url)} needs the person to sign in again")
        given, client = await self._registered(url)
        async with _http() as http:
            fresh = await sign_in.refresh(http, given, client, tokens["refresh_token"])
        db = await self._store()
        await db.execute_query(
            "UPDATE unified.connector_connections SET tokens = $3::jsonb, updated_at = now() "
            "WHERE owner = $1 AND url = $2", (owner, url, json.dumps(fresh)), store="runtime")
        return fresh

    async def _signed_out(self, owner: str, url: str) -> None:
        db = await self._store()
        await db.execute_query(
            "UPDATE unified.connector_connections SET status = 'signed_out', tokens = NULL, updated_at = now() "
            "WHERE owner = $1 AND url = $2", (owner, url), store="runtime")


_connectors: Optional[Connectors] = None


def get_connectors() -> Connectors:
    global _connectors
    if _connectors is None:
        _connectors = Connectors()
    return _connectors


# ── a connector's tools, as Lyric's tools ─────────────────────────────────────


class ConnectorTool(Tool):
    """One tool of a connector. Its name is `<connector>__<tool>`; its description and parameters are the
    connector's own. What it performs is read from what the connector declares about it (its annotations):
    a request over the network that reads, or that changes something."""

    def __init__(self, connector: str, url: str, spec: Dict[str, Any]):
        super().__init__()
        hints = spec.get("annotations") or {}
        reads = hints.get("readOnlyHint") is True
        self.name = f"{slug(connector)}__{spec['name']}"
        self.description = spec.get("description") or spec.get("title") or spec["name"]
        self.parameters = spec.get("inputSchema") or {"type": "object", "properties": {}}
        self.category = ToolCategory.NETWORK
        # The protocol's own defaults: a tool that does not say it only reads may change things, and may
        # destroy them.
        self.safety_level = (ToolSafety.SAFE if reads else
                             ToolSafety.DANGEROUS if hints.get("destructiveHint", True) else ToolSafety.MODERATE)
        self.primitive_profile = PrimitiveProfile(
            tool_name=self.name,
            primitives=[PrimitiveUse(primitive=Primitive.HTTP_REQUEST, description=f"calls {connector}"),
                        PrimitiveUse(primitive=Primitive.READ_DATA if reads else Primitive.WRITE_DATA,
                                     description=self.description)],
            tags={"connector", slug(connector)},
            requires_network=True,
            requires_credentials=True,
            is_idempotent=bool(hints.get("idempotentHint", reads)),
        )
        self.connector = connector
        self.url = url
        self.tool = spec["name"]

    async def execute(self, **kwargs) -> ToolResult:
        from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR, is_substrate_actor
        from core.reasoning.intent_authority import get_acting_actor
        actor = get_acting_actor()
        owner = SUBSTRATE_ACTOR if is_substrate_actor(actor) else actor
        try:
            result = await get_connectors().call(owner, self.url, self.tool, kwargs)
        except (ConnectorError, httpx.HTTPError) as failed:
            return ToolResult(success=False, output=None, error=str(failed), tool_name=self.name,
                              parameters=kwargs)
        text = "\n".join(part.get("text", "") for part in result.get("content") or []
                         if part.get("type") == "text")
        output: Dict[str, Any] = {"text": text}
        if result.get("structuredContent") is not None:
            output["structured"] = result["structuredContent"]
        failed = bool(result.get("isError"))
        return ToolResult(success=not failed, output=output, error=text if failed else None,
                          tool_name=self.name, parameters=kwargs,
                          metadata={"connector": self.connector, "connector_tool": self.tool})


def register_tools(registry, url: str, name: str, tools: List[Dict[str, Any]]) -> int:
    """Register a connector's tools in the tool registry. Registering one again replaces it."""
    for spec in tools:
        registry.register(ConnectorTool(name, url, spec))
    return len(tools)


async def register_connected(registry, db=None) -> int:
    """Register the tools of every connector anyone has connected, as they were last read. Called when Lyric
    starts, so a connection made before outlives the process that made it."""
    connectors = get_connectors() if db is None else Connectors(db)
    store = await connectors._store()
    rows = await store.execute_query(
        "SELECT DISTINCT ON (url) url, name, tools FROM unified.connector_connections "
        "WHERE status = 'connected' ORDER BY url, connected_at DESC", fetch_all=True, store="runtime") or []
    return sum(register_tools(registry, row["url"], row["name"], _json(row["tools"]) or []) for row in rows)
