"""A build session: the live browser window the Build tab drives (P08; Q5, Q10-Q13, Q49, Q50).

One session per workbook, opened by the UI server (``web/build_api.py``) in its own process and event loop, the way the sign-in window is:

* **Its own browser and its own copy of the workbook.**  Replays read the *draft* being edited (written to ``runs/.build/<workbook>/``), never
  the file on disk, and never touch a run: a run of the same workbook can go on at the same time in its own process and browser (the run
  reads the saved file).  A build session is not a run (no run folder, no results.json, not in the run list) and does not keep the server
  "busy"; it closes itself after ``build.idle_close_s`` of nobody using it.
* **The same actions as a real run.**  Steps are replayed by ``engine.test_runner.TestRunner`` itself (``prepare_runtime`` / ``open_session`` /
  ``_execute``), so what passes here passes in a run.  Differences are only about *when to stop*: a replay stops at its first failed step
  (the page is then probably not where the next step expects), and a ``SIDE_EFFECTS=Y`` step waits for a person to say "run it for real"
  (``TestRunner(side_effects="ask")``; production still blocks it).  Nothing is ever retried.
* **The overlay** (``overlay.js``) is added to every context the session's browser opens (``add_init_script`` + ``expose_binding``), so it is
  in every page, frame and new window, after every navigation.
* **Picking**: the overlay sends what it read from the element; ``locators.py`` lists candidate locators; each is checked here on the live page
  with the engine's own selectors (``selectors.spec.legacy_strategy``) - the first that finds exactly that element becomes the step's locator,
  others that also find it its backups.  A word of the description can become a variable: the locator is rebuilt with ``{NAME}`` and checked
  again with each data row's value.
* **Recording, Check / Save / Wait until** (P09): ``recorder.py``.  The overlay proves its calls with the session's ``key`` (baked into its
  source, which the site's scripts cannot read); only such calls can record or add a check.
* **Run up to here / this step / next N** keep the browser and the test's state between calls.  When a step at or above the last replayed one
  changes (or the data row / environment), the session says "earlier steps changed: replay from the start to be sure".
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import Config, workbook_secrets
from ..engine.ask import AskCancelled, AskTimeout
from ..engine.outcome import FAILED
from ..engine.test_runner import TestRunner
from ..events import EventBus
from ..selectors.resolve import SelectorMap
from ..workbook.builder import BuildDocument, BuildError, parse_test_sheet, read_environments
from ..workbook.model import TestCase, Workbook
from ..workbook.sheet import cell_text
from ..workbook.variables import MARKERS
from . import locators as L
from .recorder import Recorder

OVERLAY_JS = (Path(__file__).with_name("overlay.js")).read_text(encoding="utf-8")
BINDING = "__rrBuildCall"
MAX_SESSIONS = 3                         # build windows open at once (one per workbook)
LOG_KEEP = 400                           # events kept for the Build tab (it asks for the ones after the last it saw)
CHECK_S = 3.0                            # a locator check on the live page may take this long
WINDOWLESS_GRACE_S = 1.0                 # a window closed: if none is left this much later (and nothing is opening one), the person closed it
NEXT_DEFAULT = 5
LOG_TYPES = {"step_started", "step_passed", "step_failed", "step_skipped", "log", "side_effect_paused", "side_effect_blocked", "page_gate",
             "popup_dismissed", "backup_locator_suggestion", "variable_set", "user_input_needed", "user_input_received", "user_input_closed",
             "branch_taken", "iteration_started", "call_started", "call_finished", "captcha_detected"}
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class BuildAsker:
    """``engine.ask.Asker`` for a build replay: the question (ASK_USER, a blank parameter, "run this side-effect step for real?") shows in the
    Build tab, whose answer comes back through ``answer``.  The answer is never stored or logged."""

    available = True

    def __init__(self, session: "BuildSession"):
        self.session = session
        self._answers: dict[str, str] = {}

    async def ask(self, test: str, step: int, question: str, *, secret: bool = False, timeout_s: float | None = None, kind: str = "text",
                  until=None) -> str:
        s = self.session
        ask_id = uuid.uuid4().hex[:10]
        side = s.last_side_effect if s.last_side_effect and s.last_side_effect.get("step") == step else None
        s.question = {"id": ask_id, "text": question, "secret": bool(secret), "kind": kind, "step": step, "sideEffect": side}
        s.emit("user_input_needed", test=test, step=step, ask=ask_id, question=question, secret=secret, kind=kind)
        wait_s = float(timeout_s or s.cfg.ask.timeout_s)
        started = time.monotonic()
        try:
            while True:
                if ask_id in self._answers:
                    answer = self._answers.pop(ask_id)
                    s.emit("user_input_received", test=test, step=step, ask=ask_id)
                    return answer
                if s.cancelled():
                    raise AskCancelled("The replay was stopped while waiting for an answer.")
                if until is not None:
                    try:
                        if await until():
                            return ""
                    except Exception:
                        pass
                if time.monotonic() - started >= wait_s:
                    s.emit("user_input_closed", test=test, step=step, ask=ask_id, reason="timeout")
                    raise AskTimeout(f"Nobody answered within {wait_s:g} s.")
                await asyncio.sleep(0.2)
        finally:
            if s.question and s.question.get("id") == ask_id:
                s.question = None
            s.touch()

    def answer(self, ask_id: str, answer: str) -> bool:
        if not self.session.question or self.session.question.get("id") != ask_id:
            return False
        self._answers[ask_id] = answer
        return True


class _OverlayBrowser:
    """What the test's ``BrowserSession`` gets as its browser: the session's real browser, whose every new context carries the overlay."""

    def __init__(self, browser, session: "BuildSession"):
        self._browser, self._session = browser, session

    async def new_context(self, **options):
        context = await self._browser.new_context(**options)
        await self._session.arm(context)
        await self._session.close_blank()                  # the test opened its own window: the blank one is not needed any more
        return context

    def __getattr__(self, name: str):
        return getattr(self._browser, name)


def _signature(rows: list[list[Any]], upto: int, extra: Any) -> str:
    """What rows 2..``upto`` of a test sheet hold (plus the data row and environment): when it changes, earlier steps changed."""
    body = [[cell_text(v) if v is not None else "" for v in r] for r in rows[1:upto]]
    return json.dumps([body, extra], ensure_ascii=False, default=str)


class BuildSession:
    """The build browser of one workbook.  Every public coroutine runs on the server's event loop; workbook work goes to a thread."""

    def __init__(self, doc: BuildDocument, cfg: Config, folder: Path, *, environment: str, headless: bool):
        self.doc, self.cfg, self.folder = doc, cfg, folder
        self.environment = environment
        self.headless = headless
        self.name = doc.path.name
        self.test_id: str = ""
        self.data_row: int | None = None
        self.status = "starting"                                  # starting | ready | running | closed
        self.error = ""
        self.mode = "browse"                                      # browse | pick | check | save | wait | which
        self.purpose = "pick"                                     # what the next pick is for: pick | check | save | wait
        self.pick_for: int | None = None                          # the step row a pick is for
        self.pick: dict | None = None
        self.which: dict | None = None
        self.question: dict | None = None
        self.replay: dict | None = None
        self.cursor_row: int | None = None                        # the last step row replayed
        self.next_row: int | None = None                          # where "run next" carries on
        self.last_side_effect: dict | None = None
        self.version = 0                                          # bumps on every change the Build tab should see
        self.log: list[dict] = []
        self._seq = 0
        self._prefix = ""                                         # _signature of rows 2..cursor_row when they were replayed
        self._stale: tuple[int, str, bool] | None = None          # (doc version, prefix, stale) cache
        self._pw = None
        self._browser = None
        self._blank = None                                        # a window of its own until the test opens one (no Open step run yet)
        self._runner: TestRunner | None = None
        self._runtime = None
        self._flow = None
        self._loops: list[dict] = []
        self._loaded_version = -1
        self._task: asyncio.Task | None = None
        self._watch: asyncio.Task | None = None
        self._cancel: asyncio.Event | None = None
        self._picked_frame = None                                 # the frame the picked element lives in
        self._meta: dict = {}                                     # the test's sheet, parameter sheet and data rows (from the model, at start)
        self._steps_cache: tuple[int, list[dict]] | None = None
        self._opening = False                                     # start / switch are between windows (one closed, the next not open yet)
        self._closing = False
        self.notice = ""                                          # a plain-words note for the Build tab's strip (no Domain to open, ...)
        self.asker = BuildAsker(self)
        self.key = uuid.uuid4().hex + uuid.uuid4().hex            # the overlay's proof that a call is its own (P09)
        self.recorder = Recorder(self)
        self.bus = EventBus(run_id=f"build:{self.name}")
        self.bus.subscribe(self._on_event)
        self.touched = time.monotonic()

    # -- small helpers -----------------------------------------------------------------------------------------------------------------
    def touch(self) -> None:
        self.touched = time.monotonic()
        self.version += 1

    def cancelled(self) -> bool:
        return self._cancel is not None and self._cancel.is_set()

    def emit(self, type_: str, **fields) -> None:
        self.bus.emit(type_, **fields)

    def _on_event(self, event: dict) -> None:
        kind = event.get("type", "")
        if kind == "side_effect_paused":
            self.last_side_effect = {"step": event.get("step"), "row": event.get("row"), "name": event.get("name"),
                                     "environment": event.get("environment")}
        if kind == "step_started" and self.replay is not None:
            self.replay["current"] = {"row": event.get("row"), "name": event.get("name") or event.get("action") or ""}
        if kind in LOG_TYPES or kind.startswith("build_session_"):
            self._seq += 1
            keep = {k: v for k, v in event.items() if k not in ("run_id", "diagnosis", "timing", "detail")}
            self.log.append({"seq": self._seq, **keep})
            del self.log[:-LOG_KEEP]
            if kind == "log" or kind.startswith("build_session_"):          # kept on disk too: what a window did is needed after the window is gone
                try:
                    self.folder.mkdir(parents=True, exist_ok=True)
                    with open(self.folder / "session.log", "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({k: v for k, v in keep.items() if k != "seq"}, default=str) + "\n")
                except Exception:
                    pass
        self.version += 1

    def _steps(self) -> list[dict]:
        """The test's steps as the builder numbers them (``n``), read from the draft once per version: only its own sheet is parsed (the
        whole model is the Build tab's, and rebuilding it here on every poll would be slow)."""
        version = self.doc.version
        if self._steps_cache is None or self._steps_cache[0] != version:
            steps: list[dict] = []
            with self.doc.lock:
                editor = self.doc.editor
                real = next((s for s in editor.sheet_names() if s.upper() == self._meta.get("sheet", "").upper()), None)
                if real is not None:
                    steps = parse_test_sheet(editor, real, set())["steps"]
            self._steps_cache = (version, steps)
        return self._steps_cache[1]

    def _n_of(self, row: int | None) -> int | None:
        if row is None:
            return None
        step = next((s for s in self._steps() if s["row"] == row), None)
        return step["n"] if step else None

    # -- lifecycle -----------------------------------------------------------------------------------------------------------------------
    async def start(self, test_id: str, data_row: int | None) -> None:
        """Open the browser for ``test_id``.  When the test starts with an Open step, that step runs (it only opens the site), so there is a
        page to pick on; otherwise a blank window opens."""
        from playwright.async_api import async_playwright
        self._cancel = asyncio.Event()                             # (made inside a coroutine: Python 3.9 binds it to the running loop)
        self.recorder._lock = asyncio.Lock()                       # (the same)
        await asyncio.to_thread(self._select, test_id, data_row)
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            self._pw = await async_playwright().start()
            self._browser = await self.cfg.browser.launch(self._pw, self.headless)
        except Exception as err:
            await self.close()
            raise BuildError(f"Could not open a browser window: {(str(err).splitlines() or [err])[0]}", "browser", 500) from err
        self._browser.on("disconnected", lambda *_: self._browser_gone())
        self.status = "ready"
        self.emit("build_session_started", workbook=self.name, test=self.test_id, environment=self.environment, data_row=self.data_row)
        self._opening = True
        try:
            await self._open_site()
        finally:
            self._opening = False
        if self.cfg.build.idle_close_s:
            self._watch = asyncio.create_task(self._close_when_idle())
        self.touch()

    def _select(self, test_id: str, data_row: int | None) -> None:
        model = self.doc.model(self.environment)
        test = next((t for t in model["tests"] if t["id"] == test_id), None)
        if test is None:
            raise BuildError(f"There is no test {test_id!r} in {self.name}.", "not_found", 404)
        if test["kind"] != "web":
            raise BuildError(f"{test_id} is an {test['kind'].upper()} test: the build window is for website tests.", "kind", 422)
        rows = [r["row"] for r in test["dataRows"]]
        if data_row is not None and rows and int(data_row) not in rows:
            raise BuildError(f"Row {data_row} is not a data row of {test['paramSheet']}.", "data_row", 422)
        self.test_id = test_id
        self._meta = {"sheet": test["sheet"], "paramSheet": test.get("paramSheet") or "", "dataRows": test["dataRows"]}
        self._steps_cache = None
        self.data_row = int(data_row) if data_row is not None else test["buildingWith"]

    async def _open_site(self) -> None:
        """A page to pick on: the test's first step when it is an Open step (it only opens the site), else a window of its own on the
        environment's Domain (the ``DOMAIN`` row of the environment table), else a blank one with a note saying where to set the Domain."""
        self.notice = ""
        first = await asyncio.to_thread(self._first_step)
        if first and first["method"] == "OPEN":
            self._launch("to", row=first["row"])
        elif not self._open_pages():
            await self._open_on_domain()

    async def _open_on_domain(self) -> None:
        """A window of its own on the environment's Domain, or a blank one with a note saying where to set it."""
        await self._open_blank()
        domain = await asyncio.to_thread(self.domain)
        if not domain:
            self.notice = (f"No Domain is set for {self.environment or 'this environment'}, so the window opened blank. "
                           "Set it under Environments (the DOMAIN row).")
            return
        page = self._open_pages()[-1] if self._open_pages() else None
        if page is None:
            return
        try:
            await page.goto(site_url(domain), wait_until="domcontentloaded", timeout=float(self.cfg.timeouts.navigation_s) * 1000)
        except Exception as err:                              # (the window stays open: the person can type the address themselves)
            self.notice = f"Could not open {domain}: {(str(err).splitlines() or [str(err)])[0]}"

    def domain(self) -> str:
        """The environment's Domain: the ``DOMAIN`` row of the environment table, for the environment this window uses ("" when none)."""
        with self.doc.lock:
            table = read_environments(self.doc.editor)
        row = next((r for r in table["rows"] if str(r.get("variable") or "").strip().upper() == "DOMAIN"), None)
        if row is None:
            return ""
        values = row.get("values") or {}
        env = (self.environment or "").upper()
        value = next((v for n, v in values.items() if n.upper() == env), "") if env else ""
        if not value and not env and table.get("names"):
            value = values.get(table["names"][0], "")
        return str(value or "").strip()

    def _first_step(self) -> dict | None:
        steps = [s for s in self._steps() if s["enabled"] is not False]
        return steps[0] if steps else None

    async def switch(self, test_id: str, data_row: int | None, environment: str) -> None:
        """Another test / data row / environment in the same window: the next replay starts from the beginning."""
        if self._task is not None and not self._task.done():
            raise BuildError("A replay is still going. Stop it first.", "busy", 409)
        await asyncio.to_thread(self._select, test_id, data_row)
        if environment and environment != self.environment:
            self.environment = environment
        await self.recorder.stop()
        self._opening = True
        try:
            await self._drop_runner()
            self.pick = self.which = None
            self.replay = None
            self.touch()
            await self._open_site()
        finally:
            self._opening = False

    def _browser_gone(self) -> None:
        if self.status != "closed":
            self.status = "closed"
            self.error = self.error or "The build browser was closed."
            self.touch()

    async def _close_when_idle(self) -> None:
        limit = float(self.cfg.build.idle_close_s)
        while self.status != "closed":
            await asyncio.sleep(min(30.0, limit))
            running = self._task is not None and not self._task.done()
            if not running and time.monotonic() - self.touched > limit:
                self.error = f"Closed after {limit / 60:g} minutes without use."
                await self.close()
                return

    async def close(self) -> None:
        self._closing = True
        self.recorder.finish()
        if self._cancel is not None:
            self._cancel.set()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), 10)
            except BaseException:
                pass
        watch, self._watch = self._watch, None
        if watch is not None and watch is not asyncio.current_task():
            watch.cancel()
        await self._drop_runner()
        await self.close_blank()
        browser, pw = self._browser, self._pw
        self._browser = self._pw = None
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                await pw.stop()
            except Exception:
                pass
        if self.status != "closed":
            self.status = "closed"
            self.emit("build_session_closed", workbook=self.name, reason=self.error or "closed")
        self.touch()

    async def _drop_runner(self) -> None:
        runner, self._runner = self._runner, None
        self._runtime = self._flow = None
        self._loops = []
        self.cursor_row = self.next_row = None
        self._prefix = ""
        self._stale = None
        if runner is not None and runner.session is not None:
            await runner.session.close()

    # -- the overlay ---------------------------------------------------------------------------------------------------------------------
    async def arm(self, context) -> None:
        """Every context the build browser opens gets the overlay and the way back to the builder, and its windows are watched: when the
        person closes the last one, the build window is gone."""
        await context.expose_binding(BINDING, self._on_call)
        await context.add_init_script(script=OVERLAY_JS.replace("__RR_KEY__", self.key))
        context.on("page", self._watch_page)

    def _watch_page(self, page) -> None:
        page.on("close", lambda *_: self._page_closed())

    def _page_closed(self) -> None:
        """A window closed.  Closing the last one leaves the browser running with no window at all (it never says "disconnected"), so
        without this the Build tab would go on showing the window as open, and Pick would have no page.  Checked a moment later: a replay,
        a switch or the test's own Open step closes and opens windows as it goes."""
        if self.status == "closed" or self._closing:
            return
        asyncio.get_running_loop().call_later(WINDOWLESS_GRACE_S, lambda: asyncio.ensure_future(self._close_if_windowless()))

    async def _close_if_windowless(self) -> None:
        if self.status != "ready" or self._closing or self._opening:
            return
        if self._task is not None and not self._task.done():
            return
        browser = self._browser
        if browser is None or not browser.is_connected():
            return
        if any(not p.is_closed() for c in browser.contexts for p in c.pages):
            return
        self.error = "The build window was closed."
        await self.close()

    async def _open_blank(self) -> None:
        context = await self._browser.new_context(viewport=None if not self.headless else {"width": 1280, "height": 800})
        await self.arm(context)
        self._blank = context
        page = await context.new_page()
        if not self.headless:
            try:
                await page.bring_to_front()
            except Exception:
                pass

    async def close_blank(self) -> None:
        blank, self._blank = self._blank, None
        if blank is not None:
            try:
                await blank.close()
            except Exception:
                pass

    def _open_pages(self) -> list:
        pages = []
        runner = self._runner
        if runner is not None and runner.session is not None and runner.session.context is not None:
            pages = [p for p in runner.session.pages if not p.is_closed()]
        if not pages and self._blank is not None:
            pages = [p for p in self._blank.pages if not p.is_closed()]
        return pages

    def _page(self):
        """The window picking happens in: the test's current window, else the blank one."""
        runner = self._runner
        if runner is not None and runner.session is not None and runner.session.is_open:
            if runner.session.pending_dialog is not None:
                raise BuildError("A dialog is open in the build window: answer it (or run the next step) first.", "dialog", 409)
            return runner.session.page
        pages = self._open_pages()
        if not pages:
            raise BuildError("No build window is open. Run up to a step (or open the browser again).", "no_window", 409)
        return pages[-1]

    def overlay_state(self) -> dict:
        if self.mode in ("check", "save", "wait"):
            label = {"check": "Check: click an element", "save": "Save: click an element", "wait": "Wait until: click an element"}[self.mode]
        elif self.mode == "pick":
            n = self._n_of(self.pick_for)
            label = f"Picking for step {n}" if n else "Pick an element"
        elif self.mode == "which":
            label = "Which one? Click it"
        elif self.replay and self.replay.get("running"):
            cur = (self.replay.get("current") or {}).get("row")
            label = f"running step {self._n_of(cur) or '…'}"
        elif self.recorder.on:
            label = self.recorder.label()
        elif self.recorder.just_finished():
            label = self.recorder.finished_label()
        else:
            n, total = self._n_of(self.cursor_row), len(self._steps())
            label = f"step {n} of {total}" if n else f"{self.test_id} · not run yet"
        return {"mode": self.mode, "label": label, "rec": self.recorder.on, "prompts": self.recorder.overlay_prompts()}

    async def _on_call(self, source: dict, payload: Any):
        """The overlay calling (``window.__rrBuildCall``): never raises into the page.  The site's scripts can call it too, so without the
        session's key (``Recorder.trusted``) nothing it asks for writes to the workbook: hello, a mode, and a pick (which a person still has to
        use).  With the key (the overlay itself): record on / off, a recorded action, a check from the card, an answer to a prompt."""
        try:
            kind = payload.get("kind") if isinstance(payload, dict) else ""
            trusted = self.recorder.trusted(payload)
            if kind == "hello":
                if trusted:
                    asyncio.ensure_future(self.recorder.handle(source, payload))
                return self.overlay_state()
            self.touch()
            if kind == "diag" and trusted:
                self.emit("log", level="warning", message=f"overlay: {str(payload.get('what'))[:60]}: {str(payload.get('detail'))[:4000]}")
            elif kind == "mode":
                self.emit("log", level="info", message=f"overlay: mode {payload.get('mode')}")
                mode = payload.get("mode")
                await self.set_mode(mode if mode in ("pick", "browse", "check", "save", "wait") else "browse", self.pick_for)
            elif kind == "done":
                # the pill's Done: finish whatever is going on - picking / checking, and recording (only the overlay itself can stop that)
                self.which = None
                if self.recorder.on and trusted:
                    asyncio.ensure_future(self._quietly(self.recorder.stop()))
                await self.set_mode("browse", None)
            elif kind == "rec" and trusted and not self.recorder.replaying():       # (a replay's own clicks are not the person's)
                asyncio.ensure_future(self.recorder.handle(source, payload))
            elif kind == "record" and trusted:
                asyncio.ensure_future(self._quietly(self.recorder.start(self.recorder.cursor) if payload.get("on") else self.recorder.stop()))
            elif kind == "check-add" and trusted:
                asyncio.ensure_future(self._quietly(self.recorder.add_check(str(payload.get("check") or ""), str(payload.get("expected") or ""),
                                                                            str(payload.get("token") or ""))))
            elif kind == "prompt" and trusted:
                asyncio.ensure_future(self._quietly(self.recorder.answer(str(payload.get("id") or ""), str(payload.get("choice") or ""),
                                                                         token=str(payload.get("token") or ""))))
            elif kind == "pick":
                self.emit("log", level="info", message="overlay: an element was picked")
                self.which = None
                frame = source.get("frame") if isinstance(source, dict) else None
                asyncio.ensure_future(self._picked_quietly(frame, L.to_desc(payload.get("element"))))
        except Exception:
            return None
        return None

    async def _quietly(self, coro) -> None:
        try:
            await coro
        except Exception as err:                                          # (the page must never see an error; the Build tab gets it)
            self.emit("log", level="warning", message=(str(err).splitlines() or [str(err)])[0])
            self.touch()
            await self.broadcast()

    async def broadcast(self, extra: dict | None = None, frames: list | None = None) -> None:
        state = {**self.overlay_state(), **(extra or {})}
        targets = frames if frames is not None else [f for p in self._open_pages() for f in p.frames]
        runner = self._runner

        async def one(frame):
            try:
                await asyncio.wait_for(frame.evaluate("s => window.__rrBuild && window.__rrBuild.apply(s)", state), 2)
            except Exception:
                pass
        if runner is not None and runner.session is not None and runner.session.pending_dialog is not None:
            return                                                   # (a page with a dialog open answers nothing)
        await asyncio.gather(*(one(f) for f in targets))

    async def set_mode(self, mode: str, pick_for: int | None = None) -> None:
        if mode not in ("pick", "browse", "check", "save", "wait"):
            raise BuildError("mode is pick, check, save, wait or browse.", "mode", 400)
        if mode == "pick" and pick_for is None and self.recorder.on:
            mode = "check"                  # recording has no step waiting for a picked locator: a plain Pick would do nothing, so it offers the checks
        self.mode, self.pick_for = mode, pick_for
        self.purpose = mode if mode != "browse" else "pick"
        if mode != "browse":
            self.which = None
        self.touch()
        await self.broadcast({"card": None} if mode != "browse" else {})

    # -- picking -----------------------------------------------------------------------------------------------------------------------
    async def _check(self, frame, candidates: list[L.Candidate], values: dict[str, str] | None = None, ref: str = "") -> None:
        """How many elements each candidate finds on the live page, and where the picked one is among them (the engine's selectors).
        ``ref``: the element is one the overlay remembered for a recorded action, not the pick."""
        which = ("els => els.indexOf(window.__rrBuild.ref(" + json.dumps(ref) + "))") if ref else "els => els.indexOf(window.__rrBuild.picked())"
        for cand in candidates:
            selector = cand.selector(values, visible=False)
            if not selector:
                continue
            try:
                loc = frame.locator(selector)
                count = await asyncio.wait_for(loc.count(), CHECK_S)
                position = await asyncio.wait_for(loc.evaluate_all(which), CHECK_S) if count else -1
                vcount, vposition = -1, -1
                if count > 1:                                          # hidden copies of a component: count only what can be seen
                    seen = frame.locator(selector + L.VISIBLE)
                    vcount = await asyncio.wait_for(seen.count(), CHECK_S)
                    vposition = await asyncio.wait_for(seen.evaluate_all(which), CHECK_S) if vcount else -1
                cand.apply_counts(count, position, vcount, vposition)
            except Exception:
                cand.count, cand.position, cand.visible_only = 0, -1, False

    async def _picked(self, frame, desc: dict, variables: dict[str, str] | None = None) -> dict:
        """Work out the locator for the element the overlay picked (``window.__rrBuild.picked()`` in ``frame``)."""
        if frame is None or not desc:
            raise BuildError("Nothing was picked.", "pick", 409)
        self._picked_frame = frame
        purpose = self.purpose if self.mode in ("check", "save", "wait", "which") else "pick"      # ("which one?" keeps what the pick is for)
        cands = L.candidates(desc)
        await self._check(frame, cands)
        choice = L.choose(cands)
        read = None
        if purpose in ("check", "save", "wait"):                      # a step that READS the element must not find it by what it shows now
            read_cands = L.candidates(desc, own_text=False)
            await self._check(frame, read_cands)
            read = L.choose(read_cands)
            if purpose == "save" and read.ok:
                choice = read
        words = L.plain_words(desc)
        pick = {"desc": desc, "words": words, "text": L.describe(words), "locator": choice.to_json(), "ok": choice.ok, "variables": {},
                "locatorRead": read.to_json() if read is not None and read.ok else None,
                "rows": [], "frame": desc.get("frame") or "", "url": _path_of(getattr(frame, "url", "")), "for": self.pick_for,
                "forN": self._n_of(self.pick_for), "current": desc.get("current") or {}, "purpose": purpose}
        if purpose != "pick":
            pick["similar"] = await self.recorder.similar(frame, desc) if purpose == "check" else None
            pick["card"] = self.recorder.card(pick)
        self.pick = pick                                              # (whole: the Build tab may be looking)
        self.mode = "browse"
        self.touch()
        self.emit("log", level="info", message=f"picked {self.pick['text']}: "
                  + (f"{choice.primary.findby} {choice.primary.value}" if choice.primary else "no locator finds it on its own"))
        await self.broadcast({"card": self._card()})
        return self.pick

    def _card(self) -> dict:
        p = self.pick or {}
        if p.get("card"):
            return p["card"]
        loc = p.get("locator") or {}
        if not p.get("ok"):
            return {"title": p.get("text", ""), "ok": False, "lines": ["No locator finds only this element. Pick the element around it."]}
        lines = [f"{loc.get('matches', 0)} match · {loc.get('how')}: {loc.get('value', '')[:120]}"
                 + (f" (match {loc.get('index', 0) + 1})" if loc.get("index") else "")]
        if loc.get("backups"):
            lines.append(f"{len(loc['backups'])} backup locator{'s' if len(loc['backups']) != 1 else ''}")
        if p.get("frame"):
            lines.append(f"inside frame {p['frame'][:60]}")
        n = p.get("forN")
        lines.append(f"Use it on step {n} in the Build tab" if n else "Choose its step in the Build tab")
        return {"title": p.get("text", ""), "ok": True, "lines": lines}

    async def find_matches(self, text: str, kind: str = "") -> dict:
        """Q10: every element that matches ``text`` (a kind of element optional) gets a numbered outline; one is then chosen."""
        text = " ".join(str(text or "").split())
        if not text:
            raise BuildError("Type the text of the element to look for.", "which", 400)
        page = self._page()
        matches = []
        for f_index, frame in enumerate(page.frames):
            try:
                found = await asyncio.wait_for(frame.evaluate("q => window.__rrBuild ? window.__rrBuild.findAll(q) : []", {"text": text, "kind": kind}), CHECK_S)
            except Exception:
                continue
            for local, d in enumerate(found or []):
                desc = L.to_desc(d)
                matches.append({"i": len(matches), "frame": f_index, "local": local, "text": L.describe(L.plain_words(desc)),
                                "context": ((desc.get("context") or {}).get("heading") or ""), "inFrame": bool(desc.get("frame"))})
        self.which = {"text": text, "kind": kind, "matches": matches}
        self.mode = "which" if matches else "browse"
        self.touch()
        if not matches:
            await self.broadcast()
        return self.which

    async def choose(self, i: int) -> dict:
        if not self.which or not (0 <= i < len(self.which["matches"])):
            raise BuildError("That match is not on the page any more. Look for it again.", "which", 409)
        m = self.which["matches"][i]
        page = self._page()
        frame = page.frames[m["frame"]] if m["frame"] < len(page.frames) else None
        if frame is None:
            raise BuildError("That match is not on the page any more. Look for it again.", "which", 409)
        desc = await frame.evaluate("i => window.__rrBuild ? window.__rrBuild.choose(i) : null", m["local"])
        self.which = None
        await self.broadcast({"mode": "browse"}, [f for f in page.frames if f is not frame])
        return await self._picked(frame, L.to_desc(desc))

    def _values(self, token: str) -> list[tuple[int, str, bool]]:
        """``token``'s value in every data row of the test's parameter sheet: ``[(row, value, enabled)]`` (the draft as it is now)."""
        sheet = self._meta.get("paramSheet")
        if not sheet:
            return []
        with self.doc.lock:
            editor = self.doc.editor
            real = next((s for s in editor.sheet_names() if s.upper() == sheet.upper()), None)
            rows = editor.rows(real) if real else []
        if not rows:
            return []
        headers = [cell_text(h).strip().upper() for h in rows[0]]
        if token.upper() not in headers:
            return []
        col = headers.index(token.upper())
        bln = headers.index("BLNEXECUTE") if "BLNEXECUTE" in headers else None
        out = []
        for i, r in enumerate(rows[1:], start=2):
            value = cell_text(r[col]).strip() if col < len(r) and r[col] is not None else ""
            enabled = bln is None or (bln < len(r) and cell_text(r[bln]).strip().upper() in ("Y", "YES", "TRUE", "1"))
            out.append((i, value, enabled))
        return out

    async def make_variable(self, role: str, token: str) -> dict:
        """Q11: the word ``role`` (``name`` / ``context``) of the pick becomes ``{token}``: the locator is rebuilt from the forms that carry the
        word and checked again on the live page - with the "Building with" row's value, and each other data row's (how many it finds)."""
        pick = self.pick
        if not pick:
            raise BuildError("Pick an element first.", "pick", 409)
        if role not in ("name", "context"):
            raise BuildError("Only the element's name or its container's heading can become a variable.", "role", 400)
        token = token.strip().strip("{}").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            raise BuildError("A variable name is letters, digits and _ (such as PLAN).", "token", 400)
        frame = self._picked_frame
        if frame is None or frame.is_detached():
            raise BuildError("The picked element's page has gone. Pick it again.", "pick", 409)
        variables = {**pick.get("variables", {}), role: token}
        desc = pick["desc"]
        word = next((w["text"] for w in pick["words"] if w["role"] == role), "")
        if not word:
            raise BuildError("That part of the description is not there to make a variable of.", "role", 400)
        per_row = await asyncio.to_thread(lambda: {t: self._values(t) for t in variables.values()})
        building = {t: next((v for r, v, _ in rows if r == self.data_row), "") for t, rows in per_row.items()}
        own = {"name": L.element_name(desc), "context": ((desc.get("context") or {}).get("heading") or "")}
        values = {t: own[r] for r, t in variables.items()}               # first: with the words as picked it must find exactly that element
        cands = L.candidates(desc, name_as="{" + variables["name"] + "}" if "name" in variables else "",
                             context_as="{" + variables["context"] + "}" if "context" in variables else "")
        if not cands:
            raise BuildError(f"“{word}” cannot drive the locator here (no text form of this element carries it).", "variable", 422)
        await self._check(frame, cands, values)
        choice = L.choose(cands)
        rows_checked = []
        if choice.primary is not None:
            tokens = list(variables.values())
            data_rows = sorted({r for t in tokens for r, _, en in per_row.get(t, []) if en})
            for r in data_rows:
                row_values = {t: next((v for rr, v, _ in per_row.get(t, []) if rr == r), "") for t in tokens}
                if any(not v for v in row_values.values()):
                    rows_checked.append({"row": r, "values": row_values, "matches": None})
                    continue
                probe = L.Candidate(choice.primary.findby, choice.primary.value, choice.primary.how)
                await self._check(frame, [probe], row_values)
                rows_checked.append({"row": r, "values": row_values, "matches": probe.count})
        words = L.plain_words(desc, variables)
        self.pick = {**pick, "words": words, "text": L.describe(words), "locator": choice.to_json(), "ok": choice.ok, "variables": variables,
                     "rows": rows_checked, "values": building, "newVariable": {t: not per_row.get(t) for t in variables.values()}}
        self.touch()
        await self.broadcast({"card": self._card()}, [frame])
        return self.pick

    def use_ops(self, row: int | None = None) -> list[dict]:
        """The edit that puts the pick on step ``row`` (default: the step it was picked for)."""
        p = self.pick
        row = row or (p or {}).get("for")
        if not p or not p.get("ok"):
            raise BuildError("Nothing usable is picked yet.", "pick", 409)
        if not row:
            raise BuildError("Choose the step this element is for (select it, then Pick).", "step", 409)
        loc = p["locator"]
        return [{"op": "update_step", "test": self.test_id, "row": int(row),
                 "set": {"findBy": loc["findBy"], "locator": loc["value"], "index": loc.get("index") or None, "backups": loc.get("backups") or []}}]

    async def use(self, row: int | None = None) -> list[dict]:
        ops = self.use_ops(row)
        applied = await asyncio.to_thread(self.doc.apply, ops, None)
        self.emit("log", level="info", message=f"step at row {ops[0]['row']} now finds {self.pick['text']}")
        self.touch()
        await self.broadcast({"card": None})
        return applied

    async def _picked_quietly(self, frame, desc: dict) -> None:
        try:
            await self._picked(frame, desc)
        except Exception as err:                                          # (the page's click must never see an error)
            self.emit("log", level="warning", message=f"the pick could not be worked out: {(str(err).splitlines() or [err])[0]}")

    # -- replays -----------------------------------------------------------------------------------------------------------------------
    def _write_draft(self) -> Path:
        """The workbook as it is being edited (the draft), for the engine to read."""
        with self.doc.lock:
            data, version = self.doc.editor.to_bytes(), self.doc.version
        target = self.folder / _SAFE.sub("_", self.name)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        self._loaded_version = version
        return target

    def _case_for(self, wb: Workbook) -> TestCase:
        cases = [c for c in wb.discover() if c.sheet.upper() == self.test_id.upper() and c.kind == "ui"]
        if cases:
            case = next((c for c in cases if c.param_row == self.data_row), cases[0])
            return case if self.data_row is None or case.param_row == self.data_row else dataclasses.replace(case, param_row=self.data_row)
        return TestCase(id=self.test_id, sheet=self._meta["sheet"], param_sheet=self._meta.get("paramSheet") or None, param_row=self.data_row or 2,
                        title=self.test_id)

    def _fresh_runner(self) -> tuple[TestRunner, Any, Any]:
        path = self._write_draft()
        wb = Workbook(path, environment=self.environment or None, secrets=workbook_secrets())
        case = self._case_for(wb)
        planned = [r for r, _, _ in wb.runtime(case).plan()]
        cfg = dataclasses.replace(self.cfg, screenshots=dataclasses.replace(self.cfg.screenshots, mode="on_failure"))
        runner = TestRunner(workbook=wb, case=case, browser_getter=self._get_browser, cfg=cfg, bus=self.bus, run_dir=self.folder,
                            selector_map=SelectorMap.load(self.cfg.path(self.cfg.selectors.map)), cancel=self._cancel, planned_rows=planned,
                            asker=self.asker, visible=not self.headless, pw=self._pw, side_effects="ask")
        runtime = runner.prepare_runtime()
        if runtime.blocked_reason:
            raise BuildError(runtime.blocked_reason, "blocked", 422)
        return runner, runtime, runtime.flow()

    def _reload(self) -> None:
        """Steps after the last replayed one read the workbook as it is now; what earlier steps saved carries over (like tests of one run)."""
        runner = self._runner
        if runner is None or self._loaded_version == self.doc.version:
            return
        runner._shared.update(runner.written if isinstance(runner.written, dict) else {})
        runner.workbook = Workbook(self._write_draft(), environment=self.environment or None, secrets=workbook_secrets())
        runtime = runner.prepare_runtime()
        runtime.loops.extend(frame["rows"][frame["i"]] for frame in self._loops)
        self._runtime, self._flow = runtime, runtime.flow()

    async def _get_browser(self):
        if self._browser is None or not self._browser.is_connected():
            raise RuntimeError("the build browser is closed")
        return _OverlayBrowser(self._browser, self)

    def run(self, kind: str, row: int | None = None, count: int | None = None) -> dict:
        """Start a replay in the background: ``to`` (steps 1..row, from the start), ``step`` (only that row), ``next`` (``count`` steps)."""
        if self.status == "closed" or self._browser is None:
            raise BuildError("The build browser is closed. Open it again.", "closed", 409)
        if self._task is not None and not self._task.done():
            raise BuildError("A replay is already going. Wait for it or stop it.", "busy", 409)
        if kind in ("to", "step") and not row:
            raise BuildError("Which step? Select it first.", "step", 400)
        self._launch(kind, row=row, count=count)
        return self.state()

    def _launch(self, kind: str, *, row: int | None = None, count: int | None = None) -> None:
        self._cancel.clear()
        self.replay = {"kind": kind, "row": row, "rowN": self._n_of(row), "count": count, "running": True, "results": [], "stopped": "",
                       "current": None, "started": time.time()}
        self.status = "running"
        self._task = asyncio.create_task(self._replay(kind, row, count))
        self.touch()

    async def _replay(self, kind: str, row: int | None, count: int | None) -> None:
        stopped = ""
        try:
            await self.broadcast({"card": None})
            if kind == "to" or self._runner is None:
                await self._drop_runner()
                runner, runtime, flow = await asyncio.to_thread(self._fresh_runner)
                runner.open_session(runtime)
                self._runner, self._runtime, self._flow, self._loops = runner, runtime, flow, []
                self.next_row = 2
            else:
                await asyncio.to_thread(self._reload)
            if kind == "to":
                stopped = await self._run_rows(first=2, until=row)
            elif kind == "step":
                stopped = await self._run_rows(first=row, count=1, only=True)
            else:
                stopped = await self._run_rows(first=self.next_row or 2, count=max(1, int(count or NEXT_DEFAULT)))
        except asyncio.CancelledError:
            stopped = "stopped"
            raise
        except BuildError as err:
            stopped = str(err)
        except Exception as err:                                          # a runner bug must not take the server down
            stopped = f"{type(err).__name__}: {err}"
        finally:
            if self.replay is not None:
                self.replay.update(running=False, stopped=stopped or self.replay.get("stopped", ""), current=None, ended=time.time())
            self.status = "closed" if self.status == "closed" else "ready"
            self.question = None
            self.recorder.resync()
            self.emit("build_session_replay_progress", kind=kind, done=len((self.replay or {}).get("results", [])), finished=True,
                      stopped=stopped)
            self.touch()
            if kind == "to":
                if self.status == "ready" and self._browser is not None and not self._open_pages():
                    await self._open_on_domain()              # the first step could not open the site (e.g. it was refused before it ran): still give a window
                await self._to_front()
            try:
                await self.broadcast()
            except Exception:
                pass

    async def _to_front(self) -> None:
        """A window opened by the Open step comes up in front of the app that asked for it (a headed window opened from a background
        process can otherwise appear behind it, and look as if nothing opened)."""
        if self.headless or self.status == "closed":
            return
        try:
            await self._page().bring_to_front()
        except Exception:
            pass

    async def _run_rows(self, *, first: int, until: int | None = None, count: int | None = None, only: bool = False) -> str:
        """The row loop of ``TestRunner.run`` for part of a test.  Returns why it stopped early ("" when it got where it was asked to)."""
        runner, runtime = self._runner, self._runtime
        session = runner.session
        row, done = first, 0
        while row <= runtime.total_rows:
            if self.cancelled():
                return "Stopped."
            if until is not None and row > until:
                break
            if count is not None and done >= count:
                break
            marker = runtime.method_at(row)
            if marker in MARKERS and not only:
                row = runner._after_marker(runtime, row, marker, self._flow, self._loops)
                continue
            step = runtime.prepare_row(row)
            if step is None or marker in MARKERS:
                if only:
                    return f"Row {row} is not a step that runs (empty, switched off, or a flow marker)."
                row += 1
                continue
            runner._seq += 1
            seq = runner._seq
            if step.method in ("BREAK", "STOP"):
                return f"{step.method} step at row {row}"
            session.next_alert = ""
            runner._branch, runner._iteration = None, None
            record = await runner._execute(runtime, step, seq)
            runner._seq = max(runner._seq, runner._call_last)
            done += 1
            n = self._n_of(row)
            self.replay["results"].append({"row": row, "n": n, "name": record.name or record.action, "action": record.action, "status": record.status,
                                           "error": record.error, "expected": record.expected, "actual": record.actual, "notes": list(record.notes)[:6],
                                           "screenshot": record.screenshot})
            self.cursor_row = row
            self._prefix = await asyncio.to_thread(self._signature, row)
            self._stale = None
            self.emit("build_session_replay_progress", row=row, step=n, status=record.status, done=len(self.replay["results"]))
            nxt = runner._next_row(runtime, row, step, record, self._flow, self._loops) if not only else row + 1
            self.next_row = nxt
            if session.infra:
                return f"The browser stopped working: {session.infra}"
            if session.block_error:
                return session.block_error
            if runner._no_window:
                return "No browser window is open any more."
            if runner._hard_stop:
                reason, runner._hard_stop = runner._hard_stop, ""
                return reason
            if runner._captcha_stop:
                reason, runner._captcha_stop = runner._captcha_stop, ""
                return reason
            if record.status == FAILED and not record.ignored_error:
                return f"Step {n or seq} failed: {record.error}"
            row = nxt
        return ""

    def stop(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        self.touch()

    # -- "earlier steps changed" ------------------------------------------------------------------------------------------------------------
    def _signature(self, upto: int) -> str:
        with self.doc.lock:
            editor = self.doc.editor
            sheet = next((s for s in editor.sheet_names() if s.upper() == self._meta.get("sheet", "").upper()), None)
            if sheet is None:
                raise BuildError(f"The sheet of {self.test_id} is gone.", "not_found", 404)
            rows = editor.rows(sheet)
            params = []
            if self._meta.get("paramSheet") and self.data_row:
                real = next((s for s in editor.sheet_names() if s.upper() == self._meta["paramSheet"].upper()), None)
                prow = editor.rows(real) if real else []
                params = prow[self.data_row - 1] if self.data_row - 1 < len(prow) else []
        return _signature(rows, upto, [self.environment, self.data_row, [cell_text(v) if v is not None else "" for v in params]])

    def stale(self) -> bool:
        """Did a step at or above the last replayed one change since it ran (or the data row / its values)?"""
        if self.cursor_row is None or not self._prefix or self._runner is None:
            return False
        key = (self.doc.version, self._prefix)
        if self._stale is not None and self._stale[:2] == key:
            return self._stale[2]
        try:
            changed = self._signature(self.cursor_row) != self._prefix
        except BuildError:
            changed = True                                            # (the test's sheet is gone)
        self._stale = (*key, changed)
        return changed

    # -- what the Build tab shows -------------------------------------------------------------------------------------------------------
    def state(self, since: int = 0) -> dict:
        running = self._task is not None and not self._task.done()
        return {"open": self.status != "closed", "workbook": self.name, "test": self.test_id, "dataRow": self.data_row, "environment": self.environment,
                "headless": self.headless, "status": "running" if running else self.status, "error": self.error, "mode": self.mode,
                "pickFor": self.pick_for, "pick": _public_pick(self.pick), "which": self.which, "question": self.question,
                "replay": self.replay, "cursor": {"row": self.cursor_row, "n": self._n_of(self.cursor_row)} if self.cursor_row else None,
                "next": {"row": self.next_row, "n": self._n_of(self.next_row)} if self.next_row and self._runner is not None else None,
                "stale": self.stale(), "version": self.version, "modelVersion": self.doc.version, "record": self.recorder.state(),
                "notice": self.notice, "log": [e for e in self.log if e["seq"] > since], "seq": self._seq}


def site_url(domain: str) -> str:
    """A Domain as the environment table holds it, as an address a browser opens (``example.com`` -> ``https://example.com``)."""
    domain = domain.strip()
    return domain if re.match(r"^[a-z][a-z0-9+.-]*://", domain, re.I) else "https://" + domain


def _public_pick(pick: dict | None) -> dict | None:
    """The pick as the Build tab sees it (the overlay's raw reading of the element stays here)."""
    if not pick:
        return None
    return {k: v for k, v in pick.items() if k not in ("desc", "similar")}


def _path_of(url: str) -> str:
    m = re.match(r"^[a-z]+://[^/]+(/[^?#]*)?", url or "")
    return (m.group(1) or "/") if m else ""


class SessionStore:
    """The build sessions of one server: one per workbook, at most ``MAX_SESSIONS`` open at once."""

    def __init__(self):
        self.sessions: dict[str, BuildSession] = {}

    def get(self, name: str) -> BuildSession | None:
        s = self.sessions.get(name.lower())
        return s if s is not None and s.status != "closed" else None

    def last(self, name: str) -> BuildSession | None:
        return self.sessions.get(name.lower())

    async def open(self, doc: BuildDocument, cfg: Config, folder: Path, *, test_id: str, data_row: int | None, environment: str,
                   headless: bool) -> BuildSession:
        current = self.get(doc.path.name)
        if current is not None:
            await current.switch(test_id, data_row, environment)
            return current
        if sum(1 for s in self.sessions.values() if s.status != "closed") >= MAX_SESSIONS:
            raise BuildError(f"{MAX_SESSIONS} build windows are open already. Close one first.", "too_many", 409)
        session = BuildSession(doc, cfg, folder, environment=environment, headless=headless)
        self.sessions[doc.path.name.lower()] = session
        try:
            await session.start(test_id, data_row)
        except BaseException:
            await session.close()
            raise
        return session

    async def close_all(self) -> None:
        for s in list(self.sessions.values()):
            await s.close()
