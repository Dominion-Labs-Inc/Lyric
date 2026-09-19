"""RecoveryManager.can_restart: does a restart PATH exist for this component?

This is the distinction that keeps health remediation from re-issuing an
impossible restart every run — "no authorized recovery exists" (nothing to try)
must not read as "the restart was attempted and failed". Pure and in-process:
no system bring-up, no handler side effects."""
import pytest

from core.health.recovery_manager import RecoveryManager


def test_builtin_keys_have_a_path():
    rm = RecoveryManager()
    # Built-in branches of _restart_component, mirrored in _BUILTIN_RESTART_KEYS.
    for key in ("database", "health_monitor", "security_controller", "monitoring"):
        assert rm.can_restart(key) is True
    # Case/whitespace-insensitive, matching how _restart_component normalises.
    assert rm.can_restart("  Database ") is True


def test_unregistered_component_has_no_path():
    rm = RecoveryManager()
    # content_security / safety are started by an external launcher, not
    # restartable in-process — no handler, not a built-in key.
    assert rm.can_restart("content_security") is False
    assert rm.can_restart("safety") is False
    assert rm.can_restart("") is False
    assert rm.can_restart(None) is False


def test_registering_a_handler_creates_a_path():
    rm = RecoveryManager()
    assert rm.can_restart("widget") is False

    async def _noop(_params):
        return True

    rm.register_restart_handler("widget", _noop)
    assert rm.can_restart("widget") is True
