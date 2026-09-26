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
from ..workbook.model import PreparedStep, is_blank, slug
from ..workbook.sheet import ErrorText, cell_text
from .enabled import pointer
from .keys import parse_sendkeys
from .outcome import StepOut, compare_ok
from .session import ActionError, BrowserSession, FrameStep
from .settle import idle_ms, settle


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
    "DB_CONNECT", "DB_DISCONNECT", "DB_QUERY", "DB_SAVE_JSON_RESULT", "JSON_READ", "SEND_EMAIL",
    "FILE_COMPARE", "RUN_SCRIPT", "UPDATE_SYSTEM_TIMEZONE", "BROKEN_LINK_CHECK",
    "BROKEN_LINK_CHECK_CRAWL", "SNAGIT_SCREENSHOT", "BS_CAPABILITIES", "FOCUSWINDOW", "SET_VARIABLE",
    "GO_TO_ROW", "ITERATION_START", "ITERATION_END", "GET_MOUSE_POS", "DRAGANDDROP",
}

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
    async def element(self, *, timeout_s: float | None = None) -> Resolved | None:
        """Find the step's element (sets ``out.obj_exists``); ``None`` when it does not exist."""
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
        give_up = None
        if step.ignore_missing and not step.timeout and self.cfg.timeouts.optional_mode == "quiet" and self.session.is_open:
            page, quiet = self.session.page, self.cfg.waits.quiet_ms

            async def give_up(elapsed: float) -> bool:
                """Optional and still absent after the page went quiet (no requests, no DOM changes)."""
                return elapsed >= 0.2 and await idle_ms(page) >= quiet
        try:
            res = await resolve(scope, chain, step.index, timeout, self.cfg.timeouts.poll_ms / 1000, give_up)
        except SelectorSyntaxError as err:
            self.out.obj_exists = False
            raise ActionError(f"Invalid selector - {err}") from err
        if res is None:
            self.out.obj_exists = False
            if step.ignore_missing:
                self.session.missed_optional.add(key)
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
    url = ctx.value_text.strip()
    if not url:
        raise ActionError("Navigate: no URL")
    await ctx.session.pace()
    try:
        await ctx.session.page.goto(url, wait_until="load", timeout=ctx.session.nav_timeout_s * 1000)
    except Exception as err:
        ctx.out.detail = whole_error(err)
        raise ActionError(f"Navigation failed: {_first_line(err)}") from err


@action("BACK")
async def back(ctx: StepContext) -> None:
    await ctx.session.page.go_back(wait_until="load", timeout=ctx.session.nav_timeout_s * 1000)
    ctx.session.switch_to_default()


@action("REFRESH")
async def refresh(ctx: StepContext) -> None:
    await ctx.session.page.reload(wait_until="load", timeout=ctx.session.nav_timeout_s * 1000)
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
    give_up = None
    if lenient and not ctx.step.timeout:
        if key in ctx.session.missed_optional:
            timeout = min(timeout, ctx.cfg.timeouts.optional_repeat_s)
        if ctx.cfg.timeouts.optional_mode == "quiet" and ctx.session.is_open:
            page, quiet = ctx.session.page, ctx.cfg.waits.quiet_ms

            async def give_up(elapsed: float) -> bool:
                return elapsed >= 0.2 and await idle_ms(page) >= quiet
    try:
        await ctx.session.switch_to_frame(step, timeout, give_up)
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
        grace = time.monotonic() + ctx.cfg.waits.window_grace_s
        while time.monotonic() < grace and len(session.pages) <= known and not session.window_recently_opened:
            await asyncio.sleep(0.05)
    if wants_latest:
        open_windows = [p for p in session.pages if not p.is_closed()]
        if len(open_windows) == 1:
            # Legacy "switched" to the newest window, which with one window is the one it was already in: a missing popup passed and the steps
            # after it ran against the wrong page.  The window this step waits for did not open.
            raise ActionError(f"No new window opened: this step switches to the window the step before it opens, but after waiting "
                              f"{ctx.cfg.waits.window_grace_s:g} s only {len(open_windows)} window is open")
    # A window index may refer to a window that is not registered yet; wait for it.
    deadline = time.monotonic() + ctx.act_timeout_s
    while True:
        try:
            ctx.session.switch_to_window(ctx.value_text)
            return
        except ActionError:
            if time.monotonic() >= deadline:
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
    from ..totp import STEP_S, BadSecret, code_at, reserve_window
    try:
        code_at(ctx.value_text)
    except BadSecret as err:
        if ctx.asker is not None and ctx.asker.available:
            ctx.out.notes.append(f"no usable key ({err}): asked for the code instead")
            ctx.out.output = (await ask_person(ctx, "Enter the 6-digit code from Google Authenticator", secret=True)).strip()
            return
        raise ActionError(f"GET_GOOGLE_TOKEN: {err} (the Value cell is the secret key). Fill it in, or use an ASK_USER step to be asked for the "
                          "code.") from None
    # One code, one login: a code is accepted once, so a second test logging in with the same secret (at the same moment, or a run started a few seconds after
    # another) is given the next window's code instead of the one that was just used.
    booked = reserve_window(ctx.value_text, store=ctx.cfg.base_dir / ".auth" / "totp_last.json")
    if booked.wait_s > 0:
        await asyncio.sleep(booked.wait_s)
        why = ("the code for this one was already used by another login with the same authenticator secret, and Okta accepts a code once"
               if booked.reason == "used" else "the current code was about to expire")
        ctx.out.notes.append(f"waited {booked.wait_s:.1f}s for the next {STEP_S} s code window ({why})")
    ctx.out.output = code_at(ctx.value_text, booked.window * STEP_S)


