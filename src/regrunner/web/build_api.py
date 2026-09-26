"""``/api/build/*``: the Workbook Builder's server routes (dev/plan/CONTRACT.md section 3).

Kept out of ``web/app.py`` so parallel phases do not collide there: ``create_app`` calls ``register_build_routes`` once. The request guard
of ``create_app`` (localhost Host; ``X-Requested-With: regrunner`` + local Origin on every POST/PUT/DELETE) is an app-wide middleware, so it
covers these routes too. Work on a workbook (reading ~1 s on the big ones, snapshots, draft writes) runs off the event loop.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from ..workbook.builder import BuildDocument, BuildError, BuildStore, keyword_catalogue, new_workbook
from ..workbook.writer import WriterError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


class BuildApiError(HTTPException):
    def __init__(self, status: int, message: str, kind: str = "", **extra: Any):
        super().__init__(status, message)
        self.kind, self.extra = kind, extra


def register_build_routes(app: FastAPI, mgr: Any) -> BuildStore:
    """Add the builder routes.  ``mgr`` is the ``RunManager`` (``resolve_workbook``, ``current()`` for the config).  What the app caches
    about a workbook is keyed by the file's mtime, so a save from here needs no extra invalidation."""
    store = BuildStore()

    def runs_dir() -> Path:
        cfg = mgr.current()
        return cfg.path(cfg.runs_dir)

    def doc(name: str) -> BuildDocument:
        path = mgr.resolve_workbook(name)
        if path.suffix.lower() not in (".xlsx", ".xlsm"):
            raise BuildApiError(400, "The builder edits .xlsx workbooks only.", "type")
        try:
            return store.get(path, runs_dir())
        except (WriterError, KeyError, ValueError) as err:
            raise BuildApiError(422, f"Could not open {path.name} for editing: {err}", "unreadable") from err

    async def run(fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except BuildError as err:
            raise BuildApiError(err.status, str(err), err.kind, **err.extra) from err

    @app.exception_handler(BuildApiError)
    async def build_error(_, exc: BuildApiError):
        return JSONResponse({"error": exc.detail, "kind": exc.kind, **exc.extra}, status_code=exc.status_code)

    @app.get("/api/build/keywords")
    async def build_keywords():
        return keyword_catalogue()

    @app.post("/api/build/workbooks", status_code=201)
    async def build_new_workbook(body: dict[str, Any]):
        cfg = mgr.current()
        base = cfg.path(cfg.workbooks_dir)
        raw = str(body.get("name") or "").strip()
        name = _SAFE_NAME.sub("_", Path(raw).name).strip(" .")
        if not name:
            raise BuildApiError(400, "Give the workbook a name.", "name")
        if Path(name).suffix.lower() != ".xlsx":
            name += ".xlsx"
        target = base / name
        if target.exists():
            raise BuildApiError(409, f"{name} already exists.", "exists")
        base.mkdir(parents=True, exist_ok=True)
        source = body.get("from")
        if source:
            src = mgr.resolve_workbook(str(source))

            def copy() -> None:
                from ..workbook.writer import WorkbookEditor
                WorkbookEditor.open(src).save_as(target)
            await run(copy)
        else:
            envs = body.get("environments") or []
            if not isinstance(envs, list):
                raise BuildApiError(400, "environments is a list.", "environments")
            await run(new_workbook, target, [e for e in envs if isinstance(e, dict)])
        d = doc(name)
        return {"name": name, "model": await run(d.model)}

    @app.get("/api/build/workbooks/{name}")
    async def build_model_route(name: str, env: str | None = None):
        d = doc(name)
        return await run(d.model, env)

    @app.get("/api/build/workbooks/{name}/status")
    async def build_status(name: str):
        return doc(name).status()

    @app.post("/api/build/workbooks/{name}/edit")
    async def build_edit(name: str, body: dict[str, Any], env: str | None = None):
        d = doc(name)
        ops = body.get("ops")
        if not isinstance(ops, list) or not ops:
            raise BuildApiError(400, "Send the edits as a list of ops.", "op")
        applied = await run(d.apply, ops, body.get("version"))
        return {"model": await run(d.model, env or body.get("env")), "applied": applied}

    @app.post("/api/build/workbooks/{name}/undo")
    async def build_undo(name: str, env: str | None = None):
        d = doc(name)
        await run(d.undo)
        return {"model": await run(d.model, env)}

    @app.post("/api/build/workbooks/{name}/redo")
    async def build_redo(name: str, env: str | None = None):
        d = doc(name)
        await run(d.redo)
        return {"model": await run(d.model, env)}

    @app.post("/api/build/workbooks/{name}/save")
    async def build_save(name: str, body: dict[str, Any] | None = None):
        d = doc(name)
        result = await run(d.save, force=bool((body or {}).get("force")))
        return {"status": d.status(), "backup": result.backup.name if result.backup else None}

    @app.post("/api/build/workbooks/{name}/reload")
    async def build_reload(name: str, env: str | None = None):
        d = doc(name)
        await run(d.reload)
        return {"model": await run(d.model, env)}

    @app.get("/api/build/workbooks/{name}/history")
    async def build_history(name: str):
        return await run(doc(name).history)

    @app.get("/api/build/workbooks/{name}/diff")
    async def build_diff(name: str, against: str = "disk"):
        return {"changes": await run(doc(name).diff, against)}

    @app.post("/api/build/workbooks/{name}/restore")
    async def build_restore(name: str, body: dict[str, Any], env: str | None = None):
        d = doc(name)
        await run(d.restore, str(body.get("id") or ""))
        return {"model": await run(d.model, env)}

    @app.get("/api/build/workbooks/{name}/variables")
    async def build_variables(name: str):
        return (await run(doc(name).model))["variables"]

    @app.get("/api/build/workbooks/{name}/problems")
    async def build_problems(name: str, env: str | None = None):
        model = await run(doc(name).model, env)
        return {"problems": model["problems"], "problemCounts": model["problemCounts"], "environment": model["environment"]}

    @app.get("/api/build/workbooks/{name}/environments")
    async def build_environments(name: str):
        return (await run(doc(name).model))["environments"]

    @app.get("/api/build/workbooks/{name}/fingerprints")
    async def build_fingerprints(name: str):
        return (await run(doc(name).model))["fingerprints"]

    @app.get("/api/build/workbooks/{name}/sheets/{sheet}")
    async def build_sheet(name: str, sheet: str):
        d = doc(name)

        def grid() -> dict:
            with d.lock:
                editor = d.editor
                real = next((s for s in editor.sheet_names() if s.upper() == sheet.upper()), None)
                if real is None:
                    raise BuildError(f"There is no sheet called {sheet!r}.", "not_found", 404)
                rows = editor.rows(real)
                clean = [[v if isinstance(v, (str, int, float, bool)) or v is None else str(v) for v in r] for r in rows]
                return {"name": real, "hidden": editor.is_hidden(real), "headers": clean[0] if clean else [], "rows": clean[1:]}
        return await run(grid)

    return store
