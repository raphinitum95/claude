"""Action handlers: every legacy ``Method`` mapped to Playwright.

Design rules
------------
* No OS-level input anywhere: keys and mouse go through Playwright (DevTools protocol) to the page.
* Elements are located through a strategy chain (sheet Locator -> selectors.yaml -> legacy XPath)
  and *waited for* (actionability), never slept for.
* Behaviour that the legacy workbook relies on is preserved (Set clears, Write/Type append, js_click
  clicks through overlays, Ignore_not_existing_object swallows errors, Exact_Match is exact).
* Where the legacy runner was fragile we tighten precision without changing what "pass" means:
  Output retries until the expected text appears, capture-only Output waits for text to stop
  changing, js_click refuses to click a disabled control (a silent no-op), Wait returns as soon as
  the page is quiet.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..capture.review import ReviewCollector
from ..config import Config
from ..selectors.resolve import Resolved, SelectorMap, SelectorSyntaxError, build_chain, resolve
from ..selectors.spec import Strategy, parse_backup_locators, parse_locator
from ..workbook.model import PreparedStep, is_blank, slug
from ..workbook.sheet import ErrorText, cell_text
from . import checks
from .enabled import DISABLED_BY_JS, pointer
from .gates import has_side_effects, is_production, read_fingerprints
from .keys import parse_sendkeys
from .outcome import StepOut, compare_ok, normalize_expected
from .patience import NO_NOTICE, Patience, plain_seconds
from .session import ActionError, BrowserSession, FrameStep, web_address
from .settle import idle_ms, settle
from .timing import timing_of


# ---------------------------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ActionSpec:
    name: str
    handler: Callable[["StepContext"], Awaitable[None]]
    element: bool = False              # operates on an element -> "Object was not found" applies


REGISTRY: dict[str, ActionSpec] = {}


def action(*names: str, element: bool = False):
    def deco(fn):
        for name in names:
            REGISTRY[name.upper()] = ActionSpec(names[0].upper(), fn, element)
        return fn
    return deco


# Legacy quirk kept on purpose: unknown methods were silent no-ops after an existence check.
LEGACY_EXISTENCE_ALIASES = {'GETATTRIBUTE("VALUE")'}

UNSUPPORTED = {
    "DB_CONNECT", "DB_DISCONNECT", "DB_QUERY", "DB_SAVE_JSON_RESULT", "SEND_EMAIL",
    "FILE_COMPARE", "RUN_SCRIPT", "UPDATE_SYSTEM_TIMEZONE", "BROKEN_LINK_CHECK",
    "BROKEN_LINK_CHECK_CRAWL", "SNAGIT_SCREENSHOT", "BS_CAPABILITIES", "FOCUSWINDOW",
    "GO_TO_ROW", "GET_MOUSE_POS", "DRAGANDDROP",
}

# Steps about variables and the test's own flow (CONTRACT.md 1.3): they never look at the page, so they need no open window, no page-ready wait,
# no captcha check and no screenshot.
NO_PAGE_METHODS = {"SET_VARIABLE", "JSON_READ", "IF", "ELSE", "END_IF", "ITERATION_START", "ITERATION_END", "CALL_TEST"}

VISIBLE_TEXT_JS = """el => {
  // Selenium's rule, kept: an <option> / <optgroup> counts as shown when its <select> is (a closed dropdown gives its
  // options no box of their own, so checking the option itself would call every one of them hidden and read "").
  const host = (el.tagName === 'OPTION' || el.tagName === 'OPTGROUP') ? (el.closest('select') || el) : el;
  const shown = typeof host.checkVisibility === 'function'
      ? host.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) : true;
  return shown ? (el.innerText ?? el.textContent ?? '') : '';
}"""


# ---------------------------------------------------------------------------------------------
# Step context
# ---------------------------------------------------------------------------------------------
@dataclass
class StepContext:
    step: PreparedStep
    session: BrowserSession
    cfg: Config
    selector_map: SelectorMap
    review: ReviewCollector
    test_dir: Path
    harvest: Any = None
    out: StepOut = field(default_factory=StepOut)
    test_id: str = ""                                # for questions put to a person (ASK_USER)
    seq: int = 0
    asker: Any = None                                # engine.ask.Asker of the run (None in unit tests)
    secret_values: set = field(default_factory=set)  # what people typed in as secrets in this test: masked in everything that is stored
    notice: Any = None                               # engine.patience.WaitNotice of the test: tells the run screen when this step waits on purpose
    last_wait: Any = None                            # the Patience of the element search that came back empty (why it gave up)
    flow: Any = None                                 # the test runner's IF / loop / CALL_TEST side (engine/test_runner.py FlowControl); None outside a run
    runtime: Any = None                              # the test's workbook.model.TestRuntime (environment table, variables); None in unit tests
    emit: Any = None                                 # emit(type, **fields): an event of this test (masked); None in unit tests
    side_effects: str = "run"                        # SIDE_EFFECTS=Y steps: "run" (a normal run) | "ask" (a build-mode replay asks first, P08)


    # -- timeouts ----------------------------------------------------------------------------------
    @property
    def act_timeout_s(self) -> float:
        return float(self.step.timeout or self.cfg.timeouts.element_s)

    @property
    def find_timeout_s(self) -> float:
        if self.step.timeout:
            return float(self.step.timeout)
        t = self.cfg.timeouts
        return t.optional_s if self.step.ignore_missing else t.element_s

    @property
    def value_text(self) -> str:
        return cell_text(self.step.value)

    # -- element lookup ------------------------------------------------------------------------------
    def event(self, type_: str, **fields) -> None:
        """An event about this step (``step`` and ``row`` added); nothing outside a run."""
        if self.emit is not None:
            self.emit(type_, step=self.seq, row=self.step.row, **fields)

    async def element(self, *, timeout_s: float | None = None, probe_backups: bool = True) -> Resolved | None:
        """Find the step's element (sets ``out.obj_exists``); ``None`` when it does not exist.  When it does not, and the step is not optional,
        its ``BACKUP_LOCATORS`` are looked at and reported (``probe_backups``): the step still fails, it never uses what they find."""
        step = self.step
        chain = build_chain(step.findby, step.findby_value, step.locator_column, self.selector_map,
                            legacy_fallback=self.cfg.selectors.legacy_fallback)
        if not chain:
            self.out.obj_exists = False
            raise ActionError("No locator: FindBy/FindBy_Value are empty or FindBy is not recognised")
        timeout = self.find_timeout_s if timeout_s is None else timeout_s
        key = "|".join(s.selector for s in chain)
        missed = key in self.session.missed_optional
        if step.ignore_missing and missed and not step.timeout:
            timeout = min(timeout, self.cfg.timeouts.optional_repeat_s)   # already known-absent: quick re-check
        scope = await self.session.scope()
        quiet_mode = step.ignore_missing and not step.timeout and self.cfg.timeouts.optional_mode == "quiet" and self.session.is_open
        page, quiet = (self.session.page, self.cfg.waits.quiet_ms) if self.session.is_open else (None, 0)
        # ``timeout`` is how long the element is looked for once the page has *finished*; while the page is still loading the search goes on
        # (engine/patience.py), so a slow computer or site never makes an element "not found".
        pat = _patient(self, timeout, "the element")

        async def give_up(elapsed: float) -> bool:
            if await pat.give_up():
                return True
            # Optional and still absent once the page has gone quiet (no requests, no DOM changes) - but never while it is still loading.
            return quiet_mode and elapsed >= 0.2 and not pat.activity.working and await idle_ms(page) >= quiet
        limit = self.cfg.patience.max_wait_s + 60 if self.cfg.patience.enabled else timeout
        try:
            with pat:
                res = await resolve(scope, chain, step.index, limit, self.cfg.timeouts.poll_ms / 1000, give_up)
        except SelectorSyntaxError as err:
            self.out.obj_exists = False
            raise ActionError(f"Invalid selector - {err}") from err
        if res is None:
            self.out.obj_exists = False
            if step.ignore_missing:
                self.session.missed_optional.add(key)
            elif pat.reason:
                self.out.notes.append(f"not found: {pat.explain()}")
            self.last_wait = pat
            if probe_backups and not step.ignore_missing:
                await probe_backup_locators(self, scope, chain)
            return None
        self.session.missed_optional.discard(key)
        self.out.obj_exists = True
        self.out.locator = res.strategy.describe()
        self.out.locator_origin = res.strategy.origin
        self.out.target = res.locator
        await self._keep_handle(res)
        if res.used_fallback:
            self.out.fallback_used = True
            skipped = " | ".join(s.describe() for s in chain[:res.position])
            self.out.notes.append(f"fallback locator used ({res.strategy.origin}); no match for: {skipped}")
            if self.cfg.selectors.warn_on_fallback:
                self.review.flag("selector_fallback",
                                 f"Generic locator did not match; fell back to {res.strategy.describe()}",
                                 "warning", locator=res.strategy.describe())
        if self.harvest is not None and res.strategy.origin == "legacy":
            await self.harvest.record(scope, res, step)
        return res


    async def _keep_handle(self, res: Resolved) -> None:
        """Hold a handle on the element so its position can be marked on the step's screenshot."""
        shots = self.cfg.screenshots
        if shots.mode == "off" or shots.full_page:
            return
        await self.release_handle()
        try:
            self.out.handle = await res.locator.element_handle(timeout=250)
        except Exception:
            self.out.handle = None

    async def release_handle(self) -> None:
        handle, self.out.handle = self.out.handle, None
        if handle is not None:
            try:
                await handle.dispose()
            except Exception:
                pass


def act_ms(ctx: StepContext) -> int:
    return int(ctx.act_timeout_s * 1000)


def _patient(ctx, quiet_s: float, what: str, missing: str = "") -> Patience:
    """A wait that goes on while the page is still working and ends once it has been finished for ``quiet_s`` (engine/patience.py)."""
    cfg = getattr(ctx, "cfg", None)
    return Patience(ctx.session, quiet_s, what=what, cfg=cfg.patience if cfg is not None else None, missing=missing)


def _first_line(err: BaseException) -> str:
    return (str(err).strip().splitlines() or [type(err).__name__])[0]


def whole_error(err: BaseException, limit: int = 6000) -> str:
    """The browser's complete error text (Playwright's call log included), or "" when it is only the one line the step already shows."""
    text = str(err).strip()
    if len(text.splitlines()) < 2:
        return ""
    return text if len(text) <= limit else text[:limit] + "\n... (cut)"


# ---------------------------------------------------------------------------------------------
# Browser-level actions
# ---------------------------------------------------------------------------------------------
def parse_open_value(value: str) -> dict[str, str]:
    """``URL:=https://x;;HEADLESS:=TRUE;;WIDTH:=390;;HEIGHT:=844`` or a bare URL."""
    value = value.strip()
    if ";;" not in value and ":=" not in value:
        return {"URL": value}
    result: dict[str, str] = {}
    for item in value.split(";;"):
        if ":=" in item:
            key, _, val = item.partition(":=")
            result[key.strip().upper()] = val.strip()
    return result


@action("OPEN")
async def open_browser(ctx: StepContext) -> None:
    params = parse_open_value(ctx.value_text)
    url = params.get("URL", "")
    if is_blank(url):
        raise ActionError("Open: no URL (Value is empty)")
    if ctx.step.page and ctx.step.page not in ("CHROME", "CHROME1", "CHROMIUM", "BROWSERSTACK", ""):
        ctx.review.flag("browser", f"Browser type {ctx.step.page!r} requested; running {ctx.session.cfg.browser.kind.label} instead (the browser is chosen for the whole run)", "info")
    device = None
    if params.get("DEVICE_NAME") and getattr(ctx.session, "devices", None):
        device = ctx.session.devices.get(params["DEVICE_NAME"])
    await ctx.session.open(
        url,
        width=int(float(params["WIDTH"])) if params.get("WIDTH") else None,
        height=int(float(params["HEIGHT"])) if params.get("HEIGHT") else None,
        scale=float(params["PIXEL_RATIO"]) if params.get("PIXEL_RATIO") else None,
        device=device)
    ctx.out.notes.extend(ctx.session.notes)
    ctx.session.notes.clear()


@action("NAVIGATE", "DRIVER_GET")
async def navigate(ctx: StepContext) -> None:
    url = web_address(ctx.value_text)
    if not url:
        raise ActionError("Navigate: no URL")
    await ctx.session.pace()
    page = ctx.session.page
    try:
        await ctx.session.load(page, lambda **kw: page.goto(url, **kw))
    except ActionError as err:
        raise ActionError(f"Navigation failed: {err}") from err
    except Exception as err:
        ctx.out.detail = whole_error(err)
        raise ActionError(f"Navigation failed: {_first_line(err)}") from err


