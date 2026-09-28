"""The Build tab's Variables screen (add / rename / edit / delete a variable) and what Download says about secrets.

Kept out of ``web/app.py`` and ``build_api.py`` like the other builder phases' routes (``register_variables_routes``: one line in
``create_app``, sharing ``build_api.py``'s ``BuildStore`` so every edit made here goes through the same undo/draft as any other).  Most edits
are plain ops sent to ``/edit`` by the page (``add_variable``, ``set_variable``, ``set_cell``, ``set_environments``, ``delete_variable``); only
what an op cannot do lives here:

* the values of the variable on screen (``variable_values``: read on demand, the model does not carry every Params value);
* a rename with its preview (every cell that changes) and the secrets.env / ``RR_VAR_`` entries of the old name copied to the new one
  (copied, not moved: undoing the rename in the workbook must still find the old ones);
* a secret's value: written to secrets.env only, never into the workbook, never sent back (only "set" / "not set" per environment);
* ``GET /api/workbooks/{name}/download-info``: the names of the secrets a saved workbook uses, so Download can say they are not in the file.

Secret values are never logged, returned or put into an error message here.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ..build.recorder import store_secret
from ..config import load_env_file
from ..workbook.builder import (BuildError, BuildStore, TOKEN_RE, read_environments, rename_preview, secrets_used,
                                variable_values)
from ..workbook.variables import secret_value
from ..workbook.writer import WorkbookEditor
from .build_api import BuildApiError


def secret_keys(name: str, environments: list[str]) -> list[str]:
    """The secrets.env keys that can hold variable ``name``'s value, most specific first (``secret_value``'s lookup order)."""
    key = name.upper()
    return [f"RR_SECRET_{e.upper()}_{key}" for e in environments] + [f"RR_SECRET_{key}", f"RR_VAR_{key}"]


def secret_status(name: str, environments: list[str], environ: Any = None) -> dict:
    """Whether ``name`` has a value in each environment (and one for every environment), from secrets.env: booleans only, never a value."""
    env = os.environ if environ is None else environ
    key = name.upper()
    return {"name": name, "environments": {e: secret_value(name, e, env) is not None for e in environments},
            "everywhere": bool(env.get(f"RR_SECRET_{key}") or env.get(f"RR_VAR_{key}")),
            "perEnvironment": {e: bool(env.get(f"RR_SECRET_{e.upper()}_{key}")) for e in environments}}


def copy_secret_entries(path: Path, old: str, new: str, environments: list[str]) -> list[str]:
    """After a rename, give the new name every secrets.env entry the old one had (``RR_SECRET_<ENV>_OLD``, ``RR_SECRET_OLD``, ``RR_VAR_OLD``).
    The old entries stay: the rename can be undone in the workbook.  Returns the new keys written (never a value); a new key that already
    holds another value is left as it is."""
    if not path.is_file():
        return []
    held: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and not line.strip().startswith("#"):
            held[k.strip()] = v.strip().strip('"').strip("'")
    written = []
    for old_key, new_key in zip(secret_keys(old, environments), secret_keys(new, environments)):
        if old_key in held and held[old_key] and store_secret(path, new_key, held[old_key]) == "added":
            written.append(new_key)
    return written


def register_variables_routes(app: FastAPI, mgr: Any, store: BuildStore) -> None:
    def doc(name: str):
        cfg = mgr.current()
        return store.get(mgr.resolve_workbook(name), cfg.path(cfg.runs_dir))

    def secrets_file() -> Path:
        return mgr.current().base_dir / "secrets.env"

    async def run(fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except BuildError as err:
            raise BuildApiError(err.status, str(err), err.kind, **err.extra) from err

    def names_of(d) -> list[str]:
        with d.lock:
            return list(read_environments(d.editor)["names"])

    @app.get("/api/build/workbooks/{name}/variables/{token}/values")
    async def variable_detail(name: str, token: str):
        """``{token, sources: [{sheet, column, tests, rows: [{row, label, enabled, value, formula}]}], environment, environments, secret}``."""
        d = doc(name)
        model = await run(d.model)
        v = next((x for x in model["variables"] if x["key"] == token.upper()), None)
        if v is None:
            raise BuildApiError(404, f"There is no variable called {token}.", "not_found")
        sheets = [s["sheet"] for s in v["sources"]]

        def read() -> dict:
            with d.lock:
                return variable_values(d.editor, v["token"], sheets, secret=v["secret"])
        out = await run(read)
        load_env_file(secrets_file())                                    # (secrets.env edited by hand since: this reads it again)
        out["secret"] = secret_status(v["token"], out["environments"]["names"]) if v["secret"] else None
        return out

    @app.post("/api/build/workbooks/{name}/variables/rename-preview")
    async def variable_rename_preview(name: str, body: dict[str, Any]):
        """``{from, to}`` -> ``{changes: [{sheet, row, column, header, before, after}], secrets: [keys that get copied]}`` (nothing changes)."""
        d = doc(name)
        old, new = str(body.get("from") or "").strip(), str(body.get("to") or "").strip()
        if old.upper() == "DOMAIN" and new.upper() != "DOMAIN":
            raise BuildApiError(400, "DOMAIN keeps its name: the build window and every run open the address it holds.", "domain")

        def preview() -> list[dict]:
            with d.lock:
                return rename_preview(d.editor, old, new)
        changes = await run(preview)
        load_env_file(secrets_file())
        envs = names_of(d)
        held = [k for k in secret_keys(old, envs) if os.environ.get(k)]
        return {"changes": changes, "secrets": [n for o, n in zip(secret_keys(old, envs), secret_keys(new, envs)) if o in held]}

    @app.post("/api/build/workbooks/{name}/variables/rename")
    async def variable_rename(name: str, body: dict[str, Any], env: str | None = None):
        """``{from, to, version}``: the ``rename_variable`` op (one undo step) plus the secrets.env entries copied to the new name."""
        d = doc(name)
        old, new = str(body.get("from") or "").strip(), str(body.get("to") or "").strip()
        if old.upper() == "DOMAIN" and new.upper() != "DOMAIN":
            raise BuildApiError(400, "DOMAIN keeps its name: the build window and every run open the address it holds.", "domain")
        applied = await run(d.apply, [{"op": "rename_variable", "from": old, "to": new}], body.get("version"))
        copied = await asyncio.to_thread(copy_secret_entries, secrets_file(), old, new, names_of(d))
        return {"model": await run(d.model, env or body.get("env")), "applied": applied, "secretsCopied": copied}

    @app.post("/api/build/workbooks/{name}/variables/secret")
    async def variable_secret(name: str, body: dict[str, Any]):
        """``{name, environment?, value}``: ``value`` goes into secrets.env as ``RR_SECRET_<ENV>_<NAME>`` (``RR_SECRET_<NAME>`` with no
        environment: every environment), replacing what that key held.  Never into the workbook.  Answers with the status, never the value."""
        d = doc(name)
        token = str(body.get("name") or "").strip()
        environment = str(body.get("environment") or "").strip()
        value = body.get("value")
        if not TOKEN_RE.match(token):
            raise BuildApiError(400, "A secret's name is letters, digits and _ (starting with a letter).", "name")
        if not isinstance(value, str) or not value:
            raise BuildApiError(400, "Type the secret's value.", "value")
        envs = names_of(d)
        if environment and environment.upper() not in {e.upper() for e in envs}:
            raise BuildApiError(400, f"This workbook has no environment called {environment}.", "environment")
        key = f"RR_SECRET_{environment.upper()}_{token.upper()}" if environment else f"RR_SECRET_{token.upper()}"
        try:
            await asyncio.to_thread(store_secret, secrets_file(), key, value, replace=True)
        except BuildError as err:                                     # (its messages never hold the value)
            raise BuildApiError(err.status, str(err), err.kind) from err
        return {"key": key, **secret_status(token, envs)}

    @app.get("/api/workbooks/{name}/download-info")
    async def download_info(name: str):
        """What Download should say before handing the saved file over: ``{name, secrets: [names]}``.  A secret's value lives in secrets.env on
        this computer, never in the file, so whoever receives the workbook needs their own."""
        path = mgr.resolve_workbook(name)

        def read() -> list[str]:
            return secrets_used(WorkbookEditor.open(path))
        try:
            names = await asyncio.to_thread(read)
        except Exception:                                             # (not a workbook the builder can read: nothing to say about secrets)
            names = []
        return {"name": path.name, "secrets": names}
