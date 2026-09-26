"""Local web UI: FastAPI + a static single-page app (no build step).

* Runs are separate ``regrunner run`` subprocesses (own low priority, crash-isolated from the UI).
* Progress is the runner's ``events.jsonl`` tailed over a websocket - the exact stream the console reads -
  so a finished run "replays" through the same code path as a live one.
* Every option the CLI has is a field of :class:`StartRun`; the command line shown in the UI is built by the
  same function that builds the subprocess arguments, so the two cannot drift apart.
* Bound to localhost by default.  There is no login, so state-changing requests must come from this very
  page (Host, Origin and a custom header are checked), which stops another website in the user's browser
  from starting runs.  Do not expose it to a network.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .. import __version__, browsers, insight
from ..config import Config, load_config, load_env_file, workbook_secrets
from ..engine import inbox as inbox_mod
from ..engine.ask import write_answer
from ..engine.order import chains_file, clean_chains, load_chains, plan_order, save_chains
from ..engine.runner import RunOptions, SelectionError, new_run_id, select_cases
from ..events import now_iso, read_events
from ..preflight import browser_check, run_preflight, token_state
from ..runmeta import read_meta, update_meta
from ..signin import SignInError, SignInSession
from ..workbook.model import Workbook
from .build_api import register_build_routes
from .presence import UiPresence

STATIC = Path(__file__).parent / "static"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CLIENT_HEADER = "x-requested-with"               # a custom header cannot be sent cross-site without a CORS preflight
CLIENT_VALUE = "regrunner"
MAX_UPLOAD_MB = 50
CANCEL_GRACE_S = 45          # a cancel first lets the running steps finish...
KILL_AFTER_S = 12            # ...then the runner is told to stop now, and killed if it still has not gone after this long
STALE_S = 90
JOIN_WAIT_S = 240             # a run joining workers that are going waits this long to be taken in (the process reads its workbook first: seconds for a big one)
CLOSED_WAIT_S = 45           # a process that has just finished its last run needs this long to leave before another can start


class ApiError(HTTPException):
    def __init__(self, status: int, message: str, kind: str = "", **extra: Any):
        super().__init__(status, message)
        self.kind, self.extra = kind, extra


class UiPage(BaseModel):
    page: str = Field(min_length=1, max_length=64)       # a random id the page picks, so two open windows are told apart


class Answer(BaseModel):
    """A person's answer to a question the run is waiting on (an ASK_USER step)."""
    ask: str
    answer: str = Field(default="", max_length=2000)


class WorkbookPick(BaseModel):
    """One workbook of a run that covers several: which of its tests run, and in what order (each workbook has its own)."""
    workbook: str
    tests: list[str] = Field(default_factory=list, max_length=500)
    tag: str | None = None
    all: bool = False
    chains: list[list[Annotated[str, Field(max_length=120)]]] | None = Field(default=None, max_length=50)     # None = the saved ones


class StartRun(BaseModel):
    """Everything ``regrunner run`` accepts, minus what only makes sense on a terminal.

    One workbook is the fields ``workbook`` / ``tests`` / ``tag`` / ``all`` / ``chains``; several are ``workbooks`` (one entry each: its own tests and
    chains).  Everything else is shared by all of them, and each workbook becomes a run of its own on one set of workers."""
    workbook: str = ""
    tests: list[str] = Field(default_factory=list, max_length=500)
    tag: str | None = None
    all: bool = False
    workbooks: list[WorkbookPick] | None = Field(default=None, min_length=1, max_length=24)
    env: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{0,16}$")
    workers: int | None = Field(default=None, ge=1, le=64)
    screenshots: Literal["every_step", "on_failure", "off"] | None = None
    retries: int | None = Field(default=None, ge=0, le=10)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    pdf: bool | None = None
    harvest: bool | None = None
    browser: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_ -]{0,24}$")     # chrome | msedge | safari | chromium; None = the one config.yaml selects
    headed: bool = False
    nice: bool | None = None
    no_report: bool = False
    allow_prod: bool = False
    confirm_prod: str = ""                        # must be the word PROD when the run targets PROD
    chains: list[list[Annotated[str, Field(max_length=120)]]] | None = Field(default=None, max_length=50)     # tests that run one after another; None = the saved ones

    @model_validator(mode="after")
    def _one_way_of_naming_the_workbooks(self):
        if self.workbooks is None and not self.workbook:
            raise ValueError("Say which workbook to run.")
        if self.workbooks is not None and self.workbook:
            raise ValueError("Give either workbook or workbooks, not both.")
        names = [Path(p.workbook).name.lower() for p in (self.workbooks or [])]
        if len(set(names)) != len(names):
            raise ValueError("A workbook can only be in a run once: two runs of the same workbook would fill in the same parameter cells.")
        return self

    def picks(self) -> list[WorkbookPick]:
        """The workbooks to run, each with its own tests and chains."""
        if self.workbooks is not None:
            return list(self.workbooks)
        return [WorkbookPick(workbook=self.workbook, tests=self.tests, tag=self.tag, all=self.all, chains=self.chains)]


# -------------------------------------------------------------------------------------------------
# command line (single source of truth for what the UI shows and what the subprocess receives)
# -------------------------------------------------------------------------------------------------
def quote_arg(text: str) -> str:
    return f'"{text.replace(chr(34), chr(92) + chr(34))}"' if re.search(r"[\s\"'&|<>()^;]", text) else text


def _flagger(out: list[tuple[str, str]]):
    def flag(name: str, value: Any = None) -> None:
        out.append(("flag", name))
        if value is not None:
            out.append(("value", str(value)))
    return flag


def selection_flags(pick: WorkbookPick) -> list[tuple[str, str]]:
    """Which of the workbook's tests run."""
    out: list[tuple[str, str]] = []
    flag = _flagger(out)
    if pick.all:
        flag("--all")
    elif pick.tests:
        flag("--tests", ",".join(pick.tests))
    elif pick.tag:
        flag("--tag", pick.tag)
    return out


def chain_flags(pick: WorkbookPick) -> list[tuple[str, str]]:
    """The tests that run one after another in this workbook (nothing to say when they are the saved ones)."""
    out: list[tuple[str, str]] = []
    flag = _flagger(out)
    if pick.chains is not None:
        if not pick.chains:
            flag("--no-chains")
        for chain in pick.chains:
            flag("--chain", ",".join(chain))
    return out


