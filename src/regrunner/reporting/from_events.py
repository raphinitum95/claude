"""Rebuild a result set from ``events.jsonl`` when a run stopped without writing its final results.

A run can end abruptly (the computer slept, the process was killed).  Every step it completed is still in
the event log, so the evidence can be recovered: finished tests keep their status, tests that were mid-flight
are marked INTERRUPTED and tests that never started are marked QUEUED.  Fields the event stream does not
carry (per-comparison mode, exact timings) are left empty; repeat counts of review items restart at 1.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..events import read_events
from ..runmeta import read_meta
from .results import RunResult, StepRecord, TestResult

_REVIEW_TYPES = ("console_error", "network_error", "review_item")


def results_from_events(run_dir: Path) -> RunResult:
    events, _ = read_events(run_dir / "events.jsonl", 0)
    meta = read_meta(run_dir) or {}
    start = next((e for e in events if e["type"] == "run_started"), None)
    if start is None:
        raise ValueError("The event log has no run_started event; nothing to rebuild")
    result = RunResult(run_id=start["run_id"], workbook=start.get("workbook", meta.get("workbook", "")),
                       environment=start.get("environment", ""), started_at=start["ts"], workers=start.get("workers", 1),
                       seed=start.get("seed"), warnings=list(start.get("warnings", [])), partial=True,
                       browser=dict(start.get("browser") or meta.get("browser") or {}))
    tests: dict[str, TestResult] = {}
    for t in start.get("tests", []):
        tests[t["id"]] = TestResult(id=t["id"], title=t.get("title", t["id"]), scenario=t.get("scenario", ""),
                                    description=t.get("description", ""), total_steps=t.get("total_steps", 0))
    finished: set[str] = set()
    last_ts = start["ts"]
    for e in events:
        last_ts = e["ts"]
        kind, test = e["type"], tests.get(e.get("test", ""))
        if kind == "test_started" and test:
            test.status, test.started_at, test.attempt = "RUNNING", e["ts"], e.get("attempt", 1)
            test.steps.clear()                                     # a retry starts the test over
            test.review.clear()
            test.variables.clear()
        elif kind in ("step_passed", "step_failed") and test:
            test.steps.append(StepRecord(
                seq=e["step"], row=e.get("row", 0), name=e.get("name", ""), action=e.get("action", ""),
                status=e.get("status", "PASSED" if kind == "step_passed" else "FAILED"), error=e.get("error", ""),
                expected=e.get("expected", ""), actual=e.get("actual", ""), locator=e.get("locator", ""),
                locator_origin=e.get("locator_origin", ""), comparison=e.get("comparison", ""),
                fallback_used=bool(e.get("fallback")), notes=list(e.get("notes", [])), ended_at=e["ts"], duration_ms=e.get("duration_ms", 0),
                screenshot=e.get("screenshot"), screenshot_full=e.get("screenshot_full"), sets=list(e.get("sets", [])), detail=e.get("detail", ""), diagnosis=e.get("diagnosis")))
            test.variables.extend({**w, "seq": e["step"], "row": e.get("row", 0), "step": e.get("name", ""), "by_hand": False} for w in e.get("sets", []))
        elif kind == "variable_set" and test and e.get("by_hand", True):          # (a value a step saved is in that step's ``sets`` already)
            test.variables.append({"name": e.get("name", ""), "value": e.get("value", ""), "stored": e.get("value", ""), "cell": e.get("cell", ""),
                                   "seq": e.get("step", 0), "row": 0, "step": "", "by_hand": bool(e.get("by_hand"))})
        elif kind == "screenshot_saved" and test:
            for step in reversed(test.steps):
                if step.seq == e["step"]:
                    step.screenshot, step.box = e.get("path"), e.get("box")
                    break
        elif kind in _REVIEW_TYPES and test:
            item = {k: v for k, v in e.items() if k not in ("ts", "run_id")}
            test.review.append(item)
        elif kind == "test_finished" and test:
            test.status = e["status"]
            test.passed, test.failed, test.skipped = e.get("passed", 0), e.get("failed", 0), e.get("skipped", 0)
            test.duration_s, test.error, test.ended_at = e.get("duration_s", 0.0), e.get("error", ""), e["ts"]
            for item, count in zip(test.review, e.get("review_counts", [])):
                item["count"] = count
            finished.add(test.id)
        elif kind == "run_finished":
            result.status, result.ended_at = e.get("status", "INTERRUPTED"), e["ts"]
    for test in tests.values():
        if test.id in finished:
            continue
        test.passed = sum(s.status == "PASSED" for s in test.steps)
        test.failed = sum(s.status == "FAILED" for s in test.steps)
        if test.status == "RUNNING":
            test.status, test.error = "INTERRUPTED", "The run stopped while this test was running"
        else:
            test.status, test.error = "QUEUED", "The run stopped before this test started"
    if result.status == "RUNNING":
        result.status, result.ended_at = "INTERRUPTED", last_ts
    result.tests = list(tests.values())
    try:
        result.duration_s = round((datetime.fromisoformat(result.ended_at) - datetime.fromisoformat(result.started_at)).total_seconds(), 2)
    except ValueError:
        pass
    return result
