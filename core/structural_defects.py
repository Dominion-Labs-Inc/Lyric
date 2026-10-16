#!/usr/bin/env python3
"""Exceptions that mean the CODE is wrong, not that the world answered "no".

A broad handler that turns every exception into an ordinary negative result
hides a defect as a legitimate "found nothing" -- the harder failure to notice,
because a negative result looks exactly like a system working correctly and
finding nothing.

Observed: `transfer_learning_across_domains` called
`cross_domain_reasoner.find_cross_domain_mapping()`, a method that class has
never implemented. Every call raised AttributeError into a broad
`except Exception -> return {"success": False, "error": ...}`. The system
reported "no cross-domain mapping found" for the entire life of the code, and
because that is a perfectly ordinary thing for it to report, nothing ever
flagged it. The capability was dark, not absent -- the worst state to be in.

Moved here on 2026-10-04 from `core/capability.py`, which named it after
something it is not about; the guard itself is unchanged.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


STRUCTURAL_DEFECT_TYPES = (AttributeError, NameError, ImportError, TypeError)


def raise_if_structural(exc: BaseException, where: str) -> None:
    """Re-raise `exc` if it indicates a wiring defect rather than a real failure.

    Call as the first line of a broad handler::

        except Exception as e:
            raise_if_structural(e, "module.function")
            logger.error(...)
            return {"success": False, "error": str(e)}

    A missing attribute, an undefined name, a failed import or a signature
    mismatch are never conditions the caller should absorb and report as an
    ordinary negative -- they mean this path has not run correctly, possibly
    ever. Operational failures (a database down, a timeout, a refused
    connection) fall through and are still handled as before.
    """
    if isinstance(exc, STRUCTURAL_DEFECT_TYPES):
        logger.critical(
            f"STRUCTURAL DEFECT in {where}: {type(exc).__name__}: {exc} "
            f"-- this is broken wiring, not a negative result; re-raising so it "
            f"cannot be recorded as an ordinary failure",
            exc_info=True,
        )
        raise exc


__all__ = [
    "STRUCTURAL_DEFECT_TYPES",
    "raise_if_structural",
]