def cli_flags(req: StartRun, cfg: Config, environment: str) -> list[tuple[str, str]]:
    """``(kind, text)`` tokens for ``regrunner run`` with one workbook: its test selection, the settings, then its chains.  A flag appears only when it
    differs from config.yaml.  (Several workbooks: :func:`batch_tokens`.)"""
    pick = req.picks()[0]
    return [*selection_flags(pick), *shared_flags(req, cfg, environment), *chain_flags(pick)]


def shared_flags(req: StartRun, cfg: Config, environment: str) -> list[tuple[str, str]]:
    """The settings every workbook of a run shares."""
    out: list[tuple[str, str]] = []
    flag = _flagger(out)
    if req.env:
        flag("--env", req.env.upper())
    if environment == "PROD" and req.allow_prod:
        flag("--allow-prod")
    if req.workers is not None and req.workers != cfg.effective_workers:
        flag("--workers", req.workers)
    if req.screenshots is not None and req.screenshots != cfg.screenshots.mode:
        flag("--screenshots", req.screenshots)
    if req.retries is not None and req.retries != cfg.behaviour.retries:
        flag("--retries", req.retries)
    if req.seed is not None:
        flag("--seed", req.seed)
    if req.pdf is not None and req.pdf != cfg.reports.pdf:
        flag("--pdf" if req.pdf else "--no-pdf")
    if req.harvest is not None and req.harvest != cfg.selectors.harvest:
        flag("--harvest" if req.harvest else "--no-harvest")
    if req.browser and browsers.resolve(req.browser).id != cfg.browser.kind.id:
        flag("--browser", browsers.resolve(req.browser).id)
    if req.headed:
        flag("--headed")
    if req.nice is not None and req.nice != cfg.runner.low_priority:
        flag("--nice" if req.nice else "--no-nice")
    if req.no_report:
        flag("--no-report")
    return out


def command_tokens(workbook_name: str, flags: list[tuple[str, str]]) -> list[dict[str, str]]:
    head = [("cmd", "regrunner"), ("cmd", "run"), ("arg", quote_arg(workbook_name))]
    return [{"k": k, "t": t} for k, t in head + flags]


def batch_tokens(req: StartRun, cfg: Config, names: list[str], environment: str) -> list[dict[str, str]]:
    """The command for a run that covers several workbooks: each workbook with its own tests and chains, then the shared settings.  One workbook
    gives the same line as :func:`command_tokens`."""
    picks = req.picks()
    if len(picks) == 1:
        return command_tokens(names[0], cli_flags(req, cfg, environment))
    out: list[tuple[str, str]] = [("cmd", "regrunner"), ("cmd", "run")]
    for pick, name in zip(picks, names):
        out += [("arg", quote_arg(name)), *selection_flags(pick), *chain_flags(pick)]
    out += shared_flags(req, cfg, environment)
    return [{"k": k, "t": t} for k, t in out]


# -------------------------------------------------------------------------------------------------
@dataclass
class Entry:
    """One workbook of a start request, worked out: which tests, in which environment, and the run it will be."""
    pick: WorkbookPick
    path: Path
    environment: str
    test_ids: list[str]
    run_id: str = ""
    run_dir: Path | None = None
    tokens: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PoolInfo:
    """A runner process and the runs on its workers.  Runs started together, and runs that joined later, are all its ``run_ids``."""
    id: str
    proc: Any
    dir: Path                                 # its inbox: where a run that wants to join is put (engine/inbox.py)
    run_ids: list[str]
    browser: str
    headed: bool
    stopping: bool = False                    # it was told to stop now: nothing may join


