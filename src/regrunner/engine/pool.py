"""The workers of one process, shared by every run in it.

Several workbooks can be run at once: each is still its own run (own folder, events, results and report), but they draw on one set of
workers.  A free worker goes to the run that has the fewest tests going (the first of them on a tie), so the workers split evenly between
the runs that have something to start, and when a run has nothing ready (its tests wait for one another, or it is finished) the others get
its share.  A run can join while others are going (``joinable``: the web UI's runs), and then the workers idle until the pool is closed.
"""
from __future__ import annotations

import asyncio
from typing import Any


class Pool:
    def __init__(self, cancel: asyncio.Event, joinable: bool = False, gate=None):
        self.cancel = cancel                            # the whole process is being stopped (Ctrl+C / SIGTERM)
        self.joinable = joinable
        self.gate = gate                                # run -> True when its site has as many tests going as it may have right now (after a block)
        self.runs: list[Any] = []                       # objects with .schedule, .cancel and .ended (see runner.RunCtx)
        self.closed = False                             # no run will be started any more: idle workers go home
        self.changed = asyncio.Condition()              # (built inside a coroutine: Python 3.9 binds it to the loop that is current)

    # -- what is left -----------------------------------------------------------------------------------------
    def add(self, run: Any) -> None:
        self.runs.append(run)

    def _live(self):
        return [r for r in self.runs if not r.ended]

    def pending(self) -> bool:
        """Some run that is still going has a test that has not started."""
        return any(r.schedule.pending and not r.cancel.is_set() for r in self._live())

    def drained(self) -> bool:
        """Nothing is left to start (used to let a worker that was taken out of service go home)."""
        return self.closed or (not self.joinable and not self.pending())

    def all_over(self) -> bool:
        """No run that is going has a test running or waiting to start."""
        return all(r.ended or (r.schedule.running == 0 and (not r.schedule.pending or r.cancel.is_set())) for r in self.runs)

    def outstanding(self) -> int:
        """Tests that still have to run or are running, over the runs that are going."""
        return sum(r.schedule.pending + r.schedule.running for r in self._live() if not r.cancel.is_set())

    # -- handing out tests ----------------------------------------------------------------------------------
    def _pick(self):
        best = None
        for index, run in enumerate(self.runs):
            if run.ended or run.cancel.is_set() or (self.gate is not None and self.gate(run)):
                continue
            case = run.schedule.next_ready()
            if case is None:
                continue
            key = (run.schedule.running, index)
            if best is None or key < best[0]:
                best = (key, run, case)
        if best is None:
            return None
        _, run, case = best
        run.schedule.start(case)
        return run, case

    async def take(self):
        """``(run, test)`` for a free worker, waiting until one is ready; ``None`` when the worker should go home."""
        async with self.changed:
            while True:
                if self.cancel.is_set() or self.closed:
                    return None
                picked = self._pick()
                if picked is not None:
                    return picked
                if not self.joinable and not self.pending():
                    return None
                try:
                    await asyncio.wait_for(self.changed.wait(), 0.5)         # (woken by a test finishing or a run joining; the timeout notices a cancel)
                except asyncio.TimeoutError:
                    pass

    async def finished(self, run: Any, case_id: str) -> None:
        async with self.changed:
            run.schedule.finish(case_id)
            self.changed.notify_all()

    async def wake(self) -> None:
        async with self.changed:
            self.changed.notify_all()

    async def close(self) -> None:
        self.closed = True
        await self.wake()

    async def run_is_over(self, run: Any, abandoned=lambda: False) -> None:
        """Wait until none of ``run``'s tests is going and it has nothing (more) to start - or it is cancelled and its running tests have ended."""
        async with self.changed:
            while not (run.schedule.running == 0 and (not run.schedule.pending or run.cancel.is_set())) and not abandoned():
                try:
                    await asyncio.wait_for(self.changed.wait(), 0.5)
                except asyncio.TimeoutError:
                    pass
