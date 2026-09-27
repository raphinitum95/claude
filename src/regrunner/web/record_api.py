"""``/api/build/session/{name}/record|check|save|prompt`` (P09): recording in the build window and "Check this / Save this" from the Build tab
(``build/recorder.py``).  Registered by ``build_api.register_session_routes`` (one line), which owns the build windows these act on."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

from ..build.session import BuildSession, SessionStore
from ..workbook.builder import BuildError


def register_record_routes(app: FastAPI, mgr: Any, doc, run, sessions: SessionStore) -> None:
    from .build_api import BuildApiError

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

    def row_of(body: dict, key: str = "after") -> int | None:
        value = body.get(key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise BuildApiError(400, f"{key} is a row number.", key) from None

    async def edited(name: str, s: BuildSession, applied: list, env: str | None) -> dict:
        return {"applied": applied, "model": await run(doc(name).model, env), "session": await asyncio.to_thread(s.state, 0)}

    @app.post("/api/build/session/{name}/record")
    async def session_record(name: str, body: dict[str, Any]):
        """``{on, after?}``: recording on (new steps go after row ``after``, default the last step) or off."""
        s = live(name)
        await act(s.recorder.start(row_of(body)) if body.get("on") else s.recorder.stop())
        return await asyncio.to_thread(s.state, 0)

    @app.post("/api/build/session/{name}/check")
    async def session_check(name: str, body: dict[str, Any], env: str | None = None):
        """``{kind, expected?, token?, after?}``: a check / wait of the element picked in Check or Wait until mode (``recorder.CHECK_KINDS``)."""
        s = live(name)
        applied = await act(s.recorder.add_check(str(body.get("kind") or ""), str(body.get("expected") or ""), str(body.get("token") or ""),
                                                 row_of(body)))
        return await edited(name, s, applied, env)

    @app.post("/api/build/session/{name}/save")
    async def session_save(name: str, body: dict[str, Any], env: str | None = None):
        """``{token, after?}``: save the picked element's text (a field's value) as the variable ``token``."""
        s = live(name)
        applied = await act(s.recorder.add_check("save", "", str(body.get("token") or ""), row_of(body)))
        return await edited(name, s, applied, env)

    @app.post("/api/build/session/{name}/prompt")
    async def session_prompt(name: str, body: dict[str, Any], env: str | None = None):
        """``{id, choice, token?, fields?}``: answer a recorder prompt (keep / fixed / rename a typed value, keep raw clicks, save a fingerprint
        and add its gate - ``fields`` overrides name / urlContains / landmark / landmarkText -, unflag a side effect, dismiss)."""
        s = live(name)
        fields = body.get("fields") if isinstance(body.get("fields"), dict) else None
        applied = await act(s.recorder.answer(str(body.get("id") or ""), str(body.get("choice") or ""), token=str(body.get("token") or ""),
                                              fields=fields))
        return await edited(name, s, applied, env)
