"""The Results screens for a recorded session: the step-by-step card (console, calls with their bodies, fields, the switched-off-field warning),
downloading a run, and importing one that another computer sent."""
from __future__ import annotations

import json

import pytest

from tests.test_run_share import make_run
from tests.test_web_ui import js_until, open_ui
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


def with_warning(web, run_id: str) -> None:
    """make_run's step 2 failed; give step 1 the warning the engine writes, and a call + a console error on step 2."""
    folder = web.run_dir(run_id)
    state = {"step": 1, "row": 3, "name": "Open", "url": "https://s/a", "full": True, "title": "t",
             "fields": {"dob2": {"label": "Date of Birth", "type": "text", "value": "", "empty": True, "disabled": True, "readonly": False,
                                 "ariaDisabled": False, "placeholder": "DD/MM/YYYY", "visible": True}},
             "storage": {"session:quote": "{\"dob\": \"28/01/2006\"}"}, "cookies": [], "messages": ["Sorry, system error"],
             "warnings": [{"key": "dob2", "label": "Date of Birth", "how": "disabled", "placeholder": "DD/MM/YYYY",
                           "text": "\"Date of Birth\" is disabled and has no value (it shows the placeholder \"DD/MM/YYYY\")"}]}
    (folder / "tests" / "DTC_UAT" / "state.jsonl").write_text(json.dumps(state) + "\n", encoding="utf-8")


async def test_the_test_page_shows_the_session_of_each_step_and_flags_the_empty_switched_off_field(web):
    make_run(web, "ws-1")
    with_warning(web, "ws-1")
    async with open_ui(web, path="/#/results/test/ws-1/DTC_UAT") as page:
        await page.wait_for_selector("text=Session, step by step")
        text = await page.locator("body").inner_text()
        assert "1 step saw a switched-off field with nothing in it" in text
        await page.locator('[data-act="results-session-step"][data-seq="1"]').click()                  # the step with the warning
        await js_until(page, "document.body.innerText.includes('Date of Birth')")
        text = await page.locator("body").inner_text()
        assert 'is disabled and has no value (it shows the placeholder "DD/MM/YYYY")' in text
        assert 'session:quote' in text and "Sorry, system error" in text and "pageerror" in text
        await page.locator('[data-act="results-session-step"][data-seq="2"]').click()                  # the failed step: its console and its call
        await js_until(page, "document.body.innerText.includes('what was sent and answered')")
        await page.get_by_text("what was sent and answered").click()
        assert "system error" in await page.locator("details[open]").inner_text()
        assert "POST" in await page.locator("body").inner_text() and "/bin/q" in await page.locator("body").inner_text()
        assert not page.errors, page.errors


async def test_a_run_without_a_recorded_session_says_so_instead_of_showing_an_empty_card(web):
    make_run(web, "ws-2")
    for name in ("state.jsonl", "console.jsonl", "network.jsonl"):
        (web.run_dir("ws-2") / "tests" / "DTC_UAT" / name).unlink()
    async with open_ui(web, path="/#/results/test/ws-2/DTC_UAT") as page:
        await page.wait_for_selector("text=did not record its session")
        assert not page.errors, page.errors


async def test_a_run_is_downloaded_with_a_button_and_an_imported_one_opens_in_the_results_tab(web, tmp_path):
    make_run(web, "ws-3")
    with web.client() as c:
        archive = tmp_path / "ws-3.zip"
        archive.write_bytes(c.get("/api/runs/ws-3/download.zip").content)
        c.delete("/api/runs/ws-3")                                                                       # (as if it came from someone else)
    async with open_ui(web, path="/#/results") as page:
        await page.wait_for_selector("text=Look at someone else's run")
        await page.locator("#results-import-input").set_input_files(str(archive))
        await js_until(page, "location.hash === '#/results/run/ws-3'")
        await page.wait_for_selector("text=Imported run.")
        assert "does not count in this computer's history" in await page.locator("body").inner_text()
        href = await page.locator('a:has-text("Download run")').first.get_attribute("href")
        assert href == "/api/runs/ws-3/download.zip"
        assert await page.locator('[data-key="solo-ws-3"], a[href="#/results/run/ws-3"]').count() >= 1
        assert not page.errors, page.errors


async def test_a_zip_that_is_not_a_run_is_refused_with_a_message(web, tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip at all")
    async with open_ui(web, path="/#/results") as page:
        await page.wait_for_selector("text=Look at someone else's run")
        await page.locator("#results-import-input").set_input_files(str(bad))
        await page.wait_for_selector("text=That file is not a zip")
        assert page.url.endswith("#/results")
