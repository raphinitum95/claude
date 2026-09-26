"""Where a test's time went: the site, a deliberate wait, the runner itself, or a computer too busy to keep up.

"The test took 10 minutes in a run of 20 and 5 alone" says nothing about what to fix.  Each step's wall time is split into parts that
never overlap, in this order of precedence:

* **wait** - a wait the runner chose (the page-load spacing ``runner.min_page_load_gap_s``, a login code's 30 s window, a question to a
  person, a captcha solved by hand).  Its parts are kept by kind (``wait_kinds``);
* **site** - at least one of the site's own requests (a page, its files, its XHR/fetch calls; not third-party traffic, not polling) was in
  flight and the runner was not in a deliberate wait: the site was answering;
* **runner** - the runner's own work while the site had answered: screenshots, failure evidence, the quiet windows before acting, the
  captcha check.  Its parts are kept by kind (``runner_kinds``);
* **computer** - the page's own heartbeat ran late (the tab could not get the processor): what an overloaded machine costs;
* **other** - the rest: Playwright acting on the page, the browser drawing, the workbook's own Wait rows.

The split is an estimate from what the runner can see (the browser's request events, a heartbeat inside the page), not a profile, and is
labelled so.  The *queue* time (from when a test could start to when a worker took it) is not part of a test's duration: it is kept
separately (``queue_s``), so a crowded run shows as a longer run, not as slower tests.
"""
from __future__ import annotations

import contextlib
import hashlib
import time
from typing import Any

PARTS = ("wait", "site", "runner", "computer", "other")


class SiteClock:
    """How long the site has had at least one of its own requests in flight, summed over the test (all its windows)."""

    def __init__(self):
        self._inflight: set[Any] = set()
        self._total = 0.0
        self._since: float | None = None

    def started(self, request: Any) -> None:
        if not self._inflight:
            self._since = time.monotonic()
        self._inflight.add(request)

    def ended(self, request: Any) -> None:
        if request in self._inflight:
            self._inflight.discard(request)
            if not self._inflight and self._since is not None:
                self._total += time.monotonic() - self._since
                self._since = None

    def forget(self, requests) -> None:
        """A window closed: its requests will never answer (they must not count as the site working for ever)."""
        for request in list(requests):
            self.ended(request)

    def busy_s(self) -> float:
        return self._total + (time.monotonic() - self._since if self._since is not None else 0.0)


class Timing:
    """One test's time split (see the module docstring).  Cheap: a few counters; never raises into the test."""

    def __init__(self):
        self.site = SiteClock()
        self._waits: dict[str, float] = {}
        self._overhead: dict[str, float] = {}
        self._lag = 0.0
        self._open = 0                                            # spans nest (a screenshot inside failure evidence): only the outermost counts
        self._step: dict[str, Any] | None = None
        self.totals: dict[str, float] = {p: 0.0 for p in PARTS}
        self.waits: dict[str, float] = {}
        self.overhead: dict[str, float] = {}

    # -- recording ---------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def span(self, part: str, kind: str):
        """``part`` "wait" (a deliberate wait) or "runner" (the runner's own work) of kind ``kind`` ("pacing", "screenshot"...)."""
        if self._open:
            yield
            return
        self._open += 1
        t0, busy0 = time.monotonic(), self.site.busy_s()
        try:
            yield
        finally:
            self._open -= 1
            wall = time.monotonic() - t0
            busy = min(wall, max(0.0, self.site.busy_s() - busy0))
            if part == "wait":
                self._waits[kind] = self._waits.get(kind, 0.0) + wall
                self._waits["_site"] = self._waits.get("_site", 0.0) + busy     # (the site answering during a deliberate wait is the wait's)
            else:
                self._overhead[kind] = self._overhead.get(kind, 0.0) + max(0.0, wall - busy)

    def lagged(self, seconds: float) -> None:
        """The page's heartbeat ran this late: the tab was not getting the processor."""
        if seconds > 0:
            self._lag += seconds

    # -- per step --------------------------------------------------------------------------------------------
    def step_started(self) -> None:
        self._waits, self._overhead, self._lag = {}, {}, 0.0
        self._step = {"t0": time.monotonic(), "busy0": self.site.busy_s()}

    def step_ended(self) -> dict[str, Any]:
        """The step's split in ms (parts sum to the step's wall time), with the kinds of wait and runner work."""
        st = self._step or {"t0": time.monotonic(), "busy0": self.site.busy_s()}
        self._step = None
        wall = max(0.0, time.monotonic() - st["t0"])
        busy = max(0.0, self.site.busy_s() - st["busy0"])
        waits = {k: v for k, v in self._waits.items() if k != "_site"}
        left = wall
        split: dict[str, float] = {}
        for part, amount in (("wait", sum(waits.values())), ("site", busy - self._waits.get("_site", 0.0)),
                             ("runner", sum(self._overhead.values())), ("computer", self._lag)):
            split[part] = min(left, max(0.0, amount))
            left -= split[part]
        split["other"] = max(0.0, left)
        for part, seconds in split.items():
            self.totals[part] += seconds
        for kind, seconds in waits.items():
            self.waits[kind] = self.waits.get(kind, 0.0) + seconds
        for kind, seconds in self._overhead.items():
            self.overhead[kind] = self.overhead.get(kind, 0.0) + seconds
        out: dict[str, Any] = {f"{p}_ms": int(round(s * 1000)) for p, s in split.items()}
        if waits:
            out["wait_kinds_ms"] = {k: int(round(v * 1000)) for k, v in waits.items()}
        if self._overhead:
            out["runner_kinds_ms"] = {k: int(round(v * 1000)) for k, v in self._overhead.items()}
        return out

    # -- per test --------------------------------------------------------------------------------------------
    def summary(self, duration_s: float) -> dict[str, Any]:
        """The whole test (time outside any step - opening and closing the window - is "other")."""
        parts = {p: round(s, 2) for p, s in self.totals.items()}
        parts["other"] = round(max(0.0, duration_s - sum(v for k, v in parts.items() if k != "other")), 2)
        return {**{f"{p}_s": v for p, v in parts.items()},
                "wait_kinds_s": {k: round(v, 2) for k, v in sorted(self.waits.items())},
                "runner_kinds_s": {k: round(v, 2) for k, v in sorted(self.overhead.items())}}


