"""The self-repair defect classifier: a health finding → the remedy family that
fixes it. Pure and model-free, so this is a plain unit test — no system bring-up.

The point of the classifier is that a finding is routed to the RIGHT remedy
instead of everything non-liveness being dumped into code generation. These cases
are the real findings this subsystem produced (watchdog down, phantom-module
probe, stale-baseline regression, dormant ASI, zero-coverage probe)."""
import pytest

from core.learning.enhanced_asi_self_improvement import (
    classify_defect, RemedyFamily,
)


@pytest.mark.parametrize("issues,expected", [
    (["watchdog_running is False — subsystem reports it is not running"],
     RemedyFamily.LIVENESS),
    (["interaction_learner: probe failed (ModuleNotFoundError: No module named x)"],
     RemedyFamily.WIRING),
    (["Capability regression (CRITICAL): safety.health_score lost 100% against a baseline"],
     RemedyFamily.STALENESS),
    (["Low ASI improvement success rate: 6% over 35 cycles"],
     RemedyFamily.META),
    (["security probe returned no evidence"],
     RemedyFamily.OBSERVABILITY),
    (["completion trusted without verification; result unverified"],
     RemedyFamily.VERIFICATION),
    (["TypeError raised in _foo; traceback follows"],
     RemedyFamily.CODE_DEFECT),
    (["queue backlog growing; high memory"],
     RemedyFamily.EFFICIENCY),
    # Evidence classes that USED to fall through as UNCLASSIFIED (and so reached a
    # code generator that could not act on them) — now classified by evidence:
    (["2 critical service(s) down"],
     RemedyFamily.LIVENESS),
    (["9 knowledge transfer(s) stored but none loaded into the registry — "
      "transfer history is invisible to the running system"],
     RemedyFamily.WIRING),
    (["824 unrecovered failure(s) active",
      "824 failure(s) escalated beyond automatic recovery"],
     RemedyFamily.BACKLOG),
    (["5202 unresolved CRITICAL security finding(s)"],
     RemedyFamily.BACKLOG),
    (["5 knowledge transfer(s) unresolved for over 7 days — target domains never "
      "accrued enough outcome evidence to judge them; the transfer validation "
      "loop is not closing"],
     RemedyFamily.BACKLOG),
])
def test_classifies_real_findings(issues, expected):
    assert classify_defect(issues) is expected


def test_unmatched_is_none_not_code_defect():
    # HONESTY: a finding with no recognisable remedy is NOT routed to code
    # generation. It returns None so the cycle flags it, rather than dumping it
    # into a generator that cannot fix it.
    assert classify_defect(["some vague unclassifiable note"]) is None
    assert classify_defect([]) is None
    assert classify_defect(None) is None


def test_liveness_beats_generic_error_ordering():
    # A subsystem that is down AND logs an error is a liveness defect (restart),
    # not a code defect (rewrite): ordered matching puts liveness first.
    got = classify_defect(["service is not running (exception on last start)"])
    assert got is RemedyFamily.LIVENESS


def test_phantom_module_is_wiring_not_code():
    # ModuleNotFoundError is a phantom reference (wiring), never a code defect.
    got = classify_defect(["probe failed: ModuleNotFoundError: no module named z"])
    assert got is RemedyFamily.WIRING
