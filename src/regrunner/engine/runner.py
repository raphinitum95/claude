"""Run orchestration: select tests, run them concurrently, collect results, build reports.

One process can carry several runs (one per workbook) on one set of workers: :func:`execute_many`.  Each run keeps its own folder, event
stream, results and report; the workers, the browser driver, the page-load throttle and the captcha window are shared (``engine/pool.py``
hands a free worker to the run with the fewest tests going).  :func:`execute` is the one-run case.  When ``inbox_dir`` is given, further runs
can join while the process is going (``engine/inbox.py``; the web UI uses it).
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from .. import browsers
from ..config import Config, workbook_secrets
from ..events import EventBus, JsonlListener, ProgressTracker, now_iso
from ..runmeta import update_meta
from ..reporting.results import RunResult, TestResult
from ..selectors.harvest import HarvestStore
from ..selectors.resolve import SelectorMap
from ..workbook.model import TestCase, Workbook
from ..workbook.variables import VariablePool
from .diagnostics import dump_tasks
from .api_runner import ApiTestRunner
from .ask import Asker
from .inbox import Inbox
from .order import Flow, Order, load_chains, plan_order
from .patience import WaitNotice, plain_seconds
from .pool import Pool
from .resources import ResourceSampler, machine_info, read_resources, summarize
from .schedule import Schedule
from .test_runner import TestRunner
from .throttle import Throttle
from .timing import run_summary


@dataclass
class RunOptions:
    workbook: Path
    tests: list[str] | None = None          # test ids / sheet names; overrides the workbook's Y/N flags
    tags: list[str] | None = None
    environment: str | None = None
    workers: int | None = None
    headless: bool | None = None
    seed: int | None = None
    screenshots: str | None = None          # every_step | on_failure | off
    run_id: str | None = None
    report: bool = True
    pdf: bool | None = None
    harvest: bool | None = None
    retries: int | None = None
    allow_prod: bool = False
    browser: str | None = None              # chrome | msedge | safari | chromium; None = the one config.yaml selects
    chains: list[list[str]] | None = None   # tests that run one after another; None = the ones saved for the workbook / in config.yaml
    extra: dict[str, Any] = field(default_factory=dict)


class SelectionError(ValueError):
    pass


class EnvironmentMissing(SelectionError):
    """A required environment variable has no value for the run's environment: the run refuses to start (CONTRACT.md 1.4)."""

    def __init__(self, message: str, environment: str, variables: list[str]):
        super().__init__(message)
        self.environment, self.variables = environment, variables


def select_cases(cases: list[TestCase], options: RunOptions, cfg: Config) -> list[TestCase]:
    ui_cases = [c for c in cases if c.runnable]              # UI keyword sheets and API data rows
    if options.tests:
        wanted = [t.strip().lower() for t in options.tests if t.strip()]
        chosen, missing = [], []
        for name in wanted:
            hits = [c for c in ui_cases if name in (c.id.lower(), c.sheet.lower(), c.title.lower())]
            (chosen.extend(hits) if hits else missing.append(name))
        if missing:
            raise SelectionError(f"Unknown test(s): {', '.join(missing)}. Available: "
                                 f"{', '.join(c.id for c in ui_cases)}")
        return list({c.id: c for c in chosen}.values())
    if options.tags:
        tags = {t.lower() for t in options.tags}
        picked = []
        for c in ui_cases:
            own = {t.lower() for t in c.tags}
            for tag, ids in cfg.tags.items():
                if c.id in ids or c.sheet in ids:
                    own.add(tag.lower())
            if own & tags:
                picked.append(c)
        if not picked:
            raise SelectionError(f"No tests carry tag(s): {', '.join(options.tags)}")
        return picked
    return [c for c in ui_cases if c.enabled]


