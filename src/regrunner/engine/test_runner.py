"""Runs ONE test (one action sheet x one parameter row) from first row to last.

Faithful to the legacy loop (``GUI_Test_Main.run``): rows are processed in order, tokens are
substituted per row, results are written back into the sheet state, failures do not stop the
test unless ``QuitBreakOnFailure=Y``.  Everything observable is emitted as an event.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from ..capture.review import ReviewCollector
from ..config import Config
from ..events import EventBus, now_iso
from ..reporting.results import StepRecord, TestResult
from ..selectors.resolve import SelectorMap
from ..workbook.model import BLANK_OK_METHODS, PreparedStep, TestCase, Workbook, is_blank, slug
from ..workbook.sheet import cell_text
from ..workbook.variables import INLINE_RE, MARKERS, VariablePool, evaluate_condition, parse_condition
from .actions import ASK_METHODS, NO_PAGE_METHODS, ActionError, StepContext, run_action
from .ask import AskCancelled, AskTimeout, AskUnavailable
from .failure_capture import capture_failure
from .outcome import FAILED, PASSED, Verdict, evaluate
from .patience import WaitNotice
from .session import BrowserSession
from .timing import Timing

NOT_RUN = "NOT_RUN"

UNSUPPORTED_PAGES = {"PDF", "SERVICE", "WORD", "OUTLOOK", "APPLICATION"}
MASK = "••••••"
MAX_CALL_DEPTH = 5                                                    # CALL_TEST inside a called test inside...: deeper than this is a mistake


def mask_text(text: str, hidden: list[str]) -> str:
    """Hide every secret of the run (typed in by a person, ``{SECRET:X}``; longest first) wherever ``text`` would be stored or shown."""
    for secret in hidden:
        text = text.replace(secret, MASK)
    return text


def mask_fields(fields: dict, hidden: list[str]) -> dict:
    """``mask_text`` over every text value of an event (review items quote URLs and console messages, which can carry what was typed)."""
    if not hidden:
        return fields
    return {k: (mask_text(v, hidden) if isinstance(v, str) else v) for k, v in fields.items()}


class _CallBus:
    """The event bus as a called test (CALL_TEST) sees it: its steps are reported as steps of the caller, numbered after the CALL_TEST step, so the
    run screen, progress and the report show one test.  Its own start / finish are not events of the run (the call_started / call_finished pair is)."""

    def __init__(self, parent: "TestRunner", offset: int):
        self.parent, self.offset, self.last = parent, offset, offset
        self.run_id = getattr(parent.bus, "run_id", "")

    def emit(self, type_: str, **fields):
        if type_ in ("test_started", "test_finished"):
            return {}
        if "test" in fields:
            fields["test"] = self.parent.case.id
        step = fields.get("step")
        if isinstance(step, int) and not isinstance(step, bool) and step > 0:
            fields["step"] = step + self.offset
            self.last = max(self.last, fields["step"])
        if "total_steps" in fields:
            fields["total_steps"] = self.parent.result.total_steps
        return self.parent.bus.emit(type_, **fields)

    def subscribe(self, listener):
        return self.parent.bus.subscribe(listener)


class FlowControl:
    """The IF / loop / CALL_TEST side of a test (CONTRACT.md 1.3), handed to the action handlers as ``ctx.flow``.  The handlers decide; the test
    runner's row loop does the jumping (``TestRunner.run``)."""

    def __init__(self, runner: "TestRunner", runtime):
        self.runner, self.runtime = runner, runtime

    async def branch(self, ctx: StepContext) -> None:
        text = ctx.value_text.strip()
        try:
            condition = parse_condition(text)
        except ValueError as err:
            ctx.out.hard = True
            raise ActionError(f"IF: {err}") from None
        runtime = self.runtime
        value_of = lambda name: runtime.value_of(name)[0]
        try:
            holds = evaluate_condition(condition, value_of)
        except ValueError as err:
            ctx.out.hard = True
            raise ActionError(f"IF {text}: {err}. The steps under it were not run.") from None
        self.runner._branch = holds
        left = value_of(condition.left)
        shown = "empty" if left is None or not left.strip() else ("set (secret)" if left in runtime.secret_values else repr(left))
        ctx.out.output = "true" if holds else "false"
        ctx.out.notes.append(f"{condition.left} is {shown}: {'true, the steps under the IF run' if holds else 'false, the steps under the IF were skipped'}")
        self.runner._emit("branch_taken", step=ctx.seq, row=ctx.step.row, condition=text, result=holds)

    async def loop(self, ctx: StepContext) -> None:
        try:
            rows = self.runtime.iteration_rows(ctx.value_text)
        except ValueError as err:
            ctx.out.hard = True
            raise ActionError(f"ITERATION_START: {err}") from None
        self.runner._iteration = (ctx.value_text.strip() or self.runtime.case.param_sheet or "", rows)
        ctx.out.output = str(len(rows))
        ctx.out.notes.append(f"repeats the steps up to ITERATION_END {len(rows)} time{'' if len(rows) == 1 else 's'} (one per data row)")

    async def call(self, ctx: StepContext) -> None:
        runner = self.runner
        target = ctx.value_text.strip()
        ctx.out.hard = True                                            # a call that could not run is never "not found and ignored"
        if not target:
            raise ActionError("CALL_TEST needs the test to run in Value (e.g. Login or Login#2)")
        try:
            case = runner.workbook.find_case(target)
        except ValueError as err:
            raise ActionError(f"CALL_TEST: {err}") from None
        stack = (*runner.call_stack, runner.base_id)
        if case.id in stack or case.id == runner.case.id:
            raise ActionError(f"CALL_TEST {case.id} would call a test that is already running it ({' > '.join(stack)}): it would never end")
        if len(stack) > MAX_CALL_DEPTH:
            raise ActionError(f"CALL_TEST {case.id}: calls go {len(stack)} deep ({' > '.join(stack)}); {MAX_CALL_DEPTH} is the most")
        runner._emit("call_started", step=ctx.seq, row=ctx.step.row, called=case.id, status="RUNNING")
        result = await runner.run_called(case, ctx.seq, stack)
        runner._emit("call_finished", step=ctx.seq, row=ctx.step.row, called=case.id, status=result.status)
        ctx.out.output = result.status
        ctx.out.notes.append(f"ran {case.id}: {result.passed} step(s) passed, {result.failed} failed, in {result.duration_s:g}s")
        if result.status != "PASSED":
            why = result.error or (f"{result.failed} step(s) failed" if result.failed else "")
            raise ActionError(f"The called test {case.id} ended {result.status}{': ' + why if why else ''}")
        ctx.out.hard = False