@action("ALERT_OK", "ALERT_CANCEL", "ALERT_TEXT_OUT")
async def alert(ctx: StepContext) -> None:
    deadline = time.monotonic() + ctx.act_timeout_s
    while ctx.session.pending_dialog is None:
        if time.monotonic() >= deadline:
            raise ActionError("Alert button not found (no dialog is open)")
        await asyncio.sleep(0.05)
    dialog, ctx.session.pending_dialog = ctx.session.pending_dialog, None
    method = ctx.step.method
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
    if mode == "legacy":
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
            await kb.type("".join(typed))
            typed = []
        await kb.press(op.combo)
        if op.combo.split("+")[-1] in ("Enter", "NumpadEnter") and await ctx.session.watch_for_navigation():
            await ctx.session.ensure_ready()              # Enter submitted a form / followed a link: end the step on the new page
            ctx.out.notes.append("the key press loaded a page; waited for it")
    if typed:
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
    deadline = time.monotonic() + ctx.act_timeout_s
    while True:
        counts = []
        for s in chain:
            try:
                counts.append(await scope.locator(s.selector).count())
            except Exception:
                counts.append(0)
        if not any(c > step.index for c in counts):
            return
        if time.monotonic() >= deadline:
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
    deadline = time.monotonic() + 1.0
    while True:                                       # phase 1: the new state has to appear
        now = await _checkable_state(res)
        if now is None:
            return                                    # the page replaced the element: nothing left to verify
        if now["checked"] == want:
            break
        if time.monotonic() >= deadline:
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
    deadline = time.monotonic() + (ctx.find_timeout_s if ctx.step.ignore_missing else ctx.act_timeout_s)      # an optional element is not waited for long
    while True:
        state = await res.locator.evaluate(CLICKABLE_JS, timeout=act_ms(ctx))
        if state["visible"] and not state["disabled"]:
            break
        if time.monotonic() >= deadline:
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


async def _enter(ctx: StepContext, locator, text: str, clear_first: bool) -> None:
    timeout = act_ms(ctx)
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
_TYPING_RUN_KEEPS = {"SET", "WRITE", "WAIT", "OUTPUT", "EXIST", "SCREENSHOT", "SWITCHTOFRAME", "SWITCHTODEFAULT"}


_NO_PAGE_GATE = {"OPEN", "QUIT", "WAIT", "BREAK", "STOP"}          # these do not depend on the current document


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
                timeout_s: float, poll_s: float, stable_ms: int, stable_max_ms: int) -> str:
    """Read until ``accept`` (if any) is satisfied; otherwise until the value stops changing."""
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
            if time.monotonic() - started >= timeout_s:
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
        accept = lambda actual: compare_ok(step, actual)[0]        # retry until the expected text appears
    text = await _poll(read, accept, ctx.cfg.output.match_timeout_s, ctx.cfg.timeouts.poll_ms / 1000,
                       ctx.cfg.output.stable_ms, ctx.cfg.output.stable_max_ms)
    ctx.out.output = text


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
