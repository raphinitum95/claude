"""Being a polite client of a site that sits behind a WAF.

Several tests loading pages at once, each page pulling ~100 files, can trip a WAF's rate or concurrency limit: it then answers
HTTP 403 / 429 to everything, whatever the test does.  This object is shared by every test of a run and does three things:

* spaces out the *start* of page loads (``runner.min_page_load_gap_s``), so tests never all hit the site in the same instant;
* on a block, pauses every page load for ``runner.block_cooldown_s`` and takes one worker out of service for the rest of the run;
* lets a worker wait its turn (``slot``) when the run has been reduced.

There is one of these per *site* (the host the workbook opens), not one per process: several workbooks on the same workers usually target different
sites, and a block by one site's WAF says nothing about another's - it must not stall the others.  Workbooks that open the same host share theirs.
"""
from __future__ import annotations

import asyncio
import time


class Throttle:
    def __init__(self, min_gap_s: float, workers: int):
        self.min_gap_s = max(0.0, min_gap_s)
        self.limit = max(1, workers)                 # workers allowed to run a test right now
        self._until = 0.0                            # no page load before this (monotonic)
        self._last = 0.0                             # when the last page load was let through
        self._lock = asyncio.Lock()
        self.loaded_ok = False                       # some page of this run has loaded: a block after that is a rate limit, so waiting helps

    def cool_down(self, seconds: float, *, reduce: bool = True, running: int | None = None) -> bool:
        """The site blocked us.  Returns True when a worker was taken out of service (there is one fewer to run tests).

        Several workers are usually blocked in the same instant: that is one event, so only the first of them (the one that finds no
        cool-down running) takes a worker out of service.  ``running``: how many tests are going against this site right now; the
        limit comes down from that (workers the site was not using anyway are not "taken out of service")."""
        already_cooling = self.cooling > 0
        self._until = max(self._until, time.monotonic() + seconds)
        if reduce and not already_cooling:
            if running is not None:
                self.limit = max(1, min(self.limit, running))
            if self.limit > 1:
                self.limit -= 1
                return True
        return False

    def retry_budget(self, configured: int) -> int:
        """How many times a blocked test is run again.  A block after some page has loaded is a rate limit (waiting helps: the full
        ``configured`` budget).  A block when nothing has ever loaded from this machine is more likely a standing rule (allow-list, VPN,
        country): one retry after the pause, then stop."""
        return configured if self.loaded_ok else min(1, configured)

    @property
    def cooling(self) -> float:
        return max(0.0, self._until - time.monotonic())

    async def before_load(self, cancel: asyncio.Event | None = None) -> float:
        """Wait until a page load may start (cool-down over, minimum gap since the previous one).  Returns seconds waited."""
        started = time.monotonic()
        async with self._lock:                       # waiters are served one at a time, in order
            while True:
                now = time.monotonic()
                wait = max(self._until - now, self._last + self.min_gap_s - now)
                if wait <= 0 or (cancel is not None and cancel.is_set()):
                    break
                await asyncio.sleep(min(wait, 0.25))
            self._last = time.monotonic()
        return time.monotonic() - started

    async def slot(self, worker: int, cancel: asyncio.Event, drained=None) -> None:
        """A worker numbered above the current limit waits (the run was reduced after a block) - unless ``drained()`` says no test is left: a worker
        that was taken out of service must not keep the run alive once the others have finished everything."""
        while worker > self.limit and not cancel.is_set() and not (drained is not None and drained()):
            await asyncio.sleep(0.5)
