"""Before the first click / typing on a freshly loaded page the runner lets the page finish starting up - once per document."""
from __future__ import annotations

import time

import pytest
from playwright.async_api import async_playwright

from regrunner.capture.review import ReviewCollector
from regrunner.config import Config
from regrunner.engine.session import BrowserSession

pytestmark = pytest.mark.browser


async def opened(pw, site: str, path: str, **waits):
    browser = await pw.chromium.launch()

    async def getter():
        return browser
    cfg = Config()
    cfg.waits.ready_quiet_ms = 300
    for key, value in waits.items():
        setattr(cfg.waits, key, value)
    flags = []
    session = BrowserSession(getter, cfg, ReviewCollector("t", lambda *a, **k: flags.append((a, k))), "t", "UAT")
    await session.open(site + path)
    return browser, session, flags


async def timed(session) -> float:
    started = time.monotonic()
    await session.ensure_ready()
    return time.monotonic() - started


async def test_a_page_that_is_still_building_itself_is_waited_for_once(site):
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "busy.html")
        try:
            assert 0.6 < await timed(session) < 3.5                 # it kept changing for ~1.2 s, then 0.3 s of quiet
            assert await timed(session) < 0.05                      # already ready: the same document is not waited for again
            await session.page.goto(site + "busy.html")             # a new document is waited for again
            assert await timed(session) > 0.6
        finally:
            await session.close()
            await browser.close()


async def test_a_quiet_page_costs_next_to_nothing(site):
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "index.html")
        try:
            await session.page.wait_for_timeout(600)
            assert await timed(session) < 1.2                       # at most the quiet period, never the 4 s cap
        finally:
            await session.close()
            await browser.close()


async def test_a_page_that_never_settles_is_not_waited_for_forever(site):
    async with async_playwright() as pw:
        browser, session, flags = await opened(pw, site, "busy.html", ready_max_s=0.5)
        try:
            assert 0.4 < await timed(session) < 1.5
            assert any("page_busy" in str(call) for call in flags)             # and it says so under Things to review
        finally:
            await session.close()
            await browser.close()


async def test_the_gate_can_be_switched_off(site):
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "busy.html", ready_max_s=0)
        try:
            assert await timed(session) < 0.05
        finally:
            await session.close()
            await browser.close()


async def click_the_radio(pw, site: str, **waits):
    from types import SimpleNamespace

    from regrunner.engine.actions import click_and_verify
    browser, session, _ = await opened(pw, site, "hydrating.html", **waits)
    try:
        res = SimpleNamespace(locator=session.page.locator("#l"))
        ctx = SimpleNamespace(act_timeout_s=6.0, out=SimpleNamespace(notes=[]), session=session)
        await click_and_verify(ctx, res, lambda: res.locator.evaluate("e => e.click()"))
        return await session.page.evaluate("document.querySelector('input').checked")
    finally:
        await session.close()
        await browser.close()


async def test_waiting_for_the_page_is_what_makes_an_early_click_work(site):
    """The page ignores clicks until it has hydrated (0.9 s).  The runner waits for it, so the one click lands and takes."""
    async with async_playwright() as pw:
        assert await click_the_radio(pw, site) is True


async def test_without_the_wait_the_same_click_fails_honestly(site):
    """Same page, gate off: the click is ignored and the step FAILS - it is neither repeated nor reported as a pass."""
    from regrunner.engine.session import ActionError
    async with async_playwright() as pw:
        with pytest.raises(ActionError, match="did not become selected"):
            await click_the_radio(pw, site, ready_max_s=0)


async def real_ctx(session):
    from types import SimpleNamespace
    return SimpleNamespace(act_timeout_s=6.0, out=SimpleNamespace(notes=[]), session=session)


async def test_a_click_that_reloads_the_page_is_followed_by_the_load_not_by_a_click_on_the_dying_page(site):
    """The real sequence: row 15 clicks the consent button, which reloads the page; row 16 clicks a radio on the reloaded form
    (that ignores clicks until it has hydrated).  The runner holds row 16 until the new page is ready, so the one click works."""
    from types import SimpleNamespace

    from regrunner.engine.actions import click_and_verify
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "reload_after_click.html")
        try:
            await session.ensure_ready()
            accept = SimpleNamespace(locator=session.page.locator("#accept"))
            ctx15 = await real_ctx(session)
            await click_and_verify(ctx15, accept, lambda: accept.locator.evaluate("e => e.click()"))     # row 15
            assert any("loaded a page" in n for n in ctx15.out.notes)                                    # the step waited for the reload
            await session.ensure_ready()                                                                # (what run_action does before row 16)
            radio = SimpleNamespace(locator=session.page.locator("#l"))
            await click_and_verify(await real_ctx(session), radio, lambda: radio.locator.evaluate("e => e.click()"))   # row 16
            assert await session.page.evaluate("document.querySelector('input').checked") is True
        finally:
            await session.close()
            await browser.close()


async def test_a_click_that_loads_a_slow_page_ends_on_that_page(site):
    from types import SimpleNamespace

    from regrunner.engine.actions import click_and_verify
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "nav_button.html")
        try:
            await session.ensure_ready()
            go = SimpleNamespace(locator=session.page.locator("#go"))
            started = time.monotonic()
            await click_and_verify(await real_ctx(session), go, lambda: go.locator.evaluate("e => e.click()"))
            assert time.monotonic() - started > 0.7                                                     # the page takes ~0.8 s
            assert session.page.url.endswith("/api/slow") and not session.navigating()
        finally:
            await session.close()
            await browser.close()


async def test_only_controls_that_can_load_a_page_pay_for_the_watch(site):
    from types import SimpleNamespace

    from regrunner.engine.actions import click_and_verify
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "nav_button.html", nav_grace_ms=400)
        try:
            await session.ensure_ready()
            timings = {}
            for name in ("noop", "plain"):
                res = SimpleNamespace(locator=session.page.locator(f"#{name}"))
                started = time.monotonic()
                await click_and_verify(await real_ctx(session), res, lambda: res.locator.evaluate("e => e.click()"))
                timings[name] = time.monotonic() - started
            assert timings["noop"] >= 0.35                          # a button might load a page: watched for 0.4 s
            assert timings["plain"] < 0.3                           # a plain element is not
        finally:
            await session.close()
            await browser.close()
