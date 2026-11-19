"""A long pass on the substrate's own event loop gives the loop back BY TIME, not by count.

The substrate is one event loop: the coordinator, the queue's scheduled jobs, every database query and the memory
agent's writes all take their turns on it. A pass that walks a corpus on it (saying 157,786 facts, reading each said
sentence, observing each held belief) holds the loop for as long as it runs without awaiting.

It used to give way every hundred facts. A hundred facts are three to six seconds of reading, and a give-way is ONE
step for everything else, so a query that needs a dozen steps took over a minute: WordNet's sandbox run of 2026-10-08
timed out every query and every scheduled job while it said its facts. What a pass may hold the loop for is the
loop's own measure of too long (`slow_callback_duration`), whatever one item of it costs.

GIVING THE LOOP BACK IS NOT STANDING DOWN. Yielding a step keeps a long pass from blocking anything, and the pass
still runs to completion: it is politeness, not pausing. Work that may only happen in downtime -- reflection -- has
to stop outright the moment a person arrives, and stop in a way that can be taken up again rather than begun again.
That is `stand_down`: a pass given one is asked, at each give-way, whether the substrate has work to do, and told to
stop by `StandDown`, which carries where it had got to.
"""

import asyncio
import time
from typing import Any, Callable, Optional


class StandDown(Exception):
    """Raised through a long pass when the substrate has work to do.

    `at` is whatever the pass passed to its last give-way: where it had got to, in whatever terms the pass counts
    in. The pass is stopped, not failed, and whoever runs it keeps `at` so the next run takes up from there."""

    def __init__(self, at: Any = None) -> None:
        super().__init__(f"stood down at {at!r}")
        self.at = at


class GiveWay:
    """Awaited once per item of a long pass; yields to the loop when the pass has held it for its slice.

    `stand_down`: asked, at each give-way, whether the pass should stop now. A pass given none runs as it always
    has and can never be stopped here, which is every pass that is not downtime work."""

    def __init__(self, stand_down: Optional[Callable[[], bool]] = None) -> None:
        self._slice = asyncio.get_running_loop().slow_callback_duration
        self._since = time.perf_counter()
        self._stand_down = stand_down

    async def __call__(self, at: Any = None) -> None:
        """Give the loop back if this pass has held it for its slice, and stop the pass if it must stand down.

        ASKED AFTER YIELDING, NEVER BEFORE. Whether the substrate has work to do can only have become true because
        something else ran, so the question is worth asking only once the loop has had its step. A pass is asked as
        often as it gives way, which is as often as its slice elapses, so a person arriving is noticed within one
        slice rather than at the end of the pass."""
        if time.perf_counter() - self._since >= self._slice:
            await asyncio.sleep(0)
            self._since = time.perf_counter()
            if self._stand_down is not None and self._stand_down():
                raise StandDown(at)
