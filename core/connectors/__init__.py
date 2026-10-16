"""Connectors: the services a person connects Lyric to, through the open protocol services publish for apps
(MCP, modelcontextprotocol.io).

    protocol     speaking MCP with a connector: a session on either of its lines, its tools, a call
    sign_in      signing a person in to a connector (OAuth 2.1, as MCP lays it out)
    connections  each person's connections, kept; the connectors' tools as Lyric's tools

A connector's tools become tools in the tool registry, named `<connector>__<tool>`, described in the connector's own
words, which Lyric reads like anything else it reads. They act with the connection of whoever's work the act is.
"""
from core.connectors.connections import (ConnectorTool, Connectors, get_connectors, register_connected,
                                         register_tools)
from core.connectors.protocol import ConnectorError, LegacySession, Session, SignInNeeded, session

__all__ = ["ConnectorError", "ConnectorTool", "Connectors", "LegacySession", "Session", "SignInNeeded",
           "get_connectors", "register_connected", "register_tools", "session"]
