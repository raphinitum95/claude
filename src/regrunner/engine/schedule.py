"""Which test a free worker takes next: the first one, in priority order, whose dependencies (engine/order.py) have all finished.

A test that has to wait is *held in the queue* rather than started and paused: a paused test would keep a worker, and with a few workers
all taken by tests waiting for one that has not started, the run would never finish.

One :class:`Schedule` belongs to one run.  When several runs share the workers of a process, ``engine/pool.py`` asks each run's schedule
``next_ready`` and hands the worker to the run with the fewest tests going.
"""
from __future__ import annotations

import asyncio
import time


class Schedule:
    def __init__(self, cases: list, deps: dict[str, list[str]]):
        self._pending = list(cases)                    # in priority order
        self._deps = deps
        self._done: set[str] = set()
        self._running = 0
        self.opened = time.monotonic()
        self.ready_at: dict[str, float] = {c.id: self.opened for c in cases if not deps.get(c.id)}   # when each test could have started (queue time)
        self._changed = asyncio.Condition()            # (built inside execute(): Python 3.9 binds it to the loop that is current)

    @property
    def pending(self) -> int:
        """Tests that have not started."""
        return len(self._pending)

    @property
    def running(self) -> int:
        """Tests being run right now."""
        return self._running

    def drained(self) -> bool:
        """Nothing is left to start (tests may still be running)."""
        return not self._pending

    def waiting_for(self, case_id: str) -> list[str]:
        return [d for d in self._deps.get(case_id, []) if d not in self._done]

    def next_ready(self):
        """The test that may start now, or ``None`` (nothing left, or everything left waits for a test that is still going).  Does not start it."""
        ready = next((c for c in self._pending if not self.waiting_for(c.id)), None)
        if ready is None and self._pending and self._running == 0:
            ready = self._pending[0]                   # nothing can ever become ready (a cycle nobody caught): run in order rather than hang
        return ready

    def start(self, case) -> None:
        self._pending.remove(case)
        self._running += 1

    def finish(self, case_id: str) -> None:
        self._done.add(case_id)
        self._running -= 1
        now = time.monotonic()
        for case in self._pending:
            if case.id not in self.ready_at and not self.waiting_for(case.id):
                self.ready_at[case.id] = now                 # its last dependency just finished: from here on it only waits for a worker

    def queued_s(self, case_id: str) -> tuple[float, float]:
        """(seconds a test that has just started waited for a worker once it could run, seconds it waited for the tests it depends on)."""
        now = time.monotonic()
        ready = self.ready_at.get(case_id, now)
        return max(0.0, now - ready), max(0.0, ready - self.opened)

    async def take(self, cancel: asyncio.Event):
        """The next test that may start, waiting for one to become ready; ``None`` when nothing is left (or the run is cancelled)."""
        async with self._changed:
            while True:
                if cancel.is_set() or not self._pending:
                    return None
                ready = self.next_ready()
                if ready is not None:
                    self.start(ready)
                    return ready
                try:
                    await asyncio.wait_for(self._changed.wait(), 0.5)        # (woken by a test finishing; the timeout notices a cancel)
                except asyncio.TimeoutError:
                    pass

    async def finished(self, case_id: str) -> None:
        async with self._changed:
            self.finish(case_id)
            self._changed.notify_all()
