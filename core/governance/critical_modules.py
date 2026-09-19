#!/usr/bin/env python3
"""Which modules the system depends on for its own safety.

`runtime_governance` holds a fingerprint baseline of these modules and detects
that one of them was tampered with (replaced in sys.modules or patched) after
startup. The substrate itself never changes its own code: it improves only by
learning, so any change to one of these at runtime is tampering, not growth.

It lives in `core.governance` because deciding what is safety-critical is a
governance judgement, not a property of the enforcer.
"""

from __future__ import annotations

from typing import FrozenSet

#: Exact module paths whose replacement or patching is a security event.
CRITICAL_MODULES: FrozenSet[str] = frozenset({
    'core.learning.meta_learning',
    'core.learning.safety_audit_trail',
    'core.governance.governance_triggers',
    'core.governance.context_classifier',
    'core.security.safety_framework',
    'core.agents.autonomous.runtime_governance',
    'core.agents.autonomous.singleton_constitution',
})


__all__ = ["CRITICAL_MODULES"]
