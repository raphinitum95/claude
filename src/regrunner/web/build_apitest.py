"""``/api/build/api/*``: the Build tab's API / XML test editor (P10; ``build/api_builder.py``).

Registered by ``register_build_routes`` (``web/build_api.py``) with its ``doc`` / ``run`` helpers, so errors answer the same way.  Edits are not
here: the page sends ``api_*`` ops to ``/api/build/workbooks/{name}/edit`` like every other edit (one undo step each).  "Send now" sends a real
request from this computer; a production environment needs ``confirmProd: "PROD"``, like the build window.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ..build import api_builder as A
from ..workbook.builder import BuildError, read_environments


def register_api_test_routes(app: FastAPI, mgr: Any, doc, run, error) -> None:
    """``error(status, message, kind)`` builds the builder's HTTP error (``BuildApiError``)."""

    def folder_of(d) -> Path:
        cfg = mgr.current()
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(d.path.name).stem)
        return cfg.path(cfg.runs_dir) / ".build" / stem                        # (a dot folder: never listed as a run)

    def view(d, test: str, row: Any, env: str | None) -> dict:
        with d.lock:
            environments = read_environments(d.editor)
            environment = (env or A._global_text(d.editor, "Environment") or "").upper()
            return A.api_view(d.editor, test, row, environments=environments, environment=environment)

    @app.get("/api/build/api/{name}/tests/{test}")
    async def api_test_view(name: str, test: str, row: int | None = None, env: str | None = None):
        d = doc(name)
        return await run(view, d, test, row, env)

    @app.post("/api/build/api/send")
    async def api_send(body: dict[str, Any]):
        d = doc(str(body.get("workbook") or ""))
        cfg = mgr.current()
        v = await run(view, d, str(body.get("test") or ""), body.get("row"), body.get("env") or None)
        environment = v["environment"]
        if environment in set(v["production"]) | {"PROD", "PRODUCTION"} and str(body.get("confirmProd") or "").strip() != "PROD":
            raise error(400, f"{environment} is a production environment: Send now would send a real request there. Confirm by typing PROD.", "prod_confirm")
        values = body.get("values") if isinstance(body.get("values"), dict) else {}
        try:
            return await A.send_now(d, cfg, folder_of(d), test=v["test"], row=v["row"], environment=environment, values=values)
        except BuildError as err:
            raise error(err.status, str(err), err.kind) from err

    def row_values(d, test: str, row: Any) -> dict[str, str]:
        if not test:
            return {}
        v = view(d, test, row, None)
        return v["rowValues"]

    @app.post("/api/build/api/curl")
    async def api_curl(body: dict[str, Any]):
        """``{workbook, text, test?, row?, env?}`` -> ``{request, found}``: the command read, turned into the workbook's form (not applied)."""
        d = doc(str(body.get("workbook") or ""))
        try:
            parsed = A.parse_curl(str(body.get("text") or ""))
        except ValueError as err:
            raise error(422, f"That is not a cURL command: {err}.", "curl") from err

        def work() -> dict:
            with d.lock:
                environments = read_environments(d.editor)
                env = (body.get("env") or A._global_text(d.editor, "Environment") or "").upper()
            values = row_values(d, str(body.get("test") or ""), body.get("row"))
            return A.suggest(parsed, environments=environments, environment=env, row_values=values)
        return await run(work)

    @app.post("/api/build/api/postman")
    async def api_postman(body: dict[str, Any]):
        """``{workbook, collection, env?}`` -> ``{requests: [{name, folder, request, found}]}`` (nothing is created until the page sends
        ``api_add_test`` ops for the ones picked)."""
        d = doc(str(body.get("workbook") or ""))
        try:
            requests = A.parse_postman(body.get("collection"))
        except (ValueError, TypeError) as err:
            raise error(422, f"That is not a Postman collection: {err}.", "postman") from err

        def work() -> dict:
            with d.lock:
                environments = read_environments(d.editor)
                env = (body.get("env") or A._global_text(d.editor, "Environment") or "").upper()
            out = []
            for r in requests:
                s = A.suggest(r, environments=environments, environment=env)
                out.append({"name": r["name"], "folder": r["folder"], **s})
            return {"requests": out}
        return await run(work)

    @app.get("/api/build/api/{name}/templates")
    async def api_templates(name: str, location: str = ""):
        d = doc(name)
        cfg = mgr.current()
        return await run(lambda: {"templates": A.list_templates(cfg, d.path.parent, location),
                                  "folders": [str(p) for p in A.template_folders(cfg, d.path.parent, location)]})

    @app.get("/api/build/api/{name}/templates/fields")
    async def api_template_fields(name: str, folder: str, file: str, test: str, row: int | None = None, location: str = ""):
        d = doc(name)
        cfg = mgr.current()
        folders = {str(p) for p in A.template_folders(cfg, d.path.parent, location)}
        if folder not in folders or Path(file).name != file or not file:
            raise error(400, "That template is not in one of the template folders.", "template")
        path = Path(folder) / file
        if not path.is_file():
            raise error(404, f"{file} is not in {folder}.", "not_found")

        def work() -> dict:
            with d.lock:
                sheet = A.api_sheet(d.editor, test)
                return A.template_fields(path, d.editor, sheet, A._data_row(d.editor, sheet, row))
        return await run(work)
