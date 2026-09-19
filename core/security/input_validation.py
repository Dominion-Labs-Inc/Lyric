#!/usr/bin/env python3
"""Layer-1 input validation — the live owner.

`safety_framework`'s Layer 1 ("is this input safe": SQL injection, path traversal,
rate limiting) used to live in `SecurityController.validate_request`, backed by
`SystemSecurity`. Both were archived wholesale to `_disabled/` during the
governance/security consolidation — but the Layer-1 *capability* was never
re-homed, so the import threw and the gate silently FAILED OPEN. This module is
that capability re-homed as a live, self-contained validator (stdlib only — no
`core.*` imports, no DB), so the gate can fail CLOSED and the liveness reading is
honest again.

Scope is deliberately narrow: this is tool-parameter input validation, distinct
from RuntimeGovernance (capacity/lifecycle) and the DHCM membrane (the world
boundary). It is not a governance authority; it is the implementation of one
safety-framework layer. When `safety_framework` later collapses into
RuntimeGovernance (consolidation step 4), this layer goes with it.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class InputValidator:
    """Self-contained Layer-1 input validator.

    Stateless except for the rate-limit sliding window and running stats, so a
    single module-level instance is the live authority. Thread-safe (the rate
    window and stats are touched from multiple worker threads).
    """

    # SQL injection patterns — require SQL *syntax context*, not a bare keyword,
    # so ordinary prose/flags don't false-positive. Preserved verbatim from the
    # archived SystemSecurity (the `(--[^\n]*$)` form that flagged `ls --color`
    # was already replaced by the quote/separator-anchored `['\";]\s*--`).
    _SQL_INJECTION_PATTERNS = [
        r"('.*?(\bor\b|\band\b|\bunion\b|\bselect\b|\bdrop\b|\binsert\b|\bupdate\b|\bdelete\b).*?)",
        r"(--.*?(\bor\b|\band\b|\bunion\b|\bselect\b))",
        r"(;.*?(\bdrop\b|\bdelete\b|\binsert\b|\bupdate\b|\bselect\b))",
        r"(\bunion\b.*?\bselect\b)",
        r"(\bor\b\s*['\"0-9].*?[=<>])",
        r"(\band\b\s*['\"0-9].*?[=<>])",
        r"['\";]\s*--",
        r"(/\*.*?\*/)",
        r"(;\s*\b(drop|delete|insert|update|select)\b)",
        r"(\b(exec|execute|cast|declare|shutdown)\s*\()",
    ]

    # Path-traversal markers (checked case-insensitively, incl. URL-encoded).
    _PATH_TRAVERSAL_PATTERNS = ["../", "..\\", "%2e%2e", "%252e", "....", "....."]

    # Parameter names that can carry text into a SQL interface. An explicit
    # allowlist so adding a SQL-taking tool is a deliberate act — injection
    # grammar is only evidence about a value that actually becomes SQL. Applied
    # to a shell command, a Python source blob or a file glob it produces
    # confident nonsense (it fired 85x in one night on Torin's own work: a
    # `--include="*.py"` grep flag, a `**/tools/**/*.py` glob, a `sqlite3 …
    # "SELECT …"` query against Torin's OWN database). Those are covered by the
    # path-traversal rule instead.
    _SQL_SINK_PARAMS = {
        "query", "sql", "sql_query", "statement", "where", "where_clause",
        "condition", "filter_sql", "raw_sql", "db_query",
    }
    # Tools whose every string parameter should be treated as SQL-bearing.
    _SQL_SINK_TOOLS = {
        "query_database", "execute_sql", "postgres_query", "db_query",
        "check_mysql_health", "query_memory",
    }

    def __init__(self, rate_limit_window: int = 60, rate_limit_max: int = 100):
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self._SQL_INJECTION_PATTERNS]
        self.rate_limit_window = rate_limit_window
        self.rate_limit_max = rate_limit_max
        self.rate_limiting_enabled = True
        self._rate_limits: Dict[str, list] = {}
        self._lock = threading.Lock()
        self.stats = {
            "total_requests": 0,
            "blocked_requests": 0,
            "security_violations": 0,
        }
        logger.info("InputValidator initialized (live Layer-1 input validation)")

    # ── primitive checks (re-homed from SystemSecurity) ──────────────────────

    def validate_sql_input(self, input_str: str) -> Tuple[bool, str]:
        """Check a value that reaches a SQL sink for injection syntax."""
        if not input_str:
            return True, ""
        for pat in self._compiled:
            if pat.search(input_str):
                return False, "Potential SQL injection detected"
        return True, ""

    def validate_path(self, path: str, allowed_base: Optional[str] = None) -> Tuple[bool, str]:
        """Check a path-bearing value for traversal."""
        if not path:
            return True, ""
        low = path.lower()
        for pattern in self._PATH_TRAVERSAL_PATTERNS:
            if pattern in low:
                return False, "Path traversal attempt detected"
        if allowed_base:
            abs_path = os.path.abspath(path)
            abs_base = os.path.abspath(allowed_base)
            if not abs_path.startswith(abs_base):
                return False, "Path outside allowed directory"
        return True, ""

    def check_rate_limit(self, identifier: str, max_requests: Optional[int] = None) -> Tuple[bool, int]:
        """Sliding-window rate limit for an external identifier."""
        max_req = max_requests or self.rate_limit_max
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.rate_limit_window)
        with self._lock:
            window = [ts for ts in self._rate_limits.get(identifier, []) if ts > cutoff]
            if len(window) >= max_req:
                self._rate_limits[identifier] = window
                return False, 0
            window.append(now)
            self._rate_limits[identifier] = window
            return True, max_req - len(window)

    def _reaches_sql_sink(self, key: str, context: Dict[str, Any]) -> bool:
        """Can this parameter's text actually arrive at a SQL interface?"""
        if key.lower() in self._SQL_SINK_PARAMS:
            return True
        tool = (context or {}).get("tool_name") or ""
        return tool.lower() in self._SQL_SINK_TOOLS

    # ── the Layer-1 entry point (re-homed from controller.validate_request) ──

    async def validate_action_input(
        self,
        request_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Validate an action's parameters. Returns (is_valid, error_message).

        Fail-CLOSED: any unexpected internal error returns (False, reason) — an
        un-validatable input is not an agent decision. The caller must not
        convert a raise here into an ALLOW.
        """
        try:
            with self._lock:
                self.stats["total_requests"] += 1
            context = context or {}

            # Internal = agent-originated (tool calls, autonomous tasks), not
            # untrusted external input. Rate limiting applies to EXTERNAL only:
            # internal calls are already rate-limited by RuntimeGovernance, and
            # sharing the 'unknown' bucket would hard-block every agent action
            # past the window as a CRITICAL violation.
            is_internal = (
                context.get("is_internal", False)
                or context.get("source") == "autonomous_coordinator"
            )

            if self.rate_limiting_enabled and not is_internal:
                identifier = context.get("ip") or context.get("session_id") or "unknown"
                allowed, _remaining = self.check_rate_limit(identifier)
                if not allowed:
                    with self._lock:
                        self.stats["blocked_requests"] += 1
                    return False, "Rate limit exceeded"

            for key, value in request_data.items():
                if not isinstance(value, str):
                    continue

                # SQL-injection detection ALWAYS runs for a value that can reach
                # a SQL sink — `is_internal` must never disable it there, or an
                # agent-originated action becomes an unvalidated SQL path.
                if self._reaches_sql_sink(key, context):
                    is_safe, _reason = self.validate_sql_input(value)
                    if not is_safe:
                        with self._lock:
                            self.stats["security_violations"] += 1
                            self.stats["blocked_requests"] += 1
                        return False, f"SQL injection detected in {key}"

                # Path traversal on any path-bearing value.
                if "/" in value or "\\" in value:
                    is_safe, _reason = self.validate_path(value)
                    if not is_safe:
                        with self._lock:
                            self.stats["security_violations"] += 1
                            self.stats["blocked_requests"] += 1
                        return False, f"Path traversal detected in {key}"

            return True, ""

        except Exception as e:
            # Fail-CLOSED: block on a validator fault rather than waving input through.
            logger.error(f"Input validation error (blocking, fail-closed): {e}")
            return False, f"Validation error: {e}"

    def get_statistics(self) -> Dict[str, Any]:
        """Liveness + cost stats (read by the health check and the audit worker)."""
        with self._lock:
            snap = dict(self.stats)
        snap["active"] = True
        return snap


_input_validator: Optional[InputValidator] = None
_singleton_lock = threading.Lock()


def get_input_validator() -> InputValidator:
    """The one live Layer-1 input validator."""
    global _input_validator
    if _input_validator is None:
        with _singleton_lock:
            if _input_validator is None:
                _input_validator = InputValidator()
    return _input_validator