def new_run_id(cfg: Config, environment: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{(environment or 'run').upper()}"
    runs = cfg.path(cfg.runs_dir)
    candidate, n = base, 1
    while (runs / candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


# -------------------------------------------------------------------------------------------------
# one run
# -------------------------------------------------------------------------------------------------
@dataclass
class RunPlan:
    """A run worked out but not started: what would run, in what order.  Nothing on disk yet (a plan that fails leaves no run folder)."""
    options: RunOptions
    cfg: Config                                     # this run's own copy (screenshots / retries / harvest come from its options)
    workbook: Workbook
    cases: list[TestCase]
    environment: str
    headless: bool
    plans: dict[str, list[int]]
    flows: list[Flow]
    order: Order
    site: str = ""                                  # the host the workbook opens first: what page-load spacing and block cool-downs are kept per


@dataclass
class RunCtx:
    """A run that is going: everything the workers need to run its tests and to finish it."""
    plan: RunPlan
    run_id: str
    run_dir: Path
    bus: EventBus
    jsonl: JsonlListener
    schedule: Schedule
    cancel: asyncio.Event
    asker: Asker
    selector_map: SelectorMap
    harvest: HarvestStore | None
    result: RunResult
    browser_info: dict[str, Any]
    started: float = field(default_factory=time.perf_counter)
    shared: dict[tuple[str, int, int], Any] = field(default_factory=dict)      # parameter cells finished tests wrote (a policy number...): the tests that come after read them
    pool: VariablePool = field(default_factory=VariablePool)                   # the run's shared variables ({NAME}, SET_VARIABLE, CALL_TEST: CONTRACT.md 1.2)
    results: dict[str, TestResult] = field(default_factory=dict)
    tasks: set = field(default_factory=set)                                    # the tests being run (so a forced stop can end them)
    partial: dict[str, TestResult] = field(default_factory=dict)               # what a test had recorded when it was stopped by force
    shares: list[dict[str, str]] = field(default_factory=list)                 # the other runs that use the same workers
    announced: bool = False                                                    # run_started has been sent
    ended: bool = False                                                        # finishing: the pool hands out none of its tests any more
    closed: bool = False                                                       # its event stream is closed: nothing more can be said in it
    stopped: bool = False
    abandoned: bool = False                                                    # a forced stop that some test did not obey: finish without it

    # shortcuts the workers use
    @property
    def cfg(self) -> Config:
        return self.plan.cfg

    @property
    def workbook(self) -> Workbook:
        return self.plan.workbook

    @property
    def cases(self) -> list[TestCase]:
        return self.plan.cases

    @property
    def plans(self) -> dict[str, list[int]]:
        return self.plan.plans

    @property
    def order(self) -> Order:
        return self.plan.order

    @property
    def flows(self) -> list[Flow]:
        return self.plan.flows

    @property
    def environment(self) -> str:
        return self.plan.environment

    def note(self, message: str, level: str = "warning") -> None:
        if not self.closed:
            self.bus.emit("log", level=level, message=message)


def _load_and_plan(options: RunOptions, cfg: Config, headless: bool) -> RunPlan:
    """Everything that needs the workbook but no browser (seconds of CPU on a big one: called off the event loop)."""
    workbook = Workbook(options.workbook, environment=options.environment, headless=headless,
                        seed=options.seed, secrets=workbook_secrets())
    cases = select_cases(workbook.discover(), options, cfg)
    if not cases:
        raise SelectionError("No tests selected (all DataSheets rows are 'N'? use --tests or --all)")
    environment = (options.environment or workbook.global_settings().get("Environment") or "").upper() \
        if not isinstance(options.environment, str) else options.environment.upper()
    environment = environment or str(workbook.global_settings().get("Environment", "")).upper()
    if environment == "PROD" and not (options.allow_prod or cfg.runner.allow_prod):
        raise SelectionError(
            "Refusing to run against PROD: these flows place real transactions (purchases, emails). "
            "Pass --allow-prod (or set runner.allow_prod: true) if that is really what you want.")
    from ..preflight import environment_problem
    problem, missing = environment_problem(workbook, environment)
    if problem:
        raise EnvironmentMissing(problem, environment, missing)
    # Plan every test (dry run, no browser) so progress has honest totals.
    plans: dict[str, list[int]] = {}
    flows: list[Flow] = []
    position = {c.id: i for i, c in enumerate(workbook._discovered)}          # the DataSheets order: what the legacy runner ran them in
    for case in cases:
        runtime = workbook.runtime(case)
        plans[case.id] = [row for row, _, _ in runtime.plan()]
        flows.append(Flow.of(case, position.get(case.id, 0), runtime))
    chains = options.chains if options.chains is not None else load_chains(cfg, Path(options.workbook))[0]
    order = plan_order(flows, [c.id for c in cases], chains)
    try:
        from urllib.parse import urlparse
        from ..insight import start_url
        site = (urlparse(start_url(workbook)).hostname or "").lower()
    except Exception:                                                 # (an API-only workbook, a URL that cannot be worked out: it is its own site)
        site = ""
    return RunPlan(options=options, cfg=cfg, workbook=workbook, cases=cases, environment=environment, headless=headless,
                   plans=plans, flows=flows, order=order, site=site)


async def plan_run(options: RunOptions, cfg: Config, kind: browsers.Browser | None = None) -> RunPlan:
    """Work out one run.  ``cfg`` is copied: the run's own screenshots / retries / harvest settings never leak into another run's."""
    own = copy.deepcopy(cfg)
    if options.screenshots:
        own.screenshots.mode = options.screenshots
    if options.harvest is not None:
        own.selectors.harvest = options.harvest
    if options.retries is not None:
        own.behaviour.retries = options.retries
    headless = own.runner.headless if options.headless is None else options.headless
    try:
        chosen = kind or (browsers.resolve(options.browser) if options.browser else own.browser.kind)
    except browsers.BrowserError as err:
        raise SelectionError(str(err)) from err
    plan = await asyncio.to_thread(_load_and_plan, options, own, headless)
    plan.cfg.browser.name = chosen.id
    return plan


async def open_run(plan: RunPlan, bus: EventBus | None, browser_info: dict[str, Any], ask_mode: str) -> RunCtx:
    """Create the run: its folder, event stream and result.  From here on it exists on disk."""
    options, cfg = plan.options, plan.cfg
    run_id = options.run_id or new_run_id(cfg, plan.environment)
    run_dir = cfg.path(cfg.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "cancel").unlink(missing_ok=True)
    (run_dir / "stop").unlink(missing_ok=True)
    try:
        shutil.copy2(options.workbook, run_dir / f"workbook{Path(options.workbook).suffix}")   # what was executed
    except OSError:
        pass
    bus = bus or EventBus(run_id)
    bus.run_id = run_id
    jsonl = JsonlListener(run_dir / "events.jsonl")
    bus.subscribe(jsonl)
    ProgressTracker(bus)
    cancel = asyncio.Event()
    result = RunResult(run_id=run_id, workbook=str(options.workbook), environment=plan.environment, started_at=now_iso(), workers=1,
                       seed=options.seed, config=cfg.public(), warnings=list(plan.workbook.warnings), browser=browser_info,
                       machine=await asyncio.to_thread(machine_info))
    if not cfg.bypass_token(plan.environment):
        result.warnings.append(f"No {cfg.captcha_bypass.cookie_name} value configured for {plan.environment or 'this environment'}"
                               " - captcha-protected flows may be blocked (set it in secrets.env)")
    if cfg.publish.dir:
        from ..publish import probe
        problem = await probe(cfg.path(cfg.publish.dir))
        if problem:
            result.warnings.append(f"The shared folder {cfg.path(cfg.publish.dir)} cannot be written to right now ({problem}). The run "
                                   "goes ahead and stays in runs/; it is copied to the shared folder after a later run.")
    # Tests others read from first (an API purchase whose policy number a UI test types), then the longest UI test (shortest wall-clock), the API tests
    # that read what the UI tests produce last; a test that has to wait for others is held back until they are done.
    feeds = {p for named in plan.order.data.values() for producers in named.values() for p in producers}
    schedule = Schedule(sorted(plan.cases, key=lambda c: (c.id in plan.order.after_ui, c.id not in feeds, -len(plan.plans[c.id]))), plan.order.deps)
    asker = Asker(run_dir, bus, cancel, mode=ask_mode, default_timeout_s=cfg.ask.timeout_s)           # ASK_USER: who can answer
    return RunCtx(plan=plan, run_id=run_id, run_dir=run_dir, bus=bus, jsonl=jsonl, schedule=schedule, cancel=cancel, asker=asker,
                  selector_map=SelectorMap.load(cfg.path(cfg.selectors.map)), harvest=HarvestStore() if cfg.selectors.harvest else None,
                  result=result, browser_info=browser_info)


def announce_run(ctx: RunCtx, workers: int) -> None:
    """Tell the world (run.json, the event stream) that the run has begun."""
    plan, cfg, options = ctx.plan, ctx.cfg, ctx.plan.options
    ctx.announced = True
    ctx.result.workers = workers
    params = {"environment": plan.environment, "workers": workers, "browser": cfg.browser.name, "screenshots": cfg.screenshots.mode,
              "retries": cfg.behaviour.retries, "seed": options.seed, "headless": plan.headless,
              "harvest": bool(cfg.selectors.harvest), "waits": cfg.waits.mode, "report": options.report,
              "pdf": bool(cfg.reports.pdf if options.pdf is None else options.pdf),
              "nice": options.extra.get("nice"), "tests": [c.id for c in plan.cases]}
    total_steps = sum(len(rows) for rows in plan.plans.values())
    update_meta(ctx.run_dir, run_id=ctx.run_id, workbook=str(options.workbook), environment=plan.environment,
                started_at=ctx.result.started_at, status="RUNNING", params=params, test_ids=[c.id for c in plan.cases],
                tests=len(plan.cases), total_steps=total_steps, browser=ctx.browser_info, shares=ctx.shares)
    ctx.bus.emit("run_started", workbook=str(options.workbook), environment=plan.environment, workers=workers,
                 headless=plan.headless, browser=ctx.browser_info, seed=options.seed, warnings=ctx.result.warnings, params=params,
                 shares=ctx.shares,
                 tests=[{"id": c.id, "title": c.title, "description": c.description, "scenario": c.scenario,
                         "total_steps": len(plan.plans[c.id]), "waits_for": plan.order.deps.get(c.id, [])} for c in plan.cases])
    for note in plan.order.notes:                                     # what will wait for what, and what nothing sets (the terminal and the event log say it too)
        if note["kind"] in ("waits", "missing", "conflict", "parallel"):
            ctx.note(note["message"], "warning" if note["kind"] in ("missing", "conflict") else "info")


# -------------------------------------------------------------------------------------------------
# the workers
# -------------------------------------------------------------------------------------------------
class Engine:
    """The workers of one process and everything they share; the runs come and go on them."""

    def __init__(self, cfg: Config, cancel: asyncio.Event, *, kind: browsers.Browser, headless: bool, want_workers: int, ask_mode: str,
                 browser_info: dict[str, Any], inbox: Inbox | None = None):
        self.cfg = cfg                                                # (a copy that names the browser the workers use)
        self.cancel = cancel
        self.kind, self.headless, self.ask_mode, self.browser_info = kind, headless, ask_mode, browser_info
        self.want_workers = want_workers                              # what the person asked for (the ceiling a pool grows to as runs join)
        self.pool = Pool(cancel, joinable=inbox is not None, gate=self.site_full)
        self.inbox = inbox
        self.throttles: dict[str, Throttle] = {}                      # one per site: a block by one site's WAF must not stall the others'
        self.window_lock = asyncio.Lock()                             # one solving window at a time: a person can only solve one captcha at once
        self.window: dict[str, Any] = {"browser": None}
        self.pw: Any = None
        self.devices: dict = {}
        self.workers: list[asyncio.Task] = []
        self.lifecycles: list[asyncio.Task] = []
        self.last_activity = time.monotonic()
        self._winding: asyncio.Future | None = None
        self._driver_lock: asyncio.Lock | None = None
        self.driver_generation = 0                                    # how many times the browser driver was started again after it died

    # -- shared notes ------------------------------------------------------------------------------------
    def note(self, message: str, level: str = "warning") -> None:
        """A note for every run that is going (something that concerns the process, not one run)."""
        live = [r for r in self.pool.runs if not r.ended]
        if not live:                                                  # every run has said its last word: the process log is what is left (runner.log in the UI)
            print(f"[{level}] {message}", file=sys.stderr, flush=True)
            return
        for ctx in live:
            ctx.note(message, level)

    def touch(self, _event=None) -> None:
        self.last_activity = time.monotonic()

    # -- per-site politeness -----------------------------------------------------------------------------
    def throttle_for(self, ctx: RunCtx) -> Throttle:
        """The page-load pacing of the site this run's workbook opens (runs on the same host share it; a run whose host is unknown has its own)."""
        key = ctx.plan.site or ctx.run_id
        if key not in self.throttles:
            self.throttles[key] = Throttle(self.cfg.runner.min_page_load_gap_s, self.want_workers)
        return self.throttles[key]

    def running_on(self, throttle: Throttle) -> int:
        return sum(r.schedule.running for r in self.pool.runs if not r.ended and self.throttle_for(r) is throttle)

    def site_full(self, ctx: RunCtx) -> bool:
        """After a block the site is allowed fewer tests at once: the workers it cannot use go to the other runs."""
        throttle = self.throttle_for(ctx)
        return self.running_on(throttle) >= throttle.limit

    # -- runs ----------------------------------------------------------------------------------------------
    def shares_of(self, ctx: RunCtx) -> list[dict[str, str]]:
        return [{"run_id": r.run_id, "workbook": Path(str(r.plan.options.workbook)).name} for r in self.pool.runs if r is not ctx]

    def register(self, ctx: RunCtx) -> None:
        """Put a run on the pool (its tests are handed out from now on) and tell every run who shares the workers with it."""
        self.pool.add(ctx)
        ctx.bus.subscribe(self.touch)
        if self.cancel.is_set():
            ctx.cancel.set()
        for one in self.pool.runs:
            shares = self.shares_of(one)
            changed = shares != one.shares
            one.shares = shares
            if changed and one.announced and not one.ended:             # a run that was already going hears that another has joined
                update_meta(one.run_dir, shares=shares)
                one.bus.emit("pool_changed", shares=shares)

    async def add_run(self, ctx: RunCtx) -> None:
        """A run joins the workers that are going.  The pool grows by the workers this run can use, up to what was asked for."""
        self.register(ctx)
        grown = min(self.want_workers, max(1, self.pool.outstanding())) - len(self.workers)
        self.spawn_workers(max(0, grown), later=True)
        announce_run(ctx, len(self.workers))
        self.lifecycles.append(asyncio.ensure_future(self.lifecycle(ctx)))
        await self.pool.wake()

    def spawn_workers(self, count: int, later: bool = False) -> None:
        """Start ``count`` workers.  They begin apart (``runner.stagger_s``), not all loading pages in the same instant."""
        for i in range(count):
            n = len(self.workers) + 1
            self.workers.append(asyncio.ensure_future(self.worker(n, (i + 1 if later else i) * self.cfg.runner.stagger_s)))

    @contextlib.asynccontextmanager
    async def playwright_session(self):
        """``async_playwright()`` whose shutdown cannot hang the run: the driver gets ``close_timeout_s`` to stop.  (The driver running at the end
        is stopped: it may be a new one, started after the first died - ``restart_driver``.)"""
        self.pw = await async_playwright().start()
        try:
            yield self.pw
        finally:
            self.note("Stopping the browser driver", "info")
            try:
                await asyncio.wait_for(self.pw.stop(), self.cfg.runner.close_timeout_s)
            except asyncio.TimeoutError:
                self.note(f"The browser driver did not stop within {self.cfg.runner.close_timeout_s:g}s; continuing without it")
            except Exception:
                pass

    async def restart_driver(self, generation: int) -> None:
        """The browser driver (Playwright's own process) died: start a new one, once, however many tests noticed.  Every worker's browser then
        relaunches on it (``get_browser`` sees a disconnected browser)."""
        if self._driver_lock is None:
            self._driver_lock = asyncio.Lock()
        async with self._driver_lock:
            if generation != self.driver_generation:
                return                                                # another test already did it
            old = self.pw
            try:
                await asyncio.wait_for(old.stop(), self.cfg.runner.close_timeout_s)
            except Exception:
                pass
            self.pw = await async_playwright().start()
            self.devices = dict(self.pw.devices)
            self.driver_generation += 1
            self.note("The browser driver had stopped working and was started again.", "warning")

    async def get_window(self):
        """The visible browser a captcha is solved in (opened when first needed, closed after each test that used it)."""
        if self.window["browser"] is None or not self.window["browser"].is_connected():
            self.window["browser"] = await self.cfg.browser.launch(self.pw, self.cfg.captcha.headless)      # the same browser as the rest of the run
        return self.window["browser"]

    async def close_window(self) -> None:
        browser, self.window["browser"] = self.window["browser"], None
        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), self.cfg.runner.close_timeout_s)
            except Exception:
                pass

    async def watch_stall(self) -> None:
        """No event at all for longer than any single step may take = something is stuck: record where."""
        limit = self.cfg.runner.step_hard_cap_s + 60
        while True:
            await asyncio.sleep(5)
            idle = time.monotonic() - self.last_activity
            if idle > limit:
                dump_tasks(f"no activity for {int(idle)}s")
                self.note(f"No activity for {int(idle)}s. Where each part is waiting is written to runner.log in this run's folder.")
                self.last_activity = time.monotonic()               # (say it again after another stretch of silence, not every 5 s)

    async def propagate_cancel(self) -> None:
        """The process is being stopped: every run stops (a run that joins later finds it already set)."""
        await self.cancel.wait()
        for ctx in self.pool.runs:
            ctx.cancel.set()
        await self.pool.wake()

    # -- one test ------------------------------------------------------------------------------------------
    @staticmethod
    def producer_failed(ctx: RunCtx, case: TestCase) -> str:
        """Why a test cannot run: a test it waited for was to set a parameter it needs and did not (it failed before that step, or was skipped)."""
        for param, producers in ctx.order.data.get(case.id, {}).items():
            key = ctx.order.cells.get(case.id, {}).get(param)
            if key is None or tuple(key) in ctx.shared:
                continue
            states = ", ".join(f"{p} ended {ctx.results[p].status}" if p in ctx.results else p for p in producers)
            name = next((i["param"] for f in ctx.flows if f.id == case.id for i in f.reads.values() if i["param"].upper() == param), param)
            return (f"Not run: {case.id} needs {name}, which {' and '.join(producers)} should have set ({states}) and did not. "
                    "Nothing was typed in its place.")
        return ""

    @staticmethod
    def not_run(ctx: RunCtx, case: TestCase, reason: str, worker: int) -> TestResult:
        total = len(ctx.plans[case.id])
        res = TestResult(id=case.id, title=case.title, sheet=case.sheet, scenario=case.scenario, description=case.description, status="ERROR",
                         started_at=now_iso(), ended_at=now_iso(), total_steps=total, skipped=total, error=reason)
        ctx.bus.emit("test_started", test=case.id, title=case.title, total_steps=total, worker=worker, attempt=1)
        ctx.bus.emit("test_finished", test=case.id, status="ERROR", passed=0, failed=0, skipped=total, duration_s=0.0, error=reason, review_counts=[])
        ctx.note(f"{case.id}: {reason}")
        return res

    @staticmethod
    def stopped(ctx: RunCtx, case: TestCase, why: str, status: str) -> TestResult:
        """A test that did not come back on its own (a forced stop, or a crash of the runner itself): what it had recorded, ended with the reason."""
        res = ctx.partial.get(case.id) or TestResult(id=case.id, title=case.title, sheet=case.sheet, scenario=case.scenario,
                                                     description=case.description, total_steps=len(ctx.plans[case.id]))
        res.status, res.error = status, (why if status == "CANCELLED" else res.error or why)      # (the runner's own "cancelled" wording says less than why it was stopped)
        res.ended_at = res.ended_at or now_iso()
        ctx.bus.emit("test_finished", test=case.id, status=res.status, passed=res.passed, failed=res.failed, skipped=res.skipped,
                     duration_s=res.duration_s, error=res.error, review_counts=[])
        ctx.note(f"{case.id}: {res.error}", "error" if res.status == "ERROR" else "warning")
        return res

    async def run_case(self, ctx: RunCtx, case: TestCase, get_browser, n: int) -> TestResult:
        cfg, bus = ctx.cfg, ctx.bus
        attempts: list[dict[str, Any]] = []
        attempt = 0
        block_tries = 0
        at_window = False                                       # the test is being run in the visible window because a captcha needs a person
        captcha_tries = 0
        infra_tries = 0
        throttle = self.throttle_for(ctx)
        while True:
            attempt += 1
            generation = self.driver_generation
            async with contextlib.AsyncExitStack() as stack:
                if at_window:
                    await stack.enter_async_context(self.window_lock)
                    if ctx.cancel.is_set():                     # cancelled while waiting for the window: no need to open it
                        res.attempts = attempts[:-1]
                        return res
                    try:
                        await self.get_window()
                    except Exception as err:                    # no display, no browser to show: say so on the result the captcha already gave
                        reason = (str(err).strip().splitlines() or [type(err).__name__])[0][:160]
                        ctx.note(f"{case.id}: a browser window could not be opened here ({reason}).", "error")
                        res.error = res.captcha = f"{res.error} A browser window to solve it in could not be opened here ({reason})."
                        res.attempts = attempts[:-1]
                        return res
                if case.kind == "api":
                    runner = ApiTestRunner(workbook=ctx.workbook, case=case, pw=self.pw, cfg=cfg, bus=bus, run_dir=ctx.run_dir, cancel=ctx.cancel,
                                           planned=len(ctx.plans[case.id]), shared=ctx.shared, worker=n, attempt=attempt, throttle=throttle, asker=ctx.asker)
                else:
                    runner = TestRunner(workbook=ctx.workbook, case=case, browser_getter=self.get_window if at_window else get_browser, cfg=cfg, bus=bus,
                                        run_dir=ctx.run_dir, selector_map=ctx.selector_map, cancel=ctx.cancel,
                                        planned_rows=ctx.plans[case.id], worker=n, harvest=ctx.harvest, devices=self.devices,
                                        attempt=attempt, throttle=throttle, asker=ctx.asker, visible=at_window or not ctx.plan.headless, shared=ctx.shared,
                                        pool=ctx.pool, pw=self.pw)
                ctx.partial[case.id] = runner.result
                try:
                    res = await asyncio.wait_for(runner.run(), timeout=cfg.runner.test_timeout_s)
                except asyncio.TimeoutError:
                    res = runner.result
                    res.status, res.error = "ERROR", f"Test exceeded {cfg.runner.test_timeout_s}s time limit"
                except asyncio.CancelledError:
                    raise
                finally:
                    if at_window:
                        await self.close_window()
            ctx.shared.update(runner.written)                   # parameter cells this test filled in (a policy number...): the API tests read them
            if res.captcha and not at_window and ctx.plan.headless and cfg.captcha.solve == "ask" and ctx.asker.available and not ctx.cancel.is_set():
                # A captcha needs a person.  The test was stopped where it met it; it is run again from the start in a visible browser window,
                # and there it waits for the person to solve the captcha (a headless browser cannot be turned into a visible one).
                captcha_tries += 1
                at_window = True
                attempts.append({"attempt": attempt, "status": res.status, "failed": res.failed, "error": res.error,
                                 "duration_s": res.duration_s, "captcha": True})
                ctx.note(f"{case.id}: a captcha stopped this attempt. Opening a browser window: solve the captcha there and the test carries on by itself.")
                continue
            if res.infra and not ctx.cancel.is_set():
                # The machine, not the site: the browser crashed / ran out of memory / was disconnected, or the driver died.  No verdict: the test is run
                # again from the start (every attempt stays in attempts[]), after a pause that lets the computer recover.
                attempts.append({"attempt": attempt, "status": res.status, "failed": res.failed, "error": res.error,
                                 "duration_s": res.duration_s, "infra": res.infra})
                if infra_tries < cfg.runner.infra_retries:
                    infra_tries += 1
                    pause = max(0.0, float(cfg.runner.infra_pause_s))
                    ctx.note(f"{case.id}: {res.infra}. Not a test result: running it again from the start in {pause:g}s ({infra_tries}/{cfg.runner.infra_retries}).")
                    notice = WaitNotice(bus, case.id, n)
                    wait_id = notice.begin("infra_rerun", f"The browser stopped working ({res.infra[:160]}). This is not a test result: the test "
                                                          f"starts again from the beginning (try {infra_tries} of {cfg.runner.infra_retries}).", seconds=pause)
                    try:
                        if "driver" in res.error.lower() or "driver" in res.infra.lower():
                            await self.restart_driver(generation)
                        try:
                            await asyncio.wait_for(ctx.cancel.wait(), timeout=pause)
                        except asyncio.TimeoutError:
                            pass
                    finally:
                        notice.end(wait_id)
                    continue
                res.error = (f"Not run: {res.infra}. It happened on {infra_tries + 1} attempt(s) in a row, so the test could not be run on this "
                             "computer now (too little memory? too many workers?). This says nothing about the application.")
                res.attempts = attempts[:-1]
                return res
            budget = throttle.retry_budget(cfg.runner.block_retries)
            if res.blocked and block_tries < budget and not ctx.cancel.is_set():
                # The WAF refused us (HTTP 403 / 429).  Not a verdict on the application: pause every page load, take a worker out of
                # service so the load stays lower, and run this test again from the start.
                block_tries += 1
                reduced = throttle.cool_down(cfg.runner.block_cooldown_s, reduce=True, running=self.running_on(throttle))
                attempts.append({"attempt": attempt, "status": res.status, "failed": res.failed, "error": res.error,
                                 "duration_s": res.duration_s, "blocked": True})
                ctx.note(f"{case.id}: the site blocked this attempt ({res.blocked[:120]}). Pausing page loads for "
                         f"{cfg.runner.block_cooldown_s:g}s{' and running with one worker fewer' if reduced else ''}; trying again "
                         f"({block_tries}/{budget}).")
                bus.emit("run_paused", test=case.id, seconds=cfg.runner.block_cooldown_s, attempt=block_tries, of=budget,
                         reason=res.blocked[:240])
                continue
            if res.blocked and not throttle.loaded_ok and block_tries and not ctx.cancel.is_set():
                res.error = (f"{res.error} Blocked again after waiting, and nothing has loaded from this machine in this run: this looks like a "
                             "standing access rule (allow-list, VPN, country), not rate limiting, so retrying will not help until it changes.")
            if res.status in ("PASSED", "CANCELLED", "NOT_RUN") or (attempt - block_tries - captcha_tries - infra_tries) > cfg.behaviour.retries or ctx.cancel.is_set():
                res.attempts = attempts
                return res
            attempts.append({"attempt": attempt, "status": res.status, "failed": res.failed,
                             "error": res.error, "duration_s": res.duration_s})
            bus.emit("log", level="warning", message=f"{case.id}: attempt {attempt} {res.status}; retrying")

    async def worker(self, n: int, delay: float = 0.0) -> None:
        browser = None
        cfg = self.cfg

        async def get_browser():
            nonlocal browser
            if browser is None or not browser.is_connected():
                browser = await cfg.browser.launch(self.pw, self.headless)
            return browser
        try:
            if delay > 0:
                try:
                    await asyncio.wait_for(self.cancel.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
            while not self.cancel.is_set():
                picked = await self.pool.take()                       # (a site that a block reduced is skipped here until it has room again)
                if picked is None:
                    break
                ctx, case = picked
                queued_s, deps_s = ctx.schedule.queued_s(case.id)             # waiting for a worker is the run's time, not the test's
                try:
                    reason = self.producer_failed(ctx, case)
                    if reason:
                        res = self.not_run(ctx, case, reason, n)
                    else:
                        task = asyncio.ensure_future(self.run_case(ctx, case, get_browser, n))
                        ctx.tasks.add(task)
                        try:
                            await asyncio.wait({task})
                        finally:
                            ctx.tasks.discard(task)
                        if task.cancelled():
                            res = self.stopped(ctx, case, "Stopped by force: the run was cancelled and this test did not end in time.", "CANCELLED")
                        elif task.exception() is not None:
                            err = task.exception()
                            res = self.stopped(ctx, case, f"The runner failed on this test: {type(err).__name__}: {err}", "ERROR")
                        else:
                            res = task.result()
                finally:
                    await self.pool.finished(ctx, case.id)
                if ctx.cfg.measure.timing:
                    res.timing = {**(res.timing or {}), "queue_s": round(queued_s, 2), **({"deps_s": round(deps_s, 2)} if deps_s >= 0.05 else {})}
                ctx.results[case.id] = res
                ctx.result.tests = [ctx.results[c.id] for c in ctx.cases if c.id in ctx.results]
                ctx.result.save(ctx.run_dir / "results.json")
        finally:
            if browser is not None:
                try:
                    await asyncio.wait_for(browser.close(), cfg.runner.close_timeout_s)
                except asyncio.TimeoutError:
                    self.note(f"Browser for worker {n} did not close within {cfg.runner.close_timeout_s:g}s; continuing")
                except Exception:
                    pass

    # -- one run's life -----------------------------------------------------------------------------------------
    async def watch_markers(self, ctx: RunCtx) -> None:
        """``cancel`` in the run's folder = finish the current steps and stop; ``stop`` = end the tests now (the web UI writes it when a cancel takes too long)."""
        while not ctx.ended:
            if not ctx.cancel.is_set() and (ctx.run_dir / "cancel").exists():
                ctx.cancel.set()
                ctx.note("Cancellation requested; finishing the current step")
                await self.pool.wake()
            if not ctx.stopped and (ctx.run_dir / "stop").exists():
                ctx.stopped = True
                await self.force_stop(ctx)
            await asyncio.sleep(0.5)

    async def force_stop(self, ctx: RunCtx) -> None:
        ctx.cancel.set()
        ctx.note("Stopping this run now", "warning")
        for task in list(ctx.tasks):
            task.cancel()
        deadline = time.monotonic() + self.cfg.runner.close_timeout_s + 5
        while ctx.tasks and time.monotonic() < deadline:
            await asyncio.sleep(0.25)
        if ctx.tasks:                                                # a test that ignores being ended must not keep the run open
            ctx.abandoned = True
            ctx.note(f"{len(ctx.tasks)} test(s) did not stop; the run is closed without them", "error")
        await self.pool.wake()

    async def lifecycle(self, ctx: RunCtx) -> None:
        watcher = asyncio.ensure_future(self.watch_markers(ctx))
        try:
            await self.pool.run_is_over(ctx, lambda: ctx.abandoned)
            if not self.pool.joinable and self.pool.all_over():        # the last tests of the process are done: the workers close their browsers before the run says it is finished
                await self.wind_down()
            await self.finalize(ctx)
        finally:
            watcher.cancel()

    async def wind_down(self) -> None:
        """Nothing is left to run and nothing can join: let the workers go home (each closes its browser, time-limited) and wait for them."""
        if self._winding is None:
            self._winding = asyncio.ensure_future(self._close_workers())
        await self._winding

    async def _close_workers(self) -> None:
        await self.pool.close()
        await asyncio.wait(self.workers, timeout=self.cfg.runner.close_timeout_s * 2 + 10)
        self.note("All tests finished; closing the browsers", "info")

    async def finalize(self, ctx: RunCtx) -> None:
        ctx.ended = True
        cfg, options = ctx.cfg, ctx.plan.options
        note = lambda message, level="warning": ctx.note(message, level)
        ctx.asker.cleanup()                                          # nothing a person typed in stays on disk
        result = ctx.result
        result.tests = [ctx.results[c.id] for c in ctx.cases if c.id in ctx.results]
        result.ended_at = now_iso()
        result.duration_s = round(time.perf_counter() - ctx.started, 2)
        if cfg.measure.timing:
            result.timing = run_summary(result.tests)
        result.resources = summarize(read_resources(ctx.run_dir / "resources.jsonl"))
        if ctx.cancel.is_set():
            result.status = "CANCELLED"
        elif any(t.status in ("FAILED", "ERROR") for t in result.tests):
            result.status = "FAILED"
        elif any(t.status == "NOT_RUN" for t in result.tests):
            result.status = "INCOMPLETE"                              # nothing failed, but not everything could be run: not a pass either
        else:
            result.status = "PASSED"
        if ctx.harvest is not None:
            ctx.harvest.save(ctx.run_dir / "selector_suggestions.json")
            result.artifacts["selector_suggestions"] = "selector_suggestions.json"
        result.save(ctx.run_dir / "results.json")

        if options.report and cfg.reports.html:
            want_pdf = cfg.reports.pdf if options.pdf is None else options.pdf
            note("Building the report", "info")
            try:
                from ..reporting.html_report import build_report
                artifacts = await asyncio.wait_for(build_report(ctx.run_dir, pdf=want_pdf), cfg.runner.report_timeout_s)
                result.artifacts.update(artifacts)
            except asyncio.TimeoutError:
                note(f"The report was not ready after {cfg.runner.report_timeout_s:g}s and was skipped; results.json has everything", "error")
            except Exception as err:                                  # a report problem must not lose the run
                ctx.bus.emit("log", level="error", message=f"Report generation failed: {err!r}")
        result.artifacts.setdefault("results", "results.json")
        result.save(ctx.run_dir / "results.json")
        from ..publish import publish_finished_run
        await publish_finished_run(cfg, ctx.run_dir, result.status, note)          # the shared copy; bounded, never fails the run
        update_meta(ctx.run_dir, ended_at=result.ended_at, duration_s=result.duration_s, summary=result.summary, artifacts=result.artifacts,
                    shares=ctx.shares)
        ctx.bus.emit("run_finished", status=result.status, summary=result.summary, artifacts=result.artifacts,
                     duration_s=result.duration_s)
        ctx.jsonl.close()
        ctx.closed = True
        update_meta(ctx.run_dir, status=result.status)               # last: the run counts as going until everything of it is written (the UI reads this)

    # -- joining ---------------------------------------------------------------------------------------------------
    async def accept(self, run_id: str, request: dict[str, Any]) -> None:
        """A run asks to join the workers that are going.  Answers in the inbox (``rejected``) when it cannot."""
        assert self.inbox is not None
        try:
            options = options_from_request(request, run_id)
            if options.browser and browsers.resolve(options.browser).id != self.kind.id:
                raise SelectionError(f"The workers running now use {self.kind.label}; this run asked for {browsers.resolve(options.browser).label}. "
                                     "Runs that share workers share their browser.")
            if bool(request.get("headed")) != (not self.headless):
                raise SelectionError(f"The workers running now {'show their browsers' if not self.headless else 'run headless'}, and this run asks for the "
                                     "opposite. Runs that share workers share that too.")
            plan = await plan_run(options, self.cfg, self.kind)
            if self.browser_info.get("id") == "none" and any(c.kind != "api" for c in plan.cases):       # the pool began with API tests only: this is its first browser test
                found = await browsers.probe(self.kind, headless=self.headless, cached=True)
                self.browser_info = browsers.identity(self.kind, version=found["version"], headless=self.headless, user_agent=found["user_agent"])
            ctx = await open_run(plan, None, self.browser_info, self.ask_mode)
        except (SelectionError, browsers.BrowserError, browsers.BrowserUnavailable) as err:
            self.inbox.reject(run_id, str(err))
            return
        except Exception as err:                                      # a run that cannot join must never take the ones going down with it
            self.inbox.reject(run_id, f"{type(err).__name__}: {err}")
            return
        await self.add_run(ctx)

    async def watch_inbox(self) -> None:
        """Take in runs that ask to join; when every run is over, close the door (see ``engine/inbox.py``) and end the pool."""
        assert self.inbox is not None
        while True:
            for run_id, request in self.inbox.claim():
                await self.accept(run_id, request)
            if self.pool.runs and all(r.ended for r in self.pool.runs):
                self.inbox.close()                                    # from now on a run that wants in starts a process of its own...
                late = self.inbox.claim()                             # ...and one that got in just before is taken now
                for run_id, request in late:
                    await self.accept(run_id, request)
                if not late:
                    break
                continue
            await asyncio.sleep(0.4)
        await self.pool.close()

    def sample_counts(self) -> dict[str, Any]:
        live = [r for r in self.pool.runs if not r.ended]
        return {"tests_running": sum(r.schedule.running for r in live), "tests_waiting": sum(r.schedule.pending for r in live),
                "workers": len(self.workers)}

    async def serve(self, first: list[RunCtx], workers: int) -> None:
        """Run ``first`` (and whatever joins) to the end."""
        cancel_watch = asyncio.ensure_future(self.propagate_cancel())
        stall = asyncio.ensure_future(self.watch_stall())
        sampler = None
        if self.cfg.measure.sample_s > 0:                              # what the computer went through: resources.jsonl in every run that is going
            sampler = asyncio.ensure_future(ResourceSampler(
                self.cfg.measure.sample_s, lambda: [r.run_dir for r in self.pool.runs if r.announced and not r.ended], self.sample_counts).run())
        inbox_task = None
        async with self.playwright_session() as pw:
            self.pw = pw
            self.devices = dict(pw.devices)
            for ctx in first:
                self.register(ctx)
            for ctx in first:
                announce_run(ctx, workers)
            self.spawn_workers(workers)
            for ctx in first:
                self.lifecycles.append(asyncio.ensure_future(self.lifecycle(ctx)))
            await self.pool.wake()
            try:
                if self.inbox is not None:
                    inbox_task = asyncio.ensure_future(self.watch_inbox())
                    await inbox_task
                else:
                    await asyncio.gather(*self.lifecycles)
                    await self.pool.close()
                await asyncio.gather(*self.lifecycles)
                await asyncio.gather(*self.workers)
                if self._winding is None:
                    self.note("All tests finished; closing the browsers", "info")
            finally:
                cancel_watch.cancel()
                stall.cancel()
                if sampler is not None:
                    sampler.cancel()
                if inbox_task is not None:
                    inbox_task.cancel()
                await self.close_window()


def options_from_request(request: dict[str, Any], run_id: str) -> RunOptions:
    """A run's options from what the web UI writes to the inbox (``web/app.py``: the tests are always listed by id, never "all")."""
    workbook = Path(str(request.get("workbook", "")))
    if not workbook.is_file():
        raise SelectionError(f"Workbook not found: {workbook.name}")
    tests = [str(t) for t in request.get("tests") or []] or None
    chains = request.get("chains")
    return RunOptions(
        workbook=workbook, tests=tests, tags=[str(request["tag"])] if request.get("tag") and not tests else None,
        environment=request.get("env") or None, workers=None, headless=False if request.get("headed") else None,
        browser=request.get("browser") or None, seed=request.get("seed"), screenshots=request.get("screenshots") or None,
        run_id=run_id, report=not request.get("no_report"), pdf=request.get("pdf"), harvest=request.get("harvest"),
        retries=request.get("retries"), allow_prod=bool(request.get("allow_prod")),
        chains=None if chains is None else [[str(t) for t in c] for c in chains], extra={"nice": request.get("nice")})


async def execute_many(optionses: list[RunOptions], cfg: Config, buses: list[EventBus | None] | None = None,
                       cancel: asyncio.Event | None = None, inbox_dir: Path | None = None) -> list[RunResult]:
    """Run one run per entry of ``optionses`` on one set of workers.  The settings that belong to the workers (browser, headed or not, how many
    workers, who answers ASK_USER steps) are the first entry's; the rest of an entry (workbook, tests, environment, chains, screenshots,
    retries...) is its own."""
    if not optionses:
        raise SelectionError("Nothing to run.")
    cancel = cancel or asyncio.Event()
    first = optionses[0]
    headless = cfg.runner.headless if first.headless is None else first.headless
    try:
        kind = browsers.resolve(first.browser) if first.browser else cfg.browser.kind
        for other in optionses[1:]:
            if other.browser and browsers.resolve(other.browser).id != kind.id:
                raise SelectionError("Runs that share workers share their browser: pass one --browser for all of them.")
    except browsers.BrowserError as err:
        raise SelectionError(str(err)) from err
    plans = []
    for i, options in enumerate(optionses):                                                  # every run is worked out before any of them is created
        try:
            plans.append(await plan_run(options, cfg, kind))
        except EnvironmentMissing as err:
            if buses and i < len(buses) and buses[i] is not None:
                buses[i].emit("env_missing", environment=err.environment, variables=err.variables, message=str(err))
            raise
    if any(c.kind != "api" for p in plans for c in p.cases):          # start the browser once before anything is created: one that cannot start is one clear
        try:                                                          # message, not the same launch error in every test, and it gives the version for the record
            found = await browsers.probe(kind, headless=headless, cached=True)
        except browsers.BrowserUnavailable as err:
            raise SelectionError(str(err)) from err
        browser_info = browsers.identity(kind, version=found["version"], headless=headless, user_agent=found["user_agent"])
    else:
        browser_info = browsers.no_browser(headless)                  # API tests only: nothing opens a browser
    ask_mode = str(first.extra.get("ask") or "off")
    total = sum(len(p.cases) for p in plans)
    want = max(1, min(first.workers or cfg.effective_workers, cfg.runner.max_workers))
    workers = max(1, min(want, total))
    inbox = Inbox(inbox_dir) if inbox_dir is not None else None
    cfg.browser.name = kind.id                                        # the browser this run uses is what the config says from here on (sign-in, PDF...)
    pool_cfg = copy.deepcopy(cfg)
    engine = Engine(pool_cfg, cancel, kind=kind, headless=headless, want_workers=want, ask_mode=ask_mode, browser_info=browser_info, inbox=inbox)
    ctxs = [await open_run(plan, (buses[i] if buses else None), browser_info, ask_mode) for i, plan in enumerate(plans)]
    await engine.serve(ctxs, workers)
    return [ctx.result for ctx in ctxs]


async def execute(options: RunOptions, cfg: Config, bus: EventBus | None = None,
                  cancel: asyncio.Event | None = None) -> RunResult:
    return (await execute_many([options], cfg, [bus], cancel))[0]
