#!/usr/bin/env python3
"""
Event Publishers
Event publishing for monitoring results and drift notifications.
"""

try:
    from .event_publisher import publish_monitor_results
except ImportError as _no_publisher:
    publish_monitor_results = None
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "the monitor result publisher could not be imported (%s): monitor "
        "results are computed and published nowhere", _no_publisher)

__all__ = [
    'publish_monitor_results',
]