class _NoSiteClock(SiteClock):
    def started(self, request: Any) -> None:
        pass


class _NoTiming(Timing):
    """For code that runs without a test around it (a stand-in session in unit tests): records nothing, holds on to nothing."""

    def __init__(self):
        super().__init__()
        self.site = _NoSiteClock()

    @contextlib.contextmanager
    def span(self, part: str, kind: str):
        yield

    def lagged(self, seconds: float) -> None:
        pass


def timing_of(obj: Any) -> Timing:
    """The Timing of a session / step context, or one that records nothing."""
    found = getattr(obj, "timing", None)
    if found is None and hasattr(obj, "session"):
        found = getattr(getattr(obj, "session", None), "timing", None)
    return found if isinstance(found, Timing) else NO_TIMING


NO_TIMING = _NoTiming()


def fingerprint_site_code(files: dict[str, str]) -> dict[str, Any]:
    """The "site version": one short hash over the site's own code files (path + version) a test loaded.  The same files at the same versions
    give the same fingerprint; a deployment changes it.  Paths and validators only: nothing a person typed, no query strings."""
    if not files:
        return {}
    digest = hashlib.sha1("\n".join(f"{path} {files[path]}" for path in sorted(files)).encode("utf-8")).hexdigest()[:12]
    return {"fingerprint": digest, "files": len(files)}


def run_summary(tests: list[Any]) -> dict[str, Any]:
    """Totals over a run's tests (``TestResult.timing`` dicts): what the report's "where the time went" line says."""
    total: dict[str, float] = {f"{p}_s": 0.0 for p in PARTS}
    waits: dict[str, float] = {}
    overhead: dict[str, float] = {}
    queue = 0.0
    counted = 0
    for test in tests:
        timing = test.get("timing") if isinstance(test, dict) else getattr(test, "timing", None)
        if not timing:
            continue
        counted += 1
        for key in total:
            total[key] += float(timing.get(key) or 0.0)
        for kind, s in (timing.get("wait_kinds_s") or {}).items():
            waits[kind] = waits.get(kind, 0.0) + float(s)
        for kind, s in (timing.get("runner_kinds_s") or {}).items():
            overhead[kind] = overhead.get(kind, 0.0) + float(s)
        queue += float(timing.get("queue_s") or 0.0)
    return {"tests": counted, **{k: round(v, 1) for k, v in total.items()}, "queue_s": round(queue, 1),
            "wait_kinds_s": {k: round(v, 1) for k, v in sorted(waits.items())}, "runner_kinds_s": {k: round(v, 1) for k, v in sorted(overhead.items())}}


def describe(summary: dict[str, Any]) -> str:
    """One line for a person: "site 3 min 10 s (61%) · deliberate waits 1 min 02 s (20%) · ..."."""
    from .patience import plain_seconds
    labels = {"site_s": "the site", "wait_s": "deliberate waits", "runner_s": "the runner's own work", "computer_s": "busy computer",
              "other_s": "browser / actions"}
    busy = sum(float(summary.get(k) or 0.0) for k in labels)
    if busy <= 0:
        return ""
    parts = [f"{label} {plain_seconds(float(summary.get(k) or 0.0))} ({100 * float(summary.get(k) or 0.0) / busy:.0f}%)"
             for k, label in labels.items() if float(summary.get(k) or 0.0) >= 0.05]
    line = " · ".join(parts)
    if float(summary.get("queue_s") or 0.0) >= 0.5:
        line += f" · plus {plain_seconds(float(summary['queue_s']))} in the queue before starting (not counted in test times)"
    return line
