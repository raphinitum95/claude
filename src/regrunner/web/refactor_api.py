"""Duplicate ("what changes?"), find & replace, and per-step merge routes (``workbook/refactor.py``; Q26, Q29).

Kept out of ``web/app.py`` so parallel phases do not collide there, and out of ``build_api.py`` because none of this is
reserved there: every route here either only reads (``find`` preview, ``duplicate-candidates``) or applies ops through the
very same ``BuildDocument`` (``build_api.py``'s ``BuildStore``) every other edit goes through - the merge endpoint replays
``BuildDocument.diff("disk")`` itself so the client never has to resend the whole diff back.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

from ..workbook import refactor
from ..workbook.builder import BuildError, BuildStore
from .build_api import BuildApiError


def register_refactor_routes(app: FastAPI, mgr: Any, store: BuildStore) -> None:
    def doc(name: str):
        cfg = mgr.current()
        return store.get(mgr.resolve_workbook(name), cfg.path(cfg.runs_dir))

    async def run(fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except BuildError as err:
            raise BuildApiError(err.status, str(err), err.kind, **err.extra) from err

    @app.post("/api/build/workbooks/{name}/find")
    async def find_preview(name: str, body: dict[str, Any]):
        d = doc(name)

        def preview() -> list[dict]:
            with d.lock:
                return refactor.find_replace_preview(d.editor, body.get("pairs") or [])
        return {"hits": await run(preview)}

    @app.post("/api/build/workbooks/{name}/find/apply")
    async def find_apply(name: str, body: dict[str, Any], env: str | None = None):
        d = doc(name)
        ops = refactor.apply_ops_for_hits(body.get("hits") or [])
        if not ops:
            raise BuildApiError(400, "Nothing selected to change.", "empty")
        applied = await run(d.apply, ops, body.get("version"))
        return {"model": await run(d.model, env or body.get("env")), "applied": applied}

    @app.get("/api/build/workbooks/{name}/duplicate-candidates")
    async def duplicate_candidates(name: str, newName: str = ""):
        model = await run(doc(name).model)
        return {"rows": refactor.duplicate_candidates(model, newName)}

    @app.post("/api/build/workbooks/{name}/merge")
    async def merge(name: str, body: dict[str, Any], env: str | None = None):
        d = doc(name)
        hits = await run(d.diff, "disk")
        ops = refactor.merge_ops(hits, dict(body.get("picks") or {}))
        if not ops:
            raise BuildApiError(400, "Nothing picked to merge.", "empty")
        applied = await run(d.apply, ops, body.get("version"))
        return {"model": await run(d.model, env or body.get("env")), "applied": applied}
