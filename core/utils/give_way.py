"""A long pass on the substrate's own event loop gives the loop back BY TIME, not by count.

The substrate is one event loop: the coordinator, the queue's scheduled jobs, every database query and the memory
agent's writes all take their turns on it. A pass that walks a corpus on it (saying 157,786 facts, reading each said
sentence, observing each held belief) holds the loop for as long as it runs without awaiting.

It used to give way every hundred facts. A hundred facts are three to six seconds of reading, and a give-way is ONE
step for everything else, so a query that needs a dozen steps took over a minute: WordNet's sandbox run of 2026-10-08
timed out every query and every scheduled job while it said its facts. What a pass may hold the loop for is the
loop's own measure of too long (`slow_callback_duration`), whatever one item of it costs.
"""

import asyncio
import time


class GiveWay:
    """Awaited once per item of a long pass; yields to the loop when the pass has held it for its slice."""

    def __init__(self) -> None:
        self._slice = asyncio.get_running_loop().slow_callback_duration
        self._since = time.perf_counter()

    async def __call__(self) -> None:
        if time.perf_counter() - self._since >= self._slice:
            await asyncio.sleep(0)
            self._since = time.perf_counter()