@action("BACK")
async def back(ctx: StepContext) -> None:
    page = ctx.session.page
    await ctx.session.load(page, lambda **kw: page.go_back(**kw))
    ctx.session.switch_to_default()


@action("REFRESH")
async def refresh(ctx: StepContext) -> None:
    page = ctx.session.page
    await ctx.session.load(page, lambda **kw: page.reload(**kw))
    ctx.session.switch_to_default()


@action("MAXIMIZE")
async def maximize(ctx: StepContext) -> None:
    ctx.out.notes.append("viewport is fixed; MAXIMIZE is a no-op")


@action("SET_PAGE_LOAD_TIMEOUT")
async def set_page_load_timeout(ctx: StepContext) -> None:
    ctx.session.nav_timeout_s = float(ctx.value_text)
    ctx.session.context.set_default_navigation_timeout(ctx.session.nav_timeout_s * 1000)


@action("CLOSE")
async def close_window(ctx: StepContext) -> None:
    await ctx.session.close_page()


@action("QUIT")
async def quit_browser(ctx: StepContext) -> None:
    await ctx.session.close()


@action("SWITCHTOFRAME")
async def switch_to_frame(ctx: StepContext) -> None:
    value = ctx.value_text.strip()
    if value and "self.Driver" not in value:
        step = FrameStep("name", value)
    elif not is_blank(ctx.step.values.get("INDEX")):
        step = FrameStep("index", ctx.step.index)
    else:
        raise ActionError("SwitchToFrame: give the frame name/id in Value or its position in Index")
    lenient = ctx.cfg.behaviour.missing_frame == "continue"
    key = f"frame:{step.by}:{step.value}"
    timeout = ctx.act_timeout_s
    quiet_mode = False
    if lenient and not ctx.step.timeout:
        if key in ctx.session.missed_optional:
            timeout = min(timeout, ctx.cfg.timeouts.optional_repeat_s)
        quiet_mode = ctx.cfg.timeouts.optional_mode == "quiet" and ctx.session.is_open
    page, quiet = (ctx.session.page, ctx.cfg.waits.quiet_ms) if ctx.session.is_open else (None, 0)
    pat = _patient(ctx, timeout, f"the frame {step.value!r}")

    async def give_up(elapsed: float) -> bool:
        if await pat.give_up():
            return True
        return quiet_mode and elapsed >= 0.2 and not pat.activity.working and await idle_ms(page) >= quiet     # (never while it is still loading)
    try:
        with pat:
            await ctx.session.switch_to_frame(step, ctx.cfg.patience.max_wait_s + 60 if ctx.cfg.patience.enabled else timeout, give_up)
        ctx.session.missed_optional.discard(key)
    except ActionError as err:
        if not lenient or "No such frame" not in str(err):
            raise
        # The legacy runner silently ignored a missing frame (Selenium's NoSuchFrameException text did not match
        # the strings it tested for), and the shared workbook steps rely on that: the same "Switch to Frame
        # aemFormFrame" row exists on brands whose pages have no such frame.
        ctx.session.missed_optional.add(key)
        ctx.out.notes.append(f"frame {step.value!r} not found; continuing in the current document (legacy behaviour)")
        ctx.review.flag("missing_frame", f"Frame {step.value!r} was not found in step {ctx.step.name!r}; "
                        "continued in the current document like the legacy runner", "warning")


@action("SWITCHTODEFAULT")
async def switch_to_default(ctx: StepContext) -> None:
    ctx.session.switch_to_default()


@action("SWITCHTOWINDOW")
async def switch_to_window(ctx: StepContext) -> None:
    if is_blank(ctx.step.value):
        return                                   # legacy: blank value did nothing
    session = ctx.session
    if not any(not p.is_closed() for p in session.pages):
        raise ActionError("No open browser window")                  # nothing can appear now: do not wait for it
    key = ctx.value_text.strip().upper()
    wants_latest = key in ("-1", "WINDOW_HANDLES[-1]")
    if wants_latest and not session.window_recently_opened:
        # A popup triggered by the previous step is registered asynchronously; legacy runs hid this
        # race behind fixed waits.  Give it a moment to appear instead of "switching" to the old window.
        known = len(session.pages)
        with _patient(ctx, ctx.cfg.waits.window_grace_s, "the new window to open") as pat:       # a busy page may take longer to open it
            while len(session.pages) <= known and not session.window_recently_opened and not await pat.give_up():
                await asyncio.sleep(0.05)
    if wants_latest:
        open_windows = [p for p in session.pages if not p.is_closed()]
        if len(open_windows) == 1:
            # Legacy "switched" to the newest window, which with one window is the one it was already in: a missing popup passed and the steps
            # after it ran against the wrong page.  The window this step waits for did not open.
            raise ActionError(f"No new window opened: this step switches to the window the step before it opens, but after waiting "
                              f"{ctx.cfg.waits.window_grace_s:g} s only {len(open_windows)} window is open")
    # A window index may refer to a window that is not registered yet; wait for it.
    with _patient(ctx, ctx.act_timeout_s, "the window") as pat:
        while True:
            try:
                ctx.session.switch_to_window(ctx.value_text)
                return
            except ActionError:
                if await pat.give_up():
                    raise
                await asyncio.sleep(0.1)


@action("SWITCHTOMAINWINDOW")
async def switch_to_main_window(ctx: StepContext) -> None:
    ctx.session.switch_to_main_window()


@action("EXECUTESCRIPT")
async def execute_script(ctx: StepContext) -> None:
    scope = await ctx.session.scope()
    result = await scope.evaluate("() => {" + ctx.value_text + "\n}")
    if not is_blank(result):
        ctx.out.output = result if isinstance(result, str) else cell_text(result)


@action("GET_CURRENT_URL")
async def get_current_url(ctx: StepContext) -> None:
    ctx.out.output = ctx.session.page.url


ASK_METHODS = {"ASK_USER", "PROMPT", "ASK", "GET_GOOGLE_TOKEN"}       # steps that may wait for a person: the step time limit does not apply to the wait


async def ask_person(ctx: StepContext, question: str, *, secret: bool, timeout_s: float | None = None) -> str:
    """Put ``question`` to whoever the run belongs to (run screen or terminal) and return the answer; failures become the step's error."""
    from .ask import AskCancelled, AskTimeout, AskUnavailable
    if ctx.asker is None:
        raise ActionError("This step asks a person, but there is nobody to ask here.")
    try:
        with timing_of(ctx).span("wait", "ask_user"):
            answer = await ctx.asker.ask(ctx.test_id, ctx.seq, question, secret=secret, timeout_s=timeout_s)
    except AskUnavailable as err:
        raise ActionError(str(err)) from None
    except AskTimeout as err:
        raise ActionError(f"No answer to \"{question[:80]}\": {err}") from None
    except AskCancelled as err:
        raise ActionError(str(err)) from None
    if secret and answer:
        ctx.out.secret = True
        ctx.secret_values.add(answer)
    return answer


@action("ASK_USER", "PROMPT", "ASK")
async def ask_user(ctx: StepContext) -> None:
    """Ask a person for a value.  Value = the question.  Output_Property = SECRET hides what is typed.  Timeout = seconds to wait.
    The answer becomes the step's Output_Value (a later ``Set`` with ``=S<row>`` can type it); with FindBy / FindBy_Value filled it is also
    typed into that element right here (found first, so a missing field is reported before anyone is asked)."""
    step = ctx.step
    question = ctx.value_text.strip() or step.name or "Please enter a value"
    res = None
    if step.findby_value or step.locator_column:
        res = await ctx.element(timeout_s=ctx.cfg.timeouts.element_s)
        if res is None:
            raise ActionError("Object was not found")
    answer = await ask_person(ctx, question, secret=step.output_property in ("SECRET", "PASSWORD"), timeout_s=step.timeout)
    ctx.out.output = answer
    if res is not None and answer:
        await type_into(ctx, res, answer, clear_first=True)


@action("GET_GOOGLE_TOKEN")
async def get_google_token(ctx: StepContext) -> None:
    """Value = the authenticator secret; the current 6-digit code becomes the step's Output_Value (a later Set reads it).
    With no usable secret and a person to ask, it asks for the code instead."""
    from ..totp import STEP_S, BadSecret, code_at, fingerprint, reserve_window
    try:
        code_at(ctx.value_text)
    except BadSecret as err:
        if ctx.asker is not None and ctx.asker.available:
            ctx.out.notes.append(f"no usable key ({err}): asked for the code instead")
            # Nobody here knows the key, so nothing can stop two tests being given the same code: say so to the person who reads it off the phone.
            ctx.out.output = (await ask_person(ctx, "Enter the 6-digit code from Google Authenticator. Each code works once: if another test has just "
                                                    "used the code on screen, wait for the next one.", secret=True)).strip()
            return
        raise ActionError(f"GET_GOOGLE_TOKEN: {err} (the Value cell is the secret key). Fill it in, or use an ASK_USER step to be asked for the "
                          "code.") from None
    # One code, one login: a code is accepted once, so a second test logging in with the same secret (at the same moment, or a run started a few seconds after
    # another) is given the next window's code instead of the one that was just used.  A code is also only handed out with enough of its 30 s left to
    # reach the Verify click (measured on this computer: code_submitted).
    store = ctx.cfg.base_dir / ".auth" / "totp_last.json"
    booked = reserve_window(ctx.value_text, store=store)
    if booked.wait_s > 0:
        why = ("the code for this one was already used by another login with the same authenticator secret, and Okta accepts a code once"
               if booked.reason == "used" else "the current code would expire before the login is submitted")
        plain = ("another test has just used this account's current code, and the site accepts each code once" if booked.reason == "used"
                 else "the current code would expire before this test gets to submit it")
        notice = ctx.notice or NO_NOTICE
        wait_id = notice.begin("login_code", f"Waiting {booked.wait_s:.0f} s for the next login code: {plain}.", seconds=booked.wait_s)
        try:
            with timing_of(ctx).span("wait", "login_code"):
                await asyncio.sleep(booked.wait_s)
        finally:
            notice.end(wait_id)
        ctx.out.notes.append(f"waited {booked.wait_s:.1f}s for the next {STEP_S} s code window ({why})")
    code = code_at(ctx.value_text, booked.window * STEP_S)
    ctx.out.output = code
    ctx.out.secret = True                                   # a login code is never shown in a report or an event, here or where a later step types it
    ctx.secret_values.add(code)
    try:
        ctx.session.totp = {"code": code, "key": fingerprint(ctx.value_text), "store": store, "issued": time.time(),
                            "expires": (booked.window + 1) * STEP_S, "step": ctx.seq, "typed": False, "submitted": False}
    except AttributeError:
        pass


def code_typed(ctx, text: str) -> None:
    """The one-time code handed out by GET_GOOGLE_TOKEN is being typed into the page (never shown: only that it happened)."""
    booked = getattr(ctx.session, "totp", None)
    if booked and not booked["submitted"] and booked["code"] in str(text):
        booked["typed"] = True


def code_submitted(ctx) -> None:
    """The first click / Enter after the code was typed is what sends it to the site: measure how long after it was handed out, and how much of
    its 30 s was left.  Remembered per secret (``totp.record_gap``) so the next code is handed out with enough time left; a code that had already
    expired is flagged on the step (the site may then refuse the login)."""
    from ..totp import record_gap
    booked = getattr(ctx.session, "totp", None)
    if not booked or not booked["typed"] or booked["submitted"]:
        return
    booked["submitted"] = True
    now = time.time()
    gap, left = now - booked["issued"], booked["expires"] - now
    record_gap(booked["key"], gap, booked["store"])
    if left >= 0:
        ctx.out.notes.append(f"the login code from step {booked['step']} was submitted {gap:.1f} s after it was generated, {left:.1f} s before it expired")
    else:
        ctx.out.notes.append(f"the login code from step {booked['step']} was submitted {gap:.1f} s after it was generated, {-left:.1f} s AFTER it "
                             "expired: the site may refuse it. The next code is handed out with more time left.")
        review = getattr(ctx, "review", None)
        if review is not None:
            review.flag("login_code", f"A login code was submitted {-left:.1f} s after it expired (step {ctx.seq}); the site may have refused it", "warning")


