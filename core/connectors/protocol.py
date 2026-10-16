"""Speaking MCP with a connector.

A connector is a server a service runs for apps like Lyric (modelcontextprotocol.io): Linear runs one at
https://mcp.linear.app/mcp, and thousands more are listed in the open MCP Registry. Lyric is the client. A
session opens with `initialize`, then reads the connector's tools (`tools/list`) and calls them (`tools/call`).

The line is streamable HTTP (`Session`): every message Lyric sends is a POST to the connector's address,
answered with one JSON message, or with a stream of events that ends with the answer. A connector that hands out
sessions names one in `Mcp-Session-Id` and expects it back. A connector that needs the person to sign in answers
401 and says where its sign-in is described (`SignInNeeded`; core.connectors.sign_in).

A connector still on the protocol's earlier line (2024-11-05) refuses that POST (400, 404 or 405). Then, as the
protocol says, Lyric opens the earlier line (`LegacySession`): a stream it keeps open, on which the connector names
where to post messages and sends every answer. `session` opens whichever the connector speaks.

While a stream is open the connector may ask Lyric something. A `ping` is answered; anything else (sampling, a
form for the person) is refused by name: Lyric offers none of them (`initialize` declares no capabilities).
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin

import httpx

#: The protocol version Lyric speaks. The connector answers with the one the session uses.
PROTOCOL_VERSION = "2025-06-18"

#: How Lyric names itself to a connector.
CLIENT = {"name": "Lyric", "version": "1"}

#: How long the line may take: to connect, and for an answer (a tool can take a while).
TIMEOUT = httpx.Timeout(120.0, connect=15.0)


class ConnectorError(RuntimeError):
    """What went wrong with a connector, in the connector's own words where it gave any. `status` is the HTTP
    status it answered with, when that was the trouble."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class SignInNeeded(ConnectorError):
    """The connector needs the person to sign in. `resource_metadata` is where it describes its sign-in (when it
    said), and `scope` what it asks for."""

    def __init__(self, url: str, resource_metadata: Optional[str], scope: Optional[str]):
        super().__init__(f"{url} needs the person to sign in")
        self.resource_metadata = resource_metadata
        self.scope = scope


def challenge_of(header: str) -> Dict[str, str]:
    """The parameters of a `WWW-Authenticate: Bearer …` header."""
    return dict(re.findall(r'([A-Za-z_]+)="([^"]*)"', header or ""))


async def named_events(response: httpx.Response) -> AsyncIterator[Tuple[str, str]]:
    """Each event in a server-sent event stream: its name (`message` when it has none) and its data."""
    name, data = "message", []
    async for line in response.aiter_lines():
        if line == "":
            if data:
                yield name, "\n".join(data)
            name, data = "message", []
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield name, "\n".join(data)


async def events(response: httpx.Response) -> AsyncIterator[str]:
    """The data of each event in a server-sent event stream."""
    async for _, data in named_events(response):
        yield data


