#!/usr/bin/env python3
"""Security module — TorinAI.

The legacy "system-security" perimeter — `controller`, `system_security`, `firewall_manager`,
`threat_blocking`, `cloudflare_waf` — is ARCHIVED + DISABLED under `_disabled/`. The shield is
the DHCM membrane (`Dominion Labs/DHCM/`), outside the substrate; nothing here stands in for it.
Their capabilities are preserved in `CAPABILITIES_CATALOG.md`.

Still live here: the content-security helpers that back agent tools;
the shared security types; and the model-free action/ASI-safety layer. (The substrate-security
faculty, quarantine, and training-ground layers — `threat_intelligence`, `malware_sandbox`,
`security_training_pipeline` — remain as their own modules, reworked in later layers.)
"""

import logging
from typing import Any, Dict, Optional

# Content-security helpers (back agent tools in core/tools/security_tools.py)
from core.security.content_security import (
    sanitize_input,
    validate_email,
    validate_url,
    check_malicious_patterns,
    sanitize_filename,
    MALICIOUS_PATTERNS,
    EMAIL_REGEX,
)

# Shared security types (imported across the codebase)
from core.security.security_types import SecurityLevel

# Action/ASI safety layer (load-bearing, model-free)
from core.security.asi_safety import ASISafetyFramework

logger = logging.getLogger(__name__)


def get_integrated_security_system() -> Optional[Dict[str, Any]]:
    """The legacy integrated security system is ARCHIVED (see `_disabled/`). There is no
    integrated system now, so this honestly returns None — it never fabricates one. Its
    observers (health checks) already treat None as "nothing observed."
    The DHCM membrane supersedes it."""
    return None


def reset_integrated_security_system() -> None:
    """No integrated system to reset (archived). Kept so legacy callers don't break."""
    return None


__all__ = [
    "sanitize_input",
    "validate_email",
    "validate_url",
    "check_malicious_patterns",
    "sanitize_filename",
    "MALICIOUS_PATTERNS",
    "EMAIL_REGEX",
    "SecurityLevel",
    "ASISafetyFramework",
    "get_integrated_security_system",
    "reset_integrated_security_system",
]

__version__ = "2.0.0"
