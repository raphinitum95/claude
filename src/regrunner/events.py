"""Structured run events.

The runner never prints.  It emits events on an :class:`EventBus`; everything else is a listener:

* :class:`JsonlListener`   - durable ``events.jsonl`` (the web UI tails it; past runs replay from it)
* :class:`ProgressTracker` - derives ``run_progress`` (per-test and global percentages)
* console listener         - Rich live view or plain lines (``reporting/console.py``)
* results collector        - builds ``results.json`` and the HTML/PDF report

Event types (all carry ``type``, ``ts`` and ``run_id``):

    run_started    workbook, environment, workers, tests:[{id,title,total_steps,description}]
    test_started   test, title, total_steps, worker
    step_started   test, step, total_steps, row, name, action
    step_passed    test, step, total_steps, row, name, action, status, duration_ms, expected, actual,
    step_failed      error, locator, notes, screenshot, [timing]  (step_failed also on FAILED status; timing: engine/timing.py)
    step_skipped   test, step (None), total_steps, row, name, action, reason     a planned step that does not run (the IF above it was false...)
    variable_set   test, step, row, name, value, cell, by_hand   a value a person supplied (by_hand) or a step saved into the run's variables
                   (cell "run variable": not a Params column); value is masked when secret; the step's own ``sets`` list it too
    branch_taken   test, step, row, condition, result (bool)        an IF step decided
    iteration_started  test, step, row, sheet, iteration, of        a loop (ITERATION_START) begins its n-th data row (1-based)
    call_started   test, step, row, called, status ("RUNNING")      CALL_TEST starts another test; its steps follow as steps of this test
    call_finished  test, step, row, called, status                  ...and it ended (status of the called test)
    env_missing    environment, variables:[..], message             a required environment variable has no value: the run did not start
    screenshot_saved  test, step, path, kind
    console_error  test, step, kind, message, url          (kind: console|pageerror)
    network_error  test, step, kind, url, status, method, message   (kind: requestfailed|http_error)
    review_item    test, step, category, severity, message           (selector fallback, ignored error ...)
    test_finished  test, status, passed, failed, skipped, duration_s, error      (status NOT_RUN: the machine could not run it; run again)
    worker_waiting   test, worker, step, wait, code, message, [seconds]   a worker waits on purpose (code: login_code | slow_page | infra_rerun)
    worker_resumed   test, worker, step, wait, code, waited_s             ...and that wait is over
    run_progress   done, total, percent, tests:{id:{done,total,percent,status}}
    run_finished   status, summary, artifacts
    log            level, message
"""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

Event = dict[str, Any]
Listener = Callable[[Event], None]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


class EventBus:
    """Ordered fan-out. Listeners that emit while handling an event are queued, never interleaved."""

    def __init__(self, run_id: str = ""):
        self.run_id = run_id
        self._listeners: list[Listener] = []
        self._queue: deque[Event] = deque()
        self._draining = False
        self._lock = threading.RLock()

    def subscribe(self, listener: Listener) -> Listener:
        self._listeners.append(listener)
        return listener

    def emit(self, type_: str, **fields: Any) -> Event:
        event: Event = {"type": type_, "ts": now_iso(), "run_id": self.run_id, **fields}
        with self._lock:
            self._queue.append(event)
            if self._draining:
                return event
            self._draining = True
            try:
                while self._queue:
                    current = self._queue.popleft()
                    for listener in list(self._listeners):
                        try:
                            listener(current)
                        except Exception as err:            # a bad listener must never break a run
                            if current["type"] != "log":
                                self._queue.append({"type": "log", "ts": now_iso(), "run_id": self.run_id,
                                                    "level": "error",
                                                    "message": f"listener {getattr(listener, '__name__', listener)}"
                                                               f" failed: {err!r}"})
            finally:
                self._draining = False
        return event


class JsonlListener:
    """Append every event to ``events.jsonl`` (flushed per event so tailing readers stay live)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8", buffering=1)

    def __call__(self, event: Event) -> None:
        self._fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def close(self) -> None:
        self._fh.close()


class ProgressTracker:
    """Turns step events into ``run_progress`` events with per-test and global percentages."""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self.tests: dict[str, dict[str, Any]] = {}
        bus.subscribe(self.on_event)

    def on_event(self, event: Event) -> None:
        kind = event["type"]
        if kind == "run_started":
            for t in event.get("tests", []):
                self.tests[t["id"]] = {"done": 0, "total": t.get("total_steps", 0), "status": "queued"}
            self._emit()
        elif kind == "test_started":
            t = self.tests.setdefault(event["test"], {"done": 0, "total": 0, "status": "queued"})
            t.update(status="running", total=event.get("total_steps", t["total"]))
            if event.get("attempt", 1) > 1:
                t["done"] = 0                                     # a test that starts over (retry) counts from its first step again
            self._emit()
        elif kind == "run_paused" or (kind == "worker_waiting" and event.get("code") == "infra_rerun"):   # the attempt that just ended is run again: not finished
            t = self.tests.get(event.get("test", ""))
            if t is not None:
                t.update(done=0, status="queued")
                self._emit()
        elif kind in ("step_passed", "step_failed", "step_skipped"):
            t = self.tests.setdefault(event["test"], {"done": 0, "total": 0, "status": "running"})
            t["done"] += 1
            t["total"] = max(t["total"], t["done"], event.get("total_steps", 0) or 0)
            self._emit()
        elif kind == "test_finished":
            t = self.tests.setdefault(event["test"], {"done": 0, "total": 0, "status": "running"})
            t["status"] = event.get("status", "finished").lower()
            t["done"] = t["total"] = max(t["done"], t["total"])
            self._emit()

    def _emit(self) -> None:
        done = sum(t["done"] for t in self.tests.values())
        total = sum(t["total"] for t in self.tests.values())
        tests = {k: {**v, "percent": _pct(v["done"], v["total"])} for k, v in self.tests.items()}
        self.bus.emit("run_progress", done=done, total=total, percent=_pct(done, total), tests=tests)


def _pct(done: int, total: int) -> float:
    return round(100.0 * done / total, 1) if total else 0.0


def read_events(path: Path, offset: int = 0) -> tuple[list[Event], int]:
    """Read complete JSON lines from ``path`` starting at byte ``offset``; returns (events, new_offset)."""
    if not path.is_file():
        return [], offset
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
    events: list[Event] = []
    consumed = 0
    for raw in data.splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break                                            # partial line: wait for the writer to finish it
        consumed += len(raw)
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return events, offset + consumed
