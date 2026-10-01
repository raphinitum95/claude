"""Share a run, and read what a test recorded of its browser session.

* ``GET  /api/runs/{id}/download.zip``: the whole run folder in one zip (report, results, events, every test's screenshots, saved pages, console /
  network / state logs, the workbook copy) to send to whoever helps investigate.  A browser trace (``trace.zip``) holds everything that was typed, so
  it only goes in when asked for (``?trace=1``).
* ``POST /api/runs/import``: take such a zip (or the smaller ``logs.zip``) from another computer and put it in ``runs/`` as an imported run.  The zip
  comes from another person, so nothing in it is trusted: paths are checked (no ``..``, no absolute paths, no links), sizes are capped, and an imported
  run is marked ``imported`` in its run.json so it never counts in this computer's history and its HTML is only served sandboxed (web/app.py).
* ``GET  /api/results/runs/{id}/tests/{test}/session``: the console, calls (with bodies) and field state a test recorded, grouped by step, for the
  Results test page.

Plain functions take paths, so the zip rules are unit-tested without a server (tests/test_run_share.py).  Kept out of ``web/app.py`` like the other
route modules.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from .. import __version__
from ..events import now_iso
from ..runmeta import read_meta
from ..workbook.model import slug

MAX_IMPORT_MB = 1024                     # a run folder with every screenshot; bigger than this is not a run (or is a bomb)
MAX_IMPORT_FILES = 50000
SHARE_MANIFEST = "share.json"
_SKIP_DIRS = {"cancel", "inbox"}         # control files of a live run, meaningless to someone else
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class ShareError(HTTPException):
    def __init__(self, status: int, message: str, kind: str = "", **extra: Any):
        super().__init__(status, message)
        self.kind, self.extra = kind, extra


# -- download ---------------------------------------------------------------------------------------------------------
def shareable_files(run_dir: Path, include_trace: bool = False) -> list[Path]:
    """Every file of the run folder that is worth sending (control files, half-written files and, unless asked for, browser traces left out)."""
    found = []
    for path in sorted(run_dir.rglob("*")):
        rel = path.relative_to(run_dir)
        if not path.is_file() or path.is_symlink() or rel.parts[0] in _SKIP_DIRS or path.name.endswith(".tmp"):
            continue
        if not include_trace and path.name.startswith("trace") and path.suffix == ".zip":
            continue
        found.append(path)
    return found


def build_download(run_dir: Path, target: Path, include_trace: bool = False) -> int:
    """Zip ``run_dir`` into ``target`` under one top-level folder named like the run.  Returns the number of files."""
    run_id = run_dir.name
    files = shareable_files(run_dir, include_trace)
    manifest = {"kind": "regrunner-run", "format": 1, "run_id": run_id, "regrunner": __version__, "exported_at": now_iso(),
                "python": sys.version.split()[0], "platform": sys.platform, "includes_trace": include_trace and any(p.name.startswith("trace") for p in files)}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in files:
            bundle.write(path, f"{run_id}/{path.relative_to(run_dir).as_posix()}")
        bundle.writestr(f"{run_id}/{SHARE_MANIFEST}", json.dumps(manifest, indent=2))
    return len(files)


# -- import -----------------------------------------------------------------------------------------------------------
def _clean_member(name: str) -> PurePosixPath | None:
    """A zip member's path made safe, or None when it must be skipped (empty, absolute, drive letter, or climbing out with ``..``)."""
    path = PurePosixPath(name.replace("\\", "/"))
    if not path.parts or path.is_absolute() or any(part in ("..", "") for part in path.parts) or re.match(r"^[A-Za-z]:", path.parts[0]):
        return None
    return path