@action("ALERT_OK", "ALERT_CANCEL", "ALERT_TEXT_OUT")
async def alert(ctx: StepContext) -> None:
    method = ctx.step.method
    answered, ctx.session.answered_dialog = getattr(ctx.session, "answered_dialog", None), None
    if answered is not None and ctx.session.pending_dialog is None:
        # The dialog opened during the step before this one and was answered right then, the way this step says (see BrowserSession._on_dialog).
        if method == "ALERT_TEXT_OUT":
            ctx.out.output = answered["message"]
        ctx.out.notes.append(f"the dialog was answered with {'OK' if answered['how'] == 'accept' else 'Cancel'} as it opened (a page can do nothing "
                             "while a dialog is open), as this step says")
        return
    deadline = time.monotonic() + ctx.act_timeout_s
    while ctx.session.pending_dialog is None:
        if time.monotonic() >= deadline:
            raise ActionError("Alert button not found (no dialog is open)")
        await asyncio.sleep(0.05)
    dialog, ctx.session.pending_dialog = ctx.session.pending_dialog, None
    if method == "ALERT_TEXT_OUT":
        ctx.out.output = dialog.message
        await dialog.dismiss()
    elif method == "ALERT_CANCEL":
        await dialog.dismiss()
    else:
        await dialog.accept()


@action("SCREENSHOT", "PNG_SCREENSHOT", "BASE64_SCREENSHOT")
async def screenshot(ctx: StepContext) -> None:
    raw = ctx.value_text.strip()
    if not raw:
        raise ActionError("Screenshot: give a file name in Value")
    name = slug(re.split(r"[\\/]", raw)[-1]) or "screenshot"
    if not re.search(r"\.(png|jpe?g|html)$", name, re.IGNORECASE):
        name += ".png"
    target = ctx.test_dir / "named" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    # Legacy runs zoomed the browser out (Ctrl+-) before shooting a long page; a full-page shot is
    # the headless equivalent and captures everything.
    await ctx.session.page.screenshot(path=str(target), full_page=True, type="png" if name.lower().endswith("png") else "jpeg")
    ctx.out.notes.append(f"named screenshot: {target.name}")
    ctx.out.output = None


# ---------------------------------------------------------------------------------------------
# Timing / OS-level legacy actions, re-expressed for the browser
# ---------------------------------------------------------------------------------------------
@action("WAIT")
async def wait(ctx: StepContext) -> None:
    try:
        seconds = float(cell_text(ctx.step.value) or 0)
    except ValueError:
        raise ActionError(f"Wait: {ctx.step.value!r} is not a number of seconds")
    mode = ctx.cfg.waits.mode
    if mode == "off" or seconds <= 0:
        return
    if mode == "legacy" or getattr(ctx.session, "pending_dialog", None) is not None:      # (an open dialog blocks the page: nothing to watch)
        await asyncio.sleep(seconds)
        return
    if not ctx.session.is_open:
        ctx.out.notes.append("no page yet; nothing to wait for")
        return
    cap = ctx.cfg.waits.cap_s if ctx.cfg.waits.cap_s is not None else seconds
    waited = await settle(ctx.session.page, min(seconds, cap), ctx.cfg.waits.quiet_ms, ctx.cfg.waits.min_s)
    ctx.out.notes.append(f"waited {waited:.2f}s of {seconds:g}s (page settled)" if waited < seconds
                         else f"waited {seconds:g}s")


@action("SENDKEYS", "SENDKEY", "SEND_KEY", "SEND_KEYS")
async def send_keys(ctx: StepContext) -> None:
    """Legacy: OS keystrokes to the focused window. Now: keys to the focused element of this page."""
    kb = ctx.session.page.keyboard
    calls_before = ctx.session.calls_snapshot()
    typed, skipped_zoom = [], 0
    for op in parse_sendkeys(ctx.value_text):
        if op.is_browser_zoom:
            skipped_zoom += 1                       # headless pages have no browser zoom; screenshots are full-page
            continue
        if op.text:
            typed.append(op.key)
            continue
        if typed:
            code_typed(ctx, "".join(typed))
            await kb.type("".join(typed))
            typed = []
        await kb.press(op.combo)
        if op.combo.split("+")[-1] in ("Enter", "NumpadEnter"):
            code_submitted(ctx)
        if op.combo.split("+")[-1] in ("Enter", "NumpadEnter") and await ctx.session.watch_for_navigation():
            await ctx.session.ensure_ready()              # Enter submitted a form / followed a link: end the step on the new page
            ctx.out.notes.append("the key press loaded a page; waited for it")
    if typed:
        code_typed(ctx, "".join(typed))
        await kb.type("".join(typed))
    if skipped_zoom:
        ctx.out.notes.append(f"{skipped_zoom} browser-zoom shortcut(s) ignored (headless)")
    if len(parse_sendkeys(ctx.value_text)) > skipped_zoom:
        await ctx.session.settle_after_input(calls_before)   # e.g. Tab out of a field: if the page asked the server, wait for the answer


@action("MOUSE_SCROLL")
async def mouse_scroll(ctx: StepContext) -> None:
    """``400, N`` = 400 wheel notches, N=down / Y=up, optional ``, x, y`` (legacy: OS wheel events)."""
    parts = [p.strip() for p in ctx.value_text.split(",")]
    if len(parts) < 2:
        raise ActionError("MouseScroll: Value must look like '400, N' (notches, Y=up/N=down)")
    notches = max(int(float(parts[0])) - 1, 0)          # legacy loop was range(1, n)
    up = parts[1].upper() in ("Y", "YES", "TRUE", "1")
    page = ctx.session.page
    size = page.viewport_size or {"width": 1920, "height": 1080}
    x = int(float(parts[2])) if len(parts) > 2 and parts[2] else size["width"] // 2
    y = int(float(parts[3])) if len(parts) > 3 and parts[3] else size["height"] // 2
    await page.mouse.move(x, y)
    remaining = notches * 100
    while remaining > 0:
        step = min(remaining, 4000)
        await page.mouse.wheel(0, -step if up else step)
        remaining -= step
        await asyncio.sleep(0.03)


@action("MOUSE_MOVE")
async def mouse_move(ctx: StepContext) -> None:
    x, y = [int(float(p)) for p in ctx.value_text.split(",")[:2]]
    await ctx.session.page.mouse.move(x, y)


@action("MOUSE_CLICK", "MOUSE_LEFT_CLICK", "MOUSE_DOUBLE_CLICK", "MOUSE_DOUBLE_LEFT_CLICK", "MOUSE_RIGHT_CLICK")
async def mouse_click(ctx: StepContext) -> None:
    method, page = ctx.step.method, ctx.session.page
    coords = [p for p in ctx.value_text.split(",") if p.strip()]
    button = "right" if "RIGHT" in method else "left"
    count = 2 if "DOUBLE" in method else 1
    pos = page.viewport_size or {"width": 1920, "height": 1080}
    x = int(float(coords[0])) if len(coords) >= 2 else pos["width"] // 2
    y = int(float(coords[1])) if len(coords) >= 2 else pos["height"] // 2
    await page.mouse.click(x, y, button=button, click_count=count)


@action("CLEAR_CLIPBOARD")
async def clear_clipboard(ctx: StepContext) -> None:
    ctx.out.notes.append("clipboard is not shared with the browser; nothing to clear")


# ---------------------------------------------------------------------------------------------
# Element actions
# ---------------------------------------------------------------------------------------------
@action("EXIST", "GETATTRIBUTE(\"VALUE\")", element=True)
async def exist(ctx: StepContext) -> None:
    await ctx.element()
    if ctx.step.method in LEGACY_EXISTENCE_ALIASES:
        ctx.out.notes.append("legacy no-op action: only existence is checked, the value is NOT verified")
        ctx.review.flag("legacy_noop", f"Step {ctx.step.name!r} uses {ctx.step.method}, which the legacy runner "
                        "never implemented - it only checks existence", "warning")


@action("NOT_EXIST", element=False)
async def not_exist(ctx: StepContext) -> None:
    """Passes as soon as the element is absent (legacy always waited the full timeout)."""
    step = ctx.step
    chain = build_chain(step.findby, step.findby_value, step.locator_column, ctx.selector_map,
                        legacy_fallback=ctx.cfg.selectors.legacy_fallback)
    scope = await ctx.session.scope()
    with _patient(ctx, ctx.act_timeout_s, "the element to go away", "the element was still there") as pat:       # a page still loading may remove it late
        while True:
            counts = []
            for s in chain:
                try:
                    counts.append(await scope.locator(s.selector).count())
                except Exception:
                    counts.append(0)
            if not any(c > step.index for c in counts):
                return
            if await pat.give_up():
                raise ActionError("Object existed")
            await asyncio.sleep(0.1)


@action("HIGHLIGHT", element=True)
async def highlight(ctx: StepContext) -> None:
    await ctx.element()


# A control whose click can load a page (a link, a button, a submit); a radio / checkbox / label does not.
_MAY_NAVIGATE_JS = "e => !!e.closest('a[href], button, input[type=submit], input[type=button], input[type=image], [role=button], [role=link]')"


async def _may_navigate(res: Resolved) -> bool:
    try:
        return bool(await res.locator.evaluate(_MAY_NAVIGATE_JS, timeout=1500))
    except Exception:
        return False


# A radio button or checkbox, or the label that drives one.  Its state is the proof that a click did something.
_CHECKABLE_JS = """e => {
  const c = e.matches('input[type=radio],input[type=checkbox]') ? e
    : (e.tagName === 'LABEL' && e.control && /^(radio|checkbox)$/.test(e.control.type) ? e.control : null);
  return c ? {type: c.type, checked: c.checked} : null;
}"""


async def _checkable_state(res: Resolved) -> dict[str, Any] | None:
    try:
        return await res.locator.evaluate(_CHECKABLE_JS, timeout=1500)
    except Exception:
        return None                                   # not there any more, or nothing to verify


async def click_and_verify(ctx: StepContext, res: Resolved, do_click: Callable[[], Awaitable[None]]) -> None:
    """Click once, and for a radio / checkbox (or its label) check that the click *took* and stayed.

    The click is never repeated: a page that undoes a click is showing a defect (or was not ready, which is what
    ``ensure_ready`` is for), and clicking again would hide it.  The control gets up to 1 s to show the new state, and must then
    keep it for ~0.4 s; otherwise the step fails and says so, instead of passing on a click that did nothing.
    """
    await ctx.session.ensure_ready()
    before = await _checkable_state(res)
    navigates = before is None and await _may_navigate(res)
    if navigates:
        await ctx.session.pace()                          # a click that may load a page waits its turn (run-wide throttle / cool-down)
    mark = ctx.session.calls_snapshot()
    await do_click()
    code_submitted(ctx)
    if navigates:
        started_navigation = await ctx.session.watch_for_navigation()
        await ctx.session.await_call_results(mark, 3.0)   # what the click asked of the server: did it answer, and was it refused?
        ctx.session.raise_if_blocked(mark[2])
        if started_navigation:
            await ctx.session.ensure_ready()              # the click loaded a page: end the step on the new page, like a driver would
            ctx.out.notes.append("the click loaded a page; waited for it")
            return
    elif before is None:
        ctx.session.raise_if_blocked(mark[2])             # e.g. a div that loads content: refused calls are still worth failing on
    if before is None:
        return
    radio = before["type"] == "radio"
    want = True if radio else not before["checked"]
    what = "selected" if radio else "toggled"
    with _patient(ctx, 1.0, f"the {before['type']} to show the click") as pat:      # (a busy page takes longer to show it)
        while True:                                   # phase 1: the new state has to appear
            now = await _checkable_state(res)
            if now is None:
                return                                # the page replaced the element: nothing left to verify
            if now["checked"] == want:
                break
            if await pat.give_up():
                raise ActionError(f"Clicked the {before['type']} but it did not become {what} (the page ignored or undid the click)")
            await asyncio.sleep(0.1)
    for _ in range(2):                                # phase 2: ...and stay
        await asyncio.sleep(0.2)
        now = await _checkable_state(res)
        if now is not None and now["checked"] != want:
            raise ActionError(f"Clicked the {before['type']} and it became {what}, but the page then undid it")


