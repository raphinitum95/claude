"""Recording and Check / Save this through the server and the Build tab (P09): ``/api/build/session/{name}/record|check|save|prompt`` and the
editor's Rec / Check / Save / Wait until buttons and check card.  Picks go through "which one?" (the build window runs in the server's own
loop); recording a person's actions in the window is tests/test_build_recording.py."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from tests.test_build_recording import record_book
from tests.test_web_build import js_until, open_ui
from tests.test_web_build_session import wait_state
from tests.web_fixtures import web  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser


@pytest.fixture
def rec(web, request):
    name = f"rec_{request.node.name}"[:60] + ".xlsx"
    record_book(web.root / "workbooks" / name, web.site)
    return name


async def opened(c, name: str) -> dict:
    r = await c.post(f"/api/build/session/{name}/start", json={"test": "Rec", "headless": True})
    assert r.status_code == 200, r.text
    return await wait_state(c, name, lambda s: s["status"] == "ready" and s.get("replay") and not s["replay"]["running"])


async def test_the_record_check_save_and_prompt_routes(web, rec):
    async with web.aclient() as c:
        r = await c.post(f"/api/build/session/{rec}/record", json={"on": True})
        assert r.status_code == 409 and r.json()["kind"] == "closed"
        await opened(c, rec)
        r = await c.post(f"/api/build/session/{rec}/record", json={"on": True, "after": 99})
        assert r.status_code == 400 and r.json()["kind"] == "step"
        state = (await c.post(f"/api/build/session/{rec}/record", json={"on": True, "after": 2})).json()
        assert state["record"]["on"] and state["record"]["cursor"]["n"] == 1
        assert not (await c.post(f"/api/build/session/{rec}/record", json={"on": False})).json()["record"]["on"]
        await c.post(f"/api/build/session/{rec}/pick", json={"mode": "check", "row": 2})
        await c.post(f"/api/build/session/{rec}/which", json={"text": "Continue", "kind": "button"})
        pick = (await c.post(f"/api/build/session/{rec}/choose", json={"i": 0})).json()["pick"]
        form = pick["card"]["form"]
        assert form["purpose"] == "check" and form["n"] == 2 and {k["id"]: k["enabled"] for k in form["kinds"]}["enabled"] is True
        r = await c.post(f"/api/build/session/{rec}/check", json={"kind": "gt", "expected": "lots"})
        assert r.status_code == 400
        r = await c.post(f"/api/build/session/{rec}/check", json={"kind": "enabled", "expected": "Y"})
        assert r.status_code == 200, r.text
        steps = next(t for t in r.json()["model"]["tests"] if t["id"] == "Rec")["steps"]
        assert [s["method"] for s in steps] == ["OPEN", "CHECK_ENABLED"] and steps[1]["locator"]["value"] == "continue"
        await c.post(f"/api/build/session/{rec}/pick", json={"mode": "save"})
        await c.post(f"/api/build/session/{rec}/which", json={"text": "$1,234.50"})
        pick = (await c.post(f"/api/build/session/{rec}/choose", json={"i": 0})).json()["pick"]
        assert pick["card"]["form"]["token"] == "PRICE"
        r = await c.post(f"/api/build/session/{rec}/save", json={"token": "TOTAL"})
        steps = next(t for t in r.json()["model"]["tests"] if t["id"] == "Rec")["steps"]
        assert [s["method"] for s in steps] == ["OPEN", "CHECK_ENABLED", "OUTPUT"] and steps[2]["saveAs"] == "TOTAL"
        r = await c.post(f"/api/build/session/{rec}/prompt", json={"id": "nope", "choice": "keep"})
        assert r.status_code == 409 and r.json()["kind"] == "prompt"
        await c.post(f"/api/build/session/{rec}/close")


async def test_the_editor_has_rec_check_save_and_wait_and_adds_a_check_from_its_card(web, rec):
    pw, browser, page = await open_ui(web, f"/#/build/{rec}/test/Rec")
    try:
        await js_until(page, "document.querySelectorAll('.scard').length === 1")
        async with web.aclient() as c:
            await opened(c, rec)
        await js_until(page, "!!document.querySelector('[data-act=\"build-rec-toggle\"]')")
        assert [await b.inner_text() for b in await page.locator('[data-act="build-rec-mode"]').all()] == ["Check", "Save", "Wait until"]
        await page.locator('.scard [data-act="build-pick-step"]').first.click()
        await js_until(page, "document.querySelector('aside:not(.b-rail)').textContent.includes('Step 1')")
        await page.locator('[data-act="build-rec-toggle"]').first.click()
        await js_until(page, "document.querySelector('[data-act=\"build-rec-toggle\"]').textContent.includes('Recording')")
        assert "Recording after step 1" in await page.locator("aside:not(.b-rail)").inner_text()
        await page.locator('[data-act="build-rec-toggle"]').first.click()
        await js_until(page, "!document.querySelector('.sess-bar [data-act=\"build-rec-toggle\"]').textContent.includes('Recording')")
        await js_until(page, "document.body.textContent.includes('Recording stopped: no steps were recorded.')")   # the summary strip
        await page.locator('[data-act="build-sess-summary-close"]').click()
        await js_until(page, "!document.querySelector('[data-act=\"build-sess-summary-close\"]')")
        await page.locator('[data-act="build-rec-mode"][data-mode="check"]').click()
        await page.locator('input[data-input="build-sess-which-text"]').fill("$1,234.50")
        await page.locator('[data-act="build-sess-which"]').click()
        await js_until(page, "document.querySelectorAll('[data-act=\"build-sess-choose\"]').length === 1")
        await page.locator('[data-act="build-sess-choose"]').click()
        await js_until(page, "!!document.querySelector('[data-act=\"build-rec-add\"]')")
        assert await page.locator('[data-testid="expected-page"]').inner_text() == "$1,234.50"      # (from the page: read-only, kept as fixed text)
        assert await page.locator('[data-act="build-rec-kind"][data-kind="ticked"]').is_disabled()
        await page.locator('[data-act="build-rec-kind"][data-kind="gt"]').click()
        await page.locator('[data-act="build-rec-source"][data-source="own"]').click()
        await js_until(page, "!!document.querySelector('input[data-input=\"build-rec-expected\"]')")
        assert await page.locator('input[data-input="build-rec-expected"]').input_value() == "1234.5"   # (typing starts from what was read)
        await page.locator('input[data-input="build-rec-expected"]').fill("1000")
        await page.locator('[data-act="build-rec-add"]').click()
        await js_until(page, "document.querySelectorAll('.scard').length === 2")
        assert "1000" in await page.locator(".scard").nth(1).inner_text()
        async with web.aclient() as c:
            await c.post(f"/api/build/session/{rec}/close")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def shot(page, name: str) -> None:
    """``RR_SHOTS=<dir>`` keeps a screenshot of the Build tab to look at."""
    if os.environ.get("RR_SHOTS"):
        Path(os.environ["RR_SHOTS"]).mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(Path(os.environ["RR_SHOTS"]) / f"build_check_card_{name}.png"))


async def open_check_card(web, page, rec) -> None:
    """The Build tab with the window open and the check card showing for the "$1,234.50" text (Check mode, step 1 selected)."""
    await js_until(page, "document.querySelectorAll('.scard').length === 1")
    async with web.aclient() as c:
        await opened(c, rec)
    await js_until(page, "!!document.querySelector('[data-act=\"build-rec-toggle\"]')")
    await page.locator('.scard [data-act="build-pick-step"]').first.click()
    await js_until(page, "document.querySelector('aside:not(.b-rail)').textContent.includes('Step 1')")
    for _ in range(40):                                              # (a click while the window is still answering the last call is dropped: press again)
        if await page.evaluate("document.querySelector('[data-act=\"build-rec-mode\"][data-mode=\"check\"]').classList.contains('btn-pri')"):
            break
        await page.locator('[data-act="build-rec-mode"][data-mode="check"]').click()
        await asyncio.sleep(0.5)
    await page.locator('input[data-input="build-sess-which-text"]').fill("$1,234.50")
    await page.locator('[data-act="build-sess-which"]').click()
    await js_until(page, "document.querySelectorAll('[data-act=\"build-sess-choose\"]').length === 1")
    await page.locator('[data-act="build-sess-choose"]').click()
    await js_until(page, "!!document.querySelector('[data-act=\"build-rec-add\"]')")


async def test_the_check_card_expects_a_variable_chosen_from_a_list_that_can_be_searched(web, rec):
    pw, browser, page = await open_ui(web, f"/#/build/{rec}/test/Rec")
    try:
        await open_check_card(web, page, rec)
        await shot(page, "page")
        sources = page.locator('[data-act="build-rec-source"]')
        assert [await b.inner_text() for b in await sources.all()] == ["From the page", "From a variable", "Type my own"]
        assert await page.locator('[data-act="build-rec-source"][data-source="page"]').get_attribute("aria-pressed") == "true"     # the page value is the default
        await page.locator('[data-act="build-rec-source"][data-source="variable"]').click()
        await js_until(page, "!!document.querySelector('input[data-input=\"build-rec-var-search\"]')")
        assert await page.locator('[data-act="build-rec-add"]').is_disabled()                           # (nothing chosen yet)
        await shot(page, "variable")
        listed = [await o.locator(".tk").inner_text() for o in await page.locator(".vopt").all()]
        assert listed == ["LAST_NAME", "NOTES", "DOMAIN"]                                               # data first, then the environment's
        search = page.locator('input[data-input="build-rec-var-search"]')
        await search.fill("dom")
        await js_until(page, "document.querySelectorAll('.vopt').length === 1")
        await shot(page, "search")
        assert await page.locator(".vopt .tk").inner_text() == "DOMAIN"
        await search.fill("zzz")
        await js_until(page, "document.querySelectorAll('.vopt').length === 0")
        assert "No variable matches" in await page.locator(".vlist").inner_text()
        await search.fill("last na")                                                                    # (words, not the underscore)
        await js_until(page, "document.querySelectorAll('.vopt').length === 1")
        await search.press("Enter")                                                                     # (Enter takes the best match)
        await js_until(page, "!document.querySelector('[data-act=\"build-rec-add\"]').disabled")
        assert "Doe" in await page.locator('aside:not(.b-rail)').inner_text()                          # what it is worth now
        await page.locator('[data-act="build-rec-add"]').click()
        await js_until(page, "document.querySelectorAll('.scard').length === 2")
        assert "LAST_NAME" in await page.locator(".scard").nth(1).inner_text()
        async with web.aclient() as c:
            await c.post(f"/api/build/session/{rec}/close")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()


async def test_a_typed_expected_value_starts_from_the_page_and_can_have_variables_inserted_from_the_same_search(web, rec):
    pw, browser, page = await open_ui(web, f"/#/build/{rec}/test/Rec")
    try:
        await open_check_card(web, page, rec)
        await page.locator('[data-act="build-rec-kind"][data-kind="between"]').click()
        await js_until(page, "document.querySelector('[data-testid=expected-page]').textContent === '1234.5;1234.5'")   # (each kind reads its own value from the page)
        await page.locator('[data-act="build-rec-source"][data-source="own"]').click()
        field = page.locator('input[data-input="build-rec-expected"]')
        await js_until(page, "!!document.querySelector('input[data-input=\"build-rec-expected\"]')")
        await field.fill("")
        await page.locator('[data-act="build-rec-insert-toggle"]').click()
        await shot(page, "typed")
        search = page.locator('input[data-input="build-rec-var-search"]')
        await search.fill("notes")
        await js_until(page, "document.querySelectorAll('.vopt').length === 1")
        await page.locator(".vopt").click()                                                             # -> {NOTES}
        await js_until(page, "document.querySelector('input[data-input=\"build-rec-expected\"]').value === '{NOTES}'")
        await field.fill("{NOTES};2000")
        await page.locator('[data-act="build-rec-add"]').click()                                        # (a variable is not judged as "not a number")
        await js_until(page, "document.querySelectorAll('.scard').length === 2")
        assert "NOTES;2000" in await page.locator(".scard").nth(1).inner_text()                  # (named after the variable; the sheet keeps {NOTES};2000)
        async with web.aclient() as c:
            await c.post(f"/api/build/session/{rec}/close")
        assert not page.errors, page.errors
    finally:
        await browser.close()
        await pw.stop()