def plan_import(bundle: zipfile.ZipFile) -> tuple[str, list[tuple[zipfile.ZipInfo, PurePosixPath]]]:
    """Which folder of the zip is the run (the one with ``run.json``) and which members to unpack, each with its path relative to that folder.
    Raises ShareError for anything that is not exactly one run."""
    members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for info in bundle.infolist():
        if info.is_dir():
            continue
        clean = _clean_member(info.filename)
        if clean is None:
            raise ShareError(400, f"The zip holds an unsafe path ({info.filename!r}), so it was not imported.", "unsafe")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:      # a symbolic link: never followed
            continue
        members.append((info, clean))
    if len(members) > MAX_IMPORT_FILES:
        raise ShareError(413, f"The zip holds {len(members):,} files; a run never has that many.", "size")
    if sum(info.file_size for info, _ in members) > MAX_IMPORT_MB * 1024 * 1024 * 2:
        raise ShareError(413, f"The zip unpacks to more than {MAX_IMPORT_MB * 2} MB.", "size")
    roots = sorted({str(p.parent) for _, p in members if p.name == "run.json"}, key=lambda r: r.count("/"))
    if not roots:
        raise ShareError(400, "That zip is not a run: it has no run.json. Use a run's Download button (or its logs.zip).", "content")
    top = [r for r in roots if r.count("/") == roots[0].count("/")]
    if len(top) > 1:
        raise ShareError(400, "That zip holds several runs. Import them one at a time.", "content")
    root = PurePosixPath(roots[0])
    inside = members if root == PurePosixPath(".") else [(info, p.relative_to(root)) for info, p in members if root in p.parents]
    return str(root), inside


def import_name(runs_dir: Path, wanted: str) -> str:
    """The run id to store it under: its own when free, else with ``-imported`` (and a number) after it."""
    base = _SAFE_ID.sub("_", wanted).strip("._-") or "run"
    candidate, n = base, 1
    while (runs_dir / candidate).exists():
        candidate = f"{base}-imported" + (f"-{n}" if n > 1 else "")
        n += 1
    return candidate


