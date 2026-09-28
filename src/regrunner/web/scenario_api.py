"""``/api/build/workbooks/{name}/scenarios*``: the Build tab's scenario board (P12, Q35/Q36; ``workbook/scenarios.py``).

Edits are ops through ``/edit`` like every other edit (``set_scenario`` / ``delete_scenario``, CONTRACT.md 3.1), so they share the workbook's
undo and autosaved draft.  What is here only reads: the board (the model's ``scenarios`` without the rest of the workbook) and how the scenario's
lanes did in the last runs, read from the run folders' results.json (per lane, with what happened at each sync point).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ..runmeta import read_meta
from ..workbook.builder import BuildError, BuildStore
from .build_api import BuildApiError


def scenario_runs(runs_dir: Path, workbook: str, scenario: str, limit: int = 5) -> list[dict[str, Any]]:
    """The newest runs of ``workbook`` in which ``scenario`` ran, newest first: ``[{runId, when, status, environment, lanes: [{id, key, label,
    test, status, error, passed, failed, skipped, syncs}]}]``.  Plain paths, so it is tested without a server."""
    out: list[dict[str, Any]] = []
    if not runs_dir.is_dir():
        return out
    want = scenario.strip().upper()
    for run_dir in sorted((p for p in runs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.name, reverse=True):
        meta = read_meta(run_dir) or {}
        if Path(str(meta.get("workbook") or "")).name.upper() != workbook.upper():
            continue
        try:
            data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lanes = [t for t in data.get("tests", []) if str((t.get("lane") or {}).get("scenario", "")).upper() == want]
        if not lanes:
            continue
        out.append({"runId": run_dir.name, "when": data.get("started_at", ""), "status": data.get("status", meta.get("status", "")),
                    "environment": data.get("environment", ""),
                    "lanes": [{"id": t["id"], "key": t["lane"].get("key", ""), "label": t["lane"].get("label", ""), "test": t["lane"].get("test", ""),
                               "status": t.get("status", ""), "error": t.get("error", ""), "passed": t.get("passed", 0), "failed": t.get("failed", 0),
                               "skipped": t.get("skipped", 0), "syncs": t.get("syncs", [])} for t in lanes]})
        if len(out) >= limit:
            break
    return out


def register_scenario_routes(app: FastAPI, mgr: Any, store: BuildStore) -> None:
    def doc(name: str):
        cfg = mgr.current()
        return store.get(mgr.resolve_workbook(name), cfg.path(cfg.runs_dir))

    async def run(fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except BuildError as err:
            raise BuildApiError(err.status, str(err), err.kind, **err.extra) from err

    @app.get("/api/build/workbooks/{name}/scenarios")
    async def scenarios(name: str, env: str | None = None):
        model = await run(doc(name).model, env)
        return {"scenarios": model.get("scenarios", [])}

    @app.get("/api/build/workbooks/{name}/scenarios/{scenario}/runs")
    async def runs_of(name: str, scenario: str, limit: int = 5):
        path = mgr.resolve_workbook(name)
        return {"runs": await asyncio.to_thread(scenario_runs, mgr.runs_dir(), path.name, scenario, max(1, min(int(limit), 20)))}