class Session:
    """One session with a connector. Used as `async with Session(url, token) as session:`."""

    def __init__(self, url: str, token: Optional[str] = None, http: Optional[httpx.AsyncClient] = None):
        self.url = url
        self._token = token
        self._http = http
        self._own_http = http is None
        self._next = 0
        self.session_id: Optional[str] = None
        self.version: Optional[str] = None
        #: What the connector said about itself when the session opened: its name and version, and the
        #: instructions it gives for using it.
        self.server: Dict[str, Any] = {}
        self.instructions: Optional[str] = None

    async def __aenter__(self) -> "Session":
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)
        try:
            await self.open()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def open(self) -> None:
        result = await self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT})
        self.version = result.get("protocolVersion") or PROTOCOL_VERSION
        self.server = result.get("serverInfo") or {}
        self.instructions = result.get("instructions")
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def tools(self) -> List[Dict[str, Any]]:
        """Every tool the connector has, page by page."""
        found: List[Dict[str, Any]] = []
        cursor = None
        while True:
            result = await self._request("tools/list", {"cursor": cursor} if cursor else {})
            found += result.get("tools") or []
            cursor = result.get("nextCursor")
            if not cursor:
                return found

    async def call(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call one of the connector's tools. The result is the connector's: its `content`, and
        `structuredContent` and `isError` when it gave them."""
        return await self._request("tools/call", {"name": tool, "arguments": arguments or {}})

    async def close(self) -> None:
        """End the session (when the connector handed one out) and let go of the line."""
        try:
            if self.session_id and self._http is not None:
                await self._http.delete(self.url, headers=self._headers())
        except httpx.HTTPError:
            # The session ends on the connector's side by itself; nothing of Lyric's waits on this.
            pass
        finally:
            if self._own_http and self._http is not None:
                await self._http.aclose()
                self._http = None

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        return headers

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._next += 1
        answer = await self._send({"jsonrpc": "2.0", "id": self._next, "method": method, "params": params},
                                  self._next)
        if "error" in answer:
            error = answer["error"] or {}
            raise ConnectorError(f"{method}: {error.get('message') or error}")
        return answer.get("result") or {}

    async def _send(self, message: Dict[str, Any], expect: Optional[int] = None) -> Dict[str, Any]:
        """Send one message. For a request (`expect`, its id), the connector's answer to it."""
        async with self._http.stream("POST", self.url, json=message, headers=self._headers()) as response:
            if response.status_code == 401:
                found = challenge_of(response.headers.get("www-authenticate", ""))
                raise SignInNeeded(self.url, found.get("resource_metadata"), found.get("scope"))
            if response.status_code == 404 and self.session_id:
                raise ConnectorError(f"{self.url} ended the session")
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")
                raise ConnectorError(f"{self.url} answered {response.status_code}: {body[:300]}",
                                     status=response.status_code)
            if response.headers.get("mcp-session-id"):
                self.session_id = response.headers["mcp-session-id"]
            if expect is None:
                return {}
            if response.headers.get("content-type", "").startswith("text/event-stream"):
                async for data in events(response):
                    said = json.loads(data)
                    if said.get("id") == expect and ("result" in said or "error" in said):
                        return said
                    if "method" in said and "id" in said:
                        await self._answer(said)
                raise ConnectorError(f"{message['method']}: the connector's stream ended without an answer")
            said = json.loads(await response.aread())
            if said.get("id") != expect:
                raise ConnectorError(f"{message['method']}: the connector answered something else")
            return said

    async def _answer(self, asked: Dict[str, Any]) -> None:
        """Answer what the connector asked in the middle of a stream."""
        if asked["method"] == "ping":
            reply = {"jsonrpc": "2.0", "id": asked["id"], "result": {}}
        else:
            reply = {"jsonrpc": "2.0", "id": asked["id"],
                     "error": {"code": -32601, "message": f"Lyric does not offer {asked['method']}"}}
        response = await self._http.post(self.url, json=reply, headers=self._headers())
        if response.status_code >= 400:
            raise ConnectorError(f"{self.url} refused Lyric's answer to {asked['method']}: {response.status_code}")


class LegacySession:
    """One session with a connector on the protocol's earlier line (2024-11-05). Lyric keeps a stream open on the
    connector's address; the connector's first event names where Lyric posts its messages (`endpoint`), and every
    answer comes back on the stream. The same use as `Session`."""

    def __init__(self, url: str, token: Optional[str] = None, http: Optional[httpx.AsyncClient] = None):
        self.url = url
        self._token = token
        self._http = http
        self._own_http = http is None
        self._next = 0
        self._endpoint: Optional[str] = None
        self._ready: Optional[asyncio.Future] = None
        self._waiting: Dict[int, asyncio.Future] = {}
        self._reader: Optional[asyncio.Task] = None
        self.version: Optional[str] = None
        self.server: Dict[str, Any] = {}
        self.instructions: Optional[str] = None

    async def __aenter__(self) -> "LegacySession":
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT.connect, read=None), follow_redirects=True)
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._reader = asyncio.create_task(self._read())
        try:
            self._endpoint = await asyncio.wait_for(asyncio.shield(self._ready), TIMEOUT.connect)
            result = await self._request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": CLIENT})
            self.version = result.get("protocolVersion") or "2024-11-05"
            self.server = result.get("serverInfo") or {}
            self.instructions = result.get("instructions")
            await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def tools(self) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        cursor = None
        while True:
            result = await self._request("tools/list", {"cursor": cursor} if cursor else {})
            found += result.get("tools") or []
            cursor = result.get("nextCursor")
            if not cursor:
                return found

    async def call(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("tools/call", {"name": tool, "arguments": arguments or {}})

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except BaseException:
                pass
            self._reader = None
        for waiting in self._waiting.values():
            if not waiting.done():
                waiting.set_exception(ConnectorError(f"{self.url}: the session closed"))
        if self._own_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _read(self) -> None:
        """The stream: where to post first, then the connector's answers and questions."""
        headers = {"Accept": "text/event-stream"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._http.stream("GET", self.url, headers=headers) as response:
                if response.status_code == 401:
                    found = challenge_of(response.headers.get("www-authenticate", ""))
                    raise SignInNeeded(self.url, found.get("resource_metadata"), found.get("scope"))
                if response.status_code >= 400:
                    raise ConnectorError(f"{self.url} answered {response.status_code}", status=response.status_code)
                async for name, data in named_events(response):
                    if name == "endpoint":
                        if not self._ready.done():
                            self._ready.set_result(urljoin(self.url, data.strip()))
                        continue
                    said = json.loads(data)
                    waiting = self._waiting.pop(said.get("id"), None) if "method" not in said else None
                    if waiting is not None and not waiting.done():
                        waiting.set_result(said)
                    elif "method" in said and "id" in said:
                        await self._answer(said)
            raise ConnectorError(f"{self.url}: the connector closed the stream")
        except asyncio.CancelledError:
            raise
        except BaseException as broke:
            failure = broke if isinstance(broke, ConnectorError) else ConnectorError(f"{self.url}: {broke}")
            if not self._ready.done():
                self._ready.set_exception(failure)
            for waiting in self._waiting.values():
                if not waiting.done():
                    waiting.set_exception(failure)

    async def _post(self, message: Dict[str, Any]) -> None:
        response = await self._http.post(self._endpoint, json=message, headers=self._headers(),
                                         timeout=TIMEOUT)
        if response.status_code == 401:
            found = challenge_of(response.headers.get("www-authenticate", ""))
            raise SignInNeeded(self.url, found.get("resource_metadata"), found.get("scope"))
        if response.status_code >= 400:
            raise ConnectorError(f"{self.url} answered {response.status_code}: {response.text[:300]}",
                                 status=response.status_code)

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._next += 1
        waiting = asyncio.get_running_loop().create_future()
        self._waiting[self._next] = waiting
        await self._post({"jsonrpc": "2.0", "id": self._next, "method": method, "params": params})
        answer = await asyncio.wait_for(waiting, TIMEOUT.read)
        if "error" in answer:
            error = answer["error"] or {}
            raise ConnectorError(f"{method}: {error.get('message') or error}")
        return answer.get("result") or {}

    async def _answer(self, asked: Dict[str, Any]) -> None:
        if asked["method"] == "ping":
            reply = {"jsonrpc": "2.0", "id": asked["id"], "result": {}}
        else:
            reply = {"jsonrpc": "2.0", "id": asked["id"],
                     "error": {"code": -32601, "message": f"Lyric does not offer {asked['method']}"}}
        await self._post(reply)


#: What a connector on the earlier line answers a POST of `initialize` with.
_EARLIER_LINE = (400, 404, 405)


@asynccontextmanager
async def session(url: str, token: Optional[str] = None) -> AsyncIterator[Union[Session, LegacySession]]:
    """A session on whichever line the connector speaks: streamable HTTP, or the earlier one when the connector
    refuses streamable HTTP the way the protocol says it will."""
    try:
        opened: Union[Session, LegacySession] = await Session(url, token).__aenter__()
    except ConnectorError as refused:
        if isinstance(refused, SignInNeeded) or refused.status not in _EARLIER_LINE:
            raise
        opened = await LegacySession(url, token).__aenter__()
    try:
        yield opened
    finally:
        await opened.close()
