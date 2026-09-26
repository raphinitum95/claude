"""A WAF that answers 403 / 429 is not the application saying no: fail the step that met it, pace the run, cool down, try again."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from regrunner.engine.actions import click_and_verify, send_keys, type_into
from regrunner.engine.session import ActionError
from regrunner.engine.throttle import Throttle
from tests.site import server as mock_server
from tests.test_page_ready import opened
from tests.workbook_factory import build_workbook

pytestmark = pytest.mark.browser


@pytest.fixture(autouse=True)
def waf_off():
    mock_server.WAF.update(until=0.0, pages=False)
    mock_server.FLAKY.update(block=0, seen=0)
    yield
    mock_server.WAF.update(until=0.0, pages=False)
    mock_server.FLAKY.update(block=0, seen=0)


async def test_a_click_whose_server_call_is_refused_fails_the_step_instead_of_passing(site):
    """Owner_CRVD / ANZ: 'Click Submit' posted to /bin/... and the WAF answered 403; the click 'passed' and nothing happened."""
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "nav_button.html")
        try:
            await session.page.evaluate("document.getElementById('noop').setAttribute('onclick', \"fetch('/bin/slow?ms=50')\")")
            await session.ensure_ready()
            res = SimpleNamespace(locator=session.page.locator("#noop"))
            ctx = SimpleNamespace(act_timeout_s=6.0, out=SimpleNamespace(notes=[]), session=session)
            await click_and_verify(ctx, res, lambda: res.locator.evaluate("e => e.click()"))          # fine while the site answers
            mock_server.WAF["until"] = time.time() + 30
            with pytest.raises(ActionError, match=r"Blocked by the site: HTTP 403 to the GET /bin/slow"):
                await click_and_verify(ctx, res, lambda: res.locator.evaluate("e => e.click()"))
            assert "WAF" in session.block_error
        finally:
            await session.close()
            await browser.close()


async def test_a_zip_check_the_waf_refuses_is_reported_as_a_block_not_as_an_invalid_zip(site):
    """Owner_RVD: the zip check was answered 403, the form then showed 'invalid zip' and blocked its own Submit."""
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "zip_validation.html")
        try:
            base = dict(act_timeout_s=6.0, cfg=session.cfg, out=SimpleNamespace(notes=[]), session=session, review=session.review)
            await session.ensure_ready()
            mock_server.WAF["until"] = time.time() + 30
            zip_ = SimpleNamespace(locator=session.page.locator("#zip"))
            await type_into(SimpleNamespace(**base, step=SimpleNamespace(name="Zip")), zip_, "68102", clear_first=True)
            with pytest.raises(ActionError, match="Blocked by the site: HTTP 403"):
                await send_keys(SimpleNamespace(**base, value_text="{TAB}"))
        finally:
            await session.close()
            await browser.close()


async def test_an_application_error_is_not_mistaken_for_a_block(site):
    """The zip check answers 500 for an invalid zip: that is the application talking, and the step is fine."""
    async with async_playwright() as pw:
        browser, session, _ = await opened(pw, site, "zip_validation.html?path=/bin/slow?ms=100")
        try:
            base = dict(act_timeout_s=6.0, cfg=session.cfg, out=SimpleNamespace(notes=[]), session=session, review=session.review)
            await session.ensure_ready()
            zip_ = SimpleNamespace(locator=session.page.locator("#zip"))
            await type_into(SimpleNamespace(**base, step=SimpleNamespace(name="Zip")), zip_, "12345", clear_first=True)
            await send_keys(SimpleNamespace(**base, value_text="{TAB}"))
            assert session.block_error == ""
        finally:
            await session.close()
            await browser.close()


async def test_page_loads_are_spaced_out_and_a_cool_down_pauses_them():
    throttle = Throttle(min_gap_s=0.3, workers=3)
    await throttle.before_load()
    started = time.monotonic()
    await throttle.before_load()
    assert 0.25 <= time.monotonic() - started < 0.6                       # the minimum gap between two page loads

    reduced = throttle.cool_down(0.6, reduce=True)
    assert reduced and throttle.limit == 2 and throttle.cooling > 0.4
    started = time.monotonic()
    await throttle.before_load()
    assert time.monotonic() - started >= 0.5                              # nothing loads during the cool-down
    assert throttle.cool_down(0.0, reduce=True) and throttle.limit == 1
    assert not throttle.cool_down(0.0, reduce=True) and throttle.limit == 1   # never below one worker


async def test_the_throttle_lets_a_cancel_through_and_holds_reduced_workers_back():
    throttle = Throttle(min_gap_s=0.0, workers=2)
    throttle.cool_down(30, reduce=True)
    cancel = asyncio.Event()
    waiter = asyncio.create_task(throttle.before_load(cancel))
    await asyncio.sleep(0.3)
    assert not waiter.done()
    cancel.set()
    assert await asyncio.wait_for(waiter, 2) < 2                          # cancelled: not held for the 30 s

    held = asyncio.create_task(throttle.slot(2, asyncio.Event()))          # worker 2 was taken out of service
    await asyncio.sleep(0.6)
    assert not held.done()
    await asyncio.wait_for(throttle.slot(1, asyncio.Event()), 1)           # worker 1 still runs
    held.cancel()


def run_cli(site, tmp_path, base: str, runner_cfg: str):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Login flow"], base_url=base)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"runner: {{{runner_cfg}}}\ntimeouts: {{element_s: 6, optional_s: 1.5}}\noutput: {{match_timeout_s: 3}}\n"
                   "captcha_bypass: {values: {UAT: TEST-UAT-TOKEN}}\nreports: {html: false}\n")
    proc = subprocess.run([sys.executable, "-m", "regrunner", "--config", str(cfg), "run", str(wb), "--plain", "--seed", "1"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=180)
    (run_dir,) = list((tmp_path / "runs").iterdir())
    return proc, json.loads((run_dir / "results.json").read_text())["tests"][0], run_dir


def test_a_blocked_test_is_run_again_after_the_cool_down_and_then_passes(site, tmp_path):
    """CW / WM: 'The site did not load ... HTTP 403' straight after a busy stretch.  The WAF let us in again once we backed off."""
    mock_server.FLAKY.update(block=1, seen=0)                              # the first load is refused
    proc, test, run_dir = run_cli(site, tmp_path, site + "flaky/", "block_cooldown_s: 1, block_retries: 2, stagger_s: 0, min_page_load_gap_s: 0")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert test["status"] == "PASSED" and test["attempt"] == 2
    assert [a["blocked"] for a in test["attempts"]] == [True]
    said = " ".join(json.loads(l).get("message", "") for l in (run_dir / "events.jsonl").read_text().splitlines() if '"type": "log"' in l)
    assert "the site blocked this attempt" in said and "Pausing page loads for 1s" in said


def test_a_test_that_stays_blocked_ends_as_an_error_with_the_reason(site, tmp_path):
    mock_server.FLAKY.update(block=99, seen=0)
    proc, test, _ = run_cli(site, tmp_path, site + "flaky/", "block_cooldown_s: 0.5, block_retries: 1, stagger_s: 0, min_page_load_gap_s: 0")
    assert proc.returncode == 1
    assert test["status"] == "ERROR" and "HTTP 403" in test["error"] and test["blocked"]
    assert len(test["attempts"]) == 1                                      # one retry after the cool-down, then it gives up


def test_a_block_when_nothing_has_ever_loaded_gets_one_retry_and_says_it_looks_like_a_standing_rule(site, tmp_path):
    """CloudFront / an allow-list refusing this machine outright: waiting twice would only look like a hang."""
    mock_server.FLAKY.update(block=99, seen=0)
    proc, test, run_dir = run_cli(site, tmp_path, site + "flaky/", "block_cooldown_s: 0.5, block_retries: 2, stagger_s: 0, min_page_load_gap_s: 0")
    assert proc.returncode == 1
    assert test["status"] == "ERROR" and len(test["attempts"]) == 1                       # configured for two retries, one is enough to tell
    assert "standing access rule" in test["error"] and "retrying will not help" in test["error"]
    events = [json.loads(l) for l in (run_dir / "events.jsonl").read_text().splitlines()]
    (paused,) = [e for e in events if e["type"] == "run_paused"]                           # the UI shows a countdown from this
    assert paused["test"] == "Login flow" and paused["seconds"] == 0.5 and paused["attempt"] == 1 and paused["of"] == 1 and "HTTP 403" in paused["reason"]


async def test_a_block_after_pages_have_loaded_keeps_the_whole_retry_budget():
    throttle = Throttle(min_gap_s=0.0, workers=2)
    assert throttle.retry_budget(2) == 1 and throttle.retry_budget(0) == 0 and throttle.retry_budget(1) == 1
    throttle.loaded_ok = True                                                            # a page of this run loaded: it is a rate limit
    assert throttle.retry_budget(2) == 2 and throttle.retry_budget(5) == 5


def test_cloudfront_is_named_when_its_headers_say_so():
    from regrunner.engine.session import behind_cloudfront, http_block_message
    headers = {"Server": "CloudFront", "X-Cache": "Error from cloudfront", "Via": "1.1 abc.cloudfront.net (CloudFront)", "X-Amz-Cf-Id": "x"}
    assert behind_cloudfront(headers) and behind_cloudfront({"x-amz-cf-id": "1"}) and not behind_cloudfront({"server": "nginx"}) and not behind_cloudfront(None)
    said = http_block_message("https://qantas.uat.travelguard.com/", 403, headers)
    assert "HTTP 403 from CloudFront" in said and "allow-list" in said and "recaptchaBypassToken" not in said
    plain = http_block_message("https://qantas.uat.travelguard.com/", 403, {"server": "nginx"})
    assert "CloudFront" not in plain and "recaptchaBypassToken" in plain


async def test_workers_blocked_in_the_same_instant_count_as_one_block():
    throttle = Throttle(min_gap_s=0.0, workers=4)
    results = [throttle.cool_down(30, reduce=True) for _ in range(4)]           # four workers all hit the WAF together
    assert results == [True, False, False, False] and throttle.limit == 3        # one worker fewer, not three
