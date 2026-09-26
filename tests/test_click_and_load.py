"""A click has to *take*, and a page that never loaded has to be reported as such (not as a missing element 10 s later)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from regrunner.engine.actions import click_and_verify
from regrunner.engine.session import ActionError, http_block_message
from tests.workbook_factory import build_workbook

async def _no_navigation(*a, **k) -> bool:
    return False


async def _ready(*args) -> None:
    return None                                     # the real ensure_ready is covered by tests/test_page_ready.py


RADIO = "<label id='l'><input type='radio' name='t' value='a'> Comprehensive Coverage</label>"
STATE = "() => document.querySelector('input').checked"


async def click_on(html: str, target: str = "#l"):
    """Load ``html`` and click ``target`` the way JS_CLICK does; returns (checked-after, notes, seconds) or the error."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(html)
            res = SimpleNamespace(locator=page.locator(target))
            ctx = SimpleNamespace(act_timeout_s=6.0, out=SimpleNamespace(notes=[]), session=SimpleNamespace(ensure_ready=_ready, watch_for_navigation=_no_navigation, pace=_ready,
                                                                    calls_snapshot=lambda: (0, frozenset(), 0), await_call_results=_ready, raise_if_blocked=lambda *a: None))
            started = time.monotonic()
            await click_and_verify(ctx, res, lambda: res.locator.evaluate("e => e.click()"))
            return await page.evaluate(STATE) if await page.locator("input").count() else None, ctx.out.notes, time.monotonic() - started
        finally:
            await browser.close()


@pytest.mark.browser
async def test_a_normal_radio_click_passes_with_nothing_to_report():
    checked, notes, _ = await click_on(RADIO)
    assert checked is True and notes == []


@pytest.mark.browser
async def test_a_page_that_ignores_the_click_fails_the_step_and_is_not_clicked_again():
    """A defect (or a page that was not ready) must show up as a failure, not be hidden by a second click."""
    html = RADIO + "<script>window.clicks = 0; l.addEventListener('click', e => { window.clicks++; if (window.clicks === 1) e.preventDefault(); });</script>"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(html)
            res = SimpleNamespace(locator=page.locator("#l"))
            ctx = SimpleNamespace(act_timeout_s=6.0, out=SimpleNamespace(notes=[]), session=SimpleNamespace(ensure_ready=_ready, watch_for_navigation=_no_navigation, pace=_ready,
                                                                    calls_snapshot=lambda: (0, frozenset(), 0), await_call_results=_ready, raise_if_blocked=lambda *a: None))
            with pytest.raises(ActionError, match="did not become selected"):
                await click_and_verify(ctx, res, lambda: res.locator.evaluate("e => e.click()"))
            assert await page.evaluate("window.clicks") == 1                       # one click, never repeated
            assert await page.evaluate("document.querySelector('input').checked") is False
        finally:
            await browser.close()


@pytest.mark.browser
async def test_a_page_that_undoes_the_click_a_moment_later_fails_the_step():
    html = RADIO + "<script>l.addEventListener('click', () => setTimeout(() => { document.querySelector('input').checked = false; }, 350));</script>"
    with pytest.raises(ActionError, match="then undid it"):
        await click_on(html)


@pytest.mark.browser
async def test_a_click_that_never_sticks_fails_instead_of_passing():
    html = RADIO + "<script>l.addEventListener('click', e => e.preventDefault());</script>"
    with pytest.raises(ActionError, match="did not become selected"):
        await click_on(html)


@pytest.mark.browser
async def test_a_checkbox_must_end_up_toggled():
    html = "<label id='l'><input type='checkbox' checked> Agree</label>"
    checked, _, _ = await click_on(html)
    assert checked is False                                                 # it was ticked, so a click must untick it


@pytest.mark.browser
async def test_clicking_anything_else_is_not_slowed_down():
    _, notes, seconds = await click_on("<div id='b' onclick='1'>Go</div>", "#b")
    assert notes == [] and seconds < 0.5


def test_the_message_for_a_blocked_page_names_the_usual_causes():
    m = http_block_message("https://owneradvantage.uat.example.com/", 403)
    assert "HTTP 403 (access denied)" in m and "rate-limiting" in m and "recaptchaBypassToken" in m
    assert "environment may be down" in http_block_message("https://x.test/", 503)


@pytest.mark.browser
def test_a_site_that_answers_403_ends_the_test_at_once_with_the_reason(site, tmp_path):
    wb = tmp_path / "wb.xlsx"
    build_workbook(wb, flows=["Blocked"], base_url=site + "forbidden")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("runner: {block_cooldown_s: 0.5, block_retries: 0}\ntimeouts: {element_s: 6, optional_s: 1.5}\ncaptcha_bypass: {values: {UAT: X}}\nreports: {html: false}\n")   # a 403 is a WAF block: no long cool-down here
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-m", "regrunner", "--config", str(cfg), "run", str(wb), "--plain"],
                          cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1 and "HTTP 403" in proc.stdout
    assert time.monotonic() - started < 30                                  # not 48 steps x 6 s of "Object was not found"
    (run_dir,) = list((tmp_path / "runs").iterdir())
    test = json.loads((run_dir / "results.json").read_text())["tests"][0]
    assert test["status"] == "ERROR" and test["error"].startswith("The site did not load.") and "answered HTTP 403" in test["error"]
    assert [s["name"] for s in test["steps"]][-1] == "Open Browser" and test["steps"][-1]["status"] == "FAILED"
    assert test["skipped"] > 30