def import_run(zip_path: Path, runs_dir: Path, *, fallback_name: str = "run") -> dict[str, Any]:
    """Unpack the run in ``zip_path`` into ``runs_dir`` (a new folder), marked as imported.  Returns what the screen shows about it."""
    try:
        bundle = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as err:
        raise ShareError(400, "That file is not a zip.", "content") from err
    with bundle:
        root, members = plan_import(bundle)
        names = {str(rel): info for info, rel in members}
        try:
            meta = json.loads(bundle.read(names["run.json"]).decode("utf-8"))
        except (KeyError, ValueError, OSError) as err:
            raise ShareError(400, "run.json in that zip cannot be read.", "content") from err
        if not isinstance(meta, dict) or not ("results.json" in names or "events.jsonl" in names):
            raise ShareError(400, "That zip has no results.json or events.jsonl, so there is nothing to look at.", "content")
        manifest: dict[str, Any] = {}
        if SHARE_MANIFEST in names:
            try:
                manifest = json.loads(bundle.read(names[SHARE_MANIFEST]).decode("utf-8"))
            except (ValueError, OSError):
                manifest = {}
        original = str(meta.get("run_id") or (root if root != "." else "") or fallback_name)
        runs_dir.mkdir(parents=True, exist_ok=True)
        new_id = import_name(runs_dir, original)
        staging = runs_dir / f".import-{os.getpid()}-{new_id}"
        shutil.rmtree(staging, ignore_errors=True)
        limit = MAX_IMPORT_MB * 1024 * 1024
        written = 0
        try:
            for rel, info in names.items():
                if rel == "run.json":
                    continue                                       # (written last, so the run only shows up in the lists complete)
                target = (staging / rel).resolve()
                if not target.is_relative_to(staging.resolve()):
                    raise ShareError(400, f"The zip holds an unsafe path ({rel!r}), so it was not imported.", "unsafe")
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(1024 * 1024):
                        written += len(chunk)
                        if written > limit * 2:
                            raise ShareError(413, f"The zip unpacks to more than {MAX_IMPORT_MB * 2} MB.", "size")
                        out.write(chunk)
            if new_id != original and (staging / "results.json").is_file():
                try:
                    data = json.loads((staging / "results.json").read_text(encoding="utf-8"))
                    data["run_id"] = new_id
                    (staging / "results.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                except (OSError, ValueError):
                    pass
            batch = {k: meta.pop(k) for k in ("batch_id", "batch_label") if k in meta}      # a batch of the other computer is not a batch here
            meta.update(run_id=new_id, imported=True, imported_at=now_iso(), imported_from=original,
                        **({"imported_batch": batch} if batch else {}), **({"imported_regrunner": manifest["regrunner"]} if manifest.get("regrunner") else {}))
            (staging / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            os.replace(staging, runs_dir / new_id)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    results = runs_dir / new_id / "results.json"
    tests = 0
    try:
        tests = len(json.loads(results.read_text(encoding="utf-8")).get("tests", []))
    except (OSError, ValueError):
        pass
    return {"run_id": new_id, "original_run_id": original, "renamed": new_id != original, "status": meta.get("status"),
            "workbook": Path(str(meta.get("workbook") or "")).name, "tests": tests, "files": len(names),
            "has_screenshots": any(r.endswith(".jpg") for r in names)}


# -- the session a test recorded --------------------------------------------------------------------------------------
def _read_lines(path: Path, limit: int = 20000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if len(rows) >= limit:
                    break
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def build_session(run_dir: Path, test_id: str) -> dict[str, Any]:
    """What ``tests/<test>/`` recorded, grouped by step: console lines, first-party calls (with bodies), and the state lines in order."""
    folder = run_dir / "tests" / slug(test_id)
    if not folder.is_dir():
        raise ShareError(404, "test not found in this run", "not_found")
    console = _read_lines(folder / "console.jsonl")
    network = _read_lines(folder / "network.jsonl")
    state = _read_lines(folder / "state.jsonl")
    steps: dict[str, dict[str, list]] = {}
    for kind, rows in (("console", console), ("calls", network)):
        for row in rows:
            steps.setdefault(str(row.get("step") or 0), {"console": [], "calls": []})[kind].append(row)
    traces = sorted(p.name for p in folder.glob("trace*.zip"))
    return {"has": {"console": bool(console), "network": bool(network), "state": bool(state), "bodies": any("response_body" in r or "request_body" in r for r in network)},
            "steps": steps, "state": state, "traces": [f"tests/{folder.name}/{n}" for n in traces]}


def register_share_routes(app: FastAPI, mgr: Any) -> None:
    """Add the share and session routes (``mgr`` = the RunManager).  The request guard of ``create_app`` already covers them (localhost Host,
    ``X-Requested-With`` + local Origin on POST)."""

    @app.exception_handler(ShareError)
    async def share_error(_, exc: ShareError):
        return JSONResponse({"error": exc.detail, "kind": exc.kind, **exc.extra}, status_code=exc.status_code)

    @app.get("/api/runs/{run_id}/download.zip")
    async def download_run(run_id: str, trace: int = 0):
        run_dir = mgr.run_dir(run_id)
        if read_meta(run_dir) is None:
            raise ShareError(404, "run not found", "not_found")
        if mgr.is_active(run_id):
            raise ShareError(409, "This run is still going. Download it when it has finished.", "busy")
        handle, name = tempfile.mkstemp(prefix="regrunner-run-", suffix=".zip")
        os.close(handle)
        target = Path(name)
        try:
            await asyncio.to_thread(build_download, run_dir, target, bool(trace))
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return FileResponse(target, media_type="application/zip", filename=f"{run_id}.zip", background=BackgroundTask(lambda: target.unlink(missing_ok=True)))

    @app.post("/api/runs/import")
    async def import_a_run(file: UploadFile = File(...)):
        if Path(file.filename or "").suffix.lower() != ".zip":
            raise ShareError(400, "Choose the .zip a run's Download button made.", "type")
        handle, name = tempfile.mkstemp(prefix="regrunner-import-", suffix=".zip")
        target = Path(name)
        try:
            with os.fdopen(handle, "wb") as out:
                size = 0
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_IMPORT_MB * 1024 * 1024:
                        raise ShareError(413, f"That file is larger than {MAX_IMPORT_MB} MB.", "size")
                    out.write(chunk)
            return await asyncio.to_thread(import_run, target, mgr.runs_dir(), fallback_name=Path(file.filename or "run").stem)
        finally:
            target.unlink(missing_ok=True)

    @app.get("/api/results/runs/{run_id}/tests/{test_id}/session")
    async def test_session(run_id: str, test_id: str):
        run_dir = mgr.run_dir(run_id)
        if read_meta(run_dir) is None:
            raise ShareError(404, "run not found", "not_found")
        return await asyncio.to_thread(build_session, run_dir, test_id)
