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

from ..build.session import BuildSession, SessionStore
from .build_apitest import register_api_test_routes
from .record_api import register_record_routes
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

    register_session_routes(app, mgr, doc, run)
    register_api_test_routes(app, mgr, doc, run, BuildApiError)             # /api/build/api/*: the API / XML test editor (web/build_apitest.py, P10)
    return store


def register_session_routes(app: FastAPI, mgr: Any, doc, run) -> SessionStore:
    """``/api/build/session/{name}/*`` (P08): the build window of a workbook (``build/session.py``).  One per workbook; it replays the draft
    in a browser of its own, so it never gets in the way of a run (a run of the same workbook may go on at the same time)."""
    sessions = SessionStore()

    def live(name: str) -> BuildSession:
        s = sessions.get(mgr.resolve_workbook(name).name)
        if s is None:
            raise BuildApiError(409, "The build browser is not open. Open it first.", "closed")
        return s

    async def act(coro):
        try:
            return await coro
        except BuildError as err:
            raise BuildApiError(err.status, str(err), err.kind, **err.extra) from err

    def row_of(body: dict, key: str = "row") -> int | None:
        value = body.get(key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise BuildApiError(400, f"{key} is a row number.", key) from None

    async def state(s: BuildSession, since: int = 0) -> dict:
        return await asyncio.to_thread(s.state, since)

    @app.get("/api/build/session/{name}")
    async def session_state(name: str, since: int = 0):
        path = mgr.resolve_workbook(name)
        s = sessions.get(path.name)
        if s is None:
            last = sessions.last(path.name)
            return {"open": False, "workbook": path.name, "error": last.error if last is not None else ""}
        return await state(s, since)

    @app.post("/api/build/session/{name}/start")
    async def session_start(name: str, body: dict[str, Any]):
        d = doc(name)
        cfg = mgr.current()
        test = str(body.get("test") or "").strip()
        if not test:
            raise BuildApiError(400, "Which test? Open one first.", "test")
        model = await run(d.model, body.get("env") or None)
        environment = str(body.get("env") or model.get("environment") or "").upper()
        production = {n.upper() for n in model["environments"].get("production", [])} | {"PROD", "PRODUCTION"}
        if environment in production and str(body.get("confirmProd") or "").strip() != "PROD":
            raise BuildApiError(400, f"{environment} is a production environment: the build window would use the real site. Confirm by typing PROD.",
                                "prod_confirm")
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(d.path.name).stem)
        folder = cfg.path(cfg.runs_dir) / ".build" / stem          # (a dot folder: never listed as a run)
        s = await act(sessions.open(d, cfg, folder, test_id=test, data_row=row_of(body, "dataRow"), environment=environment,
                                    headless=bool(cfg.build.headless or body.get("headless"))))
        return await state(s)

    @app.post("/api/build/session/{name}/pick")
    async def session_pick(name: str, body: dict[str, Any]):
        s = live(name)
        await act(s.set_mode(str(body.get("mode") or "pick"), row_of(body)))
        return await state(s)

    @app.post("/api/build/session/{name}/which")
    async def session_which(name: str, body: dict[str, Any]):
        s = live(name)
        if body.get("row") is not None:
            s.pick_for = row_of(body)
        await act(s.find_matches(str(body.get("text") or ""), str(body.get("kind") or "")))
        return await state(s)

    @app.post("/api/build/session/{name}/choose")
    async def session_choose(name: str, body: dict[str, Any]):
        s = live(name)
        await act(s.choose(row_of(body, "i") or 0))
        return await state(s)

    @app.post("/api/build/session/{name}/variable")
    async def session_variable(name: str, body: dict[str, Any]):
        s = live(name)
        await act(s.make_variable(str(body.get("role") or ""), str(body.get("token") or "")))
        return await state(s)

    @app.post("/api/build/session/{name}/use")
    async def session_use(name: str, body: dict[str, Any], env: str | None = None):
        s = live(name)
        applied = await act(s.use(row_of(body)))
        return {"applied": applied, "model": await run(doc(name).model, env), "session": await state(s)}

    @app.post("/api/build/session/{name}/run-to-here")
    async def session_run_to(name: str, body: dict[str, Any]):
        s = live(name)
        await act(_sync(s.run, "to", row_of(body)))
        return await state(s)

    @app.post("/api/build/session/{name}/run-step")
    async def session_run_step(name: str, body: dict[str, Any]):
        s = live(name)
        await act(_sync(s.run, "step", row_of(body)))
        return await state(s)

    @app.post("/api/build/session/{name}/run-next")
    async def session_run_next(name: str, body: dict[str, Any] | None = None):
        s = live(name)
        await act(_sync(s.run, "next", None, row_of(body or {}, "count")))
        return await state(s)

    @app.post("/api/build/session/{name}/stop")
    async def session_stop(name: str):
        s = live(name)
        s.stop()
        return await state(s)

    @app.post("/api/build/session/{name}/answer")
    async def session_answer(name: str, body: dict[str, Any]):
        s = live(name)
        if not s.asker.answer(str(body.get("id") or ""), str(body.get("answer") or "")):
            raise BuildApiError(409, "That question is not waiting any more.", "closed")
        return {"ok": True}

    @app.post("/api/build/session/{name}/close")
    async def session_close(name: str):
        path = mgr.resolve_workbook(name)
        s = sessions.get(path.name)
        if s is not None:
            await s.close()
        return {"open": False, "workbook": path.name}

    register_record_routes(app, mgr, doc, run, sessions)                 # P09: record, check / save this, prompts
    return sessions


async def _sync(fn, *args):
    """A session method that is plain (it starts its work in the background) where ``act`` expects something to await."""
    return fn(*args)
