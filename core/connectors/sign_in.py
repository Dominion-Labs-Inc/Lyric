"""Signing a person in to a connector, the way the protocol lays it out (MCP authorization, on OAuth 2.1).

The person signs in with the service itself, never with Lyric, and Lyric is given a token for that one connector:

1. The connector names who signs people in for it, in its protected resource metadata (RFC 9728): where its 401
   pointed, or the well-known address beside it.
2. That sign-in server describes itself (RFC 8414, or OpenID's discovery): where to send the person, and where
   Lyric trades what comes back for a token.
3. Lyric registers itself with the sign-in server, once per connector, when the server lets apps register
   (RFC 7591). One that does not needs Lyric registered with the service by hand first.
4. The person goes to the sign-in link. PKCE ties what comes back to this one sign-in, `state` to the person who
   started it, and `resource` names the connector the token is for (RFC 8707).
5. The code that comes back is traded for the token (`exchange`), and later a refresh for a new one (`refresh`).
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

import httpx

from core.connectors.protocol import ConnectorError


def _split(url: str) -> Tuple[str, str]:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}", path


def _resource_metadata_addresses(url: str, pointed: Optional[str]) -> List[str]:
    origin, path = _split(url)
    found = [pointed] if pointed else []
    if path:
        found.append(f"{origin}/.well-known/oauth-protected-resource{path}")
    found.append(f"{origin}/.well-known/oauth-protected-resource")
    return list(dict.fromkeys(found))


def _server_metadata_addresses(issuer: str) -> List[str]:
    origin, path = _split(issuer)
    if path:
        return [f"{origin}/.well-known/oauth-authorization-server{path}",
                f"{origin}/.well-known/openid-configuration{path}",
                f"{origin}{path}/.well-known/openid-configuration"]
    return [f"{origin}/.well-known/oauth-authorization-server", f"{origin}/.well-known/openid-configuration"]


async def _first_json(http: httpx.AsyncClient, addresses: List[str]) -> Optional[Dict[str, Any]]:
    for address in addresses:
        try:
            response = await http.get(address, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            continue
        if response.status_code == 200:
            try:
                found = response.json()
            except ValueError:
                continue
            if isinstance(found, dict):
                return found
    return None


async def discover(http: httpx.AsyncClient, url: str, pointed: Optional[str] = None,
                   scope: Optional[str] = None) -> Dict[str, Any]:
    """How the connector at `url` signs people in. `pointed` and `scope` are what its 401 said."""
    resource = await _first_json(http, _resource_metadata_addresses(url, pointed))
    servers = (resource or {}).get("authorization_servers") or []
    # A connector that describes no sign-in server is its own (the protocol's earlier form).
    issuer = servers[0] if servers else _split(url)[0]
    server = await _first_json(http, _server_metadata_addresses(issuer))
    if not server or not server.get("authorization_endpoint") or not server.get("token_endpoint"):
        raise ConnectorError(f"{url}: its sign-in server ({issuer}) does not describe itself")
    methods = server.get("code_challenge_methods_supported")
    if methods is not None and "S256" not in methods:
        raise ConnectorError(f"{url}: its sign-in server does not protect the sign-in (no PKCE S256)")
    scopes = scope or " ".join((resource or {}).get("scopes_supported") or []) or None
    return {
        "issuer": issuer,
        "authorization_endpoint": server["authorization_endpoint"],
        "token_endpoint": server["token_endpoint"],
        "registration_endpoint": server.get("registration_endpoint"),
        "resource": (resource or {}).get("resource") or url,
        "scope": scopes,
    }


async def register(http: httpx.AsyncClient, sign_in: Dict[str, Any], redirect: str) -> Dict[str, Any]:
    """Lyric, registered with the connector's sign-in server as an app people sign in to it with."""
    endpoint = sign_in.get("registration_endpoint")
    if not endpoint:
        raise ConnectorError(
            f"{sign_in['issuer']} does not let apps register themselves: Lyric has to be registered with "
            f"the service before people can connect it")
    response = await http.post(endpoint, json={
        "client_name": "Lyric",
        "redirect_uris": [redirect],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    if response.status_code not in (200, 201):
        raise ConnectorError(f"{sign_in['issuer']} refused to register Lyric: {response.status_code} "
                             f"{response.text[:300]}")
    client = response.json()
    return {"client_id": client["client_id"], "client_secret": client.get("client_secret"), "redirect": redirect}


def begin(sign_in: Dict[str, Any], client: Dict[str, Any]) -> Tuple[str, str, str]:
    """The link the person signs in at, with the verifier and the state that tie its answer to this sign-in."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    asked = {
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": client["redirect"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "resource": sign_in["resource"],
    }
    if sign_in.get("scope"):
        asked["scope"] = sign_in["scope"]
    joiner = "&" if "?" in sign_in["authorization_endpoint"] else "?"
    return f"{sign_in['authorization_endpoint']}{joiner}{urlencode(asked)}", verifier, state


async def _token(http: httpx.AsyncClient, sign_in: Dict[str, Any], client: Dict[str, Any],
                 form: Dict[str, str]) -> Dict[str, Any]:
    form = {**form, "client_id": client["client_id"], "resource": sign_in["resource"]}
    auth = (client["client_id"], client["client_secret"]) if client.get("client_secret") else None
    response = await http.post(sign_in["token_endpoint"], data=form, auth=auth,
                               headers={"Accept": "application/json"})
    if response.status_code != 200:
        try:
            said = response.json()
            reason = said.get("error_description") or said.get("error") or response.text
        except ValueError:
            reason = response.text
        raise ConnectorError(f"{sign_in['issuer']} refused the sign-in: {str(reason)[:300]}")
    token = response.json()
    return {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token"),
        "expires_at": time.time() + float(token["expires_in"]) if token.get("expires_in") else None,
    }


async def exchange(http: httpx.AsyncClient, sign_in: Dict[str, Any], client: Dict[str, Any], code: str,
                   verifier: str) -> Dict[str, Any]:
    """The person's token, for the code the sign-in sent back."""
    return await _token(http, sign_in, client, {
        "grant_type": "authorization_code", "code": code, "redirect_uri": client["redirect"],
        "code_verifier": verifier})


async def refresh(http: httpx.AsyncClient, sign_in: Dict[str, Any], client: Dict[str, Any],
                  refresh_token: str) -> Dict[str, Any]:
    """A new token for the person, from their refresh token. Keeps the refresh token when no new one comes."""
    token = await _token(http, sign_in, client, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    return {**token, "refresh_token": token["refresh_token"] or refresh_token}
