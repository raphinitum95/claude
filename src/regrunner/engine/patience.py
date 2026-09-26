"""Waiting on evidence instead of a clock.

A fixed time limit turns "slow" into "failed": on a busy machine (ten browsers, low priority, little memory) a page takes longer than any
limit sized for a quiet one.  So a wait here does not end when a clock runs out.  It ends when one of these is true:

* **settled** - the page has finished (no page load going, the document complete, none of its own requests in flight, the computer
  answering promptly) and has stayed so for the step's normal time (``quiet_s``: ``timeouts.element_s`` for an element...).  An element
  missing from a finished page is a real failure, and still fails in that time: slow is not the same as wrong;
* **stalled** - nothing on the page has moved at all (no request started or answered, no frame loaded, no page load) for
  ``patience.stall_s``: a request that never answers, a frozen page;
* **too long** - ``patience.max_wait_s`` has gone by, however busy the page keeps itself (a page that never stops working).

While the page is visibly working, the clock that ends a wait keeps being pushed back.  Nothing is ever repeated: a step is waited for,
never retried.  A wait that goes past the old fixed limit is announced on the run screen (``WaitNotice``: ``worker_waiting`` /
``worker_resumed``) and noted on the step, so a person always knows why a worker is not moving.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Activity:
    """What the page is doing right now (``BrowserSession.activity``)."""
    working: bool = False            # visibly still busy: loading, waiting for its own server, or the computer is too busy to answer
    why: str = ""                    # ...in words a non-technical person understands
    last_progress: float = field(default_factory=time.monotonic)      # when something last moved (monotonic)


class WaitNotice:
    """Tells the run screen that a worker is deliberately waiting, and why (events ``worker_waiting`` / ``worker_resumed``), and keeps a note
    for the step so the report says it afterwards.  One per test; the events are replayable (the screen rebuilds from the event stream)."""

    _ids = itertools.count(1)

    def __init__(self, bus=None, test: str = "", worker: int = 0):
        self.bus, self.test, self.worker = bus, test, worker
        self.step = 0                                        # the step being run (set by the test runner)
        self.notes: list[str] = []                           # for the current step; the test runner moves them onto the step
        self.open: dict[str, dict[str, Any]] = {}

    def begin(self, code: str, message: str, *, seconds: float | None = None) -> str:
        """A wait starts.  ``seconds`` when its length is known (the screen counts down); never put a secret or a code in ``message``."""
        wait_id = f"w{next(self._ids)}"
        self.open[wait_id] = {"code": code, "t0": time.monotonic()}
        if self.bus is not None:
            extra = {"seconds": round(float(seconds), 1)} if seconds is not None else {}
            self.bus.emit("worker_waiting", test=self.test, worker=self.worker, step=self.step, wait=wait_id, code=code, message=message, **extra)
        return wait_id

    def end(self, wait_id: str, note: str = "") -> float:
        """The wait is over.  Returns how long it took; ``note`` goes on the step."""
        info = self.open.pop(wait_id, None)
        waited = time.monotonic() - info["t0"] if info else 0.0
        if info and self.bus is not None:
            self.bus.emit("worker_resumed", test=self.test, worker=self.worker, step=self.step, wait=wait_id, code=info["code"],
                          waited_s=round(waited, 1))
        if note:
            self.notes.append(note)
        return waited

    def end_all(self) -> None:
        for wait_id in list(self.open):
            self.end(wait_id)

    def take_notes(self) -> list[str]:
        notes, self.notes = self.notes, []
        return notes


NO_NOTICE = WaitNotice()                                     # for code that runs without a test around it (unit tests)


def plain_seconds(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s} s" if s < 90 else f"{s // 60} min {s % 60:02d} s" if s < 3600 else f"{s // 3600} h {(s % 3600) // 60:02d} min"


class Patience:
    """One wait.  Call :meth:`give_up` between looks at whatever is being waited for; it answers whether to stop, and :attr:`reason` /
    :meth:`explain` say why.  Always call :meth:`done` afterwards (a ``with`` block does), so an announcement on the screen is taken down.

    ``quiet_s``: how long the page must have been finished (not working) before the wait ends - the old fixed limit of this wait.
    ``what``: what is being waited for, in plain words ("the element", "the page to finish loading").
    """

    def __init__(self, session, quiet_s: float, *, what: str = "", since: float | None = None, cfg=None, missing: str = ""):
        cfg = cfg or getattr(getattr(session, "cfg", None), "patience", None)
        if cfg is None:
            from ..config import PatienceCfg
            cfg = PatienceCfg()
        self.session, self.cfg = session, cfg
        self.plain = not cfg.enabled or not hasattr(session, "activity")   # no page to ask (a stand-in session): a plain time limit
        self.quiet_s = max(0.0, float(quiet_s))
        self.what = what or "the page"
        self.missing = missing or f"{self.what} did not appear"      # how the failure reads: "the element did not appear"
        self.started = time.monotonic()
        self.since = since                                   # only requests started after this count as the page working (a click's own calls)
        self.last_working = self.started
        self.activity = Activity(last_progress=self.started)
        self.reason = ""                                     # settled | stalled | too_long | "" (not given up)
        self.worked = False                                  # the page was busy at some point: the wait went on because of it
        self.notice = getattr(session, "notice", None) or NO_NOTICE
        self._told: str | None = None

    def __enter__(self) -> Patience:
        return self

    def __exit__(self, *exc) -> None:
        self.done()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    async def give_up(self) -> bool:
        now = time.monotonic()
        cancel = getattr(self.session, "cancel", None)
        if cancel is not None and cancel.is_set():            # the run is being cancelled: no step waits on for a slow page
            self.reason = "cancelled"
            return True
        if self.plain:                                        # the old behaviour: a plain time limit
            if now - self.started >= self.quiet_s:
                self.reason = "settled"
                return True
            return False
        act = self.activity = await self.session.activity(since=self.since)
        now = time.monotonic()
        if act.working:
            self.last_working, self.worked = now, True
        if now - self.last_working >= self.quiet_s:
            self.reason = "settled"
            return True
        if act.working and now - act.last_progress >= self.cfg.stall_s:     # (a quiet page is the settled case above)
            self.reason = "stalled"
            return True
        if now - self.started >= self.cfg.max_wait_s:
            self.reason = "too_long"
            return True
        if act.working and not self._told and now - self.started >= max(self.quiet_s, self.cfg.tell_after_s):
            self._told = self.notice.begin("slow_page", f"Waiting for {self.what}: {act.why}. The step waits for it instead of failing; "
                                           "a slow computer or a slow site is not a test failure.")
        return False

    def explain(self) -> str:
        """Why the wait ended (for the step's notes / error)."""
        if self.reason == "settled":
            if self.worked:
                return (f"the page was busy for a while, then had finished (nothing loading) for {plain_seconds(self.quiet_s)} "
                        f"and {self.missing} (waited {plain_seconds(self.elapsed)} in all)")
            return f"the page had finished loading and {self.missing} within {plain_seconds(self.quiet_s)}"
        if self.reason == "stalled":
            return (f"nothing on the page moved for {plain_seconds(self.cfg.stall_s)} ({self.activity.why or 'no request, no page load'}), "
                    f"so it is stuck rather than slow (patience.stall_s)")
        if self.reason == "cancelled":
            return "the run was cancelled"
        if self.reason == "too_long":
            return (f"the page was still working after {plain_seconds(self.cfg.max_wait_s)} ({self.activity.why or 'busy'}), the most any "
                    "one wait may take (patience.max_wait_s)")
        return ""

    @property
    def on_settled_page(self) -> bool:
        """The wait ended with the page finished (or stuck): a failure now says something about where the page is, not about speed."""
        return self.reason in ("settled", "stalled", "too_long")

    def done(self) -> None:
        if self._told is not None:
            told, self._told = self._told, None
            self.notice.end(told, f"waited {plain_seconds(self.elapsed)} for {self.what}: the page was slow ({self.activity.why or 'busy'})")