class RunManager:
    """Spawns and supervises runner subprocesses.  One process carries every run started together, and later runs that join it (they share its workers)."""

    def __init__(self, cfg: Config, config_path: str | None = None):
        self.cfg = cfg
        self.config_path = config_path
        self.procs: dict[str, asyncio.subprocess.Process] = {}
        self.pools: dict[str, PoolInfo] = {}
        self.pool_of: dict[str, str] = {}                       # run id -> pool id
        self.cancel_until: dict[str, float] = {}                # run id -> when its graceful cancel runs out (time.time())
        self._gate: asyncio.Lock | None = None                  # one start at a time (made on first use: Python 3.9 binds a Lock to the loop that is current when it is created)
        self._tasks: set[asyncio.Task] = set()
        self._derived: dict[str, tuple[float, dict[str, Any]]] = {}

    def current(self) -> Config:
        """A freshly loaded config, so edits to config.yaml / secrets.env apply without restarting the UI."""
        if not self.config_path:
            return self.cfg
        try:
            return load_config(self.config_path, base_dir=self.cfg.base_dir)
        except Exception:
            return self.cfg

    def runs_dir(self) -> Path:
        d = self.cfg.path(self.cfg.runs_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
            raise ApiError(400, "bad run id")
        return self.runs_dir() / run_id

    def is_active(self, run_id: str) -> bool:
        proc = self.procs.get(run_id)
        run_dir = self.run_dir(run_id)
        meta = read_meta(run_dir)
        if proc is not None:                                    # (a run that shares its process with others is over when it says so, not when the process ends)
            return proc.returncode is None and (meta is None or meta.get("status") == "RUNNING")
        events = run_dir / "events.jsonl"
        fresh = events.exists() and time.time() - events.stat().st_mtime < STALE_S
        return bool(meta and meta.get("status") == "RUNNING" and fresh)

    def active_runs(self) -> list[str]:
        return [rid for rid in self.procs if self.is_active(rid)]

    def active_pools(self) -> list[PoolInfo]:
        return [p for p in self.pools.values() if p.proc.returncode is None]

    def pool_state(self, run_id: str) -> dict[str, Any] | None:
        """What the page needs to know about the workers a run is on: could another run join them, and with which browser."""
        pool = self.pools.get(self.pool_of.get(run_id, ""))
        if pool is None or pool.proc.returncode is not None:
            return None
        return {"id": pool.id, "browser": pool.browser, "headed": pool.headed,
                "joinable": not pool.stopping and not inbox_mod.is_closed(pool.dir), "runs": list(pool.run_ids)}

    def resolve_workbook(self, name: str) -> Path:
        base = self.cfg.path(self.cfg.workbooks_dir)
        candidate = base / Path(name).name
        if not candidate.is_file():
            raise ApiError(404, f"workbook {name!r} not found", "not_found")
        return candidate

    # -- starting ----------------------------------------------------------------------------------
    def _validate(self, req: StartRun, pick: WorkbookPick, wb_path: Path, cfg: Config) -> tuple[str, list[str]]:
        """Load the workbook and check the selection *before* spawning anything.

        Returns the effective environment and the ids of the tests that will run.
        """
        try:
            if req.browser:
                browsers.resolve(req.browser)
        except browsers.BrowserError as err:
            raise ApiError(422, str(err), "browser") from err
        try:
            wb = Workbook(wb_path, environment=(req.env or None), secrets=workbook_secrets())
            cases = wb.discover()
        except Exception as err:
            raise ApiError(422, f"Could not read workbook: {err}", "unreadable") from err
        environment = (req.env or str(wb.global_settings().get("Environment", ""))).upper()
        try:
            if pick.all:
                chosen = [c for c in cases if c.runnable]
            else:
                chosen = select_cases(cases, RunOptions(workbook=wb_path, tests=pick.tests or None,
                                                        tags=[pick.tag] if pick.tag and not pick.tests else None), cfg)
            if not chosen:
                raise SelectionError("No tests selected. Pick at least one test.")
        except SelectionError as err:
            raise ApiError(422, (f"{wb_path.name}: " if len(req.picks()) > 1 else "") + str(err), "selection") from err
        return environment, [c.id for c in chosen]

    def preview(self, req: StartRun) -> dict[str, Any]:
        cfg = self.current()
        names = [self.resolve_workbook(p.workbook).name for p in req.picks()]
        environment = req.env.upper() if req.env else ""
        try:
            tokens = batch_tokens(req, cfg, names, environment)
        except browsers.BrowserError as err:
            raise ApiError(422, str(err), "browser") from err
        return {"tokens": tokens, "text": " ".join(t["t"] for t in tokens)}

    def _alone(self, req: StartRun, entry: Entry) -> StartRun:
        """The request as if this workbook were run by itself (its own command, and what is written to the inbox when it joins)."""
        pick = entry.pick
        return req.model_copy(update={"workbook": pick.workbook, "workbooks": None, "tests": pick.tests, "tag": pick.tag, "all": pick.all, "chains": pick.chains})

    def _busy(self, message: str, run_id: str) -> ApiError:
        return ApiError(409, message, "busy", run_id=run_id)

    async def start(self, req: StartRun) -> dict[str, Any]:
        if self._gate is None:
            self._gate = asyncio.Lock()
        async with self._gate:                                     # two starts at once must not both decide there is nobody to share workers with
            return await self._start(req)

    async def _start(self, req: StartRun) -> dict[str, Any]:
        cfg = self.current()
        entries = [Entry(pick=p, path=self.resolve_workbook(p.workbook), environment="", test_ids=[]) for p in req.picks()]
        going = {Path(str((read_meta(self.run_dir(r)) or {}).get("workbook", ""))).name.lower(): r for r in self.active_runs()}
        for e in entries:
            if e.path.name.lower() in going:                       # two runs of one workbook would place the same orders twice
                raise self._busy(f"{e.path.name} is already being run ({going[e.path.name.lower()]}). Wait for it or cancel it first.", going[e.path.name.lower()])
        for e in entries:
            e.environment, e.test_ids = await asyncio.to_thread(self._validate, req, e.pick, e.path, cfg)
        prod = [e.path.name for e in entries if e.environment == "PROD"]
        if prod and not (req.allow_prod and req.confirm_prod.strip() == "PROD"):
            raise ApiError(400, "PROD runs place real orders and send real emails. Confirm by typing PROD."
                           + (f" ({', '.join(prod)} would run against PROD.)" if len(entries) > 1 else ""), "prod_confirm")
        browser_id = browsers.resolve(req.browser).id if req.browser else cfg.browser.kind.id
        headed = bool(req.headed)

        active = self.active_pools()
        open_pools = [p for p in active if not p.stopping and not inbox_mod.is_closed(p.dir)]
        target = next((p for p in open_pools if p.browser == browser_id and p.headed == headed), None)
        if target is None and len(active) >= cfg.runner.max_concurrent_runs:
            if open_pools:
                p = open_pools[0]
                raise self._busy(f"Runs are in progress with {browsers.BY_ID[p.browser].label if p.browser in browsers.BY_ID else p.browser}"
                                 f"{' (windows shown)' if p.headed else ', headless'}. Runs share one set of workers, so a run started now must use the "
                                 "same browser and the same headed / headless choice. Change it to match, or wait for them or cancel them.",
                                 next((r for r in p.run_ids if self.is_active(r)), p.run_ids[0]))

        for e in entries:                                          # from here on the runs exist: a folder each, listed as running
            e.run_id = new_run_id(cfg, e.environment)
            e.run_dir = self.run_dir(e.run_id)
            e.run_dir.mkdir(parents=True, exist_ok=True)
            e.tokens = command_tokens(e.path.name, cli_flags(self._alone(req, e), cfg, e.environment))
            update_meta(e.run_dir, run_id=e.run_id, workbook=str(e.path), environment=e.environment, started_at=now_iso(), status="RUNNING",
                        command=" ".join(t["t"] for t in e.tokens), command_tokens=e.tokens, test_ids=e.test_ids, tests=len(e.test_ids))
        load_env_file(cfg.base_dir / "secrets.env")                # pick up tokens edited since the UI started

        joined: list[Entry] = []
        refused: list[tuple[Entry, str]] = []
        rest = entries
        if target is not None:
            joined, refused, rest = await self._join(target, req, cfg, entries)
        if rest:
            if len(self.active_pools()) >= cfg.runner.max_concurrent_runs:     # what was in the way is finishing: give it a moment
                await self._wait_for_room(cfg)
            await self._spawn(req, cfg, rest, browser_id, headed)
        if refused and not joined and not rest:
            for e, _why in refused:
                shutil.rmtree(e.run_dir, ignore_errors=True)
            raise ApiError(409, refused[0][1], "join")
        started = [e for e in entries if all(e is not r[0] for r in refused)]
        first = started[0]
        return {"run_id": first.run_id, "run_ids": [e.run_id for e in started], "command": " ".join(t["t"] for t in batch_tokens(req, cfg, [e.path.name for e in entries], "PROD" if prod else "")),
                "runs": [{"run_id": e.run_id, "workbook": e.path.name, "tests": len(e.test_ids)} for e in started], "joined": bool(joined),
                "refused": [{"workbook": e.path.name, "reason": why} for e, why in refused]}

    async def _wait_for_room(self, cfg: Config) -> None:
        deadline = time.monotonic() + CLOSED_WAIT_S
        while len(self.active_pools()) >= cfg.runner.max_concurrent_runs:
            if time.monotonic() > deadline:
                raise self._busy("The run that was in progress is still shutting down. Try again in a moment.", (self.active_runs() or [""])[0])
            await asyncio.sleep(0.3)

    def _own_flags(self, e: Entry) -> list[str]:
        return [t for _, t in [*selection_flags(e.pick), *chain_flags(e.pick)]]

    async def _spawn(self, req: StartRun, cfg: Config, entries: list[Entry], browser_id: str, headed: bool) -> PoolInfo:
        """A runner process for these runs (they are its first, and later runs may join it)."""
        first = entries[0]
        pool_dir = first.run_dir / "pool"
        pool_dir.mkdir(parents=True, exist_ok=True)               # made now, so a run started a moment later can already be handed in
        args = [sys.executable, "-m", "regrunner"]
        if self.config_path:
            args += ["--config", self.config_path]
        args += ["run"]
        for e in entries:
            args += [str(e.path), *self._own_flags(e), "--run-id", e.run_id]
        args += [t for _, t in shared_flags(req, cfg, "PROD" if any(e.environment == "PROD" for e in entries) else "")]
        args += ["--plain", "--ask", "ui", "--inbox", str(pool_dir)]
        log = (first.run_dir / "runner.log").open("wb")
        proc = await asyncio.create_subprocess_exec(*args, cwd=str(cfg.base_dir), stdout=log, stderr=asyncio.subprocess.STDOUT,
                                                    env={**os.environ, "PYTHONUNBUFFERED": "1"})
        pool = PoolInfo(id=first.run_id, proc=proc, dir=pool_dir, run_ids=[e.run_id for e in entries], browser=browser_id, headed=headed)
        self.pools[pool.id] = pool
        for e in entries:
            self.procs[e.run_id] = proc
            self.pool_of[e.run_id] = pool.id
            if e is not first:
                self._point_at_log(e, first.run_id)
        task = asyncio.get_running_loop().create_task(self._supervise(pool, log))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return pool

    @staticmethod
    def _point_at_log(e: Entry, first_id: str) -> None:
        """Runs that share a process share its log: it is written once, in the folder of the run that started the process."""
        try:
            (e.run_dir / "runner.log").write_text(f"This run shares one process with {first_id}: the log of that process is in that run's folder.\n", encoding="utf-8")
        except OSError:
            pass

    async def _join(self, pool: PoolInfo, req: StartRun, cfg: Config, entries: list[Entry]) -> tuple[list[Entry], list[tuple[Entry, str]], list[Entry]]:
        """Hand the runs to a process that is already going.  Returns (joined, refused with the reason, left over: it closed first, start those yourself)."""
        joined: list[Entry] = []
        refused: list[tuple[Entry, str]] = []
        for i, e in enumerate(entries):
            alone = self._alone(req, e)
            request = {"workbook": str(e.path), "tests": e.test_ids, "env": req.env, "browser": req.browser, "headed": bool(req.headed), "seed": req.seed,
                       "screenshots": req.screenshots, "retries": req.retries, "pdf": req.pdf, "harvest": req.harvest, "no_report": req.no_report,
                       "allow_prod": req.allow_prod, "nice": req.nice, "chains": alone.chains}
            if not await asyncio.to_thread(inbox_mod.post, pool.dir, e.run_id, request):
                return joined, refused, entries[i:]              # it closed while we were asking: nothing was handed over for these
            watch = asyncio.get_running_loop().create_task(self._watch_join(pool, e))
            self._tasks.add(watch)
            watch.add_done_callback(self._tasks.discard)
            try:
                state = await asyncio.wait_for(asyncio.shield(watch), JOIN_WAIT_S)
            except asyncio.TimeoutError:
                state = "joined"                                 # still being read by the process: the watcher above cleans up if it is refused
            if state == "retracted":
                return joined, refused, entries[i:]
            if state.startswith("rejected:"):
                refused.append((e, state[len("rejected:"):]))
                continue
            self.procs[e.run_id] = pool.proc
            self.pool_of[e.run_id] = pool.id
            pool.run_ids.append(e.run_id)
            self._point_at_log(e, pool.id)
            joined.append(e)
        return joined, refused, []

    async def _watch_join(self, pool: PoolInfo, e: Entry) -> str:
        """Until the process has taken a run (``joined``), refused it (``rejected:<why>``: the run's folder is removed) or gone before it could (``retracted``)."""
        events = e.run_dir / "events.jsonl"
        while True:
            said = await asyncio.to_thread(inbox_mod.answer, pool.dir, e.run_id)
            if said.startswith("rejected:"):
                shutil.rmtree(e.run_dir, ignore_errors=True)
                return said
            if events.exists():                                  # the process made the run: it is going
                return "joined"
            if pool.proc.returncode is not None or inbox_mod.is_closed(pool.dir) and said == "waiting":
                if await asyncio.to_thread(inbox_mod.retract, pool.dir, e.run_id):
                    return "retracted"
                if pool.proc.returncode is not None:
                    return "joined"                              # it had taken it and then died: _supervise closes the run
            await asyncio.sleep(0.25)

    async def _supervise(self, pool: PoolInfo, log) -> None:
        code = await pool.proc.wait()
        log.close()
        first_dir = self.run_dir(pool.id)
        for run_id in list(pool.run_ids):                        # every run the process still owed a finish to
            run_dir = self.run_dir(run_id)
            if not run_dir.is_dir():
                continue
            finished = any(e["type"] == "run_finished" for e in read_events(run_dir / "events.jsonl", 0)[0])
            if finished:
                continue
            # The runner died before finishing (crash, selection error, killed): close the stream ourselves.
            tail = ""
            try:
                tail = "\n".join((first_dir / "runner.log").read_text(errors="replace").splitlines()[-8:])
            except OSError:
                pass
            status = "CANCELLED" if (run_dir / "cancel").exists() else "ERROR"
            error = tail or f"runner exited with code {code}"
            update_meta(run_dir, status=status, ended_at=now_iso(), error=error, exit_code=code)
            with (run_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": "run_finished", "ts": now_iso(), "run_id": run_id, "status": status,
                                     "summary": {}, "artifacts": {}, "error": error, "exit_code": code}) + "\n")

    def _others_depend_on_the_process(self, pool: PoolInfo, run_id: str) -> bool:
        """Is some other run on this process still going and not already being cancelled?  Then the process cannot be stopped for this run's sake."""
        now = time.time()
        return any(r != run_id and self.is_active(r) and self.cancel_until.get(r, now + 1) > now for r in pool.run_ids)

    async def cancel(self, run_id: str) -> None:
        run_dir = self.run_dir(run_id)
        if not run_dir.is_dir():
            raise ApiError(404, "run not found", "not_found")
        (run_dir / "cancel").write_text("cancel", encoding="utf-8")      # graceful: runner finishes the current step
        update_meta(run_dir, cancel_requested_at=now_iso(), cancel_grace_s=CANCEL_GRACE_S)
        self.cancel_until[run_id] = time.time() + CANCEL_GRACE_S
        proc = self.procs.get(run_id)
        pool = self.pools.get(self.pool_of.get(run_id, ""))
        if proc is not None:
            async def hard_stop():
                await asyncio.sleep(CANCEL_GRACE_S)
                if proc.returncode is not None or not self.is_active(run_id):
                    return
                if pool is not None and self._others_depend_on_the_process(pool, run_id):
                    (run_dir / "stop").write_text("stop", encoding="utf-8")   # end this run's tests now: the process goes on for the others
                    await asyncio.sleep(KILL_AFTER_S + 8)
                    if proc.returncode is not None or not self.is_active(run_id) or self._others_depend_on_the_process(pool, run_id):
                        return
                if pool is not None:
                    pool.stopping = True
                proc.terminate()                                      # the runner turns this into "stop now" (a few seconds)
                try:
                    await asyncio.wait_for(proc.wait(), KILL_AFTER_S)
                except asyncio.TimeoutError:
                    if proc.returncode is None:
                        proc.kill()                                   # last resort: nothing can survive this
            task = asyncio.get_running_loop().create_task(hard_stop())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    # -- listing -----------------------------------------------------------------------------------
    @staticmethod
    def _tail_progress(events_file: Path) -> dict[str, Any] | None:
        try:
            size = events_file.stat().st_size
            with events_file.open("rb") as fh:
                fh.seek(max(0, size - 65536))
                chunk = fh.read()
        except OSError:
            return None
        for raw in reversed(chunk.splitlines()):
            if b'"run_progress"' in raw:
                try:
                    e = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                return {"done": e.get("done", 0), "total": e.get("total", 0), "percent": e.get("percent", 0)}
        return None

    def _first_event(self, events_file: Path) -> dict[str, Any] | None:
        try:
            with events_file.open("rb") as fh:
                return json.loads(fh.readline() or b"null")
        except (OSError, json.JSONDecodeError):
            return None

    def summarize(self, run_dir: Path) -> dict[str, Any] | None:
        meta = read_meta(run_dir)
        if not meta:
            return None
        meta = dict(meta)
        events_file = run_dir / "events.jsonl"
        if "test_ids" not in meta:                        # runs from before run.json carried the test ids
            key = str(events_file)
            stamp = events_file.stat().st_mtime if events_file.exists() else 0
            cached = self._derived.get(key)
            if cached is None or cached[0] != stamp:
                first = self._first_event(events_file) or {}
                ids = [t["id"] for t in first.get("tests", [])] if first.get("type") == "run_started" else []
                self._derived[key] = (stamp, {"test_ids": ids, "params": first.get("params")})
            meta.update({k: v for k, v in self._derived[key][1].items() if v is not None})
        meta["active"] = self.is_active(run_dir.name)
        if not meta["active"] and meta.get("status") == "RUNNING":
            meta["status"] = "INTERRUPTED"
        if meta["active"]:
            meta["progress"] = self._tail_progress(events_file)
            meta["pool"] = self.pool_state(run_dir.name)
        meta.pop("command_tokens", None)
        return meta

    def list_runs(self, limit: int = 200) -> list[dict[str, Any]]:
        out = []
        for d in self.runs_dir().iterdir():
            if d.is_dir():
                meta = self.summarize(d)
                if meta:
                    out.append(meta)
        return sorted(out, key=lambda m: m.get("started_at", ""), reverse=True)[:limit]


