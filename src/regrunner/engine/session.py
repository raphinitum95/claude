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
from .settle import SETTLE_INIT_JS, idle_ms, settle

_TWO_LEVEL_SUFFIXES = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp",
                       "com.br", "com.mx", "co.za", "com.sg", "com.cn", "co.in"}


_SECRET_PARAM = re.compile(r"(pass(word)?|pwd|token|secret|card|cvv|cvc|ssn|auth)", re.I)


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
        browser = await self.browser_getter()
        self._browser = browser
        self.context = await browser.new_context(**options)
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
            response = await page.goto(url, wait_until="load", timeout=self.nav_timeout_s * 1000)
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
        if not pages:
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
        self.review.attach(page)
        page.on("dialog", self._on_dialog)
        page.on("close", lambda p=page: self._on_page_closed(p))

    def _on_page_closed(self, page) -> None:
        if page in self.pages:
            self.pages.remove(page)
        if self._current is page:
            self._current = self.pages[-1] if self.pages else None
            self.frame_path, self._frame = [], None

    def _on_dialog(self, dialog) -> None:
        self.pending_dialog = dialog
        self.last_dialog_text = dialog.message
        asyncio.get_running_loop().create_task(self._auto_resolve_dialog(dialog))

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
        return bool(st and st["pending"] is not None and time.monotonic() - st["pending"] < self.nav_timeout_s)

    async def watch_for_navigation(self, grace_s: float | None = None) -> bool:
        """After a click that may load a page: give the load a moment to *start* (a JS click returns before it does).
        True when one started; the caller then calls ``ensure_ready`` so the click step ends on the new page."""
        page = self._current
        st = self._nav.get(page) if page is not None else None
        if st is None:
            return False
        grace = self.cfg.waits.nav_grace_ms / 1000 if grace_s is None else grace_s
        started, docs = st["started_docs"], st["docs"]
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if st["started_docs"] != started or st["docs"] != docs or st["pending"] is not None:
                return True
            await asyncio.sleep(0.02)
        return False

    async def ensure_ready(self) -> None:
        """Before acting: a page load that has started must finish, and a freshly loaded document must be really ready.

        * a navigation in flight is waited for (up to ``timeouts.navigation_s``);
        * a document not waited for yet is waited for until it (and every frame) is ``complete`` and nothing has loaded or
          changed for ``waits.ready_quiet_ms`` - a form's own start-up script often runs after ``load``, and a click or typing
          that lands before it is ignored or undone (at most ``waits.ready_max_s``);
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
        budget_end = time.monotonic() + limit
        nav_end = time.monotonic() + self.nav_timeout_s
        while True:
            if self.navigating():
                if time.monotonic() > nav_end:
                    self.review.flag("page_busy", f"A page load had not finished after {self.nav_timeout_s:g}s; carried on anyway", "warning")
                    return
                budget_end = max(budget_end, time.monotonic() + limit)     # only time spent not loading counts against the budget
                await asyncio.sleep(0.05)
                continue
            fresh = st["waited_doc"] != st["docs"]
            if await self._all_frames_complete(page) and (not fresh or await idle_ms(page) >= quiet) and not self.navigating():
                st["waited_doc"] = st["docs"] if fresh else st["waited_doc"]
                return
            if time.monotonic() >= budget_end:
                self.review.flag("page_busy", f"The page was still loading or changing after {limit:g}s; carried on anyway", "info")
                st["waited_doc"] = st["docs"]
                return
            await asyncio.sleep(0.05)

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

        def responded(response) -> None:
            request = response.request
            tracked = request in st["t0"]
            if tracked:
                log(request, response.status)
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

    def calls_snapshot(self) -> tuple[int, frozenset, int]:
        """(servlet calls started so far, the ones in flight right now, blocks seen so far) - taken before an input or a click, so
        that only calls the action starts are waited for and checked, and a long-running background call is never mistaken for one."""
        st = self._calls.get(self._current)
        return (st["started"], frozenset(st["inflight"]), len(st["blocks"])) if st else (0, frozenset(), 0)

    async def pace(self) -> None:
        """Before a page load starts (or a click that may start one): the run-wide throttle spaces them out and honours a cool-down."""
        if self.throttle is not None:
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
        deadline = time.monotonic() + cap
        while mine() and time.monotonic() < deadline:
            await asyncio.sleep(0.03)
        if mine():
            self.review.flag("page_busy", f"A server call started by the input had not returned after {cap:g}s; carried on anyway", "warning")
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
            frame = await self._child_frame(frame, step, timeout_s=self.cfg.timeouts.element_s)
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
