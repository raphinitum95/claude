"""Results tab: history list, batch page (causes, trend, what changed, re-run), test page (block map, backup locators,
this test's history), compare (dev/plan/phases/P06-results-tab.md; CONTRACT.md "Runs and batches stay under /api/runs,
/api/batches").  Batch *grouping* is still ``web/run_batch.py``'s; this module reads the same run folders
(``results.json``) plus the workbook itself (``workbook/builder.py``, read-only: never writes) to answer the extra
questions the Results screens need.

The heavy lifting (``build_batch_page``, ``rerun_plan``, ``build_test_page``, ``build_compare``) takes plain paths and
data, not the ``RunManager``, so it can be unit-tested without a running server - the same shape as
``web/run_batch.py``'s ``batch_summary`` / ``_scan_last_durations``.  Kept out of ``web/app.py`` so parallel phases do
not collide there.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .. import history
from ..runmeta import new_batch_id, read_meta, update_meta
from ..workbook.builder import build_model
from ..workbook.writer import WorkbookEditor
from .run_batch import batch_summary

# Order matters: shown top to bottom on the batch page ("start at the top; the ones below often go away once it's fixed").
CAUSE_ORDER = ["gate", "unmet_dependency", "element_missing", "site_said_no", "waf", "captcha", "infra", "cancelled", "interrupted", "other"]
CAUSE_TITLES = {
    "gate": "Never reached a page", "unmet_dependency": "Needs a value that was never set", "element_missing": "Element not found",
    "site_said_no": "Wrong value", "waf": "Blocked by the site", "captcha": "Captcha", "infra": "Could not run (machine problem)",
    "cancelled": "Cancelled", "interrupted": "Interrupted", "other": "Other failure",
}
CAUSE_WHY = {
    "gate": "Never reached a page a step needed. A page gate is a hard stop, so later steps were not run: one cause, not a cascade.",
    "unmet_dependency": "A step used a value that nothing had set yet (its own earlier step, or a test that did not run or failed).",
    "element_missing": "The page arrived but something on it was not found.",
    "site_said_no": "The site showed something other than expected. Most likely a real site bug.",
    "waf": "The site's own protection blocked the request.",
    "captcha": "A captcha challenge stopped the test.",
    "infra": "The machine could not finish the test (the browser crashed, disconnected, or the driver died), not the site.",
    "cancelled": "The run was cancelled before this test finished.",
    "interrupted": "The runner stopped responding before this test finished.",
    "other": "Failed for another reason; see the step detail.",
}


class ResultsApiError(HTTPException):
    def __init__(self, status: int, message: str, kind: str = "", **extra: Any):
        super().__init__(status, message)
        self.kind, self.extra = kind, extra


def workbook_name(meta: dict[str, Any]) -> str:
    return Path(str(meta.get("workbook", ""))).name


def grouped_by_batch(metas: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for meta in metas:
        bid = meta.get("batch_id")
        if bid:
            groups.setdefault(bid, []).append(meta)
    return groups


def batch_metas(all_metas: list[dict[str, Any]], batch_id: str) -> list[dict[str, Any]]:
    runs = grouped_by_batch(all_metas).get(batch_id)
    if not runs:
        raise ResultsApiError(404, "batch not found", "not_found")
    return sorted(runs, key=lambda m: m.get("started_at") or "")


def read_results(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "results.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _first_bad_step(test: dict[str, Any]) -> dict[str, Any] | None:
    return next((s for s in test.get("steps", []) if s.get("status") not in ("PASSED", None)), None)


def cause_of(test: dict[str, Any]) -> str:
    """One of ``CAUSE_ORDER`` for a failed/errored/not-run test (CONTRACT.md's kinds plus two the Results page adds:
    a page-gate hard stop and a step that used a value nothing ever set)."""
    step = _first_bad_step(test)
    if step is not None:
        if str(step.get("action") or "").upper() == "ASSERT_PAGE":
            return "gate"
        if "has no value" in str(step.get("error") or ""):
            return "unmet_dependency"
    return history.test_error_kind(test)


def cause_message(test: dict[str, Any], cause: str) -> str:
    step = _first_bad_step(test)
    if step is not None:
        text = f"Step {step.get('seq', '?')} · {step.get('name') or step.get('action') or ''}"
        error = str(step.get("error") or "").strip()
        return f"{text} · {error}" if error else text
    whole_test = str(test.get("error") or test.get("infra") or test.get("blocked") or test.get("captcha") or "").strip()
    return whole_test or CAUSE_WHY.get(cause, "")


def build_batch_page(batch_id: str, metas: list[dict[str, Any]], runs_dir: Path) -> dict[str, Any]:
    summary = {**batch_summary(batch_id, metas), "runs": metas}
    rerun_of = next((m.get("rerun_of") for m in metas if m.get("rerun_of")), None)

    groups: dict[str, list[dict[str, Any]]] = {}
    tests: list[dict[str, Any]] = []
    what_changed: list[str] = []
    runs_by_workbook: dict[str, list[history.Run]] = {}
    for meta in metas:
        wb = workbook_name(meta)
        data = read_results(runs_dir / meta["run_id"])
        if data is None:
            continue
        if wb not in runs_by_workbook:
            runs_by_workbook[wb] = history.load_runs(runs_dir, wb)
            for marker in history.markers(runs_by_workbook[wb]):
                if marker.run_id == meta["run_id"]:
                    what_changed.append(marker.describe())
        for test in data.get("tests", []):
            seq = history.last_n_statuses(runs_by_workbook[wb], test.get("id", ""), 10)
            verdict = history.trend_verdict(seq)
            tests.append({"workbook": wb, "run_id": meta["run_id"], "id": test.get("id", ""), "status": test.get("status", ""),
                         "duration_s": test.get("duration_s"), "steps": len(test.get("steps", [])), "failed_steps": test.get("failed", 0),
                         "trend": seq, "verdict": verdict})
            if test.get("status") != "PASSED":
                cause = cause_of(test)
                groups.setdefault(cause, []).append({"workbook": wb, "run_id": meta["run_id"], "test": test.get("id", ""),
                                                     "message": cause_message(test, cause), "verdict": verdict})
    ordered_groups = [{"kind": k, "title": CAUSE_TITLES[k], "why": CAUSE_WHY[k], "items": groups[k]} for k in CAUSE_ORDER if groups.get(k)]
    return {"batch": summary, "rerun_of": rerun_of, "what_changed": what_changed, "groups": ordered_groups, "tests": tests}


def rerun_plan(metas: list[dict[str, Any]], runs_dir: Path) -> dict[str, Any]:
    """What a "Re-run failed" of this batch should start: one entry per workbook that had a failure, plus the settings
    to relaunch with (read from the first run that still has a ``results.json``).  Raises when the batch is still
    running, ran on PROD (re-running that needs the New run screen's confirmation), or nothing in it failed."""
    if any(m.get("active") for m in metas):
        raise ResultsApiError(409, "This batch is still running. Wait for it to finish before re-running its failures.", "busy")
    picks: list[dict[str, Any]] = []
    skipped: list[str] = []
    sample: dict[str, Any] | None = None
    for meta in metas:
        wb = workbook_name(meta)
        data = read_results(runs_dir / meta["run_id"])
        if data is None:
            continue
        failed = [t["id"] for t in data.get("tests", []) if t.get("status") in ("FAILED", "ERROR") or t.get("failed")]
        if not failed:
            skipped.append(wb)
            continue
        picks.append({"workbook": wb, "tests": failed})
        sample = sample or data
    if not picks:
        raise ResultsApiError(409, "Nothing failed in this batch: there is nothing to re-run.", "nothing_failed")
    environment = str((sample or {}).get("environment") or "").upper()
    if environment == "PROD":
        raise ResultsApiError(422, "This batch ran on PROD. Re-run its failures from New run, which asks you to confirm PROD.", "prod_confirm")
    config = (sample or {}).get("config") or {}
    browser = (sample or {}).get("browser") or {}
    shots = (config.get("screenshots") or {}).get("mode")
    return {"picks": picks, "skipped": skipped, "environment": environment or None, "workers": (sample or {}).get("workers"),
            "screenshots": shots if shots in ("every_step", "on_failure", "off") else None,
            "retries": (config.get("behaviour") or {}).get("retries"), "browser": browser.get("id") or None,
            "headed": not browser.get("headless", True)}


def test_layout(workbooks_dir: Path, wb_name: str, environment: str | None, sheet: str) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
    """This test's blocks (CONTRACT.md 2.4) and any ``BACKUP_LOCATORS`` its steps carry, read fresh from the workbook
    on disk (it may have moved on since the run: a missing file or sheet just means no block map, not an error)."""
    path = workbooks_dir / wb_name
    if not path.is_file():
        return [], {}
    try:
        model = build_model(WorkbookEditor.open(path), environment=environment, with_problems=False)
    except Exception:
        return [], {}
    test = next((t for t in model.get("tests", []) if t.get("sheet") == sheet or t.get("id") == sheet), None)
    if test is None:
        return [], {}
    backups = {s["row"]: s["locator"]["backups"] for s in test.get("steps", []) if (s.get("locator") or {}).get("backups")}
    return test.get("blocks", []), backups


def block_status(block: dict[str, Any], row_status: dict[int, str], last_row: int) -> str:
    """``pass`` / ``fail`` / ``warn`` / ``pend`` for one block of the test's block map, from the rows this run
    actually executed (``row_status``: sheet row -> step status)."""
    rows_here = [r for r in row_status if block["firstRow"] <= r <= block["lastRow"]]
    if any(row_status[r] == "FAILED" for r in rows_here):
        return "fail"
    if not rows_here:
        return "pend" if block["firstRow"] > last_row else "warn"    # inside the run but no step of this test landed in it
    return "pass" if all(row_status[r] == "PASSED" for r in rows_here) else "warn"


def build_test_page(run_dir: Path, workbooks_dir: Path, runs_dir: Path, test_id: str) -> dict[str, Any]:
    meta = read_meta(run_dir)
    if not meta:
        raise ResultsApiError(404, "run not found", "not_found")
    data = read_results(run_dir)
    if data is None:
        raise ResultsApiError(409, "This run has no results yet.", "no_results")
    test = next((t for t in data.get("tests", []) if t.get("id") == test_id), None)
    if test is None:
        raise ResultsApiError(404, "test not found in this run", "not_found")
    wb = workbook_name(meta)
    blocks, backups = test_layout(workbooks_dir, wb, meta.get("environment"), test.get("sheet") or test_id)
    row_status = {s["row"]: s.get("status") for s in test.get("steps", []) if s.get("row") is not None}
    last_row = max(row_status, default=0)
    for block in blocks:
        block["status"] = block_status(block, row_status, last_row)
    runs = history.load_runs(runs_dir, wb)
    trend = history.last_n_statuses(runs, test_id, 10)
    return {"blocks": blocks, "backups": {str(k): v for k, v in backups.items()}, "history": trend, "verdict": history.trend_verdict(trend)}


def build_compare(runs_dir: Path, names: list[str], n: int) -> dict[str, Any]:
    n = max(1, min(n, 30))
    out_rows: list[dict[str, Any]] = []
    columns: dict[str, list[dict[str, Any]]] = {}
    for wb in names:
        runs = history.load_runs(runs_dir, wb)[-n:]
        columns[wb] = [{"run_id": r.run_id, "started_at": r.started, "environment": r.data.get("environment", "")} for r in runs]
        test_ids: list[str] = []
        for r in runs:
            for t in r.data.get("tests", []):
                tid = t.get("id", "")
                if tid and tid not in test_ids:
                    test_ids.append(tid)
        for tid in test_ids:
            seq = history.last_n_statuses(runs, tid, n)
            by_run = {h["run_id"]: h["status"] for h in seq}
            out_rows.append({"workbook": wb, "test": tid, "cells": [by_run.get(c["run_id"], "") for c in columns[wb]],
                             "verdict": history.trend_verdict(seq)})
        columns[wb + "__markers"] = [m.describe() for m in history.markers(runs)]
    return {"columns": columns, "rows": out_rows}


def register_results_routes(app: FastAPI, mgr: Any) -> None:
    """Add the Results routes.  ``mgr`` is the ``RunManager``; the request guard and error shape of ``create_app``
    (localhost Host, ``X-Requested-With`` + local Origin on POST) already cover these routes."""

    @app.exception_handler(ResultsApiError)
    async def results_error(_, exc: ResultsApiError):
        return JSONResponse({"error": exc.detail, "kind": exc.kind, **exc.extra}, status_code=exc.status_code)

    @app.get("/api/results/batches/{batch_id}")
    async def batch_page(batch_id: str):
        def work():
            metas = batch_metas(mgr.list_runs(1000), batch_id)
            return build_batch_page(batch_id, metas, mgr.runs_dir())
        return await asyncio.to_thread(work)

    @app.post("/api/results/batches/{batch_id}/rerun-failed")
    async def rerun_failed(batch_id: str):
        from .app import StartRun, WorkbookPick  # deferred: app.py imports this module, so the cycle only closes at call time

        def plan():
            metas = batch_metas(mgr.list_runs(1000), batch_id)
            return rerun_plan(metas, mgr.runs_dir())
        p = await asyncio.to_thread(plan)
        # A batch is only a UI label (CONTRACT.md): "Re-run failed" always gets a fresh one, even for a single
        # workbook, where RunManager._start would otherwise leave batch_id unset.
        new_id = await asyncio.to_thread(lambda: new_batch_id(mgr.existing_batch_ids()))
        req = StartRun(workbooks=[WorkbookPick(workbook=pick["workbook"], tests=pick["tests"]) for pick in p["picks"]],
                       env=p["environment"], workers=p["workers"], screenshots=p["screenshots"], retries=p["retries"],
                       browser=p["browser"], headed=p["headed"], batch_id=new_id, batch_label=f"re-run of batch {batch_id}")
        result = await mgr.start(req)
        if result.get("batch_id"):
            for run_id in result.get("run_ids", []):
                await asyncio.to_thread(update_meta, mgr.run_dir(run_id), rerun_of=batch_id)
        return {**result, "skipped_no_failures": p["skipped"]}

    @app.get("/api/results/runs/{run_id}/tests/{test_id}")
    async def test_page(run_id: str, test_id: str):
        workbooks_dir = mgr.cfg.path(mgr.cfg.workbooks_dir)
        return await asyncio.to_thread(build_test_page, mgr.run_dir(run_id), workbooks_dir, mgr.runs_dir(), test_id)

    @app.get("/api/results/compare")
    async def compare(workbooks: str = "", n: int = 8):
        def work():
            names = [w for w in workbooks.split(",") if w.strip()]
            if not names:
                names = sorted({workbook_name(m) for m in mgr.list_runs(1000) if workbook_name(m)})
            return build_compare(mgr.runs_dir(), names, n)
        return await asyncio.to_thread(work)
