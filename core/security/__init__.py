#!/usr/bin/env python3
"""Security — Lyric.

What governs the substrate's acts is the Constitution, and what the substrate
knows about the attacks it meets is ThreatSense — both in
`core/agents/autonomous/`.

One authority lives here: `secrets.py`, the owner of the substrate's keys. It
answers which values are keys and keeps them out of what the substrate says,
remembers, hands to or gets back from a tool, gives a child process, and logs;
and it is how a key is added (`./lyric secret set NAME`).

What else is kept here:
  * `_disabled/` — the archived network-perimeter implementation (firewall,
    WAF, threat blocking) the security TOOLS in `core/tools/security_tools.py`
    are written against. Those tools serve outside systems as well as the
    substrate, so the implementation stays.
  * `security_training_pipeline.py` — the red-team training ground, not started
    at boot; its rework waits with the paused red-team work.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def get_integrated_security_system() -> Optional[Dict[str, Any]]:
    """The integrated perimeter system is archived (see `_disabled/`) and not
    started, so this returns None — it never fabricates one. Its observers
    (health's firewall check) treat None as "not running"."""
    return None


def reset_integrated_security_system() -> None:
    """No integrated system to reset (archived)."""
    return None


__all__ = ["get_integrated_security_system", "reset_integrated_security_system"]
