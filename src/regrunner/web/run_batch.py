"""Batches: a UI label tying together the individual runs started from one "New run" screen, or added later with
"Add tests to this batch" (dev/plan/CONTRACT.md; engineering doc section 5, "Run and Results tabs, and batches").

A batch never changes how a run executes: each workbook launched together is still its own run, with its own id,
folder, ``results.json``, ``events.jsonl`` and report.  The only addition is ``batch_id`` / ``batch_label`` in each
run's ``run.json`` (written by ``RunManager._start`` in ``web/app.py``); this module only reads that and groups runs
by it.  Kept out of ``web/app.py`` so parallel phases do not collide there, the same as ``web/build_api.py``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from ..runmeta import read_meta

_TERMINAL_STATUSES = {"PASSED", "FAILED", "ERROR", "CANCELLED", "INTERRUPTED", "INCOMPLETE"}


class BatchApiError(HTTPException):
    def __init__(self, status: int, message: str, kind: str = "", **extra: Any):
        super().__init__(status, message)
        self.kind, self.extra = kind, extra


def _workbook_name(meta: dict[str, Any]) -> str:
    return Path(str(meta.get("workbook", ""))).name


def _tests_of(meta: dict[str, Any]) -> int:
    return meta.get("tests") or len(meta.get("test_ids") or [])


def _done_tests_of(meta: dict[str, Any]) -> int:
    """How many of a run's tests are no longer pending, for the batch's overall percent."""
    if meta.get("active"):
        return (meta.get("progress") or {}).get("done", 0)
    return _tests_of(meta) if meta.get("status") in _TERMINAL_STATUSES else 0


def batch_summary(batch_id: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    runs = sorted(runs, key=lambda m: m.get("started_at") or "")
    label = next((m.get("batch_label") for m in runs if m.get("batch_label")), "") or f"Batch {batch_id}"
    active = [m for m in runs if m.get("active")]
    finished = [m for m in runs if not m.get("active")]
    passed = sum(1 for m in finished if m.get("status") == "PASSED")
    failed = sum(1 for m in finished if m.get("status") in ("FAILED", "ERROR", "INCOMPLETE"))
    other = len(finished) - passed - failed
    total_tests = sum(_tests_of(m) for m in runs)
    done_tests = sum(_done_tests_of(m) for m in runs)
    return {
        "id": batch_id, "label": label, "run_ids": [m["run_id"] for m in runs],
        "workbooks": [_workbook_name(m) for m in runs], "active": bool(active),
        "started_at": runs[0].get("started_at") if runs else None,
        "environment": next((m.get("environment") for m in runs if m.get("environment")), ""),
        "tests": total_tests, "percent": round(100 * done_tests / total_tests) if total_tests else 0,
        "passed": passed, "failed": failed, "other": other, "finished": len(finished), "total": len(runs),
    }


def _scan_last_durations(runs_dir: Path, names: set[str]) -> dict[str, dict[str, float]]:
    """Each named workbook's most recent finished run with a ``results.json``: ``{test id: seconds}``.  A workbook with no
    finished run of its own (or no results.json) is left out; the Timeline plan view falls back to something else
    (step counts) for it."""
    candidates: list[tuple[str, Path]] = []
    for d in runs_dir.iterdir():
        if not d.is_dir():
            continue
        meta = read_meta(d)
        if not meta or meta.get("status") == "RUNNING":
            continue
        if _workbook_name(meta) in names:
            candidates.append((meta.get("started_at") or "", d))
    out: dict[str, dict[str, float]] = {}
    for _started, d in sorted(candidates, key=lambda x: x[0], reverse=True):
        meta = read_meta(d) or {}
        name = _workbook_name(meta)
        if name in out:
            continue
        results = d / "results.json"
        if not results.is_file():
            continue
        try:
            data = json.loads(results.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[name] = {t["id"]: t.get("duration_s") or 0 for t in data.get("tests", []) if t.get("id")}
        if len(out) == len(names):
            break
    return out


def register_batch_routes(app: FastAPI, mgr: Any) -> None:
    """Add the batch routes.  ``mgr`` is the ``RunManager`` (``list_runs``, ``runs_dir``); the request guard and error shape of
    ``create_app`` (localhost Host, ``X-Requested-With`` + local Origin on POST) already cover these routes."""

    @app.exception_handler(BatchApiError)
    async def batch_error(_, exc: BatchApiError):
        return JSONResponse({"error": exc.detail, "kind": exc.kind, **exc.extra}, status_code=exc.status_code)

    def grouped(metas: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for meta in metas:
            bid = meta.get("batch_id")
            if bid:
                groups.setdefault(bid, []).append(meta)
        return groups

    @app.get("/api/batches")
    async def list_batches():
        groups = grouped(await asyncio.to_thread(mgr.list_runs, 1000))
        return sorted((batch_summary(bid, runs) for bid, runs in groups.items()),
                     key=lambda b: b["started_at"] or "", reverse=True)

    @app.get("/api/batches/{batch_id}")
    async def batch_detail(batch_id: str):
        groups = grouped(await asyncio.to_thread(mgr.list_runs, 1000))
        runs = groups.get(batch_id)
        if not runs:
            raise BatchApiError(404, "batch not found", "not_found")
        return {**batch_summary(batch_id, runs), "runs": sorted(runs, key=lambda m: m.get("started_at") or "")}

    @app.post("/api/batches/last-durations")
    async def last_durations(body: dict[str, Any]):
        names = {str(n) for n in (body.get("workbooks") or []) if str(n)}
        if not names:
            return {}
        return await asyncio.to_thread(_scan_last_durations, mgr.runs_dir(), names)
