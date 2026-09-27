"""``/api/build/templates*``: the shared template library (dev/plan/CONTRACT.md section 3, reserved for P11).

Kept out of ``web/app.py`` so parallel phases do not collide there.  Reuses the ``BuildStore`` ``register_build_routes``
already opened workbooks in, so inserting a template goes through the very same ``BuildDocument.apply`` (undo, autosaved
draft) as every other edit - a template insert is just more ``insert_step``/``add_variable`` ops, never a new op kind.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ..workbook import templates
from ..workbook.builder import BuildError, BuildStore
from .build_api import BuildApiError


def register_templates_routes(app: FastAPI, mgr: Any, store: BuildStore) -> None:
    def library_path() -> Path:
        cfg = mgr.current()
        return templates.templates_path(cfg.path(cfg.workbooks_dir))

    def doc(name: str):
        cfg = mgr.current()
        return store.get(mgr.resolve_workbook(name), cfg.path(cfg.runs_dir))

    async def run(fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except BuildError as err:
            raise BuildApiError(err.status, str(err), err.kind, **err.extra) from err

    # BuildApiError's handler is registered once by register_build_routes, which create_app always calls first.

    @app.get("/api/build/templates")
    async def list_templates():
        return {"templates": await run(templates.list_templates, library_path())}

    @app.post("/api/build/templates", status_code=201)
    async def save_template(body: dict[str, Any]):
        name = str(body.get("name") or "")
        for key in ("workbook", "test", "fromRow", "toRow"):
            if body.get(key) in (None, ""):
                raise BuildApiError(400, f"{key} is required.", key)
        model = await run(doc(str(body["workbook"])).model)
        result = await run(templates.save_as_template, model, library_path(), test_id=str(body["test"]),
                          from_row=int(body["fromRow"]), to_row=int(body["toRow"]), name=name,
                          description=str(body.get("description") or ""))
        return result

    @app.delete("/api/build/templates/{name}")
    async def delete_template(name: str):
        await run(templates.delete_template, library_path(), name)
        return {"ok": True}

    @app.get("/api/build/templates/{name}/mapping")
    async def template_mapping(name: str, workbook: str):
        tpl = await run(templates.get_template, library_path(), name)
        model = await run(doc(workbook).model)
        mapping = await run(templates.match_variables, tpl["variables"], model["variables"])
        return {"template": {"name": tpl["name"], "description": tpl["description"], "count": tpl["count"]}, "mapping": mapping}

    @app.post("/api/build/workbooks/{name}/templates/insert")
    async def insert_template(name: str, body: dict[str, Any], env: str | None = None):
        tpl = await run(templates.get_template, library_path(), str(body.get("template") or ""))
        test_id = str(body.get("test") or "")
        if not test_id:
            raise BuildApiError(400, "Say which test to insert into.", "test")
        d = doc(name)
        model = await run(d.model)
        t = next((x for x in model["tests"] if x["id"] == test_id), None)
        if t is None:
            raise BuildApiError(404, f"No test called {test_id!r}.", "not_found")
        ops = await run(templates.insert_template_ops, tpl, mapping=dict(body.get("mapping") or {}), test_id=test_id,
                       param_sheet=t.get("paramSheet"), after=body.get("after"), before=body.get("before"))
        applied = await run(d.apply, ops, body.get("version"))
        return {"model": await run(d.model, env or body.get("env")), "applied": applied}
