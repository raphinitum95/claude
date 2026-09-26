"""One test's browser: an isolated context, its pages (windows) and the current frame."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..capture.review import ReviewCollector
from ..config import Config
from ..events import now_iso
from . import captcha
from .patience import NO_NOTICE, Activity, Patience, plain_seconds
from .settle import SETTLE_INIT_JS, idle_ms, settle
from .timing import NO_TIMING, fingerprint_site_code

_TWO_LEVEL_SUFFIXES = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp",
                       "com.br", "com.mx", "co.za", "com.sg", "com.cn", "co.in"}


_SECRET_PARAM = re.compile(r"(pass(word|code)?|pwd|token|secret|card|cvv|cvc|ssn|auth|otp|^code$|[_-]code$)", re.I)


def mask_url(url: str) -> str:
    """The URL as logged: scheme and host dropped, secret-looking query values hidden, long values cut."""
    parts = urlparse(url)
    query = "&".join((k + "=" + ("***" if _SECRET_PARAM.search(k) else v[:80])) if "=" in kv else kv
                     for kv in parts.query.split("&") if kv for k, _, v in [kv.partition("=")])
    return parts.path + ("?" + query if query else "")


def behind_cloudfront(headers: dict | None) -> bool:
    """AWS CloudFront (the CDN / firewall in front of many sites) names itself in the headers of its own error pages."""
    h = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    return ("cloudfront" in h.get("server", "") or "cloudfront" in h.get("via", "") or "cloudfront" in h.get("x-cache", "")
            or "x-amz-cf-id" in h)


def http_block_message(url: str, status: int, headers: dict | None = None) -> str:
    """An error page instead of the site: say so, because otherwise every later step just reports 'Object was not found'."""
    host = urlparse(url).netloc or url
    meaning = {401: "sign-in required", 403: "access denied", 404: "not found", 429: "too many requests"}.get(status)
    cdn = " from CloudFront (the CDN / firewall in front of the site)" if status in (401, 403, 429) and behind_cloudfront(headers) else ""
    head = f"{host} answered HTTP {status}{cdn}{f' ({meaning})' if meaning else ''}, so the page did not load and none of its elements can be found."
    if status in (401, 403, 429) and cdn:
        return (head + " CloudFront refuses this machine before the site sees the request: the network address or country is not allowed "
                "(VPN / allow-list), a firewall rule matched, or too many requests came from here (then waiting a few minutes helps).")
    if status in (401, 403, 429):
        return (head + " Usual causes: the site is blocking or rate-limiting this machine (wait a few minutes; many runs in a row "
                "trigger it), the recaptchaBypassToken for this environment is missing or wrong, or the SSO session has expired "
                "(Preflight, then Sign in).")
    if status >= 500:
        return head + " The environment may be down or restarting."
    return head + " Check the URL and the environment."


class ActionError(Exception):
    """A step failed in a way that should be reported as the step's error message."""


# Errors that mean the machine, not the site: the browser tab or the browser itself went away without anyone closing it, or the browser driver died.
# ("Target page, context or browser has been closed" alone is NOT one of them: a site may close its own window.)
_INFRA_ERRORS = re.compile(r"target crashed|page crashed|browser has been closed|browser has disconnected|connection closed|"
                           r"playwright connection closed|pipe closed|browser closed unexpectedly", re.I)
_DRIVER_DIED = re.compile(r"connection closed|pipe closed", re.I)

# Traffic that says nothing about whether the page is still loading: streams that stay open by design, fire-and-forget pings.
_NOT_LOADING_TYPES = {"websocket", "eventsource", "media", "ping", "manifest"}
_DIGITS = re.compile(r"(?<!\w)\d{6,8}(?!\w)")                        # a one-time code on its own (not part of an id like E0000068)
_SECRET_JSON = re.compile(r'("(?:[^"]*(?:pass(?:word|code)?|pwd|token|secret|answer|otp|credential)[^"]*|code)"\s*:\s*)"[^"]*"', re.I)


def mask_body(text: str, limit: int = 2000) -> str:
    """A sign-in service's answer as kept in network.jsonl: values of secret-looking fields and anything that looks like a one-time code hidden."""
    text = _SECRET_JSON.sub(r'\1"***"', str(text or ""))
    text = _DIGITS.sub("******", text)
    return text if len(text) <= limit else text[:limit] + "... (cut)"


@dataclass(frozen=True)
class FrameStep:
    by: str          # "name" | "index"
    value: str | int


def cookie_domains(url: str, extra: list[str] | None = None) -> list[str]:
    """Hosts that should carry the bypass cookie: the site's registrable domain (covers sibling
    sub-domains such as an iframe host) plus any configured extras."""
    host = (urlparse(url).hostname or "").lower()
    domains: list[str] = []
    if host:
        if re.fullmatch(r"[\d.]+|[\da-f:]+", host) or "." not in host:
            domains.append(host)                       # IP / localhost: exact host only
        else:
            labels = host.split(".")
            keep = 3 if ".".join(labels[-2:]) in _TWO_LEVEL_SUFFIXES else 2
            domains.append("." + ".".join(labels[-keep:]))
    for extra_domain in extra or []:
        if extra_domain and extra_domain not in domains:
            domains.append(extra_domain)
    return domains