# -------------------------------------------------------------------------------------------------
class NoCacheStatic(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _local_host(header: str) -> bool:
    name = header.strip().lower()
    if name.startswith("["):                                   # [::1]:8765
        name = name.split("]")[0] + "]"
    elif name.count(":") == 1:
        name = name.split(":")[0]
    return name in _LOCAL_HOSTS


def _origin_ok(origin: str | None, host: str) -> bool:
    if not origin or origin == "null":
        return origin is None
    match = re.match(r"^https?://([^/]+)$", origin)
    return bool(match) and match.group(1).lower() == host.strip().lower()


def create_app(cfg: Config, config_path: str | None = None, on_all_windows_closed: Callable[[], None] | None = None) -> FastAPI:
    """``on_all_windows_closed`` (``serve --exit-when-closed``) is called once every UI window has been closed and nothing is
    left running: no run, no workers, no sign-in window. A run that is going when the last window closes is finished first."""
    signin: dict[str, SignInSession | None] = {"session": None}
    presence = UiPresence()

    def busy() -> bool:
        return bool(mgr.active_runs() or mgr.active_pools() or signin["session"] is not None)

    async def stop_when_windows_closed() -> None:
        told_about_run = False
        while True:
            await asyncio.sleep(1)
            if not presence.all_closed():
                told_about_run = False
                continue
            if busy():
                if not told_about_run:
                    print("The QA Regression window was closed while a run is going. It stops by itself when the run finishes;"
                          " reopen the window to watch it.", flush=True)
                    told_about_run = True
                continue
            print("The QA Regression window was closed: stopping.", flush=True)
            on_all_windows_closed()
            return

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        warm = asyncio.create_task(browser_check(browser=cfg.browser.kind.id))   # the first "is the browser ready?" probe takes a moment: do it now
        watcher = asyncio.create_task(stop_when_windows_closed()) if on_all_windows_closed else None
        yield
        warm.cancel()
        if watcher is not None:
            watcher.cancel()
        session = signin["session"]                        # never leave a sign-in window open behind us
        if session is not None:
            await session.close()

    app = FastAPI(title="regrunner", docs_url=None, redoc_url=None, lifespan=lifespan)
    mgr = RunManager(cfg, config_path)
    register_build_routes(app, mgr)                       # /api/build/*: the Workbook Builder (web/build_api.py)
    wb_cache: dict[tuple, Any] = {}

    # -- request guard -------------------------------------------------------------------------------
    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if not _local_host(host):
            return JSONResponse({"error": "This interface only answers on localhost.", "kind": "forbidden"}, status_code=403)
        if request.method in _UNSAFE_METHODS:
            if request.headers.get(CLIENT_HEADER, "").lower() != CLIENT_VALUE or not _origin_ok(request.headers.get("origin"), host):
                return JSONResponse({"error": "Request rejected: it did not come from the regrunner page.",
                                     "kind": "forbidden"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_, exc: HTTPException):
        body: dict[str, Any] = {"error": exc.detail}
        if isinstance(exc, ApiError):
            body.update(kind=exc.kind, **exc.extra)
        return JSONResponse(body, status_code=exc.status_code)

    # -- pages ---------------------------------------------------------------------------------------
    @app.get("/")
    async def index(request: Request):
        host = request.headers.get("host", "127.0.0.1")
        csp = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
               "font-src https://fonts.gstatic.com data:; img-src 'self' data: blob:; "
               f"connect-src 'self' ws://{host}; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store", "Content-Security-Policy": csp,
                                                            "X-Frame-Options": "DENY"})

    app.mount("/static", NoCacheStatic(directory=STATIC), name="static")

    # -- configuration / preflight ---------------------------------------------------------------------
    # -- is a UI window open? (serve --exit-when-closed) ------------------------------------------------
    @app.post("/api/ui/hello")
    async def ui_hello(body: UiPage):
        presence.hello(body.page)
        return {"ok": True}

    @app.post("/api/ui/goodbye")
    async def ui_goodbye(body: UiPage):
        presence.goodbye(body.page)
        return {"ok": True}

    @app.get("/api/config")
    async def api_config(request: Request):
        c = mgr.current()
        return {"version": __version__, "host": request.url.hostname, "port": request.url.port,
                "workers": c.effective_workers, "max_workers": c.runner.max_workers, "headless": c.runner.headless,
                "screenshots": c.screenshots.mode, "retries": c.behaviour.retries, "pdf": c.reports.pdf,
                "harvest": c.selectors.harvest, "nice": c.runner.low_priority, "waits": c.waits.mode,
                "cookie_name": c.captcha_bypass.cookie_name, "tokens": token_state(c), "tags": c.tags,
                "max_concurrent_runs": c.runner.max_concurrent_runs, "max_upload_mb": MAX_UPLOAD_MB,
                "allow_prod": c.runner.allow_prod, "selectors_map": c.selectors.map,
                "browser": c.browser.kind.id, "browsers": [b.as_dict() for b in browsers.ORDER]}

    @app.get("/api/preflight")
    async def api_preflight(deep: bool = False, browser: str | None = None):
        """``browser`` is the one picked on the form: which browser's launch check decides whether the run may start."""
        try:
            return await run_preflight(mgr.current(), deep=deep, browser=browser or None)
        except browsers.BrowserError as err:
            raise ApiError(422, str(err), "browser") from err

    # -- SSO sign-in (drives `auth login`: a visible window, then save the session) ------------------------
    @app.get("/api/auth")
    async def auth_status():
        from ..preflight import sso_state
        session = signin["session"]
        return {**sso_state(mgr.current()), "window_open": bool(session and session.is_open),
                "url": session.url if session and session.is_open else "",
                "default_url": mgr.current().auth.login_url}

    @app.post("/api/auth/login")
    async def auth_login(body: dict[str, Any]):
        session = signin["session"] or SignInSession(mgr.current())
        signin["session"] = session
        try:
            await session.open(str(body.get("url", "")))
        except SignInError as err:
            raise ApiError(400, str(err), "signin") from err
        return {"window_open": True, "url": session.url}

    @app.post("/api/auth/save")
    async def auth_save():
        session = signin["session"]
        if session is None:
            raise ApiError(409, "No sign-in window is open.", "signin")
        try:
            path = await session.save()
        except SignInError as err:
            raise ApiError(409, str(err), "signin") from err
        return {"saved": True, "path": str(path)}

    @app.post("/api/auth/cancel")
    async def auth_cancel():
        session = signin["session"]
        if session is not None:
            await session.close()
        return {"window_open": False}

    # -- workbooks -----------------------------------------------------------------------------------
    def workbook_files() -> list[Path]:
        base = cfg.path(cfg.workbooks_dir)
        base.mkdir(parents=True, exist_ok=True)
        return [p for p in base.iterdir() if p.suffix.lower() in (".xlsx", ".xlsm") and not p.name.startswith("~$")]

    @app.get("/api/workbooks")
    async def list_workbooks():
        files = sorted(workbook_files(), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"name": p.name, "size": p.stat().st_size,
                 "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")} for p in files]

    @app.post("/api/workbooks")
    async def upload_workbook(file: UploadFile = File(...)):
        name = _SAFE_NAME.sub("_", Path(file.filename or "workbook.xlsx").name).strip(" .")
        if Path(name).suffix.lower() not in (".xlsx", ".xlsm"):
            raise ApiError(400, "Only .xlsx and .xlsm workbooks can be uploaded.", "type")
        limit = int(MAX_UPLOAD_MB * 1024 * 1024)
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise ApiError(413, f"Workbook larger than {MAX_UPLOAD_MB} MB.", "size")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                looks_like_excel = "xl/workbook.xml" in z.namelist()
        except zipfile.BadZipFile:
            looks_like_excel = False
        if not looks_like_excel:
            raise ApiError(400, "That does not look like an Excel workbook.", "content")
        base = cfg.path(cfg.workbooks_dir)
        base.mkdir(parents=True, exist_ok=True)
        tmp = base / f".upload-{os.getpid()}-{name}.tmp"
        tmp.write_bytes(data)
        tmp.replace(base / name)
        return {"name": name, "size": len(data)}

    @app.delete("/api/workbooks/{name}")
    async def delete_workbook(name: str):
        """Take a workbook out of the list.  It is moved to ``workbooks/.trash/`` (not erased), so a mistake can be undone by hand;
        every run also keeps its own copy of the workbook it executed."""
        path = mgr.resolve_workbook(name)
        for run_id in mgr.active_runs():
            if Path(str((read_meta(mgr.run_dir(run_id)) or {}).get("workbook", ""))).name == path.name:
                raise ApiError(409, f"{path.name} is being used by a run that is still going. Let it finish (or cancel it), then delete.",
                               "busy", run_id=run_id)
        trash = path.parent / ".trash"
        target = trash / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{path.name}"
        try:
            trash.mkdir(exist_ok=True)
            await asyncio.to_thread(os.replace, path, target)
        except OSError as err:
            raise ApiError(409, f"{path.name} could not be removed ({err.strerror or err}). If it is open in Excel, close it and try again.",
                           "locked") from err
        if path.exists():                                                  # a sync client can put it straight back: say so, do not claim success
            raise ApiError(409, f"{path.name} was moved to .trash but is back in workbooks/ (a sync client may be restoring it).", "restored")
        for key in [k for k in wb_cache if k[1] == str(path)]:
            wb_cache.pop(key, None)
        chains_file(path).unlink(missing_ok=True)                            # its remembered order goes with it
        return {"deleted": path.name, "kept_as": f".trash/{target.name}"}

    def load_workbook(name: str, env: str | None) -> tuple[Path, Workbook]:
        path = mgr.resolve_workbook(name)
        try:
            return path, Workbook(path, environment=(env or None), secrets=workbook_secrets())
        except Exception as err:
            raise ApiError(422, f"Could not read workbook: {err}", "unreadable",
                           details=traceback.format_exc()[-3000:]) from err

    inflight: dict[tuple, asyncio.Task] = {}

    def cache_key(kind: str, name: str, env: str | None, *extra) -> tuple:
        path = mgr.resolve_workbook(name)
        return (kind, str(path), path.stat().st_mtime_ns, (env or "").upper(), *extra)

    async def cached(kind: str, name: str, env: str | None, compute, *extra):
        """Compute a read-only workbook answer off the event loop, remembered until the file changes.  Asked again while it is still being computed
        (the page asks for several things the moment a workbook is chosen, and again on every click), the asker waits for that one computation
        instead of starting another: reading a big workbook takes seconds of CPU."""
        key = cache_key(kind, name, env, *extra)
        if key in wb_cache:
            return wb_cache[key]
        task = inflight.get(key)
        if task is None:
            async def build():
                def work():
                    _, wb = load_workbook(name, env)
                    return compute(wb, mgr.current())
                try:
                    value = await asyncio.to_thread(work)
                except ApiError:
                    raise
                except KeyError as err:
                    raise ApiError(404, f"Unknown test {err}", "not_found") from err
                except Exception as err:
                    raise ApiError(422, f"Could not read workbook: {err}", "unreadable", details=traceback.format_exc()[-3000:]) from err
                wb_cache[key] = value
                while len(wb_cache) > 40:
                    wb_cache.pop(next(iter(wb_cache)))
                return value
            task = inflight[key] = asyncio.get_running_loop().create_task(build())
            task.add_done_callback(lambda t, k=key: (inflight.pop(k, None), t.cancelled() or t.exception()))       # (reading the exception marks it as seen)
        return await asyncio.shield(task)

    @app.get("/api/workbooks/{name}/tests")
    async def workbook_tests(name: str, env: str | None = None):
        summary, _flows = await cached("tests", name, env, insight.summary_and_flows)
        path = mgr.resolve_workbook(name)
        stat = path.stat()
        chains, source = load_chains(mgr.current(), path)
        return {"name": path.name, "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"), **summary,
                "chains": chains, "chains_source": source}

    @app.post("/api/workbooks/{name}/order")
    async def workbook_order(name: str, body: dict[str, Any]):
        """Which of the chosen tests wait for which (data and chains), and what to tell the person before the run.  ``chains`` null = the saved ones."""
        tests = [str(t) for t in (body.get("tests") or [])][:500]
        path = mgr.resolve_workbook(name)
        _summary, flows = await cached("tests", name, body.get("env"), insight.summary_and_flows)          # the same pass that listed the tests: no second read
        if body.get("chains") is None:
            chains, source = load_chains(mgr.current(), path)
        else:
            chains, source = clean_chains(body["chains"]), "edited"
        return {**plan_order(flows, tests, chains).as_dict(), "source": source}

    @app.put("/api/workbooks/{name}/chains")
    async def workbook_chains(name: str, body: dict[str, Any]):
        """Remember the chains for this workbook (beside it, never inside it).  An empty list forgets them."""
        path = mgr.resolve_workbook(name)
        chains = clean_chains(body.get("chains"))
        await asyncio.to_thread(save_chains, path, chains)
        return {"chains": chains}

    @app.get("/api/workbooks/{name}/start-url")
    async def workbook_start_url(name: str, env: str | None = None):
        url = await cached("url", name, env, lambda wb, c: insight.start_url(wb))
        return {"url": mgr.current().auth.login_url or url}

    @app.post("/api/workbooks/{name}/lint")
    async def workbook_lint(name: str, body: dict[str, Any] | None = None):
        return await cached("lint", name, (body or {}).get("env"), lambda wb, c: insight.lint_report(wb))

    @app.post("/api/workbooks/{name}/plan")
    async def workbook_plan(name: str, body: dict[str, Any]):
        test = str(body.get("test", "")).strip()
        if not test:
            raise ApiError(400, "Say which test to preview.", "selection")
        return await cached("plan", name, body.get("env"), lambda wb, c: insight.plan_steps(wb, c, test), test.lower())

    @app.post("/api/workbooks/{name}/audit")
    async def workbook_audit(name: str, body: dict[str, Any] | None = None):
        c = mgr.current()
        map_file = c.path(c.selectors.map)
        stamp = map_file.stat().st_mtime_ns if map_file.exists() else 0
        return await cached("audit", name, (body or {}).get("env"), insight.audit_report, stamp)

    # -- runs ------------------------------------------------------------------------------------------
    @app.post("/api/runs/command")
    async def run_command(req: StartRun):
        return mgr.preview(req)

    @app.post("/api/runs")
    async def start_run(req: StartRun):
        return await mgr.start(req)

    @app.get("/api/runs")
    async def list_runs():
        return await asyncio.to_thread(mgr.list_runs)

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str):
        run_dir = mgr.run_dir(run_id)
        meta = await asyncio.to_thread(mgr.summarize, run_dir)
        if meta is None:
            raise ApiError(404, "run not found", "not_found")
        results = run_dir / "results.json"
        files = {"report_html": (run_dir / "report.html").is_file(), "report_pdf": (run_dir / "report.pdf").is_file(),
                 "results": results.is_file(), "workbook": next((p.name for p in run_dir.glob("workbook.*")), None),
                 "suggestions": (run_dir / "selector_suggestions.json").is_file(),
                 "screenshots": sum(1 for _ in (run_dir / "tests").rglob("*.jpg")) if (run_dir / "tests").is_dir() else 0}
        return {"meta": meta, "active": meta["active"], "files": files,
                "results": json.loads(results.read_text(encoding="utf-8")) if results.is_file() else None}

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        await mgr.cancel(run_id)
        return {"ok": True}

    @app.post("/api/runs/{run_id}/answer")
    async def answer_run(run_id: str, body: Answer):
        run_dir = mgr.run_dir(run_id)
        if not run_dir.is_dir():
            raise ApiError(404, "run not found", "not_found")
        if not re.fullmatch(r"a\d+-[0-9a-f]{6}", body.ask):
            raise ApiError(400, "bad question id", "bad_request")
        if not mgr.is_active(run_id):
            raise ApiError(409, "That run is not running any more, so nothing is waiting for an answer.", "closed")
        why = write_answer(run_dir, body.ask, body.answer)
        if why == "closed":
            raise ApiError(409, "That question is no longer waiting for an answer (it timed out, or the run was cancelled).", "closed")
        if why:
            raise ApiError(404, "No such question in this run.", "not_found")
        return {"ok": True}

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str, offset: int = 0):
        events, new_offset = read_events(mgr.run_dir(run_id) / "events.jsonl", offset)
        return {"events": events, "offset": new_offset}

    @app.get("/api/runs/{run_id}/log")
    async def run_log(run_id: str, tail: int = 200):
        log = mgr.run_dir(run_id) / "runner.log"
        if not log.is_file():
            return {"lines": []}
        return {"lines": log.read_text(errors="replace").splitlines()[-max(1, min(tail, 2000)):]}

    @app.post("/api/runs/{run_id}/report")
    async def rebuild_report(run_id: str, body: dict[str, Any] | None = None):
        body = body or {}
        run_dir = mgr.run_dir(run_id)
        if not run_dir.is_dir():
            raise ApiError(404, "run not found", "not_found")
        if mgr.is_active(run_id):
            raise ApiError(409, "This run is still going; its report is built when it finishes.", "busy")
        from ..reporting.html_report import build_report
        from_events = bool(body.get("from_events"))
        if not from_events and not (run_dir / "results.json").is_file():
            raise ApiError(409, "This run has no results.json. Build the report from its events instead.", "no_results")
        try:
            artifacts = await build_report(run_dir, pdf=bool(body.get("pdf")), from_events=from_events)
        except ValueError as err:
            raise ApiError(422, str(err), "no_events") from err
        meta = read_meta(run_dir) or {}
        update_meta(run_dir, artifacts={**meta.get("artifacts", {}), **artifacts, "results": "results.json"})
        return {"artifacts": artifacts}

    @app.get("/api/runs/{run_id}/selectors")
    async def run_selectors(run_id: str):
        f = mgr.run_dir(run_id) / "selector_suggestions.json"
        if not f.is_file():
            return {"available": False, "suggestions": [], "skipped": [], "already": 0}
        from ..selectors.resolve import SelectorMap
        data = json.loads(f.read_text(encoding="utf-8"))
        c = mgr.current()
        smap = SelectorMap.load(c.path(c.selectors.map))
        fresh = [{"key": k, **v} for k, v in data.get("suggestions", {}).items() if k not in smap.entries]
        return {"available": True, "suggestions": sorted(fresh, key=lambda s: -s["score"]),
                "skipped": [{"key": k, "reason": r} for k, r in data.get("skipped", {}).items()],
                "already": len(data.get("suggestions", {})) - len(fresh)}

    @app.post("/api/runs/{run_id}/selectors/apply")
    async def apply_selectors(run_id: str, body: dict[str, Any] | None = None):
        from ..selectors.harvest import apply_suggestions
        from ..selectors.resolve import SelectorMap
        f = mgr.run_dir(run_id) / "selector_suggestions.json"
        if not f.is_file():
            raise ApiError(404, "This run harvested no selectors (turn on Harvest selectors).", "not_found")
        c = mgr.current()
        smap = SelectorMap.load(c.path(c.selectors.map))
        keys = (body or {}).get("keys")
        added = apply_suggestions(f, smap, min_score=int((body or {}).get("min_score", 85)),
                                  only=set(keys) if isinstance(keys, list) else None)
        path = smap.save(c.path(c.selectors.map))
        return {"added": added, "total": len(smap), "path": str(path)}

    @app.post("/api/runs/{run_id}/reveal")
    async def reveal(run_id: str, body: dict[str, Any] | None = None):
        run_dir = mgr.run_dir(run_id)
        target = run_dir / "tests" if (body or {}).get("folder") == "tests" and (run_dir / "tests").is_dir() else run_dir
        if not target.is_dir():
            raise ApiError(404, "run not found", "not_found")
        opener = ["explorer"] if sys.platform == "win32" else ["open"] if sys.platform == "darwin" else ["xdg-open"]
        try:
            subprocess.Popen(opener + [str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as err:
            raise ApiError(500, f"Could not open the folder: {err}", "reveal") from err
        return {"path": str(target)}

    @app.get("/runs/{run_id}/files/{path:path}")
    async def run_file(run_id: str, path: str, download: bool = False):
        base = mgr.run_dir(run_id).resolve()
        target = (base / path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise ApiError(404, "file not found", "not_found")
        return FileResponse(target, filename=target.name if download else None)

    @app.websocket("/ws/runs/{run_id}")
    async def ws_run(ws: WebSocket, run_id: str):
        host = ws.headers.get("host", "")
        if not _local_host(host) or not _origin_ok(ws.headers.get("origin"), host):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            run_dir = mgr.run_dir(run_id)
        except HTTPException:
            await ws.close(code=4400)
            return
        events_file = run_dir / "events.jsonl"
        offset, waited = 0, 0.0
        try:
            while True:
                events, offset = read_events(events_file, offset)
                if events:
                    await ws.send_json({"events": events})
                    waited = 0.0
                    if any(e["type"] == "run_finished" for e in events):
                        break
                else:
                    if not mgr.is_active(run_id) and (events_file.exists() or waited > 20):
                        break                                    # nothing more will ever arrive
                    waited += 0.15
                await asyncio.sleep(0.15)
            await ws.send_json({"events": [], "closed": True})
            await ws.close()
        except (WebSocketDisconnect, RuntimeError):
            return

    return app
