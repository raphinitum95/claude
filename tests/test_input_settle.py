"""Leaving a field starts a check on the server; the next step must not run before its answer (rows 156-158 of Owner_CRVD:
Set zip, SendKeys {TAB}, click Submit - Submit does nothing while the 'invalid zip' message is still showing).
Only the site's own servlet calls (/bin/...) started by the input are waited for."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from regrunner.engine.actions import click_and_verify, send_keys, type_into
from tests.test_page_ready import opened

pytestmark = pytest.mark.browser


async def zip_steps(site: str, query: str = "", *, click_submit: bool = True, **waits):
    """Set the zip, press Tab, (click Submit) - back to back, like the runner does.
    Returns (submitted, error still showing, seconds the Tab step took, review flags)."""
    async with async_playwright() as pw:
        browser, session, flags = await opened(pw, site, "zip_validation.html" + query, **waits)
        try:
            base = dict(act_timeout_s=6.0, cfg=session.cfg, out=SimpleNamespace(notes=[]), session=session, review=session.review)
            await session.ensure_ready()
            zip_ = SimpleNamespace(locator=session.page.locator("#zip"))
            await type_into(SimpleNamespace(**base, step=SimpleNamespace(name="Zip")), zip_, "68102", clear_first=True)   # row 156
            started = time.monotonic()
            await send_keys(SimpleNamespace(**base, value_text="{TAB}"))                                                 # row 157
            tab_seconds = time.monotonic() - started
            submitted = None
            if click_submit:
                await session.ensure_ready()                                                                             # what run_action does
                go = SimpleNamespace(locator=session.page.locator("#go"))
                await click_and_verify(SimpleNamespace(**base), go, lambda: go.locator.evaluate("e => e.click()"))       # row 158
                submitted = await session.page.evaluate("!!window.submitted")
            return submitted, await session.page.evaluate("!!document.getElementById('err')"), tab_seconds, flags
        finally:
            await session.close()
            await browser.close()


async def test_submit_after_tab_waits_for_the_zip_check_to_answer(site):
    submitted, error_showing, seconds, _ = await zip_steps(site)
    assert (submitted, error_showing) == (True, False) and 0.6 < seconds < 3        # the ~0.8 s servlet call was waited for


async def test_without_waiting_the_same_steps_lose_the_race(site):
    """The old behaviour, for the record: Submit is clicked while the check is still in flight, so nothing is submitted."""
    submitted, error_showing, _, _ = await zip_steps(site, input_settle_max_s=0)
    assert (submitted, error_showing) == (False, True)


async def test_a_servlet_call_that_takes_longer_than_8_seconds_is_still_waited_for(site):
    """A slow call (a validation, or anything started by the input) is never abandoned as 'background noise'."""
    submitted, error_showing, seconds, _ = await zip_steps(site, "?ms=9500")
    assert (submitted, error_showing) == (True, False) and seconds > 9


async def test_only_servlet_calls_are_waited_for(site):
    """A first-party call that is not under /bin/ (a page resource, an analytics ping...) is not a servlet call."""
    _, _, seconds, _ = await zip_steps(site, "?path=/api/slow?ms=3000", click_submit=False)
    assert seconds < 1.0


async def test_third_party_calls_are_never_waited_for(site):
    other_host = site.replace("127.0.0.1", "localhost") + "bin/hang"                 # same path shape, different site
    _, _, seconds, _ = await zip_steps(site, f"?url={other_host}", click_submit=False)
    assert seconds < 1.0


async def test_no_call_means_no_waiting_beyond_the_short_grace(site):
    _, _, seconds, _ = await zip_steps(site, "?nocall=1", click_submit=False)
    assert seconds < 0.8                                                             # 0.3 s to see whether a call starts


async def test_a_servlet_call_that_never_returns_is_waited_for_up_to_the_cap_only(site):
    _, _, seconds, flags = await zip_steps(site, "?path=/bin/hang", click_submit=False, input_settle_max_s=1.5)
    assert 1.3 < seconds < 3.0
    assert any("page_busy" in str(call) for call in flags)                          # and it is said under Things to review


async def test_the_servlet_pattern_is_configurable(site):
    submitted, error_showing, _, _ = await zip_steps(site, "?path=/api/slow?ms=800", call_url_patterns=["/api/"])
    assert (submitted, error_showing) == (True, False)


async def test_a_page_that_does_not_react_costs_next_to_nothing(site):
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "index.html")
        try:
            await session.ensure_ready()
            await session.page.wait_for_timeout(600)
            started = time.monotonic()
            await session.settle_after_input()
            assert time.monotonic() - started < 0.6
        finally:
            await session.close()
            await browser.close()


async def test_a_background_call_that_was_already_in_flight_is_not_waited_for(site):
    """The bug seen on UAT: one servlet call stayed open for the whole page, so every Set / SendKeys step waited the full 15 s.
    Only calls the input itself starts are waited for; here the zip check (0.8 s) is, the never-ending background call is not."""
    submitted, error_showing, seconds, flags = await zip_steps(site, "?background=/bin/hang")
    assert (submitted, error_showing) == (True, False)
    assert seconds < 3                                                               # the zip check, not the background call
    assert not any("server call started by the input" in str(call) for call in flags)     # (the page-load gate may note the open call)


async def test_the_sites_own_calls_are_logged_with_status_and_time(site):
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "zip_validation.html?ms=300")
        try:
            await session.ensure_ready()
            session.review.step, session.review.step_name = 7, "Enter Zip"
            before = session.calls_snapshot()
            await session.page.evaluate("() => { fetch('/bin/slow?ms=300&password=hunter2&zipCode=68102'); }")
            await session.settle_after_input(before)
            (call,) = [c for c in session.network if "zipCode=68102" in c["url"]]
            assert call["status"] == 200 and call["servlet"] is True and call["step"] == 7 and 250 <= call["ms"] < 2000
            assert call["url"].startswith("/bin/slow?") and "hunter2" not in call["url"] and "password=***" in call["url"]   # no host, no secrets
        finally:
            await session.close()
            await browser.close()


scenario_state: dict = {}


async def zip_error_scenario(site: str, *, click_before_typing: bool):
    """Owner_CRVD rows 156-158: an invalid zip has left its error on the page; Set the valid zip, Tab, Submit."""
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "zip_error_click.html")
        try:
            session.cfg.behaviour.click_before_typing = click_before_typing
            base = dict(act_timeout_s=6.0, cfg=session.cfg, out=SimpleNamespace(notes=[]), session=session, review=session.review)
            await session.ensure_ready()
            zip_ = SimpleNamespace(locator=session.page.locator("#zip"))
            await type_into(SimpleNamespace(**base, step=SimpleNamespace(name="Zip")), zip_, "68102", clear_first=True)
            await send_keys(SimpleNamespace(**base, value_text="{TAB}"))
            await session.ensure_ready()
            go = SimpleNamespace(locator=session.page.locator("#go"))
            await click_and_verify(SimpleNamespace(**base), go, lambda: go.locator.evaluate("e => e.click()"))
            scenario_state["picker_open"] = await session.page.evaluate("!!document.getElementById('picker')")
            return (await session.page.evaluate("window.validations"), await session.page.evaluate("!!document.querySelector('.customErr')"),
                    await session.page.evaluate("!!window.submitted"))
        finally:
            await session.close()
            await browser.close()


async def test_fixing_an_invalid_zip_works_because_set_clicks_into_the_field_first(site):
    """The Owner_CRVD failure: the site clears a field's error only on click and skips validating while one is showing."""
    validations, error_showing, submitted = await zip_error_scenario(site, click_before_typing=True)
    assert (validations, error_showing, submitted) == (1, False, True)
    assert scenario_state["picker_open"] is False          # a person's click also closes an open date picker, so the evidence is clean


async def test_without_the_click_the_site_never_revalidates_and_submit_is_blocked(site):
    """What the runner did before: focus + type, no click - no validation call, the old error stays, Submit does nothing."""
    validations, error_showing, submitted = await zip_error_scenario(site, click_before_typing=False)
    assert (validations, error_showing, submitted) == (0, True, False)