class BrowserSession:
    """Owns the BrowserContext for one test; created by the ``Open`` action, closed by ``Quit``."""

    def __init__(self, browser_getter, cfg: Config, review: ReviewCollector, test_id: str, environment: str,
                 log=None, devices: dict | None = None, throttle=None, cancel=None):
        self.browser_getter = browser_getter          # async () -> Browser (worker relaunches a crashed browser)
        self.devices = devices or {}
        self.cfg = cfg
        self.review = review
        self.test_id = test_id
        self.environment = environment
        self.log = log or (lambda *a, **k: None)
        self.context = None
        self.pages: list[Any] = []
        self._current = None
        self.frame_path: list[FrameStep] = []
        self._frame = None
        self.pending_dialog = None
        self.last_dialog_text = ""
        self.missed_optional: set[str] = set()
        self._new_pages_prev: list[Any] = []            # windows opened during the previous step
        self._new_pages_cur: list[Any] = []             # ...and during the current one
        self.nav_timeout_s = cfg.timeouts.navigation_s
        self.notes: list[str] = []
        self.throttle, self.cancel = throttle, cancel     # shared by every test of the run (engine/throttle.py)
        self.block_error = ""                          # set when a step's own server call was blocked (HTTP 403 / 429)
        self.load_status: int | None = None             # HTTP status of the first page that failed to load
        self.network: list[dict[str, Any]] = []         # the site's own XHR/fetch calls: what was asked, what came back (network.jsonl)
        self._calls: dict[Any, dict[str, Any]] = {}      # per page: first-party XHR/fetch calls ("servlet calls") started / in flight
        self._nav: dict[Any, dict[str, Any]] = {}       # per page: documents loaded, a navigation in flight, the document already waited for
        self.typed: list[Any] = []                      # fields typed in the current run of typing steps (see actions.type_into)
        self.loaded_once = False                        # has any page of this test loaded successfully?
        self.load_error = ""                            # why the first page did not load (until one does)
        self.bypass_sent = False                        # the captcha bypass cookie was put in this test's browser
        self.notice = NO_NOTICE                         # tells the run screen when this test waits on purpose (engine/patience.py)
        self._act: dict[Any, dict[str, Any]] = {}       # per page: what it is loading right now, and when anything last moved (see activity())
        self.infra = ""                                 # why this test cannot go on for a reason that is the machine's, not the site's (a crash...)
        self.infra_kind = ""                            # browser | driver
        self._closing = False                           # this test is closing its own browser window (so a disconnect is not a crash)
        self._on_disconnect = None
        self.next_alert = ""                            # the next step is this ALERT step: a dialog that opens is answered at once, the way that step says
        self.answered_dialog: dict[str, str] | None = None   # ...and what it said, for that step to read
        self.totp: dict[str, Any] | None = None         # the one-time login code handed out last, to measure when it is actually used (GET_GOOGLE_TOKEN)
        self.timing = NO_TIMING                         # where this test's time goes (engine/timing.py; the test runner gives it its own)
        self.third_party: dict[str, dict[str, int]] = {}    # host -> {requests, bytes}: what other companies' servers the pages loaded (measure.third_party)
        self.site_code: dict[str, str] = {}             # the site's own code files (measure.site_code_patterns) -> their version: the "site version"
        self._site_domains: set[str] = set()            # registrable domains of the documents this test's windows showed (= first party)

    # -- lifecycle -----------------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self.context is not None and self._current is not None and not self._current.is_closed()

    async def open(self, url: str, *, width: int | None = None, height: int | None = None,
                   device: dict | None = None, scale: float | None = None) -> None:
        await self.close()
        self.typed.clear()
        b = self.cfg.browser
        options: dict[str, Any] = {
            "viewport": {"width": int(width or b.viewport_width), "height": int(height or b.viewport_height)},
            "locale": b.locale, "ignore_https_errors": b.ignore_https_errors,
            "accept_downloads": False,
        }
        if b.timezone:
            options["timezone_id"] = b.timezone
        if b.user_agent:
            options["user_agent"] = b.user_agent
        if device:
            options.update(device)
        if scale:
            options["device_scale_factor"] = scale
        state = self.cfg.path(self.cfg.auth.storage_state)
        if state.is_file():
            options["storage_state"] = str(state)
        self._closing = False
        try:
            browser = await self.browser_getter()
            self._browser = browser
            self.context = await browser.new_context(**options)
        except Exception as err:
            # Not the site's doing: the browser would not start or open a window (out of memory, the driver gone...).  Nothing of the test has run.
            reason = (str(err).strip().splitlines() or [type(err).__name__])[0][:200]
            self.mark_infra(f"The browser could not open a window ({reason})", "driver" if _DRIVER_DIED.search(str(err)) else "browser")
            raise ActionError(self.infra) from err
        self._watch_browser(browser)
        self.context.set_default_timeout(self.cfg.timeouts.element_s * 1000)
        self.context.set_default_navigation_timeout(self.nav_timeout_s * 1000)
        await self.context.add_init_script(SETTLE_INIT_JS)
        self.context.on("page", self._register_page)
        await self._add_bypass_cookie(url)
        page = await self.context.new_page()          # fires "page" -> registered
        self._current = page
        self.frame_path, self._frame = [], None
        await self.pace()
        try:
            response = await self.load(page, lambda **kw: page.goto(url, **kw))
        except ActionError as err:
            self._load_failed(f"Navigation to {url} failed: {err}")
            raise ActionError(f"Navigation to {url} failed: {err}") from err
        except Exception as err:
            message = f"Navigation to {url} failed: {str(err).splitlines()[0]}"
            self._load_failed(message)
            raise ActionError(message) from err
        status = response.status if response is not None else None
        if status is not None and status >= 400:
            message = http_block_message(url, status, response.headers)
            if not self.loaded_once:
                self.load_status = status
            self._load_failed(message)
            raise ActionError(message)
        self.loaded_once, self.load_error = True, ""
        if self.throttle is not None:
            self.throttle.loaded_ok = True                 # this machine can reach the site: a later block is a rate limit, not a rule

    def _load_failed(self, message: str) -> None:
        if not self.loaded_once:
            self.load_error = message

    async def load(self, page, go):
        """A page load (``go`` = ``page.goto`` / ``reload`` / ``go_back`` with its options bound): with patience on, the load has as long as it keeps
        making progress - the answer to the request may take ``patience.stall_s``, and the page then gets to finish (``load``) for as long as it
        is visibly still loading.  Without patience: the old fixed ``timeouts.navigation_s``."""
        if not self.cfg.patience.enabled:
            return await go(wait_until="load", timeout=self.nav_timeout_s * 1000)
        pat = self.cfg.patience
        response = await go(wait_until="commit", timeout=max(self.nav_timeout_s, pat.stall_s) * 1000)
        await self.wait_for_load(page)
        return response

    async def wait_for_load(self, page, what: str = "the page to finish loading") -> None:
        """The ``load`` event of ``page``, waited for patiently.  Raises ActionError when the page stops making progress (or never ends)."""
        with Patience(self, self.nav_timeout_s, what=what) as pat:
            while True:
                try:
                    await page.wait_for_load_state("load", timeout=1000)
                    return
                except Exception as err:
                    if "Timeout" not in str(err) and "timeout" not in str(err):
                        raise
                if await pat.give_up():
                    raise ActionError(f"the page never finished loading: {pat.explain()}")

    async def _add_bypass_cookie(self, url: str) -> None:
        cap = self.cfg.captcha_bypass
        token = self.cfg.bypass_token(self.environment)
        if not token:
            self.review.flag("captcha_bypass", f"No {cap.cookie_name} value configured for environment "
                             f"{self.environment or '?'}; captcha-protected steps may be blocked", "warning")
            return
        secure = urlparse(url).scheme == "https"
        same_site = cap.same_site if secure else "Lax"
        domains = cookie_domains(url, cap.extra_domains)
        cookies = [{"name": cap.cookie_name, "value": token, "domain": d, "path": "/",
                    "secure": secure, "sameSite": same_site} for d in domains]
        try:
            await self.context.add_cookies(cookies)
            self.bypass_sent = True
            self.notes.append(f"{cap.cookie_name} set for {', '.join(domains)}")
        except Exception as err:
            self.review.flag("captcha_bypass", f"Could not set {cap.cookie_name}: {str(err).splitlines()[0]}", "warning")

    async def find_captcha(self):
        """A captcha challenge showing in any window of this test (engine/captcha.py), else None.  Never raises and never takes long."""
        pages = [p for p in self.pages if not p.is_closed()]
        if not pages or self.pending_dialog is not None:              # (a dialog blocks the page: nothing can be looked at until it is answered)
            return None
        try:
            return await asyncio.wait_for(captcha.find(pages), 4)
        except Exception:
            return None

    def mark_step(self) -> None:
        """Called at the start of every step so window switches can tell "a popup just opened"."""
        self._new_pages_prev, self._new_pages_cur = self._new_pages_cur, []

    @property
    def window_recently_opened(self) -> bool:
        return any(not p.is_closed() for p in [*self._new_pages_prev, *self._new_pages_cur])

    def _register_page(self, page) -> None:
        self._new_pages_cur.append(page)
        self.pages.append(page)
        self._watch_navigation(page)
        self._watch_calls(page)
        self._watch_activity(page)
        self._watch_hosts(page)
        page.on("crash", lambda *_: self.mark_infra("The browser tab crashed (the computer may have run out of memory)", "browser"))
        self.review.attach(page)
        page.on("dialog", self._on_dialog)
        page.on("close", lambda p=page: self._on_page_closed(p))

    def _on_page_closed(self, page) -> None:
        self.timing.site.forget(self._act.get(page, {}).get("inflight", {}).keys())   # its requests will never answer now
        if page in self.pages:
            self.pages.remove(page)
        if self._current is page:
            self._current = self.pages[-1] if self.pages else None
            self.frame_path, self._frame = [], None

    def _on_dialog(self, dialog) -> None:
        self.last_dialog_text = dialog.message
        if self.next_alert:
            # The next step answers it (ALERT_OK / ALERT_CANCEL / ALERT_TEXT_OUT).  A page cannot do anything while a dialog is open - the click that
            # opened it does not even finish - so it is answered now, the way that step says, and the step reads what it said: however slowly the
            # computer gets to that step, the answer is the same.
            how = "accept" if self.next_alert == "ALERT_OK" else "dismiss"
            self.answered_dialog = {"message": dialog.message, "how": how}
            asyncio.get_running_loop().create_task(self._answer(dialog, how))
            return
        self.pending_dialog = dialog
        asyncio.get_running_loop().create_task(self._auto_resolve_dialog(dialog))

    @staticmethod
    async def _answer(dialog, how: str) -> None:
        try:
            await (dialog.accept() if how == "accept" else dialog.dismiss())
        except Exception:
            pass

    async def _auto_resolve_dialog(self, dialog) -> None:
        await asyncio.sleep(1.5)                       # give an ALERT_* step the chance to consume it
        if self.pending_dialog is dialog:
            self.pending_dialog = None
            try:
                await (dialog.accept() if self.cfg.behaviour.dialogs == "accept" else dialog.dismiss())
            except Exception:
                pass

    # -- page loads ------------------------------------------------------------------------------
    def _watch_navigation(self, page) -> None:
        """Know when a page load starts and ends, from the browser's own events (the old Selenium driver did the same
        and held every command while a navigation was pending).  A click that reloads the page is only *noticed* by
        Playwright once the request goes out, ~0.1-0.2 s after the click returned, so this state is what the next step must ask."""
        st = self._nav[page] = {"docs": 0, "pending": None, "waited_doc": -1, "started_docs": 0}

        def is_main_navigation(request) -> bool:
            try:
                return bool(request.is_navigation_request()) and request.frame == page.main_frame
            except Exception:
                return False

        def on_request(request) -> None:
            if is_main_navigation(request):
                st["pending"] = time.monotonic()
                st["started_docs"] += 1

        def on_finished_navigation(request) -> None:
            if is_main_navigation(request):
                st["pending"] = None                        # failed / aborted / answered without a page (a download, a 204)

        page.on("request", on_request)
        page.on("requestfailed", on_finished_navigation)
        page.on("load", lambda *_: st.__setitem__("pending", None))
        page.on("framenavigated", lambda frame: st.__setitem__("docs", st["docs"] + 1) if frame == page.main_frame else None)

    def navigating(self) -> bool:
        page = self._current
        st = self._nav.get(page) if page is not None else None
        limit = max(self.nav_timeout_s, self.cfg.patience.stall_s) if self.cfg.patience.enabled else self.nav_timeout_s
        return bool(st and st["pending"] is not None and time.monotonic() - st["pending"] < limit)

    async def watch_for_navigation(self, grace_s: float | None = None) -> bool:
        with self.timing.span("runner", "nav_grace"):
            return await self._watch_for_navigation(grace_s)

    async def _watch_for_navigation(self, grace_s: float | None = None) -> bool:
        """After a click that may load a page: give the load a moment to *start* (a JS click returns before it does).
        True when one started; the caller then calls ``ensure_ready`` so the click step ends on the new page."""
        page = self._current
        st = self._nav.get(page) if page is not None else None
        if st is None:
            return False
        grace = self.cfg.waits.nav_grace_ms / 1000 if grace_s is None else grace_s
        started, docs = st["started_docs"], st["docs"]
        # The grace counts only while nothing the click started is still going and the computer answers promptly: on a busy machine the click's
        # own script may take seconds before it starts the load, and a step that ends before that acts on the page that is about to go away.
        with Patience(self, grace, what="the click to take effect", since=time.monotonic() - 0.05) as pat:
            while True:
                if st["started_docs"] != started or st["docs"] != docs or st["pending"] is not None:
                    return True
                if await pat.give_up():
                    return False
                await asyncio.sleep(0.02)

    async def ensure_ready(self) -> None:
        with self.timing.span("runner", "ready_wait"):                 # (the site loading meanwhile is counted as the site's: timing.py)
            await self._ensure_ready()

    async def _ensure_ready(self) -> None:
        """Before acting: a page load that has started must finish, and a freshly loaded document must be really ready.

        * a navigation in flight is waited for, for as long as it makes progress (``patience``; without it ``timeouts.navigation_s``);
        * a document not waited for yet is waited for until it (and every frame) is ``complete`` and nothing has loaded or
          changed for ``waits.ready_quiet_ms`` - a form's own start-up script often runs after ``load``, and a click or typing
          that lands before it is ignored or undone.  ``waits.ready_max_s`` bounds only the time the page spends *changing without
          loading anything* (an animation never goes quiet); while it is still loading, the wait goes on;
        * a document already waited for costs one cheap check.

        Nothing is ever repeated afterwards: if the page still undoes an action, that is reported as a failure.
        """
        page = self._current
        limit = self.cfg.waits.ready_max_s
        if page is None or page.is_closed() or limit <= 0:
            return
        st = self._nav.get(page)
        if st is None:
            return
        quiet = self.cfg.waits.ready_quiet_ms
        patient = self.cfg.patience.enabled
        with Patience(self, limit, what="the page to finish loading") as pat:
            nav_end = time.monotonic() + self.nav_timeout_s
            while True:
                if self.navigating():
                    if not patient and time.monotonic() > nav_end:
                        self.review.flag("page_busy", f"A page load had not finished after {self.nav_timeout_s:g}s; carried on anyway", "warning")
                        return
                    if patient and await pat.give_up() and pat.reason != "settled":
                        self.review.flag("page_busy", f"A page load did not finish: {pat.explain()}; carried on", "warning")
                        return
                    await asyncio.sleep(0.05)
                    continue
                fresh = st["waited_doc"] != st["docs"]
                if await self._all_frames_complete(page) and (not fresh or await idle_ms(page) >= quiet) and not self.navigating():
                    st["waited_doc"] = st["docs"] if fresh else st["waited_doc"]
                    return
                if await pat.give_up():
                    if pat.reason == "settled":
                        self.review.flag("page_busy", f"The page was still changing after {limit:g}s without loading anything; carried on anyway", "info")
                    else:
                        self.review.flag("page_busy", f"The page did not settle: {pat.explain()}; carried on", "warning")
                    st["waited_doc"] = st["docs"]
                    return
                await asyncio.sleep(0.05)

    # -- is the page still working? --------------------------------------------------------------------
    def _watch_activity(self, page) -> None:
        """Evidence that the page is still working, from the browser's own events: a page load, frames loading, requests going out and
        coming back.  Only the page's *own* requests (same site as the frame that makes them, or a frame's document) count as it still
        loading - a hung analytics call or an advert must not hold every step - and an address the page keeps asking for again and again
        (a heartbeat, a chat widget polling) is recognised after ``patience.repeat_after`` calls and ignored."""
        st = self._act[page] = {"inflight": {}, "seen": {}, "progress": time.monotonic(), "network": 0.0}
        repeat_after = max(2, int(self.cfg.patience.repeat_after))

        def moved(*_):
            st["progress"] = time.monotonic()

        def key_of(request) -> str:
            parts = urlparse(request.url)
            return f"{request.method} {parts.scheme}://{parts.netloc}{parts.path}"

        def own(request) -> bool:
            try:
                if request.resource_type == "document":
                    return True
                frame_host = (urlparse(request.frame.url).hostname or "").lower()
                host = (urlparse(request.url).hostname or "").lower()
                mine = (cookie_domains("http://" + frame_host + "/")[0] if frame_host else "").lstrip(".")
                return bool(mine) and (host == mine or host.endswith("." + mine))
            except Exception:
                return False

        def started(request) -> None:
            try:
                if request.resource_type in _NOT_LOADING_TYPES:
                    return
            except Exception:
                return
            key = key_of(request)
            st["seen"][key] = st["seen"].get(key, 0) + 1
            if st["seen"][key] >= repeat_after:
                return                                              # polling: says nothing about loading
            now = time.monotonic()
            st["progress"] = st["network"] = now
            if own(request):
                st["inflight"][request] = (now, key)
                self.timing.site.started(request)

        def ended(request) -> None:
            self.timing.site.ended(request)
            if st["inflight"].pop(request, None) is not None or st["seen"].get(key_of(request), 0) < repeat_after:
                st["progress"] = st["network"] = time.monotonic()

        def new_document(frame) -> None:
            moved()
            if frame == page.main_frame:
                st["seen"].clear()                                  # a new document: what counts as polling is learned again

        page.on("request", started)
        page.on("requestfinished", ended)
        page.on("requestfailed", ended)
        page.on("framenavigated", new_document)
        page.on("frameattached", moved)
        page.on("domcontentloaded", moved)
        page.on("load", moved)

    async def activity(self, since: float | None = None) -> Activity:
        """What the current page is doing right now (see :class:`patience.Activity`).  ``since`` (monotonic): only requests started after it
        count as the page working (what a click itself started).  Costs one small question to the page; never raises."""
        page = self._current
        now = time.monotonic()
        st = self._act.get(page) if page is not None else None
        if st is None or page.is_closed():
            return Activity(False, "", now)
        pat = self.cfg.patience
        if self.pending_dialog is not None:
            return Activity(False, "a dialog is open", st["progress"])      # the page cannot be asked anything until it is answered
        if self.navigating():
            return Activity(True, "a new page is loading", st["progress"])
        own = [(t0, key) for t0, key in st["inflight"].values() if since is None or t0 >= since]
        t0 = time.monotonic()
        try:
            state, late_ms, late_sum_ms = await asyncio.wait_for(page.main_frame.evaluate(
                "[document.readyState, window.__rr && window.__rr.takeLag ? window.__rr.takeLag() : 0,"
                " window.__rr && window.__rr.takeLagSum ? window.__rr.takeLagSum() : 0]"), max(5.0, pat.lag_ms / 1000 * 5))
            self.timing.lagged(float(late_sum_ms or 0) / 1000)
        except asyncio.TimeoutError:
            state, late_ms = "busy", 0.0
        except Exception:
            return Activity(True, "a new page is loading", st["progress"])          # mid-navigation: the old document is gone
        lag = max(time.monotonic() - t0, float(late_ms or 0) / 1000)          # slow to answer now, or its own heartbeat ran late since the last look
        if lag * 1000 >= pat.lag_ms:
            st["progress"] = time.monotonic()                       # an overloaded computer is slow, not stuck
            return Activity(True, f"the computer is very busy (the page took {lag:.1f} s to answer)", st["progress"])
        if own:
            oldest = min(own)
            more = f" and {len(own) - 1} more" if len(own) > 1 else ""
            path = urlparse(oldest[1].split(" ", 1)[-1]).path or "/"
            return Activity(True, f"the site has not answered yet ({oldest[1].split(' ', 1)[0]} {path}{more}, "
                                  f"{plain_seconds(now - oldest[0])} so far)", st["progress"])
        if since is None and state != "complete":
            return Activity(True, "the page is still loading", st["progress"])
        # The page only changing its content (an animation, a carousel, a clock) is not "still loading": that alone never holds a step.  A page
        # slowly drawing what it loaded on an overloaded computer shows up above, as the computer answering slowly.
        return Activity(False, "", st["progress"])

    # -- the machine, not the site ----------------------------------------------------------------------
    def _watch_browser(self, browser) -> None:
        old = self._on_disconnect
        if old is not None:
            try:
                self._browser.remove_listener("disconnected", old)
            except Exception:
                pass

        def gone(*_):
            if not self._closing:
                self.mark_infra("The browser closed unexpectedly (it crashed, ran out of memory or was killed)", "browser")
        self._on_disconnect = gone
        try:
            browser.on("disconnected", gone)
        except Exception:
            pass

    def mark_infra(self, reason: str, kind: str = "browser") -> None:
        if not self.infra and not self._closing:
            if kind == "driver" and "driver" not in reason:
                reason += " - the browser driver stopped working"
            self.infra, self.infra_kind = reason, kind

    async def check_infra(self, error: str) -> bool:
        """After a step that failed: was it the machine (the tab or the browser went away, the driver died) rather than the site?  Only provable
        causes count - a crash event, a browser that is no longer connected, a dead driver - never a guess from a timeout."""
        if self.infra:
            return True
        if not error or not _INFRA_ERRORS.search(error):
            return False
        await asyncio.sleep(0.3)                                    # the crash / disconnect event may arrive a moment after the error
        if self.infra:
            return True
        browser = getattr(self, "_browser", None)
        try:
            connected = browser is None or browser.is_connected()
        except Exception:
            connected = False
        if _DRIVER_DIED.search(error):
            self.mark_infra(f"The browser driver stopped working ({error.splitlines()[0][:160]})", "driver")
        elif not connected:
            self.mark_infra("The browser closed unexpectedly (it crashed, ran out of memory or was killed)", "browser")
        return bool(self.infra)

    # -- server calls started by an input ------------------------------------------------------------
    def _watch_calls(self, page) -> None:
        """Track the site's own XHR / fetch calls (the AEM servlets behind validation, look-ups and form posts) - not third-party
        traffic (reCAPTCHA, consent, analytics) and not page resources.  Every first-party call is also written to the run's
        ``network.jsonl`` (what was asked, what came back, how long it took), because "the check never cleared the error" is only
        explainable by looking at the calls."""
        st = self._calls[page] = {"started": 0, "inflight": set(), "t0": {}, "blocks": []}
        blocking = set(self.cfg.runner.block_statuses)
        waits = self.cfg.waits
        include = [re.compile(x) for x in waits.call_url_patterns]
        ignore = [re.compile(x) for x in waits.call_ignore_patterns]

        def registrable(host: str) -> str:
            return (cookie_domains("http://" + host + "/")[0] if host else "").lstrip(".")

        def first_party(request) -> bool:
            try:
                if request.resource_type not in ("xhr", "fetch"):
                    return False
                mine = registrable((urlparse(page.url).hostname or "").lower())
                theirs = (urlparse(request.url).hostname or "").lower()
                return bool(mine) and (theirs == mine or theirs.endswith("." + mine))
            except Exception:
                return False

        def is_servlet_call(request) -> bool:
            url = request.url
            if any(p.search(url) for p in ignore):
                return False
            return not include or any(p.search(url) for p in include)

        def log(request, status, error: str = "") -> None:
            t0 = st["t0"].pop(request, None)
            if len(self.network) >= 5000:
                return
            self.network.append({"at": now_iso(), "step": self.review.step, "step_name": self.review.step_name,
                                 "method": request.method, "url": mask_url(request.url), "type": request.resource_type,
                                 "status": status, "ms": int((time.monotonic() - t0) * 1000) if t0 else None,
                                 "servlet": is_servlet_call(request), "error": error})

        def started(request) -> None:
            if not first_party(request):
                return
            st["t0"][request] = time.monotonic()
            if is_servlet_call(request):
                st["started"] += 1
                st["inflight"].add(request)

        def finished(request) -> None:
            st["inflight"].discard(request)

        def is_main_navigation(request) -> bool:
            try:
                return bool(request.is_navigation_request()) and request.frame == page.main_frame
            except Exception:
                return False

        auth = [re.compile(x, re.I) for x in waits.auth_url_patterns]

        async def keep_auth_answer(request, response, t0) -> None:
            # A sign-in service refusing something (Okta: "Each code can only be used once") says why a login failed; it is not in the first-party
            # log, so its answer is kept here - never what was sent, and with anything secret-looking masked.
            try:
                body = mask_body(await asyncio.wait_for(response.text(), 5))
            except Exception:
                body = ""
            if len(self.network) < 5000:
                self.network.append({"at": now_iso(), "step": self.review.step, "step_name": self.review.step_name, "method": request.method,
                                     "url": _DIGITS.sub("******", (urlparse(request.url).hostname or "") + mask_url(request.url)), "type": request.resource_type,
                                     "status": response.status, "ms": int((time.monotonic() - t0) * 1000), "servlet": False, "auth": True,
                                     "error": "", "body": body})

        auth_t0: dict[Any, float] = {}

        def auth_started(request) -> None:
            if any(p.search(request.url) for p in auth):
                auth_t0[request] = time.monotonic()

        page.on("request", auth_started)

        def responded(response) -> None:
            request = response.request
            tracked = request in st["t0"]
            if tracked:
                log(request, response.status)
            t_auth = auth_t0.pop(request, None)
            if t_auth is not None and 400 <= response.status < 500:
                try:
                    asyncio.get_running_loop().create_task(keep_auth_answer(request, response, t_auth))
                except RuntimeError:
                    pass
            if response.status in blocking:
                # A WAF answering 403 / 429 to one of the site's servlet calls or to a page load: the site is refusing us, which is
                # a different thing from the application saying "invalid zip" (that one is a 500 here).
                navigation = is_main_navigation(request)
                if (tracked and is_servlet_call(request)) or navigation:
                    st["blocks"].append({"status": response.status, "method": request.method, "path": mask_url(request.url).split("?")[0],
                                         "navigation": navigation, "step": self.review.step})

        def failed(request) -> None:
            st["inflight"].discard(request)
            if request in st["t0"]:
                log(request, None, str(request.failure or "failed"))

        page.on("request", started)
        page.on("response", responded)
        page.on("requestfinished", finished)
        page.on("requestfailed", failed)

    def _watch_hosts(self, page) -> None:
        """For measuring (``measure``), never for deciding anything: which other companies' servers the pages load (analytics, tag managers,
        adverts, chat widgets: the input for a tracker block list) - host, requests and bytes, never a full address - and the versions of the
        site's own code files (``measure.site_code_patterns``), so a run can tell that the site deployed new code since the last one."""
        measure = self.cfg.measure
        patterns = [p for p in measure.site_code_patterns if p]
        if not measure.third_party and not patterns:
            return

        def registrable(host: str) -> str:
            return (cookie_domains("http://" + host + "/")[0] if host else "").lstrip(".")

        def navigated(frame) -> None:
            try:
                if frame == page.main_frame:
                    domain = registrable((urlparse(frame.url).hostname or "").lower())
                    if domain:
                        self._site_domains.add(domain)
            except Exception:
                pass

        def responded(response) -> None:
            try:
                request = response.request
                parts = urlparse(response.url)
                host = (parts.hostname or "").lower()
                if not host or parts.scheme not in ("http", "https"):
                    return
                if request.is_navigation_request() and request.frame == page.main_frame:
                    self._site_domains.add(registrable(host))
                domain = registrable(host)
                headers = response.headers
                if domain in self._site_domains:
                    if any(p in parts.path for p in patterns) and len(self.site_code) < 2000:
                        # A file's version: its validator when the server gives one, else its size (never its contents).
                        self.site_code[parts.path] = headers.get("etag") or headers.get("last-modified") or headers.get("content-length") or ""
                    return
                if not measure.third_party:
                    return
                entry = self.third_party.setdefault(host, {"requests": 0, "bytes": 0})
                entry["requests"] += 1
                try:
                    entry["bytes"] += int(headers.get("content-length") or 0)
                except ValueError:
                    pass
            except Exception:
                pass

        page.on("framenavigated", navigated)
        page.on("response", responded)

    def site_version(self) -> dict[str, Any]:
        """``{"fingerprint", "files"}`` of the site's own code files this test loaded ({} when none matched)."""
        return fingerprint_site_code(self.site_code)

    async def collect_lag(self) -> None:
        """At the end of a step: how late the page's heartbeat ran since it was last asked (a busy computer), into this test's timing."""
        page = self._current
        if page is None or page.is_closed() or self.pending_dialog is not None:
            return
        try:
            late_sum_ms = await asyncio.wait_for(page.main_frame.evaluate("window.__rr && window.__rr.takeLagSum ? window.__rr.takeLagSum() : 0"), 1.0)
            self.timing.lagged(float(late_sum_ms or 0) / 1000)
        except Exception:
            pass

    def calls_snapshot(self) -> tuple[int, frozenset, int]:
        """(servlet calls started so far, the ones in flight right now, blocks seen so far) - taken before an input or a click, so
        that only calls the action starts are waited for and checked, and a long-running background call is never mistaken for one."""
        st = self._calls.get(self._current)
        return (st["started"], frozenset(st["inflight"]), len(st["blocks"])) if st else (0, frozenset(), 0)

    async def pace(self) -> None:
        """Before a page load starts (or a click that may start one): the run-wide throttle spaces them out and honours a cool-down."""
        if self.throttle is not None:
            with self.timing.span("wait", "pacing"):
                await self.throttle.before_load(self.cancel)

    async def await_call_results(self, before: tuple, cap: float) -> None:
        """After a click: the servlet calls it started get up to ``cap`` seconds to *answer* (a slow submit is not waited for
        beyond that - its result is simply what the following steps meet)."""
        page = self._current
        st = self._calls.get(page) if page is not None else None
        if st is None:
            return
        inflight_before = before[1]
        deadline = time.monotonic() + cap
        while any(r not in inflight_before for r in st["inflight"]) and time.monotonic() < deadline:
            await asyncio.sleep(0.03)

    def raise_if_blocked(self, blocks_before: int) -> None:
        """The action's own server call (or the page load it caused) was refused by the WAF: fail the step with the reason instead of
        letting a click that did nothing pass."""
        st = self._calls.get(self._current)
        new = st["blocks"][blocks_before:] if st else []
        if new:
            b = new[0]
            what = "page load" if b["navigation"] else f"{b['method']} {b['path']}"
            self.block_error = (f"Blocked by the site: HTTP {b['status']} to the {what} (a WAF / rate limit, not the application). "
                                "The run pauses page loads and tries this test again; lower runner.workers if it keeps happening.")
            raise ActionError(self.block_error)

    async def settle_after_input(self, before: tuple[int, frozenset] | None = None) -> None:
        with self.timing.span("runner", "input_settle"):
            await self._settle_after_input(before)

    async def _settle_after_input(self, before: tuple[int, frozenset] | None = None) -> None:
        """After typing or a key press: if the site made a server call because of it, wait for that call - and only for those.

        Leaving a field usually asks the server (a zip code, an e-mail, a voucher) and the answer changes the form; the next step
        must not run before it.  ``before`` = ``calls_snapshot()`` taken before the input.  A call still gets
        ``waits.input_call_grace_ms`` to start (a check may be debounced); if none started, nothing is waited for.  A call the
        input started is waited for up to ``waits.input_settle_max_s`` (it is never abandoned as "background"), then the page gets a
        moment to show the answer.  Calls that were already in flight before the input, third-party traffic and page loads never count.
        """
        page = self._current
        st = self._calls.get(page) if page is not None else None
        cap = self.cfg.waits.input_settle_max_s
        if st is None or cap <= 0 or page.is_closed():
            return
        started_before, inflight_before, blocks_before = before if before is not None else (st["started"], frozenset(st["inflight"]), len(st["blocks"]))

        def mine() -> bool:
            return any(r not in inflight_before for r in st["inflight"])

        grace_end = time.monotonic() + self.cfg.waits.input_call_grace_ms / 1000
        while st["started"] == started_before and time.monotonic() < grace_end:
            await asyncio.sleep(0.02)
        if st["started"] == started_before:
            self.raise_if_blocked(blocks_before)
            return                                              # no new servlet call: nothing to wait for
        started, told = time.monotonic(), None
        pat = self.cfg.patience
        try:
            while mine():
                waited = time.monotonic() - started
                if not pat.enabled and waited >= cap:
                    break
                if pat.enabled and (waited >= pat.max_wait_s or time.monotonic() - self._act.get(page, {}).get("progress", started) >= pat.stall_s
                                    and waited >= pat.stall_s):
                    break
                if pat.enabled and told is None and waited >= max(cap, pat.tell_after_s):
                    told = self.notice.begin("slow_page", "Waiting for the site to answer what was just typed (a check it runs on the field). "
                                             "The step waits for the answer instead of moving on; a slow site is not a test failure.")
                await asyncio.sleep(0.03)
        finally:
            if told is not None:
                self.notice.end(told, f"waited {plain_seconds(time.monotonic() - started)} for the site to answer the input")
        if mine():
            self.review.flag("page_busy", f"A server call started by the input had not returned after {plain_seconds(time.monotonic() - started)}; "
                             "carried on anyway", "warning")
            return
        self.raise_if_blocked(blocks_before)                    # answered 403 / 429: the site is blocking us
        await settle(page, 1.0, 200)                            # the answer has arrived: let the page apply it

    @staticmethod
    async def _all_frames_complete(page) -> bool:
        """The page's own document is ``complete``.  (Sub-frames are covered by the quiet check, which counts every frame's
        requests and DOM changes; an advert frame that never finishes loading must not hold every page for the full budget.)"""
        try:
            return await page.main_frame.evaluate("document.readyState") == "complete"
        except Exception:
            return False                                  # mid-navigation: not ready

    async def close(self) -> None:
        """Close this test's browser window.  A window that will not close must not stall the run: after
        ``runner.close_timeout_s`` the whole (per-worker) browser is closed instead, and the run moves on."""
        context, self.context = self.context, None
        browser = getattr(self, "_browser", None)
        self.pages, self._current, self._frame, self.frame_path = [], None, None, []
        if context is None:
            return
        self._closing = True                                    # from here a disconnect is our own doing, not a crash
        if browser is not None and self._on_disconnect is not None:
            try:
                browser.remove_listener("disconnected", self._on_disconnect)
            except Exception:
                pass
            self._on_disconnect = None
        limit = self.cfg.runner.close_timeout_s
        try:
            await asyncio.wait_for(context.close(), limit)
        except asyncio.TimeoutError:
            self.review.flag("browser_close", f"The browser window did not close within {limit:g}s; closing the whole browser instead",
                             "warning")
            try:
                if browser is not None:
                    await asyncio.wait_for(browser.close(), limit)
            except Exception:
                pass                       # the worker relaunches a browser for its next test
        except Exception:
            pass

    async def close_page(self) -> None:
        page = self._current
        if page is not None:
            await page.close()

    # -- pages / windows ---------------------------------------------------------------------------
    @property
    def page(self):
        if self._current is None or self._current.is_closed():
            raise ActionError("No open browser window (an Open step must run first)")
        return self._current

    def switch_to_window(self, value: str) -> None:
        pages = [p for p in self.pages if not p.is_closed()]
        if not pages:
            raise ActionError("No open browser window")
        key = str(value).strip()
        target = None
        if re.fullmatch(r"-?\d+(\.0+)?", key):
            try:
                target = pages[int(float(key))]
            except IndexError:
                raise ActionError(f"No window at index {key} ({len(pages)} open)")
        elif key.upper() == "WINDOW_HANDLES[-1]":
            target = pages[-1]
        else:
            target = next((p for p in pages if key in p.url), None)
        if target is None:
            raise ActionError(f"No window matching {value!r}")
        self._current, self.frame_path, self._frame = target, [], None

    def switch_to_main_window(self) -> None:
        pages = [p for p in self.pages if not p.is_closed()]
        if not pages:
            raise ActionError("No open browser window")
        self._current, self.frame_path, self._frame = pages[0], [], None

    # -- frames --------------------------------------------------------------------------------------
    async def scope(self):
        """The current search scope: the page, or the frame selected with SWITCHTOFRAME."""
        page = self.page
        if not self.frame_path:
            return page
        if self._frame is not None and not self._frame.is_detached():
            return self._frame
        self._frame = await self._rebuild_frame(page)     # frame was reloaded/replaced: re-resolve the path
        return self._frame

    async def _rebuild_frame(self, page):
        frame = page.main_frame
        for step in self.frame_path:
            with Patience(self, self.cfg.timeouts.element_s, what=f"the frame {step.value!r}") as pat:
                frame = await self._child_frame(frame, step, timeout_s=self.cfg.patience.max_wait_s if self.cfg.patience.enabled else self.cfg.timeouts.element_s,
                                                give_up=lambda _elapsed, pat=pat: pat.give_up())
        return frame

    async def _child_frame(self, parent, step: FrameStep, timeout_s: float, give_up=None):
        if step.by == "name":
            v = str(step.value).replace("\\", "\\\\").replace('"', '\\"')
            selector = f'iframe[name="{v}"], iframe[id="{v}"], frame[name="{v}"], frame[id="{v}"]'
            index = 0
        else:
            selector, index = "iframe, frame", int(step.value)
        started = asyncio.get_running_loop().time()
        deadline = started + timeout_s
        while True:
            try:
                loc = parent.locator(selector)
                if await loc.count() > index:
                    handle = await loc.nth(index).element_handle()
                    frame = await handle.content_frame() if handle else None
                    if frame is not None:
                        return frame
            except Exception:
                pass
            now = asyncio.get_running_loop().time()
            if now >= deadline or (give_up is not None and await give_up(now - started)):
                raise ActionError(f"No such frame: {step.value!r}")
            await asyncio.sleep(0.1)

    async def switch_to_frame(self, step: FrameStep, timeout_s: float, give_up=None) -> None:
        parent = await self.scope()
        frame = await self._child_frame(parent, step, timeout_s, give_up)
        self.frame_path.append(step)
        self._frame = frame

    def switch_to_default(self) -> None:
        self.frame_path, self._frame = [], None