class TestRunner:
    __test__ = False

    def __init__(self, *, workbook: Workbook, case: TestCase, browser_getter: Callable[[], Awaitable],
                 cfg: Config, bus: EventBus, run_dir: Path, selector_map: SelectorMap,
                 cancel: asyncio.Event, planned_rows: list[int], worker: int = 0, harvest=None,
                 devices: dict | None = None, attempt: int = 1, throttle=None, asker=None, visible: bool = False, shared: dict | None = None,
                 pool: VariablePool | None = None, pw=None, call_stack: tuple = (), base_id: str = ""):
        self.workbook, self.case, self.cfg, self.bus = workbook, case, cfg, bus
        self.run_dir, self.selector_map, self.cancel = run_dir, selector_map, cancel
        self.planned_rows = planned_rows
        self.worker, self.harvest, self.attempt = worker, harvest, attempt
        self.test_dir = run_dir / "tests" / case.slug
        self.shots_dir = self.test_dir / "screenshots"
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self._element_step = False
        self._full_shots = 0                                           # whole-page screenshots taken (failure_capture.full_page_max_per_test)
        self._dom_saved = 0                                            # failed steps whose HTML was kept (failure_capture.dom_max_per_test)
        self._secrets: set[str] = set()                                # every secret of the run (the runtime's, once it exists): masked in all that is shown
        self.review = ReviewCollector(
            case.id, lambda type_, **f: bus.emit(type_, **mask_fields(f, self.hidden())),
            ignore_urls=cfg.review.ignore_url_patterns, ignore_messages=cfg.review.ignore_message_patterns,
            max_items=cfg.review.max_items_per_test)
        self.result = TestResult(id=case.id, title=case.title, sheet=case.sheet, scenario=case.scenario,
                                 description=case.description, total_steps=len(planned_rows), attempt=attempt)
        self.session: BrowserSession | None = None
        self.written: dict = {}                                   # parameter cells this test wrote (see TestRuntime.written)
        self._devices = devices or {}
        self._throttle = throttle
        self._asker = asker
        self._visible = visible                                   # a person can see this test's browser (run --headed, or the window opened for a captcha)
        self._shared = shared if shared is not None else {}       # parameter cells other tests of the run wrote / a person supplied
        self._captcha_stop = ""                                   # why a captcha ended this test ("" while none has)
        self._no_window = False                                   # a step found no open browser window: nothing after it can run
        self._browser_getter = browser_getter
        self._settled = True                                      # the last failed step failed on a page that had finished (not one still loading)
        self.notice = WaitNotice(bus, case.id, worker)            # when this test waits on purpose, the run screen says why
        self.timing = Timing()                                    # where its time goes (engine/timing.py; recorded when measure.timing)
        self.pool = pool                                          # the run's shared variables (None: the test has a pool of its own)
        self.call_stack = call_stack                              # the tests that called this one (CALL_TEST), outermost first
        self.base_id = base_id or case.id                         # the test's own id (a called test's case.id also names its caller)
        self._call_last = 0                                       # the last step number a called test used
        self._flowctl: FlowControl | None = None
        self._pw = pw                                             # Playwright, for an API test that CALL_TEST runs
        self._seq = 0                                             # the last step number given out
        self._branch: bool | None = None                          # what the IF step that just ran decided
        self._iteration: tuple[str, list] | None = None           # the data rows of the ITERATION_START that just ran
        self._called_steps: list[StepRecord] = []                 # a called test's steps, reported after the CALL_TEST step
        self._call_stop: tuple[str, str] = ("", "")               # (infra | blocked | captcha, why) when a called test stopped for a reason the caller shares
        self._branch_skipped = 0                                  # planned steps an IF (or a loop with nothing to repeat) left out

    def hidden(self) -> list[str]:
        """The secrets to mask, longest first (short ones would mask ordinary words)."""
        return sorted((v for v in self._secrets if len(v) >= 4), key=len, reverse=True)

    # -- helpers ------------------------------------------------------------------------------------
    def _emit(self, type_: str, **fields):
        return self.bus.emit(type_, test=self.case.id, **fields)

    async def _element_box(self, ctx: StepContext) -> dict[str, float] | None:
        """Where the element this step acted on sits in the screenshot, as % of the viewport (or None)."""
        handle, session = ctx.out.handle, self.session
        if handle is None or session is None or not session.is_open or session.pending_dialog is not None:
            return None
        try:
            box = await asyncio.wait_for(handle.bounding_box(), timeout=0.5)
            view = session.page.viewport_size
        except Exception:
            return None
        if not box or not view or not view.get("width") or not view.get("height"):
            return None
        vw, vh = view["width"], view["height"]
        x0, y0 = max(box["x"], 0.0), max(box["y"], 0.0)
        x1, y1 = min(box["x"] + box["width"], vw), min(box["y"] + box["height"], vh)
        if x1 - x0 < 2 or y1 - y0 < 2:                          # off-screen or invisible
            return None
        pct = lambda v, total: round(100.0 * v / total, 2)
        return {"x": pct(x0, vw), "y": pct(y0, vh), "w": pct(x1 - x0, vw), "h": pct(y1 - y0, vh)}

    async def _screenshot(self, seq: int, row: int, name: str, failed: bool,
                          box: dict[str, float] | None = None) -> str | None:
        mode = self.cfg.screenshots.mode
        if mode == "off" or (mode == "on_failure" and not failed):
            return None
        session = self.session
        if session is None or not session.is_open or session.pending_dialog is not None:     # an open dialog blocks the page (it is answered 1.5 s after it opened)
            return None
        try:
            data = await session.page.screenshot(
                type="jpeg", quality=self.cfg.screenshots.quality, full_page=self.cfg.screenshots.full_page,
                timeout=5000, animations="disabled", caret="hide")
        except Exception as err:
            reason = (str(err).strip().splitlines() or [type(err).__name__])[0][:200]
            self._emit("log", level="warning", message=f"{self.case.id} step {seq}: screenshot not taken ({reason})")
            return None
        path = self.shots_dir / f"{seq:04d}_r{row}_{slug(name)[:40]}.jpg"
        path.write_bytes(data)
        rel = path.relative_to(self.run_dir).as_posix()
        self._emit("screenshot_saved", step=seq, path=rel, kind="step", failed=failed, box=box)
        return rel

    async def _full_page_screenshot(self, seq: int, row: int, name: str) -> str | None:
        """The whole page of a failed step (below the fold included), next to the window-sized screenshot.  Never raises."""
        cfg, session = self.cfg, self.session
        if (not cfg.failure_capture.full_page_screenshot or cfg.screenshots.mode == "off" or self.cancel.is_set() or session is None or not session.is_open
                or self._full_shots >= cfg.failure_capture.full_page_max_per_test):
            return None
        try:
            data = await session.page.screenshot(type="jpeg", quality=cfg.screenshots.quality, full_page=True, timeout=8000, animations="disabled", caret="hide")
        except Exception:
            return None
        path = self.shots_dir / f"{seq:04d}_r{row}_{slug(name)[:40]}_full.jpg"
        try:
            path.write_bytes(data)
        except OSError:
            return None
        self._full_shots += 1
        return path.relative_to(self.run_dir).as_posix()

    # -- main loop ---------------------------------------------------------------------------------
    async def run(self) -> TestResult:
        case, result = self.case, self.result
        started = time.perf_counter()
        result.started_at = now_iso()
        self._emit("test_started", title=case.title, total_steps=result.total_steps, worker=self.worker,
                   attempt=self.attempt)
        runtime = self.workbook.runtime(case, shared=self._shared, pool=self.pool)
        self._secrets = runtime.secret_values
        self.pool = runtime.pool                                  # (the run's, or the runtime's own when the test runs by itself)
        self._flowctl = FlowControl(self, runtime)
        self.written = runtime.written
        self.session = BrowserSession(self._browser_getter, self.cfg, self.review, case.id, runtime.environment,
                                      devices=self._devices, throttle=self._throttle, cancel=self.cancel)
        self.session.notice = self.notice
        self.session.timing = self.timing
        method_col = runtime.columns.get("METHOD")
        later = {row: self.planned_rows[i + 1:] for i, row in enumerate(self.planned_rows)}

        def next_method(row: int) -> str:
            """The action of the next planned step, looking past Wait rows (a dialog is often answered after a Wait)."""
            for nxt in later.get(row, []) if method_col else []:
                try:
                    method = cell_text(runtime.sheet.read(nxt, method_col)).strip().upper()
                except Exception:
                    return ""
                if method != "WAIT":
                    return method
            return ""
        stop_reason = ""
        try:
            if runtime.blocked_reason:
                result.status, result.error = "ERROR", runtime.blocked_reason
                return result
            blocked = ""
            quit_on_failure = runtime.global_flag("QuitBreakOnFailure")
            give_up_after, in_a_row = self.cfg.runner.stop_after_failed_steps, 0      # element steps that failed one after another
            off: dict[int, tuple[str, str]] = {}                 # rows with a step but an empty blnExecute, for the hint on a failed step
            closer: tuple[int, str] | None = None                # the last Close step (which window it closed is what left nothing open)
            flow = runtime.flow()
            loops: list[dict] = []                               # the loops the test is in, innermost last: {start, end, sheet, rows, i}
            row = 2
            while row <= runtime.total_rows:
                if self.cancel.is_set():
                    result.status, stop_reason = "CANCELLED", "cancelled"
                    break
                marker = runtime.method_at(row)
                if marker in MARKERS:                            # ELSE / END_IF / ITERATION_END: where to go next, not a step
                    row = self._after_marker(runtime, row, marker, flow, loops)
                    continue
                step = runtime.prepare_row(row)
                if step is None:
                    if (empty := runtime.empty_flag_step(row)) is not None:
                        off[row] = empty
                    row += 1
                    continue
                self._seq += 1
                seq = self._seq
                if step.method in ("BREAK", "STOP"):
                    stop_reason = f"{step.method} step at row {row}"
                    break
                upcoming = next_method(row)
                self.session.next_alert = upcoming if upcoming in ("ALERT_OK", "ALERT_CANCEL", "ALERT_TEXT_OUT") else ""   # a dialog this step opens is answered as that step says
                self._branch, self._iteration = None, None
                record = await self._execute(runtime, step, seq, off)
                self._seq = max(self._seq, self._call_last)       # a called test's steps took the numbers after this one
                if self.session.infra or self._call_stop[0] == "infra":
                    result.infra = self.session.infra or self._call_stop[1]      # the machine, not the site: this attempt says nothing about the application
                    stop_reason = "the browser stopped working"
                    break
                if self._call_stop[0] == "blocked":
                    result.blocked = blocked = self._call_stop[1]
                    stop_reason = "blocked by the site"
                    break
                if self._call_stop[0] == "captcha":
                    self._captcha_stop = self._call_stop[1]
                if step.method == "CLOSE":
                    closer = (seq, step.name or step.method)
                if record.status == PASSED:
                    result.passed += 1
                else:
                    result.failed += 1
                if step.method == "OPEN" and self.session.load_error and not self.session.loaded_once:
                    blocked = self.session.load_error            # nothing ever loaded: the rest could only fail, slowly
                    stop_reason = "the site did not load"
                    if self.session.load_status in self.cfg.runner.block_statuses:
                        result.blocked = blocked                 # the WAF, not the application: the runner cools down and tries again
                    break
                if self.session.block_error:
                    result.blocked = blocked = self.session.block_error      # a step's own call was refused: nothing after it can be trusted
                    stop_reason = "blocked by the site"
                    break
                if self._no_window:
                    closed = f' (step {closer[0]} "{closer[1]}" closed the last one)' if closer else " (no Open step ran first, or the window was closed)"
                    stop_reason = f"No browser window is open any more{closed}, so the steps after step {seq} could not run"
                    break
                if self._captcha_stop:
                    result.captcha = self._captcha_stop                       # nothing behind a captcha can be trusted: stop, do not "pass" the rest
                    stop_reason = "a captcha needs a person"
                    break
                if record.status == FAILED and quit_on_failure:
                    stop_reason = "QuitBreakOnFailure: stopped after first failure"
                    break
                if give_up_after and self._element_step:                  # Wait / Switch / key presses say nothing about where the page is
                    if record.status == FAILED and record.error != "Comparison Failed":
                        if self._settled:
                            in_a_row += 1                                 # could not find or use its element on a page that had finished loading
                    elif not record.ignored_error:
                        in_a_row = 0                                      # it worked, or it read the element and only the text differed: the page is where the test expects
                    if in_a_row >= give_up_after:
                        stop_reason = (f'Stopped after {in_a_row} steps in a row could not find or use their element (the last: step {seq} "{record.name}", row {step.row}): '
                                       "the page is probably not where the test expects, so the steps after it were not run. "
                                       "(runner.stop_after_failed_steps in config.yaml; 0 = never stop)")
                        break
                row = self._next_row(runtime, row, step, record, flow, loops)
            executed = result.passed + result.failed
            result.skipped = self._branch_skipped + (max(0, result.total_steps - executed - self._branch_skipped) if stop_reason else 0)
            if result.status != "CANCELLED":
                if result.infra:
                    result.status, result.error = NOT_RUN, (f"Not run: {result.infra}. This says nothing about the application: the test is run again "
                                                            "from the start.")
                elif blocked:
                    result.status, result.error = "ERROR", (blocked if result.blocked == blocked and blocked.startswith("Blocked") else f"The site did not load. {blocked}")
                elif result.captcha:
                    result.status, result.error = "ERROR", result.captcha
                elif executed == 0:
                    result.status, result.error = "ERROR", "No executable steps (check blnExecute/parameter flags)"
                else:
                    result.status = "FAILED" if result.failed else "PASSED"
            if stop_reason:
                result.error = result.error or stop_reason
        except asyncio.CancelledError:
            result.status, result.error = "ERROR", result.error or "Test was cancelled (time limit or shutdown)"
            raise
        except Exception as err:                                  # a runner bug must not take the run down
            result.status, result.error = "ERROR", f"{type(err).__name__}: {err}"
        finally:
            await self._finish(started)
        return result

    # -- IF / loops: where the row loop goes next -------------------------------------------------------------
    def _skip_rows(self, runtime, first: int, stop: int, why: str) -> None:
        """Rows ``first`` .. ``stop - 1`` do not run (the IF above them was false...): each step among them is reported as skipped."""
        for r in range(first, stop):
            if runtime.method_at(r) in MARKERS:
                continue
            step = runtime.prepare_row(r)
            if step is None:
                continue
            self._branch_skipped += 1
            self._emit("step_skipped", step=None, total_steps=self.result.total_steps, row=r, name=step.name, action=step.method, reason=why)

    def _begin_iteration(self, frame: dict, row: int) -> None:
        self._emit("iteration_started", step=frame["seq"], row=row, sheet=frame["sheet"], iteration=frame["i"] + 1, of=len(frame["rows"]))

    def _next_row(self, runtime, row: int, step: PreparedStep, record: StepRecord, flow, loops: list[dict]) -> int:
        """The row after ``step``: past the IF's steps when it was false (or could not be decided), into / past a loop."""
        if step.method == "IF" and row in flow.end_of and self._branch is not True:
            target = flow.else_of.get(row, flow.end_of[row])
            self._skip_rows(runtime, row + 1, target, f"IF at row {row} was {'false' if self._branch is False else 'not decided'}")
            return target + 1
        if step.method == "ITERATION_START" and row in flow.end_of:
            sheet, rows = self._iteration or ("", [])
            if record.status != PASSED or not rows:
                self._skip_rows(runtime, row + 1, flow.end_of[row], f"the loop at row {row} has no data row" if record.status == PASSED
                                else f"the loop at row {row} could not start")
                return flow.end_of[row] + 1
            frame = {"start": row, "end": flow.end_of[row], "sheet": sheet, "rows": rows, "i": 0, "seq": record.seq}
            loops.append(frame)
            runtime.loops.append(rows[0])
            self._begin_iteration(frame, row)
        return row + 1

    def _after_marker(self, runtime, row: int, marker: str, flow, loops: list[dict]) -> int:
        if marker == "ELSE":                                           # reached from the IF's own steps: the ELSE side does not run
            end = flow.end_of.get(row, row)
            self._skip_rows(runtime, row + 1, end, f"the IF above row {row} was true")
            return end + 1
        if marker == "ITERATION_END" and loops and loops[-1]["end"] == row:
            frame = loops[-1]
            frame["i"] += 1
            if frame["i"] < len(frame["rows"]):
                runtime.loops[-1] = frame["rows"][frame["i"]]
                self._begin_iteration(frame, frame["start"])
                return frame["start"] + 1
            loops.pop()
            runtime.loops.pop()
        return row + 1

    # -- CALL_TEST -------------------------------------------------------------------------------------------------
    async def run_called(self, case: TestCase, seq: int, stack: tuple) -> TestResult:
        """Run ``case`` to the end for a CALL_TEST step numbered ``seq``: in a browser context of its own (none for an API test), sharing this run's
        variables, secrets and parameter cells.  Its steps are reported as this test's steps after ``seq``."""
        bus = _CallBus(self, seq)
        called = dataclasses.replace(case, id=f"{self.case.id} > {case.id}")      # (its own evidence folder; its events are re-labelled by the bus)
        if case.kind == "api":
            from .api_runner import ApiTestRunner
            if self._pw is None:
                raise ActionError(f"CALL_TEST {case.id}: an API test can only be called in a full run")
            planned = 1
            self.result.total_steps += planned
            child = ApiTestRunner(workbook=self.workbook, case=called, pw=self._pw, cfg=self.cfg, bus=bus, run_dir=self.run_dir, cancel=self.cancel,
                                  planned=planned, shared=self._shared, worker=self.worker, attempt=self.attempt, throttle=self._throttle, asker=self._asker)
        else:
            planned_rows = [r for r, _, _ in self.workbook.runtime(case).plan()]          # (planned on a pool of its own: planning writes nothing real)
            self.result.total_steps += len(planned_rows)
            child = TestRunner(workbook=self.workbook, case=called, browser_getter=self._browser_getter, cfg=self.cfg, bus=bus, run_dir=self.run_dir,
                               selector_map=self.selector_map, cancel=self.cancel, planned_rows=planned_rows, worker=self.worker, harvest=self.harvest,
                               devices=self._devices, attempt=self.attempt, throttle=self._throttle, asker=self._asker, visible=self._visible,
                               shared=self._shared, pool=self.pool, pw=self._pw, call_stack=stack, base_id=case.id)
        res = await child.run()
        written = child.written if isinstance(child.written, dict) else {}
        self._shared.update(written)
        if case.kind == "api":                                         # what the API test filled in lands in the pool under its column's name
            pool = self.pool
            for (sheet, _row, col), value in written.items():
                data = self.workbook.data.sheet(sheet)
                name = data.header_names.get(col) if data is not None else None
                if name and not is_blank(value):
                    pool.set(name, value, case.id)
        self._call_last = bus.last
        self.result.passed += res.passed
        self.result.failed += res.failed
        self._branch_skipped += res.skipped
        self.result.variables.extend(res.variables)
        for record in res.steps:
            record.seq += seq
            record.notes = [f"in {case.id} (CALL_TEST)", *record.notes]
        self._called_steps = list(res.steps)
        if res.infra:
            self._call_stop = ("infra", res.infra)
        elif res.blocked:
            self._call_stop = ("blocked", res.blocked)
        elif res.captcha:
            self._call_stop = ("captcha", res.captcha)
        return res

    def _write_network_log(self) -> None:
        """``tests/<id>/network.jsonl``: every first-party XHR/fetch call of the test (method, path, status, ms, step)."""
        calls = self.session.network if self.session is not None else []
        if not calls:
            return
        try:
            with (self.test_dir / "network.jsonl").open("w", encoding="utf-8") as fh:
                hidden = self.hidden()
                for call in calls:
                    fh.write(mask_text(json.dumps(call, ensure_ascii=False), hidden) + "\n")
        except OSError:
            pass

    async def _finish(self, started: float) -> None:
        result = self.result
        self.notice.end_all()
        if self.session is not None:
            await self.session.close()
            self._write_network_log()
        result.review = list(self.review.items)
        result.ended_at = now_iso()
        result.duration_s = round(time.perf_counter() - started, 2)
        if self.cfg.measure.timing:
            result.timing = self.timing.summary(result.duration_s)
        if self.session is not None:
            result.third_party = [{"host": host, **seen} for host, seen in sorted(self.session.third_party.items(), key=lambda kv: (-kv[1]["requests"], kv[0]))]
            result.site_version = self.session.site_version()
        self._emit("test_finished", status=result.status, passed=result.passed, failed=result.failed,
                   skipped=result.skipped, duration_s=result.duration_s, error=result.error,
                   review_counts=[item["count"] for item in self.review.items])

    @staticmethod
    def _skipped_hint(off: dict[int, tuple[str, str]], row: int, window: int = 10) -> str:
        """For a failed step: steps just above it that did not run because their blnExecute cell is empty (a login step someone forgot to switch on)."""
        near = [(r, what, name) for r, (what, name) in sorted(off.items()) if row - window <= r < row]
        if not near:
            return ""
        first, last = near[0][0], near[-1][0]
        rows = f"row {first}" if first == last else f"rows {first}-{last}" if last - first == len(near) - 1 else "rows " + ", ".join(str(n[0]) for n in near)
        what = "; ".join(f"{name or 'step'} ({method})" for _, method, name in near[:4]) + (" ..." if len(near) > 4 else "")
        return f"Not run, just above this step: {rows} - {what} - because blnExecute (column A) is empty. If they should run, put Y there."

    async def _fill_blank_params(self, runtime, step: PreparedStep, seq: int) -> tuple[PreparedStep, str]:
        """A step names a parameter whose cell is empty (nothing filled it in): the legacy runner typed the parameter's *name* into the page.
        Ask a person for the value when one can answer (it is used for this run only); otherwise return why the step cannot run."""
        for token in dict.fromkeys(t for _, t in step.blank_params):
            cell = runtime.param_cell(token)
            sets = [w for w in runtime.writers.get(token.upper(), []) if w != self.case.sheet]
            who = f" {' / '.join(sets)} fills it in when it runs and has not (yet) in this test." if sets else ""
            why = f"Parameter {token} is empty: its cell {cell} has no value and no step of this test has set it.{who}"
            asker = self._asker
            if asker is None or not asker.available:
                return step, f"{why} Fill the cell in, or start the run from the web UI or a terminal to be asked for it."
            question = f"{token} is empty for {self.case.id} (cell {cell}). Type the value to use in this run; the workbook is not changed.{who}"
            try:
                with self.timing.span("wait", "ask_user"):
                    answer = (await asker.ask(self.case.id, seq, question, timeout_s=self.cfg.ask.timeout_s)).strip()
            except AskUnavailable as err:
                return step, f"{why} {err}"
            except AskTimeout as err:
                return step, f"{why} Nobody answered: {err}"
            except AskCancelled:
                return step, "The run was cancelled while waiting for a value."
            if not answer:
                return step, f"{why} No value was given."
            runtime.provide(token, answer)
            self.result.variables.append({"name": token, "value": answer, "stored": answer, "cell": cell, "seq": seq, "row": step.row,
                                          "step": step.name, "by_hand": True})
            self._emit("variable_set", step=seq, name=token, value=answer, cell=cell, by_hand=True)
            self._emit("log", level="info", message=f"{self.case.id}: {token} was given by hand for this run ({cell})")
        again = runtime.prepare_row(step.row)                 # the row again, now that the parameter has a value
        return (again if again is not None else step), ""

    async def _perform(self, runtime, step: PreparedStep, seq: int) -> tuple[StepContext, bool]:
        """Do the step's action.  Returns its context (the outcome) and whether it acts on an element."""
        cfg = self.cfg
        blank_error = ""
        if step.blank_params and step.method not in BLANK_OK_METHODS:
            step, blank_error = await self._fill_blank_params(runtime, step, seq)
        ctx = StepContext(step=step, session=self.session, cfg=cfg, selector_map=self.selector_map,
                          review=self.review, test_dir=self.test_dir, harvest=self.harvest, test_id=self.case.id, seq=seq,
                          asker=self._asker, secret_values=runtime.secret_values, notice=self.notice, flow=self._flowctl)
        spec_element = step.method not in NO_PAGE_METHODS
        variable_error = self._variable_error(runtime, step) if not blank_error else ""
        if blank_error or variable_error:
            ctx.out.error, ctx.out.hard = blank_error or variable_error, True    # the step does not run: typing a variable's name would only be a wrong value
        elif step.page in UNSUPPORTED_PAGES:
            ctx.out.error = f"Page type {step.page} is not supported by regrunner (web UI steps only)"
        else:
            try:
                cap = cfg.runner.step_hard_cap_s + (float(step.timeout or cfg.ask.timeout_s) if step.method in ASK_METHODS else 0)   # a person may take a while
                spec = await asyncio.wait_for(run_action(ctx), timeout=cap)
                spec_element = spec.element
            except asyncio.TimeoutError:
                ctx.out.error = f"Step exceeded the {cfg.runner.step_hard_cap_s}s hard limit"
        ctx.out.notes.extend(self.notice.take_notes())           # the waits this step went through (a login code, a slow page) stay on it
        return ctx, spec_element

    @staticmethod
    def _variable_error(runtime, step: PreparedStep) -> str:
        """Why a step cannot run because of its ``{NAME}``s (CONTRACT.md 1.2): a template placeholder nobody mapped, a name nobody has a value for."""
        if step.unmapped:
            names = ", ".join("{?" + n + "}" for n in dict.fromkeys(step.unmapped))
            return f"{names} is a placeholder from a template that was never matched to a variable: choose the variable in the Build tab."
        if not step.missing_vars:
            return ""
        secrets = [n.split(":", 1)[1] for n in dict.fromkeys(step.missing_vars) if n.startswith("SECRET:")]
        names = [n for n in dict.fromkeys(step.missing_vars) if not n.startswith("SECRET:")]
        env = runtime.environment or "<ENV>"
        parts = []
        if names:
            parts.append(f"variable {' and '.join(names)} {'has' if len(names) == 1 else 'have'} no value: no Params column, no earlier step or test and "
                         f"no environment value ({runtime.environment or 'no environment'}) gives {'it' if len(names) == 1 else 'them'} one")
        for name in secrets:
            parts.append(f"secret {name} is not in secrets.env (RR_SECRET_{env}_{name} or RR_SECRET_{name})")
        return "The step was not run: " + "; ".join(parts) + "."

    def _captcha_cause(self, environment: str) -> str:
        cookie = self.cfg.captcha_bypass.cookie_name
        if self.session.bypass_sent:
            return (f"The {cookie} bypass cookie was sent, but the site showed the captcha anyway: the bypass does not work for this environment "
                    "(wrong or expired token, or the site does not accept it here).")
        return f"No {cookie} is configured for {environment or 'this environment'}, so a captcha is expected: set RECAPTCHA_BYPASS_TOKEN_{environment or '<ENV>'} in secrets.env."

    async def _captcha_gone(self) -> bool:
        return await self.session.find_captcha() is None

    async def _captcha_gate(self, runtime, step: PreparedStep, seq: int) -> tuple[str, str]:
        """Is a captcha challenge in the way of this test?  Returns (why the test cannot go on, "" if it can; a note for the step when a person
        solved one).  With a person who can see the browser the test waits for them; otherwise it stops: nothing behind a captcha is a result."""
        with self.timing.span("runner", "captcha_check"):
            hit = await self.session.find_captcha()
        if hit is None:
            return "", ""
        cfg, asker = self.cfg, self._asker
        head = f'A captcha stopped the test after step {seq} "{step.name or step.method}": {hit.asks()}.'
        cause = self._captcha_cause(runtime.environment)
        somebody = asker is not None and asker.available and cfg.captcha.solve == "ask"
        self._emit("captcha_detected", step=seq, kind=hit.kind, prompt=hit.prompt, waiting=bool(self._visible and somebody))
        if not (self._visible and somebody):
            hand = (" Started from the web UI or a terminal, a browser window opens so you can solve it by hand."
                    if cfg.captcha.solve == "ask" and not somebody and not self._visible else "")
            return f"{head} {cause} The test was stopped here and the steps after it were not run.{hand}", ""
        try:
            await hit.page.bring_to_front()
        except Exception:
            pass
        question = f"{hit.asks()}. Solve it in the browser window that opened; the test carries on by itself."
        self._emit("log", level="warning", message=f"{self.case.id}: a captcha needs a person. {question}")
        t0 = time.monotonic()
        try:
            with self.timing.span("wait", "captcha_by_hand"):
                answer = await asker.ask(self.case.id, seq, question, kind="captcha", timeout_s=cfg.captcha.timeout_s, until=self._captcha_gone)
        except AskTimeout:
            return f"{head} {cause} Nobody solved it within {cfg.captcha.timeout_s:g} s, so the test was stopped here.", ""
        except AskCancelled:
            return "", ""                                              # the run is being cancelled: the loop notices
        if answer.strip().lower() == "skip":
            return f"{head} {cause} It was skipped, so the test was stopped here.", ""
        await asyncio.sleep(1.0)                                       # the page acts on the solved captcha (submits, navigates) before the next step looks
        return "", f"a captcha ({hit.kind}) was solved by hand; waited {time.monotonic() - t0:.0f}s"

    @staticmethod
    def _output_of(runtime, step: PreparedStep, ctx: StepContext):
        """What the step "got": what its action captured, and - like the legacy runner (``dWV['OV'] = OUTPUT_VALUE``) - for a step that captured nothing
        (a ``Wait``, a click) what its own Output_Value cell holds.  Sheets lean on it: ``Verify points to earn`` is a ``Wait`` row whose Output_Value is a
        formula over the previous row's capture, compared with its Expected_Value.  A cell that only names a parameter (where an output is to be stored)
        is not a value."""
        if ctx.out.output is not None:
            return ctx.out.output
        cell = step.values.get("OUTPUT_VALUE")
        if is_blank(cell) or cell_text(cell).strip().upper() in runtime.params or INLINE_RE.fullmatch(cell_text(cell).strip()):
            return None
        return cell

    async def _diagnose(self, ctx: StepContext, step: PreparedStep, seq: int, verdict: Verdict, detail: str, stopped: str, mask, actual: str = "") -> dict | None:
        """Why a step failed, read from the page while it is still as the step left it (see ``failure_capture``).  Never raises."""
        cfg = self.cfg.failure_capture
        read_nothing = verdict.error == "Comparison Failed" and ctx.out.target is not None and not actual.strip()       # the element was found and gave no text
        if (not cfg.enabled or stopped or self.cancel.is_set() or ctx.out.hard or (verdict.error == "Comparison Failed" and not read_nothing)
                or ctx.out.error.startswith("No open browser window") or self.session is None):
            return None
        want_dom = cfg.dom_snapshot and self._dom_saved < cfg.dom_max_per_test
        try:
            diagnosis = await capture_failure(ctx, error=verdict.error, detail=detail, run_dir=self.run_dir, mask=mask,
                                              dom_dir=self.test_dir / "dom" if want_dom else None,
                                              stem=f"{seq:04d}_r{step.row}_{slug(step.name or step.method)[:40]}")
        except Exception:
            return None
        if diagnosis and diagnosis.get("dom"):
            self._dom_saved += 1
        return diagnosis

    async def _failed_on_settled_page(self, ctx: StepContext) -> bool:
        """Did the step fail on a page that had finished loading?  (Only those count towards ``runner.stop_after_failed_steps``: a failure while
        the page was still working says nothing about where the page is.)"""
        if not self.cfg.patience.enabled:
            return True
        if ctx.last_wait is not None and ctx.last_wait.on_settled_page:
            return True
        try:
            return not (await asyncio.wait_for(self.session.activity(), 10)).working
        except Exception:
            return True

    def _not_run_step(self, step: PreparedStep, seq: int, ctx: StepContext, t0: float, started_at: str) -> StepRecord:
        """The step during which the browser went away: recorded as not run (no verdict), with what the machine did."""
        why = f"Not run: {self.session.infra}"
        record = StepRecord(seq=seq, row=step.row, name=step.name, action=step.method, status=NOT_RUN, error=why, notes=ctx.out.notes,
                            started_at=started_at, ended_at=now_iso(), duration_ms=int((time.perf_counter() - t0) * 1000), detail=ctx.out.detail,
                            timing=self.timing.step_ended() if self.cfg.measure.timing else None)
        self.result.steps.append(record)
        self._emit("step_failed", step=seq, total_steps=self.result.total_steps, row=step.row, name=step.name, action=step.method, status=NOT_RUN,
                   duration_ms=record.duration_ms, expected="", actual="", error=why, locator="", notes=record.notes, screenshot=None, sets=[])
        return record

    async def _execute(self, runtime, step: PreparedStep, seq: int, off: dict[int, tuple[str, str]] | None = None) -> StepRecord:
        cfg = self.cfg
        self.review.step, self.review.step_name = seq, step.name or step.method
        self.notice.step = seq
        self.session.mark_step()
        self._emit("step_started", step=seq, total_steps=self.result.total_steps, row=step.row,
                   name=step.name, action=step.method)
        started_at, t0 = now_iso(), time.perf_counter()
        self.timing.step_started()
        ctx, spec_element = await self._perform(runtime, step, seq)
        self._element_step = bool(spec_element)                        # read by the loop: does this step say anything about where the page is?
        step = ctx.step                                                # (the row again when a parameter was supplied by hand)
        if await self.session.check_infra(ctx.out.error):
            return self._not_run_step(step, seq, ctx, t0, started_at)  # the browser went away: no verdict, the test is run again from the start
        if ctx.out.error.startswith("No open browser window"):
            self._no_window = True                                     # even when the step swallows its errors: with no window nothing can be checked
        stop, solved = "", ""
        on_page = step.method not in NO_PAGE_METHODS                    # (variables and flow never look at the page: no captcha check, no screenshot)
        if cfg.captcha.detect and step.page not in UNSUPPORTED_PAGES and on_page:
            stop, solved = await self._captcha_gate(runtime, step, seq)
            if solved and ctx.out.error:                               # the step failed behind the captcha: it is solved now, so do the step again
                await ctx.release_handle()
                ctx, spec_element = await self._perform(runtime, step, seq)
            if solved:
                ctx.out.notes.append(solved)
        output = self._output_of(runtime, step, ctx)
        actual = cell_text(output)
        verdict = evaluate(step, ctx.out, element_action=spec_element, actual=actual)
        if stop:
            verdict, self._captcha_stop = Verdict(FAILED, stop), stop        # never swallowed by Ignore_not_existing_object
        writes = runtime.record(step, verdict.status, verdict.error, output)      # the parameters this step set
        failed = verdict.status == FAILED
        if failed and spec_element:
            with self.timing.span("runner", "failure_capture"):
                self._settled = await self._failed_on_settled_page(ctx)
        hint = self._skipped_hint(off, step.row) if failed and off and not stop else ""
        error_text = f"{verdict.error} {hint}" if hint else verdict.error          # the sheet's Error_Check keeps the plain verdict
        hidden = self.hidden()                                         # what people typed in as secrets, {SECRET:X} values: never stored
        actual = MASK if ctx.out.secret else mask_text(actual, hidden)
        error_text = mask_text(error_text, hidden)
        ctx.out.notes[:] = [mask_text(n, hidden) for n in ctx.out.notes]
        sets = [{**w, **{k: (MASK if ctx.out.secret else mask_text(w[k], hidden)) for k in ("value", "stored")}} for w in writes]      # shown in reports: masked
        if verdict.ignored_error:
            ctx.out.notes.append(f"ignored (Ignore_not_existing_object=Y): {verdict.ignored_error}")
        detail = mask_text(ctx.out.detail, hidden)
        with self.timing.span("runner", "failure_capture"):
            diagnosis = await self._diagnose(ctx, step, seq, verdict, detail, stop, lambda text: mask_text(text, hidden), actual) if failed and on_page else None
        box, screenshot, screenshot_full = None, None, None
        try:
            with self.timing.span("runner", "screenshots"):
                if on_page and (cfg.screenshots.mode == "every_step" or (failed and cfg.screenshots.mode == "on_failure")):
                    box = await self._element_box(ctx)
                if on_page:
                    screenshot = await self._screenshot(seq, step.row, step.name or step.method, failed, box)
                    screenshot_full = await self._full_page_screenshot(seq, step.row, step.name or step.method) if failed and not stop else None
        finally:
            await ctx.release_handle()
        if self.session.infra:                                         # (a crash event can arrive a moment after the error it caused)
            return self._not_run_step(step, seq, ctx, t0, started_at)
        timing = None
        if cfg.measure.timing:
            with self.timing.span("runner", "measuring"):
                await self.session.collect_lag()
            timing = self.timing.step_ended()
        duration_ms = int((time.perf_counter() - t0) * 1000)
        value = MASK if "VALUE" in step.secret_columns else mask_text(step.text("VALUE"), hidden)
        expected = "" if is_blank(step.expected) else (MASK if "EXPECTED_VALUE" in step.secret_columns else mask_text(cell_text(step.expected), hidden))
        record = StepRecord(
            seq=seq, row=step.row, name=step.name, action=step.method, status=verdict.status,
            error=error_text, ignored_error=verdict.ignored_error,
            expected=expected, actual=actual,
            comparison=verdict.comparison, value=value[:500], locator=mask_text(ctx.out.locator, hidden),
            locator_origin=ctx.out.locator_origin, fallback_used=ctx.out.fallback_used, notes=ctx.out.notes, started_at=started_at,
            ended_at=now_iso(), duration_ms=duration_ms, screenshot=screenshot, box=box if screenshot else None, sets=sets,
            detail=detail, diagnosis=diagnosis, screenshot_full=screenshot_full, timing=timing)
        self.result.steps.extend(self._called_steps)                  # (a called test's steps were reported before its CALL_TEST step finished)
        self._called_steps = []
        self.result.steps.append(record)
        self.result.variables.extend({**w, "seq": seq, "row": step.row, "step": step.name, "by_hand": False} for w in sets)
        for w in sets:                                                 # the run's shared variables: what later steps and tests read as {NAME}
            self._emit("variable_set", step=seq, row=step.row, name=w["name"], value=w["value"], cell=w["cell"], by_hand=False)
        self._emit("step_failed" if failed else "step_passed", step=seq, total_steps=self.result.total_steps,
                   row=step.row, name=step.name, action=step.method, status=verdict.status,
                   duration_ms=duration_ms, expected=record.expected, actual=actual, error=error_text,
                   locator=record.locator, locator_origin=record.locator_origin, fallback=record.fallback_used,
                   comparison=record.comparison, notes=record.notes, screenshot=screenshot, sets=sets,
                   **({"detail": detail} if detail else {}), **({"diagnosis": diagnosis} if diagnosis else {}),
                   **({"screenshot_full": screenshot_full} if screenshot_full else {}), **({"timing": timing} if timing else {}))
        return record