@action("CLICK", element=True)
async def click(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None:
        await click_and_verify(ctx, res, lambda: pointer(ctx, res))


@action("DOUBLECLICK", element=True)
async def double_click(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None:
        await pointer(ctx, res, "dblclick")


@action("CONTEXTCLICK", element=True)
async def context_click(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None:
        await pointer(ctx, res, "click", button="right")


@action("MOVETOELEMENT", element=True)
async def move_to_element(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None:
        await res.locator.hover(timeout=act_ms(ctx))


# What a person could click: the element has a box and is not display:none / visibility:hidden (the same rule Playwright's own click applies).
# A styled radio button / checkbox keeps its native <input> hidden and shows a <label>: a person clicks that, so the input counts when a label is shown.
CLICKABLE_JS = """el => {
  const shown = (n) => {
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && (typeof n.checkVisibility !== 'function' || n.checkVisibility({checkVisibilityCSS: true}));
  };
  const host = (el.tagName === 'OPTION' || el.tagName === 'OPTGROUP') ? (el.closest('select') || el) : el;
  const visible = shown(host) || (el.tagName === 'INPUT' && (el.type === 'radio' || el.type === 'checkbox') && Array.from(el.labels || []).some(shown));
  return {disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true', visible: visible};
}"""


@action("JS_CLICK", element=True)
async def js_click(ctx: StepContext) -> None:
    """DOM ``element.click()`` - reaches elements a real click cannot (covered by an overlay, outside the window).

    It mimics a person, so only an element a person could see is clicked: one that is hidden (display:none, visibility:hidden, no size) fails the
    step instead of being clicked behind the scenes.  The legacy version also silently did nothing on a disabled control; we wait for it to become
    enabled and fail if it never does, so a no-op click cannot masquerade as a pass.
    """
    res = await ctx.element()
    if res is None:
        return
    with _patient(ctx, ctx.find_timeout_s if ctx.step.ignore_missing else ctx.act_timeout_s, "the element to be shown and enabled") as pat:
        while True:                                  # (an optional element is not waited for long once the page has finished)
            state = await res.locator.evaluate(CLICKABLE_JS, timeout=act_ms(ctx))
            if state["visible"] and not state["disabled"]:
                break
            if await pat.give_up():
                if not state["visible"]:
                    raise ActionError("Element is not visible, so a person could not click it (hidden or has no size)")
                raise ActionError("Element is disabled; a DOM click would do nothing")
            await asyncio.sleep(0.1)
    await click_and_verify(ctx, res, lambda: res.locator.evaluate("e => e.click()", timeout=act_ms(ctx)))


@action("TICK", element=True)
async def tick(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None and not await res.locator.evaluate("e => !!e.checked", timeout=act_ms(ctx)):
        await pointer(ctx, res)


@action("UNTICK", element=True)
async def untick(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None and await res.locator.evaluate("e => !!e.checked", timeout=act_ms(ctx)):
        await pointer(ctx, res)


@action("CLEAR", element=True)
async def clear(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None:
        await res.locator.clear(timeout=act_ms(ctx))


@action("SPECIALKEY", element=True)
async def special_key(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is None:
        return
    await res.locator.focus(timeout=act_ms(ctx))
    for op in parse_sendkeys(ctx.value_text or "{ENTER}"):
        await ctx.session.page.keyboard.press(op.combo)
        if op.combo.split("+")[-1] in ("Enter", "NumpadEnter"):
            code_submitted(ctx)


_CARET_TO_END_JS = """e => { try { if (typeof e.value === 'string' && e.setSelectionRange) {
    const n = e.value.length; e.setSelectionRange(n, n); } } catch (_) {} }"""


_VALUE_JS = "e => typeof e.value === 'string' ? e.value : (e.isContentEditable ? (e.textContent || '') : null)"


@dataclass
class TypedField:
    locator: Any
    text: str
    clear_first: bool
    label: str


async def _field_value(locator) -> str | None:
    """What the field holds right now; ``None`` when it is gone or is not a text field."""
    try:
        if await locator.count() == 0:
            return None
        return await locator.first.evaluate(_VALUE_JS, timeout=800)
    except Exception:
        return None


_CLICK_EVENTS_JS = """e => { for (const type of ['mousedown', 'mouseup', 'click']) {
  e.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, composed: true, view: window, button: 0})); } }"""


async def _editable(ctx: StepContext, locator) -> int:
    """Before typing: wait - patiently - until the field is shown and editable (a form still loading shows it disabled / hides it).  Returns the
    time limit for the typing itself (short when the field never became usable on a finished page)."""
    ms = act_ms(ctx)
    with _patient(ctx, ctx.act_timeout_s, "the field to be usable", "the field did not become editable") as pat:
        if pat.plain:
            return ms
        while True:
            try:
                if await locator.is_visible() and await locator.is_editable(timeout=1500):
                    return ms
            except Exception as err:
                if "Timeout" not in str(err):
                    return ms                                    # not a text field (a contenteditable...): the typing itself says what is wrong
            if await pat.give_up():
                ctx.out.notes.append(f"not usable: {pat.explain()}")
                return 2000
            await asyncio.sleep(0.1)


async def _enter(ctx: StepContext, locator, text: str, clear_first: bool) -> None:
    timeout = await _editable(ctx, locator)
    if ctx.cfg.behaviour.click_before_typing and text:
        # A person clicks into a field before typing, and sites rely on it: this one (Owner_CRVD) removes a field's error message
        # in a click handler and skips validating a field that still shows one, and its date picker closes on a mousedown outside
        # it.  The events of a click (mousedown, mouseup, click) are dispatched on the field, not a mouse click at its coordinates: an
        # open date picker or another overlay can cover the field, and a real click would land on that instead.
        try:
            await locator.evaluate(_CLICK_EVENTS_JS, timeout=timeout)
        except Exception:
            pass                                                # not clickable (read-only, gone): the typing below reports the real problem
    if clear_first:
        await locator.clear(timeout=timeout)                     # waits for visible + enabled + editable
    else:
        await locator.wait_for(state="visible", timeout=timeout)
    await locator.focus(timeout=timeout)
    await locator.evaluate(_CARET_TO_END_JS, timeout=timeout)
    if text:
        code_typed(ctx, text)
        await ctx.session.page.keyboard.type(text)


async def type_into(ctx: StepContext, res: Resolved, text: str, *, clear_first: bool) -> None:
    """Selenium ``send_keys`` semantics (real key events, caret at the end, optional clear first), and the text has to *stay*.

    Every field typed in the current run of typing steps is looked at again for ~0.4 s.  One that has been emptied fails the
    step and names the field: typing is never repeated, because a page that clears what was typed - or an earlier field when the
    next one is typed - has a defect, and typing it again would hide it.  (A page that has not finished starting up does this
    too; ``ensure_ready`` waits for that before the first typing.)
    """
    await ctx.session.ensure_ready()
    calls_before = ctx.session.calls_snapshot()
    await _enter(ctx, res.locator, text, clear_first)
    if not text:
        return
    now = await _field_value(res.locator)
    if now is None or not now.strip():
        await ctx.session.settle_after_input(calls_before)
        return                                                   # rejected or masked away at once: it was never "typed"
    key = str(res.locator)
    ctx.session.typed[:] = [f for f in ctx.session.typed if str(f.locator) != key]
    ctx.session.typed.append(TypedField(res.locator, text, clear_first, ctx.step.name or "field"))
    await _typed_fields_hold(ctx, key)
    await ctx.session.settle_after_input(calls_before)


async def _typed_fields_hold(ctx: StepContext, current_key: str) -> None:
    typed = ctx.session.typed
    for _look in range(2):
        await asyncio.sleep(0.2)
        for f in list(typed):
            value = await _field_value(f.locator)
            if value is None:
                typed.remove(f)                                  # the page moved on: nothing left to check
            elif not value.strip():
                if str(f.locator) == current_key:
                    raise ActionError(f"Typed '{f.label}' but the field is empty {0.2 * (_look + 1):.1f}s later (the page cleared it)")
                raise ActionError(f"'{f.label}' was typed earlier and is now empty: the page cleared it when '{typed[-1].label}' was typed")


# Steps that leave typed fields alone.  Anything else (a click, a selection, a navigation...) may legitimately reset a form,
# so it ends the run of typing steps that is being protected.
_TYPING_RUN_KEEPS = {"SET", "WRITE", "WAIT", "OUTPUT", "EXIST", "SCREENSHOT", "SWITCHTOFRAME", "SWITCHTODEFAULT", *NO_PAGE_METHODS,
                     "ASSERT_PAGE", "WAIT_UNTIL", "CHECK_VALUE", "CHECK_REGEX", "CHECK_COMPARE", "CHECK_COUNT", "CHECK_ENABLED", "CHECK_CHECKED",
                     "CHECK_SELECTED", "CHECK_DATE_FORMAT", "CHECK_LIST_ITEM"}      # (they only look at the page)


_NO_PAGE_GATE = {"OPEN", "QUIT", "WAIT", "BREAK", "STOP",          # these do not depend on the current document
                 "ALERT_OK", "ALERT_CANCEL", "ALERT_TEXT_OUT",      # (and while a dialog is open the page cannot answer: it waits for the dialog)
                 *NO_PAGE_METHODS}


def ends_typing_run(action_name: str) -> bool:
    return action_name.upper() not in _TYPING_RUN_KEEPS


@action("SET", "INPUT", element=True)
async def set_value(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None and not is_blank(ctx.step.value):
        await type_into(ctx, res, ctx.value_text, clear_first=True)


@action("WRITE", "TYPE", element=True)
async def write_value(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None and not is_blank(ctx.step.value):
        await type_into(ctx, res, ctx.value_text, clear_first=False)


@action("CLICK_SENDKEYS", element=True)
async def click_send_keys(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is None or is_blank(ctx.step.value):
        return
    await pointer(ctx, res)
    for op in parse_sendkeys(ctx.value_text):
        if op.is_browser_zoom:
            continue
        await (ctx.session.page.keyboard.type(op.key) if op.text else ctx.session.page.keyboard.press(op.combo))


@action("CUSTOMINPUTDATA", element=True)
async def custom_input(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is not None:
        await res.locator.fill(ctx.value_text, timeout=act_ms(ctx))


@action("SELECT", element=True)
async def select(ctx: StepContext) -> None:
    """Exact option text first, then case-insensitive substring; ``text:=N`` picks the Nth match."""
    res = await ctx.element()
    if res is None or is_blank(ctx.step.value):
        return
    raw = ctx.value_text
    nth = 0
    if ":=" in raw:
        raw, _, idx = raw.partition(":=")
        nth = int(idx)
    target = raw.strip()
    options = await res.locator.evaluate(
        "e => Array.from(e.options).map(o => (o.textContent || '').trim())", timeout=act_ms(ctx))
    matches = [i for i, t in enumerate(options) if t == target] or \
              [i for i, t in enumerate(options) if target.lower() in t.lower()]
    if not matches:
        ctx.out.notes.append(f"no option matching {target!r}")
        return                                                    # legacy: silently did nothing
    await res.locator.select_option(index=matches[nth] if nth < len(matches) else matches[0],
                                    timeout=act_ms(ctx))


# -- Output ----------------------------------------------------------------------------------------
def legacy_text(value: str, cfg: Config) -> str:
    if value is None:
        return ""
    if cfg.output.legacy_text:
        return value.replace(" ", " ").strip()
    return value


# What a field holds right now, as a person would say it - one property for text fields, selects, radio buttons and check boxes:
#   text field / textarea -> what is in it;  select -> the visible text of the selected option (several: joined with ";");
#   radio button -> the value of the checked button of its group (any button of the group will do), "" when none is checked;
#   check box -> "true" / "false".
CURRENT_VALUE_JS = """el => {
  const tag = el.tagName;
  if (tag === 'SELECT') return Array.from(el.selectedOptions).map(o => (o.textContent || '').trim()).join(';');
  if (tag === 'INPUT') {
    const type = (el.type || '').toLowerCase();
    if (type === 'radio') {
      const scope = el.form || el.getRootNode();
      const group = el.name ? Array.from(scope.querySelectorAll('input[type=radio]')).filter(r => r.name === el.name) : [el];
      const on = group.find(r => r.checked);
      return on ? on.value : '';
    }
    if (type === 'checkbox') return el.checked ? 'true' : 'false';
    return el.value;
  }
  if (tag === 'TEXTAREA') return el.value;
  return typeof el.value === 'string' ? el.value : '';
}"""

# Selenium's getAttribute: the live property when the element has one (value of a field you typed into, checked, href as a full URL), else the attribute.
ATTRIBUTE_JS = """(el, name) => {
  const key = name.toLowerCase();
  const flags = ['checked', 'selected', 'disabled', 'readonly', 'multiple', 'required', 'autofocus', 'hidden'];
  if (flags.includes(key)) return (key in el ? el[key] : el.hasAttribute(key)) ? 'true' : null;
  if (name in el) {
    const v = el[name];
    if (v !== null && v !== undefined && typeof v !== 'object' && typeof v !== 'function') return String(v);
  }
  return el.getAttribute(name);
}"""


async def _read_output(ctx: StepContext, res: Resolved) -> Callable[[], Awaitable[str | None]] | None:
    prop = ctx.step.output_property
    loc = res.locator
    if prop == "VALUE":
        async def read_value() -> str:
            return str(await loc.evaluate(CURRENT_VALUE_JS, timeout=2000) or "")
        return read_value
    if prop == "INNERTEXT":
        window = ctx.value_text.strip()

        async def read_text() -> str:
            text = legacy_text(await loc.evaluate(VISIBLE_TEXT_JS, timeout=2000), ctx.cfg)
            if window and ":" in window:
                lo, _, hi = window.partition(":")
                text = text[int(lo):int(hi)]
            return text
        return read_text
    if prop == "ATTRIBUTE":
        name = ctx.value_text.strip()

        async def read_attr() -> str:
            return (await loc.evaluate(ATTRIBUTE_JS, name, timeout=2000)) or ""
        return read_attr
    if prop == "COUNT":
        async def read_count() -> str:
            scope = await ctx.session.scope()
            return str(await scope.locator(res.strategy.selector).count())
        return read_count
    if prop in ("SELECTEDITEM", "SELECTEDITEMS"):
        first = prop == "SELECTEDITEM"

        async def read_selected() -> str:
            items = await loc.evaluate(
                "e => Array.from(e.selectedOptions || []).map(o => (o.textContent || '').trim())", timeout=2000)
            return (items[0] if items else "") if first else ";".join(items)
        return read_selected
    return None


async def _poll(read: Callable[[], Awaitable[str | None]], accept: Callable[[str], bool] | None,
                timeout_s: float, poll_s: float, stable_ms: int, stable_max_ms: int, give_up=None) -> str:
    """Read until ``accept`` (if any) is satisfied; otherwise until the value stops changing.  ``give_up`` (async, optional) replaces the
    ``timeout_s`` clock: a patient wait (engine/patience.py) that goes on while the page is still loading."""
    last, started = "", time.monotonic()
    stable_since = started
    first = True
    while True:
        try:
            value = await read()
            value = "" if value is None else value
        except Exception:
            value = last if not first else ""              # element re-rendering: keep looking
        first = False
        if accept is not None:
            if accept(value):
                return value
            last = value
            if (await give_up()) if give_up is not None else time.monotonic() - started >= timeout_s:
                return value
            await asyncio.sleep(poll_s)
            continue
        now = time.monotonic()
        if value != last:
            last, stable_since = value, now
        if now - stable_since >= stable_ms / 1000 or now - started >= stable_max_ms / 1000:
            return last
        await asyncio.sleep(0.05)


@action("OUTPUT", element=True)
async def output(ctx: StepContext) -> None:
    res = await ctx.element()
    if res is None:
        return
    read = await _read_output(ctx, res)
    if read is None:
        ctx.out.notes.append("no Output_Property: nothing captured")
        return
    step = ctx.step
    if step.output_property == "INNERTEXT" and "option" in step.findby_value.lower():
        ctx.out.notes.append("this reads the text of an <option>, which is the same whether or not it is selected; to check the selection use "
                             "Output_Property = value on the <select>")
    accept = None
    if step.exact_match or step.contains:
        accept = lambda actual: compare_ok(step, actual)[0]        # read again until the expected text appears (the page may still be filling it in)
    with _patient(ctx, ctx.cfg.output.match_timeout_s, "the expected text", "the expected text did not appear") as pat:
        text = await _poll(read, accept, ctx.cfg.output.match_timeout_s, ctx.cfg.timeouts.poll_ms / 1000,
                           ctx.cfg.output.stable_ms, ctx.cfg.output.stable_max_ms, give_up=pat.give_up if accept is not None else None)
    ctx.out.output = text


# ---------------------------------------------------------------------------------------------
# Variables and flow (CONTRACT.md 1.3)
# ---------------------------------------------------------------------------------------------
@action("SET_VARIABLE")
async def set_variable(ctx: StepContext) -> None:
    """Output_Value = the variable, Value = its value (text, ``{NAME}``s, a formula).  The runtime puts it in the run's pool (and the Params cell
    when the test has that column): ``TestRuntime.record``."""
    if not ctx.step.output_name:
        raise ActionError("SET_VARIABLE needs the variable's name in Output_Value (e.g. ORDER_ID or {ORDER_ID})")
    ctx.out.output = "" if is_blank(ctx.step.value) else ctx.value_text


_JSON_INDEX = re.compile(r"\[(\d+)\]")


@action("JSON_READ")
async def json_read(ctx: StepContext) -> None:
    """Read one value out of a JSON text.  Value = the JSON (usually ``{RESPONSE}``, a variable an API step or another step saved), FindBy_Value =
    the path (``policy.number``, ``items[0].id``; ``/`` works as a separator too), Output_Value = the variable to save it in, Expected_Value with
    Exact_Match / Contains = the check.  A path that does not exist fails the step (it never "reads" an empty value)."""
    import json
    from ..workbook.api import _MISSING, json_find, output_text
    text = ctx.value_text.strip()
    if not text:
        raise ActionError("JSON_READ has no JSON to read: Value is empty")
    try:
        data = json.loads(text)
    except ValueError as err:
        raise ActionError(f"Value is not JSON ({err.msg} at character {err.pos})") from None
    path = _JSON_INDEX.sub(r".[\1]", ctx.step.findby_value.strip())
    if not path:
        ctx.out.output = output_text(data) if not isinstance(data, str) else data
        return
    found = json_find(data, path)
    if found is _MISSING:
        raise ActionError(f"The JSON has nothing at {ctx.step.findby_value.strip()}")
    ctx.out.output = "" if found is None else (found if isinstance(found, str) else output_text(found))


def _flow_of(ctx: StepContext):
    if ctx.flow is None:
        raise ActionError(f"{ctx.step.method} only works in a test run")
    return ctx.flow


@action("IF")
async def if_step(ctx: StepContext) -> None:
    """Value = the condition (``{A} is filled``, ``{A} = x``, ``{A} > 3``...), on variables only.  The steps up to the matching ELSE / END_IF run only
    when it holds; the test runner does the jumping."""
    await _flow_of(ctx).branch(ctx)


@action("ELSE", "END_IF", "ITERATION_END")
async def flow_marker(ctx: StepContext) -> None:
    """Structure only: the test runner reads these rows itself and never runs them as steps."""


@action("ITERATION_START")
async def iteration_start(ctx: StepContext) -> None:
    """Value = a data sheet (blank = the test's own Params): the steps up to ITERATION_END run once per enabled row, ``{NAME}`` reading that row."""
    await _flow_of(ctx).loop(ctx)


@action("CALL_TEST")
async def call_test(ctx: StepContext) -> None:
    """Value = a test id (``Sheet`` or ``Sheet#n``): run it to the end (its own browser context; none for an API test), then carry on.  What it
    saves lands in the run's pool.  A called test that fails fails this step."""
    await _flow_of(ctx).call(ctx)


# ---------------------------------------------------------------------------------------------
# Safety steps, waits on evidence, popups, widgets and checks (CONTRACT.md 1.3, P07)
# ---------------------------------------------------------------------------------------------
def element_chain(ctx: StepContext) -> list[Strategy]:
    step = ctx.step
    chain = build_chain(step.findby, step.findby_value, step.locator_column, ctx.selector_map, legacy_fallback=ctx.cfg.selectors.legacy_fallback)
    if not chain:
        raise ActionError("No locator: FindBy/FindBy_Value are empty or FindBy is not recognised")
    return chain


async def _shown_in_chain(scope, chain: list[Strategy], index: int) -> Resolved | None:
    """The step's element when it is on the page *and shown*, else None (no waiting)."""
    for position, strategy in enumerate(chain):
        want = strategy.index if strategy.index is not None else index
        try:
            base = scope.locator(strategy.selector)
            count = await base.count()
            if count > want and await base.nth(want).is_visible():
                return Resolved(base.nth(want), strategy, position, count)
        except Exception:
            continue
    return None


def _fill_in(ctx: StepContext, text: str, what: str) -> str:
    """``{NAME}`` / ``{SECRET:NAME}`` in a fingerprint's cells (``{DOMAIN}`` in UrlContains...), from the test's variables."""
    runtime = ctx.runtime
    if runtime is None or "{" not in text:
        return text
    from ..workbook.variables import secret_value, substitute
    found: list[str] = []
    done = substitute(text, lambda n: runtime.value_of(n, found), lambda n: secret_value(n, runtime.environment))
    secrets = done.secrets + found
    if secrets:
        runtime.secret_values.update(secrets)
        ctx.secret_values.update(secrets)
    if done.missing or done.unmapped:
        names = ", ".join("{" + n + "}" for n in [*done.missing, *("?" + u for u in done.unmapped)])
        raise ActionError(f"{what} uses {names}, which has no value in this run")
    return done.text


# -- backup locators (Q49): report, never use ---------------------------------------------------------------------------------------------
BACKUP_SHOT_PAD = 40


async def _backup_screenshot(ctx: StepContext, locator) -> str | None:
    """A picture of what the backup locator found (the element and a margin around it), without scrolling or touching the page."""
    session = ctx.session
    if ctx.cfg.screenshots.mode == "off" or not session.is_open or getattr(session, "pending_dialog", None) is not None:
        return None
    page = session.page
    clip = None
    try:
        box = await locator.bounding_box(timeout=1500)
        if box and box["width"] > 0 and box["height"] > 0:
            sx, sy = await page.evaluate("() => [window.scrollX, window.scrollY]")
            x, y = max(box["x"] + sx - BACKUP_SHOT_PAD, 0), max(box["y"] + sy - BACKUP_SHOT_PAD, 0)
            clip = {"x": x, "y": y, "width": box["width"] + 2 * BACKUP_SHOT_PAD, "height": box["height"] + 2 * BACKUP_SHOT_PAD}
    except Exception:
        clip = None
    shot = {"type": "jpeg", "quality": ctx.cfg.screenshots.quality, "timeout": 5000, "animations": "disabled", "caret": "hide"}
    try:
        data = await page.screenshot(full_page=clip is not None, clip=clip, **shot) if clip else await page.screenshot(**shot)
    except Exception:
        try:
            data = await page.screenshot(**shot)                  # (the margin went past the page's edge: the window as it is)
        except Exception:
            return None
    path = ctx.test_dir / "screenshots" / f"{ctx.seq:04d}_r{ctx.step.row}_backup.jpg"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        return None
    return path.relative_to(ctx.test_dir.parent.parent).as_posix()


async def probe_backup_locators(ctx: StepContext, scope, chain: list[Strategy]) -> None:
    """The step's element was not found: look at its ``BACKUP_LOCATORS`` (CONTRACT.md 1.1) and say what they find.  The step still FAILS - a
    backup is never clicked, typed into or read (no silent healing, Q49); a person accepts the proposed locator in the Build tab, or not."""
    primary = {s.selector for s in chain}
    backups = [b for b in parse_backup_locators(ctx.step.text("BACKUP_LOCATORS")) if b.selector not in primary]
    if not backups or not ctx.session.is_open:
        return
    tried: list[dict[str, Any]] = []
    found: tuple[Strategy, int] | None = None
    for backup in backups:
        try:
            count = await asyncio.wait_for(scope.locator(backup.selector).count(), 3)
        except Exception:
            count = 0
        tried.append({"locator": backup.describe(), "matches": count})
        if count and found is None:
            found = (backup, count)
    if found is None:
        ctx.out.notes.append(f"none of the {len(backups)} backup locator{'s' if len(backups) != 1 else ''} matched either: "
                             + ", ".join(t["locator"] for t in tried))
        ctx.out.backup = {"locator": "", "matches": 0, "screenshot": None, "tried": tried}
        return
    backup, count = found
    shot = await _backup_screenshot(ctx, scope.locator(backup.selector).first)
    matches = f"{count} match{'es' if count != 1 else ''}"
    ctx.out.notes.append(f"backup locator {backup.describe()} found {matches}; the step still fails (a backup is never used by itself)")
    text = (f"Backup locator found {matches}: {backup.describe()}" + (f" (screenshot: {shot})" if shot else "") + ". "
            f"Proposed locator: {backup.describe()}. The step still failed and nothing was done with the backup: if it is the right element, "
            "accept the new locator in the Build tab.")
    ctx.out.detail = f"{ctx.out.detail}\n\n{text}" if ctx.out.detail else text
    ctx.out.backup = {"locator": backup.describe(), "matches": count, "screenshot": shot, "tried": tried}
    ctx.event("backup_locator_suggestion", locator=backup.describe(), matches=count, screenshot=shot)


# -- side-effect steps (Q13) --------------------------------------------------------------------------------------------------------------
async def side_effect_gate(ctx: StepContext) -> None:
    """A ``SIDE_EFFECTS=Y`` step (Purchase, Pay...): never on production; in a build-mode replay only after a person says so; else as usual."""
    runtime = ctx.runtime
    environment = (runtime.environment if runtime is not None else getattr(ctx.session, "environment", "")) or ""
    name = ctx.step.name or ctx.step.method
    step_words = f'Step {ctx.seq} "{name}"'
    if is_production(getattr(runtime, "env_table", None), environment):
        ctx.event("side_effect_blocked", name=name, environment=environment)
        ctx.out.hard = True
        ctx.out.stop = (f"{step_words} has real consequences (SIDE_EFFECTS=Y) and {environment} is a production environment, so it was blocked "
                        "and the steps after it were not run.")
        raise ActionError(f"Blocked: this step has real consequences (SIDE_EFFECTS=Y) and never runs in a production environment ({environment}). "
                          "It was not run.")
    if ctx.side_effects != "ask":
        return
    ctx.event("side_effect_paused", name=name, environment=environment)
    question = (f"{step_words} has real consequences (SIDE_EFFECTS=Y) in {environment or 'this environment'}. Run it for real? "
                "Answer yes to run it; anything else stops here.")
    try:
        answer = await ask_person(ctx, question, secret=False)
    except ActionError as err:
        ctx.out.hard = True
        ctx.out.stop = f"{step_words} has real consequences and nobody confirmed it ({err}), so it and the steps after it were not run."
        raise ActionError(f"Not run: this step has real consequences and was not confirmed ({err})") from None
    if answer.strip().lower() not in ("y", "yes", "run"):
        ctx.out.hard = True
        ctx.out.stop = f"{step_words} has real consequences and the person chose not to run it, so it and the steps after it were not run."
        raise ActionError("Not run: this step has real consequences and the person chose not to run it")
    ctx.out.notes.append("a person confirmed this step with real consequences before it ran")


# -- ASSERT_PAGE (Q53): the page-arrival gate ---------------------------------------------------------------------------------------------
_LANDMARK_JS = """els => els.slice(0, 50).map(e => {
  const shown = (typeof e.checkVisibility === 'function' ? e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) : true)
      && e.getClientRects().length > 0;
  return {shown, text: shown ? (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 300) : ''};
})"""


async def _landmark(page, strategy: Strategy, text: str) -> dict[str, Any]:
    """Is the landmark shown (and does it say ``text``)?  {ok, found, why}."""
    try:
        items = await page.locator(strategy.selector).evaluate_all(_LANDMARK_JS)
    except Exception:
        items = []                                                  # a page load in flight: not there yet
    shown = [i for i in items if i["shown"]]
    where = strategy.describe()
    if not items:
        return {"ok": False, "found": False, "why": f"the landmark {where} is not on the page"}
    if not shown:
        return {"ok": False, "found": False, "why": f"the landmark {where} is on the page but not shown"}
    if text and not any(text.lower() in i["text"].lower() for i in shown):
        return {"ok": False, "found": True, "why": f"the landmark {where} shows but does not say {text!r} (it says {shown[0]['text'][:80]!r})"}
    return {"ok": True, "found": True, "why": ""}


@action("ASSERT_PAGE")
async def assert_page(ctx: StepContext) -> None:
    """Value = a page fingerprint (``_rr_fingerprints``).  Passes when the URL contains its URL part AND its landmark shows (with its text), within
    the step's time (a page still loading is waited for).  A failure is always a hard stop, whatever Ignore_not_existing_object says: every step
    after it would act on the wrong page."""
    ctx.out.hard = True
    name = ctx.value_text.strip()
    step_words = f'Step {ctx.seq} "{ctx.step.name or "ASSERT_PAGE"}"'

    def stop(why: str) -> ActionError:
        ctx.out.stop = f"{step_words}: the page gate {name or '(no name)'} failed ({why}), so the steps after it were not run."
        return ActionError(why[:1].upper() + why[1:])
    if not name:
        raise stop("ASSERT_PAGE needs the name of a page fingerprint in Value")
    book = getattr(getattr(ctx.runtime, "book", None), "data", None)
    fingerprint = read_fingerprints(book).get(name.upper()) if book is not None else None
    if fingerprint is None:
        raise stop(f"there is no page fingerprint called {name!r} in this workbook (define it in the Build tab, page fingerprints)")
    try:
        url_part = _fill_in(ctx, fingerprint.url_contains, f"The fingerprint {fingerprint.name}")
        landmark = _fill_in(ctx, fingerprint.landmark, f"The fingerprint {fingerprint.name}")
        landmark_text = _fill_in(ctx, fingerprint.landmark_text, f"The fingerprint {fingerprint.name}")
        strategy = parse_locator(landmark, "fingerprint") if landmark else None
    except (ActionError, ValueError) as err:
        raise stop(str(err)) from None
    if not url_part and strategy is None:
        raise stop(f"the fingerprint {fingerprint.name} has neither a URL part nor a landmark to check")
    session = ctx.session
    url, url_ok, mark = "", False, {"ok": strategy is None, "found": strategy is None, "why": ""}
    with _patient(ctx, ctx.act_timeout_s, f"the page {fingerprint.name}", f"the page did not become {fingerprint.name}") as pat:
        while True:
            if getattr(session, "pending_dialog", None) is not None:
                mark = {"ok": False, "found": False, "why": "a dialog is open over the page"}
                url = session.page.url
                break
            page = session.page
            url = page.url
            url_ok = not url_part or url_part.lower() in url.lower()
            if strategy is not None:
                mark = await _landmark(page, strategy, landmark_text)
            if url_ok and mark["ok"]:
                break
            if await pat.give_up():
                break
            await asyncio.sleep(0.15)
    from .session import mask_url
    passed = url_ok and mark["ok"]
    ctx.out.output = url
    ctx.event("page_gate", fingerprint=fingerprint.name, passed=passed, url=mask_url(url), landmark_found=bool(mark["found"]))
    if passed:
        what = [f"the URL contains {url_part!r}"] if url_part else []
        what += [f"{landmark} shows" + (f" and says {landmark_text!r}" if landmark_text else "")] if strategy is not None else []
        ctx.out.notes.append(f"arrived at {fingerprint.name}: " + " and ".join(what))
        return
    parts = ([] if url_ok else [f"the URL does not contain {url_part!r} (it is {mask_url(url) or url})"]) + ([] if mark["ok"] else [mark["why"]])
    if pat.reason:
        ctx.out.notes.append(f"waited: {pat.explain()}")
    raise stop(f"not on the page {fingerprint.name}: " + " and ".join(parts))


# -- WAIT_UNTIL (Q41): shows / gone / text is ----------------------------------------------------------------------------------------------
_WAIT_KINDS = {"": "SHOWN", "SHOWN": "SHOWN", "SHOWS": "SHOWN", "VISIBLE": "SHOWN", "APPEARS": "SHOWN",
               "GONE": "GONE", "HIDDEN": "GONE", "DISAPPEARS": "GONE", "NOT_SHOWN": "GONE", "TEXT": "TEXT", "TEXT_IS": "TEXT"}
READ_TEXT_JS = ("el => (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) ? (" + CURRENT_VALUE_JS + ")(el) : (" + VISIBLE_TEXT_JS + ")(el))")


def _text_holds(ctx: StepContext, actual: str) -> tuple[bool, str]:
    """Expected_Value against ``actual``: Contains=Y (or neither flag) = contains, case-insensitive; Exact_Match=Y = exactly."""
    expected = normalize_expected(ctx.step.expected)
    if ctx.step.exact_match and not ctx.step.contains:
        return expected == actual, "exact"
    return expected.upper().strip() in actual.upper().strip(), "contains"


@action("WAIT_UNTIL")
async def wait_until(ctx: StepContext) -> None:
    """Output_Property = SHOWN (default) / GONE / TEXT (Expected_Value, with Exact_Match / Contains).  Waits on the page itself - never a fixed
    time - for up to the step's Timeout once the page has finished loading (a page still working is waited for)."""
    step = ctx.step
    kind = _WAIT_KINDS.get(step.output_property.replace(" ", "_"))
    if kind is None:
        ctx.out.hard = True
        raise ActionError(f"WAIT_UNTIL: Output_Property {step.output_property!r} is not SHOWN, GONE or TEXT")
    if kind == "TEXT" and is_blank(step.expected):
        ctx.out.hard = True
        raise ActionError("WAIT_UNTIL TEXT needs the text to wait for in Expected_Value")
    chain = element_chain(ctx)
    what = {"SHOWN": "the element to show", "GONE": "the element to go away", "TEXT": "the element's text"}[kind]
    missing = {"SHOWN": "the element did not show", "GONE": "the element was still shown", "TEXT": "the text did not appear"}[kind]
    text, holds = "", False
    started = time.monotonic()
    with _patient(ctx, ctx.act_timeout_s, what, missing) as pat:
        while True:
            scope = await ctx.session.scope()
            res = await _shown_in_chain(scope, chain, step.index)
            if kind == "SHOWN":
                holds = res is not None
            elif kind == "GONE":
                holds = res is None
            elif res is not None:
                try:
                    text = legacy_text(str(await res.locator.evaluate(READ_TEXT_JS, timeout=1500) or ""), ctx.cfg)
                except Exception:
                    text = ""
                holds = _text_holds(ctx, text)[0]
            if holds or await pat.give_up():
                break
            await asyncio.sleep(ctx.cfg.timeouts.poll_ms / 1000)
    waited = time.monotonic() - started
    if kind == "TEXT":
        ok, mode = _text_holds(ctx, text)
        ctx.out.output, ctx.out.check = text, mode
        if not ok:
            ctx.out.check_failed = f"waited {waited:.1f} s and the text is {text!r}, not {normalize_expected(step.expected)!r}: {pat.explain()}"
            ctx.out.notes.append(ctx.out.check_failed)
        return
    ctx.out.output = "shown" if (kind == "SHOWN") == holds else "gone"
    if not holds:
        raise ActionError(f"{missing[0].upper()}{missing[1:]} (waited {waited:.1f} s): {pat.explain()}")
    ctx.out.notes.append(f"{'shown' if kind == 'SHOWN' else 'gone'} after {waited:.1f} s")


# -- DISMISS_IF_SHOWN (Q25): a known interruption -----------------------------------------------------------------------------------------
@action("DISMISS_IF_SHOWN")
async def dismiss_if_shown(ctx: StepContext) -> None:
    """The element is the popup's close button: clicked when it shows within the step's Timeout (default ``timeouts.optional_s``, a page still
    loading is waited for).  Always logged: "appeared" or "did not appear".  Never fails because it did not appear."""
    step = ctx.step
    chain = element_chain(ctx)
    limit = float(step.timeout) if step.timeout else ctx.cfg.timeouts.optional_s
    res = None
    started = time.monotonic()
    with _patient(ctx, limit, "the popup", "the popup did not appear") as pat:
        while True:
            res = await _shown_in_chain(await ctx.session.scope(), chain, step.index)
            if res is not None or await pat.give_up():
                break
            await asyncio.sleep(ctx.cfg.timeouts.poll_ms / 1000)
    waited = time.monotonic() - started
    if res is None:
        ctx.out.output = "did not appear"
        ctx.out.notes.append(f"the popup did not appear (looked for {waited:.1f} s); nothing to close")
        ctx.event("popup_dismissed", appeared=False)
        return
    ctx.out.obj_exists, ctx.out.target = True, res.locator
    ctx.out.locator, ctx.out.locator_origin = res.strategy.describe(), res.strategy.origin
    ctx.event("popup_dismissed", appeared=True)
    ctx.out.output = "appeared"
    await click_and_verify(ctx, res, lambda: pointer(ctx, res))
    ctx.out.notes.append(f"the popup appeared after {waited:.1f} s and was closed")


# -- PICK_DATE (Q51): one step for a date picker ------------------------------------------------------------------------------------------
_FIELD_INFO_JS = """e => ({tag: e.tagName, type: (e.type || '').toLowerCase(), readonly: !!e.readOnly || e.getAttribute('aria-readonly') === 'true',
  placeholder: e.getAttribute('placeholder') || ''})"""
_DAY_CELLS = "[data-date], [aria-label], [title], td[data-month][data-year]"
# the visible, pickable day cell for the date (data-date, a jQuery UI cell, or an aria-label / title that names the date), as an index into _DAY_CELLS
_FIND_DAY_JS = r"""(els, want) => {
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const texts = want.texts.map(t => new RegExp('(^|[^0-9A-Za-z])' + esc(t) + '($|[^0-9A-Za-z])', 'i'));
  for (let i = 0; i < els.length; i++) {
    const e = els[i];
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(e).visibility === 'hidden') continue;
    if (e.disabled || e.getAttribute('aria-disabled') === 'true' || /\b(disabled|unselectable)\b/.test(e.className || '')) continue;
    if (e.matches('input, textarea, select')) continue;
    const dd = e.getAttribute('data-date');
    if (dd !== null) { if (want.exact.includes(dd.trim())) return i; continue; }
    if (e.tagName === 'TD' && e.hasAttribute('data-month') && e.hasAttribute('data-year')) {
      if (+e.getAttribute('data-year') === want.y && +e.getAttribute('data-month') === want.m0 && (e.textContent || '').trim() === String(want.d)) return i;
      continue;
    }
    const label = (e.getAttribute('aria-label') || '') + ' | ' + (e.getAttribute('title') || '');
    if (texts.some(re => re.test(label))) return i;
  }
  return -1;
}"""
_MONTH_HEADINGS_JS = r"""() => {
  const out = [];
  const re = /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+\d{4}$/i;
  for (const e of document.querySelectorAll('body *')) {
    if (e.children.length > 3 || e.matches('option, script, style')) continue;
    const t = (e.textContent || '').replace(/\s+/g, ' ').trim();
    if (t.length > 20 || !re.test(t)) continue;
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    out.push(t);
    if (out.length > 8) break;
  }
  return out;
}"""
_NEXT_MONTH = ('[aria-label*="next month" i]', '[title*="next month" i]', ".ui-datepicker-next", '[aria-label*="next" i]', '[title*="next" i]',
               'button:text-is("›")', 'button:text-is("»")', 'button:text-is(">")', 'a:text-is("›")', 'a:text-is("»")', 'a:text-is("Next")')
_PREV_MONTH = ('[aria-label*="previous month" i]', '[title*="previous month" i]', '[aria-label*="prev" i]', '[title*="prev" i]',
               ".ui-datepicker-prev", 'button:text-is("‹")', 'button:text-is("«")', 'button:text-is("<")', 'a:text-is("‹")', 'a:text-is("«")',
               'a:text-is("Prev")')
MAX_MONTHS = 120


async def _first_shown(scope, selectors) -> Any:
    for selector in selectors:
        try:
            loc = scope.locator(selector)
            for i in range(min(await loc.count(), 10)):
                if await loc.nth(i).is_visible():
                    return loc.nth(i)
        except Exception:
            continue
    return None


async def _shown_months(scope) -> list[tuple[int, int]]:
    try:
        texts = await scope.evaluate(_MONTH_HEADINGS_JS)
    except Exception:
        return []
    return sorted({m for m in (checks.month_index(t) for t in texts) if m is not None})


async def _pick_from_calendar(ctx: StepContext, res: Resolved, target) -> None:
    """A read-only date field: open its calendar, move month by month to the date's month, click the day."""
    await click_and_verify(ctx, res, lambda: pointer(ctx, res))
    scope = await ctx.session.scope()
    want = {"texts": checks.date_texts(target)[3:], "exact": checks.date_texts(target)[:3], "y": target.year, "m0": target.month - 1, "d": target.day}
    goal = (target.year, target.month)
    label = f"{target.day} {target:%B %Y}"
    moves = 0
    with _patient(ctx, ctx.act_timeout_s, "the date picker", "no date picker showed the date") as pat:
        while True:
            cells = scope.locator(_DAY_CELLS)
            try:
                at = await cells.evaluate_all(_FIND_DAY_JS, want)
            except Exception:
                at = -1
            if at >= 0:
                await cells.nth(at).click(timeout=act_ms(ctx))
                ctx.out.notes.append(f"picked {label} in the date picker" + (f" ({moves} month{'s' if moves != 1 else ''} along)" if moves else ""))
                return
            months = await _shown_months(scope)
            if not months or months[0] <= goal <= months[-1]:
                if await pat.give_up():
                    if not months:
                        raise ActionError("No date picker showed after clicking the date field (nothing on the page shows a month such as "
                                          f"'{target:%B %Y}')")
                    raise ActionError(f"The date picker shows {target:%B %Y} but {label} cannot be picked in it (the day is disabled, or the "
                                      "calendar marks its days in a way this step does not know)")
                await asyncio.sleep(0.15)
                continue
            if moves >= MAX_MONTHS:
                raise ActionError(f"Moved {moves} months in the date picker without reaching {target:%B %Y}")
            forward = goal > months[-1]
            button = await _first_shown(scope, _NEXT_MONTH if forward else _PREV_MONTH)
            if button is None:
                raise ActionError(f"The date picker shows {months[0][1]:02d}/{months[0][0]} and has no {'next' if forward else 'previous'} month "
                                  "button this step can find")
            await button.click(timeout=act_ms(ctx))
            moves += 1
            for _ in range(20):                                     # the calendar redraws: wait until it shows another month
                await asyncio.sleep(0.1)
                if await _shown_months(scope) != months:
                    break


@action("PICK_DATE", element=True)
async def pick_date(ctx: StepContext) -> None:
    """The element is the date field, Value the date (``15/03/2027``, ``2027-03-15``, a date cell...).  A browser date field is set; a field
    that takes typing gets the date typed (in the shape its placeholder shows, such as DD/MM/YYYY); a read-only field opens its calendar and the
    day is clicked.  The field must then show the date."""
    step = ctx.step
    try:
        target = checks.parse_date(step.value)
    except ValueError as err:
        ctx.out.hard = True
        raise ActionError(f"PICK_DATE: {err}") from None
    res = await ctx.element()
    if res is None:
        return
    info = await res.locator.evaluate(_FIELD_INFO_JS, timeout=act_ms(ctx))
    if info["type"] in ("date", "datetime-local", "month"):
        text = {"date": target.isoformat(), "datetime-local": f"{target.isoformat()}T00:00", "month": f"{target:%Y-%m}"}[info["type"]]
        await res.locator.fill(text, timeout=act_ms(ctx))
        ctx.out.notes.append(f"a browser date field: set to {text}")
    elif info["tag"] in ("INPUT", "TEXTAREA") and not info["readonly"]:
        if checks.looks_like_date_format(info["placeholder"]):
            text = checks.format_date(target, info["placeholder"])
        elif isinstance(step.value, str) and step.value.strip():
            text = step.value.strip()
        else:
            text = checks.format_date(target, "dd/mm/yyyy")
        await type_into(ctx, res, text, clear_first=True)
        ctx.out.notes.append(f"typed {text}")
    else:
        await _pick_from_calendar(ctx, res, target)
    shown = (await _field_value(res.locator) or "").strip()
    is_field = info["tag"] in ("INPUT", "TEXTAREA", "SELECT")
    if not shown and not is_field:                                     # a box that only shows the date (a "Depart" div): read what it says now
        try:
            shown = " ".join((await res.locator.first.inner_text(timeout=800)).split())
        except Exception:
            shown = ""
    ctx.out.output = shown
    if not shown and is_field:
        raise ActionError(f"The date {target:%d/%m/%Y} was picked but the field is empty")
    try:
        got = checks.parse_date(shown)
    except ValueError:
        got = None                                                     # a shape this step cannot read (US order, a weekday...): what it shows is the output
    if got is not None and got != target:
        raise ActionError(f"The field shows {shown!r}, not the date {target:%d/%m/%Y}")


# -- CHOOSE_SUGGESTION (Q51): autocomplete ------------------------------------------------------------------------------------------------
_SUGGESTIONS = ('[role="option"]', '[role="listbox"] li', ".ui-menu-item", 'li[class*="suggestion" i]', '[class*="suggestion" i] li',
                '[class*="autocomplete" i] li', '[class*="typeahead" i] li')
_ITEMS_JS = """els => els.slice(0, 100).map(e => {
  const r = e.getBoundingClientRect();
  const shown = r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
  return shown ? (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim() : null;
})"""


def _suggestion_matches(texts: list, want: str, exact: bool, allow_contains: bool = True) -> int:
    """Index of the suggestion to choose: the same text (case-insensitive; Exact_Match = exactly), else - unless Exact_Match - one containing it."""
    target = want.strip()
    for i, t in enumerate(texts):
        if t is not None and (t.strip() == target if exact else t.strip().lower() == target.lower()):
            return i
    if exact or not allow_contains:
        return -1
    for i, t in enumerate(texts):
        if t is not None and target.lower() in t.lower():
            return i
    return -1


@action("CHOOSE_SUGGESTION", element=True)
async def choose_suggestion(ctx: StepContext) -> None:
    """The element is the input: Value is typed into it, then the suggestion named by Expected_Value (blank = Value) is clicked in the list the
    site shows (same text first, then one that contains it; Exact_Match=Y = the same text only).  Output = the suggestion chosen."""
    step = ctx.step
    typed = ctx.value_text
    want = normalize_expected(step.expected).strip() or typed.strip()
    if not typed.strip():
        ctx.out.hard = True
        raise ActionError("CHOOSE_SUGGESTION needs the text to type in Value")
    res = await ctx.element()
    if res is None:
        return
    await type_into(ctx, res, typed, clear_first=True)
    listed = await res.locator.evaluate("e => e.list ? Array.from(e.list.options).map(o => o.value) : null", timeout=act_ms(ctx))
    if listed is not None:                                             # a <datalist>: the browser draws it, the page cannot click it
        at = _suggestion_matches(listed, want, step.exact_match)
        if at < 0:
            raise ActionError(f"No suggestion {want!r} in the field's list (it has: {' | '.join(listed[:8]) or 'nothing'})")
        if (await _field_value(res.locator) or "") != listed[at]:
            await res.locator.fill(listed[at], timeout=act_ms(ctx))
        ctx.out.output = listed[at]
        return
    owned = await res.locator.evaluate("e => e.getAttribute('aria-controls') || e.getAttribute('aria-owns') || ''", timeout=act_ms(ctx))
    selectors = ([f'[id="{owned}"] [role="option"]', f'[id="{owned}"] li'] if owned else []) + list(_SUGGESTIONS)
    scope = await ctx.session.scope()
    seen: list[str] = []
    chosen = None
    with _patient(ctx, ctx.act_timeout_s, "the suggestions", "no matching suggestion appeared") as pat:
        while chosen is None:
            lists = []
            for selector in selectors:
                try:
                    lists.append((selector, await scope.locator(selector).evaluate_all(_ITEMS_JS)))
                except Exception:
                    continue
            seen = list(dict.fromkeys(t for _, texts in lists for t in texts if t))
            for allow_contains in (False, True):                      # the same text in any list before one that only contains it
                for selector, texts in lists:
                    at = _suggestion_matches(texts, want, step.exact_match, allow_contains)
                    if at >= 0:
                        chosen = (selector, at, texts[at])
                        break
                if chosen:
                    break
            if chosen is None:
                if await pat.give_up():
                    shown = f"shown: {' | '.join(seen[:8])}" if seen else "no suggestion list showed"
                    raise ActionError(f"No suggestion {want!r} appeared after typing {typed!r} ({shown}): {pat.explain()}")
                await asyncio.sleep(0.15)
    selector, at, text = chosen
    pick = Resolved(scope.locator(selector).nth(at), Strategy("css", selector, selector, "auto"), 0, 1)
    await click_and_verify(ctx, pick, lambda: pointer(ctx, pick))
    ctx.out.output = text
    ctx.out.notes.append(f"chose {text!r}; the field shows {(await _field_value(res.locator) or '')!r}")


# -- checks -------------------------------------------------------------------------------------------------------------------------------
_ENABLED_JS = ("e => {\n  " + DISABLED_BY_JS + "\n  const off = disabledBy(e);\n  return off ? 'N:' + off.kind : 'Y';\n}")
_CHECKED_JS = """e => {
  const c = e.matches('input[type=radio],input[type=checkbox]') ? e : (e.tagName === 'LABEL' && e.control ? e.control : null);
  if (c && /^(radio|checkbox)$/.test(c.type)) return c.checked ? 'Y' : 'N';
  const aria = (e.getAttribute('aria-checked') || e.getAttribute('aria-pressed') || e.getAttribute('aria-selected') || '').toLowerCase();
  if (aria) return aria === 'true' || aria === 'mixed' ? 'Y' : 'N';
  return null;
}"""
_SELECTED_JS = "e => e.tagName === 'SELECT' ? Array.from(e.selectedOptions).map(o => (o.textContent || '').trim()).join(';') : null"


def _check_limit(ctx: StepContext) -> float:
    return float(ctx.step.timeout) if ctx.step.timeout else ctx.cfg.output.match_timeout_s


async def _check_element(ctx: StepContext, kind: str, js: str, judge: Callable[[str], tuple[bool, str]], *, not_applicable: str = "") -> None:
    """Read the element with ``js`` until ``judge`` holds (the page may still be filling it in) or the page has been finished for the check's
    time.  Reading again is looking, never acting: nothing is clicked or typed.  ``js`` returning null = the element cannot be checked this way."""
    res = await ctx.element()
    if res is None:
        return
    unfit = False

    async def read() -> str:
        nonlocal unfit
        value = await res.locator.evaluate(js, timeout=2000)
        unfit = value is None
        return "" if value is None else legacy_text(str(value), ctx.cfg)
    limit = _check_limit(ctx)
    with _patient(ctx, limit, "the expected value", "the expected value did not appear") as pat:
        value = await _poll(read, lambda v: not unfit and judge(v)[0], limit, ctx.cfg.timeouts.poll_ms / 1000,
                            ctx.cfg.output.stable_ms, ctx.cfg.output.stable_max_ms, give_up=pat.give_up)
    if unfit:
        ctx.out.hard = True
        raise ActionError(not_applicable or f"{ctx.step.method} cannot read this element")
    ok, why = judge(value)
    ctx.out.output, ctx.out.check = value, kind
    if not ok:
        ctx.out.check_failed = why
        ctx.out.notes.append(why)


def _needs(ctx: StepContext, error: str):
    ctx.out.hard = True
    return ActionError(error)


@action("CHECK_VALUE", element=True)
async def check_value(ctx: StepContext) -> None:
    """The field's current value (text field, select, radio group, check box) against Expected_Value: exactly, or Contains=Y."""
    expected = normalize_expected(ctx.step.expected)
    contains = ctx.step.contains and not ctx.step.exact_match

    def judge(actual: str) -> tuple[bool, str]:
        ok = expected.upper().strip() in actual.upper().strip() if contains else expected == actual
        return ok, f"expected {expected!r}{' in it' if contains else ''}, the field holds {actual!r}"
    await _check_element(ctx, "contains" if contains else "exact", READ_TEXT_JS, judge)


@action("CHECK_REGEX", element=True)
async def check_regex(ctx: StepContext) -> None:
    """The element's text (a field's value) matches the pattern in Expected_Value (Python regular expression, found anywhere in the text)."""
    raw = normalize_expected(ctx.step.expected)
    if not raw:
        raise _needs(ctx, "CHECK_REGEX needs the pattern in Expected_Value")
    try:
        pattern = re.compile(raw)
    except re.error as err:
        raise _needs(ctx, f"CHECK_REGEX: {raw!r} is not a valid pattern ({err})") from None
    await _check_element(ctx, "regex", READ_TEXT_JS, lambda v: (pattern.search(v) is not None, f"{v!r} does not match the pattern {raw!r}"))


@action("CHECK_COMPARE", element=True)
async def check_compare(ctx: StepContext) -> None:
    """The number in the element's text ("$1,234.50" -> 1234.5) compared with Expected_Value: Output_Property GT / GE / LT / LE / EQ / NE, or
    BETWEEN with ``low;high`` (both included)."""
    try:
        op = checks.operator_of(ctx.step.output_property)
        low, high = checks.expected_numbers(op, ctx.step.expected)
    except ValueError as err:
        raise _needs(ctx, f"CHECK_COMPARE: {err}") from None

    def judge(text: str) -> tuple[bool, str]:
        number = checks.parse_number(text)
        if number is None:
            return False, f"the element shows no number ({text[:80]!r})"
        return checks.compare(op, number, low, high), f"{checks.number_text(number)} is not {checks.describe(op, low, high)}"
    await _check_element(ctx, "compare", READ_TEXT_JS, judge)


@action("CHECK_COUNT")
async def check_count(ctx: StepContext) -> None:
    """How many elements the locator matches, against Expected_Value (Output_Property: the operator, blank = EQ).  Zero is a count like any other,
    so an element that is not there is not a failure of its own here."""
    try:
        op = checks.operator_of(ctx.step.output_property)
        low, high = checks.expected_numbers(op, ctx.step.expected)
    except ValueError as err:
        raise _needs(ctx, f"CHECK_COUNT: {err}") from None
    chain = element_chain(ctx)

    async def read() -> str:
        scope = await ctx.session.scope()
        for strategy in chain:                                          # the first locator of the chain that matches anything (as a step finds its element)
            try:
                count = await scope.locator(strategy.selector).count()
            except Exception:
                continue
            if count:
                ctx.out.locator = strategy.describe()
                return str(count)
        return "0"
    judge = lambda v: (checks.compare(op, float(v), low, high), f"{v} element{'s' if v != '1' else ''} match, not {checks.describe(op, low, high)}")
    limit = _check_limit(ctx)
    with _patient(ctx, limit, "the expected count", "the count did not become right") as pat:
        value = await _poll(read, lambda v: judge(v)[0], limit, ctx.cfg.timeouts.poll_ms / 1000, ctx.cfg.output.stable_ms,
                            ctx.cfg.output.stable_max_ms, give_up=pat.give_up)
    ok, why = judge(value)
    ctx.out.output, ctx.out.check = value, "count"
    if not ok:
        ctx.out.check_failed = why
        ctx.out.notes.append(why)


def _yes_no_expected(ctx: StepContext) -> bool:
    want = checks.yes_no(ctx.step.expected)
    if want is None:
        raise _needs(ctx, f"{ctx.step.method} needs Y or N in Expected_Value")
    return want


@action("CHECK_ENABLED", element=True)
async def check_enabled(ctx: StepContext) -> None:
    """Expected_Value Y = the element can be used, N = it is disabled (a disabled control, a disabled fieldset, or aria-disabled="true")."""
    want = _yes_no_expected(ctx)

    def judge(v: str) -> tuple[bool, str]:
        enabled = v == "Y"
        return enabled == want, ("the element is enabled" if enabled else f"the element is disabled ({v[2:]})") + f", expected {'Y' if want else 'N'}"
    await _check_element(ctx, "enabled", _ENABLED_JS, judge)
    ctx.out.output = (ctx.out.output or "")[:1]


@action("CHECK_CHECKED", element=True)
async def check_checked(ctx: StepContext) -> None:
    """Expected_Value Y = ticked / selected (check box, radio button, its label, or aria-checked), N = not."""
    want = _yes_no_expected(ctx)
    await _check_element(ctx, "checked", _CHECKED_JS,
                         lambda v: ((v == "Y") == want, f"the element is {'ticked' if v == 'Y' else 'not ticked'}, expected {'Y' if want else 'N'}"),
                         not_applicable="CHECK_CHECKED: the element is not a check box or radio button (and has no aria-checked)")


@action("CHECK_SELECTED", element=True)
async def check_selected(ctx: StepContext) -> None:
    """The selected option's text of a ``<select>`` against Expected_Value (same text; Contains=Y = contains it, case-insensitive)."""
    expected = normalize_expected(ctx.step.expected).strip()
    contains = ctx.step.contains and not ctx.step.exact_match

    def judge(actual: str) -> tuple[bool, str]:
        ok = expected.upper() in actual.upper() if contains else expected == actual.strip()
        return ok, f"the selected option is {actual!r}, expected {expected!r}"
    await _check_element(ctx, "selected", _SELECTED_JS, judge, not_applicable="CHECK_SELECTED: the element is not a <select>")


_LIST_ITEM_JS = """(e, n) => {
  const shown = x => { const r = x.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(x).visibility !== 'hidden'; };
  if (!shown(e)) return 'H:';
  let items = Array.from(e.querySelectorAll('li, [role="option"], [role="listitem"], tr')).filter(shown);
  if (!items.length) items = Array.from(e.children).filter(shown);
  if (items.length < n) return 'N:' + items.length;
  return 'T:' + (items[n - 1].innerText || items[n - 1].textContent || '').replace(/\\s+/g, ' ').trim();
}"""


@action("CHECK_LIST_ITEM", element=True)
async def check_list_item(ctx: StepContext) -> None:
    """A list that must be *showing* (a suggestion list, a dropdown's options): its Nth visible item (Output_Property, blank = 1) against
    Expected_Value (same text; Contains=Y = contains it, case-insensitive).  A list that is not visible fails, whatever the page holds in its DOM."""
    raw = str(ctx.step.output_property or "").strip()
    try:
        number = int(float(raw)) if raw else 1
        if number < 1:
            raise ValueError
    except ValueError:
        raise _needs(ctx, "CHECK_LIST_ITEM: Output_Property is the item number (1 = the first item)") from None
    expected = normalize_expected(ctx.step.expected).strip()
    contains = ctx.step.contains and not ctx.step.exact_match

    def judge(v: str) -> tuple[bool, str]:
        if v.startswith("H:"):
            return False, "the list is not showing"
        if v.startswith("N:"):
            return False, f"the list shows {v[2:]} item{'s' if v[2:] != '1' else ''}, no item {number}"
        actual = v[2:]
        ok = expected.upper() in actual.upper() if contains else expected == actual.strip()
        return ok, f"item {number} of the list is {actual!r}, expected {expected!r}"
    res = await ctx.element()
    if res is None:
        return

    async def read() -> str:
        return str(await res.locator.evaluate(_LIST_ITEM_JS, number, timeout=2000))
    limit = _check_limit(ctx)
    with _patient(ctx, limit, "the list item", "the list item did not appear") as pat:
        value = await _poll(read, lambda v: judge(v)[0], limit, ctx.cfg.timeouts.poll_ms / 1000, ctx.cfg.output.stable_ms,
                            ctx.cfg.output.stable_max_ms, give_up=pat.give_up)
    ok, why = judge(value)
    ctx.out.output, ctx.out.check = value[2:], "list_item"
    if not ok:
        ctx.out.check_failed = why
        ctx.out.notes.append(why)


@action("CHECK_DATE_FORMAT", element=True)
async def check_date_format(ctx: StepContext) -> None:
    """The element's text (a field's value) is a real date written in the format in Expected_Value (``dd/mm/yyyy``, ``d mmm yyyy``, ``yyyy-mm-dd``...)."""
    fmt = normalize_expected(ctx.step.expected).strip()
    error = checks.date_format_error(fmt) if fmt else "CHECK_DATE_FORMAT needs the format in Expected_Value, such as dd/mm/yyyy"
    if error:
        raise _needs(ctx, error if not fmt else f"CHECK_DATE_FORMAT: {error}")
    await _check_element(ctx, "date_format", READ_TEXT_JS, lambda v: checks.matches_date_format(v.strip(), fmt))


# ---------------------------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------------------------
async def run_action(ctx: StepContext) -> ActionSpec:
    """Run the step's action. Errors become ``ctx.out.error`` (never raised)."""
    method = ctx.step.method
    spec = REGISTRY.get(method)
    effective = spec or ActionSpec(method, exist, True)     # unknown actions behave as element checks (legacy)
    if ends_typing_run(effective.name):
        ctx.session.typed.clear()
    try:
        if has_side_effects(ctx.step):
            await side_effect_gate(ctx)                       # production: blocked; a build-mode replay: a person confirms first
        if method not in _NO_PAGE_GATE and ctx.session.is_open:
            await ctx.session.ensure_ready()                  # a page load in flight finishes first; a new document gets to start up
        for column in ("VALUE", "FINDBY_VALUE"):                # what the step acts on: never act on an Excel error as if it were text
            cell = ctx.step.values.get(column)
            if isinstance(cell, ErrorText) and cell.code == "#NAME?":
                raise ActionError(f"The {column.replace('_', ' ').title()} cell evaluates to #NAME? ({cell.detail or 'unknown name'}): "
                                  "regrunner cannot calculate that Excel formula, so the step was not run.")
        if method in UNSUPPORTED:
            raise ActionError(f"Action {method} is not supported by regrunner (no equivalent for a headless "
                              "browser runner). Remove or replace the step.")
        if spec is None:
            if ctx.cfg.behaviour.unknown_action == "fail" or not ctx.step.findby_value:
                raise ActionError(f"Unknown action {method!r}")
            ctx.out.notes.append(f"unknown action {method!r} treated as an existence check (legacy behaviour)")
            ctx.review.flag("unknown_action", f"Unknown action {method!r} in step {ctx.step.name!r}: "
                            "checked existence only, as the legacy runner did", "warning")
            await ctx.element()
            return effective
        await spec.handler(ctx)
    except ActionError as err:
        ctx.out.error = str(err)
    except asyncio.CancelledError:
        raise
    except Exception as err:                                  # Playwright errors: the first line is the error, the rest (its call log) is the detail
        name = type(err).__name__
        ctx.out.error = f"{name}: {_first_line(err)}" if name != "Error" else _first_line(err)
        ctx.out.detail = whole_error(err)
    return effective
