"""How a run joins a process that is already going (the web UI: "New run" while a run is in progress).

The UI server writes the new run's request as ``<inbox>/<run id>.json``; the process that owns the workers picks it up, prepares the run and
adds it to its pool.  The two never talk directly, so it is all files, and it is safe on every OS:

* the server writes ``<id>.tmp`` and renames it to ``<id>.json`` (a half-written request is never seen);
* the process *claims* a request by renaming it to ``<id>.claimed`` (only one of the two ever wins that rename);
* a process that is about to end first creates ``CLOSED``, then looks for requests one last time.  A server that wrote after that sees
  ``CLOSED`` and takes its request back (``retract``); if it cannot (the file is gone) the process has it and will run it.
  Either the process sees the request or the server sees ``CLOSED`` - never neither - so a run is never lost.
* a request the process cannot use is answered with ``<id>.rejected`` (the reason as text).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CLOSED = "CLOSED"


def _names(folder: Path, run_id: str) -> tuple[Path, Path, Path, Path]:
    return (folder / f"{run_id}.tmp", folder / f"{run_id}.json", folder / f"{run_id}.claimed", folder / f"{run_id}.rejected")


def is_closed(folder: Path) -> bool:
    return (folder / CLOSED).exists() or not folder.is_dir()


def post(folder: Path, run_id: str, request: dict[str, Any]) -> bool:
    """Hand a request to the process that owns ``folder``.  True = posted (a process is or will be looking); False = it is closed or gone:
    start a new process for this run instead."""
    tmp, final, _claimed, _rejected = _names(folder, run_id)
    if is_closed(folder):
        return False
    try:
        tmp.write_text(json.dumps(request), encoding="utf-8")
        os.replace(tmp, final)
    except OSError:
        return False
    if (folder / CLOSED).exists() and retract(folder, run_id):           # closed while we were writing: did the process see it?
        return False
    return True


def retract(folder: Path, run_id: str) -> bool:
    """Take a request back.  True = it had not been claimed (nothing will run it); False = the process already has it."""
    _tmp, final, _claimed, _rejected = _names(folder, run_id)
    try:
        final.unlink()
        return True
    except OSError:
        return False


def answer(folder: Path, run_id: str) -> str:
    """What the process said about a request: ``claimed`` (it took it; the run will announce itself), ``rejected:<why>``, or ``waiting``."""
    _tmp, final, claimed, rejected = _names(folder, run_id)
    if rejected.exists():
        try:
            return "rejected:" + rejected.read_text(encoding="utf-8")
        except OSError:
            return "rejected:the running process refused it"
    if claimed.exists():
        return "claimed"
    return "waiting" if final.exists() else "claimed"


class Inbox:
    """The receiving side (inside the process that owns the workers)."""

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def claim(self) -> list[tuple[str, dict[str, Any]]]:
        """Every request that is waiting, oldest first, each renamed so nobody else can take it."""
        out: list[tuple[str, dict[str, Any]]] = []
        try:
            waiting = sorted(self.folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
        except OSError:
            return out
        for path in waiting:
            run_id = path.stem
            _tmp, final, claimed, rejected = _names(self.folder, run_id)
            try:
                os.replace(final, claimed)                                   # only one side wins this
            except OSError:
                continue
            try:
                request = json.loads(claimed.read_text(encoding="utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("not a request")
            except (OSError, ValueError) as err:
                self.reject(run_id, f"the request could not be read ({err})")
                continue
            out.append((run_id, request))
        return out

    def reject(self, run_id: str, why: str) -> None:
        try:
            self._rejected(run_id).write_text(why, encoding="utf-8")
        except OSError:
            pass

    def _rejected(self, run_id: str) -> Path:
        return _names(self.folder, run_id)[3]

    def close(self) -> None:
        """No new run will be taken from here on (a server that posts after this starts a process of its own)."""
        try:
            (self.folder / CLOSED).write_text("closed", encoding="utf-8")
        except OSError:
            pass
